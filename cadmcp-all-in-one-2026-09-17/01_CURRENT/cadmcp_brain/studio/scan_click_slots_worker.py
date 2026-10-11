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

WORKER_VERSION = 'click_slots/7'
DEFAULTS = {'slot_width_mm': None, 'gap_width_mm': None, 'depth_mm': 2.0, 'window_depth_mm': None, 'window_length_mm': None, 'window_width_mm': None,
            'window_radius_mm': None, 'station_step_mm': 0.5, 'smooth_mm': 1.5, 'mirror_plane': None, 'abs_threshold_mm': 2.0, 'rel_threshold': 0.015,
            'cut_window': True, 'cut_gap': True, 'cut_perimeter': True,
            'trim_lip': True, 'lip_zone_frac': 0.7, 'lip_angle_deg': 30.0, 'ramp_mm': 3.0, 'ramp_lift_mm': 1.5, 'trim_gap_rear': True,
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
    pin, pout = Q + o1 * nrm, Q + o2 * nrm

    def E(P, z):
        return BRepBuilderAPI_MakeEdge(bsp(np.column_stack([P, z]))).Edge()
    zt = np.full(len(Q), ZT)
    ib, ob, it, ot = E(pin, zfl), E(pout, zfl), E(pin, zt), E(pout, zt)
    fs = [BRepFill.Face_s(ib, ob), BRepFill.Face_s(it, ot), BRepFill.Face_s(ib, it), BRepFill.Face_s(ob, ot)]
    for k in (0, -1):
        q = [gp_Pnt(*map(float, pin[k]), float(zfl[k])), gp_Pnt(*map(float, pout[k]), float(zfl[k])), gp_Pnt(*map(float, pout[k]), ZT), gp_Pnt(*map(float, pin[k]), ZT)]
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
        keep = ~off
        if keep.any() and off.any():
            # longest contiguous run of kept stations (the open path keeps its rear middle)
            idx = np.flatnonzero(np.diff(np.r_[0, keep.astype(int), 0]))
            runs = list(zip(idx[::2], idx[1::2]))
            a, b = max(runs, key=lambda r: r[1] - r[0])
            if b - a >= 10:
                trim_log['perimeter_lip'] = {'stations_before': int(len(Pp)), 'stations_after': int(b - a), 'removed_front_mm': float(step * (len(Pp) - (b - a))),
                                             'ends_xy': [Pp[a].tolist(), Pp[b - 1].tolist()],
                                             'rule': 'front run of the path (outward normal > lip_angle_deg forward, front lip_zone_frac of the x range) is not cut'}
                Pp = Pp[a:b]
    if Pp is not None and gaps and p['trim_gap_rear']:
        # whole_v1 rule: the centre gap starts at the perimeter slot, never behind it
        so = 1.0 if per.get('slot_side', 'left') == 'left' else -1.0
        Cl = Pp + min(0.1, 0.25 * W) * so * left_normal(Pp)          # just inside the slot at its panel-side wall: no end cap left
        out = []
        for k, g in enumerate(gaps):
            Q, _ = resample(g, step / 2)
            dist = seg_dist(Q, Cl)
            cut = None
            for end in (0, 1):
                order = np.arange(len(Q)) if end == 0 else np.arange(len(Q))[::-1]
                half = order[:max(2, len(Q) // 3)]
                j = half[np.argmin(dist[half])]
                if dist[j] <= W and j != order[0]:
                    cut = (end, int(j))
                    Q = Q[j:] if end == 0 else Q[:j + 1]
                    dist = dist[j:] if end == 0 else dist[:j + 1]
                    trim_log.setdefault('centre_gap', []).append({'segment': k, 'end': 'start' if end == 0 else 'end', 'new_end_xy': (Q[0] if end == 0 else Q[-1]).tolist()})
            out.append(Q)
            del cut
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
        zfl_p = zs - DEPTH
        if trim_log.get('perimeter_lip'):
            # open ends run out: the floor rises linearly to above the surface over ramp_mm (no end cap faces at the lip corners)
            nr_ = max(2, int(round(float(p['ramp_mm']) / step)))
            ramp = np.linspace(1.0, 0.0, nr_)
            zfl_p[:nr_] = zfl_p[:nr_] + ramp * (DEPTH + float(p['ramp_lift_mm']))
            zfl_p[-nr_:] = zfl_p[-nr_:] + ramp[::-1] * (DEPTH + float(p['ramp_lift_mm']))
        per_floor = (Pp, zfl_p)
        from cadmcp_brain.studio.scan_click_grooves_worker import outline_roughness
        rough = outline_roughness(Pp)
        c, fe = band_cutter(Pp, nrm, o1, o2, zfl_p, ZT)
        cutters.append(c)
        info.append({'tag': 'perimeter', 'length_mm': float(np.linalg.norm(np.diff(Pp, axis=0), axis=1).sum()), 'width_mm': W, 'stations': int(len(Pp)),
                     'floor_z_range': [float(zfl_p.min()), float(zfl_p.max())], 'free_edges': fe, 'Q': Pp, 'nrm': nrm, 'o': (o1, o2), 'zfl': zfl_p})
    if p['cut_gap']:
        for k, g in enumerate(gaps):
            Q, glen = resample(g, step)
            if glen < 0.5:
                continue
            nrm = left_normal(Q)
            zs = fill_nan(body.top_z(Q))
            if zs is None:
                warnings.append(f'centre gap segment {k} is not over the shell; skipped.')
                continue
            zs = smooth(zs, nsm)
            zfl = zs - DEPTH
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
            c, fe = band_cutter(Q, nrm, -GW / 2, GW / 2, zfl, ZT)
            cutters.append(c)
            info.append({'tag': f'centre_gap_{k}', 'length_mm': glen, 'width_mm': GW, 'stations': int(len(Q)), 'free_edges': fe,
                         'floor_z_range': [float(zfl.min()), float(zfl.max())], 'Q': Q, 'nrm': nrm, 'o': (-GW / 2, GW / 2), 'zfl': zfl})
    if not cutters:
        raise WorkerError('CLICK_SLOTS_NOTHING', 'Nothing to cut (no perimeter, gap or window in the layout, or all disabled).')
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    from OCP.TopTools import TopTools_ListOfShape
    from OCP.TopoDS import TopoDS
    tools = TopTools_ListOfShape()
    for c in cutters:
        tools.Append(c)
    args = TopTools_ListOfShape()
    args.Append(solid)
    op = BRepAlgoAPI_Cut()
    op.SetArguments(args)
    op.SetTools(tools)
    op.SetRunParallel(True)
    op.Build()
    if not op.IsDone():
        raise WorkerError('CLICK_SLOTS_BOOLEAN', 'The boolean cut failed.')
    sols = cb.solids(op.Shape())
    vols = sorted([cb.volume(s) for s in sols], reverse=True)
    so = max(sols, key=cb.volume)
    sfx = ShapeFix_Solid(so)
    sfx.Perform()
    so = TopoDS.Solid_s(sfx.Solid())
    u_ = ShapeUpgrade_UnifySameDomain(so, True, True, False)
    u_.Build()
    so2 = cb.solids(u_.Shape())
    if so2 and cb.is_valid(so2[0]):
        so = so2[0]
    out = Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    cb.write_step(so, out / 'slotted_shell.step')
    cb.write_step(cb.compound(cutters), out / 'slot_cutters.step')
    back = cb.read_step(out / 'slotted_shell.step')
    bs = cb.solids(back)
    res_body = Body(bs[0]) if bs else None
    # measurements: width across the band at floor + 0.4 mm, depth = surface - first floor hit at the band centre
    meas = {}
    for it in info:
        Q, nrm, (o1, o2), zfl = it.pop('Q'), it.pop('nrm'), it.pop('o'), it.pop('zfl')
        ks = np.linspace(len(Q) * 0.1, len(Q) * 0.9, 9).astype(int)
        wds, dps = [], []
        for k in ks:
            wds.append(_width(bs[0], Q[k], nrm[k], o1, o2, zfl[k] + 0.4) if bs else np.nan)
            mid = Q[k] + 0.5 * (o1 + o2) * nrm[k]
            zt = res_body.top_z(mid[None])[0] if res_body else np.nan
            zs0 = body.top_z((mid + (o2 - o1) * 1.5 * nrm[k])[None])[0]
            dps.append(zs0 - zt if np.isfinite(zt) and np.isfinite(zs0) else np.nan)
        meas[it['tag']] = {'width_mm_median': _nanmed(wds), 'width_mm_range': _nanrange(wds), 'floor_hit_below_neighbour_surface_mm_median': _nanmed(dps)}
    v0, v1 = cb.volume(solid), (cb.volume(bs[0]) if bs else 0.0)
    quality = {'perimeter_roughness': rough if Pp is not None else None, 'roughness_max_dev_mm': float(p['roughness_max_dev_mm']),
               'max_curvature_sign_changes': max(int(p['max_curvature_sign_changes']), int((per or {}).get('allowed_curvature_sign_changes') or 0)), 'window_gap': (wlog or {}).get('gap_alignment')}
    return {'worker': WORKER_VERSION, 'quality': quality, 'warnings': warnings, 'symmetry': sym_log, 'trim': trim_log, 'spec': {'slot_width_mm': W, 'gap_width_mm': GW, 'depth_mm': DEPTH, 'window_depth_mm': WDEPTH},
            'cutters': info, 'window': wlog, 'measured': meas,
            'result': {'solids_after_cut': len(sols), 'piece_volumes_mm3': vols[:5], 'valid': bool(bs and cb.is_valid(bs[0])), 'solids_in_step': len(bs),
                       'faces': len(cb.faces(bs[0])) if bs else 0, 'faces_below_1mm2': int(sum(cb.area(f) < 1.0 for f in cb.faces(bs[0]))) if bs else 0,
                       'faces_below_0p05mm2': int(sum(cb.area(f) < 0.05 for f in cb.faces(bs[0]))) if bs else 0, 'volume_before_mm3': v0, 'volume_after_mm3': v1, 'removed_mm3': v0 - v1},
            'files': {'step': 'slotted_shell.step', 'cutters': 'slot_cutters.step'}, 'params_used': p}


def _width(shape, q, nrm, o1, o2, z):
    from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    c = q + 0.5 * (o1 + o2) * nrm
    it = BRepIntCurveSurface_Inter()
    it.Init(shape, gp_Lin(gp_Pnt(float(c[0]), float(c[1]), float(z)), gp_Dir(float(nrm[0]), float(nrm[1]), 0.0)), 1e-7)
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
