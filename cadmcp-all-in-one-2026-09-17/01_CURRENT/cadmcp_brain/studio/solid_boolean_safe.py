"""brain_solid_boolean_safe: gated fuse / cut / common of two STEP solids with a retry ladder (plain, then fuzzy tol x 1.0, 0.7, 0.5, 1.5).

Inputs are only READ. The result STEP and the report are written once under mouse/cad/<sb_id>/ (never overwritten; same inputs return the stored report).
Geometry runs in the worker subprocess solid_boolean_safe_worker.py (OCP). The gate logic is importable by other workers (same process, needs OCP):
`safe_boolean_shapes(a, b, op, **kw)` and `gate_boolean_result(a, b, op, result, ...)` below load it lazily; its docstring defines every check.
"""
from __future__ import annotations
import math
from pathlib import Path
from typing import Any
from .scan_cad_common import check_file, check_range, run_job, server_python
from .. import __version__
from ..errors import BrainError

BOOL_VERSION = 'SB1.0'
STEP_SUFFIXES = ('.step', '.stp')
HERE = Path(__file__).parent
BOOL_REPORT = 'boolean_safe_report.json'
# tol_mm 0.01 = the ShapeFix tolerance of the approved FreeCAD fuse remedy; volume tolerance ~10 mm3 = "bookkeeping closes within about 10 mm3"
# (docs/SCAN_TO_HOLLOW_SHELL_PIPELINE_JA_SPEC.md section 7 / 8.1, LH2 build notes); multiples 1.0 / 0.7 / 0.5 / 1.5 and point test bad <= max(2, N/500) = proposed tool 10.


def _name(v: Any, what: str, code: str) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str) or not v.strip() or len(v) > 200:
        raise BrainError(f'{code}_SETTINGS', f'{what} must be a part name.', {'given': v})
    return v


def boolean_safe(workspace: Path, a_step_path: str, b_step_path: str, op: str, part_a: str | None = None, part_b: str | None = None, tol_mm: float = 0.01,
                 fuzzy_multiples: list[float] | None = None, include_plain: bool = True, volume_tol_mm3: float = 10.0, volume_tol_rel: float = 0.001,
                 points: int = 2000, near_surface_mm: float = 0.5, seed: int = 0, expect_solids: int | None = 1, unify: bool = True,
                 shapefix: str = 'if_invalid', mesh_deflection_mm: float = 0.02) -> dict[str, Any]:
    workspace, code = Path(workspace), 'BOOLEAN_SAFE'
    if op not in ('fuse', 'cut', 'common'):
        raise BrainError(f'{code}_SETTINGS', 'op must be "fuse", "cut" or "common".', {'given': op})
    for n, v, lo, hi in (('tol_mm', tol_mm, 0.0, 1.0), ('volume_tol_mm3', volume_tol_mm3, 0.0, 1000.0), ('volume_tol_rel', volume_tol_rel, 0.0, 0.1),
                         ('near_surface_mm', near_surface_mm, 0.0, 10.0), ('mesh_deflection_mm', mesh_deflection_mm, 0.001, 0.5)):
        check_range(n, v, lo, hi, f'{code}_SETTINGS')
    if fuzzy_multiples is None:
        fuzzy_multiples = [1.0, 0.7, 0.5, 1.5]
    if not isinstance(fuzzy_multiples, list) or len(fuzzy_multiples) > 8 or not all(
            not isinstance(m, bool) and isinstance(m, (int, float)) and math.isfinite(m) and 0 < m <= 20 for m in fuzzy_multiples):
        raise BrainError(f'{code}_SETTINGS', 'fuzzy_multiples must be up to 8 numbers in (0, 20] (multiples of tol_mm).', {'given': fuzzy_multiples})
    if not include_plain and not fuzzy_multiples:
        raise BrainError(f'{code}_SETTINGS', 'At least one attempt is needed (include_plain or fuzzy_multiples).')
    if isinstance(points, bool) or not isinstance(points, int) or not 100 <= points <= 100000:
        raise BrainError(f'{code}_SETTINGS', 'points must be an integer in [100, 100000].', {'given': points})
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise BrainError(f'{code}_SETTINGS', 'seed must be an integer.', {'given': seed})
    if expect_solids is not None and (isinstance(expect_solids, bool) or not isinstance(expect_solids, int) or not 1 <= expect_solids <= 100):
        raise BrainError(f'{code}_SETTINGS', 'expect_solids must be null (any count >= 1) or an integer in [1, 100].', {'given': expect_solids})
    if shapefix not in ('if_invalid', 'always', 'never'):
        raise BrainError(f'{code}_SETTINGS', 'shapefix must be "if_invalid", "always" or "never".', {'given': shapefix})
    if not isinstance(unify, bool) or not isinstance(include_plain, bool):
        raise BrainError(f'{code}_SETTINGS', 'unify and include_plain must be true or false.')
    inputs = {'a': check_file(workspace, a_step_path, STEP_SUFFIXES, f'{code}_FILE', 'a_step_path'),
              'b': check_file(workspace, b_step_path, STEP_SUFFIXES, f'{code}_FILE', 'b_step_path')}
    settings = {'op': op, 'part_a': _name(part_a, 'part_a', code), 'part_b': _name(part_b, 'part_b', code), 'tol_mm': float(tol_mm),
                'fuzzy_multiples': [float(m) for m in fuzzy_multiples], 'include_plain': include_plain, 'volume_tol_mm3': float(volume_tol_mm3),
                'volume_tol_rel': float(volume_tol_rel), 'points': points, 'near_surface_mm': float(near_surface_mm), 'seed': seed, 'expect_solids': expect_solids,
                'unify': unify, 'shapefix': shapefix, 'mesh_deflection_mm': float(mesh_deflection_mm)}

    def build_report(res, final, job_id, hashes):
        r = res['result']
        status = r['status'] if r['status'] in ('PASS', 'UNVERIFIED') and res['files'] else 'FAIL'
        return {'schema': 'solid_boolean_safe_report/1', 'status': status, 'boolean_safe_id': job_id, 'version': BOOL_VERSION, 'server_version': __version__,
                'op': op, 'inputs': {'a_step_path': a_step_path, 'b_step_path': b_step_path, 'part_a': res['part_a'], 'part_b': res['part_b']}, 'input_hashes': hashes,
                'settings': settings, 'accepted_attempt': next((x['step'] for x in r['attempts'] if x['op'] == op and x['status'] in ('PASS', 'UNVERIFIED')), None),
                'gate': r.get('gate'), 'bookkeeping': r['bookkeeping'], 'volumes_mm3': {'a': r['va_mm3'], 'b': r['vb_mm3']}, 'attempts': r['attempts'],
                'clean': r['clean'], 'faces_before_clean': r['faces_before_clean'], 'faces_after_clean': r['faces_after_clean'], 'round_trip': r.get('round_trip'),
                'outputs': {k: {'file': v} for k, v in res['files'].items()}, 'seconds': res.get('seconds'),
                'limits': ['Volumes are closed-mesh volumes at mesh_deflection_mm; the bookkeeping partner (common for fuse / cut, fuse for common) is a Boolean too, '
                           'so a pass means the two Booleans and the point test agree, not an independent exact volume.',
                           'The point test is random (seed argument) and cannot see a defect smaller than its sample spacing; points ON a surface are skipped.',
                           'UNVERIFIED = every other gate passed but the volume bookkeeping could not be completed (partner Boolean failed); do not treat as PASS.',
                           'Fuzzy values merge features closer than the value: a deliberate gap or sliver below tol x multiple disappears (the volume gate bounds the effect).']}

    return run_job(workspace=workspace, area='cad', prefix='sb_', version=BOOL_VERSION, code=code, inputs=inputs, settings=settings,
                   worker=HERE / 'solid_boolean_safe_worker.py', python=server_python(), report_name=BOOL_REPORT, build_report=build_report, timeout_s=3600)


def safe_boolean_shapes(a, b, op: str, **kw) -> dict[str, Any]:
    """In-process reuse for other workers (needs OCP): see solid_boolean_safe_worker.safe_boolean."""
    from . import solid_boolean_safe_worker as W
    return W.safe_boolean(a, b, op, **kw)


def gate_boolean_result(a, b, op: str, result, **kw) -> dict[str, Any]:
    """In-process reuse for other workers (needs OCP): see solid_boolean_safe_worker.gate_boolean (keywords va, vb, expected_mm3, params, points)."""
    from . import solid_boolean_safe_worker as W
    return W.gate_boolean(a, b, op, result, **kw)
