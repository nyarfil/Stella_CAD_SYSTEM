"""PLY -> cleaned, decimated, watertight STL. SUBPROCESS WORKER, never imported by the server.

Run as:  <scan python> scan_model_worker.py request.json
The scan python is a SEPARATE virtualenv that has numpy, scipy and pymeshlab (GPL-3.0).
pymeshlab must never be imported into the cadmcp_brain process: this file is the only place that names it,
and it imports it lazily inside main(). Request and result are JSON; the result is the last stdout line.
The numpy-only helpers below (topology, read_stl_topology, thin_wall_vertices, patch_small_holes) are
importable without pymeshlab so the server tests can exercise them directly.
"""
from __future__ import annotations
import json
import shutil
import sys
import time
import traceback
from pathlib import Path
import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

WORKER_VERSION = 'scan_model/1'
UNIT_MM = {'mm': 1.0, 'cm': 10.0, 'm': 1000.0, 'in': 25.4}


# ------------------------------------------------------------------ numpy topology
def topology(v: np.ndarray, f: np.ndarray) -> dict:
    """Closed-surface checks on an indexed mesh. watertight = every edge used by exactly two faces."""
    nf = len(f)
    out = {'faces': int(nf), 'vertices': int(len(np.unique(f))) if nf else 0}
    if not nf:
        return {**out, 'boundary_edges': 0, 'non_manifold_edges': 0, 'non_manifold_vertices': 0, 'inconsistent_winding_edges': 0,
                'components': 0, 'watertight': False, 'manifold': False, 'winding_consistent': False, 'signed_volume_mm3': 0.0, 'degenerate_faces': 0}
    d = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    key = np.sort(d, axis=1)
    uk, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    inv = inv.reshape(-1)
    boundary = int((cnt == 1).sum())
    nme = int((cnt > 2).sum())
    two = np.flatnonzero(cnt[inv] == 2)
    inconsistent = 0
    if len(two):
        order = two[np.argsort(inv[two], kind='stable')]
        pa, pb = d[order[0::2]], d[order[1::2]]
        inconsistent = int((pa[:, 0] != pb[:, 1]).sum())
    # vertex manifoldness: corners (face, vertex) glued across shared edges; one fan per vertex
    nvm = 0
    if nme == 0 and boundary == 0:
        corner = np.arange(3 * nf).reshape(3, nf).T                      # corner[f, k] is vertex f[f, k]
        order = np.argsort(inv, kind='stable')
        a, b = order[0::2], order[1::2]                                    # the two uses of each edge (flat index k*nf + f)
        ka, fa = a // nf, a % nf
        kb, fb = b // nf, b % nf
        rows, cols = [], []
        for off in (0, 1):                                                 # edge start vertex and end vertex
            ca = corner[fa, (ka + off) % 3]
            va = f[fa, (ka + off) % 3]
            # matching corner in the other face is the one holding the same vertex
            cb = np.where(f[fb, kb] == va, corner[fb, kb], corner[fb, (kb + 1) % 3])
            rows.append(ca)
            cols.append(cb)
        r, c = np.concatenate(rows), np.concatenate(cols)
        g = sp.coo_matrix((np.ones(len(r)), (r, c)), shape=(3 * nf, 3 * nf))
        _, lab = connected_components(g, directed=False)
        cv = f.reshape(-1, order='F')                                      # vertex of corner index (k*nf + f)
        pair = np.unique(np.stack([cv, lab], axis=1), axis=0)
        nvm = int((np.bincount(pair[:, 0]) > 1).sum())
    n_vert = len(v)
    gcomp = sp.coo_matrix((np.ones(nf), (f[:, 0], f[:, 1])), shape=(n_vert, n_vert))
    g2 = sp.coo_matrix((np.ones(nf), (f[:, 1], f[:, 2])), shape=(n_vert, n_vert))
    ncomp, lab = connected_components(gcomp + g2, directed=False)
    ncomp = int(len(np.unique(lab[f[:, 0]])))
    t = v[f]
    cr = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    area2 = np.linalg.norm(cr, axis=1)
    vol = float(np.einsum('ij,ij->i', t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() / 6.0)
    degenerate = int(((area2 < 1e-12) | (f[:, 0] == f[:, 1]) | (f[:, 1] == f[:, 2]) | (f[:, 0] == f[:, 2])).sum())
    return {**out, 'boundary_edges': boundary, 'non_manifold_edges': nme, 'non_manifold_vertices': nvm, 'inconsistent_winding_edges': inconsistent,
            'components': ncomp, 'watertight': bool(boundary == 0 and nme == 0), 'manifold': bool(nme == 0 and nvm == 0),
            'winding_consistent': bool(inconsistent == 0), 'signed_volume_mm3': vol, 'degenerate_faces': degenerate}


def read_stl_topology(path: Path) -> tuple[np.ndarray, np.ndarray, dict]:
    """Read a binary STL exactly like the server does (vertices merged by exact float32 position) and check it."""
    data = Path(path).read_bytes()
    n = int(np.frombuffer(data, '<u4', 1, 80)[0])
    rec = np.frombuffer(data, np.dtype([('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')]), n, 84)
    tris = rec['v'].astype(np.float64)
    v, inv = np.unique(tris.reshape(-1, 3), axis=0, return_inverse=True)
    f = inv.reshape(-1, 3).astype(np.int64)
    return v, f, topology(v, f)


def stl_weld(v: np.ndarray, f: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """What an STL round trip does: float32 coordinates, vertices merged by exact position, collapsed faces dropped."""
    u, inv = np.unique(v.astype(np.float32).astype(np.float64), axis=0, return_inverse=True)
    f2 = inv.reshape(-1)[f]
    keep = (f2[:, 0] != f2[:, 1]) & (f2[:, 1] != f2[:, 2]) & (f2[:, 0] != f2[:, 2])
    used = np.unique(f2[keep])
    remap = np.full(len(u), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    return u[used], remap[f2[keep]]


def vertex_normals(v: np.ndarray, f: np.ndarray) -> np.ndarray:
    t = v[f]
    fn = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    vn = np.zeros_like(v)
    for k in range(3):
        np.add.at(vn, f[:, k], fn)
    return vn / (np.linalg.norm(vn, axis=1, keepdims=True) + 1e-300)


def thin_wall_vertices(v: np.ndarray, f: np.ndarray, thin_d: float, ring: int = 3) -> np.ndarray:
    """Vertices whose opposing sheet (normal dot < -0.3, not within `ring` topological steps) is closer than thin_d mm."""
    n = len(v)
    e = np.unique(np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1), axis=0)
    a = sp.coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n))
    a = (a + a.T + sp.eye(n)).tocsr()
    a.data[:] = 1
    r = a
    for _ in range(ring - 1):
        r = (r @ a).tocsr()
        r.data[:] = 1
    nrm = vertex_normals(v, f)
    k = min(24, n)
    dist, idx = cKDTree(v).query(v, k=k)
    ii = np.repeat(np.arange(n), k - 1)
    jj = idx[:, 1:].reshape(-1)
    dd = dist[:, 1:].reshape(-1)
    cand = (dd < thin_d) & (np.einsum('ij,ij->i', nrm[ii], nrm[jj]) < -0.3)
    ii, jj = ii[cand], jj[cand]
    flag = np.zeros(n, bool)
    if len(ii):
        in_ring = np.asarray(r[ii, jj]).ravel() > 0
        flag[ii[~in_ring]] = True
    return v[flag]


def patch_small_holes(v: np.ndarray, f: np.ndarray, maxloop: int = 8) -> tuple[np.ndarray, np.ndarray, int]:
    """Close boundary loops of at most `maxloop` edges with a centroid fan oriented against the faces that bound them."""
    d = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    key = np.sort(d, axis=1)
    _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    bnd = d[cnt[inv.reshape(-1)] == 1]                       # boundary edges, directed as their single face uses them
    if not len(bnd):
        return v, f, 0
    n = len(v)
    g = sp.coo_matrix((np.ones(len(bnd)), (bnd[:, 0], bnd[:, 1])), shape=(n, n))
    _, lab = connected_components(g, directed=False)
    deg = np.bincount(bnd.reshape(-1), minlength=n)
    verts, new, nv, patched = [v], [], len(v), 0
    for c in np.unique(lab[bnd[:, 0]]):
        edges = bnd[lab[bnd[:, 0]] == c]
        if len(edges) > maxloop or (deg[edges.reshape(-1)] != 2).any():
            continue
        centre = v[np.unique(edges)].mean(0)
        verts.append(centre[None])
        new.extend([[b, a, nv] for a, b in edges.tolist()])
        nv += 1
        patched += 1
    if not new:
        return v, f, 0
    return np.vstack(verts), np.vstack([f, np.array(new, dtype=f.dtype)]), patched


# ------------------------------------------------------------------ pymeshlab pipeline
def _closed(t: dict) -> bool:
    return bool(t['watertight'] and t['manifold'] and t['winding_consistent'] and t['components'] == 1 and t['signed_volume_mm3'] > 0)


def _clean(ms, min_component_faces: int, hole_max: int) -> None:
    ms.meshing_remove_duplicate_vertices()
    ms.meshing_remove_duplicate_faces()
    ms.meshing_remove_connected_component_by_face_number(mincomponentsize=min_component_faces)
    ms.meshing_repair_non_manifold_edges()
    ms.meshing_repair_non_manifold_vertices()
    ms.meshing_remove_unreferenced_vertices()
    ms.meshing_close_holes(maxholesize=hole_max)


def _hd_samples(ms, a: int, b: int, pm):
    """Vertex-sampled one-directional distance a -> b (exact point-to-triangle); per-vertex values land in a's quality."""
    ms.get_hausdorff_distance(sampledmesh=a, targetmesh=b, samplevert=True, sampleedge=False, sampleface=False,
                              samplenum=2_000_000, maxdist=pm.PercentageValue(10), savesample=False)
    m = ms.mesh(a)
    return np.abs(np.array(m.vertex_scalar_array())), np.array(m.vertex_matrix())


def _stats(q: np.ndarray) -> dict:
    return {'max_mm': float(q.max()), 'mean_mm': float(q.mean()), 'p99_mm': float(np.percentile(q, 99)),
            'p99_9_mm': float(np.percentile(q, 99.9)), 'samples': int(len(q))}


def _measure(ms, ref: int, test: int, tree, zone_r: float, pm) -> tuple[dict, np.ndarray, np.ndarray]:
    qa, va = _hd_samples(ms, test, ref, pm)      # decimated -> original
    qb, vb = _hd_samples(ms, ref, test, pm)      # original -> decimated
    q = np.concatenate([qa, qb])
    pts = np.vstack([va, vb])
    inzone = np.zeros(len(q), bool) if tree is None else tree.query(pts)[0] <= zone_r
    res = {'budget': _stats(q[~inzone]), 'all': _stats(q), 'non_budget_zone': {**_stats(q[inzone]), 'fraction_of_samples': float(inzone.mean())} if inzone.any() else None}
    return res, q, pts


def _decimate(ms, src_id: int, n_faces: int, min_component_faces: int, hole_max: int, pm) -> tuple[int, int]:
    """Quadric decimation of a copy of mesh src_id, then re-close; returns (mesh id, small holes patched)."""
    ms.set_current_mesh(src_id)
    ms.generate_copy_of_current_mesh()
    ms.meshing_decimation_quadric_edge_collapse(targetfacenum=int(n_faces), qualitythr=0.5, preserveboundary=True,
                                                 preservenormal=True, optimalplacement=True)
    ms.meshing_remove_connected_component_by_face_number(mincomponentsize=min_component_faces)
    for _ in range(2):
        ms.meshing_remove_duplicate_vertices()
        ms.meshing_repair_non_manifold_edges()
        ms.meshing_repair_non_manifold_vertices()
        ms.meshing_remove_unreferenced_vertices()
        ms.meshing_close_holes(maxholesize=hole_max)
        ms.meshing_remove_connected_component_by_face_number(mincomponentsize=min_component_faces)
    mid = ms.current_mesh_id()
    m = ms.mesh(mid)
    v, f = np.array(m.vertex_matrix()), np.array(m.face_matrix())
    v, f, patched = patch_small_holes(v, f)
    # An STL merges vertices that coincide after float32 rounding, which turns thin-wall pinches into non-manifold
    # vertices on disk. Repair on the merged mesh, displacing split vertices by a sub-micron fraction of the edge.
    for _ in range(4):
        v2, f2 = stl_weld(v, f)
        if _closed(topology(v2, f2)):
            v, f = v2, f2
            break
        ms.add_mesh(pm.Mesh(vertex_matrix=v2, face_matrix=f2))
        ms.meshing_re_orient_faces_coherently()
        ms.meshing_repair_non_manifold_edges()
        ms.meshing_repair_non_manifold_vertices(vertdispratio=0.002)
        ms.meshing_remove_unreferenced_vertices()
        ms.meshing_remove_connected_component_by_face_number(mincomponentsize=min_component_faces)
        ms.meshing_remove_unreferenced_vertices()
        nm = ms.current_mesh()
        v, f = np.array(nm.vertex_matrix()), np.array(nm.face_matrix())
        ms.delete_current_mesh()
    ms.set_current_mesh(mid)
    ms.delete_current_mesh()
    ms.add_mesh(pm.Mesh(vertex_matrix=v, face_matrix=f))
    mid = ms.current_mesh_id()
    return mid, patched


def run(req: dict) -> dict:
    import pymeshlab as pm
    t0 = time.time()
    out_dir = Path(req['out_dir'])
    out_dir.mkdir(parents=True, exist_ok=True)
    scale = UNIT_MM[req['unit']]
    target, hard = float(req['target_max_error_mm']), float(req['hard_limit_error_mm'])
    min_comp, hole_max = int(req['min_component_faces']), int(req['close_holes_max_edges'])
    zone_r, thin_d = float(req['zone_radius_mm']), float(req['thin_wall_mm'])
    log: list[str] = []

    ms = pm.MeshSet()
    ms.load_new_mesh(req['input_path'])
    m0 = ms.current_mesh()
    raw_v, raw_f = int(m0.vertex_number()), int(m0.face_number())
    v0, f0 = np.array(m0.vertex_matrix()), np.array(m0.face_matrix())
    ms.clear()
    # unit -> mm, exact-position weld FIRST (a textured PLY carries one vertex per UV corner: fake seams)
    ms.add_mesh(pm.Mesh(vertex_matrix=v0 * scale, face_matrix=f0))
    ms.meshing_remove_duplicate_vertices()
    ms.meshing_remove_unreferenced_vertices()
    m = ms.current_mesh()
    ref_id = ms.current_mesh_id()
    rv, rf = np.array(m.vertex_matrix()), np.array(m.face_matrix())
    welded = topology(rv, rf)
    weld_info = {'vertices_as_loaded': raw_v, 'vertices_after_exact_weld': int(m.vertex_number()), 'faces': int(m.face_number()),
                 'topology_after_weld': welded}
    if not len(rf):
        return {'status': 'FAILED', 'error': {'code': 'SCAN_MODEL_EMPTY', 'message': 'The PLY has no faces.'}}
    ext = (rv.max(0) - rv.min(0)).tolist()

    # cleanup copy (topology only, no geometry change)
    ms.set_current_mesh(ref_id)
    ms.generate_copy_of_current_mesh()
    clean_id = ms.current_mesh_id()
    _clean(ms, min_comp, hole_max)
    cm = ms.mesh(clean_id)
    cv, cf = np.array(cm.vertex_matrix()), np.array(cm.face_matrix())
    clean_topo = topology(cv, cf)
    cleanup = {'faces_before': int(len(rf)), 'faces_after': int(len(cf)), 'components_before': welded['components'], 'components_after': clean_topo['components'],
               'min_component_faces': min_comp, 'close_holes_max_edges': hole_max}
    full_path = out_dir / 'cleaned_fullres.stl'
    ms.set_current_mesh(clean_id)
    ms.save_current_mesh(str(full_path), binary=True)
    _, _, full_disk = read_stl_topology(full_path)

    thin = thin_wall_vertices(rv, rf, thin_d)
    tree = cKDTree(thin) if len(thin) else None
    zone_frac = float((tree.query(rv)[0] <= zone_r).mean()) if tree is not None else 0.0

    # reference for every measurement: the welded original, re-read in a FRESH MeshSet each time (PyMeshLab keeps a stale
    # per-vertex quality on reused meshes, which silently returns the previous run's distances)
    ref_path = out_dir / 'ref_welded.ply'
    ms.set_current_mesh(ref_id)
    ms.save_current_mesh(str(ref_path), binary=True)
    cand_dir = out_dir / 'candidates'
    cand_dir.mkdir(exist_ok=True)
    cache: dict[int, dict] = {}

    def evaluate(n: int) -> dict:
        """Decimate to ~n faces, write the STL, then measure and verify THE FILE (what is measured is what is delivered)."""
        if n not in cache:
            mid, patched = _decimate(ms, clean_id, n, min_comp, hole_max, pm)
            path = cand_dir / f'cand_{n}.stl'
            ms.set_current_mesh(mid)
            ms.save_current_mesh(str(path), binary=True)
            ms.delete_current_mesh()
            _, _, disk = read_stl_topology(path)
            ms2 = pm.MeshSet()
            ms2.load_new_mesh(str(ref_path))
            ms2.load_new_mesh(str(path))
            res, q, pts = _measure(ms2, 0, 1, tree, zone_r, pm)
            cache[n] = {'path': path, 'patched': patched, 'disk': disk, 'error': res, 'q': q, 'pts': pts}
            log.append(f'N={n} faces={disk["faces"]} budget_max={res["budget"]["max_mm"]:.4f} all_max={res["all"]["max_mm"]:.4f} closed_manifold={_closed(disk)}')
        return cache[n]

    def within(n: int, limit: float) -> bool:
        return evaluate(n)['error']['budget']['max_mm'] <= limit

    def good(n: int, limit: float) -> bool:
        return within(n, limit) and _closed(cache[n]['disk'])

    def search(limit: float, lo: int, hi: int) -> int | None:
        """Smallest N whose delivered file meets the budget AND is closed. The error is a staircase in N, so: bisect on the
        budget alone, probe downwards in 1 % steps (a topology miss is skipped, three budget misses stop), then verify."""
        top = int(len(cf) * 0.98)
        if not within(hi, limit):
            hi = top
            if not within(hi, limit):
                return None
        while hi - lo > max(100, hi // 25):
            mid = (lo + hi) // 2
            if within(mid, limit):
                hi = mid
            else:
                lo = mid
        best = hi if good(hi, limit) else None
        n, misses, steps = hi, 0, 0
        while misses < 3 and n > lo and steps < 40:
            n, steps = int(n * 0.99), steps + 1
            if within(n, limit):
                misses = 0
                if good(n, limit):
                    best = n
            else:
                misses += 1
        while best is None and hi < top:
            hi = min(top, int(hi * 1.01) + 1)
            if good(hi, limit):
                best = hi
        return best

    def finalize(n: int, name: str) -> dict:
        c = evaluate(n)
        shutil.copyfile(c['path'], out_dir / name)
        res, q, pts = c['error'], c['q'], c['pts']
        worst = []
        if tree is not None:
            sel = (tree.query(pts)[0] <= zone_r) & (q > res['budget']['max_mm'])
            if sel.any():
                cell = np.round(pts[sel] / 3.0).astype(np.int64)
                keyed: dict[tuple, tuple[float, list]] = {}
                for cc, e, p in zip(map(tuple, cell), q[sel], pts[sel]):
                    if cc not in keyed or e > keyed[cc][0]:
                        keyed[cc] = (float(e), [round(float(x), 2) for x in p])
                worst = [{'error_mm': e, 'position_mm': p} for e, p in sorted(keyed.values(), reverse=True)[:5]]
        return {'file': name, 'target_faces': int(n), 'faces': int(c['disk']['faces']), 'small_holes_patched': int(c['patched']), 'error': res,
                'worst_non_budget_locations': worst, 'topology_on_disk': c['disk']}

    lo = max(1000, len(cf) // 20)
    n_target = search(target, lo, int(len(cf) * 0.6))
    outputs = {}
    if n_target is not None:
        outputs['target'] = finalize(n_target, 'decimated_target.stl')
    n_hard = search(hard, lo, n_target if n_target is not None else int(len(cf) * 0.6))
    if n_hard is not None and n_hard != n_target:
        outputs['hard_limit'] = finalize(n_hard, 'decimated_hard_limit.stl')
    ref_path.unlink(missing_ok=True)
    shutil.rmtree(cand_dir, ignore_errors=True)
    return {
        'status': 'OK', 'worker': WORKER_VERSION, 'pymeshlab': _pm_version(), 'python': sys.version.split()[0],
        'extent_mm': ext, 'weld': weld_info, 'cleanup': cleanup, 'cleaned_fullres': {'file': 'cleaned_fullres.stl', 'faces': int(full_disk['faces']), 'topology_on_disk': full_disk},
        'thin_wall': {'definition': f'opposing sheet closer than {thin_d} mm (normal dot < -0.3, beyond a 3-ring)', 'flagged_vertices': int(len(thin)),
                      'zone_radius_mm': zone_r, 'zone_fraction_of_vertices': zone_frac},
        'search_log': log, 'outputs': outputs, 'seconds': round(time.time() - t0, 1),
    }


def _pm_version() -> str | None:
    try:
        from importlib.metadata import version
        return version('pymeshlab')
    except Exception:
        return None


def main(argv: list[str]) -> int:
    try:
        req = json.loads(Path(argv[1]).read_text(encoding='utf-8'))
        res = run(req)
    except ModuleNotFoundError as exc:
        res = {'status': 'FAILED', 'error': {'code': 'SCAN_PYTHON_NO_PYMESHLAB', 'message': f'Missing module in the scan python: {exc.name}.'}}
    except Exception as exc:   # report, never a bare traceback
        res = {'status': 'FAILED', 'error': {'code': 'SCAN_MODEL_WORKER', 'message': f'{type(exc).__name__}: {exc}', 'trace': traceback.format_exc()[-1500:]}}
    sys.stdout.write('\n' + json.dumps(res, allow_nan=False) + '\n')
    return 0 if res.get('status') == 'OK' else 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
