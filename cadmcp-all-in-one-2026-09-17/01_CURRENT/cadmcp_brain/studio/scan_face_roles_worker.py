"""Face roles of a mouse top shell (+ optional bottom plate) by GEOMETRY. SUBPROCESS WORKER (server python with OCP, extra `geometry`).

Run as:  <server python> -I scan_face_roles_worker.py request.json      (result = last stdout line, JSON)

Method (per face of the shell, faces in TopExp_Explorer order):
  * samples on a UV grid inside the face (classifier), outward normal per sample (face orientation applied);
  * a ray from p + 0.02 n along n against the same solid: hit within slot_max_mm on most samples => groove (slot) wall, hit within
    window_max_mm => window wall (walls of a pocket face each other across the pocket);
  * floors = faces whose boundary is mostly groove / window walls that RISE above them (wall direction from the shared edge, inside the
    wall face, points along the face normal); walls without a floor or a neighbouring wall of the same kind are demoted (warning);
  * side-button tops = near-horizontal faces whose whole boundary is crisp edges (dihedral > crisp_edge_deg) to small walls that descend
    from the top (the pad protrudes); those walls = sidebutton_wall (walls of a pad in a groove may first read as slot walls: allowed;
    the groove floor / outer wall stay slot);
  * parting = remaining faces with mean n_z < -0.5;
  * panel = up-facing faces whose boundary is mostly (panel_min_groove_fraction) groove / window walls that descend from them, with the
    groove on the outside (enclosure score from the wall normals vs the face centroid); the rest of the boundary must be crisp (front lip);
  * shell = the rest.
Optional hint mesh (STL + {name: [triangle ids]} in the same frame): nearest labelled triangle of every sample; a majority hint that names a
different top role (panel / sidebutton / shell) is a warning, never a reassignment. Plate faces: floor (n_z < -0.9), parting (n_z > 0.3), side.
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

WORKER_VERSION = 'scan_face_roles/1'
COLORS = {'panel': (0.95, 0.50, 0.10), 'sidebutton': (0.15, 0.65, 0.25), 'plate': (0.20, 0.40, 0.85), 'rest': (0.62, 0.63, 0.66)}
DEFAULTS = {'slot_max_mm': 2.5, 'window_max_mm': 30.0, 'panel_min_groove_fraction': 0.6, 'crisp_edge_deg': 15.0, 'hint_max_dist_mm': 1.5,
            'grid': 7}
HINT_ROLE = (('click', 'panel'), ('side_button', 'sidebutton'), ('sidebutton', 'sidebutton'), ('wheel', 'window'), ('bottom_plate', 'plate'),
             ('plate', 'plate'), ('top_shell', 'shell'), ('shell', 'shell'))
HINT_SHORT = {'LC': 'panel', 'RC': 'panel', 'B1': 'sidebutton', 'B2': 'sidebutton', 'WH': 'window'}
TOP_ROLES = ('panel', 'sidebutton', 'shell')
RAY_OFFSET = 0.02


# ------------------------------------------------------------------ geometry primitives
def face_samples(f, grid: int):
    """-> (P, N) samples strictly inside f on a UV grid (refined once if too few)."""
    from OCP.BRepTools import BRepTools
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_IN
    from OCP.gp import gp_Pnt2d
    a = BRepAdaptor_Surface(f)
    u0, u1, v0, v1 = BRepTools.UVBounds_s(f)
    P, N = [], []
    for g in (grid, 2 * grid + 1):
        s = np.linspace(0.04, 0.96, g)
        for su in s:
            for tv in s:
                u, v = u0 + su * (u1 - u0), v0 + tv * (v1 - v0)
                if BRepClass_FaceClassifier(f, gp_Pnt2d(u, v), 1e-7).State() == TopAbs_IN:
                    n = L.face_normal_uv(f, u, v)
                    if np.all(np.isfinite(n)):
                        P.append(a.Value(u, v).Coord())
                        N.append(n)
        if len(P) >= 4:
            break
    if not P:
        p, n = L.inner_point(f)
        if p is not None:
            P, N = [p], [n]
    return np.array(P, float).reshape(-1, 3), np.array(N, float).reshape(-1, 3)


class Rays:
    def __init__(self, solid):
        from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
        self.si = IntCurvesFace_ShapeIntersector()
        self.si.Load(solid, 1e-7)

    def dist(self, p, n, dmax: float) -> float:
        from OCP.gp import gp_Lin, gp_Pnt, gp_Dir
        q = p + RAY_OFFSET * n
        self.si.Perform(gp_Lin(gp_Pnt(*map(float, q)), gp_Dir(*map(float, n))), 0.0, float(dmax))
        if not self.si.IsDone() or self.si.NbPnt() == 0:
            return float('inf')
        return RAY_OFFSET + min(self.si.WParameter(i) for i in range(1, self.si.NbPnt() + 1))


def in_face_dir(f, m, t):
    """Unit direction at edge point m, perpendicular to the edge tangent t, pointing INTO face f (None if undecidable)."""
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.BRep import BRep_Tool
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCP.TopAbs import TopAbs_IN
    from OCP.gp import gp_Pnt, gp_Pnt2d
    n = L.face_normal_at(f, m)
    if not np.all(np.isfinite(n)):
        return None, n
    d = np.cross(n, t)
    if np.linalg.norm(d) < 1e-9:
        return None, n
    d /= np.linalg.norm(d)
    S = BRep_Tool.Surface_s(f)
    for step in (0.05, 0.02, 0.005, 0.15):
        for sg in (1.0, -1.0):
            q = m + sg * step * d
            pr = GeomAPI_ProjectPointOnSurf(gp_Pnt(*map(float, q)), S)
            if pr.NbPoints() == 0:
                continue
            u, v = pr.LowerDistanceParameters()
            if BRepClass_FaceClassifier(f, gp_Pnt2d(u, v), 1e-7).State() == TopAbs_IN:
                return sg * d, n
    return None, n


def edges_info(solid, fs):
    """Shared edges -> list of dict(a, b, length, mid, angle_deg, na, nb, da, db) (a < b)."""
    from OCP.TopExp import TopExp
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape, TopTools_IndexedMapOfShape
    from OCP.TopoDS import TopoDS
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    from OCP.gp import gp_Pnt, gp_Vec
    fmap = TopTools_IndexedMapOfShape()
    for f in fs:
        fmap.Add(f)
    if fmap.Extent() != len(fs):
        raise WorkerError('FACE_ROLES_TOPOLOGY', 'Face list holds repeated faces.', {'faces': len(fs), 'unique': fmap.Extent()})
    emap = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(solid, TopAbs_EDGE, TopAbs_FACE, emap)
    out = []
    for i in range(1, emap.Extent() + 1):
        e = TopoDS.Edge_s(emap.FindKey(i))
        if BRep_Tool.Degenerated_s(e):
            continue
        anc = sorted({fmap.FindIndex(x) - 1 for x in emap.FindFromIndex(i)})
        if len(anc) != 2:
            continue
        g = GProp_GProps()
        BRepGProp.LinearProperties_s(e, g)
        c = BRepAdaptor_Curve(e)
        tm = 0.5 * (c.FirstParameter() + c.LastParameter())
        p, v = gp_Pnt(), gp_Vec()
        c.D1(tm, p, v)
        m = np.array(p.Coord())
        t = np.array(v.Coord())
        if np.linalg.norm(t) < 1e-12:
            continue
        t /= np.linalg.norm(t)
        a, b = anc
        da, na = in_face_dir(fs[a], m, t)
        db, nb = in_face_dir(fs[b], m, t)
        ang = float(np.degrees(np.arccos(np.clip(np.dot(na, nb), -1, 1)))) if np.all(np.isfinite(na)) and np.all(np.isfinite(nb)) else None
        out.append({'a': a, 'b': b, 'length': g.Mass(), 'mid': m, 'angle_deg': ang, 'na': na, 'nb': nb, 'da': da, 'db': db})
    return out


def side(e, k):
    """View of edge e from face k: (other face, n_self, n_other, d_self, d_other)."""
    if e['a'] == k:
        return e['b'], e['na'], e['nb'], e['da'], e['db']
    return e['a'], e['nb'], e['na'], e['db'], e['da']


def rise(e, k):
    """> 0 when the other face goes UP (along the normal of face k) from the shared edge; None if undecidable."""
    o, n_k, _, _, d_o = side(e, k)
    if d_o is None or not np.all(np.isfinite(n_k)):
        return None
    return float(np.dot(d_o, n_k))


def centroid(f):
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    g = GProp_GProps()
    BRepGProp.SurfaceProperties_s(f, g)
    return np.array(g.CentreOfMass().Coord())


def surf_type(f) -> str:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    return str(BRepAdaptor_Surface(f).GetType()).split('.')[-1].split('_')[-1]


# ------------------------------------------------------------------ hints
def hint_role_of(name: str) -> str | None:
    if name in HINT_SHORT:
        return HINT_SHORT[name]
    low = name.lower()
    for key, role in HINT_ROLE:
        if key in low:
            return role
    return None


def read_hint_labels(path: Path, n_tri: int) -> tuple[dict[str, np.ndarray], list[str]]:
    if Path(path).suffix.lower() == '.npz':          # face_labels + codes ('name=code'), as written by the mesh-stage tools (recognize_shell, scan_flush)
        try:
            z = np.load(path, allow_pickle=False)
            fl, codes = z['face_labels'], [str(c) for c in z['codes']]
        except (OSError, ValueError, KeyError) as exc:
            raise WorkerError('FACE_ROLES_HINTS', 'An .npz hint label file needs the arrays face_labels and codes ("name=code").', {'error': type(exc).__name__}) from exc
        if len(fl) != n_tri:
            raise WorkerError('FACE_ROLES_HINTS', 'face_labels has a different length than the hint mesh has triangles.', {'labels': int(len(fl)), 'triangles': n_tri})
        d = {}
        for c in codes:
            name, _, code = c.rpartition('=')
            if name and code.lstrip('-').isdigit():
                d[name] = np.flatnonzero(fl == int(code)).tolist()
    else:
        try:
            d = json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise WorkerError('FACE_ROLES_HINTS', 'The hint label file is not valid JSON.', {'error': type(exc).__name__}) from exc
    if isinstance(d, dict) and isinstance(d.get('regions'), dict):
        d = d['regions']
    if not isinstance(d, dict):
        raise WorkerError('FACE_ROLES_HINTS', 'The hint label file must be {name: [triangle ids]}.')
    out, ignored = {}, []
    for name, ids in d.items():
        if isinstance(ids, dict):
            ids = ids.get('face_ids', [])
        role = hint_role_of(str(name))
        if role is None:
            ignored.append(str(name))
            continue
        try:
            a = np.asarray(ids, dtype=np.int64).ravel()
        except (TypeError, ValueError) as exc:
            raise WorkerError('FACE_ROLES_HINTS', 'Hint triangle ids must be integers.', {'name': name}) from exc
        if len(a) and (a.min() < 0 or a.max() >= n_tri):
            raise WorkerError('FACE_ROLES_HINTS', 'Hint triangle ids are out of range for the hint mesh.', {'name': name, 'triangles': n_tri})
        out[str(name)] = a
    return out, ignored


def nearest(C: np.ndarray, Q: np.ndarray):
    try:
        from scipy.spatial import cKDTree
        return cKDTree(C).query(Q)
    except ImportError:
        d = np.empty(len(Q))
        j = np.empty(len(Q), np.int64)
        for s in range(0, len(Q), 64):
            dd = ((Q[s:s + 64, None, :] - C[None, :, :]) ** 2).sum(-1)
            j[s:s + 64] = dd.argmin(1)
            d[s:s + 64] = np.sqrt(dd[np.arange(len(dd)), j[s:s + 64]])
        return d, j


# ------------------------------------------------------------------ classification
def classify_shell(solid, prm: dict[str, Any], warnings: list[dict[str, Any]]):
    fs = L.faces(solid)
    nf = len(fs)
    smax, wmax = float(prm['slot_max_mm']), float(prm['window_max_mm'])
    crisp = float(prm['crisp_edge_deg'])
    rays = Rays(solid)
    S, D, area, nz, cen = [], [], np.zeros(nf), np.zeros(nf), []
    for k, f in enumerate(fs):
        P, N = face_samples(f, int(prm['grid']))
        S.append((P, N))
        D.append(np.array([rays.dist(p, n, wmax + 1.0) for p, n in zip(P, N)]))
        area[k] = L.area(f)
        nz[k] = float(N[:, 2].mean()) if len(N) else 0.0
        cen.append(centroid(f))
    E = edges_info(solid, fs)
    inc: list[list[dict]] = [[] for _ in range(nf)]
    for e in E:
        inc[e['a']].append(e)
        inc[e['b']].append(e)
    perim = np.array([sum(e['length'] for e in inc[k]) for k in range(nf)])
    role: list[str | None] = [None] * nf
    sub: list[str | None] = [None] * nf
    fr_slot = np.array([float(np.mean(d <= smax)) if len(d) else 0.0 for d in D])
    fr_win = np.array([float(np.mean((d > smax) & (d <= wmax))) if len(d) else 0.0 for d in D])
    for k in range(nf):
        if nz[k] < -0.5:
            continue
        if fr_slot[k] >= 0.5:
            role[k], sub[k] = 'slot', 'wall'
        elif fr_win[k] >= 0.5 or (fr_slot[k] + fr_win[k] >= 0.5 and fr_win[k] >= fr_slot[k]):
            role[k], sub[k] = 'window', 'wall'

    def wall_len(k, kind, sign):
        tot = 0.0
        for e in inc[k]:
            o = side(e, k)[0]
            if role[o] == kind and sub[o] == 'wall':
                r = rise(e, k)
                if r is not None and r * sign > 0.3:
                    tot += e['length']
        return tot

    # floors: up-facing-in-the-groove faces bounded mostly by walls that rise above them
    for k in range(nf):
        if role[k] is not None or perim[k] <= 0:
            continue
        ls, lw = wall_len(k, 'slot', +1), wall_len(k, 'window', +1)
        if (ls + lw) / perim[k] >= 0.5:
            role[k], sub[k] = ('slot', 'floor') if ls >= lw else ('window', 'floor')
    # close the pocket: every face that rises from a window floor is a window wall (a tilted floor hides some walls from the rays)
    for k in [i for i in range(nf) if role[i] == 'window' and sub[i] == 'floor']:
        for e in inc[k]:
            o = side(e, k)[0]
            r = rise(e, k)
            if r is not None and r > 0.5 and (role[o] is None or (role[o] == 'slot' and sub[o] == 'wall')):
                if role[o] == 'slot':
                    warnings.append({'code': 'WINDOW_WALL_FROM_SLOT', 'face': o, 'message': f'Face {o} hit like a slot wall but rises from window floor {k}; window wall.'})
                role[o], sub[o] = 'window', 'wall'
    # demote walls without a floor / partner wall of the same kind
    for kind, code in (('slot', 'SLOT_WALL_WITHOUT_GROOVE'), ('window', 'WINDOW_WALL_WITHOUT_POCKET')):
        for k in range(nf):
            if role[k] != kind or sub[k] != 'wall':
                continue
            nb = {side(e, k)[0] for e in inc[k]}
            ok = any(role[o] == kind and sub[o] == 'floor' for o in nb) if kind == 'window' else any(role[o] == kind for o in nb)
            if not ok:
                warnings.append({'code': code, 'face': k, 'message': f'Face {k} looks like a {kind} wall by its rays but has no {kind} floor/partner; kept as shell.'})
                role[k], sub[k] = None, None
    # side-button pads
    total = float(area.sum())
    for k in range(nf):
        if role[k] is not None or abs(nz[k]) >= 0.6 or not inc[k] or area[k] > 0.1 * total:
            continue
        nb = {side(e, k)[0] for e in inc[k]}
        # a pad in a groove (brain_mouse_scan_side_buttons): its walls face the groove's outer wall across the gap and read as slot walls
        grooved = any(role[o] == 'slot' and sub[o] == 'wall' for o in nb)
        if any(role[o] is not None and not (role[o] == 'slot' and sub[o] == 'wall') for o in nb) or sum(area[o] for o in nb) > (3.0 if grooved else 1.5) * area[k]:
            continue
        if not all(e['angle_deg'] is not None and e['angle_deg'] > crisp for e in inc[k]):
            continue
        rs = [rise(e, k) for e in inc[k]]
        if not all(r is not None and r < -0.5 for r in rs):
            continue
        role[k], sub[k] = 'sidebutton', 'top'
        for o in nb:
            role[o], sub[o] = 'sidebutton_wall', 'wall'
    for k in range(nf):
        if role[k] is None and nz[k] < -0.5:
            role[k], sub[k] = 'parting', None
    # panels
    fmin = float(prm['panel_min_groove_fraction'])
    panel_info = {}
    for k in range(nf):
        if role[k] is not None or nz[k] <= 0.2 or perim[k] <= 0:
            continue
        lg, enc_num = 0.0, 0.0
        for e in inc[k]:
            o, n_k, n_o, _, _ = side(e, k)
            if role[o] in ('slot', 'window') and sub[o] == 'wall':
                r = rise(e, k)
                if r is not None and r < -0.3:
                    lg += e['length']
                    g = n_o - np.dot(n_o, n_k) * n_k
                    rr = e['mid'] - cen[k]
                    rr = rr - np.dot(rr, n_k) * n_k
                    if np.linalg.norm(g) > 1e-9 and np.linalg.norm(rr) > 1e-9:
                        enc_num += e['length'] * np.sign(np.dot(g, rr))
        if lg / perim[k] < fmin or lg <= 0:
            continue
        enc = enc_num / lg
        if enc < 0.3:
            continue
        role[k], sub[k] = 'panel', 'top'
        panel_info[k] = {'groove_fraction': lg / perim[k], 'enclosure': enc}
    for k in range(nf):
        if role[k] is None:
            role[k] = 'shell'
    return fs, S, D, area, nz, E, inc, perim, role, sub, panel_info


def polygon_inside(poly: np.ndarray, Q: np.ndarray) -> np.ndarray:
    """Even-odd point-in-polygon (2D)."""
    x, y = poly[:, 0], poly[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    ins = np.zeros(len(Q), bool)
    for s in range(0, len(Q), 512):
        qx, qy = Q[s:s + 512, 0:1], Q[s:s + 512, 1:2]
        cond = (y[None] > qy) != (y2[None] > qy)
        xi = x[None] + (qy - y[None]) * (x2 - x)[None] / np.where(np.abs(y2 - y) < 1e-15, 1e-15, (y2 - y))[None]
        ins[s:s + 512] = (cond & (qx < xi)).sum(1) % 2 == 1
    return ins


def panel_check(f):
    """Samples (tessellation nodes) of the panel outside the plan (xy) loop of its own boundary (groove walls + lip); must be 0."""
    BP = L.wire_points(f, 0.002)[:, :2]
    V = L.tessellate(f, 0.02, 0.1)['V'][:, :2]
    ins = polygon_inside(BP, V)
    if (~ins).any():
        d, _ = nearest(BP, V[~ins])
        ins[np.flatnonzero(~ins)[d < 0.005]] = True
    return int(len(V)), int((~ins).sum())


def bbox_list(f):
    return [round(float(c), 3) for c in L.bbox(f)]


def run(req: dict[str, Any]) -> dict[str, Any]:
    L.require_ocp()
    prm = {**DEFAULTS, **(req.get('params') or {})}
    colors = {**COLORS, **{k: tuple(v) for k, v in (prm.get('colors') or {}).items()}}
    inp = req['inputs']
    out = Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    warnings: list[dict[str, Any]] = []
    shell = L.one_solid(Path(inp['shell']), 'FACE_ROLES_SHELL_SOLIDS')
    plate = L.one_solid(Path(inp['plate']), 'FACE_ROLES_PLATE_SOLIDS') if inp.get('plate') else None
    fs, S, D, area, nz, E, inc, perim, role, sub, pinfo = classify_shell(shell, prm, warnings)
    nf = len(fs)
    crisp = float(prm['crisp_edge_deg'])

    # ---- hints
    hint = [None] * nf
    hint_share = [None] * nf
    hint_used = False
    if inp.get('hint_mesh') and inp.get('hint_labels'):
        V, F = L.read_stl(Path(inp['hint_mesh']))
        labels, ignored = read_hint_labels(Path(inp['hint_labels']), len(F))
        if ignored:
            warnings.append({'code': 'FACE_ROLES_HINT_NAMES_IGNORED', 'names': ignored, 'message': 'Hint names without a known role were ignored.'})
        tri_role = np.array([None] * len(F), dtype=object)
        for name, ids in labels.items():
            tri_role[ids] = hint_role_of(name)
        C = V[F].mean(1)
        allP = np.vstack([s[0] for s in S if len(s[0])])
        dall, _ = nearest(C, allP)
        hmax = float(prm['hint_max_dist_mm'])
        if float(np.median(dall)) > hmax:
            warnings.append({'code': 'FACE_ROLES_HINT_FRAME', 'median_distance_mm': float(np.median(dall)),
                             'message': 'The hint mesh is not in the frame of the shell (median distance above hint_max_dist_mm); hints ignored.'})
        else:
            hint_used = True
            for k in range(nf):
                P = S[k][0]
                if not len(P):
                    continue
                d, j = nearest(C, P)
                rs = [tri_role[jj] if dd <= hmax else None for dd, jj in zip(d, j)]
                rs = ['shell' if r is None else r for r in rs]                                  # unlabelled triangle = no click / button
                vals, cnt = np.unique(np.array(rs, dtype=str), return_counts=True)
                top = int(cnt.argmax())
                hint[k], hint_share[k] = str(vals[top]), float(cnt[top] / len(rs))
                if hint_share[k] < 0.6:
                    continue
                if role[k] in TOP_ROLES and hint[k] in TOP_ROLES and hint[k] != role[k]:
                    if hint[k] == 'shell' and not any(n in ('shell', 'top_shell') for n in labels):
                        continue                                                              # no shell label given: unlabelled is not evidence
                    warnings.append({'code': 'FACE_ROLE_HINT_DISAGREES', 'solid': 'top_shell', 'face': k, 'geometry_role': role[k], 'hint_role': hint[k],
                                     'hint_share': round(hint_share[k], 3), 'message': 'The label hint disagrees with the geometry; the geometry role is kept.'})

    # ---- records
    def neighbours(k):
        agg: dict[int, dict] = {}
        for e in inc[k]:
            o = side(e, k)[0]
            a = agg.setdefault(o, {'face': o, 'role': role[o], 'shared_length_mm': 0.0, 'max_angle_deg': 0.0})
            a['shared_length_mm'] += e['length']
            if e['angle_deg'] is not None:
                a['max_angle_deg'] = max(a['max_angle_deg'], e['angle_deg'])
        return [{**a, 'shared_length_mm': round(a['shared_length_mm'], 3), 'max_angle_deg': round(a['max_angle_deg'], 1)} for a in sorted(agg.values(), key=lambda x: x['face'])]

    recs = []
    for k, f in enumerate(fs):
        p, _ = L.inner_point(f)
        d = D[k]
        recs.append({'index': k, 'role': role[k], 'sub': sub[k], 'type': surf_type(f), 'area': round(float(area[k]), 3),
                     'point': [round(float(c), 4) for c in p] if p is not None else None, 'bbox': bbox_list(f), 'mean_nz': round(float(nz[k]), 3),
                     'ray_hit_fraction': {'slot': round(float(np.mean(d <= prm['slot_max_mm'])), 3) if len(d) else None,
                                          'window': round(float(np.mean((d > prm['slot_max_mm']) & (d <= prm['window_max_mm']))), 3) if len(d) else None},
                     'samples': int(len(d)), 'hint': hint[k], 'hint_share': None if hint_share[k] is None else round(hint_share[k], 3),
                     'neighbours': neighbours(k)})
    # ---- panels
    panels = {}
    for k in [i for i in range(nf) if role[i] == 'panel']:
        lens: dict[str, float] = {}
        soft = 0.0
        for e in inc[k]:
            o = side(e, k)[0]
            lens[role[o]] = lens.get(role[o], 0.0) + e['length']
            if role[o] not in ('slot', 'window') and (e['angle_deg'] is None or e['angle_deg'] <= crisp):
                soft += e['length']
        n_s, n_out = panel_check(fs[k])
        panels[str(k)] = {'boundary_len_by_neighbour': {a: round(b, 2) for a, b in sorted(lens.items())}, 'groove_fraction': round(pinfo[k]['groove_fraction'], 3),
                          'enclosure': round(pinfo[k]['enclosure'], 3), 'non_crisp_lip_mm': round(soft, 2), 'samples': n_s, 'samples_outside_groove_loop': n_out}
        if soft > 0.5:
            warnings.append({'code': 'PANEL_LIP_NOT_CRISP', 'face': k, 'length_mm': round(soft, 2),
                             'message': 'Part of the panel boundary that is not a groove wall is tangent (not a crisp lip).'})
    # ---- window loop
    win_floor = [k for k in range(nf) if role[k] == 'window' and sub[k] == 'floor']
    loops = []
    for wf in win_floor:
        walls = {side(e, wf)[0] for e in inc[wf] if role[side(e, wf)[0]] == 'window'}
        deg = {w: len({side(e, w)[0] for e in inc[w]} & walls) for w in walls}
        loops.append({'floor': wf, 'walls': sorted(walls), 'closed': bool(walls) and all(v >= 2 for v in deg.values())})
    # ---- side buttons
    pads = []
    for k in [i for i in range(nf) if role[i] == 'sidebutton']:
        pads.append({'top': k, 'walls': sorted({side(e, k)[0] for e in inc[k]}), 'area': round(float(area[k]), 3)})
    # ---- plate
    prec = []
    if plate is not None:
        for k, f in enumerate(L.faces(plate)):
            P, N = face_samples(f, int(prm['grid']))
            z = float(N[:, 2].mean()) if len(N) else 0.0
            sb = 'floor' if z < -0.9 else ('parting' if z > 0.3 else 'side')
            p, _ = L.inner_point(f)
            prec.append({'index': k, 'role': 'plate', 'sub': sb, 'type': surf_type(f), 'area': round(L.area(f), 3),
                         'point': [round(float(c), 4) for c in p] if p is not None else None, 'bbox': bbox_list(f), 'mean_nz': round(z, 3)})
    # ---- outputs
    note = ('index = face order in the STEP (TopExp_Explorer order); Fusion face indices may differ: match faces by point / bbox.')
    roles_doc = {'top_shell': recs, 'note': note, 'worker': WORKER_VERSION}
    if plate is not None:
        roles_doc['bottom_plate'] = prec
    (out / 'face_roles.json').write_text(json.dumps(L.clean(roles_doc), indent=1), encoding='utf-8')
    rc = {'panel': colors['panel'], 'sidebutton': colors['sidebutton']}
    scol = [tuple(rc.get(r, colors['rest'])) for r in role]
    parts = [('top_shell', shell, scol, tuple(colors['rest']))]
    if plate is not None:
        parts.append(('bottom_plate', plate, [tuple(colors['plate'])] * len(prec), tuple(colors['plate'])))
    readback = L.write_colored_step(parts, out / 'assembly_colored.step')
    expected: dict[str, int] = {}
    for _, _, cols, _ in parts:
        for c in cols:
            key = '%.2f,%.2f,%.2f' % tuple(c)
            expected[key] = expected.get(key, 0) + 1
    rb = {k: v for k, v in readback.items() if k != 'none'}
    from collections import Counter
    counts = dict(Counter(role))
    checks = {
        'parting_found': 'PASS' if counts.get('parting') else 'FAIL',
        'panels_inside_groove': ('UNVERIFIED' if not panels else 'PASS' if all(p['samples_outside_groove_loop'] == 0 for p in panels.values()) else 'FAIL'),
        'window_closed_loop': ('UNVERIFIED' if not loops else 'PASS' if all(lp['closed'] for lp in loops) else 'FAIL'),
        'sidebutton_walls': ('UNVERIFIED' if not pads else 'PASS' if all(p['walls'] for p in pads) else 'FAIL'),
        'colour_readback': 'PASS' if rb == expected else 'FAIL',
        'hint_agreement': ('UNVERIFIED' if not hint_used else 'FAIL' if any(w['code'] == 'FACE_ROLE_HINT_DISAGREES' for w in warnings) else 'PASS'),
    }
    if plate is not None:
        subs = Counter(r['sub'] for r in prec)
        checks['plate_subs'] = 'PASS' if subs.get('floor') and subs.get('parting') else 'FAIL'
    return L.clean({'counts': {'top_shell': counts, 'bottom_plate': dict(Counter(r['sub'] for r in prec)) if plate is not None else None},
                    'faces': {'top_shell': nf, 'bottom_plate': len(prec) if plate is not None else None},
                    'panels': panels, 'window_loops': loops, 'sidebuttons': pads, 'colour_counts': {'expected': expected, 'read_back': readback},
                    'warnings': warnings, 'checks': checks, 'hints_used': hint_used, 'note': note,
                    'files': {'face_roles': 'face_roles.json', 'colored_step': 'assembly_colored.step'}})


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
