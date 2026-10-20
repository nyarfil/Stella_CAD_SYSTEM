"""Scan intake, step 2b (R2.1): region boundaries that follow the seam grooves on the mesh itself.

The v4 raster engine (scan_segment) finds WHERE the click, wheel and remainder regions are; its per-face labels come from top-view
polygons, so they stop at the top-view silhouette (the front faces of the clicks belong to no click), and they inherit the raster
watershed's guesses where a groove is faint in the top view. This step re-draws those boundaries on the mesh (numpy / scipy only):
  1. cue: per-vertex groove depth (band-pass normal offset) and, inside the wheel window prior only, the crease of the wheel-well rim;
  2. seeds: the interior of each v4 region (at least CORE_MM from any other label), the remainder (palm / base) far from every
     functional region, the wheel well (the wheel marker footprint shrunk by WELL_ERODE_MM); side-button pads stay as they are;
  3. groove-penalised growth over the face graph: a front crosses a groove only at a high price, so neighbouring fronts meet in it;
  4. every boundary between two regions is chained, the groove ridge is traced across it (profile smoothed along the curve,
     centroid of the above-half-peak run) and a smooth 3-D curve is fitted (cue-weighted; stretches without a cue are smoothed
     more strongly and listed as inferred);
  5. faces near each curve are re-assigned by the side of the curve they lie on; stray islands join their neighbours.
Face ids never change. Side-button pads (crest of the slope ring, not a groove) are not touched.
"""
from __future__ import annotations
from typing import Any
import numpy as np
import scipy.sparse as sp
import scipy.sparse.csgraph as cg
from scipy import ndimage as ndi
from scipy.spatial import cKDTree

G_SCALE = 0.03            # groove depth (mm, band-pass normal offset) counted as a full cue
CREASE_DEG = (10.0, 30.0)  # rim crease: normal-discontinuity angle mapped 0 -> 1 over this range
K_GROOVE = 30.0            # groove crossing penalty of the growth
CORE_MM = 1.0              # v4 click faces this far from another label seed their region
WH_CORE_MM = 2.0
REMAINDER_CORE_MM = 4.0    # palm / base faces this far from every functional region seed the remainder
WELL_ERODE_MM = 1.0        # the wheel well footprint (top view) is shrunk by this before it seeds the wheel
RIDGE_RANGE = 0.8          # groove ridge searched this far (mm) to each side of the grown boundary; baseline over twice that
LATERAL_SIG = 0.35         # across-groove smoothing (mm) of the ridge profile
RIDGE_MIN = 0.15           # ridge contrast that counts as a groove under the curve
STEP = 0.1                 # curve sampling (mm)
SIG_FIT = 1.2              # smoothing (mm) along a groove-supported stretch
SIG_INFER = 3.0            # smoothing (mm) along a stretch without a cue
BAND_MM = 1.6              # faces this close to a fitted curve are re-assigned by side
MIN_INFERRED_MM = 1.5      # unsupported runs shorter than this are not listed
CURVE_PAIRS = ((0, 1), (0, 2), (1, 2), (0, 5), (1, 5), (2, 5), (0, 6), (1, 6), (2, 6))   # LC RC WH PALM BASE indices of scan_regions.NAMES


# ------------------------------------------------------------------ mesh helpers
def face_edges(F: np.ndarray):
    """Pairs of faces sharing an edge, and that edge's vertex pair."""
    nF = len(F)
    E = np.sort(np.r_[F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]], axis=1)
    fid = np.r_[np.arange(nF), np.arange(nF), np.arange(nF)]
    o = np.lexsort((E[:, 1], E[:, 0]))
    E, fid = E[o], fid[o]
    same = (E[1:] == E[:-1]).all(1)
    return fid[:-1][same], fid[1:][same], E[:-1][same]


def _graph(ea, eb, w, n):
    return sp.coo_matrix((np.r_[w, w], (np.r_[ea, eb], np.r_[eb, ea])), shape=(n, n)).tocsr()


def cue_vertex(P: np.ndarray, L, hv: np.ndarray, angv: np.ndarray, crease_win: tuple[float, float, float, float]) -> np.ndarray:
    g = np.clip(-hv / G_SCALE, 0, 1)
    x0, x1, y0, y1 = crease_win
    win = (P[:, 0] > x0) & (P[:, 0] < x1) & (P[:, 1] > y0) & (P[:, 1] < y1)
    c = np.clip((angv - CREASE_DEG[0]) / (CREASE_DEG[1] - CREASE_DEG[0]), 0, 1) * win
    gv = np.maximum(g, c)
    return 0.5 * gv + 0.5 * (L @ gv)


def _grow(cen, gF, ea, eb, seeds, fixed):
    keep = (fixed[ea] < 0) & (fixed[eb] < 0)
    a, b = ea[keep], eb[keep]
    w = np.linalg.norm(cen[a] - cen[b], axis=1) * (1 + K_GROOVE * 0.5 * (gF[a] + gF[b]))
    _, _, srcs = cg.dijkstra(_graph(a, b, w, len(cen)), directed=True, indices=np.flatnonzero(seeds >= 0), return_predecessors=True, min_only=True)
    lab = np.where(srcs >= 0, seeds[np.maximum(srcs, 0)], -1)
    lab[fixed >= 0] = fixed[fixed >= 0]
    return lab


# ------------------------------------------------------------------ boundary chains and curves
def boundary_chains(lab, ea, eb, E, pair) -> list[np.ndarray]:
    """Vertex chains along the mesh edges between faces of the two labels (closed chains repeat their first vertex)."""
    a_, b_ = pair
    m = ((lab[ea] == a_) & (lab[eb] == b_)) | ((lab[ea] == b_) & (lab[eb] == a_))
    nbr: dict[int, list[int]] = {}
    for u, v in E[m]:
        nbr.setdefault(int(u), []).append(int(v))
        nbr.setdefault(int(v), []).append(int(u))
    seen: set[tuple[int, int]] = set()
    chains = []
    for s in [u for u, n in nbr.items() if len(n) != 2] + list(nbr):
        for n0 in nbr[s]:
            if (min(s, n0), max(s, n0)) in seen:
                continue
            seen.add((min(s, n0), max(s, n0)))
            ch, prev, cur = [s], s, n0
            while True:
                ch.append(cur)
                if len(nbr[cur]) != 2 or cur == s:
                    break
                nx = [x for x in nbr[cur] if x != prev][0]
                k = (min(cur, nx), max(cur, nx))
                if k in seen:
                    break
                seen.add(k)
                prev, cur = cur, nx
            chains.append(np.array(ch))
    return chains


def resample(p: np.ndarray, step: float = STEP, closed: bool = False) -> np.ndarray:
    if closed:
        p = np.vstack([p, p[:1]])
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]
    n = max(int(d[-1] / step), 2) + 1
    t = np.linspace(0, d[-1], n)
    q = np.column_stack([np.interp(t, d, p[:, k]) for k in range(p.shape[1])])
    return q[:-1] if closed else q


def waviness(p: np.ndarray, closed: bool) -> tuple[float, float, float] | None:
    """Millimetre-scale waviness of a polyline: deviation between its 0.5 mm and 2.5 mm Gaussian smoothings (the sub-face staircase
    and the overall shape both cancel). Returns (rms, max, length) in mm, or None for very short pieces."""
    q = resample(p, STEP, closed)
    if len(q) < 60:
        return None
    mode = 'wrap' if closed else 'nearest'
    a = ndi.gaussian_filter1d(q, 0.5 / STEP, axis=0, mode=mode)
    b = ndi.gaussian_filter1d(q, 2.5 / STEP, axis=0, mode=mode)
    d = np.linalg.norm(a - b, axis=1)
    if not closed:
        d = d[50:-50]
        if len(d) < 10:
            return None
    return float(np.sqrt((d ** 2).mean())), float(d.max()), float(len(q) * STEP)


def ridge_probe(q, vn, gv, tree, closed):
    """Lateral offset (mm) from each curve point to the groove centre and the groove contrast there."""
    t = np.gradient(q, axis=0)
    t /= np.linalg.norm(t, axis=1)[:, None] + 1e-12
    _, vi = tree.query(q)
    d = np.cross(t, vn[vi])
    d /= np.linalg.norm(d, axis=1)[:, None] + 1e-12
    offs = np.arange(-2 * RIDGE_RANGE, 2 * RIDGE_RANGE + 1e-9, 0.05)
    S = q[:, None, :] + offs[None, :, None] * d[:, None, :]
    dd, vi2 = tree.query(S.reshape(-1, 3), k=3)
    w = 1 / (dd + 0.05)
    val = ((gv[vi2] * w).sum(1) / w.sum(1)).reshape(len(q), len(offs))
    val = ndi.gaussian_filter1d(val, 0.6 / STEP, axis=0, mode='wrap' if closed else 'nearest')   # a groove is continuous along the curve, noise is not
    raw = val - np.median(val, axis=1, keepdims=True)                                             # contrast is read before the lateral smoothing
    val = ndi.gaussian_filter1d(val, LATERAL_SIG / 0.05, axis=1, mode='nearest')                 # the two walls of a wide groove merge into one centre peak
    val = val - np.median(val, axis=1, keepdims=True)
    val = np.where(np.abs(offs)[None, :] <= RIDGE_RANGE, val, -1.0)
    j = (val - 0.15 * np.abs(offs)[None, :] / RIDGE_RANGE).argmax(1)
    top = val[np.arange(len(q)), j]
    idx = np.arange(len(offs))[None, :]
    above = (val >= 0.5 * top[:, None]) & (val > -1.0)
    lo = np.where(~above & (idx < j[:, None]), idx, -1).max(1) + 1
    hi = np.where(~above & (idx > j[:, None]), idx, len(offs)).min(1)
    wv = np.where((idx >= lo[:, None]) & (idx < hi[:, None]), val, 0)
    inw = (idx >= lo[:, None]) & (idx < hi[:, None]) & (np.abs(offs)[None, :] <= RIDGE_RANGE)
    contrast = np.where(inw, raw, -1.0).max(1)       # groove depth (cue units) at the located centre, unblurred across the groove
    return (wv * offs[None, :]).sum(1) / np.maximum(wv.sum(1), 1e-9), np.maximum(top, contrast), d


def fit_curve(q, off, cue, d, closed):
    """Cue-weighted smooth of the ridge points; where the cue is missing the curve blends to a stronger smoothing of the boundary."""
    ok = cue >= RIDGE_MIN
    w = np.where(ok, cue, 0.02)
    tgt = q + (off * ok)[:, None] * d
    mode = 'wrap' if closed else 'nearest'
    fine = ndi.gaussian_filter1d(tgt * w[:, None], SIG_FIT / STEP, axis=0, mode=mode) / ndi.gaussian_filter1d(w, SIG_FIT / STEP, mode=mode)[:, None]
    den = ndi.gaussian_filter1d(w, SIG_FIT / STEP, mode=mode)
    coarse = ndi.gaussian_filter1d(q, SIG_INFER / STEP, axis=0, mode=mode)
    if not closed:                           # end points are junctions: keep them
        k = int(2 * SIG_INFER / STEP)
        ramp = np.clip(np.minimum(np.arange(len(q)), np.arange(len(q))[::-1]) / max(k, 1), 0, 1)[:, None]
        coarse = q + (coarse - q) * ramp
    a = np.clip(den / 0.3, 0, 1)[:, None]
    return a * fine + (1 - a) * coarse


def _relabel(cen, fn, vn, tree, lab, curves):
    lab = lab.copy()
    for cv in curves:
        a, b = cv['pair']
        pts = cv['pts']
        t = np.gradient(pts, axis=0)
        t /= np.linalg.norm(t, axis=1)[:, None] + 1e-12
        sel = np.flatnonzero((lab == a) | (lab == b))
        dist, j = cKDTree(pts).query(cen[sel], distance_upper_bound=BAND_MM)
        ok = np.isfinite(dist)
        if not cv['closed']:
            ok &= (j > 0) & (j < len(pts) - 1)          # beyond the ends the side test means nothing
        sel, j = sel[ok], j[ok]
        if len(sel) == 0:
            continue
        nj = vn[tree.query(pts)[1]][j]
        dv = cen[sel] - pts[j]
        s_ = np.einsum('ij,ij->i', dv, np.cross(t[j], nj))
        h_ = np.abs(np.einsum('ij,ij->i', dv, nj))
        good = (np.einsum('ij,ij->i', fn[sel], nj) > 0.2) & (h_ < 1.0)     # faces round a sharp edge from the curve (front roll-over) keep their grown label
        sel, s_ = sel[good], s_[good]
        if len(sel) == 0:
            continue
        side = s_ > 0
        va = (side & (lab[sel] == a)).sum() + (~side & (lab[sel] == b)).sum()
        vb = (side & (lab[sel] == b)).sum() + (~side & (lab[sel] == a)).sum()
        lab[sel] = np.where(side if va >= vb else ~side, a, b)
    return lab


def _islands(lab, ea, eb, fixed, nF, prior=None):
    """Keep the largest connected piece of each label; smaller pieces (below 5000 faces) first fall back to `prior` (the grown labels),
    then join the surrounding label."""
    moved = 0
    for it in range(4):
        same = lab[ea] == lab[eb]
        n, comp = cg.connected_components(sp.coo_matrix((np.ones(int(same.sum())), (ea[same], eb[same])), shape=(nF, nF)), directed=False)
        cnt = np.bincount(comp)
        keep = np.zeros(n, bool)
        for k in np.unique(lab):
            cs = np.unique(comp[lab == k])
            keep[cs[np.argmax(cnt[cs])]] = True
        bad = ~keep[comp] & (cnt[comp] < 5000) & (fixed < 0)
        if not bad.any():
            break
        if it == 0 and prior is not None:
            lab = np.where(bad, prior, lab)
            continue
        moved += int(bad.sum())
        l2 = np.where(bad, -1, lab)
        for _ in range(500):
            for x, y in ((ea, eb), (eb, ea)):
                m = (l2[x] < 0) & (l2[y] >= 0)
                l2[x[m]] = l2[y[m]]
            if (l2 >= 0).all():
                break
        lab = np.where(l2 >= 0, l2, lab)
    return lab, moved


def _chain_stats(P, lab, ea, eb, E, pairs):
    out = {}
    for pr in pairs:
        ws = []
        for c in boundary_chains(lab, ea, eb, E, pr):
            closed = len(c) > 8 and c[0] == c[-1]
            w = waviness(P[c[:-1]] if closed else P[c], closed)
            if w:
                ws.append(w)
        if ws:
            W = np.array(ws)
            out[pr] = {'rms_mm': float((W[:, 0] * W[:, 2]).sum() / W[:, 2].sum()), 'max_mm': float(W[:, 1].max()), 'length_mm': float(W[:, 2].sum()), 'pieces': len(ws)}
    return out


# ------------------------------------------------------------------ driver
def refine_regions(P, F, cen, fn, vn, L, ft: dict[str, Any], lab0: np.ndarray, well: np.ndarray, crease_win, fixed_ids=(3, 4)) -> dict[str, Any]:
    """lab0: v4 labels (scan_regions.NAMES indices, 0..6). well: faces of the wheel well (seed the wheel). Returns the new labels, the
    fitted curves and per-pair statistics (before / after waviness, cue support)."""
    nF = len(F)
    ea, eb, E = face_edges(F)
    gv = cue_vertex(P, L, ft['hv'], ft['angv'], crease_win)
    gF = gv[F].mean(1)
    fixed = np.where(np.isin(lab0, fixed_ids), lab0, -1)
    G = _graph(ea, eb, np.linalg.norm(cen[ea] - cen[eb], axis=1), nF)
    border = np.zeros(nF, bool)
    diff = lab0[ea] != lab0[eb]
    border[ea[diff]] = border[eb[diff]] = True
    dB = cg.dijkstra(G, directed=True, indices=np.flatnonzero(border), min_only=True, limit=8.0)
    dF = cg.dijkstra(G, directed=True, indices=np.flatnonzero(lab0 <= 4), min_only=True, limit=8.0)
    seeds = np.full(nF, -1)
    for k, core in ((0, CORE_MM), (1, CORE_MM), (2, WH_CORE_MM)):
        seeds[(lab0 == k) & (dB >= core)] = k
    for k in (5, 6):
        seeds[(lab0 == k) & (dF >= REMAINDER_CORE_MM)] = k
    seeds[well & ~np.isin(lab0, fixed_ids)] = 2
    seeds[fixed >= 0] = -1
    lab = _grow(cen, gF, ea, eb, seeds, fixed)
    lab[lab < 0] = lab0[lab < 0]
    grown = lab.copy()
    tree = cKDTree(P)
    curves = []
    for pr in CURVE_PAIRS:
        for c in boundary_chains(lab, ea, eb, E, pr):
            if len(c) < 5:
                continue
            closed = bool(len(c) > 8 and c[0] == c[-1])
            q = resample(P[c[:-1]] if closed else P[c], STEP, closed)
            if len(q) < 5:
                continue
            off, cue, d = ridge_probe(q, vn, gv, tree, closed)
            curves.append({'pair': pr, 'pts': fit_curve(q, off, cue, d, closed), 'closed': closed, 'cue': cue, 'offset': off})
    lab = _relabel(cen, fn, vn, tree, lab, curves)
    lab, moved = _islands(lab, ea, eb, fixed, nF, grown)
    return {'lab': lab, 'grown': grown, 'curves': curves, 'island_faces_moved': moved,
            'waviness_before': _chain_stats(P, lab0, ea, eb, E, CURVE_PAIRS), 'waviness_after': _chain_stats(P, lab, ea, eb, E, CURVE_PAIRS)}


def inferred_runs(cv: dict[str, Any]) -> list[dict[str, Any]]:
    """Stretches of a fitted curve without a groove under them (>= MIN_INFERRED_MM)."""
    ok = cv['cue'] >= RIDGE_MIN
    out = []
    n = len(ok)
    i = 0
    while i < n:
        if ok[i]:
            i += 1
            continue
        j = i
        while j < n and not ok[j]:
            j += 1
        if (j - i) * STEP >= MIN_INFERRED_MM:
            mid = cv['pts'][(i + j) // 2]
            out.append({'length_mm': round((j - i) * STEP, 1), 'mid_work_mm': np.round(mid, 1).tolist()})
        i = j
    return out
