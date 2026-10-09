"""Scan intake, step 3: groove re-synthesis and zone repair on a READY scan (brain_mouse_scan_clean).

Thin in-process module; the geometry runs in scan_clean_worker.py in a SEPARATE python (numpy, scipy, PyMeshLab) exactly like
scan_model.py: JSON request / result, units explicit (everything is mm in the prepared-scan frame), the source is never modified, outputs
are written once under mouse/scans/<clean_id>/ and never overwritten (the same inputs and settings return the stored report), checks are
PASS / FAIL / UNVERIFIED and stop codes replace loosening.
mode 'grooves': narrow grooves the scan under-resolves (0.6-1.2 mm wide, about the mesh edge length) are re-cut from a fitted parametric
  model (3D B-spline centre line + piecewise width / depth profile). Seeds come from the region boundaries of brain_mouse_recognize_regions,
  or from the `grooves` argument.
mode 'zones': explicit boxes / face selections are filled from their surroundings (topology preserving), displacement capped.
"""
from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any
import numpy as np
from . import scan_clean_seeds, scan_model, scan_regions, scan_shell
from . import scan_mesh as sm
from .. import __version__
from ..errors import BrainError
from ..req2cad.common import atomic_json, json_load
from ..util import digest, file_hash
from .scan_shell import scan_dir

SCAN_CLEAN_VERSION = 'C1.0'
WORKER = Path(__file__).with_name('scan_clean_worker.py')
REPORT = 'scan_clean_report.json'
PARAMS = 'groove_params.json'
TIMEOUT_S = 7200
MODES = ('grooves', 'zones')
MAX_GROOVES = 24
MAX_POINTS = 4000

LIMITS = [
    'Grooves are modelled as a trapezoid cut (wall, flat floor, wall) between two quadratic skins; whether the real floor is flat or rounded is not resolvable at the scan edge length (about 0.28 mm).',
    'Loops (side-button pad rings) are re-cut only on the stations where the fit is trustworthy; the others are left original. Corner pits and narrow slots between pads, and steps shorter than 2 mm, are not resolved.',
    'Stations whose fit fails, or whose groove is shallower than 0.05 mm, are left exactly as scanned (listed per groove); shallow grooves are not forced.',
    'The centre line is the fitted groove, not the seed: seeds from region boundaries are only a starting guess (error up to a few tenths of a mm).',
    'A groove is displaced along the local surface normal only; walls steeper than the normal field, undercuts and fold-overs are not repaired.',
    'Mode zones fills a zone from its surroundings (moving least squares, tapered over three edges, capped). It smooths and may erase real features inside the zone, and it does not re-cut grooves or retriangulate patches.',
    'Self-intersection counts come from a PyMeshLab face selection that over-reports on refined meshes; the check is UNVERIFIED unless the cleaned mesh has none.',
    'Surface-only: geometry behind the scanned skin, tolerances of the real part and function are not known or verified.',
]


def _check(ok: bool) -> str:
    return 'PASS' if ok else 'FAIL'


def _topology_ok(t: dict[str, Any]) -> bool:
    return bool(t['faces'] > 0 and t['watertight'] and t['manifold'] and t['winding_consistent'] and t['signed_volume_mm3'] > 0 and t['components'] == 1)


def _resolve(workspace: Path, scan_id: str | None, relative_path: str | None, unit: str | None) -> tuple[str, dict[str, Any], str | None]:
    """Prepared scan id, its prepare report and the path of the model it came from (if any)."""
    if (scan_id is None) == (relative_path is None):
        raise BrainError('SCAN_CLEAN_INPUT', 'Give exactly one of scan_id (a prepared scan or a scan_model model_id) and relative_path (an STL / OBJ in the workspace).')
    from_model = None
    if relative_path is not None:
        if unit not in sm.UNIT_MM:
            raise BrainError('SCAN_UNIT', 'unit is required with relative_path and must be one of mm, cm, m, in. It is never guessed.', {'given': unit})
        prep = scan_shell.prepare_scan(workspace, relative_path, unit)
        return prep['scan_id'], prep, None
    sid = str(scan_id)
    if sid.startswith('model_'):
        rp = scan_dir(workspace, sid) / scan_model.REPORT
        if not rp.is_file():
            raise BrainError('SCAN_NOT_FOUND', 'No scan_model result with this id. Run brain_mouse_scan_model first.')
        rep = json_load(rp)
        if rep.get('status') != 'READY':
            raise BrainError('SCAN_NOT_READY', 'The scan_model result is not READY.', {'blocking_reasons': rep.get('blocking_reasons')})
        rel = rep['cleaned_fullres']['relative_path']
        from_model = sid
        prep = scan_shell.prepare_scan(workspace, rel, 'mm')
        return prep['scan_id'], prep, from_model
    if not re.fullmatch(r'scan_[0-9a-f]{12}', sid):
        raise BrainError('SCAN_CLEAN_INPUT', 'scan_id must be a prepared scan id (scan_...) or a scan_model id (model_...).', {'given': sid})
    _, prep = scan_shell.load_prepared(workspace, sid)
    return sid, prep, None


def _validate_grooves(grooves: list[dict[str, Any]], v: np.ndarray) -> list[dict[str, Any]]:
    if not isinstance(grooves, list) or not 1 <= len(grooves) <= MAX_GROOVES:
        raise BrainError('SCAN_CLEAN_GROOVES', f'grooves must be a list of 1..{MAX_GROOVES} items {{name, points [[x, y, z] mm, ...], closed}}.')
    lo, hi = v.min(0) - 10.0, v.max(0) + 10.0
    out, names = [], set()
    for g in grooves:
        if not isinstance(g, dict) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,40}', str(g.get('name', ''))) or g['name'] in names:
            raise BrainError('SCAN_CLEAN_GROOVES', 'Every groove needs a unique name of 1..40 letters, digits, _ . -.', {'given': str(g.get('name'))[:40] if isinstance(g, dict) else None})
        names.add(g['name'])
        try:
            pts = np.array(g['points'], dtype=float)
        except (KeyError, TypeError, ValueError) as exc:
            raise BrainError('SCAN_CLEAN_GROOVES', f"Groove {g['name']}: points must be a list of [x, y, z] numbers in mm.") from exc
        if pts.ndim != 2 or pts.shape[1] != 3 or not 8 <= len(pts) <= MAX_POINTS or not np.isfinite(pts).all():
            raise BrainError('SCAN_CLEAN_GROOVES', f"Groove {g['name']}: points must be an (n, 3) array with 8 <= n <= {MAX_POINTS}, finite, mm.")
        if (pts < lo).any() or (pts > hi).any():
            raise BrainError('SCAN_CLEAN_GROOVES', f"Groove {g['name']}: points lie outside the scan (+10 mm). Coordinates are mm in the prepared-scan frame.")
        closed = bool(g.get('closed', False))
        out.append({'name': g['name'], 'kind': 'loop' if closed else 'open', 'closed': closed, 'source': 'user', 'points': pts.round(4).tolist()})
    return out


def _validate_zones(zones: list[dict[str, Any]], nf: int) -> list[dict[str, Any]]:
    if not isinstance(zones, list) or not 1 <= len(zones) <= 24:
        raise BrainError('SCAN_CLEAN_ZONES', 'zones must be a list of 1..24 items {name, box {min [x, y, z], max [x, y, z]} and / or faces [face ids]}, mm in the prepared-scan frame.')
    out, names = [], set()
    for z in zones:
        if not isinstance(z, dict) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,40}', str(z.get('name', ''))) or z['name'] in names:
            raise BrainError('SCAN_CLEAN_ZONES', 'Every zone needs a unique name of 1..40 letters, digits, _ . -.')
        names.add(z['name'])
        item: dict[str, Any] = {'name': z['name']}
        box = z.get('box')
        if box is not None:
            try:
                lo, hi = np.array(box['min'], float), np.array(box['max'], float)
            except (KeyError, TypeError, ValueError) as exc:
                raise BrainError('SCAN_CLEAN_ZONES', f"Zone {z['name']}: box needs min and max as [x, y, z].") from exc
            if lo.shape != (3,) or hi.shape != (3,) or not (np.isfinite(lo).all() and np.isfinite(hi).all()) or (hi <= lo).any():
                raise BrainError('SCAN_CLEAN_ZONES', f"Zone {z['name']}: box min must be below max on every axis.")
            item['box'] = {'min': lo.tolist(), 'max': hi.tolist()}
        faces = z.get('faces')
        if faces is not None:
            ids = np.array(faces, dtype=np.int64) if isinstance(faces, list) else None
            if ids is None or ids.ndim != 1 or not len(ids) or ids.min() < 0 or ids.max() >= nf or len(ids) > 200000:
                raise BrainError('SCAN_CLEAN_ZONES', f"Zone {z['name']}: faces must be a list of valid face ids of the prepared scan.")
            item['faces'] = ids.tolist()
        if 'box' not in item and 'faces' not in item:
            raise BrainError('SCAN_CLEAN_ZONES', f"Zone {z['name']}: give a box and / or faces.")
        out.append(item)
    return out


def scan_clean(workspace: Path, scan_id: str | None = None, relative_path: str | None = None, unit: str | None = None, mode: str = 'grooves',
               grooves: list[dict[str, Any]] | None = None, zones: list[dict[str, Any]] | None = None, max_zone_deviation_mm: float = 0.6,
               outside_tolerance_mm: float = 0.05) -> dict[str, Any]:
    if mode not in MODES:
        raise BrainError('SCAN_CLEAN_SETTINGS', f'mode must be one of {list(MODES)}.', {'given': mode})
    for name, val, top in (('max_zone_deviation_mm', max_zone_deviation_mm, 5.0), ('outside_tolerance_mm', outside_tolerance_mm, 1.0)):
        if isinstance(val, bool) or not 0 < val <= top:
            raise BrainError('SCAN_CLEAN_SETTINGS', f'{name} must be in (0, {top}] mm.', {'given': val})
    if mode == 'grooves' and zones:
        raise BrainError('SCAN_CLEAN_SETTINGS', "zones belong to mode 'zones'; mode 'grooves' takes the optional grooves override.")
    if mode == 'zones' and grooves:
        raise BrainError('SCAN_CLEAN_SETTINGS', "grooves belong to mode 'grooves'; mode 'zones' takes the zones list.")
    if mode == 'zones' and not zones:
        raise BrainError('SCAN_CLEAN_ZONES', "mode 'zones' needs an explicit zones list; nothing is guessed.")
    sid, prep, from_model = _resolve(workspace, scan_id, relative_path, unit)
    d, prep = scan_shell.load_prepared(workspace, sid)
    v, f = scan_shell.load_prepared_mesh(d)
    regions_run = None
    seeds_source = None
    if mode == 'grooves':
        if grooves:
            seeds = _validate_grooves(grooves, v)
            seeds_source = 'user grooves argument'
        else:
            reg = scan_regions.recognize_regions(workspace, sid, 'auto', False)
            if reg.get('status') != 'READY':
                raise BrainError('SCAN_CLEAN_REGIONS_NOT_READY', 'Groove detection needs a READY region recognition on this scan; give the grooves argument instead or fix the blocking reasons.',
                                 {'blocking_reasons': reg.get('blocking_reasons')})
            regions_run = reg['run_id']
            labels = np.load(d / 'regions' / regions_run / 'face_labels.npz')['face_labels']
            seeds = scan_clean_seeds.seeds_from_regions(v, f, labels)
            seeds_source = f'region boundaries of {regions_run}'
            if not seeds:
                raise BrainError('SCAN_CLEAN_NO_GROOVE_SEEDS', 'No candidate groove was found on the region boundaries of this scan; give the grooves argument or use mode zones.')
        zone_list: list[dict[str, Any]] = []
    else:
        zone_list = _validate_zones(zones or [], len(f))
        seeds = []
    settings = {'mode': mode, 'max_zone_deviation_mm': float(max_zone_deviation_mm), 'outside_tolerance_mm': float(outside_tolerance_mm),
                'grooves': seeds, 'zones': zone_list, 'regions_run': regions_run}
    clean_id = 'clean_' + digest({'npz': prep['prepared_npz_sha256'], 'settings': settings, 'version': SCAN_CLEAN_VERSION})[:12]
    out = scan_dir(workspace, clean_id)
    if (out / REPORT).is_file():
        return _stored(out)
    if out.exists():
        raise BrainError('SCAN_CLEAN_OUTPUT_EXISTS', 'The output folder exists without a report; it is never overwritten. Move it away first.', {'folder': f'mouse/scans/{clean_id}'})
    python = scan_model.find_scan_python(workspace)
    tmp = out.with_name(out.name + '.tmp-' + uuid.uuid4().hex[:8])
    tmp.mkdir(parents=True)
    try:
        with (tmp / 'input.npz').open('wb') as fh:
            np.savez(fh, vertices=v, faces=f)
        req = {'mode': mode, 'input_npz': str(tmp / 'input.npz'), 'out_dir': str(tmp / 'out'), 'grooves': seeds, 'zones': zone_list,
               'max_zone_deviation_mm': float(max_zone_deviation_mm), 'outside_tolerance_mm': float(outside_tolerance_mm)}
        (tmp / 'request.json').write_text(json.dumps(req), encoding='utf-8')
        try:
            proc = subprocess.run([str(python), '-I', str(WORKER), str(tmp / 'request.json')], capture_output=True, text=True, encoding='utf-8', errors='replace',
                                  timeout=TIMEOUT_S, cwd=str(tmp), env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        except subprocess.TimeoutExpired as exc:
            raise BrainError('SCAN_CLEAN_TIMEOUT', f'The scan worker exceeded {TIMEOUT_S} s and was stopped.') from exc
        except OSError as exc:
            raise BrainError('SCAN_PYTHON_MISSING', 'The scan python could not be started.', {'python': str(python), 'error': type(exc).__name__}) from exc
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith('{')]
        try:
            res = json.loads(lines[-1])
        except (IndexError, ValueError) as exc:
            raise BrainError('SCAN_CLEAN_WORKER', 'The scan worker returned no JSON result.', {'exit_code': proc.returncode, 'stderr_tail': proc.stderr[-800:]}) from exc
        if res.get('status') != 'OK':
            err = res.get('error') or {}
            raise BrainError(err.get('code', 'SCAN_CLEAN_WORKER'), err.get('message', 'The scan worker failed.'), {'python': str(python), 'trace': err.get('trace')})
        if not res.get('edited'):
            raise BrainError('SCAN_CLEAN_NOTHING_EDITED', 'No groove could be fitted and nothing was changed; no output was written.',
                             {'not_found': res.get('not_found'), 'seeds': [s['name'] for s in seeds]})
        folder = tmp / 'out'
        report = _report(res, folder, clean_id, sid, prep, from_model, settings, seeds_source, python)
        atomic_json(folder / REPORT, report)
        out.parent.mkdir(parents=True, exist_ok=True)
        folder.replace(out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return report


def _groove_summary(g: dict[str, Any], dev: dict[str, Any] | None, rough: dict[str, Any] | None) -> dict[str, Any]:
    segs = g['segments_constant_profile']
    live = [s for s in segs if not s['absent']]
    return {'type': g['type'], 'length_mm': g['length_mm'], 'stations_total': g['stations_total'], 'stations_left_original': g['stations_absent_or_left_original'],
            'stations_fit_failed': g['stations_fit_failed'], 'segments': len(segs), 'step_positions_s_mm': g['step_positions_s_mm'],
            'depth_mm_range': [min(s['depth_mm'] for s in live), max(s['depth_mm'] for s in live)] if live else None,
            'width_half_depth_mm_range': [min(s['width_half_depth_mm'] for s in live), max(s['width_half_depth_mm'] for s in live)] if live else None,
            'deviation_cleaned_to_original_mm': (dev or {}).get('cleaned_to_original'), 'roughness_b3_deg': rough}


def _report(res: dict[str, Any], folder: Path, clean_id: str, sid: str, prep: dict[str, Any], from_model: str | None, settings: dict[str, Any],
            seeds_source: str | None, python: Path) -> dict[str, Any]:
    base = f'mouse/scans/{clean_id}'
    mode = settings['mode']
    files: dict[str, Any] = {}
    for key, name in (('stl', 'cleaned.stl'), ('ply', 'cleaned.ply')):
        files[key] = {'relative_path': f'{base}/{name}', 'sha256': file_hash(folder / name), 'topology': res['stl_topology_on_disk'] if key == 'stl' else None}
    if mode == 'grooves':
        params = {'schema': 'groove_params/3', 'units': 'mm',
                  'frame': 'prepared-scan frame of scan_id (the frame of the input mesh; no re-orientation is applied)',
                  'profile_model': 'per station: left skin h = a0 + a1 u + a2 u^2 for u < u1; wall linear (u1 .. u1 + wall_in) down to the floor height; flat floor (floor_width); wall linear (wall_out) up to the right skin '
                                   'h = b0 + b1 u + b2 u^2. s = arc length along the centre line from its start, u = signed in-surface offset (U = N x T; for loops +u points away from the pad), '
                                   'h = height along the surface normal N. depth = chord of the two skins at the floor centre minus the floor height. Steps are the starts of the constant-profile segments.',
                  'grooves': res['grooves'], 'not_fitted': res['not_found'],
                  'note': 'centerline_bspline.control_points_mm and centerline_polyline_mm are in the same frame as the cleaned mesh'}
        atomic_json(folder / PARAMS, params)
        files['groove_params'] = {'relative_path': f'{base}/{PARAMS}', 'sha256': file_hash(folder / PARAMS)}
    topo = res['stl_topology_on_disk']
    out_dev = res['outside_zone_deviation']
    tol = settings['outside_tolerance_mm']
    blockers: list[str] = []
    if not _topology_ok(topo):
        blockers.append('OUTPUT_NOT_WATERTIGHT_MANIFOLD')
    if out_dev.get('samples', 0) and out_dev['max'] > tol:
        blockers.append('OUTSIDE_ZONE_DEVIATION_EXCEEDS_TOLERANCE')
    if not _topology_ok(res['input_topology']):
        blockers.append('INPUT_NOT_CLOSED')
    warnings: list[dict[str, Any]] = []
    si = res['self_intersection']
    if si['faces_cleaned'] > si['faces_original']:
        warnings.append({'code': 'SELF_INTERSECTION_COUNT_HIGHER', 'original': si['faces_original'], 'cleaned': si['faces_cleaned'],
                         'note': 'PyMeshLab over-reports on refined meshes; inspect the zone before relying on the result.'})
    for nf in res.get('not_found') or []:
        warnings.append({'code': 'GROOVE_NOT_EDITED', **nf})
    grooves = res.get('grooves') or {}
    per = res['per_edit_deviation']
    rough = res['roughness']
    summary: dict[str, Any] = {}
    for name, g in grooves.items():
        summary[name] = _groove_summary(g, per.get(name), rough.get(name))
        if g['stations_absent_or_left_original']:
            warnings.append({'code': 'STATIONS_LEFT_ORIGINAL', 'groove': name, 'stations': g['stations_absent_or_left_original'], 'of': g['stations_total'],
                             'note': 'Fit failed or groove shallower than 0.05 mm there; the scanned surface is kept.'})
    cap_ok = None
    if mode == 'zones':
        cap_ok = res['max_displacement_mm'] <= settings['max_zone_deviation_mm'] + 1e-9
        summary = {'zones': {'displacement': res['edit_info'], 'cleaned_to_original': per.get('zones'), 'roughness_b3_deg': rough.get('zones')}}
        if res['edit_info'].get('not_projected'):
            warnings.append({'code': 'ZONE_VERTICES_NOT_PROJECTED', 'count': res['edit_info']['not_projected'], 'note': 'Too few reference vertices around them; left as scanned.'})
    checks = {'watertight': _check(topo['watertight']), 'manifold': _check(topo['manifold']), 'winding_consistent': _check(topo['winding_consistent']),
              'single_component': _check(topo['components'] == 1),
              'outside_zone_deviation': ('UNVERIFIED' if not out_dev.get('samples') else _check(out_dev['max'] <= tol)),
              'self_intersection': 'PASS' if si['faces_cleaned'] == 0 else 'UNVERIFIED'}
    if cap_ok is not None:
        checks['zone_deviation_cap'] = _check(cap_ok)
        if not cap_ok:
            blockers.append('ZONE_DEVIATION_CAP_EXCEEDED')
    return {
        'schema': 'scan_clean_report/1', 'clean_id': clean_id, 'status': 'NOT_READY' if blockers else 'READY', 'blocking_reasons': blockers, 'warnings': warnings,
        'code_version': {'scan_clean': SCAN_CLEAN_VERSION, 'worker': res['worker'], 'package': __version__, 'pymeshlab': res.get('pymeshlab'), 'scan_python': res.get('python')},
        'source': {'scan_id': sid, 'model_id': from_model, 'prepared_npz_sha256': prep['prepared_npz_sha256'], 'source': prep['source']},
        'settings': {'mode': mode, 'max_zone_deviation_mm': settings['max_zone_deviation_mm'], 'outside_tolerance_mm': settings['outside_tolerance_mm'], 'regions_run': settings['regions_run'],
                     'grooves': [{'name': g['name'], 'kind': g['kind'], 'points': len(g['points']), 'source': g['source']} for g in settings['grooves']],
                     'zones': [{'name': z['name'], 'box': z.get('box'), 'faces': len(z.get('faces') or [])} for z in settings['zones']]},
        'seeds_source': seeds_source, 'units': {'input': 'mm (prepared scan)', 'output': 'mm', 'frame': 'prepared-scan frame'},
        'files': files, 'input_topology': res['input_topology'], 'output_topology': topo,
        'edit': {'vertices_displaced': res['vertices_displaced'], 'max_displacement_mm': res['max_displacement_mm'], 'faces_before': res['input_topology']['faces'], 'faces_after': topo['faces']},
        'edits': summary, 'not_edited': res.get('not_found') or [],
        'deviation': {'outside_zone': out_dev, 'original_to_cleaned_in_zone': res['original_to_cleaned_in_zone'], 'per_edit_cleaned_to_original': per,
                      'definition': 'exact point-to-triangle distances in mm; cleaned_to_original samples one point per new face of the edit, outside_zone samples the ORIGINAL surface farther than 0.6 mm from any moved vertex'},
        'roughness': rough, 'self_intersection': {**si, 'checker': 'PyMeshLab compute_selection_by_self_intersections_per_face'},
        'checks': checks, 'limits': LIMITS, 'log': res.get('log'), 'seconds': res['seconds'],
        'next': 'Run brain_mouse_prepare_scan on %s (unit "mm") to continue with recognize_regions / recognize_shell on the cleaned mesh.' % files['stl']['relative_path'],
        'scan_python': str(python), 'execution': {'completed': True},
    }


def _stored(folder: Path) -> dict[str, Any]:
    rep = json_load(folder / REPORT)
    for item in rep['files'].values():
        p = folder / Path(item['relative_path']).name
        if not p.is_file() or file_hash(p) != item['sha256']:
            raise BrainError('SCAN_CLEAN_OUTPUT_CHANGED', 'A stored output no longer matches its recorded hash; it is not overwritten.', {'file': p.name})
    return {**rep, 'cached': True}
