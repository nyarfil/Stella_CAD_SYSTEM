"""Opaque, colour-coded section picture of chosen parts (brain_mouse_section_render). SUBPROCESS WORKER (server python: OCP + matplotlib).

Run as:  <server python> -I mouse_section_render_worker.py request.json      (result = last stdout line, JSON)

Method: every shown part is cut by the plane with the exact B-rep section (BRepAlgoAPI_Section); the section edges are sampled every curve_step_mm,
projected into the plane frame (u right, v up), chained into closed loops and filled (holes by nesting depth), so cut material is opaque and a
cavity stays white. Planes: XZ / YZ / XY with an offset along the missing axis, "axis" = the plane through a point that holds an axis direction
(v = the axis, normal given and made perpendicular), or "plane" = origin + normal + up. Dimensions are drawn as <-> arrows between 3D points
(projected into the plane; the label defaults to the true 3D distance).
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Any

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from cadmcp_brain.studio.scan_cad_common import WorkerError, worker_main
from cadmcp_brain.studio import mouse_parts_lib as P

WORKER_VERSION = 'mouse_section_render/1'
DEFAULTS = {'curve_step_mm': 0.05, 'chain_tol_mm': 0.05, 'margin_mm': 3.0, 'dpi': 150}
PALETTE = ['#e08a3c', '#2ca02c', '#3b6fd8', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']


def _unit(v, what):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    if v.shape != (3,) or not np.isfinite(n) or n < 1e-9:
        raise WorkerError('SECTION_PLANE', f'{what} must be a non-zero 3-vector.', {'given': list(map(float, v.ravel()))})
    return v / n


def plane_frame(pl: dict[str, Any]) -> dict[str, Any]:
    """-> origin, normal, u (right), v (up), axis labels."""
    kind = pl['kind']
    off = float(pl.get('offset', 0.0))
    if kind == 'XZ':
        return dict(o=np.array([0, off, 0.0]), n=np.array([0, 1.0, 0]), u=np.array([1.0, 0, 0]), v=np.array([0, 0, 1.0]), lu='x', lv='z')
    if kind == 'YZ':
        return dict(o=np.array([off, 0, 0.0]), n=np.array([1.0, 0, 0]), u=np.array([0, 1.0, 0]), v=np.array([0, 0, 1.0]), lu='y', lv='z')
    if kind == 'XY':
        return dict(o=np.array([0, 0, off]), n=np.array([0, 0, 1.0]), u=np.array([1.0, 0, 0]), v=np.array([0, 1.0, 0]), lu='x', lv='y')
    if kind == 'axis':
        a = _unit(pl['direction'], 'direction')
        n = np.asarray(pl['normal'], float)
        n = _unit(n - (n @ a) * a, 'normal (perpendicular to the axis)')
        return dict(o=np.asarray(pl['point'], float), n=n, u=np.cross(a, n), v=a, lu='s', lv='axis')
    if kind == 'plane':
        n = _unit(pl['normal'], 'normal')
        up = np.asarray(pl.get('up', [0, 0, 1]), float)
        up = up - (up @ n) * n
        if np.linalg.norm(up) < 1e-9:
            up = np.array([1.0, 0, 0]) - n[0] * n
        v = _unit(up, 'up')
        return dict(o=np.asarray(pl['origin'], float), n=n, u=np.cross(v, n), v=v, lu='s', lv='t')
    raise WorkerError('SECTION_PLANE', 'plane.kind must be XZ, YZ, XY, axis or plane.', {'given': kind})


def section_polylines(shape, fr, step: float) -> list[np.ndarray]:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.gp import gp_Pln, gp_Pnt, gp_Dir
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_UniformAbscissa
    from cadmcp_brain.studio import cad_brep_lib as L
    sec = BRepAlgoAPI_Section(shape, gp_Pln(gp_Pnt(*map(float, fr['o'])), gp_Dir(*map(float, fr['n']))))
    sec.Build()
    if not sec.IsDone():
        raise WorkerError('SECTION_FAILED', 'The B-rep section failed.')
    segs = []
    for e in L.explore(sec.Shape(), 'edge'):
        cv = BRepAdaptor_Curve(e)
        ab = GCPnts_UniformAbscissa(cv, step)
        if ab.IsDone() and ab.NbPoints() > 1:
            Q = np.array([cv.Value(ab.Parameter(i)).Coord() for i in range(1, ab.NbPoints() + 1)])
            last = np.array(cv.Value(cv.LastParameter()).Coord())
            if np.linalg.norm(Q[-1] - last) > 1e-6:
                Q = np.vstack([Q, last])
        else:
            Q = np.array([cv.Value(cv.FirstParameter()).Coord(), cv.Value(cv.LastParameter()).Coord()])
        d = Q - fr['o']
        segs.append(np.c_[d @ fr['u'], d @ fr['v']])
    return segs


def chain(segs: list[np.ndarray], tol: float) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Join segments end to end -> (closed loops, open chains)."""
    segs = [s for s in segs if len(s) >= 2]
    loops, opens = [], []
    while segs:
        cur = list(segs.pop(0))
        while True:
            if len(cur) > 2 and np.linalg.norm(cur[0] - cur[-1]) <= tol:
                break
            best = None
            for j, s in enumerate(segs):
                for rev in (False, True):
                    q = s[::-1] if rev else s
                    d = np.linalg.norm(q[0] - cur[-1])
                    if best is None or d < best[0]:
                        best = (d, j, q)
            if best is None or best[0] > tol:
                break
            cur += list(best[2][1:])
            segs.pop(best[1])
        a = np.array(cur)
        (loops if len(a) > 2 and np.linalg.norm(a[0] - a[-1]) <= tol else opens).append(a)
    return loops, opens


def signed_area(p: np.ndarray) -> float:
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def fill_path(loops: list[np.ndarray]):
    from matplotlib.path import Path as MPath
    lp = [l for l in loops if abs(signed_area(l)) > 1e-6]
    if not lp:
        return None
    paths = [MPath(l) for l in lp]
    verts, codes = [], []
    for i, l in enumerate(lp):
        depth = sum(1 for j, m in enumerate(paths) if j != i and abs(signed_area(lp[j])) > abs(signed_area(l)) and m.contains_point(l[0]))
        want_ccw = depth % 2 == 0
        l = l if (signed_area(l) > 0) == want_ccw else l[::-1]
        verts += list(l) + [l[0]]
        codes += [MPath.MOVETO] + [MPath.LINETO] * (len(l) - 1) + [MPath.CLOSEPOLY]
    return MPath(np.array(verts), codes)


def _darker(c):
    from matplotlib.colors import to_rgb
    return tuple(0.45 * x for x in to_rgb(c))


def run(req: dict[str, Any]) -> dict[str, Any]:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch, Patch
    prm = {**DEFAULTS, **{k: v for k, v in req['params'].items() if k in DEFAULTS}}
    paths = [req['inputs'][k] for k in sorted(req['inputs'], key=lambda s: int(s.split('_')[1]))]
    parts, table = P.load_parts(paths, req['params'].get('groups'))
    show = req['params'].get('parts') or list(parts)
    P.require(parts, show, 'parts')
    fr = plane_frame(req['params']['plane'])
    colors = req['params'].get('colors') or {}
    fig, ax = plt.subplots(figsize=tuple(req['params'].get('figsize') or (16, 10)))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')
    rep, handles, ext = [], [], []
    for i, nm in enumerate(show):
        col = colors.get(nm) or PALETTE[i % len(PALETTE)]
        loops, opens = chain(section_polylines(parts[nm], fr, prm['curve_step_mm']), prm['chain_tol_mm'])
        pth = fill_path(loops)
        if pth is not None:
            ax.add_patch(PathPatch(pth, fc=col, ec=_darker(col), lw=0.6, zorder=2 + i))
            ext.append(pth.vertices)
        for o in opens:
            ax.plot(o[:, 0], o[:, 1], color=_darker(col), lw=1.0, zorder=10)
            ext.append(o)
        area = sum(abs(signed_area(l)) for l in loops)
        rep.append({'part': nm, 'color': col, 'closed_loops': len(loops), 'open_chains': len(opens), 'cut': bool(loops or opens),
                    'loop_area_sum_mm2': round(area, 3)})
        handles.append(Patch(fc=col, ec=_darker(col), label=nm + ('' if loops or opens else '  (not cut by this plane)')))
    dims = []
    for d in req['params'].get('dimensions') or []:
        a, b = np.asarray(d['from'], float), np.asarray(d['to'], float)
        pa, pb = [np.array([(x - fr['o']) @ fr['u'], (x - fr['o']) @ fr['v']]) for x in (a, b)]
        dist = float(np.linalg.norm(b - a))
        lab = d.get('label') or f'{dist:.2f}'
        col = d.get('color', 'black')
        ax.annotate('', xy=tuple(pb), xytext=tuple(pa), arrowprops=dict(arrowstyle='<->', color=col, lw=1.3), zorder=20)
        mid = (pa + pb) / 2
        ax.text(mid[0], mid[1], ' ' + lab, color=col, fontsize=11, zorder=21, va='bottom')
        dims.append({'label': lab, 'distance_3d_mm': round(dist, 3), 'off_plane_mm': [round(float((x - fr['o']) @ fr['n']), 3) for x in (a, b)]})
        ext.append(np.array([pa, pb]))
    win = req['params'].get('window')
    if win:
        ax.set_xlim(win[0], win[1])
        ax.set_ylim(win[2], win[3])
    elif ext:
        E = np.vstack(ext)
        m = prm['margin_mm']
        ax.set_xlim(E[:, 0].min() - m, E[:, 0].max() + m)
        ax.set_ylim(E[:, 1].min() - m, E[:, 1].max() + m)
    ax.set_aspect('equal')
    ax.grid(alpha=0.3)
    ax.set_xlabel(f"{fr['lu']} [mm]", fontsize=12)
    ax.set_ylabel(f"{fr['lv']} [mm]", fontsize=12)
    ax.legend(handles=handles, loc='upper right', fontsize=11)
    pl = req['params']['plane']
    title = req['params'].get('title') or (f"{pl['kind']} section, offset {float(pl.get('offset', 0.0)):.3f} mm" if pl['kind'] in ('XZ', 'YZ', 'XY')
                                           else f"{pl['kind']} section through {np.round(fr['o'], 3).tolist()}")
    ax.set_title(title, fontsize=14)
    out = Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out / 'section.png', dpi=int(prm['dpi']), facecolor='white')
    plt.close(fig)
    return {'parts_shown': rep, 'parts': table, 'plane': {'kind': pl['kind'], 'origin': fr['o'].tolist(), 'normal': fr['n'].tolist(), 'u': fr['u'].tolist(),
            'v': fr['v'].tolist(), 'axis_labels': [fr['lu'], fr['lv']]}, 'dimensions': dims, 'settings_used': prm, 'files': {'section_png': 'section.png'},
            'worker_version': WORKER_VERSION}


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
