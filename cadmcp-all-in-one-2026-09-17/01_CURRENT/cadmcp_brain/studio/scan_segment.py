"""Scan region engine v4 (numpy / scipy / Pillow only): raster stacks of the mouse surface, seeded watershed segmentation, smoothed outlines.

Port of the owner's segmentation_v4 prototype for the left/right click, the scroll wheel and the two side-button pads. The engine works in
the mouse work frame (x front, y mouse-left, z up; see scan_regions.working_coords) on a welded closed mesh:
  1. top / side / top-shoulder raster stacks (painter id buffer at PIX, barycentric height z, depth y, groove map h, normal-discontinuity map),
  2. boundary likelihood B from the groove map and the normal-discontinuity map (the prepared scan carries no texture),
  3. markers generated here from mouse-frame priors (never from a stored label file), marker watershed, clean-up,
  4. smoothed outlines: true corners kept, smoothing splines between, LC/RC (and any touching regions) share ONE fitted chain,
  5. outline masks mapped back to face ids; side-button pads combine the flank (side) view with the shoulder (top) view.
No scikit-image / matplotlib: the few filters that the prototype took from them are re-implemented below with scipy.
"""
from __future__ import annotations
from typing import Any
import numpy as np
from scipy import ndimage as ndi
import scipy.sparse as sp
import scipy.sparse.csgraph as cg
from scipy.interpolate import splprep, splev
from scipy.spatial import cKDTree

PIX = 0.05
STEP = 0.05                                   # outline resampling step (mm)
TOP_BOX = (-3.0, 50.0, -31.0, 29.0)            # x0, x1, y0, y1 of the top-view stack
SIDE_BOX = (-30.0, 12.0, -15.0, 0.0)           # x, v = -z of the +y flank stack
SHOULDER_BOX = (-30.0, 12.0, 22.0, 31.0)       # x, y of the +y shoulder seen from above
FACE_MARGIN_MM = 0.4                           # a face is "visible" when its centroid is this close to the stack surface


# ------------------------------------------------------------------ raster stacks
def _idbuf(t2: np.ndarray, depth: np.ndarray, x0: float, y0: float, nx: int, ny: int, valid: np.ndarray) -> np.ndarray:
    """Painter id buffer: pixel -> face id (-1 empty); faces are drawn far-to-near. Result indexed [ix, iy]."""
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (nx, ny), (255, 255, 255))
    dr = ImageDraw.Draw(img)
    q = (t2 - np.array([x0, y0])) / PIX
    ids = np.flatnonzero(valid)
    ids = ids[np.argsort(depth[ids], kind='stable')]
    for i in ids:
        dr.polygon([tuple(p) for p in q[i]], fill=(int(i) & 255, (int(i) >> 8) & 255, int(i) >> 16))
    a = np.array(img).astype(np.int64)
    r = a[:, :, 0] | (a[:, :, 1] << 8) | (a[:, :, 2] << 16)
    r[(a[:, :, 0] == 255) & (a[:, :, 1] == 255) & (a[:, :, 2] == 255)] = -1
    return r.T.copy()


def _bary(t2: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    a, b, c = t2[:, 0], t2[:, 1], t2[:, 2]
    d = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
    d = np.where(np.abs(d) < 1e-12, 1e-12, d)
    l1 = ((b[:, 1] - c[:, 1]) * (xs - c[:, 0]) + (c[:, 0] - b[:, 0]) * (ys - c[:, 1])) / d
    l2 = ((c[:, 1] - a[:, 1]) * (xs - c[:, 0]) + (a[:, 0] - c[:, 0]) * (ys - c[:, 1])) / d
    ll = np.clip(np.stack([l1, l2, 1 - l1 - l2], 1), -0.05, 1.05)
    return ll / ll.sum(1, keepdims=True)


def _adjacency(F: np.ndarray, nv: int):
    i = np.r_[F[:, 0], F[:, 1], F[:, 2], F[:, 1], F[:, 2], F[:, 0]]
    j = np.r_[F[:, 1], F[:, 2], F[:, 0], F[:, 0], F[:, 1], F[:, 2]]
    A = sp.coo_matrix((np.ones(len(i)), (i, j)), shape=(nv, nv)).tocsr()
    A.data[:] = 1
    return sp.diags(1 / np.maximum(np.asarray(A.sum(1)).ravel(), 1)) @ A


def surface_features(P: np.ndarray, F: np.ndarray, L, vn: np.ndarray, fn: np.ndarray) -> dict[str, Any]:
    """Per-vertex groove map h (band-pass normal offset), normal-discontinuity angle and smoothed face normals."""
    Q = P.copy()
    for _ in range(3):
        Q = Q + 0.6 * (L @ Q - Q)
    d = ((P - Q) * vn).sum(1)
    bg = d.copy()
    for _ in range(15):
        bg = bg + 0.6 * (L @ bg - bg)
    hv = d - bg
    vs = vn.copy()
    for _ in range(2):
        vs = L @ vs
    vs /= np.linalg.norm(vs, axis=1)[:, None] + 1e-12
    fs = vs[F].mean(1)
    fs /= np.linalg.norm(fs, axis=1)[:, None]
    vb = vn.copy()
    for _ in range(6):
        vb = vb + 0.6 * (L @ vb - vb)
    vb /= np.linalg.norm(vb, axis=1)[:, None] + 1e-12
    angv = np.degrees(np.arccos(np.clip((vn * vb).sum(1), -1, 1)))
    return {'hv': hv, 'angv': angv, 'fs': fs, 'defect': (fn * fs).sum(1) < 0.55}


def make_stack(M: Any, ft: dict[str, Any], which: str) -> dict[str, Any]:
    """Orthographic stack of the work mesh. which: 'top' | 'shoulder' (+y shoulder from above) | 'side' (+y flank, axes x and v = -z)."""
    tri, F, fs = M.tri, M.F, ft['fs']
    if which == 'top':
        x0, x1, y0, y1 = TOP_BOX
        t2, depth, valid = tri[:, :, :2], tri[:, :, 2].mean(1), fs[:, 2] > 0.1
    elif which == 'shoulder':
        x0, x1, y0, y1 = SHOULDER_BOX
        t2, depth, valid = tri[:, :, :2], tri[:, :, 2].mean(1), fs[:, 2] > -0.05
    else:
        x0, x1, y0, y1 = SIDE_BOX
        t2, depth = np.stack([tri[:, :, 0], -tri[:, :, 2]], -1), tri[:, :, 1].mean(1)
        valid = (fs[:, 1] > 0.1) & (tri[:, :, 1].min(1) > 15)
    nx, ny = int(round((x1 - x0) / PIX)), int(round((y1 - y0) / PIX))
    ib = _idbuf(t2, depth, x0, y0, nx, ny, valid)
    m = ib >= 0
    ii = np.nonzero(m)
    f = ib[m]
    X = x0 + (ii[0] + .5) * PIX
    Y = y0 + (ii[1] + .5) * PIX
    lam = _bary(t2[f], X, Y)
    out: dict[str, Any] = {'x0': x0, 'y0': y0, 'ok': m, 'face': ib, 'nx': nx, 'ny': ny, 'which': which}

    def put(name: str, val: np.ndarray) -> None:
        a = np.zeros((nx, ny), val.dtype)
        a[m] = val
        out[name] = a
    put('z', (tri[f][:, :, 2] * lam).sum(1))
    put('y3', (tri[f][:, :, 1] * lam).sum(1))
    dfc = ft['defect'][f]
    put('h', np.where(dfc, 0, (ft['hv'][F[f]] * lam).sum(1)))
    put('ang', np.where(dfc, 0, (ft['angv'][F[f]] * lam).sum(1)))
    return out


# ------------------------------------------------------------------ small image tools
def fillnn(a: np.ndarray, ok: np.ndarray) -> np.ndarray:
    idx = ndi.distance_transform_edt(~ok, return_distances=False, return_indices=True)
    return a[tuple(idx)]


def _norm(a: np.ndarray, ok: np.ndarray, p: float = 98) -> np.ndarray:
    return np.clip(a / max(np.percentile(a[ok], p), 1e-9), 0, 1.5)


def _disk(r: int) -> np.ndarray:
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r * r


def _open(m: np.ndarray, r_mm: float) -> np.ndarray:
    return ndi.binary_opening(m, structure=_disk(max(int(r_mm / PIX), 1)))


def _close(m: np.ndarray, r_mm: float) -> np.ndarray:
    return ndi.binary_closing(m, structure=_disk(max(int(r_mm / PIX), 1)))


def clean_mask(m: np.ndarray, ro: float, rc: float | None = None) -> np.ndarray:
    m = ndi.binary_fill_holes(m)
    if ro:
        m = _open(m, ro)
    if rc:
        m = ndi.binary_fill_holes(_close(m, rc))
    lbl, n = ndi.label(m)
    if n > 1:
        m = lbl == (np.argmax(np.bincount(lbl.ravel())[1:]) + 1)
    return m


def smooth_mask(m: np.ndarray, sig_mm: float = 0.1) -> np.ndarray:
    return ndi.gaussian_filter(m.astype(float), sig_mm / PIX) > 0.5


def watershed(img: np.ndarray, markers: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Marker watershed (4-connected) as a minimum spanning forest: a pixel takes the label of the marker it reaches over the lowest pass of
    `img`. Pixels outside `mask` are never crossed and stay 0."""
    nx, ny = img.shape
    n = nx * ny
    idx = np.arange(n).reshape(nx, ny)
    a = np.r_[idx[:-1, :].ravel(), idx[:, :-1].ravel()]
    b = np.r_[idx[1:, :].ravel(), idx[:, 1:].ravel()]
    w = np.r_[np.maximum(img[:-1, :], img[1:, :]).ravel(), np.maximum(img[:, :-1], img[:, 1:]).ravel()] + 1e-6
    if mask is not None:
        mk_ = mask.ravel()
        keep = mk_[a] & mk_[b]
        a, b, w = a[keep], b[keep], w[keep]
    mk = markers.ravel().copy()
    if mask is not None:
        mk[~mask.ravel()] = 0
    src = np.flatnonzero(mk > 0)
    g = sp.coo_matrix((np.r_[w, np.full(len(src), 1e-9)], (np.r_[a, src], np.r_[b, np.full(len(src), n)])), shape=(n + 1, n + 1)).tocsr()
    tree = cg.minimum_spanning_tree(g)
    _, pred = cg.breadth_first_order(tree, n, directed=False, return_predecessors=True)
    anc = pred.astype(np.int64)
    anc[n] = n
    anc[src] = src
    for _ in range(64):
        nxt = anc[anc]
        if (nxt == anc).all():
            break
        anc = nxt
    lab = np.zeros(n + 1, dtype=markers.dtype)
    lab[src] = mk[src]
    out = lab[anc]
    out[anc == n] = 0
    return out[:n].reshape(nx, ny)


def polygon_mask(poly: np.ndarray, x0: float, y0: float, nx: int, ny: int) -> np.ndarray:
    from PIL import Image, ImageDraw
    im = Image.new('1', (ny, nx), 0)
    pts = [(float((p[1] - y0) / PIX), float((p[0] - x0) / PIX)) for p in poly]
    if len(pts) >= 3:
        ImageDraw.Draw(im).polygon(pts, fill=1)
    return np.array(im).astype(bool)


def tri_mask(t2: np.ndarray, x0: float, y0: float, nx: int, ny: int) -> np.ndarray:
    from PIL import Image, ImageDraw
    im = Image.new('1', (ny, nx), 0)
    dr = ImageDraw.Draw(im)
    for a in t2:
        dr.polygon([(float((p[1] - y0) / PIX), float((p[0] - x0) / PIX)) for p in a], fill=1)
    return np.array(im).astype(bool)


# ------------------------------------------------------------------ contour tracing (marching squares with edge ids)
def find_contours(field: np.ndarray, level: float = 0.5) -> list[np.ndarray]:
    """Ordered iso-contours of a 2-D field in index coordinates (n, 2), closed ones repeat their first point. Saddles split by the cell mean."""
    nx, ny = field.shape
    f = field - level
    pos = f > 0
    # edge crossing points: h-edges join (i,j)-(i+1,j); v-edges join (i,j)-(i,j+1)
    hx = pos[:-1, :] != pos[1:, :]
    vx = pos[:, :-1] != pos[:, 1:]
    nh = hx.size
    hid = np.full(hx.shape, -1, np.int64)
    hid[hx] = np.arange(hx.sum())
    vid = np.full(vx.shape, -1, np.int64)
    vid[vx] = hx.sum() + np.arange(vx.sum())
    ii, jj = np.nonzero(hx)
    t = f[ii, jj] / (f[ii, jj] - f[ii + 1, jj])
    ph = np.stack([ii + t, jj.astype(float)], 1)
    ii, jj = np.nonzero(vx)
    t = f[ii, jj] / (f[ii, jj] - f[ii, jj + 1])
    pv = np.stack([ii.astype(float), jj + t], 1)
    pts = np.vstack([ph, pv]) if len(ph) + len(pv) else np.zeros((0, 2))
    del nh
    # cells
    e_b = hid[:, :-1][: nx - 1, : ny - 1]          # edge (i,j)-(i+1,j)
    e_t = hid[:, 1:][: nx - 1, : ny - 1]           # edge (i,j+1)-(i+1,j+1)
    e_l = vid[:-1, :][: nx - 1, : ny - 1]          # edge (i,j)-(i,j+1)
    e_r = vid[1:, :][: nx - 1, : ny - 1]           # edge (i+1,j)-(i+1,j+1)
    E = np.stack([e_b, e_r, e_t, e_l], -1)
    cnt = (E >= 0).sum(-1)
    nbr: dict[int, list[int]] = {}

    def link(a: int, b: int) -> None:
        nbr.setdefault(a, []).append(b)
        nbr.setdefault(b, []).append(a)
    for ci, cj in zip(*np.nonzero(cnt == 2)):
        e = E[ci, cj]
        e = e[e >= 0]
        link(int(e[0]), int(e[1]))
    for ci, cj in zip(*np.nonzero(cnt == 4)):
        e = E[ci, cj]
        centre = f[ci:ci + 2, cj:cj + 2].mean() > 0
        # corner signs a=(i,j) b=(i+1,j) c=(i+1,j+1) d=(i,j+1); edges b-bottom, r-right, t-top, l-left
        if centre == bool(pos[ci, cj]):          # a and c are joined through the middle: cut round b and d
            link(int(e[0]), int(e[1]))
            link(int(e[2]), int(e[3]))
        else:
            link(int(e[0]), int(e[3]))
            link(int(e[1]), int(e[2]))
    seen: set[int] = set()
    out: list[np.ndarray] = []
    for start in list(nbr):
        if start in seen:
            continue
        # walk to one end of an open chain, else start anywhere on a loop
        cur, prev = start, -1
        for _ in range(len(nbr) + 2):
            nx_ = [n for n in nbr[cur] if n != prev]
            if not nx_ or nx_[0] == start:
                break
            prev, cur = cur, nx_[0]
        head = cur if len(nbr[cur]) == 1 else start
        chain = [head]
        seen.add(head)
        prev, cur = -1, head
        while True:
            nxt = [n for n in nbr[cur] if n != prev and (n not in seen or n == head)]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            if cur == head:
                chain.append(cur)
                break
            chain.append(cur)
            seen.add(cur)
        out.append(pts[np.array(chain)])
    return out


def approximate_polygon(c: np.ndarray, tol: float) -> np.ndarray:
    """Douglas-Peucker for an open or closed (first == last) polyline."""
    if len(c) < 4:
        return c
    closed = np.allclose(c[0], c[-1])
    if closed:
        k = int(np.argmax(np.linalg.norm(c - c[0], axis=1)))
        a = approximate_polygon(c[:k + 1], tol)
        b = approximate_polygon(np.vstack([c[k:], c[:1]]), tol)
        return np.vstack([a, b[1:]])
    keep = np.zeros(len(c), bool)
    keep[[0, -1]] = True
    stack = [(0, len(c) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        d = c[j] - c[i]
        n = np.hypot(*d)
        seg = c[i + 1:j] - c[i]
        dist = np.abs(seg[:, 0] * d[1] - seg[:, 1] * d[0]) / n if n > 0 else np.linalg.norm(seg, axis=1)
        k = int(np.argmax(dist))
        if dist[k] > tol:
            keep[i + 1 + k] = True
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return c[keep]


def outline(m: np.ndarray, s: dict[str, Any], sig_mm: float = 0.1) -> np.ndarray:
    """Gaussian-smoothed contour of a mask in stack millimetres (largest contour, 0.02 mm Douglas-Peucker)."""
    f = ndi.gaussian_filter(np.pad(m, 3).astype(float), sig_mm / PIX)[3:-3, 3:-3]
    cs = find_contours(np.pad(f, 1), 0.5)
    cc = max(cs, key=len) - 1
    cc = approximate_polygon(cc, 0.4)
    return np.column_stack([s['x0'] + (cc[:, 0] + .5) * PIX, s['y0'] + (cc[:, 1] + .5) * PIX])


# ------------------------------------------------------------------ outline regularisation (corners + smoothing splines, shared chains)
def rs_closed(q: np.ndarray, step: float = STEP) -> np.ndarray:
    q = np.asarray(q, float)
    if np.linalg.norm(q[0] - q[-1]) > 1e-9:
        q = np.vstack([q, q[:1]])
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(q, axis=0), axis=1))]
    n = max(int(round(d[-1] / step)), 8)
    t = np.linspace(0, d[-1], n, endpoint=False)
    return np.column_stack([np.interp(t, d, q[:, 0]), np.interp(t, d, q[:, 1])])


def rs_open(q: np.ndarray, step: float = STEP) -> np.ndarray:
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(q, axis=0), axis=1))]
    n = max(int(round(d[-1] / step)), 2) + 1
    t = np.linspace(0, d[-1], n)
    return np.column_stack([np.interp(t, d, q[:, 0]), np.interp(t, d, q[:, 1])])


def find_corners(q: np.ndarray, closed: bool, win_mm: float = 0.5, thr_deg: float = 38, sig_mm: float = 0.12) -> list[int]:
    k = int(win_mm / STEP)
    if not closed and len(q) < 4 * k:
        return []
    qs = ndi.gaussian_filter1d(q, sig_mm / STEP, axis=0, mode='wrap' if closed else 'nearest')
    if closed:
        a, b = np.roll(qs, -k, 0) - qs, qs - np.roll(qs, k, 0)
    else:
        a = np.vstack([qs[k:], np.repeat(qs[-1:], k, 0)]) - qs
        b = qs - np.vstack([np.repeat(qs[:1], k, 0), qs[:-k]])
    ang = np.abs(np.arctan2(b[:, 0] * a[:, 1] - b[:, 1] * a[:, 0], (a * b).sum(1)))
    if not closed:
        ang[:k] = 0
        ang[-k:] = 0
    mx = ndi.maximum_filter1d(ang, size=2 * k + 1, mode='wrap' if closed else 'nearest')
    return [int(i) for i in np.where((ang >= mx - 1e-12) & (ang > np.radians(thr_deg)))[0]]


def _dev(a: np.ndarray, b: np.ndarray) -> float:
    bb = rs_open(b, 0.01) if len(b) > 1 else b
    return float(cKDTree(bb).query(a)[0].max())


def _fit(q: np.ndarray, per: bool, tol: float, wend: float | None = None):
    n = len(q)
    w = np.ones(n)
    if wend:
        w[0] = w[-1] = wend
    tck, _ = splprep([q[:, 0], q[:, 1]], w=w, s=n * tol ** 2, per=int(per), k=3)
    m = max(n, 20)
    xs, ys = splev(np.linspace(0, 1, m, endpoint=not per), tck)
    return tck, np.column_stack([xs, ys])


TOLS = (0.2, 0.14, 0.1, 0.075, 0.05, 0.035)


def fit_open(q: np.ndarray, maxdev: float = 0.12, straight: float = 0.15) -> dict[str, Any]:
    ch = q[-1] - q[0]
    length = float(np.linalg.norm(ch))
    if length < 0.3:
        return {'type': 'line', 'pts': q[[0, -1]].copy(), 'maxdev': 0.0}
    nrm = np.array([-ch[1], ch[0]]) / length
    dev = np.abs((q - q[0]) @ nrm)
    if dev.max() < straight and length > 1.5:
        return {'type': 'line', 'pts': np.linspace(q[0], q[-1], max(int(length / STEP), 2) + 1), 'maxdev': float(dev.max())}
    md, c, tol = 0.0, q, TOLS[-1]
    for tol in TOLS:
        try:
            _, c = _fit(q, False, tol, wend=200.0)
        except Exception:                      # too few points for a cubic spline: keep the raw chain
            return {'type': 'line', 'pts': rs_open(q), 'maxdev': 0.0}
        c[0], c[-1] = q[0], q[-1]
        md = _dev(q, c)
        if md <= maxdev:
            break
    return {'type': 'spline', 'pts': rs_open(c), 'maxdev': md, 'tol': tol}


def fit_closed(q: np.ndarray, maxdev: float = 0.12) -> dict[str, Any]:
    md, c, tol = 0.0, q, TOLS[-1]
    for tol in TOLS:
        _, c = _fit(q, True, tol)
        md = _dev(q, np.vstack([c, c[:1]]))
        if md <= maxdev:
            break
    return {'type': 'periodic', 'pts': rs_closed(c), 'maxdev': md, 'tol': tol}


def ring_runs(labels: np.ndarray, minlen: float = 0.3):
    n = len(labels)
    lab = labels.copy()
    m = int(minlen / STEP)
    for _ in range(3):
        ch = np.where(lab != np.roll(lab, 1))[0]
        if len(ch) <= 1:
            break
        for a, b in zip(ch, np.r_[ch[1:], ch[0] + n]):
            if b - a < m:
                lab[np.arange(a, b) % n] = lab[(a - 1) % n]
    ch = np.where(lab != np.roll(lab, 1))[0]
    if len(ch) == 0:
        return lab, [(lab[0], 0, n)]
    return lab, [(lab[a % n], a, b) for a, b in zip(ch, np.r_[ch[1:], ch[0] + n])]


def _to_px(q: np.ndarray, s: dict[str, Any]):
    return (np.clip(((q[:, 0] - s['x0']) / PIX).astype(int), 0, s['nx'] - 1), np.clip(((q[:, 1] - s['y0']) / PIX).astype(int), 0, s['ny'] - 1))


def _split_fit(pts: np.ndarray):
    ci = [i for i in find_corners(pts, False) if 6 < i < len(pts) - 7]
    cuts = [0] + ci + [len(pts) - 1]
    return [fit_open(pts[a:b + 1]) for a, b in zip(cuts[:-1], cuts[1:])], [pts[i] for i in ci]


def _chain_pts(pieces: list[dict[str, Any]]) -> np.ndarray:
    out = [pieces[0]['pts']]
    for p in pieces[1:]:
        out.append(p['pts'][1:])
    return np.vstack(out)


def regularise_group(raw: dict[str, np.ndarray], masks: dict[str, np.ndarray], s: dict[str, Any], closed_only: tuple[str, ...] = ()):
    """raw: raw closed outlines by name; masks: their masks. Regions whose outlines run along each other share ONE fitted chain.
    Returns the final closed polylines and per-curve info (kind, type, max deviation)."""
    names = list(raw)
    ring = {k: rs_closed(raw[k]) for k in names}
    dist = {k: ndi.distance_transform_edt(~masks[k]) * PIX for k in names}
    runs, lab = {}, {}
    for k in names:
        i, j = _to_px(ring[k], s)
        lb = np.zeros(len(ring[k]), int)
        if k not in closed_only:
            best = np.full(len(lb), 0.25)
            for n_, o in enumerate(names, 1):
                if o == k:
                    continue
                d = dist[o][i, j]
                mm = d < best
                lb[mm] = n_
                best = np.where(mm, d, best)
        lab[k], runs[k] = ring_runs(lb)
    junctions: list[np.ndarray] = []

    def snap(p: np.ndarray) -> np.ndarray:
        if junctions:
            d = np.linalg.norm(np.array(junctions) - p, axis=1)
            if d.min() < 0.8:
                return junctions[int(d.argmin())].copy()
        return p

    def run_pts(k: str, a: int, b: int) -> np.ndarray:
        return ring[k][np.arange(a, b + 1) % len(ring[k])].copy()
    canon: dict[tuple[str, str], list] = {}
    for ia, a in enumerate(names):
        for b in names[ia + 1:]:
            lb = names.index(b) + 1
            for (lv, s0, e0) in runs[a]:
                if lv != lb:
                    continue
                pts = run_pts(a, s0, e0)
                pts[0], pts[-1] = snap(pts[0]), snap(pts[-1])
                pcs, cr = _split_fit(pts)
                junctions.extend([pts[0], pts[-1]] + cr)
                canon.setdefault((a, b), []).append(pcs)
    final: dict[str, np.ndarray] = {}
    info: dict[str, list] = {}
    for k in names:
        rr = runs[k]
        if (len(rr) == 1 and rr[0][0] == 0) or k in closed_only:
            f = fit_closed(ring[k])
            final[k] = f['pts']
            info[k] = [{'kind': 'closed', 'type': f['type'], 'maxdev_mm': round(f['maxdev'], 3)}]
            continue
        parts, info[k] = [], []
        for (lv, s0, e0) in rr:
            if lv == 0:
                pts = run_pts(k, s0, e0)
                pts[0], pts[-1] = snap(pts[0]), snap(pts[-1])
                pc, cr = _split_fit(pts)
                junctions.extend(cr)
                nb = 'free'
            else:
                o = names[lv - 1]
                key = (k, o) if names.index(k) < names.index(o) else (o, k)
                mid = run_pts(k, s0, e0).mean(0)
                pc = min(canon[key], key=lambda c_: np.linalg.norm(_chain_pts(c_).mean(0) - mid))
                nb = o
            parts.append(_chain_pts(pc))
            info[k] += [{'kind': 'free' if nb == 'free' else 'shared_with_' + nb, 'type': p['type'], 'maxdev_mm': round(p['maxdev'], 3)} for p in pc]
        out = [parts[0]]
        if len(parts) > 1:
            def dd(p, q):
                return np.linalg.norm(p - q)
            e1 = min(dd(out[0][-1], parts[1][0]), dd(out[0][-1], parts[1][-1]))
            e0_ = min(dd(out[0][0], parts[1][0]), dd(out[0][0], parts[1][-1]))
            if e0_ < e1:
                out[0] = out[0][::-1]
        for pts in parts[1:]:
            if np.linalg.norm(pts[0] - out[-1][-1]) > np.linalg.norm(pts[-1] - out[-1][-1]):
                pts = pts[::-1]
            out.append(pts)
        final[k] = np.vstack([out[0]] + [p[1:] for p in out[1:]])
        if np.linalg.norm(final[k][0] - final[k][-1]) < 1e-6:
            final[k] = final[k][:-1]
    return final, info


# ------------------------------------------------------------------ cues and segmentation
def make_cues(s: dict[str, Any]) -> dict[str, Any]:
    """Boundary cues of one stack: groove depth band |h|, normal-discontinuity angle and surface slope |grad depth|."""
    ok = s['ok']
    dep = fillnn(s['z'] if s['which'] != 'side' else s['y3'], ok)
    return {'ok': ok, 'geo': _norm(ndi.gaussian_filter(np.abs(s['h']), 3), ok, 97), 'ang': _norm(s['ang'], ok),
            'slope': _norm(ndi.gaussian_gradient_magnitude(dep, 1.0) / PIX, ok, 97)}


def _grid(s: dict[str, Any]):
    X = s['x0'] + (np.arange(s['nx'])[:, None] + .5) * PIX
    Y = s['y0'] + (np.arange(s['ny'])[None, :] + .5) * PIX
    return X, Y


def _largest(m: np.ndarray) -> np.ndarray:
    lbl, n = ndi.label(m)
    return lbl == (np.argmax(np.bincount(lbl.ravel())[1:]) + 1) if n > 1 else m


def _otsu(v: np.ndarray) -> float:
    h, e = np.histogram(v, 128)
    p = h / max(h.sum(), 1)
    w = np.cumsum(p)
    mu = np.cumsum(p * (e[:-1] + e[1:]) / 2)
    sb = (mu[-1] * w - mu) ** 2 / np.maximum(w * (1 - w), 1e-12)
    return float((e[:-1] + e[1:])[int(np.argmax(sb))] / 2)


def wheel_marker(s: dict[str, Any], c: dict[str, Any], prior: dict[str, Any]) -> np.ndarray:
    """Wheel well: the knurled wheel and its slot are the one place in the prior window with a dense, strong groove response (smoothed boundary
    cue above 1.2 x its Otsu level), closed, filled and opened. Falls back to the prior core when nothing wheel-like is found."""
    X, Y = _grid(s)
    x0, x1, y0, y1 = prior['wheel_win']
    win = (X > x0) & (X < x1) & (Y > y0) & (Y < y1) & c['ok']
    sm = ndi.gaussian_filter(np.maximum(c['geo'], c['ang']), 2.0)
    blob = win & (sm > 1.2 * _otsu(sm[win]))
    blob = _open(ndi.binary_fill_holes(_close(blob, 0.5)), 0.5)
    if blob.sum() < 200:
        cx0, cx1, cy0, cy1 = prior['wheel_core']
        return (X > cx0) & (X < cx1) & (Y > cy0) & (Y < cy1) & c['ok']
    return _largest(blob)


def seg_top(s: dict[str, Any], c: dict[str, Any], prior: dict[str, Any], nbmax: float = 2.5):
    ok = c['ok']
    X, Y = _grid(s)
    XX, YY = np.broadcast_arrays(X, Y)
    B = ndi.gaussian_filter(np.maximum(c['geo'], c['ang']), 1.5)
    wheel = wheel_marker(s, c, prior)
    far = ~ndi.binary_dilation(wheel, iterations=int(2 / PIX))
    mk = np.zeros(ok.shape, int)
    for k, (lo, hi) in ((1, prior['lc_y']), (2, prior['rc_y'])):
        box = (XX > prior['click_x'][0]) & (XX < prior['click_x'][1]) & (YY > lo) & (YY < hi) & far & ok & (B < 0.25)
        mk[_largest(box)] = k
    mk[ndi.binary_dilation(wheel, iterations=int(0.6 / PIX)) & (mk == 0)] = 3
    edge = ndi.distance_transform_edt(ok) * PIX
    barrier = (B > 0.9) & (edge > 0.6)       # a rim lip exists only where a ridge lies within nbmax mm of the silhouette
    nb = ndi.distance_transform_edt(~barrier) * PIX
    mk[(((edge < 0.3) & (nb < nbmax)) | (XX < prior['rear_x'])) & (mk == 0) & ok] = 4
    w = watershed(B, mk, mask=ok)
    wmax = ndi.binary_dilation(wheel, iterations=int(0.5 / PIX))                 # no seam on the plateau round the wheel: limit the well to 0.5 mm round the blob
    left = (w == 3) & ~wmax
    w = np.where(left, 0, w)
    idx = ndi.distance_transform_edt((w != 1) & (w != 2), return_distances=False, return_indices=True)
    w = np.where(left, w[tuple(idx)], w)
    res = {k: clean_mask(w == i, 0.25) for k, i in (('LC', 1), ('RC', 2), ('WH', 3))}
    return res, B, mk


def seg_side_slope(s: dict[str, Any], env: dict[str, Any], sg: float = 1.0) -> dict[str, np.ndarray]:
    """Side-button pad = plateau edge: crest of the surface-slope ring round the raised pad (watershed on |grad y| of the flank depth)."""
    ok = s['ok']
    y3 = fillnn(s['y3'], ok)
    gy = ndi.gaussian_gradient_magnitude(y3, sg) / PIX
    X, V = _grid(s)
    out = {}
    for k in ('B1', 'B2'):
        e = env[k]
        vp = V - e['slope'] * (X - e['x_ref']) if e.get('slope') else V
        inside = lambda m: (X > e['x0'] - m) & (X < e['x1'] + m) & (vp > e['v0'] - m) & (vp < e['v1'] + m)   # noqa: E731
        core = (X > e['cx0']) & (X < e['cx1']) & (vp > e['cv0']) & (vp < e['cv1'])
        mk = np.zeros(ok.shape, int)
        mk[~inside(1.5)] = 2
        mk[core] = 1
        out[k] = clean_mask(ndi.binary_fill_holes(watershed(gy, mk, mask=ok) == 1), 0.3, 0.3)
    return out


def seg_top_btn(sb: dict[str, Any], xr: dict[str, tuple[float, float]], sg: float = 1.5) -> dict[str, np.ndarray]:
    """Top-view pad = low-|grad z| valley on the +y shoulder (the x extent is shared with the side-view outline)."""
    ok = sb['ok']
    z = fillnn(sb['z'], ok)
    gz = ndi.gaussian_gradient_magnitude(z, sg) / PIX
    X, Y = _grid(sb)
    out = {}
    for k in ('B1', 'B2'):
        x0, x1 = xr[k]
        inx = (X > x0) & (X < x1)
        mk = np.zeros(ok.shape, int)
        mk[~((X > x0 - 1.5) & (X < x1 + 1.5) & (Y > 24.0) & (Y < 29.5))] = 2
        mk[inx & (Y < 24.9)] = 2
        mk[(X > x0 + 2) & (X < x1 - 2) & (Y > 26.3) & (Y < 26.9)] = 1
        out[k] = clean_mask(ndi.binary_fill_holes(watershed(gz, mk, mask=ok) == 1) & inx, 0.3, 0.3)
    return out


# ------------------------------------------------------------------ driver
# Shape priors in the work frame (x front, y mouse-left, z up), calibrated on the OP1-class mouse. They only place MARKERS; every boundary comes from the surface.
PRIOR = {'click_x': (4.0, 34.0), 'lc_y': (6.0, 18.0), 'rc_y': (-18.0, -6.0), 'rear_x': -1.8, 'wheel_win': (16.0, 36.0, -7.0, 6.0), 'wheel_core': (21.0, 31.0, -3.5, 1.5)}
SIDE_ENV = {'B1': {'x0': -25.5, 'x1': -7.5, 'v0': -12.2, 'v1': -6.5, 'cx0': -22.0, 'cx1': -11.0, 'cv0': -10.5, 'cv1': -8.5},
            'B2': {'x0': -6.6, 'x1': 9.6, 'v0': -10.8, 'v1': -7.2, 'cx0': -4.0, 'cx1': 6.0, 'cv0': -9.7, 'cv1': -8.3, 'slope': 0.27, 'x_ref': -6.0}}
BTN_TOP_D_MM = 0.3             # shoulder-view faces within this distance (side view) of the flank outline join a pad: balances top- and side-view agreement
REG = ['LC', 'RC', 'WH', 'B1', 'B2']


class SegmentError(Exception):
    def __init__(self, message: str, detail: dict[str, Any]):
        super().__init__(message)
        self.detail = detail


def _look(arr: np.ndarray, s: dict[str, Any], a: np.ndarray, b: np.ndarray) -> np.ndarray:
    i = np.clip(((a - s['x0']) / PIX).astype(int), 0, s['nx'] - 1)
    j = np.clip(((b - s['y0']) / PIX).astype(int), 0, s['ny'] - 1)
    return arr[i, j]


def _pix_in(mask: np.ndarray, s: dict[str, Any], a: np.ndarray, b: np.ndarray) -> np.ndarray:
    i = ((a - s['x0']) / PIX).astype(int)
    j = ((b - s['y0']) / PIX).astype(int)
    ok = (i >= 0) & (i < mask.shape[0]) & (j >= 0) & (j < mask.shape[1])
    r = np.zeros(len(a), bool)
    r[ok] = mask[i[ok], j[ok]]
    return r


def lift(q: np.ndarray, s: dict[str, Any], which: str) -> np.ndarray:
    """2-D outline -> 3-D points on the surface (0.05 mm toward the viewer). which: 'top' (x, y) or 'side' (x, v = -z)."""
    ok = s['ok']
    i, j = _to_px(q, s)
    if which == 'top':
        z = fillnn(s['z'], ok)[i, j]
        z = ndi.gaussian_filter1d(ndi.median_filter(z, size=9, mode='wrap'), 2, mode='wrap')
        return np.column_stack([q[:, 0], q[:, 1], z + 0.05])
    y = fillnn(s['y3'], ok)[i, j]
    y = ndi.gaussian_filter1d(ndi.median_filter(y, size=9, mode='wrap'), 2, mode='wrap')
    return np.column_stack([q[:, 0], y + 0.05, -q[:, 1]])


def outline_evidence(q: np.ndarray, cue: np.ndarray, s: dict[str, Any], sectors: list[str], thr: float = 0.45) -> dict[str, Any]:
    """Share of an outline lying on a boundary cue (within 0.3 mm), and where the unsupported stretches are (4 sectors by outward normal)."""
    r = rs_closed(q, 0.1)
    rr = int(0.3 / PIX)
    near = ndi.maximum_filter(cue, size=2 * rr + 1)
    i, j = _to_px(r, s)
    edge = ndi.distance_transform_edt(s['ok']) * PIX
    sup = (near[i, j] > thr) | (edge[i, j] < 0.35)
    c = r.mean(0)
    t = np.roll(r, -1, 0) - np.roll(r, 1, 0)
    nrm = np.stack([t[:, 1], -t[:, 0]], 1)
    if np.sign(np.sum((r - c) * nrm)) < 0:
        nrm = -nrm
    sec = np.where(np.abs(nrm[:, 0]) >= np.abs(nrm[:, 1]), np.where(nrm[:, 0] > 0, 0, 1), np.where(nrm[:, 1] > 0, 2, 3))
    inferred = []
    for k in range(4):
        sel = sec == k
        tot, inf = float(sel.sum() * 0.1), float((sel & ~sup).sum() * 0.1)
        if inf >= 1.5 and tot > 0:
            inferred.append({'edge': sectors[k], 'inferred_mm': round(inf, 1), 'edge_mm': round(tot, 1)})
    return {'boundary_mm': round(len(r) * 0.1, 1), 'supported_fraction': round(float(sup.mean()), 2), 'inferred': inferred}


def segment_regions(M: Any, ft: dict[str, Any]) -> dict[str, Any]:
    """Run the v4 pipeline (geometry only) on a work-frame mesh."""
    st = {w: make_stack(M, ft, w) for w in ('top', 'side', 'shoulder')}
    sT, sS, sB = st['top'], st['side'], st['shoulder']
    cT, cS = make_cues(sT), make_cues(sS)
    rt, BT, MKT = seg_top(sT, cT, PRIOR)
    rs = seg_side_slope(sS, SIDE_ENV)
    empty = [k for k, m in {**rt, **rs}.items() if m.sum() * PIX * PIX < 5.0]
    if empty:
        raise SegmentError('The surface segmentation found no usable region for: ' + ', '.join(empty), {'empty_regions': empty,
                           'marker_pixels': {str(i): int((MKT == i).sum()) for i in (1, 2, 3, 4)}})
    stk = {'LC': sT, 'RC': sT, 'WH': sT, 'B1': sS, 'B2': sS}
    masks = {k: smooth_mask(m) for k, m in {**rt, **rs}.items()}
    raw = {k: outline(masks[k], stk[k]) for k in REG}
    fT, iT = regularise_group({k: raw[k] for k in ('LC', 'RC', 'WH')}, {k: masks[k] for k in ('LC', 'RC', 'WH')}, sT)
    fS, iS = regularise_group({k: raw[k] for k in ('B1', 'B2')}, {k: masks[k] for k in ('B1', 'B2')}, sS, closed_only=('B1', 'B2'))
    xr = {k: (float(raw[k][:, 0].min()), float(raw[k][:, 0].max())) for k in ('B1', 'B2')}
    rb = seg_top_btn(sB, xr)
    mB = {k: smooth_mask(rb[k]) for k in rb}
    rawB = {k: outline(mB[k], sB) for k in mB}
    fB, iB = regularise_group(rawB, mB, sB, closed_only=('B1', 'B2'))
    OL = {**fT, **fS}
    info = {**iT, **iS}
    PM = {k: polygon_mask(OL[k], stk[k]['x0'], stk[k]['y0'], stk[k]['nx'], stk[k]['ny']) for k in REG}
    PMB = {k: polygon_mask(fB[k], sB['x0'], sB['y0'], sB['nx'], sB['ny']) for k in fB}
    # ---- outline masks -> face ids
    tri, fs = M.tri, ft['fs']
    cen = tri.mean(1)
    up_f = fs[:, 2] > 0.1
    fl_f = (fs[:, 1] > 0.1) & (tri[:, :, 1].min(1) > 15)
    zl, yl = fillnn(sT['z'], sT['ok']), fillnn(sS['y3'], sS['ok'])
    vis_top = up_f & (np.abs(cen[:, 2] - _look(zl, sT, cen[:, 0], cen[:, 1])) < FACE_MARGIN_MM)
    vis_side = fl_f & (np.abs(cen[:, 1] - _look(yl, sS, cen[:, 0], -cen[:, 2])) < FACE_MARGIN_MM)
    lab = np.full(len(M.F), -1)
    ids = {k: i for i, k in enumerate(REG)}
    for k in ('WH', 'LC', 'RC'):
        lab[vis_top & (lab < 0) & _pix_in(PM[k], sT, cen[:, 0], cen[:, 1])] = ids[k]
    for k in ('B1', 'B2'):
        lab[vis_side & _pix_in(PM[k], sS, cen[:, 0], -cen[:, 2])] = ids[k]
    zlb = fillnn(sB['z'], sB['ok'])
    vis_topb = (fs[:, 2] > -0.05) & (cen[:, 1] > 24.9) & (np.abs(cen[:, 2] - _look(zlb, sB, cen[:, 0], cen[:, 1])) < FACE_MARGIN_MM)
    base = lab.copy()
    alt: dict[str, dict[str, np.ndarray]] = {}
    for k in ('B1', 'B2'):
        dside = _look(ndi.distance_transform_edt(~PM[k]) * PIX, sS, cen[:, 0], -cen[:, 2])
        cand = vis_topb & (base < 0) & _pix_in(PMB[k], sB, cen[:, 0], cen[:, 1])
        alt[k] = {'side_priority': np.flatnonzero(base == ids[k]), 'top_priority': np.flatnonzero((base == ids[k]) | cand & (dside <= 1.0)),
                  'balanced': np.flatnonzero((base == ids[k]) | cand & (dside <= BTN_TOP_D_MM))}
        lab[cand & (dside <= BTN_TOP_D_MM)] = ids[k]
    return {'lab': lab, 'ids': ids, 'stacks': st, 'cues': {'top': cT, 'side': cS}, 'B_top': BT, 'masks': PM, 'outlines': OL, 'shoulder_outlines': fB,
            'curves': info, 'shoulder_curves': iB, 'alt_face_sets': alt,
            'outlines_3d': {**{k: lift(OL[k], sT, 'top') for k in ('LC', 'RC', 'WH')}, **{k: lift(OL[k], sS, 'side') for k in ('B1', 'B2')}},
            'shoulder_outlines_3d': {k: lift(fB[k], sB, 'top') for k in fB},
            'defect_faces': int(ft['defect'].sum())}
