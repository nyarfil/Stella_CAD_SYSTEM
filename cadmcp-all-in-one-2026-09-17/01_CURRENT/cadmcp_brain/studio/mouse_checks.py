"""Mouse internals check tools: brain_mouse_interference_report, brain_mouse_wall_audit, brain_mouse_section_render.

They only READ STEP files (assemblies keep their part labels; see mouse_parts_lib) and write a report plus pictures once under mouse/checks/<id>/
(never overwritten; the same inputs return the stored report). The geometry runs in a subprocess of the server python (OCP, vtk, matplotlib =
extra `geometry`): mouse_interference_worker.py, mouse_wall_audit_worker.py, mouse_section_render_worker.py.
"""
from __future__ import annotations
import math
from pathlib import Path
from typing import Any
from .scan_cad_common import check_file, check_range, run_job, server_python
from .. import __version__
from ..errors import BrainError

CHECKS_VERSION = 'MC1.0'
STEP_SUFFIXES = ('.step', '.stp')
MAX_STEPS = 16
MAX_PAIRS = 2000
HERE = Path(__file__).parent
INTERFERENCE_REPORT, WALL_REPORT, SECTION_REPORT = 'interference_report.json', 'wall_audit_report.json', 'section_report.json'


def _num(v: Any) -> bool:
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)


def _vec3(v: Any, what: str, code: str) -> list[float]:
    if not isinstance(v, (list, tuple)) or len(v) != 3 or not all(_num(x) for x in v):
        raise BrainError(code, f'{what} must be [x, y, z] (finite numbers, mm).', {'given': v})
    return [float(x) for x in v]


def _name(v: Any, what: str, code: str) -> str:
    if not isinstance(v, str) or not v.strip() or len(v) > 200:
        raise BrainError(code, f'{what} must be a non-empty part name.', {'given': v})
    return v


def _steps(workspace: Path, step_paths: Any, code: str) -> dict[str, Path]:
    if isinstance(step_paths, str):
        step_paths = [step_paths]
    if not isinstance(step_paths, list) or not 1 <= len(step_paths) <= MAX_STEPS:
        raise BrainError(f'{code}_FILE', f'step_paths must list 1-{MAX_STEPS} STEP files inside the workspace.', {'given': step_paths})
    return {f'step_{i}': check_file(workspace, p, STEP_SUFFIXES, f'{code}_FILE', f'step_paths[{i}]') for i, p in enumerate(step_paths)}


def _groups(groups: Any, code: str) -> dict[str, list[str]] | None:
    if groups is None:
        return None
    if not isinstance(groups, dict) or not all(isinstance(m, list) and m for m in groups.values()):
        raise BrainError(f'{code}_SETTINGS', 'groups must map a new part name to a non-empty list of part names (a trailing * matches a prefix).',
                         {'given': groups})
    return {_name(g, 'group name', f'{code}_SETTINGS'): [_name(m, 'group member', f'{code}_SETTINGS') for m in ms] for g, ms in groups.items()}


def _parts(parts: Any, code: str) -> list[str] | None:
    if parts is None:
        return None
    if not isinstance(parts, list) or not parts:
        raise BrainError(f'{code}_SETTINGS', 'parts must be a non-empty list of part names (or omitted for all).', {'given': parts})
    return [_name(p, 'part', f'{code}_SETTINGS') for p in parts]


def _outputs(res: dict[str, Any]) -> dict[str, Any]:
    return {k: {'file': v} for k, v in res['files'].items()}


def interference_report(workspace: Path, step_paths: list[str], pairs: list[dict[str, Any]] | None = None, parts: list[str] | None = None,
                        groups: dict[str, list[str]] | None = None, clearance_mm: float = 0.3, overlap_tol_mm3: float = 0.01, near_mm: float = 2.5,
                        sample_mm: float = 0.5, fine_deflection_mm: float = 0.005, coarse_deflection_mm: float = 0.02) -> dict[str, Any]:
    workspace, code = Path(workspace), 'INTERFERENCE'
    for n, v, lo, hi in (('clearance_mm', clearance_mm, 0.0, 20.0), ('overlap_tol_mm3', overlap_tol_mm3, 0.0, 1000.0), ('near_mm', near_mm, 0.5, 50.0),
                         ('sample_mm', sample_mm, 0.05, 5.0), ('fine_deflection_mm', fine_deflection_mm, 0.001, 0.5),
                         ('coarse_deflection_mm', coarse_deflection_mm, 0.001, 1.0)):
        check_range(n, v, lo, hi, f'{code}_SETTINGS')
    inputs = _steps(workspace, step_paths, code)
    norm_pairs = None
    if pairs is not None:
        if not isinstance(pairs, list) or not 1 <= len(pairs) <= MAX_PAIRS:
            raise BrainError(f'{code}_SETTINGS', f'pairs must be a list of 1-{MAX_PAIRS} {{"a", "b", "clearance_mm"?, "within_mm"?}} (b "*" = every other '
                                                  'part), or omitted for all pairs.', {'given': type(pairs).__name__})
        norm_pairs = []
        for i, p in enumerate(pairs):
            if not isinstance(p, dict) or set(p) - {'a', 'b', 'clearance_mm', 'within_mm', 'label_a', 'label_b'}:
                raise BrainError(f'{code}_SETTINGS', 'Each pair is {"a", "b", "clearance_mm"?, "within_mm"?, "label_a"?, "label_b"?}.', {'index': i, 'given': p})
            q = {'a': _name(p.get('a'), f'pairs[{i}].a', f'{code}_SETTINGS'), 'b': _name(p.get('b'), f'pairs[{i}].b', f'{code}_SETTINGS')}
            for k in ('clearance_mm', 'within_mm'):
                if k in p:
                    check_range(f'pairs[{i}].{k}', p[k], 0.0, 1000.0, f'{code}_SETTINGS')
                    q[k] = float(p[k])
            for k in ('label_a', 'label_b'):
                if k in p:
                    q[k] = _name(p[k], f'pairs[{i}].{k}', f'{code}_SETTINGS')
            norm_pairs.append(q)
    settings = {'pairs': norm_pairs, 'parts': _parts(parts, code), 'groups': _groups(groups, code), 'clearance_mm': float(clearance_mm),
                'overlap_tol_mm3': float(overlap_tol_mm3), 'near_mm': float(near_mm), 'sample_mm': float(sample_mm),
                'fine_deflection_mm': float(fine_deflection_mm), 'coarse_deflection_mm': float(coarse_deflection_mm)}

    def build_report(res, final, job_id, hashes):
        s = res['summary']
        return {'schema': 'mouse_interference_report/1', 'status': 'PASS' if s['fail'] == 0 and s['pairs'] > 0 else 'FAIL',
                'interference_id': job_id, 'version': CHECKS_VERSION, 'server_version': __version__, 'inputs': {'step_paths': list(step_paths)},
                'input_hashes': hashes, 'settings': settings, 'summary': s, 'rows': res['rows'], 'parts': res['parts'], 'outputs': _outputs(res),
                'seconds': res.get('seconds'),
                'limits': ['Distances are mesh point-to-surface (densified samples, both directions); they are exact to about the tessellation deflection.',
                           'Overlap volume is the exact OCC Boolean common, computed only when the parts come closer than sample_mm.',
                           'A pair far apart (bbox gap > near_mm) reports the bbox gap, a lower bound of the true distance.',
                           'Moving parts are checked in the pose of the STEP file only; travel states need their own STEP poses.']}

    return run_job(workspace=workspace, area='checks', prefix='if_', version=CHECKS_VERSION, code=code, inputs=inputs, settings=settings,
                   worker=HERE / 'mouse_interference_worker.py', python=server_python(), report_name=INTERFERENCE_REPORT, build_report=build_report,
                   timeout_s=3600)


def wall_audit(workspace: Path, shell_step_path: str, target_thickness_mm: float, part: str | None = None, line_width_mm: float = 0.4,
               tol_mm: float = 0.05, max_over_mm: float = 0.2, density_g_cm3: float = 1.04, samples: int = 40000, deflection_mm: float = 0.02) -> dict[str, Any]:
    workspace, code = Path(workspace), 'WALL_AUDIT'
    for n, v, lo, hi in (('target_thickness_mm', target_thickness_mm, 0.1, 20.0), ('line_width_mm', line_width_mm, 0.05, 2.0), ('tol_mm', tol_mm, 0.001, 0.5),
                         ('max_over_mm', max_over_mm, 0.0, 10.0), ('density_g_cm3', density_g_cm3, 0.05, 25.0), ('deflection_mm', deflection_mm, 0.001, 0.5)):
        check_range(n, v, lo, hi, f'{code}_SETTINGS')
    if isinstance(samples, bool) or not isinstance(samples, int) or not 1000 <= samples <= 400000:
        raise BrainError(f'{code}_SETTINGS', 'samples must be an integer in [1000, 400000].', {'given': samples})
    shell = check_file(workspace, shell_step_path, STEP_SUFFIXES, f'{code}_FILE', 'shell_step_path')
    settings = {'target_thickness_mm': float(target_thickness_mm), 'part': None if part is None else _name(part, 'part', f'{code}_SETTINGS'),
                'line_width_mm': float(line_width_mm), 'tol_mm': float(tol_mm), 'max_over_mm': float(max_over_mm), 'density_g_cm3': float(density_g_cm3),
                'samples': samples, 'deflection_mm': float(deflection_mm), 'seed': 0}

    def build_report(res, final, job_id, hashes):
        ch = res['checks']
        status = 'FAIL' if 'FAIL' in ch.values() else 'WARN' if 'WARN' in ch.values() else 'PASS'
        return {'schema': 'mouse_wall_audit_report/1', 'status': status, 'wall_audit_id': job_id, 'version': CHECKS_VERSION, 'server_version': __version__,
                'inputs': {'shell_step_path': shell_step_path}, 'input_hashes': hashes, 'settings': settings, 'part': res['part'],
                'target_thickness_mm': res['target_thickness_mm'], 'stats': res['stats'], 'checks': ch, 'mass': res['mass'],
                'thick_zones': res['thick_zones'], 'thin_zones': res['thin_zones'], 'histogram': res['histogram'], 'outputs': _outputs(res),
                'seconds': res.get('seconds'),
                'limits': ['Thickness = distance along the inward skin normal to the first exit (not a vertical or horizontal section).',
                           'Posts, ribs and bosses read as thick zones; samples next to sharp edges and slot walls can read thin: check the zones listed.',
                           'Mass uses the closed tessellation volume (slightly below the exact B-rep volume, also reported).']}

    return run_job(workspace=workspace, area='checks', prefix='wa_', version=CHECKS_VERSION, code=code, inputs={'shell': shell}, settings=settings,
                   worker=HERE / 'mouse_wall_audit_worker.py', python=server_python(), report_name=WALL_REPORT, build_report=build_report, timeout_s=1800)


def section_render(workspace: Path, step_paths: list[str], plane: dict[str, Any], parts: list[str] | None = None, groups: dict[str, list[str]] | None = None,
                   colors: dict[str, str] | None = None, dimensions: list[dict[str, Any]] | None = None, window: list[float] | None = None,
                   title: str | None = None, curve_step_mm: float = 0.05) -> dict[str, Any]:
    workspace, code = Path(workspace), 'SECTION'
    check_range('curve_step_mm', curve_step_mm, 0.005, 2.0, f'{code}_SETTINGS')
    inputs = _steps(workspace, step_paths, code)
    if not isinstance(plane, dict) or plane.get('kind') not in ('XZ', 'YZ', 'XY', 'axis', 'plane'):
        raise BrainError(f'{code}_PLANE', 'plane must be {"kind": "XZ"|"YZ"|"XY", "offset": mm}, {"kind": "axis", "point", "direction", "normal"} or '
                                          '{"kind": "plane", "origin", "normal", "up"?}.', {'given': plane})
    k = plane['kind']
    if k in ('XZ', 'YZ', 'XY'):
        off = plane.get('offset', 0.0)
        if not _num(off) or set(plane) - {'kind', 'offset'}:
            raise BrainError(f'{code}_PLANE', f'A {k} plane takes only a finite offset (mm along the missing axis).', {'given': plane})
        pl = {'kind': k, 'offset': float(off)}
    elif k == 'axis':
        pl = {'kind': k, **{n: _vec3(plane.get(n), f'plane.{n}', f'{code}_PLANE') for n in ('point', 'direction', 'normal')}}
    else:
        pl = {'kind': k, **{n: _vec3(plane.get(n), f'plane.{n}', f'{code}_PLANE') for n in ('origin', 'normal')}}
        if 'up' in plane:
            pl['up'] = _vec3(plane['up'], 'plane.up', f'{code}_PLANE')
    if colors is not None and (not isinstance(colors, dict) or not all(isinstance(c, str) and len(c) <= 40 for c in colors.values())):
        raise BrainError(f'{code}_SETTINGS', 'colors must map part names to matplotlib colour strings (e.g. "#e08a3c").', {'given': colors})
    dims = []
    for i, d in enumerate(dimensions or []):
        if not isinstance(d, dict) or set(d) - {'from', 'to', 'label', 'color'}:
            raise BrainError(f'{code}_SETTINGS', 'Each dimension is {"from": [x,y,z], "to": [x,y,z], "label"?, "color"?}.', {'index': i})
        q = {'from': _vec3(d.get('from'), f'dimensions[{i}].from', f'{code}_SETTINGS'), 'to': _vec3(d.get('to'), f'dimensions[{i}].to', f'{code}_SETTINGS')}
        for n in ('label', 'color'):
            if n in d:
                q[n] = _name(d[n], f'dimensions[{i}].{n}', f'{code}_SETTINGS')
        dims.append(q)
    if window is not None and (not isinstance(window, list) or len(window) != 4 or not all(_num(x) for x in window)
                               or window[0] >= window[1] or window[2] >= window[3]):
        raise BrainError(f'{code}_SETTINGS', 'window must be [u_min, u_max, v_min, v_max] in plane coordinates (mm).', {'given': window})
    settings = {'plane': pl, 'parts': _parts(parts, code), 'groups': _groups(groups, code), 'colors': colors, 'dimensions': dims,
                'window': None if window is None else [float(x) for x in window], 'title': None if title is None else _name(title, 'title', f'{code}_SETTINGS'),
                'curve_step_mm': float(curve_step_mm)}

    def build_report(res, final, job_id, hashes):
        not_cut = [r['part'] for r in res['parts_shown'] if not r['cut']]
        open_ = [r['part'] for r in res['parts_shown'] if r['open_chains']]
        return {'schema': 'mouse_section_render_report/1', 'status': 'READY', 'section_id': job_id, 'version': CHECKS_VERSION, 'server_version': __version__,
                'inputs': {'step_paths': list(step_paths)}, 'input_hashes': hashes, 'settings': settings, 'plane': res['plane'],
                'parts_shown': res['parts_shown'], 'dimensions': res['dimensions'], 'parts': res['parts'], 'outputs': _outputs(res),
                'warnings': ([f'Not cut by this plane: {not_cut}.'] if not_cut else []) + ([f'Section loops left open (drawn as lines): {open_}.'] if open_ else []),
                'seconds': res.get('seconds')}

    return run_job(workspace=workspace, area='checks', prefix='sr_', version=CHECKS_VERSION, code=code, inputs=inputs, settings=settings,
                   worker=HERE / 'mouse_section_render_worker.py', python=server_python(), report_name=SECTION_REPORT, build_report=build_report,
                   timeout_s=1800)


__all__ = ['interference_report', 'wall_audit', 'section_render', 'CHECKS_VERSION', 'INTERFERENCE_REPORT', 'WALL_REPORT', 'SECTION_REPORT']
