"""brain_mouse_wheel_window: cut (or widen) the wheel window of a mouse top shell, gated, and report the clearance to every part near it.

Server side = argument validation + scan_cad_common.run_job (hash -> job id, worker subprocess, outputs once under mouse/cad/<ww_id>/, never
overwritten, cached report on the same inputs). The geometry runs in mouse_wheel_window_worker.py (OCP, vtk = extra `geometry`).
Owner process: spec docs/SCAN_TO_HOLLOW_SHELL_PIPELINE_JA_SPEC.md S8 (v23c2: rear edge = wheel intrusion minus 0.3 mm; v23f_fix.py: widened a further
0.8 mm rearward, half width 4.16, R 3.33).
No model-specific names or coordinates: shell_part and wheel_parts are required; the front direction is the front_axis argument ('+x' is the documented
convention, not an assumption); the corner radius defaults to 0.8 x the window half width (the owner's v23f ratio 3.33 / 4.16) unless given.
"""
from __future__ import annotations
import math
from pathlib import Path
from typing import Any
from .scan_cad_common import check_file, check_range, run_job, server_python
from .. import __version__
from ..errors import BrainError

WINDOW_VERSION = 'WW1.1'
STEP_SUFFIXES = ('.step', '.stp')
MAX_STEPS = 16
MODES = ('rect_from_wheel', 'widen_rear', 'explicit')
FRONT_AXES = ('+x', '-x', '+y', '-y')
HERE = Path(__file__).parent
REPORT = 'wheel_window_report.json'


def _num(v: Any) -> bool:
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)


def _name(v: Any, what: str) -> str:
    if not isinstance(v, str) or not v.strip() or len(v) > 200:
        raise BrainError('WHEEL_WINDOW_SETTINGS', f'{what} must be a non-empty part name.', {'given': v})
    return v


def _names(v: Any, what: str, allow_empty: bool) -> list[str]:
    if not isinstance(v, list) or (not v and not allow_empty):
        raise BrainError('WHEEL_WINDOW_SETTINGS', f'{what} must be a {"" if allow_empty else "non-empty "}list of part names.', {'given': v})
    return [_name(x, what) for x in v]


def wheel_window(workspace: Path, step_paths: list[str], mode: str = 'rect_from_wheel', shell_part: str | None = None, plate_parts: list[str] | None = None,
                 wheel_parts: list[str] | None = None, clearance_mm: float = 0.3, corner_radius_mm: float | None = None, delta_mm: float | None = None,
                 rear_edge_mm: float | None = None, half_width_mm: float | None = None, centre_y_mm: float | None = None, rect: list[float] | None = None,
                 groups: dict[str, list[str]] | None = None, near_margin_mm: float = 5.0, front_axis: str = '+x') -> dict[str, Any]:
    workspace, code = Path(workspace), 'WHEEL_WINDOW'
    if mode not in MODES:
        raise BrainError(f'{code}_SETTINGS', f'mode must be one of {list(MODES)}.', {'given': mode})
    if isinstance(step_paths, str):
        step_paths = [step_paths]
    if not isinstance(step_paths, list) or not 1 <= len(step_paths) <= MAX_STEPS:
        raise BrainError(f'{code}_FILE', f'step_paths must list 1-{MAX_STEPS} STEP files inside the workspace.', {'given': step_paths})
    inputs = {f'step_{i}': check_file(workspace, p, STEP_SUFFIXES, f'{code}_FILE', f'step_paths[{i}]') for i, p in enumerate(step_paths)}
    check_range('clearance_mm', clearance_mm, 0.0, 20.0, f'{code}_SETTINGS')
    if corner_radius_mm is not None:
        check_range('corner_radius_mm', corner_radius_mm, 0.0, 50.0, f'{code}_SETTINGS')
    if front_axis not in FRONT_AXES:
        raise BrainError(f'{code}_SETTINGS', f'front_axis must be one of {list(FRONT_AXES)} (the world direction the mouse front points to).', {'given': front_axis})
    if shell_part is None or wheel_parts is None:
        raise BrainError(f'{code}_SETTINGS', 'shell_part and wheel_parts are required (the names of the top shell and of the wheel parts in the STEP assembly).',
                         {'shell_part': shell_part, 'wheel_parts': wheel_parts})
    check_range('near_margin_mm', near_margin_mm, 0.0, 100.0, f'{code}_SETTINGS')
    for n, v in (('delta_mm', delta_mm), ('rear_edge_mm', rear_edge_mm), ('half_width_mm', half_width_mm), ('centre_y_mm', centre_y_mm)):
        if v is not None:
            check_range(n, v, -1000.0, 1000.0, f'{code}_SETTINGS')
    if half_width_mm is not None and half_width_mm <= 0:
        raise BrainError(f'{code}_SETTINGS', 'half_width_mm must be positive.', {'given': half_width_mm})
    if mode == 'widen_rear' and (delta_mm is None or delta_mm <= 0):
        raise BrainError(f'{code}_SETTINGS', 'mode widen_rear needs delta_mm > 0 (owner v23f: 0.8; no default, it depends on the wheel).', {'given': delta_mm})
    if mode == 'explicit':
        if not isinstance(rect, list) or len(rect) != 4 or not all(_num(v) for v in rect) or rect[0] >= rect[1] or rect[2] >= rect[3]:
            raise BrainError(f'{code}_SETTINGS', 'mode explicit needs rect = [x_min, x_max, y_min, y_max] (mm, min < max).', {'given': rect})
    settings = {'mode': mode, 'shell_part': _name(shell_part, 'shell_part'), 'plate_parts': _names(plate_parts or [], 'plate_parts', True),
                'wheel_parts': _names(wheel_parts, 'wheel_parts', False), 'clearance_mm': float(clearance_mm), 'front_axis': front_axis,
                'corner_radius_mm': None if corner_radius_mm is None else float(corner_radius_mm), 'delta_mm': None if delta_mm is None else float(delta_mm),
                'rear_edge_mm': None if rear_edge_mm is None else float(rear_edge_mm),
                'half_width_mm': None if half_width_mm is None else float(half_width_mm),
                'centre_y_mm': None if centre_y_mm is None else float(centre_y_mm), 'rect': None if rect is None else [float(v) for v in rect],
                'groups': groups, 'near_margin_mm': float(near_margin_mm)}
    if groups is not None and (not isinstance(groups, dict) or not all(isinstance(m, list) and m for m in groups.values())):
        raise BrainError(f'{code}_SETTINGS', 'groups must map a new part name to a non-empty list of part names.', {'given': groups})

    def build_report(res, final, job_id, hashes):
        # PASS only when every gate holds and (cut done or nothing to cut) and the wheel clearance is met; FAIL otherwise (gates failing raise instead).
        rc = res['rear_clearance']
        status = 'PASS' if res['gates_ok'] and rc.get('clearance_met') is not False else 'FAIL'
        return {'schema': 'mouse_wheel_window_report/1', 'status': status, 'window_status': res['status_window'], 'wheel_window_id': job_id,
                'version': WINDOW_VERSION, 'server_version': __version__, 'inputs': {'step_paths': list(step_paths)}, 'input_hashes': hashes,
                'settings': settings, 'gates': res['gates'], 'window': res['window'], 'cuts': res['cuts'], 'step_round_trip': res['step_round_trip'],
                'rear_clearance': rc, 'near_parts': res['near_parts'], 'parts': res['parts'],
                'outputs': {k: {'file': v} for k, v in res['files'].items()}, 'seconds': res.get('seconds'),
                'limits': ['Volumes are adaptive B-rep integrals (eps 1e-6); the default OCC rule is off by about 1 mm3 on a 13000 mm3 trimmed shell.',
                           'Distances come from mouse_interference_worker (mesh point-to-surface, exact to about the tessellation deflection; overlap = exact Boolean).',
                           'centre_y_mm / half_width_mm / rect are world coordinates; "y" is the axis across front_axis (x when front_axis is +-y). The cutter is a Z-parallel prism (shell top faces +z).',
                           'rect_from_wheel on a shell that already has a larger window clears only the residual intrusion (often NO_CHANGE_NEEDED); use widen_rear there.',
                           'The written assembly keeps part names but not colours.',
                           'Rows FAIL for parts that already overlapped the shell before the cut (known open items) are not caused by the window: compare '
                           'shell_common_before_mm3 with shell_common_after_mm3.']}

    return run_job(workspace=workspace, area='cad', prefix='ww_', version=WINDOW_VERSION, code=code, inputs=inputs, settings=settings,
                   worker=HERE / 'mouse_wheel_window_worker.py', python=server_python(), report_name=REPORT, build_report=build_report, timeout_s=3600)
