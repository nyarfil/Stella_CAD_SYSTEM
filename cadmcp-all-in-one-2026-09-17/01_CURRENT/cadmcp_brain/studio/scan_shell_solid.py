"""Closed top-shell solid from a shell_fit skin + scan front (brain_mouse_shell_solid).

Takes the READY half + mirror skin of brain_mouse_shell_fit (rear part, cut by one front plane), measures the crease line (side panel / front lip)
from the scan, builds a fair front tube (flanks + plain front wall, exact G0 / G1 to the skin) and a cap (G1 to the skin, crisp C0 lip edge),
and closes everything with the parting surface (z-const plane when the seam is flat, else the fitted seam height field). SS1.2 defaults:
seam points on the flank of a wall bulge move onto the crest (seam_to_crest, window 1.0 mm, prominence 0.08 mm, both sides within
0.75 mm, shifts averaged over 4 mm along the seam) and the seam height field uses smoothing 1e-2 (was 1e-3; the interior sagged). Runs
scan_shell_solid_worker.py in the server python (OCP); outputs once under mouse/cad/<ss_id>/.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from .scan_cad_common import check_file, check_range, layout_from, run_job, server_python
from .. import __version__
from ..errors import BrainError

SOLID_VERSION = 'SS1.11'
WORKER = Path(__file__).with_name('scan_shell_solid_worker.py')
REPORT = 'shell_solid_report.json'
CODE = 'SHELL_SOLID'


def _names(val: Any, what: str) -> list[str] | None:
    if val is None:
        return None
    if not isinstance(val, list) or not val or not all(isinstance(x, str) and 0 < len(x) <= 64 for x in val):
        raise BrainError('SHELL_SOLID_SETTINGS', f'{what} must be a non-empty list of region names.', {'given': val})
    return list(val)


def _json(path: Path, code: str) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise BrainError(code, 'The file is not readable JSON.', {'file': path.name}) from exc
    if not isinstance(obj, dict):
        raise BrainError(code, 'The file must hold a JSON object.', {'file': path.name})
    return obj


def resolve_layout(workspace: Path, layout_path: str | None) -> tuple[Path | None, str | None]:
    """slot_layout.json (click_slot_layout/1) or a brain_mouse_scan_click_grooves report -> layout file."""
    if not layout_path:
        return None, None
    return layout_from(workspace, layout_path, 'SHELL_SOLID_LAYOUT')


def shell_solid(workspace: Path, shell_fit_report_path: str, layout_path: str | None = None, labels_path: str | None = None,
                shell_regions: list[str] | None = None, plate_regions: list[str] | None = None, exclude_regions: list[str] | None = None,
                parting_mode: str = 'auto', parting_z_mm: float | None = None, flat_tolerance_mm: float = 0.3, plain_front: bool = True,
                lip_band_mm: float = 4.2, front_stiffness: float = 20.0, trim_inward_mm: float = 0.4, min_face_area_mm2: float = 0.5,
                tol_p95_mm: float = 0.3) -> dict[str, Any]:
    if parting_mode not in ('auto', 'seam', 'plane'):
        raise BrainError('SHELL_SOLID_SETTINGS', "parting_mode must be 'auto', 'seam' or 'plane'.", {'given': parting_mode})
    if parting_z_mm is not None:
        check_range('parting_z_mm', parting_z_mm, -500.0, 500.0, 'SHELL_SOLID_SETTINGS')
    check_range('flat_tolerance_mm', flat_tolerance_mm, 0.0, 20.0, 'SHELL_SOLID_SETTINGS')
    check_range('lip_band_mm', lip_band_mm, 0.0, 20.0, 'SHELL_SOLID_SETTINGS')
    check_range('front_stiffness', front_stiffness, 1.0, 1000.0, 'SHELL_SOLID_SETTINGS')
    check_range('trim_inward_mm', trim_inward_mm, 0.0, 5.0, 'SHELL_SOLID_SETTINGS')
    check_range('min_face_area_mm2', min_face_area_mm2, 0.0, 100.0, 'SHELL_SOLID_SETTINGS')
    check_range('tol_p95_mm', tol_p95_mm, 0.001, 5.0, 'SHELL_SOLID_SETTINGS')
    if not isinstance(plain_front, bool):
        raise BrainError('SHELL_SOLID_SETTINGS', 'plain_front must be true or false.', {'given': plain_front})
    rp = check_file(workspace, shell_fit_report_path, ('.json',), 'SHELL_SOLID_SKIN', 'shell_fit_report_path')
    sfr = _json(rp, 'SHELL_SOLID_SKIN')
    if sfr.get('schema') != 'shell_fit_report/1':
        raise BrainError('SHELL_SOLID_SKIN', 'shell_fit_report_path must be a brain_mouse_shell_fit report.', {'schema': sfr.get('schema')})
    if sfr.get('mode_used') != 'half':
        raise BrainError('SHELL_SOLID_NEEDS_HALF', 'The skin is one full face (asymmetric domain); this version closes half + mirror skins only.')
    src = sfr.get('source') or {}
    srf_rel = ((sfr.get('outputs') or {}).get('surface') or {}).get('relative_path')
    surf = check_file(workspace, srf_rel, ('.json',), 'SHELL_SOLID_SKIN', 'surface (from the shell_fit report)')
    mesh = check_file(workspace, src.get('relative_path'), ('.stl',), 'SHELL_SOLID_SKIN', 'mesh (from the shell_fit report)')
    lab_rel = labels_path or src.get('labels_relative_path')
    if not lab_rel:
        raise BrainError('SHELL_SOLID_LABELS', 'labels are needed (shell / plate regions): the shell_fit run had none; give labels_path.')
    lab = check_file(workspace, lab_rel, ('.json', '.npz'), 'SHELL_SOLID_LABELS', 'labels_path')
    cuts = _json(surf, 'SHELL_SOLID_SKIN').get('cut_planes') or (sfr.get('settings') or {}).get('cut_planes') \
        or ([((sfr.get('front_cut') or {}).get('chosen'))] if (sfr.get('front_cut') or {}).get('chosen') else [])
    if len(cuts) != 1:
        raise BrainError('SHELL_SOLID_NO_CUT' if not cuts else 'SHELL_SOLID_CUTS',
                         'The shell_fit run must have exactly one front cut plane (front_cut auto, or one cut_planes entry).', {'cut_planes': len(cuts)})
    lay, lay_rel = resolve_layout(workspace, layout_path)
    settings: dict[str, Any] = {'unit_scale': float((sfr.get('settings') or {}).get('unit_scale', 1.0)), 'cut_planes': cuts,
                                'parting_mode': parting_mode, 'parting_z_mm': None if parting_z_mm is None else float(parting_z_mm),
                                'flat_tolerance_mm': float(flat_tolerance_mm), 'plain_front': plain_front, 'lip_band_mm': float(lip_band_mm),
                                'front_stiffness': float(front_stiffness), 'trim_inward_mm': float(trim_inward_mm)}
    for key, val in (('shell_regions', shell_regions), ('plate_regions', plate_regions), ('exclude_regions', exclude_regions)):
        nm = _names(val, key)
        if nm is not None:
            settings[key] = nm

    def build(res: dict[str, Any], folder: Path, job_id: str, hashes: dict[str, str | None]) -> dict[str, Any]:
        br, dev, log = res['brep'], res['deviation'], res['log']
        checks = {'skin_ready': 'PASS' if sfr.get('status') == 'READY' else 'FAIL',
                  'brep_valid': 'PASS' if br['valid'] else 'FAIL',
                  'one_closed_solid': 'PASS' if br['solids'] == 1 and (br['volume_mm3'] or 0) > 0 else 'FAIL',
                  'no_slivers': 'PASS' if (br['min_face_area_mm2'] or 0) >= min_face_area_mm2 else 'FAIL',
                  'step_reimport': 'PASS' if br['valid'] and br['solids'] == 1 and br['tessellates'] else 'FAIL',
                  'sewing': 'PASS' if log['sewing']['multiple_edges'] == 0 else 'FAIL',
                  'deviation_p95': 'PASS' if (dev['all']['p95'] or 0) <= tol_p95_mm else 'FAIL'}
        blockers = [k.upper() for k, v in checks.items() if v == 'FAIL']
        files = res['files']
        return {
            'schema': 'shell_solid_report/1', 'solid_id': job_id, 'status': 'NOT_READY' if blockers else 'READY', 'blocking_reasons': blockers,
            'warnings': res['warnings'], 'code_version': {'shell_solid': SOLID_VERSION, 'worker': res['worker'], 'package': __version__},
            'source': {'shell_fit_report_relative_path': shell_fit_report_path, 'shell_fit_report_sha256': hashes['shell_fit_report'],
                       'shell_fit_id': sfr.get('fit_id'), 'mesh_relative_path': src.get('relative_path'), 'labels_relative_path': lab_rel,
                       'layout_relative_path': lay_rel, 'layout_sha256': hashes['layout']},
            'settings': settings, 'units': {'output': 'mm'}, 'parting': log.get('parting'), 'front': res['front'], 'frame': res['frame'],
            'construction': {k: log[k] for k in ('skin', 'plan', 'exterior_front', 'gamma', 'tube', 'cap_trim', 'cap', 'cap_heightfield', 'sewing') if k in log},
            'brep': br, 'deviation': dev, 'checks': checks, 'timing': res['timing'],
            'outputs': {'solid': {'file': files['step'], 'faces': br['faces'], 'volume_mm3': br['volume_mm3']},
                        'construction': {'file': files['construction']}},
            'downstream': {'note': 'top_shell_solid.step is the closed top shell without slots: next brain_mouse_click_slots (shell_step_path = this '
                                   'solid, layout_path = the click_grooves report), brain_mouse_plate_side and brain_mouse_face_roles.'},
            'limits': ['Half + mirror skins with exactly one front cut only.',
                       'The front wall is plain on purpose: cable hole, lip groove and slot grooves are not followed (the deviation there is expected).',
                       'parting_mode auto uses a z-const plane only when the shell / plate seam is flat within flat_tolerance_mm; a sloped seam '
                       '(e.g. high at the rear) becomes the fitted seam height field; seam points below / above a wall bulge are moved onto its crest '
                       '(report parting.seam_to_crest).',
                       'Side buttons, wheel window and click slots are not cut here.'],
        }

    return run_job(workspace=workspace, area='cad', prefix='ss_', version=SOLID_VERSION, code=CODE,
                   inputs={'shell_fit_report': rp, 'surface': surf, 'mesh': mesh, 'labels': lab, 'layout': lay},
                   settings=settings, worker=WORKER, python=server_python(), report_name=REPORT, build_report=build, timeout_s=2400)


__all__ = ['shell_solid', 'resolve_layout', 'SOLID_VERSION']
