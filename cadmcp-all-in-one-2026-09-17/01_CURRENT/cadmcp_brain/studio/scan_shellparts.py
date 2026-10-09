"""Scan intake, step 3: bottom plate, top shell, parting seam and sensor window (brain_mouse_recognize_shell).

Runs on a READY prepared scan after the region step (the click / wheel / side-button faces are excluded from the top shell). Surface geometry only
(the prepared scan carries no texture): numpy / scipy / Pillow.
  * parting seam: for every 1 degree azimuth bin round the footprint the outer-wall faces are scanned bottom-up for the groove of the seam
    (band-pass normal offset); a circular Viterbi path over the bins picks one smooth seam height per bin. Bins whose groove is clear are
    SUPPORTED, the rest are interpolated and listed as INFERRED (the seam is often a plain colour step without a groove, notably at the rear);
  * bottom plate = faces below the seam of their azimuth plus the interior underside; top shell = the rest minus the functional regions;
  * sensor window: the deep pocket in the underside raster (depth above the fitted plate plane), centre / size / depth in the mouse frame.
Results are stored with hashes under mouse/scans/<scan_id>/shell/<run_id>/ and never overwritten.
"""
from __future__ import annotations
import time
from pathlib import Path
from typing import Any
import numpy as np
import scipy.sparse as sp
from scipy import ndimage as ndi
from scipy.sparse.csgraph import connected_components
from . import scan_regions as sr
from . import scan_segment as sg
from . import scan_shell
from .. import __version__
from ..errors import BrainError
from ..req2cad.common import atomic_json, json_load
from ..util import digest, file_hash, safe_id

SHELL_VERSION = 'S1.2'
LABEL_CODES = {'other': 0, 'bottom_plate': 1, 'top_shell': 2}
# parting seam (S1.2): exact vertical sections round the footprint, crease + groove cues, circular Viterbi; lengths in mm (prepared scans are mm)
SEAM_COLS = 720                              # sections round the loop (0.5 degree)
PROFILE_STEP = 0.1                           # arc-length resampling of each section, mm
LEAVE_PHI, LEAVE_RUN, LEAVE_ZWIN = 20.0, 20, 8.0   # lower edge of the wall: profile rising > 20 deg for 2 mm, within 8 mm of the section's lowest point
LEAVE_JUMP_MM = 1.5                          # a section whose lower edge is this far off its neighbours crosses a scan hole: not used
ROI_SAMPLES = 130                            # seam searched up to 13 mm of arc above the lower edge
KINK_SIGMA, KINK_SHIFT = 2.0, 3              # crease channel: curvature smoothed 0.2 mm, read 0.3 mm higher (gap below the shell's rounded edge)
GROOVE_W = 0.7                               # weight of the groove channel against the crease channel
GATE_BELOW_DEG, GATE_ABOVE_DEG, GATE_PEN = 30.0, 40.0, 6.0   # a seam has a wall below (> 30 deg) and above (> 40 deg); the plate fillet does not
DP_LAM = 10.0                                # smoothness: cost per mm of height change between neighbouring sections
PRIOR_HARM, PRIOR_W, PRIOR_TOL = 3, 2.0, 1.0  # robust 3-harmonic prior on the arc offset above the lower edge; penalty 2 / mm beyond 1 mm
SUPPORT_SCORE, SUPPORT_CONTRAST, CONTRAST_SEP_MM, CONTRAST_WIN_MM = 4.0, 1.0, 1.0, 2.0   # supported: cue score > 4 and > 1 above any other point of
#   the section >= 1 mm away within the prior band (+-3 mm)
MIN_RUN = 4                                  # supported runs shorter than 2 degrees are reported as inferred
EVID_KINK, EVID_GROOVE = 3.0, 2.0            # evidence label per section
BAND_ALONG_MM, BAND_ACROSS_MM, TOP_SEED_MM = 3.0, 1.5, 4.0   # seam band for the face split; faces 4 mm above the seam seed the top shell
# sensor window: geometry only, no pose prior and no fixed coordinates; every length threshold is relative to the footprint length L
FLAT_TOL_DEG = 8.0                           # normals of the base face family lie within this cone
RASTER_PER_LENGTH = 1500.0                   # underside raster pixel = L / 1500 (0.08 mm for a 120 mm mouse); rim points are sub-pixel
REC_DEPTH_REL = 0.004                        # a recess candidate is deeper than max(6 sigma of the plate plane, 0.004 L)
EDGE_MARGIN_REL = 0.03                       # candidates lie at least this far (x L) inside the footprint outline
AREA_REL = (0.0002, 0.02)                    # candidate area range, x L^2
BG_SIGMA_REL = 0.04                          # Gaussian sigma (x L) of the slow plate shape removed before recess detection
RIM_SEARCH = tuple(round(0.10 + 0.05 * k, 2) for k in range(11))   # mesh rim: shallowest clean iso-level, as fractions of the floor depth
RIM_BAND = (0.9, 0.95, 1.0, 1.05, 1.1)       # each rim level is sampled as a thin band of iso-levels (denser points on a coarse mesh)
LINE_CURVATURE_REL = 0.2                     # outline parts with |curvature| below 0.2 / (half width) start as straight-edge candidates
LINE_RADIUS_REL = 8.0                        # a fitted arc wider than 8 x half width is treated as a straight edge
MODEL_TOL_REL = 0.025                        # family choice: RMS below max(3 sigma noise, 0.035 x half width) counts as a fit, then fewer parameters win
PIECE_TOL_REL = 0.020                        # a line / arc piece is accepted when its RMS is below max(2.5 sigma noise, 0.006 x half width)
MAX_GAP_DEG = 12.0                           # a rim loop is closed when no angular gap round the centre exceeds this
FOURIER_K = (4, 6, 8, 10, 12, 14, 16)        # harmonics tried for the smooth r(theta) outline (chosen by BIC)
OUTLINE_POINTS = 360                         # dense outline polyline length
RIM_LEVELS = (0.2, 0.35, 0.5)                # rim traced where the depth crosses these fractions of the floor depth; their spread is an uncertainty term
LIMITS = ['Surface-only: the sensor PCB, chip and lens behind the window are not visible; the window outline is the aperture rim seen from below. '
          'The sensor step uses mesh geometry only (no pose prior, PCB or texture); its thresholds are relative to the footprint length.',
          'The prepared scan has no texture, so the parting seam is found from its groove only. Bins without a clear groove (typically the rear) are interpolated '
          'and listed as inferred; the bottom plate / top shell split is only as good as the seam.',
          f'Calibrated on: {sr.CALIBRATED_ON}.']


def _circ_smooth(a: np.ndarray, med: int, sig: float) -> np.ndarray:
    k = 20
    ap = np.r_[a[-k:], a, a[:k]]
    return ndi.gaussian_filter1d(ndi.median_filter(ap, size=med, mode='nearest'), sig, mode='nearest')[k:-k]


def _edge_table(F: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    E2 = np.sort(np.r_[F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]], 1)
    E, inv = np.unique(E2, axis=0, return_inverse=True)
    return E, inv.reshape(3, -1).T


def section_profile(P: np.ndarray, F: np.ndarray, E: np.ndarray, FE: np.ndarray, cenF: np.ndarray, hv: np.ndarray, c0: np.ndarray, az: float) -> dict[str, Any] | None:
    """Exact section of the mesh with the vertical half-plane at azimuth `az` round c0, chained into one ordered polyline that starts at the
    underside end and runs out over the wall to the top; resampled every PROFILE_STEP of arc length (r = distance from c0, z, groove map hv)."""
    a = np.radians(az)
    n, u = np.array([-np.sin(a), np.cos(a)]), np.array([np.cos(a), np.sin(a)])
    s = (P[:, :2] - c0) @ n
    sf = s[F]
    fids = np.flatnonzero((sf.min(1) < 0) & (sf.max(1) > 0) & ((cenF[:, :2] - c0) @ u > 0))
    if len(fids) < 10:
        return None
    sa, sb = s[E[:, 0]], s[E[:, 1]]
    cross = sa * sb < 0
    fe = FE[fids]
    cm = cross[fe]
    two = cm.sum(1) == 2
    fe, cm = fe[two], cm[two]
    e1 = np.where(cm[:, 0], fe[:, 0], fe[:, 1])
    e2 = np.where(cm[:, 2], fe[:, 2], fe[:, 1])
    nodes, ni = np.unique(np.r_[e1, e2], return_inverse=True)
    ni = ni.reshape(2, -1).T
    nn = len(nodes)
    G = sp.coo_matrix((np.ones(len(ni)), (ni[:, 0], ni[:, 1])), shape=(nn, nn)).tocsr()
    G = ((G + G.T) > 0).astype(np.int8).tocsr()
    _, lab = connected_components(G, directed=False)
    big = int(np.argmax(np.bincount(lab)))
    deg = np.asarray(G.sum(1)).ravel()
    t = sa[nodes] / (sa[nodes] - sb[nodes])
    X = P[E[nodes, 0]] + t[:, None] * (P[E[nodes, 1]] - P[E[nodes, 0]])
    r, z = (X[:, :2] - c0) @ u, X[:, 2]
    ends = np.flatnonzero((deg == 1) & (lab == big))
    start = int(ends[np.argmin(z[ends] + 0.2 * r[ends])]) if len(ends) else int(np.flatnonzero(lab == big)[0])
    ind, ptr = G.indices, G.indptr
    order, prev, cur = [start], -1, start
    while len(order) <= nn:
        nb = [k for k in ind[ptr[cur]:ptr[cur + 1]] if k != prev]
        if not nb or nb[0] == start:
            break
        prev, cur = cur, int(nb[0])
        order.append(cur)
    if len(order) < 20:
        return None
    o = np.array(order)
    R, Z, XY = r[o], z[o], X[o, :2]
    hvn = (hv[E[nodes, 0]] * (1 - t) + hv[E[nodes, 1]] * t)[o]
    sarc = np.r_[0, np.cumsum(np.hypot(np.diff(R), np.diff(Z)))]
    S = np.arange(0, sarc[-1], PROFILE_STEP)
    return {'s': S, 'r': np.interp(S, sarc, R), 'z': np.interp(S, sarc, Z), 'hv': np.interp(S, sarc, hvn),
            'x': np.interp(S, sarc, XY[:, 0]), 'y': np.interp(S, sarc, XY[:, 1])}


def profile_cues(p: dict[str, Any]) -> dict[str, np.ndarray]:
    """Cue channels along a section profile: tangent angle phi (deg from horizontal, 90 = vertical wall), crease = curvature (deg/mm, > 0
    where the profile turns upwards), mean phi just below / above each sample, and the groove depth (negative band-pass normal offset)."""
    rs, zs = ndi.gaussian_filter1d(p['r'], 1.5), ndi.gaussian_filter1d(p['z'], 1.5)
    phi = np.degrees(np.unwrap(np.arctan2(np.gradient(zs), np.gradient(rs))))
    cv = np.gradient(ndi.gaussian_filter1d(phi, 2.0)) / PROFILE_STEP
    n = len(phi)
    c = np.r_[0, np.cumsum(phi)]
    i = np.arange(n)

    def mean_win(a0: int, a1: int) -> np.ndarray:
        lo, hi = np.clip(i + a0, 0, n), np.clip(i + a1, 0, n)
        return (c[hi] - c[lo]) / np.maximum(hi - lo, 1)
    k = ndi.gaussian_filter1d(cv, KINK_SIGMA)
    k = np.r_[k[KINK_SHIFT:], np.full(KINK_SHIFT, k[-1])]       # crease read KINK_SHIFT samples higher: the seam gap sits just below the shell's rounded lower edge
    return {'phi': phi, 'kink': k, 'phib': mean_win(-20, -5), 'phia': mean_win(3, 15), 'groove': -ndi.gaussian_filter1d(p['hv'], 2.0)}


def _leave_index(p: dict[str, Any], c: dict[str, np.ndarray]) -> int:
    """Lower edge of the outer wall: first sample (outer part of the profile, near the underside level) after which the profile keeps rising
    (phi > LEAVE_PHI) for LEAVE_RUN samples."""
    n = len(p['s'])
    if n <= LEAVE_RUN + 1:
        return -1
    up = (c['phi'] > LEAVE_PHI).astype(int)
    cs = np.r_[0, np.cumsum(up)]
    full = (cs[LEAVE_RUN:] - cs[:-LEAVE_RUN]) == LEAVE_RUN
    m = n - LEAVE_RUN
    cand = np.flatnonzero(full[:m] & (p['z'][:m] < p['z'].min() + LEAVE_ZWIN) & (p['r'][:m] > np.percentile(p['r'], 60)))
    return int(cand[0]) if len(cand) else -1


def _viterbi_z(cost: np.ndarray, Z: np.ndarray, lam: float) -> np.ndarray:
    """Circular Viterbi: one state per column, transition cost lam * |dz| between consecutive columns (z of each state given per column)."""
    n, k = cost.shape
    c3, z3 = np.vstack([cost, cost, cost]), np.vstack([Z, Z, Z])
    d = c3[0].copy()
    bp = np.zeros((3 * n, k), np.int32)
    ar = np.arange(k)
    for i in range(1, 3 * n):
        dz = np.abs(z3[i][:, None] - z3[i - 1][None, :])
        tot = d[None, :] + lam * np.where(np.isnan(dz), 1e3, dz)
        bp[i] = np.argmin(tot, 1)
        d = c3[i] + tot[ar, bp[i]]
    j = int(np.argmin(d))
    path = [j]
    for i in range(3 * n - 1, 0, -1):
        j = int(bp[i][j])
        path.append(j)
    return np.array(path[::-1][n:2 * n])


def _runs(mask: np.ndarray) -> list[np.ndarray]:
    """Circular runs of equal value: list of index arrays (in order, possibly wrapping)."""
    n = len(mask)
    if (mask == mask[0]).all():
        return [np.arange(n)]
    start = int(np.flatnonzero(mask != np.roll(mask, 1))[0])
    order = np.r_[start:n, 0:start]
    runs, cur = [], [order[0]]
    for b in order[1:]:
        if mask[b] == mask[cur[0]]:
            cur.append(b)
        else:
            runs.append(np.array(cur))
            cur = [b]
    runs.append(np.array(cur))
    return runs


def _circ_interp(i: np.ndarray, good: np.ndarray, val: np.ndarray, n: int) -> np.ndarray:
    g = np.flatnonzero(good)
    return np.interp(i, np.r_[g - n, g, g + n], np.r_[val[g], val[g], val[g]])


def seam_loop(M: Any, ft: dict[str, Any]) -> dict[str, Any]:
    """Parting seam from geometry alone. Exact vertical sections every 360 / SEAM_COLS degrees round the footprint centre; per section the
    outer wall from its lower edge up to ROI_SAMPLES * PROFILE_STEP of arc length. Cue = convex crease (curvature, log-compressed) + groove
    (negative normal offset), gated so the plate-to-wall fillet (flat below it) cannot win. A circular Viterbi path with a |dz| smoothness
    prior picks one seam point per section; a robust low-harmonic prior on the seam's arc offset above the lower edge (fitted to the clearly
    supported sections) steers a second pass. Sections whose cue is weak are INFERRED: their offset follows the prior's shape, shifted to meet
    the neighbouring supported ends."""
    P, F = M.P, M.F
    c0 = np.array([(P[:, 0].min() + P[:, 0].max()) / 2, (P[:, 1].min() + P[:, 1].max()) / 2])
    E, FE = _edge_table(F)
    n = SEAM_COLS
    AZ = -180 + (np.arange(n) + .5) * 360 / n
    PR: list[Any] = []
    CU: list[Any] = []
    LV = np.full(n, -1)
    for j, az in enumerate(AZ):
        p = section_profile(P, F, E, FE, M.cen, ft['hv'], c0, az)
        c = profile_cues(p) if p is not None else None
        PR.append(p)
        CU.append(c)
        if p is not None:
            LV[j] = _leave_index(p, c)
    valid = LV >= 0
    for j in np.flatnonzero(valid):
        if len(PR[j]['s']) - LV[j] < ROI_SAMPLES // 2:
            valid[j] = False
    if valid.sum() < 0.8 * n:
        raise BrainError('SHELL_WALL_NOT_FOUND', 'The outer wall of the scan could not be sectioned round the footprint.', {'columns_with_wall': int(valid.sum()), 'columns': n})
    zl = np.array([PR[j]['z'][LV[j]] if valid[j] else np.nan for j in range(n)])
    rl = np.array([PR[j]['r'][LV[j]] if valid[j] else np.nan for j in range(n)])
    ii = np.arange(n)
    for arr in (zl, rl):                                   # a section through a scan hole has a lower edge off its neighbours: not a wall section
        ref = _circ_interp(ii, valid, np.nan_to_num(arr), n)
        ref = _circ_smooth(ref, 11, 0.1)
        valid &= ~(np.abs(np.nan_to_num(arr, nan=1e9) - ref) > LEAVE_JUMP_MM)
    vi = np.flatnonzero(valid)
    if len(vi) < 0.8 * n:
        raise BrainError('SHELL_WALL_NOT_FOUND', 'The outer wall of the scan could not be sectioned round the footprint.', {'columns_with_wall': int(len(vi)), 'columns': n})
    K = ROI_SAMPLES
    m = len(vi)
    cost = np.full((m, K), 1e3)
    Zs, DS = np.full((m, K), np.nan), np.full((m, K), np.nan)
    KZ, GZ = np.zeros((m, K)), np.zeros((m, K))
    allk = np.concatenate([CU[j]['kink'][LV[j]:LV[j] + K] for j in vi])
    allg = np.concatenate([CU[j]['groove'][LV[j]:LV[j] + K] for j in vi])
    sk = max(1.4826 * float(np.median(np.abs(allk - np.median(allk)))), 1e-9)
    sgv = max(1.4826 * float(np.median(np.abs(allg - np.median(allg)))), 1e-12)
    for q, j in enumerate(vi):
        r = np.arange(LV[j], min(LV[j] + K, len(PR[j]['s'])))
        c = CU[j]
        kz = 2 * np.log1p(np.maximum(c['kink'][r], 0) / sk)
        gz = np.clip(c['groove'][r] / sgv, -3, 6)
        gate = (c['phib'][r] > GATE_BELOW_DEG) & (c['phia'][r] > GATE_ABOVE_DEG)
        cost[q, :len(r)] = -(kz + GROOVE_W * gz) + np.where(gate, 0, GATE_PEN)
        Zs[q, :len(r)] = PR[j]['z'][r]
        DS[q, :len(r)] = PR[j]['s'][r] - PR[j]['s'][LV[j]]
        KZ[q, :len(r)], GZ[q, :len(r)] = kz, gz
    rows = np.arange(m)
    path = _viterbi_z(cost, Zs, DP_LAM)
    angv = np.radians(AZ[vi])
    B = np.column_stack([np.ones(m)] + [g(k * angv) for k in range(1, PRIOR_HARM + 1) for g in (np.cos, np.sin)])
    prior = np.zeros(m)
    for _ in range(2):
        ds = DS[rows, path]
        use = -cost[rows, path] > SUPPORT_SCORE
        co = np.linalg.lstsq(B, ds, rcond=None)[0]
        sup0 = use.copy()
        for _ in range(6):
            if use.sum() < B.shape[1] + 3:
                break
            co = np.linalg.lstsq(B[use], ds[use], rcond=None)[0]
            res = ds - B @ co
            sig = 1.4826 * float(np.median(np.abs(res[use])))
            use = sup0 & (np.abs(res) < max(3 * sig, 0.5))
        prior = B @ co
        path = _viterbi_z(cost + PRIOR_W * np.maximum(np.abs(DS - prior[:, None]) - PRIOR_TOL, 0), Zs, DP_LAM)
    score = -cost[rows, path]
    # contrast: against every other position of the section that the loop prior allows (>= 1 mm away); a stronger crease far outside the
    # prior band (button gap, front lip step) does not make the seam ambiguous
    allowed = np.abs(DS - prior[:, None]) <= PRIOR_TOL + CONTRAST_WIN_MM
    others = np.where((np.abs(DS - DS[rows, path][:, None]) > CONTRAST_SEP_MM) & allowed, -cost, -1e9)
    contrast = score - others.max(1)
    sup = (score > SUPPORT_SCORE) & (contrast > SUPPORT_CONTRAST)
    if sup.sum() < 0.1 * m:
        raise BrainError('SHELL_SEAM_NOT_FOUND', 'No crease or groove of a parting seam was found round the wall; the shell split is not attempted.', {'supported_columns': int(sup.sum())})
    # a single section below the threshold inside a continuous cue ridge is noise; supported specks shorter than MIN_RUN sections are not support
    for rr in _runs(sup):
        if not sup[rr[0]] and len(rr) <= 1:
            sup[rr] = True
    for rr in _runs(sup):
        if sup[rr[0]] and len(rr) < MIN_RUN:
            sup[rr] = False
    ds = DS[rows, path]
    off_f = _circ_interp(np.arange(m), sup, ds - prior, m)       # inferred: prior shape, shifted linearly to meet the supported ends
    ds = _circ_smooth(np.where(sup, ds, prior + off_f), 3, 1.0)
    full_ds = np.zeros(n)
    full_ds[vi] = ds
    sup_full = np.zeros(n, bool)
    sup_full[vi] = sup
    kz_full, gz_full, sc_full, ct_full = np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n)
    kz_full[vi], gz_full[vi], sc_full[vi], ct_full[vi] = KZ[rows, path], GZ[rows, path], score, contrast
    pts = np.zeros((n, 3))
    tan = np.zeros((n, 2))
    for j in vi:
        p = PR[j]
        sj = p['s'][LV[j]] + full_ds[j]
        pts[j] = [np.interp(sj, p['s'], p['x']), np.interp(sj, p['s'], p['y']), np.interp(sj, p['s'], p['z'])]
        k0 = int(np.clip(round(sj / PROFILE_STEP), 3, len(p['s']) - 4))
        d = np.array([p['r'][k0 + 3] - p['r'][k0 - 3], p['z'][k0 + 3] - p['z'][k0 - 3]])
        tan[j] = d / max(float(np.linalg.norm(d)), 1e-12)
    for k in range(3):                                    # sections through scan holes: interpolated round the loop (and inferred);
        pts[:, k] = _circ_smooth(_circ_interp(ii, valid, pts[:, k], n), 5, 1.0)   # then a light 3-D smoothing (lower-edge jitter of single sections)
    for k in range(2):
        tan[:, k] = _circ_interp(ii, valid, tan[:, k], n)
    tan /= np.linalg.norm(tan, axis=1)[:, None] + 1e-12
    zl_f = _circ_smooth(_circ_interp(ii, valid, np.nan_to_num(zl), n), 5, 1.0)
    rl_f = _circ_smooth(_circ_interp(ii, valid, np.nan_to_num(rl), n), 5, 1.0)
    rad = np.hypot(pts[:, 0] - c0[0], pts[:, 1] - c0[1])
    seglen = np.linalg.norm(np.roll(pts, -1, 0) - pts, axis=1)
    ev = np.where(~sup_full, 'inferred', np.where((kz_full >= EVID_KINK) & (gz_full >= EVID_GROOVE), 'crease+groove',
                                                   np.where(gz_full >= EVID_GROOVE, 'groove', 'crease')))
    return {'c0': c0, 'ang': np.radians(AZ), 'az': AZ, 'pts': pts, 'z': pts[:, 2], 'rad': rad, 'tan': tan, 'supported': sup_full, 'valid': valid,
            'seglen': seglen, 'ds': full_ds, 'zl': zl_f, 'rl': rl_f, 'score': sc_full, 'contrast': ct_full, 'kink_z': kz_full, 'groove_z': gz_full, 'evidence': ev,
            'scales': {'crease_deg_per_mm': sk, 'groove_mm': sgv}}


def _face_graph(F: np.ndarray, cen: np.ndarray) -> sp.csr_matrix:
    nv = int(F.max()) + 1
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    e.sort(1)
    fid = np.tile(np.arange(len(F)), 3)
    key = e[:, 0] * nv + e[:, 1]
    o = np.argsort(key, kind='stable')
    k, f = key[o], fid[o]
    same = k[1:] == k[:-1]
    a, b = f[:-1][same], f[1:][same]
    w = np.linalg.norm(cen[a] - cen[b], axis=1) + 1e-6
    G = sp.coo_matrix((w, (a, b)), shape=(len(F), len(F))).tocsr()
    return (G + G.T).tocsr()


def classify(M: Any, ft: dict[str, Any], seam: dict[str, Any], buttons: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Bottom plate / top shell from the seam loop. Outer-wall faces within a band round the seam take the side of the seam along the section
    tangent; faces at or below the wall's lower edge inside the footprint seed the bottom plate; faces well above the seam seed the top
    parent. The split uses geometry only: the click / wheel / side-button faces of the region step are NOT inputs to it (`buttons` is used
    only afterwards, to carve the functional children out of the top parent and to count conflicts). Every other face (sensor pocket, screw bosses, label recess, scan-hole walls) joins its nearest seed along the mesh
    (multi-source Dijkstra). Finally both classes are made single edge-connected components: detached bottom islands join the top parent, detached
    top-parent islands (enclosed by the plate) join the bottom."""
    from scipy.sparse.csgraph import dijkstra
    cen = M.cen
    c0 = seam['c0']
    th = np.degrees(np.arctan2(cen[:, 1] - c0[1], cen[:, 0] - c0[0]))
    rf = np.hypot(cen[:, 0] - c0[0], cen[:, 1] - c0[1])
    rs, zs = _seam_at(seam['rad'], th), _seam_at(seam['z'], th)
    tr, tz = _seam_at(seam['tan'][:, 0], th), _seam_at(seam['tan'][:, 1], th)
    nrm = np.hypot(tr, tz) + 1e-12
    tr, tz = tr / nrm, tz / nrm
    dr, dz = rf - rs, cen[:, 2] - zs
    along = dr * tr + dz * tz
    across = dr * tz - dz * tr                            # > 0 outside the wall
    band = (np.abs(along) < BAND_ALONG_MM) & (np.abs(across) < BAND_ACROSS_MM)
    zl, rl = _seam_at(seam['zl'], th), _seam_at(seam['rl'], th)
    seed_b = (band & (along < 0)) | ((cen[:, 2] < zl + 0.3) & (rf < rl + 0.5))
    seed_t = ((band & (along >= 0)) | (dz > TOP_SEED_MM)) & ~seed_b
    seeds = np.flatnonzero(seed_b | seed_t)
    G = _face_graph(M.F, cen)
    _, _, src = dijkstra(G, directed=False, indices=seeds, min_only=True, return_predecessors=True)
    bottom = np.where(src >= 0, seed_b[np.maximum(src, 0)], False)
    bottom[seed_b] = True
    bottom[seed_t] = False
    moved = {'bottom_islands_to_top': 0, 'top_islands_to_bottom': 0}
    islands: list[dict[str, Any]] = []

    def note(fl: np.ndarray, lab_: np.ndarray, sel_: np.ndarray, to: str) -> None:
        for k in np.unique(lab_[sel_]):
            ff = fl[lab_[sel_] == k]
            islands.append({'faces': int(len(ff)), 'area_mm2': round(float(M.farea[ff].sum()), 2), 'centre_mm': [round(float(c), 1) for c in cen[ff].mean(0)], 'moved_to': to})
    for _ in range(4):
        changed = False
        idx, lab, nc = _components(M.F, bottom)
        if nc > 1:
            big = int(np.argmax(np.bincount(lab)))
            flip = idx[lab != big]
            note(idx[lab != big], lab, lab != big, 'top_shell')
            bottom[flip] = False
            moved['bottom_islands_to_top'] += int(len(flip))
            changed = True
        idx, lab, nc = _components(M.F, ~bottom)
        if nc > 1:
            big = int(np.argmax(np.bincount(lab)))
            flip = idx[lab != big]
            note(idx[lab != big], lab, lab != big, 'bottom_plate')
            bottom[flip] = True
            moved['top_islands_to_bottom'] += int(len(flip))
            changed = True
        if not changed:
            break
    if buttons is None:
        buttons = np.zeros(len(M.F), bool)
    top = ~bottom & ~buttons                              # top shell body = the remainder of the top parent
    outer = np.abs(across) < BAND_ACROSS_MM
    info = {'band_faces': int(band.sum()), 'seed_bottom_faces': int(seed_b.sum()), 'seed_top_faces': int(seed_t.sum()), **moved,
            'bottom_on_outer_wall_above_seam': int((bottom & outer & (along > 0.3) & (np.abs(along) < 15)).sum()),
            'top_on_outer_wall_below_seam': int((top & outer & (along < -0.3) & (np.abs(along) < 15)).sum()),
            'top_on_underside': int((top & (cen[:, 2] < zl + 0.3) & (rf < rl + 0.5)).sum()),
            'functional_faces_in_bottom': int((bottom & buttons).sum()), 'islands': islands}
    return bottom, top, info


def _seam_at(arr: np.ndarray, th_deg: np.ndarray) -> np.ndarray:
    n = len(arr)
    f = (th_deg + 180) / 360 * n - .5
    i0 = np.floor(f).astype(int)
    w = f - i0
    return arr[i0 % n] * (1 - w) + arr[(i0 + 1) % n] * w


def _components(F: np.ndarray, sel: np.ndarray):
    idx = np.flatnonzero(sel)
    if len(idx) == 0:
        return idx, np.zeros(0, int), 0
    Fs = F[idx]
    nv = int(F.max()) + 1
    e = np.concatenate([Fs[:, [0, 1]], Fs[:, [1, 2]], Fs[:, [2, 0]]])
    e.sort(1)
    fid = np.tile(np.arange(len(idx)), 3)
    key = e[:, 0] * nv + e[:, 1]
    o = np.argsort(key, kind='stable')
    k, f = key[o], fid[o]
    same = k[1:] == k[:-1]
    G = sp.coo_matrix((np.ones(same.sum()), (f[:-1][same], f[1:][same])), shape=(len(idx), len(idx)))
    n, lab = connected_components(G, directed=False)
    return idx, lab, n


def _idbuf_pix(t2: np.ndarray, depth: np.ndarray, x0: float, y0: float, nx: int, ny: int, pix: float, valid: np.ndarray) -> np.ndarray:
    """Painter id buffer at an arbitrary pixel size: pixel -> face id (-1 empty), faces drawn in ascending `depth` (last wins). Indexed [ix, iy]."""
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (nx, ny), (255, 255, 255))
    dr = ImageDraw.Draw(img)
    q = (t2 - np.array([x0, y0])) / pix
    ids = np.flatnonzero(valid)
    ids = ids[np.argsort(depth[ids], kind='stable')]
    for i in ids:
        dr.polygon([tuple(p) for p in q[i]], fill=(int(i) & 255, (int(i) >> 8) & 255, int(i) >> 16))
    a = np.array(img).astype(np.int64)
    r = a[:, :, 0] | (a[:, :, 1] << 8) | (a[:, :, 2] << 16)
    r[(a[:, :, 0] == 255) & (a[:, :, 1] == 255) & (a[:, :, 2] == 255)] = -1
    return r.T.copy()


def _fib_dirs(n: int) -> np.ndarray:
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    th = np.pi * (1 + 5 ** 0.5) * i
    return np.c_[np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)]


def underside_frame(P: np.ndarray, F: np.ndarray, fs: np.ndarray, farea: np.ndarray) -> dict[str, Any]:
    """Generic underside frame from geometry alone: the largest near-coplanar face family (normals within FLAT_TOL_DEG) that lies at an extreme
    of the mesh along its normal is the base plate. e3 points up (into the body), e1 is the major axis of the footprint. No prior pose is used."""
    cos_t = np.cos(np.radians(FLAT_TOL_DEG))
    step = max(1, len(fs) // 40000)
    fsub, asub = fs[::step], farea[::step]
    D = _fib_dirs(4000)
    score = np.zeros(len(D))
    for k in range(0, len(D), 250):
        score[k:k + 250] = ((D[k:k + 250] @ fsub.T) > cos_t).astype(float) @ asub
    best = None
    for k in np.argsort(-score)[:40]:                      # strongest flat families; keep the first one at an extreme of the mesh along its normal
        d = D[k]
        sel = (fs @ d) > cos_t
        if sel.sum() < 30:
            continue
        d = (fs[sel] * farea[sel][:, None]).sum(0)
        d /= np.linalg.norm(d)
        sel = (fs @ d) > cos_t
        if sel.sum() < 30:
            continue
        cen = P[F[sel]].mean(1)
        s_ = P @ d
        ext = float(s_.max() - s_.min())
        pos = float(np.median(cen @ d))
        if s_.max() - pos < 0.08 * ext:                    # the family sits at the extreme of the mesh and faces outwards: a base
            best = (d, sel, float(farea[sel].sum()))
            break
    if best is None:
        return {'found': False}
    d, sel, area = best
    e3 = -d
    cen = P[F[sel]].mean(1)
    w = farea[sel]
    o = (cen * w[:, None]).sum(0) / w.sum()
    Q = P - o
    q2 = Q - np.outer(Q @ e3, e3)
    _, evec = np.linalg.eigh(np.cov(q2.T))
    e1 = evec[:, -1] - (evec[:, -1] @ e3) * e3
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(e3, e1)
    U = np.c_[Q @ e1, Q @ e2, Q @ e3]
    return {'found': True, 'o': o, 'R': np.vstack([e1, e2, e3]), 'U': U, 'plate_faces': sel, 'plate_area': area,
            'length': float(np.ptp(U[:, 0])), 'width': float(np.ptp(U[:, 1]))}


def _superellipse_fit(p: np.ndarray, nfix: float | None = None) -> tuple[np.ndarray, float, np.ndarray]:
    """|u/a|^n + |v/b|^n = 1 rotated by th about (cx, cy); radial residual in length units. Returns params (a = major), rms, 1-sigma of params."""
    from scipy import optimize

    def res(q):
        cx, cy, a, b, n, th = q
        if nfix is not None:
            n = nfix
        ct, st = np.cos(th), np.sin(th)
        u = (p[:, 0] - cx) * ct + (p[:, 1] - cy) * st
        v = -(p[:, 0] - cx) * st + (p[:, 1] - cy) * ct
        return ((np.abs(u / a) ** n + np.abs(v / b) ** n) ** (1 / n) - 1) * np.sqrt(a * b)
    sx, sy = np.ptp(p[:, 0]) / 2, np.ptp(p[:, 1]) / 2
    q0 = [p[:, 0].mean(), p[:, 1].mean(), max(sx, 1e-9), max(sy, 1e-9), 2.5 if nfix is None else nfix, 0.0]
    lo = [-np.inf, -np.inf, 1e-9, 1e-9, 1.5, -np.pi / 2]
    hi = [np.inf, np.inf, np.inf, np.inf, 12.0, np.pi / 2]
    s = optimize.least_squares(res, q0, bounds=(lo, hi), x_scale='jac')
    J = s.jac
    cov = np.linalg.pinv(J.T @ J) * float(np.mean(s.fun ** 2)) * len(p) / max(len(p) - 6, 1)
    sd = np.sqrt(np.abs(np.diag(cov)))
    q = s.x.copy()
    if nfix is not None:
        q[4] = nfix
    if q[3] > q[2]:                                        # canonical: a = major semi-axis
        q[2], q[3], q[5] = q[3], q[2], q[5] + np.pi / 2
        sd[2], sd[3] = sd[3], sd[2]
    q[5] = (q[5] + np.pi / 2) % np.pi - np.pi / 2
    return q, float(np.sqrt(np.mean(s.fun ** 2))), sd


def _rim_points(Hn: np.ndarray, pix: float, u0: float, v0: float, c: np.ndarray, level: float, rmax: float, nray: int = 360) -> np.ndarray:
    """First outward crossing of the height map through `level` on rays from c (sub-pixel, linear interpolation)."""
    ang = np.linspace(0, 2 * np.pi, nray, endpoint=False)
    rs = np.arange(0, rmax, pix / 3)
    X = c[0] + np.outer(np.cos(ang), rs)
    Y = c[1] + np.outer(np.sin(ang), rs)
    h = ndi.map_coordinates(Hn, [(X - u0) / pix - .5, (Y - v0) / pix - .5], order=1, mode='nearest')
    out = []
    for i in range(nray):
        below = np.flatnonzero(h[i] < level)
        if len(below) == 0 or below[0] == 0:
            continue
        j = below[0]
        t = (h[i, j - 1] - level) / max(h[i, j - 1] - h[i, j], 1e-12)
        r = rs[j - 1] + t * (rs[j] - rs[j - 1])
        out.append([c[0] + r * np.cos(ang[i]), c[1] + r * np.sin(ang[i])])
    return np.array(out).reshape(-1, 2)


def _rot2(p: np.ndarray, c: np.ndarray, th: float) -> np.ndarray:
    ct, st = np.cos(th), np.sin(th)
    d = p - c
    return np.c_[d[:, 0] * ct + d[:, 1] * st, -d[:, 0] * st + d[:, 1] * ct]


def _sd_superellipse(q: np.ndarray, p: np.ndarray, nfix: float | None = None) -> np.ndarray:
    cx, cy, a, b, n, th = q
    n = nfix or n
    u = _rot2(p, np.array([cx, cy]), th)
    return ((np.abs(u[:, 0] / a) ** n + np.abs(u[:, 1] / b) ** n) ** (1 / n) - 1) * np.sqrt(a * b)


def _sd_rrect4(q: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Signed distance to a rectangle with straight edges and one corner radius per quadrant (r1 +u+v, r2 -u+v, r3 -u-v, r4 +u-v)."""
    cx, cy, a, b, th, r1, r2, r3, r4 = q
    u = _rot2(p, np.array([cx, cy]), th)
    r = np.where(u[:, 0] > 0, np.where(u[:, 1] > 0, r1, r4), np.where(u[:, 1] > 0, r2, r3))
    k = np.c_[np.abs(u[:, 0]) - (a - r), np.abs(u[:, 1]) - (b - r)]
    return np.hypot(np.maximum(k[:, 0], 0), np.maximum(k[:, 1], 0)) + np.minimum(np.maximum(k[:, 0], k[:, 1]), 0) - r


def _robust_lsq(fun, q0, lo, hi, p, scale):
    from scipy import optimize
    s = optimize.least_squares(lambda q: fun(q, p), q0, bounds=(lo, hi), loss='soft_l1', f_scale=scale, x_scale='jac')
    return s.x, fun(s.x, p)


def _fourier_basis(t: np.ndarray, K: int) -> np.ndarray:
    return np.column_stack([np.ones_like(t)] + [g(k * t) for k in range(1, K + 1) for g in (np.cos, np.sin)])


def _fourier_fit(p: np.ndarray, c: np.ndarray, K: int) -> tuple[np.ndarray, np.ndarray]:
    """Radius r(theta) about c as a K-harmonic series, iteratively reweighted (Cauchy) against scan outliers."""
    d = p - c
    t = np.arctan2(d[:, 1], d[:, 0])
    r = np.hypot(d[:, 0], d[:, 1])
    B = _fourier_basis(t, K)
    w = np.ones_like(r)
    co = np.zeros(B.shape[1])
    for _ in range(6):
        co = np.linalg.lstsq(B * w[:, None], r * w, rcond=None)[0]
        res = r - B @ co
        s = 1.4826 * float(np.median(np.abs(res)))
        w = 1 / np.sqrt(1 + (res / max(2 * s, 1e-12)) ** 2)
    return co, r - B @ co


def _fourier_curve(co: np.ndarray, c: np.ndarray, n: int = OUTLINE_POINTS) -> np.ndarray:
    t = np.linspace(-np.pi, np.pi, n, endpoint=False)
    r = _fourier_basis(t, (len(co) - 1) // 2) @ co
    return np.c_[c[0] + r * np.cos(t), c[1] + r * np.sin(t)]


def _zero_curve(fun, q: np.ndarray, c: np.ndarray, rmax: float, n: int = OUTLINE_POINTS) -> np.ndarray:
    """Dense polyline of the zero set of a star-shaped signed-distance model, by bisection on rays from c."""
    t = np.linspace(-np.pi, np.pi, n, endpoint=False)
    d = np.c_[np.cos(t), np.sin(t)]
    lo, hi = np.zeros(n), np.full(n, rmax)
    for _ in range(40):
        mid = (lo + hi) / 2
        inside = fun(q, c + mid[:, None] * d) < 0
        lo, hi = np.where(inside, mid, lo), np.where(inside, hi, mid)
    return c + lo[:, None] * d


def _res_stats(res: np.ndarray) -> dict[str, Any]:
    a = np.abs(res)
    return {'rms_mm': round(float(np.sqrt(np.mean(res ** 2))), 4), 'p95_mm': round(float(np.percentile(a, 95)), 4), 'max_mm': round(float(a.max()), 4), 'points': int(len(a))}


def _bic(res: np.ndarray, k: int) -> float:
    n = len(res)
    s = 1.4826 * float(np.median(np.abs(res))) + 1e-12
    rss = float(np.sum(np.minimum(res ** 2, (4 * s) ** 2)))   # outliers capped so a few scan spikes cannot pick the model
    return n * np.log(max(rss, 1e-30) / n) + k * np.log(n)


def _dist_to_polyline(p: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Distance of each point to a closed polyline."""
    a, d = poly, np.roll(poly, -1, 0) - poly
    L = np.maximum((d ** 2).sum(1), 1e-18)
    out = np.empty(len(p))
    for k0 in range(0, len(p), 256):
        q = p[k0:k0 + 256, None, :]
        t = np.clip(((q - a) * d).sum(2) / L, 0, 1)
        out[k0:k0 + 256] = np.hypot(*(a + t[..., None] * d - q).transpose(2, 0, 1)).min(1)
    return out


def _poly_centroid(P: np.ndarray) -> np.ndarray:
    x, y = P[:, 0], P[:, 1]
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    cr = x * y1 - x1 * y
    A = cr.sum() / 2
    return np.array([((x + x1) * cr).sum() / (6 * A), ((y + y1) * cr).sum() / (6 * A)])


def _iso_crossings(U: np.ndarray, h: np.ndarray, E: np.ndarray, level: float) -> np.ndarray:
    ha, hb = h[E[:, 0]], h[E[:, 1]]
    x = (ha - level) * (hb - level) < 0
    t = (level - ha[x]) / (hb[x] - ha[x])
    return U[E[x, 0], :2] + t[:, None] * (U[E[x, 1], :2] - U[E[x, 0], :2])


def _fit_line(p: np.ndarray, scale: float) -> tuple[dict[str, Any], np.ndarray]:
    """Robust (Cauchy-reweighted) total-least-squares line: n . x = d with |n| = 1."""
    w = np.ones(len(p))
    for _ in range(6):
        m = (p * w[:, None]).sum(0) / w.sum()
        C = ((p - m) * w[:, None]).T @ (p - m)
        ev, evec = np.linalg.eigh(C)
        n = evec[:, 0]
        res = (p - m) @ n
        w = 1 / np.sqrt(1 + (res / max(scale, 1e-12)) ** 2)
    t = (p - m) @ np.array([-n[1], n[0]])
    return {'kind': 'line', 'n': n, 'd': float(n @ m), 'point': m, 'dir': np.array([-n[1], n[0]]), 't_range': (float(t.min()), float(t.max()))}, res


def _fit_circle(p: np.ndarray, scale: float) -> tuple[dict[str, Any], np.ndarray]:
    from scipy import optimize
    A = np.c_[p, np.ones(len(p))]
    s = np.linalg.lstsq(A, -(p ** 2).sum(1), rcond=None)[0]
    c0 = -s[:2] / 2
    r0 = float(np.sqrt(max(c0 @ c0 - s[2], 1e-12)))
    o = optimize.least_squares(lambda q: np.hypot(p[:, 0] - q[0], p[:, 1] - q[1]) - q[2], [c0[0], c0[1], r0], loss='soft_l1', f_scale=max(scale, 1e-12))
    cx, cy, r = o.x
    return {'kind': 'arc', 'centre': np.array([cx, cy]), 'radius': float(abs(r))}, np.hypot(p[:, 0] - cx, p[:, 1] - cy) - abs(r)


def _piecewise_outline(p: np.ndarray, c: np.ndarray, ref: np.ndarray, sigma: float, size: float) -> dict[str, Any]:
    """Generic 'k lines + m arcs' outline: the smooth reference loop is cut where its curvature class changes (line / arc), each run of raw
    points gets the better of a robust line and a robust circle (BIC), and a run that neither fits within tolerance is split at its curvature
    extremum (recursively). Nothing about which side is round is assumed."""
    n = len(ref)
    d1 = (np.roll(ref, -1, 0) - np.roll(ref, 1, 0)) / 2
    d2 = np.roll(ref, -1, 0) - 2 * ref + np.roll(ref, 1, 0)
    kap = (d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / np.maximum(np.hypot(d1[:, 0], d1[:, 1]) ** 3, 1e-18)
    kap = ndi.gaussian_filter1d(kap, 2, mode='wrap')
    k_line = LINE_CURVATURE_REL / size
    cls = np.abs(kap) > k_line
    if cls.all() or not cls.any():
        starts = np.array([0])
    else:
        starts = np.flatnonzero(cls != np.roll(cls, 1))
    tp = np.arctan2(p[:, 1] - c[1], p[:, 0] - c[0])
    tr = np.arctan2(ref[:, 1] - c[1], ref[:, 0] - c[0])
    tol = max(2.5 * sigma, PIECE_TOL_REL * size)
    min_pts = 12

    def idx_range(i0, i1):                                   # ref indices i0..i1-1 (cyclic)
        return np.arange(i0, i1 if i1 > i0 else i1 + n) % n

    def pts_in(ii):
        a0, a1 = tr[ii[0]], tr[ii[-1]]
        span = (a1 - a0) % (2 * np.pi)
        return ((tp - a0) % (2 * np.pi)) <= span + 1e-9

    segs = []

    def solve(ii, depth=0):
        sel = pts_in(ii)
        q = p[sel]
        if sel.sum() < min_pts:
            if segs:
                segs[-1]['ref_idx'] = np.r_[segs[-1]['ref_idx'], ii]
            else:
                segs.append({'ref_idx': ii, 'prim': None, 'sel': sel})
            return
        fl, rl = _fit_line(q, sigma)
        fc_, rc_ = _fit_circle(q, sigma)
        rms_l, rms_c = float(np.sqrt(np.mean(rl ** 2))), float(np.sqrt(np.mean(rc_ ** 2)))
        straightish = fc_['radius'] > LINE_RADIUS_REL * size
        bl, bc = _bic(rl, 2), (_bic(rc_, 3) if not straightish else np.inf)
        prim, res, rms = (fl, rl, rms_l) if bl <= bc else (fc_, rc_, rms_c)
        if rms > tol and len(ii) >= 2 * 8 and depth < 6:
            inner = ii[4:-4]
            j = inner[int(np.argmin(np.abs(kap[inner]))) if prim['kind'] == 'arc' else int(np.argmax(np.abs(kap[inner])))]
            cut = int(np.flatnonzero(ii == j)[0])
            cut = min(max(cut, 4), len(ii) - 4)
            solve(ii[:cut], depth + 1)
            solve(ii[cut:], depth + 1)
            return
        segs.append({'ref_idx': ii, 'prim': prim, 'sel': sel, 'rms': rms})
    for k in range(len(starts)):
        i0 = starts[k]
        i1 = starts[(k + 1) % len(starts)] if len(starts) > 1 else starts[0] + n
        solve(idx_range(i0, i1 % n if len(starts) > 1 else i0))
    segs = [s for s in segs if s['prim'] is not None]
    # merge neighbours of the same kind that one primitive fits within tolerance (curvature noise can split a straight edge)
    merged = True
    while merged and len(segs) > 2:
        merged = False
        for k in range(len(segs)):
            s1, s2 = segs[k], segs[(k + 1) % len(segs)]
            if s1['prim']['kind'] != s2['prim']['kind']:
                continue
            q = p[s1['sel'] | s2['sel']]
            f, r = (_fit_line if s1['prim']['kind'] == 'line' else _fit_circle)(q, sigma)
            if float(np.sqrt(np.mean(r ** 2))) <= tol:
                segs[k] = {'ref_idx': np.r_[s1['ref_idx'], s2['ref_idx']], 'prim': f, 'sel': s1['sel'] | s2['sel'], 'rms': float(np.sqrt(np.mean(r ** 2)))}
                del segs[(k + 1) % len(segs)]
                merged = True
                break
    res = np.full(len(p), np.nan)
    poly = np.zeros_like(ref)
    for s in segs:
        pr = s['prim']
        q = p[s['sel']]
        rr = ref[s['ref_idx']]
        if pr['kind'] == 'line':
            res[s['sel']] = q @ pr['n'] - pr['d']
            poly[s['ref_idx']] = rr - np.outer(rr @ pr['n'] - pr['d'], pr['n'])
            t = (q - pr['point']) @ pr['dir']
            pr['t_range'] = (float(t.min()), float(t.max()))
        else:
            res[s['sel']] = np.hypot(q[:, 0] - pr['centre'][0], q[:, 1] - pr['centre'][1]) - pr['radius']
            v = rr - pr['centre']
            poly[s['ref_idx']] = pr['centre'] + v / np.maximum(np.hypot(v[:, 0], v[:, 1]), 1e-12)[:, None] * pr['radius']
            a = np.degrees(np.arctan2(q[:, 1] - pr['centre'][1], q[:, 0] - pr['centre'][0]))
            pr['sweep_deg'] = float(np.ptp(np.unwrap(np.radians(np.sort(a)))) * 180 / np.pi)
    res = np.where(np.isnan(res), 0.0, res)
    k_par = sum(2 if s['prim']['kind'] == 'line' else 3 for s in segs) + len(segs)      # + one breakpoint per segment
    return {'segments': segs, 'res': res, 'k': k_par, 'polyline': poly, 'tol': tol}


def _fillet_poly_geometry(q: np.ndarray, m: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Convex m-gon given by m lines n_i . x = d_i (n_i at angle phi_i, outward) with a fillet radius r_i at the corner between line i and i+1.
    Returns normals, offsets, radii and fillet centres (each centre is r_i inside both lines of its corner)."""
    phi, d, r = q[0:m], q[m:2 * m], q[2 * m:3 * m]
    n = np.c_[np.cos(phi), np.sin(phi)]
    cen = np.zeros((m, 2))
    for i in range(m):
        j = (i + 1) % m
        A = np.vstack([n[i], n[j]])
        det = np.linalg.det(A)
        cen[i] = np.linalg.solve(A, [d[i] - r[i], d[j] - r[i]]) if abs(det) > 1e-9 else np.array([np.nan, np.nan])
    return n, d, r, cen


def _sd_fillet_poly(q: np.ndarray, p: np.ndarray, m: int) -> np.ndarray:
    """Signed distance (exact near the boundary) to a convex polygon whose corners are rounded by tangent arcs: straight lines + arcs."""
    n, d, r, cen = _fillet_poly_geometry(q, m)
    sd = (p @ n.T - d).max(1)
    for i in range(m):
        j = (i + 1) % m
        if not np.isfinite(cen[i]).all():
            continue
        v = p - cen[i]
        corner = (v @ n[i] > 0) & (v @ n[j] > 0)
        sd = np.where(corner, np.hypot(v[:, 0], v[:, 1]) - r[i], sd)
    return sd


def _fillet_poly_from_rrect4(q4: np.ndarray) -> np.ndarray:
    cx, cy, a, b, th, r1, r2, r3, r4 = q4
    c = np.array([cx, cy])
    phi = np.array([th, th + np.pi / 2, th + np.pi, th + 1.5 * np.pi])   # +u, +v, -u, -v sides
    off = np.array([a, b, a, b])
    d = off + np.c_[np.cos(phi), np.sin(phi)] @ c
    return np.r_[phi, d, [r1, r2, r3, r4]]               # corners: (+u,+v) r1, (+v,-u) r2, (-u,-v) r3, (-v,+u) r4


def _family_fits(p: np.ndarray, c: np.ndarray, a: float, b: float, sc: float) -> dict[str, dict[str, Any]]:
    """Line + arc families as constrained rounded rectangles (straight edges tangent to corner arcs), axis a along the fitted major axis:
    rounded_rectangle (one radius), stadium (both ends semicircles), u_shape_pos / u_shape_neg (one semicircular end, the other flat with
    a corner radius; which end is round comes from the data) and rect_4radii (independent corner radii)."""
    big = 10.0 * (a + b)
    lo4 = [-big, -big, 1e-6, 1e-6, -np.pi / 2, 1e-6, 1e-6, 1e-6, 1e-6]
    hi4 = [big, big, big, big, np.pi / 2, big, big, big, big]
    q4, _ = _robust_lsq(_sd_rrect4, [c[0], c[1], a, b, 0.0, .3 * b, .3 * b, .3 * b, .3 * b], lo4, hi4, p, sc)
    if q4[3] > q4[2]:                                       # keep a along the major axis
        q4 = np.r_[q4[:2], q4[3], q4[2], q4[4] + np.pi / 2, q4[6], q4[7], q4[8], q4[5]]
    q4[5:] = np.minimum(q4[5:], min(q4[2], q4[3]))
    base = q4[:5]
    fams: dict[str, dict[str, Any]] = {'rect_4radii': {'q': q4, 'k': 9}}

    def fam(name, expand, x0, lo, hi, k):
        f = lambda q, pp: _sd_rrect4(expand(q), pp)
        q, _ = _robust_lsq(f, x0, lo, hi, p, sc)
        fams[name] = {'q': expand(q), 'k': k}
    lo5, hi5 = [-big, -big, 1e-6, 1e-6, -np.pi], [big, big, big, big, np.pi]
    fam('rounded_rectangle', lambda q: np.r_[q[:5], [min(q[5], q[2], q[3])] * 4], np.r_[base, .3 * b], lo5 + [1e-6], hi5 + [big], 6)
    fam('stadium', lambda q: np.r_[q[:5], [min(q[2], q[3])] * 4], base, lo5, hi5, 5)
    fam('u_shape_pos', lambda q: np.r_[q[:5], min(q[2], q[3]), min(q[5], q[3]), min(q[5], q[3]), min(q[2], q[3])], np.r_[base, .2 * b], lo5 + [1e-6], hi5 + [big], 6)
    fam('u_shape_neg', lambda q: np.r_[q[:5], min(q[5], q[3]), min(q[2], q[3]), min(q[2], q[3]), min(q[5], q[3])], np.r_[base, .2 * b], lo5 + [1e-6], hi5 + [big], 6)
    for f in fams.values():
        f['res'] = _sd_rrect4(f['q'], p)
    # general case: four free straight lines (not necessarily parallel) joined by four tangent arcs
    qf0 = _fillet_poly_from_rrect4(q4)
    lo = np.r_[qf0[:4] - 0.5, qf0[4:8] - big, np.full(4, 1e-6)]
    hi = np.r_[qf0[:4] + 0.5, qf0[4:8] + big, np.full(4, 1.2 * min(q4[2], q4[3]))]
    qf0[8:] = np.clip(qf0[8:], 1e-6, 1.2 * min(q4[2], q4[3]) - 1e-9)
    qf, rf_ = _robust_lsq(lambda q, pp: _sd_fillet_poly(q, pp, 4), qf0, lo, hi, p, sc)
    fams['quad_lines_arcs'] = {'q': qf, 'k': 12, 'res': rf_, 'm': 4}
    return fams


def _rrect4_params(q: np.ndarray, to_work=None) -> dict[str, Any]:
    cx, cy, a, b, th, r1, r2, r3, r4 = (float(v) for v in q)
    return {'centre_uv': [round(cx, 4), round(cy, 4)], 'length_mm': round(2 * a, 4), 'width_mm': round(2 * b, 4), 'rotation_deg': round(float(np.degrees(th)), 3),
            'corner_radii_mm': {'+u+v': round(r1, 4), '-u+v': round(r2, 4), '-u-v': round(r3, 4), '+u-v': round(r4, 4)},
            'straight_edge_lengths_mm': {'+u end': round(2 * b - r1 - r4, 4), '-u end': round(2 * b - r2 - r3, 4), '+v side': round(2 * a - r1 - r2, 4), '-v side': round(2 * a - r3 - r4, 4)}}


def mesh_rim_outline(U: np.ndarray, F: np.ndarray, h: np.ndarray, c: np.ndarray, a: float, b: float, depth: float) -> dict[str, Any]:
    """Aperture outline from the mesh itself: exact iso-height crossings of the mesh edges with planes parallel to the local plate surface.
    The rim level is the shallowest level (fraction of the floor depth, from RIM_SEARCH) whose crossings form one clean star-shaped loop
    round the candidate (full angular coverage, robust residual small, few outliers); shallower levels are rejected when they also cut other
    shallow features (grooves, labels). Model families are fitted to the raw rim points and chosen by BIC; the final outline is the BIC winner
    as a dense polyline, the best parametric family is reported for CAD."""
    rlo, rhi = 0.4 * b, 1.6 * a + 0.02 * (a + b)
    fc = U[F].mean(1)
    near = np.hypot(fc[:, 0] - c[0], fc[:, 1] - c[1]) < rhi + 0.2 * a
    Fn = F[near]
    if len(Fn) < 30:
        return {'found': False, 'reason': 'too few mesh faces round the candidate'}
    E = np.r_[Fn[:, [0, 1]], Fn[:, [1, 2]], Fn[:, [2, 0]]]
    E.sort(1)
    E = np.unique(E, axis=0)
    chosen = None
    tried = []
    for frac in RIM_SEARCH:
        lv = frac * depth
        p = np.vstack([_iso_crossings(U, h, E, lv * k) for k in RIM_BAND])
        if len(p) < 40:
            tried.append({'level_fraction': frac, 'accepted': False, 'why': 'too few crossings'})
            continue
        d = np.hypot(p[:, 0] - c[0], p[:, 1] - c[1])
        p = p[(d > rlo) & (d < rhi)]
        ang = np.degrees(np.arctan2(p[:, 1] - c[1], p[:, 0] - c[0]))
        gap = float(np.max(np.diff(np.r_[np.sort(ang), np.sort(ang)[:1] + 360]))) if len(ang) else 360.0
        if len(p) < 40 or gap > MAX_GAP_DEG:
            tried.append({'level_fraction': frac, 'accepted': False, 'why': 'loop not closed (largest angular gap %.1f deg)' % gap})
            continue
        co, res = _fourier_fit(p, c, 8)
        s = 1.4826 * float(np.median(np.abs(res)))
        out = float(np.mean(np.abs(res) > max(6 * s, 0.01 * (a + b))))
        ok = out < 0.03 and s < 0.02 * (a + b)
        tried.append({'level_fraction': frac, 'level_mm': round(lv, 3), 'accepted': ok, 'robust_sigma_mm': round(s, 4), 'outlier_fraction': round(out, 3)})
        if ok:
            chosen = (frac, lv, p, res, s)
            break
    if chosen is None:
        return {'found': False, 'reason': 'no rim level gave a clean closed loop on the mesh', 'levels_tried': tried}
    frac, lv, p, res8, s = chosen
    keep = np.abs(res8) <= max(6 * s, 0.01 * (a + b))           # scan spikes / shadowed patches
    p_all, p = p, p[keep]
    c = _poly_centroid(_fourier_curve(_fourier_fit(p, c, 8)[0], c))  # re-centre on the loop itself
    sc = max(2 * s, 1e-4 * (a + b))
    # smooth reference loop (only to locate curvature changes and to report the noise floor; it is not the outline)
    best_f = None
    for K in FOURIER_K:
        co, rf = _fourier_fit(p, c, K)
        bic = _bic(rf, 2 * K + 1)
        if best_f is None or bic < best_f[2]:
            best_f = (K, co, bic, rf)
    K, co, bic_f, rf = best_f
    ref = _fourier_curve(co, c)
    sigma = 1.4826 * float(np.median(np.abs(rf)))
    fams = _family_fits(p, c, a, b, sc)
    pw = _piecewise_outline(p, c, ref, sigma, b)
    # the piecewise chain is judged by the distance of the raw points to the polyline it actually draws, and dropped when that polyline
    # strays from the smooth reference loop (a badly placed arc centre can project the loop far away)
    pw_res = _dist_to_polyline(p, pw['polyline'])
    if float(np.abs(pw['polyline'] - ref).max()) <= max(0.1 * b, 6 * sigma):
        pw['res'] = pw_res
        fams['lines_and_arcs'] = {'res': pw_res, 'k': pw['k']}
    tau = max(3 * sigma, MODEL_TOL_REL * b)                # residual floor: a scanned rim is rounded / wavy by about this much, so fits below it tie
    for f in fams.values():
        n_ = len(f['res'])
        f['rms'] = float(np.sqrt(np.mean(f['res'] ** 2)))
        f['bic'] = n_ * np.log(max(f['rms'], tau) ** 2) + f['k'] * np.log(n_)
    qe, re = _robust_lsq(lambda q, pp: _sd_superellipse(q, pp, 2.0), [c[0], c[1], a, b, 2.0, 0.0], [-10 * (a + b)] * 2 + [1e-6, 1e-6, 1.5, -np.pi / 2],
                         [10 * (a + b)] * 2 + [10 * (a + b)] * 2 + [12, np.pi / 2], p, sc)
    qs, rs = _robust_lsq(_sd_superellipse, [c[0], c[1], a, b, 3.0, 0.0], [-10 * (a + b)] * 2 + [1e-6, 1e-6, 1.5, -np.pi / 2],
                         [10 * (a + b)] * 2 + [10 * (a + b)] * 2 + [12, np.pi / 2], p, sc)
    if qs[3] > qs[2]:
        qs = np.r_[qs[:2], qs[3], qs[2], qs[4], qs[5] + np.pi / 2]
    if qe[3] > qe[2]:
        qe = np.r_[qe[:2], qe[3], qe[2], qe[4], qe[5] + np.pi / 2]
    def fam_q_poly(name):                                  # every primitive family as a filleted polygon (lines + tangent arcs)
        f = fams[name]
        return (f['q'], f['m']) if 'm' in f else (_fillet_poly_from_rrect4(f['q']), 4)

    def fam_sdf(name):
        qf, m = fam_q_poly(name)
        return lambda q, pp: _sd_fillet_poly(q, pp, m), qf
    chosen_name = min(fams, key=lambda k_: (fams[k_]['bic'], fams[k_]['rms']))
    best_prim = min((k_ for k_ in fams if k_ != 'lines_and_arcs'), key=lambda k_: (fams[k_]['bic'], fams[k_]['rms']))
    sdf, qf = fam_sdf(best_prim)
    prim_curve = _zero_curve(sdf, qf, np.asarray(c, float), 4 * (a + b))
    if chosen_name == 'lines_and_arcs':
        curve, final_res = pw['polyline'], pw['res']
    else:
        curve, final_res = prim_curve, fams[chosen_name]['res']
    cen = _poly_centroid(curve)
    inl = np.abs(final_res) <= max(3 * tau, 6 * sigma)
    stab = None
    deeper = frac + 2 * (RIM_SEARCH[1] - RIM_SEARCH[0])
    p2 = np.vstack([_iso_crossings(U, h, E, deeper * depth * k) for k in RIM_BAND])
    if len(p2) >= 40:
        d2 = np.hypot(p2[:, 0] - c[0], p2[:, 1] - c[1])
        p2 = p2[(d2 > rlo) & (d2 < rhi)]
        if len(p2) >= 40:
            m_ = fam_q_poly(best_prim)[1]
            q2, _ = _robust_lsq(sdf, qf, np.r_[qf[:m_] - 0.5, qf[m_:2 * m_] - 10 * (a + b), np.full(m_, 1e-6)],
                                np.r_[qf[:m_] + 0.5, qf[m_:2 * m_] + 10 * (a + b), np.full(m_, 10 * (a + b))], p2, sc)
            c2 = _poly_centroid(_zero_curve(sdf, q2, np.asarray(c, float), 4 * (a + b)))
            pc = _poly_centroid(prim_curve)
            stab = {'level_fraction': round(deeper, 3), 'level_mm': round(deeper * depth, 3), 'model': best_prim,
                    'centroid_shift_uv': [float(c2[0] - pc[0]), float(c2[1] - pc[1])], 'max_offset_change_mm': round(float(np.abs(q2[m_:2 * m_] - qf[m_:2 * m_]).max()), 4)}
    segs = []
    for sgm in pw['segments']:
        pr = sgm['prim']
        if pr['kind'] == 'line':
            segs.append({'kind': 'line', 'normal_uv': [round(float(v), 5) for v in pr['n']], 'offset_mm': round(pr['d'], 4),
                         'equation': '%.5f*u + %.5f*v = %.4f' % (pr['n'][0], pr['n'][1], pr['d']), 'length_mm': round(pr['t_range'][1] - pr['t_range'][0], 3),
                         'rms_mm': round(sgm['rms'], 4), 'points': int(sgm['sel'].sum())})
        else:
            segs.append({'kind': 'arc', 'centre_uv': [round(float(v), 4) for v in pr['centre']], 'radius_mm': round(pr['radius'], 4), 'sweep_deg': round(pr.get('sweep_deg', 0.0), 1),
                         'rms_mm': round(sgm['rms'], 4), 'points': int(sgm['sel'].sum())})
    fam_json = {k_: {'criterion': round(float(f['bic']), 1), 'parameters': f['k'], **_res_stats(f['res'])} for k_, f in fams.items()}
    fam_json['ellipse (reference only)'] = {'parameters': 5, **_res_stats(re)}
    fam_json['superellipse (reference only)'] = {'parameters': 6, **_res_stats(rs)}
    fam_json['smooth_fourier (noise floor only)'] = {'parameters': 2 * K + 1, **_res_stats(rf)}
    qbest, mbest = fam_q_poly(best_prim)
    return {'found': True, 'level_fraction': frac, 'level_mm': lv, 'levels_tried': tried, 'raw_points': p, 'raw_points_all': p_all,
            'outliers_rejected': int((~keep).sum()), 'final_model': chosen_name, 'outline': curve, 'centroid': cen, 'final_residuals': _res_stats(final_res),
            'final_residuals_inliers': _res_stats(final_res[inl]), 'inlier_fraction': round(float(inl.mean()), 3),
            'families': fam_json, 'best_primitive_family': best_prim, 'primitive_poly_q': qbest, 'primitive_poly_m': mbest,
            'primitive': _describe_fillet_poly(qbest, mbest), 'primitive_curve': prim_curve, 'piecewise_segments': segs, 'noise_sigma_mm': sigma,
            'superellipse_q': qs, 'ellipse_q': qe, 'stability': stab, 'segment_tolerance_mm': pw['tol'], 'model_tolerance_mm': tau,
            'rrect_params': _rrect4_params(fams[best_prim]['q']) if 'm' not in fams[best_prim] else None}


def _describe_fillet_poly(q: np.ndarray, m: int) -> dict[str, Any]:
    """Lines (equation, tangent end points, length) and tangent arcs (centre, radius, sweep) of a filleted polygon, in plate (u, v) mm."""
    n, d, r, cen = _fillet_poly_geometry(q, m)
    lines, arcs = [], []
    for i in range(m):
        k = (i - 1) % m
        p0 = cen[k] + r[k] * n[i]                         # tangent point of the previous corner on line i
        p1 = cen[i] + r[i] * n[i]                         # tangent point of this corner on line i
        t = np.array([-n[i][1], n[i][0]])
        ln = float((p1 - p0) @ t)
        lines.append({'equation': '%.5f*u + %.5f*v = %.4f' % (n[i][0], n[i][1], d[i]), 'normal_uv': [round(float(v), 5) for v in n[i]], 'offset_mm': round(float(d[i]), 4),
                      'start_uv': [round(float(v), 4) for v in p0], 'end_uv': [round(float(v), 4) for v in p1], 'length_mm': round(max(ln, 0.0), 4),
                      'direction_deg': round(float(np.degrees(np.arctan2(t[1], t[0]))) % 360, 2), 'present': bool(ln > 1e-3)})
        j = (i + 1) % m
        sweep = float(np.degrees(np.arccos(np.clip(n[i] @ n[j], -1, 1))))
        arcs.append({'centre_uv': [round(float(v), 4) for v in cen[i]], 'radius_mm': round(float(r[i]), 4), 'sweep_deg': round(sweep, 2),
                     'from_uv': [round(float(v), 4) for v in cen[i] + r[i] * n[i]], 'to_uv': [round(float(v), 4) for v in cen[i] + r[i] * n[j]]})
    # where two arcs meet with no straight edge between them and share a centre, they form one round end (U / semicircle)
    return {'lines': lines, 'arcs': arcs, 'straight_edges': int(sum(1 for x in lines if x['present'])), 'arcs_count': m,
            'note': 'closed chain line_0, arc_0, line_1, arc_1, ...; arcs are tangent to both neighbouring lines; a line with present=false has zero length '
                    '(its two arcs meet, e.g. a round U end)'}


def find_sensor_window(P: np.ndarray, F: np.ndarray, fs: np.ndarray, farea: np.ndarray) -> dict[str, Any]:
    """Sensor window from mesh geometry alone (no pose prior, no fixed coordinates; length thresholds relative to the footprint length L):
    1. underside frame = largest flat face family at an extreme of the mesh; 2. height raster seen from below, robust plate plane;
    3. candidates = recesses deeper than max(6 sigma, REC_DEPTH_REL * L), enclosed by plate, area within AREA_REL * L^2;
    4. score = centrality on the footprint x depth x solidity x aspect x size; confidence from the score and its margin over the runner-up;
    5. rim = level crossings at RIM_LEVELS of the floor depth, superellipse fit (circle / ellipse / rounded rectangle);
       uncertainty = fit covariance (+) spread between the levels (+) a quarter pixel."""
    fr = underside_frame(P, F, fs, farea)
    if not fr['found']:
        return {'found': False, 'reason': 'no flat base face family found at an extreme of the mesh', 'candidates': []}
    U, L = fr['U'], fr['length']
    pix = L / RASTER_PER_LENGTH
    tri = U[F]
    down = (fs @ fr['R'][2]) < -0.05                      # faces seen from below
    u0, u1 = float(U[:, 0].min()) - 2 * pix, float(U[:, 0].max()) + 2 * pix
    v0, v1 = float(U[:, 1].min()) - 2 * pix, float(U[:, 1].max()) + 2 * pix
    nx, ny = int(np.ceil((u1 - u0) / pix)), int(np.ceil((v1 - v0) / pix))
    ib = _idbuf_pix(tri[:, :, :2], -tri[:, :, 2].mean(1), u0, v0, nx, ny, pix, down)   # the lowest surface wins
    ok = ib >= 0
    ii = np.nonzero(ok)
    fi = ib[ok]
    lam = sg._bary(tri[fi][:, :, :2], u0 + (ii[0] + .5) * pix, v0 + (ii[1] + .5) * pix)
    Z = np.full((nx, ny), np.nan)
    Z[ok] = (tri[fi][:, :, 2] * lam).sum(1)
    UU = u0 + (np.arange(nx)[:, None] + .5) * pix + np.zeros((1, ny))
    VV = v0 + (np.arange(ny)[None, :] + .5) * pix + np.zeros((nx, 1))
    plate_px = ok & fr['plate_faces'][np.maximum(ib, 0)]
    if plate_px.sum() < 100:
        return {'found': False, 'reason': 'the base face family is not visible from below', 'candidates': []}
    A = np.c_[UU[plate_px], VV[plate_px], np.ones(plate_px.sum())]
    zz = Z[plate_px]
    sub = max(1, len(zz) // 200000)
    A, zz = A[::sub], zz[::sub]
    co = np.zeros(3)
    for _ in range(8):
        co = np.linalg.lstsq(A, zz, rcond=None)[0]
        r = zz - A @ co
        k = np.abs(r) < max(2.5 * r.std(), 1e-4 * L)
        if k.sum() < 50:
            break
        A, zz = A[k], zz[k]
    H0 = Z - (co[0] * UU + co[1] * VV + co[2])           # height above the plate plane, + = recessed into the body
    # the base is rarely exactly planar (slight dome, skates): remove the slow plate shape by normalised Gaussian smoothing over plate-level pixels
    sg_px = BG_SIGMA_REL * L / pix
    w = plate_px.astype(float)
    Hz = np.nan_to_num(H0, nan=0.0)
    bg = np.zeros_like(Hz)
    sigma = float(np.sqrt(np.mean((zz - A @ co) ** 2)))
    for _ in range(4):
        num = ndi.gaussian_filter(Hz * w, sg_px, mode='constant')
        den = ndi.gaussian_filter(w, sg_px, mode='constant')
        bg = np.where(den > 1e-3, num / np.maximum(den, 1e-12), np.nan)
        res = H0 - bg
        rv = res[(w > 0) & np.isfinite(res)]
        if len(rv) < 100:
            break
        sigma = float(1.4826 * np.median(np.abs(rv - np.median(rv))))
        w = (ok & np.isfinite(res) & (np.abs(res) < max(3 * sigma, 1e-4 * L))).astype(float)
    H = H0 - bg                                           # local depth above the plate surface
    Hn = np.nan_to_num(H, nan=0.0)
    foot = ndi.binary_fill_holes(ndi.binary_closing(ok, iterations=3))
    inner = ndi.binary_erosion(foot, iterations=max(1, int(EDGE_MARGIN_REL * L / pix)))
    t_rec = max(6 * sigma, REC_DEPTH_REL * L)
    tol = max(4 * sigma, 0.25 * t_rec)
    m = ndi.binary_opening(ok & (Hn > t_rec), iterations=2)          # holes are filled per component (a ring of wall must not swallow the plate)
    lab, _ = ndi.label(m)
    fc = np.array([float(UU[foot].mean()), float(VV[foot].mean())])
    half = np.array([np.ptp(UU[foot]) / 2, np.ptp(VV[foot]) / 2])
    ring_w = max(2, int(0.01 * L / pix))
    cands = []
    for c, sl in enumerate(ndi.find_objects(lab), start=1):
        if sl is None:
            continue
        s = np.zeros_like(m)
        s[sl] = ndi.binary_fill_holes(lab[sl] == c)
        area = float(s.sum() * pix * pix)
        if not (AREA_REL[0] * L * L <= area <= AREA_REL[1] * L * L) or (s & ~inner).any():
            continue
        ringm = ndi.binary_dilation(s, iterations=ring_w) & ~s
        enclosed = float((ok[ringm] & (np.abs(Hn[ringm]) < tol)).mean()) if ringm.any() else 0.0
        if enclosed < 0.5:
            continue
        us, vs = UU[s], VV[s]
        cu, cv = float(us.mean()), float(vs.mean())
        evs = np.sqrt(np.maximum(np.linalg.eigvalsh(np.cov(np.c_[us, vs].T)), 1e-18))
        aspect = float(evs[1] / evs[0])
        try:
            from scipy.spatial import ConvexHull
            hull_px = float(ConvexHull(np.c_[us, vs]).volume) / (pix * pix)
        except Exception:
            hull_px = float(s.sum())
        solidity = float(min(1.0, s.sum() / max(hull_px, 1.0)))
        depth = float(np.median(Hn[s]))
        rr = float(np.hypot((cu - fc[0]) / half[0], (cv - fc[1]) / half[1]))
        eqd = 2 * np.sqrt(area / np.pi)
        rel = eqd / L
        cues = {'centrality': float(np.exp(-(rr / 0.35) ** 2)), 'depth': float(min(1.0, depth / (3 * REC_DEPTH_REL * L))),
                'solidity': float(np.clip((solidity - 0.6) / 0.3, 0, 1)), 'aspect': float(1.0 if aspect <= 2.0 else np.exp(-(aspect - 2.0))),
                'size': float(1.0 if 0.02 <= rel <= 0.12 else np.exp(-2 * abs(np.log(rel / (0.02 if rel < 0.02 else 0.12)))))}
        cands.append({'label': c, 'centroid_uv': [cu, cv], 'area': area, 'depth': depth, 'solidity': solidity, 'aspect': aspect, 'enclosed': enclosed,
                      'eq_diameter': eqd, 'centrality_r': rr, 'score': float(np.prod(list(cues.values()))), 'cues': {k: round(v, 3) for k, v in cues.items()}})
    cands.sort(key=lambda d: -d['score'])
    base = {'frame': fr, 'plane_uv': co, 'plate_rms': sigma, 'pix': pix, 'L': L, 'thresholds': {'recess_depth': t_rec, 'plate_tol': tol}, 'bg_grid': (bg, u0, v0)}
    if not cands:
        return {'found': False, 'reason': 'no enclosed recess deeper than %.3g (max of 6 sigma of the plate and %.3g x footprint length) on the underside' % (t_rec, REC_DEPTH_REL),
                'candidates': [], **base}
    best = cands[0]
    s = ndi.binary_fill_holes(lab == best['label'])
    rmax = 3.0 * best['eq_diameter'] / 2 + 4 * pix
    fits = []
    for frac in RIM_LEVELS:
        pts = _rim_points(Hn, pix, u0, v0, np.array(best['centroid_uv']), frac * best['depth'], rmax)
        if len(pts) >= 60:
            q, rms, sd = _superellipse_fit(pts)
            fits.append((frac, frac * best['depth'], pts, q, rms, sd))
    if not fits:
        return {'found': False, 'reason': 'the rim of the best recess could not be traced', 'candidates': cands, **base}
    frac, lvl, pts, q, rms, sd = fits[0]
    qe, rms_e, _ = _superellipse_fit(pts, 2.0)
    spread = np.array([f[3] for f in fits])
    sp_c = np.ptp(spread[:, :2], 0) / 2 if len(fits) > 1 else np.zeros(2)
    sp_ab = np.ptp(spread[:, 2:4], 0) / 2 if len(fits) > 1 else np.zeros(2)
    unc_c = np.sqrt(sd[:2] ** 2 + sp_c ** 2 + (pix / 4) ** 2)
    unc_ab = np.sqrt(sd[2:4] ** 2 + sp_ab ** 2 + (pix / 4) ** 2)
    inside = ndi.binary_erosion(s, iterations=max(1, int(0.15 * best['eq_diameter'] / pix)))
    floor = H[inside] if inside.sum() > 10 else H[s]
    d50, d25, d75 = (float(v) for v in np.nanpercentile(floor, [50, 25, 75]))
    shape = 'rounded_rectangle' if q[4] >= 2.4 else ('circle' if q[2] / q[3] < 1.08 else 'ellipse')
    second = cands[1]['score'] if len(cands) > 1 else 0.0
    if best['score'] >= 0.5 and best['score'] >= 2 * second and rms < 0.03 * best['eq_diameter']:
        conf = 'high'
    elif best['score'] >= 0.2 and best['score'] >= 1.3 * second:
        conf = 'medium'
    else:
        conf = 'low'
    # outline from the mesh itself (exact edge / plane crossings); the raster rim above stays as the fallback and as a cross-check
    bgf = np.where(np.isfinite(bg), bg, np.nan)
    if np.isnan(bgf).any():
        idx = ndi.distance_transform_edt(np.isnan(bgf), return_distances=False, return_indices=True)
        bgf = bgf[tuple(idx)]
    hv = U[:, 2] - (co[0] * U[:, 0] + co[1] * U[:, 1] + co[2]) - ndi.map_coordinates(bgf, [(U[:, 0] - u0) / pix - .5, (U[:, 1] - v0) / pix - .5], order=1, mode='nearest')
    try:
        outline = mesh_rim_outline(U, F, hv, np.array(q[:2]), float(q[2]), float(q[3]), d50)
    except Exception as exc:                              # never lose the raster result over a fit failure
        outline = {'found': False, 'reason': 'mesh rim fit failed: %s' % exc}
    return {'found': True, **base, 'best': best, 'candidates': cands, 'mask': s, 'rim_level': lvl, 'rim_level_fraction': frac, 'rim_points_uv': pts, 'outline': outline,
            'fit': q, 'fit_rms': rms, 'fit_sd': sd, 'ellipse_fit': qe, 'ellipse_rms': rms_e, 'unc_centre': unc_c, 'unc_semi': unc_ab,
            'levels': [(f[0], f[1], f[3], f[4]) for f in fits], 'shape': shape, 'depth': d50, 'depth_iqr': (d25, d75),
            'depth_max': float(np.nanmax(H[s])), 'confidence': conf}


def _se_outline(q: np.ndarray, n: int = 180) -> np.ndarray:
    cx, cy, a, b, nn, th = q
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    c, s = np.cos(t), np.sin(t)
    u = a * np.sign(c) * np.abs(c) ** (2 / nn)
    v = b * np.sign(s) * np.abs(s) ** (2 / nn)
    return np.c_[cx + u * np.cos(th) - v * np.sin(th), cy + u * np.sin(th) + v * np.cos(th)]


def _cand_json(r: dict[str, Any], to_work=None) -> list[dict[str, Any]]:
    out = []
    for c in (r.get('candidates') or [])[:6]:
        d = {'score': round(float(c['score']), 3), 'area_mm2': round(c['area'], 2), 'depth_mm': round(c['depth'], 2), 'equivalent_diameter_mm': round(c['eq_diameter'], 2),
             'solidity': round(c['solidity'], 3), 'aspect': round(c['aspect'], 2), 'centrality_r': round(c['centrality_r'], 3), 'cues': c['cues']}
        if to_work is not None:
            w = to_work(np.array(c['centroid_uv']))[0]
            d['centroid_mm'] = {'x': round(float(w[0]), 2), 'y': round(float(w[1]), 2)}
        out.append(d)
    return out


def _outline_json(o: dict[str, Any], to_work) -> dict[str, Any]:
    """Mesh-rim outline for the report: chosen family, primitives (lines + tangent arcs) and residuals; points in the work frame (x, y mm)."""
    if not o.get('found'):
        return {'found': False, 'reason': o.get('reason', 'mesh rim outline not computed')}
    xy = lambda uv: [round(float(v), 4) for v in to_work(np.asarray(uv, float)[None])[0][:2]]
    prim = o['primitive']
    lines = [{'present': l['present'], 'length_mm': l['length_mm'], 'start_xy': xy(l['start_uv']), 'end_xy': xy(l['end_uv']),
              'equation_plate_uv': l['equation']} for l in prim['lines']]
    arcs = [{'centre_xy': xy(a['centre_uv']), 'radius_mm': a['radius_mm'], 'sweep_deg': a['sweep_deg'], 'from_xy': xy(a['from_uv']), 'to_xy': xy(a['to_uv'])}
            for a in prim['arcs']]
    poly = to_work(np.asarray(o['outline'], float))
    piece = o['final_model'] == 'lines_and_arcs'
    return {'found': True, '_polyline_work': poly,
            'family': o['final_model'], 'best_primitive_family': o['best_primitive_family'],
            'fallback_polyline': bool(piece),
            'level_mm': round(float(o['level_mm']), 3), 'level_fraction_of_depth': round(float(o['level_fraction']), 2),
            'raw_edge_points': int(len(o['raw_points'])), 'outliers_rejected': int(o['outliers_rejected']),
            'residuals_mm': o['final_residuals'], 'residuals_inliers_mm': o['final_residuals_inliers'], 'inlier_fraction': o['inlier_fraction'],
            'noise_floor_mm': round(float(o['noise_sigma_mm']), 4), 'model_tolerance_mm': round(float(o['model_tolerance_mm']), 4),
            'primitive': {'lines': lines, 'arcs': arcs, 'straight_edges': prim['straight_edges'],
                          'major_axis_angle_to_x_deg': round(float((np.degrees(np.arctan2(*np.linalg.eigh(np.cov(poly[:, :2].T))[1][:, -1][::-1])) + 90) % 180 - 90), 2),
                          'note': 'closed chain line_0, arc_0, line_1, arc_1, ...; every arc is tangent to its two lines; a line with present=false has zero length '
                                  '(two arcs meet). A sharp corner is an arc of radius ~0; mesh edge length limits how sharp a corner can be resolved.'},
            'families': o['families'], 'stability': o['stability'],
            'polyline_points': int(len(poly)),
            'method': 'exact crossings of mesh edges with planes parallel to the local plate at the shallowest clean rim level; robust (soft-L1) fits of '
                      'line + tangent-arc families and a generic piecewise lines/arcs polyline; chosen by n*log(max(rms, tol)^2) + k*log(n)'}


def sensor_window(M: Any, ft: dict[str, Any]) -> dict[str, Any]:
    """Sensor window of the mesh (geometry only), expressed in the coordinates of M.P (the work frame)."""
    r = find_sensor_window(M.P, M.F, ft['fs'], M.farea)
    if not r['found']:
        return {'found': False, 'reason': r['reason'], 'candidates': _cand_json(r)}
    Rm, o = r['frame']['R'], r['frame']['o']
    a_, b_, c_ = r['plane_uv']

    def to_work(uv: np.ndarray) -> np.ndarray:            # point on the plate plane (u, v) -> work frame
        uv = np.atleast_2d(uv)
        w = a_ * uv[:, 0] + b_ * uv[:, 1] + c_
        return o + uv[:, 0:1] * Rm[0] + uv[:, 1:2] * Rm[1] + w[:, None] * Rm[2]
    q = r['fit']
    cw = to_work(q[:2])[0]
    outl = to_work(_se_outline(q))
    n_w = Rm[2] - a_ * Rm[0] - b_ * Rm[1]
    n_w /= np.linalg.norm(n_w)
    p0 = to_work(np.zeros((1, 2)))[0]
    abc = [float(-n_w[0] / n_w[2]), float(-n_w[1] / n_w[2]), float(p0[2] + (n_w[0] * p0[0] + n_w[1] * p0[1]) / n_w[2])] if abs(n_w[2]) > 1e-6 else [0.0, 0.0, float(p0[2])]
    cent_w = to_work(np.array(r['best']['centroid_uv']))[0]
    major = Rm[0] * np.cos(q[5]) + Rm[1] * np.sin(q[5])
    ang = (float(np.degrees(np.arctan2(major[1], major[0]))) + 90.0) % 180.0 - 90.0
    mo = _outline_json(r.get('outline') or {}, to_work)
    if mo['found']:                                       # the mesh-rim outline is the primary answer; the raster superellipse stays as cross-check
        poly_w = np.asarray(mo.pop('_polyline_work'))
        cw = to_work(np.asarray(r['outline']['centroid'])[None])[0]
        outl = poly_w
    return {'found': True, 'mask': r['mask'], 'centre_xy': [float(cw[0]), float(cw[1])], 'centroid_xy': [float(cent_w[0]), float(cent_w[1])], 'mesh_outline': mo,
            'raster_centre_xy': [float(v) for v in to_work(q[:2])[0][:2]],
            'size_xy': [float(np.ptp(outl[:, 0])), float(np.ptp(outl[:, 1]))], 'area_mm2': float(r['best']['area']), 'depth_mm': r['depth'], 'depth_max_mm': r['depth_max'],
            'depth_iqr': r['depth_iqr'], 'plate_plane': abc, 'plate_surface_z_at_centre': float(cw[2]), 'outline_xy': outl[:, :2], 'rim_xy': to_work(r['rim_points_uv'])[:, :2],
            'plane_fit_rms_mm': r['plate_rms'], 'fit': q, 'fit_rms': r['fit_rms'], 'ellipse_fit': r['ellipse_fit'], 'ellipse_rms': r['ellipse_rms'],
            'unc_centre': r['unc_centre'], 'unc_semi': r['unc_semi'], 'shape': r['shape'], 'major_axis_angle_to_x_deg': ang,
            'confidence': r['confidence'], 'levels': r['levels'], 'rim_level': r['rim_level'], 'rim_level_fraction': r['rim_level_fraction'], 'pix': r['pix'], 'L': r['L'],
            'thresholds': r['thresholds'], 'underside_normal_work': [float(v) for v in -n_w], 'candidates': _cand_json(r, to_work)}


# ------------------------------------------------------------------ overlay png (owner check of the split)
OVERLAY_COLOURS = {'bottom_plate': (120, 200, 235), 'top_shell': (245, 222, 120), 'functional': (165, 165, 165)}
SEAM_COLOURS = {'supported': (0, 95, 120), 'inferred': (235, 110, 20)}


def shell_overlays(M: Any, face_codes: np.ndarray, seam: dict[str, Any], out: Path, mirrored: bool) -> list[dict[str, Any]]:
    """Orthographic overlays: both flanks and the underside. Bottom plate light blue, top shell light yellow, functional faces grey; the seam
    is drawn solid where a crease / groove supports it and dashed where it is inferred (only where its outer wall faces the viewer)."""
    from PIL import Image, ImageDraw, ImageFont
    ss, ppm = 2, 7.0
    light = np.array([-0.4, 0.5, 0.75])
    light /= np.linalg.norm(light)
    col = np.zeros((len(face_codes), 3))
    col[face_codes == LABEL_CODES['bottom_plate']] = OVERLAY_COLOURS['bottom_plate']
    col[face_codes == LABEL_CODES['top_shell']] = OVERLAY_COLOURS['top_shell']
    col[face_codes == LABEL_CODES['other']] = OVERLAY_COLOURS['functional']
    c0, ang, tan = seam['c0'], seam['ang'], seam['tan']
    n3 = np.c_[tan[:, 1] * np.cos(ang), tan[:, 1] * np.sin(ang), -tan[:, 0]]       # outward wall normal at the seam
    views = {'side_pos_y': (np.array([-1.0, 0, 0]), np.array([0, 0, 1.0]), np.array([0, 1.0, 0]), 'flank +y (mouse-left), front left'),
             'side_neg_y': (np.array([1.0, 0, 0]), np.array([0, 0, 1.0]), np.array([0, -1.0, 0]), 'flank -y (mouse-right), front right'),
             'bottom': (np.array([1.0, 0, 0]), np.array([0, -1.0, 0]), np.array([0, 0, -1.0]), 'underside, front right, +y down')}
    result = []
    for view, (r, u, t, _) in views.items():
        pr = np.stack([M.P @ r, M.P @ u, M.P @ t], -1)
        lo, hi = pr[:, :2].min(0) - 4, pr[:, :2].max(0) + 4
        wpx, hpx = int((hi[0] - lo[0]) * ppm * ss), int((hi[1] - lo[1]) * ppm * ss) + 40 * ss
        img = Image.new('RGB', (wpx, hpx), (252, 252, 252))
        dr = ImageDraw.Draw(img)
        trp = pr[M.F]
        ft_ = M.fn @ t
        ii = np.flatnonzero(ft_ > 0.0)
        ii = ii[np.argsort(trp[ii, :, 2].mean(1))]
        shade = np.clip(0.45 + 0.25 * np.abs(ft_) + 0.35 * np.clip(M.fn @ (light[0] * r + light[1] * u + light[2] * t), 0, 1), 0, 1)
        rgb = np.clip(col * shade[:, None], 0, 255).astype(int)
        px = (trp[:, :, :2] - lo) * ppm * ss
        px[:, :, 1] = hpx - px[:, :, 1]
        for i in ii:
            dr.polygon([tuple(p) for p in px[i]], fill=tuple(rgb[i]))
        q = np.stack([seam['pts'] @ r, seam['pts'] @ u], -1)
        sx = (q[:, 0] - lo[0]) * ppm * ss
        sy = hpx - (q[:, 1] - lo[1]) * ppm * ss
        vis = (n3 @ t) > (0.05 if view != 'bottom' else -0.35)
        nn = len(sx)
        dash = 0
        for j in range(nn):
            k = (j + 1) % nn
            if not (vis[j] and vis[k]):
                continue
            if seam['supported'][j] and seam['supported'][k]:
                dr.line([(sx[j], sy[j]), (sx[k], sy[k])], fill=SEAM_COLOURS['supported'], width=3 * ss)
            else:
                dash += 1
                if (dash // 3) % 2 == 0:
                    dr.line([(sx[j], sy[j]), (sx[k], sy[k])], fill=SEAM_COLOURS['inferred'], width=3 * ss)
        img = img.resize((wpx // ss, hpx // ss), Image.LANCZOS)
        d2 = ImageDraw.Draw(img)
        try:
            font = ImageFont.load_default(size=13)
        except TypeError:
            font = ImageFont.load_default()
        d2.text((8, 6), views[view][3] + ('  [mirrored model]' if mirrored else ''), fill=(30, 30, 30), font=font)
        x0 = 8
        for name, cc in (('bottom plate', OVERLAY_COLOURS['bottom_plate']), ('top shell', OVERLAY_COLOURS['top_shell']), ('functional (click / wheel / side)', OVERLAY_COLOURS['functional'])):
            d2.rectangle([x0, 24, x0 + 14, 36], fill=cc, outline=(60, 60, 60))
            d2.text((x0 + 18, 23), name, fill=(30, 30, 30), font=font)
            x0 += 30 + 7 * len(name)
        d2.line([(x0, 30), (x0 + 22, 30)], fill=SEAM_COLOURS['supported'], width=3)
        d2.text((x0 + 26, 23), 'seam: crease / groove', fill=(30, 30, 30), font=font)
        x0 += 26 + 7 * 21 + 10
        d2.line([(x0, 30), (x0 + 6, 30)], fill=SEAM_COLOURS['inferred'], width=3)
        d2.line([(x0 + 12, 30), (x0 + 18, 30)], fill=SEAM_COLOURS['inferred'], width=3)
        d2.text((x0 + 24, 23), 'seam: inferred', fill=(30, 30, 30), font=font)
        bar = int(10 * ppm)
        d2.line([(img.width - 16 - bar, img.height - 14), (img.width - 16, img.height - 14)], fill=(0, 0, 0), width=1)
        d2.text((img.width - 16 - bar, img.height - 30), '10 mm', fill=(0, 0, 0), font=font)
        name = f'overlay_{view}.png'
        img.save(out / name)
        result.append({'file': name, 'sha256': file_hash(out / name), 'view': view})
    return result


def _not_ready(scan_id: str, reasons: list[str], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {'schema': 'scan_shell_report/1', 'scan_id': scan_id, 'status': 'NOT_READY', 'blocking_reasons': reasons, 'surface_only': True, 'limitations': LIMITS,
            **(extra or {}), 'execution': {'completed': True}}


def recognize_shell(workspace: Path, scan_id: str, handedness: str = 'auto') -> dict[str, Any]:
    scan_id = safe_id(scan_id)
    t0 = time.time()
    reg = sr.recognize_regions(workspace, scan_id, handedness, overlay=False)
    if reg.get('status') != 'READY':
        return _not_ready(scan_id, ['REGIONS_NOT_READY'] + list(reg.get('blocking_reasons') or []), {'regions_run': reg.get('run_id')})
    d, prep = scan_shell.load_prepared(workspace, scan_id)
    v, f = scan_shell.load_prepared_mesh(d)
    run_id = 'shl_' + digest({'regions': reg['run_id'], 'version': SHELL_VERSION})[:12]
    out = d / 'shell' / run_id
    if (out / 'shell_report.json').is_file():
        return _stored(out)
    mirrored = bool(reg['handedness']['mirrored_for_detection'])
    fr = sr.canonical_frame(v, f)
    q = sr.canonical_coords(v, fr)
    M = sr._Mesh(sr.working_coords(q, mirrored), np.ascontiguousarray(f[:, [0, 2, 1]]) if mirrored else f)
    codes = np.load(d / 'regions' / reg['run_id'] / 'face_labels.npz')['face_labels']
    buttons = (codes >= 1) & (codes <= 5)
    ft = sg.surface_features(M.P, M.F, M.L, M.vn, M.fn)
    seam = seam_loop(M, ft)
    bottom, top, cls_info = classify(M, ft, seam, buttons)       # the split itself is geometry only; buttons only carve the children
    islands = cls_info.pop('islands')
    sup = seam['supported']
    tot = float(seam['seglen'].sum())
    frac_sup = float(seam['seglen'][sup].sum() / tot)
    segments = []
    for r in _runs(sup):
        e, cnt = np.unique(seam['evidence'][r], return_counts=True)
        sc = float(np.mean(seam['score'][r]))
        segments.append({'support': 'groove' if sup[r[0]] else 'inferred', 'azimuth_from_deg': round(float(seam['az'][r[0]]), 2), 'azimuth_to_deg': round(float(seam['az'][r[-1]]), 2),
                         'length_mm': round(float(seam['seglen'][r].sum()), 1), 'sections': int(len(r)),
                         'evidence': {str(k): int(v) for k, v in zip(e, cnt)}, 'mean_cue_score': round(sc, 2),
                         'confidence': ('high' if sc >= 6 else 'medium') if sup[r[0]] else ('medium' if len(r) <= 2 * MIN_RUN else 'low')})
    hgt = seam['z'] - seam['zl']
    deg_per_col = 360.0 / SEAM_COLS
    step_h = float(np.max(np.abs(np.diff(np.r_[hgt, hgt[:1]])))) / deg_per_col
    step_z = float(np.max(np.abs(np.diff(np.r_[seam['z'], seam['z'][:1]])))) / deg_per_col
    closed = np.vstack([seam['pts'], seam['pts'][:1]])
    area = M.farea
    comp_b = _components(M.F, bottom)
    comp_t = _components(M.F, top)
    comp_tf = _components(M.F, top | buttons)
    sens = sensor_window(M, ft)
    blockers: list[str] = []
    warnings: list[dict[str, Any]] = []
    if frac_sup < 0.5:
        warnings.append({'code': 'SEAM_MOSTLY_INFERRED', 'supported_fraction': round(frac_sup, 2), 'note': 'less than half of the seam loop shows a crease or groove; treat the plate / shell split as indicative'})
    if comp_b[2] != 1 or comp_tf[2] != 1:
        warnings.append({'code': 'SHELL_SPLIT_FRAGMENTED', 'bottom_plate_components': int(comp_b[2]), 'top_shell_with_functional_components': int(comp_tf[2])})
    if not sens['found']:
        warnings.append({'code': 'SENSOR_NOT_FOUND', 'note': sens['reason']})
    elif sens['confidence'] == 'low':
        warnings.append({'code': 'SENSOR_AMBIGUOUS', 'note': 'the best recess candidate is weak or not clearly ahead of the runner-up; see sensor.candidates'})
    unassigned = np.flatnonzero(bottom & buttons)
    unassigned_clusters = list(islands)
    if len(unassigned):
        ui, ul, un = _components(M.F, bottom & buttons)
        for k in range(un):
            ff = ui[ul == k]
            unassigned_clusters.append({'faces': int(len(ff)), 'area_mm2': round(float(area[ff].sum()), 2), 'centre_mm': [round(float(c), 1) for c in M.cen[ff].mean(0)],
                                        'moved_to': None, 'reason': 'functional label inside the bottom plate'})
    bottom_part = bottom & ~buttons
    face_codes = np.where(bottom_part, LABEL_CODES['bottom_plate'], np.where(top, LABEL_CODES['top_shell'], 0)).astype(np.uint8)
    seam_conf = 'high' if frac_sup >= 0.85 else ('medium' if frac_sup >= 0.6 else 'low')
    children: dict[str, Any] = {'body': {'face_count': int(top.sum()), 'area_mm2': round(float(area[top].sum()), 1), 'confidence': seam_conf,
                                         'definition': 'remainder of the top shell parent after the functional children'}}
    for name, cd in sr.LABEL_CODES.items():
        if 1 <= cd <= 5:
            sel = (codes == cd) & ~bottom
            children[name] = {'face_count': int(sel.sum()), 'area_mm2': round(float(area[sel].sum()), 1),
                              'confidence': (reg.get('regions', {}).get(name) or {}).get('confidence'), 'source': 'brain_mouse_recognize_regions ' + reg['run_id']}
    parent = ~bottom
    parts_tree = {'mouse': {'face_count': int(len(f)), 'area_mm2': round(float(area.sum()), 1), 'children': {
        'bottom_plate': {'face_count': int(bottom_part.sum()), 'area_mm2': round(float(area[bottom_part].sum()), 1), 'components': int(comp_b[2]), 'confidence': seam_conf},
        'top_shell': {'face_count': int(parent.sum()), 'area_mm2': round(float(area[parent].sum()), 1), 'components': int(_components(M.F, parent)[2]),
                      'confidence': seam_conf, 'children': children}}},
        'order': 'bottom_plate vs top_shell first (parting seam, geometry only, independent of the region step); the top shell children come from the '
                 'region step (run on the whole mesh, unchanged) restricted to the top shell parent',
        'unassigned_faces': int(len(unassigned))}
    ext = np.array([(M.P[:, 0].min(), M.P[:, 0].max()), (M.P[:, 1].min(), M.P[:, 1].max())])
    sensor: dict[str, Any] = {'found': bool(sens['found'])}
    if sens['found']:
        cx, cy = sens['centre_xy']
        wp = np.array([cx, cy, sens['plate_surface_z_at_centre']])
        cq = (wp - sr.T_PRIOR) @ sr.R_PRIOR                                  # work frame -> canonical frame (inverse rotation)
        if mirrored:
            cq = cq * np.array([1.0, -1.0, 1.0])
        sensor.update({
            'centre_mm': {'x': round(cx, 2), 'y': round(cy, 2)}, 'centre_frame': 'work frame: x front, y mouse-left (thumb side), z up, mm (the frame of the region outlines; PCA frame of the reference scan)',
            'centre_centroid_mm': {'x': round(sens['centroid_xy'][0], 2), 'y': round(sens['centroid_xy'][1], 2)},
            'centre_canonical_mm': {'x': round(float(cq[0]), 2), 'y': round(float(cq[1]), 2), 'frame': 'canonical: x from rear end, y from mid-line, z above base'},
            'window_size_mm': {'along_x': round(sens['size_xy'][0], 2), 'along_y': round(sens['size_xy'][1], 2), 'area_mm2': round(sens['area_mm2'], 1),
                               'equivalent_diameter_mm': round(2 * float(np.sqrt(sens['area_mm2'] / np.pi)), 2)},
            'depth_mm': round(sens['depth_mm'], 2), 'depth_max_mm': round(sens['depth_max_mm'], 2), 'depth_definition': 'median depth of the aperture floor (inner 70 %) above the local plate surface',
            'plate_plane_z_eq': 'z = a*x + b*y + c', 'plate_plane_abc': [round(c, 5) for c in sens['plate_plane']],
            'distance_from_rear_mm': round(cx - float(ext[0, 0]), 1), 'distance_from_thumb_side_mm': round(float(ext[1, 1]) - cy, 1),
            'confidence': sens['confidence'],
            'note': 'Aperture seen from below, mesh geometry only (no pose prior, no PCB, no texture). The outline is the rim where the depth crosses '
                    '%d %% of the floor depth; the chip and lens behind it are not visible.' % round(100 * sens['rim_level_fraction']),
            'aperture': {
                'shape': sens['shape'], 'centre_mm': {'x': round(cx, 3), 'y': round(cy, 3)},
                'major_mm': round(2 * float(sens['fit'][2]), 3), 'minor_mm': round(2 * float(sens['fit'][3]), 3),
                'superellipse_exponent': round(float(sens['fit'][4]), 2), 'major_axis_angle_to_x_deg': round(sens['major_axis_angle_to_x_deg'], 1),
                'fit_rms_mm': round(sens['fit_rms'], 3), 'rim_level_mm': round(sens['rim_level'], 3),
                'ellipse_fit': {'major_mm': round(2 * float(sens['ellipse_fit'][2]), 3), 'minor_mm': round(2 * float(sens['ellipse_fit'][3]), 3), 'rms_mm': round(sens['ellipse_rms'], 3)},
                'level_sweep': [{'level_fraction': f, 'level_mm': round(float(lv), 3), 'centre_plate_uv_mm': [round(float(q[0]), 3), round(float(q[1]), 3)],
                                 'major_mm': round(2 * float(q[2]), 3), 'minor_mm': round(2 * float(q[3]), 3), 'rms_mm': round(float(rm), 3)} for f, lv, q, rm in sens['levels']],
                'definition': 'superellipse |u/a|^n + |v/b|^n = 1 fitted to sub-pixel rim points (n ~2 ellipse, n >= 2.4 rounded rectangle); sizes in the plate plane'},
            'uncertainty_mm': {'centre_major_axis': round(float(sens['unc_centre'][0]), 3), 'centre_minor_axis': round(float(sens['unc_centre'][1]), 3),
                               'major': round(2 * float(sens['unc_semi'][0]), 3), 'minor': round(2 * float(sens['unc_semi'][1]), 3),
                               'depth_iqr_half': round((sens['depth_iqr'][1] - sens['depth_iqr'][0]) / 2, 3),
                               'definition': '1 sigma: fit covariance (+) half-spread over the rim levels (+) a quarter raster pixel; centre terms along the plate u / v axes. '
                                             'Mesh accuracy of the scan itself is not included.'},
            'depth_iqr_mm': [round(sens['depth_iqr'][0], 2), round(sens['depth_iqr'][1], 2)],
            'underside': {'normal_work': [round(v, 4) for v in sens['underside_normal_work']], 'plate_rms_mm': round(sens['plane_fit_rms_mm'], 3),
                          'tilt_to_work_z_deg': round(float(np.degrees(np.arccos(min(1.0, abs(sens['underside_normal_work'][2]))))), 2),
                          'raster_pixel_mm': round(sens['pix'], 4), 'footprint_length_mm': round(sens['L'], 1),
                          'thresholds_mm': {k: round(float(v), 3) for k, v in sens['thresholds'].items()}},
            'outline': sens['mesh_outline'],
            'raster_centre_mm': {'x': round(sens['raster_centre_xy'][0], 3), 'y': round(sens['raster_centre_xy'][1], 3)},
            'candidates': sens['candidates'],
            'evidence': {'geometry': True, 'texture': False, 'pcb': False},
            'pcb_cross_check': {'performed': False, 'reason': 'The tool decides from the mesh alone; a PCB / STEP is never an input. Compare offline: the aperture centre '
                                'is the window, not necessarily the optical axis (a concentric recess round the window is a better optical-axis cue when present).'},
            'method': 'largest flat face family at an extreme of the mesh = base; height raster from below minus the slow plate shape; enclosed recesses scored by '
                      'centrality x depth x solidity x aspect x size (all relative to the footprint length); outline from exact mesh-edge rim crossings fitted '
                      'with line + tangent-arc families (see outline); the raster superellipse (aperture) is kept as a cross-check'})
    else:
        sensor['reason'] = sens['reason']
        sensor['candidates'] = sens.get('candidates', [])
    out.mkdir(parents=True, exist_ok=False)
    npz = out / 'face_labels.npz'
    with npz.open('wb') as fh:
        np.savez_compressed(fh, face_labels=face_codes, codes=np.array([f'{k}={c}' for k, c in LABEL_CODES.items()]))
    arrs: dict[str, Any] = {'seam_xyz': seam['pts'], 'seam_supported': sup, 'seam_xyz_closed': closed, 'seam_azimuth_deg': seam['az'],
                            'seam_lower_edge_z': seam['zl'], 'seam_cue_score': seam['score'], 'seam_evidence': seam['evidence'].astype('U16')}
    if sens['found']:
        arrs['sensor_outline_xy'] = sens['outline_xy']
        arrs['sensor_rim_xy'] = sens['rim_xy']
    with (out / 'outlines.npz').open('wb') as fh:
        np.savez_compressed(fh, **arrs)
    overlays = None
    try:
        overlays = shell_overlays(M, face_codes, seam, out, mirrored)
    except ImportError:
        warnings.append({'code': 'OVERLAY_SKIPPED', 'note': 'Pillow is not installed (geometry extra).'})
    report = {
        'schema': 'scan_shell_report/1', 'run_id': run_id, 'scan_id': scan_id, 'status': 'NOT_READY' if blockers else 'READY', 'blocking_reasons': blockers, 'warnings': warnings,
        'code_version': {'scan_shell': SHELL_VERSION, 'package': __version__}, 'settings': {'handedness': handedness}, 'regions_run': reg['run_id'],
        'scan': {'prepared_npz_sha256': prep['prepared_npz_sha256'], 'faces': int(len(f))}, 'surface_only': True, 'limitations': LIMITS,
        'regions': {'bottom_plate': {'face_count': int(bottom.sum()), 'area_mm2': round(float(area[bottom].sum()), 1), 'components': int(comp_b[2]),
                                     'definition': 'outer skirt below the parting seam plus the whole underside (feet, label area, screw bosses, sensor pocket): '
                                                   'one edge-connected region'},
                    'top_shell': {'face_count': int(top.sum()), 'area_mm2': round(float(area[top].sum()), 1), 'components': int(comp_t[2]),
                                  'components_with_functional_faces': int(comp_tf[2]),
                                  'definition': 'everything above the seam except the left / right click, wheel and side-button faces of the region step '
                                                '(those cut the top shell apart; top shell + functional faces is one edge-connected region)'},
                    'excluded_functional_faces': int(buttons.sum()),
                    'split_checks': {**cls_info, 'definition': 'counts of faces violating the split rules (0 = clean) and of island faces moved by the connectivity clean-up'},
                    'unassigned_faces': {'face_count': int(len(unassigned)), 'area_mm2': round(float(area[unassigned].sum()), 2), 'clusters': unassigned_clusters,
                                         'definition': 'functional faces of the region step lying inside the bottom plate (conflicts, left in no part: label code 0); '
                                                       'detached islands moved by the connectivity clean-up are listed in clusters with moved_to'}},
        'parts_tree': parts_tree,
        'seam': {'frame': 'work frame (x front, y thumb side, z up, mm)', 'length_mm': round(tot, 1), 'bins': SEAM_COLS, 'supported_fraction': round(frac_sup, 2),
                 'segments': segments, 'closed_loop': True,
                 'closure_gap_mm': round(float(np.linalg.norm(closed[0] - closed[-1])), 3),
                 'max_point_spacing_mm': round(float(seam['seglen'].max()), 3),
                 'height_above_wall_lower_edge_mm': {'min': round(float(np.min(hgt)), 2), 'median': round(float(np.median(hgt)), 2), 'max': round(float(np.max(hgt)), 2)},
                 'max_step_per_degree_mm': {'height_above_lower_edge': round(step_h, 3), 'z': round(step_z, 3)},
                 'sections_through_scan_holes': int((~seam['valid']).sum()),
                 'cue_scales': {k: round(float(v), 5) for k, v in seam['scales'].items()},
                 'method': 'exact vertical sections every %.1f degrees round the footprint; per section the outer wall from its lower edge up 13 mm; cue = convex '
                           'crease (profile curvature) + groove (band-pass normal offset), gated against the plate fillet; circular Viterbi with a height '
                           'smoothness prior and a robust 3-harmonic prior on the offset above the lower edge; weak sections are inferred (prior shape '
                           'between the supported ends)' % deg_per_col,
                 'confidence': 'high' if frac_sup >= 0.85 else ('medium' if frac_sup >= 0.6 else 'low')},
        'sensor': sensor, 'files': {'face_labels': {'file': 'face_labels.npz', 'sha256': file_hash(npz), 'faces': int(len(f)), 'codes': LABEL_CODES},
                                    'outlines': {'file': 'outlines.npz', 'sha256': file_hash(out / 'outlines.npz'), 'note': 'seam_xyz (%d x 3, work frame, one point per section), seam_xyz_closed (first point repeated), seam_supported, seam_azimuth_deg, '
                                             'seam_lower_edge_z, seam_cue_score, seam_evidence, sensor_outline_xy (fitted aperture), sensor_rim_xy (traced rim points)' % SEAM_COLS}},
        'seconds': round(time.time() - t0, 1), 'checks': {'regions_ready': 'PASS', 'seam_closed_loop': 'PASS', 'physical_function': 'UNVERIFIED'}, 'execution': {'completed': True}}
    if overlays:
        report['files']['overlays'] = overlays
    atomic_json(out / 'shell_report.json', report)
    return report


def _stored(out: Path) -> dict[str, Any]:
    rep = json_load(out / 'shell_report.json')
    items = [v for k, v in rep['files'].items() if k != 'overlays'] + list(rep['files'].get('overlays') or [])
    for it in items:
        p = out / it['file']
        if not p.is_file() or file_hash(p) != it['sha256']:
            raise BrainError('SHELL_OUTPUT_CHANGED', 'A stored shell result no longer matches its recorded hash; it is not overwritten.', {'file': it['file']})
    return {**rep, 'cached': True}
