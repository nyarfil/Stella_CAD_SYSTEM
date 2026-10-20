"""brain_mouse_seam_audit: B-rep edges of a shell solid inside given bands, with G1 deviation across each seam edge (check stage, STEP only read).

Writes seam_audit_report.json and a plan-view PNG once under mouse/checks/<sa_id>/ (never overwritten; same inputs return the stored report).
Geometry runs in the worker subprocess mouse_seam_audit_worker.py (OCP, matplotlib, extra `geometry`).
Bands: pass `bands` explicitly, or leave it out and the worker DERIVES one slot band centred on the fitted left-right symmetry plane of the shell
(plane normal = mirror_axis, default 'y' = the lateral axis of a mouse; the plane is fitted from the shell tessellation, mirror_plane_mm overrides it).
Its half width is band_half_width_mm, default 1.5 % of the shell extent along the mirror axis (a process proportion: the owner's 1.0 mm slot band on a
66 mm wide shell). Nothing assumes the symmetry plane is at 0.
"""
from __future__ import annotations
import math
from pathlib import Path
from typing import Any
from .scan_cad_common import check_file, check_range, run_job, server_python
from .. import __version__
from ..errors import BrainError

SEAM_VERSION = 'SA1.0'
STEP_SUFFIXES = ('.step', '.stp')
HERE = Path(__file__).parent
SEAM_REPORT = 'seam_audit_report.json'
AXES = ('x', 'y', 'z')
# Approved process (docs/SCAN_TO_HOLLOW_SHELL_PIPELINE_JA_SPEC.md 8.5): no seam edges in the slot band around the symmetry plane over the click range, none
# along the rear skin line on the plane. The click range belongs to the shell, so it is an argument (along_*), not a constant. No default band numbers:
# bands=None derives the slot band from the fitted symmetry plane (see the module docstring).


def _num(v: Any) -> bool:
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)


def _bands(bands: Any, code: str) -> list[dict[str, Any]]:
    if bands is None:
        return None
    if not isinstance(bands, list) or not 1 <= len(bands) <= 32:
        raise BrainError(f'{code}_SETTINGS', 'bands must list 1-32 {"name", "axis", "range": [lo, hi], "along_axis"?, "along_range"?}.', {'given': type(bands).__name__})
    out, names = [], set()
    for i, b in enumerate(bands):
        if not isinstance(b, dict) or set(b) - {'name', 'axis', 'range', 'along_axis', 'along_range'}:
            raise BrainError(f'{code}_SETTINGS', 'Each band is {"name", "axis", "range", "along_axis"?, "along_range"?}.', {'index': i, 'given': b})
        name = b.get('name', f'band_{i}')
        if not isinstance(name, str) or not name.strip() or name in names:
            raise BrainError(f'{code}_SETTINGS', 'Band names must be unique non-empty strings.', {'index': i, 'given': name})
        names.add(name)
        if b.get('axis') not in AXES:
            raise BrainError(f'{code}_SETTINGS', 'band axis must be "x", "y" or "z".', {'index': i, 'given': b.get('axis')})
        item = {'name': name, 'axis': b['axis'], 'range': _range(b.get('range'), f'bands[{i}].range', code)}
        if b.get('along_axis') is not None or b.get('along_range') is not None:
            if b.get('along_axis') not in AXES or b['along_axis'] == b['axis']:
                raise BrainError(f'{code}_SETTINGS', 'along_axis must be an axis different from the band axis.', {'index': i, 'given': b.get('along_axis')})
            item['along_axis'], item['along_range'] = b['along_axis'], _range(b.get('along_range'), f'bands[{i}].along_range', code)
        out.append(item)
    return out


def _range(v: Any, what: str, code: str) -> list[float]:
    if not isinstance(v, (list, tuple)) or len(v) != 2 or not all(_num(x) for x in v) or v[0] > v[1]:
        raise BrainError(f'{code}_SETTINGS', f'{what} must be [lo, hi] (mm, lo <= hi).', {'given': v})
    return [float(v[0]), float(v[1])]


def seam_audit(workspace: Path, shell_step_path: str, bands: list[dict[str, Any]] | None = None, part: str | None = None, g1_tol_deg: float = 1.0,
               samples: int = 9, flag: str = 'seams', band_tol_mm: float = 1e-6, deflection_mm: float = 0.1, view: str = 'XY', max_listed: int = 300,
               mirror_axis: str = 'y', mirror_plane_mm: float | None = None, band_half_width_mm: float | None = None) -> dict[str, Any]:
    workspace, code = Path(workspace), 'SEAM_AUDIT'
    if mirror_axis not in AXES:
        raise BrainError(f'{code}_SETTINGS', 'mirror_axis must be "x", "y" or "z" (the normal of the left-right symmetry plane).', {'given': mirror_axis})
    if mirror_plane_mm is not None:
        check_range('mirror_plane_mm', mirror_plane_mm, -10000.0, 10000.0, f'{code}_SETTINGS')
    if band_half_width_mm is not None:
        check_range('band_half_width_mm', band_half_width_mm, 1e-6, 1000.0, f'{code}_SETTINGS')
    check_range('g1_tol_deg', g1_tol_deg, 0.0, 90.0, f'{code}_SETTINGS')
    check_range('band_tol_mm', band_tol_mm, 0.0, 1.0, f'{code}_SETTINGS')
    check_range('deflection_mm', deflection_mm, 0.005, 2.0, f'{code}_SETTINGS')
    if isinstance(samples, bool) or not isinstance(samples, int) or not 2 <= samples <= 64:
        raise BrainError(f'{code}_SETTINGS', 'samples must be an integer in [2, 64].', {'given': samples})
    if isinstance(max_listed, bool) or not isinstance(max_listed, int) or not 1 <= max_listed <= 5000:
        raise BrainError(f'{code}_SETTINGS', 'max_listed must be an integer in [1, 5000].', {'given': max_listed})
    if flag not in ('seams', 'all'):
        raise BrainError(f'{code}_SETTINGS', 'flag must be "seams" (smooth seams, free and non-manifold edges) or "all".', {'given': flag})
    if view not in ('XY', 'XZ', 'YZ'):
        raise BrainError(f'{code}_SETTINGS', 'view must be XY, XZ or YZ.', {'given': view})
    if part is not None and (not isinstance(part, str) or not part.strip()):
        raise BrainError(f'{code}_SETTINGS', 'part must be a part name.', {'given': part})
    shell = check_file(workspace, shell_step_path, STEP_SUFFIXES, f'{code}_FILE', 'shell_step_path')
    settings = {'bands': _bands(bands, code), 'mirror_axis': mirror_axis, 'mirror_plane_mm': None if mirror_plane_mm is None else float(mirror_plane_mm),
                'band_half_width_mm': None if band_half_width_mm is None else float(band_half_width_mm), 'part': part, 'g1_tol_deg': float(g1_tol_deg), 'samples': samples, 'flag': flag, 'band_tol_mm': float(band_tol_mm),
                'deflection_mm': float(deflection_mm), 'view': view, 'max_listed': max_listed}

    def build_report(res, final, job_id, hashes):
        return {'schema': 'mouse_seam_audit_report/1', 'status': 'PASS' if res['flagged_total'] == 0 else 'FAIL', 'seam_audit_id': job_id, 'version': SEAM_VERSION,
                'server_version': __version__, 'inputs': {'shell_step_path': shell_step_path}, 'input_hashes': hashes, 'settings': settings, 'part': res['part'],
                'totals': res['totals'], 'bands': res['bands'], 'symmetry': res['symmetry'], 'flagged_total': res['flagged_total'], 'volume_mm3': res['volume_mm3'], 'bbox': res['bbox'],
                'outputs': {k: {'file': v} for k, v in res['files'].items()}, 'seconds': res.get('seconds'),
                'limits': ['A seam is read from the B-rep topology and the angle between the two outward face normals; a smooth_seam may be intended '
                           '(a designed split), the audit reports it, the owner decides.',
                           'An edge is in a band only when ALL its sample points are inside the slab; an edge that crosses the band edge is not counted.',
                           'faces_in_band comes from the tessellation (deflection_mm) and can miss a sliver thinner than that deflection.',
                           'G1 is sampled at `samples` points per edge; a kink between samples is not seen.']}

    return run_job(workspace=workspace, area='checks', prefix='sa_', version=SEAM_VERSION, code=code, inputs={'shell': shell}, settings=settings,
                   worker=HERE / 'mouse_seam_audit_worker.py', python=server_python(), report_name=SEAM_REPORT, build_report=build_report, timeout_s=1800)
