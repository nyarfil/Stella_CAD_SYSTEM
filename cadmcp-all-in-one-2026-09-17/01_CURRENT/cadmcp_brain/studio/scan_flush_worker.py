"""Bottom-plate flush of a welded scan mesh. SUBPROCESS WORKER (like scan_click_grooves_worker.py).

Run as:  <scan python> scan_flush_worker.py request.json
Needs numpy and trimesh (extra `scan-grooves`). Request and result are JSON; the result is the last stdout line.

Method: the candidate plate faces (the bottom_plate label when given, else every face) whose outward normal points down (n_z < -min_down_nz) are
searched for the dominant plane by area-weighted RANSAC (fixed seed, reproducible); when it carries at least half of the underside area it is the
reference plate (skates protruding below it are reported). Otherwise (recessed underside, ribs) the SUPPORT plane, the plane the mouse stands on, is
fitted: candidate normals come from the lower convex hull of per-cell low points of the underside
(plus the dominant plane), each plane is placed so that at most max_protrusion_pct of the area lies below it (skates, noise), and the plane with the
largest contact area (|distance| < plate_tolerance_mm) and a stable footprint wins. An underside with a recess, ribs or a rim is supported by its lowest contact ring and the recessed parts
are reported (area, depth), not treated as errors. If no support plane qualifies, the dominant plane is the fallback. The plane is refitted on its contact faces (weighted SVD), the
minimal rotation that makes its normal +z is applied, and the plane is shifted onto z = 0. Features that protrude below the plane (skates, feet)
therefore end up at z < 0 and are reported, never clipped. Face order and count are unchanged, so every label file stays valid.
"""
from __future__ import annotations
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any
import numpy as np

WORKER_VERSION = 'scan_flush/1'
DEFAULTS = {'plate_tolerance_mm': 0.12, 'min_down_nz': 0.95, 'ransac_iterations': 3000, 'max_tilt_deg': 20.0, 'max_protrusion_pct': 5.0}
DOMINANT_MIN_PCT = 50.0          # a flat plate carrying at least this share of the underside area is the reference plane as it always was (skates are reported)
MIN_CONTACT_SPREAD = 0.5       # the contact faces' xy hull must cover at least this share of the underside footprint (a stable support, not a wedge or a ridge)
SUPPORT_CELLS = 60            # underside grid resolution along the longer bbox side (cell size derives from the input extent)
PLATE_ALIASES = ('bottom_plate', 'base_plate', 'plate', 'bottom')


class FlushError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


def read_plate_ids(path: Path, n_faces: int) -> np.ndarray:
    """Plate face ids from a .json ({name: [ids]} or {"regions": {name: {"face_ids": [...]}}}) or .npz (face_labels + codes 'name=code')."""
    ids = None
    if path.suffix.lower() == '.npz':
        z = np.load(path, allow_pickle=False)
        if 'face_labels' not in z or 'codes' not in z:
            raise FlushError('FLUSH_LABELS', 'An .npz label file needs the arrays face_labels and codes ("name=code").')
        fl = z['face_labels']
        if len(fl) != n_faces:
            raise FlushError('FLUSH_LABELS', 'face_labels has a different length than the mesh has faces.', {'labels': int(len(fl)), 'faces': int(n_faces)})
        for item in z['codes']:
            name, code = str(item).rsplit('=', 1)
            if name in PLATE_ALIASES:
                ids = np.flatnonzero(fl == int(code))
                break
    else:
        data = json.loads(path.read_text(encoding='utf-8'))
        data = data.get('regions', data) if isinstance(data, dict) else data
        if not isinstance(data, dict):
            raise FlushError('FLUSH_LABELS', 'The label JSON must map region names to face id lists.')
        for k in PLATE_ALIASES:
            if k in data:
                val = data[k]
                val = val.get('face_ids') if isinstance(val, dict) else val
                if isinstance(val, list):
                    ids = np.asarray(val, dtype=np.int64)
                    break
    if ids is None or len(ids) == 0:
        raise FlushError('FLUSH_PLATE_LABEL_MISSING', 'The label file has no bottom_plate region (names accepted: ' + ', '.join(PLATE_ALIASES) + ').')
    if ids.min() < 0 or ids.max() >= n_faces:
        raise FlushError('FLUSH_LABELS', 'The plate region has face ids outside the mesh.')
    return np.unique(ids)


def face_geometry(V: np.ndarray, F: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    tri = V[F]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    a = np.linalg.norm(n, axis=1)
    return n / np.maximum(a, 1e-300)[:, None], a / 2.0, tri.mean(1)


def weighted_plane(P: np.ndarray, w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mu = (P * w[:, None]).sum(0) / w.sum()
    nn = np.linalg.svd((P - mu) * np.sqrt(w)[:, None], full_matrices=False)[2][2]
    return mu, (nn if nn[2] > 0 else -nn)


def ransac_plane(P: np.ndarray, A: np.ndarray, tol: float, iters: int, min_nz: float = 0.98, seed: int = 0):
    rng = np.random.default_rng(seed)
    best = None
    n = len(P)
    for _ in range(iters):
        i = rng.choice(n, 3, replace=False)
        p = P[i]
        nn = np.cross(p[1] - p[0], p[2] - p[0])
        ln = np.linalg.norm(nn)
        if ln < 1e-9:
            continue
        nn = nn / ln
        nn = nn if nn[2] > 0 else -nn
        if nn[2] < min_nz:
            continue
        inl = np.abs((P - p[0]) @ nn) < tol
        score = A[inl].sum()
        if best is None or score > best[0]:
            best = (score, inl)
    return best


def _hull_xy_area(xy: np.ndarray) -> float:
    if len(xy) < 3:
        return 0.0
    from scipy.spatial import ConvexHull, QhullError
    try:
        return float(ConvexHull(xy).volume)
    except QhullError:
        return 0.0


def support_plane(P: np.ndarray, A: np.ndarray, tol: float, max_tilt_deg: float, max_prot_frac: float, iters: int = 3000, seed: int = 0):
    """Support plane of the underside points P (area weights A): returns (inlier mask, point, up normal, info) or None.
    Candidate normals = the facets of the lower convex hull of the per-cell low points of the underside (a rim, ring or set of pads) plus the dominant
    RANSAC plane (a flat plate that carries small protruding skates). For each normal the plane is placed so that at most max_prot_frac of the area lies
    below it (area-weighted quantile; skates, noise), then refitted on its contact faces (|distance| < tol). The admissible candidate (tilt within
    max_tilt_deg, protrusion within max_prot_frac, contact xy hull >= MIN_CONTACT_SPREAD of the footprint) with the largest contact area wins."""
    from scipy.spatial import ConvexHull, QhullError
    ext = P[:, :2].max(0) - P[:, :2].min(0)
    cell = max(float(ext.max()) / SUPPORT_CELLS, 1e-6)
    ij = np.floor((P[:, :2] - P[:, :2].min(0)) / cell).astype(np.int64)
    key = ij[:, 0] * (ij[:, 1].max() + 1) + ij[:, 1]
    order = np.lexsort((P[:, 2], key))
    ks = key[order]
    starts = np.flatnonzero(np.r_[True, ks[1:] != ks[:-1]])
    stops = np.r_[starts[1:], len(ks)]
    sel = []
    for a0, a1 in zip(starts, stops):          # per cell: the area-weighted 10 % low quantile of z (robust against single spikes)
        idx = order[a0:a1]
        w = np.cumsum(A[idx])
        sel.append(idx[min(int(np.searchsorted(w, 0.1 * w[-1])), len(idx) - 1)])
    pts = P[np.asarray(sel)]
    cos_max = float(np.cos(np.radians(max_tilt_deg)))
    total = float(A.sum())
    foot = _hull_xy_area(P[:, :2])
    normals: list[np.ndarray] = []
    if len(pts) >= 4:
        try:
            hull = ConvexHull(pts)
            for eq in hull.equations:
                nn = -eq[:3]                      # the outward hull normal points down on the lower hull; the plane normal points up
                if nn[2] >= cos_max:
                    normals.append(nn)
        except QhullError:
            pass
    dom = ransac_plane(P, A, tol, iters, min_nz=cos_max, seed=seed)
    if dom is not None:
        normals.append(weighted_plane(P[dom[1]], A[dom[1]])[1])
    if not normals:
        return None
    rng = np.random.default_rng(seed)
    sub = rng.choice(len(P), min(len(P), 8000), replace=False)      # coarse scoring on a subset, exact scoring on the short list
    Ps, As = P[sub], A[sub]
    scored = []
    for nn in normals:
        d = Ps @ nn
        o = np.argsort(d)
        q = float(d[o][min(int(np.searchsorted(np.cumsum(As[o]), max_prot_frac * As.sum())), len(o) - 1)])
        scored.append((float(As[np.abs(d - q) < tol].sum()), nn, q))
    scored.sort(key=lambda c: -c[0])
    best = None
    for _, nn, q in scored[:25]:
        mu = P[int(np.argmin(np.abs(P @ nn - q)))]
        for _ in range(5):                        # refit on the contact faces
            inl = np.abs((P - mu) @ nn) < tol
            if inl.sum() < 3:
                break
            mu, nn = weighted_plane(P[inl], A[inl])
        sd = (P - mu) @ nn
        if nn[2] < cos_max or float(A[sd < -tol].sum()) > max_prot_frac * total:
            continue
        inl = np.abs(sd) < tol
        contact = float(A[inl].sum())
        if (best is None or contact > best[0]) and _hull_xy_area(P[inl, :2]) >= MIN_CONTACT_SPREAD * foot:
            best = (contact, inl, mu, nn)
    if best is None:
        return None
    _, inl, mu, nn = best
    spread = _hull_xy_area(P[inl, :2]) / max(foot, 1e-12)
    return inl, mu, nn, {'method': 'support_plane', 'candidate_normals': int(len(normals)), 'cell_mm': cell, 'contact_hull_ratio': float(spread)}


def rotation_to_z(nn: np.ndarray) -> np.ndarray:
    z = np.array([0.0, 0.0, 1.0])
    v = np.cross(nn, z)
    s = np.linalg.norm(v)
    if s < 1e-12:
        return np.eye(3)
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K * ((1 - float(nn @ z)) / s ** 2)


def tilt_deg(nn: np.ndarray) -> float:
    return float(np.degrees(np.arccos(np.clip(nn[2], -1, 1))))


def plate_stats(V: np.ndarray, F: np.ndarray, cand: np.ndarray, tol: float) -> dict[str, Any]:
    """Support-plane quality relative to z = 0 on the candidate underside faces (area weighted): contact (|z| < tol), recessed (z > tol, above the
    plane: pockets, ribs between contact rings) and protruding (z < -tol, below the plane: skates, noise) parts."""
    n, a, cen = face_geometry(V, F)
    z = cen[cand, 2]
    ac = a[cand]
    inl = cand[np.abs(z) < tol]
    area_all, area_in = float(ac.sum()), float(a[inl].sum())
    rec, pro = z > tol, z < -tol
    out: dict[str, Any] = {'candidate_faces': int(len(cand)), 'candidate_area_mm2': area_all, 'within_tol_faces': int(len(inl)), 'within_tol_area_mm2': area_in,
                           'within_tol_pct_area': 100.0 * area_in / area_all if area_all else 0.0, 'fit_tilt_deg': 0.0,
                           'recessed_area_mm2': float(ac[rec].sum()), 'recessed_pct_area': 100.0 * float(ac[rec].sum()) / area_all if area_all else 0.0,
                           'recessed_max_depth_mm': float(z[rec].max()) if rec.any() else 0.0,
                           'recessed_depth_p50_mm': float(np.median(z[rec])) if rec.any() else 0.0,
                           'protruding_area_mm2': float(ac[pro].sum()), 'protruding_pct_area': 100.0 * float(ac[pro].sum()) / area_all if area_all else 0.0,
                           'protruding_max_depth_mm': float(-z[pro].min()) if pro.any() else 0.0,
                           'contact_hull_ratio': (_hull_xy_area(cen[inl, :2]) / max(_hull_xy_area(cen[cand, :2]), 1e-12)) if len(inl) >= 3 else 0.0}
    if len(inl) >= 3:
        mu, nn = weighted_plane(cen[inl], a[inl])
        zi = cen[inl, 2]
        m = float(np.average(zi, weights=a[inl]))
        out.update({'mean_z_mm': m, 'rms_z_mm': float(np.sqrt(np.average((zi - m) ** 2, weights=a[inl]))), 'fit_tilt_deg': tilt_deg(nn)})
    return out


def run(req: dict[str, Any]) -> dict[str, Any]:
    t0 = time.time()
    try:
        import trimesh
    except ImportError as exc:
        raise FlushError('FLUSH_LIBRARY_UNAVAILABLE', 'trimesh is missing in the scan python (extra scan-grooves).', {'module': str(exc)}) from exc
    P = req['params']
    tol, min_nz, iters, max_tilt = float(P['plate_tolerance_mm']), float(P['min_down_nz']), int(P['ransac_iterations']), float(P['max_tilt_deg'])
    max_prot = float(P.get('max_protrusion_pct', DEFAULTS['max_protrusion_pct']))
    mesh = trimesh.load(req['input_path'], force='mesh', process=False)
    mesh.merge_vertices()
    V = np.asarray(mesh.vertices, float) * float(req['unit_scale'])
    F = np.asarray(mesh.faces, np.int64)
    src = trimesh.Trimesh(V, F, process=False)
    warnings: list[dict[str, Any]] = []
    if src.is_watertight and src.volume <= 0:
        raise FlushError('FLUSH_MESH_INSIDE_OUT', 'The mesh volume is not positive: the faces must be outward oriented (plate normals point down).', {'volume_mm3': float(src.volume)})
    if not src.is_watertight:              # a rigid flush does not need a closed surface; the fit only uses the plate faces
        warnings.append({'code': 'FLUSH_MESH_NOT_WATERTIGHT', 'message': 'The input mesh is not watertight; the flush is rigid and still valid, but downstream mesh tools need a closed mesh.'})
    N = len(F)
    n, a, cen = face_geometry(V, F)
    labels = Path(req['labels_path']) if req.get('labels_path') else None
    if labels is not None:
        plate = read_plate_ids(labels, N)
        source = 'labels'
    else:
        plate = np.arange(N)
        source = 'all_faces'
        warnings.append({'code': 'FLUSH_NO_LABELS', 'message': 'No labels: the dominant down-facing plane of the whole mesh is used; give a bottom_plate region to be certain.'})
    def fit_plane(ids: np.ndarray):
        c = ids[n[ids, 2] < -min_nz]
        if len(c) < 10:
            return None
        P_, A_ = cen[c], a[c]
        b = ransac_plane(P_, A_, tol, iters, min_nz=min_nz)
        if b is not None and 100.0 * float(A_[b[1]].sum()) / float(A_.sum()) >= DOMINANT_MIN_PCT:
            m_, nn_ = weighted_plane(P_[b[1]], A_[b[1]])
            return c, P_, A_, b[1], m_, nn_, {'method': 'dominant_plane'}
        sp = support_plane(P_, A_, tol, max_tilt, max_prot / 100.0, iters=iters)    # recessed / ribbed underside: the plane the mouse stands on
        if sp is not None:
            return c, P_, A_, sp[0], sp[1], sp[2], sp[3]
        if b is None:
            return None
        m_, nn_ = weighted_plane(P_[b[1]], A_[b[1]])
        return c, P_, A_, b[1], m_, nn_, {'method': 'dominant_plane_fallback'}

    chosen = fit_plane(plate)
    if labels is not None:                       # labels are a hint: cross-check with the whole mesh; the geometry decides
        whole = fit_plane(np.arange(N))
        if chosen is not None and whole is not None:
            ang = float(np.degrees(np.arccos(np.clip(abs(float(chosen[5] @ whole[5])), -1, 1))))
            off = float(abs((chosen[4] - whole[4]) @ whole[5]))
            if ang > 0.3 or off > tol:
                use_whole = float(whole[2][whole[3]].sum()) > float(chosen[2][chosen[3]].sum())
                warnings.append({'code': 'FLUSH_LABEL_DISAGREES', 'message': 'The plane fitted on the bottom_plate label differs from the plane fitted on the whole mesh; the one with more inlier area is used.',
                                 'details': {'angle_deg': ang, 'offset_mm': off, 'label_inlier_area_mm2': float(chosen[2][chosen[3]].sum()),
                                             'whole_inlier_area_mm2': float(whole[2][whole[3]].sum()), 'used': 'whole_mesh' if use_whole else 'labels'}})
                if use_whole:
                    chosen, source = whole, 'all_faces (label disagreed)'
        elif chosen is None and whole is not None:
            chosen, source = whole, 'all_faces (label unusable)'
            warnings.append({'code': 'FLUSH_LABEL_UNUSABLE', 'message': 'No plane was found on the bottom_plate label; the whole mesh was used.'})
    if chosen is None:
        raise FlushError('FLUSH_NO_PLANE', 'No down-facing plane within the allowed tilt was found (the mesh must be in the standard frame, z up, plate roughly horizontal).', {'min_down_nz': min_nz})
    cand, Pc, Ac, inl, mu, nn, pinfo = chosen
    tilt = tilt_deg(nn)
    if tilt > max_tilt:
        raise FlushError('FLUSH_TILT_TOO_LARGE', f'The fitted plate is tilted {tilt:.2f} deg, above max_tilt_deg; refusing to guess.', {'tilt_deg': tilt, 'max_tilt_deg': max_tilt})
    resid = (Pc[inl] - mu) @ nn
    w = Ac[inl]
    fit = {**pinfo, 'plate_source': source, 'candidate_faces': int(len(cand)), 'candidate_area_mm2': float(Ac.sum()), 'inlier_faces': int(inl.sum()), 'inlier_area_mm2': float(w.sum()),
           'inlier_area_pct': float(100 * w.sum() / Ac.sum()), 'rms_mm': float(np.sqrt(np.average(resid ** 2, weights=w))), 'max_abs_mm': float(np.abs(resid).max()),
           'normal_before': nn.tolist(), 'tilt_before_deg': tilt,
           'inlier_xy_extent_mm': [float(Pc[inl, 0].min()), float(Pc[inl, 0].max()), float(Pc[inl, 1].min()), float(Pc[inl, 1].max())]}
    if fit['method'] == 'dominant_plane_fallback':
        warnings.append({'code': 'FLUSH_SUPPORT_PLANE_FALLBACK', 'message': 'No support plane with at most max_protrusion_pct of the underside below it was found; the dominant plane (largest flat area) was used instead.'})
    Rm = rotation_to_z(nn)
    z_shift = float(-(Rm @ mu)[2])
    V2 = V @ Rm.T
    V2[:, 2] += z_shift
    T4 = np.eye(4)
    T4[:3, :3], T4[2, 3] = Rm, z_shift
    after = plate_stats(V2, F, cand, tol)
    fit['tilt_after_deg'] = after['fit_tilt_deg']
    if after['recessed_pct_area'] > 20:
        warnings.append({'code': 'FLUSH_UNDERSIDE_RECESSED', 'message': 'A large part of the underside lies above the support plane (recess, pockets, ribs); it is reported in after.recessed_*, not treated as an error.',
                         'details': {'recessed_pct_area': after['recessed_pct_area'], 'recessed_max_depth_mm': after['recessed_max_depth_mm']}})
    if after['protruding_pct_area'] > 0.5 * max_prot:
        warnings.append({'code': 'FLUSH_UNDERSIDE_PROTRUDES', 'message': 'Underside parts lie below the support plane (skates or noise); they stay at z < 0 and are reported in after.protruding_*.',
                         'details': {'protruding_pct_area': after['protruding_pct_area'], 'protruding_max_depth_mm': after['protruding_max_depth_mm']}})
    out_dir = Path(req['out_dir'])
    out_dir.mkdir(parents=True, exist_ok=True)
    flushed = trimesh.Trimesh(V2, F, process=False)
    flushed.export(out_dir / 'flushed.stl')
    transform = {'schema': 'scan_flush_transform/1', 'applied_to': 'input mesh in mm after the unit factor: V2 = V @ Rm.T; V2[:, 2] += z_shift', 'Rm': Rm.tolist(),
                 'z_shift': z_shift, 'matrix4': T4.tolist(), 'plane_tilt_deg_removed': tilt, 'plane_point_before_mm': mu.tolist()}
    (out_dir / 'flush_transform.json').write_text(json.dumps(transform, indent=1), encoding='utf-8')
    files: dict[str, Any] = {'flushed': {'file': 'flushed.stl', 'faces': int(N)}, 'transform': {'file': 'flush_transform.json'}}
    if labels is not None:                       # face order is unchanged: the same labels stay valid; copied next to the mesh for the downstream tools
        (out_dir / ('labels' + labels.suffix.lower())).write_bytes(labels.read_bytes())
        files['labels'] = {'file': 'labels' + labels.suffix.lower()}
    lowest = float(V2[:, 2].min())
    return {'status': 'OK', 'worker': WORKER_VERSION, 'params_used': {'plate_tolerance_mm': tol, 'min_down_nz': min_nz, 'ransac_iterations': iters, 'max_tilt_deg': max_tilt, 'max_protrusion_pct': max_prot},
            'fit': fit, 'transform': transform, 'after': after,
            'extent': {'bbox_before_mm': [V.min(0).tolist(), V.max(0).tolist()], 'bbox_after_mm': [V2.min(0).tolist(), V2.max(0).tolist()], 'lowest_z_after_mm': lowest,
                       'protrusion_below_plate_mm': max(0.0, -lowest)},
            'mesh': {'faces': int(N), 'watertight': bool(flushed.is_watertight), 'volume_mm3_before': float(src.volume) if src.is_watertight else None, 'volume_mm3_after': float(flushed.volume) if flushed.is_watertight else None},
            'files': files, 'warnings': warnings, 'seconds': round(time.time() - t0, 2)}


def main(argv: list[str]) -> int:
    try:
        req = json.loads(Path(argv[1]).read_text(encoding='utf-8'))
        res = run(req)
    except FlushError as exc:
        res = {'status': 'FAILED', 'error': {'code': exc.code, 'message': exc.message, 'details': exc.details}}
    except Exception as exc:
        res = {'status': 'FAILED', 'error': {'code': 'FLUSH_WORKER', 'message': f'{type(exc).__name__}: {exc}', 'trace': traceback.format_exc()[-1500:]}}
    sys.stdout.write('\n' + json.dumps(res, allow_nan=False, default=_json_default) + '\n')
    return 0 if res.get('status') == 'OK' else 2


def _json_default(o):
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.bool_):
        return bool(o)
    raise TypeError(type(o).__name__)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
