"""Printed-wall audit of a shell solid (brain_mouse_wall_audit). SUBPROCESS WORKER (server python: OCP + vtk, extra `geometry`; matplotlib for PNGs).

Run as:  <server python> -I mouse_wall_audit_worker.py request.json      (result = last stdout line, JSON)

Method: the solid is tessellated (outward triangles). Points are sampled uniformly by area (seeded) with their triangle normal; from each point a ray
runs INTO the solid along the inward surface normal and the first exit is the local wall thickness (vtkOBBTree). This is the skin-normal thickness,
not a vertical or horizontal section. Statistics are over the samples (= area weighted): min / p5 / median / p95 / max, the dominant wall (histogram
mode), the share near the target T, thick zones (> T + max_over_mm: posts, ribs, bosses) and thin zones (< T - tol_mm), and the share of walls
that are not a multiple of the extrusion line width (0.4 mm). Mass = closed-mesh volume x density (ABS 1.04 g/cm3 by default); the exact B-rep
volume is reported next to it.
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

WORKER_VERSION = 'mouse_wall_audit/1'
DEFAULTS = {'line_width_mm': 0.4, 'tol_mm': 0.05, 'max_over_mm': 0.2, 'density_g_cm3': 1.04, 'samples': 40000, 'deflection_mm': 0.02,
            'max_ray_mm': 60.0, 'seed': 0, 'zone_grid_mm': 3.0}
EPS = 1e-4


def sample_surface(V: np.ndarray, T: np.ndarray, n: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    cr = np.cross(b - a, c - a)
    ar = np.linalg.norm(cr, axis=1)
    ok = ar > 1e-12
    a, b, c, cr, ar = a[ok], b[ok], c[ok], cr[ok], ar[ok]
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(ar), size=n, p=ar / ar.sum())
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    pts = (1 - s)[:, None] * a[idx] + (s * (1 - r2))[:, None] * b[idx] + (s * r2)[:, None] * c[idx]
    return pts, cr[idx] / ar[idx][:, None]


def ray_thickness(V: np.ndarray, T: np.ndarray, pts: np.ndarray, nrm: np.ndarray, max_ray: float) -> np.ndarray:
    import vtk
    tree = vtk.vtkOBBTree()
    tree.SetDataSet(P.polydata(V, T))
    tree.SetTolerance(1e-7)
    tree.BuildLocator()
    hit = vtk.vtkPoints()
    out = np.full(len(pts), np.nan)
    p0s = pts - nrm * EPS
    p1s = pts - nrm * max_ray
    for i in range(len(pts)):
        hit.Reset()
        if tree.IntersectWithLine(p0s[i], p1s[i], hit, None) != 0 and hit.GetNumberOfPoints():
            d = np.linalg.norm(np.array([hit.GetPoint(k) for k in range(hit.GetNumberOfPoints())]) - pts[i], axis=1)
            d = d[d > 2 * EPS]
            if len(d):
                out[i] = d.min()
    return out


def zones(pts: np.ndarray, t: np.ndarray, mask: np.ndarray, grid: float, kind: str, limit: int = 20) -> list[dict[str, Any]]:
    """Group flagged samples on a coarse grid -> [{centre, extreme thickness, samples}] (largest groups first)."""
    if not mask.any():
        return []
    q = np.floor(pts[mask] / grid).astype(np.int64)
    keys, inv, cnt = np.unique(q, axis=0, return_inverse=True, return_counts=True)
    inv = inv.ravel()
    out = []
    tm, pm = t[mask], pts[mask]
    for k in np.argsort(-cnt)[:limit]:
        m = inv == k
        ext = float(tm[m].max() if kind == 'thick' else tm[m].min())
        out.append({'centre': np.round(pm[m].mean(0), 2).tolist(), f'{"max" if kind == "thick" else "min"}_mm': round(ext, 3), 'samples': int(cnt[k])})
    return out


def run(req: dict[str, Any]) -> dict[str, Any]:
    prm = {**DEFAULTS, **{k: v for k, v in req['params'].items() if k in DEFAULTS}}
    T_ = float(req['params']['target_thickness_mm'])
    parts, table = P.load_parts([req['inputs']['shell']])
    name = req['params'].get('part')
    if name is None:
        if len(parts) != 1:
            raise WorkerError('WALL_AUDIT_PART', 'The STEP file holds several parts; name the one to audit with part.', {'parts': sorted(parts)})
        name = next(iter(parts))
    P.require(parts, [name], 'part')
    shape = parts[name]
    V, Tri = P.mesh(shape, prm['deflection_mm'], 0.1)
    vol_mesh = abs(P.mesh_volume(V, Tri))
    vol_brep = abs(P.volume(shape))
    pts, nrm = sample_surface(V, Tri, int(prm['samples']), int(prm['seed']))
    t = ray_thickness(V, Tri, pts, nrm, float(prm['max_ray_mm']))
    miss = np.isnan(t)
    ok = ~miss
    tv, pv = t[ok], pts[ok]
    if len(tv) < 0.5 * len(t):
        raise WorkerError('WALL_AUDIT_OPEN', 'Most inward rays found no exit: the solid is open or inside out.', {'missed': int(miss.sum()), 'samples': len(t)})
    tol, lw = prm['tol_mm'], prm['line_width_mm']
    bins = np.arange(0.0, min(float(tv.max()), 20.0) + 2 * tol, 2 * tol)
    hist, edges = np.histogram(tv, bins=bins) if len(bins) > 1 else (np.array([len(tv)]), np.array([0.0, tv.max()]))
    k = int(np.argmax(hist))
    mode = float(np.median(tv[(tv >= edges[k]) & (tv <= edges[k + 1])]))
    near = np.abs(tv - T_) <= tol
    thick = tv > T_ + prm['max_over_mm']
    thin = tv < T_ - tol
    resid = np.abs(tv - np.round(tv / lw) * lw)
    off_grid = resid > tol
    pct = lambda m: round(100.0 * float(m.mean()), 2)  # noqa: E731
    stats = {'min_mm': round(float(tv.min()), 3), 'p5_mm': round(float(np.percentile(tv, 5)), 3), 'median_mm': round(float(np.median(tv)), 3),
             'p95_mm': round(float(np.percentile(tv, 95)), 3), 'max_mm': round(float(tv.max()), 3), 'mode_mm': round(mode, 3),
             'near_target_pct': pct(near), 'thick_pct': pct(thick), 'thin_pct': pct(thin), 'off_line_width_grid_pct': pct(off_grid),
             'samples': int(len(t)), 'rays_without_exit': int(miss.sum())}
    mode_mult = abs(mode - round(mode / lw) * lw) <= tol
    target_mult = abs(T_ - round(T_ / lw) * lw) <= 1e-6
    checks = {'dominant_wall_is_target': 'PASS' if abs(mode - T_) <= tol else 'FAIL',
              'target_is_line_width_multiple': 'PASS' if target_mult else 'FAIL',
              'dominant_wall_is_line_width_multiple': 'PASS' if mode_mult else 'FAIL',
              'p95_within_target_plus_max_over': 'PASS' if stats['p95_mm'] <= T_ + prm['max_over_mm'] + 1e-9 else 'WARN',
              'max_within_target_plus_max_over': 'PASS' if stats['max_mm'] <= T_ + prm['max_over_mm'] + 1e-9 else 'WARN',
              'no_thin_wall': 'PASS' if stats['p5_mm'] >= T_ - tol else 'WARN'}
    mass = {'density_g_cm3': prm['density_g_cm3'], 'mesh_volume_mm3': round(vol_mesh, 2), 'brep_volume_mm3': round(vol_brep, 2),
            'mass_g': round(vol_mesh * prm['density_g_cm3'] / 1000.0, 3)}
    out = Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    np.savez_compressed(out / 'thickness_samples.npz', points=pv.astype(np.float32), thickness=tv.astype(np.float32))
    files['samples_npz'] = 'thickness_samples.npz'
    if heatmap(out / 'wall_heatmap.png', pv, tv, T_, prm, stats, name):
        files['heatmap_png'] = 'wall_heatmap.png'
    return {'part': name, 'parts': table, 'target_thickness_mm': T_, 'stats': stats, 'checks': checks, 'mass': mass,
            'thick_zones': zones(pv, tv, thick, prm['zone_grid_mm'], 'thick'), 'thin_zones': zones(pv, tv, thin, prm['zone_grid_mm'], 'thin'),
            'histogram': {'bin_mm': 2 * tol, 'edges': np.round(edges, 3).tolist(), 'counts': hist.tolist()},
            'settings_used': prm, 'files': files, 'worker_version': WORKER_VERSION}


def heatmap(path: Path, pts: np.ndarray, t: np.ndarray, T_: float, prm: dict[str, Any], stats: dict[str, Any], name: str) -> bool:
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    lo, hi = max(0.0, T_ - 0.4), T_ + 0.8
    views = [('top (XY, seen from +Z)', 0, 1, 2, 1), ('bottom (XY, seen from -Z)', 0, 1, 2, -1), ('side (XZ, seen from -Y)', 0, 2, 1, 1),
             ('front (YZ, seen from +X)', 1, 2, 0, 1)]
    fig, axs = plt.subplots(2, 3, figsize=(20, 11), gridspec_kw={'width_ratios': [1, 1, 0.8]})
    fig.patch.set_facecolor('white')
    sc = None
    for ax, (title, i, j, k, sgn) in zip([axs[0, 0], axs[0, 1], axs[1, 0], axs[1, 1]], views):
        order = np.argsort(sgn * pts[:, k])                      # far side first, near side drawn on top
        sc = ax.scatter(pts[order, i], pts[order, j], c=np.clip(t[order], lo, hi), cmap='turbo', vmin=lo, vmax=hi, s=1.2, linewidths=0)
        ax.set_aspect('equal')
        ax.set_title(title)
        ax.set_xlabel('xyz'[i] + ' [mm]')
        ax.set_ylabel('xyz'[j] + ' [mm]')
        ax.grid(alpha=0.3)
    fig.colorbar(sc, ax=[axs[0, 0], axs[0, 1], axs[1, 0], axs[1, 1]], label=f'wall thickness along the surface normal [mm] (clipped {lo:.1f}-{hi:.1f})',
                 shrink=0.8)
    h = axs[0, 2]
    h.hist(np.clip(t, 0, T_ + 3), bins=np.arange(0, T_ + 3 + 0.05, 0.05), color='#3b6fd8')
    h.axvline(T_, color='red', ls='--', label=f'target {T_:.2f}')
    h.axvline(T_ + prm['max_over_mm'], color='orange', ls=':', label=f'target + {prm["max_over_mm"]:.2f}')
    h.set_xlabel('thickness [mm] (clipped)')
    h.set_ylabel('samples')
    h.legend()
    h.set_title('thickness histogram (area weighted)')
    axs[1, 2].axis('off')
    txt = '\n'.join([f'part: {name}', f'target T = {T_:.2f} mm', f"dominant wall {stats['mode_mm']:.3f}", f"min {stats['min_mm']:.3f}  p5 {stats['p5_mm']:.3f}",
                     f"median {stats['median_mm']:.3f}  p95 {stats['p95_mm']:.3f}", f"max {stats['max_mm']:.3f}", f"near T: {stats['near_target_pct']:.1f} %",
                     f"thick (> T+{prm['max_over_mm']:.1f}): {stats['thick_pct']:.1f} %", f"thin (< T-{prm['tol_mm']:.2f}): {stats['thin_pct']:.1f} %",
                     f"not a multiple of {prm['line_width_mm']:.1f}: {stats['off_line_width_grid_pct']:.1f} %"])
    axs[1, 2].text(0.0, 1.0, txt, va='top', family='monospace', fontsize=12)
    fig.suptitle('Wall audit: skin-normal ray thickness', fontsize=15)
    fig.savefig(path, dpi=110, facecolor='white')
    plt.close(fig)
    return True


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
