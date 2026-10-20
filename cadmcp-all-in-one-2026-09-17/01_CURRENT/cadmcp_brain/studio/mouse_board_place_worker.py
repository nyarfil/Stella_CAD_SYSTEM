"""Worker of brain_mouse_board_place (server python, OCP + vtk + scipy): translate a board pack into a scanned / modelled top shell by geometric rules
and report the placement residuals. Nothing is forced: a pack that does not fit gives NOT_READY with reasons (the candidate pose is still written
for inspection, as candidate_pack.step).

Frame: x = front, y = lateral (mirror normal), z = up. The pose is a TRANSLATION (the pack frame must already have the main PCB level).
  ty: sensor_part bbox centre y -> the mirror plane (fitted from the shell, or mirror_y).
  tz: floor_datum_part min z -> floor z (floor_z, or the min z of floor_part / floor_region_path = the bottom-plate bottom face).
  tx: x_rule bush_flush = the angled end face(s) of bush_part (planar faces inclined 5-75 deg to the front axis) lie on the OUTER skin (median signed
      offset along the face normal = 0, exit crossings of the shell and the bottom plate: floor_part solid or floor_region_path scan mesh); wheel = the wheel parts' x centre -> the wheel window centre.
Checks (residuals): PCB level, wheel centre vs window, each seed switch plunger under a click plate / click region and its vertical gap to the shell,
clearance of every pack part to the shell (hollow shell: distance to the material, points below the rim + parting_band_mm not checked; closed
solid skin: depth below the non-parting skin (downward faces, normal z < -0.7, are the parting surface) minus wall_mm; an outside point at or below
the shell underside height map is under the top shell = bottom-plate territory, not checked here).
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
from cadmcp_brain.studio import mouse_board_posts_worker as W
from cadmcp_brain.studio.mouse_interference_worker import samples as tri_samples


def ebox(shape):
    """Exact B-rep bbox (no triangulation, no tolerance): datum extremes do not change after the parts are meshed."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    b = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, b, False, False)
    return np.array(b.Get())


def sub_samples(V, T, step):
    """Surface samples of the triangles T only (mouse_interference_worker.samples also returns every vertex of V)."""
    u, inv = np.unique(T, return_inverse=True)
    return tri_samples(V[u], inv.reshape(T.shape), step) if len(T) else np.zeros((0, 3))


def moved(shape, t):
    return W.xform(shape, np.eye(3), np.asarray(t, float))


def outward_mesh(shape, defl):
    V, T = P.mesh(shape, defl)
    if P.mesh_volume(V, T) < 0:
        T = T[:, ::-1].copy()
    return np.asarray(V, float), np.asarray(T, int)


def implicit(V, T):
    import vtk
    nf = vtk.vtkPolyDataNormals()
    nf.SetInputData(P.polydata(V, T))
    nf.ComputeCellNormalsOn()
    nf.SplittingOff()
    nf.ConsistencyOff()
    nf.AutoOrientNormalsOff()
    nf.Update()
    imp = vtk.vtkImplicitPolyDataDistance()
    imp.SetInput(nf.GetOutput())
    return imp


def signed(imp, pts, surface=None):
    """Signed distance (negative inside). The magnitude comes from vtkImplicitPolyDataDistance; the sign, when the closed surface (V, T) is given,
    from vtkSelectEnclosedPoints (ray parity), which stays right where the closest-cell normal of a scanned B-spline tessellation is unreliable."""
    from cadmcp_brain.studio.mouse_interference_worker import signed as s
    d = s(imp, pts)
    if surface is None or not len(pts):
        return d
    import vtk
    from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy
    vp = vtk.vtkPoints()
    vp.SetData(numpy_to_vtk(np.ascontiguousarray(pts, dtype=float), deep=True))
    pd = vtk.vtkPolyData()
    pd.SetPoints(vp)
    sel = vtk.vtkSelectEnclosedPoints()
    sel.SetInputData(pd)
    sel.SetSurfaceData(P.polydata(*surface))
    sel.SetTolerance(1e-6)
    sel.Update()
    inside = vtk_to_numpy(sel.GetOutput().GetPointData().GetArray('SelectedPoints')).astype(bool)
    return np.where(inside, -np.abs(d), np.abs(d))


def classify(shape, p) -> bool:
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_IN
    from OCP.gp import gp_Pnt
    c = BRepClass3d_SolidClassifier(shape, gp_Pnt(*map(float, p)), 1e-6)
    return c.State() == TopAbs_IN


def planar_faces(shape):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepTools import BRepTools
    out = []
    for f in L.faces(shape):
        if BRepAdaptor_Surface(f).GetType() != GeomAbs_Plane:
            continue
        g = GProp_GProps()
        BRepGProp.SurfaceProperties_s(f, g)
        u0, u1, v0, v1 = BRepTools.UVBounds_s(f)
        n = np.asarray(L.face_normal_uv(f, (u0 + u1) / 2, (v0 + v1) / 2), float)
        out.append({'face': f, 'area': float(g.Mass()), 'c': np.array(g.CentreOfMass().Coord()), 'n': n / np.linalg.norm(n)})
    return out


def face_points(face, k=7):
    """Interior points of a face on a k x k UV grid (face classifier)."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    from OCP.BRepTopAdaptor import BRepTopAdaptor_FClass2d
    from OCP.TopAbs import TopAbs_IN
    from OCP.gp import gp_Pnt2d
    a = BRepAdaptor_Surface(face)
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    cl = BRepTopAdaptor_FClass2d(face, 1e-7)
    pts = []
    for fu in np.linspace(0.05, 0.95, k):
        for fv in np.linspace(0.05, 0.95, k):
            u, v = u0 + fu * (u1 - u0), v0 + fv * (v1 - v0)
            if cl.Perform(gp_Pnt2d(u, v)) == TopAbs_IN:
                pts.append(np.array(a.Value(u, v).Coord()))
    return pts


def pcb_tilt(pcb) -> tuple[float, list[float]]:
    pf = planar_faces(pcb)
    if not pf:
        raise WorkerError('BOARD_PLACE_PCB', 'pcb_part has no planar face: its level cannot be checked.', {})
    f = max(pf, key=lambda q: q['area'])
    return math.degrees(math.acos(min(1.0, abs(float(f['n'][2]))))), np.round(f['n'], 5).tolist()


def mesh_region(path, scale=1.0):
    r = L.read_stl(Path(path), scale)
    V, T = (r['V'], r['T']) if isinstance(r, dict) else (r[0], r[1])
    return np.asarray(V, float), np.asarray(T, int)


def region_contains_xy(V, T, xy) -> bool:
    a, b, c = V[T[:, 0], :2], V[T[:, 1], :2], V[T[:, 2], :2]
    p = np.asarray(xy, float)
    d = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
    ok = np.abs(d) > 1e-12
    l1 = np.where(ok, ((b[:, 1] - c[:, 1]) * (p[0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (p[1] - c[:, 1])) / np.where(ok, d, 1), -1)
    l2 = np.where(ok, ((c[:, 1] - a[:, 1]) * (p[0] - c[:, 0]) + (a[:, 0] - c[:, 0]) * (p[1] - c[:, 1])) / np.where(ok, d, 1), -1)
    return bool(np.any(ok & (l1 >= 0) & (l2 >= 0) & (1 - l1 - l2 >= 0)))


def region_centroid(V, T):
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    w = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2
    return ((a + b + c) / 3 * w[:, None]).sum(0) / w.sum(), V[np.unique(T)].min(0), V[np.unique(T)].max(0)


# ------------------------------------------------------------------ x rules
def bush_faces(bush, prm):
    lo, hi = math.cos(math.radians(prm['angled_max_deg'])), math.cos(math.radians(prm['angled_min_deg']))
    pf = [f for f in planar_faces(bush) if lo <= f['n'][0] <= hi and f['area'] >= 1.0]
    if not pf:
        raise WorkerError('BOARD_PLACE_BUSH', 'bush_part has no angled planar end face (outward normal 5-75 deg to the front axis); use x_rule wheel.',
                          {'angled_deg': [prm['angled_min_deg'], prm['angled_max_deg']]})
    groups: list[list[dict]] = []
    for f in sorted(pf, key=lambda q: -q['area']):
        for g in groups:
            if float(g[0]['n'] @ f['n']) > math.cos(math.radians(2.0)):
                g.append(f)
                break
        else:
            groups.append([f])
    g = max(groups, key=lambda q: sum(f['area'] for f in q))
    return g


_SI: dict[int, Any] = {}


def skin_hits(shape, p, d):
    """Ray hits [(distance, point, outward face normal)] along d (IntCurvesFace_ShapeIntersector, loaded once per shape)."""
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    from OCP.gp import gp_Lin, gp_Pnt, gp_Dir
    k = id(shape)
    if k not in _SI:
        si = IntCurvesFace_ShapeIntersector()
        si.Load(shape, 1e-7)
        _SI[k] = (shape, si)
    si = _SI[k][1]
    si.Perform(gp_Lin(gp_Pnt(*map(float, p)), gp_Dir(*map(float, d))), 1e-6, 1e9)
    out = []
    for i in range(1, si.NbPnt() + 1):
        n = np.asarray(L.face_normal_uv(si.Face(i), si.UParameter(i), si.VParameter(i)), float)
        out.append((float(si.WParameter(i)), np.array(si.Pnt(i).Coord()), n / (np.linalg.norm(n) + 1e-12)))
    return sorted(out, key=lambda h: h[0])


def mesh_hits(VT, p, d):
    """Ray hits [(distance, point, triangle normal)] on a triangle mesh (Moller-Trumbore, all triangles; the scan region keeps its outward order)."""
    V, T = VT
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    e1, e2 = b - a, c - a
    d = np.asarray(d, float)
    p = np.asarray(p, float)
    h = np.cross(d, e2)
    det = (e1 * h).sum(1)
    ok = np.abs(det) > 1e-12
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    sv = p - a
    u = (sv * h).sum(1) * inv
    q = np.cross(sv, e1)
    v = (q * d).sum(1) * inv
    t = (e2 * q).sum(1) * inv
    m = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0)
    nrm = np.cross(e1[m], e2[m])
    nrm /= np.linalg.norm(nrm, axis=1)[:, None] + 1e-12
    return sorted(((float(tt), p + tt * d, nn) for tt, nn in zip(t[m], nrm)), key=lambda x: x[0])


def ray_skin(sk, p, d):
    return mesh_hits(sk, p, d) if isinstance(sk, tuple) else skin_hits(sk, p, d)


def skin_xmax(sk):
    return float(sk[0][np.unique(sk[1])][:, 0].max()) if isinstance(sk, tuple) else float(ebox(sk)[3])


def exit_offsets(skins, pts, n, prm):
    """Signed offset along n from each point to the nearest OUTER skin crossing: the ray leaves the material (face normal . n > 0); downward faces
    (normal z < -0.7: the parting / bottom face of a closed skin) are not skin. Skins: B-rep solids and scan region meshes (V, T). None if no
    crossing within flush_ray_mm."""
    R = prm['flush_ray_mm']
    out = []
    for p in pts:
        best = None
        for sk in skins:
            for s, _q, fn in ray_skin(sk, p - R * n, n):
                if fn @ n > 0.05 and fn[2] > -0.7 and s <= 2 * R:
                    off = s - R
                    if best is None or abs(off) < abs(best):
                        best = off
        out.append(best)
    return out


def solve_bush_flush(skins, bush, t0, prm):
    faces = bush_faces(bush, prm)
    n = faces[0]['n']
    base = [p for f in faces for p in face_points(f['face'])]

    def f(tx):
        offs = exit_offsets(skins, [p + t0 + np.array([tx, 0, 0]) for p in base], n, prm)
        v = np.array([o for o in offs if o is not None], float)
        return v, len(base)

    # start: the face points' x on the front skin (first FRONT-facing crossing, normal x > 0.3, of a ray along -x from in front of the skins)
    xmax = max(skin_xmax(sk) for sk in skins) + 5.0
    d0 = []
    for p in base:
        q = p + t0
        h = [s for sk in skins for s, _q, fn in ray_skin(sk, (xmax, q[1], q[2]), (-1, 0, 0)) if fn[0] > 0.3]
        if h:
            d0.append(xmax - min(h) - q[0])
    if not d0:
        raise WorkerError('BOARD_PLACE_FLUSH', 'No front-facing skin in front of the bush end face at its height (top shell, floor_part or floor_region_path).',
                          {'samples': len(base)})
    tx, hist = float(np.median(d0)), []
    v, nb = f(tx)
    if len(v) < prm['min_flush_samples']:
        raise WorkerError('BOARD_PLACE_FLUSH', 'Too few bush end-face points find the outer skin along their normal (the skin is not near the bush).',
                          {'samples': nb, 'found': int(len(v)), 'ray_mm': prm['flush_ray_mm']})
    for _ in range(12):
        m = float(np.median(v))
        hist.append([round(tx, 4), round(m, 4)])
        if abs(m) < prm['flush_tol_mm']:
            break
        tx += m / max(n[0], 0.2)
        v, _nb = f(tx)
        if len(v) < prm['min_flush_samples']:
            raise WorkerError('BOARD_PLACE_FLUSH', 'The bush end face lost the outer skin while solving the flush position.', {'history': hist})
    else:
        raise WorkerError('BOARD_PLACE_FLUSH', 'The bush flush solve did not converge.', {'history': hist})
    return tx, {'faces': len(faces), 'normal': np.round(n, 4).tolist(), 'samples': nb, 'found': int(len(v)),
                'offset_median_mm': round(float(np.median(v)), 4), 'offset_p10_p90_mm': [round(float(np.percentile(v, 10)), 4), round(float(np.percentile(v, 90)), 4)],
                'history': hist}


def wheel_window(shell, plane_y, near_x, prm, region=None):
    """Window centre: the wheel region (area centroid, plan) if given, else an opening on the mirror line: stations (window_step_mm) over the shell
    length where a vertical ray from below the shell meets no surface while the outline continues on both sides. Of several openings the one
    nearest near_x (the placed wheel centre) is taken, or the longest when near_x is None."""
    if region is not None:
        c, lo, hi = region_centroid(*region)
        return {'source': 'wheel_region_path', 'centre_xy': np.round(c[:2], 4).tolist(), 'x_range': [round(lo[0], 3), round(hi[0], 3)]}
    b = L.bbox(shell)
    xs = np.arange(b[0], b[3] + 1e-9, prm['window_step_mm'])
    hit = [len(W.hits(shell, (x, plane_y, b[2] - 1.0), (0, 0, 1))) > 0 for x in xs]
    runs, run = [], None
    for i, h in enumerate(hit):
        if not h:
            run = [i, i] if run is None else [run[0], i]
        else:
            if run is not None and run[0] > 0:
                runs.append(run)
            run = None
    if not runs:
        return {'source': 'not found (no opening on the mirror line; give wheel_region_path or cut the window first)'}
    if near_x is None:
        best = max(runs, key=lambda r: r[1] - r[0])
    else:
        best = min(runs, key=lambda r: abs((xs[r[0]] + xs[r[1]]) / 2 - near_x))
    x0, x1 = xs[best[0]], xs[best[1]]
    return {'source': 'rays on the mirror line', 'centre_xy': [round(float((x0 + x1) / 2), 4), round(plane_y, 4)], 'x_range': [round(float(x0), 3), round(float(x1), 3)],
            'openings': len(runs)}


# ------------------------------------------------------------------ run
def run(req: dict[str, Any]) -> dict[str, Any]:
    L.require_ocp()
    prm = req['params']
    paths = [req['inputs'][k] for k in sorted((k for k in req['inputs'] if k.startswith('step_')), key=lambda s: int(s.split('_')[1]))]
    parts, table = P.load_parts(paths)
    pack = prm['pack_parts']
    seeds = prm.get('seed_switch_parts') or []
    need = [prm['shell_part'], prm['sensor_part'], prm['floor_datum_part'], prm['pcb_part'], *pack, *seeds, *(prm.get('plate_parts') or [])]
    for k in ('floor_part', 'bush_part', 'switch_part', 'switch_pcb_part'):
        if prm.get(k):
            need.append(prm[k])
    need += prm.get('wheel_parts') or []
    P.require(parts, sorted(set(need)), 'shell_part / pack_parts / datum parts')
    shell = W.one(parts[prm['shell_part']], prm['shell_part'])
    sb = L.bbox(shell)
    reasons: list[str] = []
    # mirror plane
    Vs, Ts = outward_mesh(shell, prm['shell_deflection_mm'])
    if prm.get('mirror_y') is not None:
        plane = {'plane_y_mm': float(prm['mirror_y']), 'plane_source': 'argument'}
    else:
        from cadmcp_brain.studio.mouse_seam_audit_worker import fit_mirror_plane
        fit = fit_mirror_plane(Vs, 1)
        plane = {'plane_y_mm': fit['plane_mm'], 'plane_source': 'fitted from the shell', 'fit_residual_mm': fit['residual_mm']}
    py = plane['plane_y_mm']
    # shell kind
    mid = ((sb[0] + sb[3]) / 2, py, (sb[2] + sb[5]) / 2)
    kind = prm['shell_kind'] if prm['shell_kind'] != 'auto' else ('solid_skin' if classify(shell, mid) else 'hollow')
    # floor
    if prm.get('floor_z') is not None:
        fz, fsrc = float(prm['floor_z']), 'argument'
    elif prm.get('floor_part'):
        fz, fsrc = float(ebox(parts[prm['floor_part']])[2]), f'min z of {prm["floor_part"]}'
    else:
        Vf, Tf = mesh_region(req['inputs']['floor_region'])
        fz, fsrc = float(np.percentile(Vf[np.unique(Tf)][:, 2], 1.0)), 'p1 z of floor_region_path'
    # translation
    sbx = ebox(parts[prm['sensor_part']])
    t = np.array([0.0, py - (sbx[1] + sbx[4]) / 2, fz - ebox(parts[prm['floor_datum_part']])[2]])
    tilt, pn = pcb_tilt(parts[prm['pcb_part']])
    if tilt > prm['level_tol_deg']:
        reasons.append(f'PCB_NOT_LEVEL: {prm["pcb_part"]} tilts {tilt:.3f} deg (> {prm["level_tol_deg"]}); the pose is a translation, level the pack frame first.')
    rule = prm['x_rule']
    if rule == 'auto':
        rule = 'bush_flush' if prm.get('bush_part') else 'wheel'
    wparts = prm.get('wheel_parts') or []
    region = mesh_region(req['inputs']['wheel_region']) if req['inputs'].get('wheel_region') else None
    flush = None
    wb = None
    if wparts:
        bbs = np.array([ebox(parts[w]) for w in wparts])
        wb = np.concatenate([bbs[:, :3].min(0), bbs[:, 3:].max(0)])
    if rule == 'bush_flush':
        skins = [shell] + ([W.one(parts[prm['floor_part']], prm['floor_part'])] if prm.get('floor_part') else []) +             ([mesh_region(req['inputs']['floor_region'])] if req['inputs'].get('floor_region') else [])
        tx, flush = solve_bush_flush(skins, W.one(parts[prm['bush_part']], prm['bush_part']), t, prm)
        t[0] = tx
    window = None
    if wb is not None:
        window = wheel_window(shell, py, None if rule == 'wheel' else (wb[0] + wb[3]) / 2 + t[0], prm, region)
    if rule == 'wheel':
        if wb is None or not window or 'centre_xy' not in window:
            raise WorkerError('BOARD_PLACE_WHEEL', 'x_rule wheel needs wheel_parts and a wheel window (wheel_region_path, or an opening in the shell).',
                              {'window': window})
        t[0] = window['centre_xy'][0] - (wb[0] + wb[3]) / 2
    wheel = None
    if wb is not None and window and 'centre_xy' in window:
        c = np.array([(wb[0] + wb[3]) / 2 + t[0], (wb[1] + wb[4]) / 2 + t[1]])
        wheel = {'wheel_centre_xy': np.round(c, 4).tolist(), 'window_centre_xy': window['centre_xy'],
                 'dx_mm': round(float(c[0] - window['centre_xy'][0]), 4), 'dy_mm': round(float(c[1] - window['centre_xy'][1]), 4)}
        if abs(wheel['dy_mm']) > prm['wheel_tol_mm']:
            reasons.append(f'WHEEL_OFF_WINDOW: the wheel centre is {wheel["dy_mm"]:+.3f} mm off the window centre laterally (> {prm["wheel_tol_mm"]}).')
        if 'x_range' in window and not (window['x_range'][0] <= c[0] <= window['x_range'][1]):
            reasons.append(f'WHEEL_OFF_WINDOW: the wheel centre x {c[0]:.3f} is outside the window {window["x_range"]}.')
    # switches under the click plates
    switches = []
    if seeds:
        D = W.board_datums(parts[prm['switch_pcb_part']], parts[prm['switch_part']], {'board_hole_dia': None, 'board_holes': None})
        master = W.one(parts[prm['switch_part']], prm['switch_part'])
        P0 = np.array(D['plunger_top'])
        regions = [mesh_region(req['inputs'][k]) for k in sorted(k for k in req['inputs'] if k.startswith('click_region_'))]
        for nm in seeds:
            R, tt, res = W.rigid_match(master, W.one(parts[nm], nm), nm, prm['seed_match_tol_mm'])
            top = R @ P0 + tt + t
            under = []
            for pn_ in prm.get('plate_parts') or []:
                pl = W.one(parts[pn_], pn_)
                if W.hits(pl, (top[0], top[1], L.bbox(pl)[2] - 1.0), (0, 0, 1)):
                    under.append(pn_)
            for i, (V, T) in enumerate(regions):
                if region_contains_xy(V, T, top[:2]):
                    under.append(f'click_region_{i}')
            h = W.hits(shell, top, (0, 0, 1))
            gap = None if not h else round(h[0][0] - (prm['wall_mm'] if kind == 'solid_skin' else 0.0), 4)
            inside = classify(shell, top)
            if kind == 'hollow' and inside:
                gap = -gap if gap is not None else None
            switches.append({'part': nm, 'plunger_top': np.round(top, 4).tolist(), 'under': under, 'tilt_deg': round(math.degrees(math.acos(max(-1, min(1, R[2, 2])))), 4),
                             'vertical_gap_to_ceiling_mm': gap, 'gap_reference': 'shell underside' if kind == 'hollow' else f'outer skin - wall_mm {prm["wall_mm"]}'})
            if len(under) != 1:
                reasons.append(f'SWITCH_NOT_UNDER_CLICK: {nm} plunger at {np.round(top[:2], 2).tolist()} is under {len(under)} click plates / regions (need 1).')
            if gap is None or gap < 0:
                reasons.append(f'SWITCH_IN_SHELL: {nm} plunger top has no room below the shell ceiling (gap {gap}).')
    # clearance of every pack part to the shell
    imp = implicit(Vs, Ts)
    from scipy.spatial import cKDTree
    if kind == 'solid_skin':
        # parting faces = downward faces (normal z < -0.7) of the closed skin: the open bottom toward the bottom plate, not a wall
        a, b_, c_ = Vs[Ts[:, 0]], Vs[Ts[:, 1]], Vs[Ts[:, 2]]
        nz = np.cross(b_ - a, c_ - a)
        nz = nz[:, 2] / (np.linalg.norm(nz, axis=1) + 1e-12)
        part = nz < -0.7
        tree = cKDTree(sub_samples(Vs, Ts[~part], 0.3))
        # underside height map: lowest shell z per plan cell; an outside point at or below it is under the top shell (bottom-plate territory)
        allp = tri_samples(Vs, Ts, 0.3)
        g = 0.5
        o = allp[:, :2].min(0)
        ij = np.floor((allp[:, :2] - o) / g).astype(int)
        zmin = np.full(ij.max(0) + 1, np.inf)
        np.minimum.at(zmin, (ij[:, 0], ij[:, 1]), allp[:, 2])

        def under(q):
            k = np.floor((q[:, :2] - o) / g).astype(int)
            ok = np.all((k >= 0) & (k < np.array(zmin.shape)), axis=1)
            z = np.full(len(q), -np.inf)
            z[ok] = zmin[k[ok, 0], k[ok, 1]]
            return q[:, 2] <= z + g
    zcut = sb[2] + prm['parting_band_mm']
    clear = {}
    through = set(prm.get('report_only_parts') or [])
    for nm in pack:
        V, T = outward_mesh(parts[nm], prm['deflection_mm'])
        pts = tri_samples(V, T, prm['sample_mm']) + t
        if kind == 'hollow':
            lo = pts[:, 2] < zcut                      # below the open rim of a hollow shell: bottom-plate territory
            q = pts[~lo]
            d = signed(imp, q, (Vs, Ts)) if len(q) else np.zeros(0)
            cl = d
        else:
            d = signed(imp, pts, (Vs, Ts))
            depth = tree.query(pts)[0]
            lo = (d >= 0) & under(pts)                # outside and under the top shell = bottom-plate territory
            q, d, depth = pts[~lo], d[~lo], depth[~lo]
            cl = np.where(d < 0, depth - prm['wall_mm'], -(np.abs(d) + prm['wall_mm']))
        if not len(q):
            clear[nm] = {'checked_points': 0, 'below_shell_points': int(lo.sum())}
            continue
        k = int(np.argmin(cl))
        clear[nm] = {'min_clearance_mm': round(float(cl[k]), 4), 'at': np.round(q[k], 3).tolist(), 'points_below_clearance': int((cl < prm['clearance_mm']).sum()),
                     'checked_points': int(len(q)), 'below_shell_points': int(lo.sum()), 'report_only': nm in through}
        if nm not in through and cl[k] < prm['clearance_mm']:
            reasons.append(f'NO_ROOM: {nm} min clearance {cl[k]:.3f} mm < {prm["clearance_mm"]} at {np.round(q[k], 2).tolist()} '
                           f'({clear[nm]["points_below_clearance"]} points).')
    out = Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    name = 'placed_pack.step' if not reasons else 'candidate_pack.step'
    W.write(out / name, [(nm, moved(L.solids(parts[nm])[0] if len(L.solids(parts[nm])) == 1 else parts[nm], t)) for nm in pack])
    sx = ebox(parts[prm['sensor_part']])
    report = {'shell_kind': kind, 'mirror': plane, 'floor': {'z_mm': round(fz, 4), 'source': fsrc}, 'x_rule': rule,
              'translation_mm': np.round(t, 4).tolist(),
              'residuals': {'sensor_y_to_plane_mm': round(float((sx[1] + sx[4]) / 2 + t[1] - py), 6),
                            'floor_datum_z_mm': round(float(ebox(parts[prm['floor_datum_part']])[2] + t[2] - fz), 6),
                            'pcb_tilt_deg': round(tilt, 4), 'pcb_normal': pn, 'bush_flush': flush, 'wheel': wheel},
              'wheel_window': window, 'switches': switches, 'clearance': clear, 'blocking_reasons': reasons, 'parts_loaded': table}
    return {'report': report, 'files': {'pack': name}}


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
