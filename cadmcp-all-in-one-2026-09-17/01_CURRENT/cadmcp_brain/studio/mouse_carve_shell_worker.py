"""Carve-from-solid top shell (brain_mouse_carve_shell). SUBPROCESS WORKER (server python: OCP + scipy + vtk, extra `geometry`).

Run as:  <server python> -I mouse_carve_shell_worker.py request.json      (result = last stdout line, JSON)

Port of the owner-approved LH2 "carve v26" build (V:/mouse/LH2-mouse/work/internals/carve/scripts, PROGRESS.md; build123d -> plain OCP):
  1. G  (c5_gpts.py + c1_lsq.py + c1_build.py): exact inner offsets (wall_mm) of the large smooth skin faces, sampled on their UV grid (holes
     of a face filled with its own surface; side-button pockets filled with the neighbouring skin surface inside the window prism), continued
     vertically below the bearing rim, plus the floor faces lifted by floor_fill_lift_mm (keeps G above the floor offset). Mapped to a star-
     shaped ray grid from ray_center (dir = (ax s, ay t, az (1-s^2)(1-t^2))), inner envelope, ONE tensor least-squares cubic B-spline
     (2nd-difference smoothing, boundary pinned to the ray-centre plane); cavity G = box piece split by that one face.
  2. K2 (c5_floff2.py): floor offset sheet = height-field LSQ fit of the exact floor_mm inner offset of the floor face(s), samples within
     floor_edge_exclude_mm of the plate outline dropped (no edge curl), linear continuation to the wall; plate outline = basis curve of the step
     face (linear extrusion), its kink smoothed, offset outward by wall_mm; K2 = prism(outline + wall) above the sheet (kept material).
  3. K3 (c5_k3.py): for each side-button window with a `sill`, K2 minus the slot-aligned box below the window, so the sill keeps the true wall.
  4. cavity = G - K3; shell = S - cavity, then - windows (c5_build5.py: two stages; one multi-tool cut with the cavity failed on v18).
  5. step fillet (c6_fil.py): radius step_fillet_mm (default wall_mm, concentric with the outer step edge) on the edge(s) between the K lateral
     face and the floor sheet -> constant normal thickness across the plate-outline step.
Every Boolean is gated (done, non-empty, solid count, valid, volume decreases); faces are tracked through the Boolean history.
"""
from __future__ import annotations
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from cadmcp_brain.studio.scan_cad_common import WorkerError, worker_main
from cadmcp_brain.studio import cad_brep_lib as L

WORKER_VERSION = 'mouse_carve_shell/2'
# Defaults = the v26 build (sources in brackets).
DEFAULTS = {
    'wall_mm': 1.2,                    # PROGRESS.md owner params 2026-10-13; c5_gpts.py T
    'floor_mm': 1.2,                   # c5_floff2.py T (floor offset)
    'step_fillet_mm': None,            # None -> wall_mm (c6_fil.py R = 1.2); 0 = no fillet
    'face_roles': None,                # {'wall','floor','step','bearing'}: face indices of the input solid (auto when omitted)
    'wall_face_min_area_mm2': None,    # auto role threshold; None -> wall_face_min_area_frac x total face area of the solid
    'wall_face_min_area_frac_hint': 0.002,   # with skin faces named by face_roles: min area share (0.2 %) only to skip slivers
    'skin_tangent_deg': 10.0,          # a face tangent-continuous (<= this angle along the shared edge) with a skin face is skin too
    'wall_face_min_area_frac': 0.05,   # c5_gpts.py used the three large smooth faces (LH2 v18: 10..18 % of the area; next face 1.9 %)
    'face_samples': 700,               # c5_gpts.py sample(700, 700)
    'face_uv_extend': 0.04,            # c5_gpts.py ext=0.04
    'pocket_margin_mm': None,          # pocket region = window outline + this; None -> 2 x wall_mm (LH2 v26 hand box reached 1.2..2.7 mm beyond window B)
    'pocket_near_mm': 3.0,             # face samples within this of the window prism define the face's slot-axis range
    'pocket_side_tol_mm': 0.3,         # c5_gpts.py side split x <= 69.7 (rear) / x >= 69.1 (front) around the 69.4 face seam
    'floor_fill_samples': 500,         # c5_gpts.py sample(F13, 500, 500)
    'floor_fill_lift_mm': 0.3,         # c5_gpts.py F13 + 0.3 n
    'bottom_band_mm': 0.5,             # c5_gpts.py seed: z < z_bottom + 0.5
    'bottom_extend_step_mm': 0.25,     # c5_gpts.py 0.25 * k, k = 1..29
    'bottom_extend_steps': 29,
    'ray_center': None,                # v26: [58.8, -0.01, -4.0] (c5_gpts.py C); auto: bbox centre xy, z_min - 6
    'ray_axes': None,                  # v26: [58, 29, 40] (c5_gpts.py AX, AY, AZ); auto: [dx/2, 0.48 dy, z_max - center_z]
    'grid': [481, 361],                # c5_grid_g4.npz shape (c5_gpts.py NS NT)
    'poles': [161, 121],               # c1_srf_g5.npz (c1_lsq.py 161 121)
    'smoothing': 1e-7,                 # c1_lsq.py LAM (g5 poles reproduced to 0.0 with 1e-7)
    'envelope_tol_mm': 0.1,            # c5_gpts.py ENVTOL
    'dedup_st': 2e-4,                  # c5_gpts.py (s,t) dedup
    'box_margin_mm': 10.0,             # c1_build.py box 140 x 80 around the shell
    'floor_samples': 301,              # c5_floff2.py 301 x 301
    'floor_poles': 121,                # c5_floff2.py NC
    'floor_smoothing': 1e-6,           # c5_floff2.py LAM
    'floor_edge_exclude_mm': 2.0,      # c5_floff2.py EXCL
    'floor_domain': None,              # v26 [64, 124, -31, 31]; auto: outline + wall bbox + floor_domain_margin_mm
    'floor_domain_margin_mm': 4.0,
    'outline_samples': 400,            # c5_floff2.py 401 samples
    'outline_offset_samples': 720,     # c5_floff2.py 721 samples
    'outline_kink_deg': 20.0,          # kink = local turning maximum above this (v18: 46 deg at the rear centre)
    'outline_kink_mm': 1.6,            # c5_floff2.py drop box |dy| < 1.6 around the kink
    'slot_band_mm': 1.0,               # spec 8.5 seam band |y - mirror_y| <= 1.0
    'mirror_y': None,                  # mirror plane y = mirror_y (standard frame: x front, y left, z up); None -> bbox centre y of the shell
    'audit_samples': 30000,
    'audit_band_mm': 2.0,              # thickness audit above bearing z_max + 2 (c5_check.py z > 9 on v18)
    'window_margin_mm': 1.5,           # c5_check.py window exclusion margin
    'deflection_mm': 0.01,
    'compact_step': True,              # c5_wnopc.py + c4_round.py: no pcurves, 10 significant digits
    'reference_samples': 6000,
}
SHEET_EPS = 1e-7


def P_(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ------------------------------------------------------------------ small OCP helpers
def lst(ol) -> list:
    out = []
    try:
        for s in ol:
            out.append(s)
        return out
    except TypeError:
        from OCP.TopTools import TopTools_ListIteratorOfListOfShape
        it = TopTools_ListIteratorOfListOfShape(ol)
        while it.More():
            out.append(it.Value())
            it.Next()
        return out


def tlist(shapes):
    from OCP.TopTools import TopTools_ListOfShape
    t = TopTools_ListOfShape()
    for s in shapes:
        t.Append(s)
    return t


def cut(arg, tools, what: str, fuzzy: float | None = None):
    """Gated Boolean cut -> (op, solids). Raises on a failed / empty result."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    op = BRepAlgoAPI_Cut()
    op.SetArguments(tlist([arg]))
    op.SetTools(tlist(tools))
    op.SetRunParallel(True)
    if fuzzy:
        op.SetFuzzyValue(fuzzy)
    t0 = time.time()
    op.Build()
    if not op.IsDone() or (hasattr(op, 'HasErrors') and op.HasErrors()):
        raise WorkerError('CARVE_BOOLEAN', f'Boolean cut failed: {what}.', {'stage': what})
    so = L.solids(op.Shape())
    P_(f' cut {what}: {round(time.time() - t0, 1)} s, solids {len(so)}')
    if not so:
        raise WorkerError('CARVE_BOOLEAN', f'Boolean cut returned no solid: {what}.', {'stage': what})
    return op, so


def images(op, shapes) -> list:
    out = []
    for s in shapes:
        m = lst(op.Modified(s))
        if m:
            out.extend(m)
        elif not op.IsDeleted(s):
            out.append(s)
    return out


def face_map(shape):
    from OCP.TopTools import TopTools_IndexedMapOfShape
    from OCP.TopExp import TopExp
    from OCP.TopAbs import TopAbs_FACE
    m = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, m)
    return m


def present(shape, faces) -> list:
    m = face_map(shape)
    return [f for f in faces if m.Contains(f)]


def same_index(F, f) -> int:
    for i, g in enumerate(F):
        if g.IsSame(f):
            return i
    return -1


def edge_faces(shape):
    from OCP.TopExp import TopExp
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
    m = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, m)
    return [(m.FindKey(i), lst(m.FindFromIndex(i))) for i in range(1, m.Extent() + 1)]


def edge_points(e, n=12) -> np.ndarray:
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRep import BRep_Tool
    from OCP.TopoDS import TopoDS
    e = TopoDS.Edge_s(e)
    if BRep_Tool.Degenerated_s(e):
        return np.zeros((0, 3))
    c = BRepAdaptor_Curve(e)
    return np.array([c.Value(t).Coord() for t in np.linspace(c.FirstParameter(), c.LastParameter(), n)])


def edge_length(e) -> float:
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    g = GProp_GProps()
    BRepGProp.LinearProperties_s(e, g)
    return float(g.Mass())


def surface(f):
    from OCP.BRep import BRep_Tool
    s = BRep_Tool.Surface_s(f)
    while hasattr(s, 'BasisSurface') and not hasattr(s, 'BasisCurve'):
        s = s.BasisSurface()
    return s


def same_extrusion(F, idx, tol=1e-4) -> bool:
    """True if the faces idx lie on one extrusion surface (same basis curve and direction): a closed outline split at its seam into several faces."""
    c0 = surface(F[idx[0]]).BasisCurve()
    d0 = surface(F[idx[0]]).Direction()
    ts = np.linspace(c0.FirstParameter(), c0.LastParameter(), 9)
    P0 = np.array([c0.Value(t).Coord() for t in ts])
    for j in idx[1:]:
        sj = surface(F[j])
        cj = sj.BasisCurve()
        Pj = np.array([cj.Value(t).Coord() for t in np.linspace(cj.FirstParameter(), cj.LastParameter(), 9)])
        dj = sj.Direction()
        if np.abs(Pj - P0).max() > tol or abs(d0.X() - dj.X()) + abs(d0.Y() - dj.Y()) + abs(d0.Z() - dj.Z()) > 1e-6:
            return False
    return True


def is_extrusion(f) -> bool:
    return hasattr(surface(f), 'BasisCurve') and hasattr(surface(f), 'Direction')


def split_keep(solid, face, inside_pt, what: str):
    """Split `solid` by one face; return the piece holding inside_pt (gate: exactly one)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Splitter
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_IN
    from OCP.gp import gp_Pnt
    sp = BRepAlgoAPI_Splitter()
    sp.SetArguments(tlist([solid]))
    sp.SetTools(tlist([face]))
    sp.Build()
    if not sp.IsDone() or (hasattr(sp, 'HasErrors') and sp.HasErrors()):
        raise WorkerError('CARVE_SPLIT', f'Splitting failed: {what}.')
    pcs = L.solids(sp.Shape())
    keep = [s for s in pcs if BRepClass3d_SolidClassifier(s, gp_Pnt(*map(float, inside_pt)), 1e-6).State() == TopAbs_IN]
    if len(pcs) < 2 or len(keep) != 1:
        raise WorkerError('CARVE_SPLIT', f'The surface does not split the box into one cavity piece: {what}.',
                          {'pieces': len(pcs), 'holding_point': len(keep), 'point': list(map(float, inside_pt))})
    k = keep[0]
    if not L.is_valid(k):
        raise WorkerError('CARVE_INVALID', f'Split piece is not a valid solid: {what}.')
    return k, len(pcs)


def box_solid(x0, y0, z0, x1, y1, z1):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    return L.solids(BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape())[0]


def prism_of_wire(wire, vec):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec
    f = BRepBuilderAPI_MakeFace(wire, True).Face()
    pr = BRepPrimAPI_MakePrism(f, gp_Vec(*map(float, vec))).Shape()
    s = L.solids(pr)
    if len(s) != 1 or not L.is_valid(s[0]):
        raise WorkerError('CARVE_PRISM', 'Prism construction failed.')
    return s[0]


def closed_curve_wire(P3):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.TColgp import TColgp_HArray1OfPnt
    from OCP.GeomAPI import GeomAPI_Interpolate
    from OCP.gp import gp_Pnt
    H = TColgp_HArray1OfPnt(1, len(P3))
    for i, q in enumerate(P3):
        H.SetValue(i + 1, gp_Pnt(*map(float, q)))
    it = GeomAPI_Interpolate(H, True, 1e-6)
    it.Perform()
    if not it.IsDone():
        raise WorkerError('CARVE_OUTLINE', 'Periodic interpolation of the plate outline failed.')
    c = it.Curve()
    return c, BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(c).Edge()).Wire()


def polyline_wire(P3):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
    from OCP.gp import gp_Pnt
    mp = BRepBuilderAPI_MakePolygon()
    for q in P3:
        mp.Add(gp_Pnt(*map(float, q)))
    mp.Close()
    return mp.Wire()


# ------------------------------------------------------------------ face sampling
def uv_loops(f):
    """UV polygons of the outer wire and of the inner wires (holes) of face f."""
    from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
    from OCP.BRepAdaptor import BRepAdaptor_Curve2d
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopoDS import TopoDS
    outer = BRepTools.OuterWire_s(f)
    loops = []
    for w in _wires(f):
        we = BRepTools_WireExplorer(w, f)
        pts = []
        while we.More():
            e = TopoDS.Edge_s(we.Current())
            c = BRepAdaptor_Curve2d(e, f)
            t0, t1 = c.FirstParameter(), c.LastParameter()
            ts = np.linspace(t0, t1, 64)
            if e.Orientation() == TopAbs_REVERSED:
                ts = ts[::-1]
            pts.append(np.array([c.Value(t).Coord() for t in ts[:-1]]))
            we.Next()
        if pts:
            loops.append((w.IsSame(outer), np.vstack(pts)))
    return [p for o, p in loops if o], [p for o, p in loops if not o]


def _wires(f):
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_WIRE
    from OCP.TopoDS import TopoDS
    ex = TopExp_Explorer(f, TopAbs_WIRE)
    out = []
    while ex.More():
        out.append(TopoDS.Wire_s(ex.Current()))
        ex.Next()
    return out


def sample_face(f, n_u, n_v, ext=0.0):
    """Grid samples of the face's own surface over its UV box (+ext): points, outward normals, in_face, in_outer (holes filled)."""
    from matplotlib.path import Path as MPath
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Pnt, gp_Vec
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.BRep import BRep_Tool
    srf = BRep_Tool.Surface_s(f)
    rev = f.Orientation() == TopAbs_REVERSED
    u0, u1, v0, v1 = BRepTools.UVBounds_s(f)
    su0, su1, sv0, sv1 = srf.Bounds()
    du, dv = (u1 - u0) * ext, (v1 - v0) * ext
    U = np.linspace(max(su0, u0 - du), min(su1, u1 + du), n_u)
    V = np.linspace(max(sv0, v0 - dv), min(sv1, v1 + dv), n_v)
    UU, VV = np.meshgrid(U, V, indexing='ij')
    uv = np.c_[UU.ravel(), VV.ravel()]
    outer, inner = uv_loops(f)
    in_outer = np.zeros(len(uv), bool)
    for o in outer:
        in_outer |= MPath(o).contains_points(uv, radius=-1e-9) | MPath(o).contains_points(uv, radius=1e-9)
    in_hole = np.zeros(len(uv), bool)
    for h in inner:
        in_hole |= MPath(h).contains_points(uv)
    P = np.empty((len(uv), 3))
    N = np.full((len(uv), 3), np.nan)
    p, a, b = gp_Pnt(), gp_Vec(), gp_Vec()
    for i, (u, v) in enumerate(uv):
        srf.D1(float(u), float(v), p, a, b)
        n = a.Crossed(b)
        m = n.Magnitude()
        P[i] = p.X(), p.Y(), p.Z()
        if m > 1e-12:
            N[i] = (n.X() / m, n.Y() / m, n.Z() / m)
    if rev:
        N = -N
    ok = np.isfinite(N[:, 0])
    return P[ok], N[ok], (in_outer & ~in_hole)[ok], in_outer[ok]


# ------------------------------------------------------------------ roles
def heal_input_mesh(S):
    """-> (solid, repair log or None). An input face that BRepMesh drops (a 2D wire gap the STEP reader re-creates from near-miss 3D curves)
    would leave the roles, the offsets and every volume check blind on that face and makes the Booleans fragile; it is repaired on a copy
    (mouse_groove_fill_worker.heal_meshable: ShapeFix_Shape under face-count / validity / volume / bbox gates) and the face order is
    checked (per-face bbox centres within 0.02 mm) because every role hint is a face index. A failed repair is CARVE_INPUT_MESH, never a
    silent skip; the repaired input is reported (check input_mesh_complete = WARN) and the written output is gated again after its own
    STEP round trip (output_tessellates_after_round_trip)."""
    from cadmcp_brain.studio import mouse_groove_fill_worker as GF
    miss = GF.unmeshed_faces(S, 0.05, clean=True)
    if not miss:
        return S, None

    def _err(code, msg, details):
        raise WorkerError('CARVE_INPUT_MESH', msg + ' Re-run the upstream cut (brain_mouse_click_slots CS1.6 gates tessellation after a '
                          'STEP round trip) instead of carving this file.', details)
    F0 = L.faces(S)
    S2, log = GF.heal_meshable(S, 0.05, 'The filled shell', err=_err)
    F2 = L.faces(S2)
    c0 = np.array([L.bbox(f) for f in F0]).reshape(len(F0), 2, 3).mean(1)
    c2 = np.array([L.bbox(f) for f in F2]).reshape(len(F2), 2, 3).mean(1)
    shift = float(np.abs(c0 - c2).max()) if len(F0) == len(F2) else float('inf')
    if shift > 0.02:
        raise WorkerError('CARVE_INPUT_MESH', 'The meshability repair of the input changed the face order; face-index role hints would be wrong.',
                          {'max_face_centre_shift_mm': shift, 'repair': log})
    log = {**log, 'face_order_max_centre_shift_mm': shift}
    P_(f' input mesh repair: {log}')
    return S2, log


def face_table(S, F, defl):
    m = L.tessellate(S, defl, 0.2)
    V, T, FID = m['V'], m['T'], m['FID']
    cr = np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]])
    rows = []
    for k in range(len(F)):
        sel = FID == k
        A2 = np.linalg.norm(cr[sel], axis=1)
        n = cr[sel].sum(0)
        coh = float(np.linalg.norm(n) / (A2.sum() + 1e-15))
        n = n / (np.linalg.norm(n) + 1e-15)
        abs_nz = float((np.abs(cr[sel][:, 2])).sum() / (A2.sum() + 1e-15))
        no_mesh = not sel.any()
        rows.append({'index': k, 'area_mm2': float(L.area(F[k])) if no_mesh else float(0.5 * A2.sum()), 'mean_normal': n, 'coherence': coh,
                     'mean_abs_nz': abs_nz, 'extrusion': is_extrusion(F[k]), 'no_mesh': no_mesh})
    return rows, m


def adjacency(S, F):
    adj = {i: set() for i in range(len(F))}
    for e, fl in edge_faces(S):
        ids = sorted({same_index(F, f) for f in fl} - {-1})
        for i in ids:
            adj[i] |= set(ids) - {i}
    return adj


def read_hints(inputs: dict, n_faces: int) -> dict:
    """Role hints from earlier tool outputs (all optional, never required): face_roles.json of brain_mouse_face_roles (list `top_shell` of
    {index, role}: parting = bearing, shell / panel = skin) and the split_click report (plate-outline / click-floor faces of the shell it wrote).
    Hints are used only when their face count matches the shell (same face order); otherwise they are reported and ignored."""
    import json
    hint: dict[str, Any] = {'bearing': None, 'skin': None, 'step': None, 'floor': None, 'used': [], 'ignored': []}

    def load(key):
        p = inputs.get(key)
        if not p:
            return None
        try:
            return json.loads(Path(p).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            hint['ignored'].append({'source': key, 'reason': 'unreadable JSON'})
            return None
    fr = load('face_roles_json')
    if isinstance(fr, dict) and isinstance(fr.get('top_shell'), list):
        rows = [r for r in fr['top_shell'] if isinstance(r, dict) and isinstance(r.get('index'), int)]
        if len(rows) == n_faces and sorted(r['index'] for r in rows) == list(range(n_faces)):
            hint['bearing'] = [r['index'] for r in rows if r.get('role') == 'parting'] or None
            hint['skin'] = [r['index'] for r in rows if r.get('role') in ('shell', 'panel')] or None
            hint['used'].append('face_roles_json')
        else:
            hint['ignored'].append({'source': 'face_roles_json', 'reason': 'face count differs from the shell', 'faces_in_file': len(rows), 'faces': n_faces})
    elif fr is not None:
        hint['ignored'].append({'source': 'face_roles_json', 'reason': 'no top_shell list'})
    sr = load('split_report')
    if isinstance(sr, dict):
        cand = None
        for holder in (sr, sr.get('handoff'), sr.get('carve_handoff'), sr.get('outputs')):
            if isinstance(holder, dict):
                for key in ('carve_face_roles', 'face_roles', 'shell_open_face_roles'):
                    if isinstance(holder.get(key), dict):
                        cand = holder[key]
                        break
            if cand:
                break
        if cand:
            ok = all(isinstance(cand.get(k, []), list) and all(isinstance(i, int) and 0 <= i < n_faces for i in cand.get(k, []))
                     for k in ('step', 'floor', 'bearing'))
            if ok and (cand.get('step') or cand.get('floor')):
                hint['step'] = list(cand.get('step') or []) or None
                hint['floor'] = list(cand.get('floor') or []) or None
                if cand.get('bearing') and not hint['bearing']:
                    hint['bearing'] = list(cand['bearing'])
                hint['used'].append('split_report')
            else:
                hint['ignored'].append({'source': 'split_report', 'reason': 'face_roles entry has no usable step / floor indices of this shell'})
        else:
            hint['ignored'].append({'source': 'split_report', 'reason': 'report holds no face_roles / carve_face_roles hand-off'})
    return hint


def grow_skin(S, F, rows, wall, excl, min_frac, tol_deg, rim=()):
    """Add faces that continue a wall (skin) face tangentially (normals along the shared edge within tol_deg), also when small (e.g. a 140 mm2 skin strip
    between two large faces, 0.8 % of the area): leaving such a face out lets the fitted cavity break through the skin there."""
    wall = list(wall)
    if not wall:
        return wall, []
    amin = min_frac * sum(r['area_mm2'] for r in rows)
    pairs = []
    for e, fl in edge_faces(S):
        ids = sorted({same_index(F, f) for f in fl} - {-1})
        if len(ids) == 2:
            pairs.append((e, ids[0], ids[1]))
    grown, cos_tol = [], math.cos(math.radians(tol_deg))
    changed = True
    while changed:
        changed = False
        for e, a, b in pairs:
            for x, y in ((a, b), (b, a)):
                if x in wall and y not in wall and y not in excl and y not in rim and rows[y]['area_mm2'] >= amin:
                    q = edge_points(e, 5)
                    if not len(q):
                        continue
                    cs = []
                    for pnt in q:
                        na, nb = L.face_normal_at(F[x], pnt), L.face_normal_at(F[y], pnt)
                        cs.append(float(np.dot(na, nb)) if np.all(np.isfinite(na)) and np.all(np.isfinite(nb)) else -1.0)
                    if min(cs) >= cos_tol:
                        wall.append(y)
                        grown.append(y)
                        changed = True
    return sorted(wall), grown


def roles(S, F, prm, rows, hint=None):
    """Roles: explicit face_roles > hints from earlier tool outputs > geometry. step + floor (the click recess) are optional: a shell without a
    plate-outline step face (not split yet) is carved with the wall offset everywhere (click_recess False)."""
    given = prm.get('face_roles') or {}
    hint = hint or {}
    n = len(F)
    for k, v in given.items():
        if k not in ('wall', 'floor', 'step', 'bearing') or not isinstance(v, list) or not all(isinstance(i, int) and 0 <= i < n for i in v):
            raise WorkerError('CARVE_ROLES', 'face_roles maps wall / floor / step / bearing to lists of face indices of the shell solid.',
                              {'role': k, 'faces': n})
    adj = adjacency(S, F)
    sources = {}
    bearing = given.get('bearing')
    sources['bearing'] = 'face_roles' if bearing else None
    if not bearing and hint.get('bearing'):
        bearing, sources['bearing'] = list(hint['bearing']), 'hint'
    if not bearing:
        bearing = [r['index'] for r in rows if r['mean_normal'][2] < -0.9 and r['coherence'] > 0.9 and r['area_mm2'] > 1.0]
        sources['bearing'] = 'geometry'
    step = given.get('step')
    floor = given.get('floor')
    sources['step'] = 'face_roles' if step else None
    if step is None and hint.get('step'):
        step, sources['step'] = list(hint['step']), 'hint'
    if floor is None and hint.get('floor'):
        floor = list(hint['floor'])
    if step is None:
        cand = [r for r in rows if r['extrusion'] and r['mean_abs_nz'] < 0.3]
        cand = [r for r in cand if abs(surface(F[r['index']]).Direction().Z()) > 0.99]
        step = [max(cand, key=lambda r: r['area_mm2'])['index']] if cand else []
        sources['step'] = 'geometry'
    if floor is None and step:
        # floor = up-facing face meeting the step face along its LOWER edge (the rim above the step meets its upper edge)
        st = F[step[0]]
        zmid = 0.5 * (L.bbox(st)[2] + L.bbox(st)[5])
        low = {}
        for e, fl in edge_faces(S):
            if any(f.IsSame(st) for f in fl):
                q = edge_points(e)
                for f in fl:
                    j = same_index(F, f)
                    if j != step[0] and len(q):
                        low.setdefault(j, []).append(float(q[:, 2].mean()))
        cand = [rows[j] for j, zs in low.items() if rows[j]['mean_normal'][2] > 0.5 and rows[j]['coherence'] > 0.5 and j not in bearing
                and np.mean(zs) < zmid]
        floor = [max(cand, key=lambda r: r['area_mm2'])['index']] if cand else []
    floor = floor or []
    if not bearing:
        raise WorkerError('CARVE_ROLES', 'No bearing (bottom, normal -z) face found; pass face_roles.bearing.', {'step': step, 'floor': floor})
    recess = bool(step and floor)
    if bool(step) != bool(floor):
        raise WorkerError('CARVE_ROLES', 'Found only one of the plate-outline step face and the click floor face; give both in face_roles (or neither '
                          'for a shell without a click recess).', {'step': step, 'floor': floor})
    if recess and not all(is_extrusion(F[j]) for j in step):
        raise WorkerError('CARVE_ROLES', 'The step face(s) must be linear extrusions of the closed plate outline (v26 method).', {'step': step})
    if recess and len(step) > 1 and not same_extrusion(F, step):
        raise WorkerError('CARVE_ROLES', 'Several step faces are given but they do not share one extrusion surface (one plate outline).', {'step': step})
    amin = prm['wall_face_min_area_mm2']
    if amin is None:
        amin = float(prm['wall_face_min_area_frac']) * sum(r['area_mm2'] for r in rows)
    excl = set(floor) | set(step) | set(bearing)
    wall = given.get('wall')
    sources['wall'] = 'face_roles' if wall else None
    if not wall:
        pool = hint.get('skin')
        sources['wall'] = 'hint+area' if pool else 'geometry'
        if pool:
            # skin faces named by an earlier tool (brain_mouse_face_roles shell / panel) are authoritative: every one of them with a real area counts, also
            # small ones (e.g. a 140 mm2 rear skin strip, 0.8 % of the area) that the plain area threshold would drop and leave the cavity fit unconstrained
            amin_h = float(prm['wall_face_min_area_frac_hint']) * sum(r['area_mm2'] for r in rows)
            wall = [r['index'] for r in rows if r['index'] in set(pool) and r['index'] not in excl and r['area_mm2'] >= amin_h]
        else:
            wall = [r['index'] for r in rows if r['area_mm2'] >= amin and r['index'] not in excl]
            # a small skin face that borders the plate-outline step is the recess rim: its inner side is the floor prism K (outline + wall),
            # not a skin offset in G (v26: the 116 mm2 rim strip is not offset; offsetting it moves the cavity by ~90 mm3 / 2 mm there)
            rim = {j for k in step for j in adj[k]} if recess else set()
            wall, grown = grow_skin(S, F, rows, wall, excl, float(prm['wall_face_min_area_frac_hint']), float(prm['skin_tangent_deg']), rim)
            sources['wall_grown_by_tangency'] = grown
            sources['rim_faces_not_grown'] = sorted(j for j in rim if j not in excl and j not in wall and rows[j]['area_mm2'] >= 1.0)
    if not wall:
        raise WorkerError('CARVE_ROLES', 'No wall (skin) faces found; lower wall_face_min_area_mm2 or pass face_roles.wall.')
    tiny = sorted({j for k in step for j in adj[k] if j not in step and rows[j]['area_mm2'] < 0.5}) if recess else []
    return {'wall': wall, 'floor': floor, 'step': step, 'bearing': bearing, 'tiny_next_to_step': tiny, 'click_recess': recess, 'sources': sources}


# ------------------------------------------------------------------ windows
def prism_info(sol):
    """A window tool must be a prism: two antiparallel planar end faces, every other face parallel to the axis."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    Fs = L.faces(sol)
    planes = []
    for f in Fs:
        a = BRepAdaptor_Surface(f)
        if a.GetType() == GeomAbs_Plane:
            q, n = L.inner_point(f)
            if q is not None:
                planes.append((f, q, n))
    for i in range(len(planes)):
        for j in range(i + 1, len(planes)):
            fi, qi, ni = planes[i]
            fj, qj, nj = planes[j]
            if float(ni @ nj) > -0.9999:
                continue
            ax = ni / np.linalg.norm(ni)
            ok = True
            for f in Fs:
                if f.IsSame(fi) or f.IsSame(fj):
                    continue
                q, n = L.inner_point(f)
                if q is None or abs(float(n @ ax)) > 1e-3:
                    ok = False
                    break
            if ok:
                return {'end_faces': (fi, fj), 'points': (qi, qj), 'normals': (ni, nj), 'axis': ax}
    return None


def window_prism(sol, center):
    info = prism_info(sol)
    if info is None:
        return None
    (fa, fb), (qa, qb), (na, nb) = info['end_faces'], info['points'], info['normals']
    # outer end face = farther from the shell centre; axis points inward (outer -> inner)
    if np.linalg.norm(qa - center) >= np.linalg.norm(qb - center):
        fo, qo, no, fi_, qi = fa, qa, na, fb, qb
    else:
        fo, qo, no, fi_, qi = fb, qb, nb, fa, qa
    ax = -no / np.linalg.norm(no)
    e2 = np.array([0.0, 0.0, 1.0]) - ax[2] * ax
    if np.linalg.norm(e2) < 1e-6:
        e2 = np.array([1.0, 0.0, 0.0]) - ax[0] * ax
    e2 /= np.linalg.norm(e2)
    e1 = np.cross(ax, e2)
    W = L.wire_points(fo, 0.05)
    xy = np.c_[(W - qo) @ e1, (W - qo) @ e2]
    return {'axis': ax, 'origin': qo, 'e1': e1, 'e2': e2, 'outline2d': xy, 'depth': float((qi - qo) @ ax), 'outer_face': fo}


def in_prism(pr, Pts, margin=0.0):
    from matplotlib.path import Path as MPath
    d = Pts - pr['origin']
    a = d @ pr['axis']
    xy = np.c_[d @ pr['e1'], d @ pr['e2']]
    inside = MPath(pr['outline2d']).contains_points(xy)
    if margin > 0:
        from scipy.spatial import cKDTree
        d, _ = cKDTree(pr['outline2d']).query(xy)
        inside |= d <= margin
    return inside & (a >= -margin) & (a <= pr['depth'] + margin)


def slot_axis_3d(pr):
    Pt = pr['outline2d']
    w, Vv = np.linalg.eigh(np.cov((Pt - Pt.mean(0)).T))
    u = Vv[:, 1]
    return u[0] * pr['e1'] + u[1] * pr['e2']


def sill_rect(pr, sill):
    """c5_k3.py: rectangle in the PCA frame of the window outline: a +-margin, b from min - drop_mm to max - margin (prism-frame 2D)."""
    Pt = pr['outline2d']
    c0 = Pt.mean(0)
    w, Vv = np.linalg.eigh(np.cov((Pt - c0).T))
    u, v = Vv[:, 1], Vv[:, 0]
    if v[1] < 0:
        v = -v
    if u[0] < 0:
        u = -u
    a, b = (Pt - c0) @ u, (Pt - c0) @ v
    mg, dz = float(sill.get('margin_mm', 0.3)), float(sill['drop_mm'])
    R = [(a.min() - mg, b.min() - dz), (a.max() + mg, b.min() - dz), (a.max() + mg, b.max() - mg), (a.min() - mg, b.max() - mg)]
    return np.array([c0 + p * u + q * v for p, q in R]), {'rect_ab': np.round(R, 3).tolist(), 'slot_axis_2d': np.round(u, 4).tolist()}


def sill_tool(pr, sill):
    """c5_k3.py: the sill rectangle extruded depth_mm inward from the outer end face."""
    H, geo = sill_rect(pr, sill)
    P3 = [pr['origin'] + h[0] * pr['e1'] + h[1] * pr['e2'] for h in H]
    return prism_of_wire(polyline_wire(P3), pr['axis'] * float(sill['depth_mm'])), geo


def pocket_region(pr, sill):
    """Region where the wall surface is continued over a side-button pocket: the window prism, widened to the hull of the window
    outline and its sill rectangle when the window has a sill (under a sill the cavity keeps the true wall offset G, c5_k3.py)."""
    if not sill:
        return pr
    from scipy.spatial import ConvexHull
    H, _ = sill_rect(pr, sill)
    Pt = np.vstack([pr['outline2d'], H])
    return {**pr, 'outline2d': Pt[ConvexHull(Pt).vertices]}


# ------------------------------------------------------------------ G: star-shaped ray grid + LSQ B-spline
def ray_inv(Q, C, AX, AY, AZ):
    u = Q - C
    a = u[:, 0] / u[:, 2]
    b = u[:, 1] / u[:, 2]
    al, be = AZ * a / AX, AZ * b / AY
    hi = np.minimum(1.0, np.minimum(1 / np.maximum(np.abs(al), 1e-12), 1 / np.maximum(np.abs(be), 1e-12)))
    lo = np.zeros_like(hi)
    for _ in range(60):
        w = (lo + hi) / 2
        f = w - (1 - (al * w) ** 2) * (1 - (be * w) ** 2)
        hi = np.where(f > 0, w, hi)
        lo = np.where(f > 0, lo, w)
    w = (lo + hi) / 2
    return al * w, be * w, np.linalg.norm(u, axis=1)


def lsq_tensor(G, NCU, NCV, LAM, zpin):
    from scipy.interpolate import BSpline
    ns, nt, _ = G.shape
    p = 3

    def knots(nc):
        return np.r_[[0.0] * p, np.linspace(0, 1, nc - p + 1), [1.0] * p]

    def solve(Bm):
        n = Bm.shape[1]
        D = np.diff(np.eye(n), 2, axis=0)
        return np.linalg.solve(Bm.T @ Bm + LAM * D.T @ D, Bm.T)
    ku, kv = knots(NCU), knots(NCV)
    Bu = BSpline.design_matrix(np.linspace(0, 1, ns), ku, p).toarray()
    Bv = BSpline.design_matrix(np.linspace(0, 1, nt), kv, p).toarray()
    Pp = np.einsum('ai,ijk,bj->abk', solve(Bu), G, solve(Bv))
    Pp[0, :, 2] = Pp[-1, :, 2] = zpin
    Pp[:, 0, 2] = Pp[:, -1, 2] = zpin
    fit = np.einsum('ai,ijk,bj->abk', Bu, Pp, Bv)
    return Pp, ku, kv, np.linalg.norm(fit - G, axis=-1)


def eval_tensor(Pp, ku, kv, ns, nt):
    from scipy.interpolate import BSpline
    Bu = BSpline.design_matrix(np.linspace(0, 1, ns), ku, 3).toarray()
    Bv = BSpline.design_matrix(np.linspace(0, 1, nt), kv, 3).toarray()
    return np.einsum('ai,ijk,bj->abk', Bu, Pp, Bv)


def build_G(S, F, R, prm, side_prisms, bb):
    from scipy.interpolate import LinearNDInterpolator, griddata
    from scipy.ndimage import minimum_filter
    from scipy.spatial import cKDTree
    T = prm['wall_mm']
    C = np.array(prm['ray_center'], float)
    AX, AY, AZ = map(float, prm['ray_axes'])
    NS, NT = map(int, prm['grid'])
    # bottom height interpolator from the bearing faces
    tb = [L.tessellate(F[i], 0.02, 0.2)['V'] for i in R['bearing']]
    Tb = np.unique(np.round(np.vstack(tb), 4), axis=0)
    zb = LinearNDInterpolator(Tb[:, :2], Tb[:, 2])
    zseed = float(Tb[:, 2].min()) + prm['bottom_band_mm']
    t0 = time.time()
    samp = {}
    for fi in R['wall']:
        Pp, Nn, inf, ino = sample_face(F[fi], prm['face_samples'], prm['face_samples'], prm['face_uv_extend'])
        samp[fi] = (Pp, Nn, inf, ino)
        P_(f' face {fi}: samples {len(Pp)} in {int(inf.sum())} in_outer {int(ino.sum())}')
    out, TRUE, stats = [], [], {}
    for fi in R['wall']:
        Pp, Nn, inf, ino = samp[fi]
        keep = ino.copy()
        # side-button pocket: the face's own surface continued inside the window prism, only over the slot-axis range the face itself
        # covers next to the pocket (+- pocket_side_tol_mm; c5_gpts.py split the rear / front faces at x 69.7 / 69.1 around their 69.4 seam)
        for pr in side_prisms:
            cand = in_prism(pr, Pp, prm['pocket_margin_mm']) & ~keep
            near = inf & in_prism(pr, Pp, prm['pocket_near_mm'])
            if not cand.any() or not near.any():
                continue
            ax = slot_axis_3d(pr)
            u_near, u_c = Pp[near] @ ax, Pp[cand] @ ax
            ok = (u_c >= u_near.min() - prm['pocket_side_tol_mm']) & (u_c <= u_near.max() + prm['pocket_side_tol_mm'])
            keep[np.where(cand)[0][ok]] = True
        Q = Pp[keep] - T * Nn[keep]
        zq = zb(Q[:, :2])
        seed = Q[(np.isfinite(zq) & (Q[:, 2] < zq + prm['bottom_band_mm'])) | (Q[:, 2] < zseed)]
        ext = np.vstack([seed - np.array([0, 0, prm['bottom_extend_step_mm'] * k]) for k in range(1, int(prm['bottom_extend_steps']) + 1)]) \
            if len(seed) else np.zeros((0, 3))
        ext = ext[ext[:, 2] > C[2] + 0.5]
        TRUE.append(Q)
        out.append(np.vstack([Q, ext]))
        stats[str(fi)] = {'kept': int(keep.sum()), 'holes_filled': int((ino & ~inf).sum()), 'pocket_filled': int((keep & ~ino).sum()),
                          'down_extension': int(len(ext))}
    Gd = np.vstack(out)
    fl = []
    for fi in R['floor']:
        Pp, Nn, inf, ino = sample_face(F[fi], prm['floor_fill_samples'], prm['floor_fill_samples'], 0.0)
        fl.append(Pp[ino] + prm['floor_fill_lift_mm'] * Nn[ino])
    Fl = np.vstack(fl) if fl else np.zeros((0, 3))
    P_(f' G samples {len(Gd)} floor fill {len(Fl)} ({round(time.time() - t0, 1)} s)')
    allQ = np.vstack([Gd, Fl])
    src = np.r_[np.zeros(len(Gd)), np.ones(len(Fl))]
    ok = allQ[:, 2] > C[2] + 0.05
    allQ, src = allQ[ok], src[ok]
    Ss, Tt, Rr = ray_inv(allQ, C, AX, AY, AZ)
    key = np.round(np.c_[Ss, Tt] / prm['dedup_st']).astype(np.int64)
    _, uix = np.unique(key, axis=0, return_index=True)
    Ss, Tt, Rr, src = Ss[uix], Tt[uix], Rr[uix], src[uix]
    hs, ht = 2 / (NS - 1), 2 / (NT - 1)
    bi = np.clip(((Ss + 1) / hs).astype(int), 0, NS)
    bj = np.clip(((Tt + 1) / ht).astype(int), 0, NT)
    BM = np.full((NS + 1, NT + 1), np.inf)
    g0 = src == 0
    np.minimum.at(BM, (bi[g0], bj[g0]), Rr[g0])
    BM3 = minimum_filter(BM, size=3, mode='nearest')
    front = (src == 0) | (Rr <= BM3[bi, bj] + prm['envelope_tol_mm'])
    dropped = int((~front).sum())
    Ss, Tt, Rr = Ss[front], Tt[front], Rr[front]
    s, t = np.linspace(-1, 1, NS), np.linspace(-1, 1, NT)
    SS, TTg = np.meshgrid(s, t, indexing='ij')
    Rg = griddata(np.c_[Ss, Tt], Rr, (SS, TTg), method='linear')
    miss = np.isnan(Rg)
    if miss.any():
        Rg[miss] = griddata(np.c_[Ss, Tt], Rr, (SS, TTg), method='nearest')[miss]
    D = np.stack([AX * SS, AY * TTg, AZ * (1 - SS ** 2) * (1 - TTg ** 2)], -1)
    D /= np.linalg.norm(D, axis=-1, keepdims=True)
    Gp = C + Rg[..., None] * D
    Pp, ku, kv, res = lsq_tensor(Gp, int(prm['poles'][0]), int(prm['poles'][1]), float(prm['smoothing']), float(C[2]))
    srf = L.bsurf(Pp, ku, kv)
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    face = BRepBuilderAPI_MakeFace(srf, SHEET_EPS).Face()
    mg = prm['box_margin_mm']
    box = box_solid(bb[0] - mg, bb[1] - mg, C[2] + 2.0, bb[3] + mg, bb[4] + mg, bb[5] + mg)
    inside = C + 0.5 * Rg[NS // 2, NT // 2] * D[NS // 2, NT // 2]
    G, npcs = split_keep(box, face, inside, 'cavity surface G')
    info = {'samples': int(len(Gd)), 'floor_fill': int(len(Fl)), 'per_face': stats, 'behind_envelope_dropped': dropped, 'grid': [NS, NT],
            'grid_missing_nearest_filled': int(miss.sum()), 'poles': list(Pp.shape[:2]), 'smoothing': prm['smoothing'],
            'grid_residual': {'max': float(res.max()), 'p99': float(np.percentile(res, 99)), 'p50': float(np.median(res))},
            'split_pieces': npcs, 'ray_center': C.tolist(), 'ray_axes': [AX, AY, AZ], 'seconds': round(time.time() - t0, 1)}
    return G, {'P': Pp, 'ku': ku, 'kv': kv, 'grid': Gp, 'true': np.vstack(TRUE), 'srf': srf}, info


# ------------------------------------------------------------------ K2: floor offset sheet + outline prism
def build_K2(S, F, R, prm, bb):
    import scipy.sparse as sp
    from scipy.interpolate import BSpline
    from scipy.sparse.linalg import spsolve
    from scipy.spatial import cKDTree
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.GeomAPI import GeomAPI_IntCS
    from OCP.Geom import Geom_Line
    from OCP.gp import gp_Pnt, gp_Dir, gp_Vec
    T, Tf = prm['wall_mm'], prm['floor_mm']
    Pl, SK = [], []
    for fi in R['floor']:
        Pp, Nn, inf, ino = sample_face(F[fi], prm['floor_samples'], prm['floor_samples'], 0.0)
        Pl.append(Pp[ino] - Tf * Nn[ino])
        SK.append(Pp[ino])
    Pl, SK = np.vstack(Pl), np.vstack(SK)
    # plate outline = basis curve of the step face, kink removed, periodic re-interpolation
    c = surface(F[R['step'][0]]).BasisCurve()
    t0, t1 = c.FirstParameter(), c.LastParameter()
    Q = np.array([c.Value(t).Coord() for t in np.linspace(t0, t1, int(prm['outline_samples']) + 1)[:-1]])
    if np.linalg.norm(Q[0] - np.array(c.Value(t1).Coord())) > 1e-3:
        raise WorkerError('CARVE_OUTLINE', 'The step face basis curve (plate outline) is not closed.')
    xy = Q[:, :2]
    d1, d0 = np.roll(xy, -1, 0) - xy, xy - np.roll(xy, 1, 0)
    ang = np.degrees(np.arccos(np.clip((d1 * d0).sum(1) / (np.linalg.norm(d1, axis=1) * np.linalg.norm(d0, axis=1) + 1e-15), -1, 1)))
    hot = ang > prm['outline_kink_deg']
    kinks = [i for i in np.where(hot)[0] if ang[i] >= ang[(i - 1) % len(ang)] and ang[i] >= ang[(i + 1) % len(ang)]]
    drop = np.zeros(len(xy), bool)
    for i in kinks:
        drop |= np.linalg.norm(xy - xy[i], axis=1) < prm['outline_kink_mm']
    Q = Q[~drop]
    OUTL, _ = closed_curve_wire(Q)
    tt = np.linspace(OUTL.FirstParameter(), OUTL.LastParameter(), int(prm['outline_offset_samples']) + 1)[:-1]
    pp, dd = [], []
    pt, dv = gp_Pnt(), gp_Vec()
    for t in tt:
        OUTL.D1(t, pt, dv)
        pp.append((pt.X(), pt.Y()))
        dd.append((dv.X(), dv.Y()))
    pp, dd = np.array(pp), np.array(dd)
    nrm = np.c_[dd[:, 1], -dd[:, 0]]
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
    area = 0.5 * np.sum(pp[:, 0] * np.roll(pp[:, 1], -1) - np.roll(pp[:, 0], -1) * pp[:, 1])
    if area < 0:
        nrm = -nrm
    po = pp + T * nrm
    zlo, zhi = bb[2] - 10.0, bb[5] + 5.4
    _, ow = closed_curve_wire(np.c_[po, np.full(len(po), zlo)])
    dist, _ = cKDTree(pp).query(SK[:, :2])
    keep = dist > prm['floor_edge_exclude_mm']
    if keep.sum() < 50:
        raise WorkerError('CARVE_FLOOR', 'Too few floor samples away from the plate outline.', {'kept': int(keep.sum())})
    NC, LAM, k = int(prm['floor_poles']), float(prm['floor_smoothing']), 3
    dom = prm.get('floor_domain')
    if dom is None:
        m = prm['floor_domain_margin_mm']
        dom = [float(po[:, 0].min() - m), float(po[:, 0].max() + m), float(po[:, 1].min() - m), float(po[:, 1].max() + m)]
    X0, X1, Y0, Y1 = map(float, dom)
    knx = np.r_[[X0] * k, np.linspace(X0, X1, NC - k + 1), [X1] * k]
    kny = np.r_[[Y0] * k, np.linspace(Y0, Y1, NC - k + 1), [Y1] * k]
    PP = Pl[keep]
    if PP[:, 0].min() < X0 or PP[:, 0].max() > X1 or PP[:, 1].min() < Y0 or PP[:, 1].max() > Y1:
        raise WorkerError('CARVE_FLOOR', 'floor_domain does not contain the floor samples.', {'domain': dom})
    n = len(PP)
    Bu = sp.csr_matrix(BSpline.design_matrix(PP[:, 0], knx, k))
    Bv = sp.csr_matrix(BSpline.design_matrix(PP[:, 1], kny, k))
    iu, wu = Bu.indices.reshape(n, -1), Bu.data.reshape(n, -1)
    iv, wv = Bv.indices.reshape(n, -1), Bv.data.reshape(n, -1)
    cols = (iu[:, :, None] * NC + iv[:, None, :]).reshape(n, -1)
    vals = (wu[:, :, None] * wv[:, None, :]).reshape(n, -1)
    rows_ = np.repeat(np.arange(n), cols.shape[1])
    A = sp.csr_matrix((vals.ravel(), (rows_, cols.ravel())), shape=(n, NC * NC))
    Dm = sp.diags([1.0, -2.0, 1.0], [0, 1, 2], shape=(NC - 2, NC))
    I = sp.identity(NC)
    M = (A.T @ A + LAM * (sp.kron(Dm, I).T @ sp.kron(Dm, I) + sp.kron(I, Dm).T @ sp.kron(I, Dm))).tocsc()
    h = spsolve(M, A.T @ PP[:, 2])
    res = np.abs(A @ h - PP[:, 2])
    gx = np.array([knx[i + 1:i + k + 1].mean() for i in range(NC)])
    gy = np.array([kny[i + 1:i + k + 1].mean() for i in range(NC)])
    Pol = np.stack(np.broadcast_arrays(gx[:, None], gy[None, :], h.reshape(NC, NC)), -1)
    Ssh = L.bsurf(Pol, knx, kny)
    sheet = BRepBuilderAPI_MakeFace(Ssh, SHEET_EPS).Face()
    miss = 0
    for q in po[::6]:
        ic = GeomAPI_IntCS(Geom_Line(gp_Pnt(float(q[0]), float(q[1]), 0.0), gp_Dir(0, 0, 1)), Ssh)
        miss += ic.NbPoints() != 1
    if miss:
        raise WorkerError('CARVE_FLOOR', 'The floor sheet is not single-valued over the plate outline + wall.', {'vertical_misses': miss})
    prism = prism_of_wire(ow, (0, 0, zhi - zlo))
    cxy = pp.mean(0)
    K2, npcs = split_keep(prism, sheet, (cxy[0], cxy[1], zhi - 1.0), 'K2 (outline prism above the floor sheet)')
    info = {'floor_samples': int(len(Pl)), 'kept_away_from_outline': int(keep.sum()), 'height_fit_residual': {'max': float(res.max()),
            'p99': float(np.percentile(res, 99))}, 'domain': [X0, X1, Y0, Y1], 'poles': NC, 'smoothing': LAM,
            'outline_kinks': [{'xy': np.round(xy[i], 3).tolist(), 'turn_deg': round(float(ang[i]), 1)} for i in kinks],
            'outline_samples_dropped': int(drop.sum()), 'outline_area_mm2': float(abs(area)), 'vertical_coverage_misses': miss}
    return K2, info


# ------------------------------------------------------------------ checks
def mesh_vol(shape, defl):
    m = L.tessellate(shape, defl, 0.1)
    V, T = m['V'], m['T']
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    return float(np.einsum('ij,ij->i', a, np.cross(b, c)).sum() / 6.0), m


def free_edges(shape) -> int:
    from OCP.BRep import BRep_Tool
    from OCP.TopoDS import TopoDS
    n = 0
    for e, fl in edge_faces(shape):
        if len(fl) < 2 and not BRep_Tool.Degenerated_s(TopoDS.Edge_s(e)):
            n += 1
    return n


def area_samples(m, sel, n, seed):
    V, T = m['V'], m['T'][sel]
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    cr = np.cross(b - a, c - a)
    ar = np.linalg.norm(cr, axis=1)
    ok = ar > 1e-12
    if not ok.any():
        return np.zeros((0, 3)), np.zeros((0, 3))
    a, b, c, cr, ar = a[ok], b[ok], c[ok], cr[ok], ar[ok]
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(ar), size=n, p=ar / ar.sum())
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    pts = (1 - s)[:, None] * a[idx] + (s * (1 - r2))[:, None] * b[idx] + (s * r2)[:, None] * c[idx]
    return pts, cr[idx] / ar[idx][:, None]


def area_samples_fid(m, sel, n, seed):
    idx_all = np.where(sel)[0]
    V, T = m['V'], m['T'][idx_all]
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    ar = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(ar), size=n, p=ar / ar.sum())
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    pts = (1 - s)[:, None] * a[idx] + (s * (1 - r2))[:, None] * b[idx] + (s * r2)[:, None] * c[idx]
    return pts, m['FID'][idx_all[idx]]


def surface_raw(f):
    from OCP.BRep import BRep_Tool
    return BRep_Tool.Surface_s(f)


def project(srf, p):
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCP.gp import gp_Pnt
    pr = GeomAPI_ProjectPointOnSurf(gp_Pnt(*map(float, p)), srf)
    if pr.NbPoints() == 0:
        return np.asarray(p, float), float('nan')
    return np.array(pr.NearestPoint().Coord()), float(pr.LowerDistance())


def thickness_stats(t, T):
    t = t[np.isfinite(t)]
    if not len(t):
        return {'n': 0}
    return {'n': int(len(t)), 'min': float(t.min()), 'p05': float(np.percentile(t, 5)), 'p50': float(np.median(t)), 'mean': float(t.mean()),
            'p95': float(np.percentile(t, 95)), 'max': float(t.max()), 'frac_within_0.1': float(np.mean(np.abs(t - T) <= 0.1))}


def mesh_distance(Vs, Ts, pts):
    import vtk
    from cadmcp_brain.studio import mouse_parts_lib as PL
    loc = vtk.vtkCellLocator()
    loc.SetDataSet(PL.polydata(Vs, Ts))
    loc.BuildLocator()
    cp = [0.0, 0.0, 0.0]
    cid, sid, d2 = vtk.reference(0), vtk.reference(0), vtk.reference(0.0)
    out = np.empty(len(pts))
    for i, p in enumerate(pts):
        loc.FindClosestPoint(list(map(float, p)), cp, cid, sid, d2)
        out[i] = math.sqrt(float(d2))
    return out


def write_out_step(shape, path: Path, compact: bool) -> None:
    if not compact:
        L.write_step(shape, path)
        return
    from OCP.Interface import Interface_Static
    Interface_Static.SetIVal_s('write.surfacecurve.mode', 0)
    try:
        L.write_step(shape, path)
    finally:
        Interface_Static.SetIVal_s('write.surfacecurve.mode', 1)
    txt = path.read_text(encoding='utf-8', errors='replace')
    hdr, sep, body = txt.partition('DATA;')

    def r(m):
        o = '%.10G' % float(m.group(0))
        if 'E' not in o and '.' not in o:
            o += '.'
        return o
    body = re.sub(r'(?<![#\w])-?\d+\.\d*(?:E[-+]?\d+)?', r, body)
    path.write_text(hdr + sep + body, encoding='utf-8')


# ------------------------------------------------------------------ run
def run(req: dict[str, Any]) -> dict[str, Any]:
    L.require_ocp()
    prm = {**DEFAULTS, **{k: v for k, v in req['params'].items() if k in DEFAULTS}}
    wins = req['params'].get('windows') or []
    t_start = time.time()
    S = L.one_solid(req['inputs']['shell'], 'CARVE_INPUT')
    if not L.is_valid(S):
        raise WorkerError('CARVE_INPUT', 'The filled shell solid is not valid.')
    S, input_mesh_repair = heal_input_mesh(S)
    F = L.faces(S)
    bb = L.bbox(S)
    center = np.array([(bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2, (bb[2] + bb[5]) / 2])
    if prm['ray_center'] is None:
        prm['ray_center'] = [float(center[0]), float(center[1]), float(bb[2] - 6.0)]
    if prm['ray_axes'] is None:
        prm['ray_axes'] = [float((bb[3] - bb[0]) / 2), float(0.48 * (bb[4] - bb[1])), float(bb[5] - prm['ray_center'][2])]
    if prm['ray_center'][2] >= bb[2]:
        raise WorkerError('CARVE_SETTINGS', 'ray_center must lie below the shell (z below its lowest point).', {'z_min': float(bb[2])})
    T = float(prm['wall_mm'])
    if prm['pocket_margin_mm'] is None:
        prm['pocket_margin_mm'] = 2.0 * T
    if prm['mirror_y'] is None:
        prm['mirror_y'] = float(center[1])
    R_fillet = T if prm['step_fillet_mm'] is None else float(prm['step_fillet_mm'])
    rows, Smesh = face_table(S, F, 0.05)
    hint = read_hints(req['inputs'], len(F))
    if req['inputs'].get('offset_source'):
        # v26: offsets from c5_clean_b.step (v18 with the wheel hole plugged and button A defeatured), cut applied to v18
        Ss = L.one_solid(req['inputs']['offset_source'], 'CARVE_INPUT')
        if not L.is_valid(Ss):
            raise WorkerError('CARVE_INPUT', 'The offset source solid is not valid.')
        Fs = L.faces(Ss)
        rows_s, _ = face_table(Ss, Fs, 0.05)
        Rs = roles(Ss, Fs, prm, rows_s, None)
        R = roles(S, F, {**prm, 'face_roles': None}, rows, hint)
        bbs = L.bbox(Ss)
    else:
        R = roles(S, F, prm, rows, hint)
        Ss, Fs, Rs, rows_s, bbs = S, F, R, rows, bb
    P_(f'roles {R}')
    vS = L.volume(S)
    mvS, _ = mesh_vol(S, prm['deflection_mm'])
    # windows
    W = []
    for i, w in enumerate(wins):
        sol = L.one_solid(req['inputs'][f'window_{i}'], 'CARVE_WINDOW')
        if not L.is_valid(sol):
            raise WorkerError('CARVE_WINDOW', 'A window tool is not a valid solid.', {'window': i})
        pr = window_prism(sol, center)
        if w.get('type') == 'side_button' and pr is None:
            raise WorkerError('CARVE_WINDOW', 'A side_button window tool must be a prism (two planar end faces, side faces along the axis).',
                              {'window': i})
        if w.get('sill') and pr is None:
            raise WorkerError('CARVE_WINDOW', 'A window with a sill must be a prism.', {'window': i})
        W.append({'i': i, 'spec': w, 'solid': sol, 'prism': pr})
    side_prisms = [pocket_region(w['prism'], w['spec'].get('sill')) for w in W if w['spec'].get('type') == 'side_button']
    # 1. G
    G, Gfit, Ginfo = build_G(Ss, Fs, Rs, prm, side_prisms, bbs)
    # 2. K2
    if Rs['click_recess']:
        K2, Kinfo = build_K2(Ss, Fs, Rs, prm, bbs)
    else:
        K2, Kinfo = None, {'click_recess': False, 'note': 'no plate-outline step face: the wall offset is applied everywhere (cavity = G)'}
    # 3. K3 sills
    K3, sills = K2, []
    for w in W:
        if not w['spec'].get('sill'):
            continue
        if K3 is None:
            raise WorkerError('CARVE_SETTINGS', 'A window sill needs the click recess (plate-outline step face); this shell has none.', {'window': w['i']})
        tool, geo = sill_tool(w['prism'], w['spec']['sill'])
        # gate on the closed-mesh volume: BRepGProp on the trimmed floor sheet of K is unreliable here (LH2: +3000 mm3 error, a real
        # sill cut read as a volume increase and was skipped)
        v0 = mesh_vol(K3, 0.02)[0]
        _, so = cut(K3, [tool], f'K3 sill window {w["i"]}')
        mv = [mesh_vol(x, 0.02)[0] for x in so]
        k = so[int(np.argmax(mv))]
        dv = v0 - max(mv)
        if not dv > 1e-3:
            raise WorkerError('CARVE_BOOLEAN', 'A window sill removed nothing from the floor prism K (silent no-op); check the sill drop / depth.',
                              {'window': w['i'], 'removed_mm3': float(dv), **geo})
        if not L.is_valid(k):
            raise WorkerError('CARVE_INVALID', 'K3 is not valid after the sill cut.', {'window': w['i']})
        K3 = k
        sills.append({'window': w['i'], 'applied': True, 'removed_mm3': float(dv), 'pieces': len(so), **geo})
    lat = [f for f in L.faces(K3) if is_extrusion(f)] if K3 is not None else []
    sheet_f = [f for f in L.faces(K3) if type(surface(f)).__name__ == 'Geom_BSplineSurface'] if K3 is not None else []
    # 4. cavity = G - K3
    vG = mesh_vol(G, 0.02)[0]
    if K3 is None:
        opA, so, cav = None, [G], G
        if not L.is_valid(cav):
            raise WorkerError('CARVE_INVALID', 'The cavity solid G is not valid.')
    else:
        opA, so = cut(G, [K3], 'cavity = G - K')
        mv = [mesh_vol(x, 0.02)[0] for x in so]
        cav = so[int(np.argmax(mv))]
        if not L.is_valid(cav) or not max(mv) < vG - 1e-3:
            raise WorkerError('CARVE_BOOLEAN', 'G - K did not remove the floor/step material (no-op or invalid).', {'pieces': len(so), 'G_mesh_mm3': vG,
                                                                                                               'cavity_mesh_mm3': mv})
    cav_pieces = len(so)
    lat, sheet_f = images(opA, lat), images(opA, sheet_f)
    #    stage 1: S - cavity
    # a result that is not one valid solid is retried with a growing Boolean fuzzy value (generic OCC tolerance ladder, never a silent accept)
    fuzzy_used = None
    for fz in (None, 1e-5, 1e-4, 1e-3):
        opB, so = cut(S, [cav], 'shell stage 1 = S - cavity' + ('' if fz is None else f' (fuzzy {fz})'), fuzzy=fz)
        vols = [L.volume(s) for s in so]
        V1 = so[int(np.argmax(vols))]
        if L.is_valid(V1) and max(vols) < vS - 1.0:
            fuzzy_used = fz
            break
    else:
        raise WorkerError('CARVE_BOOLEAN', 'S - cavity removed no volume or is invalid (silent no-op), also with Boolean fuzzy values up to 1e-3.',
                          {'volumes': vols, 'shell_volume_mm3': vS, 'valid': bool(L.is_valid(V1)), 'cavity_mesh_mm3': mesh_vol(cav, 0.02)[0], 'G_mesh_mm3': vG})
    P_(f' stage 1 fuzzy value used: {fuzzy_used}')
    # pieces the cavity isolates (e.g. a window frame ring) are kept until the window cut: the windows must remove them (v26 cut both in sequence)
    P1 = list(so)
    stage = [{'stage': 'S - cavity', 'pieces': len(so), 'isolated_mm3': [float(v) for k_, v in enumerate(vols) if k_ != int(np.argmax(vols))]}]
    stray = [float(v) for k_, v in enumerate(vols) if k_ != int(np.argmax(vols))]
    stray_shapes = [x for k_, x in enumerate(so) if k_ != int(np.argmax(vols))]
    lat, sheet_f = images(opB, lat), images(opB, sheet_f)
    skin = {'wall': images(opB, [F[i] for i in R['wall']]), 'floor': images(opB, [F[i] for i in R['floor']])}
    mv1, _ = mesh_vol(V1, prm['deflection_mm'])
    #    stage 2: windows
    shell, win_rep = V1, []
    if W:
        from OCP.BRep import BRep_Builder
        from OCP.TopoDS import TopoDS_Compound

        def pack(pieces):
            if len(pieces) == 1:
                return pieces[0]
            cb, cp = BRep_Builder(), TopoDS_Compound()
            cb.MakeCompound(cp)
            for p_ in pieces:
                cb.Add(cp, p_)
            return cp
        # c5_build5.py: cavity first, then all windows in one cut. Pieces the cavity isolated stay in the argument, so a window that only
        # removes such a piece (v26 window A frame ring) is not mistaken for a no-op and nothing is dropped unseen.
        opC, pieces = cut(pack(P1), [w['solid'] for w in W], 'shell stage 2 = - windows')
        lat, sheet_f = images(opC, lat), images(opC, sheet_f)
        skin = {k: images(opC, v) for k, v in skin.items()}
        vols = [L.volume(s) for s in pieces]
        shell = pieces[int(np.argmax(vols))]
        if not L.is_valid(shell):
            raise WorkerError('CARVE_INVALID', 'The shell is not valid after the window cut.')
        stray = [float(v) for k_, v in enumerate(vols) if k_ != int(np.argmax(vols))]
        stray_shapes = [x for k_, x in enumerate(pieces) if k_ != int(np.argmax(vols))]
        stage.append({'stage': '- windows', 'pieces': len(pieces), 'discarded_mm3': stray})
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
        for w in W:
            rem = 0.0
            for p_ in P1:
                cm = BRepAlgoAPI_Common(p_, w['solid'])
                rem += L.volume(cm.Shape()) if cm.IsDone() else float('nan')
            win_rep.append({'window': w['i'], 'type': w['spec'].get('type', 'other'), 'removed_mm3': float(rem),
                            'prism_axis': None if w['prism'] is None else np.round(w['prism']['axis'], 4).tolist()})
        bad = [x for x in win_rep if not x['removed_mm3'] > 1e-3]
        if bad:
            raise WorkerError('CARVE_BOOLEAN', 'A window tool removed no material (silent no-op).', {'windows': win_rep, 'stages': stage})
    lat, sheet_f = present(shell, lat), present(shell, sheet_f)
    # 5. step fillet
    fil = {'radius_mm': R_fillet, 'edges': 0}
    if not R['click_recess']:
        fil['note'] = 'no click recess'
    if R_fillet > 0 and R['click_recess']:
        from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
        from OCP.TopoDS import TopoDS
        es = []
        for e, fl in edge_faces(shell):
            if any(any(f.IsSame(a) for a in lat) for f in fl) and any(any(f.IsSame(b) for b in sheet_f) for f in fl):
                es.append(e)
        fil.update({'edges': len(es), 'edge_lengths_mm': [round(edge_length(e), 2) for e in es]})
        if es:
            v0 = L.volume(shell)
            mf = BRepFilletAPI_MakeFillet(shell)
            for e in es:
                mf.Add(R_fillet, TopoDS.Edge_s(e))
            mf.Build()
            if not mf.IsDone():
                raise WorkerError('CARVE_FILLET', 'The step fillet failed.', {'radius_mm': R_fillet, 'edges': len(es),
                                                                               'edge_lengths_mm': fil['edge_lengths_mm']})
            so = L.solids(mf.Shape())
            if len(so) != 1 or not L.is_valid(so[0]):
                raise WorkerError('CARVE_FILLET', 'The step fillet gave no single valid solid.', {'solids': len(so)})
            skin = {k: images(mf, v) for k, v in skin.items()}
            shell = so[0]
            fil['volume_change_mm3'] = float(L.volume(shell) - v0)
        else:
            fil['note'] = 'no edge between the K lateral face and the floor sheet in the shell'
    # outputs
    out = Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    step_mode = {}
    for nm, shp in (('hollow_shell.step', shell), ('cavity.step', cav)):
        step_mode[nm] = 'compact' if prm['compact_step'] else 'full'
        write_out_step(shp, out / nm, prm['compact_step'])
        back = L.solids(L.read_step(out / nm))
        if prm['compact_step'] and (len(back) != 1 or not L.is_valid(back[0])):
            write_out_step(shp, out / nm, False)        # compact file did not re-import as one valid solid: keep pcurves
            step_mode[nm] = 'full (compact re-import failed)'
    iso = []
    if stray_shapes:
        # pieces the cavity cut off the shell (e.g. side-button caps inside their slots, window frame rings): reported and written, never silently lost
        write_out_step(L.compound(stray_shapes), out / 'isolated_pieces.step', False)
        files_iso = {'isolated_pieces_step': 'isolated_pieces.step'}
        iso = [{'volume_mm3': round(float(v), 3), 'bbox': np.round(L.bbox(x, optimal=True), 2).tolist()} for v, x in zip(stray, stray_shapes)]
    else:
        files_iso = {}
    np.savez_compressed(out / 'cavity_fit.npz', poles=Gfit['P'], ku=Gfit['ku'], kv=Gfit['kv'])
    rt = L.solids(L.read_step(out / 'hollow_shell.step'))
    rt_valid = bool(rt) and all(L.is_valid(s) for s in rt)
    # the written file is what every downstream tool reads: a face the STEP reader rebuilds with a 2D gap is dropped by BRepMesh there (an
    # in-memory ShapeFix does not survive the file), so meshability is gated on the re-imported solid, never on the in-memory one
    from cadmcp_brain.studio import mouse_groove_fill_worker as GF
    rt_unmeshed = GF.unmeshed_faces(rt[0], 0.05, clean=True) if len(rt) == 1 else []
    # ---- checks
    Fsh = L.faces(shell)
    mvF, msh = mesh_vol(shell, prm['deflection_mm'])
    sk_idx = {k: {same_index(Fsh, f) for f in present(shell, v)} - {-1} for k, v in skin.items()}
    from cadmcp_brain.studio.mouse_wall_audit_worker import ray_thickness
    zcut = max(float(L.bbox(F[i])[5]) for i in R['bearing']) + prm['audit_band_mm']
    th = {}
    win_prisms = [w['prism'] for w in W if w['prism'] is not None]
    win_boxes = [L.bbox(w['solid']) for w in W if w['prism'] is None]
    for k in ('wall', 'floor'):
        if k == 'floor' and not R['click_recess']:
            th[k] = {'n': 0, 'note': 'no click recess'}
            continue
        sel = np.isin(msh['FID'], list(sk_idx[k]))
        n = int(prm['audit_samples'] * (0.75 if k == 'wall' else 0.25))
        pts, nr = area_samples(msh, sel, n, 1)
        m = pts[:, 2] > zcut
        for pr in win_prisms:
            m &= ~in_prism(pr, pts, prm['window_margin_mm'])
        for b in win_boxes:
            mg = prm['window_margin_mm']
            m &= ~np.all((pts >= b[:3] - mg) & (pts <= b[3:] + mg), axis=1)
        t = ray_thickness(msh['V'], msh['T'], pts[m], nr[m], 60.0)
        th[k] = thickness_stats(t, T if k == 'wall' else float(prm['floor_mm']))
    # skin deviation: points on the input skin (wall faces, away from windows) -> distance to the result
    sp_, fid_ = area_samples_fid(Smesh, np.isin(Smesh['FID'], R['wall']), 4000, 2)
    keep = np.ones(len(sp_), bool)
    for pr in win_prisms:
        keep &= ~in_prism(pr, sp_, prm['window_margin_mm'])
    sp_, fid_ = sp_[keep][:2000], fid_[keep][:2000]
    sp_ = np.array([project(surface_raw(F[k]), p)[0] for p, k in zip(sp_, fid_)])
    sd = mesh_distance(msh['V'], msh['T'], sp_)
    skin_dev = {'n': int(len(sd)), 'max': float(sd.max()), 'p99': float(np.percentile(sd, 99))}
    # cavity fit deviation vs the exact offsets
    from scipy.spatial import cKDTree
    nu_, nv_ = 961, 641
    Q = eval_tensor(Gfit['P'], Gfit['ku'], Gfit['kv'], nu_, nv_).reshape(-1, 3)
    tr = cKDTree(Q)
    rng = np.random.default_rng(3)
    tru = Gfit['true'][rng.choice(len(Gfit['true']), size=min(8000, len(Gfit['true'])), replace=False)]
    _, jq = tr.query(tru, workers=-1)
    from OCP.ShapeAnalysis import ShapeAnalysis_Surface
    from OCP.gp import gp_Pnt, gp_Pnt2d
    sas = ShapeAnalysis_Surface(Gfit['srf'])
    prj = np.empty_like(tru)
    for k_, (p, j) in enumerate(zip(tru, jq)):
        uv = sas.NextValueOfUV(gp_Pnt2d((j // nv_) / (nu_ - 1), (j % nv_) / (nv_ - 1)), gp_Pnt(*map(float, p)), 1e-7)
        prj[k_] = Gfit['srf'].Value(uv.X(), uv.Y()).Coord()
    dq = np.linalg.norm(prj - tru, axis=1)
    C = np.array(prm['ray_center'])
    thicker = np.linalg.norm(tru - C, axis=1) > np.linalg.norm(prj - C, axis=1)
    cav_dev = {'n': int(len(dq)), 'max': float(dq.max()), 'p95': float(np.percentile(dq, 95)), 'p99': float(np.percentile(dq, 99)),
               'max_thinner_side': float(dq[~thicker].max()) if (~thicker).any() else 0.0,
               'max_thicker_side': float(dq[thicker].max()) if thicker.any() else 0.0,
               'frac_over_0.02': float(np.mean(dq > 0.02)), 'note': 'distance from exact per-face wall offsets to the fitted cavity surface; '
               'thicker side = cavity inside the exact offset (inner envelope at concave creases)'}
    # seams in the slot band
    if R['click_recess']:
        fl_bb = np.array([L.bbox(F[i]) for i in R['floor']])
        x0, x1 = float(fl_bb[:, 0].min()), float(fl_bb[:, 3].max())
    else:
        x0, x1 = 1.0, 0.0       # no click x range: the slot-band seam check is not applicable
    seam, n_edges = [], 0
    for e, fls in edge_faces(shell):
        n_edges += 1
        q = edge_points(e)
        if not len(q):
            continue
        if np.all(np.abs(q[:, 1] - prm['mirror_y']) <= prm['slot_band_mm']) and np.all((q[:, 0] >= x0) & (q[:, 0] <= x1)):
            seam.append(np.round(np.r_[q.min(0), q.max(0)], 2).tolist())
    rep = {'solid_count': len(rt), 'valid': bool(L.is_valid(shell)), 'free_edges': free_edges(shell), 'faces': len(Fsh), 'edges_total': n_edges,
           'seam_edges_in_slot_band': len(seam), 'seam_edges': seam,
           'step_round_trip': {'solids': len(rt), 'valid': rt_valid, 'volume_delta_mm3': float(abs(L.volume(rt[0]) - L.volume(shell))) if rt else None,
                               'unmeshed_faces': rt_unmeshed},
           'wall_thickness': th['wall'], 'floor_thickness': th['floor'], 'cavity_deviation': cav_dev, 'outer_skin_deviation': skin_dev,
           'volume': {'input_brep_mm3': float(vS), 'input_mesh_mm3': mvS, 'shell_brep_mm3': float(L.volume(shell)), 'shell_mesh_mm3': mvF,
                      'removed_mesh_mm3': mvS - mvF, 'removed_by_cavity_mesh_mm3': mvS - mv1, 'removed_by_windows_and_fillet_mesh_mm3': mv1 - mvF,
                      'cavity_brep_mm3': float(L.volume(cav)), 'mass_g_abs': round(mvF * 1.04 / 1000.0, 3)},
           'windows': win_rep, 'sills': sills, 'stages': stage, 'stray_pieces_mm3': stray, 'cavity_pieces': cav_pieces, 'step_fillet': fil,
           'audit_z_min_mm': zcut, 'step_files': step_mode}
    # optional reference comparison
    files = {'hollow_shell_step': 'hollow_shell.step', 'cavity_step': 'cavity.step', 'cavity_fit_npz': 'cavity_fit.npz', **files_iso}
    rep['isolated_pieces'] = iso
    if req['inputs'].get('reference'):
        from cadmcp_brain.studio import mouse_parts_lib as PL
        parts, _ = PL.load_parts([req['inputs']['reference']])
        name = req['params'].get('reference_part')
        if name is None:
            if len(parts) != 1:
                raise WorkerError('CARVE_REFERENCE', 'The reference STEP holds several parts; name one with reference_part.', {'parts': sorted(parts)})
            name = next(iter(parts))
        PL.require(parts, [name], 'reference_part')
        ref = parts[name]
        mvR, mref = mesh_vol(ref, prm['deflection_mm'])
        n = int(prm['reference_samples'])
        pa, _ = area_samples(msh, np.ones(len(msh['T']), bool), n, 4)
        pb, _ = area_samples(mref, np.ones(len(mref['T']), bool), n, 5)
        da = mesh_distance(mref['V'], mref['T'], pa)
        db = mesh_distance(msh['V'], msh['T'], pb)
        dd = np.r_[da, db]
        rep['reference'] = {'part': name, 'mesh_volume_mm3': mvR, 'volume_delta_mm3': mvF - mvR, 'volume_delta_pct': 100.0 * (mvF - mvR) / mvR,
                            'deviation_max': float(dd.max()), 'deviation_p95': float(np.percentile(dd, 95)), 'deviation_p50': float(np.median(dd)),
                            'result_to_reference': {'max': float(da.max()), 'p95': float(np.percentile(da, 95))},
                            'reference_to_result': {'max': float(db.max()), 'p95': float(np.percentile(db, 95))},
                            'frac_over_0.05': float(np.mean(dd > 0.05))}
    # checks + verdict
    ck = {'one_solid': 'PASS' if len(rt) == 1 else 'FAIL',
          'valid_after_round_trip': 'PASS' if rt_valid and rep['valid'] else 'FAIL',
          'no_free_edges': 'PASS' if rep['free_edges'] == 0 else 'FAIL',
          'input_mesh_complete': 'PASS' if input_mesh_repair is None and not any(r['no_mesh'] for r in rows) else 'WARN',
          'output_tessellates_after_round_trip': 'PASS' if len(rt) == 1 and not rt_unmeshed else 'FAIL',
          'no_stray_pieces': 'PASS' if sum(stray) < 1.0 else 'WARN',
          'no_seam_in_slot_band': 'NA' if not R['click_recess'] else 'PASS' if not seam else 'WARN',
          'wall_p05_ge_T_minus_0.02': 'PASS' if th['wall'].get('p05', 0) >= T - 0.02 else 'WARN',
          'floor_p05_ge_T_minus_0.02': 'NA' if not R['click_recess'] else 'PASS' if th['floor'].get('p05', 0) >= float(prm['floor_mm']) - 0.02 else 'WARN',
          'cavity_deviation_p95_le_0.02': 'PASS' if cav_dev['p95'] <= 0.02 else 'WARN',
          'cavity_deviation_max_le_0.02': 'PASS' if cav_dev['max'] <= 0.02 else 'WARN',
          'outer_skin_unchanged_max_le_0.02': 'PASS' if skin_dev['max'] <= 0.02 else 'WARN',
          'step_fillet_applied': 'NA' if not R['click_recess'] else 'PASS' if R_fillet <= 0 or fil['edges'] > 0 else 'WARN'}
    rep['checks'] = ck
    rep['verdict'] = 'FAIL' if 'FAIL' in ck.values() else 'WARN' if 'WARN' in ck.values() else 'PASS'
    rep['roles'] = R
    rep['input_faces_without_mesh'] = [r['index'] for r in rows if r['no_mesh']]
    rep['input_mesh_repair'] = input_mesh_repair
    rep['role_hints'] = {k: hint[k] for k in ('used', 'ignored')}
    rep['click_recess'] = bool(R['click_recess'])
    rep['offset_source_roles'] = None if Ss is S else Rs
    rep['cavity_G'] = Ginfo
    rep['floor_K'] = Kinfo
    rep['face_table'] = [{'index': r['index'], 'area_mm2': round(r['area_mm2'], 2), 'mean_normal': np.round(r['mean_normal'], 3).tolist(),
                          'extrusion': r['extrusion']} for r in rows]
    used = {k: v for k, v in prm.items()}
    used['step_fillet_mm'] = R_fillet
    return {'report': L.clean(rep), 'files': files, 'settings_used': L.clean(used), 'worker_version': WORKER_VERSION,
            'seconds': round(time.time() - t_start, 1)}


def main_big_stack(argv, stack_mb: int = 256) -> int:
    """worker_main on a thread with a large stack. The OCC Boolean / BRepMesh recursion on big trimmed B-spline faces (the whole top skin
    of a mouse is one face) exceeds the 1 MB default thread stack of python.exe on Windows: the process then dies with 0xC00000FD before any
    JSON result (LH2 split shell, S - cavity stage). The stack size is generic process head-room, not a part-tuned value."""
    import threading
    res: dict[str, int] = {}

    def target():
        res['rc'] = int(worker_main(run, WorkerError, argv) or 0)
    for mb in (stack_mb, stack_mb // 2, stack_mb // 4, stack_mb // 8):       # the platform caps the thread stack; take the largest it accepts
        try:
            threading.stack_size(mb * 1024 * 1024)
            break
        except ValueError:
            continue
    th = threading.Thread(target=target, name='carve-worker')
    th.start()
    th.join()
    return res.get('rc', 1)


if __name__ == '__main__':
    raise SystemExit(main_big_stack(sys.argv))
