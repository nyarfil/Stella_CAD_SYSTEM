"""Fair B-spline skin of a (symmetrised) scan shell region (brain_mouse_shell_fit).

Half + mirror (sewn, mirror G1) when the symmetry source says the domain is symmetric, else one face over the full region: symmetry is
never forced. Runs scan_shell_fit_worker.py in the server python (OCP); outputs once under mouse/cad/<sf_id>/.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from . import scan_mesh as sm
from .scan_cad_common import check_file, check_range, run_job, server_python
from .. import __version__
from ..errors import BrainError

FIT_VERSION = 'SF1.3'
WORKER = Path(__file__).with_name('scan_shell_fit_worker.py')
REPORT = 'shell_fit_report.json'
CODE = 'SHELL_FIT'


def _plane(obj: Any, what: str) -> dict[str, Any]:
    ok = isinstance(obj, dict) and isinstance(obj.get('normal'), list) and len(obj['normal']) == 3 and isinstance(obj.get('d'), (int, float)) \
        and not isinstance(obj.get('d'), bool) and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in obj['normal']) \
        and sum(float(x) ** 2 for x in obj['normal']) > 1e-12
    if not ok:
        raise BrainError('SHELL_FIT_SETTINGS', f'{what} must be {{"normal": [nx, ny, nz], "d": d}} (plane normal . x = d, mm).', {'given': obj})
    return {'normal': [float(x) for x in obj['normal']], 'd': float(obj['d'])}


def shell_fit(workspace: Path, relative_path: str, unit: str, labels_path: str | None = None, regions: list[str] | None = None,
              symmetry_report_path: str | None = None, mirror_plane: dict[str, Any] | None = None, mode: str = 'auto', fit_side: str = 'auto',
              cut_planes: list[dict[str, Any]] | None = None, degree: int = 3, spans_u: int = 10, spans_v: int = 6, smoothing: float = 1e-7,
              min_wavelength_mm: float = 10.0, tol_p95_mm: float = 0.2, tol_max_mm: float = 1.0, front_cut: str = 'auto',
              front_cut_step_mm: float = 3.0) -> dict[str, Any]:
    if unit not in sm.UNIT_MM:
        raise BrainError('SCAN_UNIT', 'unit is required and must be one of mm, cm, m, in. It is never guessed.', {'given': unit})
    if mode not in ('auto', 'half', 'full'):
        raise BrainError('SHELL_FIT_SETTINGS', "mode must be 'auto', 'half' or 'full'.", {'given': mode})
    if fit_side not in ('auto', 'positive', 'negative'):
        raise BrainError('SHELL_FIT_SETTINGS', "fit_side must be 'auto', 'positive' or 'negative'.", {'given': fit_side})
    for name, val, lo, hi in (('degree', degree, 2, 7), ('spans_u', spans_u, 1, 40), ('spans_v', spans_v, 1, 40)):
        check_range(name, val, lo, hi, 'SHELL_FIT_SETTINGS')
        if not isinstance(val, int):
            raise BrainError('SHELL_FIT_SETTINGS', f'{name} must be an integer.', {'given': val})
    if front_cut not in ('auto', 'none'):
        raise BrainError('SHELL_FIT_SETTINGS', "front_cut must be 'auto' or 'none'.", {'given': front_cut})
    check_range('front_cut_step_mm', front_cut_step_mm, 0.5, 20.0, 'SHELL_FIT_SETTINGS')
    check_range('smoothing', smoothing, 0.0, 1e-2, 'SHELL_FIT_SETTINGS')
    check_range('min_wavelength_mm', min_wavelength_mm, 0.0, 100.0, 'SHELL_FIT_SETTINGS')
    check_range('tol_p95_mm', tol_p95_mm, 0.001, 5.0, 'SHELL_FIT_SETTINGS')
    check_range('tol_max_mm', tol_max_mm, 0.001, 20.0, 'SHELL_FIT_SETTINGS')
    if regions is not None and (not isinstance(regions, list) or not regions or not all(isinstance(x, str) and 0 < len(x) <= 64 for x in regions)):
        raise BrainError('SHELL_FIT_SETTINGS', 'regions must be a non-empty list of region names.', {'given': regions})
    if regions is not None and not labels_path:
        raise BrainError('SHELL_FIT_SETTINGS', 'regions needs labels_path.')
    cuts = [_plane(c, 'each cut plane') for c in (cut_planes or [])]
    if len(cuts) > 3:
        raise BrainError('SHELL_FIT_SETTINGS', 'At most 3 cut planes.', {'given': len(cuts)})
    mp = _plane(mirror_plane, 'mirror_plane') if mirror_plane is not None else None
    if mp is not None and symmetry_report_path:
        raise BrainError('SHELL_FIT_SETTINGS', 'Give either symmetry_report_path or mirror_plane, not both.')
    if mode == 'half' and mp is None and not symmetry_report_path:
        raise BrainError('SHELL_FIT_NOT_SYMMETRIC', 'mode half needs a symmetry source (symmetry_report_path or mirror_plane).')
    src = check_file(workspace, relative_path, ('.stl',), 'SCAN_FILE', 'relative_path')
    lab = check_file(workspace, labels_path, ('.json', '.npz'), 'SHELL_FIT_LABELS', 'labels_path') if labels_path else None
    rep = check_file(workspace, symmetry_report_path, ('.json',), 'SHELL_FIT_SYMMETRY', 'symmetry_report_path') if symmetry_report_path else None
    settings = {'unit_scale': sm.UNIT_MM[unit], 'regions': regions or ['top_shell'], 'mode': mode, 'fit_side': fit_side, 'cut_planes': cuts,
                'degree': int(degree), 'spans_u': int(spans_u), 'spans_v': int(spans_v), 'lam': float(smoothing), 'min_wavelength_mm': float(min_wavelength_mm),
                'tol_p95_mm': float(tol_p95_mm), 'tol_max_mm': float(tol_max_mm), 'mirror_plane': mp,
                'front_cut': 'none' if cuts else front_cut, 'front_cut_step_mm': float(front_cut_step_mm)}

    def build(res: dict[str, Any], folder: Path, job_id: str, hashes: dict[str, str | None]) -> dict[str, Any]:
        dev, br, mb, lay = res['deviation'], res['brep'], res['mirror_border'], res['layout']
        checks = {'deviation_p95': 'PASS' if (dev['all']['p95'] or 0) <= tol_p95_mm else 'FAIL',
                  'deviation_max': 'PASS' if (dev['all']['max'] or 0) <= tol_max_mm else 'FAIL',
                  'brep_valid': 'PASS' if br['valid'] else 'FAIL',
                  'sewn': 'PASS' if br['faces'] == (2 if res['mode_used'] == 'half' else 1) and br['multiple_edges'] == 0 else 'FAIL',
                  'parameterisation': 'PASS' if lay['parameterisation']['flipped_area_fraction'] <= 1e-3 and res['fairness']['param_angle_min_deg'] >= 10 else 'FAIL',
                  'mirror_G1': ('PASS' if mb['G1_normal_angle_deg_max'] <= 0.01 and mb['G0_gap_to_plane_mm'] <= 1e-6 else 'FAIL') if mb else 'NOT_APPLICABLE',
                  'min_wavelength': 'PASS' if res['fit']['min_representable_wavelength_mm'] >= min_wavelength_mm - 1e-9 else 'FAIL',
                  'closed_solid': 'NOT_APPLICABLE'}
        blockers = [k.upper() for k, v in checks.items() if v == 'FAIL']
        files = res['files']
        return {
            'schema': 'shell_fit_report/1', 'fit_id': job_id, 'status': 'NOT_READY' if blockers else 'READY', 'blocking_reasons': blockers, 'warnings': res['warnings'],
            'code_version': {'shell_fit': FIT_VERSION, 'worker': res['worker'], 'package': __version__},
            'source': {'relative_path': relative_path, 'sha256': hashes['mesh'], 'labels_relative_path': labels_path, 'labels_sha256': hashes['labels'],
                       'symmetry_report_relative_path': symmetry_report_path, 'symmetry_report_sha256': hashes['symmetry']},
            'settings': settings, 'units': {'input': unit, 'output': 'mm'}, 'mode_used': res['mode_used'], 'symmetry_reason': res['symmetry_reason'],
            'side': res['side'], 'domain': res['domain'], 'layout': lay, 'fit': res['fit'], 'deviation': dev, 'mirror_border': mb, 'fairness': res['fairness'],
            'brep': br, 'checks': checks,
            'front_cut': res.get('front_cut') or {'mode': 'given' if cuts else 'none', 'chosen': None},
            'cut_planes_used': (res.get('params_used') or {}).get('cut_planes', cuts),
            'outputs': {'skin': {'file': files['step'], 'faces': br['faces']}, 'surface': {'file': files['surface']}},
            'downstream': {'note': 'shell_skin.step is an OPEN skin (half + mirror sewn, or one face). brain_mouse_shell_solid closes a half + mirror skin '
                                   'with one front cut (front wall, crisp lip, parting surface); then brain_mouse_click_slots, brain_mouse_plate_side '
                                   'and brain_mouse_face_roles.'},
            'limits': ['front_cut auto (only without cut_planes): no cut when the full fit is READY, else the most forward READY cut perpendicular '
                       'to the mirror plane along the input x axis (standard frame: x front); the chosen cut is in front_cut / cut_planes_used.',
                       'One four-sided face per half: a region with an interior crease needs its own split (not detected here).',
                       f'Waviness shorter than about {res["fit"]["min_representable_wavelength_mm"]:.1f} mm cannot be represented (knot spacing); deviation '
                       'there is the scan ripple that was rejected on purpose.',
                       'Feature holes in the domain are bridged by the fair surface (zero fit weight); features are rebuilt by their own tools.',
                       'The skin is not closed to a solid and has no crisp lip here (brain_mouse_shell_solid does that).'],
            'seconds': res['seconds'],
        }

    return run_job(workspace=workspace, area='cad', prefix='sf_', version=FIT_VERSION, code=CODE, inputs={'mesh': src, 'labels': lab, 'symmetry': rep},
                   settings=settings, worker=WORKER, python=server_python(), report_name=REPORT, build_report=build, timeout_s=1800)


__all__ = ['shell_fit', 'FIT_VERSION']
