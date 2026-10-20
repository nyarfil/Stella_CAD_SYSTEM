"""Click-groove fill of a mouse top shell (brain_mouse_groove_fill). SUBPROCESS WORKER (server python: OCP, numpy).

Run as:  <server python> -I mouse_groove_fill_worker.py request.json      (result = last stdout line, JSON)

What it replaces: the hand-made `wip/S_skin_filled.step` of the LH2 build (groove outer wall, 0.5 mm floor and inner wall faces removed, the hole capped on
the shared skin B-spline, end caps on the nose face, slot cap, sewn at tol 0.02, 0 free edges).

Method (B-rep surgery, no Boolean; a Boolean against faces that lie on the skin silently fails, see the spec section S4):
  1. detect the groove: floor = narrow upward face (width < 1.2, nz > 0.8, length > 20) + the near-vertical long faces next to it (|nz| < 0.2) = the walls;
     the skin face = the largest big upward face next to the removed faces (its surface is the "shared skin").  Face ids can be given instead.
  2. remove those faces; the free edges form closed hole loops (ordered through shared vertices).
  3. every edge of a loop is classified by the surface of the face that stays next to it: ON the skin surface or not.  The loop is cut into runs.
     Skin cap  = ONE face on the skin surface bounded by the skin edges (their own pcurves) and one straight chord for every non-skin run.
     Run cap   = the face between a non-skin run and its chord: on the surface the run's neighbours share (the nose face), otherwise a plane
                 (the slot end wall), accepted only when run + chord are planar within planar_tol_mm.
  4. kept faces + caps are sewn (tol sew_tol_mm), closed to a solid; gates: 0 free edges, 0 multiple edges, one valid solid, positive mesh volume,
     volume added > 0, STEP round trip.
Everything is a gate: a hole loop this method cannot cap raises GROOVE_FILL_UNSUPPORTED (never a silent partial fill).
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
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeSolid, BRepBuilderAPI_MakeVertex, BRepBuilderAPI_MakeWire,
                                BRepBuilderAPI_Sewing)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepLib import BRepLib
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.GC import GC_MakeSegment
from OCP.GProp import GProp_GProps
from OCP.Geom import Geom_Plane
from OCP.Geom2d import Geom2d_BSplineCurve
from OCP.ShapeFix import ShapeFix_Face, ShapeFix_Shell, ShapeFix_Solid
from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal
from OCP.TColgp import TColgp_Array1OfPnt2d
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_FORWARD, TopAbs_REVERSED, TopAbs_VERTEX
from OCP.TopExp import TopExp
from OCP.TopLoc import TopLoc_Location
from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape, TopTools_IndexedMapOfShape
from OCP.TopoDS import TopoDS, TopoDS_Edge, TopoDS_Vertex
from OCP.gp import gp_Dir, gp_Pln, gp_Pnt, gp_Pnt2d

from cadmcp_brain.studio import cad_brep_lib as L
from cadmcp_brain.studio import mouse_parts_lib as P
from cadmcp_brain.studio.scan_cad_common import WorkerError, worker_main

WORKER_VERSION = 'mouse_groove_fill/2'
# detection thresholds of the approved process (click_split.py / spec S4: floor width < 1.2, wall |nz| < 0.2).  The two size thresholds are None = derived
# from the shell bbox (GROOVE_LEN_FRAC of the longest side, SKIN_AREA_FRAC of the plan bbox area); LH2 verification passes 20 mm / 300 mm2 explicitly.
GROOVE_LEN_FRAC = 0.17
SKIN_AREA_FRAC = 0.04
DEFAULTS = {'max_floor_width_mm': 1.2, 'floor_min_nz': 0.8, 'wall_max_abs_nz': 0.2, 'min_groove_length_mm': None, 'min_patch_area_mm2': None,
            'sew_tol_mm': 0.02, 'planar_tol_mm': 0.02, 'mesh_deflection_mm': 0.003, 'part': None, 'groove_faces': None}
CODE = 'GROOVE_FILL'


def fail(code: str, msg: str, details: dict | None = None):
    raise WorkerError(f'{CODE}_{code}', msg, details or {})


# ---------------------------------------------------------------- measures shared with the click-split worker
MESH_REPAIRS: list[dict[str, Any]] = []        # every unmeshable-face repair done in this worker process (reported by the callers)


def unmeshed_faces(shape, defl: float, parallel: bool = True, clean: bool = False) -> list[int]:
    """Mesh the shape; indices (explorer order) of the faces that got no triangulation."""
    if clean:
        BRepTools.Clean_s(shape)
    BRepMesh_IncrementalMesh(shape, defl, False, 0.05, parallel)
    return [i for i, f in enumerate(L.faces(shape)) if BRep_Tool.Triangulation_s(f, TopLoc_Location()) is None]


def heal_meshable(shape, defl: float, what: str, vol_rel_tol: float = 1e-4, bbox_tol_mm: float = 0.02, err=None):
    """-> (shape, log or None). A shape whose faces all triangulate is returned as is. Otherwise: (1) the same mesh without the parallel
    mesher, (2) ShapeFix_Shape on a copy (closes the 2D wire gaps of a B-spline face that make BRepMesh drop it; every face stays valid in 3D, e.g.
    the slot-cut skin face of click_slots with a 2.8e-5 pcurve gap). The repair is accepted only if the result is one valid solid with the same face
    count, all faces meshable, B-rep volume within vol_rel_tol and bbox within bbox_tol_mm; else GROOVE_FILL_MESH (or err(code, msg, details) of the
    caller) is raised (never a silent skip)."""
    miss = unmeshed_faces(shape, defl)
    if not miss:
        return shape, None
    log: dict[str, Any] = {'what': what, 'unmeshed_faces_before': miss, 'deflection_mm': defl}
    if not unmeshed_faces(shape, defl, parallel=False, clean=True):
        log['method'] = 'sequential mesher'
        MESH_REPAIRS.append(log)
        return shape, log
    from OCP.ShapeFix import ShapeFix_Shape
    sf = ShapeFix_Shape(shape)
    sf.Perform()
    ss = L.solids(sf.Shape())
    v0, b0 = L.volume(shape), L.bbox(shape)
    ok = len(ss) == 1 and bool(BRepCheck_Analyzer(ss[0]).IsValid()) and len(L.faces(ss[0])) == len(L.faces(shape))
    miss2 = unmeshed_faces(ss[0], defl, clean=True) if ok else miss
    dv = abs(L.volume(ss[0]) - v0) / max(abs(v0), 1e-9) if ok else None
    db = float(np.abs(L.bbox(ss[0]) - b0).max()) if ok else None
    log.update(method='ShapeFix_Shape', unmeshed_faces_after=miss2, volume_rel_change=dv, bbox_change_mm=db, solids=len(ss))
    if not ok or miss2 or dv > vol_rel_tol or db > bbox_tol_mm:
        (err or fail)('MESH', f'{what}: {len(miss)} face(s) cannot be triangulated and the repair did not pass its gates.', {'repair': log})
    MESH_REPAIRS.append(log)
    return ss[0], log


def mesh_volume(shape, defl: float) -> float:
    """Signed closed-mesh volume (mm3). BRepGProp volumes of these B-spline solids move by ~100 mm3 between methods; the mesh volume is stable.
    A face that does not triangulate is repaired on a copy (heal_meshable, gated) before the volume is measured."""
    if unmeshed_faces(shape, defl):
        shape = L.solids(shape)[0] if L.solids(shape) else shape
        shape, _ = heal_meshable(shape, defl, 'mesh_volume input')
        BRepMesh_IncrementalMesh(shape, defl, False, 0.05, True)
    tot = 0.0
    for f in L.faces(shape):
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(f, loc)
        if tri is None:
            fail('MESH', 'A face has no triangulation; the volume cannot be measured.')
        tr = loc.Transformation()
        pts = np.array([tri.Node(i).Transformed(tr).Coord() for i in range(1, tri.NbNodes() + 1)])
        tt = np.array([[tri.Triangle(i).Value(k) for k in (1, 2, 3)] for i in range(1, tri.NbTriangles() + 1)]) - 1
        v = np.einsum('ij,ij->i', pts[tt[:, 0]], np.cross(pts[tt[:, 1]], pts[tt[:, 2]])).sum() / 6.0
        tot += -v if f.Orientation() == TopAbs_REVERSED else v
    return float(tot)


def edge_length(e) -> float:
    g = GProp_GProps()
    BRepGProp.LinearProperties_s(e, g)
    return float(g.Mass())


def edge_face_map(shape) -> TopTools_IndexedDataMapOfShapeListOfShape:
    m = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, m)
    return m


def edge_counts(shape) -> dict[str, int]:
    """Independent topology check: edges used by one face (free), by more than two faces (multiple)."""
    m = edge_face_map(shape)
    free = multi = 0
    for i in range(1, m.Extent() + 1):
        if BRep_Tool.Degenerated_s(TopoDS.Edge_s(m.FindKey(i))):
            continue
        faces = TopTools_IndexedMapOfShape()
        for g in m.FindFromIndex(i):
            faces.Add(g)
        n = len(list(m.FindFromIndex(i)))      # a seam edge is listed twice for its one face: that is a closed surface, not a free edge
        if faces.Extent() == 1 and n < 2:
            free += 1
        elif n > 2:
            multi += 1
    return {'free_edges': free, 'multiple_edges': multi}


def max_tolerance(shape) -> float:
    t = 0.0
    for kind in (TopAbs_EDGE, TopAbs_VERTEX):
        mp = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, kind, mp)
        for i in range(1, mp.Extent() + 1):
            s = mp.FindKey(i)
            t = max(t, BRep_Tool.Tolerance_s(TopoDS.Edge_s(s)) if kind == TopAbs_EDGE else BRep_Tool.Tolerance_s(TopoDS.Vertex_s(s)))
    return float(t)


def select_solid(path: str, part: str | None, what: str):
    parts, _ = P.load_parts([path])
    if part is None:
        if len(parts) != 1:
            fail('PART', f'{what} holds {len(parts)} parts: name the shell with its part name.', {'known': sorted(parts)})
        part = next(iter(parts))
    elif part not in parts:
        fail('PART', f'{what} has no part "{part}".', {'known': sorted(parts)})
    ss = L.solids(parts[part])
    if len(ss) != 1:
        fail('PART', f'Part "{part}" must be exactly one solid.', {'solids': len(ss)})
    healed, _ = heal_meshable(ss[0], 0.01, what)
    return part, healed


# ---------------------------------------------------------------- topology helpers
class Topo:
    """Faces of one solid in explorer order (the ids reported and accepted by this tool) with edge adjacency and per-face metrics."""

    def __init__(self, solid):
        self.solid = solid
        self.faces = L.faces(solid)
        self.fmap = TopTools_IndexedMapOfShape()
        for f in self.faces:
            self.fmap.Add(f)
        self.idx = {self.fmap.FindIndex(f): i for i, f in enumerate(self.faces)}
        self.emap = edge_face_map(solid)
        self.adj: dict[int, set[int]] = {i: set() for i in range(len(self.faces))}
        self.edge_faces: dict[int, list[int]] = {}
        for k in range(1, self.emap.Extent() + 1):
            fs = sorted({self.idx[self.fmap.FindIndex(g)] for g in self.emap.FindFromIndex(k) if self.fmap.FindIndex(g)})
            self.edge_faces[k] = fs
            for a in fs:
                for b in fs:
                    if a != b:
                        self.adj[a].add(b)
        self.info = [self._metrics(f) for f in self.faces]

    @staticmethod
    def _metrics(f) -> dict[str, float]:
        per = sum(edge_length(e) for e in L.explore(BRepTools.OuterWire_s(f), 'edge'))
        area = L.area(f)
        pt, nrm = L.inner_point(f)
        if pt is None:                                       # thin or non-convex face missed by the UV grid: normal at a boundary vertex
            from OCP.BRep import BRep_Tool
            from OCP.TopAbs import TopAbs_VERTEX
            from OCP.TopExp import TopExp_Explorer
            from OCP.TopoDS import TopoDS
            ex = TopExp_Explorer(f, TopAbs_VERTEX)
            v = TopoDS.Vertex_s(ex.Current()) if ex.More() else None
            if v is not None:
                uv = BRep_Tool.Parameters_s(v, f)
                nrm, pt = L.face_normal_uv(f, uv.X(), uv.Y()), np.array(BRep_Tool.Pnt_s(v).Coord())
        nz = float(nrm[2]) if nrm is not None and np.all(np.isfinite(nrm)) else 0.0
        return {'area': float(area), 'w': 2.0 * area / max(per, 1e-9), 'len': per / 2.0, 'nz': nz,
                'pt': [round(float(x), 3) for x in pt] if pt is not None else None}


def same_surface(sa, face_b, tol: float = 1e-5) -> bool:
    """True when the surface of face_b coincides with sa on face_b's own uv box (sampled 5 x 5, clamped to sa's domain)."""
    sb = BRep_Tool.Surface_s(face_b)
    if type(sa).__name__ != type(sb).__name__:
        return False
    ub = BRepTools.UVBounds_s(face_b)
    a = sa.Bounds()
    u0, u1, v0, v1 = max(ub[0], a[0]), min(ub[1], a[1]), max(ub[2], a[2]), min(ub[3], a[3])
    if u1 <= u0 or v1 <= v0 or abs(u1) > 1e50 or abs(v1) > 1e50:
        return False
    worst = 0.0
    for u in np.linspace(u0, u1, 5):
        for v in np.linspace(v0, v1, 5):
            worst = max(worst, sa.Value(u, v).Distance(sb.Value(u, v)))
    return worst < tol


def resolve_thresholds(solid, prm: dict[str, Any]) -> dict[str, Any]:
    """Fill None size thresholds from the shell bbox (scale-invariant); explicit values win."""
    bb = L.bbox(solid)
    dx, dy, dz = bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]
    out = dict(prm)
    if out.get('min_groove_length_mm') is None:
        out['min_groove_length_mm'] = GROOVE_LEN_FRAC * max(dx, dy, dz)
    if out.get('min_patch_area_mm2') is None:
        out['min_patch_area_mm2'] = SKIN_AREA_FRAC * dx * dy
    return out


def find_groove(T: Topo, p: dict[str, Any]) -> dict[str, Any]:
    info, adj = T.info, T.adj
    floors = [i for i, d in enumerate(info) if d['w'] < p['max_floor_width_mm'] and d['nz'] > p['floor_min_nz'] and d['len'] > p['min_groove_length_mm']]
    best, cands = None, []
    for fl in floors:
        walls = [j for j in adj[fl] if abs(info[j]['nz']) < p['wall_max_abs_nz'] and info[j]['len'] > p['min_groove_length_mm']]
        if not walls:
            continue
        near = {k for j in [fl] + walls for k in adj[j]}
        skin = [k for k in near if info[k]['area'] > p['min_patch_area_mm2'] and info[k]['nz'] > 0.5]
        if not skin:
            continue
        cands.append({'floor': fl, 'walls': sorted(walls), 'length_mm': round(info[fl]['len'], 2)})
        if best is None or info[fl]['len'] > info[best[0]]['len']:
            best = (fl, sorted(walls))
    if best is None:
        fail('NOT_FOUND', 'No click groove found (narrow upward floor with long near-vertical walls next to a big skin face).',
             {'floor_candidates': floors, 'thresholds': {k: p[k] for k in ('max_floor_width_mm', 'floor_min_nz', 'wall_max_abs_nz', 'min_groove_length_mm',
                                                                          'min_patch_area_mm2')}})
    return {'faces': sorted([best[0]] + best[1]), 'floor': best[0], 'walls': best[1], 'other_candidates': [c for c in cands if c['floor'] != best[0]]}


def hole_loops(T: Topo, removed: set[int]) -> list[list[dict[str, Any]]]:
    """Closed loops of the free edges left by removing faces. Each element: edge, start/end vertex index in traversal order, forward (edge's first
    vertex is the traversal start), nb (index of the kept face next to it)."""
    vmap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(T.solid, TopAbs_VERTEX, vmap)
    free = []
    for k, fs in T.edge_faces.items():
        e = TopoDS.Edge_s(T.emap.FindKey(k))
        if BRep_Tool.Degenerated_s(e):
            continue
        kept = [i for i in fs if i not in removed]
        if len(kept) == 1 and len(fs) == 2:
            vf, vl = TopoDS_Vertex(), TopoDS_Vertex()
            TopExp.Vertices_s(e, vf, vl, False)
            a, b = vmap.FindIndex(vf), vmap.FindIndex(vl)
            if a == b:
                fail('UNSUPPORTED', 'A hole edge is a closed curve with one vertex (not supported).', {'face': kept[0]})
            free.append({'edge': e, 'nf': a, 'nl': b, 'nb': kept[0]})
    if not free:
        fail('NO_HOLE', 'Removing the groove faces leaves no free edges (nothing to cap).')
    at: dict[int, list[int]] = {}
    for i, d in enumerate(free):
        at.setdefault(d['nf'], []).append(i)
        at.setdefault(d['nl'], []).append(i)
    if any(len(v) != 2 for v in at.values()):
        fail('UNSUPPORTED', 'The hole boundary is not a set of simple closed loops (a vertex joins more than two free edges).',
             {'vertex_degrees': sorted({len(v) for v in at.values()})})
    used, loops = set(), []
    for s in range(len(free)):
        if s in used:
            continue
        loop, cur, start = [], s, free[s]['nf']
        vi = start
        while True:
            d = free[cur]
            used.add(cur)
            fwd = d['nf'] == vi
            ve = d['nl'] if fwd else d['nf']
            loop.append({**d, 'start': vi, 'end': ve, 'forward': fwd})
            vi = ve
            nxt = [j for j in at[vi] if j != cur]
            if vi == start:
                break
            if not nxt or nxt[0] in used:
                fail('UNSUPPORTED', 'A hole boundary could not be closed into a loop.')
            cur = nxt[0]
        loops.append(loop)
    return loops


# ---------------------------------------------------------------- new topology
def _pcurve(edge, face):
    c2 = BRep_Tool.CurveOnSurface_s(edge, face, 0.0, 0.0)
    if c2 is None:
        fail('NO_PCURVE', 'A hole edge has no parameter curve on its neighbour face.')
    f, l = BRep_Tool.Range_s(edge, face)
    return c2, f, l


def _new_edge(c3, f: float, l: float, va, vb, bb: BRep_Builder):
    """Edge on the 3D curve c3 over [f, l] between the (shared) vertices va (at f) and vb (at l)."""
    e = TopoDS_Edge()
    bb.MakeEdge(e, c3, TopLoc_Location(), 1e-6)
    bb.Add(e, va.Oriented(TopAbs_FORWARD))
    bb.Add(e, vb.Oriented(TopAbs_REVERSED))
    bb.Range(e, f, l)
    for v, par in ((va, f), (vb, l)):
        d = BRep_Tool.Pnt_s(v).Distance(c3.Value(par))
        bb.UpdateVertex(v, par, e, d + 1e-7)
        bb.UpdateVertex(v, d + 1e-7)
    return e


def _add_pcurve(e, c2, surf, f: float, l: float, bb: BRep_Builder, tol: float):
    bb.UpdateEdge(e, c2, surf, TopLoc_Location(), tol)
    bb.Range(e, surf, TopLoc_Location(), f, l)


def _linear_pcurve(uv_a, uv_b, length: float):
    """Degree-1 pcurve a -> b with the parameter running 0 .. length (the parameter of the straight 3D chord)."""
    poles = TColgp_Array1OfPnt2d(1, 2)
    poles.SetValue(1, gp_Pnt2d(*uv_a))
    poles.SetValue(2, gp_Pnt2d(*uv_b))
    knots, mult = TColStd_Array1OfReal(1, 2), TColStd_Array1OfInteger(1, 2)
    knots.SetValue(1, 0.0)
    knots.SetValue(2, length)
    mult.SetValue(1, 2)
    mult.SetValue(2, 2)
    return Geom2d_BSplineCurve(poles, knots, mult, 1)


def _sample_dev(c3, c2, surf, f: float, l: float, n: int = 24) -> float:
    w = 0.0
    for t in np.linspace(f, l, n):
        q = c2.Value(t)
        w = max(w, c3.Value(t).Distance(surf.Value(q.X(), q.Y())))
    return float(w)


class Cap:
    """Builds the cap faces of one hole loop with shared vertices and shared chord edges."""

    def __init__(self, T: Topo, skin_surf, p: dict[str, Any]):
        self.T, self.skin, self.p, self.bb = T, skin_surf, p, BRep_Builder()
        self.verts: dict[int, TopoDS_Vertex] = {}
        self.vmap = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(T.solid, TopAbs_VERTEX, self.vmap)

    def vertex(self, vi: int):
        if vi not in self.verts:
            self.verts[vi] = BRepBuilderAPI_MakeVertex(BRep_Tool.Pnt_s(TopoDS.Vertex_s(self.vmap.FindKey(vi)))).Vertex()
        return self.verts[vi]

    def pnt(self, vi: int):
        return BRep_Tool.Pnt_s(self.vertex(vi))

    def edge_copy(self, el: dict[str, Any], surf=None, pc=None):
        """New edge for a loop element with the original 3D curve; optional pcurve (c2, f, l) on surf."""
        e = el['edge']
        c3 = BRep_Tool.Curve_s(e, 0.0, 0.0)
        f, l = BRep_Tool.Range_s(e)
        ne = _new_edge(c3, f, l, self.vertex(el['nf']), self.vertex(el['nl']), self.bb)
        if surf is not None:
            c2, pf, pl = pc
            dev = _sample_dev(c3, c2, surf, pf, pl)
            _add_pcurve(ne, c2, surf, pf, pl, self.bb, dev + 1e-7)
            self.bb.UpdateEdge(ne, max(dev, BRep_Tool.Tolerance_s(ne)) + 1e-7)
        return ne

    def chord(self, va: int, vb: int):
        a, b = self.pnt(va), self.pnt(vb)
        seg = GC_MakeSegment(a, b).Value()
        return _new_edge(seg, seg.FirstParameter(), seg.LastParameter(), self.vertex(va), self.vertex(vb), self.bb), seg

    def chord_pcurve(self, ch, seg, surf, uv_a, uv_b):
        f, l = seg.FirstParameter(), seg.LastParameter()
        c2 = _linear_pcurve(uv_a, uv_b, l - f) if f == 0.0 else _linear_pcurve(uv_a, uv_b, l)
        dev = _sample_dev(seg, c2, surf, f, l)
        _add_pcurve(ch, c2, surf, f, l, self.bb, dev + 1e-7)
        self.bb.UpdateEdge(ch, max(dev, BRep_Tool.Tolerance_s(ch)) + 1e-7)
        return dev

    @staticmethod
    def _uv(el: dict[str, Any], at_start: bool, pc) -> tuple[float, float]:
        c2, f, l = pc
        first = at_start == el['forward']          # traversal start is the edge's first end when forward
        q = c2.Value(f if first else l)
        return q.X(), q.Y()

    def build(self, loop: list[dict[str, Any]], runs_ok: bool = True) -> dict[str, Any]:
        T = self.T
        for el in loop:
            el['skin'] = same_surface(self.skin, T.faces[el['nb']])
        n = len(loop)
        if not any(e['skin'] for e in loop):
            fail('UNSUPPORTED', 'No hole edge lies on the skin surface; the loop cannot be capped on it.', {'edges': n})
        r0 = next((i for i in range(n) if loop[i]['skin'] != loop[i - 1]['skin']), 0)
        seq = loop[r0:] + loop[:r0]
        groups: list[list[dict[str, Any]]] = []
        for el in seq:
            if groups and groups[-1][0]['skin'] == el['skin']:
                groups[-1].append(el)
            else:
                groups.append([el])
        faces, rows, dev_max = [], [], 0.0
        skin_pieces: list[Any] = []
        for el in seq:                              # pcurves of all skin edges first (chords need the uv of their neighbours)
            if el['skin']:
                pc = _pcurve(el['edge'], T.faces[el['nb']])
                c3 = BRep_Tool.Curve_s(el['edge'], 0.0, 0.0)
                f, l = BRep_Tool.Range_s(el['edge'])
                q = pc[0].Value(0.5 * (pc[1] + pc[2]))
                off = c3.Value(0.5 * (f + l)).Distance(self.skin.Value(q.X(), q.Y()))
                if off > 1e-3:
                    fail('SKIN_MISMATCH', 'A skin edge does not lie on the skin surface at its pcurve (surfaces differ).', {'offset_mm': off})
                el['pc'] = pc
        for gi, g in enumerate(groups):
            if g[0]['skin']:
                for el in g:
                    skin_pieces.append(('edge', el, self.edge_copy(el, self.skin, el['pc'])))
            else:
                prev, nxt = groups[gi - 1][-1], groups[(gi + 1) % len(groups)][0]
                ch, seg = self.chord(g[0]['start'], g[-1]['end'])
                uva = self._uv(prev, False, prev['pc'])
                uvb = self._uv(nxt, True, nxt['pc'])
                dev_max = max(dev_max, self.chord_pcurve(ch, seg, self.skin, uva, uvb))
                skin_pieces.append(('chord', g, ch, seg))
        if len(groups) == 1:                       # whole loop on the skin (annulus or full ring): not supported, see module doc
            fail('UNSUPPORTED', 'The hole is a loop entirely on the skin surface (closed groove ring): not supported.', {'edges': n})
        wire_edges = [x[2] for x in skin_pieces]
        mw = BRepBuilderAPI_MakeWire()
        for e in wire_edges:
            mw.Add(e)
        if not mw.IsDone():
            fail('WIRE', 'The skin cap boundary could not be joined into one wire.')
        face = BRepBuilderAPI_MakeFace(self.skin, mw.Wire(), True).Face()
        face = self._fix_face(face, 'skin cap')
        faces.append(face)
        rows.append({'kind': 'skin_cap', 'edges': len(wire_edges), 'area_mm2': round(L.area(face), 3)})
        # run caps
        for x in skin_pieces:
            if x[0] != 'chord':
                continue
            g, ch, seg = x[1], x[2], x[3]
            cap, kind, dev = self._run_cap(g, ch, seg)
            dev_max = max(dev_max, dev)
            faces.append(cap)
            rows.append({'kind': kind, 'edges': len(g), 'area_mm2': round(L.area(cap), 3)})
        return {'faces': faces, 'caps': rows, 'chord_deviation_mm': dev_max}

    def _fix_face(self, face, what: str):
        sff = ShapeFix_Face(face)
        sff.FixOrientationMode = True
        sff.Perform()
        face = TopoDS.Face_s(sff.Face())
        a = L.area(face)
        if not math.isfinite(a) or a <= 0:
            fail('CAP_FACE', f'The {what} has no area after construction.', {'area': a})
        BRepLib.UpdateTolerances_s(face, False)
        return face

    def _run_cap(self, g: list[dict[str, Any]], ch, seg):
        T = self.T
        nbs = [T.faces[el['nb']] for el in g]
        s0 = BRep_Tool.Surface_s(nbs[0])
        planar_surface = type(s0).__name__ == 'Geom_Plane'
        if all(same_surface(s0, f) for f in nbs[1:]) and not planar_surface:
            pcs = [_pcurve(el['edge'], T.faces[el['nb']]) for el in g]
            new = [self.edge_copy(el, s0, pc) for el, pc in zip(g, pcs)]
            uva = self._uv(g[0], True, pcs[0])
            uvb = self._uv(g[-1], False, pcs[-1])
            dev = self.chord_pcurve(ch, seg, s0, uva, uvb)
            mw = BRepBuilderAPI_MakeWire()
            for e in new + [ch]:
                mw.Add(e)
            if not mw.IsDone():
                fail('WIRE', 'A run cap boundary could not be joined into one wire.')
            return self._fix_face(BRepBuilderAPI_MakeFace(s0, mw.Wire(), True).Face(), 'run cap'), 'surface_cap', dev
        # planar run cap: the run edges + chord must be planar within planar_tol_mm
        new = [self.edge_copy(el) for el in g]
        pts = []
        for e in new + [ch]:
            c = BRepAdaptor_Curve(e)
            pts += [c.Value(t).Coord() for t in np.linspace(c.FirstParameter(), c.LastParameter(), 12)]
        pts = np.array(pts)
        c0 = pts.mean(0)
        nrm = np.linalg.svd(pts - c0)[2][-1]
        dev = float(np.abs((pts - c0) @ nrm).max())
        if dev > self.p['planar_tol_mm']:
            fail('UNSUPPORTED', 'A non-skin part of the hole is neither on one surface nor planar; it cannot be capped.',
                 {'planarity_mm': dev, 'planar_tol_mm': self.p['planar_tol_mm'], 'neighbour_faces': [el['nb'] for el in g]})
        pl = Geom_Plane(gp_Pln(gp_Pnt(*map(float, c0)), gp_Dir(*map(float, nrm))))
        mw = BRepBuilderAPI_MakeWire()
        for e in new + [ch]:
            mw.Add(e)
        if not mw.IsDone():
            fail('WIRE', 'A planar run cap boundary could not be joined into one wire.')
        face = BRepBuilderAPI_MakeFace(pl, mw.Wire(), True).Face()
        for e in L.explore(face, 'edge'):
            BRepLib.BuildPCurveForEdgeOnPlane_s(e, face)
        return self._fix_face(face, 'planar run cap'), 'planar_cap', dev


# ---------------------------------------------------------------- driver
def fill_solid(solid, p: dict[str, Any]) -> dict[str, Any]:
    """Core: -> {solid, report-ish dict}. Used by run() and by the click-split worker."""
    prm = resolve_thresholds(solid, {**DEFAULTS, **{k: v for k, v in p.items() if k in DEFAULTS and v is not None or k in ('part', 'groove_faces')}})
    T = Topo(solid)
    if prm['groove_faces'] is not None:
        ids = sorted(set(int(i) for i in prm['groove_faces']))
        if not ids or ids[0] < 0 or ids[-1] >= len(T.faces):
            fail('FACES', 'groove_faces must be indices into the faces of the shell.', {'faces': len(T.faces), 'given': prm['groove_faces']})
        det = {'faces': ids, 'floor': None, 'walls': None, 'other_candidates': [], 'given': True}
    else:
        det = find_groove(T, prm)
    removed = set(det['faces'])
    near = {k for j in removed for k in T.adj[j] if k not in removed}
    skin_ids = sorted([k for k in near if T.info[k]['area'] > prm['min_patch_area_mm2'] and T.info[k]['nz'] > 0.5], key=lambda k: -T.info[k]['area'])
    if not skin_ids:
        fail('NO_SKIN', 'No big upward face (the skin) lies next to the groove faces.', {'min_patch_area_mm2': prm['min_patch_area_mm2']})
    skin_face = T.faces[skin_ids[0]]
    skin_surf = BRep_Tool.Surface_s(skin_face)
    loops = hole_loops(T, removed)
    cap_faces, cap_rows, chord_dev = [], [], 0.0
    for li, loop in enumerate(loops):
        b = Cap(T, skin_surf, prm).build(loop)
        cap_faces += b['faces']
        cap_rows += [{**r, 'loop': li} for r in b['caps']]
        chord_dev = max(chord_dev, b['chord_deviation_mm'])
    defl = prm['mesh_deflection_mm']
    v0 = mesh_volume(solid, defl)
    area_removed = float(sum(T.info[i]['area'] for i in removed))
    sew = BRepBuilderAPI_Sewing(prm['sew_tol_mm'], True, True, True, False)
    for i, f in enumerate(T.faces):
        if i not in removed:
            sew.Add(f)
    for f in cap_faces:
        sew.Add(f)
    sew.Perform()
    n_free, n_multi = int(sew.NbFreeEdges()), int(sew.NbMultipleEdges())
    if n_free or n_multi:
        fail('SEWING', f'Sewing at tol {prm["sew_tol_mm"]} left {n_free} free and {n_multi} multiple edges.',
             {'free_edges': n_free, 'multiple_edges': n_multi, 'caps': cap_rows})
    shells = L.explore(sew.SewedShape(), 'shell')
    if len(shells) != 1:
        fail('SEWING', f'Sewing gave {len(shells)} shells (one closed shell expected).')
    sf = ShapeFix_Shell(shells[0])
    sf.Perform()
    sol = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(sf.Shell())).Solid()
    fx = ShapeFix_Solid(sol)
    fx.Perform()
    out = fx.Solid()
    v1 = mesh_volume(out, defl)
    if v1 < 0:                                      # inside-out shell: flip once, then the gate below decides
        out = out.Reversed()
        v1 = mesh_volume(out, defl)
    valid = bool(BRepCheck_Analyzer(out).IsValid())
    ec = edge_counts(out)
    return {'solid': out, 'detection': det, 'skin_face': skin_ids[0], 'skin_surface': skin_surf, 'loops': [len(x) for x in loops], 'caps': cap_rows,
            'removed_area_mm2': round(area_removed, 3), 'volume_before_mm3': v0, 'volume_after_mm3': v1, 'volume_added_mm3': v1 - v0, 'valid': valid,
            'faces_before': len(T.faces), 'faces_after': len(L.faces(out)), 'sewing_free_edges': n_free, 'sewing_multiple_edges': n_multi, **ec,
            'max_tolerance_mm': max_tolerance(out), 'chord_deviation_mm': chord_dev, 'topo': T, 'thresholds': prm}


def gates(r: dict[str, Any], prm: dict[str, Any]) -> None:
    ss = L.solids(r['solid'])
    if len(ss) != 1:
        fail('SOLID', f'The filled shell is {len(ss)} solids (one expected).')
    if not r['valid']:
        fail('INVALID', 'The filled shell is not a valid B-rep (BRepCheck).')
    if r['free_edges'] or r['multiple_edges']:
        fail('OPEN', 'The filled shell has free or multiple edges.', {'free_edges': r['free_edges'], 'multiple_edges': r['multiple_edges']})
    if r['volume_after_mm3'] <= 0 or r['volume_added_mm3'] <= 0:
        fail('VOLUME', 'The fill must add volume to a positive solid.', {'before': r['volume_before_mm3'], 'after': r['volume_after_mm3']})


def run(req: dict[str, Any]) -> dict[str, Any]:
    prm = {**DEFAULTS, **{k: v for k, v in req['params'].items() if k in DEFAULTS}}
    name, solid = select_solid(req['inputs']['shell'], prm['part'], 'The shell STEP')
    r = fill_solid(solid, prm)
    prm = r['thresholds']
    gates(r, prm)
    out = Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    L.write_step(r['solid'], out / 'filled_skin.step')
    back = L.solids(L.read_step(out / 'filled_skin.step'))          # round trip gate
    if len(back) != 1 or not BRepCheck_Analyzer(back[0]).IsValid():
        fail('ROUND_TRIP', 'The written STEP does not read back as one valid solid.', {'solids': len(back)})
    rt = {'solids': len(back), 'valid': True, 'volume_mm3': mesh_volume(back[0], prm['mesh_deflection_mm']), **edge_counts(back[0])}
    if rt['free_edges'] or abs(rt['volume_mm3'] - r['volume_after_mm3']) > 5.0:
        fail('ROUND_TRIP', 'The STEP round trip changed the solid.', {'round_trip': rt, 'volume_mm3': r['volume_after_mm3']})
    T = r['topo']
    keep = ('detection', 'skin_face', 'loops', 'caps', 'removed_area_mm2', 'volume_before_mm3', 'volume_after_mm3', 'volume_added_mm3', 'valid', 'faces_before',
            'faces_after', 'sewing_free_edges', 'sewing_multiple_edges', 'free_edges', 'multiple_edges', 'max_tolerance_mm', 'chord_deviation_mm')
    res = {k: r[k] for k in keep}
    res.update({'part': name, 'settings_used': {k: prm[k] for k in prm if k not in ('part', 'groove_faces')}, 'round_trip': rt,
                'removed_faces': [{'id': i, **{k: T.info[i][k] for k in ('area', 'w', 'len', 'nz', 'pt')}} for i in r['detection']['faces']],
                'files': {'filled_skin': 'filled_skin.step'}, 'worker_version': WORKER_VERSION, 'mesh_repairs': list(MESH_REPAIRS)})
    return res


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
