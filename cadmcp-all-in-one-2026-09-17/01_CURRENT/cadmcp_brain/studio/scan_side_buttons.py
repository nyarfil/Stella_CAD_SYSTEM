"""Side-button pads + surrounding groove on a closed mouse top shell (brain_mouse_scan_side_buttons).

Detects the side buttons of the scan (side-button labels of the recognition / flush steps, or raised flank patches without labels), builds a
regular pad per button (straight edges, small corner radii, crisp top = quadratic fit of the scan pad top, or skin + default proud when the
confidence is below high) with a groove round it, on the given shell STEP (normally slotted_shell.step of brain_mouse_click_slots) and writes a
new STEP. Generic: 0..max_per_flank buttons per flank, any handedness, never mirrored. Runs scan_side_buttons_worker.py in the server python
(OCP); outputs once under mouse/cad/<sb_id>/; the input STEP is never modified.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .scan_cad_common import check_file, check_range, run_job, server_python
from .scan_side_buttons_worker import DEFAULTS, is_button_name
from .. import __version__
from ..errors import BrainError
from ..req2cad.common import json_load

SB_VERSION = 'SB1.0'
WORKER = Path(__file__).with_name('scan_side_buttons_worker.py')
REPORT = 'side_buttons_report.json'
CODE = 'SIDE_BUTTONS'
IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')
_RANGES = {'groove_width_mm': (0.0, 2.0), 'groove_depth_mm': (0.0, 5.0), 'corner_radius_mm': (0.1, 5.0), 'top_threshold_mm': (0.05, 2.0),
           'outline_tol_mm': (0.05, 2.0), 'min_area_mm2': (1.0, 500.0), 'default_proud_mm': (0.3, 3.0)}


def _regions(workspace: Path, rel: str) -> tuple[Path, dict[str, str], str | None]:
    p = check_file(workspace, rel, ('.json',), 'SIDE_BUTTONS_REGIONS', 'regions_report_path')
    rep = json_load(p)
    regs = rep.get('regions') if isinstance(rep, dict) else None
    if not isinstance(regs, dict):
        raise BrainError('SIDE_BUTTONS_REGIONS', 'regions_report_path must be a brain_mouse_recognize_regions report (with "regions").', {'given': rel})
    conf = {str(k): str(v.get('confidence')) for k, v in regs.items() if isinstance(v, dict) and is_button_name(str(k)) and v.get('confidence')}
    hand = ((rep.get('handedness') or {}).get('detected')) if isinstance(rep.get('handedness'), dict) else None
    return p, conf, hand


def side_buttons(workspace: Path, shell_step_path: str, mesh_path: str, labels_path: str | None = None, regions_report_path: str | None = None,
                 reference_images: list[str] | None = None, groove_width_mm: float = 0.4, groove_depth_mm: float = 1.5, corner_radius_mm: float = 1.0,
                 proud_mm: float | None = None, default_proud_mm: float = 1.0, top_threshold_mm: float = 0.35, outline_tol_mm: float = 0.35,
                 max_per_flank: int = 2, min_area_mm2: float = 15.0) -> dict[str, Any]:
    workspace = Path(workspace)
    vals = {'groove_width_mm': groove_width_mm, 'groove_depth_mm': groove_depth_mm, 'corner_radius_mm': corner_radius_mm, 'top_threshold_mm': top_threshold_mm,
            'outline_tol_mm': outline_tol_mm, 'min_area_mm2': min_area_mm2, 'default_proud_mm': default_proud_mm}
    for k, (lo, hi) in _RANGES.items():
        check_range(k, vals[k], lo, hi, 'SIDE_BUTTONS_SETTINGS')
    if proud_mm is not None:
        check_range('proud_mm', proud_mm, 0.3, 3.0, 'SIDE_BUTTONS_SETTINGS')
    if isinstance(max_per_flank, bool) or not isinstance(max_per_flank, int) or not 0 <= max_per_flank <= 6:
        raise BrainError('SIDE_BUTTONS_SETTINGS', 'max_per_flank must be an integer in [0, 6].', {'given': max_per_flank})
    if (groove_width_mm == 0) != (groove_depth_mm == 0):
        raise BrainError('SIDE_BUTTONS_SETTINGS', 'groove_width_mm and groove_depth_mm are both 0 (no groove, plain raised pad) or both > 0.')
    imgs: list[Path] = []
    if reference_images is not None:
        if not isinstance(reference_images, list) or len(reference_images) > 8 or not all(isinstance(x, str) for x in reference_images):
            raise BrainError('SIDE_BUTTONS_SETTINGS', 'reference_images must be a list of at most 8 workspace-relative image paths.')
        for r in reference_images:
            if not (workspace / r).is_file():
                raise BrainError('SIDE_BUTTONS_SETTINGS', 'A reference image does not exist.', {'given': r})
            imgs.append(check_file(workspace, r, IMAGE_SUFFIXES, 'SIDE_BUTTONS_SETTINGS', 'reference_images'))
    shell = check_file(workspace, shell_step_path, ('.step', '.stp'), 'SIDE_BUTTONS_FILE', 'shell_step_path')
    if mesh_path.lower().endswith('.json') and labels_path is None:
        rep = json_load(check_file(workspace, mesh_path, ('.json',), 'SIDE_BUTTONS_FILE', 'mesh_path (report)'))
        outs = (rep.get('outputs') or {}) if isinstance(rep, dict) else {}
        mesh_rel = next((v.get('relative_path') for v in outs.values() if isinstance(v, dict) and str(v.get('relative_path', '')).lower().endswith('.stl')), None)
        lab_rel = (outs.get('labels') or {}).get('relative_path') if isinstance(outs.get('labels'), dict) else None
        if not mesh_rel:
            raise BrainError('SIDE_BUTTONS_FILE', 'The mesh report lists no STL output.', {'given': mesh_path})
        mesh_path, labels_path = mesh_rel, lab_rel
    if labels_path is None:
        mp_ = mesh_path.replace(chr(92), '/')
        pair = mp_.rsplit('/', 1)[0] + '/labels.npz' if '/' in mp_ else 'labels.npz'
        if (workspace / pair).is_file():
            labels_path = pair
    mesh = check_file(workspace, mesh_path, ('.stl',), 'SIDE_BUTTONS_FILE', 'mesh_path')
    labels = check_file(workspace, labels_path, ('.json', '.npz'), 'SIDE_BUTTONS_LABELS', 'labels_path') if labels_path is not None else None
    reg_p, conf, hand = _regions(workspace, regions_report_path) if regions_report_path is not None else (None, {}, None)
    settings = {**DEFAULTS, **vals, 'proud_mm': proud_mm, 'max_per_flank': max_per_flank, 'region_confidence': conf or None, 'handedness': hand}
    inputs: dict[str, Path | None] = {'shell': shell, 'mesh': mesh, 'labels': labels, 'regions': reg_p}
    for k, ip in enumerate(imgs):
        inputs[f'image_{k}'] = ip
    rel = {'shell_step_path': shell_step_path, 'mesh_path': mesh_path, 'labels_path': labels_path, 'regions_report_path': regions_report_path,
           'reference_images': reference_images}

    def build(res: dict[str, Any], folder: Path, job_id: str, hashes: dict[str, str | None]) -> dict[str, Any]:
        r, btns = res['result'], res['buttons']
        mod = r['modified']
        checks = {'brep_valid': 'PASS' if r['valid'] else 'FAIL',
                  'one_solid': 'PASS' if r['solids_in_step'] == 1 and r['pieces_after_boolean'] == 1 else 'FAIL',
                  'reimport': 'PASS' if r['valid'] and r.get('tessellates') else 'FAIL',
                  'no_slivers': 'FAIL' if r['faces_below_0p05mm2'] else ('WARN' if r['faces_below_1mm2'] > r.get('faces_below_1mm2_before', 0) and r['faces_below_1mm2'] else 'PASS'),
                  'buttons_per_flank': 'FAIL' if any(b['code'] == 'SIDE_BUTTONS_TOO_MANY' for b in res['blockers']) else 'PASS',
                  'outline_regular': ('NOT_APPLICABLE' if not btns else 'PASS' if all((b.get('min_sharp_corner_r') is None or b['min_sharp_corner_r'] >= DEFAULTS['min_corner_radius_mm'] - 1e-9)
                                                                                     and (b.get('bspline_outline_dev_mm') or 0) <= 0.01 for b in btns) else 'FAIL')}
        if mod and res['grooved']:
            ok = all(b.get('measured') and b['measured']['groove_width_mm'] and abs(b['measured']['groove_width_mm']['p50'] - groove_width_mm) <= 0.05
                     and b['measured']['groove_depth_mm'] and abs(b['measured']['groove_depth_mm']['p50'] - groove_depth_mm) <= 0.1 for b in btns)
            checks['groove_as_specified'] = 'PASS' if ok else 'FAIL'
        if mod:
            checks['pad_proud'] = 'PASS' if all(b.get('measured') and b['measured']['proud_mm'] and b['measured']['proud_mm']['p50'] >= DEFAULTS['proud_min_mm']
                                                 for b in btns) else 'FAIL'
        blockers = sorted({b['code'] for b in res['blockers']} | {k.upper() for k, v in checks.items() if v == 'FAIL'})
        warnings = list(res['warnings'])
        low = [b['name'] for b in btns if b.get('confidence') != 'high']
        if not btns:
            warnings.append({'code': 'NO_SIDE_BUTTONS', 'message': 'No side button found; the output STEP equals the input shell.'})
        review = []
        if low:
            review.append({'code': 'SIDE_BUTTON_CONFIDENCE_BELOW_HIGH', 'buttons': low,
                           'message': ('v6-style default pad (regular outline, skin + default proud) built; '
                                       + ('compare with the reference_images.' if imgs else 'no reference_images given: check the pads by eye.'))})
        status = 'NOT_READY' if blockers else ('REVIEW' if review else 'READY')
        return {'schema': 'side_buttons_report/1', 'side_buttons_id': job_id, 'status': status, 'blocking_reasons': blockers, 'review_reasons': review,
                'warnings': warnings, 'code_version': {'side_buttons': SB_VERSION, 'worker': res['worker'], 'package': __version__},
                'source': {**rel, 'hashes': hashes}, 'settings': settings, 'units': {'input': 'mm', 'output': 'mm'},
                'buttons': btns, 'per_flank': res['per_flank'], 'handedness': {'from_buttons': res['handedness_from_buttons'], 'regions_report': res['handedness_regions']},
                'blockers_detail': res['blockers'], 'result': r, 'checks': checks,
                'outputs': {'shell': {'file': res['files']['step']}, 'buttons': {'file': res['files']['buttons']}},
                'downstream': {'note': 'Next: brain_mouse_plate_side / brain_mouse_face_roles with shell_step_path = outputs.shell (pads read as sidebutton + sidebutton_wall).'},
                'limits': ['The outline is the regularised convex hull of the raised scan points (slope-ring crest); concave button outlines are not followed.',
                           'Pad walls and groove walls are parallel to the push direction (mean skin normal), not normal to the local skin.',
                           'reference_images are recorded for the reviewer only; they are not analysed.',
                           'The input shell STEP is never modified; the result is a new file.'],
                'seconds': res.get('seconds')}

    return run_job(workspace=workspace, area='cad', prefix='sb_', version=SB_VERSION, code=CODE, inputs=inputs, settings=settings, worker=WORKER,
                   python=server_python(), report_name=REPORT, build_report=build, timeout_s=1800)


__all__ = ['side_buttons', 'SB_VERSION', 'REPORT']
