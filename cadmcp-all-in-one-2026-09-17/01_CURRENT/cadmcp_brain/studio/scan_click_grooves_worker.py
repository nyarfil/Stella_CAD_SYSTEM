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

WORKER_VERSION = 'scan_click_grooves/1'
UNIT_MM = {'mm': 1.0, 'cm': 10.0, 'm': 1000.0, 'in': 25.4}
STEP = 0.2                    # station spacing of the sweeps, mm
PIXEL = 0.1                   # height-field pixel, mm
ROLE_ALIASES = {'LC': 'left_click', 'left_click': 'left_click', 'RC': 'right_click', 'right_click': 'right_click', 'WH': 'wheel', 'wheel': 'wheel',
                'scroll_wheel': 'wheel', 'top_shell': 'top_shell', 'palm_shell': 'top_shell', 'bottom_plate': 'bottom_plate', 'B1': 'side_button_1',
                'side_button_1': 'side_button_1', 'B2': 'side_button_2', 'side_button_2': 'side_button_2'}


DEFAULTS = {'slot_width_mm': 0.5, 'slot_depth_mm': 2.0, 'panel_overlap_mm': 0.2, 'perimeter_clearance_mm': 0.005, 'fit_tolerance_mm': 0.2, 'fillet_radius_mm': None,
            'min_wall_mm': 0.0, 'rebuild_window': True, 'overlay': True, 'gap_clear_mm': 2.0, 'gap_front_margin_mm': 2.5, 'gap_overshoot_mm': 0.5}


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


def fillet_open(Pq: np.ndarray, R: float, step_deg: float = 1.5) -> np.ndarray:
    """Round every interior vertex of an open polyline with radius R (clipped to 0.45 of the adjacent pieces)."""
    out = [Pq[0]]
    for i in range(1, len(Pq) - 1):
        a, b, c = Pq[i - 1], Pq[i], Pq[i + 1]
        la, lc = np.linalg.norm(a - b), np.linalg.norm(c - b)
        if la < 1e-9 or lc < 1e-9:
            continue
        u, w = (a - b) / la, (c - b) / lc
        ang = np.arccos(np.clip(u @ w, -1, 1))
        if np.pi - ang < 1e-3:
            out.append(b)
            continue
        t = min(R / np.tan(ang / 2), 0.45 * la, 0.45 * lc)
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
    P = req['params']
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
    # ---- measurements
    metrics = _measure(tm, shp, src, res, fid, N, V, F, sweeps, infos, window, gap, per, runs, cutters, DEPTH, W)
    metrics['volume'] = {'before_mm3': float(src.volume), 'after_mm3': float(res.volume), 'removed_mm3': float(src.volume - res.volume)}
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
                   'gap_clear_mm': float(P['gap_clear_mm']), 'gap_front_margin_mm': float(P['gap_front_margin_mm']), 'gap_overshoot_mm': float(P['gap_overshoot_mm'])}
    fit = {'upper_click': upper, 'lower_click': lower, 'gap_start_lines': {k: {'slope': gap[k][0], 'intercept_y': gap[k][1], **gap[k + '_fit']} for k in ('upper', 'lower')},
           'gap_mid_line': {'slope': gap['mid'][0], 'intercept_y': gap['mid'][1]}, 'gap_lines_merged': bool(gap['merged']), 'gap_line_separation_mm': gap['line_separation_mm'],
           'perimeter': {'vertices_after_fit': int(len(per['path'])), 'fillet_radius_mm': per['R'], 'fit_rms_mm': per['rms'], 'fit_max_mm': per['max'], 'stations': int(len(per['A'])),
                         'outward_sign_along_left_normal': per['out'], 'encroachment': per['encroachment']},
           'window': ({k: window[k] for k in ('corners_TR_TL_BL_BR', 'corner_radius_mm', 'dims_mm', 'rim_plane', 'floor_plane', 'gap_x_range', 'edge_fit_dev_mm', 'source', 'min_wall_raise_mm')} if window else None),
           'slot_stations': {k: infos[i]['n'] for i, k in enumerate([x['tag'] for x in infos])}}
    return {'status': 'OK', 'worker': WORKER_VERSION, 'files': files, 'metrics': metrics, 'fit': fit, 'params_used': params_used, 'warnings': warnings,
            'seconds': round(time.time() - t_start, 1), 'libs': {'manifold3d': getattr(mf, '__version__', None), 'shapely': shp.__version__, 'trimesh': tm.__version__}}


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
    return {'hole': best[1], 'wheel_xy': wxy, 'PA': PA, 'PB': PB}


def _finish_window(win: dict[str, Any], V, F, zf, gap, P, shp, warnings) -> None:
    hole, PA, PB = win['hole'], win['PA'], win['PB']
    x0, y0, x1, y1 = hole.bounds
    cx, cy, w, h = (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0
    raw = np.vstack([_densify(shp, PA.exterior, 0.05), _densify(shp, PB.exterior, 0.05)])
    d = shp.distance(hole.exterior, shp.points(raw))
    raw = raw[d < 0.35]
    gy = gap['mid'][0] * raw[:, 0] + gap['mid'][1]
    gapm = np.abs(raw[:, 1] - gy) < 1.0
    sel = {
        'top': raw[(raw[:, 1] > cy) & (np.abs(raw[:, 0] - cx) < 0.3 * w)],
        'bottom': raw[(raw[:, 1] < cy) & (np.abs(raw[:, 0] - cx) < 0.3 * w)],
        'left': raw[(raw[:, 0] < cx) & (np.abs(raw[:, 1] - cy) < 0.28 * h) & ~gapm],
        'right': raw[(raw[:, 0] > cx) & (np.abs(raw[:, 1] - cy) < 0.28 * h) & ~gapm]}
    for k, pts in sel.items():
        if len(pts) < 8:
            warnings.append({'code': 'WINDOW_EDGE_UNSUPPORTED', 'edge': k, 'note': 'Too few outline points on this window edge; the window is not rebuilt.'})
            win.clear()
            win['failed'] = True
            return
    pt = robust_line(sel['top'][:, 0], sel['top'][:, 1])
    pb = robust_line(sel['bottom'][:, 0], sel['bottom'][:, 1])
    pl = robust_line(sel['left'][:, 1], sel['left'][:, 0])        # x = a y + b
    pr = robust_line(sel['right'][:, 1], sel['right'][:, 0])

    def corner(pa, pc):
        y = (pa[0] * pc[1] + pa[1]) / (1 - pa[0] * pc[0])
        return np.array([pc[0] * y + pc[1], y])
    C = np.array([corner(pt, pr), corner(pt, pl), corner(pb, pl), corner(pb, pr)])      # TR, TL, BL, BR
    cp = raw[(np.linalg.norm(raw[:, None, :] - C[None], axis=2).min(1) < 5.0) & ~gapm]
    rmax = 0.45 * min(np.linalg.norm(C[0] - C[1]), np.linalg.norm(C[1] - C[2]))
    best = (1e9, 0.5)
    if len(cp):
        for Rr in np.arange(0.5, min(6.0, rmax) + 1e-9, 0.25):
            e = seg_dist(cp, fillet_closed(C, Rr), closed=True)
            rms = float(np.sqrt((e ** 2).mean()))
            if rms < best[0] - 1e-9:
                best = (rms, float(Rr))
    Rw = best[1]
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
    dev = {}
    for k, pts, (ax, pp) in (('top', sel['top'], (0, pt)), ('bottom', sel['bottom'], (0, pb)), ('left', sel['left'], (1, pl)), ('right', sel['right'], (1, pr))):
        tt, vv = (pts[:, 0], pts[:, 1]) if ax == 0 else (pts[:, 1], pts[:, 0])
        r = np.abs(vv - np.polyval(pp, tt)) / np.sqrt(1 + pp[0] ** 2)
        dev[k] = {'max': float(r.max()), 'rms': float(np.sqrt((r ** 2).mean()))}
    FLOOR = float(coef[0])
    win.update({'poly': poly, 'poly_geom': pg, 'corners_TR_TL_BL_BR': C.round(4).tolist(), 'corner_radius_mm': Rw, 'corner_fit_rms_mm': best[0],
                'dims_mm': {'width_x': float(np.linalg.norm(C[0] - C[1])), 'height_y': float(np.linalg.norm(C[1] - C[2]))},
                'rim_plane': {'a': float(coef[0]), 'b': float(coef[1]), 'c': float(coef[2]), 'resid_max_mm': float(np.abs(resid).max()), 'resid_rms_mm': float(resid.std())},
                'edge_fit_dev_mm': dev, 'gap_x_range': [float(gx[0]), float(gx[2])], 'source': 'hole of the closed click outline holding the wheel',
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
    path = fit_polyline(T, float(P['fit_tolerance_mm']))
    given = P.get('fillet_radius_mm')
    if given:
        Rsel = float(given)
        A = fillet_open(path, Rsel)
    else:
        scan = []
        for Rr in np.arange(0.5, 6.01, 0.25):
            e = seg_dist(T, fillet_open(path, Rr))
            scan.append((float(Rr), float(np.sqrt((e ** 2).mean()))))
        rbest = min(r for _, r in scan)
        Rsel = max(Rr for Rr, r in scan if r <= rbest + 0.002)       # the outline barely constrains R: the largest radius that fits as well as the best (within 2 micrometres rms)
        A = fillet_open(path, Rsel)
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
    clear = float(P['perimeter_clearance_mm'])
    shift = max(0.0, float(d_in.max())) + clear
    Aout = Q0 + sgn * shift * nl
    d_after = depth_inside(Aout)
    for _ in range(12):                      # the outline is not parallel to the path everywhere: push on until nothing is inside
        if d_after.max() <= -clear + 1e-9:
            break
        shift += float(d_after.max()) + clear
        Aout = Q0 + sgn * shift * nl
        d_after = depth_inside(Aout)
    enc = {'max_inside_before_mm': float(d_in.max()), 'shift_outward_mm': float(shift), 'max_inside_after_mm': float(d_after.max())}
    return {'path': path, 'A': Aout, 'R': Rsel, 'rms': float(np.sqrt((d ** 2).mean())), 'max': float(d.max()), 'out': sgn, 'encroachment': enc}


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
                        'wall_faces_nz_gt_0p01': int((nz[wall] > 0.01).sum()), 'wall_area_mm2': float(area[wall].sum()), 'floor_like': int((~wall).sum()),
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
