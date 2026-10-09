"""Click-panel groove rebuild on a welded scan mesh (brain_mouse_scan_click_grooves).

Input: a welded, watertight, outward-oriented STL (standard frame: x front, y left, z up, mm after the unit factor) and the face labels of the
regions (left click, right click, wheel; optional palm shell, plates, side buttons). The geometry work runs in the SEPARATE scan python as a
subprocess with a JSON request / result (scan_click_grooves_worker.py: numpy, scipy, trimesh, shapely, manifold3d). PyMeshLab is never involved.
The source files are never modified; outputs are written once under mouse/scans/<groove_id>/ and never overwritten (the same inputs and
settings return the stored report). Nothing is written into the repository or the project folders.
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
from .scan_click_grooves_worker import DEFAULTS
from .scan_model import ENV_PYTHON, find_scan_python
from .scan_shell import scan_dir
from .. import __version__
from ..errors import BrainError
from ..req2cad.common import atomic_json, json_load
from ..util import digest, file_hash, safe_path

CLICK_GROOVES_VERSION = 'G1.0'
WORKER = Path(__file__).with_name('scan_click_grooves_worker.py')
TIMEOUT_S = 1800
REPORT = 'click_grooves_report.json'
MAX_LABEL_BYTES = 64 * 1024 * 1024
_RANGES = {'slot_width_mm': (0.1, 3.0), 'slot_depth_mm': (0.2, 10.0), 'panel_overlap_mm': (0.0, 1.0), 'perimeter_clearance_mm': (0.0, 0.5),
           'fit_tolerance_mm': (0.02, 1.0), 'min_wall_mm': (0.0, 5.0), 'gap_clear_mm': (0.5, 6.0), 'gap_front_margin_mm': (0.0, 8.0), 'gap_overshoot_mm': (0.0, 3.0)}


def scan_click_grooves(workspace: Path, relative_path: str, labels_path: str, unit: str, slot_width_mm: float = DEFAULTS['slot_width_mm'],
                       slot_depth_mm: float = DEFAULTS['slot_depth_mm'], panel_overlap_mm: float = DEFAULTS['panel_overlap_mm'],
                       perimeter_clearance_mm: float = DEFAULTS['perimeter_clearance_mm'], fit_tolerance_mm: float = DEFAULTS['fit_tolerance_mm'],
                       fillet_radius_mm: float | None = None, min_wall_mm: float = DEFAULTS['min_wall_mm'], rebuild_window: bool = True, overlay: bool = True,
                       gap_clear_mm: float = DEFAULTS['gap_clear_mm'], gap_front_margin_mm: float = DEFAULTS['gap_front_margin_mm'],
                       gap_overshoot_mm: float = DEFAULTS['gap_overshoot_mm']) -> dict[str, Any]:
    if unit not in sm.UNIT_MM:
        raise BrainError('SCAN_UNIT', 'unit is required and must be one of mm, cm, m, in. It is never guessed.', {'given': unit})
    given = {'slot_width_mm': slot_width_mm, 'slot_depth_mm': slot_depth_mm, 'panel_overlap_mm': panel_overlap_mm, 'perimeter_clearance_mm': perimeter_clearance_mm,
             'fit_tolerance_mm': fit_tolerance_mm, 'min_wall_mm': min_wall_mm, 'gap_clear_mm': gap_clear_mm, 'gap_front_margin_mm': gap_front_margin_mm,
             'gap_overshoot_mm': gap_overshoot_mm}
    for name, val in given.items():
        lo, hi = _RANGES[name]
        if isinstance(val, bool) or not lo <= val <= hi:
            raise BrainError('CLICK_GROOVE_SETTINGS', f'{name} must be in [{lo}, {hi}] mm.', {'given': val})
    if fillet_radius_mm is not None and (isinstance(fillet_radius_mm, bool) or not 0.2 <= fillet_radius_mm <= 20):
        raise BrainError('CLICK_GROOVE_SETTINGS', 'fillet_radius_mm must be omitted (fitted to the outline) or in [0.2, 20] mm.', {'given': fillet_radius_mm})
    src = safe_path(workspace, relative_path)
    if src.suffix.lower() != '.stl' or src.is_symlink() or not src.is_file():
        raise BrainError('SCAN_FILE', 'scan_click_grooves reads a regular .stl file inside the workspace.')
    if src.stat().st_size > sm.MAX_MESH_BYTES:
        raise BrainError('SCAN_FILE', 'The mesh file is too large.')
    lab = safe_path(workspace, labels_path)
    if lab.suffix.lower() not in ('.json', '.npz') or lab.is_symlink() or not lab.is_file():
        raise BrainError('CLICK_GROOVE_LABELS', 'labels_path must be a regular .json (region name -> face ids) or .npz (face_labels + codes) file inside the workspace.')
    if lab.stat().st_size > MAX_LABEL_BYTES:
        raise BrainError('CLICK_GROOVE_LABELS', 'The label file is too large.')
    settings = {**given, 'fillet_radius_mm': None if fillet_radius_mm is None else float(fillet_radius_mm), 'rebuild_window': bool(rebuild_window), 'overlay': bool(overlay),
                'unit': unit}
    settings = {k: (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for k, v in settings.items()}
    sha, lsha = file_hash(src), file_hash(lab)
    groove_id = 'grv_' + digest({'mesh': sha, 'labels': lsha, 'settings': settings, 'version': CLICK_GROOVES_VERSION})[:12]
    out = scan_dir(workspace, groove_id)
    if (out / REPORT).is_file():
        return _stored(out)
    if out.exists():
        raise BrainError('CLICK_GROOVE_OUTPUT_EXISTS', 'The output folder exists without a report; it is never overwritten. Move it away first.', {'folder': f'mouse/scans/{groove_id}'})
    python = find_scan_python(workspace)
    tmp = out.with_name(out.name + '.tmp-' + uuid.uuid4().hex[:8])
    tmp.mkdir(parents=True)
    try:
        req = {'input_path': str(src), 'labels_path': str(lab), 'unit_scale': sm.UNIT_MM[unit], 'out_dir': str(tmp / 'out'),
               'params': {**{k: v for k, v in settings.items() if k != 'unit'}}}
        (tmp / 'request.json').write_text(json.dumps(req), encoding='utf-8')
        try:
            proc = subprocess.run([str(python), '-I', str(WORKER), str(tmp / 'request.json')], capture_output=True, text=True, encoding='utf-8', errors='replace',
                                  timeout=TIMEOUT_S, cwd=str(tmp), env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        except subprocess.TimeoutExpired as exc:
            raise BrainError('CLICK_GROOVE_TIMEOUT', f'The groove worker exceeded {TIMEOUT_S} s and was stopped.') from exc
        except OSError as exc:
            raise BrainError('SCAN_PYTHON_MISSING', 'The scan python could not be started.', {'python': str(python), 'error': type(exc).__name__}) from exc
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith('{')]
        try:
            res = json.loads(lines[-1])
        except (IndexError, ValueError) as exc:
            raise BrainError('CLICK_GROOVE_WORKER', 'The groove worker returned no JSON result.', {'exit_code': proc.returncode, 'stderr_tail': proc.stderr[-800:]}) from exc
        if res.get('status') != 'OK':
            err = res.get('error') or {}
            raise BrainError(err.get('code', 'CLICK_GROOVE_WORKER'), err.get('message', 'The groove worker failed.'), {'python': str(python), 'details': err.get('details'), 'trace': err.get('trace')})
        final = tmp / 'out'
        report = _report(res, final, groove_id, relative_path, labels_path, sha, lsha, settings, python)
        atomic_json(final / REPORT, report)
        out.parent.mkdir(parents=True, exist_ok=True)
        final.replace(out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return report


def _check(ok: bool) -> str:
    return 'PASS' if ok else 'FAIL'


def _report(res: dict[str, Any], folder: Path, groove_id: str, rel: str, labels_rel: str, sha: str, lsha: str, settings: dict[str, Any], python: Path) -> dict[str, Any]:
    base = f'mouse/scans/{groove_id}'
    files = res['files']
    outputs = {'combined': {'relative_path': f"{base}/{files['combined']['file']}", 'sha256': file_hash(folder / files['combined']['file']), 'faces': files['combined']['faces']},
               'regions': {k: {'relative_path': f"{base}/{v['file']}", 'sha256': file_hash(folder / v['file']), 'faces': v['faces']} for k, v in files['regions'].items()}}
    if files.get('overlay'):
        outputs['overlay'] = {'relative_path': f"{base}/{files['overlay']['file']}", 'sha256': file_hash(folder / files['overlay']['file'])}
    m = res['metrics']
    blockers: list[str] = []
    if not m['watertight']['after']:
        blockers.append('RESULT_NOT_WATERTIGHT')
    if m['bodies']['components'] != 1 or not m['bodies']['winding_consistent']:
        blockers.append('RESULT_NOT_ONE_BODY')
    if m['encroachment']['max_inside_after_mm'] > 1e-3:
        blockers.append('PERIMETER_SLOT_ENCROACHES_PANEL_EDGE')
    widths = [v['width_mm_p5_50_95'][1] for k, v in m['slot_measure'].items() if k == 'perimeter']
    if not widths:
        blockers.append('NO_SLOT_MEASURED')
    return {
        'schema': 'scan_click_grooves_report/1', 'groove_id': groove_id, 'status': 'NOT_READY' if blockers else 'READY', 'blocking_reasons': blockers, 'warnings': res['warnings'],
        'code_version': {'scan_click_grooves': CLICK_GROOVES_VERSION, 'worker': res['worker'], 'package': __version__, 'libs': res.get('libs')},
        'source': {'relative_path': rel, 'sha256': sha, 'labels_relative_path': labels_rel, 'labels_sha256': lsha}, 'settings': settings, 'units': {'input': settings['unit'], 'output': 'mm'},
        'params_used': res['params_used'], 'fit': res['fit'], 'metrics': m, 'outputs': outputs, 'seconds': res['seconds'],
        'checks': {'watertight_after': _check(m['watertight']['after']), 'single_body': _check(m['bodies']['components'] == 1), 'winding_consistent': _check(m['bodies']['winding_consistent']),
                   'no_perimeter_encroachment': _check(m['encroachment']['max_inside_after_mm'] <= 1e-3),
                   'cut_through': 'REPORTED' if any(v['cut_through_runs'] for v in m['cut_through'].values()) else 'NONE', 'physical_function': 'UNVERIFIED'},
        'limits': ['Surface mesh only: the click switches, hinges and wall thickness behind the slots are not known; cut-through is reported, never prevented unless min_wall_mm > 0.',
                   'The mesh must already be in the standard frame (x front, y left, z up, bottom plate at z 0 mm) and welded; the labels come from brain_mouse_recognize_regions / recognize_shell or a manual list.',
                   'No B-rep or CAD file is generated.'],
        'scan_python': str(python), 'execution': {'completed': True},
    }


def _stored(folder: Path) -> dict[str, Any]:
    rep = json_load(folder / REPORT)
    items = [rep['outputs']['combined'], *rep['outputs']['regions'].values(), *([rep['outputs']['overlay']] if 'overlay' in rep['outputs'] else [])]
    for item in items:
        p = folder / Path(item['relative_path']).name
        if not p.is_file() or file_hash(p) != item['sha256']:
            raise BrainError('CLICK_GROOVE_OUTPUT_CHANGED', 'A stored output no longer matches its recorded hash; it is not overwritten.', {'file': p.name})
    return {**rep, 'cached': True}


__all__ = ['scan_click_grooves', 'ENV_PYTHON', 'CLICK_GROOVES_VERSION']
