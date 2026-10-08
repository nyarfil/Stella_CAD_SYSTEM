"""Scan -> hollow shell, stage A2 (smooth B-spline route "smooth_fit"). See docs/design/SCAN_TO_SHELL_A2.md.

Two B-spline surfaces with the same (u, v) parametrisation are fitted to rays from one centre: the outer skin (hits on
the scan) and the inner skin (distance-to-scan = thickness). A planar ring face on the opening plane closes them into a
hollow solid. No offset operation is used. Applicability is checked, never assumed; nothing falls back to route
faceted_sdf, nothing is loosened or densified automatically, and every check is PASS / FAIL / UNVERIFIED.
"""
from __future__ import annotations
import hashlib
import math
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import numpy as np
from pydantic import ValidationError
from scipy.spatial import cKDTree
from . import scan_mesh as sm
from . import scan_shell as ss
from .. import __version__
from ..errors import BrainError
from ..req2cad.common import atomic_json
from ..util import file_hash

SCAN_FIT_VERSION = 'A2.0'
ROUTE = 'smooth_fit'
SAMPLES = 20_000
DENSE = 241  # dense evaluation grid of the fitted surface used for the scan -> output direction
EPS_T = 1e-9


# ------------------------------------------------------------------ frame
def _frame(up: np.ndarray) -> np.ndarray:
    """Rows e1, e2, up of an orthonormal right-handed frame; e1 is the world axis least aligned with up (projected)."""
    ref = np.zeros(3)
    ref[int(np.argmin(np.abs(up)))] = 1.0
    e1 = ref - (ref @ up) * up
    e1 /= np.linalg.norm(e1)
    return np.stack([e1, np.cross(up, e1), up])


# ------------------------------------------------------------------ section of the scan with the opening plane
def _section_segments(v: np.ndarray, f: np.ndarray) -> np.ndarray:
    """Directed segments (m, 2, 2) of the mesh cut by z = 0 (local frame). Vertices with z > 0 count as 'above'.
    The direction is counter-clockwise seen from +z for an outward-oriented mesh."""
    above = v[f][:, :, 2] > 0
    k = above.sum(1)
    out: list[np.ndarray] = []
    for case in (1, 2):
        sel = np.flatnonzero(k == case)
        if not len(sel):
            continue
        tri = f[sel]
        odd = np.where(above[sel] if case == 1 else ~above[sel], 1, 0)
        shift = np.argmax(odd, axis=1)
        rt = np.take_along_axis(tri, (np.arange(3)[None, :] + shift[:, None]) % 3, axis=1)
        a, b, c = v[rt[:, 0]], v[rt[:, 1]], v[rt[:, 2]]
        za, zb, zc = a[:, 2], b[:, 2], c[:, 2]
        pab = a + (b - a) * (za / (za - zb))[:, None]
        pac = a + (c - a) * (za / (za - zc))[:, None]
        # case 1: a above, clipped triangle a, pab, pac (CCW) -> cut edge pab -> pac
        # case 2: a below, b and c above, clipped quad pab, b, c, pca -> cut edge pca -> pab
        out.append(np.stack([pab[:, :2], pac[:, :2]], 1) if case == 1 else np.stack([pac[:, :2], pab[:, :2]], 1))
    return np.concatenate(out) if out else np.zeros((0, 2, 2))


def _section_centroid(segs: np.ndarray) -> tuple[np.ndarray, float]:
    p, q = segs[:, 0], segs[:, 1]
    cr = p[:, 0] * q[:, 1] - q[:, 0] * p[:, 1]
    area = float(cr.sum() / 2.0)
    if abs(area) < 1e-9:
        raise BrainError('SMOOTH_FIT_NO_SECTION', 'The opening plane does not cut the scan (or the section has no area).', {'section_area_mm2': area})
    cx = float(((p[:, 0] + q[:, 0]) * cr).sum() / (6.0 * area))
    cy = float(((p[:, 1] + q[:, 1]) * cr).sum() / (6.0 * area))
    return np.array([cx, cy]), area


# ------------------------------------------------------------------ square -> hemisphere map
def hemisphere_directions(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Unit hemisphere directions for the n x n square grid (u, v in [-1, 1]) via the elliptical grid map, and the
    boundary mask (square boundary -> equator, z = 0)."""
    g = np.linspace(-1.0, 1.0, n)
    u, v = np.meshgrid(g, g, indexing='ij')
    x = u * np.sqrt(1.0 - v * v / 2.0)
    y = v * np.sqrt(1.0 - u * u / 2.0)
    z2 = 1.0 - x * x - y * y
    bnd = np.zeros((n, n), bool)
    bnd[0, :] = bnd[-1, :] = bnd[:, 0] = bnd[:, -1] = True
    z = np.where(bnd, 0.0, np.sqrt(np.clip(z2, 0.0, None)))
    d = np.stack([x, y, z], axis=-1)
    d[bnd] /= np.linalg.norm(d[bnd], axis=-1, keepdims=True)  # exact unit length on the equator
    return d, bnd


# ------------------------------------------------------------------ ray hits
class _RayMesh:
    """Exact ray / triangle intersection for rays that share one origin, with angular candidate culling."""

    def __init__(self, v: np.ndarray, f: np.ndarray, origin: np.ndarray, half: np.ndarray):
        keep = (v[f][:, :, 2] >= -1e-9).any(axis=1)
        self.a, self.b, self.c = (v[f[keep][:, i]] for i in range(3))
        self.origin = origin
        self.half = half
        s = [(x - origin) / half for x in (self.a, self.b, self.c)]
        un = [x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-12) for x in s]
        near = np.minimum.reduce([np.linalg.norm(x, axis=1) for x in s]) < 1e-6
        cen = un[0] + un[1] + un[2]
        cn = np.linalg.norm(cen, axis=1, keepdims=True)
        cen = cen / np.maximum(cn, 1e-12)
        rad = np.maximum.reduce([np.linalg.norm(x - cen, axis=1) for x in un]) * 1.02 + 1e-9
        wide = near | (cn[:, 0] < 0.5) | (rad > 0.6)  # triangles too large angularly for the culling: always candidates
        self.wide = np.flatnonzero(wide)
        idx = np.flatnonzero(~wide)
        self.idx, self.cen, self.rad = idx, cen[idx], rad[idx]
        self.tree = cKDTree(self.cen) if len(idx) else None
        self.rmax = float(self.rad.max()) if len(idx) else 0.0

    def hits(self, dirs_unit: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """dirs_unit: unit directions in the scaled frame. Returns (ray ids, parameters t) of all deduplicated hits,
        t measured along the mm direction (a dx, b dy, c dz)."""
        n = len(dirs_unit)
        lists = self.tree.query_ball_point(dirs_unit, self.rmax) if self.tree is not None else [[] for _ in range(n)]
        ray_ids, tri_ids = [], []
        for i, lst in enumerate(lists):
            if lst:
                arr = self.idx[np.asarray(lst, dtype=np.int64)]
                arr = arr[np.linalg.norm(self.cen[np.asarray(lst, dtype=np.int64)] - dirs_unit[i], axis=1) <= self.rad[np.asarray(lst, dtype=np.int64)]]
            else:
                arr = np.zeros(0, np.int64)
            if len(self.wide):
                arr = np.concatenate([arr, self.wide])
            ray_ids.append(np.full(len(arr), i, np.int64))
            tri_ids.append(arr)
        rid, tid = np.concatenate(ray_ids), np.concatenate(tri_ids)
        d = dirs_unit * self.half
        a, b, c = self.a[tid], self.b[tid], self.c[tid]
        e1, e2 = b - a, c - a
        dd = d[rid]
        pv = np.cross(dd, e2)
        det = np.einsum('ij,ij->i', e1, pv)
        good = np.abs(det) > 1e-14 * np.maximum(np.linalg.norm(e1, axis=1) * np.linalg.norm(e2, axis=1) * np.linalg.norm(dd, axis=1), 1e-300)
        sdet = np.where(good, det, 1.0)
        tv = self.origin - a
        u = np.einsum('ij,ij->i', tv, pv) / sdet
        qv = np.cross(tv, e1)
        w = np.einsum('ij,ij->i', dd, qv) / sdet
        t = np.einsum('ij,ij->i', e2, qv) / sdet
        tol = 1e-10
        ok = good & (u >= -tol) & (w >= -tol) & (u + w <= 1 + tol) & (t > EPS_T)
        rid, t = rid[ok], t[ok]
        order = np.lexsort((t, rid))
        rid, t = rid[order], t[order]
        if len(t):
            dup = np.concatenate([[False], (rid[1:] == rid[:-1]) & (np.abs(t[1:] - t[:-1]) <= 1e-8 * np.maximum(1.0, t[1:]))])
            rid, t = rid[~dup], t[~dup]
        return rid, t


def _section_hits(segs: np.ndarray, c2: np.ndarray, dirs2: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """2D rays from c2 against the section segments. Returns (ray ids, t) deduplicated."""
    p, q = segs[:, 0], segs[:, 1]
    r = q - p
    rid_all, t_all = [], []
    for i, d in enumerate(dirs2):
        den = d[0] * r[:, 1] - d[1] * r[:, 0]
        good = np.abs(den) > 1e-14
        sden = np.where(good, den, 1.0)
        w = p - c2
        t = (w[:, 0] * r[:, 1] - w[:, 1] * r[:, 0]) / sden
        s = (w[:, 0] * d[1] - w[:, 1] * d[0]) / sden
        ok = good & (t > EPS_T) & (s >= -1e-9) & (s <= 1 + 1e-9)
        tt = np.sort(t[ok])
        if len(tt):
            keep = np.concatenate([[True], np.abs(np.diff(tt)) > 1e-8 * np.maximum(1.0, tt[1:])])
            tt = tt[keep]
        rid_all.append(np.full(len(tt), i, np.int64))
        t_all.append(tt)
    return np.concatenate(rid_all), np.concatenate(t_all)


def ray_grid(v: np.ndarray, f: np.ndarray, grid: int) -> dict[str, Any]:
    """Local-frame mesh (plane z = 0, up = +z) -> grid of surface points and the star-shape verdict."""
    segs = _section_segments(v, f)
    if not len(segs):
        raise BrainError('SMOOTH_FIT_NO_SECTION', 'The opening plane does not cut the scan.')
    c2, area = _section_centroid(segs)
    origin = np.array([c2[0], c2[1], 0.0])
    pts_above = v[v[:, 2] > 0]
    if not len(pts_above):
        raise BrainError('SMOOTH_FIT_NO_SECTION', 'No scan material lies above the opening plane (check the normal direction).')
    allp = np.concatenate([pts_above[:, :2], segs.reshape(-1, 2)])
    half = np.array([np.abs(allp[:, 0] - c2[0]).max(), np.abs(allp[:, 1] - c2[1]).max(), pts_above[:, 2].max()])
    if (half <= 1e-6).any():
        raise BrainError('SMOOTH_FIT_NO_SECTION', 'The part above the opening plane is degenerate.', {'half_extents_mm': half.tolist()})
    dirs, bnd = hemisphere_directions(grid)
    flat = dirs.reshape(-1, 3)
    isb = bnd.reshape(-1)
    pts = np.zeros((grid * grid, 3))
    nhits = np.zeros(grid * grid, np.int64)
    # interior rays against the mesh
    rm = _RayMesh(v, f, origin, half)
    ii = np.flatnonzero(~isb)
    rid, t = rm.hits(flat[ii])
    cnt = np.bincount(rid, minlength=len(ii))
    nhits[ii] = cnt
    first = np.full(len(ii), np.nan)
    first_idx = np.searchsorted(rid, np.arange(len(ii)))
    has = cnt > 0
    first[has] = t[first_idx[has]]
    pts[ii] = origin + (flat[ii] * half) * first[:, None]
    # equator rays against the section curve (exactly on the plane)
    bi = np.flatnonzero(isb)
    d2 = flat[bi][:, :2] * half[:2]
    rid2, t2 = _section_hits(segs, c2, d2)
    cnt2 = np.bincount(rid2, minlength=len(bi))
    nhits[bi] = cnt2
    f2 = np.full(len(bi), np.nan)
    f2i = np.searchsorted(rid2, np.arange(len(bi)))
    h2 = cnt2 > 0
    f2[h2] = t2[f2i[h2]]
    pts[bi, :2] = c2 + d2 * f2[:, None]
    pts[bi, 2] = 0.0
    fail = nhits != 1
    s_hit = np.zeros(grid * grid)
    s_hit[ii] = first
    s_hit[bi] = f2
    return {'s_hit': np.nan_to_num(s_hit).reshape(grid, grid), 'dirs_mm': (flat * half).reshape(grid, grid, 3), 'origin_local': origin, 'points': pts.reshape(grid, grid, 3), 'hit_counts': nhits.reshape(grid, grid), 'fail_mask': fail.reshape(grid, grid),
            'centre_local_mm': origin.tolist(), 'section_area_mm2': area, 'half_extents_mm': half.tolist(),
            'directions': dirs, 'boundary': bnd}


def inner_ray_points(dist, v: np.ndarray, f: np.ndarray, rg: dict[str, Any], p0: np.ndarray, R: np.ndarray, t: float, steps: int = 48, iters: int = 32,
                     polish: int = 3, n_samples: int = 400000) -> dict[str, Any]:
    """Inner skin points on the same rays as the outer skin: the outermost point along each ray (centre C -> outer hit) at
    distance t from the scan (phi = -t, phi = -unsigned distance inside the scan).
    1. bracket + bisection on a fast distance (nearest of `n_samples` dense surface samples + all vertices, a slight over-estimate of the distance);
    2. `polish` Newton steps on the EXACT point-to-mesh distance of A1 (MeshDistance) with a finite-difference slope, so the result
       is a crossing of the exact distance field up to the reported residual (not trilinear phi).
    A ray with no sample at distance >= t has no phi = -t crossing (locally solid): reported, never patched."""
    from scipy.spatial import cKDTree as _KD
    sp, _ = sm.sample_surface(v, f, n_samples)
    tree = _KD(np.concatenate([sp, v]))
    O = np.asarray(rg['origin_local'])
    D = rg['dirs_mm'].reshape(-1, 3)
    S = rg['s_hit'].reshape(-1)
    n = len(S)

    def pw(sv: np.ndarray, idx: np.ndarray) -> np.ndarray:
        return p0 + (O + D[idx] * sv[:, None]) @ R

    def fast(sv: np.ndarray, idx: np.ndarray) -> np.ndarray:
        return tree.query(pw(sv, idx), workers=-1)[0]

    fr = np.linspace(0.0, 1.0, steps + 1)
    all_idx = np.arange(n)
    dm = np.stack([fast(S * fk, all_idx) for fk in fr], axis=1)
    good = dm >= t
    has = good.any(axis=1)
    last = steps - np.argmax(good[:, ::-1], axis=1)
    lo = np.where(has, fr[last] * S, 0.0)
    hi = np.where(has, fr[np.minimum(last + 1, steps)] * S, 0.0)
    act = np.flatnonzero(has & (last < steps))
    for _ in range(iters):
        if not len(act):
            break
        mid = 0.5 * (lo[act] + hi[act])
        ok = fast(mid, act) >= t
        lo[act] = np.where(ok, mid, lo[act])
        hi[act] = np.where(ok, hi[act], mid)
    sc = lo.copy()
    h = np.flatnonzero(has & (last < steps))
    resid = np.zeros(n)
    dl = np.linalg.norm(D, axis=1)
    for _ in range(polish):
        if not len(h):
            break
        d0 = dist.distance(pw(sc[h], h))
        eps = 0.05
        d1 = dist.distance(pw(np.maximum(sc[h] - eps, 0.0), h))
        slope = (d1 - d0) / np.maximum(sc[h] - np.maximum(sc[h] - eps, 0.0), 1e-12)  # d(dist)/ds, expected negative toward the surface... (positive going inward)
        slope = np.where(np.abs(slope) < 1e-3 * dl[h], -1e-3 * dl[h], -np.abs(slope))
        step = (d0 - t) / (-slope)  # move outward (s up) when d0 > t
        sc[h] = np.clip(sc[h] + step, 0.0, S[h])
        resid[h] = d0 - t
    final = dist.distance(pw(sc[has], np.flatnonzero(has))) if has.any() else np.zeros(0)
    res_all = np.zeros(n)
    res_all[has] = final - t
    pts = O + D * sc[:, None]
    return {'points': pts.reshape(rg['points'].shape), 'locally_solid': (~has).reshape(rg['s_hit'].shape), 's': sc.reshape(rg['s_hit'].shape),
            'crossing_residual_mm': {'max_abs': float(np.abs(res_all).max()) if has.any() else None, 'mean_abs': float(np.abs(res_all[has]).mean()) if has.any() else None,
                                     'basis': 'exact distance at the final inner points minus thickness'},
            'method': f'bracket ({steps + 1} samples per ray) + {iters} bisections on a dense-sample nearest distance, then {polish} Newton steps on the exact point-to-mesh distance (A1 MeshDistance); not trilinear phi'}


# ------------------------------------------------------------------ B-spline helpers
def _ocp_fit():
    ss._ocp()


def fit_surface(points: np.ndarray, degree_min: int, degree_max: int, tol: float, smoothing: float):
    """GeomAPI_PointsToBSplineSurface on the (n, n, 3) grid. Returns the Geom_BSplineSurface (local frame)."""
    from OCP.Approx import Approx_ParametrizationType
    from OCP.GeomAbs import GeomAbs_Shape
    from OCP.GeomAPI import GeomAPI_PointsToBSplineSurface
    from OCP.gp import gp_Pnt
    from OCP.TColgp import TColgp_Array2OfPnt
    n = points.shape[0]
    arr = TColgp_Array2OfPnt(1, n, 1, n)
    for i in range(n):
        for j in range(n):
            p = points[i, j]
            arr.SetValue(i + 1, j + 1, gp_Pnt(float(p[0]), float(p[1]), float(p[2])))
    if smoothing > 0:
        w = float(smoothing)
        api = GeomAPI_PointsToBSplineSurface(arr, w, w, w, int(degree_max), GeomAbs_Shape.GeomAbs_C2, float(tol))
    else:
        api = GeomAPI_PointsToBSplineSurface(arr, Approx_ParametrizationType.Approx_IsoParametric, int(degree_min), int(degree_max), GeomAbs_Shape.GeomAbs_C2, float(tol))
    if not api.IsDone():
        raise BrainError('SMOOTH_FIT_APPROX_FAILED', 'GeomAPI_PointsToBSplineSurface did not complete.')
    return api.Surface()


def surface_data(surf) -> dict[str, np.ndarray | int]:
    nu, nv = surf.NbUPoles(), surf.NbVPoles()
    poles = np.array([[[surf.Pole(i, j).X(), surf.Pole(i, j).Y(), surf.Pole(i, j).Z()] for j in range(1, nv + 1)] for i in range(1, nu + 1)])
    uk, vk = surf.UKnots(), surf.VKnots()
    um, vm = surf.UMultiplicities(), surf.VMultiplicities()
    return {'poles': poles, 'uknots': np.array([uk.Value(i) for i in range(uk.Lower(), uk.Upper() + 1)]),
            'vknots': np.array([vk.Value(i) for i in range(vk.Lower(), vk.Upper() + 1)]),
            'umults': np.array([um.Value(i) for i in range(um.Lower(), um.Upper() + 1)], dtype=np.int64),
            'vmults': np.array([vm.Value(i) for i in range(vm.Lower(), vm.Upper() + 1)], dtype=np.int64),
            'udeg': int(surf.UDegree()), 'vdeg': int(surf.VDegree())}


def make_surface(d: dict[str, Any]):
    from OCP.Geom import Geom_BSplineSurface
    from OCP.gp import gp_Pnt
    from OCP.TColgp import TColgp_Array2OfPnt
    from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal
    nu, nv = d['poles'].shape[:2]
    pa = TColgp_Array2OfPnt(1, nu, 1, nv)
    for i in range(nu):
        for j in range(nv):
            p = d['poles'][i, j]
            pa.SetValue(i + 1, j + 1, gp_Pnt(float(p[0]), float(p[1]), float(p[2])))

    def reals(x):
        a = TColStd_Array1OfReal(1, len(x))
        for i, val in enumerate(x):
            a.SetValue(i + 1, float(val))
        return a

    def ints(x):
        a = TColStd_Array1OfInteger(1, len(x))
        for i, val in enumerate(x):
            a.SetValue(i + 1, int(val))
        return a
    return Geom_BSplineSurface(pa, reals(d['uknots']), reals(d['vknots']), ints(d['umults']), ints(d['vmults']), int(d['udeg']), int(d['vdeg']))


def poles_hash(d: dict[str, Any]) -> str:
    h = hashlib.sha256()
    for k in ('poles', 'uknots', 'vknots', 'umults', 'vmults'):
        h.update(np.ascontiguousarray(d[k]).tobytes())
    h.update(np.array([d['udeg'], d['vdeg']], dtype=np.int64).tobytes())
    return h.hexdigest()


def _interior_knots(knots: np.ndarray, mults: np.ndarray) -> list[dict[str, float]]:
    return [{'knot': float(k), 'multiplicity': int(m)} for k, m in zip(knots[1:-1], mults[1:-1])]


# ------------------------------------------------------------------ B-rep
def _eval_surface(surf, uv: np.ndarray) -> np.ndarray:
    out = np.empty((len(uv), 3))
    for i, (u, v) in enumerate(uv):
        p = surf.Value(float(u), float(v))
        out[i] = (p.X(), p.Y(), p.Z())
    return out


def build_hollow_solid(surf_out, surf_in, p0: np.ndarray, up: np.ndarray):
    """Outer face + inner face + one planar ring face on the opening plane (outer rim wire, inner rim hole), sewn into a solid."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_Sewing
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Ax3, gp_Dir, gp_Pln, gp_Pnt
    from OCP.ShapeFix import ShapeFix_Face, ShapeFix_Solid
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS, TopoDS_Solid
    faces = []
    for sf_ in (surf_out, surf_in):
        mk = BRepBuilderAPI_MakeFace(sf_, 1e-7)
        if not mk.IsDone():
            raise BrainError('SMOOTH_FIT_BREP_INVALID', 'A fitted surface could not be made into a face.')
        faces.append(mk.Face())
    outer, inner = faces
    plane = gp_Pln(gp_Ax3(gp_Pnt(*map(float, p0)), gp_Dir(*map(float, -up))))
    ring = BRepBuilderAPI_MakeFace(plane, BRepTools.OuterWire_s(outer), True)
    if not ring.IsDone():
        raise BrainError('SMOOTH_FIT_BREP_INVALID', 'The ring face could not be built from the outer rim wire (is the rim planar?).')
    ring.Add(BRepTools.OuterWire_s(inner))
    fx = ShapeFix_Face(ring.Face())
    fx.Perform()
    sew = BRepBuilderAPI_Sewing(1e-6)
    for fc in (outer, inner, fx.Face()):
        sew.Add(fc)
    sew.Perform()
    ex = TopExp_Explorer(sew.SewedShape(), TopAbs_SHELL)
    if not ex.More():
        raise BrainError('SMOOTH_FIT_BREP_INVALID', 'Sewing did not produce a shell.')
    solid = TopoDS_Solid()
    BRep_Builder().MakeSolid(solid)
    BRep_Builder().Add(solid, TopoDS.Shell_s(ex.Current()))
    from OCP.BRepCheck import BRepCheck_Analyzer
    if BRepCheck_Analyzer(solid).IsValid() and ss._volume(solid) > 0:
        return solid, []
    before = {'invalid': invalid_details(solid), 'volume_mm3': ss._volume(solid)}
    fs = ShapeFix_Solid()
    fs.Init(solid)
    fs.Perform()
    fixed = fs.Solid()
    return fixed, [{'what': 'ShapeFix_Solid after sewing (raw sewn solid was invalid or inside-out)', 'before': before,
                    'valid_after': bool(BRepCheck_Analyzer(fixed).IsValid()), 'volume_after_mm3': ss._volume(fixed)}]


def faces_of(shape) -> list:
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape
    fm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, fm)
    return [TopoDS.Face_s(fm.FindKey(i)) for i in range(1, fm.Extent() + 1)]


def invalid_details(shape) -> list[dict[str, Any]]:
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
    from OCP.TopExp import TopExp_Explorer
    an = BRepCheck_Analyzer(shape)
    out = []
    for kind, name in ((TopAbs_FACE, 'face'), (TopAbs_EDGE, 'edge'), (TopAbs_VERTEX, 'vertex')):
        ex, i = TopExp_Explorer(shape, kind), 0
        while ex.More():
            r = an.Result(ex.Current())
            if r is not None:
                bad = [str(x).split('.')[-1] for x in r.Status() if 'NoError' not in str(x)]
                if bad:
                    out.append({'kind': name, 'index': i, 'status': bad})
            i += 1
            ex.Next()
    return out[:20]


def tessellate_face(face, deflection: float) -> tuple[np.ndarray, np.ndarray]:
    """Triangles of one face (orientation applied, global coordinates)."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    cp = TopoDS.Face_s(BRepBuilderAPI_Copy(face).Shape())
    BRepMesh_IncrementalMesh(cp, float(deflection), False, 0.1, False)
    loc = TopLoc_Location()
    poly = BRep_Tool.Triangulation_s(cp, loc)
    if poly is None:
        return np.zeros((0, 3)), np.zeros((0, 3), np.int64)
    trsf = loc.Transformation()
    vv = np.array([(p.X(), p.Y(), p.Z()) for p in (poly.Node(i).Transformed(trsf) for i in range(1, poly.NbNodes() + 1))])
    ff = np.array([poly.Triangle(i).Get() for i in range(1, poly.NbTriangles() + 1)], dtype=np.int64) - 1
    if cp.Orientation() == TopAbs_REVERSED:
        ff = ff[:, [0, 2, 1]]
    return vv, ff


def tessellate_shape(shape, deflection: float) -> tuple[np.ndarray, np.ndarray]:
    vs, fs, base = [], [], 0
    for face in faces_of(shape):
        v, f = tessellate_face(face, deflection)
        if len(f):
            vs.append(v)
            fs.append(f + base)
            base += len(v)
    return np.concatenate(vs), np.concatenate(fs)


def _project_distance(surf, pts: np.ndarray, uv0: np.ndarray) -> np.ndarray:
    """Distance from points to the (untrimmed) B-spline surface by bounded local minimisation of |S(u,v)-P|^2 started at uv0.
    (OCCT's GeomAPI_ProjectPointOnSurf crashed natively on some degraded surfaces, so only D1 evaluations are used.)"""
    from OCP.gp import gp_Pnt, gp_Vec
    from scipy.optimize import minimize
    u0, u1, v0, v1 = surf.Bounds()
    out = np.empty(len(pts))
    for i, (p, start) in enumerate(zip(pts, uv0)):
        def fun(x, p=p):
            pt, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
            surf.D1(float(x[0]), float(x[1]), pt, du, dv)
            r = np.array([pt.X() - p[0], pt.Y() - p[1], pt.Z() - p[2]])
            return float(r @ r), np.array([2 * (r @ [du.X(), du.Y(), du.Z()]), 2 * (r @ [dv.X(), dv.Y(), dv.Z()])])
        res = minimize(fun, start, jac=True, method='L-BFGS-B', bounds=[(u0, u1), (v0, v1)], options={'maxiter': 100, 'ftol': 1e-14, 'gtol': 1e-10})
        out[i] = math.sqrt(max(min(res.fun, fun(start)[0]), 0.0))
    return out


class OuterSurfaceDistance:
    """Distance to the fitted outer face: dense tessellation for all points, exact projection to confirm the worst."""

    def __init__(self, surf, n: int = DENSE):
        u0, u1, v0, v1 = surf.Bounds()
        g_u, g_v = np.linspace(u0, u1, n), np.linspace(v0, v1, n)
        uu, vv = np.meshgrid(g_u, g_v, indexing='ij')
        pts = _eval_surface(surf, np.stack([uu.ravel(), vv.ravel()], 1))
        idx = np.arange(n * n).reshape(n, n)
        f1 = np.stack([idx[:-1, :-1], idx[1:, :-1], idx[1:, 1:]], -1).reshape(-1, 3)
        f2 = np.stack([idx[:-1, :-1], idx[1:, 1:], idx[:-1, 1:]], -1).reshape(-1, 3)
        self.surf = surf
        self.md = sm.MeshDistance(pts, np.concatenate([f1, f2]))
        self.vertices = pts
        self.uv = np.stack([uu.ravel(), vv.ravel()], 1)
        self.tree = cKDTree(pts)

    def refined(self, pts: np.ndarray, dmesh: np.ndarray, which: str, k: int = 60) -> float:
        order = np.argsort(dmesh)
        sel = order[-k:] if which == 'max' else order[:k]
        ex = _project_distance(self.surf, pts[sel], self.uv[self.tree.query(pts[sel])[1]])
        return float(ex.max() if which == 'max' else ex.min())


# ------------------------------------------------------------------ build
def _stats(x: np.ndarray, *pcts: float) -> dict[str, float]:
    return ss._stats(x, *pcts)


def build_shell_smooth(workspace: Path, scan_id: str, thickness_mm: float, opening: dict[str, Any], grid: int = 121, degree_min: int = 3,
                       degree_max: int = 5, outer_tolerance_mm: float = 0.15, thickness_tolerance_mm: float = 0.1,
                       fit_tolerance_mm: float | None = None, smoothing: float = 0.0) -> dict[str, Any]:
    fit_tol = float(fit_tolerance_mm) if fit_tolerance_mm is not None else outer_tolerance_mm / 2.0
    for name, val in (('thickness_mm', thickness_mm), ('outer_tolerance_mm', outer_tolerance_mm), ('thickness_tolerance_mm', thickness_tolerance_mm), ('fit_tolerance_mm', fit_tol)):
        if not math.isfinite(val) or val <= 0:
            raise BrainError('SHELL_SETTINGS', f'{name} must be a positive finite number.')
    if not math.isfinite(smoothing) or smoothing < 0:
        raise BrainError('SHELL_SETTINGS', 'smoothing must be a finite number >= 0 (0 = plain approximation).')
    if isinstance(grid, bool) or not isinstance(grid, int) or not 9 <= grid <= 201:
        raise BrainError('SHELL_SETTINGS', 'grid must be an integer in [9, 201].')
    if any(isinstance(x, bool) or not isinstance(x, int) for x in (degree_min, degree_max)) or not 3 <= degree_min <= degree_max <= 5:
        raise BrainError('SHELL_SETTINGS', 'degree_min <= degree_max must be integers within 3..5.')
    try:
        op = ss.PlaneOpening.model_validate(opening)
    except ValidationError as exc:
        raise BrainError('SHELL_OPENING_INVALID', 'opening must be {type:"plane", point:[x,y,z], normal:[x,y,z]} in mm.', {'error_count': len(exc.errors())}) from exc
    d, prep = ss.load_prepared(workspace, scan_id)
    ss._ocp()
    t0 = time.perf_counter()
    v, f = ss.load_prepared_mesh(d)
    p0 = np.array(op.point, dtype=np.float64)
    nrm = np.array(op.normal, dtype=np.float64)
    nrm /= np.linalg.norm(nrm)
    up = -nrm
    t = float(thickness_mm)
    R = _frame(up)
    settings = {'route': ROUTE, 'scan_id': scan_id, 'thickness_mm': t, 'opening': {'type': 'plane', 'point': p0.tolist(), 'normal': nrm.tolist()},
                'grid': grid, 'degree_min': degree_min, 'degree_max': degree_max, 'outer_tolerance_mm': outer_tolerance_mm,
                'thickness_tolerance_mm': thickness_tolerance_mm, 'fit_tolerance_mm': fit_tol, 'smoothing': smoothing,
                'smoothing_note': 'smoothing = 0: plain approximation; > 0: GeomAPI_PointsToBSplineSurface smoothing variant with weights (length, curvature, torsion) all equal to this value and degree_max as degree bound (degree_min not used)'}
    out_name = 'build_report_smooth.json'

    def stop(code: str, message: str, details: dict[str, Any]):
        atomic_json(d / out_name, {'schema': 'scan_shell_build_report/1', 'settings': settings,
                                   'execution': {'completed': False, 'code': code, 'message': message, 'details': details}, 'design_status': 'UNVERIFIED'})
        raise BrainError(code, message, details)

    vl = (v - p0) @ R.T
    # 1. grid of ray hits (star-shape verdict first)
    rg = ray_grid(vl, f, grid)
    fail = rg['fail_mask']
    if fail.any():
        dirs = rg['directions'][fail]
        order = np.argsort(rg['hit_counts'][fail], kind='stable')[::-1]
        examples = [{'direction_scaled_frame': [round(float(x), 5) for x in dirs[i]], 'hits': int(rg['hit_counts'][fail][i])} for i in order[:12]]
        stop('SMOOTH_FIT_NOT_STAR_SHAPED', 'The scan above the opening plane is not star-shaped from the section centroid: some rays do not leave the surface exactly once. Route faceted_sdf may still work; nothing falls back.',
             {'failing_rays': int(fail.sum()), 'rays': int(fail.size), 'failing_fraction': float(fail.mean()), 'grid': grid,
              'hit_count_histogram': {int(k): int(c) for k, c in zip(*np.unique(rg['hit_counts'], return_counts=True))},
              'examples': examples, 'centre_world_mm': (p0 + rg['centre_local_mm'][0] * R[0] + rg['centre_local_mm'][1] * R[1]).tolist(),
              'sampled_on_grid_only': True})
    t_rays = time.perf_counter() - t0
    # 2. inner rays (phi = -t crossing on the same rays), then fit both surfaces with identical settings
    t1 = time.perf_counter()
    dist = sm.MeshDistance(v, f)
    ir = inner_ray_points(dist, v, f, rg, p0, R, t)
    solid_mask = ir['locally_solid']
    if solid_mask.any():
        dirs = rg['directions'][solid_mask]
        examples = [{'direction_scaled_frame': [round(float(x), 5) for x in dd_], 'ray_index': [int(a_), int(b_)]} for dd_, (a_, b_) in zip(dirs[:12], np.argwhere(solid_mask)[:12])]
        stop('SMOOTH_FIT_LOCALLY_SOLID', 'Some rays from the centre have no phi = -t crossing above the opening plane (the scan is locally thinner than 2 x thickness or solid there). No fallback was attempted.',
             {'failing_rays': int(solid_mask.sum()), 'rays': int(solid_mask.size), 'failing_fraction': float(solid_mask.mean()), 'grid': grid, 'thickness_mm': t,
              'examples': examples, 'centre_world_mm': (p0 + rg['centre_local_mm'][0] * R[0] + rg['centre_local_mm'][1] * R[1]).tolist(), 'sampled_on_grid_only': True})
    t_inner = time.perf_counter() - t1
    t1 = time.perf_counter()
    try:
        surf_l = fit_surface(rg['points'], degree_min, degree_max, fit_tol, smoothing)
        surf_i = fit_surface(ir['points'], degree_min, degree_max, fit_tol, smoothing)
    except BrainError as exc:
        stop(exc.code, exc.message, getattr(exc, 'details', {}) or {})
    sd = surface_data(surf_l)
    sdi = surface_data(surf_i)
    t_fit = time.perf_counter() - t1
    snap = 0.0
    for sdx in (sd, sdi):
        plx = sdx['poles']
        bzx = np.concatenate([plx[0, :, 2], plx[-1, :, 2], plx[:, 0, 2], plx[:, -1, 2]])
        snap = max(snap, float(np.abs(bzx).max()))
    if snap > fit_tol / 10.0:
        stop('SMOOTH_FIT_BOUNDARY_NOT_PLANAR', 'The fitted boundary poles do not lie on the opening plane; the ring face cannot be planar.', {'max_boundary_pole_offset_mm': snap, 'limit_mm': fit_tol / 10.0})
    for sdx in (sd, sdi):
        plx = sdx['poles']
        plx[0, :, 2] = 0.0
        plx[-1, :, 2] = 0.0
        plx[:, 0, 2] = 0.0
        plx[:, -1, 2] = 0.0
    surf_l = make_surface(sd)
    surf_i = make_surface(sdi)
    pl = sd['poles']
    iu = _interior_knots(sd['uknots'], sd['umults'])
    iv = _interior_knots(sd['vknots'], sd['vmults'])
    maxmult_u = max([k['multiplicity'] for k in iu], default=0)
    maxmult_v = max([k['multiplicity'] for k in iv], default=0)
    maxmult = max(maxmult_u, maxmult_v)
    fit_report = {
        'grid': grid, 'points': int(grid * grid), 'parametrisation': 'square (u,v) in [-1,1]^2 -> elliptical grid map -> unit disk -> upper unit hemisphere; isoparametric (uniform) parameters',
        'rim_corner_singular_points': 'the four square corners are parametric singular points (Jacobian degenerates); they lie on the opening plane boundary',
        'centre_local_mm': rg['centre_local_mm'], 'section_area_mm2': rg['section_area_mm2'], 'half_extents_mm': rg['half_extents_mm'],
        'degree': [sd['udeg'], sd['vdeg']], 'poles': [int(pl.shape[0]), int(pl.shape[1])], 'pole_count': int(pl.shape[0] * pl.shape[1]),
        'interior_knots_u': iu, 'interior_knots_v': iv, 'max_interior_knot_multiplicity': {'u': maxmult_u, 'v': maxmult_v},
        'smoothing': smoothing, 'smoothing_weights': [smoothing] * 3 if smoothing > 0 else None, 'fit_tolerance_mm': fit_tol,
        'residual_at_grid_points_mm': None,
        'boundary_pole_plane_offset_snapped_mm': snap, 'poles_sha256': poles_hash(sd),
    }
    # 3. world surface, solid, hollow
    sw = dict(sd)
    sw['poles'] = p0 + pl @ R
    surf_w = make_surface(sw)
    osd = OuterSurfaceDistance(surf_w)
    gw = (p0 + rg['points'].reshape(-1, 3) @ R)
    gmesh = osd.md.distance(gw)
    gexact = osd.refined(gw, gmesh, 'max')
    gi = int(np.argmax(gmesh))
    fit_report['residual_at_grid_points_mm'] = {'max': max(float(gmesh.max()), gexact), 'mean': float(gmesh.mean()), 'worst_grid_index': [gi // grid, gi % grid],
                                                'basis': 'closest-point distance from every grid point to the fitted surface (dense tessellation; the 60 worst re-measured by exact projection)',
                                                'within_fit_tolerance': bool(max(float(gmesh.max()), gexact) <= fit_tol)}
    swi = dict(sdi)
    swi['poles'] = p0 + sdi['poles'] @ R
    surf_wi = make_surface(swi)
    fit_report['inner_surface'] = {'degree': [sdi['udeg'], sdi['vdeg']], 'poles': [int(sdi['poles'].shape[0]), int(sdi['poles'].shape[1])], 'poles_sha256': poles_hash(sdi),
                                   'crossing': ir['method'], 'crossing_residual_mm': ir['crossing_residual_mm'], 'same_parametrisation_as_outer': True}
    fit_report['poles_inner'] = fit_report['inner_surface']['poles']
    t2 = time.perf_counter()
    try:
        shape, repairs = build_hollow_solid(surf_w, surf_wi, p0, up)
    except BrainError as exc:
        stop(exc.code, exc.message, getattr(exc, 'details', {}) or {})
    except Exception as exc:  # OCCT raises Standard_Failure types
        stop('SMOOTH_FIT_BREP_INVALID', f'Building the hollow solid raised {type(exc).__name__}: {str(exc)[:300]}; no fallback was attempted.', {})
    if shape is None or shape.IsNull():
        stop('SMOOTH_FIT_BREP_INVALID', 'The hollow solid is null.', {})
    t_brep = time.perf_counter() - t2
    topo = ss._topology(shape, p0, nrm)
    if topo['solids'] != 1:
        stop('SMOOTH_FIT_BREP_INVALID', 'The sewn result is not a single solid; no fallback was attempted.', topo)
    # 4. exports
    ss._write_step(shape, d / 'shell_smooth.step')
    step_sha = file_hash(d / 'shell_smooth.step')
    tv, tf = tessellate_shape(shape, 0.02)
    stl_sha = ss._write(d / 'shell_smooth.stl', ss._stl_bytes(tv, tf))
    fit_sha = ss._write(d / 'fit_surface.npz', sm.npz_bytes(poles=sd['poles'], uknots=sd['uknots'], vknots=sd['vknots'], umults=sd['umults'], vmults=sd['vmults'],
                                                           degrees=np.array([sd['udeg'], sd['vdeg']]), world_poles=sw['poles'], frame=R, origin=p0))
    # 5. classify faces
    outer_faces, inner_faces, plane_faces = [], [], []
    for face in faces_of(shape):
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Plane
        ad = BRepAdaptor_Surface(face)
        if ad.GetType() == GeomAbs_Plane:
            plane_faces.append(face)
            continue
        fv, ff = tessellate_face(face, 0.05)
        dm = float(np.median(dist.distance(fv[:: max(1, len(fv) // 400)]))) if len(fv) else None  # median distance of its vertices to the scan: ~0 outer skin, ~t inner skin
        (outer_faces if dm is not None and dm < t / 2.0 else inner_faces).append((face, dm))
    checks: dict[str, Any] = {}
    checks['brep_valid'] = {'status': ss._chk(topo['valid']), **{k: topo[k] for k in ('solids', 'shells', 'faces')}}
    checks['single_closed_solid'] = {'status': ss._chk(topo['solids'] == 1 and topo['shells'] == 1 and topo['shell_closed']), 'shell_closed': topo['shell_closed'], 'solids': topo['solids']}
    v_brep = ss._volume(shape)
    try:
        rt = ss._read_step(d / 'shell_smooth.step')
        if rt.IsNull():
            raise BrainError('STEP_ROUNDTRIP_FAILED', 'Exported STEP read back as a null shape.')
        rt_topo = ss._topology(rt, p0, nrm)
        rt_vol = ss._volume(rt)
        checks['step_roundtrip'] = {'status': ss._chk(rt_topo['valid'] and rt_topo['solids'] == 1 and abs(rt_vol - v_brep) / max(v_brep, 1e-300) <= 1e-6),
                                    'volume_mm3': rt_vol, 'valid': rt_topo['valid'], 'solids': rt_topo['solids']}
    except Exception as exc:
        checks['step_roundtrip'] = {'status': 'FAIL', 'reason': f'{type(exc).__name__}: {str(exc)[:200]}'}
    checks['face_structure'] = {'status': 'PASS' if len(outer_faces) >= 1 and len(inner_faces) >= 1 and plane_faces else 'FAIL', 'faces': topo['faces'],
                                'outer_faces': len(outer_faces), 'inner_faces': len(inner_faces), 'planar_faces': len(plane_faces),
                                'surface_types': sorted({str(BRepAdaptor_Surface(fc).GetType()).split('.')[-1] for fc, _ in outer_faces + inner_faces})}
    # outer deviation, both directions
    rng = np.random.default_rng(20260917)
    bu0, bu1, bv0, bv1 = surf_w.Bounds()
    uv = np.stack([rng.uniform(bu0, bu1, SAMPLES), rng.uniform(bv0, bv1, SAMPLES)], 1)
    ptsf = _eval_surface(surf_w, uv)
    devf = dist.distance(ptsf)
    fwd = _stats(devf, 99)
    fwd['samples'] = SAMPLES
    fwd['worst_point_mm'] = ptsf[int(np.argmax(devf))].tolist()
    fwd['sampling'] = 'uniform in (u, v) on the fitted surface, not area-weighted'
    spts, _ = sm.sample_surface(v, f, SAMPLES)
    above = (spts - p0) @ up >= 0.0
    sp = spts[above]
    dmesh = osd.md.distance(sp)
    exact_max = osd.refined(sp, dmesh, 'max')
    rev = _stats(dmesh, 99)
    rev['max'] = max(float(dmesh.max()), exact_max)
    rev['samples'] = int(len(sp))
    rev['worst_point_mm'] = sp[int(np.argmax(dmesh))].tolist()
    rev['max_basis'] = f'dense {DENSE}x{DENSE} tessellation of the fitted surface; the 60 worst points re-measured by exact orthogonal projection (exact max {exact_max:.6g})'
    ok_dev = fwd['max'] <= outer_tolerance_mm and rev['max'] <= outer_tolerance_mm
    checks['outer_deviation'] = {'status': ss._chk(ok_dev), 'tolerance_mm': outer_tolerance_mm, 'output_to_scan': fwd, 'scan_to_output': rev, 'grid_used': grid,
                                 'code': None if ok_dev else 'SMOOTH_FIT_OUT_OF_TOLERANCE', 'note': 'not loosened and not densified automatically'}
    # wall thickness on the inner faces
    if inner_faces:
        iv_, if_ = [], []
        base = 0
        for fc, _ in inner_faces:
            a, b = tessellate_face(fc, 0.005)
            iv_.append(a)
            if_.append(b + base)
            base += len(a)
        iv_, if_ = np.concatenate(iv_), np.concatenate(if_)
        hin = (iv_ - p0) @ up
        checks['inner_skin_extent'] = {'status': ss._chk(float(hin.min()) >= -1e-3), 'min_height_above_opening_plane_mm': float(hin.min()), 'limit_mm': -1e-3,
                                       'lowest_vertex_mm': iv_[int(np.argmin(hin))].tolist(), 'note': 'the inner skin must not extend below the opening plane'}
        ipts, _ = sm.sample_surface(iv_, if_, SAMPLES)
        w_scan = dist.distance(ipts)
        w_mesh = osd.md.distance(ipts)
        w_exact_min = osd.refined(ipts, w_mesh, 'min')
        w_surf_min = min(float(w_mesh.min()), w_exact_min)
        st = _stats(w_scan, 1)
        st['samples'] = SAMPLES
        st['worst_point_mm'] = ipts[int(np.argmin(w_scan))].tolist()
        floor = t - thickness_tolerance_mm
        checks['wall_thickness'] = {'status': ss._chk(st['min'] >= floor and w_surf_min >= floor), 'target_mm': t, 'tolerance_mm': thickness_tolerance_mm,
                                    'vs_scan': st, 'vs_outer_bspline': {**_stats(w_mesh, 1), 'min': w_surf_min, 'worst_point_mm': ipts[int(np.argmin(w_mesh))].tolist(), 'samples': SAMPLES, 'exact_projection_min_of_60_smallest': w_exact_min},
                                    'note': 'sampled minimum on the inner skin, not a global minimum; inner skin tessellated at 0.005 mm deflection'}
    else:
        checks['wall_thickness'] = {'status': 'FAIL', 'reason': 'no inner faces found'}
        checks['inner_skin_extent'] = {'status': 'FAIL', 'reason': 'no inner faces found'}
    scan_kept = ss._clipped_volume(v, f, p0, nrm)
    cavity = scan_kept - v_brep
    rim_ok = any(c >= 2 for c in topo['opening_plane_faces_wire_counts'])
    checks['opening_present'] = {'status': ss._chk(rim_ok and cavity > 0), 'planar_faces_on_opening_plane_wire_counts': topo['opening_plane_faces_wire_counts'],
                                 'scan_volume_kept_side_mm3': scan_kept, 'shell_volume_mm3': v_brep, 'cavity_volume_mm3': cavity,
                                 }
    checks['fit_knots'] = {'status': ss._chk(maxmult_u < sd['udeg'] and maxmult_v < sd['vdeg']), 'max_interior_multiplicity': {'u': maxmult_u, 'v': maxmult_v},
                           'degree': [sd['udeg'], sd['vdeg']], 'rule': 'no interior knot multiplicity >= degree (per direction)'}
    # surface quality of the outer face
    from .surface_quality import analyze_surface_quality
    from OCP.TopExp import TopExp
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopTools import TopTools_IndexedMapOfShape
    fm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, fm)
    oid = [i for i in range(1, fm.Extent() + 1) if any(fm.FindKey(i).IsSame(fc) for fc, _ in outer_faces)]
    try:
        sq = analyze_surface_quality(SimpleNamespace(wrapped=shape), 'consumer_product', faces=oid)
        sqs = sq['surface_quality_status']
        checks['surface_quality'] = {'status': sqs if sqs in ('PASS', 'FAIL') else 'UNVERIFIED', 'profile': 'consumer_product', 'outer_face_ids': oid,
                                     'result_status': sqs, 'unassessed_checks': sq.get('unassessed_checks'), 'checks': sq.get('checks'), 'counts': sq.get('counts'),
                                     'internal_knot_findings': sq.get('internal_knot_findings'), 'worst_waviness_faces': sq.get('worst_waviness_faces'),
                                     'smallest_radius_faces': sq.get('smallest_radius_faces'),
                                     'faces': [{k: x for k, x in fr.items() if k != 'radius_min_samples'} for fr in sq.get('faces', [])],
                                     'rim_edges': 'the outer-to-opening-plane edges are creases by construction and are reported as such by the analysis, not as smooth G-continuity'}
    except Exception as exc:  # analysis problems are UNVERIFIED, never PASS
        checks['surface_quality'] = {'status': 'UNVERIFIED', 'reason': f'{type(exc).__name__}: {str(exc)[:200]}'}
    checks['self_intersection'] = {'status': prep.get('checks', {}).get('self_intersection', 'UNVERIFIED'),
                                   'note': 'scan self-intersection is not checked by prepare; the result is checked only by BRepCheck'}
    checks['edit_suitability'] = {'status': 'INFO', 'note': 'few smooth faces; fitted B-spline outer surface, fitted B-spline inner surface, planar rim ring; boolean/export ok if checks pass'}
    blocking = ['brep_valid', 'single_closed_solid', 'step_roundtrip', 'face_structure', 'outer_deviation', 'wall_thickness', 'opening_present', 'inner_skin_extent', 'fit_knots', 'surface_quality']
    states = [checks[k]['status'] for k in blocking]
    design = 'PASS' if all(s == 'PASS' for s in states) else ('FAIL' if 'FAIL' in states else 'UNVERIFIED')
    report = {
        'schema': 'scan_shell_build_report/1', 'code_version': {'scan_fit': SCAN_FIT_VERSION, 'package': __version__}, 'route': ROUTE, 'settings': settings,
        'ignored_route_settings': {'voxel_mm': 'unused by smooth_fit', 'max_faces': 'unused by smooth_fit', 'max_voxels': 'unused by smooth_fit'},
        'inputs': {'prepared_npz_sha256': prep['prepared_npz_sha256'], 'source_sha256': prep['source']['sha256'], 'unmeasured_surface_mm2': prep.get('unmeasured_surface_mm2', 0.0)},
        'star_shape': {'status': 'PASS', 'rays': int(grid * grid), 'sampled_on_grid_only': True, 'note': 'every grid ray left the surface exactly once; not proven for rays between grid points'},
        'fit_report': fit_report, 'repairs_applied': repairs,
        'hashes': {'poles_sha256': fit_report['poles_sha256'], 'fit_surface_npz': fit_sha, 'shell_smooth_stl': stl_sha, 'shell_smooth_step': step_sha,
                   'note': 'shell_smooth.step contains a writer timestamp; determinism is defined on poles_sha256'},
        'timing_s': {'rays': t_rays, 'inner_rays': t_inner, 'fit': t_fit, 'brep': t_brep, 'total': time.perf_counter() - t0},
        'brep_faces': topo['faces'], 'checks': checks, 'blocking_checks': blocking, 'unverified_items': [k for k, c in checks.items() if c['status'] == 'UNVERIFIED'],
        'codes': [c['code'] for c in checks.values() if c.get('code')], 'design_status': design, 'execution': {'completed': True},
        'files': ['shell_smooth.step', 'shell_smooth.stl', 'fit_surface.npz', out_name],
    }
    atomic_json(d / out_name, report)
    return report
