"""brain_mouse_board_place: compute the pose of a board pack (main PCB + sensor + lens + wheel + bush, optionally in-place switch boards) inside a
top shell by geometric rules, report the residuals, and write the translated pack. Nothing is forced: when the pack does not fit, status is
NOT_READY with blocking_reasons (the pose is written as candidate_pack.step for inspection only).

Argument validation only; the geometry runs in mouse_board_place_worker.py (server python, OCP + vtk + scipy) through scan_cad_common.run_job: outputs
are written once under mouse/cad/<pl_id>/ and never overwritten; the same inputs return the stored report.
Generic process (owner's universal internals rules, docs/reference/op1_teardown/MOUSE_INTERNALS_PRINCIPLES_JA.md): no part name, coordinate or mirror
plane is built in; every name is an argument.
  * Pose = TRANSLATION (the pack frame must already have its PCB level: PCB_NOT_LEVEL otherwise, never rotated to fit).
      ty: sensor_part bbox centre on the mirror plane (fitted from the shell, mirror_y overrides).
      tz: floor_datum_part min z on the floor = the bottom-plate bottom face (rule: the around-lens helper bottom = bottom-plate bottom): floor_z, or
          the min z of floor_part, or the 1st percentile z of floor_region_path (STL in the shell frame). One of them is required.
      tx: x_rule 'bush_flush' (owner rule: the bush's angled end face is flush with the outer skin of the top shell + bottom plate: floor_part solid or
          floor_region_path scan mesh; bush_part required), 'wheel' (wheel_parts centre
          x on the wheel window centre) or 'auto' (bush_flush when bush_part is given, else wheel).
  * Wheel window: wheel_region_path (scan wheel region STL, area centroid) or an opening found by vertical rays on the mirror line.
  * Switches (optional): seed_switch_parts = in-place switch parts carried in the pack, matched rigidly to switch_part (level master, with
    switch_pcb_part); each plunger must lie under exactly one click plate (plate_parts) or click region (click_region_paths); the vertical gap to the
    ceiling is reported. The final pitch / travel is brain_mouse_board_posts' job (seed_switch_parts = the placed copies).
  * Clearance: every pack part vs the shell (hollow: distance to the material; closed solid skin: depth below the skin - wall_mm; a point outside the skin
    at or below the shell underside (height map) lies under the top shell = bottom-plate territory, not checked here; hollow: points below
    the rim + parting_band_mm are not checked). Parts listed in
    report_only_parts are reported, not blocking: a wheel through a window or a bush through a cable hole not cut yet, and the in-place switch boards
    that brain_mouse_board_posts re-places (pitch + normal shift).
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .scan_cad_common import check_file, check_range, run_job, server_python
from .mouse_checks import _name, _steps
from .. import __version__
from ..errors import BrainError

CODE = 'BOARD_PLACE'
BOARD_PLACE_VERSION = 'board_place/1'
REPORT = 'board_place_report.json'
HERE = Path(__file__).resolve().parent
NUMS = {
    'clearance_mm': (0.3, 0.0, 10.0),             # min room between a pack part and the shell material / planned wall
    'wall_mm': (1.2, 0.3, 10.0),                  # closed solid skin: the planned shell wall (as brain_mouse_carve_shell)
    'level_tol_deg': (0.5, 0.01, 10.0),
    'parting_band_mm': (3.0, 0.0, 20.0),          # hollow shell: points below its rim + this belong to the bottom plate (not checked here)
    'sample_mm': (0.6, 0.1, 5.0),
    'deflection_mm': (0.05, 0.005, 1.0),
    'shell_deflection_mm': (0.1, 0.01, 1.0),
    'window_step_mm': (0.25, 0.05, 5.0),
    'wheel_tol_mm': (1.0, 0.0, 20.0),             # lateral wheel-to-window tolerance
    'flush_tol_mm': (0.02, 0.001, 1.0),
    'flush_ray_mm': (20.0, 1.0, 100.0),
    'min_flush_samples': (6, 1, 500),
    'angled_min_deg': (5.0, 0.0, 89.0),           # bush end face = planar face inclined to the front axis by this range
    'angled_max_deg': (75.0, 1.0, 90.0),
    'seed_match_tol_mm': (0.01, 1e-5, 1.0),
}


def _list(v: Any, what: str, lo: int, hi: int) -> list[str]:
    if not isinstance(v, list) or not lo <= len(v) <= hi or len(set(map(str, v))) != len(v):
        raise BrainError(f'{CODE}_SETTINGS', f'{what} must list {lo}-{hi} distinct part names.', {'given': v})
    return [_name(x, f'{what}[]', f'{CODE}_SETTINGS') for x in v]


def board_place(workspace: Path, step_paths: list[str], shell_part: str | None = None, pack_parts: list[str] | None = None,
                sensor_part: str | None = None, floor_datum_part: str | None = None, pcb_part: str | None = None,
                floor_z: float | None = None, floor_part: str | None = None, floor_region_path: str | None = None,
                x_rule: str = 'auto', bush_part: str | None = None, wheel_parts: list[str] | None = None, wheel_region_path: str | None = None,
                seed_switch_parts: list[str] | None = None, switch_part: str | None = None, switch_pcb_part: str | None = None,
                plate_parts: list[str] | None = None, click_region_paths: list[str] | None = None, report_only_parts: list[str] | None = None,
                mirror_y: float | None = None, shell_kind: str = 'auto', **numbers: Any) -> dict[str, Any]:
    workspace = Path(workspace)
    unknown = set(numbers) - set(NUMS)
    if unknown:
        raise BrainError(f'{CODE}_SETTINGS', 'Unknown parameters.', {'unknown': sorted(unknown)})
    inputs: dict[str, Any] = dict(_steps(workspace, step_paths, CODE))
    for k, v in (('shell_part', shell_part), ('sensor_part', sensor_part), ('floor_datum_part', floor_datum_part), ('pcb_part', pcb_part)):
        if v is None:
            raise BrainError(f'{CODE}_SETTINGS', f'{k} is required (part name in the STEP; no model-specific default).', {'argument': k})
    pack = _list(pack_parts, 'pack_parts', 1, 80)
    for k, v in (('sensor_part', sensor_part), ('floor_datum_part', floor_datum_part), ('pcb_part', pcb_part)):
        if _name(v, k, f'{CODE}_SETTINGS') not in pack:
            raise BrainError(f'{CODE}_SETTINGS', f'{k} must be one of pack_parts (it moves with the pack).', {k: v})
    if shell_part in pack:
        raise BrainError(f'{CODE}_SETTINGS', 'shell_part cannot be in pack_parts.', {})
    srcs = [x is not None for x in (floor_z, floor_part, floor_region_path)]
    if sum(srcs) != 1:
        raise BrainError(f'{CODE}_SETTINGS', 'Give exactly one floor source: floor_z, floor_part (bottom plate) or floor_region_path (bottom-plate STL).', {})
    if floor_z is not None:
        check_range('floor_z', floor_z, -1000.0, 1000.0, f'{CODE}_SETTINGS')
    if floor_region_path is not None:
        inputs['floor_region'] = check_file(workspace, floor_region_path, ('.stl',), f'{CODE}_FILE', 'floor_region_path')
    if x_rule not in ('auto', 'bush_flush', 'wheel'):
        raise BrainError(f'{CODE}_SETTINGS', 'x_rule must be auto, bush_flush or wheel.', {'given': x_rule})
    if x_rule == 'bush_flush' and bush_part is None:
        raise BrainError(f'{CODE}_SETTINGS', 'x_rule bush_flush needs bush_part.', {})
    if bush_part is not None and _name(bush_part, 'bush_part', f'{CODE}_SETTINGS') not in pack:
        raise BrainError(f'{CODE}_SETTINGS', 'bush_part must be one of pack_parts.', {})
    wheels = None if wheel_parts is None else _list(wheel_parts, 'wheel_parts', 1, 8)
    if wheels and not set(wheels) <= set(pack):
        raise BrainError(f'{CODE}_SETTINGS', 'wheel_parts must be in pack_parts.', {})
    if (x_rule == 'wheel' or (x_rule == 'auto' and bush_part is None)) and not wheels:
        raise BrainError(f'{CODE}_SETTINGS', 'x_rule wheel needs wheel_parts.', {})
    if wheel_region_path is not None:
        inputs['wheel_region'] = check_file(workspace, wheel_region_path, ('.stl',), f'{CODE}_FILE', 'wheel_region_path')
    seeds = None if seed_switch_parts is None else _list(seed_switch_parts, 'seed_switch_parts', 1, 4)
    plates = None if plate_parts is None else _list(plate_parts, 'plate_parts', 1, 4)
    if seeds:
        if not set(seeds) <= set(pack):
            raise BrainError(f'{CODE}_SETTINGS', 'seed_switch_parts must be in pack_parts (they move with the pack).', {})
        if switch_part is None or switch_pcb_part is None:
            raise BrainError(f'{CODE}_SETTINGS', 'seed_switch_parts needs switch_part and switch_pcb_part (the level master switch board).', {})
        if plates is None and click_region_paths is None:
            raise BrainError(f'{CODE}_SETTINGS', 'seed_switch_parts needs plate_parts or click_region_paths to check the plungers are under the clicks.', {})
    if click_region_paths is not None:
        if not isinstance(click_region_paths, list) or not 1 <= len(click_region_paths) <= 4:
            raise BrainError(f'{CODE}_SETTINGS', 'click_region_paths must list 1-4 STL files.', {'given': click_region_paths})
        for i, p in enumerate(click_region_paths):
            inputs[f'click_region_{i}'] = check_file(workspace, p, ('.stl',), f'{CODE}_FILE', f'click_region_paths[{i}]')
    thr = None if report_only_parts is None else _list(report_only_parts, 'report_only_parts', 1, 40)
    if thr and not set(thr) <= set(pack):
        raise BrainError(f'{CODE}_SETTINGS', 'report_only_parts must be in pack_parts.', {})
    if shell_kind not in ('auto', 'hollow', 'solid_skin'):
        raise BrainError(f'{CODE}_SETTINGS', 'shell_kind must be auto, hollow or solid_skin.', {'given': shell_kind})
    if mirror_y is not None:
        check_range('mirror_y', mirror_y, -1000.0, 1000.0, f'{CODE}_SETTINGS')
    settings: dict[str, Any] = {
        'shell_part': _name(shell_part, 'shell_part', f'{CODE}_SETTINGS'), 'pack_parts': pack, 'sensor_part': sensor_part, 'floor_datum_part': floor_datum_part,
        'pcb_part': pcb_part, 'floor_z': None if floor_z is None else float(floor_z),
        'floor_part': None if floor_part is None else _name(floor_part, 'floor_part', f'{CODE}_SETTINGS'),
        'x_rule': x_rule, 'bush_part': bush_part, 'wheel_parts': wheels, 'seed_switch_parts': seeds,
        'switch_part': None if switch_part is None else _name(switch_part, 'switch_part', f'{CODE}_SETTINGS'),
        'switch_pcb_part': None if switch_pcb_part is None else _name(switch_pcb_part, 'switch_pcb_part', f'{CODE}_SETTINGS'),
        'plate_parts': plates, 'report_only_parts': thr, 'mirror_y': None if mirror_y is None else float(mirror_y), 'shell_kind': shell_kind}
    for k, (d, lo, hi) in NUMS.items():
        v = numbers.get(k, d)
        check_range(k, v, lo, hi, f'{CODE}_SETTINGS')
        settings[k] = int(v) if isinstance(d, int) else float(v)
    if settings['angled_min_deg'] >= settings['angled_max_deg']:
        raise BrainError(f'{CODE}_SETTINGS', 'angled_min_deg must be below angled_max_deg.', {})

    def build_report(res, final, job_id, hashes):
        r = res['report']
        reasons = r.pop('blocking_reasons')
        warnings = []
        w = (r.get('residuals') or {}).get('wheel')
        if w and abs(w['dx_mm']) > settings['wheel_tol_mm']:
            warnings.append(f'Wheel centre is {w["dx_mm"]:+.3f} mm from the window centre along x (bush flush decides x; owner accepted such an offset on OP1).')
        if r.get('wheel_window') and 'centre_xy' not in r['wheel_window']:
            warnings.append('No wheel window found: the wheel position is unchecked.')
        return {'schema': 'mouse_board_place_report/1', 'status': 'NOT_READY' if reasons else 'READY', 'blocking_reasons': reasons, 'board_place_id': job_id,
                'version': BOARD_PLACE_VERSION, 'server_version': __version__, 'inputs': {'step_paths': list(step_paths)}, 'input_hashes': hashes,
                'settings': settings, **r, 'outputs': {k: {'file': v} for k, v in res['files'].items()}, 'warnings': warnings, 'seconds': res.get('seconds'),
                'next': 'READY: brain_mouse_board_posts with the placed pack (seed_switch_parts = the placed switch copies, plate_parts) after the shell is '
                        'carved; check with brain_mouse_interference_report. NOT_READY: fix the reasons (pack, shell or rules); nothing is forced.',
                'limits': ['World convention: x = front, y = lateral (mirror normal), z = up. Translation only.',
                           'Clearance is sampled (sample_mm) against a tessellated shell; the bottom plate is not checked here.',
                           'Protected parts are only moved rigidly as one pack; nothing is modified.']}

    return run_job(workspace=workspace, area='cad', prefix='pl_', version=BOARD_PLACE_VERSION, code=CODE, inputs=inputs, settings=settings,
                   worker=HERE / 'mouse_board_place_worker.py', python=server_python(), report_name=REPORT, build_report=build_report, timeout_s=3600)


__all__ = ['board_place', 'BOARD_PLACE_VERSION', 'REPORT', 'NUMS']
