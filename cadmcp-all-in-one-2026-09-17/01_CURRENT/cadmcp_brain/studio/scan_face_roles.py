"""Face roles of a mouse top shell and bottom plate by geometry (brain_mouse_face_roles).

Inputs are STEP files inside the workspace (shell = one solid, optional plate = one solid) and an optional hint mesh (STL + {name: [triangle
ids]} labels, same frame). The B-rep work runs in the server python as a subprocess (scan_face_roles_worker.py, OCP, extra `geometry`).
Outputs (face_roles.json, assembly_colored.step, face_roles_report.json) go once under mouse/cad/<fr_id>/ and are never overwritten; the
same inputs return the stored report. Labels are hints only: the geometry decides and disagreements are warnings.
"""
from __future__ import annotations
import math
from pathlib import Path
from typing import Any
from .scan_cad_common import check_file, check_range, run_job, server_python
from .scan_face_roles_worker import COLORS, DEFAULTS
from .. import __version__
from ..errors import BrainError
from ..req2cad.common import json_load

FR_VERSION = 'FR1.0'
WORKER = Path(__file__).with_name('scan_face_roles_worker.py')
REPORT = 'face_roles_report.json'
TIMEOUT_S = 900
STEP_SUFFIXES = ('.step', '.stp')
_RANGES = {'slot_max_mm': (0.05, 10.0), 'window_max_mm': (0.5, 200.0), 'panel_min_groove_fraction': (0.1, 1.0), 'crisp_edge_deg': (1.0, 89.0),
           'hint_max_dist_mm': (0.01, 20.0)}
NOTE = ('Face index = TopExp_Explorer order of the given STEP; Fusion (or any other CAD) may number faces differently: match faces by '
        'point / bbox in face_roles.json. Labels are hints; the geometry decides.')


def _colors(colors: dict[str, Any] | None) -> dict[str, list[float]]:
    out = {k: list(v) for k, v in COLORS.items()}
    if colors is None:
        return out
    if not isinstance(colors, dict):
        raise BrainError('FACE_ROLES_SETTINGS', 'colors must be an object {panel|sidebutton|plate|rest: [r, g, b]}.')
    for k, v in colors.items():
        if k not in COLORS:
            raise BrainError('FACE_ROLES_SETTINGS', 'Unknown colour key.', {'key': k, 'allowed': sorted(COLORS)})
        if (not isinstance(v, (list, tuple)) or len(v) != 3
                or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not 0 <= x <= 1 for x in v)):
            raise BrainError('FACE_ROLES_SETTINGS', 'A colour must be three sRGB components in [0, 1].', {'key': k, 'given': v})
        out[k] = [float(x) for x in v]
    return out


def face_roles(workspace: Path, shell_step_path: str, plate_step_path: str | None = None, hint_mesh_path: str | None = None,
               hint_labels_path: str | None = None, slot_max_mm: float = DEFAULTS['slot_max_mm'], window_max_mm: float = DEFAULTS['window_max_mm'],
               panel_min_groove_fraction: float = DEFAULTS['panel_min_groove_fraction'], crisp_edge_deg: float = DEFAULTS['crisp_edge_deg'],
               hint_max_dist_mm: float = DEFAULTS['hint_max_dist_mm'], colors: dict[str, Any] | None = None) -> dict[str, Any]:
    workspace = Path(workspace)
    vals = {'slot_max_mm': slot_max_mm, 'window_max_mm': window_max_mm, 'panel_min_groove_fraction': panel_min_groove_fraction,
            'crisp_edge_deg': crisp_edge_deg, 'hint_max_dist_mm': hint_max_dist_mm}
    for k, (lo, hi) in _RANGES.items():
        check_range(k, vals[k], lo, hi, 'FACE_ROLES_SETTINGS')
    if window_max_mm <= slot_max_mm:
        raise BrainError('FACE_ROLES_SETTINGS', 'window_max_mm must be larger than slot_max_mm.', {'slot_max_mm': slot_max_mm, 'window_max_mm': window_max_mm})
    cols = _colors(colors)
    if hint_mesh_path is not None and hint_mesh_path.lower().endswith('.json') and hint_labels_path is None:
        # a report path (e.g. brain_mouse_scan_flush): its mesh + labels outputs are the hint pair
        rep = json_load(check_file(workspace, hint_mesh_path, ('.json',), 'FACE_ROLES_HINTS', 'hint_mesh_path (report)'))
        outs = rep.get('outputs') or {} if isinstance(rep, dict) else {}
        mesh_rel = next((v.get('relative_path') for k, v in outs.items() if isinstance(v, dict) and str(v.get('relative_path', '')).lower().endswith('.stl')), None)
        lab_rel = (outs.get('labels') or {}).get('relative_path') if isinstance(outs.get('labels'), dict) else None
        if not mesh_rel or not lab_rel:
            raise BrainError('FACE_ROLES_HINTS', 'The hint report lists no STL mesh + labels outputs.', {'given': hint_mesh_path})
        hint_mesh_path, hint_labels_path = mesh_rel, lab_rel
    if hint_mesh_path is not None and hint_labels_path is None:
        mp_ = hint_mesh_path.replace(chr(92), '/')
        pair = mp_.rsplit('/', 1)[0] + '/labels.npz' if '/' in mp_ else 'labels.npz'
        if (Path(workspace) / pair).is_file():
            hint_labels_path = pair
    if (hint_mesh_path is None) != (hint_labels_path is None):
        raise BrainError('FACE_ROLES_HINTS', 'Give hint_mesh_path and hint_labels_path together (or neither); labels.npz next to the mesh or a '
                                             'report path (e.g. the brain_mouse_scan_flush report) is paired automatically.')
    shell = check_file(workspace, shell_step_path, STEP_SUFFIXES, 'FACE_ROLES_FILE', 'shell_step_path')
    plate = check_file(workspace, plate_step_path, STEP_SUFFIXES, 'FACE_ROLES_FILE', 'plate_step_path') if plate_step_path is not None else None
    hmesh = check_file(workspace, hint_mesh_path, ('.stl',), 'FACE_ROLES_HINTS', 'hint_mesh_path') if hint_mesh_path is not None else None
    hlab = check_file(workspace, hint_labels_path, ('.json', '.npz'), 'FACE_ROLES_HINTS', 'hint_labels_path') if hint_labels_path is not None else None
    settings = {**DEFAULTS, **vals, 'colors': cols}
    rel = {'shell_step_path': shell_step_path, 'plate_step_path': plate_step_path, 'hint_mesh_path': hint_mesh_path, 'hint_labels_path': hint_labels_path}

    def build_report(res: dict[str, Any], final: Path, job_id: str, hashes: dict[str, str | None]) -> dict[str, Any]:
        checks = res['checks']
        status = 'READY' if not any(v == 'FAIL' for v in checks.values()) else 'REVIEW'
        return {'status': status, 'face_roles_id': job_id, 'version': FR_VERSION, 'server_version': __version__, 'inputs': rel, 'input_hashes': hashes,
                'settings': settings, 'counts': res['counts'], 'faces': res['faces'], 'panels': res['panels'], 'window_loops': res['window_loops'],
                'sidebuttons': res['sidebuttons'], 'colour_counts': res['colour_counts'], 'hints_used': res['hints_used'], 'warnings': res['warnings'],
                'checks': checks, 'note': NOTE, 'seconds': res.get('seconds'),
                'outputs': {'face_roles': {'file': 'face_roles.json'}, 'colored_step': {'file': 'assembly_colored.step'}},
                'limits': ['Roles come from rays, adjacency and dihedral angles of the B-rep; a groove wider than slot_max_mm reads as a window, a pocket '
                           'wider than window_max_mm is not seen by rays (only its floor-adjacent walls are).',
                           'Side buttons are recognised as protruding pads (crisp edges, descending walls); flush or recessed buttons stay shell.',
                           'Fusion face indices may differ from the STEP order; match by point / bbox.']}

    return run_job(workspace=workspace, area='cad', prefix='fr_', version=FR_VERSION, code='FACE_ROLES',
                   inputs={'shell': shell, 'plate': plate, 'hint_mesh': hmesh, 'hint_labels': hlab}, settings=settings, worker=WORKER,
                   python=server_python(), report_name=REPORT, build_report=build_report, timeout_s=TIMEOUT_S)


__all__ = ['face_roles', 'REPORT', 'FR_VERSION']
