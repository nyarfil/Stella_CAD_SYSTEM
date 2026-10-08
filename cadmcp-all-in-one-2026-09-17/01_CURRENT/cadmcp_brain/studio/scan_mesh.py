"""Pure numpy/scipy triangle-mesh tools for scan -> shell stage A1.

Reading, welding, inspection, allow-listed repairs, exact point-to-triangle distance,
ray-parity inside test, signed distance field and surface-nets extraction. No CAD kernel here.
Nothing is rescaled or repaired unless the caller asks for it; every operation reports numbers.
"""
from __future__ import annotations
import io
import re
import zipfile
from collections import deque
from pathlib import Path
import numpy as np
from scipy import ndimage
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from ..errors import BrainError

UNIT_MM = {'mm': 1.0, 'cm': 10.0, 'm': 1000.0, 'in': 25.4}
MAX_MESH_BYTES = 400 * 1024 * 1024
JITTER = (3.1415926e-6, 2.7182818e-6)  # fixed, deterministic sub-micron ray offsets (mm)


# ---------------------------------------------------------------- reading / npz
def read_mesh(path: Path) -> tuple[np.ndarray, np.ndarray]:
    if path.is_symlink() or not path.is_file():
        raise BrainError('SCAN_FILE', 'Scan must be a regular workspace file.')
    if path.stat().st_size > MAX_MESH_BYTES:
        raise BrainError('SCAN_FILE', 'Scan file is too large.')
    suffix = path.suffix.lower()
    data = path.read_bytes()
    try:
        if suffix == '.stl':
            tris = _stl(data)
            v, inv = np.unique(tris.reshape(-1, 3), axis=0, return_inverse=True)
            return v.astype(np.float64), inv.reshape(-1, 3).astype(np.int64)
        if suffix == '.obj':
            return _obj(data.decode('utf-8', errors='strict'))
    except BrainError:
        raise
    except Exception as exc:
        raise BrainError('SCAN_FILE', f'Scan could not be parsed: {type(exc).__name__}.') from exc
    raise BrainError('SCAN_FILE', 'Only .stl (binary or ASCII) and .obj scans are supported.')


def _stl(data: bytes) -> np.ndarray:
    if len(data) >= 84:
        n = int(np.frombuffer(data, '<u4', 1, 80)[0])
        if len(data) == 84 + 50 * n and n > 0:
            rec = np.frombuffer(data, np.dtype([('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')]), n, 84)
            return rec['v'].astype(np.float64)
    text = data.decode('ascii', errors='strict')
    nums = re.findall(r'vertex\s+(\S+)\s+(\S+)\s+(\S+)', text)
    if not nums or len(nums) % 3:
        raise BrainError('SCAN_FILE', 'STL is neither valid binary nor ASCII.')
    return np.array(nums, dtype=np.float64).reshape(-1, 3, 3)


def _obj(text: str) -> tuple[np.ndarray, np.ndarray]:
    vs, fs = [], []
    for line in text.splitlines():
        p = line.split()
        if not p:
            continue
        if p[0] == 'v':
            vs.append([float(x) for x in p[1:4]])
        elif p[0] == 'f':
            idx = [int(t.split('/')[0]) for t in p[1:]]
            idx = [i - 1 if i > 0 else len(vs) + i for i in idx]
            fs.extend([idx[0], idx[k], idx[k + 1]] for k in range(1, len(idx) - 1))
    if not vs or not fs:
        raise BrainError('SCAN_FILE', 'OBJ has no vertices or faces.')
    v, f = np.array(vs, dtype=np.float64), np.array(fs, dtype=np.int64)
    if f.min() < 0 or f.max() >= len(v) or not np.isfinite(v).all():
        raise BrainError('SCAN_FILE', 'OBJ indices or coordinates are invalid.')
    return v, f


def npz_bytes(**arrays: np.ndarray) -> bytes:
    """Deterministic .npz (fixed zip timestamps) so identical arrays give an identical file hash."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:
        for name in sorted(arrays):
            b = io.BytesIO()
            np.save(b, np.ascontiguousarray(arrays[name]), allow_pickle=False)
            z.writestr(zipfile.ZipInfo(name + '.npy', (1980, 1, 1, 0, 0, 0)), b.getvalue())
    return buf.getvalue()


# ---------------------------------------------------------------- basic geometry
def areas(v: np.ndarray, f: np.ndarray) -> np.ndarray:
    return 0.5 * np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]]), axis=1)


def signed_volume(v: np.ndarray, f: np.ndarray) -> float:
    return float(np.einsum('ij,ij->i', v[f[:, 0]], np.cross(v[f[:, 1]], v[f[:, 2]])).sum() / 6.0)


def weld(v: np.ndarray, f: np.ndarray, tol: float) -> tuple[np.ndarray, np.ndarray, float]:
    """Merge vertices closer than tol (single-linkage). Returns mesh and max vertex displacement."""
    if tol <= 0 or len(v) == 0:
        return v, f, 0.0
    pairs = cKDTree(v).query_pairs(tol, output_type='ndarray')
    n = len(v)
    g = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n)) if len(pairs) else coo_matrix((n, n))
    _, lab = connected_components(g, directed=False)
    first = np.full(lab.max() + 1, n, dtype=np.int64)
    np.minimum.at(first, lab, np.arange(n))
    rep = first[lab]
    disp = float(np.linalg.norm(v - v[rep], axis=1).max())
    keep = np.unique(rep)
    remap = np.full(n, -1, dtype=np.int64)
    remap[keep] = np.arange(len(keep))
    return v[keep], remap[rep][f], disp


def compact(v: np.ndarray, f: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    used = np.unique(f)
    remap = np.full(len(v), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    return v[used], remap[f]


def edge_table(f: np.ndarray):
    d = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    key = np.sort(d, axis=1)
    uk, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    return d, uk, inv.reshape(-1), cnt


def face_components(f: np.ndarray, nv: int) -> tuple[int, np.ndarray]:
    a = np.concatenate([f[:, 0], f[:, 1]])
    b = np.concatenate([f[:, 1], f[:, 2]])
    g = coo_matrix((np.ones(len(a)), (a, b)), shape=(nv, nv))
    n, lab = connected_components(g, directed=False)
    return n, lab[f[:, 0]]


def boundary_loops(v: np.ndarray, f: np.ndarray) -> list[list[int]]:
    d, uk, inv, cnt = edge_table(f)
    bnd = d[cnt[inv] == 1]
    nxt: dict[int, list[int]] = {}
    for a, b in bnd.tolist():
        nxt.setdefault(a, []).append(b)
    loops, seen = [], set()
    for a0 in sorted(nxt):
        for b0 in list(nxt[a0]):
            if (a0, b0) in seen:
                continue
            loop, a, b = [a0], a0, b0
            seen.add((a, b))
            while b != a0:
                loop.append(b)
                opts = [x for x in nxt.get(b, []) if (b, x) not in seen]
                if not opts:
                    break
                a, b = b, opts[0]
                seen.add((a, b))
            loops.append(loop)
    return loops


def loop_perimeter(v: np.ndarray, loop: list[int]) -> float:
    p = v[loop]
    return float(np.linalg.norm(p - np.roll(p, -1, axis=0), axis=1).sum())


def inspect(v: np.ndarray, f: np.ndarray) -> dict:
    """Topology and metrics of a welded indexed mesh. Self-intersection is NOT checked."""
    n_vert = int(len(np.unique(f))) if len(f) else 0
    d, uk, inv, cnt = edge_table(f) if len(f) else (np.zeros((0, 2), int), np.zeros((0, 2), int), np.zeros(0, int), np.zeros(0, int))
    ar = areas(v, f) if len(f) else np.zeros(0)
    diag = float(np.linalg.norm(v.max(0) - v.min(0))) if len(v) else 0.0
    deg = (ar <= max(1e-12, (1e-9 * diag) ** 2)) | (f[:, 0] == f[:, 1]) | (f[:, 1] == f[:, 2]) | (f[:, 0] == f[:, 2]) if len(f) else np.zeros(0, bool)
    # orientation: an interior edge must be used once in each direction.
    inconsistent = 0
    if len(f):
        two = np.flatnonzero(cnt[inv] == 2)
        if len(two):
            order = two[np.argsort(inv[two], kind='stable')]
            pa, pb = d[order[0::2]], d[order[1::2]]
            inconsistent = int((pa[:, 0] != pb[:, 1]).sum())
    ncomp, flab = face_components(f, len(v)) if len(f) else (0, np.zeros(0, int))
    comps = []
    if len(f):
        used = np.unique(flab)
        for c in used:
            sel = flab == c
            comps.append({'triangles': int(sel.sum()), 'area_mm2': float(ar[sel].sum()), 'signed_volume_mm3': signed_volume(v, f[sel])})
    loops = boundary_loops(v, f) if len(f) and (cnt == 1).any() else []
    return {
        'triangles': int(len(f)), 'vertices': n_vert,
        'bbox_min_mm': v[np.unique(f)].min(0).tolist() if len(f) else None,
        'bbox_max_mm': v[np.unique(f)].max(0).tolist() if len(f) else None,
        'surface_area_mm2': float(ar.sum()), 'signed_volume_mm3': signed_volume(v, f) if len(f) else 0.0,
        'boundary_edges': int((cnt == 1).sum()), 'non_manifold_edges': int((cnt > 2).sum()),
        'boundary_loops': [{'vertices': len(lp), 'perimeter_mm': loop_perimeter(v, lp)} for lp in loops],
        'inconsistent_orientation_edges': inconsistent,
        'degenerate_triangles': int(deg.sum()),
        'components': comps, 'component_count': len(comps),
        'self_intersection': 'UNVERIFIED',
    }


# ---------------------------------------------------------------- allow-listed repairs
def remove_degenerate(v, f):
    ar = areas(v, f)
    diag = float(np.linalg.norm(v.max(0) - v.min(0)))
    bad = (ar <= max(1e-12, (1e-9 * diag) ** 2)) | (f[:, 0] == f[:, 1]) | (f[:, 1] == f[:, 2]) | (f[:, 0] == f[:, 2])
    return f[~bad], int(bad.sum())


def drop_small_components(v, f, fraction: float):
    n, lab = face_components(f, len(v))
    ar = areas(v, f)
    per = np.bincount(lab, weights=ar)
    drop_labels = np.flatnonzero((per > 0) & (per < fraction * per.sum()))
    drop = np.isin(lab, drop_labels)
    return f[~drop], {'components_dropped': int(len(drop_labels)), 'triangles_dropped': int(drop.sum()), 'area_dropped_mm2': float(ar[drop].sum())}


def orient_outward(v, f):
    """Make each component consistently oriented (BFS over manifold edges), then outward (signed volume > 0)."""
    f = f.copy()
    d, uk, inv, cnt = edge_table(f)
    m = len(f)
    nb: list[list[int]] = [[] for _ in range(m)]
    two = np.flatnonzero(cnt[inv] == 2)
    if len(two):
        order = two[np.argsort(inv[two], kind='stable')]
        a, b = order[0::2] % m, order[1::2] % m
        for x, y in zip(a.tolist(), b.tolist()):
            nb[x].append(y)
            nb[y].append(x)
    seen = np.zeros(m, bool)
    flipped = 0
    comp_faces: list[list[int]] = []
    for s in range(m):
        if seen[s]:
            continue
        seen[s] = True
        q, members = deque([s]), [s]
        while q:
            x = q.popleft()
            ex = {(int(f[x, i]), int(f[x, (i + 1) % 3])) for i in range(3)}
            for y in nb[x]:
                if seen[y]:
                    continue
                ey = {(int(f[y, i]), int(f[y, (i + 1) % 3])) for i in range(3)}
                if ex & ey:  # a shared directed edge means y is flipped relative to x
                    f[y] = f[y][[0, 2, 1]]
                    flipped += 1
                seen[y] = True
                q.append(y)
                members.append(y)
        comp_faces.append(members)
    inward = 0
    for members in comp_faces:
        if signed_volume(v, f[members]) < 0:
            f[members] = f[members][:, [0, 2, 1]]
            inward += 1
    return f, {'triangles_flipped_for_consistency': flipped, 'components_flipped_to_outward': inward}


def fill_holes(v, f, max_perimeter: float):
    """Centroid-fan fill of boundary loops shorter than max_perimeter. The filled area is not scan data."""
    loops = boundary_loops(v, f)
    new_v, new_f, info = [v], [f], {'loops_filled': 0, 'loops_skipped_too_long': 0, 'filled_area_mm2': 0.0, 'loops': []}
    nv = len(v)
    for lp in loops:
        per = loop_perimeter(v, lp)
        if per > max_perimeter or len(lp) < 3:
            info['loops_skipped_too_long'] += 1
            continue
        c = v[lp].mean(0)
        idx = nv
        nv += 1
        new_v.append(c[None, :])
        ring = np.array(lp)
        # boundary edge a->b is used by an existing face; the cap uses b->a.
        tri = np.stack([np.roll(ring, -1), ring, np.full(len(ring), idx)], axis=1)
        new_f.append(tri)
        cv = np.vstack([v, c[None, :]])
        ar = float(areas(cv, tri).sum())
        info['filled_area_mm2'] += ar
        info['loops_filled'] += 1
        info['loops'].append({'vertices': len(lp), 'perimeter_mm': per, 'area_mm2': ar})
    return np.vstack(new_v), np.vstack(new_f), info


# ---------------------------------------------------------------- exact distance
def _closest_d2(p, a, b, c) -> np.ndarray:
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = np.einsum('ij,ij->i', ab, ap), np.einsum('ij,ij->i', ac, ap)
    bp = p - b
    d3, d4 = np.einsum('ij,ij->i', ab, bp), np.einsum('ij,ij->i', ac, bp)
    cp = p - c
    d5, d6 = np.einsum('ij,ij->i', ab, cp), np.einsum('ij,ij->i', ac, cp)
    vc, vb, va = d1 * d4 - d3 * d2, d5 * d2 - d1 * d6, d3 * d6 - d5 * d4
    den = va + vb + vc
    den = np.where(den == 0, 1.0, den)
    q = a + ab * (vb / den)[:, None] + ac * (vc / den)[:, None]
    q = np.where(((va <= 0) & (d4 - d3 >= 0) & (d5 - d6 >= 0))[:, None], b + (c - b) * ((d4 - d3) / np.where((d4 - d3) + (d5 - d6) == 0, 1, (d4 - d3) + (d5 - d6)))[:, None], q)
    q = np.where(((vb <= 0) & (d2 >= 0) & (d6 <= 0))[:, None], a + ac * (d2 / np.where(d2 - d6 == 0, 1, d2 - d6))[:, None], q)
    q = np.where(((d6 >= 0) & (d5 <= d6))[:, None], c, q)
    q = np.where(((vc <= 0) & (d1 >= 0) & (d3 <= 0))[:, None], a + ab * (d1 / np.where(d1 - d3 == 0, 1, d1 - d3))[:, None], q)
    q = np.where(((d3 >= 0) & (d4 <= d3))[:, None], b, q)
    q = np.where(((d1 <= 0) & (d2 <= 0))[:, None], a, q)
    return np.einsum('ij,ij->i', p - q, p - q)


class MeshDistance:
    """Exact unsigned point-to-mesh distance via KD-tree on triangle centroids with a proven candidate radius."""

    def __init__(self, v: np.ndarray, f: np.ndarray):
        self.a, self.b, self.c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
        cen = (self.a + self.b + self.c) / 3.0
        self.rmax = float(max(np.linalg.norm(x - cen, axis=1).max() for x in (self.a, self.b, self.c)))
        self.tree = cKDTree(cen)
        self.n = len(f)

    def _eval(self, p, idx):
        return _closest_d2(np.repeat(p, idx.shape[1], axis=0) if idx.shape[1] > 1 else p, self.a[idx.reshape(-1)], self.b[idx.reshape(-1)], self.c[idx.reshape(-1)]).reshape(idx.shape)

    def distance(self, pts: np.ndarray, chunk: int = 200_000) -> np.ndarray:
        out = np.empty(len(pts))
        for s in range(0, len(pts), chunk):
            out[s:s + chunk] = self._chunk(pts[s:s + chunk])
        return out

    def _chunk(self, p: np.ndarray) -> np.ndarray:
        k = min(8, self.n)
        best = np.full(len(p), np.inf)
        todo = np.arange(len(p))
        while len(todo):
            dd, idx = self.tree.query(p[todo], k=k)
            dd, idx = dd.reshape(len(todo), -1), idx.reshape(len(todo), -1)
            d2 = self._eval(p[todo], idx).min(axis=1)
            best[todo] = np.sqrt(d2)
            # Any triangle outside the k nearest has centroid distance >= dd[:, -1], hence true distance >= that - rmax.
            ok = (best[todo] <= dd[:, -1] - self.rmax) | (k >= self.n)
            todo = todo[~ok]
            if not len(todo):
                break
            if k >= 128:  # exact fallback by radius for the few unresolved points
                for i in todo:
                    cand = np.asarray(self.tree.query_ball_point(p[i], best[i] + self.rmax), dtype=np.int64)
                    best[i] = np.sqrt(_closest_d2(np.repeat(p[i][None], len(cand), 0), self.a[cand], self.b[cand], self.c[cand]).min())
                break
            k = min(k * 4, self.n)
        return best


def sample_surface(v: np.ndarray, f: np.ndarray, n: int, seed: int = 20260917) -> tuple[np.ndarray, np.ndarray]:
    """Area-weighted points on triangles with a fixed seed. Returns points and source triangle ids."""
    ar = areas(v, f)
    rng = np.random.default_rng(seed)
    tid = rng.choice(len(f), size=n, p=ar / ar.sum())
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    w = np.stack([1 - s, s * (1 - r2), s * r2], axis=1)
    return np.einsum('ij,ijk->ik', w, v[f[tid]]), tid


# ---------------------------------------------------------------- inside test
def _parity_lines(v3, f, u_nodes, v_nodes, w_nodes, sel=None):
    """Ray parity along +w for every (u, v) node line. Returns bool (nu, nv, nw) inside mask.
    Lines are offset by a fixed sub-micron jitter so rays never meet vertices/edges of grid-aligned meshes."""
    nu, nv, nw = len(u_nodes), len(v_nodes), len(w_nodes)
    du, dv, dw = u_nodes[1] - u_nodes[0], v_nodes[1] - v_nodes[0], w_nodes[1] - w_nodes[0]
    uj, vj = u_nodes + JITTER[0], v_nodes + JITTER[1]
    tog = np.zeros((nu * nv, nw + 1), dtype=np.uint8)
    P = v3[f]
    pu, pv, pw = P[:, :, 0], P[:, :, 1], P[:, :, 2]
    i0 = np.ceil((pu.min(1) - uj[0]) / du).astype(np.int64).clip(0, nu)
    i1 = np.floor((pu.max(1) - uj[0]) / du).astype(np.int64).clip(-1, nu - 1)
    j0 = np.ceil((pv.min(1) - vj[0]) / dv).astype(np.int64).clip(0, nv)
    j1 = np.floor((pv.max(1) - vj[0]) / dv).astype(np.int64).clip(-1, nv - 1)
    ni, nj = np.maximum(i1 - i0 + 1, 0), np.maximum(j1 - j0 + 1, 0)
    cnt = ni * nj
    order = np.flatnonzero(cnt > 0)
    pos = 0
    while pos < len(order):
        tot, end = 0, pos
        while end < len(order) and (tot + cnt[order[end]] <= 4_000_000 or end == pos):
            tot += cnt[order[end]]
            end += 1
        t = order[pos:end]
        pos = end
        rep = np.repeat(t, cnt[t])
        loc = np.arange(len(rep)) - np.repeat(np.cumsum(cnt[t]) - cnt[t], cnt[t])
        nj_r = nj[rep]
        ii, jj = i0[rep] + loc // nj_r, j0[rep] + loc % nj_r
        x, y = uj[ii], vj[jj]
        x0, y0 = pu[rep, 0], pv[rep, 0]
        x1, y1, x2, y2 = pu[rep, 1], pv[rep, 1], pu[rep, 2], pv[rep, 2]
        det = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        good = np.abs(det) > 1e-18
        safe = np.where(good, det, 1.0)
        l0 = ((y1 - y2) * (x - x2) + (x2 - x1) * (y - y2)) / safe
        l1 = ((y2 - y0) * (x - x2) + (x0 - x2) * (y - y2)) / safe
        l2 = 1 - l0 - l1
        hit = good & (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        if sel is not None:
            hit &= sel[ii, jj]
        z = l0 * pw[rep, 0] + l1 * pw[rep, 1] + l2 * pw[rep, 2]
        k = np.floor((z[hit] - w_nodes[0]) / dw).astype(np.int64) + 1
        line = ii[hit] * nv + jj[hit]
        np.add.at(tog, (line, k.clip(0, nw)), 1)
    par = np.bitwise_xor.accumulate(tog & 1, axis=1)[:, :nw]
    return par.astype(bool).reshape(nu, nv, nw)


def inside_mask(v, f, axes, check_lines: int = 2000) -> tuple[np.ndarray, dict]:
    xs, ys, zs = axes
    mask = _parity_lines(v, f, xs, ys, zs)
    # Independent cross-check: parity along X on a fixed-seed subset of (y, z) lines.
    rng = np.random.default_rng(20260917)
    nl = min(check_lines, len(ys) * len(zs))
    pick = rng.choice(len(ys) * len(zs), size=nl, replace=False)
    jy, kz = pick // len(zs), pick % len(zs)
    sel = np.zeros((len(ys), len(zs)), bool)
    sel[jy, kz] = True
    other = _parity_lines(v[:, [1, 2, 0]], f, ys, zs, xs, sel)  # u=y, v=z, w=x
    a, b = other[jy, kz, :], mask[:, jy, kz].T
    mism = int((a != b).sum())
    return mask, {'checked_nodes': int(a.size), 'mismatched_nodes': mism, 'mismatch_rate': mism / max(int(a.size), 1)}


# ---------------------------------------------------------------- signed distance field
def signed_distance(v, f, axes, mask, exact_band_mm: tuple[float, ...], keep_exact, spacing, dist: MeshDistance | None = None):
    """phi (outside +, inside -). Coarse EDT everywhere, exact distance where keep_exact is True and |phi_c - iso| is small.
    exact_band_mm: iso values (0 and -t). Returns phi float64 and the number of exact nodes."""
    sp = (spacing, spacing, spacing)
    d_out = ndimage.distance_transform_edt(~mask, sampling=sp)
    d_in = ndimage.distance_transform_edt(mask, sampling=sp)
    phi = np.where(mask, -d_in, d_out)
    near = np.zeros(mask.shape, bool)
    for iso in exact_band_mm:
        near |= np.abs(phi - iso) <= 2.0 * spacing
    near &= keep_exact
    ids = np.flatnonzero(near.ravel())
    if len(ids):
        ix = np.unravel_index(ids, mask.shape)
        pts = np.stack([axes[0][ix[0]], axes[1][ix[1]], axes[2][ix[2]]], axis=1)
        dist = dist or MeshDistance(v, f)
        d = dist.distance(pts)
        s = np.where(mask.ravel()[ids], -1.0, 1.0)
        phi.ravel()[ids] = s * d
    return phi, int(len(ids))


# ---------------------------------------------------------------- surface nets
_CORNER = np.array([[i, j, k] for i in (0, 1) for j in (0, 1) for k in (0, 1)])
_EDGES = [(a, b) for a in range(8) for b in range(8) if a < b and (_CORNER[a] != _CORNER[b]).sum() == 1]


def surface_nets(psi: np.ndarray, origin, spacing: float, label: np.ndarray):
    """Closed, outward-oriented triangle mesh of psi <= 0. label (int8 per node) marks the active term at positive nodes.
    Returns vertices, faces, per-vertex label (plane if any crossing is plane-dominated: the true rim lies in the plane; else the larger of inner/outer),
    and a per-vertex 'pure' flag (every crossing of the cell belongs to the same term)."""
    nx, ny, nz = psi.shape
    inside = psi <= 0
    cs = (nx - 1, ny - 1, nz - 1)
    csum = np.zeros(cs, dtype=np.int8)
    for dx, dy, dz in _CORNER:
        csum += inside[dx:dx + cs[0], dy:dy + cs[1], dz:dz + cs[2]]
    act = np.flatnonzero(((csum > 0) & (csum < 8)).ravel())
    if len(act) == 0:
        raise BrainError('SHELL_MESH_EMPTY', 'The shell field has no zero crossing.')
    ci = np.stack(np.unravel_index(act, cs), axis=1)
    acc = np.zeros((len(act), 3))
    nc = np.zeros(len(act))
    lab_votes = np.zeros((len(act), 3), dtype=np.int32)
    for a, b in _EDGES:
        pa, pb = ci + _CORNER[a], ci + _CORNER[b]
        va = psi[pa[:, 0], pa[:, 1], pa[:, 2]]
        vb = psi[pb[:, 0], pb[:, 1], pb[:, 2]]
        cross = (va <= 0) != (vb <= 0)
        if not cross.any():
            continue
        den = np.where(cross, va - vb, 1.0)
        t = np.where(cross, va / den, 0.0)
        pt = pa + (pb - pa) * t[:, None]
        acc += np.where(cross[:, None], pt, 0.0)
        nc += cross
        pos = np.where((va > 0)[:, None], pa, pb)
        lb = label[pos[:, 0], pos[:, 1], pos[:, 2]]
        for q in range(3):
            lab_votes[:, q] += cross & (lb == q)
    verts = origin + (acc / nc[:, None]) * spacing
    vlabel = np.where(lab_votes[:, 2] > 0, 2, np.where(lab_votes[:, 1] > lab_votes[:, 0], 1, 0)).astype(np.int8)
    ids_sorted = act  # sorted flat ids
    strides = (cs[1] * cs[2], cs[2], 1)
    faces = []
    for ax in range(3):
        b_ax, c_ax = (ax + 1) % 3, (ax + 2) % 3
        lo, hi = [slice(None)] * 3, [slice(None)] * 3
        n = psi.shape[ax]
        lo[ax], hi[ax] = slice(0, n - 1), slice(1, n)
        a_in, b_in = inside[tuple(lo)], inside[tuple(hi)]
        e = np.argwhere(a_in != b_in)
        e = e[(e[:, b_ax] >= 1) & (e[:, c_ax] >= 1) & (e[:, b_ax] < cs[b_ax] + 0) & (e[:, c_ax] < cs[c_ax] + 0)]
        if not len(e):
            continue
        quad = []
        for db, dc in ((-1, -1), (0, -1), (0, 0), (-1, 0)):
            cc = e.copy()
            cc[:, b_ax] += db
            cc[:, c_ax] += dc
            flat = cc[:, 0] * strides[0] + cc[:, 1] * strides[1] + cc[:, 2]
            pos = np.searchsorted(ids_sorted, flat)
            if (pos >= len(ids_sorted)).any() or (ids_sorted[pos] != flat).any():
                raise BrainError('SHELL_MESH_NOT_MANIFOLD', 'Surface-nets quad refers to a cell without a vertex.')
            quad.append(pos)
        q = np.stack(quad, axis=1)
        out_pos = a_in[tuple(e.T)]  # lower node inside -> outward normal along +axis
        q = np.where(out_pos[:, None], q, q[:, ::-1])
        d02 = np.linalg.norm(verts[q[:, 0]] - verts[q[:, 2]], axis=1)
        d13 = np.linalg.norm(verts[q[:, 1]] - verts[q[:, 3]], axis=1)
        s = d02 <= d13
        t1 = np.where(s[:, None], q[:, [0, 1, 2]], q[:, [1, 2, 3]])
        t2 = np.where(s[:, None], q[:, [0, 2, 3]], q[:, [1, 3, 0]])
        faces.append(np.concatenate([t1, t2]))
    f = np.concatenate(faces)
    pure = lab_votes.max(axis=1) == nc
    return verts, f.astype(np.int64), vlabel, pure


def mesh_manifold_report(f: np.ndarray, nv: int) -> dict:
    """Closed 2-manifold test: edge use, orientation, and vertex-link connectivity (pinch vertices)."""
    d, uk, inv, cnt = edge_table(f)
    bad_edges = int((cnt != 2).sum())
    two = np.flatnonzero(cnt[inv] == 2)
    inconsistent = 0
    if len(two):
        order = two[np.argsort(inv[two], kind='stable')]
        inconsistent = int((d[order[0::2], 0] != d[order[1::2], 1]).sum())
    m = len(f)
    pinch = 0
    if bad_edges == 0 and inconsistent == 0:
        # corner graph: corner (t, i) at vertex f[t, i]; join corners sharing an edge at the same vertex.
        tid = np.tile(np.arange(m), 3)
        # directed edge e = (a->b) of triangle t sits at corner index (e // m) as start corner; its end corner is next.
        slot = np.repeat(np.arange(3), m)
        start_corner = tid * 3 + slot
        end_corner = tid * 3 + (slot + 1) % 3
        key = d[:, 0].astype(np.int64) * nv + d[:, 1]
        rkey = d[:, 1].astype(np.int64) * nv + d[:, 0]
        order = np.argsort(key)
        rpos = order[np.searchsorted(key[order], rkey)]  # reverse directed edge index
        # reverse edge (b->a): start corner at b, end corner at a. Join start(e) with end(rev) (vertex a), end(e) with start(rev) (vertex b).
        r = np.concatenate([start_corner, end_corner])
        s = np.concatenate([end_corner[rpos], start_corner[rpos]])
        g = coo_matrix((np.ones(len(r)), (r, s)), shape=(3 * m, 3 * m))
        _, lab = connected_components(g, directed=False)
        cv = f.reshape(-1)
        pairs = np.unique(np.stack([cv, lab], axis=1), axis=0)
        per_vertex = np.bincount(pairs[:, 0], minlength=nv)
        pinch = int((per_vertex > 1).sum())
    return {'non_two_use_edges': bad_edges, 'inconsistent_orientation_edges': inconsistent, 'pinch_vertices': pinch,
            'closed_2_manifold': bad_edges == 0 and inconsistent == 0 and pinch == 0}
