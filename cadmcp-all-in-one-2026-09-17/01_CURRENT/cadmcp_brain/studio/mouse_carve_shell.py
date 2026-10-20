"""brain_mouse_carve_shell: carve-from-solid hollowing of a filled mouse top-shell solid in one cavity cut (spec section 8,
docs/SCAN_TO_HOLLOW_SHELL_PIPELINE_JA_SPEC.md). Port of the owner-approved LH2 carve v26 build (OFFICIAL v23f -> carve v26, wall / floor 1.2).

Server side: argument validation + scan_cad_common.run_job. The geometry runs in mouse_carve_shell_worker.py (server python: OCP, scipy, vtk,
matplotlib = extra `geometry`). Outputs once under mouse/cad/<cv_id>/ (hollow_shell.step, cavity.step, cavity_fit.npz, carve_report.json;
never overwritten; the same inputs return the stored report).
"""
from __future__ import annotations
import math
from pathlib import Path
from typing import Any
from .scan_cad_common import check_file, check_range, run_job, server_python
from .. import __version__
from ..errors import BrainError

CARVE_VERSION = 'CV1.4'
STEP_SUFFIXES = ('.step', '.stp')
REPORT = 'carve_report.json'
HERE = Path(__file__).parent
MAX_WINDOWS = 12
WINDOW_TYPES = ('wheel', 'side_button', 'other')
ROLE_KEYS = ('wall', 'floor', 'step', 'bearing')


def _num(v: Any) -> bool:
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)


def _vec(v: Any, n: int, what: str, code: str) -> list[float] | None:
    if v is None:
        return None
    if not isinstance(v, (list, tuple)) or len(v) != n or not all(_num(x) for x in v):
        raise BrainError(code, f'{what} must be a list of {n} finite numbers.', {'given': v})
    return [float(x) for x in v]


def _int2(v: Any, lo: int, hi: int, what: str, code: str) -> list[int]:
    if not isinstance(v, (list, tuple)) or len(v) != 2 or not all(isinstance(x, int) and not isinstance(x, bool) and lo <= x <= hi for x in v):
        raise BrainError(code, f'{what} must be [n_u, n_v], integers in [{lo}, {hi}].', {'given': v})
    return [int(x) for x in v]


def carve_shell(workspace: Path, shell_step_path: str, windows: list[dict[str, Any]] | None = None, wall_mm: float = 1.2, floor_mm: float = 1.2,
                step_fillet_mm: float | None = None, face_roles: dict[str, list[int]] | None = None, ray_center: list[float] | None = None,
                ray_axes: list[float] | None = None, grid: list[int] | None = None, poles: list[int] | None = None, smoothing: float = 1e-7,
                floor_poles: int = 121, floor_smoothing: float = 1e-6, floor_edge_exclude_mm: float = 2.0, floor_domain: list[float] | None = None,
                floor_fill_lift_mm: float = 0.3, envelope_tol_mm: float = 0.1, face_samples: int = 700, wall_face_min_area_mm2: float | None = None,
                outline_kink_deg: float = 20.0, outline_kink_mm: float = 1.6, slot_band_mm: float = 1.0, compact_step: bool = True,
                reference_step_path: str | None = None, reference_part: str | None = None,
                offset_source_step_path: str | None = None, pocket_margin_mm: float | None = None,
                mirror_y: float | None = None, wall_face_min_area_frac: float = 0.05, face_roles_path: str | None = None,
                split_report_path: str | None = None) -> dict[str, Any]:
    workspace, code = Path(workspace), 'CARVE'
    sc = f'{code}_SETTINGS'
    for n, v, lo, hi in (('wall_mm', wall_mm, 0.2, 10.0), ('floor_mm', floor_mm, 0.2, 10.0), ('smoothing', smoothing, 0.0, 1.0),
                         ('floor_smoothing', floor_smoothing, 0.0, 1.0), ('floor_edge_exclude_mm', floor_edge_exclude_mm, 0.0, 20.0),
                         ('floor_fill_lift_mm', floor_fill_lift_mm, 0.0, 5.0), ('envelope_tol_mm', envelope_tol_mm, 0.0, 5.0),
                         ('wall_face_min_area_frac', wall_face_min_area_frac, 0.0, 1.0), ('outline_kink_deg', outline_kink_deg, 1.0, 179.0),
                         ('outline_kink_mm', outline_kink_mm, 0.0, 20.0), ('slot_band_mm', slot_band_mm, 0.0, 20.0)):
        check_range(n, v, lo, hi, sc)
    for n, v, lo, hi in (('step_fillet_mm', step_fillet_mm, 0.0, 10.0), ('wall_face_min_area_mm2', wall_face_min_area_mm2, 0.0, 1e7),
                         ('pocket_margin_mm', pocket_margin_mm, 0.0, 20.0), ('mirror_y', mirror_y, -1e4, 1e4)):
        if v is not None:
            check_range(n, v, lo, hi, sc)
    for n, v, lo, hi in (('floor_poles', floor_poles, 8, 400), ('face_samples', face_samples, 20, 2000)):
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise BrainError(sc, f'{n} must be an integer in [{lo}, {hi}].', {'given': v})
    if not isinstance(compact_step, bool):
        raise BrainError(sc, 'compact_step must be true or false.', {'given': compact_step})
    grid_ = _int2(grid if grid is not None else [481, 361], 21, 2001, 'grid', sc)
    poles_ = _int2(poles if poles is not None else [161, 121], 8, 600, 'poles', sc)
    if poles_[0] > grid_[0] or poles_[1] > grid_[1]:
        raise BrainError(sc, 'poles must not exceed grid in either direction.', {'grid': grid_, 'poles': poles_})
    rc = _vec(ray_center, 3, 'ray_center', sc)
    ra = _vec(ray_axes, 3, 'ray_axes', sc)
    if ra is not None and min(ra) <= 0:
        raise BrainError(sc, 'ray_axes must be positive.', {'given': ra})
    fd = _vec(floor_domain, 4, 'floor_domain', sc)
    if fd is not None and (fd[0] >= fd[1] or fd[2] >= fd[3]):
        raise BrainError(sc, 'floor_domain is [x_min, x_max, y_min, y_max] with min < max.', {'given': fd})
    roles = None
    if face_roles is not None:
        if not isinstance(face_roles, dict) or set(face_roles) - set(ROLE_KEYS) or not all(
                isinstance(v, list) and v and all(isinstance(i, int) and not isinstance(i, bool) and i >= 0 for i in v) for v in face_roles.values()):
            raise BrainError(sc, 'face_roles maps wall / floor / step / bearing to non-empty lists of face indices (0-based, TopExp order).',
                             {'given': face_roles})
        roles = {k: [int(i) for i in v] for k, v in face_roles.items()}
    inputs: dict[str, Path | None] = {'shell': check_file(workspace, shell_step_path, STEP_SUFFIXES, f'{code}_FILE', 'shell_step_path')}
    wins = []
    if windows is not None:
        if not isinstance(windows, list) or len(windows) > MAX_WINDOWS:
            raise BrainError(sc, f'windows must be a list of at most {MAX_WINDOWS} {{"step", "type", "sill"?}}.', {'given': type(windows).__name__})
        for i, w in enumerate(windows):
            if not isinstance(w, dict) or set(w) - {'step', 'type', 'sill', 'label'} or w.get('type', 'other') not in WINDOW_TYPES:
                raise BrainError(sc, 'Each window is {"step": path, "type": "wheel"|"side_button"|"other", "sill"?: {"drop_mm", "depth_mm", '
                                     '"margin_mm"?}, "label"?}.', {'index': i, 'given': w})
            inputs[f'window_{i}'] = check_file(workspace, w.get('step'), STEP_SUFFIXES, f'{code}_FILE', f'windows[{i}].step')
            q: dict[str, Any] = {'type': w.get('type', 'other')}
            if 'label' in w:
                if not isinstance(w['label'], str) or not w['label'].strip() or len(w['label']) > 80:
                    raise BrainError(sc, 'window label must be a short non-empty string.', {'index': i})
                q['label'] = w['label']
            if w.get('sill') is not None:
                s = w['sill']
                if not isinstance(s, dict) or set(s) - {'drop_mm', 'depth_mm', 'margin_mm'} or not {'drop_mm', 'depth_mm'} <= set(s):
                    raise BrainError(sc, 'sill is {"drop_mm", "depth_mm", "margin_mm"?} (v26 window B: 4.0, 9.0, 0.3).', {'index': i, 'given': s})
                check_range(f'windows[{i}].sill.drop_mm', s['drop_mm'], 0.0, 50.0, sc)
                check_range(f'windows[{i}].sill.depth_mm', s['depth_mm'], 0.01, 200.0, sc)
                check_range(f'windows[{i}].sill.margin_mm', s.get('margin_mm', 0.3), 0.0, 10.0, sc)
                q['sill'] = {'drop_mm': float(s['drop_mm']), 'depth_mm': float(s['depth_mm']), 'margin_mm': float(s.get('margin_mm', 0.3))}
            wins.append(q)
    # earlier tool outputs next to the shell (e.g. face_roles.json of the same folder) are used when not given; the worker checks the face count
    sib = inputs['shell'].parent
    ws = workspace.resolve()
    for fname, cur in (('face_roles.json', face_roles_path), ('carve_handoff.json', split_report_path), ('split_click_report.json', split_report_path)):
        cand = sib / fname
        if cur is None and (fname == 'face_roles.json' or split_report_path is None) and cand.is_file() and not cand.is_symlink() and cand.resolve().is_relative_to(ws):
            rel = cand.resolve().relative_to(ws).as_posix()
            if fname == 'face_roles.json':
                face_roles_path = rel
            else:
                split_report_path = rel
                cur = rel
    if face_roles_path is not None:
        inputs['face_roles_json'] = check_file(workspace, face_roles_path, ('.json',), f'{code}_FILE', 'face_roles_path')
    if split_report_path is not None:
        inputs['split_report'] = check_file(workspace, split_report_path, ('.json',), f'{code}_FILE', 'split_report_path')
    if offset_source_step_path is not None:
        inputs['offset_source'] = check_file(workspace, offset_source_step_path, STEP_SUFFIXES, f'{code}_FILE', 'offset_source_step_path')
    if reference_step_path is not None:
        inputs['reference'] = check_file(workspace, reference_step_path, STEP_SUFFIXES, f'{code}_FILE', 'reference_step_path')
    if reference_part is not None and (not isinstance(reference_part, str) or not reference_part.strip() or len(reference_part) > 200):
        raise BrainError(sc, 'reference_part must be a part name.', {'given': reference_part})
    settings = {'wall_mm': float(wall_mm), 'floor_mm': float(floor_mm), 'step_fillet_mm': None if step_fillet_mm is None else float(step_fillet_mm),
                'face_roles': roles, 'ray_center': rc, 'ray_axes': ra, 'grid': grid_, 'poles': poles_, 'smoothing': float(smoothing),
                'floor_poles': floor_poles, 'floor_smoothing': float(floor_smoothing), 'floor_edge_exclude_mm': float(floor_edge_exclude_mm),
                'floor_domain': fd, 'floor_fill_lift_mm': float(floor_fill_lift_mm), 'envelope_tol_mm': float(envelope_tol_mm), 'face_samples': face_samples,
                'wall_face_min_area_mm2': None if wall_face_min_area_mm2 is None else float(wall_face_min_area_mm2),
                'wall_face_min_area_frac': float(wall_face_min_area_frac),
                'pocket_margin_mm': None if pocket_margin_mm is None else float(pocket_margin_mm), 'mirror_y': None if mirror_y is None else float(mirror_y), 'outline_kink_deg': float(outline_kink_deg), 'outline_kink_mm': float(outline_kink_mm),
                'slot_band_mm': float(slot_band_mm), 'compact_step': compact_step, 'windows': wins, 'reference_part': reference_part}

    def build_report(res, final, job_id, hashes):
        r = res['report']
        status = {'PASS': 'READY', 'WARN': 'READY_WITH_WARNINGS', 'FAIL': 'NOT_READY'}[r['verdict']]
        return {'schema': 'mouse_carve_shell_report/1', 'status': status, 'carve_id': job_id, 'version': CARVE_VERSION, 'server_version': __version__,
                'inputs': {'shell_step_path': shell_step_path, 'windows': [w.get('step') for w in (windows or [])],
                           'reference_step_path': reference_step_path, 'offset_source_step_path': offset_source_step_path,
                           'face_roles_path': face_roles_path, 'split_report_path': split_report_path},
                'input_hashes': hashes, 'settings': settings, 'settings_used': res['settings_used'], **r,
                'outputs': {k: {'file': v} for k, v in res['files'].items()}, 'seconds': res.get('seconds'),
                'method': 'carve v26 port: G = one LSQ B-spline of the wall offsets (star ray grid); K = outline+wall prism above the floor offset '
                          'sheet (+ window sills); cavity = G - K; shell = S - cavity, then - windows; step fillet R = wall.',
                'limits': ['Click recess optional: with no plate-outline step face (shell not split yet) the wall offset is applied everywhere (cavity = G, report click_recess false, '
                           'floor / slot-band / fillet checks NA). Roles: face_roles > hints (face_roles_path = brain_mouse_face_roles face_roles.json, '
                           'split_report_path = split_click report with a face_roles hand-off) > geometry; hints are optional and ignored when their face count differs.',
                           'Standard frame expected: z up with the bearing face at the bottom, x front, mirror plane y = mirror_y (default: bbox '
                           'centre); either handedness. No part-specific coordinates: ray grid, floor domain, wall-face threshold and pocket '
                           'margin default to values derived from the input (see settings_used).',
                           'The outer skin is the input solid; protected parts (PCB, switches, sensor, wheel) are not inputs: check them with '
                           'brain_mouse_interference_report on hollow_shell.step.',
                           'The floor offset is a height field (z-graph) and the plate outline must be one vertical linear-extrusion step face.',
                           'The cavity surface is star-shaped from ray_center; concave creases follow the inner envelope (thicker, never thinner).',
                           'Thickness = ray along the inward skin normal on the result tessellation (deflection_mm), windows and the bearing band excluded.',
                           'Plate-to-floor gap is not measured here (the floor top is the input recess, unchanged).']}

    return run_job(workspace=workspace, area='cad', prefix='cv_', version=CARVE_VERSION, code=code, inputs=inputs, settings=settings,
                   worker=HERE / 'mouse_carve_shell_worker.py', python=server_python(), report_name=REPORT, build_report=build_report,
                   timeout_s=5400)


__all__ = ['carve_shell', 'CARVE_VERSION', 'REPORT']
