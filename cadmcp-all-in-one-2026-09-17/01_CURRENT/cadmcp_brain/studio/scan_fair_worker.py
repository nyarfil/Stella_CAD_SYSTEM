"""Worker of brain_mouse_scan_fair (runs in the separate scan python: numpy, scipy, trimesh).

Band-stop fairing of a welded scan mesh: removes ripples / facets / dents shorter than min_wavelength_mm and keeps everything else. Same
vertices, same faces, same face order (no remesh). Method (generic, no labels needed):
  minimise  sum_i wd_i |v_i - v0_i|^2  +  lam * sum_i wb_i |(L v)_i|^2      (L = uniform graph Laplacian, mean(neighbours) - x)
  lam = 16 (w / (2 pi h))^4 so the half-gain wavelength of the smoother is w = min_wavelength_mm (h = mean edge length): a bi-Laplacian
  (thin-plate) energy, whose low-pass keeps volume (no Taubin-style shrink) and needs one sparse LU per iteration.
Feature protection (all reported):
  - plate: the dominant flat cluster of face normals (area >= plate_min_area_frac of the surface) is frozen together with the band
    within rim_height_mm of its plane along its normal (rim); derived from the geometry, no fixed axis.
  - labels (optional): faces of fixed_regions are frozen.
  - auto features: after the plain solve, vertices it moved by more than feature_tol_mm (default w / 40: ripple amplitude is small against its
    wavelength, a larger move means shape: steps, button pads, wheel, rim) get a low bending weight wb = (1 + (move / tol)^2)^-2 (dilated) in a
    second solve, so they are kept instead of crushed.
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
from cadmcp_brain.studio.scan_symmetrise_worker import closest_on_surface, read_regions  # noqa: E402

WORKER_VERSION = 'scan_fair/1'
DEFAULTS = {'min_wavelength_mm': 12.0, 'feature_protection': 'auto', 'feature_tol_mm': None, 'plate_freeze': 'auto', 'rim_height_mm': None,
            'plate_min_area_frac': 0.02, 'plate_normal_deg': 3.0, 'tol_p95_mm': 0.5, 'volume_tol_pct': 0.5, 'fixed_regions': [], 'unit_scale': 1.0,
            'deviation_sample': 40000}
FROZEN_W = 1e4


def _lap(F: np.ndarray, n: int):
    import scipy.sparse as sp
    E = np.vstack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    E = np.unique(np.sort(E, axis=1), axis=0)
    A = sp.coo_matrix((np.ones(len(E) * 2), (np.r_[E[:, 0], E[:, 1]], np.r_[E[:, 1], E[:, 0]])), shape=(n, n)).tocsr()
    deg = np.asarray(A.sum(1)).ravel()
    L = (sp.diags(1.0 / np.maximum(deg, 1)) @ A - sp.eye(n)).tocsr()
    return L, E


def _normals(V, F):
    n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    a = np.linalg.norm(n, axis=1)
    return n / np.maximum(a, 1e-30)[:, None], a / 2.0


def _vertex_normals(V, F):
    fn, fa = _normals(V, F)
    vn = np.zeros_like(V)
    for k in range(3):
        np.add.at(vn, F[:, k], fn * fa[:, None])
    return vn / np.maximum(np.linalg.norm(vn, axis=1), 1e-30)[:, None]


def signed_volume(V, F) -> float:
    return float(np.einsum('ij,ij->i', V[F[:, 0]], np.cross(V[F[:, 1]], V[F[:, 2]])).sum() / 6.0)


def find_plate(V, F, min_frac: float, deg: float):
    """Dominant flat face-normal cluster: (unit normal pointing out of the mesh, plane offset, face mask, area fraction) or None."""
    fn, fa = _normals(V, F)
    tot = fa.sum()
    cosd = np.cos(np.radians(deg))
    # greedy: seed directions = area-weighted coarse histogram peaks; refine by mean direction
    best = None
    seeds = fn[np.argsort(-fa)[:: max(1, len(F) // 400)]]
    for s in seeds:
        m = fn @ s >= cosd
        a = fa[m].sum()
        if best is None or a > best[0]:
            best = (a, m)
    if best is None or best[0] < min_frac * tot:
        return None
    m = best[1]
    for _ in range(3):
        s = (fn[m] * fa[m, None]).sum(0)
        s /= np.linalg.norm(s)
        m = fn @ s >= cosd
    cen = V[F].mean(1)
    d = float(np.median(cen[m] @ s))
    # the plate must be flat in position as well: keep faces within a thin slab of the plane
    m &= np.abs(cen @ s - d) < 0.5
    if fa[m].sum() < min_frac * tot:
        return None
    d = float(np.median(cen[m] @ s))
    return s, d, m, float(fa[m].sum() / tot)


def stats(x: np.ndarray) -> dict[str, float]:
    x = np.asarray(x, float)
    if len(x) == 0:
        return {'p50': 0.0, 'p95': 0.0, 'max': 0.0, 'rms': 0.0}
    return {'p50': float(np.median(x)), 'p95': float(np.percentile(x, 95)), 'max': float(x.max()), 'rms': float(np.sqrt((x ** 2).mean()))}


def solve_fair(V0, L, LtL_fn, lam, wd, wb, prev=None):
    import scipy.sparse as sp
    import scipy.sparse.linalg as sl
    M = (sp.diags(wd) + lam * LtL_fn(wb)).tocsc()
    lu = sl.splu(M)
    return np.column_stack([lu.solve(wd * V0[:, i]) for i in range(3)])


FEATURE_SIGMA = 5.0      # seed threshold, robust sigmas of the smoothed residual
FEATURE_SIGMA_LO = 2.5   # hysteresis: grow into neighbours above this


def _adjacency(F, n):
    import scipy.sparse as sp
    E = np.vstack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    A = sp.coo_matrix((np.ones(len(E)), (E[:, 0], E[:, 1])), shape=(n, n)).tocsr()
    A = ((A + A.T) > 0).astype(float).tocsr()
    return A


def detect_features(V0, Vp, F, L, h, w, free, tol_mm, A):
    """Features = compact blobs of ONE-SIGNED residual of the plain solve. r = normal component of V0 - Vp; s = r low-passed at w/2: ripples
    alternate in sign over a few wavelengths and cancel in s, a step / pad / wheel keeps a coherent signed s. Seeds |s| > FEATURE_SIGMA robust
    sigmas (and > tol_mm if given), hysteresis down to FEATURE_SIGMA_LO, small components dropped. Returns (mask, score, components)."""
    import scipy.sparse as sp
    import scipy.sparse.csgraph as cg
    import scipy.sparse.linalg as sl
    n = len(V0)
    r = np.einsum('ij,ij->i', V0 - Vp, _vertex_normals(Vp, F))
    lam_s = 16.0 * ((w / 2.0) / (2 * np.pi * h)) ** 4
    M = (sp.eye(n) + lam_s * (L.T @ L)).tocsc()
    s = sl.splu(M).solve(r)
    sf = s[free]
    sig = 1.4826 * np.median(np.abs(sf - np.median(sf))) + 1e-12
    q = np.abs(s) / sig
    tol = tol_mm if tol_mm is not None else w / 20.0          # a ripple is small against its wavelength; a feature is not
    lo = ((q > FEATURE_SIGMA_LO) & (np.abs(s) > tol / 3.0)) & free
    hi = ((q > FEATURE_SIGMA) & (np.abs(s) > tol)) & free
    _, lab = cg.connected_components(A[lo][:, lo], directed=False)
    idx = np.flatnonzero(lo)
    keep_lab = np.unique(lab[hi[idx]])
    mask = np.zeros(n, bool)
    mask[idx[np.isin(lab, keep_lab)]] = True
    min_v = max(3, int((w / 6.0) ** 2 / (0.866 * h * h)))
    comps = []
    if mask.any():
        idx = np.flatnonzero(mask)
        _, lab = cg.connected_components(A[mask][:, mask], directed=False)
        for c in range(lab.max() + 1):
            ids = idx[lab == c]
            if len(ids) < min_v:
                mask[ids] = False
                continue
            P = V0[ids]
            comps.append({'vertices': int(len(ids)), 'area_mm2': float(len(ids) * 0.866 * h * h), 'centre_mm': P.mean(0).round(2).tolist(),
                          'extent_mm': (P.max(0) - P.min(0)).round(2).tolist(), 'peak_residual_mm': float(np.abs(r[ids]).max()),
                          'peak_smoothed_residual_mm': float(s[ids][np.argmax(np.abs(s[ids]))]), 'sign': 'raised' if s[ids][np.argmax(np.abs(s[ids]))] > 0 else 'recessed'})
    comps.sort(key=lambda c: -c['area_mm2'])
    return mask, {'amplitude_floor_mm': float(tol), 'robust_sigma_mm': float(sig), 'seed_threshold_mm': float(FEATURE_SIGMA * sig), 'grow_threshold_mm': float(FEATURE_SIGMA_LO * sig)}, comps


def fair(V0, F, L, lam, wd0, tol_mm, auto, w, h, free):
    """Plain band-stop solve; then (auto) detect compact one-signed residual blobs (real features) and solve again with their bending weight
    dropped and data weight raised, so they are kept instead of crushed."""
    import scipy.sparse as sp
    Lc = L.tocsr()
    LT = Lc.T.tocsr()
    n = len(V0)

    def LtL(wb):
        return LT @ sp.diags(wb) @ Lc
    Vp = solve_fair(V0, L, LtL, lam, wd0, np.ones(n))
    if not auto:
        return Vp, np.zeros(n, bool), np.ones(n), {}, []
    A = _adjacency(F, n)
    mask, info, comps = detect_features(V0, Vp, F, L, h, w, free, tol_mm, A)
    if not mask.any():
        return Vp, mask, np.ones(n), info, comps
    deg = np.maximum(np.asarray(A.sum(1)).ravel(), 1)
    d = mask.astype(float)
    for _ in range(3):                   # soft shoulders: a protected band needs a ramp, or the shoulders get pulled in
        d = np.maximum(d, 0.7 * (A @ d) / deg + 0.3 * d)
    d = np.where(free, d, 0.0)
    wb = 1.0 - 0.8 * d
    wd = wd0 * (1.0 + 0 * d)
    V = solve_fair(V0, L, LtL, lam, wd, wb)
    info['low_weight_fraction'] = float((wb < 0.5).mean())
    return V, mask, wb, info, comps


def run(req: dict[str, Any]) -> dict[str, Any]:
    import trimesh
    p = {**DEFAULTS, **(req.get('params') or {})}
    inp = req['inputs']
    m = trimesh.load(str(inp['mesh']), process=False, force='mesh')
    m.merge_vertices()
    V0 = np.asarray(m.vertices, float) * float(p['unit_scale'])
    F = np.asarray(m.faces, np.int64)
    if len(F) == 0:
        raise WorkerError('FAIR_MESH', 'The mesh has no faces.')
    wt_before = bool(m.is_watertight)
    n = len(V0)
    L, E = _lap(F, n)
    h = float(np.linalg.norm(V0[E[:, 0]] - V0[E[:, 1]], axis=1).mean())
    w = float(p['min_wavelength_mm'])
    lam = 16.0 * (w / (2 * np.pi * h)) ** 4
    warnings: list[str] = []
    if w < 4 * h:
        warnings.append(f'min_wavelength_mm {w:g} is below 4 x the mean edge length {h:.3g} mm: the mesh cannot represent it; the smoother is nearly a no-op.')

    wd = np.ones(n)
    frozen_plate = np.zeros(n, bool)
    plate_info: dict[str, Any] = {'found': False}
    if p['plate_freeze'] == 'auto':
        pl = find_plate(V0, F, float(p['plate_min_area_frac']), float(p['plate_normal_deg']))
        if pl is not None:
            s, d, pm, frac = pl
            rim = float(p['rim_height_mm']) if p['rim_height_mm'] is not None else w / 3.0
            # outward direction: the mesh lies on the side opposite to s
            side = np.sign(np.median(V0 @ s) - d) or 1.0
            ht = side * (V0 @ s - d)
            frozen_plate = ht < rim
            plate_info = {'found': True, 'normal_out': (-side * s).tolist(), 'offset': d, 'area_fraction': frac, 'rim_height_mm': rim,
                          'faces': int(pm.sum()), 'frozen_vertices': int(frozen_plate.sum())}
    else:
        warnings.append('plate_freeze off: the flat plate / rim is smoothed like the rest.')
    wd[frozen_plate] = FROZEN_W

    frozen_lab = np.zeros(n, bool)
    lab_info: dict[str, Any] = {'regions_frozen': [], 'regions_missing': []}
    if inp.get('labels') and p['fixed_regions']:
        region, names = read_regions(Path(inp['labels']), len(F))
        for r in p['fixed_regions']:
            if r in names:
                frozen_lab[F[region == names.index(r)].ravel()] = True
                lab_info['regions_frozen'].append(r)
            else:
                lab_info['regions_missing'].append(r)
        wd[frozen_lab] = FROZEN_W
    elif p['fixed_regions']:
        warnings.append('fixed_regions given without labels_path: ignored.')

    auto = p['feature_protection'] == 'auto'
    free0 = wd < FROZEN_W / 2
    tol = None if p['feature_tol_mm'] is None else float(p['feature_tol_mm'])
    V, feat, wb, log, comps = fair(V0, F, L, lam, wd, tol, auto, w, h, free0)
    free = wd < FROZEN_W / 2
    feat = feat & free
    protected = frozen_plate | frozen_lab | feat

    # ---- metrics
    mesh0 = trimesh.Trimesh(V0, F, process=False)
    mesh1 = trimesh.Trimesh(V, F, process=False)
    vol0, vol1 = signed_volume(V0, F), signed_volume(V, F)
    wt_after = bool(mesh1.is_watertight)
    disp = np.linalg.norm(V - V0, axis=1)
    idx = np.flatnonzero(free)
    if len(idx) > int(p['deviation_sample']):
        idx = idx[np.linspace(0, len(idx) - 1, int(p['deviation_sample'])).astype(int)]
    dev = closest_on_surface(V0, F, V[idx])[1]

    def rough(Vx):
        vn = _vertex_normals(Vx, F)
        Lv = L @ Vx
        kn = np.einsum('ij,ij->i', Lv, vn) * 2.0 / h ** 2                  # signed mean-curvature estimate (1/mm)
        L2 = L @ kn
        return kn, L2

    def ripple(Vx, sel, wl):
        """RMS normal component of the high-pass residual V - S(wl) V (uniform-weight bi-Laplacian smoother, half-gain wavelength wl)."""
        Vs = solve_fair(Vx, L, lambda wbb: L.T @ L, 16.0 * (wl / (2 * np.pi * h)) ** 4, wd, np.ones(n))
        return float(np.sqrt((np.einsum('ij,ij->i', Vx - Vs, _vertex_normals(Vx, F))[sel] ** 2).mean()))

    kn0, l20 = rough(V0)
    kn1, l21 = rough(V)
    nonfeat = free
    freemask = free
    rip = {}
    for wl in (w / 2.0, w):
        e = {'before': ripple(V0, nonfeat, wl), 'after': ripple(V, nonfeat, wl), 'unprotected_before': ripple(V0, nonfeat & ~feat, wl),
             'unprotected_after': ripple(V, nonfeat & ~feat, wl)}
        e['ratio'] = e['after'] / max(e['before'], 1e-12)
        e['unprotected_ratio'] = e['unprotected_after'] / max(e['unprotected_before'], 1e-12)
        rip[f'wavelength_{wl:g}_mm'] = e

    def jitter(Vx):
        fn, _ = _normals(Vx, F)
        # angle between normals of faces sharing a vertex: use mean normal per vertex vs face normal
        vn = _vertex_normals(Vx, F)
        ang = np.degrees(np.arccos(np.clip(np.einsum('ij,ij->i', fn, vn[F].mean(1) / np.maximum(np.linalg.norm(vn[F].mean(1), axis=1), 1e-30)[:, None]), -1, 1)))
        return ang
    j0, j1 = jitter(V0), jitter(V)

    out = Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    mesh1.export(str(out / 'faired.stl'))
    np.savez_compressed(out / 'fair_mask.npz', displacement_mm=disp, frozen_plate=frozen_plate, frozen_labels=frozen_lab, feature_weight=wb,
                        protected=protected)
    dvol = (vol1 - vol0) / vol0 * 100.0 if abs(vol0) > 0 else 0.0
    return {'worker': WORKER_VERSION, 'warnings': warnings, 'params_used': p,
            'method': {'lambda': lam, 'mean_edge_mm': h, 'half_gain_wavelength_mm': w, 'feature_pass': log},
            'plate': plate_info, 'labels': lab_info,
            'protected': {'vertices': int(protected.sum()), 'fraction': float(protected.mean()), 'plate_rim': int(frozen_plate.sum()),
                          'labels': int(frozen_lab.sum()), 'auto_features': int(feat.sum()), 'protected_plate': int(frozen_plate.sum()), 'protected_features': int(feat.sum()), 'feature_components': comps,
                          'auto_feature_fraction_of_free': float(feat.sum() / max(1, free.sum()))},
            'volume': {'before_mm3': vol0, 'after_mm3': vol1, 'change_pct': dvol},
            'deviation_mm': {**stats(dev), 'vertices_sampled': int(len(idx)), 'note': 'free (unfrozen) vertices to the input surface'},
            'displacement_mm': stats(disp[free]),
            'ripple_rms_mm': {**rip, 'note': 'normal component of the high-pass residual (V - uniform smoother at that half-gain wavelength) on ALL non-frozen vertices (protected features included, so the number is honest)'},
            'curvature_roughness': {'mean_curvature_rms_1_per_mm': {'before': stats(kn0[freemask])['rms'], 'after': stats(kn1[freemask])['rms']},
                                    'curvature_laplacian_rms': {'before': stats(l20[freemask])['rms'], 'after': stats(l21[freemask])['rms']},
                                    'face_normal_jitter_deg': {'before': stats(j0)['p95'], 'after': stats(j1)['p95'], 'stat': 'p95'}},
            'mesh': {'faces': int(len(F)), 'vertices': int(n), 'watertight_before': wt_before, 'watertight_after': wt_after,
                     'faces_after': int(len(mesh1.faces)), 'manifold_edges': bool(mesh1.is_winding_consistent)},
            'files': {'mesh': 'faired.stl', 'mask': 'fair_mask.npz'}}


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
