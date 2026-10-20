"""Hollow bottom plate with ledge + tongue (brain_mouse_plate_joint). SUBPROCESS WORKER (server python: OCP + numpy + scipy + vtk).

Run as:  <server python> -I mouse_plate_joint_worker.py request.json      (result = last stdout line, JSON)

ADOPTED design (default, owner v20a / official v39): bearing = plate_top, rim only (no tongue), rim measured in plan, floor 1.2, plus the front bearing
pad(s) `pads_mm`.  The ledge + tongue joint (bearing = z0_profile, tongue_height_mm > 0, v20b / v22d) was rejected by the owner: it stays as an EXPERIMENTAL option.

Method (ported to plain OCP from the owner's v20b build, wip/plate_v20b/s8_offlev.py + s9_build.py; the numbers are arguments, see mouse_plate_joint.py):
  1. The outer skin around the plate / shell joint is modelled as a star-shaped radial field r(z, theta) about the plan centre of the plate
     bottom, from horizontal sections of the plate AND the shell (outermost crossing per angle; a vertical gap between the plate top and the shell
     bottom is bridged along z).  A light smoothing spline (rms `smoothing_rms_mm`) is fitted.
  2. Inward offset surfaces at depth d_ledge and d_ledge + tongue width are sampled from that field (true 3D normal, or the horizontal offset for
     ledge_measure = plan), re-cut to constant-z levels and lofted into closed solids O1, O2 (periodic B-spline sections).
  3. Bearing top = flat profile z0(x) (piecewise levels joined by linear ramps of width ramp_factor * |dz|) swept across y (prism H0; the tongue prism
     H1 is the same profile raised by the tongue height), or the plate blank's own top (bearing = plate_top; no tongue).
  4. Hollow plate N = floor (plate blank below floor_mm) + ledge ((plate blank cut by H0) - O1) + tongue ((O1 - O2) cut by H1).  The outer face of the
     ledge is the plate blank's own skin (flush); every Boolean is gated (non-null, valid, expected solid count, mesh-volume bookkeeping).
Checks: one valid solid, STEP round trip, bottom flat on z = 0, floor thickness by vertical rays, common volume with the shell, tongue-to-shell
gap and ledge / tongue heights at the stations, bearing contact areas, offset-model accuracy, mass.  Nothing is moved: the shell and the blank are
only read.
"""
from __future__ import annotations
import math
import sys
from pathlib import Path
from typing import Any

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from cadmcp_brain.studio.scan_cad_common import WorkerError, worker_main
from cadmcp_brain.studio import cad_brep_lib as L
from cadmcp_brain.studio import mouse_parts_lib as P
from cadmcp_brain.studio.mouse_wall_audit_worker import sample_surface

WORKER_VERSION = 'mouse_plate_joint/1'
DEFAULTS = {'wall_mm': 1.3, 'clearance_mm': 0.15, 'ledge_mm': None, 'ledge_measure': 'plan', 'tongue_width_mm': 1.1, 'tongue_height_mm': 0.0,
            'floor_mm': 1.2, 'bearing': 'plate_top', 'pads_mm': [], 'ramp_factor': 2.0, 'z0_rear_mm': None,
            'z0_levels_mm': None,
            'stations_x_mm': None, 'density_g_cm3': 1.04, 'deflection_mm': 0.005, 'check_deflection_mm': 0.01,
            'section_step_mm': 0.25, 'angular_bins': 720, 'wire_points': 240, 'smoothing_rms_mm': 0.003, 'gap_tol_mm': 0.05,
            'common_tol_mm3': 0.01, 'contact_tol_mm': 0.05, 'samples': 120000, 'seed': 0, 'shell_part': None, 'plate_part': None}
EPS = 1e-9
# No model-specific defaults: pads_mm is empty (a pad is an explicit design decision), z0_levels_mm / z0_rear_mm are REQUIRED for bearing = z0_profile (experimental), and
# stations_x_mm default to STATION_COUNT stations spread over STATION_FROM..STATION_TO of the plate x extent.  The mirror plane is the plate bbox mid plane in y
# (also the default y centre of a pad and the side split of the stations).  LH2 verification recipe (explicit arguments): pads_mm [{x_from 103.6, x_to 113.4, half_width_y 8.6,
# y_centre 0}] and stations_x_mm [5, 18, 30, 44, 60, 70, 80, 100] (official v20a / v39); z0_levels_mm [{76, 2.0}, {52, 2.5}, {36, 3.1}, {24, 4.2}, {12, 5.5}] with z0_rear_mm 6.9 (v20b).
STATION_COUNT, STATION_FROM, STATION_TO = 8, 0.05, 0.85


# ------------------------------------------------------------------ bearing profile
def z0_polyline(levels: list[dict[str, float]], rear: float, k: float, x_lo: float, x_hi: float) -> list[tuple[float, float]]:
    """Piecewise-flat z0(x): z0 = level.z0 for x >= level.x_from, `rear` below the smallest x_from; a linear ramp of total width k * |dz| centred on
    every boundary joins the plateaus.  -> polyline [(x, z)] from x_lo to x_hi (z0func.profile_pts of the v20b build)."""
    lv = sorted(levels, key=lambda t: t['x_from'])                      # ascending x
    xs = [float(t['x_from']) for t in lv]
    zs = [float(rear)] + [float(t['z0']) for t in lv]                   # zs[i] for x < xs[i], zs[i+1] for x >= xs[i]
    ramps = [(b - k * abs(zs[i + 1] - zs[i]) / 2.0, b + k * abs(zs[i + 1] - zs[i]) / 2.0) for i, b in enumerate(xs)]
    edges = [x_lo] + [v for i, r in enumerate(ramps) if zs[i] != zs[i + 1] for v in r] + [x_hi]       # equal neighbours: no step, no ramp
    if any(edges[i] >= edges[i + 1] for i in range(len(edges) - 1)):
        raise WorkerError('PLATE_JOINT_PROFILE', 'z0 steps are too close together for their ramps (ramp width = ramp_factor * |dz|) or outside the plate x range.',
                          {'x_from': xs, 'ramps': ramps})
    pts = [(x_lo, zs[0])]
    for i, (r0, r1) in enumerate(ramps):
        if zs[i] != zs[i + 1]:
            pts += [(r0, zs[i]), (r1, zs[i + 1])]
    pts.append((x_hi, zs[-1]))
    return pts


def z0_at(poly: list[tuple[float, float]], x) -> np.ndarray:
    a = np.asarray(poly, float)
    return np.interp(np.asarray(x, float), a[:, 0], a[:, 1])


# ------------------------------------------------------------------ mesh helpers
def tri_volume(V: np.ndarray, T: np.ndarray) -> float:
    return abs(P.mesh_volume(V, T))


def shape_mesh(shape, defl: float) -> tuple[np.ndarray, np.ndarray]:
    return P.mesh(shape, defl, 0.1)


def mesh_vol(shape, defl: float) -> float:
    V, T = shape_mesh(shape, defl)
    return tri_volume(V, T)


def plane_points(V: np.ndarray, T: np.ndarray, z: float, step: float) -> np.ndarray:
    """Points (n, 2) of the section of a triangle mesh with the plane Z = z, each segment subdivided to <= step."""
    s = V[T][:, :, 2] - z
    s = np.where(np.abs(s) < 1e-10, 1e-10, s)
    mixed = (s.min(axis=1) < 0) & (s.max(axis=1) > 0)
    if not mixed.any():
        return np.zeros((0, 2))
    TT, ss = T[mixed], s[mixed]
    P3 = V[TT]
    pa, pb = [], []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        cross = ss[:, i] * ss[:, j] < 0
        t = ss[cross, i] / (ss[cross, i] - ss[cross, j])
        pa.append((np.where(cross)[0], P3[cross, i, :2] + t[:, None] * (P3[cross, j, :2] - P3[cross, i, :2])))
    idx = np.concatenate([a for a, _ in pa])
    pts = np.vstack([p for _, p in pa])
    o = np.argsort(idx, kind='stable')
    idx, pts = idx[o], pts[o]
    first = np.r_[True, idx[1:] != idx[:-1]]
    k = np.flatnonzero(first)
    if len(pts) != 2 * len(k) or not np.all(np.diff(np.r_[k, len(pts)]) == 2):
        return pts
    p, q = pts[k], pts[k + 1]
    n = np.maximum(1, np.ceil(np.linalg.norm(q - p, axis=1) / step).astype(int))
    rep = np.repeat(np.arange(len(p)), n)
    u = (np.arange(len(rep)) - np.repeat(np.cumsum(n) - n, n) + 0.5) / n[rep]
    return p[rep] + u[:, None] * (q[rep] - p[rep])


def outer_radius(sections: list[np.ndarray], c: np.ndarray, angs: np.ndarray, nbin: int) -> np.ndarray:
    """Outermost radius per target angle from the section points of several meshes; NaN where no outline reaches that angle (coverage gap)."""
    pts = np.vstack([s for s in sections if len(s)]) if any(len(s) for s in sections) else np.zeros((0, 2))
    out = np.full(len(angs), np.nan)
    if not len(pts):
        return out
    d = pts - c
    th = np.arctan2(d[:, 1], d[:, 0]) % (2 * np.pi)
    r = np.hypot(d[:, 0], d[:, 1])
    b = np.minimum((th / (2 * np.pi) * nbin).astype(int), nbin - 1)
    best = np.full(nbin, -1.0)
    np.maximum.at(best, b, r)
    sel = np.flatnonzero(r >= best[b] - 1e-12)
    # one point per bin: the first of the maxima
    _, u = np.unique(b[sel], return_index=True)
    sel = sel[u]
    ths, rs = th[sel], r[sel]
    o = np.argsort(ths)
    ths, rs = ths[o], rs[o]
    tw = np.r_[ths[-3:] - 2 * np.pi, ths, ths[:3] + 2 * np.pi]
    rw = np.r_[rs[-3:], rs, rs[:3]]
    val = np.interp(angs, tw, rw)
    j = np.searchsorted(tw, angs)
    left, right = tw[np.clip(j - 1, 0, len(tw) - 1)], tw[np.clip(j, 0, len(tw) - 1)]
    ok = ((angs - left) <= 1.6 * 2 * np.pi / nbin) & ((right - angs) <= 1.6 * 2 * np.pi / nbin)
    out[ok] = val[ok]
    return out


# ------------------------------------------------------------------ radial skin model and offsets
class SkinModel:
    """r(z, theta) about the centre c: smoothing bicubic spline of the outermost section radius (theta periodic by padding)."""

    def __init__(self, zs: np.ndarray, angs: np.ndarray, R: np.ndarray, c: np.ndarray, rms: float):
        from scipy.interpolate import RectBivariateSpline
        self.c = c
        self.fold_columns, self.fold_max_loop_mm = 0, 0.0
        pad = 16
        thp = np.r_[angs[-pad:] - 2 * np.pi, angs, angs[:pad] + 2 * np.pi]
        Rp = np.hstack([R[:, -pad:], R, R[:, :pad]])
        self.zlo, self.zhi = float(zs[0]), float(zs[-1])
        self.spl = RectBivariateSpline(zs, thp, Rp, kx=3, ky=3, s=Rp.size * rms * rms)

    def r(self, z, t, dz=0, dt=0):
        return self.spl(z, t, dx=dz, dy=dt, grid=False)

    def offset_levels(self, d: float, measure: str, zlev: np.ndarray, na: int, nc: int = 720) -> np.ndarray:
        """Outline of the inward offset surface (depth d) on the levels zlev -> points (len(zlev), na, 2) in x, y; columns keep the angular order."""
        tc = np.linspace(0, 2 * np.pi, nc, endpoint=False)
        zz = np.arange(self.zlo - (d + 0.5), self.zhi + 1e-9, 0.04)             # below the lowest section: straight continuation of the skin (tangent at the bottom)
        T, Z = np.meshgrid(tc, zz)
        Zc = np.maximum(Z, self.zlo)
        R, Rt, Rz = self.r(Zc, T), self.r(Zc, T, 0, 1), self.r(Zc, T, 1, 0)
        R = R + Rz * (Z - Zc)
        c, s = np.cos(T), np.sin(T)
        Pt = np.stack([Rt * c - R * s, Rt * s + R * c, np.zeros_like(R)], -1)
        Pz = np.stack([Rz * c, Rz * s, np.ones_like(R)], -1)
        n = np.cross(Pt, Pz)
        n /= np.linalg.norm(n, axis=-1, keepdims=True)
        rad = np.stack([c, s, np.zeros_like(c)], -1)
        n = n * np.sign(np.sum(n * rad, -1, keepdims=True))                      # outward
        n_in = -n
        if measure == 'plan':
            h = n_in.copy()
            h[..., 2] = 0.0
            h /= np.maximum(np.linalg.norm(h, axis=-1, keepdims=True), 1e-9)
            n_in = h
        Q = np.stack([self.c[0] + R * c, self.c[1] + R * s, Z], -1) + d * n_in
        out = np.empty((len(zlev), nc, 2))
        for k in range(nc):
            qz = Q[:, k, 2]
            keep = qz > np.maximum.accumulate(np.r_[-np.inf, qz[:-1]])    # a tight fold (offset deeper than the local radius) is trimmed to its outer envelope
            if not keep.all():
                self.fold_columns += 1
                self.fold_max_loop_mm = max(self.fold_max_loop_mm, float((np.maximum.accumulate(qz) - qz).max()))
            qz, Qk = qz[keep], Q[keep, k]
            if zlev[0] < qz[0] or zlev[-1] > qz[-1]:
                raise WorkerError('PLATE_JOINT_RANGE', 'The skin model does not reach the offset levels; sections of the shell are missing at that height.',
                                  {'z_levels': [float(zlev[0]), float(zlev[-1])], 'model_z': [float(qz[0]), float(qz[-1])], 'depth_mm': d})
            out[:, k, 0] = np.interp(zlev, qz, Qk[:, 0])
            out[:, k, 1] = np.interp(zlev, qz, Qk[:, 1])
        step = nc // na
        return out[:, ::step][:, :na]


# ------------------------------------------------------------------ OCP construction
def loft_solid(levels: np.ndarray, pts: np.ndarray):
    """Closed solid lofted through periodic B-spline outlines (pts (nz, na, 2)) at the heights `levels`."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    ts = BRepOffsetAPI_ThruSections(True, False, 1e-6)
    ts.SetSmoothing(False)
    ts.CheckCompatibility(False)
    na = pts.shape[1]
    prm = np.arange(na) / na
    for z, xy in zip(levels, pts):
        P3 = np.column_stack([xy, np.full(len(xy), z)])
        w = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(L.interp_closed(P3, prm)).Edge()).Wire()
        ts.AddWire(w)
    ts.Build()
    if not ts.IsDone():
        raise WorkerError('PLATE_JOINT_LOFT', 'Lofting the offset outlines failed.')
    ss = L.solids(ts.Shape())
    if len(ss) != 1:
        raise WorkerError('PLATE_JOINT_LOFT', 'The loft is not one solid.', {'solids': len(ss)})
    s = ss[0]
    if L.volume(s) < 0:
        s = s.Reversed()
    return s


def make_box(x0, y0, z0, x1, y1, z1):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    return L.solids(BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape())[0]


def profile_prism(poly: list[tuple[float, float]], dz: float, ylo: float, yhi: float, zbot: float):
    """Region under the profile (z <= z0(x) + dz), z >= zbot, y in [ylo, yhi]."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Pnt, gp_Vec
    pts = [(x, z + dz) for x, z in poly] + [(poly[-1][0], zbot), (poly[0][0], zbot)]
    mp = BRepBuilderAPI_MakePolygon()
    for x, z in pts:
        mp.Add(gp_Pnt(float(x), float(ylo), float(z)))
    mp.Close()
    f = BRepBuilderAPI_MakeFace(mp.Wire(), True).Face()
    ss = L.solids(BRepPrimAPI_MakePrism(f, gp_Vec(0, float(yhi - ylo), 0)).Shape())
    if len(ss) != 1:
        raise WorkerError('PLATE_JOINT_PRISM', 'The profile prism is not one solid.')
    return ss[0]


def boolean(kind: str, a, b, what: str, vol_tol: float, defl: float):
    """Gated Boolean: non-null, no errors, only solids with volume > 0 kept; returns (result shape, its solids, mesh volume)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    cls = {'cut': BRepAlgoAPI_Cut, 'common': BRepAlgoAPI_Common, 'fuse': BRepAlgoAPI_Fuse}[kind]
    op = cls(a, b)
    if not op.IsDone():
        raise WorkerError('PLATE_JOINT_BOOLEAN', f'Boolean {kind} failed: {what}.', {'step': what})
    r = op.Shape()
    if r.IsNull():
        raise WorkerError('PLATE_JOINT_BOOLEAN', f'Boolean {kind} returned a null shape: {what}.', {'step': what})
    ss = [s for s in L.solids(r) if abs(L.volume(s)) > 1e-6]
    if not ss:
        raise WorkerError('PLATE_JOINT_BOOLEAN', f'Boolean {kind} returned no solid: {what}.', {'step': what})
    shape = ss[0] if len(ss) == 1 else L.compound(ss)
    return shape, ss, mesh_vol(shape, defl)


def unify(shape, defl: float):
    """Merge coplanar / same-surface faces; kept only when valid and the mesh volume does not move."""
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    try:
        u = ShapeUpgrade_UnifySameDomain(shape, True, True, True)
        u.Build()
        r = u.Shape()
        ss = L.solids(r)
        if len(ss) == 1 and L.is_valid(ss[0]) and abs(mesh_vol(ss[0], defl) - mesh_vol(shape, defl)) < 0.05:
            return ss[0]
    except Exception:  # noqa: BLE001 - cleaning is optional
        pass
    return shape


# ------------------------------------------------------------------ evidence helpers
def locator(V: np.ndarray, T: np.ndarray):
    import vtk
    loc = vtk.vtkStaticCellLocator()
    loc.SetDataSet(P.polydata(V, T))
    loc.BuildLocator()
    return loc


def distances(loc, pts: np.ndarray) -> np.ndarray:
    import vtk
    out = np.empty(len(pts))
    cp, cid, sid, d2 = [0.0] * 3, vtk.mutable(0), vtk.mutable(0), vtk.mutable(0.0)
    for i, p in enumerate(pts):
        loc.FindClosestPoint(p, cp, cid, sid, d2)
        out[i] = math.sqrt(d2.get())
    return out


def vertical_hits(V: np.ndarray, T: np.ndarray, xy: np.ndarray, z0: float, z1: float) -> list[np.ndarray]:
    import vtk
    tree = vtk.vtkOBBTree()
    tree.SetDataSet(P.polydata(V, T))
    tree.SetTolerance(1e-7)
    tree.BuildLocator()
    hit = vtk.vtkPoints()
    out = []
    for x, y in xy:
        hit.Reset()
        zs = []
        if tree.IntersectWithLine((x, y, z0), (x, y, z1), hit, None) != 0:
            zs = sorted(hit.GetPoint(k)[2] for k in range(hit.GetNumberOfPoints()))
        out.append(np.array(zs))
    return out


def clusters(z: np.ndarray, w: np.ndarray, tol: float = 0.03, min_w: float = 0.0) -> list[tuple[float, float]]:
    """Plateau heights: [(z, weight)] highest first (weights = sample areas)."""
    if not len(z):
        return []
    o = np.argsort(z)
    z, w = z[o], w[o]
    brk = np.flatnonzero(np.diff(z) > tol)
    out = []
    for g in np.split(np.arange(len(z)), brk + 1):
        if w[g].sum() >= min_w:
            out.append((float(np.average(z[g], weights=w[g])), float(w[g].sum())))
    return sorted(out, key=lambda t: -t[0])


# ------------------------------------------------------------------ main
def pick(parts: dict[str, Any], name: str | None, what: str):
    if name is None:
        if len(parts) != 1:
            raise WorkerError('PLATE_JOINT_PART', f'The {what} STEP holds several parts; name one with {what}_part.', {'parts': sorted(parts)})
        name = next(iter(parts))
    P.require(parts, [name], f'{what}_part')
    ss = L.solids(parts[name])
    if len(ss) != 1:
        raise WorkerError('PLATE_JOINT_PART', f'The {what} part must be exactly one solid.', {'part': name, 'solids': len(ss)})
    return name, ss[0]


def run(req: dict[str, Any]) -> dict[str, Any]:
    import time
    t0 = time.time()
    L.require_ocp()
    prm = {**DEFAULTS, **{k: v for k, v in req['params'].items() if k in DEFAULTS}}
    out = Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    wall, tw, th, floor = float(prm['wall_mm']), float(prm['tongue_width_mm']), float(prm['tongue_height_mm']), float(prm['floor_mm'])
    measure, bearing = prm['ledge_measure'], prm['bearing']
    ledge = float(prm['ledge_mm']) if prm['ledge_mm'] is not None else wall + float(prm['clearance_mm'])
    clearance = ledge - wall if measure == 'normal' else None
    defl, cdefl = float(prm['deflection_mm']), float(prm['check_deflection_mm'])
    if bearing == 'plate_top' and th > 0:
        raise WorkerError('PLATE_JOINT_SETTINGS', 'bearing = plate_top has no profile to raise a tongue from: set tongue_height_mm = 0 (a rim without tongue) '
                                                  'or use bearing = z0_profile.')
    if th > 0 and prm['pads_mm']:
        raise WorkerError('PLATE_JOINT_SETTINGS', 'Bearing pads are only built for the rim-only plate (tongue_height_mm = 0); pass pads_mm = [] with the experimental tongue.')
    if th > 0 and measure != 'normal':
        raise WorkerError('PLATE_JOINT_SETTINGS', 'The tongue clearance is defined normal to the skin: use ledge_measure = normal with a tongue.')
    sh_parts, _ = P.load_parts([req['inputs']['shell']])
    pl_parts, _ = P.load_parts([req['inputs']['plate']])
    shell_name, shell = pick(sh_parts, prm['shell_part'], 'shell')
    plate_name, plate = pick(pl_parts, prm['plate_part'], 'plate')
    for nm, s in (('shell', shell), ('plate', plate)):
        if not L.is_valid(s):
            raise WorkerError('PLATE_JOINT_INPUT', f'The {nm} solid is not valid.')
    bb = L.bbox(plate)
    xlo, ylo, zlo_p, xhi, yhi, zhi_p = [float(v) for v in bb]
    if bearing == 'z0_profile' and (prm['z0_levels_mm'] is None or prm['z0_rear_mm'] is None):
        raise WorkerError('PLATE_JOINT_Z0_REQUIRED', 'bearing = z0_profile needs z0_levels_mm and z0_rear_mm (no model-specific default): the bearing height profile z0(x) of this mouse.')
    stations_x = [float(v) for v in prm['stations_x_mm']] if prm['stations_x_mm'] is not None else [round(float(v), 3) for v in np.linspace(xlo + STATION_FROM * (xhi - xlo), xlo + STATION_TO * (xhi - xlo), STATION_COUNT)]
    if abs(zlo_p) > 1e-3:
        raise WorkerError('PLATE_JOINT_INPUT', 'The plate bottom must lie on z = 0 (flat bottom); move it with the flush / assembly tools first.', {'min_z': zlo_p})
    c = np.array([(xlo + xhi) / 2.0, (ylo + yhi) / 2.0])
    levels = prm['z0_levels_mm']
    poly = z0_polyline(levels, float(prm['z0_rear_mm']) if bearing == 'z0_profile' else 0.0, float(prm['ramp_factor']), xlo - 6.0, xhi + 6.0) if bearing == 'z0_profile' else []     # no profile with plate_top
    zcap = (max(z for _, z in poly) + th) if bearing == 'z0_profile' else zhi_p
    notes: list[str] = []

    # ---- 1. skin model from sections of the plate and the shell
    Vp, Tp = shape_mesh(plate, defl)
    Vs, Ts = shape_mesh(shell, defl)
    vol_plate_mesh = tri_volume(Vp, Tp)
    na_bins = int(prm['angular_bins'])
    angs = np.linspace(0, 2 * np.pi, na_bins, endpoint=False)
    z_top_sample = zcap + 0.6 + ledge + (tw if th > 0 else 0.0) + 0.5      # offset points move up by at most the depth
    zs = np.arange(0.02, z_top_sample, float(prm['section_step_mm']))
    R = np.full((len(zs), na_bins), np.nan)
    src = np.zeros((len(zs), 2), dtype=int)                       # points used from (plate, shell)
    skin_step = 0.1
    for i, z in enumerate(zs):
        sp, ss_ = plane_points(Vp, Tp, z, skin_step), plane_points(Vs, Ts, z, skin_step)
        src[i] = (len(sp), len(ss_))
        R[i] = outer_radius([sp, ss_], c, angs, na_bins)
    ok_all = np.isfinite(R)
    if not ok_all[0].all():
        raise WorkerError('PLATE_JOINT_SKIN', 'The plate section at the bottom does not cover every direction (not star-shaped about its plan centre?).',
                          {'angle_deg': [float(np.degrees(angs[k])) for k in np.flatnonzero(~ok_all[0])[:5]]})
    last = np.array([np.flatnonzero(ok_all[:, k])[-1] for k in range(na_bins)])
    n_cover = int(last.min()) + 1                                 # levels with the skin present in every direction (the shell may lack its front above some height)
    zs, R, src = zs[:n_cover], R[:n_cover], src[:n_cover]
    z_cover = float(zs[-1])
    for k in range(na_bins):                                      # bridge vertical coverage gaps (plate top below shell bottom)
        col, ok = R[:, k], np.isfinite(R[:, k])
        if not ok.all():
            col[~ok] = np.interp(zs[~ok], zs[ok], col[ok])
    bridged = int(np.isnan(R).sum())
    model = SkinModel(zs, angs, R, c, float(prm['smoothing_rms_mm']))
    # star-shapedness: polygon area of the sampled outline vs the plate outline area at z = 0.5 (mesh section area by shoelace on the polar polygon)
    ring = np.stack([R[len(zs) // 3] * np.cos(angs), R[len(zs) // 3] * np.sin(angs)], 1)
    star_area = 0.5 * abs(np.sum(ring[:, 0] * np.roll(ring[:, 1], -1) - np.roll(ring[:, 0], -1) * ring[:, 1]))

    # ---- 2. offset lofts
    zl0 = max(0.6, floor - 0.6)
    zl1 = zcap + 0.6
    zlev = np.arange(zl0, zl1 + 1e-9, 0.5)
    na = int(prm['wire_points'])
    solids_o: dict[str, Any] = {}
    skin_dev: dict[str, Any] = {}
    depths = {'O1': ledge} | ({'O2': ledge + tw} if th > 0 else {})
    for name, d in depths.items():
        pts = model.offset_levels(d, measure, zlev, na)
        solids_o[name] = loft_solid(zlev, pts)
        if not L.is_valid(solids_o[name]):
            raise WorkerError('PLATE_JOINT_LOFT', f'The offset loft {name} is not valid.')
    # ---- 3. profile prisms
    ypad = max(abs(ylo), abs(yhi)) + 5.0
    zbot = -2.0
    box_floor = make_box(xlo - 5, -ypad, zbot, xhi + 5, ypad, floor)
    H0 = profile_prism(poly, 0.0, -ypad, ypad, zbot) if bearing == 'z0_profile' else None
    H1 = profile_prism(poly, th, -ypad, ypad, zbot) if (bearing == 'z0_profile' and th > 0) else None

    # ---- 4. boolean build with bookkeeping
    vt = lambda v: max(1.0, 2e-4 * v)  # noqa: E731
    book: list[dict[str, Any]] = []
    floor_part, _, v_floor = boolean('common', plate, box_floor, 'floor = plate blank below floor_mm', 1.0, defl)
    A, v_A = plate, vol_plate_mesh
    if H0 is not None:
        A, _, v_A = boolean('common', plate, H0, 'blank under the bearing profile', 1.0, defl)
    O1 = solids_o['O1']
    ledge_s, _, v_led = boolean('cut', A, O1, 'ledge = blank under the profile minus the inner offset O1', 1.0, defl)
    _, _, v_ac = boolean('common', A, O1, 'bookkeeping: blank under the profile inside O1', 1.0, defl)
    book.append({'step': 'ledge', 'cut_mm3': round(v_led, 3), 'inside_mm3': round(v_ac, 3), 'whole_mm3': round(v_A, 3), 'residual_mm3': round(v_led + v_ac - v_A, 3)})
    parts_n = [floor_part, ledge_s]
    v_parts = [v_floor, v_led]
    tongue_s = None
    if th > 0:
        O2 = solids_o['O2']
        band, _, v_band = boolean('cut', O1, O2, 'tongue band O1 - O2', 1.0, defl)
        # keep the tongue from just below the floor top upward so it overlaps the floor volume (never face to face)
        above = make_box(xlo - 5, -ypad, floor - 0.2, xhi + 5, ypad, zcap + 5)
        band_a, _, _ = boolean('common', band, above, 'tongue band above the floor', 1.0, defl)
        tongue_s, _, v_t = boolean('common', band_a, H1, 'tongue = band under the raised profile', 1.0, defl)
        parts_n.append(tongue_s)
        v_parts.append(v_t)
    pad_info: list[dict[str, Any]] = []
    N, _, v_N = parts_n[0], None, v_floor
    if th == 0:
        # rim-only plate: N = blank minus the cavity C = (O1 above the floor) minus the pad rectangles; one Cut, no fuse of coincident skin faces
        above = make_box(xlo - 5, -ypad, floor, xhi + 5, ypad, zcap + 5)
        C, _, v_C = boolean('common', O1, above, 'cavity = inner offset O1 above the floor', 1.0, defl)
        for i_pad, pd in enumerate(prm['pads_mm'] or []):
            yc = float(pd['y_centre']) if pd.get('y_centre') is not None else float(c[1])
            bx = make_box(float(pd['x_from']), yc - float(pd['half_width_y']), zbot, float(pd['x_to']), yc + float(pd['half_width_y']), zcap + 5.0)
            _, _, v_pad = boolean('common', plate, bx, f'bearing pad {i_pad}: blank inside the pad rectangle (must not be empty)', 1.0, defl)
            C, _, v_C = boolean('cut', C, bx, f'cavity minus pad rectangle {i_pad}', 1.0, defl)
            pad_info.append({'x_from': float(pd['x_from']), 'x_to': float(pd['x_to']), 'half_width_y': float(pd['half_width_y']), 'y_centre': yc, 'blank_volume_mm3': round(v_pad, 3)})
        _, _, v_AC = boolean_or_zero(A, C, defl)
        N, ss, v_N = boolean('cut', A, C, 'hollow plate = blank minus cavity', 1.0, defl)
        expect = v_A - v_AC
        book.append({'step': 'hollow', 'volume_mm3': round(v_N, 3), 'expected_mm3': round(expect, 3), 'residual_mm3': round(v_N - expect, 3), 'cavity_mm3': round(v_C, 3)})
        if len(ss) != 1 or abs(v_N - expect) > vt(v_N):
            raise WorkerError('PLATE_JOINT_BOOKKEEPING', 'The cavity cut did not give one solid with the expected volume (silent Boolean failure).',
                              {'solids': len(ss), 'volume': v_N, 'expected': expect})
        parts_n = [N]
    for k, p in enumerate(parts_n[1:], start=1):
        _, _, v_c = boolean('common', N, p, f'bookkeeping: overlap of part {k}', 1.0, defl)
        N, ss, v_new = boolean('fuse', N, p, f'fuse part {k} into the plate', 1.0, defl)
        expect = v_N + v_parts[k] - v_c
        book.append({'step': f'fuse_{k}', 'volume_mm3': round(v_new, 3), 'expected_mm3': round(expect, 3), 'residual_mm3': round(v_new - expect, 3)})
        if len(ss) != 1 or abs(v_new - expect) > vt(v_new):
            raise WorkerError('PLATE_JOINT_BOOKKEEPING', 'A fuse did not give one solid with the expected volume (silent Boolean failure).',
                              {'step': k, 'solids': len(ss), 'volume': v_new, 'expected': expect})
        v_N = v_new
    N = unify(N if len(L.solids(N)) != 1 else L.solids(N)[0], defl)
    if len(L.solids(N)) != 1 or not L.is_valid(L.solids(N)[0]):
        raise WorkerError('PLATE_JOINT_INVALID', 'The hollow plate is not one valid solid.', {'solids': len(L.solids(N))})
    N = L.solids(N)[0]
    step_path = out / 'hollow_plate.step'
    L.write_step(N, step_path)
    back = L.solids(L.read_step(step_path))
    vN, TN = shape_mesh(N, cdefl)
    vol_mesh = tri_volume(vN, TN)
    rt_vol = mesh_vol(back[0], cdefl) if len(back) == 1 else None
    checks: dict[str, Any] = {}
    checks['one_valid_solid'] = {'status': 'PASS', 'solids': 1, 'valid': True, 'faces': len(L.faces(N))}
    checks['step_roundtrip'] = {'status': 'PASS' if (len(back) == 1 and L.is_valid(back[0]) and abs(rt_vol - vol_mesh) < max(0.5, 5e-4 * vol_mesh)) else 'FAIL',
                                'solids': len(back), 'valid': bool(back and L.is_valid(back[0])), 'volume_mm3': rt_vol, 'delta_mm3': None if rt_vol is None else round(rt_vol - vol_mesh, 4)}
    bbn = [float(v) for v in L.bbox(N)]
    # bottom flat on z = 0
    fn = vN[TN]
    nrm = np.cross(fn[:, 1] - fn[:, 0], fn[:, 2] - fn[:, 0])
    ar = 0.5 * np.linalg.norm(nrm, axis=1)
    nz = nrm[:, 2] / np.maximum(2 * ar, 1e-18)
    on0 = (np.abs(fn[:, :, 2]).max(axis=1) < 1e-4) & (nz < -0.99)
    fp = Vp[Tp]
    nrp = np.cross(fp[:, 1] - fp[:, 0], fp[:, 2] - fp[:, 0])
    arp = 0.5 * np.linalg.norm(nrp, axis=1)
    onp = (np.abs(fp[:, :, 2]).max(axis=1) < 1e-4) & (nrp[:, 2] / np.maximum(2 * arp, 1e-18) < -0.99)
    bot_area, bot_in = float(ar[on0].sum()), float(arp[onp].sum())
    checks['bottom_flat_z0'] = {'status': 'PASS' if abs(float(vN[:, 2].min())) < 1e-4 and bot_area >= 0.999 * bot_in else 'FAIL', 'min_z_mm': round(float(vN[:, 2].min()), 6), 'flat_area_mm2': round(bot_area, 3),
                                'input_flat_area_mm2': round(bot_in, 3)}
    # floor thickness by vertical rays through the cavity
    gx, gy = np.meshgrid(np.arange(xlo + 1.0, xhi, 2.0), np.arange(ylo + 1.0, yhi, 2.0))
    xy = np.column_stack([gx.ravel(), gy.ravel()])
    hits = vertical_hits(vN, TN, xy, -1.0, zcap + 5.0)
    ft = []
    hits_blank = vertical_hits(Vp, Tp, xy, -1.0, zcap + 5.0)
    for h, hb in zip(hits, hits_blank):
        h, hb = h[h > -0.5], hb[hb > -0.5]
        if not len(hb) or hb.max() < floor + 0.5:                         # outside the blank or on its sloped outer edge: not a floor ray
            continue
        if len(h) == 2 and h[0] < 1e-3 and h[1] < floor + 0.5:           # enters at the bottom plane, leaves at the cavity floor
            ft.append(h[1] - h[0])
    ft = np.array(ft)
    if len(ft) >= 20:
        checks['floor_thickness'] = {'status': 'PASS' if abs(float(np.median(ft)) - floor) < 0.005 and ft.min() > floor - 0.01 else 'FAIL', 'target_mm': floor,
                                     'min_mm': round(float(ft.min()), 4), 'median_mm': round(float(np.median(ft)), 4), 'max_mm': round(float(ft.max()), 4), 'rays': int(len(ft))}
    else:
        checks['floor_thickness'] = {'status': 'FAIL', 'target_mm': floor, 'rays': int(len(ft)), 'note': 'too few cavity rays: no hollow found'}
    if pad_info:
        for pi in pad_info:
            xs_ = np.linspace(pi['x_from'] + 0.5, pi['x_to'] - 0.5, 5)
            ys_ = np.linspace(pi['y_centre'] - pi['half_width_y'] + 0.5, pi['y_centre'] + pi['half_width_y'] - 0.5, 5)
            hh = vertical_hits(vN, TN, np.array([[x, y] for x in xs_ for y in ys_]), -1.0, zcap + 5.0)
            tops = [float(h[h > -0.5].max()) for h in hh if (h > -0.5).any()]
            pi['top_z_min'], pi['top_z_max'], pi['top_samples'] = (round(min(tops), 3), round(max(tops), 3), len(tops)) if tops else (None, None, 0)
        bad = [pi for pi in pad_info if pi['top_samples'] < 20 or pi['top_z_min'] <= floor + 0.05]
        checks['bearing_pads'] = {'status': 'FAIL' if bad else 'PASS', 'pads': pad_info,
                                  'note': 'pad = plate blank inside the stated rectangle; top = blank top (rim bearing face); must stand above the floor'}
    # common volume with the shell
    _, _, v_common = boolean_or_zero(N, shell, cdefl)
    checks['common_with_shell'] = {'status': 'PASS' if v_common <= float(prm['common_tol_mm3']) else 'FAIL', 'common_mm3': round(v_common, 4), 'tol_mm3': float(prm['common_tol_mm3'])}

    # ---- evidence on surface samples
    pts_s, nrm_s = sample_surface(vN, TN, int(prm['samples']), int(prm['seed']))
    shell_loc = locator(*shape_mesh(shell, cdefl))
    z0_samp = z0_at(poly, pts_s[:, 0]) if bearing == 'z0_profile' else None
    stations: list[dict[str, Any]] = []
    gap_min_all: list[float] = []
    for xs_ in stations_x:
        for side in (-1, 1):
            slab = (np.abs(pts_s[:, 0] - xs_) <= 0.6) & (side * (pts_s[:, 1] - c[1]) > 0)
            row: dict[str, Any] = {'x': float(xs_), 'side': 'low_y' if side < 0 else 'high_y'}
            up = slab & (nrm_s[:, 2] > 0.9) & (pts_s[:, 2] > floor + 0.3)
            cl = clusters(pts_s[up, 2], np.ones(int(up.sum())), 0.03, 6.0) if up.any() else []
            if bearing == 'z0_profile':
                zx = float(z0_at(poly, xs_))
                row['z0_expected'] = round(zx, 4)
                row['ledge_top_z'] = next((round(z, 4) for z, _ in cl if abs(z - zx) < 0.1), None)
                row['highest_plateau_below_z0'] = next((round(z, 4) for z, _ in cl if z < zx - 0.1), None) if row['ledge_top_z'] is None else None
                if th > 0:
                    row['tongue_top_expected_z'] = round(zx + th, 4)
                    row['tongue_top_z'] = next((round(z, 4) for z, _ in cl if abs(z - (zx + th)) < 0.1), None)
                    sel = slab & (pts_s[:, 2] > zx + 0.15) & (pts_s[:, 2] < zx + th - 0.15)
                    if sel.sum() >= 5:
                        d = distances(shell_loc, pts_s[sel])
                        row['tongue_to_shell_min_mm'] = round(float(d.min()), 4)
                        row['tongue_to_shell_p50_mm'] = round(float(np.median(d)), 4)
                        gap_min_all.append(float(d.min()))
                    else:
                        row['tongue_to_shell_min_mm'] = None
            else:
                row['rim_top_z'] = round(cl[0][0], 4) if cl else None
            stations.append(row)
    if th > 0:
        gaps = [r['tongue_to_shell_min_mm'] for r in stations if r.get('tongue_to_shell_min_mm') is not None]
        tol = float(prm['gap_tol_mm'])
        if not gaps:
            checks['tongue_gap_at_stations'] = {'status': 'UNVERIFIED', 'note': 'no tongue samples at the stations'}
        else:
            bad = [r for r in stations if r.get('tongue_to_shell_min_mm') is not None and abs(r['tongue_to_shell_min_mm'] - clearance) > tol]
            checks['tongue_gap_at_stations'] = {'status': 'PASS' if not bad and len(gaps) == len(stations) else 'FAIL', 'expected_mm': round(clearance, 4), 'tol_mm': tol,
                                                'min_mm': round(min(gaps), 4), 'max_mm': round(max(gaps), 4), 'stations_measured': len(gaps), 'stations': len(stations),
                                                'outside_tolerance': [{'x': r['x'], 'side': r['side'], 'gap_mm': r['tongue_to_shell_min_mm']} for r in bad]}
    # bearing contact: up-facing ledge / rim top
    topz = pts_s[:, 2]
    sel = (nrm_s[:, 2] > 0.5) & (topz > floor + 0.3)
    if th > 0 and z0_samp is not None:
        sel &= topz < z0_samp + 0.3                                     # the ledge top and its ramps (not the tongue top)
    area_per = float(0.5 * np.linalg.norm(np.cross(vN[TN][:, 1] - vN[TN][:, 0], vN[TN][:, 2] - vN[TN][:, 0]), axis=1).sum()) / len(pts_s)
    if sel.any():
        d = distances(shell_loc, pts_s[sel])
        ct = float(prm['contact_tol_mm'])
        checks['bearing_contact'] = {'status': 'INFO', 'bearing_face_area_mm2': round(float(sel.sum()) * area_per, 2), 'contact_tol_mm': ct,
                                     'contact_area_mm2': round(float((d <= ct).sum()) * area_per, 2), 'within_0p3mm_area_mm2': round(float((d <= 0.3).sum()) * area_per, 2),
                                     'distance_p50_mm': round(float(np.median(d)), 4), 'distance_max_mm': round(float(d.max()), 4), 'samples': int(sel.sum())}
    else:
        checks['bearing_contact'] = {'status': 'UNVERIFIED', 'note': 'no up-facing bearing samples'}
    if bearing == 'z0_profile':
        deficits = [round(r['z0_expected'] - r['ledge_top_z'], 4) for r in stations if r.get('ledge_top_z') is not None]
        deficits += [round(r['z0_expected'] - r['highest_plateau_below_z0'], 4) for r in stations if r.get('highest_plateau_below_z0') is not None]
        missing = [r for r in stations if r.get('ledge_top_z') is None and r.get('highest_plateau_below_z0') is None]
        short = [r for r in stations if r.get('highest_plateau_below_z0') is not None]
        worst = max(deficits) if deficits else None
        checks['ledge_reaches_profile'] = {'status': 'PASS' if (not missing and not short and worst is not None and worst <= 0.02) else 'WARN',
                                           'note': 'A ledge top below z0(x) means the plate blank is lower than the profile there (the blank is never raised); '
                                                   'a missing plateau means the ledge top at that station is not flat at z0(x).',
                                           'max_deficit_mm': worst, 'stations_without_plateau': [{'x': r['x'], 'side': r['side']} for r in missing]}
    # offset-model accuracy: skin samples of the plate -> O1 (normal mode only)
    if measure == 'normal':
        skin_pts = Vp[Tp].mean(axis=1)
        fnp = np.cross(Vp[Tp][:, 1] - Vp[Tp][:, 0], Vp[Tp][:, 2] - Vp[Tp][:, 0])
        fnp /= np.maximum(np.linalg.norm(fnp, axis=1, keepdims=True), 1e-18)
        pk = (np.abs(fnp[:, 2]) < 0.9) & (skin_pts[:, 2] > zl0 + min(2.5, 0.2 * (zl1 - zl0))) & (skin_pts[:, 2] < zl1 - min(3.5, 0.3 * (zl1 - zl0)))
        if pk.sum() > 100:
            rng = np.random.default_rng(0)
            pick_i = rng.choice(np.flatnonzero(pk), size=min(1500, int(pk.sum())), replace=False)
            for nm, d0 in depths.items():
                loc_o = locator(*shape_mesh(solids_o[nm], cdefl))
                dd = distances(loc_o, skin_pts[pick_i])
                skin_dev[nm] = {'depth_mm': d0, 'distance_p5': round(float(np.percentile(dd, 5)), 4), 'distance_median': round(float(np.median(dd)), 4),
                                'distance_p95': round(float(np.percentile(dd, 95)), 4), 'max_abs_error_mm': round(float(np.abs(dd - d0).max()), 4), 'samples': int(len(dd))}
            worst_err = max(v['max_abs_error_mm'] for v in skin_dev.values())
            checks['offset_model_accuracy'] = {'status': 'PASS' if worst_err <= 0.03 else 'WARN', 'tol_mm': 0.03, 'levels': skin_dev,
                                               'note': 'nearest distance from skin samples of the plate blank (heights z0+2.5 .. top-3.5) to the offset solids; the nearest-point distance '
                                                       'equals the normal offset except near edges'}
        else:
            checks['offset_model_accuracy'] = {'status': 'UNVERIFIED', 'note': 'too few vertical skin samples on the plate blank to compare with the offset solids'}
    mass = {'density_g_cm3': float(prm['density_g_cm3']), 'mesh_volume_mm3': round(vol_mesh, 2), 'brep_volume_mm3': round(abs(L.volume(N)), 2),
            'mass_g': round(vol_mesh * float(prm['density_g_cm3']) / 1000.0, 3)}
    z0_json = {'levels': levels, 'rear_mm': None if prm['z0_rear_mm'] is None else float(prm['z0_rear_mm']), 'ramp_factor': float(prm['ramp_factor'])}
    params_json = {
        'schema': 'mouse_plate_joint_params/1', 'plate': plate_name, 'shell': shell_name, 'frames': 'plate bottom z = 0; model x / y as in the input files; stations split by the plate bbox mid plane in y (side low_y / high_y)',
        'bearing': bearing, 'z0_function': ('piecewise-flat in x (independent of y); z0 = level.z0 for x >= level.x_from, rear below the smallest x_from; a linear ramp of '
                                            'total width ramp_factor * |dz| centred on each boundary joins the plateaus') if bearing == 'z0_profile' else 'plate blank top (no profile)',
        'z0': z0_json, 'z0_profile_polyline_xz': [[round(x, 3), round(z, 3)] for x, z in poly],
        'ledge': {'width_mm': ledge, 'measured': measure, 'note': ('= foundation wall + clearance; outer edge flush with the plate blank skin, top flat at z0(x)'
                                                                   if measure == 'normal' else 'horizontal chord (plan wall) of the rim, top = blank top')},
        'tongue': ({'from_skin_mm': ledge, 'to_skin_mm': ledge + tw, 'width_normal_mm': tw, 'height_above_z0_mm': th, 'top': 'z0(x) + height',
                    'clearance_to_foundation_inner_face_mm': clearance, 'foundation_wall_mm': wall} if th > 0 else None),
        'plate_floor_mm': floor, 'bearing_pads': pad_info, 'offset_surfaces': {'model': 'radial field r(z, theta) about the plate plan centre, smoothing rms %.4f mm' % float(prm['smoothing_rms_mm']),
                                                        'centre_xy': [round(float(c[0]), 4), round(float(c[1]), 4)], 'levels': [round(float(zlev[0]), 3), round(float(zlev[-1]), 3), 0.5],
                                                        'wire_points': na}, 'stations': stations, 'stations_x_mm': stations_x}
    import json
    (out / 'joint_params.json').write_text(json.dumps(L.clean(params_json), indent=1), encoding='utf-8')
    return {'plate_part': plate_name, 'shell_part': shell_name, 'ledge_mm': ledge, 'clearance_mm': clearance, 'tongue_width_mm': tw, 'tongue_height_mm': th, 'floor_mm': floor,
            'bearing': bearing, 'ledge_measure': measure, 'centre_xy': c.tolist(), 'bbox': bbn, 'plate_blank': {'bbox': [float(v) for v in bb], 'mesh_volume_mm3': round(vol_plate_mesh, 2)},
            'checks': checks, 'mass': mass, 'stations': stations, 'stations_x_mm': stations_x, 'bookkeeping': book, 'skin_model': {'levels_sampled': int(len(zs)), 'offset_fold_columns': model.fold_columns, 'offset_fold_max_loop_mm': round(model.fold_max_loop_mm, 4), 'covered_to_z_mm': z_cover, 'bridged_samples': bridged,
                                                                                                     'outline_area_mm2': round(star_area, 1), 'section_points': src[:: max(1, len(zs) // 8)].tolist()},
            'notes': notes, 'files': {'step': 'hollow_plate.step', 'params': 'joint_params.json'}, 'settings_used': {k: prm[k] for k in prm if k not in ('z0_levels_mm', 'stations_x_mm')}, 'z0': z0_json,
            'worker_version': WORKER_VERSION, 'worker_seconds': round(time.time() - t0, 1)}


def boolean_or_zero(a, b, defl: float):
    """Common volume of a and b; an empty common is a valid 0 (a Boolean error is not)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    op = BRepAlgoAPI_Common(a, b)
    if not op.IsDone():
        raise WorkerError('PLATE_JOINT_BOOLEAN', 'The common volume with the shell could not be computed (Boolean error).')
    r = op.Shape()
    ss = [] if r.IsNull() else [s for s in L.solids(r) if abs(L.volume(s)) > 1e-9]
    if not ss:
        return None, [], 0.0
    sh = ss[0] if len(ss) == 1 else L.compound(ss)
    return sh, ss, mesh_vol(sh, defl)


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
