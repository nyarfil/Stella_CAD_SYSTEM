"""brain_mouse_plate_joint: hollow bottom plate with ledge + tongue from the shell skin and the bearing profile z0(x).

Server side: argument validation + scan_cad_common.run_job (hash -> job id, worker subprocess, outputs once under mouse/cad/<pj_id>/, never
overwritten, cached report on the same inputs).  The geometry runs in mouse_plate_joint_worker.py (OCP, numpy, scipy, vtk = extra `geometry`).
ADOPTED default = official v20a / v39 plate (rim only, plan rim, front pad); the ledge + tongue joint (z0_profile, tongue_height_mm > 0) is EXPERIMENTAL
(owner rejected v20b / v22d; its gates are unchanged and it is not READY on real shells).
Process numbers (wall, clearance, floor, ledge) are arguments with the defaults of the approved process (docs/SCAN_TO_HOLLOW_SHELL_PIPELINE_JA_SPEC.md S9, joint_params.json of the v20b build).
Model-specific numbers have NO default (generic for any mouse): bearing pads (pads_mm, default none), the z0 profile of the experimental joint (required) and the stations (derived from the plate x extent).
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .scan_cad_common import check_file, check_range, run_job, server_python
from .. import __version__
from ..errors import BrainError

PLATE_JOINT_VERSION = 'PJ1.1'
STEP_SUFFIXES = ('.step', '.stp')
HERE = Path(__file__).parent
PLATE_JOINT_REPORT = 'plate_joint_report.json'
# No model-specific defaults.  LH2 verification recipe (explicit arguments, official v20a / v39, v24_parts/AUDIT.md): pads_mm [{x_from 103.6, x_to 113.4, half_width_y 8.6, y_centre 0}],
# stations_x_mm [5, 18, 30, 44, 60, 70, 80, 100]; experimental joint (v20b): z0_levels_mm [{76, 2.0}, {52, 2.5}, {36, 3.1}, {24, 4.2}, {12, 5.5}], z0_rear_mm 6.9.


def _levels(levels: Any, code: str) -> list[dict[str, float]]:
    if levels is None:
        return []
    ok = isinstance(levels, list) and 1 <= len(levels) <= 12 and all(isinstance(t, dict) and set(t) == {'x_from', 'z0'} for t in levels)
    if ok:
        for t in levels:
            check_range('z0_levels_mm.x_from', t['x_from'], -200.0, 400.0, f'{code}_SETTINGS')
            check_range('z0_levels_mm.z0', t['z0'], 0.0, 60.0, f'{code}_SETTINGS')
        xs = [float(t['x_from']) for t in levels]
        ok = len(set(xs)) == len(xs)
    if not ok:
        raise BrainError(f'{code}_SETTINGS', 'z0_levels_mm must be 1-12 distinct {"x_from": mm, "z0": mm} (z0 applies for x >= x_from; z0_rear_mm below the smallest x_from).',
                         {'given': levels})
    return [{'x_from': float(t['x_from']), 'z0': float(t['z0'])} for t in sorted(levels, key=lambda t: t['x_from'])]


def plate_joint(workspace: Path, shell_step_path: str, plate_step_path: str, shell_part: str | None = None, plate_part: str | None = None, wall_mm: float = 1.3,
                clearance_mm: float = 0.15, ledge_mm: float | None = None, ledge_measure: str = 'plan', tongue_width_mm: float = 1.1,
                tongue_height_mm: float = 0.0, floor_mm: float = 1.2, bearing: str = 'plate_top', pads_mm: list[dict[str, float]] | None = None, z0_levels_mm: list[dict[str, float]] | None = None,
                z0_rear_mm: float | None = None, ramp_factor: float = 2.0, stations_x_mm: list[float] | None = None, density_g_cm3: float = 1.04,
                gap_tol_mm: float = 0.05, deflection_mm: float = 0.005) -> dict[str, Any]:
    workspace, code = Path(workspace), 'PLATE_JOINT'
    for n, v, lo, hi in (('wall_mm', wall_mm, 0.2, 10.0), ('clearance_mm', clearance_mm, 0.0, 2.0), ('tongue_width_mm', tongue_width_mm, 0.2, 10.0),
                         ('tongue_height_mm', tongue_height_mm, 0.0, 10.0), ('floor_mm', floor_mm, 0.4, 5.0),
                         ('ramp_factor', ramp_factor, 0.2, 10.0), ('density_g_cm3', density_g_cm3, 0.05, 25.0), ('gap_tol_mm', gap_tol_mm, 0.001, 1.0),
                         ('deflection_mm', deflection_mm, 0.002, 0.1)):
        check_range(n, v, lo, hi, f'{code}_SETTINGS')
    if z0_rear_mm is not None:
        check_range('z0_rear_mm', z0_rear_mm, 0.0, 60.0, f'{code}_SETTINGS')
    if ledge_mm is not None:
        check_range('ledge_mm', ledge_mm, 0.3, 12.0, f'{code}_SETTINGS')
    if ledge_measure not in ('normal', 'plan'):
        raise BrainError(f'{code}_SETTINGS', 'ledge_measure must be "normal" (measured normal to the skin, the approved 1.45) or "plan" (horizontal rim wall, e.g. the v24 1.6).',
                         {'given': ledge_measure})
    if bearing not in ('z0_profile', 'plate_top'):
        raise BrainError(f'{code}_SETTINGS', 'bearing must be "plate_top" (default, the adopted plate: the blank keeps its own top, rim only, no tongue) or "z0_profile" (EXPERIMENTAL ledge + tongue joint, '
                                             'flat bearing face z0(x)).', {'given': bearing})
    if bearing == 'plate_top' and tongue_height_mm != 0:
        raise BrainError(f'{code}_SETTINGS', 'bearing = plate_top has no profile to raise a tongue from: pass tongue_height_mm = 0.', {'given': tongue_height_mm})
    if tongue_height_mm > 0 and ledge_measure != 'normal':
        raise BrainError(f'{code}_SETTINGS', 'The tongue clearance is defined normal to the skin: use ledge_measure = "normal" with a tongue.', {'given': ledge_measure})
    eff_ledge = float(ledge_mm) if ledge_mm is not None else float(wall_mm) + float(clearance_mm)
    if tongue_height_mm > 0 and eff_ledge < wall_mm - 1e-9:
        raise BrainError(f'{code}_SETTINGS', 'The ledge (= wall + clearance unless ledge_mm is given) must not be thinner than the foundation wall: the tongue would cut into it.',
                         {'ledge_mm': eff_ledge, 'wall_mm': wall_mm})
    levels = _levels(z0_levels_mm, code)
    if bearing == 'z0_profile' and (not levels or z0_rear_mm is None):
        raise BrainError(f'{code}_Z0_REQUIRED', 'bearing = z0_profile needs z0_levels_mm and z0_rear_mm: the bearing height profile z0(x) of this mouse has no default.', {'z0_levels_mm': z0_levels_mm, 'z0_rear_mm': z0_rear_mm})
    if pads_mm is None:
        pads = []
    else:
        ok = isinstance(pads_mm, list) and len(pads_mm) <= 8 and all(isinstance(t, dict) and {'x_from', 'x_to', 'half_width_y'} <= set(t) <= {'x_from', 'x_to', 'half_width_y', 'y_centre'} for t in pads_mm)
        if ok:
            for t in pads_mm:
                if t.get('y_centre') is not None:
                    check_range('pads_mm.y_centre', t['y_centre'], -400.0, 400.0, f'{code}_SETTINGS')
                check_range('pads_mm.x_from', t['x_from'], -200.0, 400.0, f'{code}_SETTINGS')
                check_range('pads_mm.x_to', t['x_to'], -200.0, 400.0, f'{code}_SETTINGS')
                check_range('pads_mm.half_width_y', t['half_width_y'], 0.5, 200.0, f'{code}_SETTINGS')
            ok = all(t['x_to'] > t['x_from'] for t in pads_mm)
        if not ok:
            raise BrainError(f'{code}_SETTINGS', 'pads_mm must be a list (up to 8, default [] = none) of {"x_from": mm, "x_to": mm, "half_width_y": mm[, "y_centre": mm]} (model x/y; y_centre defaults to the plate bbox mid plane in y): the plate blank inside that rectangle is kept as a bearing pad.',
                             {'given': pads_mm})
        pads = [{k: float(t[k]) for k in ('x_from', 'x_to', 'half_width_y', 'y_centre') if t.get(k) is not None} for t in pads_mm]
    if tongue_height_mm > 0 and pads:
        raise BrainError(f'{code}_SETTINGS', 'Bearing pads are only built for the rim-only plate: pass pads_mm = [] together with the experimental tongue (tongue_height_mm > 0).', {'pads_mm': pads})
    if stations_x_mm is None:
        stations = None                                   # derived from the plate x extent (worker)
    else:
        if not isinstance(stations_x_mm, list) or not 1 <= len(stations_x_mm) <= 30:
            raise BrainError(f'{code}_SETTINGS', 'stations_x_mm must list 1-30 x positions (mm).', {'given': stations_x_mm})
        for v in stations_x_mm:
            check_range('stations_x_mm', v, -200.0, 400.0, f'{code}_SETTINGS')
        stations = [float(v) for v in stations_x_mm]
    shell = check_file(workspace, shell_step_path, STEP_SUFFIXES, f'{code}_FILE', 'shell_step_path')
    plate = check_file(workspace, plate_step_path, STEP_SUFFIXES, f'{code}_FILE', 'plate_step_path')
    for n, v in (('shell_part', shell_part), ('plate_part', plate_part)):
        if v is not None and (not isinstance(v, str) or not v.strip() or len(v) > 200):
            raise BrainError(f'{code}_SETTINGS', f'{n} must be a part name.', {'given': v})
    settings = {'shell_part': shell_part, 'plate_part': plate_part, 'wall_mm': float(wall_mm), 'clearance_mm': float(clearance_mm),
                'ledge_mm': None if ledge_mm is None else float(ledge_mm), 'ledge_measure': ledge_measure, 'tongue_width_mm': float(tongue_width_mm),
                'tongue_height_mm': float(tongue_height_mm), 'floor_mm': float(floor_mm), 'bearing': bearing, 'pads_mm': pads, 'z0_levels_mm': levels or None, 'z0_rear_mm': None if z0_rear_mm is None else float(z0_rear_mm),
                'ramp_factor': float(ramp_factor), 'stations_x_mm': stations, 'density_g_cm3': float(density_g_cm3), 'gap_tol_mm': float(gap_tol_mm),
                'deflection_mm': float(deflection_mm)}

    def build_report(res, final, job_id, hashes):
        ch = res['checks']
        fail = [k for k, v in ch.items() if v.get('status') == 'FAIL']
        warn = [k for k, v in ch.items() if v.get('status') == 'WARN']
        unv = [k for k, v in ch.items() if v.get('status') == 'UNVERIFIED']
        return {'schema': 'mouse_plate_joint_report/1', 'status': 'NOT_READY' if fail or unv else 'READY', 'blocking_reasons': fail + [f'{k} UNVERIFIED' for k in unv],
                'warnings': warn, 'plate_joint_id': job_id, 'version': PLATE_JOINT_VERSION, 'server_version': __version__,
                'inputs': {'shell_step_path': shell_step_path, 'plate_step_path': plate_step_path}, 'input_hashes': hashes, 'settings': settings,
                'plate_part': res['plate_part'], 'shell_part': res['shell_part'],
                'joint': {'ledge_mm': res['ledge_mm'], 'ledge_measure': res['ledge_measure'], 'clearance_mm': res['clearance_mm'], 'tongue_width_mm': res['tongue_width_mm'],
                          'tongue_height_mm': res['tongue_height_mm'], 'floor_mm': res['floor_mm'], 'bearing': res['bearing'], 'pads_mm': pads, 'experimental_tongue': res['tongue_height_mm'] > 0, 'centre_xy': res['centre_xy']},
                'stations_x_mm': res['stations_x_mm'], 'bbox': res['bbox'], 'plate_blank': res['plate_blank'], 'checks': ch, 'mass': res['mass'], 'stations': res['stations'], 'bookkeeping': res['bookkeeping'],
                'skin_model': res['skin_model'], 'outputs': {'hollow_plate': {'file': res['files']['step']}, 'joint_params': {'file': res['files']['params']}},
                'seconds': res.get('seconds'),
                'limits': ['The plate blank (input solid) is never raised: a bearing profile above its top is reported (ledge_reaches_profile), not built. '
                           'The shell is only read: a plate that touches it is reported (common_with_shell), never trimmed.',
                           'Offsets come from a star-shaped radial skin model about the plan centre of the plate (sections of plate and shell, smoothing rms 0.003 mm); '
                           'the check offset_model_accuracy measures the loft against the blank skin.',
                           'The tongue-to-shell gap is the nearest distance from plate surface samples on the tongue to the shell mesh, so it is exact to about the mesh '
                           'deflection (0.01 mm) and reads the foundation inner face only when the shell has the stated wall.',
                           'Volumes in bookkeeping are closed-mesh volumes; B-rep volumes of spline solids differ by up to ~0.5 %.']}

    return run_job(workspace=workspace, area='cad', prefix='pj_', version=PLATE_JOINT_VERSION, code=code, inputs={'shell': shell, 'plate': plate}, settings=settings,
                   worker=HERE / 'mouse_plate_joint_worker.py', python=server_python(), report_name=PLATE_JOINT_REPORT, build_report=build_report, timeout_s=3600)


__all__ = ['plate_joint', 'PLATE_JOINT_VERSION', 'PLATE_JOINT_REPORT']
