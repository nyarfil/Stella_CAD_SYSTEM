"""Main-click switch boards under a hollow top shell + board posts + click-plate actuator posts (brain_mouse_board_posts).
SUBPROCESS WORKER (server python: OCP, extra `geometry`).

Run as:  <server python> -I mouse_board_posts_worker.py request.json      (result = last stdout line, JSON)

Port of the owner-approved LH2 v39 process (work/internals/posts/scripts/build_v39s.py = boards + shell posts, build_v39a.py = actuator posts +
floor holes) to plain OCP. Every design number is a request parameter; the board datums come from the board geometry:
  * board (pcb) part: level in its own (park) frame, top face z = board top, thickness from its bbox, holes = CONCAVE vertical cylindrical faces
    (the largest diameter group, or those of board_hole_dia, or explicit board_holes [[x, y], ...] in the park frame); the measured hole diameter
    sets the post diameter (post_dia = hole - post_hole_clearance_mm unless post_dia is given);
  * switch part: topmost horizontal face = plunger top (centre of its box), the largest horizontal face below it = switch body top (footprint).
Stages (params.stage): 'place' = board pose only; 'posts' = + shell posts; 'all' = + actuator posts on the click plates + floor holes.

Placement (v37-v39): one board copied for every side (pure rotation R + translation); R = pitch about +Y, roll 0, pitch = atan(-slope) of a
plane fitted to the floor underside (vertical rays) over the switch-body footprint around each pivot, averaged over the sides (or pitch_deg).
The plunger top starts at the side's pivot and moves only along the board normal u: the shift per side makes the minimum switch-body-top ->
shell distance along u equal body_gap_mm; the smallest shift of all sides is applied to every side (keeps the mirror).
Board posts (v37 + v39): plain cylinder post_dia along u from the board bottom (tip flush) up into the floor, 4 stop ribs (rib_width wide,
rib_beyond_mm past the pin, at rib_angles_deg) from the board top up into the floor; every column is trimmed by a plane top_margin_mm below
the floor-top plane fitted over its footprint (plus the fit residual); M-screw pilot hole + lead-in chamfer from the post tip.
Actuator posts (v39a): rounded rectangle on the plunger axis, tip tip_gap_mm above the plunger top, fused into the plate, root fillet; floor
hole = post + hole_clear_mm per side, grown by the lateral motion of the post at mid floor height over travel_mm about the plate hinge.
Every Boolean is gated (done, non-empty, expected solid count, valid, volume bookkeeping).
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
from cadmcp_brain.studio import mouse_parts_lib as P
from cadmcp_brain.studio import cad_brep_lib as L

WORKER_VERSION = 'mouse_board_posts/2'
OVERLAP = 0.05          # boolean overlap of hole tools below the post tip (mm), as v39 (ZT - 0.05)
OVERLEN = 3.0           # over-length of post / rib columns before the floor-top trim (mm), as v39
CUT_BOX = (40.0, 30.0)  # trim half-space as a box: side, height (mm), as v39


# ------------------------------------------------------------------ OCP primitives
def _trsf(R, t):
    from OCP.gp import gp_Trsf
    tr = gp_Trsf()
    tr.SetValues(*map(float, R[0]), float(t[0]), *map(float, R[1]), float(t[1]), *map(float, R[2]), float(t[2]))
    return tr


def xform(shape, R, t):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    return BRepBuilderAPI_Transform(shape, _trsf(R, t), True).Shape()


def _ax2(o, z, x=None):
    from OCP.gp import gp_Ax2, gp_Pnt, gp_Dir
    if x is None:
        return gp_Ax2(gp_Pnt(*map(float, o)), gp_Dir(*map(float, z)))
    return gp_Ax2(gp_Pnt(*map(float, o)), gp_Dir(*map(float, z)), gp_Dir(*map(float, x)))


def cylinder(c, r, h):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    return BRepPrimAPI_MakeCylinder(_ax2(c, (0, 0, 1)), r, h).Shape()


def cone(c, r1, r2, h):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCone
    return BRepPrimAPI_MakeCone(_ax2(c, (0, 0, 1)), r1, r2, h).Shape()


def box_at(corner, z, x, dx, dy, dz):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    return BRepPrimAPI_MakeBox(_ax2(corner, z, x), dx, dy, dz).Shape()


def rbox(cx, cy, z0, w, h, r, height):
    """Rounded-rectangle prism w x h (corner r) centred at (cx, cy), from z0 up by height."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    from OCP.gp import gp_Pnt
    b = BRepPrimAPI_MakeBox(gp_Pnt(cx - w / 2, cy - h / 2, z0), gp_Pnt(cx + w / 2, cy + h / 2, z0 + height)).Shape()
    if r <= 0:
        return b
    f = BRepFilletAPI_MakeFillet(b)
    for e in L.explore(b, 'edge'):
        a, c = _edge_ends(e)
        if abs(a[2] - c[2]) > height * 0.5:
            f.Add(r, e)
    f.Build()
    if not f.IsDone():
        raise WorkerError('BOARD_POSTS_PRIMITIVE', 'Rounded-rectangle fillet failed.', {'w': w, 'h': h, 'r': r})
    return f.Shape()


def plane_box(o, n, side=CUT_BOX[0], height=CUT_BOX[1]):
    """Box above the plane (origin o, normal n): side x side, height along n (the v39 trim cutter)."""
    n = np.asarray(n, float) / np.linalg.norm(n)
    ref = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    x = ref - (ref @ n) * n
    x /= np.linalg.norm(x)
    y = np.cross(n, x)
    corner = np.asarray(o, float) - x * side / 2 - y * side / 2
    return box_at(corner, n, x, side, side, height)


def _edge_ends(e):
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    c = BRepAdaptor_Curve(e)
    return np.array(c.Value(c.FirstParameter()).Coord()), np.array(c.Value(c.LastParameter()).Coord())


def edge_mid(e):
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    c = BRepAdaptor_Curve(e)
    return np.array(c.Value(0.5 * (c.FirstParameter() + c.LastParameter())).Coord())


def unify(shape):
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    u = ShapeUpgrade_UnifySameDomain(shape, True, True, True)
    u.Build()
    return u.Shape()


def boolean(kind, a, tools, what, expect_solids=None, clean=False):
    """Gated OCC Boolean (fuse / cut / common) of a (one shape or a list) with tools. Returns (shape, record)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse, BRepAlgoAPI_Cut, BRepAlgoAPI_Common
    from OCP.TopTools import TopTools_ListOfShape
    op = {'fuse': BRepAlgoAPI_Fuse, 'cut': BRepAlgoAPI_Cut, 'common': BRepAlgoAPI_Common}[kind]()
    args, tl = TopTools_ListOfShape(), TopTools_ListOfShape()
    for s in (a if isinstance(a, list) else [a]):
        args.Append(s)
    for s in tools:
        tl.Append(s)
    op.SetArguments(args)
    op.SetTools(tl)
    op.Build()
    if not op.IsDone() or op.Shape().IsNull():
        raise WorkerError('BOARD_POSTS_BOOLEAN', f'Boolean {kind} failed: {what}.', {'step': what})
    out = unify(op.Shape()) if clean else op.Shape()
    ss = L.solids(out)
    rec = {'step': what, 'op': kind, 'solids': len(ss), 'brep_volume_mm3': round(P.volume(out), 4) if ss else 0.0}
    if kind != 'common' and not ss:
        raise WorkerError('BOARD_POSTS_BOOLEAN', f'Boolean {kind} gave no solid: {what}.', rec)
    if expect_solids is not None and len(ss) != expect_solids:
        raise WorkerError('BOARD_POSTS_BOOLEAN', f'Boolean {kind} gave {len(ss)} solids, expected {expect_solids}: {what}.', rec)
    return out, rec


def one(shape, what):
    ss = L.solids(shape)
    if len(ss) != 1:
        raise WorkerError('BOARD_POSTS_SOLIDS', f'{what}: expected one solid, got {len(ss)}.', {'step': what})
    return ss[0]


def largest(shape):
    return max(L.solids(shape), key=P.volume)


# ------------------------------------------------------------------ ray queries
_RAY: dict[int, tuple[Any, Any]] = {}


def hits(shape, p, d):
    """Forward ray hits [(distance, point)] sorted. IntCurvesFace_ShapeIntersector loaded once per shape (same hits as the BRepIntCurveSurface
    rays of v39, about 100x faster on the scanned B-spline shell)."""
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    from OCP.gp import gp_Lin, gp_Pnt, gp_Dir
    k = id(shape)
    if k not in _RAY:
        si = IntCurvesFace_ShapeIntersector()
        si.Load(shape, 1e-7)
        _RAY[k] = (shape, si)
    si = _RAY[k][1]
    si.Perform(gp_Lin(gp_Pnt(*map(float, p)), gp_Dir(*map(float, d))), 1e-6, 1e9)
    out = [(float(si.WParameter(i)), np.array(si.Pnt(i).Coord())) for i in range(1, si.NbPnt() + 1)]
    out.sort(key=lambda h: h[0])
    ded = []
    for h in out:                                      # a hit on a shared edge is reported once per face
        if not ded or h[0] - ded[-1][0] > 1e-7:
            ded.append(h)
    return ded


def first_hit(shape, p, d, what):
    h = hits(shape, p, d)
    if not h:
        raise WorkerError('BOARD_POSTS_NO_FLOOR', f'No shell surface found along the ray: {what}.', {'from': np.round(p, 3).tolist(), 'dir': np.round(d, 4).tolist()})
    return h[0][0]


def rot(axis, ang):
    a = np.asarray(axis, float) / np.linalg.norm(axis)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * K @ K


def plane_fit(pts):
    """z = c0 + c1 x + c2 y least squares -> (coeffs, max abs residual)."""
    pts = np.asarray(pts, float)
    A = np.c_[np.ones(len(pts)), pts[:, 0], pts[:, 1]]
    cf = np.linalg.lstsq(A, pts[:, 2], rcond=None)[0]
    return cf, float(np.abs(A @ cf - pts[:, 2]).max())


# ------------------------------------------------------------------ board datums from geometry
def horizontal_faces(shape, up_only=True):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    out = []
    for f in L.faces(shape):
        a = BRepAdaptor_Surface(f)
        if a.GetType() != GeomAbs_Plane:
            continue
        n = L.face_normal_at(f, a.Plane().Location().Coord())
        if not np.all(np.isfinite(n)) or abs(n[2]) < 0.9999 or (up_only and n[2] < 0):
            continue
        out.append({'z': float(a.Plane().Location().Z()), 'bbox': L.bbox(f), 'area': L.area(f)})
    return out


def board_datums(pcb, switch, prm) -> dict[str, Any]:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.TopAbs import TopAbs_REVERSED
    pb = L.bbox(pcb)
    top_faces = horizontal_faces(pcb)
    if not top_faces:
        raise WorkerError('BOARD_POSTS_BOARD', 'The board part has no horizontal top face: it must lie level in its own frame (normal +Z).')
    btop = max(f['z'] for f in top_faces)
    thick = float(btop - pb[2])
    holes = prm.get('board_holes')
    cands = []                                                        # concave vertical cylinders: (radius, x, y)
    for f in L.faces(pcb):
        a = BRepAdaptor_Surface(f)
        if a.GetType() != GeomAbs_Cylinder:
            continue
        c = a.Cylinder()
        if abs(abs(c.Axis().Direction().Z()) - 1) > 1e-6 or c.Radius() < 0.25:
            continue
        ax = np.array([c.Location().X(), c.Location().Y()])
        try:
            from OCP.BRepTools import BRepTools
            u0, u1, v0, v1 = BRepTools.UVBounds_s(f)
            uu, vv = (u0 + u1) / 2, (v0 + v1) / 2
            q = np.array(a.Value(uu, vv).Coord())
            n = np.asarray(L.face_normal_uv(f, uu, vv), float)
            concave = bool(np.dot(n[:2], ax - q[:2]) > 0)                                    # outward normal of the solid points to the axis
        except Exception:  # noqa: BLE001
            concave = f.Orientation() == TopAbs_REVERSED
        if concave:
            cands.append((float(c.Radius()), round(c.Location().X(), 4), round(c.Location().Y(), 4)))
    if prm.get('board_hole_dia') is not None:
        r_want = prm['board_hole_dia'] / 2
    elif cands:
        r_want = max(r for r, _x, _y in cands)                        # mounting holes = the largest concave vertical cylinders
    else:
        r_want = None
    found = []
    for r, x_, y_ in cands:
        if r_want is not None and abs(r - r_want) <= 0.02 * r_want and not any(math.hypot(x_ - q[0], y_ - q[1]) < 0.01 for q in found):
            found.append((x_, y_))
    found.sort(key=lambda q: -q[0])                                   # front (larger x in the park frame) first, as v39
    hole_dia = None
    if holes is None:
        if not found:
            raise WorkerError('BOARD_POSTS_HOLES', 'No concave vertical hole in the board part; give board_holes and board_hole_dia.',
                              {'board_hole_dia': prm.get('board_hole_dia')})
        holes = found
        hole_dia = 2.0 * float(np.mean([r for r, _x, _y in cands if abs(r - r_want) <= 0.02 * r_want]))
    elif prm.get('board_hole_dia') is not None:
        hole_dia = float(prm['board_hole_dia'])
    elif r_want is not None:
        hole_dia = 2.0 * r_want
    if hole_dia is None:
        raise WorkerError('BOARD_POSTS_HOLES', 'board_holes given but the hole diameter is unknown: give board_hole_dia (or post_dia).', {})
    sw = horizontal_faces(switch)
    if len(sw) < 2:
        raise WorkerError('BOARD_POSTS_SWITCH', 'The switch part needs a plunger top face and a body top face (horizontal, facing +Z).')
    sw.sort(key=lambda f: -f['z'])
    pl = sw[0]
    below = [f for f in sw if f['z'] < pl['z'] - 0.05 and f['z'] > btop + 0.05]
    if not below:
        raise WorkerError('BOARD_POSTS_SWITCH', 'No switch body top face between the board top and the plunger top.')
    body = max(below, key=lambda f: f['area'])
    b, q = pl['bbox'], body['bbox']
    return {'board_top_z': btop, 'board_thickness': thick, 'hole_dia_mm': hole_dia, 'holes': [list(map(float, h)) for h in holes], 'holes_found': found,
            'plunger_top': [float((b[0] + b[3]) / 2), float((b[1] + b[4]) / 2), float(pl['z'])], 'plunger_rect': [float(b[0]), float(b[3]), float(b[1]), float(b[4])],
            'body_top_z': float(body['z']), 'body_rect': [float(q[0]), float(q[3]), float(q[1]), float(q[4])]}


# ------------------------------------------------------------------ derived sides (no `sides` argument): pivots from in-place switch seeds, hinges from the plates
def vertices(shape) -> np.ndarray:
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_VERTEX
    from OCP.BRep import BRep_Tool
    from OCP.TopoDS import TopoDS
    e, v = TopExp_Explorer(shape, TopAbs_VERTEX), []
    while e.More():
        v.append(BRep_Tool.Pnt_s(TopoDS.Vertex_s(e.Current())).Coord())
        e.Next()
    return np.unique(np.round(np.array(v, float), 7), axis=0) if v else np.zeros((0, 3))


def inertia_frame(shape):
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, g)
    M = g.MatrixOfInertia()
    w, V = np.linalg.eigh(np.array([[M.Value(i, j) for j in (1, 2, 3)] for i in (1, 2, 3)]))
    if np.linalg.det(V) < 0:
        V[:, 2] = -V[:, 2]
    return np.array(g.CentreOfMass().Coord()), w, V, float(g.Mass())


def rigid_match(master, seed, what, tol):
    """Rigid transform (R, t) with seed = R master + t, from the inertia frames (centre of mass + principal axes; the four proper sign choices and
    the pure translation are tried) and checked on the B-rep vertices (max nearest-vertex distance <= tol). The seed must be a rigid copy."""
    from scipy.spatial import cKDTree
    cm, wm, Vm, mm = inertia_frame(master)
    cs, ws, Vs, ms = inertia_frame(seed)
    if abs(ms - mm) > 1e-3 * mm or np.abs(ws - wm).max() > 1e-3 * np.abs(wm).max():
        raise WorkerError('BOARD_POSTS_SEED', f'{what} is not a rigid copy of switch_part (volume / inertia differ).', {'seed': what, 'volume': [mm, ms]})
    vm, vs = vertices(master), vertices(seed)
    tree = cKDTree(vs)
    cands = [np.eye(3)] + [Vs @ np.diag(sg) @ Vm.T for sg in ((1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1))]
    best = None
    for R in cands:
        t = cs - R @ cm
        d = float(tree.query(vm @ R.T + t)[0].max()) if len(vm) else 0.0
        if best is None or d < best[2]:
            best = (R, t, d)
    if best[2] > tol:
        raise WorkerError('BOARD_POSTS_SEED', f'{what} does not match switch_part by a rigid motion (vertex residual {best[2]:.4f} mm).', {'seed': what, 'tol_mm': tol})
    return best


def plate_thickness(plate):
    b = L.bbox(plate)
    t = []
    for fx in np.linspace(0.2, 0.8, 5):
        for fy in np.linspace(0.2, 0.8, 5):
            h = hits(plate, (b[0] + fx * (b[3] - b[0]), b[1] + fy * (b[4] - b[1]), b[2] - 1.0), (0, 0, 1))
            if len(h) >= 2:
                t.append(h[1][0] - h[0][0])
    if not t:
        raise WorkerError('BOARD_POSTS_HINGE', 'The click plate thickness could not be measured (no vertical ray crosses it twice).', {})
    return float(np.median(t))


def plate_hinge(plate, plane_y, prm, what):
    """Hinge = the plate root line on the underside of its rear edge (front = +x): the rear corner vertices of the plate B-rep (vertices within
    hinge_band_frac x plate length of the rearmost vertex) are clustered at the end nearest the mirror plane (inner) and the farthest end (outer,
    cluster width hinge_cluster_frac x plate width); each end point is the mean of its underside vertices (below the lowest one + half the
    plate thickness). The inner end is projected onto the mirror plane when it lies within the cluster width of it (the two plates share one
    root line there). This is the LH2 v35-v39 definition ("two points from the plate's rear vertices", build_v39a.py)."""
    V = vertices(plate)
    if len(V) < 2:
        raise WorkerError('BOARD_POSTS_HINGE', f'{what}: the plate has no B-rep vertices to find its rear edge.', {})
    b = L.bbox(plate)
    length, width = b[3] - b[0], b[4] - b[1]
    rear = V[V[:, 0] <= V[:, 0].min() + prm['hinge_band_frac'] * length]
    d = np.abs(rear[:, 1] - plane_y)
    tol = prm['hinge_cluster_frac'] * width
    th = plate_thickness(plate)
    ends = []
    for sel in (d <= d.min() + tol, d >= d.max() - tol):
        c = rear[sel]
        c = c[c[:, 2] <= c[:, 2].min() + 0.5 * th]
        ends.append(c.mean(axis=0))
    inner, outer = ends
    if abs(outer[1] - inner[1]) < 0.5 * width:
        raise WorkerError('BOARD_POSTS_HINGE', f'{what}: the rear edge spans less than half the plate width; the hinge is not derivable, give sides.',
                          {'rear_vertices': len(rear), 'span_mm': float(abs(outer[1] - inner[1])), 'width_mm': float(width)})
    projected = bool(abs(inner[1] - plane_y) <= tol)
    if projected:
        inner = np.array([inner[0], plane_y, inner[2]])
    return [inner, outer], {'rear_vertices': int(len(rear)), 'thickness_mm': round(th, 4), 'inner_projected_to_plane': projected,
                            'raw': [np.round(e, 4).tolist() for e in ends]}


def _mirror(p, plane_y):
    return np.array([p[0], 2 * plane_y - p[1], p[2]])


def derive_sides(shell, parts, D, plane_y, prm):
    """sides from geometry: pivot = plunger top of an in-place copy of switch_part (seed) per side + the owner's seed_shift_mm [front, inward];
    plate = the click plate above the seed; hinge = plate_hinge. Two sides on both sides of the mirror plane are symmetrised (mean of one side
    and the mirror image of the other). Returns (sides, info, z rules); pivot z is finished by pivot_z_by_plunger_gap in run()."""
    dv = prm['derive']
    master = one(parts[prm['switch_part']], prm['switch_part'])
    P0 = np.array(D['plunger_top'])
    seeds = []
    for nm in dv['seed_switch_parts']:
        R, t, res = rigid_match(master, one(parts[nm], nm), nm, prm['seed_match_tol_mm'])
        top = R @ P0 + t
        tilt = math.degrees(math.acos(max(-1.0, min(1.0, float(R[2, 2])))))
        seeds.append({'part': nm, 'plunger_top': top, 'tilt_deg': tilt, 'yaw_deg': math.degrees(math.atan2(R[1, 0], R[0, 0])), 'match_residual_mm': res})
    plates = dv.get('plate_parts') or []
    pair = list(range(len(seeds)))
    if plates:
        pair, used = [], set()
        for s in seeds:
            x, y, _z = s['plunger_top']
            over = [k for k, pn in enumerate(plates) if k not in used and hits(one(parts[pn], pn), (x, y, L.bbox(parts[pn])[2] - 1.0), (0, 0, 1))]
            if len(over) != 1:
                raise WorkerError('BOARD_POSTS_SEED', f'Seed {s["part"]} is not under exactly one click plate (plan position).',
                                  {'seed': s['part'], 'plunger_xy': np.round(s['plunger_top'][:2], 3).tolist(), 'plates_over': [plates[k] for k in over]})
            pair.append(over[0])
            used.add(over[0])
    names = dv.get('side_names') or ([plates[k] for k in pair] if plates else [s['part'] for s in seeds])
    fr, inw = dv['seed_shift_mm']
    for s in seeds:
        p = np.array(s['plunger_top'], float)
        side = p[1] - plane_y
        if inw and abs(side) < 1e-6:
            raise WorkerError('BOARD_POSTS_SEED', 'A seed on the mirror plane has no inward direction for seed_shift_mm.', {'seed': s['part']})
        s['pivot'] = p + np.array([fr, -math.copysign(inw, side), 0.0])
    rule = dv['pivot_z_rule']
    for s in seeds:
        s['z_rule'] = ('plunger_gap' if s['tilt_deg'] < 0.05 else 'seed') if rule == 'auto' else rule
    hinges, hinfo = [], []
    for k in pair:
        if plates:
            h, hi = plate_hinge(one(parts[plates[k]], plates[k]), plane_y, prm, plates[k])
            hinges.append(h)
            hinfo.append(hi)
    sym = False
    if dv['symmetrise'] and len(seeds) == 2 and (seeds[0]['pivot'][1] - plane_y) * (seeds[1]['pivot'][1] - plane_y) < 0:
        sym = True
        a, b = seeds[0]['pivot'], _mirror(seeds[1]['pivot'], plane_y)
        m = (a + b) / 2
        seeds[0]['pivot_unsym'], seeds[1]['pivot_unsym'] = a.copy(), seeds[1]['pivot'].copy()
        seeds[0]['pivot'], seeds[1]['pivot'] = m, _mirror(m, plane_y)
        if hinges:
            hm = [(hinges[0][i] + _mirror(hinges[1][i], plane_y)) / 2 for i in (0, 1)]
            hinfo[0]['unsymmetrised'] = [np.round(p, 4).tolist() for p in hinges[0]]
            hinfo[1]['unsymmetrised'] = [np.round(p, 4).tolist() for p in hinges[1]]
            hinges = [hm, [_mirror(p, plane_y) for p in hm]]
    sides = []
    for i, s in enumerate(seeds):
        q = {'name': names[i], 'pivot': [float(x) for x in s['pivot']]}
        if plates:
            q['plate_part'] = plates[pair[i]]
            q['hinge'] = [[float(x) for x in p] for p in hinges[i]]
        sides.append(q)
    info = {'seeds': [{'part': s['part'], 'side': names[i], 'seed_plunger_top': np.round(s['plunger_top'], 4).tolist(), 'tilt_deg': round(s['tilt_deg'], 4),
                       'yaw_deg': round(s['yaw_deg'], 4), 'match_residual_mm': round(s['match_residual_mm'], 6), 'z_rule': s['z_rule']}
                      for i, s in enumerate(seeds)],
            'seed_shift_mm': [fr, inw], 'symmetrised': sym, 'hinges': {names[i]: hinfo[i] for i in range(len(hinfo))},
            'definition': 'pivot = in-place seed plunger top + seed_shift_mm (front, inward), z by z_rule; hinge = plate rear-edge underside corners'}
    return sides, info, [s['z_rule'] for s in seeds]


def pivot_z_by_plunger_gap(shell, D, sides, rules, pitch, prm):
    """v37 rule for level seeds: keep the pivot XY, move it vertically until the minimum plunger-top -> floor-underside distance along the board
    normal (5 x 7 rays over the plunger top) is plunger_gap_mm; the lowest z of those sides is used for all of them (mirror kept)."""
    R = pitch_rot(pitch)
    u = R[:, 2]
    P0 = np.array(D['plunger_top'])
    px0, px1, py0, py1 = D['plunger_rect']
    grid = [(x, y) for x in np.linspace(px0, px1, 5) for y in np.linspace(py0, py1, 7)]
    zs = {}
    for s, r in zip(sides, rules):
        if r != 'plunger_gap':
            continue
        T = np.array(s['pivot'], float)
        for _ in range(prm['max_iter'] + 8):
            t = T - R @ P0
            g = min(first_hit(shell, R @ np.array([x, y, P0[2]]) + t, u, f'{s["name"]} plunger top -> floor') for x, y in grid)
            if abs(g - prm['plunger_gap_mm']) < 2e-4:
                break
            T[2] += (g - prm['plunger_gap_mm']) / R[2, 2]
        else:
            raise WorkerError('BOARD_POSTS_GAP', 'The vertical plunger-gap solve did not converge.', {'side': s['name']})
        zs[s['name']] = float(T[2])
    if zs:
        zc = min(zs.values())
        for s, r in zip(sides, rules):
            if r == 'plunger_gap':
                s['pivot'][2] = zc
    return zs


# ------------------------------------------------------------------ stages
def pitch_fit(shell, D, sides, prm):
    """Pitch about +Y: atan(-slope) of planes fitted to the floor underside (vertical rays) over the switch-body footprint around each pivot,
    averaged over the sides; or pitch_deg. -> (pitch rad, fits)."""
    P0 = np.array(D['plunger_top'])
    bx0, bx1, by0, by1 = D['body_rect']
    bc = np.array([(bx0 + bx1) / 2, (by0 + by1) / 2])
    hx, hy = (bx1 - bx0) / 2, (by1 - by0) / 2
    nx, ny = prm['pitch_grid']
    fits = {}
    if prm.get('pitch_deg') is None:
        slopes = []
        for s in sides:
            pv = np.array(s['pivot'])
            c = pv[:2] + bc - P0[:2]
            z0 = pv[2] - prm['floor_ray_below_pivot_mm']
            pts = []
            for dx in np.linspace(-hx, hx, nx):
                for dy in np.linspace(-hy, hy, ny):
                    x, y = c[0] + dx, c[1] + dy
                    pts.append((x, y, z0 + first_hit(shell, (x, y, z0), (0, 0, 1), f'{s["name"]} floor underside')))
            cf, res = plane_fit(pts)
            slopes.append(cf[1])
            fits[s['name']] = {'slope_x': float(cf[1]), 'slope_y': float(cf[2]), 'residual_mm': res, 'samples': len(pts)}
        pitch = math.atan(-float(np.mean(slopes)))
    else:
        pitch = math.radians(prm['pitch_deg'])
    return pitch, fits


def pitch_rot(pitch):
    return np.array([[math.cos(pitch), 0, math.sin(pitch)], [0, 1, 0], [-math.sin(pitch), 0, math.cos(pitch)]])


def place(shell, D, sides, prm, pitch=None, fits=None):
    if pitch is None:
        pitch, fits = pitch_fit(shell, D, sides, prm)
    P0 = np.array(D['plunger_top'])
    bx0, bx1, by0, by1 = D['body_rect']
    R = pitch_rot(pitch)
    u = R[:, 2]
    px0, px1, py0, py1 = D['plunger_rect']
    m, ins = prm['plunger_exclusion_mm'], prm['body_grid_inset_mm']
    gx, gy = prm['body_grid']
    body_pts = [(x, y) for x in np.linspace(bx0 + ins, bx1 - ins, gx) for y in np.linspace(by0 + ins, by1 - ins, gy)
                if not (px0 - m < x < px1 + m and py0 - m < y < py1 + m)]

    def body_gap(T):
        t = T - R @ P0
        g = [first_hit(shell, R @ np.array([x, y, D['body_top_z']]) + t, u, 'switch body top -> shell') for x, y in body_pts]
        k = int(np.argmin(g))
        return float(g[k]), body_pts[k]

    shifts = {}
    for s in sides:
        T0, d = np.array(s['pivot'], float), 0.0
        for _ in range(prm['max_iter']):
            g, _p = body_gap(T0 + u * d)
            if abs(g - prm['body_gap_mm']) < 2e-4:
                break
            d += g - prm['body_gap_mm']
        else:
            raise WorkerError('BOARD_POSTS_GAP', 'The normal shift for the body gap did not converge.', {'side': s['name']})
        shifts[s['name']] = d
    dn = min(shifts.values())
    out = {}
    for s in sides:
        T = np.array(s['pivot'], float) + u * dn
        t = T - R @ P0
        pg = []
        for x in np.linspace(px0, px1, 5):
            for y in np.linspace(py0, py1, 7):
                q = R @ np.array([x, y, P0[2]]) + t
                pg.append(first_hit(shell, q - u * 3, u, 'plunger top -> shell') - 3)
        g, gp = body_gap(T)
        out[s['name']] = {'R': R, 't': t, 'T': T, 'u': u, 'plunger_top': T.tolist(), 'normal_shift_mm': dn, 'body_gap_mm': g,
                          'body_gap_nearest_local_xy': list(gp), 'plunger_gap_min_mm': float(min(pg))}
    return pitch, fits, shifts, dn, out


def columns(shell, W, u, pts, z0, cx, cy, prm, what):
    """Rays along u from local points at height z0: -> (max floor-underside distance, min, max, trim box in the local frame)."""
    fl = []
    for px, py in pts:
        h = hits(shell, W((px, py, z0)), u)
        if len(h) < 2:
            raise WorkerError('BOARD_POSTS_NO_FLOOR', f'No floor (underside + top) above {what}.', {'local': [px, py, z0]})
        fl.append((h[0][0], h[1][0]))
    a = [f[0] for f in fl]
    cf, res = plane_fit([(px, py, z0 + f[1]) for (px, py), f in zip(pts, fl)])
    n = np.array([-cf[1], -cf[2], 1.0])
    n /= np.linalg.norm(n)
    mg = prm['top_margin_mm']
    o = np.array([cx, cy, cf[0] + cf[1] * cx + cf[2] * cy]) - n * mg - np.array([0, 0, mg + res])
    return max(a), min(a), max(a), plane_box(o, n), res


def build_posts(shell, D, placed, prm):
    pr = prm['post_dia'] / 2
    fin_r = pr + prm['rib_beyond_mm']
    bt, th = D['board_top_z'], D['board_thickness']
    zt = bt - th
    tools, holes, info, records = [], [], {}, []
    for name, pl in placed.items():
        R, t, u = pl['R'], pl['t'], pl['u']
        W = lambda p, R=R, t=t: R @ np.asarray(p, float) + t
        bosses = []
        for k, (hx, hy) in enumerate(D['holes']):
            ring = [(hx, hy)] + [(hx + pr * math.cos(a), hy + pr * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 12, endpoint=False)]
            mu, umin, umax, cut, res = columns(shell, W, u, ring, bt, hx, hy, prm, f'{name} post {k}')
            col = cylinder((hx, hy, zt), pr, mu + prm['post_embed_mm'] + OVERLEN + th)
            col, rec = boolean('cut', col, [cut], f'{name} post {k} trim', expect_solids=1)
            loc = [col]
            fins = []
            for ang in prm['rib_angles_deg']:
                a = math.radians(ang)
                c_, s_ = math.cos(a), math.sin(a)
                w = prm['rib_width'] / 2
                corners = [(hx + rr * c_ - ww * s_, hy + rr * s_ + ww * c_) for rr in (pr, fin_r) for ww in (-w, w)]
                mf, fmin, fmax, cutf, _r = columns(shell, W, u, corners + [(hx + fin_r * c_, hy + fin_r * s_)], bt, hx, hy, prm, f'{name} rib {k}/{ang}')
                lf = mf + prm['post_embed_mm'] + OVERLEN
                r0 = pr - prm['rib_overlap_mm']
                ln = fin_r - r0
                xd, yd = np.array([c_, s_, 0.0]), np.array([-s_, c_, 0.0])
                corner = np.array([hx, hy, bt]) + xd * r0 - yd * w
                fin = box_at(corner, (0, 0, 1), xd, ln, prm['rib_width'], lf)
                fin, _ = boolean('cut', fin, [cutf], f'{name} rib {k}/{ang} trim', expect_solids=1)
                loc.append(fin)
                fins.append({'angle_deg': ang, 'len_mm': round(lf, 3)})
            for s in loc:
                tools.append(xform(s, R, t))
            hole = cylinder((hx, hy, zt - OVERLAP), prm['pilot_dia'] / 2, prm['pilot_depth_mm'] + OVERLAP)
            ch = cone((hx, hy, zt - OVERLAP), prm['pilot_dia'] / 2 + prm['chamfer_mm'] + OVERLAP, prm['pilot_dia'] / 2, prm['chamfer_mm'] + OVERLAP)
            holes += [xform(hole, R, t), xform(ch, R, t)]
            bosses.append({'hole_local_xy': [hx, hy], 'axis_pt': np.round(W((hx, hy, bt)), 3).tolist(), 'tip_pt': np.round(W((hx, hy, zt)), 3).tolist(),
                           'height_board_top_to_floor_underside': [round(umin, 3), round(umax, 3)],
                           'post_len_from_tip': round(mu + prm['post_embed_mm'] + OVERLEN + th, 3), 'floor_top_fit_residual_mm': round(res, 4),
                           'ribs': fins, 'material_above_hole_to_floor_underside': round(umin + th - prm['pilot_depth_mm'], 3)})
        info[name] = {'bosses': bosses}
    posts, rec = boolean('fuse', tools[0], tools[1:], 'posts + ribs union', expect_solids=len(placed) * len(D['holes']), clean=True)
    records.append(rec)
    v_posts = bvol(posts)
    com, rec = boolean('common', shell, [posts], 'shell / posts overlap')
    records.append(rec)
    v_ov = bvol(com)
    fused, rec = boolean('fuse', shell, [posts], 'shell + posts', expect_solids=1)
    records.append(rec)
    book = {'posts_tool_mm3': v_posts, 'posts_in_shell_overlap_mm3': v_ov}
    book['posts_in_result_mm3'] = bvol(boolean('common', fused, [posts], 'posts kept in the result')[0])
    book['mesh_delta_fuse_mm3'] = mvol(fused, prm) - mvol(shell, prm)
    if abs(book['posts_in_result_mm3'] - v_posts) > 0.005 * v_posts + 0.05 or abs(book['mesh_delta_fuse_mm3'] - (v_posts - v_ov)) > 0.02 * v_posts + 1.0:
        raise WorkerError('BOARD_POSTS_BOOKKEEPING', 'Shell + posts: the posts are not all in the result or the added volume is not posts - overlap.', book)
    hc = L.compound(holes)
    book['hole_material_mm3'] = bvol(boolean('common', fused, [hc], 'pilot hole material')[0])
    holed, rec = boolean('cut', fused, holes, 'pilot holes + chamfers')
    records.append(rec)
    out = largest(holed)
    book['hole_material_left_mm3'] = bvol(boolean('common', out, [hc], 'pilot holes left')[0])
    book['mesh_delta_holes_mm3'] = mvol(out, prm) - mvol(fused, prm)
    if not book['hole_material_mm3'] > 1e-3 or book['hole_material_left_mm3'] > 1e-3 or             abs(book['mesh_delta_holes_mm3'] + book['hole_material_mm3']) > 0.05 * book['hole_material_mm3'] + 0.5:
        raise WorkerError('BOARD_POSTS_BOOKKEEPING', 'The pilot holes did not remove their material (silent no-op cut).', book)
    book['solids_after_holes'] = len(L.solids(holed))
    return out, posts, info, records, book


def bvol(shape) -> float:
    """Exact B-rep volume (plain Gauss integration). Only for small solids: on the large trimmed B-spline faces of a scanned shell it is off
    by several % (v26 shell: 13350.6 B-rep vs 12610.7 closed mesh), so big solids are bookkept with mvol differences."""
    return float(P.volume(shape)) if L.solids(shape) else 0.0


def mvol(shape, prm) -> float:
    V, T = P.mesh(shape, prm['mesh_deflection_mm'])
    return abs(P.mesh_volume(V, T))


rec_vol = bvol


def build_actuators(shell, plates, D, placed, sides, prm):
    PW, PH, CR, FIL = prm['act_w'], prm['act_h'], prm['act_corner_r'], prm['act_root_fillet']
    PRE, HCLR = prm['tip_gap_mm'], prm['hole_clear_mm']
    P0 = np.array(D['plunger_top'])
    holes, info, out_plates, out_posts, records = [], {}, {}, {}, []
    for s in sides:
        name, plate = s['name'], plates[s['name']]
        pl = placed[name]
        R, u = pl['R'], pl['u']
        Pw = R @ P0 + pl['t']
        fl = hits(shell, Pw - u * 3, u)
        pp = hits(plate, Pw, u)
        if len(fl) < 2 or len(pp) < 2:
            raise WorkerError('BOARD_POSTS_PLATE', 'Floor or click plate not found above the plunger.', {'side': name})
        a1, a2, b1, b2 = fl[0][0] - 3, fl[1][0] - 3, pp[0][0], pp[1][0]
        fp = [(sx * (PW / 2 + FIL), sy * (PH / 2 + FIL)) for sx in (-1, -0.5, 0, 0.5, 1) for sy in (-1, -0.5, 0, 0.5, 1)]
        us, ts = [], []
        for px, py in fp:
            hh = hits(plate, Pw + R[:, 0] * px + R[:, 1] * py, u)
            if len(hh) < 2:
                raise WorkerError('BOARD_POSTS_PLATE', 'The click plate does not cover the actuator footprint.', {'side': name, 'local': [px, py]})
            us.append(hh[0][0])
            ts.append(hh[1][0])
        cf, res = plane_fit([(px, py, z) for (px, py), z in zip(fp, ts)])
        n = np.array([-cf[1], -cf[2], 1.0])
        n /= np.linalg.norm(n)
        cutter = plane_box((0, 0, cf[0] - prm['act_top_margin_mm'] / n[2] - res), n, 60.0, 30.0)
        ztop = max(us) + prm['act_into_plate_mm']
        col = rbox(0, 0, PRE, PW, PH, CR, ztop - PRE)
        col, _ = boolean('cut', col, [cutter], f'{name} actuator trim', expect_solids=1)
        post = one(xform(col, R, Pw), f'{name} actuator post')
        newp, rec = boolean('fuse', plate, [post], f'{name} plate + actuator', expect_solids=1, clean=True)
        records.append(rec)
        sol = one(newp, f'{name} plate + actuator')
        v_post, v_ov = bvol(post), bvol(boolean('common', plate, [post], f'{name} plate / actuator overlap')[0])
        kept = bvol(boolean('common', sol, [post], f'{name} actuator kept')[0])
        dm = mvol(sol, prm) - mvol(plate, prm)
        if abs(kept - v_post) > 0.005 * v_post + 0.05 or abs(dm - (v_post - v_ov)) > 0.02 * v_post + 0.5 or not v_post - v_ov > 1e-3:
            raise WorkerError('BOARD_POSTS_BOOKKEEPING', 'The actuator post is not fused into the plate as expected.',
                              {'side': name, 'post': v_post, 'overlap': v_ov, 'kept': kept, 'mesh_delta': dm})
        fil_ok, n_edges = False, 0
        if FIL > 0:
            from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
            sel = []
            for e in L.explore(sol, 'edge'):
                mp = edge_mid(e)
                hh = hits(plate, mp - np.array([0, 0, 3.0]), (0, 0, 1))
                loc = R.T @ (mp - Pw)
                if hh and abs(hh[0][0] - 3) < 2e-3 and math.hypot(loc[0], loc[1]) < math.hypot(PW, PH) / 2 + 0.05:
                    sel.append(e)
            n_edges = len(sel)
            if sel:
                try:
                    mf = BRepFilletAPI_MakeFillet(sol)
                    for e in sel:
                        mf.Add(FIL, e)
                    mf.Build()
                    if mf.IsDone():
                        fs = L.solids(mf.Shape())
                        if len(fs) == 1 and L.is_valid(fs[0]):
                            sol, fil_ok = fs[0], True
                except Exception:  # noqa: BLE001 - a failed fillet is reported, the plate stays unfilleted
                    fil_ok = False
        h0, h1 = np.array(s['hinge'][0], float), np.array(s['hinge'][1], float)
        ax = (h1 - h0) / np.linalg.norm(h1 - h0)
        lever = float(np.linalg.norm(np.cross(Pw - h0, ax)))
        th = prm['travel_mm'] / lever
        Rt = rot(ax, th)
        if (Rt @ (Pw - h0) + h0 - Pw) @ u > 0:
            th = -th
            Rt = rot(ax, th)
        mid = Pw + u * (a1 + a2) / 2
        dmov = Rt @ (mid - h0) + h0 - mid
        dl = R.T @ (dmov - (dmov @ u) * u)
        m = prm['hole_probe_margin_mm']
        hz = []
        for px in (-(PW / 2 + m), 0, PW / 2 + m):
            for py in (-(PH / 2 + m), 0, PH / 2 + m):
                h = hits(shell, Pw + R[:, 0] * px + R[:, 1] * py - u * 3, u)
                if len(h) < 2:
                    raise WorkerError('BOARD_POSTS_NO_FLOOR', 'No floor around the actuator hole.', {'side': name, 'local': [px, py]})
                hz.append((h[0][0] - 3, h[1][0] - 3))
        zlo, zhi = min(h[0] for h in hz) - prm['hole_below_mm'], max(h[1] for h in hz) + prm['hole_above_mm']
        HX, HY = PW + 2 * HCLR + abs(dl[0]), PH + 2 * HCLR + abs(dl[1])
        holes.append(xform(rbox(dl[0] / 2, dl[1] / 2, zlo, HX, HY, CR, zhi - zlo), R, Pw))
        out_plates[name], out_posts[name] = sol, post
        info[name] = {'plate': s['plate_part'], 'plunger_top': np.round(Pw, 4).tolist(), 'floor_underside_along_u': round(a1, 3), 'floor_top_along_u': round(a2, 3),
                      'plate_underside_along_u': round(b1, 3), 'plate_top_along_u': round(b2, 3), 'post_len_tip_to_underside': round(b1 - PRE, 3),
                      'fillet_ring_underside': [round(min(us), 3), round(max(us), 3)], 'hinge_p0': h0.tolist(), 'hinge_p1': h1.tolist(), 'lever_mm': round(lever, 3),
                      'theta_deg': round(math.degrees(th), 4), 'lateral_at_floor_mid_mm': round(float(math.hypot(dl[0], dl[1])), 4),
                      'hole': f'rect {HX:.3f} x {HY:.3f} r{CR}', 'hole_z_along_u': [round(zlo, 3), round(zhi, 3)], 'post': f'rect {PW} x {PH} r{CR}',
                      'root_fillet_edges': n_edges, 'root_fillet_applied': fil_ok, 'plate_valid': L.is_valid(sol), 'plate_top_plane_resid': round(res, 4)}
    hc = L.compound(holes)
    mat = bvol(boolean('common', shell, [hc], 'floor hole material')[0])
    cut, rec = boolean('cut', shell, holes, 'floor holes')
    records.append(rec)
    out = largest(cut)
    left = bvol(boolean('common', out, [hc], 'floor holes left')[0])
    dm = mvol(out, prm) - mvol(shell, prm)
    book = {'hole_material_mm3': mat, 'hole_material_left_mm3': left, 'mesh_delta_mm3': dm, 'solids_after_cut': len(L.solids(cut))}
    if not mat > 1e-3 or left > 1e-3 or abs(dm + mat) > 0.05 * mat + 0.5:
        raise WorkerError('BOARD_POSTS_BOOKKEEPING', 'The floor holes did not remove their material (silent no-op cut).', book)
    return out, holes, out_plates, out_posts, info, records, book


def write(path: Path, parts: list[tuple[str, Any]]) -> str:
    """Named XCAF STEP (one component per part, label = part name; mouse_parts_lib reads the names back)."""
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs
    from OCP.TDataStd import TDataStd_Name
    from OCP.Interface import Interface_Static
    Interface_Static.SetIVal_s('write.surfacecurve.mode', 0)        # as the v39 scripts
    doc = TDocStd_Document(TCollection_ExtendedString('XmlOcaf'))
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    asm = st.NewShape()
    for name, sol in parts:
        comp = st.AddComponent(asm, sol, False)
        TDataStd_Name.Set_s(comp, TCollection_ExtendedString(name))
        TDataStd_Name.Set_s(st.FindShape(sol, False), TCollection_ExtendedString(name))
    st.UpdateAssemblies()
    w = STEPCAFControl_Writer()
    w.SetNameMode(True)
    if not w.Transfer(doc, STEPControl_AsIs) or int(w.Write(str(path))) != 1:
        raise WorkerError('BOARD_POSTS_STEP_WRITE', 'STEP write failed.', {'file': path.name})
    return path.name


def roundtrip(path: Path) -> dict[str, Any]:
    ss = L.solids(L.read_step(path))
    return {'solids': len(ss), 'valid': all(L.is_valid(s) for s in ss), 'brep_volume_mm3': round(sum(P.volume(s) for s in ss), 4)}


def run(req: dict[str, Any]) -> dict[str, Any]:
    L.require_ocp()
    prm = req['params']
    paths = [req['inputs'][k] for k in sorted(req['inputs'], key=lambda s: int(s.split('_')[1]))]
    parts, table = P.load_parts(paths)
    sides = prm['sides']
    dv = prm.get('derive')
    if sides is None:
        need = [prm['shell_part'], prm['pcb_part'], prm['switch_part'], *prm['board_parts'], *dv['seed_switch_parts'], *(dv.get('plate_parts') or [])]
    else:
        need = [prm['shell_part'], prm['pcb_part'], prm['switch_part'], *prm['board_parts']] + \
            ([s['plate_part'] for s in sides] if prm['stage'] == 'all' else [])
    P.require(parts, sorted(set(need)), 'shell_part / board_parts / sides.plate_part')
    shell = parts[prm['shell_part']]
    if len(L.solids(shell)) != 1:
        raise WorkerError('BOARD_POSTS_SHELL', 'The shell part must be one solid.', {'solids': len(L.solids(shell))})
    shell = L.solids(shell)[0]
    D = board_datums(parts[prm['pcb_part']], parts[prm['switch_part']], prm)
    prm = dict(prm)
    if prm.get('post_dia') is None:
        if D['hole_dia_mm'] is None:
            raise WorkerError('BOARD_POSTS_HOLES', 'post_dia cannot follow the board hole: the hole diameter is unknown.', {})
        prm['post_dia'] = round(D['hole_dia_mm'] - prm['post_hole_clearance_mm'], 4)
        D['post_dia_source'] = f'measured hole {D["hole_dia_mm"]:.4f} - clearance {prm["post_hole_clearance_mm"]}'
    else:
        D['post_dia_source'] = 'argument'
    if prm['pilot_dia'] >= prm['post_dia'] - 0.4:
        raise WorkerError('BOARD_POSTS_SETTINGS', 'pilot_dia must leave at least 0.2 mm wall in the post (post_dia follows the measured hole).',
                          {'pilot_dia': prm['pilot_dia'], 'post_dia': prm['post_dia']})
    if prm.get('mirror_y') is not None:
        plane = {'plane_y_mm': float(prm['mirror_y']), 'plane_source': 'argument'}
    else:
        from cadmcp_brain.studio.mouse_seam_audit_worker import fit_mirror_plane
        m0 = L.tessellate(shell, 0.1, 0.3)
        fit = fit_mirror_plane(m0['V'], 1)
        plane = {'plane_y_mm': fit['plane_mm'], 'plane_source': 'fitted from the shell', 'fit_residual_mm': fit['residual_mm'], 'shell_extent_y_mm': fit['extent_mm']}
    report_plane = plane
    derivation = None
    if sides is None:
        sides, derivation, rules = derive_sides(shell, parts, D, plane['plane_y_mm'], prm)
        pitch, fits = pitch_fit(shell, D, sides, prm)
        derivation['pivot_z_plunger_gap_per_side'] = pivot_z_by_plunger_gap(shell, D, sides, rules, pitch, prm)
        derivation['sides'] = [dict(s) for s in sides]
        pitch, fits, shifts, dn, placed = place(shell, D, sides, prm, *pitch_fit(shell, D, sides, prm))
    else:
        pitch, fits, shifts, dn, placed = place(shell, D, sides, prm)
    out = Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    board_names = {}
    asm = []
    for s in sides:
        pl = placed[s['name']]
        named = []
        for i, bp in enumerate(prm['board_parts']):
            nm = f'{prm["board_prefix"]}_{s["name"]}_{i}'
            named.append((nm, one(xform(parts[bp], pl['R'], pl['t']), nm)))
        board_names[s['name']] = [n for n, _ in named]
        files[f'boards_{s["name"]}'] = write(out / f'boards_{s["name"]}.step', named)
        asm += named
    mirror = None
    if len(sides) == 2:
        a, b = (np.array(placed[s['name']]['plunger_top']) for s in sides)
        my = plane['plane_y_mm']
        mirror = {'plunger_x_diff_mm': abs(a[0] - b[0]), 'plunger_z_diff_mm': abs(a[2] - b[2]), **plane,
                  'plunger_y_mirror_dev_mm': abs((a[1] - my) + (b[1] - my))}
    report_plane = plane
    report: dict[str, Any] = {
        'stage': prm['stage'], 'board': D, 'post_dia_mm': prm['post_dia'], 'mirror_plane': report_plane, 'pitch_deg': math.degrees(pitch), 'roll_deg': 0.0, 'pitch_fit': fits,
        'normal_shift_per_side_mm': shifts, 'normal_shift_common_mm': dn, 'body_gap_target_mm': prm['body_gap_mm'], 'mirror': mirror,
        'sides': {n: {'R': np.round(p['R'], 6).tolist(), 't': np.round(p['t'], 4).tolist(), 'u': np.round(p['u'], 5).tolist(),
                      'plunger_top': np.round(p['T'], 4).tolist(), 'body_gap_mm': round(p['body_gap_mm'], 4),
                      'body_gap_nearest_local_xy': np.round(p['body_gap_nearest_local_xy'], 3).tolist(),
                      'plunger_gap_min_mm': round(p['plunger_gap_min_mm'], 4), 'board_parts': board_names[n]} for n, p in placed.items()},
        'derived_sides': derivation, 'parts_loaded': table, 'booleans': []}
    if prm['stage'] in ('posts', 'all'):
        shell2, posts, pinfo, recs, vol = build_posts(shell, D, placed, prm)
        report['booleans'] += recs
        report['posts'] = pinfo
        report['shell_posts_volume'] = vol
        if prm['stage'] == 'posts':
            final = shell2
        else:
            plates = {s['name']: one(parts[s['plate_part']], s['plate_part']) for s in sides}
            final, htools, nplates, aposts, ainfo, recs2, vol2 = build_actuators(shell2, plates, D, placed, sides, prm)
            report['booleans'] += recs2
            report['actuators'] = ainfo
            report['floor_holes_volume'] = vol2
            for s in sides:
                pn = f'{s["plate_part"]}{prm["plate_suffix"]}'
                files[f'plate_{s["name"]}'] = write(out / f'{pn}.step', [(pn, nplates[s['name']])])
                files[f'actuator_post_{s["name"]}'] = write(out / f'actuator_post_{s["name"]}.step', [(f'actuator_post_{s["name"]}', aposts[s['name']])])
                asm.append((pn, nplates[s['name']]))
            files['floor_hole_tool'] = write(out / 'floor_hole_tool.step', [(f'floor_hole_{i}', one(h, 'floor hole tool')) for i, h in enumerate(htools)])
            files['shell_posts_only'] = write(out / 'shell_posts_only.step', [(prm['shell_out_name'] + '_no_holes', shell2)])
        files['shell'] = write(out / f'{prm["shell_out_name"]}.step', [(prm['shell_out_name'], final)])
        files['posts_tool'] = write(out / 'posts_tool.step', [(prm['posts_out_name'], s) for s in L.solids(posts)])
        asm += [(prm['shell_out_name'], final)] + [(prm['posts_out_name'] if i == 0 else f'{prm["posts_out_name"]}_{i}', s) for i, s in enumerate(L.solids(posts))]
        mv = mvol(final, prm)
        report['shell'] = {'valid': L.is_valid(final), 'mesh_volume_mm3': mv, 'mesh_volume_in_mm3': mvol(shell, prm), 'brep_volume_mm3': P.volume(final),
                           'brep_volume_in_mm3': P.volume(shell), 'mass_g': mv * prm['density_g_cm3'] * 1e-3, 'roundtrip': roundtrip(out / files['shell']),
                           'note': 'mass from the closed-mesh volume (mesh_deflection_mm); the B-rep Gauss volume of the scanned B-spline faces is not reliable'}
        if not report['shell']['valid'] or report['shell']['roundtrip']['solids'] != 1 or not report['shell']['roundtrip']['valid']:
            raise WorkerError('BOARD_POSTS_SHELL_INVALID', 'The shell with posts is not one valid solid after the STEP round trip.', report['shell'])
    files['assembly'] = write(out / 'board_posts_parts.step', asm)
    return {'report': L.clean(report), 'files': files, 'worker_version': WORKER_VERSION}


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
