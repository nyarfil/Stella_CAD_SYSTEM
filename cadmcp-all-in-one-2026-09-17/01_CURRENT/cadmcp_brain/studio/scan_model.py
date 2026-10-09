"""Scan intake, step 1: PLY -> welded, cleaned, decimated, watertight STL (brain_mouse_scan_model).

The mesh work runs in a SEPARATE python (a virtualenv with numpy, scipy and PyMeshLab) as a subprocess with a
JSON request/result. PyMeshLab is GPL-3.0 and is never imported into this process (scan_model_worker.py is the only
file that names it). Units are explicit. The source file is never modified; outputs are written once under
mouse/scans/<model_id>/ and never overwritten (the same inputs and settings return the stored report).
Every number is measured against the exact-position-welded original; thin-wall zones are reported separately.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any
from . import scan_mesh as sm
from .. import __version__
from ..errors import BrainError
from ..req2cad.common import atomic_json, json_load
from ..util import digest, file_hash, safe_path
from .scan_shell import scan_dir

SCAN_MODEL_VERSION = 'B1.0'
WORKER = Path(__file__).with_name('scan_model_worker.py')
ENV_PYTHON = 'CADMCP_SCAN_PYTHON'
TIMEOUT_S = 3600
REPORT = 'scan_model_report.json'
FALLBACKS = (Path('V:/mouse/.venv-scan'),)    # owner machine default; any other install sets CADMCP_SCAN_PYTHON


def _venv_python(root: Path) -> Path | None:
    for rel in ('Scripts/python.exe', 'bin/python'):
        if (root / rel).is_file():
            return root / rel
    return None


def find_scan_python(workspace: Path) -> Path:
    """CADMCP_SCAN_PYTHON, else a .venv-scan next to the workspace or any parent, else the owner default, else PATH."""
    env = os.environ.get(ENV_PYTHON)
    if env:
        p = Path(env)
        if not p.is_file():
            raise BrainError('SCAN_PYTHON_MISSING', f'{ENV_PYTHON} does not point to an existing python executable.', {'value': env})
        return p
    for base in [Path(workspace).resolve(), *Path(workspace).resolve().parents]:
        found = _venv_python(base / '.venv-scan')
        if found:
            return found
    for root in FALLBACKS:
        found = _venv_python(root)
        if found:
            return found
    which = shutil.which('cadmcp-scan-python')
    if which:
        return Path(which)
    raise BrainError('SCAN_PYTHON_MISSING', f'No scan python found. Create a virtualenv with numpy, scipy and pymeshlab and set {ENV_PYTHON} to its python executable. '
                     'PyMeshLab is GPL-3.0 and is deliberately kept out of the server process.', {'env': ENV_PYTHON})


def _check(ok: bool) -> str:
    return 'PASS' if ok else 'FAIL'


def _topology_ok(t: dict[str, Any]) -> bool:
    return bool(t['faces'] > 0 and t['watertight'] and t['manifold'] and t['winding_consistent'] and t['signed_volume_mm3'] > 0 and t['components'] == 1)


def scan_model(workspace: Path, relative_path: str, unit: str, target_max_error_mm: float = 0.05, hard_limit_error_mm: float = 0.10,
               min_component_faces: int = 100, close_holes_max_edges: int = 30, thin_wall_mm: float = 1.0) -> dict[str, Any]:
    if unit not in sm.UNIT_MM:
        raise BrainError('SCAN_UNIT', 'unit is required and must be one of mm, cm, m, in. It is never guessed.', {'given': unit})
    for name, val in (('target_max_error_mm', target_max_error_mm), ('hard_limit_error_mm', hard_limit_error_mm), ('thin_wall_mm', thin_wall_mm)):
        if isinstance(val, bool) or not 0 < val <= 5:
            raise BrainError('SCAN_MODEL_SETTINGS', f'{name} must be in (0, 5] mm.', {'given': val})
    if target_max_error_mm > hard_limit_error_mm:
        raise BrainError('SCAN_MODEL_SETTINGS', 'target_max_error_mm must not exceed hard_limit_error_mm.')
    if not 1 <= min_component_faces <= 100000 or not 0 <= close_holes_max_edges <= 1000:
        raise BrainError('SCAN_MODEL_SETTINGS', 'min_component_faces must be 1..100000 and close_holes_max_edges 0..1000.')
    src = safe_path(workspace, relative_path)
    if src.suffix.lower() != '.ply' or src.is_symlink() or not src.is_file():
        raise BrainError('SCAN_FILE', 'scan_model reads a regular .ply file inside the workspace.')
    if src.stat().st_size > sm.MAX_MESH_BYTES:
        raise BrainError('SCAN_FILE', 'Scan file is too large.')
    sha = file_hash(src)
    settings = {'unit': unit, 'target_max_error_mm': float(target_max_error_mm), 'hard_limit_error_mm': float(hard_limit_error_mm),
                'min_component_faces': int(min_component_faces), 'close_holes_max_edges': int(close_holes_max_edges), 'thin_wall_mm': float(thin_wall_mm)}
    model_id = 'model_' + digest({'sha256': sha, 'settings': settings, 'version': SCAN_MODEL_VERSION})[:12]
    out = scan_dir(workspace, model_id)
    if (out / REPORT).is_file():
        return _stored(out, model_id)
    if out.exists():
        raise BrainError('SCAN_MODEL_OUTPUT_EXISTS', 'The output folder exists without a report; it is never overwritten. Move it away first.', {'folder': f'mouse/scans/{model_id}'})
    python = find_scan_python(workspace)
    tmp = out.with_name(out.name + '.tmp-' + uuid.uuid4().hex[:8])
    tmp.mkdir(parents=True)
    try:
        req = {**{k: v for k, v in settings.items() if k != 'thin_wall_mm'}, 'thin_wall_mm': settings['thin_wall_mm'], 'zone_radius_mm': 1.5,
               'input_path': str(src), 'out_dir': str(tmp / 'out')}
        (tmp / 'request.json').write_text(json.dumps(req), encoding='utf-8')
        try:
            proc = subprocess.run([str(python), '-I', str(WORKER), str(tmp / 'request.json')], capture_output=True, text=True, encoding='utf-8',
                                  errors='replace', timeout=TIMEOUT_S, cwd=str(tmp), env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        except subprocess.TimeoutExpired as exc:
            raise BrainError('SCAN_MODEL_TIMEOUT', f'The scan worker exceeded {TIMEOUT_S} s and was stopped.') from exc
        except OSError as exc:
            raise BrainError('SCAN_PYTHON_MISSING', 'The scan python could not be started.', {'python': str(python), 'error': type(exc).__name__}) from exc
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith('{')]
        try:
            res = json.loads(lines[-1])
        except (IndexError, ValueError) as exc:
            raise BrainError('SCAN_MODEL_WORKER', 'The scan worker returned no JSON result.', {'exit_code': proc.returncode, 'stderr_tail': proc.stderr[-800:]}) from exc
        if res.get('status') != 'OK':
            err = res.get('error') or {}
            raise BrainError(err.get('code', 'SCAN_MODEL_WORKER'), err.get('message', 'The scan worker failed.'), {'python': str(python), 'trace': err.get('trace')})
        report = _report(res, tmp / 'out', model_id, relative_path, sha, settings, python)
        final = tmp / 'out'
        atomic_json(final / REPORT, report)
        out.parent.mkdir(parents=True, exist_ok=True)
        final.replace(out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return report


def _report(res: dict[str, Any], folder: Path, model_id: str, rel: str, sha: str, settings: dict[str, Any], python: Path) -> dict[str, Any]:
    base = f'mouse/scans/{model_id}'
    files: dict[str, Any] = {}
    full = res['cleaned_fullres']
    files['cleaned_fullres'] = {'relative_path': f"{base}/{full['file']}", 'sha256': file_hash(folder / full['file']), 'faces': full['faces'], 'topology': full['topology_on_disk']}
    outputs: dict[str, Any] = {}
    for key in ('target', 'hard_limit'):
        o = res['outputs'].get(key)
        if not o:
            continue
        outputs[key] = {'relative_path': f"{base}/{o['file']}", 'sha256': file_hash(folder / o['file']), 'faces': o['faces'], 'error_vs_welded_original_mm': o['error'],
                        'small_holes_patched': o['small_holes_patched'], 'topology': o['topology_on_disk'], 'worst_non_budget_locations': o['worst_non_budget_locations']}
    pick = 'target' if 'target' in outputs else ('hard_limit' if 'hard_limit' in outputs else None)
    blockers: list[str] = []
    if pick is None:
        blockers.append('ERROR_BUDGET_NOT_MET')
    else:
        t = outputs[pick]['topology']
        if not _topology_ok(t):
            blockers.append('OUTPUT_NOT_WATERTIGHT_MANIFOLD')
    if not _topology_ok(full['topology_on_disk']):
        blockers.append('CLEANED_FULLRES_NOT_WATERTIGHT_MANIFOLD')
    weld = res['weld']
    t0 = weld['topology_after_weld']
    warnings: list[dict[str, Any]] = []
    if pick == 'hard_limit':
        warnings.append({'code': 'TARGET_NOT_MET', 'note': f"No face count met the {settings['target_max_error_mm']} mm target; the {settings['hard_limit_error_mm']} mm hard limit output is provided."})
    if t0['boundary_edges']:
        warnings.append({'code': 'ORIGINAL_HAS_OPEN_EDGES', 'boundary_edges': t0['boundary_edges'], 'note': 'The welded original is not closed; holes were closed up to close_holes_max_edges.'})
    if weld['vertices_after_exact_weld'] < weld['vertices_as_loaded']:
        warnings.append({'code': 'VERTICES_WELDED_BY_POSITION', 'before': weld['vertices_as_loaded'], 'after': weld['vertices_after_exact_weld'],
                         'note': 'Per-UV-corner duplicate vertices were merged first; otherwise they appear as fake seams.'})
    zone = res['thin_wall']
    return {
        'schema': 'scan_model_report/1', 'model_id': model_id, 'status': 'NOT_READY' if blockers else 'READY', 'blocking_reasons': blockers, 'warnings': warnings,
        'code_version': {'scan_model': SCAN_MODEL_VERSION, 'worker': res['worker'], 'package': __version__, 'pymeshlab': res.get('pymeshlab'), 'scan_python': res.get('python')},
        'source': {'relative_path': rel, 'sha256': sha}, 'settings': settings, 'units': {'input': settings['unit'], 'output': 'mm'},
        'extent_mm': res['extent_mm'], 'weld': weld, 'cleanup': res['cleanup'], 'cleaned_fullres': files['cleaned_fullres'], 'outputs': outputs,
        'recommended': pick, 'target_met': 'target' in outputs,
        'error_definition': 'Two-sided vertex-sampled Hausdorff (exact point-to-triangle) between the decimated mesh and the exact-position-welded original, in mm. '
                            'The budget statistics exclude thin-wall zones; those are reported as non_budget_zone and are NOT part of the budget.',
        'thin_wall_zone': zone, 'search_log': res['search_log'], 'seconds': res['seconds'],
        'checks': {'watertight': _check(pick is not None and outputs[pick]['topology']['watertight']), 'manifold': _check(pick is not None and outputs[pick]['topology']['manifold']),
                   'winding_consistent': _check(pick is not None and outputs[pick]['topology']['winding_consistent']),
                   'single_component': _check(pick is not None and outputs[pick]['topology']['components'] == 1),
                   'error_budget': _check('target' in outputs), 'error_hard_limit': _check(pick is not None), 'self_intersection': 'UNVERIFIED'},
        'next': ('Run brain_mouse_prepare_scan on %s with unit "mm", then brain_mouse_recognize_regions (and brain_mouse_recognize_shell) on the prepared scan_id (the full-resolution cleaned STL gives the best region boundaries).'
                 % (outputs[pick]['relative_path'] if pick else files['cleaned_fullres']['relative_path'])),
        'scan_python': str(python), 'execution': {'completed': True},
    }


def _stored(folder: Path, model_id: str) -> dict[str, Any]:
    rep = json_load(folder / REPORT)
    names = [rep['cleaned_fullres']] + list(rep['outputs'].values())
    for item in names:
        p = folder / Path(item['relative_path']).name
        if not p.is_file() or file_hash(p) != item['sha256']:
            raise BrainError('SCAN_MODEL_OUTPUT_CHANGED', 'A stored output no longer matches its recorded hash; it is not overwritten.', {'file': p.name})
    return {**rep, 'cached': True}


if __name__ == '__main__':       # pragma: no cover
    print(sys.argv)
