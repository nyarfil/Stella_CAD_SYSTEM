"""Scan groove re-synthesis and zone repair. SUBPROCESS WORKER, never imported by the server.

Run as:  <scan python> scan_clean_worker.py request.json
Same contract as scan_model_worker.py: JSON request, JSON result on the last stdout line, numpy / scipy plus PyMeshLab (GPL-3.0)
in a separate virtualenv; pymeshlab is imported lazily and only for distance / self-intersection measurements.
The numpy-only model code (Curve, profile fit, Unit, subdivide_sel, zone_repair) is importable without pymeshlab for the tests.

mode 'grooves'. A groove is a 3D B-spline centre line (open or closed) with a piecewise-constant profile along it:
  per station a left skin (quadratic), a trapezoid cut (wall, flat floor, wall) and a right skin (quadratic), in the curve frame
  (s along the curve, u across it in the surface, h along the surface normal). The profile is fitted to dense face samples of the mesh,
  the centre line is re-centred on the fitted groove (up to 6 times), a dynamic programme groups stations into constant-profile segments
  (steps are explicit), faces round the groove are subdivided (2 levels, conforming) and the vertices are moved ALONG THE SURFACE NORMAL to
  the model profile. Nothing outside the blend window moves. Stations that fail the fit or are shallower than 0.05 mm are left original.
mode 'zones'. Topology-preserving fill: every vertex of the zone is projected onto a local moving-least-squares quadric fitted to the
  vertices around the zone (not to the zone itself), tapered to zero over three edges at the zone border, and the displacement is capped.
"""
from __future__ import annotations
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spl
from scipy.interpolate import splev, splprep
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import least_squares
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))     # the worker runs with -I; the numpy-only topology helpers live next to it
from scan_model_worker import read_stl_topology, topology    # noqa: E402

WORKER_VERSION = 'scan_clean/2'
LAMBDA_OPEN, LAMBDA_LOOP = 30.0, 12.0      # segmentation penalty (larger = fewer steps)
DF_MIN = 0.05                               # a groove shallower than this (mm) is "absent": left original
SKIN_HALF_WIDTH = {'open': 0.9, 'loop': 1.4}
SUBDIVISION_LEVELS = 2
OUTSIDE_MARGIN_MM = 0.6
SAMPLE_DENSITY = 300.0                      # face samples per mm^2 near a groove
INTENT_EXTEND_MM = 1.0                      # design intent: the clean groove continues this far past the last trusted station
INTENT_KNOT_MM = (6.0, 9.0, 14.0, 20.0)     # centre-line spline knot spacings tried in turn until the curvature limit holds
INTENT_MAX_CURVATURE = 0.2                  # 1/mm (radius >= 5 mm) for the smoothed centre line
INTENT_STRAIGHT_P95_MM = 0.2                # auto 'straight': 95th percentile of the in-plan scatter of the fitted centres
INTENT_STRAIGHT_MAX_LEN_MM = 25.0
INTENT_AGREE_DEPTH_MM, INTENT_AGREE_WIDTH_MM, INTENT_AGREE_CENTRE_MM = 0.06, 0.2, 0.08


# ------------------------------------------------------------------ mesh helpers
def vnormals(v: np.ndarray, f: np.ndarray) -> np.ndarray:
    t = v[f]
    c = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    vn = np.zeros_like(v)
    for k in range(3):
        np.add.at(vn, f[:, k], c)
    return vn / np.maximum(np.linalg.norm(vn, axis=1), 1e-20)[:, None]


def fnormals(v: np.ndarray, f: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    t = v[f]
    c = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    a = np.linalg.norm(c, axis=1)
    return c / np.maximum(a, 1e-20)[:, None], a / 2


def sample_faces(v: np.ndarray, f: np.ndarray, fsel: np.ndarray, dens: float = 60.0, seed: int = 1, minimum: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = v[f[fsel]]
    ar = 0.5 * np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1)
    k = np.maximum(minimum, np.round(ar * dens)).astype(int)
    fi = np.repeat(np.arange(len(t)), k)
    r = rng.random((len(fi), 2))
    m = r.sum(1) > 1
    r[m] = 1 - r[m]
    return t[fi, 0] + r[:, :1] * (t[fi, 1] - t[fi, 0]) + r[:, 1:] * (t[fi, 2] - t[fi, 0])


def adjacency(f: np.ndarray, nv: int) -> sp.csr_matrix:
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    a = sp.coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(nv, nv))
    a = ((a + a.T) > 0).astype(float).tocsr()
    return a


def smoothstep(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


# ------------------------------------------------------------------ skin (fill from surroundings), used for the normal field only
class Skin:
    """Vertices and normals of the mesh with the neighbourhood of every seed replaced by the biharmonic fill of its surroundings.
    It is only a reference for the surface normal along a groove; no vertex of the output is taken from it."""

    def __init__(self, v: np.ndarray, f: np.ndarray, seeds: list[dict[str, Any]]):
        nv = len(v)
        d_open, d_loop = np.full(nv, np.inf), np.full(nv, np.inf)
        for kind, dst in (('open', d_open), ('loop', d_loop)):
            pts = [np.asarray(s['points'], float) for s in seeds if s['kind'] == kind]
            if pts:
                p = np.vstack(pts)
                dst[:] = cKDTree(_densify(p, 0.25)).query(v)[0]
        w = np.maximum(smoothstep((SKIN_HALF_WIDTH['open'] - d_open) / 0.35), smoothstep((SKIN_HALF_WIDTH['loop'] - d_loop) / 0.35))
        free = w > 0.3
        sol = v.copy()
        if free.any():
            a = adjacency(f, nv)
            deg = np.asarray(a.sum(1)).ravel()
            lap = (sp.diags(1 / deg) @ a - sp.eye(nv)).tocsr()
            ll = (lap.T @ lap).tocsr()
            fr, fx = np.flatnonzero(free), np.flatnonzero(~free)
            mat = ll[fr][:, fr].tocsc()
            rhs = -ll[fr][:, fx] @ v[fx]
            lu = spl.splu(mat)
            for k in range(3):
                sol[fr, k] = lu.solve(rhs[:, k])
        self.v = v + w[:, None] * (sol - v)
        self.n = vnormals(self.v, f)
        self.tree = cKDTree(self.v)
        self.free_vertices = int(free.sum())


def _densify(p: np.ndarray, step: float) -> np.ndarray:
    out = [p[:1]]
    for a, b in zip(p[:-1], p[1:]):
        k = max(int(np.linalg.norm(b - a) / step), 1)
        out.append(a + (b - a) * (np.arange(1, k + 1) / k)[:, None])
    return np.vstack(out)


# ------------------------------------------------------------------ centre line
class Curve:
    def __init__(self, ctrl: np.ndarray, closed: bool, skin: Skin, centre: np.ndarray, smooth: float = 0.0, ds: float = 0.05):
        ctrl = np.asarray(ctrl, float)
        keep = np.r_[True, np.linalg.norm(np.diff(ctrl, axis=0), axis=1) > 1e-3]       # splprep rejects repeated points
        ctrl = ctrl[keep]
        self.closed = closed
        if closed:
            ctrl = np.vstack([ctrl, ctrl[:1]])
        self.tck, _ = splprep(ctrl.T, k=3, s=smooth * len(ctrl), per=1 if closed else 0)
        uu = np.linspace(0, 1, 20000)
        pp = np.array(splev(uu, self.tck)).T
        L = np.r_[0, np.cumsum(np.linalg.norm(np.diff(pp, axis=0), axis=1))]
        self.L = float(L[-1])
        n = int(self.L / ds)
        ut = np.interp(np.linspace(0, self.L, n, endpoint=not closed), L, uu)
        self.P = np.array(splev(ut, self.tck)).T
        self.s = np.linspace(0, self.L, n, endpoint=not closed)
        self.n = n
        dd = np.roll(self.P, -1, 0) - np.roll(self.P, 1, 0) if closed else np.gradient(self.P, axis=0)
        self.T = dd / np.linalg.norm(dd, axis=1)[:, None]
        _, ix = skin.tree.query(self.P)
        N = skin.n[ix].copy()
        N *= np.sign(((self.P - centre) * N).sum(1))[:, None]          # outward
        N -= (N * self.T).sum(1)[:, None] * self.T
        N /= np.linalg.norm(N, axis=1)[:, None]
        mode = 'wrap' if closed else 'nearest'
        N = gaussian_filter1d(N, 20, axis=0, mode=mode)
        N -= (N * self.T).sum(1)[:, None] * self.T
        N /= np.linalg.norm(N, axis=1)[:, None]
        self.N, self.U = N, np.cross(N, self.T)
        self.tree = cKDTree(self.P)

    def query(self, X: np.ndarray):
        _, ix = self.tree.query(X, workers=-1)
        D = X - self.P[ix]
        return self.s[ix], (D * self.U[ix]).sum(1), (D * self.T[ix]).sum(1), (D * self.N[ix]).sum(1), ix


# ------------------------------------------------------------------ profile model (th = u1, wall_in, floor, wall_out, floor_height, left quad a0..a2, right quad b0..b2)
def sides(th):
    u1 = th[0]
    u4 = th[0] + th[1] + th[2] + th[3]
    return th[5] + th[6] * u1 + th[7] * u1 * u1, th[8] + th[9] * u4 + th[10] * u4 * u4


def depth_of(th) -> float:
    u1 = th[0]
    u2 = u1 + th[1]
    u3 = u2 + th[2]
    u4 = u3 + th[3]
    hl, hr = sides(th)
    uc = 0.5 * (u2 + u3)
    return float(hl + (hr - hl) * (uc - u1) / (u4 - u1) - th[4])


def profile2(u, th):
    u1 = th[0]
    u2 = u1 + th[1]
    u3 = u2 + th[2]
    u4 = u3 + th[3]
    hf = th[4]
    hl, hr = sides(th)
    h = np.empty_like(u)
    m = u < u1
    h[m] = th[5] + th[6] * u[m] + th[7] * u[m] ** 2
    m = (u >= u1) & (u < u2)
    h[m] = hl + (hf - hl) * (u[m] - u1) / th[1]
    m = (u >= u2) & (u < u3)
    h[m] = hf
    m = (u >= u3) & (u < u4)
    h[m] = hf + (hr - hf) * (u[m] - u3) / th[3]
    m = u >= u4
    h[m] = th[8] + th[9] * u[m] + th[10] * u[m] ** 2
    return h


def fit_profile2(u: np.ndarray, h: np.ndarray):
    lo = np.array([-1.8, 0.05, 0.0, 0.05, -3, -5, -3, -2, -5, -3, -2])
    hi = np.array([1.0, 1.5, 1.5, 1.5, 3, 5, 3, 2, 5, 3, 2])
    best = None

    def pf(m):
        return np.polyfit(u[m], h[m], 2)[::-1] if m.sum() >= 8 else np.zeros(3)
    for u1, gw in ((-0.7, 0.35), (-0.45, 0.25), (-0.9, 0.5), (-0.3, 0.3)):
        u4 = u1 + 0.2 + 2 * gw
        a_l = pf(u < u1 - 0.3) if (u < u1 - 0.3).sum() >= 8 else pf(u < 0)
        a_r = pf(u > u4 + 0.3) if (u > u4 + 0.3).sum() >= 8 else pf(u > 0)
        mid = (u > u1) & (u < u4)
        hf = np.percentile(h[mid], 10) if mid.sum() > 3 else 0
        x0 = np.clip(np.r_[u1, gw, 0.1, gw, hf, a_l, a_r], lo + 1e-6, hi - 1e-6)
        try:
            r = least_squares(lambda x: profile2(u, x) - h, x0, bounds=(lo, hi), loss='soft_l1', f_scale=0.03, max_nfev=120)
        except Exception:
            continue
        if best is None or r.cost < best.cost:
            best = r
    if best is None:
        return None, float('nan')
    return best.x, float(np.sqrt(np.mean(best.fun ** 2)))


def segment_dp(Y: np.ndarray, lam: float, minlen: int = 3):
    """Optimal partition of the rows of Y (n, k) into piecewise-constant segments; returns [(i0, i1), ...]."""
    n = len(Y)
    c1 = np.cumsum(np.vstack([np.zeros((1, Y.shape[1])), Y]), 0)
    c2 = np.cumsum(np.r_[0, (Y ** 2).sum(1)])

    def cost(i, j):
        s = c1[j] - c1[i]
        return (c2[j] - c2[i]) - (s ** 2).sum() / (j - i)
    F = np.full(n + 1, np.inf)
    F[0] = -lam
    prev = np.zeros(n + 1, int)
    for j in range(1, n + 1):
        for i in range(0, j - minlen + 1 if j >= minlen else 0):
            val = F[i] + cost(i, j) + lam
            if val < F[j]:
                F[j], prev[j] = val, i
        if not np.isfinite(F[j]):
            F[j], prev[j] = cost(0, j) + lam, 0
    seg, j = [], n
    while j > 0:
        i = prev[j]
        seg.append((i, j))
        j = i
    return seg[::-1]


def fit_stations(curve: Curve, Pq: np.ndarray, ds: float = 0.5, win: float = 0.3, umax: float = 3.0) -> np.ndarray:
    """One profile fit per station: rows [s, th(11), rms, n]; NaN rows where a station has too few samples."""
    s, u, _, h, _ = curve.query(Pq)
    keep = (np.abs(u) < umax) & (np.abs(h) < 3)
    s, u, hh = s[keep], u[keep], h[keep]
    o = np.argsort(s)
    s, u, hh = s[o], u[o], hh[o]
    st = np.arange(0.0, curve.L, ds) if curve.closed else np.arange(win, curve.L - win + 1e-9, ds)
    rows = []
    for si in st:
        lo, hi = np.searchsorted(s, [si - win, si + win])
        if curve.closed and (si - win < 0 or si + win > curve.L):
            if si - win < 0:
                idx = np.r_[np.arange(np.searchsorted(s, si - win + curve.L), len(s)), np.arange(0, hi)]
            else:
                idx = np.r_[np.arange(lo, len(s)), np.arange(0, np.searchsorted(s, si + win - curve.L))]
            uu, dd = u[idx], hh[idx]
        else:
            uu, dd = u[lo:hi], hh[lo:hi]
        if len(uu) < 60:
            rows.append(np.r_[si, [np.nan] * 13])
            continue
        th, rms = fit_profile2(uu, dd)
        rows.append(np.r_[si, [np.nan] * 11, np.nan, len(uu)] if th is None else np.r_[si, th, rms, len(uu)])
    return np.array(rows)


def refine_centre(curve: Curve, T: np.ndarray, ctrl_ds: float = 0.5, sig: float = 3, shift_cap: float = 0.6):
    s = T[:, 0]
    ok = ~np.isnan(T[:, 1])
    th = T[:, 1:12]
    uc = th[:, 0] + th[:, 1] + 0.5 * th[:, 2]
    dfv = np.array([depth_of(x) if not np.isnan(x[0]) else np.nan for x in th])
    wv = ok & (dfv > 0.06) & (T[:, 12] < 0.08)
    if wv.sum() < 4:
        return None, 0.0
    uc2 = np.interp(s, s[wv], uc[wv])
    uc2 = np.clip(gaussian_filter1d(uc2, sig, mode='wrap' if curve.closed else 'nearest'), -shift_cap, shift_cap)
    si = np.arange(0, curve.L, ctrl_ds)
    if not curve.closed:
        si = np.r_[si[:-1], curve.L - 1e-6] if curve.L - si[-1] < 0.1 else np.r_[si, curve.L - 1e-6]
    idx = np.searchsorted(curve.s, si).clip(0, curve.n - 1)
    shift = np.interp(si, s, uc2, period=curve.L if curve.closed else None)
    return curve.P[idx] + shift[:, None] * curve.U[idx], float(np.abs(shift).mean())


def profile2v(u: np.ndarray, th: np.ndarray) -> np.ndarray:
    u1 = th[:, 0]
    g1 = np.maximum(th[:, 1], 0.05)
    g3 = np.maximum(th[:, 3], 0.05)
    u2 = u1 + g1
    u3 = u2 + th[:, 2]
    u4 = u3 + g3
    hf = th[:, 4]
    hl = th[:, 5] + th[:, 6] * u1 + th[:, 7] * u1 ** 2
    hr = th[:, 8] + th[:, 9] * u4 + th[:, 10] * u4 ** 2
    h = np.empty_like(u)
    m = u < u1
    h[m] = (th[:, 5] + th[:, 6] * u + th[:, 7] * u * u)[m]
    m = (u >= u1) & (u < u2)
    h[m] = (hl + (hf - hl) * (u - u1) / g1)[m]
    m = (u >= u2) & (u < u3)
    h[m] = hf[m]
    m = (u >= u3) & (u < u4)
    h[m] = (hf + (hr - hf) * (u - u3) / g3)[m]
    m = u >= u4
    h[m] = (th[:, 8] + th[:, 9] * u + th[:, 10] * u * u)[m]
    return h


def widths(Q: np.ndarray) -> np.ndarray:
    """Width at half depth of rows [u1, g1, g2, g3, ...]."""
    u1 = Q[:, 0]
    g1 = np.maximum(Q[:, 1], 0.05)
    g3 = np.maximum(Q[:, 3], 0.05)
    u2 = u1 + g1
    u3 = u2 + Q[:, 2]
    return (u3 + g3 * 0.5) - (u1 + g1 * 0.5)


class Unit:
    """One fitted groove: centre line + per-station profile + constant-profile segments + presence mask."""

    def __init__(self, name: str, curve: Curve, T: np.ndarray, closed: bool, lam: float, rms_bad: float = 0.06, df_bad: float = 0.7, sig_side: float = 2):
        self.name, self.curve, self.T, self.closed, self.lam, self.sig_side = name, curve, T, closed, lam, sig_side
        self.df_bad = df_bad
        self.L = curve.L
        self._finalize(rms_bad, df_bad)

    def _finalize(self, rms_bad: float, df_bad: float) -> None:
        T = self.T
        s = T[:, 0]
        th = T[:, 1:12].copy()
        rms = T[:, 12]
        df = np.array([depth_of(x) if not np.isnan(x[0]) else np.nan for x in th])
        bad = np.isnan(th[:, 0]) | (rms > rms_bad) | (df > df_bad) | (df < -0.2)
        good = ~bad
        self.n_stations, self.n_good = len(s), int(good.sum())
        self.fit_ok = self.n_good >= 4
        per = self.L if self.closed else None
        n = len(s)
        self.segments: list[dict[str, Any]] = []
        self.s, self.th_raw, self.df_raw, self.bad = s, th, df, bad
        if not self.fit_ok:
            self.Q, self.pres = np.zeros((n, 11)), np.zeros(n)
            return
        thi = th.copy()
        for k in range(11):
            thi[:, k] = np.interp(s, s[good], th[good, k], period=per)
        dfi = np.array([depth_of(x) for x in thi])
        feat = np.c_[dfi / 0.05, (thi[:, 1] + thi[:, 2] + thi[:, 3]) / 0.30, thi[:, 2] / 0.30]
        shift = 0
        if self.closed:
            dd = np.abs(np.diff(np.r_[feat[-1:], feat], axis=0)).sum(1)
            shift = int(np.argmax(np.convolve(dd, np.ones(3), 'same')))
            feat = np.roll(feat, -shift, 0)
        seg = segment_dp(feat, self.lam, minlen=4)
        Q = np.zeros((n, 11))
        for i0, i1 in seg:
            ix = (np.arange(i0, i1) + shift) % n
            use = ix[good[ix]] if good[ix].sum() >= 2 else ix
            med = np.median(np.c_[thi[use, :4], dfi[use]], axis=0)
            Q[ix, :4], Q[ix, 4] = med[:4], med[4]
            self.segments.append({'s0_mm': float(s[ix[0]]), 's1_mm': float(s[ix[-1]]), 'stations': int(len(ix)), 'u1_mm': float(med[0]), 'wall_in_mm': float(med[1]),
                                  'floor_mm': float(med[2]), 'wall_out_mm': float(med[3]), 'depth_mm': float(med[4]), 'width_half_depth_mm': float(widths(Q[ix[:1]])[0]),
                                  'stations_failed_fit': int((~good[ix]).sum()), 'absent': bool(med[4] < DF_MIN)})
        mode = 'wrap' if self.closed else 'nearest'
        for k in range(5, 11):
            Q[:, k] = gaussian_filter1d(thi[:, k], self.sig_side, mode=mode)
        absent = Q[:, 4] < DF_MIN
        bd = bad | np.roll(bad, 1) | np.roll(bad, -1)
        if not self.closed:
            bd[0] |= bad[0]
            bd[-1] |= bad[-1]
        pres = np.where(absent | bd, 0.0, 1.0)
        pres = np.clip(gaussian_filter1d(pres, 1.0, mode=mode), 0, 1)
        pres = np.where(absent | bd, np.minimum(pres, 0.0), np.where(pres > 0.99, 1.0, pres))
        self.Q, self.pres, self.absent = Q, pres, absent

    def th_at(self, sv: np.ndarray):
        per = self.L if self.closed else None
        Q = np.stack([np.interp(sv, self.s, self.Q[:, k], period=per) for k in range(11)], 1)
        p = np.interp(sv, self.s, self.pres, period=per)
        if not self.closed:
            p *= smoothstep(np.minimum(sv - self.s[0], self.s[-1] - sv) / 1.0)
        u1 = Q[:, 0]
        g1 = np.maximum(Q[:, 1], 0.05)
        u2 = u1 + g1
        u3 = u2 + Q[:, 2]
        u4 = u3 + np.maximum(Q[:, 3], 0.05)
        hl = Q[:, 5] + Q[:, 6] * u1 + Q[:, 7] * u1 ** 2
        hr = Q[:, 8] + Q[:, 9] * u4 + Q[:, 10] * u4 ** 2
        uc = 0.5 * (u2 + u3)
        th = Q.copy()
        th[:, 4] = hl + (hr - hl) * (uc - u1) / (u4 - u1) - Q[:, 4]
        th[:, 1], th[:, 3] = g1, u4 - u3
        return th, p

    def extent(self, sv: np.ndarray):
        th, p = self.th_at(sv)
        u1 = th[:, 0]
        return u1, u1 + th[:, 1] + th[:, 2] + th[:, 3], p

    def model(self, X: np.ndarray):
        s, u, _, h, ix = self.curve.query(X)
        th, p = self.th_at(s)
        hm = profile2v(u, th)
        u1 = th[:, 0]
        u4 = u1 + th[:, 1] + th[:, 2] + th[:, 3]
        om = smoothstep((u - (u1 - 1.3)) / 0.5) * (1 - smoothstep((u - (u4 + 0.5)) / 0.5)) * p
        return om, hm - h, self.curve.N[ix]


# ------------------------------------------------------------------ conforming subdivision of a face selection
def subdivide_sel(V: np.ndarray, F: np.ndarray, sel: np.ndarray, levels: int):
    V = np.asarray(V, float)
    F = F.copy()
    sel = sel.copy()
    for _ in range(levels):
        if not sel.any():
            break
        e = np.concatenate([F[sel][:, [0, 1]], F[sel][:, [1, 2]], F[sel][:, [2, 0]]])
        e = np.unique(np.sort(e, 1), axis=0)
        base = len(V)
        M = len(V) + len(e) + 7
        key = e[:, 0].astype(np.int64) * M + e[:, 1]
        o = np.argsort(key)
        keys, ids = key[o], base + o
        V = np.vstack([V, 0.5 * (V[e[:, 0]] + V[e[:, 1]])])

        def mid(a, b):
            k = np.minimum(a, b).astype(np.int64) * M + np.maximum(a, b)
            j = np.minimum(np.searchsorted(keys, k), len(keys) - 1)
            return np.where(keys[j] == k, ids[j], -1)
        A, B, C = F[:, 0], F[:, 1], F[:, 2]
        ab, bc, ca = mid(A, B), mid(B, C), mid(C, A)
        k = (ab >= 0).astype(int) + (bc >= 0) + (ca >= 0)
        nF, nS = [], []

        def add(t, s_):
            nF.append(t)
            nS.append(np.full(len(t), s_) if np.isscalar(s_) else s_)
        i0 = k == 0
        add(F[i0], sel[i0])
        i3 = k == 3
        a, b, c, x, y, z = A[i3], B[i3], C[i3], ab[i3], bc[i3], ca[i3]
        for t in (np.c_[a, x, z], np.c_[x, b, y], np.c_[z, y, c], np.c_[x, y, z]):
            add(t, sel[i3])
        i1 = k == 1
        j = i1 & (ab >= 0)
        add(np.c_[A[j], ab[j], C[j]], False)
        add(np.c_[ab[j], B[j], C[j]], False)
        j = i1 & (bc >= 0)
        add(np.c_[B[j], bc[j], A[j]], False)
        add(np.c_[bc[j], C[j], A[j]], False)
        j = i1 & (ca >= 0)
        add(np.c_[C[j], ca[j], B[j]], False)
        add(np.c_[ca[j], A[j], B[j]], False)
        i2 = k == 2
        j = i2 & (ab < 0)
        add(np.c_[C[j], ca[j], bc[j]], False)
        add(np.c_[A[j], B[j], bc[j]], False)
        add(np.c_[A[j], bc[j], ca[j]], False)
        j = i2 & (bc < 0)
        add(np.c_[A[j], ab[j], ca[j]], False)
        add(np.c_[ab[j], B[j], C[j]], False)
        add(np.c_[ab[j], C[j], ca[j]], False)
        j = i2 & (ca < 0)
        add(np.c_[B[j], bc[j], ab[j]], False)
        add(np.c_[A[j], ab[j], C[j]], False)
        add(np.c_[ab[j], bc[j], C[j]], False)
        F = np.vstack(nF).astype(np.int64)
        sel = np.concatenate(nS).astype(bool)
    return V, F, sel


# ------------------------------------------------------------------ design intent: constant clean groove on a smooth centre line
def _huber_w(r: np.ndarray, k: float) -> np.ndarray:
    return 1.0 / np.maximum(1.0, np.abs(r) / k)


def _polyline_curvature(P: np.ndarray) -> float:
    d = np.diff(P, axis=0)
    ln = np.linalg.norm(d, axis=1)
    t = d / np.maximum(ln, 1e-12)[:, None]
    ang = np.arccos(np.clip((t[1:] * t[:-1]).sum(1), -1, 1))
    return float((ang / np.maximum(0.5 * (ln[1:] + ln[:-1]), 1e-12)).max()) if len(ang) else 0.0


def intent_trusted(un: 'Unit') -> np.ndarray:
    th, T = un.T[:, 1:12], un.T
    return ~np.isnan(th[:, 0]) & (T[:, 12] < 0.08) & (un.df_raw > 0.06) & (un.df_raw < un.df_bad)


def intent_centre(un: 'Unit', ext: float, straight: bool | None) -> tuple[np.ndarray, dict[str, Any]] | None:
    """Smooth, low-curvature centre line through the centres of the trusted stations (robust), extended by ext mm at both ends."""
    c = un.curve
    ref = intent_trusted(un)
    if ref.sum() < 6:
        return None
    th = un.T[ref, 1:12]
    uc = th[:, 0] + th[:, 1] + 0.5 * th[:, 2]
    idx = np.searchsorted(c.s, un.T[ref, 0]).clip(0, c.n - 1)
    C = c.P[idx] + uc[:, None] * c.U[idx]
    Nm = c.N[idx].mean(0)
    Nm /= np.linalg.norm(Nm)
    c0 = np.median(C, axis=0)
    D = C - c0
    Dp = D - (D @ Nm)[:, None] * Nm
    w = np.ones(len(C))
    e = np.zeros(3)
    for _ in range(4):
        cov = (Dp * w[:, None]).T @ Dp
        e = np.linalg.eigh(cov)[1][:, -1]
        lat = Dp - (Dp @ e)[:, None] * e
        w = _huber_w(np.linalg.norm(lat, axis=1), 0.1)
    if e @ (C[-1] - C[0]) < 0:
        e = -e
    m = np.cross(Nm, e)
    scatter = np.abs(D @ m)
    p95 = float(np.percentile(scatter, 95))
    length = float(np.linalg.norm(C[-1] - C[0]))
    is_straight = bool(straight) if straight is not None else (p95 <= INTENT_STRAIGHT_P95_MM and length <= INTENT_STRAIGHT_MAX_LEN_MM)
    step = 0.25
    info: dict[str, Any] = {'trusted_stations': int(ref.sum()), 'trusted_s_range_mm': [float(un.T[ref, 0].min()), float(un.T[ref, 0].max())],
                            'centre_scatter_p95_mm_about_plan_line': round(p95, 4), 'extend_mm': ext}
    if is_straight:
        t = D @ e
        z = D @ Nm
        wz = np.ones(len(t))
        for _ in range(4):
            co = np.polyfit(t, z, 2, w=wz)
            wz = _huber_w(z - np.polyval(co, t), 0.05)
        tg = np.arange(t.min() - ext, t.max() + ext + 1e-9, step)
        pts = c0 + tg[:, None] * e + np.polyval(co, tg)[:, None] * Nm
        info.update({'shape': 'straight in plan (line in the surface-tangent plane, height from a quadratic of the fitted centres)', 'straight': True,
                     'in_plan_residual_rms_mm': float(np.sqrt(np.mean(scatter ** 2))), 'max_curvature_per_mm': _polyline_curvature(pts)})
        return pts, info
    from scipy.interpolate import make_lsq_spline
    tau = np.r_[0, np.cumsum(np.linalg.norm(np.diff(C, axis=0), axis=1))]
    tau, ordr = np.unique(tau, return_index=True)
    Cs = C[ordr]
    best = None
    for kn in INTENT_KNOT_MM:
        nint = max(0, int(round((tau[-1] - tau[0]) / kn)) - 1)
        knots = np.r_[[tau[0]] * 4, np.linspace(tau[0], tau[-1], nint + 2)[1:-1], [tau[-1]] * 4]
        wt = np.ones(len(tau))
        sp3 = None
        try:
            for _ in range(5):
                sp3 = make_lsq_spline(tau, Cs, knots, k=3, w=wt)
                wt = _huber_w(np.linalg.norm(sp3(tau) - Cs, axis=1), 0.1)
        except Exception:
            continue
        tg = np.r_[np.arange(tau[0], tau[-1], step), tau[-1]]
        body = sp3(tg)
        t0, t1 = sp3(tau[0], 1), sp3(tau[-1], 1)
        t0, t1 = t0 / np.linalg.norm(t0), t1 / np.linalg.norm(t1)
        ks = np.arange(step, ext + 1e-9, step)[:, None]
        pts = np.vstack([body[0] - ks[::-1] * t0, body, body[-1] + ks * t1])
        kap = _polyline_curvature(pts)
        res = float(np.sqrt(np.mean((sp3(tau) - Cs) ** 2)))
        best = (pts, kn, kap, res)
        if kap <= INTENT_MAX_CURVATURE:
            break
    if best is None:
        return None
    pts, kn, kap, res = best
    info.update({'shape': 'smooth cubic B-spline through the robust centres', 'straight': False, 'knot_spacing_mm': kn, 'max_curvature_per_mm': kap,
                 'curvature_limit_per_mm': INTENT_MAX_CURVATURE, 'curvature_limit_met': bool(kap <= INTENT_MAX_CURVATURE), 'centre_fit_rms_mm': res})
    return pts, info


def intent_refit_skins(curve: Curve, Pq: np.ndarray, T2: np.ndarray, prof: np.ndarray, win: float = 0.3, umax: float = 3.0, nmin: int = 40) -> tuple[np.ndarray, np.ndarray]:
    """Per station skins (left / right quadratic) from the samples OUTSIDE the constant groove only, outliers (slit interior, flash) trimmed. Returns (skins (n, 6), ok (n,))."""
    s, u, _, h, _ = curve.query(Pq)
    keep = (np.abs(u) < umax) & (np.abs(h) < 3)
    s, u, h = s[keep], u[keep], h[keep]
    o = np.argsort(s)
    s, u, h = s[o], u[o], h[o]
    u1 = prof[0]
    u4 = prof[0] + prof[1] + prof[2] + prof[3]
    n = len(T2)
    out = np.full((n, 6), np.nan)
    ok = np.zeros(n, bool)
    for i in range(n):
        si = T2[i, 0]
        lo, hi = np.searchsorted(s, [si - win, si + win])
        uu, hh = u[lo:hi], h[lo:hi]
        res = []
        for side, m in ((0, uu < u1 - 0.1), (1, uu > u4 + 0.1)):
            if m.sum() < nmin:
                break
            x, y = uu[m], hh[m]
            co = np.polyfit(x, y, 2)[::-1]
            if np.isfinite(T2[i, 1]):
                co = np.asarray(T2[i, 6 + 3 * side:9 + 3 * side], float)
            good = True
            for scale in (0.25, 0.12, 0.08):
                r = y - (co[0] + co[1] * x + co[2] * x * x)
                k = np.abs(r) < scale
                if k.sum() < nmin:
                    good = False
                    break
                co = np.polyfit(x[k], y[k], 2)[::-1]
            if not good:
                break
            res.append(co)
        if len(res) == 2:
            out[i], ok[i] = np.r_[res[0], res[1]], True
    return out, ok


def build_intent_unit(un: 'Unit', seed: dict[str, Any], skin: Skin, centre: np.ndarray, Pq: np.ndarray, log) -> tuple['Unit', dict[str, Any]] | dict[str, Any]:
    """Replace a fitted open groove by the design-intent groove: smoothed centre line, constant robust-median width / depth, skins refitted from the trusted surface."""
    cen = intent_centre(un, INTENT_EXTEND_MM, seed.get('straight'))
    if cen is None:
        return {'not_found': 'design intent: fewer than 6 trusted stations (depth 0.06-0.7 mm, fit rms below 0.08 mm); the fitted groove is used'}
    pts, cinfo = cen
    cur = Curve(pts, False, skin, centre, smooth=0.0)
    T2 = fit_stations(cur, Pq)
    th2 = T2[:, 1:12]
    df2 = np.array([depth_of(x) if not np.isnan(x[0]) else np.nan for x in th2])
    good2 = ~np.isnan(th2[:, 0]) & (T2[:, 12] < 0.08) & (df2 > 0.06) & (df2 < un.df_bad)
    if good2.sum() < 4:
        return {'not_found': 'design intent: the refit along the smoothed centre line has fewer than 4 trusted stations; the fitted groove is used'}
    q = np.c_[th2[good2, :4], df2[good2]]
    med = np.median(q, axis=0)
    mad = np.median(np.abs(q - med), axis=0)
    prof = med[:4]
    depth = float(med[4])
    skins, sok = intent_refit_skins(cur, Pq, T2, prof)
    if sok.sum() < 4:
        return {'not_found': 'design intent: too few stations with trusted skins on both sides; the fitted groove is used'}
    s2 = T2[:, 0]
    for k in range(6):
        skins[:, k] = np.interp(s2, s2[sok], skins[sok, k])
        skins[:, k] = gaussian_filter1d(skins[:, k], 3, mode='nearest')
    u1 = prof[0]
    u2, u3 = u1 + prof[1], u1 + prof[1] + prof[2]
    u4 = u3 + prof[3]
    hl = skins[:, 0] + skins[:, 1] * u1 + skins[:, 2] * u1 ** 2
    hr = skins[:, 3] + skins[:, 4] * u4 + skins[:, 5] * u4 ** 2
    hf = hl + (hr - hl) * (0.5 * (u2 + u3) - u1) / (u4 - u1) - depth
    n = len(s2)
    Tint = np.c_[s2, np.tile(prof, (n, 1)), hf, skins, np.zeros(n), np.full(n, 999.0)]
    new = Unit(un.name, cur, Tint, False, LAMBDA_OPEN, df_bad=un.df_bad, sig_side=1)
    new.ctrl, new.seed_kind = pts, seed.get('kind')
    # classify the stations of the ORIGINAL fit
    c = un.curve
    th = un.T[:, 1:12]
    uc_o = th[:, 0] + th[:, 1] + 0.5 * th[:, 2]
    idx = np.searchsorted(c.s, un.T[:, 0]).clip(0, c.n - 1)
    X = c.P[idx] + np.nan_to_num(uc_o)[:, None] * c.U[idx]
    sn, u_off, tan, _, _ = cur.query(X)
    covered = (np.abs(tan) < 0.3) & (sn > 0.05) & (sn < cur.L - 0.05)
    w_o = widths(np.nan_to_num(th))
    w_med = float((u3 + max(prof[3], 0.05) * 0.5) - (u1 + max(prof[1], 0.05) * 0.5))
    fit_ok = ~un.bad & ~np.isnan(un.df_raw)
    agree = (fit_ok & (np.abs(np.nan_to_num(un.df_raw, nan=9) - depth) <= INTENT_AGREE_DEPTH_MM) & (np.abs(w_o - w_med) <= INTENT_AGREE_WIDTH_MM)
             & (np.abs(u_off - 0.5 * (u1 + u4)) <= INTENT_AGREE_CENTRE_MM))
    status = np.where(~covered, 'original', np.where(agree, 'fitted', 'intent'))
    n_fail = int(((status == 'intent') & ~fit_ok).sum())
    info = {**cinfo, 'width_half_depth_mm': round(w_med, 4), 'depth_mm': round(depth, 4), 'depth_mad_mm': round(float(mad[4]), 4),
            'profile_mm': {'u1': round(float(prof[0]), 4), 'wall_in': round(float(prof[1]), 4), 'floor': round(float(prof[2]), 4), 'wall_out': round(float(prof[3]), 4)},
            'profile_stations_used': int(good2.sum()), 'profile_stations_total': int(n), 'skin_stations_interpolated': int((~sok).sum()),
            'original_stations': {'total': int(len(status)), 'fitted': int((status == 'fitted').sum()), 'rebuilt_by_intent': int((status == 'intent').sum()),
                                  'left_original': int((status == 'original').sum()), 'rebuilt_fit_failed': n_fail,
                                  'rebuilt_scan_differs': int((status == 'intent').sum()) - n_fail},
            'station_status': [{'s_mm': round(float(a), 2), 'status': str(b)} for a, b in zip(un.T[:, 0], status)]}
    log(f'{un.name}: design intent: {info["original_stations"]}, width {w_med:.3f} depth {depth:.3f}, {info["shape"]}')
    return new, info


def apply_intent_cap(dl: np.ndarray, cap: float) -> tuple[np.ndarray, int, int]:
    """Displacement up to cap mm is applied fully; between cap and 2 cap it fades to zero (deep undercuts such as a slit interior stay as scanned)."""
    mag = np.linalg.norm(dl, axis=1)
    fac = np.where(mag <= cap, 1.0, np.clip(2.0 - mag / np.maximum(cap, 1e-12), 0.0, 1.0))
    return dl * fac[:, None], int((mag > cap).sum()), int((mag >= 2 * cap).sum())


# ------------------------------------------------------------------ grooves pipeline
def build_unit(seed: dict[str, Any], v: np.ndarray, f: np.ndarray, skin: Skin, centre: np.ndarray, log, intent: bool = False) -> Unit | dict[str, Any]:
    """Fit one groove from its seed polyline. Returns a Unit, or {'not_found': reason}."""
    pts = np.asarray(seed['points'], float)
    closed = bool(seed['closed'])
    if len(pts) < 8:
        return {'not_found': 'seed has fewer than 8 points'}
    smooth0 = 0.02 if closed else 0.01
    cur = Curve(pts, closed, skin, centre, smooth=smooth0)
    if closed:
        pc = pts.mean(0)
        rad = cur.P - pc
        rad -= (rad * cur.N).sum(1)[:, None] * cur.N
        if ((cur.U * rad).sum(1)).mean() < 0:
            cur = Curve(pts[::-1], closed, skin, centre, smooth=smooth0)
    near = cKDTree(cur.P).query(v, workers=-1)[0] < 4.0
    fs = near[f].any(1)
    Pq = sample_faces(v, f, np.flatnonzero(fs), dens=SAMPLE_DENSITY, seed=1)
    ctrl_cur, smooth_cur = pts, smooth0
    T = None
    for it in range(6):
        T = fit_stations(cur, Pq)
        ctrl, sh = refine_centre(cur, T)
        log(f'{seed["name"]}: centre iteration {it} mean shift {sh:.3f} mm')
        if ctrl is None:
            return {'not_found': 'no station carries a groove deeper than 0.06 mm with a fit rms below 0.08 mm'}
        if sh < 0.01:
            break
        cur = Curve(ctrl, closed, skin, centre, smooth=0.003)
        ctrl_cur, smooth_cur = ctrl, 0.003
    T = fit_stations(cur, Pq)
    unit = Unit(seed['name'], cur, T, closed, LAMBDA_LOOP if closed else LAMBDA_OPEN)
    unit.ctrl = ctrl_cur
    unit.seed_kind = seed.get('kind')
    unit.intent = None
    unit.intent_failed = None
    if not unit.fit_ok:
        return {'not_found': f'only {unit.n_good} of {unit.n_stations} stations could be fitted'}
    if intent and not closed:
        r = build_intent_unit(unit, seed, skin, centre, Pq, log)
        if isinstance(r, tuple):
            new, info = r
            new.intent, new.intent_failed = info, None
            return new
        log(f'{seed["name"]}: {r["not_found"]}')
        unit.intent_failed = r['not_found']
    return unit


def apply_units(v: np.ndarray, f: np.ndarray, units: list[Unit], log, cap: float = 0.6):
    """Subdivide round every unit and move vertices to the model profile along the curve normal."""
    cen = v[f].mean(1)
    sel = np.zeros(len(f), bool)
    for un in units:
        s, u, _, h, _ = un.curve.query(cen)
        u1, u4, p = un.extent(s)
        sel |= (u > u1 - 1.3) & (u < u4 + 1.0) & (np.abs(h) < 2.5) & (p > 0)
    V2, F2, sel2 = subdivide_sel(v, f, sel, SUBDIVISION_LEVELS)
    log(f'subdivision: {int(sel.sum())} faces selected, {len(f)} -> {len(F2)} faces')
    best = np.zeros((len(V2), 3))
    bn = np.zeros(len(V2))
    owner = np.full(len(V2), -1)
    info = {}
    for k, un in enumerate(units):
        dd, _ = cKDTree(un.curve.P).query(V2, workers=-1)
        cand = np.flatnonzero(dd < 3.0)
        om, off, N = un.model(V2[cand])
        act = om > 1e-6
        ci = cand[act]
        dl = (om[act] * off[act])[:, None] * N[act]
        cap_info: dict[str, Any] = {}
        if getattr(un, 'intent', None) is not None:
            dl, n_over, n_far = apply_intent_cap(dl, cap)
            cap_info = {'cap_mm': cap, 'vertices_over_cap': n_over, 'vertices_left_as_scanned_beyond_2cap': n_far, 'cap_binds': bool(n_over > 0)}
        mag = np.linalg.norm(dl, axis=1)
        better = mag > bn[ci]
        best[ci[better]] = dl[better]
        bn[ci[better]] = mag[better]
        owner[ci[better]] = k
        info[un.name] = {'vertices_active': int(act.sum()), 'max_displacement_mm': float(mag.max()) if len(mag) else 0.0, **cap_info}
    return V2, F2, V2 + best, owner, info


# ------------------------------------------------------------------ metrics
def b3_subset(V: np.ndarray, F: np.ndarray, ids: np.ndarray, r: float = 1.5) -> np.ndarray:
    """Local normal scatter (degrees): sqrt of the smallest eigenvalue of the area-weighted normal covariance within r."""
    n, a = fnormals(V, F)
    cen = V[F].mean(1)
    tree = cKDTree(cen)
    out = np.zeros(len(ids))
    for k, i in enumerate(ids):
        idx = tree.query_ball_point(cen[i], r)
        w, nn = a[idx], n[idx]
        m = (nn * w[:, None]).sum(0) / w.sum()
        C = ((nn[:, :, None] * nn[:, None, :]) * w[:, None, None]).sum(0) / w.sum() - np.outer(m, m)
        ev = np.maximum(np.linalg.eigvalsh(C), 0)
        out[k] = np.degrees(np.sqrt(ev[0]))
    return out


def _pcts(x: np.ndarray) -> dict[str, float | int]:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if not len(x):
        return {'samples': 0}
    return {'samples': int(len(x)), 'mean': float(x.mean()), 'p95': float(np.percentile(x, 95)), 'max': float(x.max())}


def dist_to_mesh(pm, pts: np.ndarray, v: np.ndarray, f: np.ndarray) -> np.ndarray:
    """Exact point-to-triangle distance of pts to the mesh (fresh MeshSet every time: PyMeshLab keeps stale per-vertex quality)."""
    if not len(pts):
        return np.zeros(0)
    ms = pm.MeshSet()
    ms.add_mesh(pm.Mesh(vertex_matrix=np.ascontiguousarray(v, dtype=np.float64), face_matrix=np.ascontiguousarray(f, dtype=np.int32)))
    ms.add_mesh(pm.Mesh(vertex_matrix=np.ascontiguousarray(pts, dtype=np.float64)))
    ms.get_hausdorff_distance(sampledmesh=1, targetmesh=0, samplevert=True, sampleedge=False, sampleface=False, samplenum=len(pts),
                              maxdist=pm.PercentageValue(50), savesample=False)
    return np.abs(np.array(ms.mesh(1).vertex_scalar_array()))


def self_intersecting_faces(pm, v: np.ndarray, f: np.ndarray) -> int:
    ms = pm.MeshSet()
    ms.add_mesh(pm.Mesh(vertex_matrix=np.ascontiguousarray(v, dtype=np.float64), face_matrix=np.ascontiguousarray(f, dtype=np.int32)))
    ms.compute_selection_by_self_intersections_per_face()
    return int(np.asarray(ms.current_mesh().face_selection_array(), bool).sum())


def write_stl(path: Path, v: np.ndarray, f: np.ndarray) -> None:
    n, _ = fnormals(v, f)
    rec = np.zeros(len(f), dtype=np.dtype([('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')]))
    rec['n'], rec['v'] = n, v[f]
    path.write_bytes(b'cadmcp scan_clean'.ljust(80, b' ') + np.uint32(len(f)).tobytes() + rec.tobytes())


def write_ply(path: Path, v: np.ndarray, f: np.ndarray) -> None:
    head = (f'ply\nformat binary_little_endian 1.0\ncomment cadmcp scan_clean, mm\nelement vertex {len(v)}\nproperty double x\nproperty double y\nproperty double z\n'
            f'element face {len(f)}\nproperty list uchar int vertex_indices\nend_header\n').encode('ascii')
    fr = np.zeros(len(f), dtype=np.dtype([('c', 'u1'), ('i', '<i4', 3)]))
    fr['c'], fr['i'] = 3, f
    path.write_bytes(head + np.ascontiguousarray(v, dtype='<f8').tobytes() + fr.tobytes())


def _clean_json(o):
    if isinstance(o, dict):
        return {k: _clean_json(x) for k, x in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean_json(x) for x in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return _clean_json(o.tolist())
    return o


def _topology_dict(t: dict[str, Any]) -> dict[str, Any]:
    return {k: t[k] for k in ('faces', 'vertices', 'boundary_edges', 'non_manifold_edges', 'non_manifold_vertices', 'inconsistent_winding_edges', 'components',
                              'watertight', 'manifold', 'winding_consistent', 'signed_volume_mm3', 'degenerate_faces')}


def _station_rows(un: Unit) -> list[dict[str, Any]]:
    tmp = widths(un.Q)
    rows = []
    for i, sv in enumerate(un.s):
        th, _ = un.th_at(np.array([sv]))
        th = th[0]
        rows.append({'s_mm': round(float(sv), 3), 'present': bool(un.pres[i] > 0.5), 'fit_failed': bool(un.bad[i]), 'depth_mm': round(float(un.Q[i, 4]), 4),
                     'width_half_depth_mm': round(float(tmp[i]), 4), 'u1_mm': round(float(th[0]), 4), 'wall_in_mm': round(float(th[1]), 4), 'floor_width_mm': round(float(th[2]), 4),
                     'wall_out_mm': round(float(th[3]), 4), 'floor_height_mm': round(float(th[4]), 4),
                     'left_skin_poly': [round(float(x), 5) for x in un.Q[i, 5:8]], 'right_skin_poly': [round(float(x), 5) for x in un.Q[i, 8:11]],
                     'depth_measured_mm': None if np.isnan(un.df_raw[i]) else round(float(un.df_raw[i]), 4),
                     'fit_rms_mm': None if np.isnan(un.T[i, 12]) else round(float(un.T[i, 12]), 4)})
    return rows


def groove_record(un: Unit) -> dict[str, Any]:
    c = un.curve
    steps = [round(float(sg['s0_mm']), 3) for sg in un.segments[1:]] if not un.closed else [round(float(sg['s0_mm']), 3) for sg in un.segments]
    return {
        'type': 'closed loop' if un.closed else 'open curve', 'length_mm': round(float(c.L), 3),
        'centerline_bspline': {'degree': 3, 'periodic': bool(un.closed), 'knots': np.asarray(c.tck[0]).tolist(),
                               'control_points_mm': np.array(c.tck[1]).T.round(4).tolist()},
        'centerline_polyline_mm': c.P[::10].round(4).tolist(),
        'segments_constant_profile': un.segments, 'step_positions_s_mm': steps,
        'floor_shape': 'trapezoid with a measured flat floor width; round versus flat floor is not resolvable at the scan edge length',
        'stations_total': int(un.n_stations), 'stations_fit_failed': int(un.bad.sum()), 'stations_absent_or_left_original': int((un.pres < 0.5).sum()),
        'stations': _station_rows(un), **_intent_record(un)}


def _intent_record(un: Unit) -> dict[str, Any]:
    it = getattr(un, 'intent', None)
    if it is None:
        return {'design_intent': {'applied': False, 'reason': getattr(un, 'intent_failed', None)}} if getattr(un, 'intent_failed', None) else {}
    o = it['original_stations']
    return {'design_intent': {'applied': True, **it},
            'stations_total': o['total'], 'stations_fit_failed': o['rebuilt_fit_failed'], 'stations_absent_or_left_original': o['left_original'],
            'stations_fitted': o['fitted'], 'stations_rebuilt_by_intent': o['rebuilt_by_intent']}


# ------------------------------------------------------------------ zones mode
def mls_project(P: np.ndarray, ref: np.ndarray, targets: np.ndarray, R: float = 2.5, minpts: int = 25, grow=(2.5, 3.5, 5.0, 6.5)):
    """Project P[targets] onto a local quadric fitted to the reference points ref (not to the targets)."""
    tr = cKDTree(ref)
    out = P[targets].copy()
    ok = np.zeros(len(targets), bool)
    for t, i in enumerate(targets):
        p = P[i]
        idx = []
        R_ = grow[0]
        for R_ in grow:
            idx = tr.query_ball_point(p, R_)
            if len(idx) >= minpts:
                break
        if len(idx) < minpts:
            continue
        X = ref[idx]
        d = np.linalg.norm(X - p, axis=1)
        w = np.exp(-(d / (R_ / 2)) ** 2)
        c = (X * w[:, None]).sum(0) / w.sum()
        Y = X - c
        _, U = np.linalg.eigh((Y * w[:, None]).T @ Y)
        n, e1, e2 = U[:, 0], U[:, 2], U[:, 1]
        x, y, z = Y @ e1, Y @ e2, Y @ n
        B = np.stack([np.ones_like(x), x, y, x * x, x * y, y * y], 1)
        co = np.linalg.lstsq(B * np.sqrt(w)[:, None], z * np.sqrt(w), rcond=None)[0]
        px, py = (p - c) @ e1, (p - c) @ e2
        out[t] = c + px * e1 + py * e2 + co @ np.array([1, px, py, px * px, px * py, py * py]) * n
        ok[t] = True
    return out, ok


def zone_repair(v: np.ndarray, f: np.ndarray, zone_vertices: np.ndarray, cap_mm: float, taper_hops: int = 3):
    """Displacement-only fill of the zone from its surroundings. Returns (new vertices, info)."""
    nv = len(v)
    inz = np.zeros(nv, bool)
    inz[zone_vertices] = True
    adj = adjacency(f, nv)
    depth = np.zeros(nv)                 # hops from the zone border (0 outside, 1 on the first ring inside, ...)
    outside = ~inz
    cur = outside.copy()
    for h in range(1, 60):
        nxt = (adj @ cur.astype(float) > 0) & ~cur
        if not nxt.any():
            break
        depth[nxt & inz] = h
        cur |= nxt
    wt = smoothstep(depth / float(taper_hops + 1))
    wt[~inz] = 0.0
    near = cKDTree(v[inz]).query(v)[0] < 7.0 if inz.any() else np.zeros(nv, bool)
    ref = v[near & ~inz]
    targets = np.flatnonzero(inz)
    if len(ref) < 25 or not len(targets):
        return v.copy(), {'zone_vertices': int(len(targets)), 'projected': 0, 'reference_vertices': int(len(ref))}
    proj, ok = mls_project(v, ref, targets)
    vn = v.copy()
    d = (proj - v[targets]) * (wt[targets] * ok)[:, None]
    mag = np.linalg.norm(d, axis=1)
    sc = np.minimum(1.0, cap_mm / np.maximum(mag, 1e-12))
    vn[targets] = v[targets] + d * sc[:, None]
    return vn, {'zone_vertices': int(len(targets)), 'projected': int(ok.sum()), 'not_projected': int((~ok).sum()), 'reference_vertices': int(len(ref)),
                'displacement_mean_mm': float(np.linalg.norm(vn[targets] - v[targets], axis=1).mean()), 'displacement_max_mm': float(np.linalg.norm(vn[targets] - v[targets], axis=1).max()),
                'capped_vertices': int((mag > cap_mm).sum()), 'taper_hops': taper_hops}


# ------------------------------------------------------------------ run
def _zone_mask(v: np.ndarray, f: np.ndarray, z: dict[str, Any]) -> np.ndarray:
    m = np.zeros(len(v), bool)
    if z.get('box'):
        lo, hi = np.asarray(z['box']['min'], float), np.asarray(z['box']['max'], float)
        m |= ((v >= lo) & (v <= hi)).all(1)
    if z.get('faces') is not None:
        ids = np.asarray(z['faces'], np.int64)
        m[np.unique(f[ids])] = True
    return m


def _faces_touching(f: np.ndarray, vmask: np.ndarray) -> np.ndarray:
    return vmask[f].any(1)


def run(req: dict[str, Any]) -> dict[str, Any]:
    import pymeshlab as pm
    t0 = time.time()
    out_dir = Path(req['out_dir'])
    out_dir.mkdir(parents=True, exist_ok=True)
    z = np.load(req['input_npz'], allow_pickle=False)
    v, f = z['vertices'].astype(np.float64), z['faces'].astype(np.int64)
    mode = req['mode']
    log_lines: list[str] = []

    def log(s: str) -> None:
        log_lines.append(s)
        print(s, file=sys.stderr, flush=True)
    topo_in = topology(v, f)
    centre = v.mean(0)
    res: dict[str, Any] = {'status': 'OK', 'worker': WORKER_VERSION, 'mode': mode, 'python': sys.version.split()[0], 'input_topology': _topology_dict(topo_in), 'log': log_lines}
    try:
        from importlib.metadata import version
        res['pymeshlab'] = version('pymeshlab')
    except Exception:
        res['pymeshlab'] = None
    rng = np.random.default_rng(3)
    tol = float(req['outside_tolerance_mm'])

    if mode == 'grooves':
        seeds = req['grooves']
        skin = Skin(v, f, seeds)
        log(f'skin: {skin.free_vertices} free vertices for the normal field')
        units: list[Unit] = []
        not_found: list[dict[str, Any]] = []
        for sd in seeds:
            r = build_unit(sd, v, f, skin, centre, log, bool(req.get('design_intent')))
            if isinstance(r, Unit):
                units.append(r)
                absent_all = all(sg['absent'] for sg in r.segments)
                if absent_all or (r.pres < 0.5).all():
                    not_found.append({'name': sd['name'], 'reason': f'fitted but shallower than {DF_MIN} mm or unfit everywhere: left original'})
            else:
                not_found.append({'name': sd['name'], **r})
        active = [u for u in units if (u.pres > 0.5).any()]
        if not active:
            res['not_found'] = not_found
            res['units'] = []
            res['edited'] = False
            res['seconds'] = round(time.time() - t0, 1)
            return res
        V2, F2, Vn, owner, info = apply_units(v, f, active, log, float(req['max_zone_deviation_mm']))
        res['not_found'] = [n for n in not_found if n['name'] not in {u.name for u in active}]
        edited_groups = [(u.name, k) for k, u in enumerate(active)]
    else:
        zones = req['zones']
        zmask = np.zeros(len(v), bool)
        zinfo = []
        for zz in zones:
            m = _zone_mask(v, f, zz)
            zinfo.append({'name': zz['name'], 'vertices': int(m.sum())})
            zmask |= m
        if not zmask.any():
            return {**res, 'status': 'FAILED', 'error': {'code': 'SCAN_CLEAN_ZONE_EMPTY', 'message': 'No vertex lies in any zone box or face selection.'}}
        Vn, zi = zone_repair(v, f, np.flatnonzero(zmask), float(req['max_zone_deviation_mm']))
        V2, F2 = v, f
        owner = np.where(zmask, 0, -1)
        info = {'zones': zinfo, **zi}
        active = []
        edited_groups = [('zones', 0)]
        res['not_found'] = []

    moved = np.linalg.norm(Vn - V2, axis=1) > 1e-9
    res['edit_info'] = info
    res['edited'] = bool(moved.any())
    topo = topology(Vn, F2)
    res['topology'] = _topology_dict(topo)
    res['vertices_displaced'] = int(moved.sum())
    res['max_displacement_mm'] = float(np.linalg.norm(Vn - V2, axis=1).max())

    # files, then the checks read THE FILES back
    write_stl(out_dir / 'cleaned.stl', Vn, F2)
    write_ply(out_dir / 'cleaned.ply', Vn, F2)
    _, _, disk = read_stl_topology(out_dir / 'cleaned.stl')
    res['stl_topology_on_disk'] = _topology_dict(disk)
    res['files'] = {'stl': 'cleaned.stl', 'ply': 'cleaned.ply'}

    # deviations
    tm = cKDTree(Vn[moved]) if moved.any() else None
    cen0 = v[f].mean(1)
    if tm is not None:
        dz = tm.query(cen0, workers=-1)[0]
        near = np.flatnonzero(dz < 6)
        P = sample_faces(v, f, near, dens=1e-9, seed=3, minimum=3)
        P = P[tm.query(P, workers=-1)[0] > OUTSIDE_MARGIN_MM]
        if len(P) > 400000:
            P = P[rng.choice(len(P), 400000, replace=False)]
        d_out = dist_to_mesh(pm, P, Vn, F2)
        res['outside_zone_deviation'] = {**_pcts(d_out), 'definition': 'original surface samples farther than 0.6 mm from any moved vertex (within 6 mm of the edit; the margin covers the longest original edges, so a face that straddles the edit border is not counted as outside) to the cleaned mesh, mm',
                                         'tolerance_mm': tol, 'n_over_tolerance': int((d_out > tol).sum())}
        inzone = np.flatnonzero(dz <= 0.4)
        P = sample_faces(v, f, inzone, dens=1e-9, seed=4, minimum=4) if len(inzone) else np.zeros((0, 3))
        if len(P) > 400000:
            P = P[rng.choice(len(P), 400000, replace=False)]
        res['original_to_cleaned_in_zone'] = _pcts(dist_to_mesh(pm, P, Vn, F2))
    else:
        res['outside_zone_deviation'] = {'samples': 0, 'tolerance_mm': tol, 'n_over_tolerance': 0}
        res['original_to_cleaned_in_zone'] = {'samples': 0}

    per: dict[str, Any] = {}
    for name, k in edited_groups:
        fk = np.flatnonzero((owner[F2] == k).any(1)) if mode == 'grooves' else np.flatnonzero(moved[F2].any(1))
        if not len(fk):
            continue
        P = sample_faces(Vn, F2, fk, dens=1e-9, seed=5, minimum=1)
        d = dist_to_mesh(pm, P, v, f)
        per[name] = {'cleaned_to_original': _pcts(d), 'faces': int(len(fk)), 'vertices_displaced': int((owner == k).sum() if mode == 'grooves' else moved.sum())}
    res['per_edit_deviation'] = per

    # roughness b3 (normal scatter, degrees), original faces vs cleaned faces round each groove
    rough: dict[str, Any] = {}
    if mode == 'grooves':
        cn = Vn[F2].mean(1)
        for un in active:
            lim = 1.2
            sel_old = np.flatnonzero(_near_groove(un, cen0, lim))
            sel_new = np.flatnonzero(_near_groove(un, cn, lim))
            if len(sel_old) and len(sel_new):
                a = b3_subset(v, f, rng.choice(sel_old, min(1500, len(sel_old)), replace=False))
                b = b3_subset(Vn, F2, rng.choice(sel_new, min(1500, len(sel_new)), replace=False))
                rough[un.name] = {'b3_median_deg_original': float(np.median(a)), 'b3_median_deg_cleaned': float(np.median(b)), 'b3_mean_deg_original': float(a.mean()),
                                  'b3_mean_deg_cleaned': float(b.mean()), 'faces_original': int(len(sel_old)), 'faces_cleaned': int(len(sel_new)),
                                  'definition': 'sqrt of the smallest eigenvalue of the area-weighted face-normal covariance within 1.5 mm, faces with |u|<1.2 mm of the centre line'}
    else:
        zf_old = np.flatnonzero(zmask[f].all(1))
        zf_new = np.flatnonzero(zmask[F2].all(1))
        if len(zf_old) > 10:
            a = b3_subset(v, f, rng.choice(zf_old, min(1500, len(zf_old)), replace=False))
            b = b3_subset(Vn, F2, rng.choice(zf_new, min(1500, len(zf_new)), replace=False))
            rough['zones'] = {'b3_median_deg_original': float(np.median(a)), 'b3_median_deg_cleaned': float(np.median(b)), 'b3_mean_deg_original': float(a.mean()),
                              'b3_mean_deg_cleaned': float(b.mean()), 'faces_original': int(len(zf_old)), 'faces_cleaned': int(len(zf_new))}
    res['roughness'] = rough

    # self intersection (PyMeshLab face selection; known to over-report on refined meshes, so it is never a PASS on its own)
    si0, si1 = self_intersecting_faces(pm, v, f), self_intersecting_faces(pm, Vn, F2)
    res['self_intersection'] = {'faces_original': si0, 'faces_cleaned': si1}

    # groove records
    if mode == 'grooves':
        res['grooves'] = {}
        for un in active:
            res['grooves'][un.name] = groove_record(un)
        res['units'] = [u.name for u in active]
    res['seconds'] = round(time.time() - t0, 1)
    return res


def _near_groove(un: Unit, cen: np.ndarray, lim: float) -> np.ndarray:
    s, u, _, h, _ = un.curve.query(cen)
    _, p = un.th_at(s)
    return (np.abs(u) < lim) & (np.abs(h) < 2) & (p > 0)


def main(argv: list[str]) -> int:
    try:
        req = json.loads(Path(argv[1]).read_text(encoding='utf-8'))
        res = run(req)
    except ModuleNotFoundError as exc:
        res = {'status': 'FAILED', 'error': {'code': 'SCAN_PYTHON_NO_PYMESHLAB', 'message': f'Missing module in the scan python: {exc.name}.'}}
    except Exception as exc:
        res = {'status': 'FAILED', 'error': {'code': 'SCAN_CLEAN_WORKER', 'message': f'{type(exc).__name__}: {exc}', 'trace': traceback.format_exc()[-1800:]}}
    sys.stdout.write('\n' + json.dumps(_clean_json(res), allow_nan=False) + '\n')
    return 0 if res.get('status') == 'OK' else 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
