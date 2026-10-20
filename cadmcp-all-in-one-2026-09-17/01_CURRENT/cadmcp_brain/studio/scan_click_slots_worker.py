"""Worker of brain_mouse_click_slots (server python: numpy, scipy, OCP).

Cuts the click-panel slots and the wheel window into a closed shell SOLID (B-rep), from a plan layout (click_slot_layout/1, written by
brain_mouse_scan_click_grooves as slot_layout.json, or given by hand). Spec parameters with overridable defaults: perimeter slot width,
centre gap width (both slot sides together), slot depth below the local B-rep surface, rounded-rectangle window (length / width / corner
radius) with a flat floor parallel to its rim plane. Vertical walls and crisp edges. Optional mirror plane: the layout is symmetrised only
where it passes the same coarse test as the shell (p80 mirror residual <= max(abs_threshold_mm, rel_threshold x diag)); never forced.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Any
import numpy as np

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cadmcp_brain.studio.scan_cad_common import WorkerError, worker_main  # noqa: E402

WORKER_VERSION = 'click_slots/13'
FUZZY_LADDER_REL = (0.0, 1e-5, 3e-5, 1e-4)      # x shell bbox diagonal (tolerance ladder of the gated boolean; 0 = exact first)
DEFAULTS = {'slot_width_mm': None, 'gap_width_mm': None, 'depth_mm': 2.0, 'window_depth_mm': None, 'window_length_mm': None, 'window_width_mm': None,
            'window_radius_mm': None, 'station_step_mm': 0.5, 'smooth_mm': 1.5, 'mirror_plane': None, 'abs_threshold_mm': 2.0, 'rel_threshold': 0.015,
            'cut_window': True, 'cut_gap': True, 'cut_perimeter': True,
            'trim_lip': True, 'lip_height_mm': None, 'lip_zone_frac': 0.7, 'lip_angle_deg': 30.0, 'lip_edge_deg': 20.0, 'lip_edge_clear_mm': 0.5, 'ramp_mm': 3.0, 'ramp_lift_mm': 1.5,
            'trim_gap_rear': True, 'through_wall': False,
            'window_on_gap_tol_mm': 1.0, 'gap_window_blend_mm': 1.5, 'roughness_max_dev_mm': 0.02, 'max_curvature_sign_changes': 0}


def resample(Q, step):
    sl = np.r_[0, np.cumsum(np.linalg.norm(np.diff(Q, axis=0), axis=1))]
    n = max(3, int(np.ceil(sl[-1] / step)) + 1)
    t = np.linspace(0, sl[-1], n)
    return np.column_stack([np.interp(t, sl, Q[:, k]) for k in range(Q.shape[1])]), float(sl[-1])


def left_normal(Q):
    tg = np.gradient(Q, axis=0)
    tg /= np.maximum(np.linalg.norm(tg, axis=1), 1e-12)[:, None]
    return np.column_stack([-tg[:, 1], tg[:, 0]])


def mirror2(P, n, d):
    X = np.column_stack([P, np.zeros(len(P))])
    s = X @ n - d
    return (X - 2 * s[:, None] * n)[:, :2]


def seg_dist(P, Q):
    """distance of points P to the polyline Q (plan)."""
    A, B = Q[:-1], Q[1:]
    AB = B - A
    L2 = np.maximum((AB ** 2).sum(1), 1e-18)
    t = np.clip(((P[:, None, :] - A[None]) * AB[None]).sum(2) / L2[None], 0, 1)
    C = A[None] + t[..., None] * AB[None]
    return np.linalg.norm(P[:, None, :] - C, axis=2).min(1)


class Body:
    def __init__(self, solid):
        from cadmcp_brain.studio import cad_brep_lib as cb
        self.s = solid
        b = cb.bbox(solid)
        self.zmin, self.zmax = float(b[2]), float(b[5])
        self.diag = float(np.linalg.norm(b[3:] - b[:3]))

    def top_z(self, xy):
        from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
        from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
        out = np.full(len(xy), np.nan)
        for i, (x, y) in enumerate(xy):
            it = BRepIntCurveSurface_Inter()
            it.Init(self.s, gp_Lin(gp_Pnt(float(x), float(y), self.zmax + 10.0), gp_Dir(0, 0, -1)), 1e-7)
            zz = []
            while it.More():
                zz.append(it.Pnt().Z())
                it.Next()
            if zz:
                out[i] = max(zz)
        return out

    def top_normal(self, xy):
        """outward (z >= 0) unit normal of the top skin at each xy (face normal at the highest vertical-ray hit); NaN where no hit."""
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
        from OCP.BRepLProp import BRepLProp_SLProps
        from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
        out = np.full((len(xy), 3), np.nan)
        for i, (x, y) in enumerate(xy):
            it = BRepIntCurveSurface_Inter()
            it.Init(self.s, gp_Lin(gp_Pnt(float(x), float(y), self.zmax + 10.0), gp_Dir(0, 0, -1)), 1e-7)
            best = None
            while it.More():
                if best is None or it.Pnt().Z() > best[0]:
                    best = (it.Pnt().Z(), it.Face(), it.U(), it.V())
                it.Next()
            if best is None:
                continue
            pr = BRepLProp_SLProps(BRepAdaptor_Surface(best[1]), best[2], best[3], 1, 1e-6)
            if not pr.IsNormalDefined():
                continue
            nv = pr.Normal()
            n = np.array([nv.X(), nv.Y(), nv.Z()])
            out[i] = n if n[2] >= 0 else -n
        return out


def crisp_edge_points(solid, min_deg: float, step_mm: float = 0.25):
    """Sampled 3D points of the solid's crisp edges: edges shared by two faces, sampled every step_mm, kept where the dihedral angle between
    the two face normals is >= min_deg (a styling crease such as the click-panel lip; smooth skin seams measure ~0 deg). (N, 3) or None."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_AbscissaPoint
    from OCP.GeomLProp import GeomLProp_SLProps
    from OCP.ShapeAnalysis import ShapeAnalysis_Surface
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
    from OCP.TopoDS import TopoDS
    amap = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(solid, TopAbs_EDGE, TopAbs_FACE, amap)
    cos_min = np.cos(np.radians(min_deg))
    out = []
    for i in range(1, amap.Extent() + 1):
        faces = [TopoDS.Face_s(s) for s in amap.FindFromIndex(i)]
        if len(faces) != 2:
            continue
        e = TopoDS.Edge_s(amap.FindKey(i))
        if BRep_Tool.Degenerated_s(e):
            continue
        c = BRepAdaptor_Curve(e)
        a, b = c.FirstParameter(), c.LastParameter()
        n = max(2, int(GCPnts_AbscissaPoint.Length_s(c, a, b) / step_mm) + 1)
        sas = [ShapeAnalysis_Surface(BRep_Tool.Surface_s(f)) for f in faces]
        for t in np.linspace(a, b, n):
            pnt = c.Value(t)
            nv = []
            for f, s in zip(faces, sas):
                uv = s.ValueOfUV(pnt, 1e-3)
                pr = GeomLProp_SLProps(s.Surface(), uv.X(), uv.Y(), 1, 1e-6)
                if not pr.IsNormalDefined():
                    break
                d = pr.Normal()
                nv.append(np.array([d.X(), d.Y(), d.Z()]))
            if len(nv) == 2 and abs(float(nv[0] @ nv[1])) <= cos_min:
                out.append([pnt.X(), pnt.Y(), pnt.Z()])
    return np.asarray(out, float) if out else None


def skin_frame(body, Q, zs, nrm2):
    """through_wall: per-station 3D frame on the top skin: P3 = (Q, zs), n3 = outward skin normal (exact face normal; NaN rows filled by
    the nearest station), t3 = unit transverse direction in the tangent plane on the side of the 2D left normal nrm2."""
    n3 = body.top_normal(Q)
    bad = ~np.isfinite(n3).all(1)
    if bad.all():
        n3 = np.tile([0.0, 0.0, 1.0], (len(Q), 1))
    elif bad.any():
        idx = np.arange(len(Q))
        for j in range(3):
            n3[:, j] = np.interp(idx, idx[~bad], n3[~bad, j])
        n3 /= np.linalg.norm(n3, axis=1)[:, None]
    tg = np.gradient(np.column_stack([Q, zs]), axis=0)
    tg -= (tg * n3).sum(1)[:, None] * n3                       # path tangent in the tangent plane
    tg /= np.maximum(np.linalg.norm(tg, axis=1), 1e-12)[:, None]
    t3 = np.cross(n3, tg)
    t3 /= np.maximum(np.linalg.norm(t3, axis=1), 1e-12)[:, None]
    flip = (t3[:, :2] * nrm2).sum(1) < 0
    t3[flip] = -t3[flip]
    return np.column_stack([Q, zs]), n3, t3


def match_end_frames(frame, host, reach, nb):
    """through_wall junctions: where an end of this band lies within `reach` (plan) of the host band's path, blend its normals over the
    last nb stations into the host's normal at the nearest host station, so the two tilted bands overlap at every depth (no ligament
    under the skin); t3 is rebuilt from the blended normal. Returns the number of ends matched."""
    P3, n3, t3 = frame
    H3, hn3, _ = host
    done = 0
    for end in (0, 1):
        idx = np.arange(len(P3)) if end == 0 else np.arange(len(P3))[::-1]
        e = P3[idx[0], :2]
        j = int(np.argmin(np.linalg.norm(H3[:, :2] - e, axis=1)))
        if np.linalg.norm(H3[j, :2] - e) > reach:
            continue
        nn = min(nb, len(P3))
        w = np.linspace(1.0, 0.0, nn)
        for q, wk in zip(idx[:nn], w):
            v = (1 - wk) * n3[q] + wk * hn3[j]
            n3[q] = v / max(np.linalg.norm(v), 1e-12)
            tg = t3[q]
            tg = np.cross(n3[q], np.cross(tg, n3[q]))          # keep t3 in the new tangent plane
            t3[q] = tg / max(np.linalg.norm(tg), 1e-12)
        done += 1
    return done


def lip_line(body, A, B, z_nose, step, h=0.5):
    """through_wall front closure of the perimeter: the plane through the two trimmed perimeter ends (lifted to the skin) and the nose point
    (skin point on the ends' mid-line, frame x = front, at height z_nose) is intersected with the top skin; returns the xy stations A..B of
    that curve (resampled at step) and a log. Each station marches forward from the chord until the skin drops below the plane (first
    crossing, refined by bisection); the search for the next station restarts just behind the previous crossing."""
    A, B = np.asarray(A, float), np.asarray(B, float)
    zA, zB = body.top_z(np.vstack([A, B]))
    if not (np.isfinite(zA) and np.isfinite(zB)):
        raise WorkerError('CLICK_SLOTS_LIP', 'A perimeter end is not over the shell skin.', {'ends_xy': [A.tolist(), B.tolist()]})
    chord = B - A
    L = float(np.linalg.norm(chord))
    u = chord / max(L, 1e-12)
    fwd = np.array([-u[1], u[0]])
    if fwd[0] < 0:
        fwd = -fwd
    mid = 0.5 * (A + B)
    reach = body.diag
    xs = mid + fwd[None, :] * np.arange(0.0, reach, h)[:, None]
    z = body.top_z(xs)
    ok = np.isfinite(z)
    if not ok[0]:
        raise WorkerError('CLICK_SLOTS_LIP', 'The mid-point of the perimeter ends is not over the shell skin.', {'mid_xy': mid.tolist()})
    # front-most skin point on the mid-line (end of the first contiguous run of skin): where the skin meets the front edge of the shell
    first_gap = np.flatnonzero(~ok)
    jf = int(first_gap[0]) - 1 if len(first_gap) else len(z) - 1
    z_front = float(z[jf])
    lip_note = None
    if z_nose is not None and z[0] <= z_nose:
        raise WorkerError('CLICK_SLOTS_LIP', 'The skin on the mid-line of the ends is not above lip height at the perimeter ends.',
                          {'z_skin_mid': float(z[0]), 'z_nose': float(z_nose)})
    below = np.flatnonzero(ok[:jf + 1] & (z[:jf + 1] <= z_nose)) if z_nose is not None else np.array([], int)
    if z_nose is None or not len(below):
        # derived (no lip_height_mm), or the skin ends above the requested height: the lip plane runs through the front-most skin point
        if z_nose is not None:
            lip_note = 'requested lip height %.2f is below the skin at the front edge (%.2f): the front-most skin point is used' % (z_nose, z_front)
        if jf < 1 or z_front >= z[0]:
            raise WorkerError('CLICK_SLOTS_LIP', 'The skin does not fall towards the front between the perimeter ends and the shell front.',
                              {'z_skin_mid': float(z[0]), 'z_skin_front': z_front})
        nose = xs[jf].copy()
        z_nose = z_front
    else:
        j = int(below[0])
        t = (z[j - 1] - z_nose) / max(z[j - 1] - z[j], 1e-12)
        nose = xs[j - 1] + t * (xs[j] - xs[j - 1])
    A3, B3, N3 = np.r_[A, zA], np.r_[B, zB], np.r_[nose, z_nose]
    n = np.cross(B3 - A3, N3 - A3)
    n /= max(np.linalg.norm(n), 1e-12)
    if n[2] < 0:
        n = -n

    def zplane(xy):
        return A3[2] - ((xy - A3[:2]) @ n[:2]) / max(abs(n[2]), 1e-9)

    def crossing(c, start):
        # first forward offset s >= start where skin z <= plane z (bracket with h, bisect 6 times); None if never
        prev = None
        for s_ in np.arange(max(start, 0.0), reach, h):
            q = c + fwd * s_
            zq = body.top_z(q[None])[0]
            if not np.isfinite(zq):
                return None
            if zq - zplane(q[None])[0] <= 0:
                if prev is None:
                    return s_
                lo, hi = prev, s_
                for _ in range(6):
                    m = 0.5 * (lo + hi)
                    qm = c + fwd * m
                    dm = body.top_z(qm[None])[0] - zplane(qm[None])[0]
                    if np.isfinite(dm) and dm > 0:
                        lo = m
                    else:
                        hi = m
                return 0.5 * (lo + hi)
            prev = s_
        return None
    ns = max(3, int(np.ceil(L / max(step, 1e-3))) + 1)
    pts = []
    last = 0.0
    for t_ in np.linspace(0.0, L, ns):
        c = A + u * t_
        s_ = crossing(c, last - 2 * h)
        if s_ is None:
            continue
        pts.append(c + fwd * s_)
        last = s_
    if len(pts) < 3:
        raise WorkerError('CLICK_SLOTS_LIP', 'The lip plane does not meet the skin between the perimeter ends.', {})
    P = np.asarray(pts)
    P[0], P[-1] = A, B
    Q, length = resample(P, step)
    return Q, {'nose_xyz': N3.tolist(), 'plane_normal': n.tolist(), 'pitch_deg_down_forward': float(np.degrees(np.arctan2(n[0], n[2]))),
               'length_mm': length, 'stations': int(len(Q)), 'ends_xy': [A.tolist(), B.tolist()], 'note': lip_note}


def vertical_depth(body, Q, depth, nsm, max_slope_deg=80.0, h=0.3):
    """through_wall: vertical cutter depth per station that gives a depth of `depth` measured along the skin normal, depth / cos(slope),
    slope from central differences of the top surface (h mm); clamped at max_slope_deg (a near-vertical skin would need an infinite
    vertical cut) and smoothed like the floor. On a flat skin this is `depth` itself."""
    zx1 = body.top_z(Q + [h, 0.0])
    zx0 = body.top_z(Q - [h, 0.0])
    zy1 = body.top_z(Q + [0.0, h])
    zy0 = body.top_z(Q - [0.0, h])
    gx, gy = (zx1 - zx0) / (2 * h), (zy1 - zy0) / (2 * h)
    cos = 1.0 / np.sqrt(1.0 + np.nan_to_num(gx, nan=0.0) ** 2 + np.nan_to_num(gy, nan=0.0) ** 2)
    cos = np.maximum(cos, np.cos(np.radians(max_slope_deg)))
    return smooth(depth / cos, nsm)


def smooth(z, n):
    if n <= 1:
        return z
    k = np.ones(n) / n
    return np.convolve(np.pad(z, n // 2, mode='edge'), k, mode='valid')[:len(z)]


def fill_nan(z):
    ok = np.isfinite(z)
    if not ok.any():
        return None
    i = np.arange(len(z))
    return np.interp(i, i[ok], z[ok])


def band_cutter(Q, nrm, o1, o2, zfl, ZT):
    """closed solid: floor = ruled sheet at zfl, top at ZT, two ruled vertical walls, two planar end caps; sewn (port of whole_v1 w6)."""
    pin, pout = Q + o1 * nrm, Q + o2 * nrm
    zt = np.full(len(Q), ZT)
    return _band_from_rails(np.column_stack([pin, zfl]), np.column_stack([pout, zfl]), np.column_stack([pin, zt]), np.column_stack([pout, zt]))


def normal_band_cutter(P3, n3, t3, o1, o2, depth, lift):
    """through_wall band: the cross-section follows the skin normal n3 (unit, outward) instead of the vertical: rails at P3 + t3*o +
    n3*(-depth | +lift), t3 = unit transverse direction in the tangent plane (left of the path). Same sewing/validation as band_cutter."""
    lo_in, lo_out = P3 + o1 * t3 - depth * n3, P3 + o2 * t3 - depth * n3
    hi_in, hi_out = P3 + o1 * t3 + lift * n3, P3 + o2 * t3 + lift * n3
    return _band_from_rails(lo_in, lo_out, hi_in, hi_out)


def _band_from_rails(lo_in, lo_out, hi_in, hi_out):
    """closed solid from four 3D rails (N x 3): two ruled 'floor/top' sheets, two ruled walls, two planar end caps; sewn."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeSolid, BRepBuilderAPI_MakeWire, BRepBuilderAPI_Sewing
    from OCP.BRepFill import BRepFill
    from OCP.GeomAbs import GeomAbs_C2
    from OCP.GeomAPI import GeomAPI_PointsToBSpline
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Pnt
    from cadmcp_brain.studio import cad_brep_lib as cb

    def bsp(P):
        a = TColgp_Array1OfPnt(1, len(P))
        for i, p in enumerate(P):
            a.SetValue(i + 1, gp_Pnt(*map(float, p)))
        return GeomAPI_PointsToBSpline(a, 3, 3, GeomAbs_C2, 2e-3).Curve()

    def E(P):
        return BRepBuilderAPI_MakeEdge(bsp(P)).Edge()
    ib, ob, it, ot = E(lo_in), E(lo_out), E(hi_in), E(hi_out)
    fs = [BRepFill.Face_s(ib, ob), BRepFill.Face_s(it, ot), BRepFill.Face_s(ib, it), BRepFill.Face_s(ob, ot)]
    for k in (0, -1):
        q = [gp_Pnt(*map(float, lo_in[k])), gp_Pnt(*map(float, lo_out[k])), gp_Pnt(*map(float, hi_out[k])), gp_Pnt(*map(float, hi_in[k]))]
        mw = BRepBuilderAPI_MakeWire()
        for j in range(4):
            mw.Add(BRepBuilderAPI_MakeEdge(q[j], q[(j + 1) % 4]).Edge())
        fs.append(BRepBuilderAPI_MakeFace(mw.Wire(), True).Face())
    sew = BRepBuilderAPI_Sewing(5e-3)
    for f in fs:
        sew.Add(f)
    sew.Perform()
    ex = TopExp_Explorer(sew.SewedShape(), TopAbs_SHELL)
    if not ex.More():
        raise WorkerError('CLICK_SLOTS_CUTTER_INVALID', 'A slot cutter could not be sewn into a shell.')
    so = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(ex.Current())).Solid()
    sf = ShapeFix_Solid(so)
    sf.Perform()
    best = TopoDS.Solid_s(sf.Solid())
    if cb.volume(best) < 0:
        best = TopoDS.Solid_s(best.Reversed())
    return best, int(sew.NbFreeEdges())


def window_cutter(body, C, R, z_floor_plane, ZT):
    """rounded rectangle (centre, axis, length, width, radius) prism, vertical walls, kept above the floor plane z = a + b x + c y."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Splitter
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.GC import GC_MakeArcOfCircle
    from OCP.TopAbs import TopAbs_IN
    from OCP.TopTools import TopTools_ListOfShape
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt, gp_Vec
    from cadmcp_brain.studio import cad_brep_lib as cb
    c, u, L, Wd = C['centre'], C['axis'], C['length'], C['width']
    v = np.array([-u[1], u[0]])
    R = min(R, 0.5 * min(L, Wd) - 1e-3)
    z0 = body.zmin - 1.0

    def P(a, b):
        p = c + a * u + b * v
        return gp_Pnt(float(p[0]), float(p[1]), z0)
    hl, hw = L / 2, Wd / 2
    s45 = R * (1 - np.cos(np.pi / 4))
    pts = [(hl, -hw + R), (hl, hw - R), (hl - R, hw), (-hl + R, hw), (-hl, hw - R), (-hl, -hw + R), (-hl + R, -hw), (hl - R, -hw)]
    mids = [(hl - s45, hw - s45), (-hl + s45, hw - s45), (-hl + s45, -hw + s45), (hl - s45, -hw + s45)]
    mw = BRepBuilderAPI_MakeWire()
    for i in range(4):
        a, b = pts[2 * i], pts[2 * i + 1]
        mw.Add(BRepBuilderAPI_MakeEdge(P(*a), P(*b)).Edge())
        if R > 1e-6:
            mw.Add(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(P(*b), P(*mids[i]), P(*pts[(2 * i + 2) % 8])).Value()).Edge())
        else:
            mw.Add(BRepBuilderAPI_MakeEdge(P(*b), P(*pts[(2 * i + 2) % 8])).Edge())
    prism = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(mw.Wire(), True).Face(), gp_Vec(0, 0, ZT - z0)).Shape()
    a0, b0, c0 = z_floor_plane
    nv = np.array([-b0, -c0, 1.0])
    nv /= np.linalg.norm(nv)
    zc = a0 + b0 * c[0] + c0 * c[1]
    pl = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(float(c[0]), float(c[1]), float(zc)), gp_Dir(*map(float, nv))), -200, 200, -200, 200).Face()
    sp = BRepAlgoAPI_Splitter()
    A = TopTools_ListOfShape()
    A.Append(prism)
    T = TopTools_ListOfShape()
    T.Append(pl)
    sp.SetArguments(A)
    sp.SetTools(T)
    sp.Build()
    for s in cb.solids(sp.Shape()):
        if BRepClass3d_SolidClassifier(s, gp_Pnt(float(c[0]), float(c[1]), float(zc) + 0.5), 1e-6).State() == TopAbs_IN:
            return s, {'centre': c.tolist(), 'axis': u.tolist(), 'length_mm': L, 'width_mm': Wd, 'corner_radius_mm': R}
    raise WorkerError('CLICK_SLOTS_CUTTER_INVALID', 'The window cutter could not be split by its floor plane.')


def symmetric_average(Pp, n, d, step):
    """Exactly symmetric open path from a near-symmetric one: split at its crossing of the mirror plane (the crossing farthest from both
    ends), both branches resampled from the crossing outward over their own lengths (point i of one branch = point i of the other: arc-length
    correspondence, not the index of the whole path), the second branch mirrored, averaged, and the half mirrored back."""
    sd = np.column_stack([Pp, np.zeros(len(Pp))]) @ n - d
    cr = np.flatnonzero(np.sign(sd[:-1]) != np.sign(sd[1:]))
    if not len(cr):
        Mr = mirror2(Pp, n, d)[::-1]
        return 0.5 * (Pp + Mr), 'averaged with its mirror image by station (no plane crossing found)'
    i = int(cr[np.argmax(np.minimum(cr, len(Pp) - 2 - cr))])
    t = sd[i] / (sd[i] - sd[i + 1])
    c = Pp[i] + t * (Pp[i + 1] - Pp[i])
    A = np.vstack([c, Pp[i::-1]])
    B = np.vstack([c, Pp[i + 1:]])
    la = np.linalg.norm(np.diff(A, axis=0), axis=1).sum()
    lb = np.linalg.norm(np.diff(B, axis=0), axis=1).sum()
    m = max(3, int(np.ceil(0.5 * (la + lb) / step)) + 1)

    def rs(Q):
        sl = np.r_[0, np.cumsum(np.linalg.norm(np.diff(Q, axis=0), axis=1))]
        tt = np.linspace(0, sl[-1], m)
        return np.c_[np.interp(tt, sl, Q[:, 0]), np.interp(tt, sl, Q[:, 1])]
    H = 0.5 * (rs(A) + mirror2(rs(B), n, d))
    H[0] = H[0] - ((np.r_[H[0], 0.0] @ n - d) / max(np.linalg.norm(n[:2]) ** 2, 1e-12)) * n[:2]      # the centre point on the plane
    full = np.vstack([H[::-1], mirror2(H[1:], n, d)])
    return full, 'branches from the plane crossing averaged by arc length with the mirrored other branch (exactly symmetric)'


def window_from_corners(corners):
    TR, TL, BL, BR = [np.asarray(x, float) for x in corners]
    c = (TR + TL + BL + BR) / 4
    u = (TR + BR) / 2 - (TL + BL) / 2
    L = float(np.linalg.norm(u))
    u /= max(L, 1e-12)
    Wd = float(np.linalg.norm((TR + TL) / 2 - (BR + BL) / 2))
    return {'centre': c, 'axis': u, 'length': L, 'width': Wd}


def run(req: dict[str, Any]) -> dict[str, Any]:
    from cadmcp_brain.studio import cad_brep_lib as cb
    from scipy.spatial import cKDTree
    cb.require_ocp()
    p = {**DEFAULTS, **(req.get('params') or {})}
    inp = req['inputs']
    lay = json.loads(Path(inp['layout']).read_text(encoding='utf-8'))
    if lay.get('schema') != 'click_slot_layout/1':
        raise WorkerError('CLICK_SLOTS_LAYOUT', "The layout must be a click_slot_layout/1 JSON (slot_layout.json of brain_mouse_scan_click_grooves).")
    solid = cb.one_solid(Path(inp['shell']), 'CLICK_SLOTS_SHELL')
    if not cb.is_valid(solid):
        raise WorkerError('CLICK_SLOTS_SHELL', 'The shell solid is not valid.')
    body = Body(solid)
    W = float(p['slot_width_mm'] or lay.get('slot_width_mm') or 0.5)
    GW = float(p['gap_width_mm'] or (lay.get('centre_gap') or {}).get('width_mm') or 2 * W)
    DEPTH = float(p['depth_mm'])
    WDEPTH = float(p['window_depth_mm'] or DEPTH)
    warnings: list[str] = []
    sym_log: dict[str, Any] = {'plane': None}
    per = lay.get('perimeter')
    gaps = [np.asarray(s, float) for s in ((lay.get('centre_gap') or {}).get('segments') or [])]
    win = lay.get('window')
    n = d = None
    if p['mirror_plane']:
        n = np.asarray(p['mirror_plane']['normal'], float)
        n /= np.linalg.norm(n)
        d = float(p['mirror_plane']['d'])
        sym_log['plane'] = {'normal': n.tolist(), 'd': d}
    step = float(p['station_step_mm'])
    Pp = None
    rough = None
    if per and p['cut_perimeter']:
        Pp, plen = resample(np.asarray(per['points'], float), step)
        if n is not None:
            thr = max(p['abs_threshold_mm'], p['rel_threshold'] * float(np.linalg.norm(Pp.max(0) - Pp.min(0))))
            res = seg_dist(mirror2(Pp, n, d), Pp)
            st = float(np.percentile(res, 80))
            ok = st <= thr
            sym_log['perimeter'] = {'stat_p80_mm': st, 'threshold_mm': thr, 'symmetric': bool(ok)}
            if ok:
                Pp, how = symmetric_average(Pp, n, d, step)
                sym_log['perimeter']['correction'] = how
            else:
                sym_log['perimeter']['correction'] = 'kept as given (asymmetric)'
    if gaps and n is not None and p['cut_gap']:
        nn = n[:2] / max(np.linalg.norm(n[:2]), 1e-12)
        out = []
        for g in gaps:
            dist = np.abs(np.column_stack([g, np.zeros(len(g))]) @ n - d) / max(np.linalg.norm(n[:2]), 1e-12)
            thr = max(p['abs_threshold_mm'], 0.0)
            if float(dist.max()) <= thr:
                g = g - ((np.column_stack([g, np.zeros(len(g))]) @ n - d) / max(np.linalg.norm(n[:2]) ** 2, 1e-12))[:, None] * n[:2]
                out.append(g)
                sym_log.setdefault('centre_gap', []).append({'max_offset_mm': float(dist.max()), 'symmetric': True, 'correction': 'snapped onto the mirror plane'})
            else:
                out.append(g)
                sym_log.setdefault('centre_gap', []).append({'max_offset_mm': float(dist.max()), 'symmetric': False, 'correction': 'kept as given'})
        gaps = out
        del nn
    ZT = body.zmax + 5.0
    trim_log: dict[str, Any] = {}
    if Pp is not None and p['trim_lip']:
        # whole_v1 rule: the perimeter slot does not run along the front lip (the panel ends at the crisp lip: no notch, no slivers).
        # Front run = stations in the front part of the path (x above lip_zone_frac of its x range; frame x = front) whose outward
        # normal points forward by more than lip_angle_deg from the side direction.
        so = 1.0 if per.get('slot_side', 'left') == 'left' else -1.0
        nr = so * left_normal(Pp)
        k = max(1, int(round(2.0 / step)))
        nr = np.column_stack([smooth(nr[:, 0], 2 * k + 1), smooth(nr[:, 1], 2 * k + 1)])
        nr /= np.linalg.norm(nr, axis=1)[:, None]
        x0_, x1_ = float(Pp[:, 0].min()), float(Pp[:, 0].max())
        front = Pp[:, 0] > x0_ + float(p['lip_zone_frac']) * (x1_ - x0_)
        off = front & (nr[:, 0] > np.sin(np.radians(float(p['lip_angle_deg']))))
        # The same rule from the B-rep side: where the slot band (W beside the path + lip_edge_clear_mm) would straddle a crisp edge of the
        # shell (dihedral >= lip_edge_deg, e.g. the panel lip continuing round the front corners with its outward normal still sideways),
        # the panel ends at that crease and no slot is cut: a band on a crease leaves wedge faces of ~0.01 mm2 where its floor and walls
        # cross the edge (NO_SLIVERS), and the run-out ramp would exit the surface across it.
        crease_clear = W + float(p['lip_edge_clear_mm'])
        E = crisp_edge_points(solid, float(p['lip_edge_deg'])) if float(p['lip_edge_deg']) > 0 else None
        z_raw = body.top_z(Pp)
        zc = fill_nan(z_raw) if E is not None else None
        near = np.zeros(len(Pp), bool)
        if E is not None and zc is not None:
            near = cKDTree(E).query(np.column_stack([Pp, zc]))[0] <= crease_clear
        off_any = off | near
        keep = ~off_any
        if keep.any() and off_any.any():
            # longest contiguous run of kept stations (the open path keeps its rear middle)
            idx = np.flatnonzero(np.diff(np.r_[0, keep.astype(int), 0]))
            runs = list(zip(idx[::2], idx[1::2]))
            a, b = max(runs, key=lambda r: r[1] - r[0])
            if b - a >= 10:
                removed = np.ones(len(Pp), bool)
                removed[a:b] = False
                trim_log['perimeter_lip'] = {'stations_before': int(len(Pp)), 'stations_after': int(b - a), 'removed_front_mm': float(step * (len(Pp) - (b - a))),
                                             'ends_xy': [Pp[a].tolist(), Pp[b - 1].tolist()],
                                             'rule': 'front run of the path (outward normal > lip_angle_deg forward, front lip_zone_frac of the x range) is not cut; '
                                                     'neither is any station whose slot band lies within slot_width + lip_edge_clear_mm of a crisp edge of the '
                                                     'shell (dihedral >= lip_edge_deg): the panel ends at the crease',
                                             'lip_angle_stations_removed': int((removed & off).sum()),
                                             'crease_stations_removed': int((removed & near & ~off).sum()),
                                             'crease': {'lip_edge_deg': float(p['lip_edge_deg']), 'clear_mm': float(crease_clear),
                                                        'crisp_edge_samples': int(0 if E is None else len(E))}}
                # CS1.9: a slot end stopped by the crease rule must not leave an uncut stub before the shell edge: walk on from the kept end over
                # the removed non-lip stations to the first station whose whole band (centre and both walls) is off the shell, plus 2 stations of
                # overshoot; that end then leaves through the outer edge (open end, no ramp). Ends that cannot exit (the path stays over the shell
                # or meets the lip run first) stay as trimmed and are reported by the SLOT_END_NOT_AT_EDGE gate.
                a2, b2, ends_log = a, b, []
                nrm0 = left_normal(Pp)
                o_lo, o_hi = (0.0, W) if per.get('slot_side', 'left') == 'left' else (-W, 0.0)
                over = 2

                def band_clear(i):
                    q = np.array([Pp[i] + o * nrm0[i] for o in (o_lo, 0.5 * (o_lo + o_hi), o_hi)])
                    return bool(np.isnan(body.top_z(q)).all())
                for side_, (idx0, step_) in enumerate(((a - 1, -1), (b, 1))):
                    j, hit = idx0, None
                    while 0 <= j < len(Pp) and not off[j] and not p['through_wall']:
                        if band_clear(j):
                            hit = j
                            break
                        j += step_
                    reason = 'open' if not 0 <= idx0 < len(Pp) else ('lip_angle' if off[idx0] else 'crease')
                    if hit is not None:
                        last = hit
                        for _ in range(over):
                            nxt = last + step_
                            if 0 <= nxt < len(Pp) and not off[nxt]:
                                last = nxt
                        if side_ == 0:
                            a2 = last
                        else:
                            b2 = last + 1
                        ends_log.append({'end': 'start' if side_ == 0 else 'end', 'reason': reason, 'exits_shell': True,
                                         'extended_mm': float(step * abs(last - idx0 + step_))})
                    else:
                        ends_log.append({'end': 'start' if side_ == 0 else 'end', 'reason': reason, 'exits_shell': False, 'extended_mm': 0.0})
                if (a2, b2) != (a, b):
                    removed[:] = True
                    removed[a2:b2] = False
                    trim_log['perimeter_lip'].update({
                        'stations_after': int(b2 - a2), 'removed_front_mm': float(step * (len(Pp) - (b2 - a2))), 'ends_xy_before_extension': trim_log['perimeter_lip']['ends_xy'],
                        'ends_xy': [Pp[a2].tolist(), Pp[b2 - 1].tolist()], 'crease_stations_removed': int((removed & near & ~off).sum())})
                trim_log['perimeter_lip']['ends'] = ends_log
                Pp = Pp[a2:b2]
    lip_path = None
    if Pp is not None and p['through_wall']:
        if not trim_log.get('perimeter_lip'):
            if p['lip_height_mm'] is not None:
                warnings.append('lip_height_mm given but the perimeter was not opened at the front lip: no lip line cut.')
        else:
            # hollow-first lip rule: the plate's front edge is the intersection of the skin with the plane through the two perimeter ends and the
            # nose point at lip_height_mm above the shell's lowest point (explicit design value); cut as one more normal-following band of
            # slot width so the plates separate from the shell along the front lip
            lip_path, lip_log = lip_line(body, Pp[-1], Pp[0], None if p['lip_height_mm'] is None else body.zmin + float(p['lip_height_mm']), step)
            lip_log['lip_height_mm'] = None if p['lip_height_mm'] is None else float(p['lip_height_mm'])
            lip_log['z_rim'] = float(body.zmin)
            trim_log['lip_line'] = lip_log
    if Pp is not None and gaps and p['trim_gap_rear']:
        # whole_v1 rule: the centre gap starts at the perimeter slot, never behind it
        so = 1.0 if per.get('slot_side', 'left') == 'left' else -1.0
        # just inside the slot at its panel-side wall: no end cap left; through_wall: at the band centre (the normal-following bands tilt
        # with the skin, so an end cap at the wall would leave a ligament below the skin; the gap end tilts with the perimeter, see skin_frame)
        Cl = Pp + (0.5 * W if p['through_wall'] else min(0.1, 0.25 * W)) * so * left_normal(Pp)
        out = []
        for k, g in enumerate(gaps):
            Q, _ = resample(g, step / 2)
            # host paths this gap may end in: the perimeter slot and (through_wall) every other gap's centre line (a gap ending inside
            # another band ends at that band's centre: an end cap on or just past the host wall leaves zero-area junction faces)
            hosts = [('perimeter', Cl, W)]
            if lip_path is not None:
                hosts.append(('lip', lip_path, W))
            if p['through_wall']:
                hosts += [(f'centre_gap_{k2}', resample(g2, step / 2)[0], max(W, GW)) for k2, g2 in enumerate(gaps) if k2 != k]
            for end in (0, 1):
                order = np.arange(len(Q)) if end == 0 else np.arange(len(Q))[::-1]
                half = order[:max(2, len(Q) // 3)]
                best_h = None
                for hname, H, reach in hosts:
                    dist = seg_dist(Q, H)
                    j = half[np.argmin(dist[half])]
                    if dist[j] <= reach and j != order[0] and (best_h is None or dist[j] < best_h[0]):
                        best_h = (float(dist[j]), int(j), hname)
                if best_h is not None:
                    _, j, hname = best_h
                    Q = Q[j:] if end == 0 else Q[:j + 1]
                    trim_log.setdefault('centre_gap', []).append({'segment': k, 'end': 'start' if end == 0 else 'end', 'host': hname,
                                                                  'new_end_xy': (Q[0] if end == 0 else Q[-1]).tolist()})
            out.append(Q)
        gaps = out
    cutters, info = [], []
    per_floor = None
    win_geo = None
    wlog = None
    if win and p['cut_window']:
        C = window_from_corners(win['corners_TR_TL_BL_BR'])
        R = float(p['window_radius_mm'] or win.get('corner_radius_mm') or 0.0)
        if p['window_length_mm']:
            C['length'] = float(p['window_length_mm'])
        if p['window_width_mm']:
            C['width'] = float(p['window_width_mm'])
        if n is not None:
            nn = n[:2] / max(np.linalg.norm(n[:2]), 1e-12)
            off = float((np.r_[C['centre'], 0.0] @ n - d) / max(np.linalg.norm(n[:2]), 1e-12))
            ang = float(np.degrees(np.arcsin(min(1.0, abs(C['axis'] @ nn)))))
            ok = abs(off) <= p['abs_threshold_mm'] and ang <= 5.0
            sym_log['window'] = {'centre_offset_mm': off, 'axis_angle_to_plane_deg': ang, 'symmetric': bool(ok)}
            if ok:
                C['centre'] = C['centre'] - off * nn
                ax = C['axis'] - (C['axis'] @ nn) * nn
                C['axis'] = ax / np.linalg.norm(ax)
                sym_log['window']['correction'] = 'centre on the mirror plane, axis parallel to it'
            else:
                sym_log['window']['correction'] = 'kept as given'
        # the window sits on the centre-gap line (the gap enters it on its centre line, no step) when the gap line passes within
        # window_on_gap_tol_mm of the window centre: centre moved onto the line, axis parallel to it
        gal = None
        if gaps and p['cut_gap']:
            G = np.vstack(gaps)
            gc, gd = G.mean(0), G[-1] - G[0]
            gd = gd / max(np.linalg.norm(gd), 1e-12)
            gn = np.array([-gd[1], gd[0]])
            cross = lambda a: float(np.degrees(np.arcsin(min(1.0, abs(a[0] * gd[1] - a[1] * gd[0])))))
            off = float((C['centre'] - gc) @ gn)
            ang = cross(C['axis'])
            on = abs(off) <= float(p['window_on_gap_tol_mm']) and ang <= 5.0
            if on:
                C['centre'] = C['centre'] - off * gn
                C['axis'] = gd if C['axis'] @ gd >= 0 else -gd
            gal = {'offset_before_mm': off, 'angle_before_deg': ang, 'on_gap_line': bool(on), 'offset_after_mm': float((C['centre'] - gc) @ gn),
                   'angle_after_deg': cross(C['axis'])}
        # rim plane fitted to the B-rep surface along the outline, floor parallel to it
        th = np.linspace(0, 2 * np.pi, 96, endpoint=False)
        v = np.array([-C['axis'][1], C['axis'][0]])
        ring = C['centre'] + np.outer(np.cos(th) * C['length'] / 2, C['axis']) + np.outer(np.sin(th) * C['width'] / 2, v)
        zr = body.top_z(ring)
        ok = np.isfinite(zr)
        if ok.sum() < 10:
            raise WorkerError('CLICK_SLOTS_LAYOUT', 'The window outline does not lie over the shell.')
        A = np.column_stack([np.ones(ok.sum()), ring[ok]])
        abc = np.linalg.lstsq(A, zr[ok], rcond=None)[0]
        resid = zr[ok] - A @ abc
        fl = [float(abc[0] - WDEPTH), float(abc[1]), float(abc[2])]          # depth measured vertically below the rim plane (whole_v1 w6)
        win_geo = (C, fl)
        c, wl = window_cutter(body, C, R, fl, ZT)
        cutters.append(c)
        wlog = {**wl, 'gap_alignment': gal, 'rim_plane': {'a': float(abc[0]), 'b': float(abc[1]), 'c': float(abc[2]), 'resid_max_mm': float(np.abs(resid).max())},
                'floor_plane': fl, 'depth_below_rim_mm': WDEPTH}
    nsm = max(1, int(round(float(p['smooth_mm']) / step)))
    if Pp is not None:
        side = per.get('slot_side', 'left')
        o1, o2 = (0.0, W) if side == 'left' else (-W, 0.0)
        nrm = left_normal(Pp)
        zs = fill_nan(body.top_z(Pp + 0.5 * (o1 + o2) * nrm))
        if zs is None:
            raise WorkerError('CLICK_SLOTS_LAYOUT', 'The perimeter path does not lie over the shell.')
        zs = smooth(zs, nsm)
        dv_p = vertical_depth(body, Pp + 0.5 * (o1 + o2) * nrm, DEPTH, nsm) if p['through_wall'] else None
        zfl_p = zs - (dv_p if dv_p is not None else DEPTH)
        if trim_log.get('perimeter_lip') and not p['through_wall']:
            # open ends run out: the floor rises linearly to above the surface over ramp_mm (no end cap faces at the lip corners)
            nr_ = max(2, int(round(float(p['ramp_mm']) / step)))
            ramp = np.linspace(1.0, 0.0, nr_)
            e_log = trim_log['perimeter_lip'].get('ends') or [{}, {}]
            if not e_log[0].get('exits_shell'):                      # an end that leaves through the shell edge keeps its full depth (no ramp)
                zfl_p[:nr_] = zfl_p[:nr_] + ramp * (DEPTH + float(p['ramp_lift_mm']))
            if not e_log[1].get('exits_shell'):
                zfl_p[-nr_:] = zfl_p[-nr_:] + ramp[::-1] * (DEPTH + float(p['ramp_lift_mm']))
        per_floor = (Pp, zfl_p)
        from cadmcp_brain.studio.scan_click_grooves_worker import outline_roughness
        rough = outline_roughness(Pp)
        frame = None
        if p['through_wall']:
            frame = skin_frame(body, Pp, zs, nrm)
            c, fe = normal_band_cutter(*frame, o1, o2, DEPTH, DEPTH)
        else:
            c, fe = band_cutter(Pp, nrm, o1, o2, zfl_p, ZT)
        cutters.append(c)
        info.append({'tag': 'perimeter', 'frame': frame, 'length_mm': float(np.linalg.norm(np.diff(Pp, axis=0), axis=1).sum()), 'width_mm': W, 'stations': int(len(Pp)),
                     'vertical_depth_mm_range': [float(dv_p.min()), float(dv_p.max())] if dv_p is not None else None,
                     'floor_z_range': [float(zfl_p.min()), float(zfl_p.max())], 'free_edges': fe, 'Q': Pp, 'nrm': nrm, 'o': (o1, o2), 'zfl': zfl_p})
        if lip_path is not None:
            # the lip band overruns both perimeter ends by W/2 along its own tangent (the two end caps of an L-corner never meet otherwise)
            Ql = lip_path
            ext = 0.5 * W
            t0 = Ql[0] - Ql[1]
            t1 = Ql[-1] - Ql[-2]
            Ql = np.vstack([Ql[0] + ext * t0 / max(np.linalg.norm(t0), 1e-12), Ql, Ql[-1] + ext * t1 / max(np.linalg.norm(t1), 1e-12)])
            Ql, _ = resample(Ql, step)
            nrm_l = left_normal(Ql)
            zs_l = fill_nan(body.top_z(Ql))
            if zs_l is None:
                raise WorkerError('CLICK_SLOTS_LIP', 'The lip line is not over the shell skin.', {})
            zs_l = smooth(zs_l, nsm)
            frame_l = skin_frame(body, Ql, zs_l, nrm_l)
            match_end_frames(frame_l, frame, W, max(2, int(round(2 * W / step))))
            c, fe = normal_band_cutter(*frame_l, -W / 2, W / 2, DEPTH, DEPTH)
            cutters.append(c)
            info.append({'tag': 'lip', 'frame': frame_l, 'length_mm': float(np.linalg.norm(np.diff(Ql, axis=0), axis=1).sum()), 'width_mm': W,
                         'stations': int(len(Ql)), 'free_edges': fe, 'floor_z_range': [float((zs_l - DEPTH).min()), float((zs_l - DEPTH).max())],
                         'Q': Ql, 'nrm': nrm_l, 'o': (-W / 2, W / 2), 'zfl': zs_l - DEPTH})
    if p['cut_gap']:
        for k, g in enumerate(gaps):
            Q, glen = resample(g, step)
            if glen < 0.5:
                continue
            if p['through_wall'] and win_geo is not None:
                # junction with the window: a gap that ends at the window outline is extended along its end tangent into the window by the band
                # depth (the normal-following end cap tilts with the skin; a vertical window wall next to a tilted cap leaves a ligament under the
                # skin). The extension lies inside the window footprint, which the window cutter removes anyway.
                Cw = win_geo[0]
                ax = Cw['axis']
                ay = np.array([-ax[1], ax[0]])
                for end in (0, 1):
                    e = Q[0] if end == 0 else Q[-1]
                    tg = (Q[0] - Q[1]) if end == 0 else (Q[-1] - Q[-2])
                    tg /= max(np.linalg.norm(tg), 1e-12)
                    rel = e - Cw['centre']
                    dout = max(abs(rel @ ax) - Cw['length'] / 2, abs(rel @ ay) - Cw['width'] / 2)
                    if abs(dout) > max(W, GW) + 0.2 or (tg @ rel) >= 0:        # not at the outline, or not heading into the window
                        continue
                    ext = DEPTH + max(dout, 0.0)
                    n_ext = max(1, int(np.ceil(ext / step)))
                    tail = e + tg * np.linspace(ext / n_ext, ext, n_ext)[:, None]
                    Q = np.vstack([tail[::-1], Q]) if end == 0 else np.vstack([Q, tail])
                    trim_log.setdefault('gap_window_extension', []).append({'segment': k, 'end': 'start' if end == 0 else 'end', 'extended_mm': float(ext)})
                Q, glen = resample(Q, step)
            nrm = left_normal(Q)
            zs = fill_nan(body.top_z(Q))
            if zs is None:
                warnings.append(f'centre gap segment {k} is not over the shell; skipped.')
                continue
            zs = smooth(zs, nsm)
            dv_g = vertical_depth(body, Q, DEPTH, nsm) if p['through_wall'] else None
            zfl = zs - (dv_g if dv_g is not None else DEPTH)
            # junctions (whole_v1: one gap band merging into the perimeter slot and the window): the gap floor stays >= 0.05 mm above the
            # floor it runs into, so its end cap is open (no step face / sliver at the junction)
            if per_floor is not None:
                dj, jj = cKDTree(per_floor[0]).query(Q)
                near = dj <= W + 0.2
                zfl[near] = np.maximum(zfl[near], per_floor[1][jj[near]] + 0.05)
            if win_geo is not None:
                Cw, flw = win_geo
                rel = Q - Cw['centre']
                u = rel @ Cw['axis']
                v = rel @ np.array([-Cw['axis'][1], Cw['axis'][0]])
                # distance outside the window box; the gap floor is lifted to >= window floor + 0.05 inside and blended out over
                # gap_window_blend_mm outside (continuous: no step face where the gap meets the window)
                dout = np.hypot(np.maximum(np.abs(u) - Cw['length'] / 2, 0.0), np.maximum(np.abs(v) - Cw['width'] / 2, 0.0))
                wgt = np.clip(1.0 - dout / float(p['gap_window_blend_mm']), 0.0, 1.0)
                wgt = wgt * wgt * (3 - 2 * wgt)
                zw = flw[0] + flw[1] * Q[:, 0] + flw[2] * Q[:, 1]
                zfl = zfl + wgt * np.maximum(zw + 0.05 - zfl, 0.0)
            frame = None
            if p['through_wall']:
                frame = skin_frame(body, Q, zs, nrm)
                c, fe = None, None                                  # built below, once every gap frame exists (junction blending)
            else:
                c, fe = band_cutter(Q, nrm, -GW / 2, GW / 2, zfl, ZT)
            cutters.append(c)
            info.append({'tag': f'centre_gap_{k}', 'frame': frame, 'cutter_index': len(cutters) - 1, 'length_mm': glen, 'width_mm': GW, 'stations': int(len(Q)), 'free_edges': fe,
                         'floor_z_range': [float(zfl.min()), float(zfl.max())], 'Q': Q, 'nrm': nrm, 'o': (-GW / 2, GW / 2), 'zfl': zfl})
        if p['through_wall']:
            # junctions: the ends of each gap band take the normal of the band they run into (perimeter or another gap) so the tilted
            # bands overlap at every depth; the frames are blended against the unblended host frames, then every gap cutter is built
            nb = max(2, int(round(2 * max(W, GW) / step)))
            hosts_f = [(it_['tag'], (it_['frame'][0].copy(), it_['frame'][1].copy(), it_['frame'][2].copy()), W if it_['tag'] == 'perimeter' else max(W, GW))
                       for it_ in info if it_['frame'] is not None]
            for it_ in info:
                if not it_['tag'].startswith('centre_gap_'):
                    continue
                for hname, hframe, reach in hosts_f:
                    if hname != it_['tag']:
                        match_end_frames(it_['frame'], hframe, reach, nb)
                c, fe = normal_band_cutter(*it_['frame'], -GW / 2, GW / 2, DEPTH, DEPTH)
                cutters[it_.pop('cutter_index')] = c
                it_['free_edges'] = fe
    if not cutters:
        raise WorkerError('CLICK_SLOTS_NOTHING', 'Nothing to cut (no perimeter, gap or window in the layout, or all disabled).')
    so, boolean_log, pieces = cut_gated(solid, cutters, body.diag, Path(req['out_dir']), keep_all=bool(p['through_wall']))
    # meshability gate: a face whose 2D wire has a gap (here 3e-5 mm in the slot-cut skin B-spline) is valid in 3D but is silently dropped by BRepMesh,
    # which breaks every later volume / rendering / groove-fill step; repaired by ShapeFix_Shape under volume / bbox / face-count / validity gates.
    from cadmcp_brain.studio import mouse_groove_fill_worker as GF

    def _err(code, msg, details):
        raise WorkerError('CLICK_SLOTS_MESH', msg, details)
    if p['through_wall']:
        # through_wall pieces are gated after the STEP round trip (cut_gated + the re-import checks below): the in-memory BRepMesh of a
        # fresh Boolean result drops faces that the written file (precision 1e-4) triangulates, so the in-memory repair is not applied
        mesh_fix = None
    else:
        so, mesh_fix = GF.heal_meshable(so, 0.01, 'The slotted shell', err=_err)
    boolean_log['mesh_repair'] = mesh_fix
    sols_n = boolean_log['pieces']
    vols = boolean_log['piece_volumes_mm3']
    sols = [None] * sols_n               # only the count is used below
    out = Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    cb.write_step(so, out / 'slotted_shell.step')
    cb.write_step(cb.compound(cutters), out / 'slot_cutters.step')
    files = {'step': 'slotted_shell.step', 'cutters': 'slot_cutters.step'}
    # through_wall: the cut is meant to separate the shell into pieces (hollow-first order); every piece is kept, healed and written
    # (piece_1 = largest = slotted_shell.step; piece_k.step the others, by volume) and the width is measured just below the skin.
    extra = []
    if p['through_wall']:
        for k, pc in enumerate(pieces[1:], start=2):
            # the gate that matters is after the STEP round trip (write precision 1e-4 merges the near-coincident vertices the exact
            # cut leaves at the slot-wall x skin corners); the re-read piece must be one valid solid whose every face triangulates
            cb.write_step(pc, out / f'piece_{k}.step')
            back_k = cb.solids(cb.read_step(out / f'piece_{k}.step'))
            bad = GF.unmeshed_faces(back_k[0], 0.01) if len(back_k) == 1 else None
            if len(back_k) != 1 or not cb.is_valid(back_k[0]) or bad:
                raise WorkerError('CLICK_SLOTS_MESH', f'Piece {k} of the slotted shell is not one valid, meshable solid after the STEP round trip.',
                                  {'solids': len(back_k), 'unmeshed_faces': bad})
            extra.append(back_k[0])
        files['pieces'] = ['slotted_shell.step'] + [f'piece_{k}.step' for k in range(2, len(pieces) + 1)]
    back = cb.read_step(out / 'slotted_shell.step')
    bs = cb.solids(back)
    res_body = Body(bs[0]) if bs else None
    probe = cb.compound([bs[0]] + extra) if bs and extra else (bs[0] if bs else None)
    # measurements: width across the band at floor + 0.4 mm (through_wall: skin - 0.4 mm), depth = surface - first floor hit at the band centre
    meas = {}
    for it in info:
        Q, nrm, (o1, o2), zfl, frame = it.pop('Q'), it.pop('nrm'), it.pop('o'), it.pop('zfl'), it.pop('frame', None)
        ks = np.linspace(len(Q) * 0.1, len(Q) * 0.9, 9).astype(int)
        wds, dps = [], []
        for k in ks:
            mid = Q[k] + 0.5 * (o1 + o2) * nrm[k]
            if frame is not None:
                # through_wall: probe along the band's transverse direction t3, 0.4 mm below the skin along the normal (a horizontal probe
                # across a slit cut normal to a sloped skin would measure the chord W / cos(slope))
                P3, n3, t3 = frame
                q3 = P3[k] - 0.4 * n3[k]
                wds.append(_width(probe, q3[:2], t3[k][:2], o1, o2, q3[2], dir3=t3[k]) if probe is not None else np.nan)
            else:
                wds.append(_width(probe, Q[k], nrm[k], o1, o2, zfl[k] + 0.4) if probe is not None else np.nan)
            zt = res_body.top_z(mid[None])[0] if res_body else np.nan
            zs0 = body.top_z((mid + (o2 - o1) * 1.5 * nrm[k])[None])[0]
            dps.append(zs0 - zt if np.isfinite(zt) and np.isfinite(zs0) else np.nan)
        if it['tag'] == 'perimeter' and res_body is not None and not p['through_wall']:
            for k_, e_ in enumerate((trim_log.get('perimeter_lip') or {}).get('ends') or []):
                if e_['reason'] != 'crease':
                    continue
                i_ = 0 if k_ == 0 else len(Q) - 1
                tg_ = Q[0] - Q[1] if k_ == 0 else Q[-1] - Q[-2]
                tg_ = tg_ / max(np.linalg.norm(tg_), 1e-12)
                e_['stub_mm'] = stub_to_edge(res_body, Q[i_], tg_, nrm[i_], o1, o2, 0.25 * body.diag)
        meas[it['tag']] = {'width_mm_median': _nanmed(wds), 'width_mm_range': _nanrange(wds), 'floor_hit_below_neighbour_surface_mm_median': _nanmed(dps)}
    v0, v1 = cb.volume(solid), (cb.volume(bs[0]) if bs else 0.0)
    quality = {'perimeter_roughness': rough if Pp is not None else None, 'roughness_max_dev_mm': float(p['roughness_max_dev_mm']),
               'max_curvature_sign_changes': max(int(p['max_curvature_sign_changes']), int((per or {}).get('allowed_curvature_sign_changes') or 0)), 'window_gap': (wlog or {}).get('gap_alignment')}
    return {'worker': WORKER_VERSION, 'quality': quality, 'warnings': warnings, 'symmetry': sym_log, 'trim': trim_log, 'spec': {'slot_width_mm': W, 'gap_width_mm': GW, 'depth_mm': DEPTH, 'window_depth_mm': WDEPTH},
            'cutters': info, 'window': wlog, 'measured': meas, 'boolean': boolean_log,
            'result': {'solids_after_cut': len(sols), 'piece_volumes_mm3': vols[:5], 'valid': bool(bs and cb.is_valid(bs[0])), 'solids_in_step': len(bs),
                       'pieces_written': len(files.get('pieces') or []) or None, 'pieces_valid': bool(all(cb.is_valid(x) for x in extra)) if extra else None,
                       'faces': len(cb.faces(bs[0])) if bs else 0, 'faces_below_1mm2': int(sum(cb.area(f) < 1.0 for f in cb.faces(bs[0]))) if bs else 0,
                       'faces_below_0p05mm2': int(sum(cb.area(f) < 0.05 for f in cb.faces(bs[0]))) if bs else 0, 'volume_before_mm3': v0, 'volume_after_mm3': v1, 'removed_mm3': v0 - v1,
                       'unmeshed_faces_after_reimport': (GF.unmeshed_faces(bs[0], 0.01) if bs else [])},
            'files': files, 'params_used': p}


def stub_to_edge(res_body, e, t, nrm, o1, o2, reach, step=0.25):
    """Length (mm) of the uncut skin between a slot end and the outer edge of the PRODUCED shell, measured on the result solid: walk from the end
    point e along its outward tangent t (unit xy) until the whole band (both walls and the centre) has no skin below any more. 0 = the end is
    already off the shell (open end through the edge); None = no edge within reach."""
    s = 0.0
    while s <= reach:
        c = e + t * s
        q = np.array([c + o * nrm for o in (o1, 0.5 * (o1 + o2), o2)])
        if np.isnan(res_body.top_z(q)).all():
            return float(s)
        s += step
    return None


def step_round_trip_unmeshed(solid, tmp_dir, defl: float = 0.01) -> list[int]:
    """Write the solid to a temporary STEP in tmp_dir, read it back and return the faces (explorer order) that BRepMesh drops after the
    re-import. Only the written file counts: an in-memory ShapeFix (tolerances, pcurves, removed micro edges) is not stored in STEP, the reader
    rebuilds pcurves from the 3D curves and re-inserts a degenerated bridging edge wherever two consecutive 3D curves miss each other by more
    than the file precision, and such a face is dropped by BRepMesh in every downstream tool."""
    import io
    import contextlib
    from cadmcp_brain.studio import cad_brep_lib as cb
    from cadmcp_brain.studio import mouse_groove_fill_worker as GF
    tmp_dir = Path(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    p = tmp_dir / '_round_trip_probe.step'
    with contextlib.redirect_stdout(io.StringIO()):
        cb.write_step(solid, p)
    back = cb.solids(cb.read_step(p))
    try:
        p.unlink()
    except OSError:
        pass
    if len(back) != 1:
        return list(range(len(cb.faces(solid))))
    return GF.unmeshed_faces(back[0], defl, clean=True)


def cut_gated(solid, cutters, diag, tmp_dir=None, keep_all=False):
    """Boolean cut of all cutters from the shell, gated. Where the exact boolean (fuzzy 0) leaves a solid that fails BRepCheck (the ramped
    slot ends meet the surface at near-tangent wedges: a sewn-edge tolerance mismatch gives shell BadOrientationOfSubshape although every
    face is valid), the cut is repeated with a growing fuzzy value (relative to the shell bbox diagonal, ladder FUZZY_LADDER_REL; the cutters
    themselves are sewn at 5e-3 mm). Each attempt is healed (ShapeFix_Solid, UnifySameDomain kept only if still valid) and accepted only if
    done + valid + a solid left + volume removed >0 and <= the cutter volume (bookkeeping) + every face still tessellates after a STEP round
    trip (tmp_dir given). The round trip is the gate that matters downstream: the exact cut leaves intersection curves that miss the
    neighbouring edge by ~1e-4 mm at a shared vertex (cutter wall x skin x rim); in memory ShapeFix hides it, but the STEP reader re-creates a
    degenerated bridging edge and BRepMesh then drops the whole skin face (LH2: one 140 mm2 face, which broke carve_shell and wheel_window).
    A larger fuzzy value merges those vertices in the Boolean itself, so the fix is geometric and survives the file. The first accepted attempt
    wins; if none passes the least-bad one is returned and the caller's BREP_VALID / TESSELLATES gates fail. Fuzzy values stay far below the
    0.1 mm minimum slot width. keep_all (through_wall): every piece is healed and gated (valid, meshable after the round trip), the
    bookkeeping uses the sum of the pieces, and the healed pieces (largest first) are returned as the third value; otherwise only the
    largest piece is kept and the others count as removed material."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopTools import TopTools_ListOfShape
    from OCP.TopoDS import TopoDS
    from cadmcp_brain.studio import cad_brep_lib as cb
    v0 = cb.volume(solid)
    vcut = sum(cb.volume(c) for c in cutters)
    attempts, best, best_valid = [], None, False
    def one_cut(shapes, tools_, fz):
        tools = TopTools_ListOfShape()
        for c in tools_:
            tools.Append(c)
        args = TopTools_ListOfShape()
        for a in shapes:
            args.Append(a)
        op = BRepAlgoAPI_Cut()
        op.SetArguments(args)
        op.SetTools(tools)
        op.SetRunParallel(True)
        if fz > 0:
            op.SetFuzzyValue(fz)
        op.Build()
        return op
    ladder = [(rel, False) for rel in FUZZY_LADDER_REL] + ([(rel, True) for rel in FUZZY_LADDER_REL] if keep_all else [])
    for rel, sequential in ladder:
        fz = float(rel) * diag
        if sequential:
            # through_wall fallback: one cutter at a time, each step on all current pieces (the all-at-once cut can silently skip tools
            # where the normal-following bands overlap at the gap / perimeter / window junctions: on the test fixture it removed one tool's
            # volume out of four); tried after the all-at-once ladder because sequential cuts leave more junction slivers
            cur, done = [solid], True
            for c in cutters:
                op = one_cut(cur, [c], fz)
                if not op.IsDone():
                    done = False
                    break
                cur = cb.solids(op.Shape())
            rec = {'fuzzy_mm': fz, 'done': done, 'sequential': True}
            attempts.append(rec)
            if not done:
                continue
            sols = cur
        else:
            op = one_cut([solid], cutters, fz)
            rec = {'fuzzy_mm': fz, 'done': bool(op.IsDone()), 'sequential': False}
            attempts.append(rec)
            if not op.IsDone():
                continue
            sols = cb.solids(op.Shape())
        if not sols:
            rec['solids'] = 0
            continue
        def heal(x):
            sfx = ShapeFix_Solid(TopoDS.Solid_s(x))
            sfx.Perform()
            fixed = sfx.Solid()
            x = TopoDS.Solid_s(fixed) if fixed.ShapeType() == TopAbs_SOLID else max(cb.solids(fixed), key=cb.volume)   # ShapeFix may hand back a compound
            try:
                u_ = ShapeUpgrade_UnifySameDomain(x, True, True, False)
                u_.Build()
                x2 = cb.solids(u_.Shape())
            except Exception:                   # Unify can throw (GCE2d_MakeLine) on a small piece; keep the un-unified solid
                x2 = None
            return x2[0] if x2 and cb.is_valid(x2[0]) else x
        kept = sorted((heal(x) for x in sols), key=cb.volume, reverse=True) if keep_all else [heal(max(sols, key=cb.volume))]
        so = kept[0]
        removed = v0 - sum(cb.volume(x) for x in kept)
        rec.update(solids=len(sols), valid=bool(all(cb.is_valid(x) for x in kept)), removed_mm3=float(removed), faces=len(cb.faces(so)))
        bookkeeping = 0.0 < removed <= vcut * 1.001
        rec['volume_bookkeeping_ok'] = bool(bookkeeping)
        meshable = True
        if rec['valid'] and bookkeeping and tmp_dir is not None:
            rec['unmeshed_faces_after_step_round_trip'] = [f for x in kept for f in step_round_trip_unmeshed(x, tmp_dir)]
            meshable = not rec['unmeshed_faces_after_step_round_trip']
        cand = (so, sols, kept)
        if rec['valid'] and bookkeeping and meshable:
            best = cand
            rec['accepted'] = True
            break
        if best is None or (rec['valid'] and bookkeeping and not best_valid):
            best, best_valid = cand, bool(rec['valid'] and bookkeeping)     # least-bad fallback: the first solid, else the first valid + bookkept one
    if best is None:
        raise WorkerError('CLICK_SLOTS_BOOLEAN', 'The boolean cut failed.', {'attempts': attempts})
    so, sols, kept = best
    vols = sorted([cb.volume(s) for s in sols], reverse=True)
    return so, {'attempts': attempts, 'fuzzy_mm_used': attempts[-1]['fuzzy_mm'] if attempts[-1].get('accepted') else None, 'pieces': len(sols),
                'piece_volumes_mm3': vols[:5]}, kept


def _width(shape, q, nrm, o1, o2, z, dir3=None):
    from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    c = q + 0.5 * (o1 + o2) * nrm
    d = (float(nrm[0]), float(nrm[1]), 0.0) if dir3 is None else tuple(map(float, dir3))
    it = BRepIntCurveSurface_Inter()
    it.Init(shape, gp_Lin(gp_Pnt(float(c[0]), float(c[1]), float(z)), gp_Dir(*d)), 1e-7)
    ts = []
    while it.More():
        ts.append(it.W())
        it.Next()
    ts = np.asarray(ts)
    pos, neg = ts[ts > 0], ts[ts < 0]
    if not len(pos) or not len(neg):
        return np.nan
    return float(pos.min() - neg.max())


def _nanmed(a):
    a = np.asarray(a, float)
    a = a[np.isfinite(a)]
    return float(np.median(a)) if a.size else None


def _nanrange(a):
    a = np.asarray(a, float)
    a = a[np.isfinite(a)]
    return [float(a.min()), float(a.max())] if a.size else None


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
