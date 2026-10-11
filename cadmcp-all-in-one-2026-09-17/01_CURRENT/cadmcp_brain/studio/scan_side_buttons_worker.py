"""Side-button pads + surrounding groove on a closed mouse top shell. SUBPROCESS WORKER (server python: numpy, scipy, OCP).

Run as:  <server python> -I scan_side_buttons_worker.py request.json      (result = last stdout line, JSON)

Method (generic: no mouse-specific constants, never mirrored, any number of flanks / buttons):
  * proud height h of every scan vertex above the B-rep skin (dense samples of the shell tessellation, nearest sample + its plane);
  * candidates = connected components of the side-button labels (names side_button* / sidebutton* / B1..B4) or, without labels, of the
    flank triangles whose vertices all lie > top_threshold_mm above the skin (|n_z| < flank_max_nz); components below min_area_mm2 dropped;
  * per button: push direction d = mean skin normal, plane frame (u horizontal, v up); top points = vertices with h > top_threshold_mm;
    outline = convex hull of the top points, simplified (vertices closer than outline_tol_mm to their chord removed, turns below
    min_turn_deg merged), straight edges re-fitted to the hull (total least squares), corners filleted (corner_radius_mm on corners
    >= 30 deg, tangent blend arcs on mild turns), one periodic B-spline edge through the rounded outline;
  * top = quadratic height field fitted to the top points (confidence high) or skin + default proud (v6-style default, REVIEW);
  * groove = outline offset by groove_width_mm, floor = skin (ray hits along -d) - groove_depth_mm; cut; pad = outline prism from
    floor - embed_mm to the top, fused. Crisp edges, no fillets on the pad.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Any

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from cadmcp_brain.studio.scan_cad_common import WorkerError, worker_main
from cadmcp_brain.studio import cad_brep_lib as L

WORKER_VERSION = 'scan_side_buttons/1'
DEFAULTS = {'groove_width_mm': 0.4, 'groove_depth_mm': 1.5, 'corner_radius_mm': 1.0, 'min_corner_radius_mm': 0.5, 'proud_mm': None,
            'default_proud_mm': 1.0, 'top_threshold_mm': 0.35, 'outline_tol_mm': 0.35, 'min_turn_deg': 8.0, 'max_per_flank': 2,
            'min_area_mm2': 15.0, 'max_area_mm2': 600.0, 'min_top_points': 40, 'fit_res_max_mm': 0.5, 'hull_dev_max_mm': 1.0,
            'proud_min_mm': 0.2, 'proud_max_mm': 3.0, 'embed_mm': 0.3, 'flank_max_nz': 0.6, 'mesh_max_dist_mm': 1.0,
            'skin_max_dev_mm': 0.5, 'min_button_gap_mm': 0.8, 'region_confidence': None, 'handedness': None}
BUTTON_KEYS = ('side_button', 'sidebutton', 'thumb_button')
SHORT = ('B1', 'B2', 'B3', 'B4')


def is_button_name(name: str) -> bool:
    return name in SHORT or any(k in name.lower() for k in BUTTON_KEYS)


# ------------------------------------------------------------------ inputs
def read_labels(path: Path, n_tri: int) -> dict[str, np.ndarray]:
    """.npz (face_labels + codes 'name=code') or .json {name: [ids]} / {'regions': {name: {'face_ids': ids}}} -> button labels only."""
    if path.suffix.lower() == '.npz':
        try:
            z = np.load(path, allow_pickle=False)
            fl, codes = z['face_labels'], [str(c) for c in z['codes']]
        except (OSError, ValueError, KeyError) as exc:
            raise WorkerError('SIDE_BUTTONS_LABELS', 'An .npz label file needs the arrays face_labels and codes ("name=code").', {'error': type(exc).__name__}) from exc
        if len(fl) != n_tri:
            raise WorkerError('SIDE_BUTTONS_LABELS', 'face_labels has a different length than the mesh has triangles.', {'labels': int(len(fl)), 'triangles': n_tri})
        d = {}
        for c in codes:
            name, _, code = c.rpartition('=')
            if name and code.lstrip('-').isdigit():
                d[name] = np.flatnonzero(fl == int(code))
    else:
        try:
            d = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise WorkerError('SIDE_BUTTONS_LABELS', 'The label file is not valid JSON.', {'error': type(exc).__name__}) from exc
        if isinstance(d, dict) and isinstance(d.get('regions'), dict):
            d = d['regions']
        if not isinstance(d, dict):
            raise WorkerError('SIDE_BUTTONS_LABELS', 'The label file must be {name: [triangle ids]}.')
    out = {}
    for name, ids in d.items():
        if not is_button_name(str(name)):
            continue
        if isinstance(ids, dict):
            ids = ids.get('face_ids', [])
        try:
            a = np.asarray(ids, dtype=np.int64).ravel()
        except (TypeError, ValueError) as exc:
            raise WorkerError('SIDE_BUTTONS_LABELS', 'Triangle ids must be integers.', {'name': name}) from exc
        if len(a) and (a.min() < 0 or a.max() >= n_tri):
            raise WorkerError('SIDE_BUTTONS_LABELS', 'Triangle ids are out of range for the mesh.', {'name': name, 'triangles': n_tri})
        if len(a):
            out[str(name)] = a
    return out


def skin_samples(solid, step: float = 0.6):
    """Dense points + outward normals on the shell (tessellation triangles subdivided to <= step)."""
    m = L.tessellate(solid, 0.02, 0.1)
    V, T = m['V'], m['T']
    A, B, C = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    n = np.cross(B - A, C - A)
    nn = np.linalg.norm(n, axis=1)
    ok = nn > 1e-12
    A, B, C, n, nn = A[ok], B[ok], C[ok], n[ok], nn[ok]
    n = n / nn[:, None]
    emax = np.max(np.c_[np.linalg.norm(B - A, axis=1), np.linalg.norm(C - B, axis=1), np.linalg.norm(A - C, axis=1)], axis=1)
    k = np.clip(np.ceil(emax / step), 1, 80).astype(int)
    P, N = [], []
    for kk in np.unique(k):
        sel = k == kk
        ij = np.array([(i, j) for i in range(kk + 1) for j in range(kk + 1 - i)], float) / kk
        a, b, c = A[sel], B[sel], C[sel]
        P.append((a[:, None, :] + ij[None, :, :1] * (b - a)[:, None, :] + ij[None, :, 1:] * (c - a)[:, None, :]).reshape(-1, 3))
        N.append(np.repeat(n[sel], len(ij), axis=0))
    return np.vstack(P), np.vstack(N)


class Rays:
    def __init__(self, shape):
        from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
        self.si = IntCurvesFace_ShapeIntersector()
        self.si.Load(shape, 1e-7)

    def first(self, p, d, tmax: float) -> float:
        from OCP.gp import gp_Lin, gp_Pnt, gp_Dir
        self.si.Perform(gp_Lin(gp_Pnt(*map(float, p)), gp_Dir(*map(float, d))), 0.0, float(tmax))
        if not self.si.IsDone() or self.si.NbPnt() == 0:
            return float('nan')
        return min(self.si.WParameter(i) for i in range(1, self.si.NbPnt() + 1))


def line_hits(shape, p, d) -> np.ndarray:
    from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    it = BRepIntCurveSurface_Inter()
    it.Init(shape, gp_Lin(gp_Pnt(*map(float, p)), gp_Dir(*map(float, d))), 1e-7)
    ts = []
    while it.More():
        ts.append(it.W())
        it.Next()
    return np.sort(np.asarray(ts, float))


def components(F: np.ndarray, ids: np.ndarray) -> list[np.ndarray]:
    """Connected triangle sets (shared vertices) of the triangle subset ids."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    if not len(ids):
        return []
    t = F[ids]
    nv = int(F.max()) + 1
    rows = np.r_[t[:, 0], t[:, 1], t[:, 2]]
    cols = np.r_[t[:, 1], t[:, 2], t[:, 0]]
    g = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(nv, nv))
    _, lab = connected_components(g, directed=False)
    tl = lab[t[:, 0]]
    return [ids[tl == c] for c in np.unique(tl)]


# ------------------------------------------------------------------ outline
def _poly_area(P):
    x, y = P[:, 0], P[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _seg_dist(p, a, b):
    ab = b - a
    t = np.clip(np.dot(p - a, ab) / max(np.dot(ab, ab), 1e-18), 0, 1)
    return float(np.linalg.norm(p - (a + t * ab)))


def _turns(P):
    d = np.roll(P, -1, axis=0) - P
    d /= np.linalg.norm(d, axis=1)[:, None] + 1e-18
    dp = np.roll(d, 1, axis=0)
    cr = dp[:, 0] * d[:, 1] - dp[:, 1] * d[:, 0]
    return np.arctan2(cr, np.einsum('ij,ij->i', dp, d))      # signed turn at each vertex (CCW > 0)


def regular_outline(Q: np.ndarray, tol: float, min_turn_deg: float):
    """Convex hull of Q -> simplified convex polygon with straight edges re-fitted to the hull (CCW). Returns (poly, hull)."""
    from scipy.spatial import ConvexHull
    H = Q[ConvexHull(Q).vertices]
    if _poly_area(H) < 0:
        H = H[::-1]
    idx = list(range(len(H)))
    while len(idx) > 4:
        n = len(idx)
        dist = [_seg_dist(H[idx[i]], H[idx[i - 1]], H[idx[(i + 1) % n]]) for i in range(n)]
        i = int(np.argmin(dist))
        if dist[i] > tol:
            break
        idx.pop(i)
    while len(idx) > 4:
        tr = np.degrees(np.abs(_turns(H[idx])))
        i = int(np.argmin(tr))
        if tr[i] >= min_turn_deg:
            break
        idx.pop(i)
    n = len(idx)
    lines = []
    for j in range(n):
        a, b = idx[j], idx[(j + 1) % n]
        seg = [H[a]]
        k = a
        while k != b:
            k = (k + 1) % len(H)
            seg.append(H[k])
        S = np.array(seg)
        dense = np.vstack([np.linspace(S[i], S[i + 1], max(2, int(np.linalg.norm(S[i + 1] - S[i]) / 0.1) + 1))[:-1] for i in range(len(S) - 1)] + [S[-1:]])
        c = dense.mean(0)
        _, _, vt = np.linalg.svd(dense - c)
        lines.append((c, vt[0]))
    P = []
    for j in range(n):
        (c1, t1), (c2, t2) = lines[j - 1], lines[j]
        A = np.c_[t1, -t2]
        if abs(np.linalg.det(A)) < 1e-6:
            P.append(H[idx[j]])
            continue
        s = np.linalg.solve(A, c2 - c1)
        P.append(c1 + s[0] * t1)
    P = np.array(P)
    tr = _turns(P)
    if np.any(tr <= 0) or np.any(np.linalg.norm(P - H[idx], axis=1) > 3 * tol + 1.0):
        P = H[idx]                                            # refit broke convexity: keep the simplified hull
    return P, H


def fillet_plan(P: np.ndarray, corner_r: float):
    """Per vertex of the convex CCW polygon P: radius, centre, inward normals of the two edges. Corners >= 30 deg get corner_r, mild turns a
    tangent blend (tangent length 0.4 x the shorter edge); tangent lengths limited to the edges."""
    n = len(P)
    d = np.roll(P, -1, axis=0) - P
    ln = np.linalg.norm(d, axis=1)
    d /= ln[:, None]
    nin = np.c_[-d[:, 1], d[:, 0]]                            # inward (left) normal of edge j = P[j] -> P[j+1]
    th = np.abs(_turns(P))                                    # turn at vertex j between edge j-1 and j
    tl = np.zeros(n)
    for j in range(n):
        tq = np.tan(th[j] / 2)
        lmin = min(ln[j - 1], ln[j])
        tl[j] = corner_r * tq if th[j] >= np.radians(30) else 0.4 * lmin
    for _ in range(3):
        for j in range(n):
            s = tl[j] + tl[(j + 1) % n]
            if s > 0.98 * ln[j]:
                f = 0.98 * ln[j] / s
                tl[j] *= f
                tl[(j + 1) % n] *= f
    r = tl / np.tan(th / 2)
    out = []
    for j in range(n):
        n1, n2 = nin[j - 1], nin[j]
        bis = n1 + n2
        bis /= np.linalg.norm(bis)
        c = P[j] + bis * r[j] / np.cos(th[j] / 2)
        out.append({'r': float(r[j]), 'c': c, 'n1': n1, 'n2': n2, 'turn_deg': float(np.degrees(th[j]))})
    return out


def rounded(plan, w: float = 0.0, ds: float = 0.25) -> np.ndarray:
    """Dense closed CCW outline (no repeated point) of the filleted polygon, offset outward by w."""
    pts = []
    n = len(plan)
    for j in range(n):
        f, g = plan[j], plan[(j + 1) % n]
        R = f['r'] + w
        a0 = np.arctan2(*(-f['n1'])[::-1])
        a1 = np.arctan2(*(-f['n2'])[::-1])
        sw = (a1 - a0) % (2 * np.pi)
        k = max(2, int(np.ceil(sw * R / (0.6 * ds))))
        for t in np.linspace(0, sw, k + 1)[:-1]:
            pts.append(f['c'] + R * np.array([np.cos(a0 + t), np.sin(a0 + t)]))
        e0 = f['c'] - R * f['n2']
        e1 = g['c'] - (g['r'] + w) * g['n1']
        m = max(1, int(np.ceil(np.linalg.norm(e1 - e0) / ds)))
        for t in np.linspace(0, 1, m + 1)[:-1]:
            pts.append(e0 + t * (e1 - e0))
    P = np.array(pts)
    keep = np.r_[True, np.linalg.norm(np.diff(P, axis=0), axis=1) > 1e-6]
    return P[keep]


def poly2(Q, s):
    A = np.c_[np.ones(len(Q)), Q[:, 0], Q[:, 1], Q[:, 0] ** 2, Q[:, 0] * Q[:, 1], Q[:, 1] ** 2]
    c = np.linalg.lstsq(A, s, rcond=None)[0]
    return c


def poly2_eval(c, Q):
    Q = np.atleast_2d(Q)
    return np.c_[np.ones(len(Q)), Q[:, 0], Q[:, 1], Q[:, 0] ** 2, Q[:, 0] * Q[:, 1], Q[:, 1] ** 2] @ c


def inside(poly, Q):
    x, y = Q[:, 0], Q[:, 1]
    res = np.zeros(len(Q), bool)
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        hit = ((yi > y) != (yj > y)) & (x < (xj - xi) * (y - yi) / (yj - yi + 1e-300) + xi)
        res ^= hit
        j = i
    return res


# ------------------------------------------------------------------ B-rep pieces
class Frame:
    def __init__(self, O, d):
        self.O, self.d = O, d
        ez = np.array([0.0, 0.0, 1.0])
        u = np.cross(ez, d) if abs(d[2]) < 0.95 else np.cross(d, np.array([0.0, 1.0, 0.0]))
        u /= np.linalg.norm(u)
        if u[0] < 0:
            u = -u
        v = np.cross(d, u)
        self.u, self.v = u, v

    def to2(self, P):
        R = P - self.O
        return np.c_[R @ self.u, R @ self.v], R @ self.d

    def to3(self, Q, s):
        Q = np.atleast_2d(Q)
        s = np.broadcast_to(np.asarray(s, float), (len(Q),))
        return self.O + Q[:, :1] * self.u + Q[:, 1:2] * self.v + s[:, None] * self.d


def grid_surface(fr: Frame, gu, gv, S):
    from OCP.TColgp import TColgp_Array2OfPnt
    from OCP.GeomAPI import GeomAPI_PointsToBSplineSurface
    from OCP.GeomAbs import GeomAbs_C2
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Pnt
    a = TColgp_Array2OfPnt(1, len(gu), 1, len(gv))
    for i, uu in enumerate(gu):
        for j, vv in enumerate(gv):
            p = fr.to3(np.array([[uu, vv]]), S[i, j])[0]
            a.SetValue(i + 1, j + 1, gp_Pnt(*map(float, p)))
    srf = GeomAPI_PointsToBSplineSurface(a, 3, 3, GeomAbs_C2, 1e-4).Surface()
    return BRepBuilderAPI_MakeFace(srf, 1e-6).Face()


def outline_prism(fr: Frame, Q2, s_hi, s_lo):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.GeomAPI import GeomAPI_ProjectPointOnCurve
    from OCP.gp import gp_Pnt, gp_Vec
    P3 = fr.to3(Q2, s_hi)
    cv = L.interp_closed(P3)
    from scipy.spatial import cKDTree
    Pc = np.vstack([P3, P3[:1]])
    dense = (Pc[:-1, None, :] + np.linspace(0, 1, 16, endpoint=False)[None, :, None] * (Pc[1:] - Pc[:-1])[:, None, :]).reshape(-1, 3)
    S = np.array([cv.Value(float(t)).Coord() for t in np.linspace(0, 1, 1200, endpoint=False)])
    dev = float(cKDTree(dense).query(S)[0].max())
    w = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(cv).Edge()).Wire()
    face = BRepBuilderAPI_MakeFace(w, True).Face()
    vec = -(s_hi - s_lo) * fr.d
    return BRepPrimAPI_MakePrism(face, gp_Vec(*map(float, vec))).Shape(), dev


def split_pick(prism, tools, probe):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Splitter
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_IN
    from OCP.TopTools import TopTools_ListOfShape
    from OCP.gp import gp_Pnt
    sp = BRepAlgoAPI_Splitter()
    a = TopTools_ListOfShape()
    a.Append(prism)
    t = TopTools_ListOfShape()
    for f in tools:
        t.Append(f)
    sp.SetArguments(a)
    sp.SetTools(t)
    sp.Build()
    if not sp.IsDone():
        return None
    for s in L.solids(sp.Shape()):
        if BRepClass3d_SolidClassifier(s, gp_Pnt(*map(float, probe)), 1e-6).State() == TopAbs_IN:
            return s
    return None


# ------------------------------------------------------------------ main
def run(req: dict[str, Any]) -> dict[str, Any]:
    p = {**DEFAULTS, **(req.get('params') or {})}
    inp = req['inputs']
    out = Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    warnings: list[dict[str, Any]] = []
    from scipy.spatial import cKDTree
    shell = L.one_solid(Path(inp['shell']), 'SIDE_BUTTONS_SHELL_SOLIDS')
    if not L.is_valid(shell):
        raise WorkerError('SIDE_BUTTONS_SHELL_INVALID', 'The input shell solid is not a valid B-rep.')
    V, F = L.read_stl(Path(inp['mesh']))
    SP, SN = skin_samples(shell)
    kd = cKDTree(SP)
    dd, ii = kd.query(V)
    h = np.einsum('ij,ij->i', V - SP[ii], SN[ii])
    med = float(np.median(dd))
    if med > float(p['mesh_max_dist_mm']):
        raise WorkerError('SIDE_BUTTONS_FRAME', 'The scan mesh is not in the frame of the shell (median distance above mesh_max_dist_mm).',
                          {'median_distance_mm': med, 'mesh_max_dist_mm': p['mesh_max_dist_mm']})
    tri_area = 0.5 * np.linalg.norm(np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]), axis=1)
    thr = float(p['top_threshold_mm'])
    # ---- candidates
    cands = []
    labels = read_labels(Path(inp['labels']), len(F)) if inp.get('labels') else {}
    source = 'labels' if labels else 'geometry'
    if labels:
        for name, ids in sorted(labels.items()):
            comps = sorted(components(F, ids), key=lambda c: -tri_area[c].sum())
            big = [c for c in comps if tri_area[c].sum() >= float(p['min_area_mm2'])]
            if len(comps) > 1:
                warnings.append({'code': 'SIDE_BUTTON_LABEL_SPLIT', 'label': name, 'pieces': len(comps), 'kept': len(big[:1]),
                                 'message': 'The label has several disconnected pieces; the largest is used.'})
            if not big:
                warnings.append({'code': 'SIDE_BUTTON_LABEL_TOO_SMALL', 'label': name, 'area_mm2': float(tri_area[ids].sum()),
                                 'message': 'The label is smaller than min_area_mm2; ignored.'})
                continue
            cands.append({'name': name, 'tris': big[0]})
    else:
        tn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
        tn /= np.linalg.norm(tn, axis=1)[:, None] + 1e-18
        sel = np.flatnonzero((h[F].min(axis=1) > thr) & (np.abs(tn[:, 2]) < float(p['flank_max_nz'])) & (dd[F].max(axis=1) < 4.0))
        k = 0
        for c in sorted(components(F, sel), key=lambda c: -tri_area[c].sum()):
            a = tri_area[c].sum()
            if float(p['min_area_mm2']) <= a <= float(p['max_area_mm2']):
                k += 1
                cands.append({'name': f'detected_{k}', 'tris': c})
        warnings.append({'code': 'SIDE_BUTTONS_FROM_GEOMETRY', 'found': len(cands),
                         'message': 'No side-button labels: pads detected as raised flank patches (confidence at most medium).'})
    rconf = p.get('region_confidence') or {}
    buttons = []
    for cd in cands:
        vid = np.unique(F[cd['tris']])
        top = vid[h[vid] > thr]
        top_src = 'top_points'
        if len(top) < int(p['min_top_points']):
            top, top_src = vid, 'all_label_points'
        d = SN[ii[top]].mean(0)
        d /= np.linalg.norm(d)
        fr = Frame(V[top].mean(0), d)
        Q, s = fr.to2(V[top])
        Qall, _ = fr.to2(V[vid])
        poly, hull = regular_outline(Q, float(p['outline_tol_mm']), float(p['min_turn_deg']))
        plan = fillet_plan(poly, float(p['corner_radius_mm']))
        O2 = rounded(plan)
        H = np.vstack([np.linspace(hull[i], hull[(i + 1) % len(hull)], 12, endpoint=False) for i in range(len(hull))])
        dev_h = float(max(np.min(np.linalg.norm(O2[:, None] - H[None], axis=2), axis=1).max(), np.min(np.linalg.norm(H[:, None] - O2[None], axis=2), axis=1).max()))
        cpoly2 = poly2(Q, s)
        res = s - poly2_eval(cpoly2, Q)
        flank = '+y' if d[1] > 0.5 else '-y' if d[1] < -0.5 else 'other'
        reasons = []
        if source != 'labels':
            reasons.append('geometry_detection')
        rc = rconf.get(cd['name']) if isinstance(rconf, dict) else None
        if rc is not None and rc != 'high':
            reasons.append(f'region_confidence_{rc}')
        if top_src != 'top_points':
            reasons.append('few_top_points')
        if np.percentile(np.abs(res), 95) > float(p['fit_res_max_mm']):
            reasons.append('top_fit_residual')
        if dev_h > float(p['hull_dev_max_mm']):
            reasons.append('outline_far_from_hull')
        sharp = [c['r'] for c in plan if c['turn_deg'] >= 30]
        buttons.append({'name': cd['name'], 'source': source, 'flank': flank, 'frame': fr, 'Q': Q, 's': s, 'poly': poly, 'plan': plan, 'O2': O2,
                        'hull_dev_mm': dev_h, 'top_poly': cpoly2, 'fit_res_p95_mm': float(np.percentile(np.abs(res), 95)),
                        'n_top': int(len(top)), 'top_source': top_src, 'region_confidence': rc, 'reasons': reasons,
                        'label_area_mm2': float(tri_area[cd['tris']].sum()), 'min_sharp_corner_r': float(min(sharp)) if sharp else None,
                        'label_extent_2d': [Qall.min(0).tolist(), Qall.max(0).tolist()]})
    flanks: dict[str, int] = {}
    for b in buttons:
        flanks[b['flank']] = flanks.get(b['flank'], 0) + 1
    blockers: list[dict[str, Any]] = []
    if any(n > int(p['max_per_flank']) for n in flanks.values()):
        blockers.append({'code': 'SIDE_BUTTONS_TOO_MANY', 'per_flank': flanks, 'max_per_flank': int(p['max_per_flank'])})
    if any(b['flank'] == 'other' for b in buttons):
        blockers.append({'code': 'SIDE_BUTTON_NOT_ON_FLANK', 'names': [b['name'] for b in buttons if b['flank'] == 'other']})
    # ---- per-button geometry
    rays = Rays(shell)
    W, DEP, EMB = float(p['groove_width_mm']), float(p['groove_depth_mm']), float(p['embed_mm'])
    grooved = W > 0 and DEP > 0
    cutters, pads = [], []
    for b in buttons:
        fr = b['frame']
        Og = rounded(b['plan'], W) if grooved else b['O2']
        lo, hi = Og.min(0) - 2.0, Og.max(0) + 2.0
        gu = np.linspace(lo[0], hi[0], int(np.clip(np.ceil((hi[0] - lo[0]) / 0.8) + 1, 9, 61)))
        gv = np.linspace(lo[1], hi[1], int(np.clip(np.ceil((hi[1] - lo[1]) / 0.8) + 1, 7, 41)))
        GQ = np.array([[x, y] for x in gu for y in gv])
        s_far = float(max(b['s'].max(), 0.0) + 6.0)
        hits = np.array([rays.first(q, -fr.d, s_far + 15.0) for q in fr.to3(GQ, s_far)])
        sk = s_far - hits
        ok = np.isfinite(sk) & (np.abs(sk) < 5.0)
        ins = inside(Og, GQ)
        b['skin_rays'] = {'grid': [len(gu), len(gv)], 'missed_inside': int((ins & ~ok).sum())}
        if ok.sum() < 6:
            blockers.append({'code': 'SIDE_BUTTON_SKIN_NOT_FOUND', 'name': b['name']})
            b['geometry'] = None
            continue
        cs = poly2(GQ[ok], sk[ok])
        sres = np.abs(sk - poly2_eval(cs, GQ))
        b['skin_quadratic_dev_mm'] = float(np.nanmax(np.where(ok & ins, sres, 0.0)))
        if (ins & ~ok).any() or b['skin_quadratic_dev_mm'] > float(p['skin_max_dev_mm']):
            blockers.append({'code': 'SIDE_BUTTON_SKIN_DISCONTINUOUS', 'name': b['name'], 'missed_rays': int((ins & ~ok).sum()),
                             'dev_mm': b['skin_quadratic_dev_mm'], 'message': 'The skin under the button is not one smooth surface (edge, slot or hole).'})
        sk = np.where(ok & (sres < 1.0), sk, poly2_eval(cs, GQ))
        SK = sk.reshape(len(gu), len(gv))
        ins_pad = inside(b['O2'], GQ)
        scan_top = poly2_eval(b['top_poly'], GQ)
        proud_scan = (scan_top - sk)[ins_pad]
        b['proud_scan_mm'] = {'min': float(proud_scan.min()), 'median': float(np.median(proud_scan)), 'max': float(proud_scan.max())} if len(proud_scan) else None
        if b['proud_scan_mm'] and not (float(p['proud_min_mm']) <= b['proud_scan_mm']['min'] and b['proud_scan_mm']['max'] <= float(p['proud_max_mm'])):
            b['reasons'].append('scan_proud_out_of_range')
        b['confidence'] = 'high' if not b['reasons'] else ('medium' if len(b['reasons']) == 1 else 'low')
        if p.get('proud_mm') is not None:
            b['top_mode'] = 'fixed_proud'
            TOP = SK + float(p['proud_mm'])
        elif b['confidence'] == 'high':
            b['top_mode'] = 'scan_fit'
            TOP = scan_top.reshape(SK.shape)
        else:
            b['top_mode'] = 'default_proud'
            TOP = SK + float(p['default_proud_mm'])
        prd = (TOP.ravel() - sk)[ins_pad]
        b['proud_used_mm'] = {'min': float(prd.min()), 'median': float(np.median(prd)), 'max': float(prd.max())}
        if not (float(p['proud_min_mm']) <= b['proud_used_mm']['min'] and b['proud_used_mm']['max'] <= float(p['proud_max_mm'])):
            blockers.append({'code': 'SIDE_BUTTON_PROUD_OUT_OF_RANGE', 'name': b['name'], 'proud_mm': b['proud_used_mm']})
        floor = SK - DEP if grooved else SK - EMB
        s_lo = float(floor.min() - EMB - 3.0)
        cq = b['O2'].mean(0)
        k0 = int(np.argmin(np.linalg.norm(GQ - cq, axis=1)))
        i0, j0 = divmod(k0, len(gv))
        b['_grid'] = (gu, gv, SK, TOP)
        try:
            if grooved:
                pr, dev_g = outline_prism(fr, Og, s_far, s_lo)
                cut = split_pick(pr, [grid_surface(fr, gu, gv, floor)], fr.to3(GQ[k0:k0 + 1], floor[i0, j0] + 0.5 * DEP)[0])
                if cut is None:
                    raise WorkerError('SIDE_BUTTONS_CUTTER', 'The groove cutter could not be split by its floor.', {'name': b['name']})
                cutters.append(cut)
            else:
                dev_g = 0.0
            pr, dev_p = outline_prism(fr, b['O2'], s_far, s_lo)
            pad = split_pick(pr, [grid_surface(fr, gu, gv, floor - EMB), grid_surface(fr, gu, gv, TOP)],
                             fr.to3(GQ[k0:k0 + 1], 0.5 * (floor[i0, j0] - EMB + TOP[i0, j0]))[0])
            if pad is None:
                raise WorkerError('SIDE_BUTTONS_PAD', 'The pad could not be split by its top / bottom surfaces.', {'name': b['name']})
            pads.append(pad)
            b['bspline_outline_dev_mm'] = float(max(dev_g, dev_p))
        except WorkerError as exc:
            blockers.append({'code': exc.code, 'name': b['name'], 'message': exc.message})
    # ---- buttons too close to each other
    for i in range(len(buttons)):
        for j in range(i + 1, len(buttons)):
            bi, bj = buttons[i], buttons[j]
            if '_grid' not in bi or '_grid' not in bj:
                continue
            Pi = bi['frame'].to3(rounded(bi['plan'], W), 0.0)
            Pj = bj['frame'].to3(rounded(bj['plan'], W), 0.0)
            gap = float(cKDTree(Pi).query(Pj)[0].min())
            if gap < float(p['min_button_gap_mm']):
                blockers.append({'code': 'SIDE_BUTTONS_OVERLAP', 'names': [bi['name'], bj['name']], 'gap_mm': gap})
    # ---- boolean
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    from OCP.TopTools import TopTools_ListOfShape
    from OCP.TopoDS import TopoDS

    def boolean(cls, a, tools):
        op = cls()
        A = TopTools_ListOfShape()
        A.Append(a)
        T = TopTools_ListOfShape()
        for t in tools:
            T.Append(t)
        op.SetArguments(A)
        op.SetTools(T)
        op.Build()
        if not op.IsDone():
            raise WorkerError('SIDE_BUTTONS_BOOLEAN', 'A boolean operation failed.', {'op': cls.__name__})
        return op.Shape()
    v0 = L.volume(shell)
    body, pieces = shell, 1
    if pads and not blockers:
        body = boolean(BRepAlgoAPI_Cut, shell, cutters) if cutters else shell
        body = boolean(BRepAlgoAPI_Fuse, body, pads)
        ss = L.solids(body)
        pieces = len(ss)
        body = max(ss, key=L.volume)
        sfx = ShapeFix_Solid(body)
        sfx.Perform()
        body = TopoDS.Solid_s(sfx.Solid())
        u_ = ShapeUpgrade_UnifySameDomain(body, True, True, False)
        u_.Build()
        b2 = L.solids(u_.Shape())
        if b2 and L.is_valid(b2[0]):
            body = b2[0]
    L.write_step(body, out / 'side_buttons_shell.step')
    back = L.solids(L.read_step(out / 'side_buttons_shell.step'))
    rb = back[0] if back else None
    fa = [L.area(f) for f in L.faces(rb)] if rb is not None else []
    result = {'valid': bool(rb is not None and L.is_valid(rb)), 'solids_in_step': len(back), 'pieces_after_boolean': pieces,
              'faces': len(fa), 'faces_before': len(L.faces(shell)), 'faces_below_0p05mm2': int(sum(a < 0.05 for a in fa)),
              'faces_below_1mm2': int(sum(a < 1.0 for a in fa)), 'faces_below_1mm2_before': int(sum(L.area(f) < 1.0 for f in L.faces(shell))),
              'volume_before_mm3': v0, 'volume_after_mm3': L.volume(rb) if rb is not None else None,
              'modified': bool(pads and not blockers)}
    try:
        L.tessellate(rb, 0.05, 0.2) if rb is not None else None
        result['tessellates'] = rb is not None
    except WorkerError:
        result['tessellates'] = False
    # ---- measurements on the re-imported result
    recs = []
    for b in buttons:
        fr = b['frame']
        rec = {k: b.get(k) for k in ('name', 'source', 'flank', 'confidence', 'reasons', 'region_confidence', 'top_mode', 'n_top', 'top_source',
                                     'fit_res_p95_mm', 'hull_dev_mm', 'label_area_mm2', 'proud_scan_mm', 'proud_used_mm', 'skin_rays',
                                     'skin_quadratic_dev_mm', 'bspline_outline_dev_mm', 'min_sharp_corner_r')}
        O2 = b['O2']
        ext = O2.max(0) - O2.min(0)
        rec.update(frame={'origin': fr.O.tolist(), 'push_dir': fr.d.tolist(), 'u': fr.u.tolist(), 'v': fr.v.tolist()},
                   outline={'vertices': len(b['poly']), 'length_u_mm': float(ext[0]), 'height_v_mm': float(ext[1]), 'area_mm2': float(_poly_area(O2)),
                            'corner_radii_mm': [round(c['r'], 3) for c in b['plan']], 'turns_deg': [round(c['turn_deg'], 1) for c in b['plan']],
                            'centre_3d': None})
        if '_grid' in b:
            gu, gv, SK, TOP = b['_grid']
            c2 = O2.mean(0)
            iu, jv = int(np.argmin(np.abs(gu - c2[0]))), int(np.argmin(np.abs(gv - c2[1])))
            rec['outline']['centre_3d'] = fr.to3(c2[None], SK[iu, jv])[0].tolist()
            if rb is not None and result['modified']:
                meas = {'groove_width_mm': [], 'groove_depth_mm': [], 'proud_mm': []}
                from scipy.interpolate import RegularGridInterpolator
                skf = RegularGridInterpolator((gu, gv), SK)
                tn = np.roll(O2, -1, axis=0) - np.roll(O2, 1, axis=0)
                tn /= np.linalg.norm(tn, axis=1)[:, None]
                nout = np.c_[tn[:, 1], -tn[:, 0]]
                for k in np.linspace(0, len(O2) - 1, 16).astype(int):
                    q, n2 = O2[k], nout[k]
                    if grooved:
                        s_mid = float(skf(q[None])[0]) - 0.5 * DEP
                        p0 = fr.to3((q - 0.25 * n2)[None], s_mid)[0]
                        dirn = n2[0] * fr.u + n2[1] * fr.v
                        ts = line_hits(rb, p0, dirn)
                        ts = ts[ts > 0]
                        if len(ts) >= 2:
                            meas['groove_width_mm'].append(float(ts[1] - ts[0]))
                        qg = q + 0.5 * W * n2
                        sf = float(skf(qg[None])[0])
                        t = Rays(rb).first(fr.to3(qg[None], sf + 6.0)[0], -fr.d, 20.0)
                        if np.isfinite(t):
                            meas['groove_depth_mm'].append(float(sf - (sf + 6.0 - t)))
                inner = O2 + 0.6 * (c2 - O2) / (np.linalg.norm(c2 - O2, axis=1)[:, None] + 1e-12) * np.minimum(np.linalg.norm(c2 - O2, axis=1), 1.5)[:, None]
                rr = Rays(rb)
                for q in np.vstack([inner[::max(1, len(inner) // 12)], c2[None]]):
                    sf = float(skf(q[None])[0])
                    t = rr.first(fr.to3(q[None], sf + 6.0)[0], -fr.d, 20.0)
                    if np.isfinite(t):
                        meas['proud_mm'].append(float(6.0 - t))
                rec['measured'] = {k: (L.stats(v) if v else None) for k, v in meas.items()}
        rec['outline_2d'] = np.round(O2, 4).tolist()
        recs.append(rec)
    hand = p.get('handedness')
    fl = sorted({b['flank'] for b in buttons})
    hand_geo = 'right' if fl == ['+y'] else 'left' if fl == ['-y'] else ('both_flanks' if len(fl) > 1 else 'none')
    (out / 'side_buttons.json').write_text(json.dumps(L.clean({'schema': 'side_buttons/1', 'frame_note': 'outline_2d in the button frame (u, v); '
                                                                   '3D = origin + u * u_axis + v * v_axis (+ s * push_dir)', 'buttons': recs}), indent=1), encoding='utf-8')
    return L.clean({'worker': WORKER_VERSION, 'buttons': recs, 'per_flank': flanks, 'handedness_from_buttons': hand_geo, 'handedness_regions': hand,
                    'blockers': blockers, 'warnings': warnings, 'result': result, 'grooved': grooved, 'mesh_median_distance_mm': med,
                    'files': {'step': 'side_buttons_shell.step', 'buttons': 'side_buttons.json'}, 'params_used': p})


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
