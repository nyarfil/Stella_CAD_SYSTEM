"""Cable pocket fill on the front wall of a welded scan mesh. SUBPROCESS WORKER (like scan_flush_worker.py).

Run as:  <scan python> scan_cable_fill_worker.py request.json
Needs numpy, scipy, trimesh and shapely >= 2.1 (extra `scan-grooves`). Request and result are JSON; the result is the last stdout line.

The cable hole / USB pocket of a scan is unreliable (grade C): the front wall of the shell is designed PLAIN, so the pocket is not followed but
filled with the wall inferred from the trusted wall around it. Generic, no mouse-specific coordinates (wired or wireless, any position,
asymmetric allowed). Frame: standard (x front, y left, z up); the front side is +x unless the click labels lie on the -x side.

  1 front view   rays along -x over a grid_mm grid in (y, z) against the faces within front_depth_mm of the most forward point give the front
                 height field H(y, z) (first hit), the hit face and its normal. Trusted wall = front-facing hits (n_x > front_nx) whose face is
                 not in exclude_regions (wheel, side buttons, sensor: labels are hints only).
  2 global wall  normalised Gaussian smoothing of H over the trusted cells (sigma detect_sigma_mm), iterated with one-sided trimming (cells
                 deeper than min_depth_mm / 2 below the wall leave the fit), gives the wall S. Recess = S - H >= min_depth_mm, or an
                 enclosed cell with no hit (through hole).
  3 pockets      morphological opening with a disk of diameter min_width_mm (grooves and slits are narrower and stay), connected components
                 with area >= min_area_mm2. No component => READY no-op (the mesh is copied unchanged).
  4 inferred     per pocket a polynomial x = P(y, z) of total degree `degree` is fitted to the trusted ring (ring_mm wide, recesses and
    wall          grooves trimmed one-sidedly, robust IRLS). Gates: ring residual p95 <= smooth_tol_mm, minimum principal radius of P over
                 the pocket >= min_radius_mm (straight or gentle R), ring coverage >= MIN_RING_COVER, area <= max_area_mm2.
  5 patch        the pocket faces (centroid in the footprint dilated by margin_mm, or near it and below the wall) are removed; the new
                 boundary loop (must be one simple polygon in (y, z)) is triangulated (constrained Delaunay + longest-edge bisection to
                 patch_edge_mm + Laplacian smoothing), lifted onto P with the loop residual blended out over blend_mm, oriented outward and
                 labelled with the nearest rim region. Small extra loops (<= CAP_MAX_EDGES) are fan-capped.
Outputs: filled.stl (kept faces in input order, then patch faces), labels (same codes, patch faces labelled), cable_fill.npz (grid, H, S,
pocket mask, P samples, face_source: input face id per output face or -1).
"""
from __future__ import annotations
import heapq
import json
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any
import numpy as np

WORKER_VERSION = 'scan_cable_fill/1'
DEFAULTS = {'grid_mm': 0.25, 'front_depth_mm': 20.0, 'front_nx': 0.5, 'detect_sigma_mm': 4.0, 'min_depth_mm': 0.8, 'min_width_mm': 2.0,
            'min_area_mm2': 4.0, 'max_area_mm2': 600.0, 'ring_mm': 4.0, 'degree': 3, 'smooth_tol_mm': 0.3, 'min_radius_mm': 8.0,
            'margin_mm': 0.5, 'patch_edge_mm': 0.6, 'blend_mm': 1.5}
DEFAULT_EXCLUDE = ('wheel', 'side_button_1', 'side_button_2', 'sensor', 'WH', 'B1', 'B2')
CLICK_NAMES = ('left_click', 'right_click', 'LC', 'RC')
MIN_RING_COVER = 0.5
MIN_RING_KEPT = 0.5         # at least this fraction of the ring must agree with the inferred wall
MIN_TRUSTED_CELLS = 200
CAP_MAX_EDGES = 40
TRIM_MM = 0.25
RIM_MIN_NX = 0.2           # a rim face of the patch must face the front at least this much (n_x)


class CableError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


# ------------------------------------------------------------------ labels
def read_labels(path: Path | None, n_faces: int) -> tuple[np.ndarray, dict[int, str], str]:
    """(code per face, code -> name, kind 'npz'|'json'|'none'). Unlabelled faces get code -1 (json) / their npz code."""
    if path is None:
        return np.full(n_faces, -1, np.int64), {}, 'none'
    if path.suffix.lower() == '.npz':
        z = np.load(path, allow_pickle=False)
        if 'face_labels' not in z or 'codes' not in z:
            raise CableError('CABLE_LABELS', 'An .npz label file needs the arrays face_labels and codes ("name=code").')
        fl = np.asarray(z['face_labels']).astype(np.int64)
        if len(fl) != n_faces:
            raise CableError('CABLE_LABELS', 'face_labels has a different length than the mesh has faces.', {'labels': int(len(fl)), 'faces': int(n_faces)})
        names = {}
        for item in z['codes']:
            nm, code = str(item).rsplit('=', 1)
            names[int(code)] = nm
        return fl, names, 'npz'
    data = json.loads(path.read_text(encoding='utf-8'))
    data = data.get('regions', data) if isinstance(data, dict) else data
    if not isinstance(data, dict):
        raise CableError('CABLE_LABELS', 'The label JSON must map region names to face id lists.')
    fl = np.full(n_faces, -1, np.int64)
    names = {}
    for i, (nm, val) in enumerate(data.items()):
        val = val.get('face_ids') if isinstance(val, dict) else val
        if not isinstance(val, list):
            continue
        ids = np.asarray(val, dtype=np.int64)
        if len(ids) and (ids.min() < 0 or ids.max() >= n_faces):
            raise CableError('CABLE_LABELS', f'Region {nm} has face ids outside the mesh.')
        fl[ids] = i
        names[i] = str(nm)
    return fl, names, 'json'


def write_labels(out_dir: Path, kind: str, fl: np.ndarray, names: dict[int, str]) -> str | None:
    if kind == 'npz':
        codes = np.array([f'{nm}={c}' for c, nm in sorted(names.items())])
        np.savez(out_dir / 'labels.npz', face_labels=fl.astype(np.uint8 if fl.min() >= 0 and fl.max() < 256 else np.int32), codes=codes)
        return 'labels.npz'
    if kind == 'json':
        (out_dir / 'labels.json').write_text(json.dumps({nm: np.flatnonzero(fl == c).tolist() for c, nm in sorted(names.items())}), encoding='utf-8')
        return 'labels.json'
    return None


# ------------------------------------------------------------------ geometry helpers
def face_geometry(V: np.ndarray, F: np.ndarray):
    tri = V[F]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    a = np.linalg.norm(n, axis=1)
    return n / np.maximum(a, 1e-300)[:, None], a / 2.0, tri.mean(1)


def disk(r_cells: float) -> np.ndarray:
    r = max(int(np.ceil(r_cells)), 0)
    yy, zz = np.mgrid[-r:r + 1, -r:r + 1]
    return (yy ** 2 + zz ** 2) <= r_cells ** 2 + 1e-9


def front_view(Vp: np.ndarray, F: np.ndarray, cand: np.ndarray, g: float):
    """Height field of the most forward surface point along -x' over a (y, z) grid (z-buffer rasterisation of the candidate faces at the cell
    centres, = the first hit of a ray along -x'). Returns grid axes, H (nan = no hit), hit face id (-1 none)."""
    sub = np.flatnonzero(cand)
    T = Vp[F[sub]]
    lo, hi = T.reshape(-1, 3).min(0), T.reshape(-1, 3).max(0)
    ys = np.arange(lo[1] - g, hi[1] + g + 1e-9, g)
    zs = np.arange(lo[2] - g, hi[2] + g + 1e-9, g)
    ny, nz = len(ys), len(zs)
    H = np.full(ny * nz, -np.inf)
    hid = np.full(ny * nz, -1, np.int64)
    a, b, c = T[:, 0], T[:, 1], T[:, 2]
    det = (b[:, 1] - a[:, 1]) * (c[:, 2] - a[:, 2]) - (c[:, 1] - a[:, 1]) * (b[:, 2] - a[:, 2])
    ok = np.abs(det) > 1e-12
    iy0 = np.ceil((T[:, :, 1].min(1) - ys[0]) / g - 1e-9).astype(np.int64)
    iy1 = np.floor((T[:, :, 1].max(1) - ys[0]) / g + 1e-9).astype(np.int64)
    iz0 = np.ceil((T[:, :, 2].min(1) - zs[0]) / g - 1e-9).astype(np.int64)
    iz1 = np.floor((T[:, :, 2].max(1) - zs[0]) / g + 1e-9).astype(np.int64)
    cy, cz = np.maximum(iy1 - iy0 + 1, 0), np.maximum(iz1 - iz0 + 1, 0)
    cnt = np.where(ok, cy * cz, 0)
    CH = 4_000_000
    order = np.arange(len(sub))
    start = 0
    csum = np.cumsum(cnt)
    while start < len(order):
        base = csum[start - 1] if start else 0
        stop = int(np.searchsorted(csum, base + CH, side='right'))
        stop = max(stop, start + 1)
        k = order[start:stop]
        n = cnt[k]
        f = np.repeat(k, n)
        if len(f):
            off = np.arange(len(f)) - np.repeat(np.cumsum(n) - n, n)
            jy = iy0[f] + off // np.maximum(cz[f], 1)
            jz = iz0[f] + off % np.maximum(cz[f], 1)
            py, pz = ys[0] + jy * g, zs[0] + jz * g
            l1 = ((b[f, 1] - py) * (c[f, 2] - pz) - (c[f, 1] - py) * (b[f, 2] - pz)) / det[f]
            l2 = ((c[f, 1] - py) * (a[f, 2] - pz) - (a[f, 1] - py) * (c[f, 2] - pz)) / det[f]
            l3 = 1.0 - l1 - l2
            inn = (l1 >= -1e-9) & (l2 >= -1e-9) & (l3 >= -1e-9)
            x = l1 * a[f, 0] + l2 * b[f, 0] + l3 * c[f, 0]
            cell = jy * nz + jz
            f, x, cell = f[inn], x[inn], cell[inn]
            o = np.lexsort((-x, cell))
            f, x, cell = f[o], x[o], cell[o]
            first = np.r_[True, cell[1:] != cell[:-1]]
            f, x, cell = f[first], x[first], cell[first]
            better = x > H[cell]
            H[cell[better]] = x[better]
            hid[cell[better]] = sub[f[better]]
        start = stop
    H[~np.isfinite(H)] = np.nan
    return ys, zs, H.reshape(ny, nz), hid.reshape(ny, nz)


def gsmooth(H: np.ndarray, W: np.ndarray, sig: float, g: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Gaussian-weighted local QUADRATIC regression of H over the cells W (sigma sig cells): returns (wall value, support 0..1).
    A local quadratic has no gradient bias at the edge of the trusted area and no curvature bias, so one-sided trimming does not ratchet."""
    from scipy.signal import fftconvolve
    r = int(np.ceil(3 * sig))
    dy, dz = np.mgrid[-r:r + 1, -r:r + 1].astype(float)
    G = np.exp(-(dy ** 2 + dz ** 2) / (2 * sig ** 2))
    dy, dz = dy * g, dz * g
    Wf = W.astype(float)
    Hw = np.where(W, np.nan_to_num(H), 0.0)
    exps = [(0, 0), (1, 0), (0, 1), (2, 0), (1, 1), (0, 2)]
    mom = {}

    def M(a, b, src):
        key = (a, b, id(src))
        if key not in mom:
            mom[key] = fftconvolve(src, ((-1) ** (a + b)) * G * dy ** a * dz ** b, mode='same')
        return mom[key]
    n = len(exps)
    A = np.empty(H.shape + (n, n))
    rhs = np.empty(H.shape + (n,))
    for i, (a1, b1) in enumerate(exps):
        rhs[..., i] = M(a1, b1, Hw)
        for j, (a2, b2) in enumerate(exps):
            A[..., i, j] = M(a1 + a2, b1 + b2, Wf)
    support = A[..., 0, 0] / G.sum()
    tr = np.trace(A, axis1=-2, axis2=-1)[..., None]
    A = A + (1e-6 * tr + 1e-12)[..., None] * np.eye(n)
    c = np.linalg.solve(A, rhs[..., None])[..., 0]
    return c[..., 0], support


def poly_terms(y: np.ndarray, z: np.ndarray, deg: int) -> np.ndarray:
    return np.stack([y ** i * z ** j for i in range(deg + 1) for j in range(deg + 1 - i)], 1)


class Poly:
    def __init__(self, coef, deg, c, s):
        self.coef, self.deg, self.c, self.s = coef, deg, c, s

    def __call__(self, y, z):
        u, v = (np.asarray(y, float) - self.c[0]) / self.s, (np.asarray(z, float) - self.c[1]) / self.s
        return poly_terms(np.atleast_1d(u), np.atleast_1d(v), self.deg) @ self.coef

    def derivs(self, y, z, h=1e-3):
        f = self.__call__
        fy = (f(y + h, z) - f(y - h, z)) / (2 * h)
        fz = (f(y, z + h) - f(y, z - h)) / (2 * h)
        fyy = (f(y + h, z) - 2 * f(y, z) + f(y - h, z)) / h ** 2
        fzz = (f(y, z + h) - 2 * f(y, z) + f(y, z - h)) / h ** 2
        fyz = (f(y + h, z + h) - f(y + h, z - h) - f(y - h, z + h) + f(y - h, z - h)) / (4 * h ** 2)
        return fy, fz, fyy, fzz, fyz


def fit_poly(y, z, x, deg: int, iters: int = 8) -> tuple[Poly, np.ndarray]:
    c = np.array([y.mean(), z.mean()])
    s = max(float(np.ptp(y)), float(np.ptp(z)), 1e-6) / 2
    A = poly_terms((y - c[0]) / s, (z - c[1]) / s, deg)
    keep = np.ones(len(x), bool)
    w = np.ones(len(x))
    coef = None
    for _ in range(iters):
        sw = np.sqrt(w * keep)
        coef = np.linalg.lstsq(A * sw[:, None], x * sw, rcond=None)[0]
        r = x - A @ coef
        mad = 1.4826 * np.median(np.abs(r[keep] - np.median(r[keep]))) + 1e-6
        new = (r > -TRIM_MM) & (np.abs(r) < max(4 * mad, 0.15))   # one-sided: recesses / grooves leave; outliers above too
        w = 1.0 / np.maximum(1.0, np.abs(r) / max(1.5 * mad, 0.02))
        if new.sum() < A.shape[1] * 3 or (new == keep).all():
            break
        keep = new
    return Poly(coef, deg, c, s), keep


def min_radius(P: Poly, y, z) -> float:
    fy, fz, fyy, fzz, fyz = P.derivs(y, z)
    kmax = 0.0
    for a, b, A, B, C in zip(fy, fz, fyy, fzz, fyz):
        g = np.array([a, b])
        I = np.eye(2) + np.outer(g, g)
        II = np.array([[A, C], [C, B]]) / np.sqrt(1 + g @ g)
        k = np.linalg.eigvals(np.linalg.solve(I, II)).real
        kmax = max(kmax, float(np.abs(k).max()))
    return float('inf') if kmax < 1e-9 else 1.0 / kmax


# ------------------------------------------------------------------ mesh surgery
def edges_of(F: np.ndarray) -> np.ndarray:
    return np.r_[F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]


def boundary_loops(F: np.ndarray, touch: set) -> tuple[list[list[int]], int]:
    """Boundary cycles of F that contain a vertex in `touch`. Returns (cycles, number of non-simple boundary vertices)."""
    E = np.sort(edges_of(F), 1)
    u, c = np.unique(E, axis=0, return_counts=True)
    be = u[c == 1]
    adj = defaultdict(list)
    for a, b in be:
        adj[int(a)].append(int(b))
        adj[int(b)].append(int(a))
    seen, cycles, bad = set(), [], 0
    for s in list(adj):
        if s in seen:
            continue
        comp, st = [s], [s]
        seen.add(s)
        while st:
            a = st.pop()
            for b in adj[a]:
                if b not in seen:
                    seen.add(b)
                    st.append(b)
                    comp.append(b)
        if not touch.intersection(comp):
            continue
        if any(len(adj[v]) != 2 for v in comp):
            bad += sum(len(adj[v]) != 2 for v in comp)
            continue
        order, prev = [comp[0]], None
        while True:
            cur = order[-1]
            nxt = [b for b in adj[cur] if b != prev][0]
            if nxt == order[0]:
                break
            prev = cur
            order.append(nxt)
        cycles.append(order)
    return cycles, bad


def refine(P2: np.ndarray, T: np.ndarray, nb: int, h: float, max_pts: int = 200000):
    """Longest-edge bisection of interior edges longer than h (edges between the first nb points along the loop are never split)."""
    pts = [tuple(p) for p in P2]
    tris = [list(t) for t in T]
    bset = {tuple(sorted((i, (i + 1) % nb))) for i in range(nb)}
    e2t = defaultdict(set)
    for ti, t in enumerate(tris):
        for k in range(3):
            e2t[tuple(sorted((t[k], t[(k + 1) % 3])))].add(ti)

    def L(e):
        a, b = pts[e[0]], pts[e[1]]
        return float(np.hypot(a[0] - b[0], a[1] - b[1]))
    heap = [(-L(e), e) for e in e2t if e not in bset and L(e) > h]
    heapq.heapify(heap)
    while heap and len(pts) < max_pts:
        _, e = heapq.heappop(heap)
        ts = e2t.get(e)
        if not ts:
            continue
        a, b = pts[e[0]], pts[e[1]]
        m = len(pts)
        pts.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
        del e2t[e]
        for ti in list(ts):
            t = tris[ti]
            k = next(k for k in range(3) if {t[k], t[(k + 1) % 3]} == set(e))
            t0, t1, t2 = t[k], t[(k + 1) % 3], t[(k + 2) % 3]
            for kk in range(3):
                ee = tuple(sorted((t[kk], t[(kk + 1) % 3])))
                if ee in e2t:
                    e2t[ee].discard(ti)
            new = [[t0, m, t2], [m, t1, t2]]
            tris[ti] = new[0]
            tris.append(new[1])
            for nti, nt in ((ti, new[0]), (len(tris) - 1, new[1])):
                for kk in range(3):
                    ee = tuple(sorted((nt[kk], nt[(kk + 1) % 3])))
                    e2t[ee].add(nti)
            for ee in (tuple(sorted((t0, m))), tuple(sorted((m, t1))), tuple(sorted((m, t2)))):
                if L(ee) > h:
                    heapq.heappush(heap, (-L(ee), ee))
    return np.array(pts), np.array(tris, np.int64)


def signed_area(P2, T):
    a, b, c = P2[T[:, 0]], P2[T[:, 1]], P2[T[:, 2]]
    return 0.5 * ((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))


def smooth2d(P2, T, nb, iters=10):
    nbrs = defaultdict(set)
    for t in T:
        for k in range(3):
            nbrs[t[k]].update((t[(k + 1) % 3], t[(k + 2) % 3]))
    inner = np.arange(nb, len(P2))
    if not len(inner):
        return P2
    s0 = np.sign(signed_area(P2, T))
    for _ in range(iters):
        Q = P2.copy()
        for v in inner:
            Q[v] = P2[list(nbrs[v])].mean(0)
        if (np.sign(signed_area(Q, T)) != s0).any() or (np.abs(signed_area(Q, T)) < 1e-9).any():
            break
        P2 = Q
    return P2


def crossing_vertices(L2: np.ndarray) -> np.ndarray:
    """Loop vertex indices of segments that cross a non-adjacent segment (or of coincident projected points) in the front view."""
    n = len(L2)
    A, B = L2, np.roll(L2, -1, 0)
    i, j = np.triu_indices(n, 2)
    k = ~((i == 0) & (j == n - 1))
    i, j = i[k], j[k]

    def orient(p, q, r):
        return (q[:, 0] - p[:, 0]) * (r[:, 1] - p[:, 1]) - (q[:, 1] - p[:, 1]) * (r[:, 0] - p[:, 0])
    d1, d2 = orient(A[i], B[i], A[j]), orient(A[i], B[i], B[j])
    d3, d4 = orient(A[j], B[j], A[i]), orient(A[j], B[j], B[i])
    eps = 1e-12
    hit = (d1 * d2 < -eps) & (d3 * d4 < -eps)                       # proper crossing

    def on_seg(p, q, r, d):                                          # r collinear with p-q and inside its box
        return (np.abs(d) <= eps) & (np.minimum(p[:, 0], q[:, 0]) - 1e-9 <= r[:, 0]) & (r[:, 0] <= np.maximum(p[:, 0], q[:, 0]) + 1e-9)             & (np.minimum(p[:, 1], q[:, 1]) - 1e-9 <= r[:, 1]) & (r[:, 1] <= np.maximum(p[:, 1], q[:, 1]) + 1e-9)
    adj = (j == i + 1) | ((i == 0) & (j == n - 1))
    touch = on_seg(A[i], B[i], A[j], d1) | on_seg(A[i], B[i], B[j], d2) | on_seg(A[j], B[j], A[i], d3) | on_seg(A[j], B[j], B[i], d4)
    hit |= touch & ~adj
    _, inv, cnt = np.unique(np.round(L2, 9), axis=0, return_inverse=True, return_counts=True)
    dup = np.flatnonzero(cnt[inv.ravel()] > 1)
    bad = np.unique(np.r_[i[hit], (i[hit] + 1) % n, j[hit], (j[hit] + 1) % n, dup])
    return bad.astype(np.int64)


def triangulate_loop(loop2d: np.ndarray, h: float):
    import shapely
    from shapely.geometry import Polygon
    poly = Polygon(loop2d)
    if not poly.is_valid or poly.area <= 0:
        raise CableError('CABLE_LOOP_NOT_SIMPLE', 'The boundary loop of the removed pocket is not a simple polygon in the front view.', {'reason': shapely.is_valid_reason(poly)})
    key = {tuple(p): i for i, p in enumerate(loop2d.tolist())}
    if len(key) != len(loop2d):
        raise CableError('CABLE_LOOP_NOT_SIMPLE', 'Two loop vertices project onto the same front-view point.')
    tris = []
    for tri in shapely.constrained_delaunay_triangles(poly).geoms:
        cs = list(tri.exterior.coords)[:3]
        try:
            tris.append([key[tuple(c)] for c in cs])
        except KeyError as exc:
            raise CableError('CABLE_TRIANGULATION', 'The constrained triangulation returned a vertex that is not on the loop.') from exc
    T = np.array(tris, np.int64)
    T[signed_area(loop2d, T) < 0] = T[signed_area(loop2d, T) < 0][:, ::-1]
    P2, T = refine(loop2d, T, len(loop2d), h)
    P2 = smooth2d(P2, T, len(loop2d))
    return P2, T


# ------------------------------------------------------------------ main
def run(req: dict[str, Any]) -> dict[str, Any]:
    import trimesh
    from scipy import ndimage as ndi
    from scipy.spatial import cKDTree
    t0 = time.time()
    p = {**DEFAULTS, **(req.get('params') or {})}
    exclude = tuple(req.get('exclude_regions') or DEFAULT_EXCLUDE)
    src = trimesh.load(req['input_path'], force='mesh', process=False)
    V = np.asarray(src.vertices, float) * float(req.get('unit_scale', 1.0))
    F = np.asarray(src.faces, np.int64)
    # weld coincident vertices (an STL stores every triangle separately); face order and count are unchanged
    _, first, inv = np.unique(np.round(V, 6), axis=0, return_index=True, return_inverse=True)
    V, F = V[first], inv.ravel()[F]
    nF = len(F)
    lab_path = Path(req['labels_path']) if req.get('labels_path') else None
    fl, names, kind = read_labels(lab_path, nF)
    fn, fa, cen = face_geometry(V, F)
    excl_codes = [c for c, nm in names.items() if nm in exclude]
    excluded = np.isin(fl, excl_codes)
    warnings: list[dict[str, Any]] = []
    # front side: +x unless the click labels lie behind the mesh centre
    sign, front_source = 1.0, 'standard frame (+x)'
    click_codes = [c for c, nm in names.items() if nm in CLICK_NAMES]
    if click_codes and np.isin(fl, click_codes).any():
        cc = cen[np.isin(fl, click_codes)][:, 0].mean()
        if cc < (V[:, 0].min() + V[:, 0].max()) / 2:
            sign, front_source = -1.0, 'click labels on the -x side'
        else:
            front_source = 'click labels on the +x side'
    Vp = V.copy()
    Vp[:, 0] *= sign
    Fp_ = F[:, ::-1].copy() if sign < 0 else F      # a mirror flips the winding: keep the outward normals outward in the work frame
    fnx = fn[:, 0] * sign
    cenx = cen[:, 0] * sign
    g = float(p['grid_mm'])
    xmax = float(Vp[:, 0].max())
    cand = (Vp[F].max(1)[:, 0] >= xmax - p['front_depth_mm'])
    ys, zs, H, hid = front_view(Vp, Fp_, cand, g)
    hit = hid >= 0
    nxh = np.where(hit, fnx[np.maximum(hid, 0)], -1.0)
    exh = np.where(hit, excluded[np.maximum(hid, 0)], False)
    trusted = hit & (nxh > p['front_nx']) & ~exh
    grid = {'y0': float(ys[0]), 'z0': float(zs[0]), 'ny': int(len(ys)), 'nz': int(len(zs)), 'grid_mm': g}
    base = {'status': 'OK', 'worker': WORKER_VERSION, 'params_used': {**p, 'exclude_regions': list(exclude)}, 'front': {'sign': sign, 'source': front_source, 'x_front_mm': xmax * sign},
            'grid': grid, 'trusted_cells': int(trusted.sum())}
    out_dir = Path(req['out_dir'])
    out_dir.mkdir(parents=True, exist_ok=True)
    if trusted.sum() < MIN_TRUSTED_CELLS:
        return {**base, 'ready': False, 'blocking': ['CABLE_FRONT_WALL_NOT_FOUND'], 'pockets': [], 'applied': False, 'files': {}, 'warnings': warnings,
                'seconds': round(time.time() - t0, 2)}
    # ---- global wall S and recess mask
    sig = p['detect_sigma_mm'] / g
    W = trusted.copy()
    for _ in range(8):
        S, den = gsmooth(H, W, sig, g)
        neww = trusted & ~(H < S - 0.5 * p['min_depth_mm'])
        if (neww == W).all():
            break
        W = neww
    support = ndi.gaussian_filter(ndi.binary_fill_holes(trusted).astype(float), sig, mode='constant')
    enclosed_nohit = ndi.binary_fill_holes(trusted) & ~hit
    recess = (support >= 0.6) & (((S - H) >= p['min_depth_mm']) & hit & ~exh | enclosed_nohit)
    opened = ndi.binary_opening(recess, structure=disk(p['min_width_mm'] / 2 / g))
    comp, nc = ndi.label(opened)
    areas = ndi.sum(np.ones_like(H), comp, index=np.arange(1, nc + 1)) * g * g if nc else np.zeros(0)
    pockets_idx = [i + 1 for i in range(nc) if areas[i] >= p['min_area_mm2']]
    pockets_idx.sort(key=lambda k: -areas[k - 1])
    blocking: list[str] = []
    pockets: list[dict[str, Any]] = []
    Vout, Fout, lout = Vp.copy(), Fp_.copy(), fl.copy()
    fsrc = np.arange(nF)
    pmask_all = np.zeros(H.shape, bool)
    Pgrid = np.full(H.shape, np.nan)
    YY, ZZ = np.meshgrid(ys, zs, indexing='ij')
    for k in pockets_idx:
        pk = comp == k
        pmask_all |= pk
        area = float(pk.sum() * g * g)
        info: dict[str, Any] = {'area_yz_mm2': round(area, 2), 'y_range_mm': [round(float(YY[pk].min()), 2), round(float(YY[pk].max()), 2)],
                                'z_range_mm': [round(float(ZZ[pk].min()), 2), round(float(ZZ[pk].max()), 2)],
                                'centre_yz_mm': [round(float(YY[pk].mean()), 2), round(float(ZZ[pk].mean()), 2)], 'through_hole': bool((pk & ~hit).any())}
        pockets.append(info)
        if area > p['max_area_mm2']:
            info['blocking'] = 'CABLE_POCKET_TOO_LARGE'
            blocking.append('CABLE_POCKET_TOO_LARGE')
            continue
        rc = p['ring_mm'] / g
        ring_all = ndi.binary_dilation(pk, structure=disk(rc)) & ~ndi.binary_dilation(pk, structure=disk(max(1.0, 0.5 / g)))
        ring = ring_all & trusted & ~recess
        cover = float(ring.sum() / max(ring_all.sum(), 1))
        info['ring_cover'] = round(cover, 3)
        if cover < MIN_RING_COVER or ring.sum() < 30:
            info['blocking'] = 'CABLE_RING_INCOMPLETE'
            blocking.append('CABLE_RING_INCOMPLETE')
            continue
        P, keep = fit_poly(YY[ring], ZZ[ring], H[ring], int(p['degree']))
        r_ring = H[ring] - P(YY[ring], ZZ[ring])
        r_keep = r_ring[r_ring > -TRIM_MM]          # smoothness: every ring cell except the one-sided recess / groove cells
        r_all = H[ring_all & hit] - P(YY[ring_all & hit], ZZ[ring_all & hit])
        sel = np.flatnonzero(pk.ravel())
        sel = sel[:: max(1, len(sel) // 400)]
        rad = min_radius(P, YY.ravel()[sel], ZZ.ravel()[sel])
        Pk = P(YY[pk], ZZ[pk])
        Pgrid[pk] = Pk
        depth = Pk - H[pk]
        info.update(ring_fit={'cells': int(ring.sum()), 'kept_fraction': round(float(keep.mean()), 3), 'p50_mm': round(float(np.median(np.abs(r_keep))), 4),
                              'p95_mm': round(float(np.percentile(np.abs(r_keep), 95)), 4), 'max_mm': round(float(np.abs(r_keep).max()), 4)},
                    wall_vs_surrounding={'p50_mm': round(float(np.median(np.abs(r_all))), 4), 'p95_mm': round(float(np.percentile(np.abs(r_all), 95)), 4),
                                         'note': 'inferred wall P vs every hit ring cell (grooves included)'},
                    inferred_min_radius_mm=(None if not np.isfinite(rad) else round(rad, 2)), degree=int(p['degree']),
                    fill_depth_mm={'max': round(float(np.nanmax(depth)), 3) if np.isfinite(depth).any() else None,
                                   'mean': round(float(np.nanmean(depth)), 3) if np.isfinite(depth).any() else None},
                    fill_volume_mm3=round(float(np.nansum(np.clip(depth, 0, None)) * g * g), 2))
        if info['ring_fit']['p95_mm'] > p['smooth_tol_mm'] or rad < p['min_radius_mm'] or keep.mean() < MIN_RING_KEPT:
            info['blocking'] = 'CABLE_INFERRED_WALL_NOT_SMOOTH'
            blocking.append('CABLE_INFERRED_WALL_NOT_SMOOTH')
            continue
        # ---- surgery on the current mesh
        try:
            Vout, Fout, lout, fsrc, patch = fill_pocket(Vout, Fout, lout, fsrc, P, pk, ys, zs, g, p, excluded_codes=excl_codes,
                                                        maxdepth=float(np.nanmax(depth)) if np.isfinite(depth).any() else p['front_depth_mm'])
        except CableError as exc:
            info['blocking'] = exc.code
            info['blocking_details'] = exc.details
            blocking.append(exc.code)
            continue
        info['patch'] = patch
        for wcode in patch.pop('warnings', []):
            warnings.append({'code': wcode, 'message': f'pocket at y,z {info["centre_yz_mm"]}: see patch report'})
    # outputs
    applied = any('patch' in q for q in pockets) and not blocking
    Vfin = Vout.copy()
    Vfin[:, 0] *= sign
    files: dict[str, Any] = {}
    np.savez_compressed(out_dir / 'cable_fill.npz', ys=ys, zs=zs, H=H, S=S, pocket=pmask_all, P=Pgrid, trusted=trusted, recess=recess,
                        face_source=fsrc if not blocking else np.zeros(0, np.int64))
    files['diagnostics'] = {'file': 'cable_fill.npz'}
    if not blocking:
        if applied:
            used = np.unique(Fout)
            remap = np.full(len(Vfin), -1, np.int64)
            remap[used] = np.arange(len(used))
            Vw, Fw = Vfin[used], remap[Fout if sign > 0 else Fout[:, ::-1]]
            # outward orientation of the whole set is kept from the input; patch faces were oriented against their rim
            mesh = trimesh.Trimesh(Vw, Fw, process=False)
            mesh.export(out_dir / 'filled.stl')
            files['filled'] = {'file': 'filled.stl', 'faces': int(len(Fw))}
            lf = write_labels(out_dir, kind, lout, names)
        else:
            (out_dir / 'filled.stl').write_bytes(Path(req['input_path']).read_bytes())
            files['filled'] = {'file': 'filled.stl', 'faces': int(nF)}
            lf = None
            if lab_path is not None:
                lf = 'labels' + lab_path.suffix.lower()
                (out_dir / lf).write_bytes(lab_path.read_bytes())
        if lf:
            files['labels'] = {'file': lf}
    return {**base, 'ready': not blocking, 'blocking': sorted(set(blocking)), 'pockets': pockets, 'applied': bool(applied),
            'candidates': {'recess_components': int(nc), 'below_min_area': int(nc - len(pockets_idx))},
            'mesh': {'faces_in': int(nF), 'faces_out': int(len(Fout))}, 'files': files, 'warnings': warnings, 'seconds': round(time.time() - t0, 2)}


def patch_labels(loop, Fk, kept_idx, fl, pc2, L2):
    """Region of each patch face. Every loop edge takes the region of its kept face; the region with most loop edges is the patch region;
    each contiguous run (>= 3 edges) of another region (e.g. the plate below the parting seam) owns the part of the patch cut off by the
    straight chord between its end points, so a seam crossing the pocket continues as a straight line instead of following nearest faces."""
    from shapely import contains_xy
    from shapely.geometry import Polygon
    e2f = {}
    for i, f in zip(kept_idx, Fk):
        for k in range(3):
            e2f[(int(f[k]), int(f[(k + 1) % 3]))] = i
            e2f[(int(f[(k + 1) % 3]), int(f[k]))] = i
    n = len(loop)
    el = np.array([fl[e2f[(int(loop[i]), int(loop[(i + 1) % n]))]] if (int(loop[i]), int(loop[(i + 1) % n])) in e2f else -10**9 for i in range(n)])
    valid = el > -10**9
    if not valid.any():
        return np.full(len(pc2), fl[kept_idx[0]])
    vals, cnt = np.unique(el[valid], return_counts=True)
    major = vals[np.argmax(cnt)]
    el[~valid] = major
    lab = np.full(len(pc2), major, dtype=fl.dtype)
    if (el == major).all():
        return lab
    s0 = int(np.flatnonzero(el == major)[0])           # rotate so that a major edge comes first: runs do not wrap
    order = (np.arange(n) + s0) % n
    e = el[order]
    runs, i = [], 0
    while i < n:
        j = i
        while j + 1 < n and e[j + 1] == e[i]:
            j += 1
        if e[i] != major and j - i + 1 >= 3:
            runs.append((i, j, e[i]))
        i = j + 1
    for i, j, code in sorted(runs, key=lambda r: -(r[1] - r[0])):
        idx = order[i:j + 2] if j + 1 < n else np.r_[order[i:], order[0]]
        poly = Polygon(L2[idx])
        if not poly.is_valid or poly.area <= 0:
            poly = poly.buffer(0)
        if poly.area > 0:
            lab[contains_xy(poly, pc2[:, 0], pc2[:, 1])] = code
    return lab


def fill_pocket(Vp, F, fl, fsrc, P, pk, ys, zs, g, p, excluded_codes, maxdepth):
    from scipy import ndimage as ndi
    from scipy.spatial import cKDTree
    import scipy.sparse as sp
    import scipy.sparse.csgraph as cg
    fn, fa, cen = face_geometry(Vp, F)
    nF = len(F)
    ny, nz = len(ys), len(zs)
    iy = np.clip(np.round((cen[:, 1] - ys[0]) / g).astype(int), 0, ny - 1)
    iz = np.clip(np.round((cen[:, 2] - zs[0]) / g).astype(int), 0, nz - 1)
    inside = (cen[:, 1] >= ys[0]) & (cen[:, 1] <= ys[-1]) & (cen[:, 2] >= zs[0]) & (cen[:, 2] <= zs[-1])
    foot = ndi.binary_dilation(pk, structure=disk(p['margin_mm'] / g))
    near = ndi.binary_dilation(pk, structure=disk((p['margin_mm'] + 1.0) / g))
    far = ndi.binary_dilation(pk, structure=disk((p['margin_mm'] + 3.0) / g))
    Pc = P(cen[:, 1], cen[:, 2])
    band = inside & (cen[:, 0] >= Pc - (maxdepth + 1.0)) & (cen[:, 0] <= Pc + 1.5) & ~np.isin(fl, excluded_codes)
    E = edges_of(F)
    fid = np.tile(np.arange(nF), 3)
    Es = np.sort(E, 1)
    o = np.lexsort((Es[:, 1], Es[:, 0]))
    Es, fo = Es[o], fid[o]
    same = (Es[1:] == Es[:-1]).all(1)
    fa_, fb_ = fo[:-1][same], fo[1:][same]

    def components(mask):
        m = mask[fa_] & mask[fb_]
        A = sp.coo_matrix((np.ones(m.sum()), (fa_[m], fb_[m])), shape=(nF, nF))
        return cg.connected_components(A + A.T, directed=False)
    dele = band & foot[iy, iz]
    # the pocket walls just outside the footprint: below the wall and connected to the footprint faces through such faces
    ext = band & near[iy, iz] & (cen[:, 0] < Pc - 0.15)
    _, comp = components(dele | ext)
    dele = dele | (ext & np.isin(comp, np.unique(comp[dele])))
    def near_wall(lp):
        q = Vp[lp]
        return float(np.median(np.abs(q[:, 0] - P(q[:, 1], q[:, 2]))))
    grown_for_crossings = 0
    for attempt in range(16):
        for _ in range(8):
            keepf = ~dele
            nco, comp = components(keepf)
            sizes = np.bincount(comp[keepf], minlength=nco)
            inner = (far[iy, iz] & inside)
            cm = np.bincount(comp[keepf], weights=inner[keepf].astype(float), minlength=nco)
            island_comp = np.flatnonzero((cm == sizes) & (sizes > 0) & (np.arange(nco) != np.argmax(sizes)))
            isl = keepf & np.isin(comp, island_comp)      # kept pieces enclosed by the removed area
            dele = dele | isl
            kept = F[~dele]
            touched = set(np.unique(F[dele]).tolist())
            Ek = np.sort(edges_of(kept), 1)
            u, c = np.unique(Ek, axis=0, return_counts=True)
            deg = np.bincount(u[c == 1].ravel(), minlength=len(Vp))
            badv = np.array([v for v in np.flatnonzero(deg > 2) if v in touched], np.int64)
            if not isl.any() and not len(badv):
                break
            if len(badv):                                  # non-simple boundary vertex: remove the kept faces around it
                dele = dele | (np.isin(F, badv).any(1) & far[iy, iz] & inside)
        kept_idx = np.flatnonzero(~dele)
        Fk = F[kept_idx]
        touched = set(np.unique(F[dele]).tolist())
        loops, bad = boundary_loops(Fk, touched)
        if bad or not loops:
            raise CableError('CABLE_LOOP_NOT_SIMPLE', 'Removing the pocket faces did not leave one simple boundary loop.', {'non_simple_vertices': int(bad), 'loops': len(loops)})
        loops.sort(key=lambda lp: (-len(lp)))
        main = loops[0]
        if near_wall(main) > 1.5:
            raise CableError('CABLE_LOOP_NOT_SIMPLE', 'The largest boundary loop is not on the inferred wall.', {'median_offset_mm': near_wall(main)})
        loop = np.array(main, np.int64)
        L2 = Vp[loop][:, 1:3]
        badl = crossing_vertices(L2)
        onloop = np.isin(F, loop).any(1) & ~dele
        folded = onloop & (fn[:, 0] < RIM_MIN_NX) & far[iy, iz] & inside   # rim faces turned away from the front (scan folds)
        if not len(badl) and not folded.any():
            break
        # the rim folds over in the front view (overhang, parting slit): remove the kept faces at the crossing / fold and retry
        grown_for_crossings += 1
        dele = dele | folded | (np.isin(F, loop[badl]).any(1) & far[iy, iz] & inside)
    else:
        raise CableError('CABLE_LOOP_NOT_SIMPLE', 'The boundary loop still crosses itself in the front view after removing the folded rim faces.', {'crossing_vertices': int(len(badl))})
    warns = []
    caps = []
    for lp in loops[1:]:
        if len(lp) <= CAP_MAX_EDGES:
            caps.append(lp)
        else:
            warns.append('CABLE_EXTRA_LOOP_LEFT_OPEN')
    P2, T = triangulate_loop(L2, p['patch_edge_mm'])
    nb = len(loop)
    res = Vp[loop, 0] - P(L2[:, 0], L2[:, 1])
    inner2 = P2[nb:]
    if len(inner2):
        dd, ii = cKDTree(L2).query(inner2, k=min(12, nb))
        w = 1.0 / np.maximum(dd, 1e-6) ** 3
        corr = (w * res[ii]).sum(1) / w.sum(1) * np.exp(-(dd[:, 0] / p['blend_mm']) ** 2)
        Xi = P(inner2[:, 0], inner2[:, 1]) + corr
        newV = np.c_[Xi, inner2]
    else:
        newV = np.zeros((0, 3))
    Vall = np.vstack([Vp, newV])
    idmap = np.r_[loop, np.arange(len(Vp), len(Vp) + len(newV))]
    Fp = idmap[T]
    # orient against the rim: a shared loop edge must run opposite in the patch and in the kept face
    dk = set(map(tuple, edges_of(Fk).tolist()))
    same = sum(1 for e in edges_of(Fp).tolist() if tuple(e) in dk)
    if same > nb / 2:
        Fp = Fp[:, ::-1]
    same = sum(1 for e in edges_of(Fp).tolist() if tuple(e) in dk)
    Fc = []
    for lp in caps:
        c = Vall[lp].mean(0)
        Vall = np.vstack([Vall, c])
        ci = len(Vall) - 1
        f = np.array([[lp[i], lp[(i + 1) % len(lp)], ci] for i in range(len(lp))])
        if sum(1 for e in edges_of(f).tolist() if tuple(e) in dk) > len(lp) / 2:
            f = f[:, ::-1]
        Fc.append(f)
    Fc = np.vstack(Fc) if Fc else np.zeros((0, 3), np.int64)
    loopset = np.zeros(len(Vall), bool)
    loopset[loop] = True
    rim = kept_idx[loopset[Fk].any(1)]
    newF = np.vstack([Fp, Fc])
    pc = Vall[newF].mean(1)
    lnew = patch_labels(loop, Fk, kept_idx, fl, pc[:, 1:3], L2)
    # seam smoothness: dihedral between patch and rim faces across loop edges
    nP = face_geometry(Vall, Fp)[0]
    nR = fn
    e2f = {}
    for i, f in zip(kept_idx, Fk):
        for k in range(3):
            e2f[tuple(sorted((int(f[k]), int(f[(k + 1) % 3]))))] = i
    ang = []
    for j, f in enumerate(Fp):
        for k in range(3):
            e = tuple(sorted((int(f[k]), int(f[(k + 1) % 3]))))
            if e in e2f:
                ang.append(np.degrees(np.arccos(np.clip(nP[j] @ nR[e2f[e]], -1, 1))))
    ang = np.array(ang) if ang else np.zeros(1)
    patch_area = float(face_geometry(Vall, newF)[1].sum())
    Fout = np.vstack([Fk, newF])
    lout = np.r_[fl[kept_idx], lnew]
    fs = np.r_[fsrc[kept_idx], np.full(len(newF), -1)]
    nPx = nP[:, 0]
    rep = {'faces_removed': int(dele.sum()), 'removed_area_mm2': round(float(fa[dele].sum()), 2), 'patch_faces': int(len(newF)),
           'patch_area_mm2': round(patch_area, 2), 'loop_vertices': int(nb), 'extra_loops_capped': len(caps), 'rim_regrow_rounds': grown_for_crossings,
           'loop_residual_mm': {'mean_abs': round(float(np.abs(res).mean()), 4), 'max_abs': round(float(np.abs(res).max()), 4)},
           'seam_dihedral_deg': {'p95': round(float(np.percentile(ang, 95)), 2), 'max': round(float(ang.max()), 2), 'mean': round(float(ang.mean()), 2)},
           'orientation_conflicts': int(same), 'patch_facing_front_fraction': round(float((nPx > 0).mean()), 3), 'warnings': warns}
    return Vall, Fout, lout, fs, rep


def main(argv: list[str]) -> int:
    try:
        req = json.loads(Path(argv[1]).read_text(encoding='utf-8'))
        res = run(req)
    except CableError as exc:
        res = {'status': 'FAILED', 'error': {'code': exc.code, 'message': exc.message, 'details': exc.details}}
    except Exception as exc:
        res = {'status': 'FAILED', 'error': {'code': 'CABLE_WORKER', 'message': f'{type(exc).__name__}: {exc}', 'trace': traceback.format_exc()[-1500:]}}
    sys.stdout.write('\n' + json.dumps(res, allow_nan=False, default=_json_default) + '\n')
    return 0 if res.get('status') == 'OK' else 2


def _json_default(o):
    if isinstance(o, np.floating):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.bool_):
        return bool(o)
    raise TypeError(type(o).__name__)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
