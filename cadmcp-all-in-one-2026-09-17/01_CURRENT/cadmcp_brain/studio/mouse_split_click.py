"""brain_mouse_split_click_region: groove-aware click footprint + plate carve of a mouse top shell (port of the approved click_split.py / LH2 v17 process).

Generic for any left-right symmetric mouse: no LH2 coordinates in defaults (see the worker header for the LH2 verification recipe).
Inputs are only READ. The geometry runs in a subprocess of the server python (OCP): mouse_split_click_worker.py (it calls the groove fill of
mouse_groove_fill_worker.py first when no filled skin is given). Output once under mouse/cad/<id>/ (never overwritten; the same inputs return the stored
report): shell_open.step, plate_L.step, plate_R.step, click_split_parts.step (named parts), filled_skin.step (when the groove was filled here) + report.
"""
from __future__ import annotations
import json
import math
from pathlib import Path
from typing import Any
from .scan_cad_common import check_file, check_range, run_job, server_python
from .. import __version__
from ..errors import BrainError

SPLIT_VERSION = 'SC1.4'
STEP_SUFFIXES = ('.step', '.stp')
HERE = Path(__file__).parent
SPLIT_REPORT = 'split_click_report.json'
WINDOW_KEYS = ('w', 'h', 'r', 'cx', 'cy')
# No default window: it comes from the wheel part (wheel_step_path), from an explicit window argument, or cut_window = false.
# LH2 verification recipe (explicit arguments, not defaults): window {w 19.12, h 8.32, r 3.33, cx 97.325, cy -0.01} (approved v17, spec S4), uv_margin 3.0,
# min_patch_area_mm2 300, min_groove_length_mm 20.


def _num(v: Any) -> bool:
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)


def _part(v: Any, what: str, code: str) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str) or not v.strip() or len(v) > 200:
        raise BrainError(code, f'{what} must be a non-empty part name.', {'given': v})
    return v


def split_click_region(workspace: Path, shell_step_path: str, shell_part: str | None = None, skin_step_path: str | None = None, skin_part: str | None = None,
                       patch_faces: list[int] | None = None, plate_thickness_mm: float = 1.1, gap_mm: float = 1.0, outer_groove_mm: float = 0.5,
                       centre_slot_mm: float = 1.0, centre_mm: float | None = None, outline_margin_mm: float = 0.1, cut_window: bool = True,
                       window: dict[str, float] | None = None, slab_top_mm: float = 5.0, fit_n: int = 161, fit_tol_mm: float = 2e-5,
                       mesh_deflection_mm: float = 0.003, book_tol_mm3: float = 30.0, sym_tol: float = 0.02, interference_tol_mm3: float = 0.01,
                       ray_n: int = 400, ray_tol_thickness_mm: float = 0.002, ray_tol_gap_mm: float = 0.01, ray_pass: float = 0.97,
                       min_patch_area_mm2: float | None = None, sew_tol_mm: float = 0.02, wheel_step_path: str | None = None, wheel_part: str | None = None,
                       wheel_margin_mm: float = 0.0, window_corner_r_mm: float = 0.0, lateral_axis: str = 'auto', centre_source: str = 'patches',
                       uv_margin: float | None = None, min_groove_length_mm: float | None = None) -> dict[str, Any]:
    workspace, code = Path(workspace), 'SPLIT'
    for n, v, lo, hi in (('plate_thickness_mm', plate_thickness_mm, 0.1, 10.0), ('gap_mm', gap_mm, 0.0, 10.0), ('outer_groove_mm', outer_groove_mm, 0.05, 5.0),
                         ('centre_slot_mm', centre_slot_mm, 0.1, 10.0), ('outline_margin_mm', outline_margin_mm, 0.02, 2.0), ('slab_top_mm', slab_top_mm, 1.0, 50.0),
                         ('fit_tol_mm', fit_tol_mm, 1e-7, 0.01), ('mesh_deflection_mm', mesh_deflection_mm, 0.0005, 0.5), ('book_tol_mm3', book_tol_mm3, 0.0, 1000.0),
                         ('sym_tol', sym_tol, 0.0, 0.5), ('interference_tol_mm3', interference_tol_mm3, 0.0, 100.0),
                         ('ray_tol_thickness_mm', ray_tol_thickness_mm, 1e-5, 1.0), ('ray_tol_gap_mm', ray_tol_gap_mm, 1e-5, 1.0), ('ray_pass', ray_pass, 0.5, 1.0),
                         ('sew_tol_mm', sew_tol_mm, 1e-5, 0.5), ('wheel_margin_mm', wheel_margin_mm, -5.0, 20.0),
                         ('window_corner_r_mm', window_corner_r_mm, 0.0, 50.0)):
        check_range(n, v, lo, hi, f'{code}_SETTINGS')
    for n, v, lo, hi in (('min_patch_area_mm2', min_patch_area_mm2, 0.0, 1e6), ('min_groove_length_mm', min_groove_length_mm, 0.0, 1000.0), ('uv_margin', uv_margin, 1e-9, 1e6)):
        if v is not None:
            check_range(n, v, lo, hi, f'{code}_SETTINGS')
    if lateral_axis not in ('auto', 'x', 'y'):
        raise BrainError(f'{code}_SETTINGS', 'lateral_axis must be "auto" (measured: the plan axis along which the two click patches are separated), "x" or "y".', {'given': lateral_axis})
    if centre_source not in ('patches', 'shell_bbox'):
        raise BrainError(f'{code}_SETTINGS', 'centre_source must be "patches" (midpoint of the gap between the two patches) or "shell_bbox" (mid plane of the shell bbox).', {'given': centre_source})
    if isinstance(fit_n, bool) or not isinstance(fit_n, int) or not 21 <= fit_n <= 401:
        raise BrainError(f'{code}_SETTINGS', 'fit_n must be an integer in [21, 401].', {'given': fit_n})
    if isinstance(ray_n, bool) or not isinstance(ray_n, int) or not 20 <= ray_n <= 5000:
        raise BrainError(f'{code}_SETTINGS', 'ray_n must be an integer in [20, 5000].', {'given': ray_n})
    if centre_mm is not None and not _num(centre_mm):
        raise BrainError(f'{code}_SETTINGS', 'centre_mm (mirror plane coordinate along the lateral axis) must be a finite number or omitted (see centre_source).', {'given': centre_mm})
    if patch_faces is not None and (not isinstance(patch_faces, list) or len(patch_faces) != 2
                                    or not all(isinstance(i, int) and not isinstance(i, bool) and i >= 0 for i in patch_faces)):
        raise BrainError(f'{code}_SETTINGS', 'patch_faces must be two face indices of the filled skin solid (then shell_step_path IS the filled skin), or omitted.',
                         {'given': patch_faces})
    if patch_faces is not None and skin_step_path is not None:
        raise BrainError(f'{code}_SETTINGS', 'Give either skin_step_path (filled skin + shell_step_path as groove source) or patch_faces, not both.')
    win = None
    if cut_window:
        if window is not None:
            if wheel_step_path is not None:
                raise BrainError(f'{code}_SETTINGS', 'Give either window or wheel_step_path, not both.')
            if (not isinstance(window, dict) or set(window) - set(WINDOW_KEYS) or not {'w', 'h', 'cx', 'cy'} <= set(window)
                    or not all(_num(v) for v in window.values())):
                raise BrainError(f'{code}_SETTINGS', 'window must give w, h, cx, cy (and optionally r, default 0) in mm: a rectangle in the model x/y plan (w along x, h along y).',
                                 {'given': window})
            win = {'r': 0.0, **{k: float(v) for k, v in window.items()}}
            if not (win['w'] > 0 and win['h'] > 0 and 0 <= win['r'] < min(win['w'], win['h']) / 2):
                raise BrainError(f'{code}_SETTINGS', 'window needs w, h > 0 and 0 <= r < min(w, h) / 2.', {'window': win})
        elif wheel_step_path is None:
            raise BrainError(f'{code}_WINDOW_REQUIRED', 'cut_window is true but the wheel window is unknown: pass wheel_step_path (+ wheel_part; the window is the wheel plan bbox + wheel_margin_mm), '
                                                        'an explicit window {w, h, cx, cy[, r]}, or cut_window = false. There is no default window.')
    elif window is not None or wheel_step_path is not None:
        raise BrainError(f'{code}_SETTINGS', 'window / wheel_step_path was given but cut_window is false.')
    shell = check_file(workspace, shell_step_path, STEP_SUFFIXES, f'{code}_FILE', 'shell_step_path')
    skin = check_file(workspace, skin_step_path, STEP_SUFFIXES, f'{code}_FILE', 'skin_step_path') if skin_step_path is not None else None
    wheel = check_file(workspace, wheel_step_path, STEP_SUFFIXES, f'{code}_FILE', 'wheel_step_path') if wheel_step_path is not None else None
    settings = {'shell_part': _part(shell_part, 'shell_part', f'{code}_SETTINGS'), 'skin_part': _part(skin_part, 'skin_part', f'{code}_SETTINGS'),
                'wheel_part': _part(wheel_part, 'wheel_part', f'{code}_SETTINGS'), 'wheel_margin_mm': float(wheel_margin_mm), 'window_corner_r_mm': float(window_corner_r_mm),
                'cut_window': bool(cut_window), 'lateral_axis': lateral_axis, 'centre_source': centre_source, 'uv_margin': None if uv_margin is None else float(uv_margin),
                'min_groove_length_mm': None if min_groove_length_mm is None else float(min_groove_length_mm),
                'patch_faces': patch_faces, 'plate_thickness_mm': float(plate_thickness_mm), 'gap_mm': float(gap_mm), 'outer_groove_mm': float(outer_groove_mm),
                'centre_slot_mm': float(centre_slot_mm), 'centre_mm': None if centre_mm is None else float(centre_mm),
                'outline_margin_mm': float(outline_margin_mm), 'window': win, 'slab_top_mm': float(slab_top_mm), 'fit_n': fit_n, 'fit_tol': float(fit_tol_mm),
                'mesh_deflection_mm': float(mesh_deflection_mm), 'book_tol_mm3': float(book_tol_mm3), 'sym_tol': float(sym_tol),
                'interference_tol_mm3': float(interference_tol_mm3), 'ray_n': ray_n, 'ray_tol_t_mm': float(ray_tol_thickness_mm), 'ray_tol_gap_mm': float(ray_tol_gap_mm),
                'ray_pass': float(ray_pass), 'min_patch_area_mm2': None if min_patch_area_mm2 is None else float(min_patch_area_mm2), 'sew_tol_mm': float(sew_tol_mm)}

    def build_report(res, final, job_id, hashes):
        rays, book = res['rays'], res['book']
        roles = res['carve_face_roles']
        rel = f'mouse/cad/{job_id}'
        plates = {sd: {'part_name': f'click_plate_{sd}', 'file_part_name': f'plate_{sd}', 'step_path': f'{rel}/plate_{sd}.step',
                       'assembly_step_path': f'{rel}/click_split_parts.step', 'volume_mm3': res['solids'][f'plate_{sd}']['volume_mm3'],
                       'bbox': res['solids'][f'plate_{sd}']['bbox']} for sd in ('L', 'R')}
        handoff = {'schema': 'mouse_split_click_handoff/1', 'split_click_id': job_id,
                   'shell_open_step_path': f'{rel}/shell_open.step', 'face_roles': {k: roles[k] for k in ('step', 'floor', 'bearing')},
                   'carve_face_roles': {k: roles[k] for k in ('step', 'floor', 'bearing')}, 'roles_detail': roles, 'click_plates': plates}
        (Path(final) / 'carve_handoff.json').write_text(json.dumps(handoff, indent=1), encoding='utf-8')
        res['files']['carve_handoff'] = 'carve_handoff.json'
        return {'schema': 'mouse_split_click_report/1', 'status': 'READY', 'split_click_id': job_id, 'version': SPLIT_VERSION, 'server_version': __version__,
                'inputs': {'shell_step_path': shell_step_path, 'skin_step_path': skin_step_path}, 'input_hashes': hashes, 'settings': settings, 'mode': res['mode'],
                'detection': res['detection'], 'lateral_axis': res['lateral_axis'], 'centre_mm': res['centre_mm'], 'shell_mid_mm': res['shell_mid_mm'],
                'window': res['window'], 'window_source': res['window_source'], 'uv_margin_used': res['uv_margin_used'], 'slab_top_used_mm': res.get('slab_top_used_mm'), 'slab_top_tried_mm': res.get('slab_top_tried_mm'), 'mesh_repairs': res.get('mesh_repairs', []), 'face_roles': handoff['face_roles'], 'carve_face_roles': handoff['carve_face_roles'],
                'carve_roles_detail': roles, 'click_plates': plates, 'shell_open_step_path': handoff['shell_open_step_path'], 'solids': res['solids'], 'groove_fill': res.get('groove_fill'),
                'evidence': {'plate_ray_thickness': {'target_mm': settings['plate_thickness_mm'], 'tol_mm': settings['ray_tol_t_mm'], 'share_ok': rays['thk_ok'],
                                                    'median_mm': rays['thk_med'], 'p5_mm': rays['thk_p5'], 'p95_mm': rays['thk_p95'], 'rays': rays['thk_n']},
                             'gap_ray': {'target_mm': settings['gap_mm'], 'tol_mm': settings['ray_tol_gap_mm'], 'share_ok': rays['gap_ok'], 'median_mm': rays['gap_med'],
                                         'p5_mm': rays['gap_p5'], 'p95_mm': rays['gap_p95'], 'rays': rays['gap_n']},
                             'required_ray_share': settings['ray_pass'], 'lr_symmetry_rel': res['symmetry'], 'lr_symmetry_limit': settings['sym_tol'],
                             'interference_mm3': res['interference_mm3'], 'interference_limit_mm3': settings['interference_tol_mm3'],
                             'volume_bookkeeping': {**book, 'limit_abs_residual_mm3': settings['book_tol_mm3']}},
                'warnings': res['warnings'], 'outputs': {k: {'file': v} for k, v in res['files'].items()}, 'seconds': res.get('seconds'),
                'limits': ['Volumes are closed-mesh volumes (mesh_deflection_mm); BRepGProp volumes of these B-spline solids differ by up to ~100 mm3.',
                           'The offset slabs are C2 B-spline fits of the true normal offset (fit_n x fit_n, fit_tol_mm), accurate to ~1e-3 mm inside the click area.',
                           'The wheel window is the plan bbox of the given wheel part (+ margin) or an explicit argument, not detected from the pocket faces; there is no default.',
                           'The mirror plane is measured (lateral axis = the plan axis separating the two patches; centre = the patch gap midpoint unless centre_mm / centre_source); "L" = the smaller lateral coordinate.',
                           'Ray thickness / gap near steep walls (within ~0.7 mm of the window edge) are excluded by the sampling margins, not measured.']}

    return run_job(workspace=workspace, area='cad', prefix='sc_', version=SPLIT_VERSION, code=code, inputs={'shell': shell, 'skin': skin, 'wheel': wheel}, settings=settings,
                   worker=HERE / 'mouse_split_click_worker.py', python=server_python(), report_name=SPLIT_REPORT, build_report=build_report, timeout_s=3600)


__all__ = ['split_click_region', 'SPLIT_VERSION', 'SPLIT_REPORT']
