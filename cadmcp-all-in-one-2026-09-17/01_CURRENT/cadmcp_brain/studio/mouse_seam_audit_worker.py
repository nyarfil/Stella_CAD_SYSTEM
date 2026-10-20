"""Seam audit of a shell solid (brain_mouse_seam_audit). SUBPROCESS WORKER (server python: OCP + matplotlib, extra `geometry`).

Run as:  <server python> -I mouse_seam_audit_worker.py request.json      (result = last stdout line, JSON)

Every B-rep edge is classified from its adjacent faces and the angle between the two outward face normals, measured at `samples` points along the
edge (0 deg = G1 continuous):
  smooth_seam         two faces, max normal angle <= g1_tol_deg: a split of one smooth surface (a visible "seam band" when it is not designed)
  crease              two faces, max normal angle >  g1_tol_deg: a real edge (slot wall, lip, window, ...)
  closed_surface_seam the edge joins a periodic face with itself (cylinder / torus seam): G1 by construction
  free                one face only (open boundary: not a closed solid)
  non_manifold        three or more faces
An edge is IN a band when all its sample points lie inside the band slab (axis range) and its mid point lies in the optional along-range.
Flagged = in a band and (smooth_seam | free | non_manifold); with flag='all' every in-band edge. Faces per band = faces whose tessellation
overlaps the band (independent of the edges). The PNG is a plan view of all edges (grey), flagged edges (red) and the bands.
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Any

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from cadmcp_brain.studio.scan_cad_common import WorkerError, worker_main
from cadmcp_brain.studio import cad_brep_lib as L
from cadmcp_brain.studio import mouse_parts_lib as P

WORKER_VERSION = 'mouse_seam_audit/2'
BAND_HALF_WIDTH_FRACTION = 0.015   # derived slot band half width / shell extent along the mirror axis
AXES = {'x': 0, 'y': 1, 'z': 2}
VIEWS = {'XY': (0, 1), 'XZ': (0, 2), 'YZ': (1, 2)}


def face_normals(edge, face, ts: np.ndarray) -> np.ndarray:
    """Outward unit normals of `face` at the edge parameters ts (NaN where undefined)."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve2d, BRepAdaptor_Surface
    from OCP.BRepLProp import BRepLProp_SLProps
    from OCP.TopAbs import TopAbs_REVERSED
    c2, sf = BRepAdaptor_Curve2d(edge, face), BRepAdaptor_Surface(face, True)
    sign = -1.0 if face.Orientation() == TopAbs_REVERSED else 1.0
    out = np.full((len(ts), 3), np.nan)
    for i, t in enumerate(ts):
        p = c2.Value(float(t))
        pr = BRepLProp_SLProps(sf, p.X(), p.Y(), 1, 1e-6)
        if pr.IsNormalDefined():
            n = pr.Normal()
            out[i] = sign * np.array([n.X(), n.Y(), n.Z()])
    return out


def fit_mirror_plane(V: np.ndarray, axis: int, seed: int = 0) -> dict[str, Any]:
    """Fit the plane (normal = world axis `axis`) that maps the vertex cloud onto itself best: minimise the trimmed mean (lowest 85 %) of the distance
    from each reflected point to its nearest vertex. Coarse scan over the middle 30 % of the extent, then a bounded refinement. Returns the plane
    coordinate, the trimmed mean residual and the extent along the axis."""
    from scipy.optimize import minimize_scalar
    from scipy.spatial import cKDTree
    rng = np.random.default_rng(seed)
    P = V[rng.choice(len(V), size=20000, replace=False)] if len(V) > 20000 else V
    tree = cKDTree(V)
    lo, hi = float(V[:, axis].min()), float(V[:, axis].max())
    ext = hi - lo

    def cost(c: float) -> float:
        R = P.copy()
        R[:, axis] = 2.0 * c - R[:, axis]
        d = np.sort(tree.query(R)[0])
        return float(d[:max(1, int(0.85 * len(d)))].mean())

    mid = 0.5 * (lo + hi)
    grid = np.linspace(mid - 0.15 * ext, mid + 0.15 * ext, 61)
    c0 = float(grid[int(np.argmin([cost(c) for c in grid]))])
    step = float(grid[1] - grid[0])
    r = minimize_scalar(cost, bounds=(c0 - step, c0 + step), method='bounded', options={'xatol': 1e-5})
    return {'plane_mm': float(r.x), 'residual_mm': float(r.fun), 'extent_mm': float(ext), 'bbox_mid_mm': mid}


def in_band(pts: np.ndarray, band: dict[str, Any], tol: float) -> bool:
    a = AXES[band['axis']]
    lo, hi = band['range']
    if not (pts[:, a].min() >= lo - tol and pts[:, a].max() <= hi + tol):
        return False
    if band.get('along_axis'):
        b = AXES[band['along_axis']]
        lo2, hi2 = band['along_range']
        m = pts[len(pts) // 2, b]
        return lo2 - tol <= m <= hi2 + tol
    return True


def run(req: dict[str, Any]) -> dict[str, Any]:
    import time
    t0 = time.time()
    L.require_ocp()
    from OCP.TopExp import TopExp
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape, TopTools_IndexedMapOfShape
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRep import BRep_Tool
    from OCP.GCPnts import GCPnts_AbscissaPoint
    prm, out = req['params'], Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    parts, _ = P.load_parts([req['inputs']['shell']])
    name = prm.get('part')
    if name is None:
        if len(parts) != 1:
            raise WorkerError('SEAM_PART_AMBIGUOUS', 'The STEP holds several parts: name one with `part`.', {'parts': sorted(parts)})
        name = next(iter(parts))
    P.require(parts, [name], 'part')
    shape = parts[name]
    tol, g1_tol, ns = prm['band_tol_mm'], prm['g1_tol_deg'], prm['samples']
    ma = AXES[prm.get('mirror_axis', 'y')]
    # symmetry plane of the shell (fitted from the tessellation unless given); the derived slot band is centred on it
    mesh0 = L.tessellate(shape, prm['deflection_mm'], 0.3)
    sym = {'axis': prm.get('mirror_axis', 'y'), 'source': 'argument' if prm.get('mirror_plane_mm') is not None else 'fitted'}
    if prm.get('mirror_plane_mm') is not None:
        sym.update({'plane_mm': float(prm['mirror_plane_mm'])})
        ext = float(mesh0['V'][:, ma].max() - mesh0['V'][:, ma].min())
    else:
        sym.update(fit_mirror_plane(mesh0['V'], ma))
        ext = sym['extent_mm']
        if sym['residual_mm'] > 0.02 * ext and prm['bands'] is None:
            raise WorkerError('SEAM_NOT_SYMMETRIC', 'The shell is not left-right symmetric about any plane normal to the mirror axis (fit residual '
                              f"{sym['residual_mm']:.3f} mm); give bands or mirror_plane_mm.", sym)
    sym['extent_mm'] = ext
    bands = prm['bands']
    if bands is None:
        hw = prm['band_half_width_mm'] if prm.get('band_half_width_mm') is not None else BAND_HALF_WIDTH_FRACTION * ext
        bands = [{'name': 'slot_band', 'axis': prm.get('mirror_axis', 'y'), 'range': [sym['plane_mm'] - hw, sym['plane_mm'] + hw]}]
        sym['derived_band_half_width_mm'] = hw
    emap, fmap = TopTools_IndexedDataMapOfShapeListOfShape(), TopTools_IndexedMapOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, emap)
    TopExp.MapShapes_s(shape, TopAbs_FACE, fmap)
    n_edges, n_faces = emap.Extent(), fmap.Extent()
    draw_n = max(ns, 17)
    edges: list[dict[str, Any]] = []
    degenerate = 0
    for i in range(1, n_edges + 1):
        e = TopoDS.Edge_s(emap.FindKey(i))
        if BRep_Tool.Degenerated_s(e):
            degenerate += 1
            continue
        cv = BRepAdaptor_Curve(e)
        f0, f1 = cv.FirstParameter(), cv.LastParameter()
        ts = np.linspace(f0, f1, draw_n)
        pts = np.array([cv.Value(float(t)).Coord() for t in ts])
        faces = []
        for x in emap.FindFromIndex(i):
            f = TopoDS.Face_s(x)
            if not any(f.IsSame(g) for g in faces):
                faces.append(f)
        fids = [fmap.FindIndex(f) for f in faces]
        angle, cls = None, ''
        if len(faces) == 1:
            cls = 'closed_surface_seam' if BRep_Tool.IsClosed_s(e, faces[0]) else 'free'
        elif len(faces) == 2:
            tn = np.linspace(f0, f1, ns)
            n0, n1 = face_normals(e, faces[0], tn), face_normals(e, faces[1], tn)
            dots = np.clip(np.einsum('ij,ij->i', n0, n1), -1.0, 1.0)
            ang = np.degrees(np.arccos(dots[np.isfinite(dots)])) if np.isfinite(dots).any() else np.array([])
            if len(ang) == 0:
                cls = 'normal_undefined'
            else:
                angle = float(ang.max())
                cls = 'smooth_seam' if angle <= g1_tol else 'crease'
        else:
            cls = 'non_manifold'
        edges.append({'id': i, 'class': cls, 'faces': fids, 'g1_max_deg': angle, 'length_mm': float(GCPnts_AbscissaPoint.Length_s(cv)),
                      'curve': str(cv.GetType()).split('.')[-1], 'mid': [float(v) for v in pts[len(pts) // 2]],
                      'bbox': [float(v) for v in np.r_[pts.min(0), pts.max(0)]], '_pts': pts})
    defect = {'smooth_seam', 'free', 'non_manifold', 'normal_undefined'}
    flag_all = prm['flag'] == 'all'
    # face coverage per band from the tessellation (independent of the edges)
    m = mesh0
    V, T, FID = m['V'], m['T'], m['FID']
    flist = L.faces(shape)
    fid_map = np.array([fmap.FindIndex(f) for f in flist])[FID]
    TV = V[T]                                                       # (nT, 3, 3)
    rows, flagged_ids = [], set()
    for b in bands:
        a = AXES[b['axis']]
        lo, hi = b['range']
        cover = (TV[:, :, a].max(1) >= lo - tol) & (TV[:, :, a].min(1) <= hi + tol)
        if b.get('along_axis'):
            c = AXES[b['along_axis']]
            lo2, hi2 = b['along_range']
            cover &= (TV[:, :, c].max(1) >= lo2 - tol) & (TV[:, :, c].min(1) <= hi2 + tol)
        cover_faces = sorted({int(x) for x in np.unique(fid_map[cover])})
        inb = [e for e in edges if in_band(e['_pts'], b, tol)]
        flag = [e for e in inb if flag_all or e['class'] in defect]
        flagged_ids.update(e['id'] for e in flag)
        by_class: dict[str, int] = {}
        for e in inb:
            by_class[e['class']] = by_class.get(e['class'], 0) + 1
        rows.append({'name': b['name'], 'axis': b['axis'], 'range': b['range'], 'along_axis': b.get('along_axis'), 'along_range': b.get('along_range'),
                     'edges_in_band': len(inb), 'by_class': by_class, 'flagged_edges': len(flag), 'faces_in_band': len(cover_faces),
                     'faces_with_edge_in_band': len({f for e in inb for f in e['faces']}),
                     'flagged_length_mm': float(sum(e['length_mm'] for e in flag)),
                     'edges': [{k: v for k, v in e.items() if k != '_pts'} | {'flagged': e in flag} for e in inb[:prm['max_listed']]],
                     'edges_truncated': max(0, len(inb) - prm['max_listed'])})
    totals = {}
    for e in edges:
        totals[e['class']] = totals.get(e['class'], 0) + 1
    png = plot(out / 'seam_plan.png', edges, flagged_ids, bands, prm['view'], f'{name}: {len(flagged_ids)} flagged edges')
    return {'files': {'seam_plan.png': 'seam_plan.png'} if png else {}, 'part': name, 'totals': {'faces': n_faces, 'edges': n_edges, 'degenerate_edges': degenerate,
            'by_class': totals, 'seam_like_edges_all': totals.get('smooth_seam', 0)}, 'bands': rows, 'symmetry': sym, 'flagged_total': len(flagged_ids),
            'volume_mm3': L.volume(shape), 'bbox': [float(x) for x in L.bbox(shape, optimal=False)], 'seconds': round(time.time() - t0, 1), 'worker_version': WORKER_VERSION}


def plot(path: Path, edges, flagged_ids: set, bands, view: str, title: str) -> bool:
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.collections import LineCollection
    except ImportError:
        return False
    u, v = VIEWS[view]
    fig, ax = plt.subplots(figsize=(11, 7))
    segs = lambda es: [e['_pts'][:, [u, v]] for e in es]            # noqa: E731
    ax.add_collection(LineCollection(segs([e for e in edges if e['id'] not in flagged_ids]), colors='#9a9a9a', linewidths=0.4))
    fl = [e for e in edges if e['id'] in flagged_ids]
    ax.add_collection(LineCollection(segs(fl), colors='#d01010', linewidths=1.4))
    allp = np.vstack([e['_pts'][:, [u, v]] for e in edges]) if edges else np.zeros((1, 2))
    lo, hi = allp.min(0), allp.max(0)
    names = 'xyz'
    for b in bands:
        a = AXES[b['axis']]
        if a in (u, v):
            r0, r1 = b['range']
            if a == u:
                ax.axvspan(r0, r1, color='#4080ff', alpha=0.12)
            else:
                ax.axhspan(r0, r1, color='#4080ff', alpha=0.12)
    ax.set_xlim(lo[0] - 3, hi[0] + 3)
    ax.set_ylim(lo[1] - 3, hi[1] + 3)
    ax.set_aspect('equal')
    ax.set_xlabel(f'{names[u]} mm')
    ax.set_ylabel(f'{names[v]} mm')
    ax.set_title(f'{title} (red = flagged, blue = bands; {view} view, all edges projected)')
    fig.savefig(path, dpi=110, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return True


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
