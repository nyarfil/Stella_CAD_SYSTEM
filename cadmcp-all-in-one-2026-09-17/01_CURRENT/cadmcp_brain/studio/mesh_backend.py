"""User-selectable mesh backend (numpy / pymeshlab / cgal) for generic mesh operations: brain_mesh_backend + brain_mesh_ops.

Modelled on the CAD tool choice: the USER picks the backend per operation; the choice is saved inside this workspace only
(<workspace>/.cadmcp/mesh-backend.json, never another project's file). Without an explicit `backend` argument or a saved choice
an operation returns NEEDS_USER_CHOICE with the options; nothing is picked automatically and a failed backend never falls back
silently. The mouse scan-to-solid tools do not use this module (their methods are unchanged).

Backends: numpy = the studio's own mesh code (scan_mesh: exact point-to-triangle distance, centroid-fan hole fill) in this process;
pymeshlab = MeshLab filters in the separate scan python (GPL-3.0, subprocess); cgal = the separate cgal-mcp service (CGAL Master
MCP, GPL-3.0-or-later OR commercial; operated over stdio JSON-RPC by cgal_link, never imported or linked here).
Results are NEW files under mouse/mesh_ops/<mo_id>/ (sources never written; same inputs return the stored report).
"""
from __future__ import annotations

import json
import shutil
import struct
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np

from . import cgal_link
from . import scan_mesh as sm
from .scan_cad_common import check_file, job_folder
from ..errors import BrainError
from ..req2cad.common import atomic_json, json_load
from ..util import digest, file_hash

VERSION = 'mesh_ops/1'
SELECTION_FILE = '.cadmcp/mesh-backend.json'
WORKER = Path(__file__).with_name('mesh_ops_worker.py')
Operation = Literal['hausdorff', 'simplify', 'fill_holes']
BackendName = Literal['numpy', 'pymeshlab', 'cgal']
CGAL_OP = {'hausdorff': 'mesh.distance.hausdorff_approximate_symmetric', 'simplify': 'mesh.simplify.edge_collapse', 'fill_holes': 'mesh.repair.fill_holes'}
SUPPORT: dict[str, tuple[str, ...]] = {'hausdorff': ('numpy', 'pymeshlab', 'cgal'), 'simplify': ('pymeshlab', 'cgal'), 'fill_holes': ('numpy', 'cgal')}
BACKENDS: dict[str, dict[str, Any]] = {
    'numpy': {'runs_in': 'this server process (numpy / scipy, studio scan_mesh)', 'licence': 'project code (BSD numpy / scipy)',
              'offers': {'hausdorff': 'exact point-to-triangle distance of area samples + vertices, both ways; also p50 / p95 / mean',
                         'fill_holes': 'centroid fan per boundary loop (no refinement / fairing)'},
              'limits': 'any size that fits in memory', 'cost': 'no extra process; seconds for ~100k faces'},
    'pymeshlab': {'runs_in': 'separate scan python subprocess (env CADMCP_SCAN_PYTHON)', 'licence': 'GPL-3.0 (out of process)',
                  'offers': {'hausdorff': 'MeshLab sampled Hausdorff (vertices + face samples), both ways',
                             'simplify': 'quadric edge collapse with the settings of brain_mouse_scan_model'},
                  'limits': 'any size that fits in memory', 'cost': 'subprocess start ~1-2 s'},
    'cgal': {'runs_in': 'separate cgal-mcp service (CGAL Master MCP, stdio JSON-RPC; started per call and stopped)',
             'licence': 'GPL-3.0-or-later OR commercial, per CGAL package (out of process, never linked)',
             'offers': {'hausdorff': 'PMP approximate symmetric Hausdorff with an independent validator',
                        'simplify': 'Surface_mesh_simplification edge collapse (Lindstrom-Turk) with mandatory integrity + symmetric Hausdorff validators',
                        'fill_holes': 'PMP hole filling (EVERY hole up to max_hole_edges; selective filling is not offered) with a replay validator'},
             'limits': 'Master 1.0.0: hausdorff and simplify inputs <= 400 faces (refused before computing); fill_holes <= 2M faces',
             'cost': 'service start ~2-3 s + validation; standalone acceptance of cgal-mcp is NOT met (see its README)'},
}


# ------------------------------------------------------------------ selection
def _sel_path(ws: Path) -> Path:
    return Path(ws) / SELECTION_FILE


def read_selection(ws: Path) -> dict[str, Any]:
    p = _sel_path(ws)
    if not p.is_file():
        return {}
    try:
        return dict(json_load(p).get('selections') or {})
    except Exception:  # noqa: BLE001 - an unreadable file is treated as no choice
        return {}


def availability(backend: str, ws: Path) -> dict[str, Any]:
    if backend == 'numpy':
        return {'available': True}
    if backend == 'pymeshlab':
        from .scan_model import find_scan_python
        try:
            return {'available': True, 'python': str(find_scan_python(ws))}
        except BrainError as exc:
            return {'available': False, 'reason': exc.code}
    return cgal_link.status()


def options(operation: str, ws: Path) -> list[dict[str, Any]]:
    return [{'backend': b, 'offers': BACKENDS[b]['offers'][operation], 'runs_in': BACKENDS[b]['runs_in'], 'licence': BACKENDS[b]['licence'],
             'limits': BACKENDS[b]['limits'], 'cost': BACKENDS[b]['cost'], **availability(b, ws)} for b in SUPPORT[operation]]


def backend_status(ws: Path, action: str, operation: str | None, backend: str | None, reason: str | None) -> dict[str, Any]:
    ops = [operation] if operation else list(SUPPORT)
    if any(o not in SUPPORT for o in ops):
        raise BrainError('MESH_BACKEND_ARGUMENT', f'operation must be one of {sorted(SUPPORT)}.', {'given': operation})
    sel = read_selection(ws)
    if action in ('select', 'clear'):
        if action == 'select' and (backend is None or any(backend not in SUPPORT[o] for o in ops)):
            raise BrainError('MESH_BACKEND_ARGUMENT', 'select needs a backend that supports every named operation.',
                             {'given': backend, 'supported': {o: SUPPORT[o] for o in ops}})
        for o in ops:
            if action == 'select':
                sel[o] = {'backend': backend, 'set_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'reason': (reason or '')[:500]}
            else:
                sel.pop(o, None)
        atomic_json(_sel_path(ws), {'schema': 'cadmcp.mesh_backend_selection/1', 'selections': sel})
    return {'schema': 'mesh_backend_status/1', 'selection_file': SELECTION_FILE, 'scope': 'this workspace only',
            'selections': {o: sel.get(o) for o in ops}, 'options': {o: options(o, ws) for o in ops},
            'how_to_set': "brain_mesh_backend(action='select', operation=<op>, backend=<name>) after the user chose; or pass backend= to brain_mesh_ops",
            'automatic_choice': False}


# ------------------------------------------------------------------ helpers
def _stl_bytes(V: np.ndarray, F: np.ndarray) -> bytes:
    T = V[F].astype(np.float32)
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-30)
    rec = np.zeros(len(F), dtype=[('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')])
    rec['n'], rec['v'] = n, T
    return b'cadmcp mesh_ops'.ljust(80, b' ') + struct.pack('<I', len(F)) + rec.tobytes()


def hausdorff_numpy(A: tuple, B: tuple, samples: int) -> dict[str, Any]:
    def one(X, Y):
        P = np.vstack([X[0], sm.sample_surface(X[0], X[1], samples)[0]])
        return sm.MeshDistance(Y[0], Y[1]).distance(P)
    ab, ba = one(A, B), one(B, A)
    st = lambda d: {'max': float(d.max()), 'p95': float(np.percentile(d, 95)), 'p50': float(np.median(d)), 'mean': float(d.mean())}  # noqa: E731
    return {'hausdorff_mm': float(max(ab.max(), ba.max())), 'a_to_b_mm': st(ab), 'b_to_a_mm': st(ba)}


def fill_holes_numpy(V, F, max_hole_edges: int) -> tuple[np.ndarray, np.ndarray, dict]:
    loops = sm.boundary_loops(V, F)
    keep = [lp for lp in loops if 3 <= len(lp) <= max_hole_edges]
    nv, newV, newF = len(V), [V], [F]
    for lp in keep:
        ring = np.array(lp)
        newV.append(V[ring].mean(0)[None])
        newF.append(np.stack([np.roll(ring, -1), ring, np.full(len(ring), nv)], axis=1))
        nv += 1
    return np.vstack(newV), np.vstack(newF), {'filled_hole_count': len(keep), 'skipped_hole_count': len(loops) - len(keep)}


def _pymeshlab(ws: Path, op: str, tmp: Path, a: Path, b: Path | None, params: dict) -> dict[str, Any]:
    from .scan_model import find_scan_python
    py = find_scan_python(ws)
    req = tmp / 'pml_request.json'
    req.write_text(json.dumps({'op': op, 'a': str(a), 'b': str(b) if b else None, 'params': params, 'out_dir': str(tmp / 'pml')}), encoding='utf-8')
    proc = subprocess.run([str(py), '-I', str(WORKER), str(req)], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=1800)
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith('{')]
    res = json.loads(lines[-1]) if lines else {'status': 'ERROR', 'error': {'code': 'MESH_OPS_PYMESHLAB', 'message': proc.stderr[-1500:]}}
    if res.get('status') != 'OK':
        raise BrainError(res['error']['code'], res['error']['message'])
    return res


# ------------------------------------------------------------------ operation
def mesh_ops(ws: Path, operation: str, relative_path: str, unit: str, other_path: str | None, backend: str | None, target_faces: int | None,
             max_hole_edges: int, samples: int, max_deviation_mm: float) -> dict[str, Any]:
    if operation not in SUPPORT:
        raise BrainError('MESH_OPS_ARGUMENT', f'operation must be one of {sorted(SUPPORT)}.', {'given': operation})
    if unit not in ('mm', 'cm', 'm'):
        raise BrainError('MESH_OPS_UNIT', 'unit is required: mm, cm or m (never guessed).', {'given': unit})
    if not 100 <= samples <= 20000 or not 3 <= max_hole_edges <= 2000 or not 0 < max_deviation_mm <= 100:
        raise BrainError('MESH_OPS_ARGUMENT', 'samples 100..20000, max_hole_edges 3..2000, 0 < max_deviation_mm <= 100.')
    src = check_file(ws, relative_path, ('.stl', '.obj'), 'MESH_OPS_FILE', 'relative_path')
    oth = check_file(ws, other_path, ('.stl', '.obj'), 'MESH_OPS_FILE', 'other_path') if operation == 'hausdorff' and other_path else None
    if operation == 'hausdorff' and oth is None:
        raise BrainError('MESH_OPS_ARGUMENT', 'hausdorff needs other_path.')
    if operation == 'simplify' and (target_faces is None or target_faces < 4):
        raise BrainError('MESH_OPS_ARGUMENT', 'simplify needs target_faces >= 4.')
    chosen, how = (backend, 'argument') if backend else ((read_selection(ws).get(operation) or {}).get('backend'), 'saved_selection')
    if chosen is None:
        return {'schema': 'mesh_ops_report/1', 'status': 'NEEDS_USER_CHOICE', 'operation': operation, 'options': options(operation, ws),
                'how_to_set': f"ask the user, then brain_mesh_backend(action='select', operation='{operation}', backend=<name>) or pass backend=",
                'automatic_choice': False, 'executed': False}
    if chosen not in SUPPORT[operation]:
        raise BrainError('MESH_OPS_BACKEND', f'{chosen} does not offer {operation}.', {'supported': SUPPORT[operation]})
    av = availability(chosen, ws)
    if not av.get('available'):
        return {'schema': 'mesh_ops_report/1', 'status': 'BACKEND_UNAVAILABLE', 'operation': operation, 'backend': chosen, 'availability': av,
                'options': options(operation, ws), 'fallback': 'none (the user chooses another backend)', 'executed': False}
    params = {'target_faces': target_faces, 'max_hole_edges': max_hole_edges, 'samples': samples, 'max_deviation_mm': max_deviation_mm}
    hashes = {'a': file_hash(src), 'b': file_hash(oth) if oth else None}
    job_id = 'mo_' + digest({'v': VERSION, 'op': operation, 'backend': chosen, 'unit': unit, 'params': params, 'inputs': hashes})[:12]
    out = job_folder(ws, 'mesh_ops', job_id)
    if (out / 'mesh_ops_report.json').is_file():
        return {**json_load(out / 'mesh_ops_report.json'), 'cached': True}
    s = sm.UNIT_MM[unit]
    A = sm.read_mesh(src)
    A = (A[0] * s, A[1])
    B = (lambda m: (m[0] * s, m[1]))(sm.read_mesh(oth)) if oth else None
    t0 = time.time()
    rep: dict[str, Any] = {'schema': 'mesh_ops_report/1', 'operation': operation, 'backend': chosen, 'backend_from': how, 'job_id': job_id,
                           'units': 'mm', 'params': params, 'source': {'relative_path': relative_path, 'sha256': hashes['a'], 'faces': int(len(A[1])),
                                                                         'other': {'relative_path': other_path, 'sha256': hashes['b'], 'faces': int(len(B[1]))} if B else None},
                           'cgal_used': chosen == 'cgal', 'cgal': None}
    result = None
    with tempfile.TemporaryDirectory(prefix='mesh-ops-') as td:
        tmp = Path(td)
        try:
            if chosen == 'numpy':
                if operation == 'hausdorff':
                    rep['metrics'] = hausdorff_numpy(A, B, samples)
                else:
                    V, F, info = fill_holes_numpy(A[0], A[1], max_hole_edges)
                    result, rep['backend_metrics'] = (V, F), info
            elif chosen == 'pymeshlab':
                (tmp / 'a.stl').write_bytes(_stl_bytes(*A))
                if B:
                    (tmp / 'b.stl').write_bytes(_stl_bytes(*B))
                res = _pymeshlab(ws, operation, tmp, tmp / 'a.stl', tmp / 'b.stl' if B else None, params)
                rep['pymeshlab'] = {'worker': res['worker'], 'version': res.get('pymeshlab'), 'compute_s': res['compute_s']}
                if operation == 'hausdorff':
                    rep['metrics'] = res['metrics']
                else:
                    result = (np.load(tmp / 'pml' / 'v.npy'), np.load(tmp / 'pml' / 'f.npy'))
            else:
                result = _run_cgal(operation, tmp, A, B, params, rep)
        except cgal_link.CgalUnavailable as exc:
            return {**rep, 'status': 'BACKEND_UNAVAILABLE', 'reason': str(exc)[:1000], 'fallback': 'none (the user chooses another backend)', 'executed': False}
        except cgal_link.CgalRefused as exc:
            return {**rep, 'status': 'REFUSED', 'refusal': {'code': exc.code, 'message': str(exc)[:1500]}, 'seconds': round(time.time() - t0, 2),
                    'note': 'cgal-mcp refused or did not validate; no result is delivered and nothing falls back silently', 'executed': False}
    rep['seconds'] = round(time.time() - t0, 2)
    blocking: list[str] = []
    if result is not None:
        V, F = result
        chk = hausdorff_numpy((V, F), A, samples)
        loops_src, loops_out = len(sm.boundary_loops(*A)), len(sm.boundary_loops(V, F))
        rep['result'] = {'faces': int(len(F)), 'vertices': int(len(V)), 'boundary_loops': loops_out, 'source_boundary_loops': loops_src,
                         'independent_check_numpy': chk, 'note': 'independent check = studio exact distance, same for every backend'}
        if operation == 'simplify':
            if chk['hausdorff_mm'] > max_deviation_mm:
                blocking.append('MESH_OPS_DEVIATION_ABOVE_LIMIT')
            if loops_out > loops_src:
                blocking.append('MESH_OPS_NEW_HOLES')
        if operation == 'fill_holes' and chk['b_to_a_mm']['max'] > 1e-6 * float(np.ptp(A[0], axis=0).max()):
            blocking.append('MESH_OPS_SOURCE_NOT_PRESERVED')
    rep['blocking_reasons'] = blocking
    rep['status'] = 'READY' if not blocking else 'NOT_READY'
    if file_hash(src) != hashes['a']:
        raise BrainError('MESH_OPS_SOURCE_CHANGED', 'The source changed during the run; nothing is written.')
    tmpdir = out.with_name(out.name + '.tmp-' + uuid.uuid4().hex[:8])
    tmpdir.mkdir(parents=True)
    try:
        if result is not None and not blocking:
            (tmpdir / 'result.stl').write_bytes(_stl_bytes(*result))
            rep['outputs'] = {'mesh': {'relative_path': f'mouse/mesh_ops/{job_id}/result.stl', 'sha256': file_hash(tmpdir / 'result.stl')}}
        atomic_json(tmpdir / 'mesh_ops_report.json', rep)
        tmpdir.replace(out)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return rep


def _run_cgal(operation: str, tmp: Path, A: tuple, B: tuple | None, params: dict, rep: dict) -> tuple | None:
    t = time.time()
    with cgal_link.CgalClient() as c:
        rep['cgal_server_start_s'] = round(time.time() - t, 2)
        a = c.import_mesh(A[0], A[1], 'mm', tmp / 'a.off')
        if operation == 'hausdorff':
            b = c.import_mesh(B[0], B[1], 'mm', tmp / 'b.off')
            job = c.run({'operation_id': CGAL_OP[operation], 'inputs': {'first': a['artifact_id'], 'second': b['artifact_id']},
                         'parameters': {'sampling': {'method': 'random_uniform', 'random_seed': 20260917, 'points_on_faces': params['samples'],
                                                     'points_on_edges': max(1, params['samples'] // 10), 'include_vertices': True}}})
            r = c.artifact_json(job['outputs'][0]['artifact_id'], tmp / 'h.json')
            rep['metrics'] = {'hausdorff_mm': float(r['results']['distance'])}
        elif operation == 'simplify':
            job = c.run({'operation_id': CGAL_OP[operation], 'inputs': {'geometry': a['artifact_id']},
                         'parameters': {'stop': {'kind': 'face_count', 'value': int(params['target_faces'])}, 'policy': 'lindstrom_turk',
                                        'max_symmetric_deviation': {'value': params['max_deviation_mm'], 'unit': 'mm'},
                                        'hausdorff_error_bound': {'value': min(0.01, params['max_deviation_mm'] / 10), 'unit': 'mm'}}})
        else:
            job = c.run({'operation_id': CGAL_OP[operation], 'inputs': {'source': a['artifact_id']}, 'parameters': {'max_hole_edges': params['max_hole_edges']}})
            rr = cgal_link.validator_report(job, 'mesh.validate.repair_fill_holes').get('reference_metrics', {})
            rep['backend_metrics'] = {k: rr.get(k) for k in ('filled_hole_count', 'skipped_hole_count', 'added_face_count')}
        rep['cgal'] = cgal_link.provenance(c, job)
        if operation == 'hausdorff':
            return None
        out = job['outputs'][0]
        c.call('cgal_artifact_export', {'artifact_id': out['artifact_id'], 'path': str(tmp / 'out.off')})
        if file_hash(tmp / 'out.off') != out['sha256']:
            raise cgal_link.CgalRefused('EXPORT_MISMATCH', 'exported bytes differ from the validated artifact')
        return cgal_link.read_off(tmp / 'out.off')


class MeshBackendToolsMixin:
    def brain_mesh_backend(self, action: Literal['status', 'select', 'clear'] = 'status', operation: Operation | None = None,
                           backend: BackendName | None = None, reason: str | None = None) -> dict[str, Any]:
        """User-selectable mesh backend per operation (hausdorff, simplify, fill_holes) for brain_mesh_ops, saved in THIS workspace only (.cadmcp/mesh-backend.json; other projects are never touched). action 'status' (read-only) lists every option with what it offers, where it runs, licence, limits, cost and live availability (numpy = studio code in this process; pymeshlab = separate scan python, GPL-3.0; cgal = separate cgal-mcp service over stdio JSON-RPC, never linked; Master 1.0.0 limits hausdorff / simplify to <= 400 faces). 'select' stores the user's choice (call only after the user chose), 'clear' removes it. Nothing is chosen automatically. The mouse scan-to-solid tools are not affected."""
        return backend_status(self.brain.store.root, action, operation, backend, reason)

    def brain_mesh_ops(self, operation: Operation, relative_path: str, unit: str, other_path: str | None = None, backend: BackendName | None = None,
                       target_faces: int | None = None, max_hole_edges: int = 30, samples: int = 20000, max_deviation_mm: float = 0.5) -> dict[str, Any]:
        """Generic mesh operation through the backend the USER selected (backend argument, else the saved brain_mesh_backend choice; neither => NEEDS_USER_CHOICE with the options, nothing runs). operation 'hausdorff' (relative_path vs other_path, symmetric, samples per mesh + vertices), 'simplify' (to target_faces; READY only if the independent deviation <= max_deviation_mm and no new holes), 'fill_holes' (EVERY boundary loop with <= max_hole_edges edges; selective filling is not offered; READY only if the source surface is preserved). Inputs: workspace-relative .stl / .obj, unit mm / cm / m required (output mm). Every mesh result is re-measured by the same studio exact-distance check (independent_check_numpy) so backends compare fairly; report fields backend, cgal_used, cgal (version, registry revision, plan / job id, validators), seconds. cgal refusals (e.g. PRECONDITION_FAILED above 400 faces) return REFUSED; an absent backend returns BACKEND_UNAVAILABLE; there is no silent fallback. Writes result.stl + mesh_ops_report.json once under mouse/mesh_ops/<mo_id>/ (never overwritten; sources never modified; same inputs return the stored report)."""
        return mesh_ops(self.brain.store.root, operation, relative_path, unit, other_path, backend, target_faces, max_hole_edges, samples, max_deviation_mm)
