"""Cable pocket fill of the front wall of a welded scan mesh (brain_mouse_scan_cable_fill).

The cable hole / USB pocket of a scan is grade-C data: the designed front wall is plain (straight or a gentle R), so the pocket is detected
on the front view and filled with the wall inferred from the trusted wall around it (method: scan_cable_fill_worker.py). Optional chain
stage between brain_mouse_scan_flush and brain_mouse_scan_symmetrise / brain_mouse_shell_fit / brain_mouse_shell_solid /
brain_mouse_plate_side (outline_path): pass filled.stl and the rewritten labels (the face order changes: kept faces in input order, then the
patch). No pocket => READY no-op (the mesh and the labels are copied unchanged). The work runs in the SEPARATE scan python as a subprocess
(numpy, scipy, trimesh, shapely). The source is never modified; outputs go once under mouse/scans/<cf_id>/ and are never overwritten.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any
from . import scan_mesh as sm
from .scan_cable_fill_worker import DEFAULT_EXCLUDE, DEFAULTS
from .scan_model import find_scan_python
from .scan_shell import scan_dir
from .. import __version__
from ..errors import BrainError
from ..req2cad.common import atomic_json, json_load
from ..util import digest, file_hash, safe_path

CABLE_FILL_VERSION = 'CF1.0'
WORKER = Path(__file__).with_name('scan_cable_fill_worker.py')
TIMEOUT_S = 900
REPORT = 'cable_fill_report.json'
MAX_LABEL_BYTES = 64 * 1024 * 1024
_RANGES = {'grid_mm': (0.05, 1.0), 'front_depth_mm': (2.0, 80.0), 'front_nx': (0.0, 0.95), 'detect_sigma_mm': (1.0, 15.0), 'min_depth_mm': (0.2, 10.0),
           'min_width_mm': (0.5, 20.0), 'min_area_mm2': (0.5, 500.0), 'max_area_mm2': (1.0, 5000.0), 'ring_mm': (1.0, 15.0), 'degree': (1, 4),
           'smooth_tol_mm': (0.02, 2.0), 'min_radius_mm': (0.5, 1000.0), 'margin_mm': (0.0, 3.0), 'patch_edge_mm': (0.1, 3.0), 'blend_mm': (0.1, 10.0)}


def scan_cable_fill(workspace: Path, relative_path: str, unit: str, labels_path: str | None = None, exclude_regions: list[str] | None = None,
                    **params: Any) -> dict[str, Any]:
    if unit not in sm.UNIT_MM:
        raise BrainError('SCAN_UNIT', 'unit is required and must be one of mm, cm, m, in. It is never guessed.', {'given': unit})
    unknown = set(params) - set(DEFAULTS)
    if unknown:
        raise BrainError('CABLE_SETTINGS', 'Unknown settings.', {'unknown': sorted(unknown)})
    settings: dict[str, Any] = {}
    for name, default in DEFAULTS.items():
        val = params.get(name)
        val = default if val is None else val
        lo, hi = _RANGES[name]
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not lo <= val <= hi:
            raise BrainError('CABLE_SETTINGS', f'{name} must be in [{lo}, {hi}].', {'given': val})
        settings[name] = int(val) if name == 'degree' else float(val)
    if settings['min_area_mm2'] >= settings['max_area_mm2']:
        raise BrainError('CABLE_SETTINGS', 'min_area_mm2 must be smaller than max_area_mm2.')
    excl = list(DEFAULT_EXCLUDE) if exclude_regions is None else [str(x) for x in exclude_regions]
    src = safe_path(workspace, relative_path)
    if src.suffix.lower() != '.stl' or src.is_symlink() or not src.is_file():
        raise BrainError('SCAN_FILE', 'scan_cable_fill reads a regular .stl file inside the workspace.')
    if src.stat().st_size > sm.MAX_MESH_BYTES:
        raise BrainError('SCAN_FILE', 'The mesh file is too large.')
    lab = None
    if labels_path:
        lab = safe_path(workspace, labels_path)
        if lab.suffix.lower() not in ('.json', '.npz') or lab.is_symlink() or not lab.is_file():
            raise BrainError('CABLE_LABELS', 'labels_path must be a regular .json (region name -> face ids) or .npz (face_labels + codes) file inside the workspace.')
        if lab.stat().st_size > MAX_LABEL_BYTES:
            raise BrainError('CABLE_LABELS', 'The label file is too large.')
    sha, lsha = file_hash(src), (file_hash(lab) if lab else None)
    key = {'mesh': sha, 'labels': lsha, 'settings': settings, 'exclude': excl, 'unit': unit, 'version': CABLE_FILL_VERSION}
    cf_id = 'cf_' + digest(key)[:12]
    out = scan_dir(workspace, cf_id)
    if (out / REPORT).is_file():
        return _stored(out)
    if out.exists():
        raise BrainError('CABLE_OUTPUT_EXISTS', 'The output folder exists without a report; it is never overwritten. Move it away first.', {'folder': f'mouse/scans/{cf_id}'})
    python = find_scan_python(workspace)
    tmp = out.with_name(out.name + '.tmp-' + uuid.uuid4().hex[:8])
    tmp.mkdir(parents=True)
    try:
        req = {'input_path': str(src), 'labels_path': str(lab) if lab else None, 'unit_scale': sm.UNIT_MM[unit], 'out_dir': str(tmp / 'out'),
               'params': settings, 'exclude_regions': excl}
        (tmp / 'request.json').write_text(json.dumps(req), encoding='utf-8')
        try:
            proc = subprocess.run([str(python), '-I', str(WORKER), str(tmp / 'request.json')], capture_output=True, text=True, encoding='utf-8', errors='replace',
                                  timeout=TIMEOUT_S, cwd=str(tmp), env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        except subprocess.TimeoutExpired as exc:
            raise BrainError('CABLE_TIMEOUT', f'The cable fill worker exceeded {TIMEOUT_S} s and was stopped.') from exc
        except OSError as exc:
            raise BrainError('SCAN_PYTHON_MISSING', 'The scan python could not be started.', {'python': str(python), 'error': type(exc).__name__}) from exc
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith('{')]
        try:
            res = json.loads(lines[-1])
        except (IndexError, ValueError) as exc:
            raise BrainError('CABLE_WORKER', 'The cable fill worker returned no JSON result.', {'exit_code': proc.returncode, 'stderr_tail': proc.stderr[-800:]}) from exc
        if res.get('status') != 'OK':
            err = res.get('error') or {}
            raise BrainError(err.get('code', 'CABLE_WORKER'), err.get('message', 'The cable fill worker failed.'), {'python': str(python), 'details': err.get('details'), 'trace': err.get('trace')})
        final = tmp / 'out'
        report = build_report(res, final, cf_id, relative_path, labels_path, sha, lsha, {**settings, 'unit': unit, 'exclude_regions': excl}, str(python))
        atomic_json(final / REPORT, report)
        out.parent.mkdir(parents=True, exist_ok=True)
        final.replace(out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return report


def _check(ok: bool) -> str:
    return 'PASS' if ok else 'FAIL'


def build_report(res: dict[str, Any], folder: Path, cf_id: str, rel: str, labels_rel: str | None, sha: str, lsha: str | None, settings: dict[str, Any],
                 python: str) -> dict[str, Any]:
    base = f'mouse/scans/{cf_id}'
    files = res['files']
    outputs: dict[str, Any] = {}
    for name, item in files.items():
        outputs[name] = {'relative_path': f"{base}/{item['file']}", 'sha256': file_hash(folder / item['file'])}
        if 'faces' in item:
            outputs[name]['faces'] = item['faces']
    blockers = list(res['blocking'])
    pockets = res['pockets']
    filled = [q for q in pockets if 'patch' in q]
    smooth_ok = all(q.get('blocking') != 'CABLE_INFERRED_WALL_NOT_SMOOTH' for q in pockets)
    status = 'NOT_READY' if blockers else 'READY'
    return {
        'schema': 'scan_cable_fill_report/1', 'cf_id': cf_id, 'status': status, 'blocking_reasons': blockers, 'warnings': res['warnings'],
        'applied': res['applied'], 'no_op': (not pockets) and not blockers,
        'code_version': {'scan_cable_fill': CABLE_FILL_VERSION, 'worker': res['worker'], 'package': __version__},
        'source': {'relative_path': rel, 'sha256': sha, 'labels_relative_path': labels_rel, 'labels_sha256': lsha}, 'settings': settings,
        'units': {'input': settings['unit'], 'output': 'mm'}, 'params_used': res['params_used'], 'front': res['front'], 'grid': res['grid'],
        'trusted_cells': res['trusted_cells'], 'candidates': res.get('candidates'), 'pockets': pockets,
        'summary': {'pockets_found': len(pockets), 'pockets_filled': len(filled), 'fill_area_yz_mm2': round(sum(q['area_yz_mm2'] for q in filled), 2),
                    'fill_depth_max_mm': max([q['fill_depth_mm']['max'] or 0 for q in filled], default=None),
                    'wall_fit_p95_mm': max([q['ring_fit']['p95_mm'] for q in filled], default=None),
                    'wall_vs_surrounding_p95_mm': max([q['wall_vs_surrounding']['p95_mm'] for q in filled], default=None),
                    'inferred_min_radius_mm': min([q['inferred_min_radius_mm'] for q in filled if q['inferred_min_radius_mm'] is not None], default=None)},
        'mesh': res.get('mesh'), 'outputs': outputs, 'seconds': res['seconds'],
        'checks': {'front_wall_found': _check('CABLE_FRONT_WALL_NOT_FOUND' not in blockers), 'inferred_wall_smooth': _check(smooth_ok),
                   'patch_loop_simple': _check('CABLE_LOOP_NOT_SIMPLE' not in blockers and 'CABLE_TRIANGULATION' not in blockers),
                   'ring_complete': _check('CABLE_RING_INCOMPLETE' not in blockers), 'pocket_size': _check('CABLE_POCKET_TOO_LARGE' not in blockers),
                   'physical_function': 'UNVERIFIED'},
        'downstream': {'mesh': (outputs.get('filled') or {}).get('relative_path'), 'labels': (outputs.get('labels') or {}).get('relative_path'),
                       'note': 'READY only: pass filled.stl + labels (face order changed: kept faces in input order, then the patch) to brain_mouse_scan_symmetrise, '
                               'brain_mouse_shell_fit (relative_path = symmetrised filled mesh, labels_path = these labels) and brain_mouse_plate_side (outline_path). '
                               'NOT_READY writes no filled mesh: keep the unfilled chain.'},
        'limits': ['The front wall must be a height field x(y, z) around the pocket (standard frame, x front); a pocket on a strongly curved corner is NOT_READY (ring or smoothness gate).',
                   'Only recesses at least min_width_mm wide in both directions are filled; grooves and parting slits are kept.',
                   'The fill is the inferred design wall, not the scanned pocket: the pocket geometry is deliberately discarded.'],
        'scan_python': python, 'execution': {'completed': True},
    }


def _stored(folder: Path) -> dict[str, Any]:
    rep = json_load(folder / REPORT)
    for item in rep['outputs'].values():
        p = folder / Path(item['relative_path']).name
        if not p.is_file() or file_hash(p) != item['sha256']:
            raise BrainError('CABLE_OUTPUT_CHANGED', 'A stored output no longer matches its recorded hash; it is not overwritten.', {'file': p.name})
    return {**rep, 'cached': True}


__all__ = ['scan_cable_fill', 'build_report', 'CABLE_FILL_VERSION']
