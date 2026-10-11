"""Bottom plate with ONE straight ruled side under a given shell (brain_mouse_plate_side). SUBPROCESS WORKER (server python with OCP).

Run as:  <server python> -I scan_plate_side_worker.py request.json
Needs OCP, numpy, scipy, shapely. Request and result are JSON; the result is the last stdout line.

Method (the whole_v5 plate method made generic for any mouse):
1. Shell: the parting face = the largest down-facing face (n_z < -0.5 at an inner point); the outer parting edge = its outer wire (ccw in plan).
2. Base outline (z = 0): mesh section / lowest plate face of a STEP / polyline. In a polar frame about the outline centroid projected onto the mirror
   line, the loop is split into angular sectors that come in mirror pairs. Coarse symmetry test per pair = p80 of the distance from the mirrored
   points to the outline, threshold max(abs_thr_mm, rel_thr * bbox diagonal). Passing pairs are replaced by the better side mirrored (lower
   curvature roughness) or by the average when both are similar; failing pairs (real asymmetry) stay as given; transitions are blended. Then a
   polar LP fairing on u = 1/r (minimise the total variation of u + u'' with |delta r| <= max_change_mm), a periodic cubic spline, and a clip to
   the shell parting outline (inset >= min_inset_mm).
3. Plate = floor (z = 0) + the shell parting surface (exact copy, extended) + ONE ruled side (degree 3 x 1, periodic, n_stations rulings from the
   edge along the inward plan normal to the base outline). General fuse, keep floor + side below the parting surface + parting face inside.
4. Checks on the re-imported STEP files. The shell STEP is only read (hashed before / after).
"""
from __future__ import annotations
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
from cadmcp_brain.studio.scan_cad_common import WorkerError, worker_main  # noqa: E402
from cadmcp_brain.studio import cad_brep_lib as L  # noqa: E402

WORKER_VERSION = 'plate_side/5'
EXT = 0.35                 # side surface extended above the edge by this fraction of each ruling (cut away by the parting surface)
GRID = 1440                # polar grid nodes (0.25 deg)
ROUGH_SIGMA_DEG = 1.5      # curvature smoothing for the roughness statistic
ROUGH_EPS = 1e-3           # 1/mm floor of the roughness ratio (clean outlines count as similar)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


# ------------------------------------------------------------------ polyline helpers
def ccw(P) -> bool:
    x, y = P[:, 0], P[:, 1]
    return 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y) > 0


def loop_length(P) -> float:
    return float(np.linalg.norm(np.diff(np.vstack([P, P[:1]]), axis=0), axis=1).sum())


def resample(P, n):
    """Closed polyline (first point not repeated) -> n points equally spaced in arc length."""
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(np.vstack([P, P[:1]]), axis=0), axis=1))]
    t = np.linspace(0, s[-1], int(n), endpoint=False)
    return np.c_[[np.interp(t, s, np.r_[P[:, k], P[0, k]]) for k in range(P.shape[1])]].T


def plan_normal(P):
    t = np.roll(P, -1, 0) - np.roll(P, 1, 0)
    t /= np.linalg.norm(t, axis=1)[:, None]
    return np.c_[t[:, 1], -t[:, 0]]            # ccw loop -> right normal = outward


def curvature(P):
    d1 = (np.roll(P, -1, 0) - np.roll(P, 1, 0)) / 2
    d2 = np.roll(P, -1, 0) - 2 * P + np.roll(P, 1, 0)
    return (d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / np.linalg.norm(d1, axis=1) ** 3


def ray_hits(P0, Dv, Q, tmin=-1e-6, chunk=256):
    """First hit (t >= tmin) of rays P0 + t Dv with the closed polyline Q -> t, arc-length position on Q, total length."""
    A = Q
    E = np.roll(Q, -1, 0) - A
    seg = np.linalg.norm(E, axis=1)
    s0 = np.r_[0, np.cumsum(seg)][:-1]
    T = np.full(len(P0), np.nan)
    POS = np.full(len(P0), np.nan)
    for i in range(0, len(P0), chunk):
        p, w = P0[i:i + chunk, None, :], Dv[i:i + chunk, None, :]
        den = w[..., 0] * E[None, :, 1] - w[..., 1] * E[None, :, 0]
        ap = A[None] - p
        with np.errstate(divide='ignore', invalid='ignore'):
            t = (ap[..., 0] * E[None, :, 1] - ap[..., 1] * E[None, :, 0]) / den
            s = (ap[..., 0] * w[..., 1] - ap[..., 1] * w[..., 0]) / den
        ok = (np.abs(den) > 1e-15) & (s >= 0) & (s <= 1) & (t >= tmin)
        t = np.where(ok, t, np.inf)
        j = np.argmin(t, axis=1)
        r = np.arange(len(j))
        tt = t[r, j]
        good = np.isfinite(tt)
        T[i:i + chunk] = np.where(good, tt, np.nan)
        POS[i:i + chunk] = np.where(good, s0[j] + s[r, j] * seg[j], np.nan)
    return T, POS, float(seg.sum())


def poly_dist(P, Q, k=3):
    """Distance from points P to the closed polyline Q (any dimension): exact on the segments next to the k nearest vertices."""
    from scipy.spatial import cKDTree
    P, Q = np.asarray(P, float), np.asarray(Q, float)
    _, J = cKDTree(Q).query(P, k=k)
    best = np.full(len(P), np.inf)
    n = len(Q)
    for j in np.atleast_2d(J.T):
        for a, b in ((j - 1) % n, j), (j, (j + 1) % n):
            A, E = Q[a], Q[b] - Q[a]
            t = np.clip(np.einsum('ij,ij->i', P - A, E) / np.maximum(np.einsum('ij,ij->i', E, E), 1e-300), 0, 1)
            best = np.minimum(best, np.linalg.norm(P - A - t[:, None] * E, axis=1))
    return best


def hausdorff(A, B) -> float:
    """Hausdorff distance between two closed polylines (vertices of each against the segments of the other)."""
    return float(max(poly_dist(A, B).max(), poly_dist(B, A).max()))


# ------------------------------------------------------------------ shell parting face and edge
def shell_parting(shell, step=0.05):
    from OCP.TopExp import TopExp
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
    from OCP.TopoDS import TopoDS
    from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    fs = L.faces(shell)
    cand = []
    for k, f in enumerate(fs):
        p, n = L.inner_point(f)
        if p is not None and np.isfinite(n).all() and n[2] < -0.5:
            cand.append((L.area(f), k, p))
    if not cand:
        raise WorkerError('PLATE_SIDE_NO_PARTING_FACE', 'The shell has no down-facing face (n_z < -0.5 at an inner point): no parting face.')
    cand.sort(key=lambda c: -c[0])
    fpart = fs[cand[0][1]]
    mp = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shell, TopAbs_EDGE, TopAbs_FACE, mp)
    we = BRepTools_WireExplorer(BRepTools.OuterWire_s(fpart))
    P, TN = [], []
    while we.More():
        e = we.Current()
        c = BRepAdaptor_Curve(e)
        g = GProp_GProps()
        BRepGProp.LinearProperties_s(e, g)
        ts = np.linspace(c.FirstParameter(), c.LastParameter(), max(8, int(g.Mass() / step)))
        if e.Orientation() == TopAbs_REVERSED:
            ts = ts[::-1]
        pts = np.array([c.Value(t).Coord() for t in ts[:-1]])
        nb = [TopoDS.Face_s(x) for x in mp.FindFromKey(e) if not TopoDS.Face_s(x).IsSame(fpart)]
        nn = np.full_like(pts, np.nan)
        if nb:                                         # wall normal every ~0.5 mm (edge-angle statistics only)
            for i in range(0, len(pts), 10):
                nn[i] = L.face_normal_at(nb[0], pts[i])
        P.append(pts)
        TN.append(nn)
        we.Next()
    TOP, TN = np.vstack(P), np.vstack(TN)
    if not ccw(TOP):
        TOP, TN = TOP[::-1], TN[::-1]
    info = {'face_index': cand[0][1], 'area_mm2': cand[0][0], 'down_faces': [{'index': k, 'area_mm2': a} for a, k, _ in cand],
            'edge_points': len(TOP), 'edge_length_mm': loop_length(TOP), 'edge_z_mm': [float(TOP[:, 2].min()), float(TOP[:, 2].max())]}
    if len(cand) > 1:
        info['note'] = 'Several down-facing faces; the largest is the parting face, its outer wire the outer parting edge.'
    if TOP[:, 2].min() <= 0.05:
        raise WorkerError('PLATE_SIDE_PARTING_TOO_LOW', 'The shell parting edge reaches z <= 0.05 mm; the plate floor is z = 0.', {'edge_z_min': float(TOP[:, 2].min())})
    return fpart, TOP, TN, info


# ------------------------------------------------------------------ base outline sources
def mesh_section(path: Path, z: float):
    V, F = L.read_stl(path)
    above = V[:, 2] > z
    fa = above[F]
    cnt = fa.sum(1)
    sel = (cnt == 1) | (cnt == 2)
    if not sel.any():
        raise WorkerError('PLATE_SIDE_OUTLINE', 'The mesh has no section at section_z_mm.', {'z': z, 'mesh_z': [float(V[:, 2].min()), float(V[:, 2].max())]})
    Fs, fs = F[sel], fa[sel]
    nV = len(V)
    keys = []
    for a, b in ((0, 1), (1, 2), (2, 0)):
        diff = fs[:, a] != fs[:, b]
        lo, hi = np.minimum(Fs[:, a], Fs[:, b]), np.maximum(Fs[:, a], Fs[:, b])
        keys.append(np.where(diff, lo * nV + hi, -1))
    K = np.stack(keys, 1)
    pairs = np.sort(K, 1)[:, 1:]                       # the two crossing edges of every triangle
    adj: dict[int, list[int]] = {}
    for a, b in pairs.tolist():
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    seen: set[int] = set()
    loops = []
    for start in adj:
        if start in seen:
            continue
        loop, prev, cur = [start], None, start
        seen.add(start)
        while True:
            nxt = [x for x in adj[cur] if x != prev]
            if not nxt or nxt[0] == start or nxt[0] in seen:
                break
            prev, cur = cur, nxt[0]
            seen.add(cur)
            loop.append(cur)
        if len(loop) >= 8:
            loops.append(np.array(loop, np.int64))
    out = []
    for lp in loops:
        a, b = lp // nV, lp % nV
        za, zb = V[a, 2], V[b, 2]
        t = (z - za) / (zb - za)
        P = V[a, :2] + t[:, None] * (V[b, :2] - V[a, :2])
        x, y = P[:, 0], P[:, 1]
        out.append((abs(0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)), P))
    if not out:
        raise WorkerError('PLATE_SIDE_OUTLINE', 'No closed section loop at section_z_mm.', {'z': z})
    out.sort(key=lambda c: -c[0])
    return out[0][1], {'source': 'mesh_section', 'z_mm': z, 'loops': len(out), 'loop_area_mm2': float(out[0][0]), 'points': len(out[0][1])}


def step_floor(path: Path):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    best = None
    for f in L.faces(L.read_step(path)):
        a = BRepAdaptor_Surface(f)
        if a.GetType() != GeomAbs_Plane:
            continue
        n = np.array(a.Plane().Axis().Direction().Coord())
        if abs(n[2]) < 0.999:
            continue
        p, _ = L.inner_point(f)
        if p is not None and (best is None or p[2] < best[0]):
            best = (p[2], f)
    if best is None:
        raise WorkerError('PLATE_SIDE_OUTLINE', 'The plate STEP has no planar z = const face.')
    P = L.wire_points(best[1], 0.05)[:, :2]
    return P, {'source': 'step_lowest_planar_face', 'z_mm': float(best[0]), 'points': len(P)}


def polyline(path: Path):
    try:
        d = json.loads(Path(path).read_text(encoding='utf-8'))
        P = np.array(d['points'], float)
    except (ValueError, KeyError, TypeError) as exc:
        raise WorkerError('PLATE_SIDE_OUTLINE', 'The polyline JSON must be {"points": [[x, y], ...]}.') from exc
    if P.ndim != 2 or P.shape[1] < 2 or len(P) < 8 or not np.isfinite(P).all():
        raise WorkerError('PLATE_SIDE_OUTLINE', 'The polyline needs at least 8 finite [x, y] points.')
    P = P[:, :2]
    if np.linalg.norm(P[0] - P[-1]) < 1e-9:
        P = P[:-1]
    return P, {'source': 'polyline', 'points': len(P)}


def read_outline(mode: str, path: Path, z: float):
    from shapely.geometry import Polygon
    Q, info = {'mesh': lambda: mesh_section(path, z), 'step': lambda: step_floor(path), 'polyline': lambda: polyline(path)}[mode]()
    keep = np.r_[True, np.linalg.norm(np.diff(Q, axis=0), axis=1) > 1e-9]
    Q = Q[keep]
    if not Polygon(Q).is_valid:
        raise WorkerError('PLATE_SIDE_OUTLINE', 'The base outline self-intersects.', {'source': info['source']})
    if not ccw(Q):
        Q = Q[::-1]
    return Q, info


SECTION_Z_CANDIDATES = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.2, 1.5, 2.0)


def auto_section(path: Path, mirror, p):
    """section_z_mm auto: the lowest candidate z whose largest section loop is a valid, star-shaped outline (polar method) and whose area is
    within 2 % of the next star-shaped candidate (not in a chamfer / foot transition). Every candidate is reported."""
    from shapely.geometry import Polygon
    rows, ok = [], []
    for z in SECTION_Z_CANDIDATES:
        row = {'z_mm': z}
        try:
            Q, info = read_outline('mesh', path, z)
            radial_grid(Q, make_frame(Q, mirror), M=720)
            row.update(star_shaped=True, area_mm2=float(Polygon(Q).area))
            ok.append((z, Q, info, row['area_mm2']))
        except WorkerError as exc:
            row.update(star_shaped=False, error=exc.code)
        rows.append(row)
        if len(ok) >= 2 and abs(ok[-1][3] - ok[-2][3]) <= 0.02 * ok[-2][3]:
            break
    if not ok:
        raise WorkerError('PLATE_SIDE_OUTLINE_NOT_STAR_SHAPED', 'No mesh section between 0.3 and 2.0 mm is a star-shaped outline; give section_z_mm '
                          'or another outline_mode.', {'candidates': rows})
    pick = ok[0]
    for a, b in zip(ok, ok[1:]):
        if abs(b[3] - a[3]) <= 0.02 * a[3]:
            pick = a
            break
    z, Q, info, _ = pick
    info = {**info, 'section_z_mode': 'auto', 'section_z_candidates': rows,
            'rule': 'lowest star-shaped section whose area is within 2 % of the next star-shaped candidate'}
    if p.get('extrapolate_to_floor', True) and z > 1e-6:
        Q, ext = extrapolate_floor(path, mirror, Q, z, p)
        info['floor_extrapolation'] = ext
    return Q, info


def ray_far(c, D, Q, chunk=256):
    """Farthest hit (t >= 0) of rays c + t D with the closed polyline Q (NaN without a hit): the outer wall also for non-star loops."""
    A = np.asarray(Q, float)
    Ed = np.roll(A, -1, 0) - A
    out = np.full(len(D), np.nan)
    ap = A[None] - np.asarray(c, float)
    for i in range(0, len(D), chunk):
        w = D[i:i + chunk, None, :]
        den = w[..., 0] * Ed[None, :, 1] - w[..., 1] * Ed[None, :, 0]
        with np.errstate(divide='ignore', invalid='ignore'):
            t = (ap[..., 0] * Ed[None, :, 1] - ap[..., 1] * Ed[None, :, 0]) / den
            s = (ap[..., 0] * w[..., 1] - ap[..., 1] * w[..., 0]) / den
        ok = (np.abs(den) > 1e-15) & (s >= 0) & (s <= 1) & (t >= 0)
        m = np.where(ok, t, -np.inf).max(1)
        out[i:i + chunk] = np.where(np.isfinite(m), m, np.nan)
    return out


def extrapolate_floor(path: Path, mirror, Q, z0, p):
    """whole_v1 rule: the plate base outline is the outline AT the floor (z = 0), not a section above a rounded / chamfered foot.
    Per polar angle r(z) = farthest ray hit of the largest mesh section loop, sections every 0.1 mm from floor_min_z_mm (0.1) to
    z0 + floor_fit_span_mm. PS1.5: below the chosen (whole-loop star-shaped) section z0 a lower section counts per angle only while the
    wall stays continuous going down (r drops by <= floor_max_slope * 0.1 mm per step and never grows by > 0.05 mm; a section that
    jumps into the underside / a raised floor area ends the run), so the rounded foot is measured down to the floor where it exists.
    r(z) is fitted (quadratic with >= 4 sections, else linear) over the valid sections of that angle and evaluated at z = 0. Only inward
    corrections (the wall tucks in going down) are applied, capped at floor_max_change_mm and smoothed over 3 deg."""
    fr = make_frame(Q, mirror)
    g, r0, _ = radial_grid(Q, fr, M=GRID)
    D = fr.cart(g, np.ones(len(g))) - fr.c
    zmin = float(p.get('floor_min_z_mm', 0.1))
    span = float(p.get('floor_fit_span_mm', 0.8))
    lows = [round(z, 3) for z in np.arange(zmin, z0 - 1e-6, 0.1)]
    highs = [round(z0 + k * 0.1, 3) for k in range(int(round(span / 0.1)) + 1)]
    R, used = [], []
    for z in lows + highs:
        try:
            if z >= z0 - 1e-9 and z != z0:
                Qz = read_outline('mesh', path, z)[0]
                radial_grid(Qz, fr, M=720)                                  # above z0 the sections must be star-shaped (as before)
            else:
                Qz = Q if abs(z - z0) < 1e-9 else mesh_section(path, z)[0]
            R.append(ray_far(fr.c, D, Qz))
            used.append(z)
        except WorkerError:
            if z >= z0:
                continue
            R.append(np.full(len(g), np.nan))
            used.append(z)
    zz = np.asarray(used)
    R = np.asarray(R)
    k0 = int(np.argmin(np.abs(zz - z0)))
    if len(used) < 2:
        return Q, {'applied': False, 'reason': 'fewer than two star-shaped sections above the chosen z', 'sections_z_mm': used}
    slope = float(p.get('floor_max_slope', 4.0))
    deg_max = int(p.get('floor_fit_degree', 2))
    r_at0 = np.full(len(g), np.nan)
    zlo = np.full(len(g), zz[k0])
    for j in range(len(g)):
        k = k0
        while k > 0 and np.isfinite(R[k - 1, j]) and R[k, j] - R[k - 1, j] <= slope * (zz[k] - zz[k - 1]) and R[k - 1, j] <= R[k, j] + 0.05:
            k -= 1
        zlo[j] = zz[k]
        zs, rs = zz[k:], R[k:, j]
        ok = np.isfinite(rs)
        if ok.sum() < 2:
            continue
        deg = deg_max if ok.sum() >= 4 else 1
        r_at0[j] = np.polyval(np.polyfit(zs[ok], rs[ok], deg), 0.0)
    r_at0 = np.where(np.isfinite(r_at0), r_at0, r0)
    dr = np.clip(r_at0 - r0, -float(p.get('floor_max_change_mm', 1.0)), 0.0)
    dr = circ_smooth(dr, GRID * 3 / 360)
    Qn = fr.cart(g, r0 + dr)
    below = zlo < z0 - 1e-6
    return Qn, {'applied': True, 'sections_z_mm': used, 'inward_shift_mm': {'median': float(np.median(-dr)), 'max': float((-dr).max())},
                'degree': deg_max, 'lowest_section_z_mm': {'median': float(np.median(zlo)), 'min': float(zlo.min()), 'max': float(zlo.max())},
                'angles_using_sections_below_z0_fraction': float(below.mean()),
                'rule': 'per angle r(z) over the continuous sections from the floor_min_z_mm run up to z0 + floor_fit_span_mm (quadratic with >= 4), '
                        'evaluated at z = 0; inward only, capped'}


# ------------------------------------------------------------------ base outline processing
class Frame:
    """Polar frame: centre on the mirror line, axis a along it (right-handed with the mirror normal n). Mirror = phi -> -phi."""

    def __init__(self, cen, a, n):
        self.c, self.a, self.n = np.asarray(cen, float), np.asarray(a, float), np.asarray(n, float)

    def polar(self, P):
        d = np.asarray(P, float)[:, :2] - self.c
        return np.arctan2(d @ self.n, d @ self.a), np.hypot(d @ self.a, d @ self.n)

    def cart(self, phi, r):
        return self.c + (r * np.cos(phi))[:, None] * self.a + (r * np.sin(phi))[:, None] * self.n


def make_frame(Q, mirror):
    from shapely.geometry import Polygon
    cen = np.array(Polygon(Q).centroid.coords[0])
    if mirror is None:
        return Frame(cen, (1.0, 0.0), (0.0, 1.0))
    n2, d2 = np.asarray(mirror[0], float), float(mirror[1])
    cen = cen - (cen @ n2 - d2) * n2
    return Frame(cen, (n2[1], -n2[0]), n2)


def radial_grid(P, fr: Frame, M=GRID, what='outline'):
    Pd = resample(P, max(4000, int(loop_length(P) / 0.05)))
    phi, r = fr.polar(Pd)
    dphi = np.angle(np.exp(1j * (np.roll(phi, -1) - phi)))
    if (dphi <= 0).any() or abs(dphi.sum() - 2 * np.pi) > 1e-6:
        raise WorkerError('PLATE_SIDE_OUTLINE_NOT_STAR_SHAPED', f'The {what} is not star-shaped about its centre (polar method needs it).',
                          {'centre': fr.c.tolist(), 'backward_steps': int((dphi <= 0).sum())})
    o = np.argsort(phi)
    grid = -np.pi + (np.arange(M) + 0.5) * 2 * np.pi / M
    return grid, np.interp(grid, phi[o], r[o], period=2 * np.pi), Pd


def circ_smooth(x, width):
    """Circular convolution with a symmetric Hann kernel of odd length ~width samples (keeps mirror relations)."""
    w = max(3, int(width) | 1)
    k = np.hanning(w + 2)[1:-1]
    k /= k.sum()
    h = w // 2
    xp = np.r_[x[-h:], x, x[:h]]
    return np.convolve(xp, k, mode='valid')


def fair_lp(r, h, max_change):
    """min sum |D(u + u'')| s.t. |1/(u0+du) - r| <= max_change, periodic. Returns new r."""
    import scipy.sparse as sp
    from scipy.optimize import linprog
    M = len(r)
    if max_change <= 0:
        return 1 / r, {'solved': False, 'reason': 'max_change_mm = 0'}
    u0 = 1 / r
    R2 = float(np.mean(r)) ** 2                                   # variable scaling: x = du * R2 (mm-like)
    I = sp.identity(M, format='csr')
    Sp, Sm = sp.eye(M, k=1, format='csr') + sp.eye(M, k=-(M - 1), format='csr'), sp.eye(M, k=-1, format='csr') + sp.eye(M, k=M - 1, format='csr')
    K = (I + (Sp - 2 * I + Sm) / h ** 2).tocsr()
    DK = ((Sp - I) @ K).tocsr() / R2
    Kc = (Sp - I) @ K @ u0
    lo = (1 / (r + max_change) - u0) * R2
    hi = (1 / np.maximum(r - max_change, 1e-6) - u0) * R2
    c = np.r_[np.zeros(M), np.ones(M)]
    A = sp.vstack([sp.hstack([DK, -I]), sp.hstack([-DK, -I])]).tocsr()
    b = np.r_[-Kc, Kc]
    res = linprog(c, A_ub=A, b_ub=b, bounds=list(zip(lo, hi)) + [(0, None)] * M, method='highs')
    if res.status != 0:
        return u0, {'solved': False, 'reason': res.message}
    du = res.x[:M] / R2
    tv0 = float(np.abs(Kc).sum())
    return u0, {'solved': True, 'du': du, 'curvature_tv_before': tv0, 'curvature_tv_after': float(res.fun)}


def _sstep(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def front_rim(r1, phi, fr: Frame, edge_xy, mirror, p, thr):
    """Front zone = shell parting outline offset inward by a uniform rim (front_rim_mm), convex corners at least front_min_corner_radius_mm,
    symmetrised only when the offset passes the coarse test; blended into the outline between front_blend_deg[0] and [1] (whole_v6 method)."""
    from shapely.geometry import Polygon
    rim = float(p['front_rim_mm'])
    rad = float(p.get('front_min_corner_radius_mm') or 0.0)
    fb0, fb1 = [float(x) for x in (p.get('front_blend_deg') or (38.0, 58.0))]
    poly = Polygon(edge_xy).buffer(-(rim + rad), join_style='round', resolution=64)
    if rad > 0 and not poly.is_empty:
        poly = poly.buffer(rad, join_style='round', resolution=64)
    if poly.is_empty:
        raise WorkerError('PLATE_SIDE_FRONT_RIM', 'The shell parting outline vanishes when offset by front_rim_mm (+ corner radius).', {'rim_mm': rim, 'radius_mm': rad})
    if poly.geom_type != 'Polygon':
        poly = max(poly.geoms, key=lambda g: g.area)
    off = np.array(poly.exterior.coords)[:-1]
    if not ccw(off):
        off = off[::-1]
    _, roff, _ = radial_grid(off, fr, M=len(phi), what='front rim outline')
    fd = p.get('front_direction')
    fd = np.asarray(fd, float) if fd is not None else np.array([1.0, 0.0])
    alpha0 = 0.0 if fd @ fr.a >= 0 else np.pi
    dphi = np.degrees(np.abs(np.angle(np.exp(1j * (phi - alpha0)))))
    zone = dphi < fb1
    out = {'rim_mm': rim, 'blend_deg': [fb0, fb1], 'front_direction_2d': (fr.a if alpha0 == 0 else -fr.a).tolist(),
           'front_direction_source': 'argument' if p.get('front_direction') is not None else 'default +x of the frame (standard frame: x = front)',
           'min_corner_radius_requested_mm': rad or None}
    if mirror is not None:
        st = float(np.percentile(np.abs(roff - roff[::-1])[zone], 80))
        ok = st <= thr
        out['symmetry'] = {'p80_radial_lr_diff_mm': st, 'threshold_mm': thr, 'symmetric': bool(ok)}
        if ok:
            roff = 0.5 * (roff + roff[::-1])
            out['symmetry']['correction'] = 'averaged with its mirror image'
        else:
            out['symmetry']['correction'] = 'kept as offset (asymmetric shell edge, not forced)'
    tf = 1 - _sstep((dphi - fb0) / max(fb1 - fb0, 1e-9))
    return tf * roff + (1 - tf) * r1, out, zone, alpha0


def process_outline(Q, edge_xy, mirror, p) -> dict[str, Any]:
    """Q (ccw source outline), edge_xy (ccw shell parting outline in plan), mirror (n2, d2) or None, params -> final outline + report."""
    from scipy.interpolate import CubicSpline
    from scipy.ndimage import gaussian_filter1d
    from shapely.geometry import Point, Polygon
    fr = make_frame(Q, mirror)
    phi, r0, Qd = radial_grid(Q, fr)
    M = len(phi)
    h = 2 * np.pi / M
    diag = float(np.linalg.norm(Q.max(0) - Q.min(0)))
    thr = max(p['abs_thr_mm'], p['rel_thr'] * diag)
    rep: dict[str, Any] = {'centre': fr.c.tolist(), 'axis': fr.a.tolist(), 'mirror_normal_2d': fr.n.tolist(), 'bbox_diagonal_mm': diag, 'threshold_mm': thr,
                           'source_length_mm': loop_length(Q), 'source_points': len(Q)}
    w = np.zeros(M)
    alpha = np.full(M, 0.5)
    if mirror is not None:
        S = int(p['n_sectors'])
        sec = np.minimum(((phi + np.pi) / (2 * np.pi / S)).astype(int), S - 1)
        G = fr.cart(phi, r0)
        dist = poly_dist(fr.cart(-phi, r0), Q)
        k = curvature(G)
        dev = np.abs(k - gaussian_filter1d(k, ROUGH_SIGMA_DEG / 360 * M, mode='wrap'))
        stat = np.array([np.percentile(dist[sec == s], 80) for s in range(S)])
        rough = np.array([np.percentile(dev[sec == s], 95) for s in range(S)])
        sectors = []
        for s in range(S):
            m_ = S - 1 - s
            pair = max(stat[s], stat[m_])
            ok = bool(pair <= thr)
            ratio = (min(rough[s], rough[m_]) + ROUGH_EPS) / (max(rough[s], rough[m_]) + ROUGH_EPS)
            if not ok:
                dec, a_ = 'asymmetric_kept', 0.5
            elif ratio > p['similar_ratio']:
                dec, a_ = 'symmetrised_average', 0.5
            elif rough[s] < rough[m_]:
                dec, a_ = 'symmetrised_from_this_side', 1.0
            else:
                dec, a_ = 'symmetrised_from_mirror_side', 0.0
            w[sec == s] = 1.0 if ok else 0.0
            alpha[sec == s] = a_
            lo_deg = -180 + s * 360 / S
            sectors.append({'sector': s, 'mirror_sector': m_, 'phi_deg': [lo_deg, lo_deg + 360 / S], 'p80_mm': float(stat[s]), 'pair_p80_mm': float(pair),
                            'roughness': float(rough[s]), 'roughness_ratio': float(ratio), 'near_symmetric': ok, 'decision': dec})
        width = (2 * np.pi / S) / 2 / h                                      # blend over half a sector
        ws, al = np.clip(circ_smooth(w, width), 0, 1), circ_smooth(alpha, width)
        rsym = al * r0 + (1 - al) * r0[::-1]
        r1 = (1 - ws) * r0 + ws * rsym
        rep['symmetry'] = {'applied': True, 'whole_loop_p80_mm': float(np.percentile(dist, 80)), 'whole_loop_near_symmetric': bool(np.percentile(dist, 80) <= thr),
                           'sectors': sectors, 'near_symmetric_sectors': int(sum(x['near_symmetric'] for x in sectors)), 'asymmetric_sectors': [x['sector'] for x in sectors if not x['near_symmetric']],
                           'blend_deg': float(360 / S / 2), 'change_mm': L.stats(np.abs(r1 - r0))}
    else:
        ws = w
        r1 = r0.copy()
        rep['symmetry'] = {'applied': False, 'reason': 'No mirror plane (symmetry_report_path or mirror_normal + mirror_d) was given; the outline is not symmetrised.'}
    fzone = falpha = None
    if float(p.get('front_rim_mm') or 0.0) > 0:
        r1, rep['front'], fzone, falpha = front_rim(r1, phi, fr, edge_xy, mirror, p, thr)
    else:
        rep['front'] = {'rim_mm': 0.0, 'note': 'front_rim_mm = 0: the front follows the given outline.'}
    u0, lp = fair_lp(r1, h, p['max_change_mm'])
    if lp.get('solved'):
        du = lp.pop('du')
        du = (1 - ws) * du + ws * 0.5 * (du + du[::-1])                       # keep the symmetrised sectors exactly symmetric
        du = np.clip(du, 1 / (r1 + p['max_change_mm']) - u0, 1 / np.maximum(r1 - p['max_change_mm'], 1e-6) - u0)
        r2 = 1 / (u0 + du)
    else:
        r2 = r1.copy()
    rep['fairing'] = {**lp, 'max_change_mm': p['max_change_mm'], 'change_mm': L.stats(np.abs(r2 - r1))}
    cs = CubicSpline(np.r_[phi, phi[0] + 2 * np.pi], np.r_[r2, r2[0]], bc_type='periodic')
    Kd = max(3600, int(loop_length(Q) / 0.05))
    ph = -np.pi + (np.arange(Kd) + 0.5) * 2 * np.pi / Kd
    rs = cs(ph)
    lim_poly = Polygon(edge_xy)
    if p['min_inset_mm'] > 0:
        lim_poly = lim_poly.buffer(-p['min_inset_mm'], join_style='round')
        if lim_poly.geom_type != 'Polygon':
            lim_poly = max(lim_poly.geoms, key=lambda g: g.area)
    if not lim_poly.contains(Point(*fr.c)):
        raise WorkerError('PLATE_SIDE_OUTLINE_OUTSIDE_SHELL', 'The base outline centre is outside the shell parting outline.', {'centre': fr.c.tolist()})
    lim = np.array(lim_poly.exterior.coords)[:-1]
    dirs = fr.cart(ph, np.ones(Kd)) - fr.c
    rl, _, _ = ray_hits(np.tile(fr.c, (Kd, 1)), dirs, lim, tmin=0.0)
    rl = np.where(np.isnan(rl), np.inf, rl)
    r3 = np.minimum(rs, rl - 1e-6)
    clipped = rs - r3
    B = fr.cart(ph, r3)
    S1 = fr.cart(phi, r1)
    rep['clip'] = {'min_inset_mm': p['min_inset_mm'], 'points_clipped': int((clipped > 1e-9).sum()), 'max_clip_mm': float(clipped.max())}
    rad_src = r3 - np.interp(ph, phi, r0, period=2 * np.pi)
    rep['change_vs_source_mm'] = {'radial_max_abs': float(np.abs(rad_src).max()), 'radial_mean_abs': float(np.abs(rad_src).mean()), 'hausdorff': hausdorff(B, Q)}
    rep['change_vs_symmetrised_mm'] = {'radial_max_abs': float(np.abs(r3 - np.interp(ph, phi, r1, period=2 * np.pi)).max()),
                                       'hausdorff': hausdorff(B, S1)}
    kb = curvature(B)
    if fzone is not None:
        dB = np.degrees(np.abs(np.angle(np.exp(1j * (ph - falpha)))))
        fb0 = rep['front']['blend_deg'][0]
        from scipy.ndimage import gaussian_filter1d as _g1
        _sig = max(1.0, 1.0 / max(loop_length(B) / len(B), 1e-6))           # 1 mm curvature smoothing (finite-difference noise)
        kz = _g1(kb, _sig, mode='wrap')[dB < fb0]                                                  # pure rim zone (the blend mixes in the flank outline)
        Ez = np.asarray(edge_xy, float)
        pe, re_ = fr.polar(Ez)
        de = np.degrees(np.abs(np.angle(np.exp(1j * (pe - falpha)))))
        band = poly_dist(Ez[de < fb0], B) if (de < fb0).any() else np.array([np.nan])
        rep['front']['min_corner_radius_mm'] = float(1 / kz.max()) if kz.size and kz.max() > 0 else None
        rep['front']['rim_measured_mm'] = {'p50': float(np.nanmedian(band)), 'min': float(np.nanmin(band)), 'max': float(np.nanmax(band))}
    rep['final'] = {'points': len(B), 'length_mm': loop_length(B), 'curvature_sign_changes': int(np.sum(np.diff(np.sign(np.r_[kb, kb[:1]])) != 0)),
                    'curvature_range': [float(kb.min()), float(kb.max())]}
    return {'B': B, 'frame': fr, 'phi': ph, 'r': r3, 'r_source_grid': (phi, r0), 'r_sym_grid': (phi, r1), 'report': rep}


# ------------------------------------------------------------------ plate build
def rulings(TOP, B, N):
    from scipy.ndimage import gaussian_filter1d
    Ptop = resample(TOP, N)
    m = plan_normal(Ptop[:, :2])
    for sig in (2, 5, 10, 20, 40):
        mm = np.c_[gaussian_filter1d(m[:, 0], sig, mode='wrap'), gaussian_filter1d(m[:, 1], sig, mode='wrap')]
        mm /= np.linalg.norm(mm, axis=1)[:, None]
        hh, pos, Lb = ray_hits(Ptop[:, :2], -mm, B)
        if np.isnan(hh).any():
            continue
        dpos = (np.diff(np.r_[pos, pos[0]]) + Lb / 2) % Lb - Lb / 2
        if (dpos > 1e-9).all():
            Pb = np.c_[Ptop[:, :2] - hh[:, None] * mm, np.zeros(N)]
            return Ptop, Pb, hh, {'normal_smoothing_sigma_stations': sig, 'monotonic': True, 'min_base_step_mm': float(dpos.min()), 'max_base_step_mm': float(dpos.max()),
                                  'inset_mm': {'min': float(hh.min()), 'p50': float(np.median(hh)), 'max': float(hh.max())}}
    raise WorkerError('PLATE_SIDE_RULINGS_CROSS', 'No ruling set from the parting edge to the base outline keeps the station order (rulings would cross).',
                      {'stations': N})


def build_plate(fpart, TOP, B, N):
    from OCP.TColgp import TColgp_Array2OfPnt
    from OCP.TColStd import TColStd_Array1OfReal, TColStd_Array1OfInteger
    from OCP.Geom import Geom_BSplineSurface
    from OCP.gp import gp_Pnt, gp_Pln, gp_Dir
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid
    from OCP.BRepAlgoAPI import BRepAlgoAPI_BuilderAlgo
    from OCP.TopTools import TopTools_ListOfShape
    from OCP.BRep import BRep_Tool
    from OCP.BRepLib import BRepLib
    from OCP.TopoDS import TopoDS_Face, TopoDS
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from shapely import contains_xy
    from shapely.geometry import Polygon
    Ptop, Pb, hh, rinfo = rulings(TOP, B, N)
    prm = np.r_[0, np.cumsum(np.linalg.norm(np.diff(Ptop, axis=0), axis=1))]
    prm = prm / (prm[-1] + np.linalg.norm(Ptop[0] - Ptop[-1]))
    ct, cb = L.interp_closed(Ptop, prm), L.interp_closed(Pb, prm)
    nk, npo = ct.NbKnots(), ct.NbPoles()
    if cb.NbPoles() != npo or any(abs(ct.Knot(k) - cb.Knot(k)) > 1e-12 for k in range(1, nk + 1)):
        raise WorkerError('PLATE_SIDE_BUILD', 'Top and bottom rows are not compatible B-splines.')
    uu = np.linspace(0, 1, 20 * N, endpoint=False)
    Xt = np.array([ct.Value(u).Coord() for u in uu])
    Xb = np.array([cb.Value(u).Coord() for u in uu])
    rinfo['top_row_vs_edge_mm'] = float(poly_dist(Xt, TOP).max())
    rinfo['bottom_row_vs_outline_mm'] = float(poly_dist(Xb[:, :2], B).max())
    Pl = TColgp_Array2OfPnt(1, npo, 1, 2)
    for i in range(npo):
        a, b = np.array(ct.Pole(i + 1).Coord()), np.array(cb.Pole(i + 1).Coord())
        Pl.SetValue(i + 1, 1, gp_Pnt(*map(float, a + EXT * (a - b))))
        Pl.SetValue(i + 1, 2, gp_Pnt(*map(float, b)))
    uk, um = TColStd_Array1OfReal(1, nk), TColStd_Array1OfInteger(1, nk)
    for k in range(nk):
        uk.SetValue(k + 1, ct.Knot(k + 1))
        um.SetValue(k + 1, ct.Multiplicity(k + 1))
    vk, vm = TColStd_Array1OfReal(1, 2), TColStd_Array1OfInteger(1, 2)
    vk.SetValue(1, 0.0)
    vk.SetValue(2, 1.0)
    vm.SetValue(1, 2)
    vm.SetValue(2, 2)
    srf = Geom_BSplineSurface(Pl, uk, vk, um, vm, ct.Degree(), 1, True, False)
    v_edge = EXT / (1 + EXT)
    fside = BRepBuilderAPI_MakeFace(srf, 1e-7).Face()
    eb = BRepBuilderAPI_MakeEdge(srf.VIso(1.0)).Edge()
    ffloor = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0, 0, 0), gp_Dir(0, 0, -1)), BRepBuilderAPI_MakeWire(eb).Wire()).Face()
    ext_len = float(3.0 + 2 * EXT * hh.max())
    fI = TopoDS_Face()
    BRepLib.ExtendFace_s(fpart, ext_len, True, True, True, True, fI)
    SI = BRep_Tool.Surface_s(fI)
    sew = BRepBuilderAPI_Sewing(1e-5)
    sew.Add(fside)
    sew.Add(ffloor)
    sew.Perform()
    lst = TopTools_ListOfShape()
    lst.Append(sew.SewedShape())
    lst.Append(fI)
    gf = BRepAlgoAPI_BuilderAlgo()
    gf.SetArguments(lst)
    gf.SetFuzzyValue(1e-6)
    gf.Build()
    if not gf.IsDone():
        raise WorkerError('PLATE_SIDE_BUILD', 'General fuse of side, floor and parting surface failed.')
    poly = Polygon(TOP[:, :2])
    keep, tags = [], []
    for f in L.faces(gf.Shape()):
        ip, n = L.inner_point(f)
        if ip is None:
            tags.append('no_inner_point')
            continue
        if abs(ip[2]) < 1e-6 and abs(n[2]) > 0.99:
            tag = 'floor'
        elif GeomAPI_ProjectPointOnSurf(gp_Pnt(*map(float, ip)), SI).LowerDistance() < 1e-5:
            tag = 'parting_in' if contains_xy(poly, ip[0], ip[1]) else 'parting_out'
        else:
            pr = GeomAPI_ProjectPointOnSurf(gp_Pnt(*map(float, ip)), srf)
            tag = 'side_low' if pr.LowerDistanceParameters()[1] > v_edge else 'side_up'
        tags.append(tag)
        if tag in ('floor', 'parting_in', 'side_low'):
            keep.append(f)
    if sorted(t for t in tags if t in ('floor', 'parting_in', 'side_low')) != ['floor', 'parting_in', 'side_low']:
        raise WorkerError('PLATE_SIDE_BUILD', 'The fuse did not split into exactly one floor, one inner parting face and one lower side face.', {'faces': tags})
    sew = BRepBuilderAPI_Sewing(1e-5)
    for f in keep:
        sew.Add(f)
    sew.Perform()
    shells = L.explore(sew.SewedShape(), 'shell')
    if len(shells) != 1 or sew.NbFreeEdges():
        raise WorkerError('PLATE_SIDE_BUILD', 'The kept faces do not sew into one closed shell.', {'shells': len(shells), 'free_edges': sew.NbFreeEdges()})
    sol = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(shells[0])).Solid()
    fx = ShapeFix_Solid(sol)
    fx.Perform()
    sol = L.solids(fx.Solid())[0]
    if L.volume(sol) <= 0:
        sol = TopoDS.Solid_s(sol.Reversed())
    rinfo.update({'stations': N, 'extension_fraction': EXT, 'parting_extension_mm': ext_len, 'fuse_faces': tags, 'side_degree': [srf.UDegree(), srf.VDegree()],
                  'side_poles': [srf.NbUPoles(), srf.NbVPoles()], 'side_u_periodic': bool(srf.IsUPeriodic())})
    return sol, Ptop, Pb, rinfo


# ------------------------------------------------------------------ checks on the re-imported files
def plate_faces(plate, SI_face):
    from OCP.BRep import BRep_Tool
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCP.gp import gp_Pnt
    SI = BRep_Tool.Surface_s(SI_face)
    roles = {}
    for f in L.faces(plate):
        ip, n = L.inner_point(f)
        if ip is None:
            continue
        if abs(ip[2]) < 1e-6 and abs(n[2]) > 0.99:
            roles['floor'] = f
        elif GeomAPI_ProjectPointOnSurf(gp_Pnt(*map(float, ip)), SI).LowerDistance() < 1e-5:
            roles['parting'] = f
        else:
            roles['side'] = f
    return roles


def checks(shell_path: Path, plate_path: Path, asm_path: Path, fpart, TOP, TN, Ptop, Pb, base: dict[str, Any], Q) -> dict[str, Any]:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    import shapely
    from shapely.geometry import Polygon
    out: dict[str, Any] = {}
    shell = L.one_solid(shell_path, 'PLATE_SIDE_SHELL')
    ps = L.solids(L.read_step(plate_path))
    asm = L.read_step(asm_path)
    out['plate'] = {'solids': len(ps), 'valid': bool(len(ps) == 1 and L.is_valid(ps[0])), 'faces': len(L.faces(ps[0])) if ps else 0,
                    'volume_mm3': float(L.volume(ps[0])) if ps else None, 'bbox': L.bbox(ps[0]).round(4).tolist() if ps else None}
    out['assembly'] = {'solids': len(L.solids(asm)), 'valid': bool(L.is_valid(asm))}
    if len(ps) != 1:
        return out
    plate = ps[0]
    try:
        cm = BRepAlgoAPI_Common(shell, plate)
        out['overlap_volume_mm3'] = float(sum(L.volume(s) for s in L.solids(cm.Shape()))) if cm.IsDone() else None
    except Exception:  # noqa: BLE001 - reported as unverified
        out['overlap_volume_mm3'] = None
    out['min_distance_mm'] = float(BRepExtrema_DistShapeShape(shell, plate).Value())
    roles = plate_faces(plate, fpart)
    out['plate_face_roles'] = sorted(roles)
    poly = Polygon(TOP[:, :2])
    tess = L.tessellate(plate, 0.01, 0.05)
    V = tess['V']
    inside = shapely.contains_xy(poly, V[:, 0], V[:, 1])
    d = shapely.distance(shapely.points(V[:, :2]), poly.exterior)
    prot = np.where(inside, -d, d)
    out['plan_protrusion_mm'] = {'max': float(prot.max()), 'points_outside_gt_1um': int((prot > 1e-3).sum()), 'points': len(V)}
    if 'parting' in roles:
        PE = L.wire_points(roles['parting'], 0.02)
        dE = poly_dist(PE, TOP)
        out['top_edge_vs_shell_edge_mm'] = {'max': float(dE.max()), 'p95': float(np.percentile(dE, 95))}
    fr = base['frame']
    if 'floor' in roles:
        F0 = L.wire_points(roles['floor'], 0.02)
        out['floor_z_max_abs_mm'] = float(np.abs(F0[:, 2]).max())
        F0 = F0[:, :2]
        phf, rf = fr.polar(F0)
        o = np.argsort(phf)
        phs, r0 = base['r_source_grid']
        rad = np.interp(phs, phf[o], rf[o], period=2 * np.pi) - r0
        out['floor_vs_base_outline_mm'] = {'hausdorff': hausdorff(F0, base['B'])}
        out['floor_vs_source_outline_mm'] = {'hausdorff': hausdorff(F0, Q), 'radial_max_abs': float(np.abs(rad).max()), 'radial_mean_abs': float(np.abs(rad).mean()),
                                             'radial_min': float(rad.min()), 'radial_max': float(rad.max())}
    # side profile: rays from the frame centre at several z; r(z) must be monotonic on every ray. The re-imported side face is a ruled
    # B-spline S(u, v) = (1 - t) A(u) + t B(u) (t linear in v, B on z = 0), so its section at height z is (z / A_z) A + (1 - z / A_z) B (exact rows).
    if 'side' in roles:
        from OCP.BRep import BRep_Tool
        S = BRep_Tool.Surface_s(roles['side'])
        u0, u1, v0, v1 = S.Bounds()
        us = np.linspace(u0, u1, 8000, endpoint=False)
        A = np.array([S.Value(u, v0).Coord() for u in us])
        Bz = np.array([S.Value(u, v1).Coord() for u in us])
        swapped = np.abs(Bz[:, 2]).max() > 1e-6
        if swapped:
            A, Bz = Bz, A
        pht, _ = fr.polar(TOP)
        o = np.argsort(pht)
        angs = np.radians(np.arange(-180, 180, 2.0))
        zt = np.interp(angs, pht[o], TOP[o, 2], period=2 * np.pi)
        nonmono, maxdev, used = 0, 0.0, 0
        for a, ztop in zip(angs, zt):
            dv = (math.cos(a) * fr.a + math.sin(a) * fr.n)[None]
            zs = np.linspace(0.01, ztop - 0.03, 25)
            r_ = np.array([ray_hits(fr.c[None], dv, (z / A[:, 2])[:, None] * A[:, :2] + (1 - z / A[:, 2])[:, None] * Bz[:, :2], tmin=0.0)[0][0] for z in zs])
            ok = np.isfinite(r_)
            if ok.sum() < 5:
                continue
            used += 1
            z_, r_ = zs[ok], r_[ok]
            dr = np.diff(r_)
            nonmono += int(np.any(dr < -1e-4) and np.any(dr > 1e-4))
            line = r_[0] + (r_[-1] - r_[0]) * (z_ - z_[0]) / (z_[-1] - z_[0])
            maxdev = max(maxdev, float(np.abs(r_ - line).max()))
        out['side_profile'] = {'rays': used, 'z_levels_per_ray': 25, 'rays_non_monotonic_r_of_z': nonmono, 'max_dev_from_straight_line_mm': maxdev,
                               'note': 'Rays are radial from the outline centre, not along the rulings; along each ruling the side is exactly straight.'}
        # shell wall / plate side angle at the parting edge (turn of the outward normals)
        sel = np.flatnonzero(np.isfinite(TN).all(1))
        sel = sel[::max(1, len(sel) // 360)]
        te = EXT / (1 + EXT)
        E = (1 - te) * A + te * Bz
        ang = []
        for i in sel:
            j = int(np.argmin(np.linalg.norm(E[:, :2] - TOP[i, :2], axis=1)))
            t = 1 - TOP[i, 2] / A[j, 2]
            v = v1 - t * (v1 - v0) if swapped else v0 + t * (v1 - v0)
            npl = L.face_normal_uv(roles['side'], us[j], v)
            ang.append(math.degrees(math.acos(float(np.clip(TN[i] @ npl, -1, 1)))))
        out['shell_plate_edge_angle_deg'] = _zones(fr.polar(TOP[sel])[0], np.array(ang))
    run = np.linalg.norm(Ptop[:, :2] - Pb[:, :2], axis=1)
    out['side_to_floor_angle_deg'] = _zones(fr.polar(Pb)[0], np.degrees(np.arctan2(Ptop[:, 2], run)))
    return out


def _zones(phi, val):
    a = np.degrees(np.abs(phi))
    z = np.where(a <= 40, 'front', np.where(a >= 140, 'rear', 'flank'))
    res = {'all': {'min': float(val.min()), 'p50': float(np.median(val)), 'max': float(val.max())}} if len(val) else {}
    for k in ('front', 'flank', 'rear'):
        if (z == k).any():
            v = val[z == k]
            res[k] = {'min': float(v.min()), 'p50': float(np.median(v)), 'max': float(v.max())}
    return res


# ------------------------------------------------------------------ entry
def run(req: dict[str, Any]) -> dict[str, Any]:
    import time
    L.require_ocp()
    t0 = time.time()
    timing = {}
    p = req['params']
    shell_path, outline_path = Path(req['inputs']['shell']), Path(req['inputs']['outline'])
    out = Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    sha0 = sha256(shell_path)
    shell = L.one_solid(shell_path, 'PLATE_SIDE_SHELL')
    if not L.is_valid(shell):
        raise WorkerError('PLATE_SIDE_SHELL', 'The shell solid is not valid (BRepCheck).')
    fpart, TOP, TN, pinfo = shell_parting(shell)
    mir = p.get('mirror')
    mirror = None
    warnings = []
    if mir:
        n = np.array(mir['normal'], float)
        n /= np.linalg.norm(n)
        d = float(mir['d']) / float(np.linalg.norm(mir['normal']))
        s = float(np.linalg.norm(n[:2]))
        if s < 0.9:
            raise WorkerError('PLATE_SIDE_SYMMETRY', 'The mirror plane is not close to vertical (|n_xy| < 0.9).', {'normal': n.tolist()})
        n2, d2 = n[:2] / s, d / s
        if n2[1] < 0 or (n2[1] == 0 and n2[0] < 0):
            n2, d2 = -n2, -d2
        mirror = (n2, d2)
        if s < 0.999:
            warnings.append({'code': 'PLATE_SIDE_MIRROR_TILTED', 'message': 'The mirror plane is tilted; its trace on z = 0 is used.', 'n_xy': s})
    Q, oinfo = auto_section(outline_path, mirror, p) if p['outline_mode'] == 'mesh' and p.get('section_z_mm') is None else \
        read_outline(p['outline_mode'], outline_path, p['section_z_mm'])
    timing['parting_s'] = round(time.time() - t0, 2)
    base = process_outline(Q, TOP[:, :2], mirror, p)
    timing['outline_s'] = round(time.time() - t0, 2)
    brep = base['report']
    if brep['clip']['max_clip_mm'] > p['max_change_mm'] + 1e-6:
        warnings.append({'code': 'PLATE_SIDE_OUTLINE_CLIPPED', 'message': 'The base outline reached outside the shell parting outline (minus min_inset_mm) and was clipped by more than max_change_mm.',
                         'max_clip_mm': brep['clip']['max_clip_mm'], 'points': brep['clip']['points_clipped']})
    sol, Ptop, Pb, rinfo = build_plate(fpart, TOP, base['B'], int(p['n_stations']))
    timing['build_s'] = round(time.time() - t0, 2)
    files = {'bottom_plate': 'bottom_plate.step', 'assembly': 'assembly.step', 'base_outline': 'base_outline.json'}
    L.write_step(sol, out / files['bottom_plate'])
    L.write_step(L.compound([shell, L.solids(L.read_step(out / files['bottom_plate']))[0]]), out / files['assembly'])
    fr = base['frame']
    (out / files['base_outline']).write_text(json.dumps(L.clean({
        'schema': 'base_outline/1', 'frame': 'shell frame, plate floor z = 0, mm', 'closed': True, 'orientation': 'ccw', 'centre': fr.c, 'axis': fr.a,
        'mirror': None if mirror is None else {'normal_2d': mirror[0], 'd': mirror[1]}, 'points': np.round(base['B'], 6),
        'source': oinfo, 'symmetry': brep['symmetry'], 'fairing': brep['fairing'], 'clip': brep['clip']})), encoding='utf-8')
    chk = checks(shell_path, out / files['bottom_plate'], out / files['assembly'], fpart, TOP, TN, Ptop, Pb, base, Q)
    sha1 = sha256(shell_path)
    timing['checks_s'] = round(time.time() - t0, 2)
    return {'worker': WORKER_VERSION, 'files': files, 'parting': pinfo, 'outline_source': oinfo, 'base_outline': brep, 'side': rinfo, 'checks': chk,
            'shell_sha256_before': sha0, 'shell_sha256_after': sha1, 'warnings': warnings,
            'timing_cumulative': timing}


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
