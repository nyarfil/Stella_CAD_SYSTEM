"""Band-stop fairing of a welded scan mesh (brain_mouse_scan_fair).

Mesh stage, no CAD, no labels required. Removes ripples / facets / dents shorter than min_wavelength_mm with a thin-plate (bi-Laplacian)
low-pass on the fine mesh: same vertices, same faces, same face order (no remesh, no inflation). The flat plate rim and real features are
protected. Runs scan_fair_worker.py in the separate scan python; outputs once under mouse/scans/<fa_id>/.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from . import scan_mesh as sm
from .scan_cad_common import check_file, check_range, run_job
from .scan_model import find_scan_python
from .scan_symmetrise_worker import DEFAULTS as SYM_DEFAULTS
from .. import __version__
from ..errors import BrainError

FAIR_VERSION = 'F1.0'
WORKER = Path(__file__).with_name('scan_fair_worker.py')
REPORT = 'fair_report.json'
CODE = 'FAIR'


def scan_fair(workspace: Path, relative_path: str, unit: str, min_wavelength_mm: float = 12.0, labels_path: str | None = None,
              fixed_regions: list[str] | None = None, feature_protection: str = 'auto', feature_tol_mm: float | None = None,
              plate_freeze: str = 'auto', rim_height_mm: float | None = None, tol_p95_mm: float = 0.5, volume_tol_pct: float = 0.5) -> dict[str, Any]:
    if unit not in sm.UNIT_MM:
        raise BrainError('SCAN_UNIT', 'unit is required and must be one of mm, cm, m, in. It is never guessed.', {'given': unit})
    check_range('min_wavelength_mm', min_wavelength_mm, 2.0, 100.0, 'FAIR_SETTINGS')
    check_range('tol_p95_mm', tol_p95_mm, 0.02, 5.0, 'FAIR_SETTINGS')
    check_range('volume_tol_pct', volume_tol_pct, 0.01, 5.0, 'FAIR_SETTINGS')
    if feature_tol_mm is not None:
        check_range('feature_tol_mm', feature_tol_mm, 0.02, 5.0, 'FAIR_SETTINGS')
    if rim_height_mm is not None:
        check_range('rim_height_mm', rim_height_mm, 0.0, 50.0, 'FAIR_SETTINGS')
    for name, val in (('feature_protection', feature_protection), ('plate_freeze', plate_freeze)):
        if val not in ('auto', 'off'):
            raise BrainError('FAIR_SETTINGS', f"{name} must be 'auto' or 'off'.", {'given': val})
    if fixed_regions is not None and (not isinstance(fixed_regions, list) or len(fixed_regions) > 64
                                      or not all(isinstance(x, str) and 0 < len(x) <= 64 for x in fixed_regions)):
        raise BrainError('FAIR_SETTINGS', 'fixed_regions must be a list of region names.', {'given': fixed_regions})
    src = check_file(workspace, relative_path, ('.stl',), 'SCAN_FILE', 'relative_path')
    lab = check_file(workspace, labels_path, ('.json', '.npz'), 'FAIR_LABELS', 'labels_path') if labels_path else None
    settings = {'unit_scale': sm.UNIT_MM[unit], 'min_wavelength_mm': float(min_wavelength_mm), 'feature_protection': feature_protection,
                'feature_tol_mm': None if feature_tol_mm is None else float(feature_tol_mm), 'plate_freeze': plate_freeze,
                'rim_height_mm': None if rim_height_mm is None else float(rim_height_mm),
                'fixed_regions': (SYM_DEFAULTS['fixed_regions'] if fixed_regions is None else list(fixed_regions)) if lab else [],
                'tol_p95_mm': float(tol_p95_mm), 'volume_tol_pct': float(volume_tol_pct)}

    def build(res: dict[str, Any], folder: Path, job_id: str, hashes: dict[str, str | None]) -> dict[str, Any]:
        vol, dev, msh = res['volume'], res['deviation_mm'], res['mesh']
        blockers = []
        if not msh['watertight_after']:
            blockers.append('NOT_WATERTIGHT')
        if msh['faces_after'] != msh['faces']:
            blockers.append('FACE_COUNT_CHANGED')
        if abs(vol['change_pct']) > settings['volume_tol_pct']:
            blockers.append('VOLUME_CHANGE_TOO_LARGE')
        if dev['p95'] > settings['tol_p95_mm']:
            blockers.append('DEVIATION_P95_TOO_LARGE')
        files = res['files']
        return {
            'schema': 'scan_fair_report/1', 'fair_id': job_id, 'status': 'NOT_READY' if blockers else 'READY', 'blocking_reasons': blockers,
            'warnings': res['warnings'], 'code_version': {'scan_fair': FAIR_VERSION, 'worker': res['worker'], 'package': __version__},
            'source': {'relative_path': relative_path, 'sha256': hashes['mesh'], 'labels_relative_path': labels_path, 'labels_sha256': hashes['labels']},
            'settings': settings, 'units': {'input': unit, 'output': 'mm'}, 'method': res['method'], 'plate': res['plate'], 'labels': res['labels'],
            'protected': res['protected'], 'volume': vol, 'deviation_mm': dev, 'displacement_mm': res['displacement_mm'],
            'ripple_rms_mm': res['ripple_rms_mm'], 'curvature_roughness': res['curvature_roughness'], 'mesh': msh,
            'outputs': {'faired': {'file': files['mesh'], 'faces': msh['faces']}, 'mask': {'file': files['mask']}},
            'checks': {'watertight_after': 'PASS' if msh['watertight_after'] else 'FAIL',
                       'face_order_unchanged': 'PASS' if msh['faces_after'] == msh['faces'] else 'FAIL',
                       'volume_change': 'PASS' if abs(vol['change_pct']) <= settings['volume_tol_pct'] else 'FAIL',
                       'deviation_p95': 'PASS' if dev['p95'] <= settings['tol_p95_mm'] else 'FAIL'},
            'downstream': {'note': 'Same vertices and face order as the input: labels stay valid for faired.stl. Judge the result with the deviation and '
                                   'ripple numbers, not by eye alone.'},
            'limits': ['Wavelengths below min_wavelength_mm are removed, longer ones kept (half-gain at min_wavelength_mm, smooth roll-off).',
                       'Auto feature protection keeps compact one-signed residual blobs of the plain pass (seed |smoothed residual| above both 5 robust '
                       'sigmas and feature_tol_mm, default min_wavelength_mm / 20; sign-alternating ripple cancels and is not kept); bumps below that '
                       'amplitude are smoothed, and protected blobs keep their own sharp content (see ripple_rms_mm all vs unprotected_ratio). Give labels '
                       '+ fixed_regions for exact protection; feature_components lists what was kept.',
                       'The plate rim is frozen only when a dominant flat face cluster exists (>= 2 % of the surface).',
                       'Positions only; no remeshing: faceting finer than the mesh cannot be fixed, coarse input stays coarse.'],
            'seconds': res['seconds'],
        }

    return run_job(workspace=workspace, area='scans', prefix='fa_', version=FAIR_VERSION, code=CODE, inputs={'mesh': src, 'labels': lab},
                   settings=settings, worker=WORKER, python=find_scan_python(workspace), report_name=REPORT, build_report=build, timeout_s=1800)


__all__ = ['scan_fair', 'FAIR_VERSION']
