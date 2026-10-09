"""Bottom-plate flush of a welded scan mesh (brain_mouse_scan_flush).

Input: a welded, outward-oriented STL in the standard frame (x front, y left, z up; mm after the unit factor) and, optionally, the
label file with the bottom_plate region. The plate plane is fitted (area-weighted RANSAC + refit), the tilt is removed and the plate is put on
z = 0; the rigid transform and the residual statistics are returned. Face order is unchanged, so the same labels stay valid for the flushed mesh
(brain_mouse_scan_click_grooves expects exactly this frame). The work runs in the SEPARATE scan python as a subprocess (scan_flush_worker.py:
numpy, trimesh). The source is never modified; outputs go once under mouse/scans/<flush_id>/ and are never overwritten.
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
from .scan_flush_worker import DEFAULTS
from .scan_model import ENV_PYTHON, find_scan_python
from .scan_shell import scan_dir
from .. import __version__
from ..errors import BrainError
from ..req2cad.common import atomic_json, json_load
from ..util import digest, file_hash, safe_path

FLUSH_VERSION = 'F1.0'
WORKER = Path(__file__).with_name('scan_flush_worker.py')
TIMEOUT_S = 600
REPORT = 'flush_report.json'
MAX_LABEL_BYTES = 64 * 1024 * 1024
_RANGES = {'plate_tolerance_mm': (0.01, 1.0), 'min_down_nz': (0.5, 0.999), 'ransac_iterations': (100, 50000), 'max_tilt_deg': (0.1, 45.0)}
READY_MAX_TILT_AFTER_DEG = 0.05
READY_MIN_WITHIN_PCT = 50.0


def scan_flush(workspace: Path, relative_path: str, unit: str, labels_path: str | None = None, plate_tolerance_mm: float = DEFAULTS['plate_tolerance_mm'],
               min_down_nz: float = DEFAULTS['min_down_nz'], ransac_iterations: int = DEFAULTS['ransac_iterations'], max_tilt_deg: float = DEFAULTS['max_tilt_deg']) -> dict[str, Any]:
    if unit not in sm.UNIT_MM:
        raise BrainError('SCAN_UNIT', 'unit is required and must be one of mm, cm, m, in. It is never guessed.', {'given': unit})
    given = {'plate_tolerance_mm': plate_tolerance_mm, 'min_down_nz': min_down_nz, 'ransac_iterations': ransac_iterations, 'max_tilt_deg': max_tilt_deg}
    for name, val in given.items():
        lo, hi = _RANGES[name]
        if isinstance(val, bool) or not lo <= val <= hi:
            raise BrainError('FLUSH_SETTINGS', f'{name} must be in [{lo}, {hi}].', {'given': val})
    src = safe_path(workspace, relative_path)
    if src.suffix.lower() != '.stl' or src.is_symlink() or not src.is_file():
        raise BrainError('SCAN_FILE', 'scan_flush reads a regular .stl file inside the workspace.')
    if src.stat().st_size > sm.MAX_MESH_BYTES:
        raise BrainError('SCAN_FILE', 'The mesh file is too large.')
    lab = None
    if labels_path:
        lab = safe_path(workspace, labels_path)
        if lab.suffix.lower() not in ('.json', '.npz') or lab.is_symlink() or not lab.is_file():
            raise BrainError('FLUSH_LABELS', 'labels_path must be a regular .json (region name -> face ids) or .npz (face_labels + codes) file inside the workspace.')
        if lab.stat().st_size > MAX_LABEL_BYTES:
            raise BrainError('FLUSH_LABELS', 'The label file is too large.')
    settings = {'plate_tolerance_mm': float(plate_tolerance_mm), 'min_down_nz': float(min_down_nz), 'ransac_iterations': int(ransac_iterations), 'max_tilt_deg': float(max_tilt_deg), 'unit': unit}
    sha, lsha = file_hash(src), (file_hash(lab) if lab else None)
    flush_id = 'fl_' + digest({'mesh': sha, 'labels': lsha, 'settings': settings, 'version': FLUSH_VERSION})[:12]
    out = scan_dir(workspace, flush_id)
    if (out / REPORT).is_file():
        return _stored(out)
    if out.exists():
        raise BrainError('FLUSH_OUTPUT_EXISTS', 'The output folder exists without a report; it is never overwritten. Move it away first.', {'folder': f'mouse/scans/{flush_id}'})
    python = find_scan_python(workspace)
    tmp = out.with_name(out.name + '.tmp-' + uuid.uuid4().hex[:8])
    tmp.mkdir(parents=True)
    try:
        req = {'input_path': str(src), 'labels_path': str(lab) if lab else None, 'unit_scale': sm.UNIT_MM[unit], 'out_dir': str(tmp / 'out'),
               'params': {k: v for k, v in settings.items() if k != 'unit'}}
        (tmp / 'request.json').write_text(json.dumps(req), encoding='utf-8')
        try:
            proc = subprocess.run([str(python), '-I', str(WORKER), str(tmp / 'request.json')], capture_output=True, text=True, encoding='utf-8', errors='replace',
                                  timeout=TIMEOUT_S, cwd=str(tmp), env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        except subprocess.TimeoutExpired as exc:
            raise BrainError('FLUSH_TIMEOUT', f'The flush worker exceeded {TIMEOUT_S} s and was stopped.') from exc
        except OSError as exc:
            raise BrainError('SCAN_PYTHON_MISSING', 'The scan python could not be started.', {'python': str(python), 'error': type(exc).__name__}) from exc
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith('{')]
        try:
            res = json.loads(lines[-1])
        except (IndexError, ValueError) as exc:
            raise BrainError('FLUSH_WORKER', 'The flush worker returned no JSON result.', {'exit_code': proc.returncode, 'stderr_tail': proc.stderr[-800:]}) from exc
        if res.get('status') != 'OK':
            err = res.get('error') or {}
            raise BrainError(err.get('code', 'FLUSH_WORKER'), err.get('message', 'The flush worker failed.'), {'python': str(python), 'details': err.get('details'), 'trace': err.get('trace')})
        final = tmp / 'out'
        report = _report(res, final, flush_id, relative_path, labels_path, sha, lsha, settings, python)
        atomic_json(final / REPORT, report)
        out.parent.mkdir(parents=True, exist_ok=True)
        final.replace(out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return report


def _check(ok: bool) -> str:
    return 'PASS' if ok else 'FAIL'


def _report(res: dict[str, Any], folder: Path, flush_id: str, rel: str, labels_rel: str | None, sha: str, lsha: str | None, settings: dict[str, Any], python: Path) -> dict[str, Any]:
    base = f'mouse/scans/{flush_id}'
    files = res['files']
    outputs = {'flushed': {'relative_path': f"{base}/{files['flushed']['file']}", 'sha256': file_hash(folder / files['flushed']['file']), 'faces': files['flushed']['faces']},
               'transform': {'relative_path': f"{base}/{files['transform']['file']}", 'sha256': file_hash(folder / files['transform']['file'])}}
    if files.get('labels'):
        outputs['labels'] = {'relative_path': f"{base}/{files['labels']['file']}", 'sha256': file_hash(folder / files['labels']['file'])}
    after, fit = res['after'], res['fit']
    blockers: list[str] = []
    if after['fit_tilt_deg'] > READY_MAX_TILT_AFTER_DEG:
        blockers.append('RESIDUAL_TILT_TOO_LARGE')
    if after['within_tol_pct_area'] < READY_MIN_WITHIN_PCT:
        blockers.append('PLATE_NOT_FLAT_ON_Z0')
    return {
        'schema': 'scan_flush_report/1', 'flush_id': flush_id, 'status': 'NOT_READY' if blockers else 'READY', 'blocking_reasons': blockers, 'warnings': res['warnings'],
        'code_version': {'scan_flush': FLUSH_VERSION, 'worker': res['worker'], 'package': __version__},
        'source': {'relative_path': rel, 'sha256': sha, 'labels_relative_path': labels_rel, 'labels_sha256': lsha}, 'settings': settings, 'units': {'input': settings['unit'], 'output': 'mm'},
        'params_used': res['params_used'], 'plane_fit': fit, 'transform': res['transform'],
        'residual': {'tilt_before_deg': fit['tilt_before_deg'], 'tilt_after_deg': after['fit_tilt_deg'], 'plate_within_tolerance_pct_area': after['within_tol_pct_area'],
                     'tolerance_mm': settings['plate_tolerance_mm'], 'rms_z_mm': after.get('rms_z_mm'), 'mean_z_mm': after.get('mean_z_mm'), 'plane_fit_area_mm2': fit['inlier_area_mm2'],
                     'plane_fit_rms_mm': fit['rms_mm']},
        'extent': res['extent'], 'mesh': res['mesh'], 'outputs': outputs, 'seconds': res['seconds'],
        'checks': {'residual_tilt': _check(after['fit_tilt_deg'] <= READY_MAX_TILT_AFTER_DEG), 'plate_on_z0': _check(after['within_tol_pct_area'] >= READY_MIN_WITHIN_PCT),
                   'watertight_after': 'PASS' if res['mesh']['watertight'] else 'NOT_APPLICABLE', 'physical_function': 'UNVERIFIED'},
        'downstream': {'mesh': outputs['flushed']['relative_path'], 'labels': (outputs.get('labels') or {}).get('relative_path'),
                       'note': 'Pass the flushed mesh (and the copied labels, same face order) to brain_mouse_scan_click_grooves; its standard frame is x front, y left, z up, plate at z 0.'},
        'limits': ['Rigid transform only (rotation about the horizontal axis through the plate plane, then a z shift): shape, scale and face order are unchanged.',
                   'Features that protrude below the plate (skates, feet) end up at negative z and are reported as protrusion_below_plate_mm, never clipped.',
                   'The mesh must already be in the standard frame (x front, y left, z up); no frame detection is done here.'],
        'scan_python': str(python), 'execution': {'completed': True},
    }


def _stored(folder: Path) -> dict[str, Any]:
    rep = json_load(folder / REPORT)
    for item in rep['outputs'].values():
        p = folder / Path(item['relative_path']).name
        if not p.is_file() or file_hash(p) != item['sha256']:
            raise BrainError('FLUSH_OUTPUT_CHANGED', 'A stored output no longer matches its recorded hash; it is not overwritten.', {'file': p.name})
    return {**rep, 'cached': True}


__all__ = ['scan_flush', 'ENV_PYTHON', 'FLUSH_VERSION']
