"""Worker of brain_mouse_scan_symmetrise (runs in the separate scan python: numpy, scipy, trimesh).

Coarse mirror-symmetry detection + scan-error symmetrisation of a welded scan mesh. Rules (owner, 2026-10-10):
- Symmetry is never forced. The decision is COARSE: p80 of the unbounded vertex -> mirrored-surface distance after a robust best-fit
  mirror plane, against thr = max(abs_threshold_mm, rel_threshold * bbox diagonal), per region AND per local cell (cells on folded
  coordinates so one cell holds both mirror sides). Normal scan error (0.1-1 mm, roll, bias) passes; real design asymmetry (several mm) fails.
- Region labels are hints only: they group faces for the report and pair regions with their mirror counterpart; the geometry test decides.
- Only passing regions/cells are corrected (move along the vertex normal toward the mirrored counterpart; average both sides when their
  roughness is similar, else mirror the better side; correspondences farther than correspondence_cap_mm ignored; ramp to 0 next to fixed
  faces). Asymmetric cells, fixed feature regions, excluded regions and faces whose mirror lands on a fixed feature stay as scanned.
Face order and topology are unchanged (labels stay valid). The plane is reported in the INPUT frame as n . x = d.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Any
import numpy as np

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cadmcp_brain.studio.scan_cad_common import WorkerError, worker_main  # noqa: E402

WORKER_VERSION = 'scan_symmetrise/1'
DEFAULTS = {'abs_threshold_mm': 2.0, 'rel_threshold': 0.015, 'cell_mm': None, 'stat_pct': 80, 'min_region_faces': 50, 'min_cell_samples': 15,
            'plane_gate_factor': 2.0, 'correspondence_cap_mm': 1.0, 'ramp_mm': 2.0, 'passes': 3, 'normal_hint': None, 'plane_search': 'lateral',
            'fixed_regions': ['wheel', 'WH', 'side_button_1', 'side_button_2', 'B1', 'B2', 'sensor', 'sensor_window'],
            'exclude_regions': ['bottom_plate', 'base_plate', 'plate', 'bottom'], 'unit_scale': 1.0}
UNLABELLED = 'unlabelled'


def mirror_pts(X: np.ndarray, n: np.ndarray, d: float) -> np.ndarray:
    s = X @ n - d
    return X - 2 * s[:, None] * n


def read_regions(path: Path | None, n_faces: int) -> tuple[np.ndarray, list[str]]:
    """Region index per face + names. JSON {name: [ids]} / {"regions": {name: {"face_ids": [...]}}} or .npz face_labels + codes 'name=code'.
    Faces without a label get the region 'unlabelled'. Overlaps: the later name wins (reported as a warning by the caller)."""
    names = [UNLABELLED]
    region = np.zeros(n_faces, np.int64)
    if path is None:
        return region, names
    groups: dict[str, np.ndarray] = {}
    if path.suffix.lower() == '.npz':
        z = np.load(path, allow_pickle=False)
        if 'face_labels' not in z or 'codes' not in z:
            raise WorkerError('SYMMETRISE_LABELS', 'An .npz label file needs the arrays face_labels and codes ("name=code").')
        fl = z['face_labels']
        if len(fl) != n_faces:
            raise WorkerError('SYMMETRISE_LABELS', 'face_labels has a different length than the mesh has faces.', {'labels': int(len(fl)), 'faces': int(n_faces)})
        for item in z['codes']:
            name, code = str(item).rsplit('=', 1)
            groups[name] = np.flatnonzero(fl == int(code))
    else:
        data = json.loads(path.read_text(encoding='utf-8'))
        data = data.get('regions', data) if isinstance(data, dict) else data
        if not isinstance(data, dict):
            raise WorkerError('SYMMETRISE_LABELS', 'The label JSON must map region names to face id lists.')
        for k, val in data.items():
            val = val.get('face_ids') if isinstance(val, dict) else val
            if isinstance(val, list):
                groups[str(k)] = np.asarray(val, dtype=np.int64)
    for k, ids in groups.items():
        if len(ids) == 0:
            continue
        if ids.min() < 0 or ids.max() >= n_faces:
            raise WorkerError('SYMMETRISE_LABELS', 'A region has face ids outside the mesh.', {'region': k})
        names.append(k)
        region[ids] = len(names) - 1
    return region, names


def closest_on_surface(V: np.ndarray, F: np.ndarray, Q: np.ndarray, exact_within_mm: float = 6.0, chunk: int = 20000) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Closest point on a triangle mesh for each query (no rtree needed). Candidates = every triangle whose centroid lies within
    min(d_v, exact_within_mm) + R_max of the query (d_v = distance to the nearest mesh vertex, R_max = largest centroid-to-corner radius),
    plus the 8 nearest centroids; exact point-triangle distance (Ericson). Exact whenever the true distance is below exact_within_mm;
    beyond that an upper bound (>= exact_within_mm) is returned. Returns (points, distances, triangle ids)."""
    from scipy.spatial import cKDTree
    A, B, C = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    cen = (A + B + C) / 3.0
    rmax = float(np.sqrt(np.max([((X - cen) ** 2).sum(1).max() for X in (A, B, C)])))
    used = np.unique(F.ravel())
    dv = cKDTree(V[used]).query(Q)[0]
    kd = cKDTree(cen)
    k = min(8, len(F))
    best_d = np.full(len(Q), np.inf)
    best_p = np.zeros_like(Q)
    best_t = np.zeros(len(Q), np.int64)
    for s0 in range(0, len(Q), chunk):
        q = Q[s0:s0 + chunk]
        lists = kd.query_ball_point(q, np.minimum(dv[s0:s0 + chunk], exact_within_mm) + rmax + 1e-9)
        knn = kd.query(q, k=k)[1].reshape(len(q), k)
        qi = np.concatenate([np.repeat(np.arange(len(q)), [len(x) for x in lists]), np.repeat(np.arange(len(q)), k)])
        ti = np.concatenate([np.fromiter((t for x in lists for t in x), np.int64), knn.ravel()])
        pt = _closest_pt_tri(q[qi], A[ti], B[ti], C[ti])
        dd = np.linalg.norm(pt - q[qi], axis=1)
        order = np.lexsort((dd, qi))
        first = order[np.r_[True, qi[order][1:] != qi[order][:-1]]]
        g = s0 + qi[first]
        best_d[g], best_p[g], best_t[g] = dd[first], pt[first], ti[first]
    return best_p, best_d, best_t


def _closest_pt_tri(P, A, B, C):
    ab, ac, ap = B - A, C - A, P - A
    d1, d2 = (ab * ap).sum(1), (ac * ap).sum(1)
    bp = P - B
    d3, d4 = (ab * bp).sum(1), (ac * bp).sum(1)
    cp = P - C
    d5, d6 = (ab * cp).sum(1), (ac * cp).sum(1)
    vc = d1 * d4 - d3 * d2
    vb = d5 * d2 - d1 * d6
    va = d3 * d6 - d5 * d4
    den = va + vb + vc
    den = np.where(np.abs(den) < 1e-300, 1e-300, den)
    v, w = vb / den, vc / den
    res = A + ab * v[:, None] + ac * w[:, None]                         # interior
    e_ab = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    t = d1 / np.where(np.abs(d1 - d3) < 1e-300, 1e-300, d1 - d3)
    res = np.where(e_ab[:, None], A + ab * t[:, None], res)
    e_ac = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    t = d2 / np.where(np.abs(d2 - d6) < 1e-300, 1e-300, d2 - d6)
    res = np.where(e_ac[:, None], A + ac * t[:, None], res)
    e_bc = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    t = (d4 - d3) / np.where(np.abs((d4 - d3) + (d5 - d6)) < 1e-300, 1e-300, (d4 - d3) + (d5 - d6))
    res = np.where(e_bc[:, None], B + (C - B) * t[:, None], res)
    res = np.where(((d1 <= 0) & (d2 <= 0))[:, None], A, res)
    res = np.where(((d3 >= 0) & (d4 <= d3))[:, None], B, res)
    res = np.where(((d6 >= 0) & (d5 <= d6))[:, None], C, res)
    return res


def face_normals(V, F):
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    return fn / np.maximum(np.linalg.norm(fn, axis=1), 1e-300)[:, None]


def vertex_normals(V: np.ndarray, F: np.ndarray) -> np.ndarray:
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    N = np.zeros_like(V)
    for k in range(3):
        np.add.at(N, F[:, k], fn)
    return N / np.maximum(np.linalg.norm(N, axis=1), 1e-300)[:, None]


def fit_mirror_plane(V: np.ndarray, F: np.ndarray, n0=None, sample: int = 6000, seed: int = 0) -> dict[str, Any]:
    """Robust best-fit mirror plane: point-to-tangent-plane distance of mirrored samples (nearest vertex + its normal), soft-L1 loss so
    one-sided features do not bias it. Candidates: PCA axes (or the hint); the best by median residual wins."""
    from scipy.optimize import least_squares
    from scipy.spatial import cKDTree
    rng = np.random.default_rng(seed)
    N = vertex_normals(V, F)
    used = np.unique(F.ravel())
    kd = cKDTree(V[used])
    Vu, Nu = V[used], N[used]
    P = Vu[rng.choice(len(Vu), min(sample, len(Vu)), replace=False)]
    c0 = Vu.mean(0)
    cands = [np.asarray(n0, float)] if n0 is not None else list(np.linalg.svd(P - c0, full_matrices=False)[2])

    def nrm(x, b):
        e1 = np.cross(b, [1, 0, 0] if abs(b[0]) < 0.9 else [0, 1, 0])
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(b, e1)
        n = b + x[0] * e1 + x[1] * e2
        return n / np.linalg.norm(n)

    best, tried = None, []
    for b in cands:
        b = b / np.linalg.norm(b)
        c = c0.copy()
        for _ in range(3):
            def res(x, b=b, c=c):
                n = nrm(x, b)
                M = mirror_pts(P, n, x[2] + c @ n)
                j = kd.query(M)[1]
                return ((M - Vu[j]) * Nu[j]).sum(1)
            r = least_squares(res, [0, 0, 0], loss='soft_l1', f_scale=0.3, diff_step=1e-4)
            b2 = nrm(r.x, b)
            off = r.x[2] + c @ b2
            c = c + (off - c @ b2) * b2
            b = b2
        n = b
        d = float(c @ n)
        dist = kd.query(mirror_pts(P, n, d))[0]
        rr = {'normal': n, 'd': d, 'p50': float(np.median(dist)), 'p80': float(np.percentile(dist, 80))}
        tried.append({'normal': n.tolist(), 'd': d, 'p50': rr['p50']})
        if best is None or rr['p50'] < best['p50']:
            best = rr
    n, d = best['normal'], best['d']
    for _ in range(2):                                                  # trimmed refit: one-sided features (> 3 x median) do not pull the plane
        dist = kd.query(mirror_pts(P, n, d))[0]
        keep = dist <= max(3.0 * float(np.median(dist)), 0.3)
        Pk = P[keep]
        c = c0 + ((d - c0 @ n) * n)

        def res2(x, b=n, c=c):
            nn = nrm(x, b)
            M = mirror_pts(Pk, nn, x[2] + c @ nn)
            j = kd.query(M)[1]
            return ((M - Vu[j]) * Nu[j]).sum(1)
        r = least_squares(res2, [0, 0, 0], loss='soft_l1', f_scale=0.3, diff_step=1e-4)
        n2 = nrm(r.x, n)
        d = float(r.x[2] + c @ n2)
        n = n2
    dist = kd.query(mirror_pts(P, n, d))[0]
    best = {**best, 'normal': n, 'd': d, 'p50': float(np.median(dist)), 'p80': float(np.percentile(dist, 80))}
    k = int(np.argmax(np.abs(n))) if abs(n[1]) < 0.3 else 1          # orient: toward +y (left) when lateral, else largest component positive
    if n[k] < 0:
        n, d = -n, -d
    return {'normal': n.tolist(), 'd': float(d), 'p50': best['p50'], 'p80': best['p80'], 'candidates': tried}


def region_mirror_test(V, F, region, names, n, d, p) -> tuple[dict[str, Any], np.ndarray]:
    used = np.unique(F.ravel())
    diag = float(np.linalg.norm(V[used].max(0) - V[used].min(0)))
    thr = max(p['abs_threshold_mm'], p['rel_threshold'] * diag)
    cell = p['cell_mm'] or max(8.0, 0.08 * diag)
    pct = p['stat_pct']
    sub = used[:: max(1, len(used) // 40000)]
    _, dist, tri = closest_on_surface(V, F, mirror_pts(V[sub], n, d))
    vdist = np.full(len(V), np.nan)
    vdist[sub] = dist
    vtri = np.full(len(V), -1)
    vtri[sub] = tri
    g = float(np.percentile(dist, pct))
    plane_valid = bool(g <= p['plane_gate_factor'] * thr)
    out = {'threshold_mm': thr, 'statistic': f'p{pct} of |mirror residual| (mm), unbounded, after the best-fit plane', 'abs_threshold_mm': p['abs_threshold_mm'],
           'rel_threshold': p['rel_threshold'], 'bbox_diag_mm': diag, 'cell_mm': cell,
           'global': {'p50': float(np.median(dist)), 'stat': g, 'samples': int(len(sub)), 'plane_valid': plane_valid,
                      'note': 'plane_valid is False when the global statistic exceeds plane_gate_factor x threshold: no usable mirror plane, nothing is symmetrised'},
           'regions': {}}
    s_ = V @ n - d
    fold = V - np.minimum(s_, 0)[:, None] * 2 * n
    key = np.floor(fold / cell).astype(np.int64)
    fkey = np.floor(fold[F].mean(1) / cell).astype(np.int64)
    asym_face = np.zeros(len(F), bool)
    ms = p['min_cell_samples']
    for r in np.unique(region):
        fr = np.flatnonzero(region == r)
        name = names[r]
        vi = np.unique(F[fr].ravel())
        vi = vi[~np.isnan(vdist[vi])]
        if len(fr) < p['min_region_faces'] or len(vi) < ms:
            out['regions'][name] = {'faces': int(len(fr)), 'symmetric': False, 'decision': 'too small to test: kept as scanned'}
            asym_face[fr] = True
            continue
        dv = vdist[vi]
        st = float(np.percentile(dv, pct))
        cells: dict[tuple, list] = {}
        for k, dd in zip(map(tuple, key[vi]), dv):
            cells.setdefault(k, []).append(dd)
        tested = {k: float(np.percentile(a, pct)) for k, a in cells.items() if len(a) >= ms}
        bad = {k for k, s in tested.items() if s > thr}
        if bad:
            asym_face[fr[np.fromiter((tuple(k) in bad for k in fkey[fr]), bool, len(fr))]] = True
        frac = len(bad) / max(len(tested), 1)
        sym = bool(plane_valid and st <= thr and frac <= 0.5)
        if not plane_valid:
            dec = 'skip: no usable mirror plane (kept as scanned)'
        elif not sym:
            dec = 'ASYMMETRIC: kept as scanned'
        elif bad:
            dec = f'symmetric except {len(bad)}/{len(tested)} cells (those kept as scanned)'
        else:
            dec = 'symmetric (difference = scan error, symmetrised)'
        vt = vtri[vi]
        cp = int(np.bincount(region[vt[vt >= 0]], minlength=len(names)).argmax())
        out['regions'][name] = {'faces': int(len(fr)), 'samples': int(len(vi)), 'p50': float(np.median(dv)), 'stat': st, 'cells': len(tested), 'asym_cells': len(bad),
                                'worst_cell_stat': max(tested.values()) if tested else None, 'counterpart': names[cp], 'symmetric': sym, 'decision': dec}
        if not sym:
            asym_face[fr] = True
    return out, asym_face


def roughness(V, N, idx, R=1.5):
    """per-vertex |offset| of a local quadric fit (side-quality metric)."""
    from scipy.spatial import cKDTree
    kd = cKDTree(V)
    out = np.zeros(len(idx))
    for k, i in enumerate(idx):
        nb = kd.query_ball_point(V[i], R)
        if len(nb) < 10:
            continue
        n = N[i]
        t1 = np.cross(n, [1, 0, 0] if abs(n[0]) < 0.9 else [0, 1, 0])
        t1 /= np.linalg.norm(t1)
        t2 = np.cross(n, t1)
        L = V[nb] - V[i]
        x, y, z = L @ t1, L @ t2, L @ n
        A = np.column_stack([np.ones_like(x), x, y, x * x, x * y, y * y])
        out[k] = abs(np.linalg.lstsq(A, z, rcond=None)[0][0])
    return out


def _st(a):
    a = np.abs(np.asarray(a, float))
    if a.size == 0:
        return {'p50': None, 'p95': None, 'max': None}
    return {'p50': float(np.median(a)), 'p95': float(np.percentile(a, 95)), 'max': float(a.max())}


def symmetrise(V, F, region, names, n, d, sym_regions, fixed_faces, pairs, p):
    from scipy.spatial import cKDTree
    cap, ramp, passes = p['correspondence_cap_mm'], p['ramp_mm'], p['passes']
    cand = np.isin(region, sym_regions) & ~fixed_faces
    Vn = V.copy()
    candV = np.zeros(len(V), bool)
    candV[F[cand].ravel()] = True
    fixV = np.zeros(len(V), bool)
    fixV[F[~cand].ravel()] = True
    idx = np.flatnonzero(candV & ~fixV)
    if len(idx) == 0 or not cand.any():
        return Vn, cand, {'pairs': [], 'moved_vertices': 0, 'displacement': _st([]), 'residual_before': _st([]), 'residual_after': _st([])}
    vreg = np.full(len(V), -1)
    for r in sym_regions:
        vreg[F[cand & (region == r)].ravel()] = r
    side = np.sign(V[idx] @ n - d)
    Fc = F[cand]

    def counterpart(X):
        vn = vertex_normals(X, F)
        q, dist, tri = closest_on_surface(X, Fc, mirror_pts(X[idx], n, d))
        fnq = face_normals(X, Fc)[tri]
        ok = (dist < cap) & ((mirror_pts(fnq, n, 0.0) * vn[idx]).sum(1) > 0.8)
        s = ((mirror_pts(q, n, d) - X[idx]) * vn[idx]).sum(1)
        return s, ok, vn

    s0, ok0, vn = counterpart(V)
    rng = np.random.default_rng(0)
    mode = np.zeros(len(idx))
    plog = []
    for pr in pairs:
        k = np.isin(vreg[idx], pr)
        if k.sum() < 20:
            continue
        qs = {}
        for sd in (1, -1):
            sel = np.flatnonzero(k & (side == sd))
            if len(sel) <= 10:
                qs[sd] = np.inf
                continue
            sel = sel if len(sel) <= 4000 else rng.choice(sel, 4000, replace=False)
            qs[sd] = float(np.percentile(roughness(V, vn, idx[sel]), 95))
        lo, hi = sorted(qs.values())
        if hi < 0.01 or lo / max(hi, 1e-9) > 0.7:
            dec, w = 'average both sides', (0.5, 0.5)
        else:
            better = min(qs, key=qs.get)
            dec = f'mirror the better side ({"+" if better > 0 else "-"} normal side)'
            w = (0.0, 1.0) if better > 0 else (1.0, 0.0)
        mode[k & (side > 0)] = w[0]
        mode[k & (side < 0)] = w[1]
        plog.append({'regions': [names[int(x)] for x in pr], 'side_roughness_p95': {'+': qs[1], '-': qs[-1]}, 'correction': dec,
                     'residual_before': _st(s0[k & ok0])})
    dU = cKDTree(V[fixV]).query(V[idx])[0] if fixV.any() else np.full(len(idx), np.inf)
    wgt = mode * np.clip((dU - 0.3) / ramp, 0, 1) * ok0
    for it in range(passes):
        s, ok, vn = counterpart(Vn)
        Vn = Vn.copy()
        Vn[idx] += (np.where(ok, s, 0) * wgt * (1.0 if it == 0 else 0.5))[:, None] * vn[idx]
    s1, ok1, _ = counterpart(Vn)
    disp = np.linalg.norm(Vn - V, axis=1)
    for L, pr in zip(plog, [pr for pr in pairs if np.isin(vreg[idx], pr).sum() >= 20]):
        k = np.isin(vreg[idx], pr)
        L['residual_after'] = _st(s1[k & ok1])
        L['moved_vs_scan'] = _st(disp[idx[k]])
    return Vn, cand, {'pairs': plog, 'moved_vertices': int((disp > 1e-9).sum()), 'displacement': _st(disp[idx]),
                      'residual_before': _st(s0[ok0]), 'residual_after': _st(s1[ok1])}


def load_mesh(path: Path, scale: float):
    import trimesh
    m = trimesh.load(str(path), process=False, force='mesh')
    m.merge_vertices()
    V = np.asarray(m.vertices, float) * scale
    F = np.asarray(m.faces, np.int64)
    if len(F) == 0:
        raise WorkerError('SYMMETRISE_MESH', 'The mesh has no faces.')
    return V, F, bool(m.is_watertight)


def run(req: dict[str, Any]) -> dict[str, Any]:
    import trimesh
    p = {**DEFAULTS, **(req.get('params') or {})}
    inp = req['inputs']
    V, F, wt = load_mesh(Path(inp['mesh']), float(p['unit_scale']))
    region, names = read_regions(Path(inp['labels']) if inp.get('labels') else None, len(F))
    warnings = [] if inp.get('labels') else ['No labels given: the whole mesh is one region; the per-cell test still decides locally.']
    hint = {'lateral': [0.0, 1.0, 0.0], 'pca': None, 'hint': p['normal_hint']}[p['plane_search']]
    pl = fit_mirror_plane(V, F, hint)
    n, d = np.asarray(pl['normal']), pl['d']
    test, asym_face = region_mirror_test(V, F, region, names, n, d, p)
    fixed_ids = [names.index(r) for r in p['fixed_regions'] if r in names]
    excl_ids = [names.index(r) for r in p['exclude_regions'] if r in names]
    lands = np.zeros(len(F), bool)
    if fixed_ids:
        _, dist, tri = closest_on_surface(V, F, mirror_pts(V[F].mean(1), n, d))
        lands = np.isin(region[tri], fixed_ids) & (dist < test['threshold_mm'])
    fixed = asym_face | np.isin(region, fixed_ids + excl_ids) | lands
    sym_regions = [names.index(k) for k, v in test['regions'].items() if v['symmetric'] and names.index(k) not in fixed_ids + excl_ids]
    pairs, seen = [], set()
    for r in sym_regions:
        if r in seen:
            continue
        cp = names.index(test['regions'][names[r]]['counterpart'])
        pr = (r, cp) if (cp in sym_regions and cp != r and cp not in seen) else (r,)
        pairs.append(pr)
        seen.update(pr)
    if test['global']['plane_valid']:
        Vn, cand, slog = symmetrise(V, F, region, names, n, d, sym_regions, fixed, pairs, p)
    else:
        Vn, cand, slog = V.copy(), np.zeros(len(F), bool), {'pairs': [], 'moved_vertices': 0, 'displacement': _st([]), 'residual_before': _st([]), 'residual_after': _st([])}
        warnings.append('No usable mirror plane: the mesh is written unchanged.')
    disp = np.linalg.norm(Vn - V, axis=1)
    keptV = np.zeros(len(V), bool)
    keptV[F[~cand].ravel()] = True
    out = Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    trimesh.Trimesh(Vn, F, process=False).export(str(out / 'symmetrised.stl'))
    np.savez_compressed(out / 'symmetry_mask.npz', asymmetric_face=asym_face, fixed_face=fixed, symmetrised_face=cand, face_displacement_mm=disp[F].max(1))
    plane = {'normal': pl['normal'], 'd': pl['d'], 'frame': 'input mesh frame (mm)', 'equation': 'normal . x = d',
             'fit_p50_mm': pl['p50'], 'fit_p80_mm': pl['p80']}
    (out / 'mirror_plane.json').write_text(json.dumps({'plane': plane, 'threshold_mm': test['threshold_mm'], 'abs_threshold_mm': test['abs_threshold_mm'],
                                                       'rel_threshold': test['rel_threshold'], 'stat_pct': p['stat_pct']}, indent=1), encoding='utf-8')
    check = trimesh.load(str(out / 'symmetrised.stl'), process=False, force='mesh')
    check.merge_vertices()
    return {'worker': WORKER_VERSION, 'warnings': warnings, 'plane': plane, 'plane_candidates': pl['candidates'], 'symmetry_test': test,
            'symmetrise': {**slog, 'symmetrised_regions': [names[r] for r in sym_regions], 'kept_as_scanned_regions': [x for x in names if names.index(x) not in sym_regions],
                           'fixed_regions_present': [names[r] for r in fixed_ids], 'excluded_regions_present': [names[r] for r in excl_ids],
                           'faces_in_asymmetric_cells': int(asym_face.sum()), 'faces_mirroring_onto_fixed': int(lands.sum()),
                           'symmetrised_faces': int(cand.sum()), 'correspondence_cap_mm': p['correspondence_cap_mm'],
                           'max_displacement_kept_faces_mm': float(disp[keptV].max()) if keptV.any() else 0.0},
            'mesh': {'faces': int(len(F)), 'vertices': int(len(V)), 'watertight_before': wt, 'watertight_after': bool(check.is_watertight),
                     'faces_after': int(len(check.faces))},
            'files': {'mesh': 'symmetrised.stl', 'mask': 'symmetry_mask.npz', 'plane': 'mirror_plane.json'}, 'params_used': p}


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
