"""Click-panel slots and wheel window cut into a closed shell solid (brain_mouse_click_slots).

Plan layout from slot_layout.json (brain_mouse_scan_click_grooves) or a hand-written click_slot_layout/1; widths, depth and window size are
spec parameters. Floors follow the local B-rep surface minus the depth (smoothed); walls vertical; crisp edges. An optional mirror plane
symmetrises the layout only where it passes the coarse test (never forced). Runs scan_click_slots_worker.py in the server python (OCP);
outputs once under mouse/cad/<cs_id>/; the input STEP is never modified.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .scan_cad_common import check_file, check_range, layout_from, mirror_from_report, run_job, server_python
from .. import __version__
from ..errors import BrainError

SLOTS_VERSION = 'CS1.9'
WORKER = Path(__file__).with_name('scan_click_slots_worker.py')
REPORT = 'click_slots_report.json'
CODE = 'CLICK_SLOTS'


def click_slots(workspace: Path, shell_step_path: str, layout_path: str, slot_width_mm: float | None = None, gap_width_mm: float | None = None,
                depth_mm: float = 2.0, window_depth_mm: float | None = None, window_length_mm: float | None = None, window_width_mm: float | None = None,
                window_radius_mm: float | None = None, mirror_plane: dict[str, Any] | None = None, abs_threshold_mm: float = 2.0, rel_threshold: float = 0.015,
                cut_perimeter: bool = True, cut_gap: bool = True, cut_window: bool = True, smooth_mm: float = 1.5,
                symmetry_report_path: str | None = None, through_wall: bool = False, lip_height_mm: float | None = None) -> dict[str, Any]:
    for name, val, lo, hi in (('slot_width_mm', slot_width_mm, 0.1, 10.0), ('gap_width_mm', gap_width_mm, 0.1, 20.0), ('window_depth_mm', window_depth_mm, 0.1, 20.0),
                              ('window_length_mm', window_length_mm, 1.0, 120.0), ('window_width_mm', window_width_mm, 1.0, 60.0),
                              ('window_radius_mm', window_radius_mm, 0.0, 30.0)):
        if val is not None:
            check_range(name, val, lo, hi, 'CLICK_SLOTS_SETTINGS')
    check_range('depth_mm', depth_mm, 0.1, 20.0, 'CLICK_SLOTS_SETTINGS')
    check_range('abs_threshold_mm', abs_threshold_mm, 0.0, 20.0, 'CLICK_SLOTS_SETTINGS')
    check_range('rel_threshold', rel_threshold, 0.0, 0.2, 'CLICK_SLOTS_SETTINGS')
    check_range('smooth_mm', smooth_mm, 0.0, 20.0, 'CLICK_SLOTS_SETTINGS')
    for name, val in (('cut_perimeter', cut_perimeter), ('cut_gap', cut_gap), ('cut_window', cut_window), ('through_wall', through_wall)):
        if not isinstance(val, bool):
            raise BrainError('CLICK_SLOTS_SETTINGS', f'{name} must be true or false.', {'given': val})
    if not (cut_perimeter or cut_gap or cut_window):
        raise BrainError('CLICK_SLOTS_SETTINGS', 'At least one of cut_perimeter, cut_gap, cut_window must be true.')
    if lip_height_mm is not None:
        check_range('lip_height_mm', lip_height_mm, 0.1, 200.0, 'CLICK_SLOTS_SETTINGS')
        if not through_wall:
            raise BrainError('CLICK_SLOTS_SETTINGS', 'lip_height_mm (front lip line) needs through_wall=true.', {'given': lip_height_mm})
    mp = None
    if mirror_plane is not None:
        ok = isinstance(mirror_plane, dict) and isinstance(mirror_plane.get('normal'), list) and len(mirror_plane['normal']) == 3 \
            and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in mirror_plane['normal']) \
            and isinstance(mirror_plane.get('d'), (int, float)) and not isinstance(mirror_plane.get('d'), bool) \
            and sum(float(x) ** 2 for x in mirror_plane['normal']) > 1e-12
        if not ok:
            raise BrainError('CLICK_SLOTS_SETTINGS', 'mirror_plane must be {"normal": [nx, ny, nz], "d": d} (plane normal . x = d, mm).', {'given': mirror_plane})
        mp = {'normal': [float(x) for x in mirror_plane['normal']], 'd': float(mirror_plane['d'])}
    if symmetry_report_path is not None:
        if mp is not None:
            raise BrainError('CLICK_SLOTS_SETTINGS', 'Give either symmetry_report_path or mirror_plane, not both.')
        mp = mirror_from_report(workspace, symmetry_report_path, 'CLICK_SLOTS_SETTINGS')
    shell = check_file(workspace, shell_step_path, ('.step', '.stp'), 'CLICK_SLOTS_SHELL', 'shell_step_path')
    lay, layout_rel = layout_from(workspace, layout_path, 'CLICK_SLOTS_LAYOUT')
    settings = {'slot_width_mm': slot_width_mm, 'gap_width_mm': gap_width_mm, 'depth_mm': float(depth_mm), 'window_depth_mm': window_depth_mm,
                'window_length_mm': window_length_mm, 'window_width_mm': window_width_mm, 'window_radius_mm': window_radius_mm, 'mirror_plane': mp,
                'abs_threshold_mm': float(abs_threshold_mm), 'rel_threshold': float(rel_threshold), 'cut_perimeter': cut_perimeter, 'cut_gap': cut_gap,
                'cut_window': cut_window, 'smooth_mm': float(smooth_mm), 'through_wall': through_wall, 'lip_height_mm': None if lip_height_mm is None else float(lip_height_mm)}

    def build(res: dict[str, Any], folder: Path, job_id: str, hashes: dict[str, str | None]) -> dict[str, Any]:
        r, spec, meas = res['result'], res['spec'], res['measured']
        wtol = 0.15
        width_ok = all(m['width_mm_median'] is not None and abs(m['width_mm_median'] - (spec['gap_width_mm'] if k.startswith('centre_gap') else spec['slot_width_mm'])) <= wtol
                       for k, m in meas.items())
        checks = {'brep_valid': 'PASS' if r['valid'] else 'FAIL',
                  'tessellates': 'PASS' if not r.get('unmeshed_faces_after_reimport') else 'FAIL',
                  'one_solid': 'PASS' if r['solids_in_step'] == 1 else 'FAIL',
                  'material_removed': 'PASS' if r['removed_mm3'] > 0 else 'FAIL',
                  'no_loose_pieces': ('PASS' if r['solids_after_cut'] == 1 else 'WARN') if not through_wall else 'NOT_APPLICABLE',
                  'pieces_valid': ('PASS' if r.get('pieces_valid') in (True, None) else 'FAIL') if through_wall else 'NOT_APPLICABLE',
                  'cutters_closed': 'PASS' if all(c['free_edges'] == 0 for c in res['cutters']) else 'FAIL',
                  'slot_width': ('PASS' if width_ok else 'FAIL') if meas else 'NOT_APPLICABLE',
                  'no_slivers': 'FAIL' if r.get('faces_below_0p05mm2', 0) else ('WARN' if r.get('faces_below_1mm2', 0) else 'PASS')}
        q = res.get('quality') or {}
        pr = q.get('perimeter_roughness')
        checks['perimeter_outline_regular'] = 'NOT_APPLICABLE' if not pr else (
            'PASS' if pr['smooth_dev_max_mm'] <= q['roughness_max_dev_mm'] and pr['curvature_sign_changes'] <= q['max_curvature_sign_changes'] else 'FAIL')
        wg = q.get('window_gap')
        checks['window_on_gap_line'] = 'NOT_APPLICABLE' if not wg or not wg.get('on_gap_line') else (
            'PASS' if abs(wg['offset_after_mm']) <= 1e-3 and wg['angle_after_deg'] <= 0.01 else 'FAIL')
        # CS1.9 gate: a perimeter end stopped by the crease rule must leave through the outer edge of the produced shell (uncut stub <= 0.1 mm)
        ce = [e for e in ((res.get('trim') or {}).get('perimeter_lip') or {}).get('ends') or [] if e.get('reason') == 'crease']
        checks['slot_end_not_at_edge'] = 'NOT_APPLICABLE' if not ce or through_wall else (
            'PASS' if all(e.get('stub_mm') is not None and e['stub_mm'] <= 0.1 for e in ce) else 'FAIL')
        blockers = [k.upper() for k, v in checks.items() if v == 'FAIL']
        warnings = list(res['warnings'])
        if checks['no_slivers'] == 'WARN':
            warnings.append(f'{r["faces_below_1mm2"]} small faces (< 1 mm2) in the slotted shell (slot ends near other edges).')
        if checks['no_loose_pieces'] == 'WARN':
            warnings.append(f'The cut left {r["solids_after_cut"]} pieces; only the largest is kept (check the layout).')
        files = res['files']
        if through_wall:
            warnings.append(f'through_wall: the cut left {r["solids_after_cut"]} piece(s); all are written (slotted_shell.step = largest, piece_k.step the others).')
        return {
            'schema': 'click_slots_report/1', 'slots_id': job_id, 'status': 'NOT_READY' if blockers else 'READY', 'blocking_reasons': blockers, 'warnings': warnings,
            'code_version': {'click_slots': SLOTS_VERSION, 'worker': res['worker'], 'package': __version__},
            'source': {'shell_step_path': shell_step_path, 'shell_sha256': hashes['shell'], 'layout_path': layout_path, 'layout_relative_path': layout_rel,
                       'layout_sha256': hashes['layout'], 'symmetry_report_path': symmetry_report_path},
            'settings': settings, 'units': {'input': 'mm', 'output': 'mm'}, 'spec_used': spec, 'symmetry': res['symmetry'], 'trim': res.get('trim'), 'cutters': res['cutters'],
            'window': res['window'], 'measured': meas, 'boolean': res.get('boolean'), 'result': r, 'checks': checks, 'quality': res.get('quality'),
            'outputs': {'slotted_shell': {'file': files['step']}, 'cutters': {'file': files['cutters']}, 'pieces': [{'file': f} for f in (files.get('pieces') or [])]},
            'downstream': {'note': 'Next: brain_mouse_plate_side for the bottom plate, then brain_mouse_face_roles for colours/roles (XCAF STEP).'},
            'limits': ['Floors follow the B-rep top surface along each path (vertical hit), smoothed; a path that leaves the shell is refused.',
                       'Walls are vertical (plan offset), not normal to the surface.',
                       'The input shell STEP is never modified; the slotted shell is a new file.'],
            'seconds': res.get('seconds'),
        }

    return run_job(workspace=workspace, area='cad', prefix='cs_', version=SLOTS_VERSION, code=CODE, inputs={'shell': shell, 'layout': lay},
                   settings=settings, worker=WORKER, python=server_python(), report_name=REPORT, build_report=build, timeout_s=1800)


__all__ = ['click_slots', 'SLOTS_VERSION']
