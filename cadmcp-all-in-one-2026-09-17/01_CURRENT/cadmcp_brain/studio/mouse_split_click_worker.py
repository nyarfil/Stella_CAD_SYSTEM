"""Click-region split of a mouse top shell (brain_mouse_split_click_region). SUBPROCESS WORKER (server python: OCP, numpy).

Run as:  <server python> -I mouse_split_click_worker.py request.json      (result = last stdout line, JSON)

Port of the approved `automation/click_split.py` (LH2 v17) to plain OCP. From a top shell whose click groove is filled flush (or the shell with the groove:
the fill of mouse_groove_fill_worker runs first) it carves
  plate_L / plate_R = skin layer under the click footprint, `plate_thickness_mm` thick along the skin normal, split at the centre slot line;
  shell_open        = the shell minus the click recess (footprint + margin + outer groove, down to skin offset -(thickness + gap)) minus the wheel window.
Every failure remedy of the project is built in (spec S4):
  * outlines are rebuilt as ONE smooth periodic spline (offset +outline_margin for the plates, + outline_margin + outer_groove for the shell cut), never the raw
    projected patch edges: their prism walls would lie on the skin's own seam edges and the Booleans would silently fail;
  * cutting slabs start `slab_top_mm` ABOVE the skin (no coincident top); the plate top comes from the skin itself;
  * Offset surfaces fail/hang: the true normal offset is sampled on a fit_n x fit_n uv grid and fitted as a C2 B-spline (GeomAPI_PointsToBSplineSurface,
    fit_tol); a slab = two fitted faces + four ruled faces, sewn;
  * every Boolean wrapper rejects a None / empty / failed result (SPLIT_BOOLEAN_EMPTY), never continues on it;
  * volumes are mesh volumes (deflection mesh_deflection_mm), the B-rep volume of these B-spline solids moves by ~100 mm3 between methods;
  * projected patch edges miss by up to 0.02-0.05 (fuzzy-Boolean slivers upstream): joined in wire order by shared vertices (project_outline), gated.
Gates (all raise): volume bookkeeping residual <= book_tol_mm3, plates not larger than the removed region, |V_L - V_R| / mean <= sym_tol, zero interference
(shell-L, shell-R, L-R), one valid shell solid, ray thickness of the plate and ray gap under it within the tolerances on >= ray_pass of the rays.
"""
from __future__ import annotations
import math
import sys
from pathlib import Path
from typing import Any

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_CompCurve, BRepAdaptor_Curve
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeSolid,
                                BRepBuilderAPI_MakeWire, BRepBuilderAPI_Sewing, BRepBuilderAPI_Transform)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepFill import BRepFill
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet2d
from OCP.BRepGProp import BRepGProp
from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
from OCP.BRepLib import BRepLib
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakePrism
from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
from OCP.GCPnts import GCPnts_AbscissaPoint
from OCP.GProp import GProp_GProps
from OCP.Geom import Geom_Plane, Geom_TrimmedCurve
from OCP.GeomAPI import GeomAPI_Interpolate, GeomAPI_PointsToBSplineSurface, GeomAPI_ProjectPointOnCurve
from OCP.GeomAdaptor import GeomAdaptor_Curve
from OCP.GeomAbs import GeomAbs_C2
from OCP.GeomLProp import GeomLProp_SLProps
from OCP.GeomProjLib import GeomProjLib
from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds, ShapeAnalysis_Wire
from OCP.ShapeFix import ShapeFix_Solid, ShapeFix_Wire
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TColgp import TColgp_Array2OfPnt, TColgp_HArray1OfPnt
from OCP.TopAbs import TopAbs_REVERSED
from OCP.TopTools import TopTools_HSequenceOfShape, TopTools_ListOfShape
from OCP.TopoDS import TopoDS, TopoDS_Vertex
from OCP.gp import gp_Dir, gp_Lin, gp_Pln, gp_Pnt, gp_Trsf, gp_Vec

from cadmcp_brain.studio import cad_brep_lib as L
from cadmcp_brain.studio import mouse_groove_fill_worker as GF
from cadmcp_brain.studio import mouse_parts_lib as P
from cadmcp_brain.studio.scan_cad_common import WorkerError, worker_main

WORKER_VERSION = 'mouse_split_click/4'
# Defaults = the approved v17 process (automation/click_split.py DEFAULTS, run_v17.py): plate 1.1, gap 1.0, outer groove 0.5, centre slot 1.0, outline +0.1,
# recess +0.6 (= margin + groove), slab top +5, fit 161 x 161 / 2e-5, mesh deflection 0.003, bookkeeping 30 mm3, symmetry 2 %, rays 1.1 +-0.002 / 1.0 +-0.01 on >= 97 %.
DEFAULTS = {'plate_thickness_mm': 1.1, 'gap_mm': 1.0, 'outer_groove_mm': 0.5, 'centre_slot_mm': 1.0,
            'window': None, 'cut_window': True, 'wheel_part': None, 'wheel_margin_mm': 0.0, 'window_corner_r_mm': 0.0, 'lateral_axis': 'auto',
            'centre_source': 'patches', 'centre_mm': None, 'uv_margin': None, 'outline_margin_mm': 0.1, 'slab_top_mm': 5.0,
            'fit_n': 161, 'fit_tol': 2e-5, 'outline_step_mm': 0.15, 'mesh_deflection_mm': 0.003, 'book_tol_mm3': 30.0, 'sym_tol': 0.02,
            'ray_n': 400, 'ray_tol_t_mm': 0.002, 'ray_tol_gap_mm': 0.01, 'ray_pass': 0.97, 'patch_faces': None, 'min_patch_area_mm2': None,
            'shell_part': None, 'skin_part': None, 'interference_tol_mm3': 0.01,
            'max_floor_width_mm': 1.2, 'floor_min_nz': 0.8, 'wall_max_abs_nz': 0.2, 'min_groove_length_mm': None, 'sew_tol_mm': 0.02, 'planar_tol_mm': 0.02}
# LH2 verification recipe (explicit arguments, NOT defaults): window {w 19.12, h 8.32, r 3.33, cx 97.325, cy -0.01}, uv_margin 3.0, min_patch_area_mm2 300, min_groove_length_mm 20.
# Conventions: +z is up (the skin faces up).  The mirror plane is MEASURED: the lateral axis is the plan axis (x or y) along which the two click patches are separated
# (or lateral_axis 'x'/'y'); plate "L" is the side with the smaller coordinate along that axis, "R" the larger (a naming by side of the plane, not a handedness claim).
# The wheel window is a rectangle in the model x/y plan: w along x, h along y, centre (cx, cy).
# split() works with the lateral axis = y (its numerics are the verified ones); a model whose patches are separated along x is turned by +90 deg about z first
# (x -> y, low x stays low) and every result is turned back, so the output frame is always the input frame.
LAT = 1
CODE = 'SPLIT'


def fail(code: str, msg: str, details: dict | None = None):
    raise WorkerError(f'{CODE}_{code}', msg, details or {})


# ---------------------------------------------------------------- guards / measures
def boolean(kind: str, a, b, what: str, fuzzy: float = 0.0):
    """Common / Cut; None for a failed run. Callers use req() when an empty result is an error."""
    op = BRepAlgoAPI_Common() if kind == 'common' else BRepAlgoAPI_Cut()
    la, lt = TopTools_ListOfShape(), TopTools_ListOfShape()
    la.Append(a)
    lt.Append(b)
    op.SetArguments(la)
    op.SetTools(lt)
    op.SetRunParallel(True)
    if fuzzy > 0:
        op.SetFuzzyValue(fuzzy)
    op.Build()
    if not op.IsDone():
        return None
    return op.Shape()


def req(shape, what: str):
    """Boolean results must hold a solid: OCC returns an empty compound (or nothing) on silent failure."""
    if shape is None or not L.solids(shape):
        fail('BOOLEAN_EMPTY', f'{what}: the Boolean returned nothing (silent OCC failure).', {'step': what})
    return shape


def vsum(shape, defl: float) -> float:
    return 0.0 if shape is None else sum(GF.mesh_volume(q, defl) for q in L.solids(shape))


def biggest(shape):
    return max(L.solids(shape), key=L.volume)


def prop_center(face) -> np.ndarray:
    g = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, g)
    return np.array(g.CentreOfMass().Coord())


def plane_normal_z(face) -> float:
    s = BRep_Tool.Surface_s(face)
    if type(s).__name__ != 'Geom_Plane':
        fail('NOT_PLANAR', 'An outline face is not planar.')
    z = s.Axis().Direction().Z()
    return -z if face.Orientation() == TopAbs_REVERSED else z


def up_face(face):
    return face if plane_normal_z(face) > 0 else TopoDS.Face_s(face.Reversed())


def rot90(shape, sign: int):
    t = gp_Trsf()
    t.SetValues(0.0, -float(sign), 0.0, 0.0, float(sign), 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0)      # exact quarter turn (no cos(pi/2) noise)
    return BRepBuilderAPI_Transform(shape, t, True).Shape()


def translate(shape, dx=0.0, dy=0.0, dz=0.0):
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(dx, dy, dz))
    return BRepBuilderAPI_Transform(shape, t, True).Shape()


# ---------------------------------------------------------------- outlines
_PLN = Geom_Plane(gp_Pln(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)))


OUTLINE_CONNECT_TOL = 0.02     # mm: a projected edge shorter than this is noise, never geometry (fuzzy-Boolean slivers on the patch rim)
OUTLINE_MAX_GAP = 0.1          # mm: largest jump between consecutive projected edge ends that is still closed by a shared vertex


def _param_nearest(pt, curve) -> float:
    """Parameter of the point of `curve` nearest to `pt`: the inner extrema (GeomAPI_ProjectPointOnCurve) and both ends (an end minimum is not an
    extremum and would leave the projector empty)."""
    cands = [(curve.Value(u).Distance(pt), u) for u in (curve.FirstParameter(), curve.LastParameter())]
    pr = GeomAPI_ProjectPointOnCurve(pt, curve)
    for k in range(1, pr.NbPoints() + 1):
        cands.append((pr.Distance(k), pr.Parameter(k)))
    return float(min(cands)[1])


def project_outline(face):
    """Outer wire of a 3D face projected to z = 0 (exact curves), as a planar face with normal +Z.
    The edges are taken in wire order (BRepTools_WireExplorer), projected one by one, and consecutive ends are joined by ONE shared vertex at
    their midpoint (tolerance = the gap), so the wire is closed by construction instead of by a tolerance-driven re-chaining: a fuzzy Boolean
    upstream leaves 0.01-0.03 mm slivers with 0.05 mm vertex tolerances on the patch rim, and ShapeAnalysis_FreeBounds / ShapeFix_Wire at 0.02 mm
    then produced an open, self-intersecting wire whose face vanished in the footprint fuse (one plate lost, SYMMETRY 156 %). Projected edges
    shorter than OUTLINE_CONNECT_TOL are dropped (their span becomes the shared vertex); a gap above OUTLINE_MAX_GAP, or a result that is not one
    closed, valid, non-self-intersecting wire, is OUTLINE."""
    BRepLib.BuildCurves3d_s(face)
    items = []                                                                  # (projected curve, p_start, p_end) in wire order
    skipped = []
    we = BRepTools_WireExplorer(BRepTools.OuterWire_s(face), TopoDS.Face_s(face))
    while we.More():
        e = we.Current()
        we.Next()
        if BRep_Tool.Degenerated_s(e) or GF.edge_length(e) < 1e-3:
            continue
        ad = BRepAdaptor_Curve(e)
        c = BRep_Tool.Curve_s(e, 0.0, 0.0)
        pc = GeomProjLib.ProjectOnPlane_s(Geom_TrimmedCurve(c, ad.FirstParameter(), ad.LastParameter()), _PLN, gp_Dir(0, 0, 1), True)
        p0, p1 = pc.Value(pc.FirstParameter()), pc.Value(pc.LastParameter())
        if e.Orientation() == TopAbs_REVERSED:
            p0, p1 = p1, p0
        if GCPnts_AbscissaPoint.Length_s(GeomAdaptor_Curve(pc)) < OUTLINE_CONNECT_TOL:
            skipped.append(float(GCPnts_AbscissaPoint.Length_s(GeomAdaptor_Curve(pc))))
            continue
        items.append((pc, p0, p1))
    if len(items) < 3:
        fail('OUTLINE', f'The projected patch outline has only {len(items)} usable edges.', {'skipped_projected_edges_mm': skipped})
    bld = BRep_Builder()
    verts, gaps = [], []
    for i in range(len(items)):                                                 # vertex i = junction between item i-1 (end) and item i (start)
        a, b = items[i - 1][2], items[i][1]
        gap = float(a.Distance(b))
        gaps.append(gap)
        v = TopoDS_Vertex()
        bld.MakeVertex(v, gp_Pnt(0.5 * (a.X() + b.X()), 0.5 * (a.Y() + b.Y()), 0.0), max(1e-6, 0.6 * gap))
        verts.append(v)
    if max(gaps) > OUTLINE_MAX_GAP:
        fail('OUTLINE', f'The projected patch outline has a {max(gaps):.3f} mm gap between consecutive edges (limit {OUTLINE_MAX_GAP}).',
             {'gaps_mm': gaps, 'skipped_projected_edges_mm': skipped})
    mw = BRepBuilderAPI_MakeWire()
    for i, (pc, p0, p1) in enumerate(items):
        va, vb = verts[i], verts[(i + 1) % len(items)]
        fwd = pc.Value(pc.FirstParameter()).Distance(p0) <= pc.Value(pc.FirstParameter()).Distance(p1)
        # re-trim the curve at the shared vertices (closest points), so neighbouring edges meet instead of overlapping by the closed gap
        ua, ub = (_param_nearest(BRep_Tool.Pnt_s(v), pc) for v in (va, vb))
        lo, hi = (min(ua, ub), max(ua, ub))
        if hi - lo > 1e-9:
            pc = Geom_TrimmedCurve(pc, lo, hi)
        me = BRepBuilderAPI_MakeEdge(pc, va, vb) if fwd else BRepBuilderAPI_MakeEdge(pc, vb, va)
        if not me.IsDone():
            fail('OUTLINE', 'A projected outline edge could not be built on its shared vertices.', {'edge': i, 'gaps_mm': gaps})
        mw.Add(me.Edge())
    if not mw.IsDone():
        fail('OUTLINE', 'The projected outline edges do not chain into one wire.', {'gaps_mm': gaps, 'skipped_projected_edges_mm': skipped})
    f = up_face(BRepBuilderAPI_MakeFace(mw.Wire(), True).Face())
    w = BRepTools.OuterWire_s(f)
    saw = ShapeAnalysis_Wire(w, f, 1e-4)
    closed, selfint, valid = bool(BRep_Tool.IsClosed_s(w)), bool(saw.CheckSelfIntersection()), bool(BRepCheck_Analyzer(f).IsValid())
    if not (closed and valid) or selfint:
        fail('OUTLINE', 'The projected patch outline is not one closed, valid, non-self-intersecting wire.',
             {'closed': closed, 'valid': valid, 'self_intersecting': selfint, 'gaps_mm': gaps, 'skipped_projected_edges_mm': skipped,
              'edges_mm': [float(GF.edge_length(e)) for e in L.explore(w, 'edge')]})
    return f


def wire_length(w) -> float:
    g = GProp_GProps()
    BRepGProp.LinearProperties_s(w, g)
    return float(g.Mass())


def smooth_offset(face, off: float, step: float):
    """Outer outline of a planar face offset by `off` (+ out / - in), rebuilt as ONE periodic spline. -> (face, polygon Nx2)."""
    ow = BRepTools.OuterWire_s(face)
    curve = BRepAdaptor_CompCurve(ow)
    total = GCPnts_AbscissaPoint.Length_s(curve)
    n = int(wire_length(ow) / step)
    pts = []
    for i in range(n):
        par = GCPnts_AbscissaPoint(curve, total * i / n, curve.FirstParameter()).Parameter()
        q = curve.Value(par)
        pts.append((q.X(), q.Y()))
    pts = np.array(pts)
    A = 0.5 * np.sum(pts[:, 0] * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1) * pts[:, 1])
    t = np.roll(pts, -1, 0) - np.roll(pts, 1, 0)
    t /= np.linalg.norm(t, axis=1)[:, None]
    nrm = np.stack([t[:, 1], -t[:, 0]], 1) * (1 if A > 0 else -1)
    op = pts + off * nrm
    keep = np.array([q for q in op if np.min(np.hypot(pts[:, 0] - q[0], pts[:, 1] - q[1])) > abs(off) * 0.9])
    sel = keep[::2]
    arr = TColgp_HArray1OfPnt(1, len(sel))
    for i, (x, y) in enumerate(sel):
        arr.SetValue(i + 1, gp_Pnt(float(x), float(y), 0.0))
    it = GeomAPI_Interpolate(arr, True, 1e-6)
    it.Perform()
    if not it.IsDone():
        fail('OUTLINE', 'The offset outline spline could not be interpolated.', {'offset_mm': off})
    ed = BRepBuilderAPI_MakeEdge(it.Curve()).Edge()
    f = up_face(BRepBuilderAPI_MakeFace(BRepBuilderAPI_MakeWire(ed).Wire(), True).Face())
    return f, keep


def prism(face2d, z0: float, h: float):
    s = BRepPrimAPI_MakePrism(translate(face2d, dz=z0), gp_Vec(0, 0, h)).Shape()
    ss = L.solids(s)
    if len(ss) != 1 or L.volume(ss[0]) <= 0:
        fail('PRISM', 'A cutting prism is empty or inverted.')
    return ss[0]


def rect_face(x0: float, x1: float, y0: float, y1: float, r: float = 0.0):
    mp = BRepBuilderAPI_MakePolygon()
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        mp.Add(gp_Pnt(x, y, 0.0))
    mp.Close()
    face = up_face(BRepBuilderAPI_MakeFace(mp.Wire(), True).Face())
    if r <= 0:
        return face
    fl = BRepFilletAPI_MakeFillet2d(face)
    for v in _vertices(face):
        fl.AddFillet(v, r)
    fl.Build()
    if not fl.IsDone():
        fail('WINDOW', 'The rounded window outline could not be built (radius too large?).', {'r': r})
    return up_face(TopoDS.Face_s(fl.Shape()))


def _vertices(shape):
    from OCP.TopAbs import TopAbs_VERTEX
    from OCP.TopExp import TopExp_Explorer
    ex = TopExp_Explorer(shape, TopAbs_VERTEX)
    seen, out = [], []
    while ex.More():
        v = TopoDS.Vertex_s(ex.Current())
        if not any(v.IsSame(s) for s in seen):
            seen.append(v)
            out.append(v)
        ex.Next()
    return out


def fuse_faces(faces: list) -> Any:
    op = BRepAlgoAPI_Fuse()
    la, lt = TopTools_ListOfShape(), TopTools_ListOfShape()
    la.Append(faces[0])
    for f in faces[1:]:
        lt.Append(f)
    op.SetArguments(la)
    op.SetTools(lt)
    op.SetRunParallel(True)
    op.Build()
    if not op.IsDone():
        fail('FOOTPRINT', 'The footprint union failed.')
    u = ShapeUpgrade_UnifySameDomain(op.Shape(), True, True, True)
    u.Build()
    return u.Shape()


# ---------------------------------------------------------------- offset slabs
class Skin:
    def __init__(self, patches, p: dict[str, Any]):
        self.s = BRep_Tool.Surface_s(patches[0])
        s2 = BRep_Tool.Surface_s(patches[1])
        if [round(x, 6) for x in self.s.Bounds()] != [round(x, 6) for x in s2.Bounds()]:
            fail('PATCH_SURFACE', 'The two click patches do not share one skin surface.')
        uv = [BRepTools.UVBounds_s(f) for f in patches]
        U0, U1, V0, V1 = self.s.Bounds()
        m = p['uv_margin']
        if m is None:                                         # one patch-span on every side (clamped to the surface domain)
            m = float(max(max(a[1] for a in uv) - min(a[0] for a in uv), max(a[3] for a in uv) - min(a[2] for a in uv)))
        self.margin = m
        self.u0, self.u1 = max(min(a[0] for a in uv) - m, U0), min(max(a[1] for a in uv) + m, U1)
        self.v0, self.v1 = max(min(a[2] for a in uv) - m, V0), min(max(a[3] for a in uv) + m, V1)
        pr = GeomLProp_SLProps(self.s, (self.u0 + self.u1) / 2, (self.v0 + self.v1) / 2, 1, 1e-6)
        self.sgn = 1 if pr.Normal().Z() > 0 else -1          # +sgn = outward
        self.p = p
        self._grid = None

    def point_normal(self, u: float, v: float):
        pr = GeomLProp_SLProps(self.s, u, v, 1, 1e-6)
        q, n = pr.Value(), pr.Normal()
        return np.array([q.X(), q.Y(), q.Z()]), self.sgn * np.array([n.X(), n.Y(), n.Z()])

    def grid(self):
        """Skin points and outward normals on the fit grid (computed once; every slab face reuses it)."""
        if self._grid is None:
            N = self.p['fit_n']
            Q, Nn = np.zeros((N, N, 3)), np.zeros((N, N, 3))
            for i, u in enumerate(np.linspace(self.u0, self.u1, N)):
                for j, v in enumerate(np.linspace(self.v0, self.v1, N)):
                    Q[i, j], Nn[i, j] = self.point_normal(u, v)
            self._grid = (Q, Nn)
        return self._grid

    def safe_top(self, top: float, floor_mm: float = 0.25, min_jacobian: float = 0.3) -> tuple[float, list[float]]:
        """Largest slab top offset <= top (halving) whose outward offset surface does not fold: on the fit grid the area element of
        Q + d N must stay >= min_jacobian x that of Q everywhere. Where the skin is concave with radius R < d the offset folds over itself, the slab
        self-intersects and the Booleans with it fail silently (the scan skin of a mouse has dishes of R ~ 2 mm; the LH2 skin does not).
        The top only has to clear the skin (the solids being cut lie below it), so a smaller top changes no result. -> (top used, tried)."""
        Q, Nn = self.grid()
        Qu, Qv = np.diff(Q, axis=0)[:, :-1], np.diff(Q, axis=1)[:-1, :]
        Nc = Nn[:-1, :-1]
        base = np.einsum('ijk,ijk->ij', np.cross(Qu, Qv), Nc)
        tried, d = [], float(top)
        while True:
            O = Q + d * Nn
            Ou, Ov = np.diff(O, axis=0)[:, :-1], np.diff(O, axis=1)[:-1, :]
            ratio = np.einsum('ijk,ijk->ij', np.cross(Ou, Ov), Nc) / np.maximum(np.abs(base), 1e-12)
            tried.append(d)
            if float(ratio.min()) >= min_jacobian or d <= floor_mm:
                return d, tried
            d = max(d / 2.0, floor_mm)

    def fit_offset_face(self, off: float):
        """Clean B-spline fitted to the true normal offset (off > 0 outward)."""
        N = self.p['fit_n']
        Q, Nn = self.grid()
        O = Q + off * Nn
        arr = TColgp_Array2OfPnt(1, N, 1, N)
        for i in range(N):
            for j in range(N):
                arr.SetValue(i + 1, j + 1, gp_Pnt(float(O[i, j, 0]), float(O[i, j, 1]), float(O[i, j, 2])))
        bs = GeomAPI_PointsToBSplineSurface(arr, 3, 8, GeomAbs_C2, self.p['fit_tol']).Surface()
        return BRepBuilderAPI_MakeFace(bs, 1e-6).Face()

    def slab(self, top: float, bottom: float):
        """Solid between the offsets `top` and `bottom` (outward positive): two fitted faces + four ruled faces, sewn."""
        a, b = self.fit_offset_face(top), self.fit_offset_face(bottom)
        sew = BRepBuilderAPI_Sewing(1e-4)
        sew.Add(a)
        sew.Add(b)
        for e1, e2 in zip(L.explore(a, 'edge'), L.explore(b, 'edge')):
            sew.Add(BRepFill.Face_s(e1, e2))
        sew.Perform()
        if sew.NbFreeEdges():
            fail('SLAB', 'Slab sewing left free edges.', {'free_edges': int(sew.NbFreeEdges())})
        shells = L.explore(sew.SewedShape(), 'shell')
        if len(shells) != 1:
            fail('SLAB', 'Slab sewing gave no single shell.')
        fx = ShapeFix_Solid(BRepBuilderAPI_MakeSolid(shells[0]).Solid())
        fx.Perform()
        sol = fx.Solid()
        if not BRepCheck_Analyzer(sol).IsValid() or L.volume(sol) <= 0:
            fail('SLAB', 'Slab solid is invalid.')
        return sol


# ---------------------------------------------------------------- checks
def _inpoly(x: float, y: float, Pg: np.ndarray) -> bool:
    xs, ys = Pg[:, 0], Pg[:, 1]
    xj, yj = np.roll(xs, 1), np.roll(ys, 1)
    return bool((((ys > y) != (yj > y)) & (x < (xj - xs) * (y - ys) / (yj - ys + 1e-30) + xs)).sum() % 2 == 1)


def _hits(shape, start, d) -> list[float]:
    it = BRepIntCurveSurface_Inter()
    it.Init(shape, gp_Lin(gp_Pnt(*map(float, start)), gp_Dir(*map(float, d))), 1e-7)
    h = []
    while it.More():
        h.append(it.W())
        it.Next()
    return sorted(x for x in h if x > 1e-4)


def ray_checks(skin: Skin, poly_plate, plates, shell, p: dict[str, Any], cy: float, win: dict[str, float] | None, ax: int) -> dict[str, Any]:
    rng = np.random.default_rng(11)
    t, gap = p['plate_thickness_mm'], p['gap_mm']
    th, gp, tries = [], [], 0
    while len(th) < p['ray_n'] and tries < 300000:
        tries += 1
        u, v = rng.uniform(skin.u0, skin.u1), rng.uniform(skin.v0, skin.v1)
        q, n = skin.point_normal(u, v)
        if not _inpoly(q[0], q[1], poly_plate):
            continue
        if win and abs(q[0] - win['cx']) < win['w'] / 2 + 0.3 and abs(q[1] - win['cy']) < win['h'] / 2 + 0.3:
            continue
        if abs(q[ax] - cy) < p['centre_slot_mm'] / 2 + 0.3:
            continue
        pl = plates[0] if q[ax] < cy else plates[1]
        h = _hits(pl, q + 0.05 * n, -n)
        if len(h) < 2:
            continue
        th.append(h[1] - h[0])
        g = _hits(shell, q - t * n, -n)
        if g:
            gp.append(g[0])
    if not th or not gp:
        fail('RAYS', 'The ray check found no sample inside the plates.', {'tries': tries})
    th, gp = np.array(th), np.array(gp)
    r = {'thk_n': len(th), 'thk_med': float(np.median(th)), 'thk_p5': float(np.percentile(th, 5)), 'thk_p95': float(np.percentile(th, 95)),
         'thk_ok': float((abs(th - t) <= p['ray_tol_t_mm']).mean()), 'gap_n': len(gp), 'gap_med': float(np.median(gp)),
         'gap_p5': float(np.percentile(gp, 5)), 'gap_p95': float(np.percentile(gp, 95)), 'gap_ok': float((abs(gp - gap) <= p['ray_tol_gap_mm']).mean())}
    if r['thk_ok'] < p['ray_pass'] or r['gap_ok'] < p['ray_pass']:
        fail('RAY_CHECK', 'Ray check failed: plate thickness or the gap under the plates is off on too many rays.', {'rays': r, 'need_share': p['ray_pass']})
    return r


# ---------------------------------------------------------------- patches
def order_patches(faces: list, mode: str):
    """-> (faces ordered low -> high along the lateral axis, axis index 0 = x / 1 = y).  auto = the plan axis with the larger centre separation."""
    c = [prop_center(f) for f in faces]
    d = np.abs(c[0] - c[1])[:2]
    ax = {'x': 0, 'y': 1}[mode] if mode in ('x', 'y') else int(d[1] >= d[0])
    if d[ax] < 1e-3:
        fail('LATERAL_AXIS', 'The two click patches are not separated along the lateral axis.', {'lateral_axis': mode, 'centre_separation_xy': [float(v) for v in d]})
    return [faces[i] for i in sorted(range(2), key=lambda i: c[i][ax])], ax


def derive_window(path: str | None, prm: dict[str, Any]) -> dict[str, float]:
    """Wheel window = plan (x/y) bbox of the wheel part grown by wheel_margin_mm on every side; corner radius window_corner_r_mm."""
    if not path:
        fail('WINDOW_REQUIRED', 'cut_window is true but neither window nor a wheel part is given: pass window {w, h, cx, cy[, r]} or wheel_step_path (+ wheel_part), or cut_window = false.')
    parts, _ = P.load_parts([path])
    name = prm['wheel_part']
    if name is None:
        if len(parts) != 1:
            fail('WINDOW_REQUIRED', f'The wheel STEP holds {len(parts)} parts: name the wheel with wheel_part.', {'known': sorted(parts)})
        name = next(iter(parts))
    elif name not in parts:
        fail('WINDOW_REQUIRED', f'The wheel STEP has no part "{name}".', {'known': sorted(parts)})
    bb, m = L.bbox(parts[name]), prm['wheel_margin_mm']
    win = {'w': float(bb[3] - bb[0] + 2 * m), 'h': float(bb[4] - bb[1] + 2 * m), 'r': float(prm['window_corner_r_mm']), 'cx': float((bb[0] + bb[3]) / 2), 'cy': float((bb[1] + bb[4]) / 2)}
    if not 0 <= win['r'] < min(win['w'], win['h']) / 2:
        fail('WINDOW_REQUIRED', 'window_corner_r_mm must be below half the smaller wheel window side.', {'window': win})
    return win


def detect_patches(T: GF.Topo, det: dict[str, Any], prm: dict[str, Any]):
    """The two click patches = the big upward faces next to the INNER groove wall (the wall with exactly two of them; the plates are the smaller islands)."""
    info = T.info
    big_up = {i for i, d in enumerate(info) if d['area'] > prm['min_patch_area_mm2'] and d['nz'] > 0.5}
    cands = []
    for wl in det['walls'] or []:
        pats = sorted(k for k in T.adj[wl] if k in big_up)
        if len(pats) == 2:
            cands.append((sum(info[k]['area'] for k in pats), wl, pats))
    if not cands:
        fail('PATCHES', 'No groove wall has exactly two big upward faces next to it (the two click patches).',
             {'walls': det['walls'], 'min_patch_area_mm2': prm['min_patch_area_mm2']})
    cands.sort()
    _, wl, pats = cands[0]
    faces, ax = order_patches([T.faces[k] for k in pats], prm['lateral_axis'])           # low side first
    pats = sorted(pats, key=lambda k: prop_center(T.faces[k])[ax])
    return faces, {'inner_wall': wl, 'patches': pats, 'ambiguous_walls': len(cands) > 1, 'lateral_axis': 'xy'[ax]}


# ---------------------------------------------------------------- hand-off to the next stages
def unify_gated(shell):
    """Merge faces on one underlying surface (the pocket wall of the tool is one extrusion face, the Boolean splits it where it meets edges of the
    filled skin): the carve stage expects ONE plate-outline step face. Accepted only if the result is one valid solid of the same volume and bbox with
    no more faces; else the shell is kept as it is. -> (shell, log)"""
    n0, v0, b0 = len(L.faces(shell)), L.volume(shell), L.bbox(shell)
    u = ShapeUpgrade_UnifySameDomain(shell, True, True, False)
    u.Build()
    ss = L.solids(u.Shape())
    ok = len(ss) == 1 and bool(BRepCheck_Analyzer(ss[0]).IsValid()) and len(L.faces(ss[0])) <= n0
    ok = ok and abs(L.volume(ss[0]) - v0) <= 1e-6 * abs(v0) and float(np.abs(L.bbox(ss[0]) - b0).max()) <= 1e-3
    log = {'faces_before': n0, 'faces_after': len(L.faces(ss[0])) if ss else None, 'applied': bool(ok)}
    return (ss[0] if ok else shell), log


def face_samples(shell, defl: float = 0.05, per_face: int = 60, seed: int = 7):
    """-> list per face (explorer order) of dict(points Nx3 (mesh vertices), mean_n (area weighted), coherence, area)."""
    tm = L.tessellate(shell, defl, 0.3)
    V, T, FID = tm['V'], tm['T'], tm['FID']
    rng = np.random.default_rng(seed)
    out = []
    for k in range(len(L.faces(shell))):
        tri = T[FID == k]
        if not len(tri):
            out.append({'vertical': 0.0, 'points': np.zeros((0, 3)), 'mean_n': np.zeros(3), 'coherence': 0.0, 'area': 0.0})
            continue
        cr = np.cross(V[tri[:, 1]] - V[tri[:, 0]], V[tri[:, 2]] - V[tri[:, 0]])
        a = np.linalg.norm(cr, axis=1)
        nsum = cr.sum(0)
        pts = V[np.unique(tri)]
        if len(pts) > per_face:
            pts = pts[rng.choice(len(pts), per_face, replace=False)]
        nz = cr[:, 2] / np.maximum(a, 1e-12)
        out.append({'vertical': float(a[np.abs(nz) < 0.35].sum() / max(a.sum(), 1e-12)), 'points': pts, 'mean_n': nsum / max(np.linalg.norm(nsum), 1e-12), 'coherence': float(np.linalg.norm(nsum) / max(a.sum(), 1e-12)),
                    'area': float(0.5 * a.sum())})
    return out


def carve_roles(shell, skin_surface, depth: float, tol: float = 0.15) -> dict[str, Any]:
    """Face roles of the opened shell for brain_mouse_carve_shell (indices = explorer order of `shell` as read from shell_open.step).
    Defined by the construction, measured on the faces: the click recess is `depth` (= plate thickness + gap) below the skin.
      floor = upward faces (mean nz > 0.5) whose points all lie `depth` +- tol below the shared skin surface (distance to the skin B-spline);
      step  = near-vertical faces (>90 % of the area with |nz| < 0.35; a closed wall has no meaningful mean normal) that touch a floor face and run from the skin (min distance < tol) down to the floor
              (max distance = depth +- tol): the plate-outline wall. The window walls reach through the shell (max distance > depth + tol) and
              side-button or other grooves are not that deep, so neither is taken;
      bearing = faces whose mean normal points down (nz < -0.9) coherently."""
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    fs = L.faces(shell)
    sm = face_samples(shell)
    dist = []
    for d in sm:
        dd = []
        for q in d['points']:
            pr = GeomAPI_ProjectPointOnSurf(gp_Pnt(float(q[0]), float(q[1]), float(q[2])), skin_surface)
            dd.append(pr.LowerDistance() if pr.NbPoints() else np.nan)
        dist.append(np.asarray(dd, float))
    floor = [i for i, (d, x) in enumerate(zip(sm, dist)) if len(x) and d['mean_n'][2] > 0.5 and np.isfinite(x).all()
             and np.abs(x - depth).max() <= tol]
    m = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shell, TopAbs_EDGE, TopAbs_FACE, m)
    fidx = {}
    for i, f in enumerate(fs):
        fidx[f.__hash__() if False else i] = f
    def touches(i, group):
        for e in L.explore(fs[i], 'edge'):
            if m.Contains(e):
                for g in m.FindFromKey(e):
                    for j in group:
                        if g.IsSame(fs[j]):
                            return True
        return False
    step = [i for i, (d, x) in enumerate(zip(sm, dist)) if len(x) and d['vertical'] > 0.9 and np.isfinite(x).all() and x.min() <= tol
            and abs(x.max() - depth) <= tol and touches(i, floor)]
    sig = set()                                                    # one extrusion surface cut in two by the closed outline's seam shows as equal basis-curve signatures
    for i in step:
        su = BRep_Tool.Surface_s(fs[i])
        bc = su.BasisCurve() if hasattr(su, 'BasisCurve') else None
        if bc is not None and hasattr(bc, 'NbPoles'):
            p0 = bc.Pole(1)
            sig.add((bc.NbPoles(), round(p0.X(), 6), round(p0.Y(), 6), round(bc.LastParameter(), 6)))
        else:
            sig.add(('face', i))
    bearing = [i for i, d in enumerate(sm) if d['mean_n'][2] < -0.9 and d['coherence'] > 0.9 and d['area'] > 1.0]
    return {'step': step, 'floor': floor, 'bearing': bearing, 'step_faces_share_one_extrusion_surface': len(sig) == 1 and len(step) > 1, 'faces': len(fs), 'depth_mm': depth, 'tol_mm': tol,
            'rule': 'floor = upward faces depth below the shared skin; step = near-vertical faces from the skin down to that floor touching it; bearing = coherent downward faces'}


# ---------------------------------------------------------------- main
def cut_shell_gated(S, Ts, W, defl: float, bS):
    """S - shell tool (- window) in the gated fuzzy ladder of scan_click_slots (0, 1e-5, 3e-5, 1e-4 x bbox diagonal). The shell tool's outer wall
    runs along the slot rim the shell already has (click_slots): the exact cut inflates edge tolerances there to ~0.1 mm and leaves a degenerated
    0.07 mm bridging edge on the skin face, which BRepMesh then refuses (in memory and after the STEP round trip). Accepted only if every solid is
    valid, every face triangulates at the process deflection, and (one solid) every face still triangulates after a STEP round trip; the volume
    bookkeeping of split() stays the independent check. -> (shape, log); SHELL_MESH if no rung passes."""
    import tempfile
    from cadmcp_brain.studio.scan_click_slots_worker import FUZZY_LADDER_REL, step_round_trip_unmeshed
    diag = float(np.linalg.norm(np.asarray(bS[3:]) - np.asarray(bS[:3])))
    attempts = []
    orders = (('shell_tool', 'window'), ('window', 'shell_tool')) if W is not None else (('shell_tool',),)
    for rel in FUZZY_LADDER_REL:
        for order in orders:                                                    # the window first leaves the slot-rim re-cut as the last, simpler step
            fz = float(rel) * diag
            rec: dict[str, Any] = {'fuzzy_mm': fz, 'order': list(order)}
            attempts.append(rec)
            sh = S
            for step in order:
                if sh is None or not L.solids(sh):
                    break
                sh = boolean('cut', sh, Ts if step == 'shell_tool' else W, f'{step} cut', fz)
            sols = L.solids(sh) if sh is not None else []
            rec['solids'] = len(sols)
            if not sols:
                continue
            rec['valid'] = all(bool(BRepCheck_Analyzer(q).IsValid()) for q in sols)
            rec['unmeshed_faces'] = [GF.unmeshed_faces(q, defl, clean=True) for q in sols]
            if not rec['valid'] or any(rec['unmeshed_faces']):
                continue
            if len(sols) == 1:
                with tempfile.TemporaryDirectory() as td:
                    rec['unmeshed_faces_after_step_round_trip'] = step_round_trip_unmeshed(sols[0], Path(td), defl)
                if rec['unmeshed_faces_after_step_round_trip']:
                    continue
            rec['accepted'] = True
            return sh, {'attempts': attempts, 'fuzzy_mm_used': fz, 'order': list(order)}
    fail('SHELL_MESH', 'The shell cut gives a solid whose faces do not all triangulate at any fuzzy value (in memory or after a STEP round trip).',
         {'attempts': attempts})


def split(S, patches, prm: dict[str, Any], log=None) -> dict[str, Any]:
    p = prm
    win = p['window']
    skin = Skin(patches, p)
    ax, lg = LAT, 1 - LAT                                     # lateral axis y (the mirror plane normal), longitudinal x
    bS = L.bbox(S)
    fL, fR = project_outline(patches[0]), project_outline(patches[1])
    bL, bR = L.bbox(fL), L.bbox(fR)
    mid_shell = float((bS[ax] + bS[3 + ax]) / 2)
    if p['centre_mm'] is not None:
        cy = float(p['centre_mm'])
    elif p['centre_source'] == 'shell_bbox':
        cy = mid_shell
    else:
        cy = float((bL[3 + ax] + bR[ax]) / 2)
    slot_gap = float(bR[ax] - bL[3 + ax])
    warnings = []
    if abs(slot_gap - p['centre_slot_mm']) > 0.05:
        warnings.append(f'Patch gap {slot_gap:.3f} mm differs from centre_slot_mm {p["centre_slot_mm"]}.')
    if abs(cy - mid_shell) > 0.01 * (bS[3 + ax] - bS[ax]):
        warnings.append(f'The centre slot plane {cy:.3f} is {abs(cy - mid_shell):.3f} mm from the shell bbox mid plane {mid_shell:.3f}.')
    x0, x1 = float(min(bL[lg], bR[lg]) - p['outline_margin_mm']), float(max(bL[3 + lg], bR[3 + lg]) + 0.3 * p['outline_margin_mm'])      # slot overshoot = 1 x / 0.3 x the outline margin (v17: 0.1 / 0.03)
    h2 = (p['centre_slot_mm'] + 0.2) / 2
    slot = rect_face(x0, x1, cy - h2, cy + h2)
    pz0, ph = float(bS[2] - 1.0), float(bS[5] - bS[2] + p['slab_top_mm'] + 2.0)
    members = [fL, fR, slot]
    winf = None
    if win:
        winf = translate(rect_face(-win['w'] / 2, win['w'] / 2, -win['h'] / 2, win['h'] / 2, win['r']), win['cx'], win['cy'])
        members.append(winf)
    U = fuse_faces(members)
    uf = L.faces(U)
    if len(uf) != 1:
        fail('FOOTPRINT', f'The footprint union gave {len(uf)} faces (one expected).')
    a_union, a_min = L.area(uf[0]), L.area(fL) + L.area(fR)                    # the two patches are disjoint: the union holds at least both
    if a_union < a_min - 1.0:
        fail('FOOTPRINT', f'The footprint union ({a_union:.1f} mm2) is smaller than the two patch outlines ({a_min:.1f} mm2): a member was lost in the fuse.',
             {'union_mm2': a_union, 'patch_L_mm2': L.area(fL), 'patch_R_mm2': L.area(fR)})
    m = p['outline_margin_mm']
    Up, poly_p = smooth_offset(uf[0], m, p['outline_step_mm'])
    Us, _ = smooth_offset(uf[0], m + p['outer_groove_mm'], p['outline_step_mm'])
    Qp, Qs = prism(Up, pz0, ph), prism(Us, pz0, ph)
    W = prism(winf, pz0, ph) if winf is not None else None
    t, gap = p['plate_thickness_mm'], p['gap_mm']
    top, top_tried = skin.safe_top(p['slab_top_mm'])
    if top < p['slab_top_mm']:
        warnings.append(f'slab_top_mm {p["slab_top_mm"]} folds the concave skin (offset Jacobian); {top:g} mm used (the top only has to clear the skin).')
    Tp = req(boolean('common', skin.slab(top, -t), Qp, 'plate tool'), 'plate tool')
    Ts = req(boolean('common', skin.slab(top, -(t + gap)), Qs, 'shell tool'), 'shell tool')
    X = req(boolean('common', S, Tp, 'S & plate tool'), 'S & plate tool')
    pad = float(max(bS[3] - bS[0], bS[4] - bS[1], bS[5] - bS[2]) + 1.0)          # helper boxes sized from the shell bbox
    lo, hi = [bS[0] - pad, bS[1] - pad, bS[2] - pad], [bS[3] + pad, bS[4] + pad, bS[5] + pad]
    hiL, loR = list(hi), list(lo)
    hiL[ax], loR[ax] = cy, cy
    boxL = BRepPrimAPI_MakeBox(gp_Pnt(*lo), gp_Pnt(*hiL)).Shape()
    boxR = BRepPrimAPI_MakeBox(gp_Pnt(*loR), gp_Pnt(*hi)).Shape()
    Lh = req(boolean('common', X, boxL, 'plate L split'), 'plate L split')
    Rh = req(boolean('common', X, boxR, 'plate R split'), 'plate R split')
    pL, pR = biggest(Lh), biggest(Rh)
    d = p['mesh_deflection_mm']
    wp = boolean('common', req(boolean('cut', S, Ts, 'S - shell tool'), 'S - shell tool'), W, 'window common') if W is not None else None
    if wp is not None and not L.solids(wp):
        wp = None
        warnings.append('The wheel window removed nothing from the shell (already open or outside it).')
    sh, shell_boolean = cut_shell_gated(S, Ts, W if wp is not None else None, d, bS)
    if log:
        log(f'shell boolean {shell_boolean}')
    sols = L.solids(sh)
    if len(sols) != 1 or not all(BRepCheck_Analyzer(q).IsValid() for q in sols):
        fail('SHELL', f'The shell is {len(sols)} solids / valid={[bool(BRepCheck_Analyzer(q).IsValid()) for q in sols]} (one valid solid expected).')
    shell = sols[0]
    vS, vsh, vL, vR = (GF.mesh_volume(x, d) for x in (S, shell, pL, pR))
    vST = vsum(req(boolean('common', S, Ts, 'S & shell tool'), 'S & shell tool'), d)
    vW = vsum(wp, d)
    resid = vS - vsh - vST - vW
    book = {'S': vS, 'shell': vsh, 'plate_L': vL, 'plate_R': vR, 'removed_non_plate': vST - vL - vR, 'window': vW, 'residual': resid}
    if log:
        log(f'bookkeeping {book}')
    if abs(resid) > p['book_tol_mm3']:
        fail('BOOKKEEPING', f'Volume bookkeeping residual {resid:.1f} mm3 exceeds {p["book_tol_mm3"]}.', {'book': book})
    if vST - vL - vR < -p['book_tol_mm3']:
        fail('BOOKKEEPING', 'The plates are larger than the removed region.', {'book': book})
    sym = abs(vL - vR) / ((vL + vR) / 2)
    if sym > p['sym_tol']:
        fail('SYMMETRY', f'Plates are not symmetric: {vL:.1f} vs {vR:.1f} mm3 ({sym:.3%}).', {'book': book})
    inter = {}
    for nm, a, b in (('shell-L', shell, pL), ('shell-R', shell, pR), ('L-R', pL, pR)):
        i = boolean('common', a, b, nm)
        inter[nm] = vsum(i, d) if i is not None else 0.0
        if inter[nm] > p['interference_tol_mm3']:
            fail('INTERFERENCE', f'Interference {nm}: {inter[nm]:.3f} mm3.', {'interference': inter})
    rays = ray_checks(skin, poly_p, (pL, pR), shell, p, cy, win, ax)
    return {'shell': shell, 'plate_L': pL, 'plate_R': pR, 'book': book, 'shell_boolean': shell_boolean, 'rays': rays, 'centre_mm': cy, 'shell_mid_mm': mid_shell, 'uv_margin': skin.margin, 'slab_top_used_mm': top, 'slab_top_tried_mm': top_tried, 'symmetry': sym, 'interference': inter,
            'warnings': warnings}


def run(req_: dict[str, Any]) -> dict[str, Any]:
    prm = {**DEFAULTS, **{k: v for k, v in req_['params'].items() if k in DEFAULTS}}
    inputs = req_['inputs']
    out = Path(req_['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    fill = None
    shell_name, shell_solid = GF.select_solid(inputs['shell'], prm['shell_part'], 'The shell STEP')
    prm = GF.resolve_thresholds(shell_solid, prm)
    win_source = None
    if prm['cut_window']:
        if prm['window'] is not None:
            win, win_source = {'r': 0.0, **{k: float(v) for k, v in prm['window'].items()}}, 'argument'
            if set(win) != {'w', 'h', 'r', 'cx', 'cy'}:
                fail('WINDOW_REQUIRED', 'window needs w, h, cx, cy (r optional, default 0).', {'window': prm['window']})
        else:
            win, win_source = derive_window(inputs.get('wheel'), prm), 'wheel_part'
        prm['window'] = win
    else:
        prm['window'] = None
    if prm['patch_faces'] is not None:                                          # the input is the filled skin itself; patches named by face index
        S, T = shell_solid, None
        F = L.faces(S)
        ids = [int(i) for i in prm['patch_faces']]
        if len(ids) != 2 or min(ids) < 0 or max(ids) >= len(F):
            fail('PATCH_FACES', 'patch_faces must be two face indices of the skin solid.', {'faces': len(F), 'given': prm['patch_faces']})
        patches, ax0 = order_patches([F[i] for i in ids], prm['lateral_axis'])
        det = {'patches': ids, 'given': True, 'lateral_axis': 'xy'[ax0]}
        mode = 'skin_with_patch_faces'
    else:
        if inputs.get('skin'):
            _, S = GF.select_solid(inputs['skin'], prm['skin_part'], 'The filled skin STEP')
            T = GF.Topo(shell_solid)
            gdet = GF.find_groove(T, {**GF.DEFAULTS, **prm})
            mode = 'filled_skin_plus_groove_source'
        else:
            fill = GF.fill_solid(shell_solid, {**GF.DEFAULTS, **prm})
            GF.gates(fill, prm)
            S, T, gdet = fill['solid'], fill['topo'], fill['detection']
            L.write_step(S, out / 'filled_skin.step')
            files['filled_skin'] = 'filled_skin.step'
            # Cut the solid the evidence refers to: the written file read back. The in-memory fill result carries the skin face with the
            # pcurve/tolerance state of the groove-fill Booleans; cut along the existing slot rim it leaves an unmeshable strip face at every fuzzy
            # value, while the same cuts on the re-imported solid (what every other tool sees) triangulate at fuzzy 0. The other two modes already
            # start from a file. The patches keep their geometry (surfaces); only the Boolean operand changes.
            S = L.one_solid(out / 'filled_skin.step', 'ROUND_TRIP')
            mode = 'groove_fill_then_split'
        patches, det = detect_patches(T, gdet, prm)
    turned = det['lateral_axis'] == 'x'
    sprm = dict(prm)
    if turned:                                                                  # work in the verified frame (lateral = y), turn the results back
        S = rot90(S, 1)
        patches = [TopoDS.Face_s(rot90(f, 1)) for f in patches]
        if prm['window']:
            w_ = prm['window']
            sprm['window'] = {'w': w_['h'], 'h': w_['w'], 'r': w_['r'], 'cx': -w_['cy'], 'cy': w_['cx']}
    r = split(S, patches, sprm, log=lambda m: print(m, file=sys.stderr, flush=True))
    if turned:
        for key in ('shell', 'plate_L', 'plate_R'):
            r[key] = L.solids(rot90(r[key], -1))[0]
    r['shell'], unify_log = unify_gated(r['shell'])
    skin_face = TopoDS.Face_s(rot90(patches[0], -1)) if turned else patches[0]
    for nm, key in (('shell_open', 'shell'), ('plate_L', 'plate_L'), ('plate_R', 'plate_R')):
        L.write_step(r[key], out / f'{nm}.step')
        files[nm] = f'{nm}.step'
    grey = (0.6, 0.6, 0.6)
    L.write_colored_step([('Top_Shell', r['shell'], [grey] * len(L.faces(r['shell'])), grey),
                          ('click_plate_L', r['plate_L'], [grey] * len(L.faces(r['plate_L'])), (0.9, 0.5, 0.2)),
                          ('click_plate_R', r['plate_R'], [grey] * len(L.faces(r['plate_R'])), (0.2, 0.5, 0.9))], out / 'click_split_parts.step')
    files['parts'] = 'click_split_parts.step'
    d = prm['mesh_deflection_mm']
    solids = {}
    for key in ('shell', 'plate_L', 'plate_R'):
        s = r[key]
        bb = L.bbox(s)
        back = L.solids(L.read_step(out / (files['shell_open'] if key == 'shell' else files[key])))
        if len(back) != 1 or not BRepCheck_Analyzer(back[0]).IsValid():
            fail('ROUND_TRIP', f'The written {key} STEP does not read back as one valid solid.', {'solids': len(back)})
        solids[key] = {'volume_mm3': GF.mesh_volume(s, d), 'brep_volume_mm3': L.volume(s), 'bbox': [round(float(x), 4) for x in bb], 'faces': len(L.faces(s)),
                       'valid': bool(BRepCheck_Analyzer(s).IsValid()), 'round_trip_volume_mm3': GF.mesh_volume(back[0], d), **GF.edge_counts(s)}
    shell_back = L.solids(L.read_step(out / files['shell_open']))[0]                 # roles are indices into THIS file's faces
    roles = carve_roles(shell_back, BRep_Tool.Surface_s(skin_face), float(prm['plate_thickness_mm'] + prm['gap_mm']))
    roles['unify'] = unify_log
    res = {'mode': mode, 'carve_face_roles': roles, 'detection': det, 'shell_part': shell_name, 'book': r['book'], 'shell_boolean': r['shell_boolean'], 'rays': r['rays'], 'centre_mm': r['centre_mm'], 'shell_mid_mm': r['shell_mid_mm'], 'lateral_axis': det['lateral_axis'], 'window': prm['window'], 'window_source': win_source, 'uv_margin_used': r['uv_margin'], 'slab_top_used_mm': r['slab_top_used_mm'], 'slab_top_tried_mm': r['slab_top_tried_mm'], 'mesh_repairs': list(GF.MESH_REPAIRS), 'symmetry': r['symmetry'],
           'interference_mm3': r['interference'], 'solids': solids, 'warnings': r['warnings'], 'files': files, 'worker_version': WORKER_VERSION,
           'settings_used': {k: prm[k] for k in prm if k not in ('shell_part', 'skin_part', 'patch_faces')}}
    if fill is not None:
        res['groove_fill'] = {k: fill[k] for k in ('detection', 'loops', 'caps', 'removed_area_mm2', 'volume_added_mm3', 'free_edges', 'multiple_edges',
                                                    'max_tolerance_mm', 'valid')}
    return res


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
