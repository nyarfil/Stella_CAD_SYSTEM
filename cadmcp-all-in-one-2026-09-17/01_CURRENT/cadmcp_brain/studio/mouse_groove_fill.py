"""brain_mouse_groove_fill: close the click groove of a mouse top shell on the shared skin B-spline (replaces the hand-made S_skin_filled.step).

The input STEP is only READ. The geometry (face removal, caps, sewing, gates) runs in a subprocess of the server python (OCP): mouse_groove_fill_worker.py.
Conventions: +z is up (the skin faces up); the size thresholds min_groove_length_mm (default 17 % of the longest bbox side) and min_patch_area_mm2 (default 4 % of the
plan bbox area) are derived from the shell bbox unless given; the LH2 values (20 mm, 300 mm2) are verification arguments only.
Output once under mouse/cad/<id>/ (never overwritten; the same inputs return the stored report): filled_skin.step + groove_fill_report.json.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .scan_cad_common import check_file, check_range, run_job, server_python
from .. import __version__
from ..errors import BrainError

GROOVE_FILL_VERSION = 'GF1.2'
STEP_SUFFIXES = ('.step', '.stp')
HERE = Path(__file__).parent
GROOVE_FILL_REPORT = 'groove_fill_report.json'


def _part(v: Any, what: str, code: str) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str) or not v.strip() or len(v) > 200:
        raise BrainError(code, f'{what} must be a non-empty part name.', {'given': v})
    return v


def groove_fill(workspace: Path, shell_step_path: str, part: str | None = None, groove_faces: list[int] | None = None, max_floor_width_mm: float = 1.2,
                floor_min_nz: float = 0.8, wall_max_abs_nz: float = 0.2, min_groove_length_mm: float | None = None, min_patch_area_mm2: float | None = None,
                sew_tol_mm: float = 0.02, planar_tol_mm: float = 0.02, mesh_deflection_mm: float = 0.003) -> dict[str, Any]:
    workspace, code = Path(workspace), 'GROOVE_FILL'
    for n, v, lo, hi in (('max_floor_width_mm', max_floor_width_mm, 0.05, 20.0), ('floor_min_nz', floor_min_nz, 0.0, 1.0), ('wall_max_abs_nz', wall_max_abs_nz, 0.0, 1.0),
                         ('sew_tol_mm', sew_tol_mm, 1e-5, 0.5), ('planar_tol_mm', planar_tol_mm, 1e-5, 0.5), ('mesh_deflection_mm', mesh_deflection_mm, 0.0005, 0.5)):
        check_range(n, v, lo, hi, f'{code}_SETTINGS')
    for n, v, lo, hi in (('min_groove_length_mm', min_groove_length_mm, 0.0, 1000.0), ('min_patch_area_mm2', min_patch_area_mm2, 0.0, 1e6)):
        if v is not None:
            check_range(n, v, lo, hi, f'{code}_SETTINGS')
    if groove_faces is not None:
        if not isinstance(groove_faces, list) or not 1 <= len(groove_faces) <= 64 or not all(isinstance(i, int) and not isinstance(i, bool) and i >= 0 for i in groove_faces):
            raise BrainError(f'{code}_SETTINGS', 'groove_faces must list 1-64 face indices (explorer order of the shell solid), or be omitted to detect the groove.',
                             {'given': groove_faces})
    shell = check_file(workspace, shell_step_path, STEP_SUFFIXES, f'{code}_FILE', 'shell_step_path')
    settings = {'part': _part(part, 'part', f'{code}_SETTINGS'), 'groove_faces': sorted(set(groove_faces)) if groove_faces is not None else None,
                'max_floor_width_mm': float(max_floor_width_mm), 'floor_min_nz': float(floor_min_nz), 'wall_max_abs_nz': float(wall_max_abs_nz),
                'min_groove_length_mm': None if min_groove_length_mm is None else float(min_groove_length_mm),
                'min_patch_area_mm2': None if min_patch_area_mm2 is None else float(min_patch_area_mm2), 'sew_tol_mm': float(sew_tol_mm),
                'planar_tol_mm': float(planar_tol_mm), 'mesh_deflection_mm': float(mesh_deflection_mm)}

    def build_report(res, final, job_id, hashes):
        return {'schema': 'mouse_groove_fill_report/1', 'status': 'READY', 'groove_fill_id': job_id, 'version': GROOVE_FILL_VERSION, 'server_version': __version__,
                'inputs': {'shell_step_path': shell_step_path}, 'input_hashes': hashes, 'settings': settings, 'part': res['part'], 'detection': res['detection'],
                'removed_faces': res['removed_faces'], 'mesh_repairs': res.get('mesh_repairs', []), 'skin_face': res['skin_face'], 'hole_loops_edges': res['loops'], 'caps': res['caps'],
                'evidence': {'free_edges': res['free_edges'], 'multiple_edges': res['multiple_edges'], 'sewing_free_edges': res['sewing_free_edges'],
                             'sew_tol_mm': settings['sew_tol_mm'], 'valid': res['valid'], 'faces_before': res['faces_before'], 'faces_after': res['faces_after'],
                             'removed_area_mm2': res['removed_area_mm2'], 'volume_before_mm3': res['volume_before_mm3'], 'volume_after_mm3': res['volume_after_mm3'],
                             'volume_added_mm3': res['volume_added_mm3'], 'max_tolerance_mm': res['max_tolerance_mm'],
                             'chord_deviation_mm': res['chord_deviation_mm'], 'step_round_trip': res['round_trip']},
                'outputs': {k: {'file': v} for k, v in res['files'].items()}, 'seconds': res.get('seconds'),
                'limits': ['Volumes are closed-mesh volumes (deflection mesh_deflection_mm); BRepGProp volumes of these B-spline solids differ by up to ~100 mm3.',
                           'The cap on the skin is bounded by the original skin edges and one straight chord per non-skin run (end of the groove, slot end); the '
                           'chord is a 3D line (edge tolerance = its distance to the surface, reported as chord_deviation_mm).',
                           'A closed groove ring (annulus) or a hole boundary that is neither on the skin, on one surface nor planar is refused '
                           '(GROOVE_FILL_UNSUPPORTED), never filled partially.']}

    return run_job(workspace=workspace, area='cad', prefix='gf_', version=GROOVE_FILL_VERSION, code=code, inputs={'shell': shell}, settings=settings,
                   worker=HERE / 'mouse_groove_fill_worker.py', python=server_python(), report_name=GROOVE_FILL_REPORT, build_report=build_report, timeout_s=1800)


__all__ = ['groove_fill', 'GROOVE_FILL_VERSION', 'GROOVE_FILL_REPORT']
