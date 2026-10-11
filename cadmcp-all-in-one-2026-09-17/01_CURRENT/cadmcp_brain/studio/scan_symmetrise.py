"""Coarse mirror-symmetry detection and scan-error symmetrisation of a welded scan mesh (brain_mouse_scan_symmetrise).

Mesh stage, no CAD. Symmetry is never forced: a robust best-fit mirror plane, then a coarse per-region AND per-cell test (p80 mirror residual
vs max(abs_threshold_mm, rel_threshold x bbox diagonal)); only passing regions/cells are corrected, real asymmetry stays as scanned. Labels
are hints. Runs scan_symmetrise_worker.py in the separate scan python; outputs once under mouse/scans/<sy_id>/.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from . import scan_mesh as sm
from .scan_cad_common import check_file, check_range, run_job
from .scan_model import find_scan_python
from .scan_symmetrise_worker import DEFAULTS
from .. import __version__
from ..errors import BrainError

SYM_VERSION = 'S1.0'
WORKER = Path(__file__).with_name('scan_symmetrise_worker.py')
REPORT = 'symmetry_report.json'
CODE = 'SYMMETRISE'


def scan_symmetrise(workspace: Path, relative_path: str, unit: str, labels_path: str | None = None, abs_threshold_mm: float = 2.0, rel_threshold: float = 0.015,
                    cell_mm: float | None = None, correspondence_cap_mm: float = 1.0, fixed_regions: list[str] | None = None,
                    exclude_regions: list[str] | None = None, normal_hint: list[float] | None = None, passes: int = 3, ramp_mm: float = 2.0, plane_search: str = 'lateral') -> dict[str, Any]:
    if plane_search not in ('lateral', 'pca', 'hint'):
        raise BrainError('SYMMETRISE_SETTINGS', "plane_search must be 'lateral', 'pca' or 'hint'.", {'given': plane_search})
    if (plane_search == 'hint') != (normal_hint is not None):
        raise BrainError('SYMMETRISE_SETTINGS', "normal_hint is required with plane_search 'hint' and accepted only there.", {'plane_search': plane_search})
    if unit not in sm.UNIT_MM:
        raise BrainError('SCAN_UNIT', 'unit is required and must be one of mm, cm, m, in. It is never guessed.', {'given': unit})
    check_range('abs_threshold_mm', abs_threshold_mm, 0.2, 20.0, 'SYMMETRISE_SETTINGS')
    check_range('rel_threshold', rel_threshold, 0.0, 0.1, 'SYMMETRISE_SETTINGS')
    if cell_mm is not None:
        check_range('cell_mm', cell_mm, 2.0, 100.0, 'SYMMETRISE_SETTINGS')
    check_range('correspondence_cap_mm', correspondence_cap_mm, 0.05, 5.0, 'SYMMETRISE_SETTINGS')
    check_range('passes', passes, 1, 10, 'SYMMETRISE_SETTINGS')
    if not isinstance(passes, int):
        raise BrainError('SYMMETRISE_SETTINGS', 'passes must be an integer.', {'given': passes})
    check_range('ramp_mm', ramp_mm, 0.0, 20.0, 'SYMMETRISE_SETTINGS')
    for name, val in (('fixed_regions', fixed_regions), ('exclude_regions', exclude_regions)):
        if val is not None and (not isinstance(val, list) or not all(isinstance(x, str) and 0 < len(x) <= 64 for x in val) or len(val) > 64):
            raise BrainError('SYMMETRISE_SETTINGS', f'{name} must be a list of region names.', {'given': val})
    if normal_hint is not None:
        if not isinstance(normal_hint, list) or len(normal_hint) != 3 or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in normal_hint) \
                or sum(float(x) ** 2 for x in normal_hint) < 1e-12:
            raise BrainError('SYMMETRISE_SETTINGS', 'normal_hint must be a non-zero [nx, ny, nz].', {'given': normal_hint})
    src = check_file(workspace, relative_path, ('.stl',), 'SCAN_FILE', 'relative_path')
    lab = check_file(workspace, labels_path, ('.json', '.npz'), 'SYMMETRISE_LABELS', 'labels_path') if labels_path else None
    settings = {'unit_scale': sm.UNIT_MM[unit], 'abs_threshold_mm': float(abs_threshold_mm), 'rel_threshold': float(rel_threshold),
                'cell_mm': None if cell_mm is None else float(cell_mm), 'correspondence_cap_mm': float(correspondence_cap_mm), 'passes': int(passes),
                'ramp_mm': float(ramp_mm), 'fixed_regions': DEFAULTS['fixed_regions'] if fixed_regions is None else list(fixed_regions),
                'exclude_regions': DEFAULTS['exclude_regions'] if exclude_regions is None else list(exclude_regions),
                'normal_hint': None if normal_hint is None else [float(x) for x in normal_hint], 'plane_search': plane_search}

    def build(res: dict[str, Any], folder: Path, job_id: str, hashes: dict[str, str | None]) -> dict[str, Any]:
        test, sy = res['symmetry_test'], res['symmetrise']
        blockers = [] if test['global']['plane_valid'] else ['NO_MIRROR_PLANE']
        if res['mesh']['faces_after'] != res['mesh']['faces']:
            blockers.append('FACE_COUNT_CHANGED')
        sym = [k for k, v in test['regions'].items() if v.get('symmetric')]
        asym = [k for k, v in test['regions'].items() if not v.get('symmetric')]
        files = res['files']
        return {
            'schema': 'scan_symmetry_report/1', 'symmetry_id': job_id, 'status': 'NOT_READY' if blockers else 'READY', 'blocking_reasons': blockers,
            'warnings': res['warnings'], 'code_version': {'scan_symmetrise': SYM_VERSION, 'worker': res['worker'], 'package': __version__},
            'source': {'relative_path': relative_path, 'sha256': hashes['mesh'], 'labels_relative_path': labels_path, 'labels_sha256': hashes['labels']},
            'settings': settings, 'units': {'input': unit, 'output': 'mm'},
            'plane': res['plane'], 'plane_candidates': res['plane_candidates'], 'threshold_mm': test['threshold_mm'],
            'symmetric_regions': sym, 'asymmetric_regions': asym, 'symmetry_test': test, 'symmetrise': sy, 'mesh': res['mesh'],
            'outputs': {'symmetrised': {'file': files['mesh'], 'faces': res['mesh']['faces']}, 'mask': {'file': files['mask']}, 'plane': {'file': files['plane']}},
            'checks': {'mirror_plane': 'PASS' if test['global']['plane_valid'] else 'FAIL',
                       'face_order_unchanged': 'PASS' if res['mesh']['faces_after'] == res['mesh']['faces'] else 'FAIL',
                       'kept_faces_unmoved': 'PASS' if sy['max_displacement_kept_faces_mm'] <= 1e-9 else 'FAIL',
                       'watertight_after': 'PASS' if res['mesh']['watertight_after'] else ('FAIL' if res['mesh']['watertight_before'] else 'NOT_APPLICABLE')},
            'downstream': {'note': 'The plane (normal . x = d, input frame) and the per-region decisions are the symmetry source for brain_mouse_shell_fit and '
                                   'brain_mouse_plate_side (symmetry_report_path = this report). Same face order: the input labels stay valid for symmetrised.stl.'},
            'limits': ['The decision is coarse on purpose: differences below the threshold are treated as scan error and corrected; real design asymmetry '
                       'above it is kept as scanned. A region that is symmetric except some cells keeps those cells as scanned.',
                       'Vertices move along their normal only (no remeshing); grooves narrower than the correspondence cap are not rebuilt here.',
                       'One mirror plane per part; a part with no usable plane is written unchanged (NOT_READY).'],
            'seconds': res['seconds'],
        }

    return run_job(workspace=workspace, area='scans', prefix='sy_', version=SYM_VERSION, code=CODE, inputs={'mesh': src, 'labels': lab}, settings=settings,
                   worker=WORKER, python=find_scan_python(workspace), report_name=REPORT, build_report=build, timeout_s=1800)


__all__ = ['scan_symmetrise', 'SYM_VERSION']
