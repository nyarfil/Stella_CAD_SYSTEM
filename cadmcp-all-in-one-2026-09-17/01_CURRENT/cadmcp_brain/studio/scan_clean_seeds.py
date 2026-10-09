"""Groove seed curves from region labels (numpy / scipy only; runs in the server process).

A seed is a rough 3D polyline (about 1 mm spacing, position error up to a few tenths of a mm) near a groove the scan under-resolves.
The worker (scan_clean_worker.py) refines each seed against the mesh; a seed that does not lie on a measurable groove is reported
and the surface is left unchanged there. Seeds come from boundaries between recognized regions (brain_mouse_recognize_regions):
  gap  : left click | right click (one chain)
  rim  : click | palm or click | other, away from the wheel; long chains are split at corners
  pad  : every boundary of a side-button pad (closed loop around the pad when the ring is complete)
The wheel pocket is a real feature and is excluded (wheel_clear_mm).
"""
from __future__ import annotations
from typing import Any
import numpy as np
import scipy.sparse as sp
import scipy.sparse.csgraph as cg
from scipy.spatial import cKDTree

LC, RC, WHEEL, B1, B2, PALM, OTHER = 1, 2, 3, 4, 5, 6, 0
MIN_POINTS = 15
LINK_MM = 1.0
CORNER_DEG = 70.0


def boundary_edge_midpoints(v: np.ndarray, f: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Midpoints of mesh edges whose two faces carry different labels, the two labels (low, high) and the edge vertex pairs."""
    nf = len(f)
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    fi = np.tile(np.arange(nf), 3)
    key = np.sort(e, axis=1)
    order = np.lexsort((key[:, 1], key[:, 0]))
    k, fo = key[order], fi[order]
    same = (k[0::2] == k[1::2]).all(1)
    fa, fb, ea = fo[0::2][same], fo[1::2][same], k[0::2][same]
    diff = labels[fa] != labels[fb]
    fa, fb, ea = fa[diff], fb[diff], ea[diff]
    mid = 0.5 * (v[ea[:, 0]] + v[ea[:, 1]])
    la, lb = labels[fa], labels[fb]
    return mid, np.minimum(la, lb), np.maximum(la, lb), ea


def _components(pts: np.ndarray) -> list[np.ndarray]:
    if len(pts) < 2:
        return []
    pairs = cKDTree(pts).query_pairs(LINK_MM, output_type='ndarray')
    g = sp.coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(pts), len(pts)))
    n, lab = cg.connected_components(g, directed=False)
    return [np.flatnonzero(lab == c) for c in range(n) if (lab == c).sum() >= MIN_POINTS]


def _resample(path: np.ndarray, step: float, closed: bool) -> np.ndarray:
    p = np.vstack([path, path[:1]]) if closed else path
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]
    n = max(int(s[-1] / step), 3)
    t = np.linspace(0, s[-1], n, endpoint=not closed)
    return np.stack([np.interp(t, s, p[:, k]) for k in range(3)], 1)


def _smooth(path: np.ndarray, width_pts: int, closed: bool) -> np.ndarray:
    if len(path) < 2 * width_pts + 1:
        return path
    k = np.ones(2 * width_pts + 1) / (2 * width_pts + 1)
    out = np.empty_like(path)
    for c in range(3):
        if closed:
            x = np.r_[path[-width_pts:, c], path[:, c], path[:width_pts, c]]
            out[:, c] = np.convolve(x, k, 'valid')
        else:
            x = np.r_[np.full(width_pts, path[0, c]), path[:, c], np.full(width_pts, path[-1, c])]
            out[:, c] = np.convolve(x, k, 'valid')
    return out


def _longest_path(pts: np.ndarray) -> np.ndarray:
    """Points of the longest geodesic chain through a point set (k-nearest graph, double sweep)."""
    tree = cKDTree(pts)
    d, idx = tree.query(pts, k=min(8, len(pts)))
    rows = np.repeat(np.arange(len(pts)), idx.shape[1])
    keep = d.reshape(-1) <= 1.6 * LINK_MM
    g = sp.coo_matrix((d.reshape(-1)[keep] + 1e-9, (rows[keep], idx.reshape(-1)[keep])), shape=(len(pts), len(pts)))
    g = g.maximum(g.T).tocsr()
    d0 = cg.dijkstra(g, indices=0)
    a = int(np.argmax(np.where(np.isfinite(d0), d0, -1)))
    da, pred = cg.dijkstra(g, indices=a, return_predecessors=True)
    b = int(np.argmax(np.where(np.isfinite(da), da, -1)))
    path = [b]
    while path[-1] != a and pred[path[-1]] >= 0:
        path.append(int(pred[path[-1]]))
    return pts[path[::-1]]


def _split_corners(path: np.ndarray, step: float = 1.0) -> list[np.ndarray]:
    n = len(path)
    w = int(round(3.0 / step))
    if n < 2 * w + 3:
        return [path]
    cut = []
    for i in range(w, n - w):
        a, b = path[i] - path[i - w], path[i + w] - path[i]
        c = float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
        if np.degrees(np.arccos(np.clip(c, -1, 1))) > CORNER_DEG:
            cut.append(i)
    if not cut:
        return [path]
    groups, cur = [], [cut[0]]
    for i in cut[1:]:
        if i - cur[-1] <= w:
            cur.append(i)
        else:
            groups.append(cur)
            cur = [i]
    groups.append(cur)
    idx = [int(np.mean(g)) for g in groups]
    bounds = [0] + idx + [n - 1]
    return [path[a:b + 1] for a, b in zip(bounds[:-1], bounds[1:])]


def _euler_ring(edges: np.ndarray) -> np.ndarray | None:
    """Closed vertex sequence through a set of mesh edges when they form ONE connected closed boundary (every vertex has an even
    degree); None otherwise. A pinch vertex (degree 4) is passed twice."""
    deg = np.bincount(edges.ravel())
    if (deg % 2).any():
        return None
    adj: dict[int, list[int]] = {}
    for a, b in edges.tolist():
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    start = int(edges[0, 0])
    stack, ring = [start], []
    while stack:
        u = stack[-1]
        if adj[u]:
            w = adj[u].pop()
            adj[w].remove(u)
            stack.append(w)
        else:
            ring.append(stack.pop())
    if len(ring) != len(edges) + 1:       # more than one connected piece
        return None
    return np.array(ring[:-1])


def seeds_from_regions(v: np.ndarray, f: np.ndarray, labels: np.ndarray, wheel_clear_mm: float = 2.5, min_length_mm: float = 8.0) -> list[dict[str, Any]]:
    """Seeds as [{'name', 'kind': 'open'|'loop', 'closed', 'source', 'points': [[x, y, z], ...]}]; deterministic order."""
    mid, lo, hi, ev = boundary_edge_midpoints(v, f, labels)
    cen = v[f].mean(1)
    wheel = cen[labels == WHEEL]
    if len(wheel):
        far = cKDTree(wheel).query(mid)[0] > wheel_clear_mm
    else:
        far = np.ones(len(mid), bool)
    rim = ((lo == OTHER) & ((hi == LC) | (hi == RC))) | (((lo == LC) | (lo == RC)) & (hi == PALM))     # click | other, click | palm
    classes: list[tuple[str, np.ndarray]] = [('gap', (lo == LC) & (hi == RC)), ('rim', rim), ('pad1', (lo == B1) | (hi == B1)), ('pad2', (lo == B2) | (hi == B2))]
    out: list[dict[str, Any]] = []
    for cname, m in classes:
        sel = m & far
        pts = mid[sel]
        if cname.startswith("pad") and sel.any() and sel.sum() == m.sum():
            ring = _euler_ring(ev[sel])
            if ring is not None:
                rp = _smooth(_resample(v[ring], 1.0, True), 2, True)
                length = float(np.linalg.norm(np.diff(np.vstack([rp, rp[:1]]), axis=0), axis=1).sum())
                if length >= min_length_mm:
                    out.append({'name': f'{cname}_loop', 'kind': 'loop', 'closed': True, 'source': f'closed region boundary {cname}', 'points': rp.round(4).tolist()})
                continue
        for ci, comp in enumerate(_components(pts)):
            cp = pts[comp]
            path = _longest_path(cp)
            path = _smooth(_resample(path, 1.0, False), 2, False)
            pieces = _split_corners(path) if cname == 'rim' else [path]
            for pi, pc in enumerate(pieces):
                length = float(np.linalg.norm(np.diff(pc, axis=0), axis=1).sum()) if len(pc) > 1 else 0.0
                if length >= min_length_mm:
                    nm = f'{cname}{ci}' if len(pieces) == 1 else f'{cname}{ci}_{pi}'
                    out.append({'name': nm, 'kind': 'open', 'closed': False, 'source': f'region boundary {cname}', 'points': pc.round(4).tolist()})
    return out
