"""Click-panel groove rebuild on a welded scan mesh. SUBPROCESS WORKER (like scan_model_worker.py).

Run as:  <scan python> scan_click_grooves_worker.py request.json
The scan python needs numpy, scipy, trimesh, shapely and manifold3d (extra `scan-grooves`); Pillow is optional (overlay PNG).
PyMeshLab is not used here and is never imported. Request and result are JSON; the result is the last stdout line.

Method (generic: nothing is tied to one mouse; frame and geometry come from the mesh and the region labels):
  1. top-view outlines of the two click regions (projected faces), their closed union, the wheel window = the hole of the union that
     holds the wheel;
  2. centre-gap start lines = robust straight fit of each click's inner edge outside the window x range; perimeter start line = the outer
     ring of the closed union (minus the stretch next to the gap) as averaged straight lines (Douglas-Peucker on 0.5 mm bin means, total
     least squares per piece, corners at the intersections) with fillets of a radius fitted to the ring;
  3. slots = vertical-walled prisms of constant width, flat floor (depth below the locally smoothed panel surface), swept along the start
     lines; the perimeter slot path is shifted outward until it cannot encroach on the panel edge;
  4. wheel removal = a rounded-rectangle window (fitted to the notch edges) with a floor plane parallel to the fitted rim plane;
  5. exact boolean (manifold3d), weld, degenerate / zero-volume flap and splinter clean-up, single-body watertight check;
  6. measurements on the RESULT (width, depth, flatness, verticality, cut-through, bodies, volume).
"""
from __future__ import annotations
import json
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import numpy as np
from scipy.ndimage import distance_transform_edt, gaussian_filter1d, map_coordinates, maximum_filter1d
from scipy.spatial import cKDTree

WORKER_VERSION = 'scan_click_grooves/6'
UNIT_MM = {'mm': 1.0, 'cm': 10.0, 'm': 1000.0, 'in': 25.4}
STEP = 0.2                    # station spacing of the sweeps, mm
PIXEL = 0.1                   # height-field pixel, mm
ROLE_ALIASES = {'LC': 'left_click', 'left_click': 'left_click', 'RC': 'right_click', 'right_click': 'right_click', 'WH': 'wheel', 'wheel': 'wheel',
                'scroll_wheel': 'wheel', 'top_shell': 'top_shell', 'palm_shell': 'top_shell', 'bottom_plate': 'bottom_plate', 'B1': 'side_button_1',
                'side_button_1': 'side_button_1', 'B2': 'side_button_2', 'side_button_2': 'side_button_2'}


DEFAULTS = {'slot_width_mm': 0.5, 'slot_depth_mm': 2.0, 'panel_overlap_mm': 0.2, 'perimeter_clearance_mm': 0.005, 'fit_tolerance_mm': 0.2, 'fillet_radius_mm': None,
            'min_wall_mm': 0.0, 'rebuild_window': True, 'overlay': True, 'gap_clear_mm': 2.0, 'gap_front_margin_mm': 2.5, 'gap_overshoot_mm': 0.5,
            # G1.4 regular outline (lines + one fillet radius, symmetric where near-symmetric) and its gates
            'symmetric_outline': True, 'symmetry_tol_mm': 1.5, 'min_turn_deg': 10.0, 'merge_dev_mm': 0.4, 'concave_dev_mm': 1.5, 'overhang_mm': 0.5,
            'max_overhang_mm': 1.5, 'max_overhang_length_mm': 15.0, 'spike_width_mm': 2.0, 'roughness_max_dev_mm': 0.02, 'window_on_gap_tol_mm': 1.0,
            'mirror_plane': None, 'gap_snap_tol_mm': 2.0, 'min_corner_radius_mm': 0.5,
            # G1.5 window rule and its gate
            'window_source': 'envelope', 'window_corner_radius_mm': None, 'window_corner_frac': 0.8, 'window_clear_mm': 0.5, 'window_min_corner_radius_mm': 2.0,
            'window_aspect_min': 1.0, 'window_aspect_max': 4.0}


class GrooveError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


def _load_libs() -> SimpleNamespace:
    try:
        import manifold3d
        import shapely
        import trimesh
    except ImportError as exc:
        name = getattr(exc, 'name', None) or str(exc)
        raise GrooveError('CLICK_GROOVE_KERNEL_UNAVAILABLE', f'The boolean kernel / mesh libraries are missing in this python: {name}. '
                          'Install the optional extra scan-grooves (trimesh, shapely, manifold3d) into the scan python.', {'module': name}) from exc
    return SimpleNamespace(mf=manifold3d, shp=shapely, tm=trimesh)


# ------------------------------------------------------------------ height field and vertical rays (numpy only)
def raster_top(v: np.ndarray, f: np.ndarray, x0: float, x1: float, y0: float, y1: float, res: float = PIXEL) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Top surface height z(x, y) on a regular grid (max z of all faces covering a pixel centre); NaN where nothing covers it."""
    xs = np.arange(x0, x1, res)
    ys = np.arange(y0, y1, res)
    nx, ny = len(xs), len(ys)
    Z = np.full(nx * ny, -np.inf)
    T = v[f]
    lo, hi = T[:, :, :2].min(1), T[:, :, :2].max(1)
    keep = (hi[:, 0] >= x0) & (lo[:, 0] <= x1) & (hi[:, 1] >= y0) & (lo[:, 1] <= y1)
    T, lo, hi = T[keep], lo[keep], hi[keep]
    i0 = np.clip(np.ceil((lo[:, 0] - x0) / res - 1e-9).astype(int), 0, nx)
    i1 = np.clip(np.floor((hi[:, 0] - x0) / res + 1e-9).astype(int), -1, nx - 1)
    j0 = np.clip(np.ceil((lo[:, 1] - y0) / res - 1e-9).astype(int), 0, ny)
    j1 = np.clip(np.floor((hi[:, 1] - y0) / res + 1e-9).astype(int), -1, ny - 1)
    wx, wy = i1 - i0 + 1, j1 - j0 + 1
    ok = (wx > 0) & (wy > 0)
    T, i0, j0, wx, wy = T[ok], i0[ok], j0[ok], wx[ok], wy[ok]
    a, b, c = T[:, 0], T[:, 1], T[:, 2]
    det = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
    good = np.abs(det) > 1e-14
    a, b, c, det, i0, j0, wx, wy = a[good], b[good], c[good], det[good], i0[good], j0[good], wx[good], wy[good]

    def paint(sel: np.ndarray, dx: int, dy: int) -> None:
        aa, bb, cc, dd = a[sel], b[sel], c[sel], det[sel]
        px = x0 + (i0[sel] + dx) * res
        py = y0 + (j0[sel] + dy) * res
        l1 = ((bb[:, 1] - cc[:, 1]) * (px - cc[:, 0]) + (cc[:, 0] - bb[:, 0]) * (py - cc[:, 1])) / dd
        l2 = ((cc[:, 1] - aa[:, 1]) * (px - cc[:, 0]) + (aa[:, 0] - cc[:, 0]) * (py - cc[:, 1])) / dd
        l3 = 1.0 - l1 - l2
        inside = (l1 >= -1e-9) & (l2 >= -1e-9) & (l3 >= -1e-9)
        if inside.any():
            z = l1 * aa[:, 2] + l2 * bb[:, 2] + l3 * cc[:, 2]
            idx = (j0[sel] + dy) * nx + (i0[sel] + dx)
            np.maximum.at(Z, idx[inside], z[inside])
    small = (wx <= 10) & (wy <= 10)
    for dx in range(10):
        for dy in range(10):
            sel = np.flatnonzero(small & (wx > dx) & (wy > dy))
            if len(sel):
                paint(sel, dx, dy)
    for t in np.flatnonzero(~small):                      # a few large flat faces: one pixel block each
        gi, gj = np.meshgrid(i0[t] + np.arange(wx[t]), j0[t] + np.arange(wy[t]))
        px, py = x0 + gi.ravel() * res, y0 + gj.ravel() * res
        l1 = ((b[t, 1] - c[t, 1]) * (px - c[t, 0]) + (c[t, 0] - b[t, 0]) * (py - c[t, 1])) / det[t]
        l2 = ((c[t, 1] - a[t, 1]) * (px - c[t, 0]) + (a[t, 0] - c[t, 0]) * (py - c[t, 1])) / det[t]
        l3 = 1.0 - l1 - l2
        inside = (l1 >= -1e-9) & (l2 >= -1e-9) & (l3 >= -1e-9)
        z = l1 * a[t, 2] + l2 * b[t, 2] + l3 * c[t, 2]
        idx = gj.ravel() * nx + gi.ravel()
        np.maximum.at(Z, idx[inside], z[inside])
    Z[~np.isfinite(Z)] = np.nan
    return xs, ys, Z.reshape(ny, nx)


class VerticalHits:
    """All z where the vertical line through (x, y) crosses the mesh (cell-bucketed triangles)."""

    def __init__(self, v: np.ndarray, f: np.ndarray, cell: float = 1.0):
        self.T = v[f]
        self.cell = cell
        lo = self.T[:, :, :2].min(1)
        hi = self.T[:, :, :2].max(1)
        self.buckets: dict[tuple[int, int], list[int]] = {}
        ci0 = np.floor(lo / cell).astype(int)
        ci1 = np.floor(hi / cell).astype(int)
        for t in range(len(f)):
            for i in range(ci0[t, 0], ci1[t, 0] + 1):
                for j in range(ci0[t, 1], ci1[t, 1] + 1):
                    self.buckets.setdefault((i, j), []).append(t)
        self.buckets = {k: np.asarray(val) for k, val in self.buckets.items()}

    def hits(self, xy: np.ndarray) -> list[np.ndarray]:
        xy = np.asarray(xy, float) + np.array([1.7e-7, 2.3e-7])      # off exact edges
        out: list[np.ndarray] = [np.zeros(0) for _ in range(len(xy))]
        cells = np.floor(xy / self.cell).astype(int)
        order = np.lexsort((cells[:, 1], cells[:, 0]))
        start = 0
        while start < len(order):
            c0 = tuple(cells[order[start]])
            end = start
            while end < len(order) and tuple(cells[order[end]]) == c0:
                end += 1
            ids = order[start:end]
            cand = self.buckets.get(c0)
            if cand is not None:
                t = self.T[cand]
                p = xy[ids]
                a, b, c = t[:, 0], t[:, 1], t[:, 2]
                det = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
                okd = np.abs(det) > 1e-14
                a, b, c, det = a[okd], b[okd], c[okd], det[okd]
                px, py = p[:, 0][:, None], p[:, 1][:, None]
                l1 = ((b[:, 1] - c[:, 1])[None] * (px - c[:, 0][None]) + (c[:, 0] - b[:, 0])[None] * (py - c[:, 1][None])) / det[None]
                l2 = ((c[:, 1] - a[:, 1])[None] * (px - c[:, 0][None]) + (a[:, 0] - c[:, 0])[None] * (py - c[:, 1][None])) / det[None]
                l3 = 1 - l1 - l2
                ins = (l1 > 0) & (l2 > 0) & (l3 > 0)
                z = l1 * a[:, 2][None] + l2 * b[:, 2][None] + l3 * c[:, 2][None]
                for k, pid in enumerate(ids):
                    out[pid] = np.sort(z[k][ins[k]])
            start = end
        return out

    def top(self, xy: np.ndarray) -> np.ndarray:
        h = self.hits(xy)
        return np.array([x[-1] if len(x) else np.nan for x in h])


# ------------------------------------------------------------------ planar geometry helpers
def resample(A: np.ndarray, step: float = STEP) -> tuple[np.ndarray, np.ndarray]:
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(A, axis=0), axis=1))]
    n = max(2, int(np.ceil(s[-1] / step)) + 1)
    t = np.linspace(0, s[-1], n)
    return np.c_[np.interp(t, s, A[:, 0]), np.interp(t, s, A[:, 1])], t


def tls_line(P: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    c = P.mean(0)
    _, _, vt = np.linalg.svd(P - c)
    return c, vt[0]


def lines_intersect(c1, d1, c2, d2):
    M = np.array([d1, -d2]).T
    if abs(np.linalg.det(M)) < 1e-9:
        return None
    t = np.linalg.solve(M, c2 - c1)
    return c1 + t[0] * d1


def dp_indices(pts: np.ndarray, tol: float) -> list[int]:
    def rec(i: int, j: int) -> list[int]:
        if j <= i + 1:
            return [i, j]
        a, b = pts[i], pts[j]
        d = b - a
        L = np.linalg.norm(d)
        if L < 1e-12:
            return [i, j]
        n = np.array([-d[1], d[0]]) / L
        dist = np.abs((pts[i + 1:j] - a) @ n)
        k = int(dist.argmax())
        if dist[k] > tol:
            return rec(i, i + 1 + k)[:-1] + rec(i + 1 + k, j)
        return [i, j]
    return rec(0, len(pts) - 1)


def seg_dist(P: np.ndarray, A: np.ndarray, closed: bool = False) -> np.ndarray:
    if closed:
        A = np.vstack([A, A[:1]])
    d = np.full(len(P), 1e9)
    for a, b in zip(A[:-1], A[1:]):
        ab = b - a
        den = ab @ ab
        if den < 1e-18:
            continue
        t = np.clip(((P - a) @ ab) / den, 0, 1)
        d = np.minimum(d, np.linalg.norm(P - (a + t[:, None] * ab), axis=1))
    return d


def fillet_open(Pq: np.ndarray, R, step_deg: float = 1.5, clip: float = 0.45) -> np.ndarray:
    """Round every interior vertex of an open polyline with radius R (a number, or one radius per interior vertex; clipped to clip x the
    adjacent pieces)."""
    out = [Pq[0]]
    Rs = np.broadcast_to(np.asarray(R, float), (max(len(Pq) - 2, 0),)) if np.ndim(R) == 0 else np.asarray(R, float)
    for i in range(1, len(Pq) - 1):
        R = float(Rs[i - 1])
        a, b, c = Pq[i - 1], Pq[i], Pq[i + 1]
        la, lc = np.linalg.norm(a - b), np.linalg.norm(c - b)
        if la < 1e-9 or lc < 1e-9:
            continue
        u, w = (a - b) / la, (c - b) / lc
        ang = np.arccos(np.clip(u @ w, -1, 1))
        if np.pi - ang < 1e-3:
            out.append(b)
            continue
        t = min(R / np.tan(ang / 2), clip * la, clip * lc)
        r_eff = t * np.tan(ang / 2)
        p1, p2 = b + u * t, b + w * t
        bis = u + w
        bis /= np.linalg.norm(bis)
        cen = b + bis * (r_eff / np.sin(ang / 2))
        a1 = np.arctan2(*(p1 - cen)[::-1])
        a2 = np.arctan2(*(p2 - cen)[::-1])
        da = (a2 - a1 + np.pi) % (2 * np.pi) - np.pi
        n = max(2, int(abs(np.degrees(da)) / step_deg))
        for s in np.linspace(0, 1, n + 1):
            out.append(cen + r_eff * np.array([np.cos(a1 + da * s), np.sin(a1 + da * s)]))
    out.append(Pq[-1])
    return np.array(out)


def fillet_closed(C: np.ndarray, R: float, step_deg: float = 1.5) -> np.ndarray:
    out = []
    n = len(C)
    for i in range(n):
        a, b, c = C[i - 1], C[i], C[(i + 1) % n]
        u, w = (a - b) / np.linalg.norm(a - b), (c - b) / np.linalg.norm(c - b)
        ang = np.arccos(np.clip(u @ w, -1, 1))
        t = R / np.tan(ang / 2)
        p1, p2 = b + u * t, b + w * t
        bis = u + w
        bis /= np.linalg.norm(bis)
        cen = b + bis * (R / np.sin(ang / 2))
        a1 = np.arctan2(*(p1 - cen)[::-1])
        a2 = np.arctan2(*(p2 - cen)[::-1])
        da = (a2 - a1 + np.pi) % (2 * np.pi) - np.pi
        m = max(2, int(abs(np.degrees(da)) / step_deg))
        for s in np.linspace(0, 1, m + 1):
            out.append(cen + R * np.array([np.cos(a1 + da * s), np.sin(a1 + da * s)]))
    return np.array(out)


def robust_line(t: np.ndarray, v: np.ndarray, floor: float = 0.05, iters: int = 4) -> np.ndarray:
    """v = p0 t + p1 with iterative 2.5 sigma clipping."""
    for _ in range(iters):
        p = np.polyfit(t, v, 1)
        r = v - np.polyval(p, t)
        k = np.abs(r) < max(2.5 * r.std(), floor)
        if k.all() or k.sum() < 4:
            break
        t, v = t[k], v[k]
    return np.polyfit(t, v, 1)


def fit_polyline(T: np.ndarray, tol: float, bin_mm: float = 0.5) -> np.ndarray:
    """Averaged straight pieces through an ordered point chain; vertices at the intersections of consecutive pieces."""
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(T, axis=0), axis=1))]
    bx = np.floor(s / bin_mm).astype(int)
    ub = np.unique(bx)
    Tm = np.array([T[bx == i].mean(0) for i in ub])
    Tb = np.array([s[bx == i].mean() for i in ub])
    idx = dp_indices(Tm, tol)
    segs, cuts = [], []
    for a, b in zip(idx[:-1], idx[1:]):
        sel = T[(s >= Tb[a] - bin_mm / 2 - 0.01) & (s <= Tb[b] + bin_mm / 2 + 0.01)]
        if len(sel) < 2:
            continue
        segs.append(tls_line(sel))
        cuts.append(Tm[b])
    if not segs:
        raise GrooveError('CLICK_GROOVE_PERIMETER_FIT', 'The perimeter chain could not be fitted by straight pieces.')
    verts = []
    for i in range(len(segs) - 1):
        p = lines_intersect(*segs[i], *segs[i + 1])
        if p is None or np.linalg.norm(p - cuts[i]) > 3.0:
            p = cuts[i]
        verts.append(p)
    c0, d0 = segs[0]
    c1, d1 = segs[-1]
    start = c0 + ((T[0] - c0) @ d0) * d0
    end = c1 + ((T[-1] - c1) @ d1) * d1
    return np.vstack([start[None], np.array(verts).reshape(-1, 2), end[None]])


def _dir_along(P: np.ndarray, d: np.ndarray) -> np.ndarray:
    return d if (P[-1] - P[0]) @ d >= 0 else -d


def fit_lines_regular(T: np.ndarray, tol: float, bin_mm: float = 0.5, min_turn_deg: float = 10.0, merge_dev_mm: float = 0.4,
                      concave_dev_mm: float = 1.5, min_piece_mm: float = 4.0) -> dict[str, Any]:
    """Regularised straight pieces through an ordered (open) point chain: Douglas-Peucker on bin means, total least squares per piece, then
    pieces are merged while a joint has a turn below min_turn_deg (scan noise kink) or turns against the dominant direction (wave / step)
    and the merged piece still fits its points (p95 distance <= merge_dev_mm, <= concave_dev_mm for an opposite turn). Vertices at the
    intersections of consecutive lines. A piece shorter than min_piece_mm (chord) is always merged into the neighbour it fits best: corners
    are rounded by the fillets, never by short pieces. Returns {'verts', 'lines': [(c, d)], 'groups': [(s0, s1)], 'merged': n, 'opposite_turns_kept': n}."""
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(T, axis=0), axis=1))]
    bx = np.floor(s / bin_mm).astype(int)
    ub = np.unique(bx)
    Tm = np.array([T[bx == i].mean(0) for i in ub])
    Tb = np.array([s[bx == i].mean() for i in ub])
    idx = dp_indices(Tm, tol)
    groups = [(Tb[a] - bin_mm / 2 - 0.01, Tb[b] + bin_mm / 2 + 0.01) for a, b in zip(idx[:-1], idx[1:])]
    groups[0] = (s[0] - 1.0, groups[0][1])
    groups[-1] = (groups[-1][0], s[-1] + 1.0)

    def pts(g):
        return T[(s >= g[0]) & (s <= g[1])]

    def line(g):
        sel = pts(g)
        if len(sel) < 2:
            return None, sel
        c, d = tls_line(sel)
        return (c, _dir_along(sel, d)), sel
    merged = 0
    while True:
        lines = [line(g)[0] for g in groups]
        if any(ln is None for ln in lines):
            k = next(i for i, ln in enumerate(lines) if ln is None)
            j = k - 1 if k > 0 else k + 1
            if len(groups) == 1:
                raise GrooveError('CLICK_GROOVE_PERIMETER_FIT', 'The perimeter chain could not be fitted by straight pieces.')
            a, b = sorted((j, k))
            groups[a:b + 1] = [(groups[a][0], groups[b][1])]
            continue
        if len(groups) < 2:
            break
        chords = [np.linalg.norm(pts(g)[-1] - pts(g)[0]) for g in groups]
        short = [i for i, c in enumerate(chords) if c < min_piece_mm]
        if short:
            i = min(short, key=lambda q: chords[q])
            opts = [j for j in (i - 1, i + 1) if 0 <= j < len(groups)]
            def mdev(j):
                a, b = sorted((i, j))
                ln, sel = line((groups[a][0], groups[b][1]))
                return np.inf if ln is None else float(np.percentile(np.abs((sel - ln[0]) @ np.array([-ln[1][1], ln[1][0]])), 95))
            j = min(opts, key=mdev)
            a, b = sorted((i, j))
            groups[a:b + 1] = [(groups[a][0], groups[b][1])]
            merged += 1
            continue
        turns = np.array([np.arctan2(lines[i][1][0] * lines[i + 1][1][1] - lines[i][1][1] * lines[i + 1][1][0], lines[i][1] @ lines[i + 1][1])
                          for i in range(len(lines) - 1)])
        dom = np.sign(turns.sum()) or 1.0
        best = None
        for i, t in enumerate(turns):
            opposite = np.sign(t) != dom and abs(t) > 1e-9
            if abs(t) >= np.radians(min_turn_deg) and not opposite:
                continue
            g = (groups[i][0], groups[i + 1][1])
            ln, sel = line(g)
            if ln is None:
                continue
            c, d = ln
            dev = float(np.percentile(np.abs((sel - c) @ np.array([-d[1], d[0]])), 95))
            lim = concave_dev_mm if opposite else merge_dev_mm
            if dev <= lim and (best is None or dev < best[0]):
                best = (dev, i)
        if best is None:
            break
        i = best[1]
        groups[i:i + 2] = [(groups[i][0], groups[i + 1][1])]
        merged += 1
    lines = [line(g)[0] for g in groups]
    verts = []
    for i in range(len(lines) - 1):
        p = lines_intersect(*lines[i], *lines[i + 1])
        cut = T[np.argmin(np.abs(s - groups[i][1]))]
        if p is None or np.linalg.norm(p - cut) > 3.0:
            p = cut
        verts.append(p)
    c0, d0 = lines[0]
    c1, d1 = lines[-1]
    start = c0 + ((T[0] - c0) @ d0) * d0
    end = c1 + ((T[-1] - c1) @ d1) * d1
    turns = [np.arctan2(lines[i][1][0] * lines[i + 1][1][1] - lines[i][1][1] * lines[i + 1][1][0], lines[i][1] @ lines[i + 1][1]) for i in range(len(lines) - 1)]
    dom = np.sign(sum(turns)) or 1.0
    return {'verts': np.vstack([start[None], np.array(verts).reshape(-1, 2), end[None]]), 'lines': lines, 'groups': groups, 'merged': merged,
            'opposite_turns_kept': int(sum(1 for t in turns if np.sign(t) != dom and abs(t) > 1e-9))}


def select_radii(path: np.ndarray, raw: np.ndarray, r_min: float = 0.5, r_max: float = 60.0, slack_mm: float = 0.01, clip: float = 0.49) -> np.ndarray:
    """One fillet radius per interior vertex: the largest radius (r_min..r_max, clipped by clip x the adjacent pieces) whose local rounded
    corner fits the raw outline points near the vertex as well as the best radius (rms within slack_mm). A sharp corner keeps a small
    radius; a polygonal stretch over a round outline becomes a chain of tangent arcs (G1)."""
    cands = np.unique(np.r_[r_min, np.geomspace(max(r_min, 0.1), r_max, 40)])
    out = []
    for i in range(1, len(path) - 1):
        a, b, c = path[i - 1], path[i], path[i + 1]
        la, lc = np.linalg.norm(a - b), np.linalg.norm(c - b)
        rho = clip * min(la, lc)
        near = raw[np.linalg.norm(raw - b, axis=1) <= rho + 0.25]
        if len(near) < 5:
            out.append(r_min)
            continue
        rms = []
        for R in cands:
            loc = fillet_open(np.array([a, b, c]), R, clip=clip)
            rms.append(float(np.sqrt((seg_dist(near, loc) ** 2).mean())))
        rms = np.array(rms)
        ok = rms <= rms.min() + slack_mm
        out.append(float(cands[ok].max()))
    return np.array(out)


def outline_roughness(P: np.ndarray, step: float = 0.2, win_mm: float = 6.0, kappa_win_mm: float = 3.0, kappa_eps: float = 0.02,
                      corner_kappa: float = 0.1) -> dict[str, Any]:
    """Roughness of a plan outline (open polyline, mm): resampled at step; smooth_dev = distance from its Savitzky-Golay smoothed fit
    (cubic, win_mm window) on the straight / gently curved stretches (stations farther than win_mm / 2 from a corner, |curvature| >
    corner_kappa); curvature sign changes = changes between turning left and right (|curvature| > kappa_eps, cubic SG over kappa_win_mm).
    A clean outline of straight lines and constant-radius arcs that turns one way has smooth_dev ~ 0 and no sign change."""
    from scipy.signal import savgol_filter
    Q, _ = resample(np.asarray(P, float), step)
    w = int(round(win_mm / step)) | 1
    kw = int(round(kappa_win_mm / step)) | 1
    if len(Q) < w + 2:
        return {'stations': int(len(Q)), 'smooth_dev_max_mm': 0.0, 'smooth_dev_p95_mm': 0.0, 'curvature_sign_changes': 0, 'note': 'too short to measure'}
    d1 = np.c_[savgol_filter(Q[:, 0], kw, 3, deriv=1), savgol_filter(Q[:, 1], kw, 3, deriv=1)]
    d2 = np.c_[savgol_filter(Q[:, 0], kw, 3, deriv=2), savgol_filter(Q[:, 1], kw, 3, deriv=2)]
    kap = (d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / (np.linalg.norm(d1, axis=1) ** 3 + 1e-12) / step
    Qs = np.c_[savgol_filter(Q[:, 0], w, 3), savgol_filter(Q[:, 1], w, 3)]
    dev = np.linalg.norm(Q - Qs, axis=1)
    corner = maximum_filter1d((np.abs(kap) > corner_kappa).astype(np.uint8), size=w) > 0
    flat = ~corner
    flat[: w // 2] = False
    flat[-(w // 2):] = False
    sg = np.sign(kap) * (np.abs(kap) > kappa_eps)
    sg[: kw // 2] = 0                                   # Savitzky-Golay end effect: the half window at each open end is not judged
    sg[len(sg) - kw // 2:] = 0
    nzi = np.flatnonzero(sg != 0)
    nz = sg[nzi]
    chg = nzi[1:][np.diff(nz) != 0] if len(nz) > 1 else np.zeros(0, int)
    return {'stations': int(len(Q)), 'smooth_dev_max_mm': float(dev[flat].max()) if flat.any() else 0.0,
            'smooth_dev_p95_mm': float(np.percentile(dev[flat], 95)) if flat.any() else 0.0,
            'curvature_sign_changes': int(len(chg)), 'sign_change_xy': Q[chg].round(2).tolist()[:20], 'curvature_max_per_mm': float(np.abs(kap).max()),
            'method': {'step_mm': step, 'smooth_window_mm': win_mm, 'curvature_window_mm': kappa_win_mm, 'kappa_eps_per_mm': kappa_eps, 'corner_kappa_per_mm': corner_kappa}}


# ------------------------------------------------------------------ input
def read_labels(path: Path, n_faces: int) -> dict[str, np.ndarray]:
    """Region face ids by role. .json: {role: [ids]} or {"regions": {role: {"face_ids": [...]} | [...]}}; .npz: face_labels + codes ('name=code')."""
    suffix = path.suffix.lower()
    raw: dict[str, np.ndarray] = {}
    if suffix == '.npz':
        z = np.load(path, allow_pickle=False)
        if 'face_labels' not in z or 'codes' not in z:
            raise GrooveError('CLICK_GROOVE_LABELS', 'An .npz label file needs the arrays face_labels and codes ("name=code").')
        fl = z['face_labels']
        if len(fl) != n_faces:
            raise GrooveError('CLICK_GROOVE_LABELS', 'face_labels has a different length than the mesh has faces.', {'labels': int(len(fl)), 'faces': int(n_faces)})
        for item in z['codes']:
            name, code = str(item).rsplit('=', 1)
            raw[name] = np.flatnonzero(fl == int(code))
    else:
        data = json.loads(path.read_text(encoding='utf-8'))
        data = data.get('regions', data) if isinstance(data, dict) else data
        if not isinstance(data, dict):
            raise GrooveError('CLICK_GROOVE_LABELS', 'The label JSON must map region names to face id lists.')
        for k, val in data.items():
            ids = val.get('face_ids') if isinstance(val, dict) else val
            if isinstance(ids, list):
                raw[k] = np.asarray(ids, dtype=np.int64)
    roles: dict[str, np.ndarray] = {}
    for k, ids in raw.items():
        role = ROLE_ALIASES.get(k)
        if role is None:
            continue
        if len(ids) and (ids.min() < 0 or ids.max() >= n_faces):
            raise GrooveError('CLICK_GROOVE_LABELS', f'Region {k} has face ids outside the mesh.', {'region': k})
        roles[role] = np.unique(ids)
    for need in ('left_click', 'right_click'):
        if need not in roles or len(roles[need]) < 20:
            raise GrooveError('CLICK_GROOVE_REGIONS_MISSING', f'The label file has no usable {need} region (needs left_click and right_click; wheel is optional).', {'found': sorted(roles)})
    return roles


# ------------------------------------------------------------------ the pipeline
def run(req: dict[str, Any]) -> dict[str, Any]:
    t_start = time.time()
    L = _load_libs()
    tm, mf, shp = L.tm, L.mf, L.shp
    P = {**DEFAULTS, **req['params']}
    W, DEPTH, OVERLAP = float(P['slot_width_mm']), float(P['slot_depth_mm']), float(P['panel_overlap_mm'])
    warnings: list[dict[str, Any]] = []
    src_mesh = tm.load(req['input_path'], force='mesh', process=False)
    src_mesh.merge_vertices()                                  # STL stores triangle soup; faces and their order are unchanged
    scale = float(req['unit_scale'])
    V = np.asarray(src_mesh.vertices, float) * scale
    F = np.asarray(src_mesh.faces, np.int64)
    src = tm.Trimesh(V, F, process=False)
    N = len(F)
    if not src.is_watertight or src.volume <= 0:
        raise GrooveError('CLICK_GROOVE_MESH_NOT_WATERTIGHT', 'The input mesh must be welded, watertight and outward oriented (run brain_mouse_scan_model first).',
                          {'watertight': bool(src.is_watertight), 'volume_mm3': float(src.volume)})
    roles = read_labels(Path(req['labels_path']), N)
    lab = np.full(N, -1, np.int64)
    role_names = sorted(roles)
    for i, name in enumerate(role_names):
        lab[roles[name]] = i
    # ---- outlines
    polys = {}
    for name in ('left_click', 'right_click'):
        polys[name] = _region_polygon(shp, V, F, roles[name])
    cy = {k: float(p.centroid.y) for k, p in polys.items()}
    if abs(cy['left_click'] - cy['right_click']) < 2.0:
        raise GrooveError('CLICK_GROOVE_FRAME', 'The two click regions are not separated along y; the mesh must be in the standard frame (x front, y left, z up).',
                          {'centroid_y': cy})
    upper, lower = (('left_click', 'right_click') if cy['left_click'] > cy['right_click'] else ('right_click', 'left_click'))
    PA, PB = polys[upper], polys[lower]
    closing = 1.0
    union = shp.union_all([PA, PB]).buffer(closing, 16).buffer(-closing, 16)
    if union.geom_type == 'MultiPolygon':
        union = max(union.geoms, key=lambda g: g.area)
    xmin, ymin, xmax, ymax = union.bounds
    # ---- height field of the source
    mx0, mx1, my0, my1 = xmin - 3, xmax + 3, ymin - 3, ymax + 3
    xs, ys, Z0 = raster_top(V, F, mx0, mx1, my0, my1)
    bad = ~np.isfinite(Z0)
    Zf = Z0.copy()
    if bad.any():
        Zf = Zf[tuple(distance_transform_edt(bad, return_distances=False, return_indices=True))]

    def zf(x, y):
        return map_coordinates(Zf, [(np.asarray(y) - ys[0]) / PIXEL, (np.asarray(x) - xs[0]) / PIXEL], order=1, mode='nearest')
    # ---- window (hole of the closed union that holds the wheel)
    window = None
    if P['rebuild_window'] and 'wheel' in roles:
        window = _fit_window(shp, V, F, roles['wheel'], union, PA, PB, zf, warnings, P)
    wx_range = (window['hole'].bounds[0], window['hole'].bounds[2]) if window else None
    # ---- gap start lines
    gap = _fit_gap_lines(shp, PA, PB, xmin, xmax, wx_range, float(P['gap_front_margin_mm']))
    _snap_gap_to_plane(gap, P.get('mirror_plane'), xmin, xmax, float(P['gap_snap_tol_mm']))
    if window:
        _finish_window(window, V, F, zf, gap, P, shp, warnings)
        if window.get('failed'):
            window = None
    # ---- perimeter start line
    per = _perimeter(shp, union, PA, PB, gap, P, warnings)
    cutters: list[Any] = []
    sweeps: dict[str, dict[str, Any]] = {}
    infos: list[dict[str, Any]] = []
    min_wall = float(P['min_wall_mm'])
    wall_tree = None
    if min_wall > 0:
        pts, _ = tm.sample.sample_surface(src, 200000, seed=20260917)
        wall_tree = (cKDTree(np.vstack([pts, V])), np.vstack([pts, V])[:, 2])
    out = per['out']
    sg = 1.0 if out > 0 else -1.0
    o1, o2 = (0.0, W) if sg > 0 else (-W, 0.0)
    m, info, pa = _sweep(per['A'], o1, o2, lambda Q, nrm: zf(*(Q - sg * nrm * 0.05).T), DEPTH, zf, 'perimeter', wall_tree=wall_tree, min_wall=min_wall)
    m = _orient(tm, m)
    cutters.append(m)
    infos.append(info)
    pa['panel_side'] = 'lo' if sg > 0 else 'hi'
    sweeps['perimeter'] = pa
    gl = gap['mid']
    runs = [('gap', xmin - float(P['gap_overshoot_mm']), xmax + float(P['gap_overshoot_mm']))]
    PF = None
    if window:
        xl, xr = window['gap_x_range']
        runs = [('gap_rear', xmin - float(P['gap_overshoot_mm']), xl + 0.15), ('gap_front', xr - 0.15, xmax + float(P['gap_overshoot_mm']))]
        PF = window['PF']
    for name, x0, x1 in runs:
        if x1 - x0 < 0.5:
            continue
        for who, ln, (a1, a2), side in ((upper, gap['upper'], (-W, OVERLAP), 'hi'), (lower, gap['lower'], (-OVERLAP, W), 'lo')):
            xx = np.array([x0, x1])
            G = np.c_[xx, ln[0] * xx + ln[1]]
            m, info, pa = _sweep(G, a1, a2, lambda Q, nrm: 0.5 * (zf(*(Q + 0.9 * nrm).T) + zf(*(Q - 0.9 * nrm).T)), DEPTH, zf, f'{name}_{who}',
                                 blend=(window['poly_geom'], PF) if window else None, wall_tree=wall_tree, min_wall=min_wall)
            m = _orient(tm, m)
            cutters.append(m)
            infos.append(info)
            pa['panel_side'] = side
            sweeps[f'{name}_{who}'] = pa
    # ---- boolean
    def tomf(mesh, face_id):
        return mf.Manifold(mf.Mesh(np.asarray(mesh.vertices, np.float32), np.asarray(mesh.faces, np.uint32), face_id=np.asarray(face_id, np.uint32)))
    M = tomf(src, np.arange(N))
    if M.status() != mf.Error.NoError:
        raise GrooveError('CLICK_GROOVE_BOOLEAN_INPUT', f'The input mesh is not a valid manifold for the boolean kernel ({M.status()}).')
    Cs = []
    for i, c in enumerate(cutters):
        mc = tomf(c, np.full(len(c.faces), N + 10 + i))
        if mc.status() != mf.Error.NoError:
            raise GrooveError('CLICK_GROOVE_CUTTER_INVALID', f'Slot cutter {infos[i]["tag"]} is not a valid manifold ({mc.status()}); a path radius is probably smaller than the slot width.', {'tag': infos[i]['tag']})
        Cs.append(mc)
    plug = None
    if window:
        pocket, plug = _pocket(mf, window, V)
        pocket = _tag(mf, pocket, N + 5)
        plug = _tag(mf, plug, N + 6)
        Cs.append(pocket)
    C = mf.Manifold.batch_boolean(Cs, mf.OpType.Add)
    R = (M + plug) - C if plug is not None else M - C
    mm = R.to_mesh()
    res, fid, cleanup = _cleanup(tm, np.asarray(mm.vert_properties)[:, :3].astype(float), np.asarray(mm.tri_verts), np.asarray(mm.face_id))
    # ---- labels of the result faces and outputs
    orig = fid < N
    Lres = np.full(len(fid), -1, np.int64)
    Lres[orig] = lab[fid[orig]]
    wheel_code = role_names.index('wheel') if 'wheel' in roles else -99
    cen = res.triangles_center
    donor = orig & (Lres != wheel_code)
    if (~orig).any() and donor.any():
        _, nn = cKDTree(cen[donor]).query(cen[~orig])
        Lres[~orig] = Lres[donor][nn]
    out_dir = Path(req['out_dir'])
    out_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, Any] = {}
    res.export(out_dir / 'combined_grooved.stl')
    files['combined'] = {'file': 'combined_grooved.stl', 'faces': int(len(res.faces))}
    regions_out: dict[str, Any] = {}
    for code, name in enumerate(role_names + ['other']):
        sel = Lres == (code if name != 'other' else -1)
        if not sel.any():
            continue
        part = tm.Trimesh(res.vertices, res.faces[sel], process=False)
        part.remove_unreferenced_vertices()
        fn = f'{name}.stl'
        part.export(out_dir / fn)
        regions_out[name] = {'file': fn, 'faces': int(sel.sum())}
    files['regions'] = regions_out
    layout = {'schema': 'click_slot_layout/1', 'frame': 'input mesh frame (mm): x front, y left, z up, plate z 0',
              'note': 'Plan (x, y) start lines of the slots, for brain_mouse_click_slots (B-rep). The slot band lies on slot_side of the travel direction.',
              'slot_width_mm': W, 'slot_depth_mm': DEPTH,
              'perimeter': {'points': np.asarray(per['A'], float).round(5).tolist(), 'slot_side': 'left' if per['out'] > 0 else 'right',
                            'allowed_curvature_sign_changes': 2 * int(per['symmetry'].get('opposite_turns_kept', 0)), 'symmetry_mode': per['symmetry']['mode']},
              'centre_gap': {'segments': [[[float(x0), float(gl[0] * x0 + gl[1])], [float(x1), float(gl[0] * x1 + gl[1])]] for _, x0, x1 in runs if x1 - x0 >= 0.5],
                             'width_mm': 2 * W, 'line': {'slope': float(gl[0]), 'intercept_y': float(gl[1])}},
              'window': ({'corners_TR_TL_BL_BR': window['corners_TR_TL_BL_BR'], 'corner_radius_mm': window['corner_radius_mm'], 'rim_plane': window['rim_plane'],
                          'floor_plane': window['floor_plane']} if window else None)}
    (out_dir / 'slot_layout.json').write_text(json.dumps(layout, default=_json_default), encoding='utf-8')
    files['layout'] = {'file': 'slot_layout.json'}
    # ---- measurements
    metrics = _measure(tm, shp, src, res, fid, N, V, F, sweeps, infos, window, gap, per, runs, cutters, DEPTH, W)
    metrics['volume'] = {'before_mm3': float(src.volume), 'after_mm3': float(res.volume), 'removed_mm3': float(src.volume - res.volume)}
    metrics['outline_quality'] = outline_quality(per, window, gap, P)
    metrics['watertight'] = {'before': bool(src.is_watertight), 'after': bool(res.is_watertight)}
    metrics['faces'] = {'before': int(N), 'after': int(len(res.faces))}
    metrics['cleanup'] = cleanup
    if cleanup['splinters_removed']:
        warnings.append({'code': 'SPLINTERS_REMOVED', 'count': len(cleanup['splinters_removed'])})
    if window and window.get('min_wall_raise_mm', 0) > 0:
        warnings.append({'code': 'WINDOW_FLOOR_RAISED_FOR_MIN_WALL', 'raise_mm': window['min_wall_raise_mm']})
    cut_runs = {k: v['cut_through_runs'] for k, v in metrics['cut_through'].items() if v['cut_through_runs']}
    if cut_runs:
        warnings.append({'code': 'CUT_THROUGH', 'note': 'The slot floor leaves the original solid (the wall below is thinner than the slot depth); allowed and reported.', 'where': cut_runs})
    overlay = None
    if P['overlay']:
        overlay = _overlay(out_dir, V, F, res, (xmin - 2, xmax + 2, ymin - 2, ymax + 2), warnings)
        if overlay:
            files['overlay'] = overlay
    params_used = {'slot_width_mm': W, 'slot_depth_mm': DEPTH, 'panel_overlap_mm': OVERLAP, 'perimeter_clearance_mm': float(P['perimeter_clearance_mm']),
                   'fit_tolerance_mm': float(P['fit_tolerance_mm']), 'min_wall_mm': min_wall, 'rebuild_window': bool(window),
                   'fillet_radius_mm': per['R'], 'fillet_radius_source': 'given' if P.get('fillet_radius_mm') else 'fitted to the outline',
                   'gap_clear_mm': float(P['gap_clear_mm']), 'gap_front_margin_mm': float(P['gap_front_margin_mm']), 'gap_overshoot_mm': float(P['gap_overshoot_mm']),
                   **{k: P[k] for k in ('spike_width_mm', 'symmetric_outline', 'symmetry_tol_mm', 'min_turn_deg', 'merge_dev_mm', 'concave_dev_mm', 'overhang_mm', 'max_overhang_mm',
                                        'max_overhang_length_mm', 'roughness_max_dev_mm', 'window_on_gap_tol_mm', 'min_corner_radius_mm', 'window_source',
                                        'window_corner_radius_mm', 'window_corner_frac', 'window_clear_mm', 'window_min_corner_radius_mm', 'window_aspect_min', 'window_aspect_max')}}
    fit = {'upper_click': upper, 'lower_click': lower, 'gap_start_lines': {k: {'slope': gap[k][0], 'intercept_y': gap[k][1], **gap[k + '_fit']} for k in ('upper', 'lower')},
           'gap_mid_line': {'slope': gap['mid'][0], 'intercept_y': gap['mid'][1]}, 'gap_mirror_plane': gap.get('mirror_plane'), 'gap_lines_merged': bool(gap['merged']), 'gap_line_separation_mm': gap['line_separation_mm'],
           'perimeter': {'vertices_after_fit': int(len(per['path'])), 'fillet_radius_mm': per['R'], 'fit_rms_mm': per['rms'], 'fit_max_mm': per['max'], 'stations': int(len(per['A'])),
                         'outward_sign_along_left_normal': per['out'], 'encroachment': per['encroachment']},
           'window': ({k: window[k] for k in ('corners_TR_TL_BL_BR', 'corner_radius_mm', 'dims_mm', 'rim_plane', 'floor_plane', 'gap_x_range', 'edge_fit_dev_mm', 'source', 'rim_detection', 'min_wall_raise_mm', 'gap_alignment', 'side_fits_uv', 'corner_fit_rms_mm')} if window else None),
           'slot_stations': {k: infos[i]['n'] for i, k in enumerate([x['tag'] for x in infos])}}
    return {'status': 'OK', 'worker': WORKER_VERSION, 'files': files, 'metrics': metrics, 'fit': fit, 'params_used': params_used, 'warnings': warnings,
            'seconds': round(time.time() - t_start, 1), 'libs': {'manifold3d': getattr(mf, '__version__', None), 'shapely': shp.__version__, 'trimesh': tm.__version__}}


def outline_quality(per: dict[str, Any], window: dict[str, Any] | None, gap: dict[str, Any], P: dict[str, Any]) -> dict[str, Any]:
    """Gate inputs: perimeter roughness (smooth_dev, curvature sign changes; allowed = 2 per deliberate concave corner the regular fit kept),
    and the window centre / axis relative to the centre-gap line."""
    allowed = 2 * int(per['symmetry'].get('opposite_turns_kept', 0))
    r = per['roughness']
    q = {'perimeter': {**r, 'allowed_sign_changes': allowed, 'max_dev_limit_mm': float(P['roughness_max_dev_mm']),
                       'ok': bool(r['smooth_dev_max_mm'] <= float(P['roughness_max_dev_mm']) and r['curvature_sign_changes'] <= allowed)},
         'perimeter_symmetry': per['symmetry']}
    if window:
        C = np.asarray(window['corners_TR_TL_BL_BR'], float)
        m_, b_ = float(gap['mid'][0]), float(gap['mid'][1])
        c = C.mean(0)
        off = float((c[1] - (m_ * c[0] + b_)) / np.hypot(1.0, m_))
        ax = C[0] - C[1]
        ang = float(np.degrees(abs(np.arctan2(ax[1], ax[0]) - np.arctan(m_))))
        on = bool(window.get('gap_alignment', {}).get('on_gap_line'))
        q['window_gap'] = {'centre_offset_mm': off, 'axis_angle_deg': ang, 'on_gap_line': on, 'ok': bool((not on) or (abs(off) <= 1e-3 and ang <= 0.01))}
        L_, H_ = float(window['dims_mm']['width_x']), float(window['dims_mm']['height_y'])
        Rw_, asp = float(window['corner_radius_mm']), max(L_, H_) / max(min(L_, H_), 1e-9)
        rmin = min(float(P['window_min_corner_radius_mm']), 0.45 * min(L_, H_))
        q['window_shape'] = {'corner_radius_mm': Rw_, 'length_mm': L_, 'width_mm': H_, 'aspect': asp, 'min_corner_radius_mm': rmin,
                             'aspect_range': [float(P['window_aspect_min']), float(P['window_aspect_max'])],
                             'ok': bool(Rw_ >= rmin - 1e-9 and float(P['window_aspect_min']) <= asp <= float(P['window_aspect_max']))}
    return q


# ------------------------------------------------------------------ stages
def _region_polygon(shp, V: np.ndarray, F: np.ndarray, ids: np.ndarray, nz_min: float = 0.25):
    t3 = V[F[ids]]
    nrm = np.cross(t3[:, 1] - t3[:, 0], t3[:, 2] - t3[:, 0])
    ln = np.linalg.norm(nrm, axis=1)
    top = (ln > 1e-12) & (nrm[:, 2] > nz_min * ln)               # top-view outline: steep groove / lip walls do not widen it
    tri = t3[top][:, :, :2]
    if len(tri) < 10:
        raise GrooveError('CLICK_GROOVE_REGIONS_MISSING', 'A click region has (almost) no upward-facing faces; the mesh is not in the standard frame (z up).')
    polys = shp.polygons(tri)
    u = shp.union_all(polys).buffer(0.03, 8).buffer(-0.03, 8)
    if u.geom_type == 'MultiPolygon':
        u = max(u.geoms, key=lambda g: g.area)
    return shp.Polygon(u.exterior)


def _densify(shp, ring, step: float) -> np.ndarray:
    n = max(8, int(ring.length / step))
    return np.array([ring.interpolate(s).coords[0] for s in np.linspace(0, ring.length, n, endpoint=False)])


def _fit_gap_lines(shp, PA, PB, xmin: float, xmax: float, wx_range, front_margin: float, merge_tol: float = 0.3) -> dict[str, Any]:
    ba, bb = _densify(shp, PA.exterior, 0.05), _densify(shp, PB.exterior, 0.05)
    xs_, ya, yb = [], [], []
    for xc in np.arange(xmin + 0.25, xmax - front_margin, 0.5):
        if wx_range and wx_range[0] - 0.3 < xc < wx_range[1] + 0.6:
            continue
        a = ba[np.abs(ba[:, 0] - xc) < 0.25][:, 1]
        b = bb[np.abs(bb[:, 0] - xc) < 0.25][:, 1]
        if len(a) and len(b):
            xs_.append(xc)
            ya.append(a.min())
            yb.append(b.max())
    if len(xs_) < 8:
        raise GrooveError('CLICK_GROOVE_NO_GAP', 'The centre gap between the two clicks could not be measured (fewer than 8 slices with both click edges).', {'slices': len(xs_)})
    xs_, ya, yb = np.array(xs_), np.array(ya), np.array(yb)
    out: dict[str, Any] = {}
    for key, yy in (('upper', ya), ('lower', yb)):
        p = robust_line(xs_, yy, floor=0.03, iters=4)
        r = yy - np.polyval(p, xs_)
        out[key] = (float(p[0]), float(p[1]))
        out[key + '_fit'] = {'rms_mm': float(r.std()), 'max_dev_mm': float(np.abs(r).max()), 'slices': int(len(xs_))}
    out['mid'] = ((out['upper'][0] + out['lower'][0]) / 2, (out['upper'][1] + out['lower'][1]) / 2)
    sep = float(np.abs(np.polyval(np.array(out['upper']), xs_) - np.polyval(np.array(out['lower']), xs_)).mean())
    out['line_separation_mm'] = sep
    out['merged'] = sep < merge_tol
    if out['merged']:                                           # the clicks meet at one boundary: both slots are cut about the same centre line
        out['upper'] = out['lower'] = out['mid']
    out['gap_width_scan_mm'] = float(np.median(ya - yb))
    if out['gap_width_scan_mm'] < -1.5 or out['gap_width_scan_mm'] > 4.0:
        raise GrooveError('CLICK_GROOVE_NO_GAP', 'The measured centre gap is implausible; check the click labels.', {'median_gap_mm': out['gap_width_scan_mm']})
    return out


def _snap_gap_to_plane(gap: dict[str, Any], plane: dict[str, Any] | None, xmin: float, xmax: float, tol: float) -> None:
    """With a mirror plane (n . p = d, taken at z = 0 like brain_mouse_click_slots) the centre-gap line is moved onto the plane's plan line when
    it lies within tol mm of it over the click x range (coarse test; otherwise kept and reported)."""
    if not plane:
        gap['mirror_plane'] = None
        return
    n = np.asarray(plane['normal'], float)
    n = n / np.linalg.norm(n)
    d = float(plane['d'])
    if abs(n[1]) < 0.7:
        gap['mirror_plane'] = {'snapped': False, 'note': 'mirror plane is not across y (frame x front, y left)'}
        return
    ps, pi = -n[0] / n[1], d / n[1]
    xx = np.array([xmin, xmax])
    off = np.abs(np.polyval(gap['mid'], xx) - np.polyval([ps, pi], xx)) / np.hypot(1.0, ps)
    ok = bool(off.max() <= tol)
    gap['mirror_plane'] = {'snapped': ok, 'max_offset_mm': float(off.max()), 'tolerance_mm': tol, 'line': {'slope': float(ps), 'intercept_y': float(pi)}}
    if ok:
        dm, db = ps - gap['mid'][0], pi - gap['mid'][1]
        for k in ('upper', 'lower'):
            gap[k] = (gap[k][0] + dm, gap[k][1] + db)
        gap['mid'] = (float(ps), float(pi))


def _fit_window(shp, V, F, wheel_ids, union, PA, PB, zf, warnings, P) -> dict[str, Any] | None:
    wxy = V[F[wheel_ids]][:, :, :2].reshape(-1, 2)
    wc = shp.Point(wxy.mean(0))
    best = None
    for ring in union.interiors:
        h = shp.Polygon(ring)
        if h.area < 4.0:
            continue
        score = 0.0 if h.contains(wc) else h.distance(wc) + 1.0
        if best is None or score < best[0]:
            best = (score, h)
    if best is None or best[0] > 5.0:
        warnings.append({'code': 'WINDOW_NOT_FOUND', 'note': 'No hole of the click outline holds the wheel; the window is not rebuilt.'})
        return None
    return {'hole': best[1], 'wheel_xy': wxy, 'PA': PA, 'PB': PB, 'wheel_ids': np.asarray(wheel_ids)}


def _window_rim(V, F, wheel_ids, hole, drop_mm: float = 0.3, open_mm: float = 1.0):
    """Rim of the wheel well from the geometry: top height field without the wheel faces; the well = pixels without a surface or deeper than
    drop_mm below the quadratic surface fitted to a ring 2-5 mm outside the label hole (= the top edge of the rim chamfer); opened by open_mm (drops thin grooves such as the centre gap),
    component holding the hole centre, holes filled. Returns (boundary points, info) or (None, reason)."""
    from scipy.ndimage import binary_fill_holes, binary_opening, label as nd_label
    from shapely import contains_xy
    keep = np.ones(len(F), bool)
    keep[np.asarray(wheel_ids, np.int64)] = False
    x0, y0, x1, y1 = hole.bounds
    m = 6.0
    xs, ys, Z = raster_top(V, F[keep], x0 - m, x1 + m, y0 - m, y1 + m)
    gx, gy = np.meshgrid(xs, ys)
    pts = np.c_[gx.ravel(), gy.ravel()]
    inside = contains_xy(hole, pts[:, 0], pts[:, 1]).reshape(Z.shape)
    dist = distance_transform_edt(~inside) * PIXEL
    ring = (dist > 2.0) & (dist < 5.0) & np.isfinite(Z)
    if ring.sum() < 200:
        return None, 'too few top-surface pixels round the label hole'
    cx_, cy_ = float(gx[ring].mean()), float(gy[ring].mean())
    def basis(x, y):
        u, v = x - cx_, y - cy_
        return np.stack([np.ones_like(u), u, v, u * u, u * v, v * v], -1)
    A = basis(gx[ring], gy[ring])
    zr = Z[ring]
    ok = np.ones(len(zr), bool)
    for _ in range(3):
        coef, *_ = np.linalg.lstsq(A[ok], zr[ok], rcond=None)
        res = zr - A @ coef
        ok = np.abs(res) < max(3.0 * res[ok].std(), 0.05)
    plane = basis(gx, gy) @ coef
    deep = ~np.isfinite(Z) | (Z < plane - drop_mm)
    r = max(1, int(round(open_mm / PIXEL)))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    deep = binary_opening(deep, structure=(xx ** 2 + yy ** 2) <= r * r)
    lab, n = nd_label(deep)
    c = np.asarray(hole.centroid.coords[0])
    ci, cj = int(round((c[1] - ys[0]) / PIXEL)), int(round((c[0] - xs[0]) / PIXEL))
    if not (0 <= ci < Z.shape[0] and 0 <= cj < Z.shape[1]) or lab[ci, cj] == 0:
        return None, 'the label hole centre is not inside a well deeper than drop_mm'
    comp = lab == lab[ci, cj]
    # the window must also clear the protruding wheel: footprint box of wheel vertices higher than drop_mm above the ring surface + clear_mm
    WV = V[F[np.asarray(wheel_ids, np.int64)]].reshape(-1, 3)
    hi = WV[WV[:, 2] > basis(WV[:, 0], WV[:, 1]) @ coef + drop_mm]
    clear_mm = 0.5
    well = binary_fill_holes(comp)
    well_edge = well & ~(np.roll(well, 1, 0) & np.roll(well, -1, 0) & np.roll(well, 1, 1) & np.roll(well, -1, 1))
    box = footprint = hull = None
    if len(hi):
        bx0, by0 = hi[:, :2].min(0) - clear_mm
        bx1, by1 = hi[:, :2].max(0) + clear_mm
        comp |= (gx >= bx0) & (gx <= bx1) & (gy >= by0) & (gy <= by1)
        box = [float(bx0), float(by0), float(bx1), float(by1)]
        footprint = [float(v) for v in (*(hi[:, :2].min(0)), *(hi[:, :2].max(0)))]
        if len(hi) >= 3:
            from scipy.spatial import ConvexHull
            try:
                hull = hi[ConvexHull(hi[:, :2]).vertices, :2].round(4).tolist()
            except Exception:
                hull = None
    comp = binary_fill_holes(comp)
    if comp[0].any() or comp[-1].any() or comp[:, 0].any() or comp[:, -1].any():
        return None, 'the well reaches the search box edge (not a closed window)'
    area = comp.sum() * PIXEL ** 2
    if not hole.area * 0.8 <= area <= hole.area * 4.0:
        return None, f'well area {area:.1f} mm2 is not comparable with the label hole ({hole.area:.1f} mm2)'
    edge = comp & ~(np.roll(comp, 1, 0) & np.roll(comp, -1, 0) & np.roll(comp, 1, 1) & np.roll(comp, -1, 1))
    B = np.c_[gx[edge], gy[edge]]
    return B, {'source': 'rim of the wheel well (top height field without the wheel faces, drop >= %.1f mm below the ring surface)' % drop_mm,
               'well_area_mm2': float(area), 'label_hole_area_mm2': float(hole.area), 'rim_points': int(len(B)), 'wheel_box_xy': box, 'wheel_footprint_xy': footprint, 'wheel_hull_xy': hull,
               '_well_edge': np.c_[gx[well_edge], gy[well_edge]]}


def _finish_window(win: dict[str, Any], V, F, zf, gap, P, shp, warnings) -> None:
    hole, PA, PB = win['hole'], win['PA'], win['PB']
    rim, rinfo = _window_rim(V, F, win['wheel_ids'], hole) if win.get('wheel_ids') is not None else (None, 'no wheel faces')
    well_edge = rinfo.pop('_well_edge', None) if isinstance(rinfo, dict) else None
    # G1.5 window rule (generic): rounded rectangle in the centre-gap frame (u along the gap line, v across it).
    #  sides  = outer envelope of the wheel-well rim (geometry) and the label notch of the click outline (window_source 'envelope'; or
    #           'rim' / 'labels' only); the window only grows, half height symmetric about the gap line when on it;
    #  radius = best fit to the label-notch corners (else the well-rim corners), <= 0.45 x the short side; window_corner_radius_mm overrides;
    #  cover  = the sides grow (never the radius shrinks) until the protruding wheel footprint + window_clear_mm lies inside the rounded corners.
    m_, b_ = float(gap['mid'][0]), float(gap['mid'][1])
    nrm_ = np.hypot(1.0, m_)
    ax_, ay_, o_ = np.array([1.0, m_]) / nrm_, np.array([-m_, 1.0]) / nrm_, np.array([0.0, b_])
    to_uv = lambda X: np.c_[(X - o_) @ ax_, (X - o_) @ ay_]
    lab_raw = np.vstack([_densify(shp, PA.exterior, 0.05), _densify(shp, PB.exterior, 0.05)])
    lab_raw = lab_raw[shp.distance(hole.exterior, shp.points(lab_raw)) < 0.35]
    if rim is None:
        warnings.append({'code': 'WINDOW_RIM_FROM_LABELS', 'note': f'Wheel-well rim not found from the geometry ({rinfo}); the window is fitted to the '
                                                               'label hole of the click outline (may be smaller than the real rim).'})
        rinfo = None
    mode = str(P.get('window_source', 'envelope'))
    srcs = {}
    if rim is not None and mode in ('envelope', 'rim'):
        srcs['rim'] = to_uv(rim)
    if (mode in ('envelope', 'labels') or not srcs) and len(lab_raw) >= 32:
        srcs['labels'] = to_uv(lab_raw)
    q = float(P.get('window_rim_quantile', 95.0))
    sides, sel, fits = None, {}, {}
    for name, U in srcs.items():
        u0, v0 = U.min(0)
        u1, v1 = U.max(0)
        cu, cv, w, h = (u0 + u1) / 2, (v0 + v1) / 2, u1 - u0, v1 - v0
        gm = np.abs(U[:, 1]) < 1.0
        ss = {'top': U[(U[:, 1] > cv) & (np.abs(U[:, 0] - cu) < 0.3 * w), 1], 'bottom': U[(U[:, 1] < cv) & (np.abs(U[:, 0] - cu) < 0.3 * w), 1],
              'left': U[(U[:, 0] < cu) & (np.abs(U[:, 1] - cv) < 0.28 * h) & ~gm, 0], 'right': U[(U[:, 0] > cu) & (np.abs(U[:, 1] - cv) < 0.28 * h) & ~gm, 0]}
        if min(len(v) for v in ss.values()) < 8:
            continue
        if name == 'rim':        # scan noise / wheel leftovers only make the well smaller: outer envelope (quantile q) of the rim points
            f = {'top': np.percentile(ss['top'], q), 'bottom': np.percentile(ss['bottom'], 100 - q), 'left': np.percentile(ss['left'], 100 - q),
                 'right': np.percentile(ss['right'], q)}
        else:                    # label notch edge = a line: median
            f = {k: float(np.median(v)) for k, v in ss.items()}
        fits[name] = {k: float(v) for k, v in f.items()}
        sel[name] = ss
        sides = dict(f) if sides is None else {'top': max(sides['top'], f['top']), 'bottom': min(sides['bottom'], f['bottom']),
                                               'left': min(sides['left'], f['left']), 'right': max(sides['right'], f['right'])}
    if sides is None:
        warnings.append({'code': 'WINDOW_EDGE_UNSUPPORTED', 'note': 'Too few outline points on a window edge; the window is not rebuilt.'})
        win.clear()
        win['failed'] = True
        return
    sides = {k: float(v) for k, v in sides.items()}
    off_perp = 0.5 * (sides['top'] + sides['bottom'])
    on_gap = abs(off_perp) <= float(P['window_on_gap_tol_mm'])

    def symm(sd):
        if on_gap:
            hh = max(sd['top'], -sd['bottom'])
            sd['top'], sd['bottom'] = hh, -hh
    symm(sides)
    gap_align = {'fitted_centre_offset_mm': float(off_perp), 'on_gap_line': bool(on_gap), 'tolerance_mm': float(P['window_on_gap_tol_mm'])}

    def corners_xy(sd):
        Cu = np.array([[sd['right'], sd['top']], [sd['left'], sd['top']], [sd['left'], sd['bottom']], [sd['right'], sd['bottom']]])
        return o_ + Cu[:, :1] * ax_ + Cu[:, 1:] * ay_                                # TR, TL, BL, BR
    C = corners_xy(sides)
    # corner radius from the label notch corners (the drawn window), else from the well rim (without the wheel box)
    if 'labels' in srcs:
        cp, cp_src = lab_raw[np.abs(srcs['labels'][:, 1]) > 1.0], 'label notch corners'
    else:
        cp, cp_src = (well_edge if well_edge is not None and len(well_edge) >= 8 else rim), 'well rim corners'
    cp = cp[np.linalg.norm(cp[:, None, :] - C[None], axis=2).min(1) < 5.0]
    if len(cp):
        cp = cp[seg_dist(cp, C, closed=True) < 1.5]
    short_ = lambda sd: min(sd['right'] - sd['left'], sd['top'] - sd['bottom'])
    rmax = 0.45 * short_(sides)
    best = (float('nan'), 0.5)
    given = P.get('window_corner_radius_mm')
    # the label notch is the drawn window only when it is about as large as the window (>= 90 % of its area); then its corner radius is
    # fitted; otherwise (automatic labels hug the wheel) radius rule = window_corner_frac x half the short side (near-obround)
    lf = fits.get('labels')
    lab_ok = bool(lf) and (lf['right'] - lf['left']) * (lf['top'] - lf['bottom']) >= 0.9 * (sides['right'] - sides['left']) * (sides['top'] - sides['bottom'])
    r_rule = 'override' if given else ('label notch corner fit' if lab_ok and len(cp) else 'window_corner_frac x half short side')
    if given:
        best = (float('nan'), float(min(float(given), rmax)))
    elif r_rule == 'label notch corner fit':
        best = (1e9, 0.5)
        for Rr in np.arange(0.5, min(8.0, rmax) + 1e-9, 0.25):
            e = seg_dist(cp, fillet_closed(C, Rr), closed=True)
            rms = float(np.sqrt((e ** 2).mean()))
            if rms < best[0] - 1e-9:
                best = (rms, float(Rr))
    else:
        best = (float('nan'), float(min(rmax, float(P['window_corner_frac']) * 0.5 * short_(sides))))
    Rw = best[1] if given else max(best[1], min(float(P['window_min_corner_radius_mm']), rmax))   # never a sharp window corner
    ref = dict(sides)
    box = (rinfo or {}).get('wheel_footprint_xy') if isinstance(rinfo, dict) else None
    hull = (rinfo or {}).get('wheel_hull_xy') if isinstance(rinfo, dict) else None
    if box:
        cl = float(P.get('window_clear_mm', 0.5))
        if hull and len(hull) >= 3:      # plan outline of the protruding wheel (convex hull) + clearance: round tyre ends stay round
            from shapely.geometry import Polygon as _Pg
            Bp = to_uv(np.asarray(_Pg(hull).buffer(cl, 8).exterior.coords)[:-1])
        else:
            Bu = to_uv(np.array([[box[0], box[1]], [box[0], box[3]], [box[2], box[1]], [box[2], box[3]]]))
            Bp = np.array([[Bu[:, 0].min() - cl, Bu[:, 1].min() - cl], [Bu[:, 0].min() - cl, Bu[:, 1].max() + cl],
                           [Bu[:, 0].max() + cl, Bu[:, 1].min() - cl], [Bu[:, 0].max() + cl, Bu[:, 1].max() + cl]])
        for _ in range(8):
            before = dict(sides)
            for bu_, bv_ in Bp:
                ku = 'right' if bu_ > 0.5 * (sides['left'] + sides['right']) else 'left'
                kv = 'top' if bv_ > 0.5 * (sides['top'] + sides['bottom']) else 'bottom'
                du = (sides['right'] - bu_) if ku == 'right' else (bu_ - sides['left'])
                dv = (sides['top'] - bv_) if kv == 'top' else (bv_ - sides['bottom'])
                gu, gv = max(0.0, -du), max(0.0, -dv)
                du, dv = du + gu, dv + gv
                a_, b2 = Rw - du, Rw - dv
                if a_ > 0 and b2 > 0 and a_ * a_ + b2 * b2 > Rw * Rw:     # the footprint corner sits in the rounded-off corner: grow both sides
                    disc = (a_ + b2) ** 2 - 2 * (a_ * a_ + b2 * b2 - Rw * Rw)
                    d_ = 0.5 * ((a_ + b2) - np.sqrt(max(disc, 0.0)))
                    gu, gv = gu + d_, gv + d_
                sides[ku] += gu if ku == 'right' else -gu
                sides[kv] += gv if kv == 'top' else -gv
            symm(sides)
            if r_rule == 'window_corner_frac x half short side':
                Rw = float(min(0.45 * short_(sides), float(P['window_corner_frac']) * 0.5 * short_(sides)))
            if all(abs(sides[k] - before[k]) < 1e-6 for k in sides):
                break
        C = corners_xy(sides)
    grown = {k: float(abs(sides[k] - ref[k])) for k in sides}
    x0, y0 = C.min(0)
    x1, y1 = C.max(0)
    src_note = 'G1.5 window: sides = outer envelope of %s + wheel plan outline with %.2f mm clearance; corner radius: %s' % (
        ' + '.join(srcs), float(P.get('window_clear_mm', 0.5)), r_rule if r_rule != 'label notch corner fit' else r_rule + ' (' + cp_src + ')')
    win['_fits_uv'] = {'sources': fits, 'final_sides_uv': {k: float(v) for k, v in sides.items()}, 'wheel_cover_growth_mm': grown}
    poly = fillet_closed(C, Rw)
    from shapely.geometry import Polygon
    from shapely.geometry.polygon import orient
    pg = orient(Polygon(poly))
    poly = np.array(pg.exterior.coords)[:-1]
    ring = pg.buffer(1.0).exterior
    rr = _densify(shp, ring, 0.25)
    gyr = gap['mid'][0] * rr[:, 0] + gap['mid'][1]
    rr = rr[np.abs(rr[:, 1] - gyr) > 1.6]
    zr = zf(rr[:, 0], rr[:, 1])
    Mx = np.c_[np.ones(len(rr)), rr]
    coef, *_ = np.linalg.lstsq(Mx, zr, rcond=None)
    resid = zr - Mx @ coef
    line_mid = shp.LineString([(x0 - 5, gap['mid'][0] * (x0 - 5) + gap['mid'][1]), (x1 + 5, gap['mid'][0] * (x1 + 5) + gap['mid'][1])])
    seg = pg.intersection(line_mid)
    gx = seg.bounds
    fu = win.pop('_fits_uv')
    dev = {name: {k: {'p50_mm': float(np.median(np.abs(v - fu['final_sides_uv'][k]))), 'max_mm': float(np.abs(v - fu['final_sides_uv'][k]).max())}
                  for k, v in ss.items()} for name, ss in sel.items()}
    FLOOR = float(coef[0])
    win.update({'poly': poly, 'poly_geom': pg, 'corners_TR_TL_BL_BR': C.round(4).tolist(), 'corner_radius_mm': Rw, 'corner_fit_rms_mm': (float(best[0]) if np.isfinite(best[0]) else None),
                'dims_mm': {'width_x': float(np.linalg.norm(C[0] - C[1])), 'height_y': float(np.linalg.norm(C[1] - C[2]))},
                'rim_plane': {'a': float(coef[0]), 'b': float(coef[1]), 'c': float(coef[2]), 'resid_max_mm': float(np.abs(resid).max()), 'resid_rms_mm': float(resid.std())},
                'edge_fit_dev_mm': dev, 'side_fits_uv': fu, 'gap_x_range': [float(gx[0]), float(gx[2])], 'source': src_note, 'rim_detection': rinfo, 'gap_alignment': gap_align,
                'base_plane': coef, 'min_wall_raise_mm': 0.0})
    off = 0.0
    nominal = FLOOR - float(P['slot_depth_mm'])
    mw = float(P['min_wall_mm'])
    if mw > 0:
        tm_ = __import__('trimesh')
        # filled below by the caller through _window_wall (needs the wall tree); kept simple: raise until the sample cloud is >= mw away from the floor plane
        pts, _ = tm_.sample.sample_surface(tm_.Trimesh(V, F, process=False), 200000, seed=20260917)
        tree = cKDTree(np.vstack([pts, V]))
        allp = np.vstack([pts, V])
        gx_ = np.arange(poly[:, 0].min(), poly[:, 0].max() + 0.01, 1.0)
        gy_ = np.arange(poly[:, 1].min(), poly[:, 1].max() + 0.01, 1.0)
        gp = np.array([(x, y) for x in gx_ for y in gy_ if pg.contains(shp.Point(x, y))] + [tuple(c) for c in poly[::5]])
        while off <= 3.0:
            zq = nominal + off + coef[1] * gp[:, 0] + coef[2] * gp[:, 1]
            viol = False
            for p_, z_ in zip(gp, zq):
                idx = tree.query_ball_point([p_[0], p_[1], z_], mw)
                if idx and (allp[idx][:, 2] <= z_ + 0.3).any():
                    viol = True
                    break
            if not viol:
                break
            off += 0.1
        win['min_wall_raise_mm'] = float(off)
    b, c = float(coef[1]), float(coef[2])
    a_floor = nominal + off
    win['floor_plane'] = [a_floor, b, c]
    win['nominal_floor_a'] = nominal
    win['PF'] = lambda x, y, a=a_floor, b=b, c=c: a + b * np.asarray(x) + c * np.asarray(y)


def _perimeter(shp, union, PA, PB, gap, P, warnings) -> dict[str, Any]:
    ring = _densify(shp, union.exterior, 0.25)
    gy = gap['mid'][0] * ring[:, 0] + gap['mid'][1]
    excl = np.abs(ring[:, 1] - gy) < float(P['gap_clear_mm'])
    if not excl.any() or excl.all():
        raise GrooveError('CLICK_GROOVE_PERIMETER_FIT', 'The outer ring does not cross the centre gap line; the click outline is not what a click pair looks like.')
    n = len(ring)
    # circular runs of excluded points; the one with the larger mean x is the front end of the gap
    first_ok = int(np.flatnonzero(~excl)[0])
    order = np.roll(np.arange(n), -first_ok)
    runs, cur = [], []
    for i in order:
        if excl[i]:
            cur.append(i)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    if len(runs) < 2:
        raise GrooveError('CLICK_GROOVE_PERIMETER_FIT', 'Only one gap crossing found on the outer ring (need rear and front).', {'runs': len(runs)})
    front = max(runs, key=lambda r: ring[r][:, 0].mean())
    start = (front[-1] + 1) % n
    seq = np.roll(np.arange(n), -start)
    seq = seq[: int(np.flatnonzero(seq == front[0])[0])]
    T = ring[seq[~excl[seq]]]
    if len(T) < 20:
        raise GrooveError('CLICK_GROOVE_PERIMETER_FIT', 'The perimeter chain is too short.')
    path, sym, A, Rsel = _regular_path(T, gap, P)
    d = seg_dist(T, A)
    Q0, _ = resample(A)
    tg = np.gradient(Q0, axis=0)
    tg /= np.linalg.norm(tg, axis=1)[:, None]
    nl = np.c_[-tg[:, 1], tg[:, 0]]
    inside_test = shp.contains_xy(union, Q0[:, 0] + 0.05 * nl[:, 0], Q0[:, 1] + 0.05 * nl[:, 1])
    sgn = -1.0 if inside_test.mean() > 0.5 else 1.0          # outward = sgn * left normal

    def depth_inside(Qx):
        out = np.full(len(Qx), -1e9)
        for pg in (PA, PB):
            inn = shp.contains_xy(pg, Qx[:, 0], Qx[:, 1])
            dd = shp.distance(pg.exterior, shp.points(Qx))
            out = np.maximum(out, np.where(inn, dd, -dd))
        return out
    d_in = depth_inside(Q0)
    # label overhang: a run of stations where the labelled panel sticks out of the regular outline by more than overhang_mm (scan / label
    # noise the regular fit dropped on purpose) does not push the whole slot outward; it is reported and gated by its size.
    ovh_lim = float(P['overhang_mm'])
    enc_run = d_in > 0.05
    overhang = np.zeros(len(Q0), bool)
    idx = np.flatnonzero(np.diff(np.r_[0, enc_run.astype(int), 0]))
    ovh_runs = []
    for a, b in zip(idx[::2], idx[1::2]):
        if d_in[a:b].max() > ovh_lim:
            overhang[a:b] = True
            ovh_runs.append({'length_mm': float(STEP * (b - a)), 'max_mm': float(d_in[a:b].max()), 'xy': Q0[a + int(np.argmax(d_in[a:b]))].round(2).tolist()})
    counted = ~overhang
    clear = float(P['perimeter_clearance_mm'])
    # label outline = hint: spikes of the region boundary narrower than spike_width_mm (morphological opening along the arc) do not move
    # the slot; any wider encroachment (a real panel edge inside the slot) is cleared in full
    wq = max(1, int(round(float(P['spike_width_mm']) / STEP)))
    from scipy.ndimage import grey_opening
    def qv(d):
        if not counted.any():
            return 0.0
        dd = np.where(counted, d, -1e3)
        return float(grey_opening(dd, size=wq, mode='nearest')[counted].max())
    q = float(P['spike_width_mm'])
    shift = max(0.0, qv(d_in)) + clear
    Aout = Q0 + sgn * shift * nl
    d_after = depth_inside(Aout)
    for _ in range(12):                      # the outline is not parallel to the path everywhere: push on until the quantile is outside
        if qv(d_after) <= -clear + 1e-9:
            break
        shift += qv(d_after) + clear
        Aout = Q0 + sgn * shift * nl
        d_after = depth_inside(Aout)
    spikes = counted & (d_after > 0)
    enc = {'max_inside_before_mm': float(d_in.max()), 'shift_outward_mm': float(shift), 'spike_width_mm': q, 'inside_after_robust_mm': qv(d_after),
           'max_inside_after_mm': float(d_after[counted].max()), 'label_spikes_inside_after': {'stations': int(spikes.sum()), 'length_mm': float(STEP * spikes.sum())},
           'label_overhang': {'limit_mm': ovh_lim, 'runs': ovh_runs, 'total_length_mm': float(sum(r['length_mm'] for r in ovh_runs)),
                              'max_mm': float(max([r['max_mm'] for r in ovh_runs], default=0.0)), 'max_inside_after_incl_overhang_mm': float(d_after.max())}}
    return {'path': path, 'A': Aout, 'R': Rsel, 'rms': float(np.sqrt((d ** 2).mean())), 'max': float(d.max()), 'out': sgn, 'encroachment': enc, 'symmetry': sym,
            'roughness': outline_roughness(Aout)}


def _outside_excess(other: np.ndarray, verts: np.ndarray, width_mm: float) -> float:
    """Half frame (+v side, path from the rear centre outward): how far the other branch's points lie OUTSIDE the fitted half path (away
    from the gap line), robust over width_mm of arc (morphological opening: narrower label spikes do not count)."""
    import shapely
    from scipy.ndimage import grey_opening
    ring = np.vstack([verts, [[verts[-1, 0], 0.0], [verts[0, 0], 0.0]]])
    pg = shapely.Polygon(ring).buffer(0)
    d = seg_dist(other, verts)
    out = ~shapely.contains_xy(pg, other[:, 0], other[:, 1]) & (other[:, 1] > 0)
    dep = np.where(out, d, -d)
    ds = np.median(np.linalg.norm(np.diff(other, axis=0), axis=1)) if len(other) > 1 else 1.0
    wq = max(1, int(round(width_mm / max(ds, 1e-6))))
    return float(grey_opening(dep, size=wq, mode='nearest').max()) if len(dep) else 0.0


def _regular_path(T: np.ndarray, gap: dict[str, Any], P: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any], np.ndarray, Any]:
    """Regular perimeter start line (before the fillets) from the ordered outer-ring chain T (front end -> round the rear -> other front end;
    the stretch at the rear gap crossing is already removed). Frame: u along the centre-gap line, v across it. When both branches (one per
    click) are near-symmetric about the gap line (coarse test per fitted piece: p90 distance of the other branch's points to the mirrored
    piece <= symmetry_tol_mm), the branch with the better fit (lower rms) is mirrored onto the other one (no forced symmetry: a failed
    piece keeps both branches as fitted); the rear piece is made perpendicular to the gap line when it is within 5 degrees of it."""
    tol = float(P['fit_tolerance_mm'])
    kw = {'min_turn_deg': float(P['min_turn_deg']), 'merge_dev_mm': float(P['merge_dev_mm']), 'concave_dev_mm': float(P['concave_dev_mm'])}
    m_, b_ = float(gap['mid'][0]), float(gap['mid'][1])
    eu = np.array([1.0, m_]) / np.hypot(1.0, m_)
    ev = np.array([-eu[1], eu[0]])
    o = np.array([0.0, b_])
    to_f = lambda X: np.c_[(X - o) @ eu, (X - o) @ ev]
    from_f = lambda U: o + U[:, :1] * eu + U[:, 1:2] * ev
    Tf = to_f(T)
    info: dict[str, Any] = {'mode': 'as_fitted', 'tolerance_mm': float(P['symmetry_tol_mm'])}
    whole = fit_lines_regular(T, tol, **kw)
    info['whole_fit'] = {'pieces': len(whole['lines']), 'merged': whole['merged'], 'opposite_turns_kept': whole['opposite_turns_kept']}
    given = P.get('fillet_radius_mm')

    def finish(Vw, raw_w, extra):
        R = float(given) if given else select_radii(Vw, raw_w, r_min=float(P['min_corner_radius_mm']))
        A = fillet_open(Vw, R, clip=0.49)
        Rinfo = float(given) if given else {'per_vertex_mm': [round(float(r), 3) for r in R], 'min_mm': float(np.min(R)) if len(R) else None,
                                            'max_mm': float(np.max(R)) if len(R) else None}
        return Vw, {**info, **extra}, A, Rinfo
    if not P.get('symmetric_outline', True):
        info['mode'] = 'as_fitted (symmetric_outline off)'
        return finish(whole['verts'], T, {'opposite_turns_kept': whole['opposite_turns_kept']})
    j = int(np.argmax(np.linalg.norm(np.diff(Tf, axis=0), axis=1)))           # the bridged rear gap crossing
    br = [Tf[:j + 1][::-1], Tf[j + 1:]]                                       # both from the rear centre outward
    sg = [float(np.sign(np.median(b[:, 1]))) for b in br]
    if len(br[0]) < 20 or len(br[1]) < 20 or sg[0] == sg[1] or 0.0 in sg:
        info['note'] = 'the chain does not split into one branch per side of the gap line'
        return finish(whole['verts'], T, {'opposite_turns_kept': whole['opposite_turns_kept']})
    half = [b * [1.0, s] for b, s in zip(br, sg)]                             # both branches on the +v side
    fits = [fit_lines_regular(h, tol, **kw) for h in half]
    rms = [float(np.sqrt((seg_dist(h, f['verts']) ** 2).mean())) for h, f in zip(half, fits)]
    # which branch is mirrored: the other branch's label outline must not stick out of the mirrored one by more than overhang_mm over
    # any stretch wider than spike_width_mm (else the mirrored slot would cut into that click); among the admissible ones the lower rms.
    # Mirror-equivariant: a mirrored scan picks the same physical branch.
    out_x = [_outside_excess(half[1 - i], fits[i]['verts'], float(P['spike_width_mm'])) for i in range(2)]
    adm = [i for i in range(2) if out_x[i] <= float(P['overhang_mm'])]
    k = min(adm, key=lambda i: rms[i]) if adm else int(np.argmin(out_x))
    info['branch_outside_excess_mm'] = out_x
    best, other = fits[k], half[1 - k]
    dist = seg_dist(other, best['verts'])
    # per fitted piece: the other branch's points nearest to that piece
    vb = best['verts']
    piece = np.full(len(other), -1)
    dmin = np.full(len(other), np.inf)
    for i, (a, b) in enumerate(zip(vb[:-1], vb[1:])):
        dd = seg_dist(other, np.array([a, b]))
        upd = dd < dmin
        piece[upd], dmin[upd] = i, dd[upd]
    regions = []
    for i in range(len(vb) - 1):
        sel = piece == i
        p90 = float(np.percentile(dist[sel], 90)) if sel.sum() >= 3 else 0.0
        regions.append({'piece': i, 'from_uv': vb[i].round(2).tolist(), 'to_uv': vb[i + 1].round(2).tolist(), 'points': int(sel.sum()), 'p90_mm': p90,
                        'near_symmetric': bool(p90 <= info['tolerance_mm'])})
    info.update({'branch_fit_rms_mm': rms, 'better_branch': 'v' + ('+' if sg[k] > 0 else '-'), 'regions': regions})
    if not all(r['near_symmetric'] for r in regions):
        info['mode'] = 'as_fitted (not near-symmetric in every region)'
        return finish(whole['verts'], T, {'opposite_turns_kept': whole['opposite_turns_kept']})
    V = best['verts'].copy()
    c0, d0 = best['lines'][0]
    if abs(d0 @ np.array([1.0, 0.0])) <= np.sin(np.radians(5.0)):              # rear piece ~ perpendicular to the gap line
        # the following pieces that are within min_turn_deg of the perpendicular join the rear piece (no small kink where the forced
        # perpendicular line meets a slightly tilted next piece); its position = mean u of all their points
        ang_ok = lambda d: abs(d @ np.array([1.0, 0.0])) <= np.sin(np.radians(float(P['min_turn_deg'])))
        nj = 1
        while nj < len(best['lines']) - 1 and ang_ok(best['lines'][nj][1]):
            nj += 1
        s_ = np.r_[0, np.cumsum(np.linalg.norm(np.diff(half[k], axis=0), axis=1))]
        sel = half[k][(s_ >= best['groups'][0][0]) & (s_ <= best['groups'][nj - 1][1])]
        cu = float(sel[:, 0].mean())
        line0 = (np.array([cu, 0.0]), np.array([0.0, 1.0]))
        V = np.vstack([V[:1], V[nj:]])
        if len(best['lines']) > nj:
            p = lines_intersect(*line0, *best['lines'][nj])
            if p is not None:
                V[1] = p
        V[0] = np.array([cu, 0.0])
        info['rear_piece'] = 'perpendicular to the gap line' + (f' ({nj} pieces joined)' if nj > 1 else '')
        full = np.vstack([(V[1:] * [1, -1])[::-1], V[1:]])                   # the rear centre is a straight continuation, no vertex
    else:
        p = lines_intersect(c0, d0, np.array([0.0, 0.0]), np.array([1.0, 0.0]))
        if p is not None and np.linalg.norm(p - V[0]) < 6.0:
            V[0] = p
        V[0, 1] = 0.0
        info['rear_piece'] = 'corner on the gap line'
        full = np.vstack([(V[1:] * [1, -1])[::-1], V])
    first_side = float(np.sign(np.median(Tf[: max(3, len(Tf) // 10), 1])))
    if np.sign(full[0, 1]) != first_side:
        full = full * [1, -1]
    info['mode'] = 'mirrored better branch about the centre-gap line'
    raw_sym = np.vstack([half[k], half[k] * [1, -1]])                      # the better branch on both sides: radii come out symmetric
    Vw, inf2, A, Rinfo = finish(full, raw_sym, {'opposite_turns_kept': best['opposite_turns_kept']})
    return from_f(Vw), inf2, from_f(A), Rinfo


def _orient(tm, m):
    if m.volume < 0:
        m.invert()
    return m


def _sweep(A: np.ndarray, o1: float, o2: float, zs_fn, DEPTH: float, zf, tag: str, blend=None, wall_tree=None, min_wall: float = 0.0):
    Q, t = resample(A, STEP)
    tang = np.gradient(Q, axis=0)
    tang /= np.linalg.norm(tang, axis=1)[:, None]
    nrm = np.c_[-tang[:, 1], tang[:, 0]]
    pin, pout = Q + o1 * nrm, Q + o2 * nrm
    zs_ = zs_fn(Q, nrm)
    zsm = gaussian_filter1d(zs_, 1.0 / STEP, mode='nearest')
    zfl = zsm - DEPTH
    if blend is not None:
        PLAN, PF = blend
        import shapely
        dist = shapely.distance(PLAN.exterior, shapely.points(Q))
        w = np.clip(1 - dist / 3.0, 0, 1)
        w = w * w * (3 - 2 * w)
        zfl = zfl + w * np.maximum(0, PF(Q[:, 0], Q[:, 1]) - zfl)
    capped = np.zeros(len(Q), bool)
    if wall_tree is not None and min_wall > 0:
        tree, zall = wall_tree
        pm = 0.5 * (pin + pout)
        need = zfl.copy()
        for i in range(len(Q)):
            z = need[i]
            while z < zs_[i]:
                bad = False
                for pp in (pin[i], pm[i], pout[i]):
                    idx = tree.query_ball_point([pp[0], pp[1], z], min_wall)
                    if idx and (zall[idx] <= z + 0.3).any():
                        bad = True
                        break
                if not bad:
                    break
                z += 0.1
            need[i] = z
        capped = need > zfl + 1e-6
        zfl = np.maximum(need, gaussian_filter1d(need, 1.0 / STEP, mode='nearest'))
    zt = maximum_filter1d(np.maximum(zf(pin[:, 0], pin[:, 1]), zf(pout[:, 0], pout[:, 1])), 9) + 3.0
    n = len(Q)
    Vv = np.zeros((n, 4, 3))
    Vv[:, 0, :2], Vv[:, 0, 2] = pin, zfl
    Vv[:, 1, :2], Vv[:, 1, 2] = pout, zfl
    Vv[:, 2, :2], Vv[:, 2, 2] = pout, zt
    Vv[:, 3, :2], Vv[:, 3, 2] = pin, zt
    Fc = []
    for i in range(n - 1):
        for k in range(4):
            a = i * 4 + k
            b = i * 4 + (k + 1) % 4
            c = (i + 1) * 4 + (k + 1) % 4
            d = (i + 1) * 4 + k
            Fc += [[a, b, c], [a, c, d]]
    Fc += [[0, 2, 1], [0, 3, 2]]
    e = (n - 1) * 4
    Fc += [[e, e + 1, e + 2], [e, e + 2, e + 3]]
    import trimesh
    m = trimesh.Trimesh(Vv.reshape(-1, 3), np.array(Fc), process=False)
    info = {'tag': tag, 'length': float(t[-1]), 'n': int(n), 'capped_stations': int(capped.sum()), 'zfloor_range': [float(zfl.min()), float(zfl.max())],
            'depth_to_surface_mean': float((zs_ - zfl).mean())}
    return m, info, {'Q': Q, 'nrm': nrm, 'zfl': zfl, 'zs': zs_, 'o1': o1, 'o2': o2}


def _pocket(mf, window: dict[str, Any], V: np.ndarray):
    FL = window['floor_plane']
    PB_, PC_ = FL[1], FL[2]
    nn = np.array([-PB_, -PC_, 1.0])
    Ln = np.linalg.norm(nn)
    nn /= Ln
    z0 = float(V[:, 2].min()) - 5.0
    z1 = float(V[:, 2].max()) + 5.0
    cs = mf.CrossSection([np.asarray(window['poly'], float)])
    pr = mf.Manifold.extrude(cs, z1 - z0).translate((0.0, 0.0, z0))
    pocket = pr.trim_by_plane(tuple(nn), FL[0] / Ln)
    plug = pr.trim_by_plane(tuple(-nn), -FL[0] / Ln).trim_by_plane(tuple(nn), (FL[0] - 3.0) / Ln)
    return pocket, plug


def _tag(mf, Mn, idv: int):
    q = Mn.to_mesh()
    return mf.Manifold(mf.Mesh(np.array(q.vert_properties, dtype=np.float32), np.array(q.tri_verts, dtype=np.uint32), face_id=np.full(len(q.tri_verts), idv, dtype=np.uint32)))


def _cleanup(tm, verts: np.ndarray, faces: np.ndarray, fid: np.ndarray):
    """Weld, drop degenerate faces, cancel zero-volume flaps (same triangle twice with opposite winding), keep the largest body."""
    _, ui, inv = np.unique(np.round(verts, 6), axis=0, return_index=True, return_inverse=True)
    f2 = inv.reshape(-1)[faces]
    ok = (f2[:, 0] != f2[:, 1]) & (f2[:, 1] != f2[:, 2]) & (f2[:, 0] != f2[:, 2])
    deg = int((~ok).sum())
    f2, fid = f2[ok], fid[ok]
    key = np.sort(f2, axis=1)
    _, inv2, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    inv2 = inv2.reshape(-1)
    flap = cnt[inv2] >= 2
    n_flap = int(flap.sum())
    if n_flap:
        f2, fid = f2[~flap], fid[~flap]
    res = tm.Trimesh(verts[ui], f2, process=False)
    cc = tm.graph.connected_components(res.face_adjacency, nodes=np.arange(len(res.faces)), min_len=1)
    big = max(cc, key=len)
    keep = np.zeros(len(res.faces), bool)
    keep[big] = True
    splinters = [{'faces': int(len(c)), 'center': res.triangles_center[c].mean(0).round(2).tolist()} for c in cc if len(c) != len(big)]
    res = tm.Trimesh(res.vertices, res.faces[keep], process=False)
    fid = fid[keep]
    res.remove_unreferenced_vertices()
    return res, fid, {'degenerate_faces_removed': deg, 'zero_volume_flap_faces_removed': n_flap, 'splinters_removed': splinters}


# ------------------------------------------------------------------ measurements on the result
def _measure(tm, shp, src, res, fid, N, V, F, sweeps, infos, window, gap, per, runs, cutters, DEPTH, W) -> dict[str, Any]:
    out: dict[str, Any] = {}
    vq_res = VerticalHits(np.asarray(res.vertices), np.asarray(res.faces))
    vq_src = VerticalHits(V, F)
    pc = lambda a: [float(x) for x in np.percentile(a, [5, 50, 95]).round(3)]
    stats: dict[str, Any] = {}
    for tag, sw in sweeps.items():
        Q, nrm, zfl = sw['Q'], sw['nrm'], sw['zfl']
        o1, o2 = sw['o1'], sw['o2']
        idx = np.arange(min(5, len(Q) - 1), max(len(Q) - 5, 1), 6)
        if len(idx) == 0:
            continue
        off = np.arange(o1 - 0.4, o2 + 0.4001, 0.02)
        pts = np.array([Q[i] + o * nrm[i] for i in idx for o in off])
        H = vq_res.top(pts).reshape(len(idx), len(off))
        wid, dep_p, dep_o, flat = [], [], [], []
        for r in range(len(idx)):
            h = H[r]
            if not np.isfinite(h).all():
                continue
            fl = np.nanmin(h)
            slot = h < fl + 0.03
            if slot.sum() < 5:
                continue
            oo = off[slot]
            wid.append(oo.max() - oo.min() + 0.02)
            s2 = (off >= oo.min() + 0.04) & (off <= oo.max() - 0.04)
            flat.append(np.nanmax(h[s2]) - np.nanmin(h[s2]))
            ref_lo = np.nanmean(h[(off < o1 - 0.03) & (off > o1 - 0.13)])
            ref_hi = np.nanmean(h[(off > o2 + 0.03) & (off < o2 + 0.13)])
            if sw['panel_side'] == 'lo':
                dep_p.append(ref_lo - fl)
                dep_o.append(ref_hi - fl)
            else:
                dep_p.append(ref_hi - fl)
                dep_o.append(ref_lo - fl)
        if not wid:
            continue
        wid, dep_p, dep_o, flat = map(np.array, (wid, dep_p, dep_o, flat))
        stats[tag] = {'stations': int(len(wid)), 'width_mm_p5_50_95': pc(wid), 'width_min_max': [float(wid.min()), float(wid.max())],
                      'depth_below_panel_side_surface_p5_50_95': pc(dep_p), 'depth_below_outer_side_surface_p5_50_95': pc(dep_o),
                      'floor_flatness_across_width_max_mm': float(flat.max()), 'floor_flatness_p95': float(np.percentile(flat, 95))}
    out['slot_measure'] = stats
    newf = fid >= N
    nz = np.abs(res.face_normals[newf, 2])
    area = res.area_faces[newf]
    wall = nz < 0.5
    out['new_faces'] = {'total': int(newf.sum()), 'wall_like': int(wall.sum()), 'wall_max_abs_nz': float(nz[wall].max()) if wall.any() else None,
                        'wall_area_weighted_mean_abs_nz': float((nz[wall] * area[wall]).sum() / area[wall].sum()) if wall.any() else None,
                        'wall_faces_nz_gt_0p01': int((nz[wall] > 0.01).sum()), 'wall_area_nz_gt_0p05_mm2': float(area[wall & (nz > 0.05)].sum()), 'wall_area_mm2': float(area[wall].sum()), 'floor_like': int((~wall).sum()),
                        'floor_area_mm2': float(area[~wall].sum()), 'floor_normal_tilt_deg_max': float(np.degrees(np.arccos(np.clip(nz[~wall], 0, 1))).max()) if (~wall).any() else None}
    # cut-through: slot floor points outside the original solid, and the material left below the floor
    ct: dict[str, Any] = {}
    for tag, sw in sweeps.items():
        Q, nrm, zfl = sw['Q'], sw['nrm'], sw['zfl']
        idx = np.arange(0, len(Q), 2)
        o1, o2 = sw['o1'], sw['o2']
        zq = zfl[idx] - 0.02
        outside = np.zeros(len(idx), bool)
        below = np.full(len(idx), np.nan)
        for oo in (o1, 0.5 * (o1 + o2), o2):
            xy = Q[idx] + oo * nrm[idx]
            hh = vq_src.hits(xy)
            for k, h in enumerate(hh):
                above = int((h > zq[k]).sum())
                if above % 2 == 0:
                    outside[k] = True
                if oo == 0.5 * (o1 + o2):
                    b = h[h < zq[k]]
                    below[k] = zq[k] - b[-1] if len(b) else np.nan
        runs_ = []
        if outside.any():
            ii = np.flatnonzero(outside)
            brk = np.flatnonzero(np.diff(ii) > 2)
            for r_ in np.split(ii, brk + 1):
                runs_.append({'x_range': [float(Q[idx][r_[0], 0]), float(Q[idx][r_[-1], 0])], 'y_range': [float(Q[idx][r_[0], 1]), float(Q[idx][r_[-1], 1])],
                              'length_mm': float(STEP * 2 * len(r_))})
        dep = (sw['zs'] - sw['zfl'])[idx]
        ct[tag] = {'stations': int(len(idx)), 'floor_outside_original_solid': int(outside.sum()), 'cut_through_runs': runs_,
                   'material_below_floor_min_mm': float(np.nanmin(below)) if np.isfinite(below).any() else None,
                   'depth_below_surface': {'min': float(dep.min()), 'p5': float(np.percentile(dep, 5)), 'p50': float(np.median(dep)), 'p95': float(np.percentile(dep, 95)), 'max': float(dep.max())}}
    out['cut_through'] = ct
    comps = tm.graph.connected_components(res.face_adjacency, nodes=np.arange(len(res.faces)), min_len=1)
    out['bodies'] = {'components': int(len(comps)), 'watertight': bool(res.is_watertight), 'winding_consistent': bool(res.is_winding_consistent), 'euler': int(res.euler_number),
                     'source_components': int(len(tm.graph.connected_components(src.face_adjacency, nodes=np.arange(len(src.faces)), min_len=1)))}
    # total centre-gap width at floor level on the result (union of the two slots plus the scanned gap)
    gw = []
    glx = gap['mid']
    for name, x0, x1 in runs:
        for xg in np.arange(x0 + 1.0, x1 - 2.0, 1.0):
            yc = glx[0] * xg + glx[1]
            yy = np.arange(yc - 2.5, yc + 2.5001, 0.02)
            hh = vq_res.top(np.c_[np.full_like(yy, xg), yy])
            if not np.isfinite(hh).all():
                continue
            i0 = int(np.nanargmin(hh))
            ok_ = hh <= hh[i0] + 0.5
            a_ = b_ = i0
            while a_ > 0 and ok_[a_ - 1]:
                a_ -= 1
            while b_ < len(yy) - 1 and ok_[b_ + 1]:
                b_ += 1
            gw.append({'x': float(xg), 'run': name, 'width': float(yy[b_] - yy[a_] + 0.02)})
    if gw:
        ws = np.array([g['width'] for g in gw])
        out['centre_gap_width'] = {'by_x': gw, 'median_mm': float(np.median(ws)), 'p5_p95_mm': [float(np.percentile(ws, 5)), float(np.percentile(ws, 95))],
                                   'scanned_gap_before_median_mm': float(gap['gap_width_scan_mm'])}
    out['encroachment'] = per['encroachment']
    if window:
        FL = window['floor_plane']
        pg = window['poly_geom']
        fc = res.triangles_center
        inplan = shp.contains_xy(pg.buffer(0.02), fc[:, 0], fc[:, 1])
        zpl = FL[0] + FL[1] * fc[:, 0] + FL[2] * fc[:, 1]
        fl = newf & inplan & (np.abs(fc[:, 2] - zpl) < 0.02) & (np.abs(res.face_normals[:, 2]) > 0.5)
        wm: dict[str, Any] = {}
        if fl.any():
            FV = res.vertices[np.unique(res.faces[fl])]
            FV = FV[np.abs(FV[:, 2] - (FL[0] + FL[1] * FV[:, 0] + FL[2] * FV[:, 1])) < 0.05]
            Mx = np.c_[np.ones(len(FV)), FV[:, :2]]
            cf, *_ = np.linalg.lstsq(Mx, FV[:, 2], rcond=None)
            rr = FV[:, 2] - Mx @ cf
            wm['floor'] = {'area_mm2': float(res.area_faces[fl].sum()), 'max_dev_from_plane_mm': float(np.abs(rr).max()), 'tilt_deg': float(np.degrees(np.arctan(np.hypot(cf[1], cf[2]))))}
        inpl = shp.contains_xy(pg.buffer(-0.1), res.vertices[:, 0], res.vertices[:, 1])
        zv = res.vertices[:, 2] - (FL[0] + FL[1] * res.vertices[:, 0] + FL[2] * res.vertices[:, 1])
        wm['max_vertex_height_above_floor_inside_window_mm'] = float(zv[inpl].max()) if inpl.any() else None
        ring = pg.buffer(1.0).exterior
        rp = _densify(shp, ring, 0.25)
        rp = rp[np.abs(rp[:, 1] - (glx[0] * rp[:, 0] + glx[1])) > 1.6]
        zr = vq_res.top(rp)
        dd_ = zr - (FL[0] + FL[1] * rp[:, 0] + FL[2] * rp[:, 1])
        if np.isfinite(dd_).any():
            wm['depth_below_rim_surface_mm'] = {'p5': float(np.nanpercentile(dd_, 5)), 'p50': float(np.nanmedian(dd_)), 'p95': float(np.nanpercentile(dd_, 95))}
        out['window'] = wm
    return out


# ------------------------------------------------------------------ overlay
def _overlay(out_dir: Path, V, F, res, box, warnings) -> dict[str, Any] | None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        warnings.append({'code': 'OVERLAY_SKIPPED', 'note': 'Pillow is not installed in the scan python.'})
        return None
    imgs = []
    for v_, f_ in ((V, F), (np.asarray(res.vertices), np.asarray(res.faces))):
        xs, ys, Z = raster_top(v_, f_, box[0], box[1], box[2], box[3], 0.1)
        bad = ~np.isfinite(Z)
        if bad.any():
            Z = Z[tuple(distance_transform_edt(bad, return_distances=False, return_indices=True))]
        gy, gx = np.gradient(Z, 0.1)
        sh = np.clip(0.5 + 0.5 * -(gx * 0.6 + gy * 0.8) / np.sqrt(1 + gx ** 2 + gy ** 2) * 1.8, 0, 1)
        img = Image.fromarray((np.flipud(sh) * 255).astype(np.uint8)).convert('RGB')
        imgs.append(img)
    w, h = imgs[0].size
    canvas = Image.new('RGB', (w * 2 + 10, h + 24), (255, 255, 255))
    canvas.paste(imgs[0], (0, 24))
    canvas.paste(imgs[1], (w + 10, 24))
    d = ImageDraw.Draw(canvas)
    d.text((6, 6), 'BEFORE (scan)', fill=(0, 0, 0))
    d.text((w + 16, 6), 'AFTER (rebuilt click grooves)   top view, x right, y up', fill=(0, 0, 0))
    canvas.save(out_dir / 'before_after.png')
    return {'file': 'before_after.png'}


def main(argv: list[str]) -> int:
    try:
        req = json.loads(Path(argv[1]).read_text(encoding='utf-8'))
        res = run(req)
    except GrooveError as exc:
        res = {'status': 'FAILED', 'error': {'code': exc.code, 'message': exc.message, 'details': exc.details}}
    except Exception as exc:
        res = {'status': 'FAILED', 'error': {'code': 'CLICK_GROOVE_WORKER', 'message': f'{type(exc).__name__}: {exc}', 'trace': traceback.format_exc()[-1500:]}}
    sys.stdout.write('\n' + json.dumps(res, allow_nan=False, default=_json_default) + '\n')
    return 0 if res.get('status') == 'OK' else 2


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.bool_):
        return bool(o)
    raise TypeError(type(o).__name__)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
