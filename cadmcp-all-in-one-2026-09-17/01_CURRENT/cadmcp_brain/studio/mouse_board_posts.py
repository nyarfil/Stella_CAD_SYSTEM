"""brain_mouse_board_posts: place the main-click switch boards under a hollow top shell and build the board posts on the shell, plus the
actuator posts on the click plates and their floor holes (the owner-approved LH2 v34 -> v39 process, 2026-10-15).

Argument validation only; the geometry runs in mouse_board_posts_worker.py (server python, OCP = extra `geometry`) through
scan_cad_common.run_job: outputs are written once under mouse/cad/<bp_id>/ and never overwritten; the same inputs return the stored report.
Generic process (any left-right-symmetric mouse): no part name, coordinate or mirror plane is built in.
  * Required arguments: shell_part, pcb_part, switch_part. board_parts defaults to [pcb_part, switch_part]; list extra parts (connector ...) to copy
    them with the board. Output names: <board_prefix>_<side>_<i>, <shell_part>_posts (or shell_out_name).
  * sides (per side: name, pivot = where the plunger top sits before the normal shift, and for stage "all" plate_part + hinge = two points on the
    click-plate hinge axis) is an explicit override. Omitted, the sides are DERIVED (definition of the LH2 v34-v39 process):
      - seed_switch_parts (required then): one in-place rigid copy of switch_part per side (e.g. the switches of an in-place board assembly or of
        brain_mouse_board_place). Pivot = the seed's plunger top (rigid match master -> seed) + seed_shift_mm [front (+x), inward (toward the mirror
        plane)] (default [0, 0]; an owner design input, LH2 v34: [-1, 1]); z: pivot_z_rule 'plunger_gap' (v37: vertical move until the minimum
        plunger-top -> floor-underside distance along the board normal is plunger_gap_mm 0.80, lowest side for all), 'seed' (keep the seed z) or
        'auto' (level seed -> plunger_gap, pitched seed -> seed).
      - plate_parts (required for stage "all"): the click plates; each seed is paired with the plate above it. Hinge = the plate's rear-edge
        underside corners (rear corner vertices within hinge_band_frac x plate length of the rearmost vertex, clustered at the inner and outer end,
        hinge_cluster_frac x plate width; inner end projected on the mirror plane), as the v39 "two points from the plate's rear vertices".
      - symmetrise (default true): two sides on both sides of the mirror plane get the mean of one side and the mirror image of the other (v35).
      - side_names: optional (default the plate names, else the seed names).
  * Measured from the geometry: board top and thickness, the board mounting holes (concave vertical cylinders of the PCB; the largest diameter group,
    or board_hole_dia to pick one, or explicit board_holes), plunger top and switch-body footprint, the floor (vertical and normal-direction rays),
    and the mirror plane (fitted from the shell, mirror_y overrides it) which is used to check that the sides are mirror images.
  * The post diameter FOLLOWS THE MEASURED HOLE: post_dia = measured hole diameter - post_hole_clearance_mm (default 0.25 mm diametral, a slip fit; the
    owner's v39 has hole 4.65 / post 4.4), unless post_dia is given.
Named process defaults (rationale; they are sizes of the owner-approved LH2 v39 process, V:/mouse/LH2-mouse/work/internals/posts/scripts/build_v39s.py,
build_v39a.py, official/OFFICIAL_v39_NOTES.md, and are arguments): body_gap_mm 0.38 = print-tolerance gap between switch body and floor underside;
pilot_dia 1.4 / pilot_depth 4.5 = M1.6 self-tapping pilot (depth max(2 d, 4) + 0.5); rib_width 0.8 (two 0.4 mm lines), rib_beyond 0.95 = stop
ribs that centre a loose board; act_w x act_h 3.4 x 5.0 = actuator post on the plunger (switch plunger footprint + margin); tip_gap 0.10 =
no pre-load on the plunger; hole_clear 0.32 per side + travel 0.5 = floor hole that never touches the moving post; density 1.04 = ABS.
"""
from __future__ import annotations
import math
from pathlib import Path
from typing import Any
from .scan_cad_common import check_range, run_job, server_python
from .mouse_checks import _name, _steps, _vec3
from .. import __version__
from ..errors import BrainError

BOARD_POSTS_VERSION = 'BP1.0'
REPORT = 'board_posts_report.json'
HERE = Path(__file__).parent
CODE = 'BOARD_POSTS'
STAGES = ('place', 'posts', 'all')

# name: (default, lo, hi) -- v39 values (build_v39s.py / build_v39a.py)
NUMS = {
    'post_hole_clearance_mm': (0.25, 0.0, 2.0),    # diametral clearance board hole - post (slip fit; post_dia = measured hole - this)
    'body_gap_mm': (0.38, 0.0, 5.0),               # switch body top -> floor underside along the board normal (v39 GAP)
    'floor_ray_below_pivot_mm': (5.5, 0.5, 50.0),  # pitch fit: vertical rays start this far below the pivot (v39: z 10)
    'plunger_exclusion_mm': (0.3, 0.0, 5.0),       # body-gap grid skips the plunger footprint + this margin
    'body_grid_inset_mm': (0.12, 0.0, 2.0),        # body-gap grid inset from the body-top edges
    'post_embed_mm': (0.6, 0.0, 5.0),              # columns run to the max floor underside + embed (+ over-length, then trimmed)
    'top_margin_mm': (0.3, 0.0, 2.0),              # trim plane below the floor-top plane (along its normal and again vertically, + fit residual)
    'rib_width': (0.8, 0.1, 5.0),
    'rib_beyond_mm': (0.95, 0.05, 10.0),           # rib reach past the pin surface
    'rib_overlap_mm': (0.3, 0.0, 2.0),             # rib starts this far inside the pin
    'pilot_dia': (1.4, 0.3, 10.0),                 # M1.6 self-tapping pilot
    'pilot_depth_mm': (4.5, 0.5, 30.0),            # max(2 d, 4) + 0.5
    'chamfer_mm': (0.3, 0.0, 2.0),
    'act_w': (3.4, 0.3, 20.0),                     # actuator post along the board x
    'act_h': (5.0, 0.3, 20.0),                     # actuator post along the board y
    'act_corner_r': (0.2, 0.0, 2.0),
    'act_root_fillet': (0.3, 0.0, 2.0),
    'act_into_plate_mm': (1.0, 0.1, 10.0),         # actuator column runs to the max plate underside + this, then trimmed
    'act_top_margin_mm': (0.3, 0.0, 2.0),          # actuator trim plane below the plate-top plane
    'tip_gap_mm': (0.10, 0.0, 5.0),                # actuator tip -> plunger top
    'hole_clear_mm': (0.32, 0.0, 5.0),             # floor hole clearance per side
    'travel_mm': (0.5, 0.0, 5.0),                  # click travel at the plunger used to grow the floor hole
    'hole_probe_margin_mm': (1.0, 0.0, 10.0),      # floor depth probes around the hole
    'hole_below_mm': (0.6, 0.0, 10.0),
    'hole_above_mm': (0.4, 0.0, 10.0),
    'density_g_cm3': (1.04, 0.05, 25.0),           # ABS
    'mesh_deflection_mm': (0.01, 0.001, 0.5),      # closed-mesh volume bookkeeping of big solids
    'plunger_gap_mm': (0.80, -5.0, 10.0),          # derived pivots, z rule plunger_gap: v37 plunger top -> floor underside along the normal
    'hinge_band_frac': (0.02, 0.001, 0.2),         # derived hinge: rear band of vertices, fraction of the plate length
    'hinge_cluster_frac': (0.025, 0.001, 0.2),     # derived hinge: end clusters, fraction of the plate width
    'seed_match_tol_mm': (0.01, 1e-5, 1.0),        # seed = rigid copy of switch_part: max vertex residual
}
INTS = {'pitch_grid': ((9, 3), 2, 50), 'body_grid': ((15, 7), 2, 80)}


def _num(v: Any) -> bool:
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)


def _sides(sides: Any, need_plate: bool) -> list[dict[str, Any]]:
    if sides is None:
        raise BrainError(f'{CODE}_SETTINGS', 'sides is required: per side {"name", "pivot": [x,y,z], "plate_part"?, "hinge"?: [[x,y,z],[x,y,z]]} '
                         '(no model-specific default exists).', {})
    if not isinstance(sides, list) or not 1 <= len(sides) <= 4:
        raise BrainError(f'{CODE}_SETTINGS', 'sides must list 1-4 {"name", "pivot": [x,y,z], "plate_part"?, "hinge"?: [[x,y,z],[x,y,z]]}.', {'given': sides})
    out, names = [], set()
    for i, s in enumerate(sides):
        if not isinstance(s, dict) or set(s) - {'name', 'pivot', 'plate_part', 'hinge'}:
            raise BrainError(f'{CODE}_SETTINGS', 'Each side is {"name", "pivot", "plate_part"?, "hinge"?}.', {'index': i})
        nm = _name(s.get('name'), f'sides[{i}].name', f'{CODE}_SETTINGS')
        if nm in names or not nm.replace('_', '').isalnum():
            raise BrainError(f'{CODE}_SETTINGS', 'Side names must be unique and alphanumeric.', {'given': nm})
        names.add(nm)
        q = {'name': nm, 'pivot': _vec3(s.get('pivot'), f'sides[{i}].pivot', f'{CODE}_SETTINGS')}
        if need_plate:
            q['plate_part'] = _name(s.get('plate_part'), f'sides[{i}].plate_part', f'{CODE}_SETTINGS')
            h = s.get('hinge')
            if not isinstance(h, list) or len(h) != 2:
                raise BrainError(f'{CODE}_SETTINGS', 'stage "all" needs sides[].hinge = two points on the click-plate hinge axis.', {'index': i})
            q['hinge'] = [_vec3(p, f'sides[{i}].hinge', f'{CODE}_SETTINGS') for p in h]
            if math.dist(*q['hinge']) < 1.0:
                raise BrainError(f'{CODE}_SETTINGS', 'The two hinge points must be at least 1 mm apart.', {'index': i})
        out.append(q)
    return out


def _names(v: Any, what: str, lo: int = 1, hi: int = 4) -> list[str]:
    if not isinstance(v, list) or not lo <= len(v) <= hi or len(set(map(str, v))) != len(v):
        raise BrainError(f'{CODE}_SETTINGS', f'{what} must list {lo}-{hi} distinct part names.', {'given': v})
    return [_name(x, f'{what}[]', f'{CODE}_SETTINGS') for x in v]


def _derive(sides, stage, plate_parts, seed_switch_parts, seed_shift_mm, side_names, pivot_z_rule, symmetrise):
    if sides is not None:
        if any(v is not None for v in (plate_parts, seed_switch_parts, seed_shift_mm, side_names)):
            raise BrainError(f'{CODE}_SETTINGS', 'Give either sides (explicit override) or the derivation inputs (seed_switch_parts, plate_parts ...), not both.', {})
        return None
    if seed_switch_parts is None:
        raise BrainError(f'{CODE}_SETTINGS', 'sides is omitted, so the pivots are derived: give seed_switch_parts = one in-place copy of switch_part per side '
                         '(e.g. from brain_mouse_board_place or an in-place board assembly), or give sides explicitly. No model-specific default exists.', {})
    seeds = _names(seed_switch_parts, 'seed_switch_parts')
    plates = None if plate_parts is None else _names(plate_parts, 'plate_parts')
    if stage == 'all' and plates is None:
        raise BrainError(f'{CODE}_SETTINGS', 'stage "all" with derived sides needs plate_parts (the click plates; the hinge comes from their rear edge).', {})
    if plates is not None and len(plates) != len(seeds):
        raise BrainError(f'{CODE}_SETTINGS', 'plate_parts and seed_switch_parts must have the same length (one plate per seed).', {})
    sh = [0.0, 0.0] if seed_shift_mm is None else seed_shift_mm
    if not isinstance(sh, list) or len(sh) != 2 or not all(_num(x) and abs(x) <= 50 for x in sh):
        raise BrainError(f'{CODE}_SETTINGS', 'seed_shift_mm must be [front, inward] in mm (|value| <= 50).', {'given': seed_shift_mm})
    names = None
    if side_names is not None:
        names = _names(side_names, 'side_names')
        if len(names) != len(seeds) or not all(n.replace('_', '').isalnum() for n in names):
            raise BrainError(f'{CODE}_SETTINGS', 'side_names must give one alphanumeric name per seed.', {'given': side_names})
    if pivot_z_rule not in ('auto', 'plunger_gap', 'seed'):
        raise BrainError(f'{CODE}_SETTINGS', 'pivot_z_rule must be auto, plunger_gap or seed.', {'given': pivot_z_rule})
    if not isinstance(symmetrise, bool):
        raise BrainError(f'{CODE}_SETTINGS', 'symmetrise must be true or false.', {'given': symmetrise})
    return {'seed_switch_parts': seeds, 'plate_parts': plates, 'seed_shift_mm': [float(x) for x in sh], 'side_names': names,
            'pivot_z_rule': pivot_z_rule, 'symmetrise': symmetrise}


def board_posts(workspace: Path, step_paths: list[str], stage: str = 'all', shell_part: str | None = None,
                board_parts: list[str] | None = None, pcb_part: str | None = None, switch_part: str | None = None,
                sides: list[dict[str, Any]] | None = None, board_holes: list[list[float]] | None = None, pitch_deg: float | None = None,
                mirror_y: float | None = None, rib_angles_deg: list[float] | None = None, board_hole_dia: float | None = None,
                post_dia: float | None = None, board_prefix: str = 'board', shell_out_name: str | None = None,
                plate_parts: list[str] | None = None, seed_switch_parts: list[str] | None = None, seed_shift_mm: list[float] | None = None,
                side_names: list[str] | None = None, pivot_z_rule: str = 'auto', symmetrise: bool = True, **numbers: Any) -> dict[str, Any]:
    workspace = Path(workspace)
    if stage not in STAGES:
        raise BrainError(f'{CODE}_SETTINGS', f'stage must be one of {STAGES}.', {'given': stage})
    unknown = set(numbers) - set(NUMS) - set(INTS)
    if unknown:
        raise BrainError(f'{CODE}_SETTINGS', 'Unknown parameters.', {'unknown': sorted(unknown)})
    inputs = _steps(workspace, step_paths, CODE)
    for k, v in (('shell_part', shell_part), ('pcb_part', pcb_part), ('switch_part', switch_part)):
        if v is None:
            raise BrainError(f'{CODE}_SETTINGS', f'{k} is required (the part name in the STEP assembly; no model-specific default).', {'argument': k})
    board_parts = board_parts or [pcb_part, switch_part]
    if not isinstance(board_parts, list) or not 1 <= len(board_parts) <= 20:
        raise BrainError(f'{CODE}_SETTINGS', 'board_parts must list 1-20 part names (board, switch, connector ...).', {'given': board_parts})
    board_parts = [_name(b, 'board_parts[]', f'{CODE}_SETTINGS') for b in board_parts]
    pcb_part = _name(pcb_part, 'pcb_part', f'{CODE}_SETTINGS')
    switch_part = _name(switch_part, 'switch_part', f'{CODE}_SETTINGS')
    if pcb_part not in board_parts or switch_part not in board_parts:
        raise BrainError(f'{CODE}_SETTINGS', 'board_parts must contain pcb_part and switch_part.', {'board_parts': board_parts})
    _name(board_prefix, 'board_prefix', f'{CODE}_SETTINGS')
    if shell_out_name is not None:
        _name(shell_out_name, 'shell_out_name', f'{CODE}_SETTINGS')
    derive = _derive(sides, stage, plate_parts, seed_switch_parts, seed_shift_mm, side_names, pivot_z_rule, symmetrise)
    settings: dict[str, Any] = {'stage': stage, 'shell_part': _name(shell_part, 'shell_part', f'{CODE}_SETTINGS'), 'board_parts': board_parts,
                                'pcb_part': pcb_part, 'switch_part': switch_part, 'sides': None if derive else _sides(sides, stage == 'all'), 'derive': derive,
                                'board_prefix': board_prefix, 'shell_out_name': shell_out_name or f'{shell_part}_posts', 'posts_out_name': 'posts_tool',
                                'plate_suffix': '_posts', 'max_iter': 12}
    for k, v, lo, hi in (('board_hole_dia', board_hole_dia, 0.5, 20.0), ('post_dia', post_dia, 0.5, 20.0)):
        if v is not None:
            check_range(k, v, lo, hi, f'{CODE}_SETTINGS')
        settings[k] = None if v is None else float(v)
    if board_holes is not None:
        if not isinstance(board_holes, list) or not 1 <= len(board_holes) <= 8 or \
                not all(isinstance(h, list) and len(h) == 2 and all(_num(x) for x in h) for h in board_holes):
            raise BrainError(f'{CODE}_SETTINGS', 'board_holes must list 1-8 [x, y] hole centres in the board part frame (mm).', {'given': board_holes})
        board_holes = [[float(x) for x in h] for h in board_holes]
    settings['board_holes'] = board_holes
    if pitch_deg is not None:
        check_range('pitch_deg', pitch_deg, -60.0, 60.0, f'{CODE}_SETTINGS')
    settings['pitch_deg'] = None if pitch_deg is None else float(pitch_deg)
    if mirror_y is not None and not _num(mirror_y):
        raise BrainError(f'{CODE}_SETTINGS', 'mirror_y must be a finite number (the mirror plane y = mirror_y), or omitted to fit it from the shell.', {'given': mirror_y})
    settings['mirror_y'] = None if mirror_y is None else float(mirror_y)
    ra = [60.0, 120.0, 240.0, 300.0] if rib_angles_deg is None else rib_angles_deg     # v37: 4 stop ribs clear of the switch and connector
    if not isinstance(ra, list) or not 0 <= len(ra) <= 12 or not all(_num(a) for a in ra):
        raise BrainError(f'{CODE}_SETTINGS', 'rib_angles_deg must list 0-12 angles (deg, about the post axis from the board +x).', {'given': ra})
    settings['rib_angles_deg'] = [float(a) for a in ra]
    for k, (d, lo, hi) in NUMS.items():
        v = numbers.get(k, d)
        check_range(k, v, lo, hi, f'{CODE}_SETTINGS')
        settings[k] = float(v)
    for k, (d, lo, hi) in INTS.items():
        v = numbers.get(k, d)
        if not isinstance(v, (list, tuple)) or len(v) != 2 or not all(isinstance(x, int) and not isinstance(x, bool) and lo <= x <= hi for x in v):
            raise BrainError(f'{CODE}_SETTINGS', f'{k} must be [nx, ny] integers in [{lo}, {hi}].', {'given': v})
        settings[k] = [int(x) for x in v]
    if settings['post_dia'] is not None and settings['pilot_dia'] >= settings['post_dia'] - 0.4:
        raise BrainError(f'{CODE}_SETTINGS', 'pilot_dia must leave at least 0.2 mm wall in the post.', {'pilot_dia': settings['pilot_dia']})

    def build_report(res, final, job_id, hashes):
        r = res['report']
        warnings = []
        m = r.get('mirror') or {}
        if (m.get('plunger_y_mirror_dev_mm') or 0) > (0.01 if m.get('plane_source') == 'argument' else 0.05):
            warnings.append(f'Side pivots are not mirror images about y = {m.get("plane_y_mm"):.3f} ({m["plunger_y_mirror_dev_mm"]:.3f} mm).')
        for n, a in (r.get('actuators') or {}).items():
            if not a.get('root_fillet_applied') and settings['act_root_fillet'] > 0:
                warnings.append(f'{n}: actuator root fillet not applied ({a.get("root_fillet_edges")} edges selected).')
        return {'schema': 'mouse_board_posts_report/1', 'status': 'READY', 'board_posts_id': job_id, 'version': BOARD_POSTS_VERSION,
                'server_version': __version__, 'inputs': {'step_paths': list(step_paths)}, 'input_hashes': hashes, 'settings': settings, **r,
                'outputs': {k: {'file': v} for k, v in res['files'].items()}, 'warnings': warnings, 'seconds': res.get('seconds'),
                'next': 'Check the result with brain_mouse_interference_report (step_paths = the input assembly + board_posts_parts.step) and '
                        'brain_mouse_section_render through the post axes.',
                'limits': ['World convention: x = front/back, y = lateral (mirror normal), z = up; the pitch is about +Y. A model in another frame must be '
                           'rotated into it first.',
                           'Boards are copied rigidly (rotation + translation, no mirror); a mirror-symmetric result needs a board symmetric about '
                           'its plunger line and mirrored pivots.',
                           'Pitch only (about +Y), roll 0. Distances are along ray samples (grids in the report), not a continuous minimum.',
                           'Clearance to other parts is not checked here: run brain_mouse_interference_report.',
                           'Protected parts are only read; nothing but the shell and the click plates is modified.']}

    return run_job(workspace=workspace, area='cad', prefix='bp_', version=BOARD_POSTS_VERSION, code=CODE, inputs=inputs, settings=settings,
                   worker=HERE / 'mouse_board_posts_worker.py', python=server_python(), report_name=REPORT, build_report=build_report, timeout_s=3600)


__all__ = ['board_posts', 'BOARD_POSTS_VERSION', 'REPORT', 'NUMS']
