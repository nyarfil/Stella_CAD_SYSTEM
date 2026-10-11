"""Hand flip of a finished mouse: right-hand <-> left-hand by mirroring the WHOLE model (brain_mouse_handedness_flip).

Inputs: the top shell STEP (one solid, normally side_buttons_shell.step), the bottom plate STEP (one solid, floor z = 0), the face_roles.json of
brain_mouse_face_roles for exactly these two files (or its face_roles_report.json), and the mouse mirror plane (a brain_mouse_scan_symmetrise report or
explicit mirror_normal + mirror_d; never a built-in plane). Nothing is re-designed: the model is mirrored about that plane, re-levelled rigidly so the
floor is exactly z = 0, the face roles are carried over (the side buttons end up on the opposite flank) and the colour-coded assembly is rewritten.
The geometry runs in a subprocess of the server python (scan_handedness_flip_worker.py, OCP, numpy). The inputs are only read; outputs go once under
mouse/cad/<hf_id>/ and are never overwritten (the same inputs return the stored report).
"""
from __future__ import annotations
import math
from pathlib import Path
from typing import Any
from .scan_cad_common import check_file, check_range, mirror_from_report, run_job, server_python
from .scan_face_roles import _colors
from .. import __version__
from ..errors import BrainError
from ..req2cad.common import json_load

HF_VERSION = 'HF1.0'
WORKER = Path(__file__).with_name('scan_handedness_flip_worker.py')
REPORT = 'handedness_flip_report.json'
TIMEOUT_S = 900
STEP_SUFFIXES = ('.step', '.stp')
DEFAULTS = {'floor_tol_mm': 1e-3, 'volume_tol_pct': 0.1}
_RANGES = {'floor_tol_mm': (1e-6, 0.1), 'volume_tol_pct': (0.0, 5.0)}


def handedness_flip(workspace: Path, shell_step_path: str, plate_step_path: str, face_roles_path: str, symmetry_report_path: str | None = None,
                    mirror_normal: list[float] | None = None, mirror_d: float | None = None, floor_tol_mm: float = DEFAULTS['floor_tol_mm'],
                    volume_tol_pct: float = DEFAULTS['volume_tol_pct'], front_direction: list[float] | None = None,
                    colors: dict[str, Any] | None = None) -> dict[str, Any]:
    workspace = Path(workspace)
    for name, val in {'floor_tol_mm': floor_tol_mm, 'volume_tol_pct': volume_tol_pct}.items():
        check_range(name, val, *_RANGES[name], 'HANDEDNESS_FLIP_SETTINGS')
    if front_direction is not None and (not isinstance(front_direction, (list, tuple)) or len(front_direction) != 2
                                        or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in front_direction)
                                        or math.hypot(*front_direction) < 1e-9):
        raise BrainError('HANDEDNESS_FLIP_SETTINGS', 'front_direction must be a plan vector [dx, dy] (default +x = front of the standard frame).',
                         {'given': front_direction})
    cols = _colors(colors)
    shell = check_file(workspace, shell_step_path, STEP_SUFFIXES, 'HANDEDNESS_FLIP_FILE', 'shell_step_path')
    plate = check_file(workspace, plate_step_path, STEP_SUFFIXES, 'HANDEDNESS_FLIP_FILE', 'plate_step_path')
    roles = check_file(workspace, face_roles_path, ('.json',), 'HANDEDNESS_FLIP_FILE', 'face_roles_path')
    roles_rel = face_roles_path
    rep = json_load(roles)
    if isinstance(rep, dict) and 'top_shell' not in rep and isinstance(rep.get('outputs'), dict):     # a face_roles_report.json
        rel = (rep['outputs'].get('face_roles') or {}).get('relative_path')
        if not isinstance(rel, str) or not rel:
            raise BrainError('HANDEDNESS_FLIP_FILE', 'The face roles report lists no face_roles output.', {'given': face_roles_path})
        roles, roles_rel = check_file(workspace, rel, ('.json',), 'HANDEDNESS_FLIP_FILE', 'face_roles (named by the report)'), rel
    sym = None
    if symmetry_report_path is not None:
        if mirror_normal is not None or mirror_d is not None:
            raise BrainError('HANDEDNESS_FLIP_SYMMETRY', 'Give either symmetry_report_path or mirror_normal + mirror_d, not both.')
        sym = check_file(workspace, symmetry_report_path, ('.json',), 'HANDEDNESS_FLIP_SYMMETRY', 'symmetry_report_path')
        mirror = {**mirror_from_report(workspace, symmetry_report_path, 'HANDEDNESS_FLIP_SYMMETRY'), 'source': 'symmetry_report'}
    elif mirror_normal is not None and mirror_d is not None:
        mirror = {'normal': mirror_normal, 'd': mirror_d, 'source': 'arguments'}
    else:
        raise BrainError('HANDEDNESS_FLIP_SYMMETRY', 'The mirror plane is required: symmetry_report_path (brain_mouse_scan_symmetrise report) or mirror_normal + mirror_d.')
    n = mirror['normal']
    if (not isinstance(n, (list, tuple)) or len(n) != 3 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in n)
            or isinstance(mirror['d'], bool) or not isinstance(mirror['d'], (int, float)) or not math.isfinite(mirror['d'])):
        raise BrainError('HANDEDNESS_FLIP_SYMMETRY', 'The mirror plane needs a finite normal [nx, ny, nz] and a finite d (n.x = d).', {'given': mirror})
    s = math.hypot(*n)
    if s < 1e-9 or math.hypot(n[0], n[1]) / s < 0.9:
        raise BrainError('HANDEDNESS_FLIP_SYMMETRY', 'The mirror plane must be close to vertical (|n_xy| >= 0.9 |n|).', {'normal': n})
    mirror = {'normal': [float(x) / s for x in n], 'd': float(mirror['d']) / s, 'source': mirror['source']}
    settings = {'floor_tol_mm': float(floor_tol_mm), 'volume_tol_pct': float(volume_tol_pct), 'mirror': mirror, 'colors': cols,
                'front_direction': None if front_direction is None else [float(x) for x in front_direction], 'face_tol_mm': 1e-4}
    rel = {'shell_step_path': shell_step_path, 'plate_step_path': plate_step_path, 'face_roles_path': roles_rel, 'symmetry_report_path': symmetry_report_path}

    def build_report(res: dict[str, Any], final: Path, job_id: str, hashes: dict[str, str | None]) -> dict[str, Any]:
        checks = res['checks']
        blockers = [k for k, v in checks.items() if v == 'FAIL']
        return {'schema': 'handedness_flip_report/1', 'status': 'NOT_READY' if blockers else 'READY', 'blocking_reasons': blockers,
                'handedness_flip_id': job_id, 'version': HF_VERSION, 'server_version': __version__, 'inputs': rel, 'input_hashes': hashes,
                'settings': settings, 'checks': checks, 'measurements': res['measurements'], 'warnings': res['warnings'],
                'outputs': {k: {'file': v} for k, v in res['files'].items()}, 'seconds': res.get('seconds'),
                'downstream': {'note': 'top_shell.step / bottom_plate.step / assembly.step are the mirrored model (floor z = 0); assembly_colored.step carries '
                                       'the XCAF face colours of face_roles.json (same face order as top_shell.step / bottom_plate.step).'},
                'limits': ['Pure mirror plus a rigid re-level: geometry is neither redesigned nor re-measured against any scan.',
                           'The mirror plane is the one given; a plane that is not the mouse symmetry plane gives a displaced, not a flipped, mouse.',
                           'Side buttons are recognised from the face roles (sidebutton / sidebutton_wall); a model without them reports the flank as UNVERIFIED.',
                           'Face indices follow TopExp_Explorer order of the written STEP files; match by point / bbox in other CAD.']}

    return run_job(workspace=workspace, area='cad', prefix='hf_', version=HF_VERSION, code='HANDEDNESS_FLIP',
                   inputs={'shell': shell, 'plate': plate, 'roles': roles, 'symmetry': sym}, settings=settings, worker=WORKER, python=server_python(),
                   report_name=REPORT, build_report=build_report, timeout_s=TIMEOUT_S)


__all__ = ['handedness_flip', 'HF_VERSION', 'REPORT', 'DEFAULTS']
