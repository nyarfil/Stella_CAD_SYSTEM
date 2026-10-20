"""Click front wall: the groove-bounded band below the front edge of the left / right click (R2.3).

The top-view engine (scan_segment) labels a face only when it is visible from above. The front lip of a click button (the rim that
rolls over the front edge and the wall below it, down to the parting slit towards the front frame) hangs below the crest and is
hidden from the top, so it stays in the remainder although it is click-button thickness. Each click's front wall is the region
ENCLOSED BY GROOVE LINES, from the surface alone (no texture, no label file, no mouse-specific coordinates):

  upper boundary  the crest groove along the click front edge = the click's own front arc (seeds: remainder faces touching a click face
                  within FRONT_SECTOR_DEG of the front axis); its height zc(y) and depth xc(y) are measured per 0.5 mm column.
  lower boundary  the front parting slit = the lowest near-horizontal facet group (|n_z| > LEDGE_NZ) under the crest; where a column has
                  no ledge facets the per-face groove cue (gF, scan_grooves.cue_vertex: band-pass |h| + crease angle) peak is used.
                  The curve zs(y) is interpolated, median-filtered and Gaussian-smoothed along y (regularised) and is never crossed.
  side ends       the columns with groove evidence (a measured slit or a groove-cue peak) plus at most END_MM; the lateral grooves
                  where the click meets the shell lie beyond them.
  inner           the LC | RC centre slit: a face belongs to the click whose front seed is nearest in the top view.

The loop (ylo, yhi, zc(y), zs(y), xc(y)) is returned in the report; a face is added only when its centroid lies INSIDE it and it is
connected to the seeds through other loop faces. There is no growth outside the loop and no ragged-edge fill.
Heights and directions are in the work frame (x front, y mouse-left, z up). Only family-level lengths are used.
"""
from __future__ import annotations
from typing import Any
import numpy as np
import scipy.sparse as sp
import scipy.sparse.csgraph as cg
from scipy import ndimage as ndi
from scipy.spatial import cKDTree

FRONT_SECTOR_DEG = 40.0     # a click face is on the front arc when its outward direction is within this angle of the front axis
REACH_MM = 10.0             # the lip and the slit are searched this far (over the surface) from the click
ZMAX_MM = 3.0               # the parting slit lies at most this far below the crest
LEDGE_NZ = 0.6              # slit facets: |n_z| above this (near-horizontal)
MIN_LEDGE_FACES = 3         # slit facets needed in a column to measure it
GROOVE_PEAK = 0.5           # groove cue (0..1) above which a face counts as lying in a groove
MARGIN_MM = 0.1             # the lower lip of the slit still belongs to the strip
CREST_EPS_MM = 0.15         # loop top = crest height + this
BACK_MM = 1.5               # loop faces lie at most this far behind the crest of their column
BIN_MM = 0.5                # column width along y
SMOOTH_MM = 3.0             # median window of the slit profile
GAUSS_MM = 1.0              # Gaussian regularisation of the slit curve (sigma)
END_MM = 0.5                # the loop ends this far beyond the last column with groove evidence
CREST_PCT = 10.0            # crest = this percentile of the seed heights in a column (the front edge, not a wheel notch)


def _face_pairs(F: np.ndarray):
    nF = len(F)
    E = np.sort(np.r_[F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]], axis=1)
    fid = np.r_[np.arange(nF), np.arange(nF), np.arange(nF)]
    o = np.lexsort((E[:, 1], E[:, 0]))
    E, fid = E[o], fid[o]
    same = (E[1:] == E[:-1]).all(1)
    return fid[:-1][same], fid[1:][same]


def _interp_nan(v: np.ndarray) -> np.ndarray:
    ok = np.isfinite(v)
    if not ok.any():
        return v
    i = np.arange(len(v))
    return np.interp(i, i[ok], v[ok])


def in_loop(cen: np.ndarray, loop: dict[str, Any]) -> np.ndarray:
    """True for points whose centroid lies inside the groove loop (ylo <= y <= yhi, slit curve <= z <= crest curve, not behind the crest)."""
    y0, bs = loop['y0'], loop['bin_mm']
    nb = len(loop['zc'])
    b = np.clip(np.floor((cen[:, 1] - y0) / bs).astype(int), 0, nb - 1)
    return ((cen[:, 1] >= loop['ylo']) & (cen[:, 1] <= loop['yhi']) & (cen[:, 2] <= loop['zc'][b] + CREST_EPS_MM + 1e-9)
            & (cen[:, 2] >= loop['zs'][b] - 1e-9) & (cen[:, 0] >= loop['xc'][b] - BACK_MM - 1e-9))


def _one_click(cen, fn, gF, ea, eb, nF, lab, k, cand) -> dict[str, Any] | None:
    isk = lab == k
    if not isk.any():
        return None
    ck = cen[isk].mean(0)
    adj = np.unique(np.r_[eb[isk[ea] & cand[eb]], ea[isk[eb] & cand[ea]]])
    if not len(adj):
        return None
    u = cen[adj, :2] - ck[:2]
    ang = np.degrees(np.arctan2(np.abs(u[:, 1]), u[:, 0]))
    seeds = adj[(u[:, 0] > 0) & (ang <= FRONT_SECTOR_DEG)]
    if len(seeds) < 5:
        return None
    ec = cand[ea] & cand[eb]
    w = np.linalg.norm(cen[ea[ec]] - cen[eb[ec]], axis=1)
    G = sp.coo_matrix((np.r_[w, w], (np.r_[ea[ec], eb[ec]], np.r_[eb[ec], ea[ec]])), shape=(nF, nF)).tocsr()
    d = cg.dijkstra(G, directed=False, indices=seeds, min_only=True, limit=REACH_MM)
    near = np.isfinite(d) & cand
    # ---- columns along y; upper groove = crest of the click front arc
    y0 = float(cen[seeds, 1].min()) - BIN_MM
    nb = int(np.ceil((cen[seeds, 1].max() + BIN_MM - y0) / BIN_MM)) + 1
    bs = np.clip(((cen[seeds, 1] - y0) / BIN_MM).astype(int), 0, nb - 1)
    zc = np.full(nb, np.nan)
    xc = np.full(nb, np.nan)
    for b in range(nb):
        m = bs == b
        if m.any():
            zc[b] = np.percentile(cen[seeds[m], 2], CREST_PCT)
            xc[b] = np.percentile(cen[seeds[m], 0], 90)
    zc, xc = _interp_nan(zc), _interp_nan(xc)
    nf = np.flatnonzero(near)
    bf = np.clip(((cen[nf, 1] - y0) / BIN_MM).astype(int), 0, nb - 1)
    inside = (cen[nf, 1] >= y0) & (cen[nf, 1] <= y0 + nb * BIN_MM)
    under = inside & (cen[nf, 2] < zc[bf] - 0.3) & (cen[nf, 2] > zc[bf] - ZMAX_MM) & (cen[nf, 0] > xc[bf] - BACK_MM - 2.0)
    led = under & (np.abs(fn[nf, 2]) > LEDGE_NZ)
    # ---- lower groove = parting slit: ledge facets, else the groove-cue peak
    zs = np.full(nb, np.nan)
    evid = np.zeros(nb, bool)
    for b in range(nb):
        m = led & (bf == b)
        if m.sum() >= MIN_LEDGE_FACES:
            zs[b] = np.percentile(cen[nf[m], 2], 10)
            evid[b] = True
    if gF is not None:
        gm = under & (gF[nf] > GROOVE_PEAK)
        for b in range(nb):
            if not evid[b]:
                m = gm & (bf == b)
                if m.sum() >= MIN_LEDGE_FACES:
                    zs[b] = np.percentile(cen[nf[m], 2], 10)
                    evid[b] = True
    measured = float(evid.mean())
    out = {'k': k, 'faces': np.zeros(0, np.int64), 'seeds': seeds, 'measured_fraction': measured, 'thickness_mm': None, 'loop': None}
    if not evid.any():
        return out
    # regularise: interpolate over unmeasured columns, median then Gaussian along y; the curve stays a single smooth line
    zs = _interp_nan(zs)
    win = max(int(round(SMOOTH_MM / BIN_MM)) | 1, 3)
    zs = ndi.median_filter(zs, size=win, mode='nearest')
    zs = ndi.gaussian_filter1d(zs, GAUSS_MM / BIN_MM, mode='nearest')
    zs = np.minimum(zs, zc - 0.3) - MARGIN_MM
    ev = np.flatnonzero(evid)
    ylo = y0 + ev.min() * BIN_MM - END_MM
    yhi = y0 + (ev.max() + 1) * BIN_MM + END_MM
    loop = {'y0': y0, 'bin_mm': BIN_MM, 'ylo': float(ylo), 'yhi': float(yhi), 'zc': zc, 'zs': zs, 'xc': xc}
    t = zc - zs - MARGIN_MM
    out.update(loop=loop, thickness_mm=float(np.median(t)), thickness_range_mm=[float(t.min()), float(t.max())])
    # ---- faces inside the loop that connect to the seeds through other loop faces
    allowed = np.zeros(nF, bool)
    allowed[nf[in_loop(cen[nf], loop)]] = True
    s_ok = seeds[allowed[seeds]]
    if not len(s_ok):
        return out
    e2 = allowed[ea] & allowed[eb]
    A = sp.coo_matrix((np.ones(e2.sum()), (ea[e2], eb[e2])), shape=(nF, nF))
    _, comp = cg.connected_components(A + A.T, directed=False)
    out['faces'] = np.flatnonzero(np.isin(comp, np.unique(comp[s_ok])) & allowed)
    return out


def extend_click_front(F: np.ndarray, cen: np.ndarray, fn: np.ndarray, lab: np.ndarray, clicks: tuple[int, int] = (0, 1),
                       remainder: tuple[int, ...] = (5,), gF: np.ndarray | None = None) -> tuple[np.ndarray, dict[str, Any]]:
    """Return (labels with the click front walls added, report). lab holds region indices; faces with lab < 0 or in `remainder` may be taken.
    gF: optional per-face groove cue 0..1 (scan_grooves.cue_vertex averaged over the face)."""
    nF = len(F)
    ea, eb = _face_pairs(F)
    cand = np.isin(lab, remainder) | (lab < 0)
    res = [r for r in (_one_click(cen, fn, gF, ea, eb, nF, lab, k, cand) for k in clicks) if r is not None]
    info: dict[str, Any] = {'applied': False, 'clicks': {}, 'loops': {}}
    if not res:
        info['reason'] = 'no front arc found on the click regions'
        return lab, info
    new = lab.copy()
    allf = np.unique(np.concatenate([r['faces'] for r in res]))
    if len(allf):
        allseed = np.concatenate([r['seeds'] for r in res])
        owner = np.concatenate([np.full(len(r['seeds']), r['k']) for r in res])
        _, nn = cKDTree(cen[allseed, :2]).query(cen[allf, :2])
        own = owner[nn]
        for r in res:
            k = r['k']
            fs = allf[own == k]
            fs = fs[in_loop(cen[fs], r['loop'])]
            sel = np.zeros(nF, bool)
            sel[fs] = True
            sel |= lab == k
            e2 = sel[ea] & sel[eb]
            A = sp.coo_matrix((np.ones(e2.sum()), (ea[e2], eb[e2])), shape=(nF, nF))
            _, comp = cg.connected_components(A + A.T, directed=False)
            main = np.bincount(comp[lab == k]).argmax()
            new[fs[comp[fs] == main]] = k
    for r in res:
        k = r['k']
        info['clicks'][int(k)] = {'seed_faces': int(len(r['seeds'])), 'faces_added': int((new == k).sum() - (lab == k).sum()),
                                  'thickness_median_mm': None if r['thickness_mm'] is None else round(r['thickness_mm'], 2),
                                  'thickness_range_mm': [round(v, 2) for v in r.get('thickness_range_mm', [])] or None,
                                  'columns_with_groove_evidence': round(r['measured_fraction'], 2)}
        if r['loop'] is not None:
            info['loops'][int(k)] = r['loop']
    info['faces_moved'] = int((new != lab).sum())
    info['applied'] = info['faces_moved'] > 0
    return new, info
