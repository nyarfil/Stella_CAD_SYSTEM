"""Wheel window of a mouse top shell (brain_mouse_wheel_window). SUBPROCESS WORKER (server python: OCP + vtk, extra `geometry`).

Run as:  <server python> -I mouse_wheel_window_worker.py request.json      (result = last stdout line, JSON)

Port of the owner's v23c2 / v23f_fix.py step to plain OCP. The cutting tool is a prism (Z-parallel) over the window rectangle, with the corner radius
on the vertical edges, spanning the whole shell height. Modes:
  explicit          rect = [x_min, x_max, y_min, y_max]; all four corners rounded.
  widen_rear        the existing window is measured on the shell (vertical ray scan at the wheel centre); the tool starts delta_mm behind its rear edge
                    (or behind rear_edge_mm) and ends inside the window; only the two REAR corners are rounded (v23f: delta 0.8, half width 4.16, R 3.33).
  rect_from_wheel   shell surface samples closer than clearance_mm to the wheel parts (exact mesh distance, no OCC offset) are the intrusion; the tool is
                    the plan rectangle of the intrusion (half width = max(intrusion, half_width_mm)), enlarged in 0.05 mm steps until the rounded corners
                    leave no sample outside it. Nothing to cut -> status NO_CHANGE_NEEDED (no boolean is run).
Front direction: front_axis ('+x' default, '-x', '+y', '-y') names the world direction the mouse front points to; "rear" is the opposite side. All
window logic runs in a local frame (u = along the front axis, v = lateral) and is mapped back to the world rectangle. Corner radius: corner_radius_mm,
or (None) CORNER_RADIUS_FRACTION x the window half width (a process proportion: the owner's v23f has R 3.33 on half width 4.16 = 0.80).
Every Boolean is gated: result non-null, no OCC error, exactly one solid, valid, removed volume = volume of common(part, tool). The output assembly is
written as STEP, read back, and every other part is compared (volume, centre of mass) with the input. Distances and overlaps against the parts near the
window come from mouse_interference_worker.run on the written assembly.
"""
from __future__ import annotations
import json
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

WORKER_VERSION = 'mouse_wheel_window/4'
CORNER_RADIUS_FRACTION = 0.8   # corner radius / window half width when corner_radius_mm is not given (owner v23f: R 3.33, half width 4.16)
VOL_TOL_MM3 = 0.05          # removed volume vs common volume
ROUNDTRIP_REL = 1e-4        # STEP round trip volume
STEP_GROW_MM = 0.05
MAX_GROW = 80
EPS_INTRUSION_MM3 = 1e-3


# ---------------------------------------------------------------- OCP helpers
_VOL_CACHE: dict[int, tuple[Any, float]] = {}


def vol(s) -> float:
    """Volume by adaptive B-rep integration (eps 1e-6). The default Gauss rule is off by ~1 mm3 on a 13000 mm3 trimmed B-spline shell (measured:
    default removed 10.87 vs common 9.37, adaptive removed 9.369), so every volume gate uses this."""
    k = id(s)
    if k in _VOL_CACHE and _VOL_CACHE[k][0] is s:
        return _VOL_CACHE[k][1]
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(s, g, 1e-6, False)
    v = abs(float(g.Mass()))
    _VOL_CACHE[k] = (s, v)
    return v


def solids_vol(shape) -> float:
    return sum(vol(s) for s in L.solids(shape))


def com(s) -> np.ndarray:
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(s, g)
    p = g.CentreOfMass()
    return np.array([p.X(), p.Y(), p.Z()])


def make_box(x0, x1, y0, y1, z0, z1):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    return BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()


def z_edges(box) -> list[Any]:
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    m = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(box, TopAbs_EDGE, m)
    out = []
    for i in range(1, m.Extent() + 1):
        e = TopoDS.Edge_s(m.FindKey(i))
        c = BRepAdaptor_Curve(e)
        a, b = c.Value(c.FirstParameter()), c.Value(c.LastParameter())
        if abs(a.X() - b.X()) < 1e-9 and abs(a.Y() - b.Y()) < 1e-9:
            out.append((e, a.X(), a.Y()))
    return out


def window_tool(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float, radius: float, rear_only: bool, rear: tuple[int, float] | None = None):
    """Prism over [x0,x1] x [y0,y1] with R on the vertical edges (the two rear ones when rear_only). rear = (axis index 0|1, world coordinate of the rear
    side of the rectangle); the length of the rectangle along that axis and the width across it are checked against the radius."""
    ax = 0 if rear is None else rear[0]
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        raise WorkerError('WINDOW_RECT', 'The window rectangle is empty.', {'x': [x0, x1], 'y': [y0, y1]})
    box = make_box(x0, x1, y0, y1, z0, z1)
    if radius <= 0:
        return L.solids(box)[0]
    n_round = 2 if rear_only else 4
    length, width = ((x1 - x0), (y1 - y0)) if ax == 0 else ((y1 - y0), (x1 - x0))
    if radius * 2 >= width - 1e-9 or radius * (1 if rear_only else 2) >= length - 1e-9:
        raise WorkerError('WINDOW_RADIUS', 'corner_radius_mm does not fit the window rectangle (needs R < half width and R < length).',
                          {'radius': radius, 'x': [x0, x1], 'y': [y0, y1]})
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    f = BRepFilletAPI_MakeFillet(box)
    rear_c = x0 if rear is None else rear[1]
    es = [e for e, x, y in z_edges(box) if (not rear_only) or abs((x, y)[ax] - rear_c) < 1e-9]
    if len(es) != n_round:
        raise WorkerError('WINDOW_FILLET', 'The tool prism has an unexpected edge set.', {'edges': len(es), 'expected': n_round})
    for e in es:
        f.Add(radius, e)
    f.Build()
    if not f.IsDone() or f.Shape().IsNull():
        raise WorkerError('WINDOW_FILLET', 'The corner fillet of the cutting tool failed.', {'radius': radius})
    t = L.solids(f.Shape())
    if len(t) != 1 or not L.is_valid(t[0]):
        raise WorkerError('WINDOW_FILLET', 'The filleted cutting tool is not one valid solid.', {'solids': len(t)})
    return t[0]


def boolean(kind: str, a, b):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Common
    op = (BRepAlgoAPI_Cut if kind == 'cut' else BRepAlgoAPI_Common)(a, b)
    op.Build()
    if not op.IsDone() or op.Shape().IsNull():
        raise WorkerError('WINDOW_BOOLEAN', f'OCC Boolean {kind} failed (null result or error).', {'kind': kind})
    return op.Shape()


def mesh_common_volume(a, b, defl: float = 0.02) -> float | None:
    """Volume of the intersection of the two closed tessellations (trimesh weld + manifold3d), None when unavailable or not manifold."""
    try:
        import manifold3d as m3
        import trimesh
    except ImportError:
        return None
    ms = []
    for shape in (a, b):
        V, T = P.mesh(shape, defl)
        if P.mesh_volume(V, T) < 0:
            T = T[:, ::-1].copy()
        tm = trimesh.Trimesh(V, T, process=True)
        tm.merge_vertices(digits_vertex=6)
        mm = m3.Manifold(m3.Mesh(vert_properties=np.asarray(tm.vertices, dtype=np.float32), tri_verts=np.asarray(tm.faces, dtype=np.uint32)))
        if mm.status() != m3.Error.NoError or mm.is_empty():
            return None
        ms.append(mm)
    return float(abs((ms[0] ^ ms[1]).volume()))


def common_volume(a, b) -> tuple[float, str]:
    """Volume of a & b -> (mm3, method). The exact OCC Common first; when it reports an error or a null result (known on near-contact trimmed
    B-spline shells: BRepAlgoAPI_Common silently fails where the two skins touch) the closed tessellations are intersected with manifold3d
    (method 'mesh', stated in the report). Neither branch may read 0 silently: a failed OCC run with no mesh fallback is WINDOW_BOOLEAN."""
    try:
        return solids_vol(boolean('common', a, b)), 'occ'
    except WorkerError as e:
        v = mesh_common_volume(a, b)
        if v is None:
            raise WorkerError('WINDOW_BOOLEAN', 'OCC Boolean common failed and the mesh intersection fallback (trimesh + manifold3d) is not available.',
                              {'occ': e.details}) from e
        print(f'[wheel_window] OCC common failed; mesh intersection used ({v:.4f} mm3)', file=sys.stderr, flush=True)
        return v, 'mesh'


def gated_cut(name: str, part, tool, must_remove: bool) -> dict[str, Any]:
    """Cut tool out of part. Gates: result non-null, one solid, valid, removed volume = common volume. Returns {shape, ...}."""
    v0 = vol(part)
    v_common, c_method = common_volume(part, tool)
    row = {'part': name, 'volume_before_mm3': round(v0, 4), 'common_volume_mm3': round(v_common, 4), 'common_method': c_method}
    if v_common < 1e-6:
        if must_remove:
            raise WorkerError('WINDOW_NO_EFFECT', f'The cutting tool does not touch "{name}": the Boolean would be a silent no-op.', row)
        return {**row, 'shape': part, 'changed': False, 'removed_mm3': 0.0, 'gates': {'tool_touches_part': False}}
    res = boolean('cut', part, tool)
    ss = L.solids(res)
    removed = v0 - sum(vol(s) for s in ss)
    gates = {'solid_count_1': len(ss) == 1, 'valid': bool(ss) and all(L.is_valid(s) for s in ss),
             'removed_equals_common': abs(removed - v_common) <= VOL_TOL_MM3 + 0.005 * v_common}
    row.update({'removed_mm3': round(removed, 4), 'volume_after_mm3': round(v0 - removed, 4), 'gates': gates})
    bad = [k for k, v in gates.items() if not v]
    if bad:
        raise WorkerError('WINDOW_CUT_GATE', f'The window cut of "{name}" failed gates: {bad}.', row)
    return {**row, 'shape': ss[0], 'changed': True}


# ---------------------------------------------------------------- window measurement
class Probe:
    """Does a vertical line at (x, y) hit the shell? (the shell is a thin top skin: material on the line = window closed there)."""

    def __init__(self, shell):
        from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
        self.it = IntCurvesFace_ShapeIntersector()
        self.it.Load(shell, 1e-6)
        bb = L.bbox(shell, optimal=False)
        self.z0, self.z1 = float(bb[2]) - 1.0, float(bb[5]) + 1.0

    def hit(self, x: float, y: float) -> bool:
        from OCP.gp import gp_Lin, gp_Pnt, gp_Dir
        self.it.Perform(gp_Lin(gp_Pnt(x, y, self.z0), gp_Dir(0, 0, 1)), 0.0, self.z1 - self.z0)
        return self.it.NbPnt() > 0

    def edge(self, a: float, b: float, along_x: bool, fixed: float) -> float:
        """a open, b closed: bisect to the boundary."""
        for _ in range(34):
            m = 0.5 * (a + b)
            h = self.hit(m, fixed) if along_x else self.hit(fixed, m)
            a, b = (a, m) if h else (m, b)
        return 0.5 * (a + b)

    def interval(self, c: float, fixed: float, along_x: bool, step: float = 0.05, span: float = 40.0) -> tuple[float, float] | None:
        h = (lambda t: self.hit(t, fixed)) if along_x else (lambda t: self.hit(fixed, t))
        if h(c):
            return None
        out = []
        for sgn in (-1, 1):
            t = c
            while abs(t - c) < span and not h(t):
                t += sgn * step
            if abs(t - c) >= span:
                return None
            out.append(self.edge(t - sgn * step, t, along_x, fixed))
        return out[0], out[1]


def measure_window(shell, cx: float, cy: float, ai: int = 0, span: float = 40.0) -> dict[str, Any]:
    """Open window around (cx, cy): world x/y ranges, found first along the front axis (ai 0 = x, 1 = y), then across it through the middle."""
    pr = Probe(shell)
    if ai == 0:
        xr = pr.interval(cx, cy, True, span=span)
        yr = pr.interval(cy, 0.5 * (xr[0] + xr[1]), False, span=span) if xr is not None else None
    else:
        yr = pr.interval(cy, cx, False, span=span)
        xr = pr.interval(cx, 0.5 * (yr[0] + yr[1]), True, span=span) if yr is not None else None
    if xr is None or yr is None:
        return {'found': False}
    return {'found': True, 'x_range': [round(xr[0], 4), round(xr[1], 4)], 'y_range': [round(yr[0], 4), round(yr[1], 4)],
            'at': {'y': round(cy, 4), 'x': round(0.5 * (xr[0] + xr[1]), 4)}}


def wheel_centre(parts: dict[str, Any], names: list[str]) -> tuple[float, float]:
    bb = L.bbox(L.compound([parts[n] for n in names]), optimal=False)
    return float((bb[0] + bb[3]) / 2), float((bb[1] + bb[4]) / 2)


def refine_samples(tri: np.ndarray, spacing: float, prune=None) -> np.ndarray:
    """Points on triangles (n,3,3): midpoint subdivision until every edge <= spacing; prune(tri) -> bool mask drops sub-triangles early."""
    out = []
    while len(tri):
        e = np.max(np.linalg.norm(tri - np.roll(tri, -1, axis=1), axis=2), axis=1)
        if prune is not None:
            k = prune(tri)
            tri, e = tri[k], e[k]
        done = e <= spacing
        if done.any():
            out.append(tri[done].reshape(-1, 3))
            out.append(tri[done].mean(1))
        tri = tri[~done]
        if not len(tri):
            break
        a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
        ab, bc, ca = (a + b) / 2, (b + c) / 2, (c + a) / 2
        tri = np.concatenate([np.stack([a, ab, ca], 1), np.stack([ab, b, bc], 1), np.stack([ca, bc, c], 1), np.stack([ab, bc, ca], 1)])
    return np.vstack(out) if out else np.zeros((0, 3))


def clearance_points(shell, wheel_shapes: list, clearance: float, slack: float) -> tuple[np.ndarray, dict[str, Any]]:
    """Points on the shell surface that lie closer than clearance + slack to the wheel parts (exact point-to-mesh distance). Replaces the OCC offset
    of the wheel (which fails on filleted / B-spline wheels): material of the shell within `clearance` of the wheel always has its boundary within
    that distance, so the points give the extent of the intrusion. Sample spacing is derived from the clearance (<= 0.15 mm)."""
    import vtk
    from scipy.spatial import cKDTree
    from cadmcp_brain.studio import mouse_parts_lib as PL
    spacing = min(0.15, max(0.05, clearance / 3.0))
    wm = [L.tessellate(w, 0.01, 0.3) for w in wheel_shapes]
    wV = np.vstack([m['V'] for m in wm])
    off = np.cumsum([0] + [len(m['V']) for m in wm])
    wT = np.vstack([m['T'] + o for m, o in zip(wm, off)])
    lim = clearance + slack
    wb0, wb1 = wV.min(0) - lim - 1.0, wV.max(0) + lim + 1.0
    tree = cKDTree(refine_samples(wV[wT], spacing))
    sm = L.tessellate(shell, 0.02, 0.3)
    tri = sm['V'][sm['T']]
    tri = tri[np.all(tri.max(1) >= wb0, axis=1) & np.all(tri.min(1) <= wb1, axis=1)]

    def prune(t):
        c = t.mean(1)
        r = np.max(np.linalg.norm(t - c[:, None, :], axis=2), axis=1)
        d, _ = tree.query(c, workers=-1)
        return d - r - spacing <= lim

    keep0 = prune(tri) if len(tri) else np.zeros(0, bool)
    cand = refine_samples(tri[keep0], spacing, prune) if keep0.any() else np.zeros((0, 3))
    n_cand = len(cand)
    pts = np.zeros((0, 3))
    dmin = None
    if n_cand:
        d0, _ = tree.query(cand, workers=-1)
        # the wheel samples lie on the wheel surface, so the sample-tree distance is an upper bound of the mesh distance and over-estimates it by at most
        # 0.6 x spacing (every mesh point is that close to a sample): points with tree distance <= lim are inside, > lim + 0.6 x spacing outside, only the
        # band in between gets the exact (slow) mesh distance
        band = d0 <= lim + 0.6 * spacing
        sure = (d0 <= lim)[band]
        cand = cand[band]
        loc = vtk.vtkCellLocator()
        loc.SetDataSet(PL.polydata(wV, wT))
        loc.BuildLocator()
        cp = [0.0, 0.0, 0.0]
        cid, sid, d2 = vtk.reference(0), vtk.reference(0), vtk.reference(0.0)
        dist = np.zeros(len(cand))
        for i in np.where(~sure)[0]:
            loc.FindClosestPoint(list(map(float, cand[i])), cp, cid, sid, d2)
            dist[i] = math.sqrt(float(d2))
        pts = cand[sure | (dist <= lim)]
        dmin = float(dist[~sure].min()) if (~sure).any() else None
    return pts, {'spacing_mm': spacing, 'candidates': int(n_cand), 'points_within': int(len(pts)), 'min_exact_distance_in_band_mm': dmin, 'exact_distance_evaluations': int((~sure).sum()) if n_cand else 0, 'slack_mm': slack,
                 'method': 'shell surface samples vs wheel mesh distance (no OCC offset)'}


def in_footprint(u: np.ndarray, v: np.ndarray, u0: float, u1: float, v0: float, v1: float, r: float) -> np.ndarray:
    """Points inside the rectangle [u0,u1] x [v0,v1] with all four corners rounded by r."""
    inside = (u >= u0) & (u <= u1) & (v >= v0) & (v <= v1)
    if r > 0:
        du = np.maximum(np.maximum(u0 + r - u, u - (u1 - r)), 0.0)
        dv = np.maximum(np.maximum(v0 + r - v, v - (v1 - r)), 0.0)
        inside &= du * du + dv * dv <= r * r
    return inside


# ---------------------------------------------------------------- STEP assembly
def write_assembly(parts: dict[str, Any], path: Path) -> None:
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs
    from OCP.TDataStd import TDataStd_Name
    doc = TDocStd_Document(TCollection_ExtendedString('XmlOcaf'))
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    asm = st.NewShape()
    for n, s in parts.items():
        st.AddComponent(asm, s, False)
        TDataStd_Name.Set_s(st.FindShape(s, False), TCollection_ExtendedString(n))
    st.UpdateAssemblies()
    w = STEPCAFControl_Writer()
    w.SetNameMode(True)
    if not w.Transfer(doc, STEPControl_AsIs) or int(w.Write(str(path))) != 1:
        raise WorkerError('WINDOW_STEP_WRITE', 'The assembly STEP could not be written.', {'file': path.name})


# ---------------------------------------------------------------- main
def near_parts(parts, tool_bbox, skip: set[str], margin: float, always: list[str]) -> list[str]:
    out = []
    for n, s in parts.items():
        if n in skip:
            continue
        b = L.bbox(s, optimal=False)
        gap = [max(0.0, tool_bbox[i] - b[i + 3], b[i] - tool_bbox[i + 3]) for i in range(3)]
        if n in always or math.sqrt(sum(g * g for g in gap)) <= margin:
            out.append(n)
    return out


def run(req: dict[str, Any]) -> dict[str, Any]:
    import time
    t0 = time.time()
    timing: dict[str, float] = {}

    def lap(k: str) -> None:
        timing[k] = round(time.time() - t0, 1)
        print(f'[wheel_window] {k} {timing[k]} s', file=sys.stderr, flush=True)

    prm = req['params']
    out = Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    paths = [req['inputs'][k] for k in sorted(req['inputs'], key=lambda s: int(s.split('_')[1]))]
    parts, table = P.load_parts(paths, prm.get('groups'))
    shell_name, plate_names = prm['shell_part'], list(prm.get('plate_parts') or [])
    wheel_names = list(prm['wheel_parts'])
    P.require(parts, [shell_name] + plate_names + wheel_names, 'shell_part / plate_parts / wheel_parts')
    if shell_name in plate_names or set(wheel_names) & ({shell_name} | set(plate_names)):
        raise WorkerError('WINDOW_PARTS', 'shell_part, plate_parts and wheel_parts must be different parts.', {})
    shell = parts[shell_name]
    if len(L.solids(shell)) != 1:
        raise WorkerError('WINDOW_SHELL', 'The shell part must be exactly one solid.', {'solids': len(L.solids(shell))})
    mode, clearance = prm['mode'], float(prm['clearance_mm'])
    radius_arg = prm.get('corner_radius_mm')
    fa = prm.get('front_axis', '+x')
    ai, sgn = (0 if fa[1] == 'x' else 1), (1.0 if fa[0] == '+' else -1.0)
    sb = L.bbox(shell, optimal=False)
    z0, z1 = float(sb[2]) - 1.0, float(sb[5]) + 1.0
    span = 0.5 * max(float(sb[3] - sb[0]), float(sb[4] - sb[1]))            # window search span scales with the shell footprint
    cx, cy = wheel_centre(parts, wheel_names)

    def ulat(x_rng, y_rng):                       # world ranges -> local (u along the front axis, v lateral), each [lo, hi]
        al, la = (x_rng, y_rng) if ai == 0 else (y_rng, x_rng)
        return ([al[0], al[1]] if sgn > 0 else [-al[1], -al[0]]), [la[0], la[1]]

    def world_rect(u0, u1, v0, v1):
        al, la = ([u0, u1] if sgn > 0 else [-u1, -u0]), [v0, v1]
        return (al[0], al[1], la[0], la[1]) if ai == 0 else (la[0], la[1], al[0], al[1])

    lap('loaded')
    before = measure_window(shell, cx, cy, ai, span)
    info: dict[str, Any] = {'mode': mode, 'front_axis': fa, 'wheel_centre_xy': [round(cx, 3), round(cy, 3)], 'window_before': before}
    rear_only = False
    status = 'OK'
    x0 = x1 = y0 = y1 = 0.0
    radius = 0.0
    rear_c: tuple[int, float] | None = None
    lat_c = cy if ai == 0 else cx                 # wheel centre across the front axis (world coordinate)
    if before['found']:
        bu, bv = ulat(before['x_range'], before['y_range'])

    if mode == 'explicit':
        x0, x1, y0, y1 = [float(v) for v in prm['rect']]
        hw = ((y1 - y0) if ai == 0 else (x1 - x0)) / 2
        radius = float(radius_arg) if radius_arg is not None else CORNER_RADIUS_FRACTION * hw
        rear_c = (ai, x0 if ai == 0 and sgn > 0 else x1 if ai == 0 else y0 if sgn > 0 else y1)
    elif mode == 'widen_rear':
        if prm.get('rear_edge_mm') is not None:
            rear_u = sgn * float(prm['rear_edge_mm'])
        elif before['found']:
            rear_u = bu[0]
        else:
            raise WorkerError('WINDOW_NO_WINDOW', 'No open window was found around the wheel centre; give rear_edge_mm or use rect_from_wheel / explicit.',
                              {'wheel_centre_xy': [cx, cy]})
        if prm.get('half_width_mm') is not None:
            hw = float(prm['half_width_mm'])
        elif before['found']:
            hw = (bv[1] - bv[0]) / 2
        else:
            raise WorkerError('WINDOW_NO_WINDOW', 'half_width_mm is needed when no window is measurable.', {})
        vc = float(prm['centre_y_mm']) if prm.get('centre_y_mm') is not None else ((bv[0] + bv[1]) / 2 if before['found'] else lat_c)
        radius = float(radius_arg) if radius_arg is not None else CORNER_RADIUS_FRACTION * hw
        delta = float(prm['delta_mm'])
        x0, x1, y0, y1 = world_rect(rear_u - delta, rear_u + radius + 1.0, vc - hw, vc + hw)
        rear_only, rear_c = True, (ai, sgn * (rear_u - delta))
        info.update({'rear_edge_before_mm': round(sgn * rear_u, 4), 'delta_mm': delta})
    else:  # rect_from_wheel
        # tolerance on the clearance test: half the sample spacing (+0.02) so that the rectangle never ends exactly at a sampled extreme
        slack = 0.5 * min(0.15, max(0.05, clearance / 3.0)) + 0.02
        ipts, cinfo = clearance_points(shell, [parts[n] for n in wheel_names], clearance, slack)
        info['intrusion'] = cinfo
        if len(ipts) == 0:
            status = 'NO_CHANGE_NEEDED'
        else:
            pu, pv = (ipts[:, 0], ipts[:, 1]) if ai == 0 else (ipts[:, 1], ipts[:, 0])
            pu = sgn * pu
            iu, iv = [float(pu.min()), float(pu.max())], [float(pv.min()), float(pv.max())]
            hw = max((iv[1] - iv[0]) / 2, float(prm['half_width_mm']) if prm.get('half_width_mm') is not None else 0.0)
            if prm.get('centre_y_mm') is not None:
                vc = float(prm['centre_y_mm'])
            elif before['found']:
                vc = (bv[0] + bv[1]) / 2
            else:
                vc = (iv[0] + iv[1]) / 2
            radius = float(radius_arg) if radius_arg is not None else CORNER_RADIUS_FRACTION * hw
            u0, u1 = iu[0] - 1e-3, max(iu[1] + 1e-3, iu[0] + 2 * radius + 0.5)
            v0, v1 = vc - hw, vc + hw
            info['intrusion_bbox_uv'] = [round(v, 4) for v in (iu[0], iu[1], iv[0], iv[1])]
            for it in range(MAX_GROW + 1):
                out_pts = ~in_footprint(pu, pv, u0, u1, v0, v1, radius)
                if not out_pts.any():
                    break
                if it == MAX_GROW:
                    raise WorkerError('WINDOW_GROW', 'The rectangle could not be grown to clear the wheel clearance zone.', {'points_left': int(out_pts.sum())})
                lu = [float(pu[out_pts].min()), float(pu[out_pts].max())]
                rear_short, front_short = lu[0] < u0 + radius + 0.1, lu[1] > u1 - radius - 0.1
                if rear_short or not front_short:
                    u0 -= STEP_GROW_MM
                if front_short or not rear_short:
                    u1 += STEP_GROW_MM
                if float(pv[out_pts].min()) < v0:
                    v0 -= STEP_GROW_MM
                if float(pv[out_pts].max()) > v1:
                    v1 += STEP_GROW_MM
            x0, x1, y0, y1 = world_rect(u0, u1, v0, v1)
            rear_c = (ai, sgn * u0)
            info['grow_steps'] = it
    info['corner_radius_source'] = 'argument' if radius_arg is not None else f'{CORNER_RADIUS_FRACTION} x window half width'

    result_parts = dict(parts)
    cuts: list[dict[str, Any]] = []
    if status == 'OK':
        tool = window_tool(x0, x1, y0, y1, z0, z1, radius, rear_only, rear_c)
        tool_bbox = L.bbox(tool, optimal=True)
        info['tool'] = {'x': [round(x0, 4), round(x1, 4)], 'y': [round(y0, 4), round(y1, 4)], 'z': [round(z0, 3), round(z1, 3)], 'corner_radius_mm': radius,
                        'rounded_corners': 'rear' if rear_only else 'all four', 'volume_mm3': round(vol(tool), 3)}
        for n in [shell_name] + plate_names:
            c = gated_cut(n, parts[n], tool, must_remove=(n == shell_name))
            result_parts[n] = c.pop('shape')
            cuts.append(c)
    else:
        tool_bbox = L.bbox(make_box(cx - 10, cx + 10, cy - 5, cy + 5, z0, z1), optimal=False)
    cut_names = [c['part'] for c in cuts if c['changed']]
    lap('cut_done')

    # ---- written assembly and STEP round trip
    stem = Path(paths[0]).stem
    asm_name = f'{stem}_wheelwindow.step'
    write_assembly(result_parts, out / asm_name)
    back, _ = P.load_parts([str(out / asm_name)])
    from cadmcp_brain.studio import mouse_groove_fill_worker as GF
    rt: dict[str, Any] = {'parts_same_names': sorted(back) == sorted(result_parts), 'cut_parts': [], 'unchanged_max_volume_change_mm3': 0.0,
                          'unchanged_max_centre_shift_mm': 0.0}
    gates = {'step_round_trip_names': rt['parts_same_names']}
    if rt['parts_same_names']:
        for n in result_parts:
            a, b = result_parts[n], back[n]
            if n in cut_names:
                ss = L.solids(b)
                # meshability is gated on the re-imported solid: a face the STEP reader rebuilds with a 2D wire gap is dropped by BRepMesh in every
                # downstream tool, and an in-memory ShapeFix would not survive the file
                unmeshed = GF.unmeshed_faces(ss[0], 0.05, clean=True) if len(ss) == 1 else []
                ok = len(ss) == 1 and L.is_valid(ss[0]) and abs(vol(b) - vol(a)) <= ROUNDTRIP_REL * vol(a) and not unmeshed
                rt['cut_parts'].append({'part': n, 'solids': len(ss), 'valid': bool(ss) and L.is_valid(ss[0]), 'volume_mm3': round(vol(b), 4),
                                        'volume_diff_mm3': round(vol(b) - vol(a), 6), 'unmeshed_faces': unmeshed, 'ok': ok})
                gates[f'step_round_trip_{n}'] = ok
            else:
                rt['unchanged_max_volume_change_mm3'] = max(rt['unchanged_max_volume_change_mm3'], abs(vol(b) - vol(parts[n])))
                rt['unchanged_max_centre_shift_mm'] = max(rt['unchanged_max_centre_shift_mm'], float(np.linalg.norm(com(b) - com(parts[n]))))
        gates['other_parts_unchanged'] = rt['unchanged_max_volume_change_mm3'] <= 1e-3 and rt['unchanged_max_centre_shift_mm'] <= 1e-3
    rt['unchanged_max_volume_change_mm3'] = round(rt['unchanged_max_volume_change_mm3'], 6)
    rt['unchanged_max_centre_shift_mm'] = round(rt['unchanged_max_centre_shift_mm'], 6)
    lap('round_trip_done')
    files = {'assembly_step': asm_name}
    for n in cut_names:
        fn = f'{n}_wheelwindow.step'
        L.write_step(result_parts[n], out / fn)
        files[f'{n}_step'] = fn

    # ---- window after, near parts. The full shell (13000 mm3 trimmed B-splines) makes the Booleans, the tessellation and BRepExtrema very slow, so every
    # measurement uses the neighbourhood of the window: all parts cropped to the tool bounding box + near_margin_mm (distances below that margin and
    # overlaps inside the box are exact; the report states the box).
    shell_after = back[shell_name] if rt['parts_same_names'] else result_parts[shell_name]
    info['window_after'] = measure_window(shell_after, cx, cy, ai, span)
    pad = float(prm['near_margin_mm'])
    crop = make_box(tool_bbox[0] - pad, tool_bbox[3] + pad, tool_bbox[1] - pad, tool_bbox[4] + pad, z0, z1)
    info['neighbourhood_box'] = [round(float(v), 3) for v in (tool_bbox[0] - pad, tool_bbox[3] + pad, tool_bbox[1] - pad, tool_bbox[4] + pad)]

    def cropped(shape):
        ss = L.solids(boolean('common', shape, crop))
        return ss[0] if len(ss) == 1 else shape

    near = near_parts(parts, tool_bbox, {shell_name} | set(plate_names), pad, wheel_names)
    hood = {c: cropped(back[c] if rt['parts_same_names'] else result_parts[c]) for c in [shell_name] + plate_names}
    hood.update({n: cropped(parts[n]) for n in near})
    shell_before_piece = cropped(parts[shell_name])
    near_tab = []
    for n in near:
        cb, cb_method = common_volume(shell_before_piece, hood[n])
        near_tab.append({'part': n, 'is_wheel': n in wheel_names, 'shell_common_before_mm3': round(cb, 4), 'common_before_method': cb_method})
    lap('common_before_done')
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    for r in near_tab:                              # exact B-rep distance on the neighbourhood pieces
        d = BRepExtrema_DistShapeShape(hood[shell_name], hood[r['part']])
        d.Perform()
        r['shell_exact_min_dist_mm'] = round(float(d.Value()), 4) if d.IsDone() else None
    lap('exact_distance_done')
    rows: list[dict[str, Any]] = []
    if near:
        from cadmcp_brain.studio import mouse_interference_worker as WI
        write_assembly(hood, out / 'window_neighbourhood.step')
        files_extra = {'neighbourhood_step': 'window_neighbourhood.step'}
        pairs = [{'a': c, 'b': n, 'clearance_mm': clearance} for c in [shell_name] + plate_names for n in near]
        res = WI.run({'inputs': {'step_0': str(out / 'window_neighbourhood.step')}, 'out_dir': str(out / 'interference'),
                      'params': {'pairs': pairs, 'clearance_mm': clearance}})
        rows = res['rows']
        files.update(files_extra)
        for r in near_tab:
            m = [x for x in rows if x['part_a'] == shell_name and x['part_b'] == r['part']]
            if m:
                r.update({'shell_common_after_mm3': m[0]['overlap_mm3'], 'shell_min_dist_after_mm': m[0]['min_dist_mm'],
                          'penetration_mm': m[0]['penetration_mm'], 'method': m[0]['method'], 'required_mm': m[0]['required_mm'], 'result': m[0]['result']})
    wheel_rows = [r for r in near_tab if r['is_wheel'] and r.get('shell_min_dist_after_mm') is not None]
    rear = {'min_distance_to_wheel_parts_mm': min((r['shell_min_dist_after_mm'] for r in wheel_rows), default=None),
            'per_wheel_part_mm': {r['part']: r['shell_min_dist_after_mm'] for r in wheel_rows},
            'per_wheel_part_exact_mm': {r['part']: r['shell_exact_min_dist_mm'] for r in near_tab if r['is_wheel']}, 'required_mm': clearance,
            'clearance_met': all(min(r['shell_min_dist_after_mm'], r.get('shell_exact_min_dist_mm') or 1e9) >= clearance - 1e-3 and (r['shell_common_after_mm3'] or 0.0) < 0.01
                                 for r in wheel_rows)
            if wheel_rows else None}
    with open(out / 'wheel_window_near_parts.json', 'w', encoding='utf-8') as fh:
        json.dump({'near_parts': near_tab, 'rows': rows}, fh, indent=1, default=str)
    files['near_parts_json'] = 'wheel_window_near_parts.json'
    lap('interference_done')
    ok = all(gates.values()) and status in ('OK', 'NO_CHANGE_NEEDED')
    return {'status_window': status, 'gates': gates, 'gates_ok': ok, 'window': info, 'cuts': cuts, 'step_round_trip': rt, 'near_parts': near_tab,
            'rear_clearance': rear, 'parts': table, 'files': files, 'timing_s': timing, 'worker_version': WORKER_VERSION}


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
