"""Worker of brain_mouse_shell_fit (server python: numpy, scipy, trimesh, OCP).

Fits the outer skin of a (symmetrised) scan region as ONE fair degree-p B-spline face per half (half + mirror, sewn) when the region is
mirror-symmetric, or one face over the full region when it is not (symmetry is never forced). Generic port of the manual sym_ref2 pipeline:
- domain = labelled shell faces (labels are hints), the half on one side of the mirror plane (exact cut), optional cut planes (exact), ears
  removed, jagged boundary smoothed and re-projected, holes (features) fan-filled with zero fit weight;
- 4 corners: ends of the plane sides + boundary turning > corner_turn_deg (>= corner_min_sep_mm apart); a 3-corner domain gets a 4th
  corner on its longest free side chosen by fit score; harmonic (cotan) map to the unit square, mirror side = v 0;
- constrained least squares (KKT): plane sides exactly on their plane, mirror G1 (row 1 - row 0 parallel to the plane normal), thin-plate
  energy lam, Gauss-Newton parameter correction; spans capped so the knot spacing is >= min_wavelength_mm / 2 (no waviness shorter than
  about min_wavelength_mm can be represented);
- OCP Geom_BSplineSurface (poles in the input frame), mirror copy by gp_Trsf.SetMirror, sewing, STEP; independent OCP deviation check.
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
from cadmcp_brain.studio.scan_symmetrise_worker import closest_on_surface, read_regions  # noqa: E402

WORKER_VERSION = 'shell_fit/3'
DEFAULTS = {'regions': ['top_shell'], 'mode': 'auto', 'fit_side': 'auto', 'cut_planes': [], 'degree': 3, 'spans_u': 10, 'spans_v': 6, 'lam': 1e-7,
            'min_wavelength_mm': 10.0, 'corner_turn_deg': 35.0, 'corner_min_sep_mm': 5.0, 'corner_window_mm': 3.0, 'smooth_iterations': 30,
            'tol_p95_mm': 0.2, 'tol_max_mm': 1.0, 'mirror_plane': None, 'unit_scale': 1.0, 'iterations': 5, 'front_cut': 'none',
            'front_cut_step_mm': 3.0, 'front_cut_refine_mm': 0.5, 'front_cut_start_fraction': 0.15, 'front_cut_stop_fraction': 0.75,
            'front_cut_margin_mm': 0.5}


# ------------------------------------------------------------------ B-spline least squares (port of sym_ref2/bsfit.py)
def knots(p, spans):
    return np.r_[np.zeros(p), np.linspace(0, 1, spans + 1), np.ones(p)]


def basis(t, p, x, nu=0):
    from scipy.interpolate import BSpline
    n = len(t) - p - 1
    x = np.clip(x, 0, 1 - 1e-12)
    return BSpline(t, np.eye(n), p, extrapolate=False)(x, nu=nu) if nu else BSpline.design_matrix(x, t, p).toarray()


class Surf:
    def __init__(self, p, q, su, sv):
        self.p, self.q = p, q
        self.tu, self.tv = knots(p, su), knots(q, sv)
        self.nu, self.nv = len(self.tu) - p - 1, len(self.tv) - q - 1
        self.P = None

    def A(self, u, v, du=0, dv=0):
        Bu = basis(self.tu, self.p, u, du)
        Bv = basis(self.tv, self.q, v, dv)
        return (Bu[:, :, None] * Bv[:, None, :]).reshape(len(u), -1)

    def ev(self, u, v, du=0, dv=0):
        return self.A(u, v, du, dv) @ self.P.reshape(-1, 3)

    def idx(self, i, j):
        return i * self.nv + j


def boundary_edges(F):
    e = np.sort(np.vstack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), axis=1)
    u, inv, cnt = np.unique(e, axis=0, return_inverse=True, return_counts=True)
    return u[cnt == 1], cnt[inv.ravel()].reshape(3, -1).T == 1


def loops_of(F):
    """Directed boundary loops (as they run in the faces)."""
    d = np.vstack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    key = {tuple(x) for x in d.tolist()}
    nxt = {}
    for a, b in d.tolist():
        if (b, a) not in key:
            nxt[a] = b
    loops, seen = [], set()
    for s in list(nxt):
        if s in seen:
            continue
        lp, c = [], s
        while c not in seen and c in nxt:
            seen.add(c)
            lp.append(c)
            c = nxt[c]
        loops.append(np.array(lp))
    return loops


def turning(P, Nrm, w):
    L = len(P)
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(np.r_[P, P[:1]], axis=0), axis=1))]
    tot = s[-1]
    out = np.zeros(L)
    for i in range(L):
        a = np.searchsorted(s, (s[i] - w) % tot) % L
        b = np.searchsorted(s, (s[i] + w) % tot) % L
        n = Nrm[i]
        u = P[i] - P[a]
        v = P[b] - P[i]
        u -= (u @ n) * n
        v -= (v @ n) * n
        out[i] = np.degrees(np.arctan2(np.cross(u, v) @ n, u @ v))
    return out, s[:-1], tot


def cotan_laplacian(V, F):
    import scipy.sparse as sp
    I, J, W = [], [], []
    for k in range(3):
        i, j, o = F[:, k], F[:, (k + 1) % 3], F[:, (k + 2) % 3]
        a = V[i] - V[o]
        b = V[j] - V[o]
        cot = (a * b).sum(1) / np.maximum(np.linalg.norm(np.cross(a, b), axis=1), 1e-12)
        w = np.maximum(0.5 * cot, 1e-4)
        I += [i, j]
        J += [j, i]
        W += [w, w]
    Wm = sp.coo_matrix((np.concatenate(W), (np.concatenate(I), np.concatenate(J))), shape=(len(V), len(V))).tocsr()
    return sp.diags(np.asarray(Wm.sum(1)).ravel()) - Wm


def harmonic_square(V, F, loop, cpos, Lap):
    import scipy.sparse.linalg as spl
    loop = np.roll(loop, -cpos[0])
    cp = [(c - cpos[0]) % len(loop) for c in cpos] + [len(loop)]
    sq = np.array([[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]], float)
    uvb = np.zeros((len(loop), 2))
    P = V[np.r_[loop, loop[0]]]
    side = np.zeros(len(loop), int)
    for k in range(4):
        a, b = cp[k], cp[k + 1]
        seg = np.linalg.norm(np.diff(P[a:b + 1], axis=0), axis=1)
        t = np.r_[0, np.cumsum(seg)] / max(seg.sum(), 1e-12)
        uvb[a:b] = sq[k] + (sq[k + 1] - sq[k]) * t[:-1, None]
        side[a:b] = k
    isb = np.zeros(len(V), bool)
    isb[loop] = True
    I = np.flatnonzero(~isb)
    UV = np.zeros((len(V), 2))
    UV[loop] = uvb
    A = Lap[I][:, I].tocsc()
    rhs = -Lap[I][:, loop] @ uvb
    lu = spl.splu(A)
    UV[I] = np.column_stack([lu.solve(rhs[:, 0]), lu.solve(rhs[:, 1])])
    bside = -np.ones(len(V), int)
    bside[loop] = side
    return UV, bside


def distortion(V, F, UV):
    e1 = V[F[:, 1]] - V[F[:, 0]]
    e2 = V[F[:, 2]] - V[F[:, 0]]
    x = e1 / np.maximum(np.linalg.norm(e1, axis=1), 1e-12)[:, None]
    n = np.cross(e1, e2)
    n /= np.maximum(np.linalg.norm(n, axis=1), 1e-12)[:, None]
    y = np.cross(n, x)
    P = np.stack([np.c_[(e1 * x).sum(1), (e1 * y).sum(1)], np.c_[(e2 * x).sum(1), (e2 * y).sum(1)]], 2)
    Q = np.stack([UV[F[:, 1]] - UV[F[:, 0]], UV[F[:, 2]] - UV[F[:, 0]]], 2)
    det = np.linalg.det(P)
    area = 0.5 * np.abs(det)
    ok = area > 1e-3 * max(float(np.median(area)), 1e-12)            # slivers from the exact plane cuts are not judged
    J = np.zeros_like(P)
    J[ok] = Q[ok] @ np.linalg.inv(P[ok])
    s = np.linalg.svd(J, compute_uv=False)
    flip = np.linalg.det(J) <= 0
    return s[:, 0] / np.maximum(s[:, 1], 1e-12), flip & ok, area


def fit(S, uv, X, w, lam, cons, ngrid=40):
    nc = S.nu * S.nv
    A = S.A(uv[:, 0], uv[:, 1])
    g = (np.arange(ngrid) + 0.5) / ngrid
    gu, gv = [a.ravel() for a in np.meshgrid(g, g, indexing='ij')]
    E = np.vstack([S.A(gu, gv, 2, 0), np.sqrt(2) * S.A(gu, gv, 1, 1), S.A(gu, gv, 0, 2)]) / ngrid
    H1 = (A * w[:, None]).T @ A + lam * float(w.sum()) * (E.T @ E)
    H = np.kron(H1, np.eye(3))
    rhs = ((A * w[:, None]).T @ X).ravel()
    if cons:
        C = np.array([c for c, _ in cons])
        dd = np.array([v for _, v in cons])
        K = np.block([[H, C.T], [C, np.zeros((len(C), len(C)))]])
        sol = np.linalg.lstsq(K, np.r_[rhs, dd], rcond=None)[0][:3 * nc]
    else:
        sol = np.linalg.solve(H, rhs)
    S.P = sol.reshape(S.nu, S.nv, 3)
    return S


def project(S, uv, X, iters=6, fix=None):
    uv = uv.copy()
    for _ in range(iters):
        P = S.ev(uv[:, 0], uv[:, 1])
        Su = S.ev(uv[:, 0], uv[:, 1], 1, 0)
        Sv = S.ev(uv[:, 0], uv[:, 1], 0, 1)
        r = X - P
        a11, a12, a22 = (Su * Su).sum(1), (Su * Sv).sum(1), (Sv * Sv).sum(1)
        b1, b2 = (Su * r).sum(1), (Sv * r).sum(1)
        det = a11 * a22 - a12 ** 2 + 1e-12
        du = (a22 * b1 - a12 * b2) / det
        dv = (a11 * b2 - a12 * b1) / det
        if fix is not None:
            du[fix[0]] = 0
            dv[fix[1]] = 0
        uv[:, 0] = np.clip(uv[:, 0] + np.clip(du, -0.05, 0.05), 0, 1)
        uv[:, 1] = np.clip(uv[:, 1] + np.clip(dv, -0.05, 0.05), 0, 1)
    return uv, np.linalg.norm(X - S.ev(uv[:, 0], uv[:, 1]), axis=1)


def fairness(S, N=81):
    g = np.linspace(0, 1, N)
    gu, gv = [a.ravel() for a in np.meshgrid(g, g, indexing='ij')]
    Su, Sv = S.ev(gu, gv, 1, 0), S.ev(gu, gv, 0, 1)
    Suu, Suv, Svv = S.ev(gu, gv, 2, 0), S.ev(gu, gv, 1, 1), S.ev(gu, gv, 0, 2)
    n = np.cross(Su, Sv)
    J = np.linalg.norm(n, axis=1)
    n /= np.maximum(J, 1e-12)[:, None]
    E, Fm, G = (Su * Su).sum(1), (Su * Sv).sum(1), (Sv * Sv).sum(1)
    L, M, Nn = (Suu * n).sum(1), (Suv * n).sum(1), (Svv * n).sum(1)
    den = np.maximum(E * G - Fm ** 2, 1e-12)
    H = (E * Nn - 2 * Fm * M + G * L) / (2 * den)
    K = (L * Nn - M ** 2) / den
    kmax = np.abs(H) + np.sqrt(np.maximum(H ** 2 - K, 0))
    Hg = H.reshape(N, N)
    gH = np.gradient(Hg, g, g)
    dH = np.hypot(gH[0] / np.linalg.norm(Su, axis=1).reshape(N, N).clip(1e-9), gH[1] / np.linalg.norm(Sv, axis=1).reshape(N, N).clip(1e-9))
    sinang = J / np.maximum(np.linalg.norm(Su, axis=1) * np.linalg.norm(Sv, axis=1), 1e-12)
    return {'dH_p95': float(np.percentile(dH, 95)), 'dH_max': float(dH.max()), 'kmax_p50': float(np.median(kmax)), 'kmax_p99': float(np.percentile(kmax, 99)),
            'kmax_max': float(kmax.max()), 'param_angle_min_deg': float(np.degrees(np.arcsin(np.clip(sinang.min(), 0, 1))))}


# ------------------------------------------------------------------ domain
def vertex_normals(V, F):
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    N = np.zeros_like(V)
    for k in range(3):
        np.add.at(N, F[:, k], fn)
    return N / np.maximum(np.linalg.norm(N, axis=1), 1e-300)[:, None]


def largest_component(V, F):
    import trimesh
    m = trimesh.Trimesh(V, F, process=False)
    parts = m.split(only_watertight=False)
    if not len(parts):
        raise WorkerError('SHELL_FIT_DOMAIN', 'The fitting domain is empty.')
    b = max(parts, key=lambda c: len(c.faces))
    return np.asarray(b.vertices, float), np.asarray(b.faces, np.int64)


def build_domain(V, F, planes, p, warnings):
    """planes: list of dicts (name, n, d, symmetry) in the aligned frame; keep n . x <= d. Returns V, F (disk, holes filled), weights, info."""
    import trimesh
    m = trimesh.Trimesh(V, F, process=False)
    m.remove_unreferenced_vertices()
    ref_V, ref_F = np.asarray(m.vertices).copy(), np.asarray(m.faces).copy()
    for pl in planes:
        m = trimesh.intersections.slice_mesh_plane(m, -np.asarray(pl['n']), np.asarray(pl['n']) * pl['d'])
        if len(m.faces) == 0:
            raise WorkerError('SHELL_FIT_DOMAIN', 'A cut plane removes the whole fitting domain.', {'plane': pl['name']})
    m.merge_vertices()
    V, F = largest_component(np.asarray(m.vertices, float), np.asarray(m.faces, np.int64))
    for pl in planes:                                          # snap near-plane vertices (float32 STL input) onto the exact plane
        nn = np.asarray(pl['n'])
        off = V @ nn - pl['d']
        near = np.abs(off) < 0.01
        V[near] -= off[near, None] * nn

    def on_planes(X):
        return np.column_stack([np.abs(X @ np.asarray(pl['n']) - pl['d']) < 1e-6 for pl in planes]) if planes else np.zeros((len(X), 0), bool)

    for _ in range(60):                                        # remove ears (faces with >= 2 boundary edges), keep exact cut boundaries
        _, fb = boundary_edges(F)
        onp = on_planes(V)
        oncut = (onp[F].sum(1) >= 2).any(1) if planes else np.zeros(len(F), bool)
        ear = (fb.sum(1) >= 2) & ~oncut
        if not ear.any():
            break
        V, F = largest_component(V, F[~ear])
    for _ in range(int(p['smooth_iterations'])):               # smooth the jagged label boundary, re-project onto the region
        be, _ = boundary_edges(F)
        nb: dict[int, list[int]] = {}
        for a, c in be.tolist():
            nb.setdefault(a, []).append(c)
            nb.setdefault(c, []).append(a)
        idx = np.array([k for k, v in nb.items() if len(v) == 2])
        if len(idx) == 0:
            break
        avg = np.array([V[nb[k]].mean(0) for k in idx])
        new = 0.5 * V[idx] + 0.5 * avg
        onp = on_planes(V[idx])
        for k, pl in enumerate(planes):
            sel = onp[:, k]
            nn = np.asarray(pl['n'])
            new[sel] -= ((new[sel] @ nn) - pl['d'])[:, None] * nn
        free = ~onp.any(1) if planes else np.ones(len(idx), bool)
        if free.any():
            new[free] = closest_on_surface(ref_V, ref_F, new[free])[0]
        V = V.copy()
        V[idx] = new
    loops = loops_of(F)
    if not loops:
        raise WorkerError('SHELL_FIT_DOMAIN', 'The fitting domain has no boundary (closed surface); give cut planes or a shell region with an opening.')
    lens = [float(np.linalg.norm(np.diff(V[np.r_[lp, lp[:1]]], axis=0), axis=1).sum()) for lp in loops]
    outer = int(np.argmax(lens))
    w = np.zeros(len(V))
    A = 0.5 * np.linalg.norm(np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]), axis=1)
    np.add.at(w, F.ravel(), np.repeat(A / 3, 3))
    w /= max(w.mean(), 1e-12)
    holes = []
    for k, lp in enumerate(loops):                             # fan-fill holes (features) with a zero-weight centre vertex
        if k == outer:
            continue
        c = len(V)
        V = np.vstack([V, V[lp].mean(0)])
        w = np.r_[w, 0.0]
        nxt = np.roll(lp, -1)
        F = np.vstack([F, np.column_stack([nxt, lp, np.full(len(lp), c)])])
        holes.append({'boundary_mm': lens[k], 'vertices': int(len(lp))})
    if holes:
        warnings.append(f'{len(holes)} hole(s) in the fitting domain (features) were bridged by the fair surface; their points carry no fit weight.')
    return V, F, w, {'faces': int(len(F)), 'vertices': int(len(V)), 'holes_filled': holes, 'boundary_length_mm': lens[outer], 'outer_loop': loops[outer]}


def orient_loop(V, F, loop):
    P = V[loop]
    c = P.mean(0)
    area_vec = np.cross(P - c, np.roll(P, -1, 0) - c).sum(0)
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]).sum(0)
    return loop if area_vec @ fn >= 0 else loop[::-1]


# ------------------------------------------------------------------ layout + fit
class Layout:
    def __init__(self, V, F, w, loop, planes, p, log):
        self.V, self.F, self.w, self.loop, self.planes, self.p, self.log = V, F, w, loop, planes, p, log
        self.Pl = V[loop]
        self.Lap = cotan_laplacian(V, F)
        Nl = vertex_normals(V, F)[loop]
        self.tang, self.s, self.tot = turning(self.Pl, Nl, p['corner_window_mm'])
        onp = np.column_stack([np.abs(self.Pl @ np.asarray(pl['n']) - pl['d']) < 1e-5 for pl in planes]) if planes else np.zeros((len(loop), 0), bool)
        for k in range(onp.shape[1]):                          # close 1-2 vertex gaps inside a plane run
            on = onp[:, k]
            for g in (1, 2):
                fill = np.zeros_like(on)
                for sh in range(1, g + 1):
                    fill |= np.roll(on, sh) & np.roll(on, -(g + 1 - sh))
                on = on | (fill & ~on)
            onp[:, k] = on
        self.onp = onp
        forced = []
        for k in range(onp.shape[1]):                          # ends of each plane run are corners
            on = onp[:, k]
            if not on.any() or on.all():
                continue
            starts = np.flatnonzero(on & ~np.roll(on, 1))
            ends = np.flatnonzero(on & ~np.roll(on, -1))
            for a, b in zip(starts, ends):
                forced += [int(a), int(b)]
        forced = sorted(set(forced))
        sep = p['corner_min_sep_mm']
        if planes and len(forced) > 1:                          # ends of two different plane runs a few tenths apart = one corner (plane/plane meet)
            pd = np.column_stack([np.abs(self.Pl @ np.asarray(pl['n']) - pl['d']) for pl in planes])
            merged = True
            while merged and len(forced) > 1:
                merged = False
                for a_, b_ in zip(forced, forced[1:] + forced[:1]):
                    if a_ != b_ and self._dist(a_, b_) < sep and not (onp[a_] & onp[b_]).any():
                        keep = a_ if pd[a_].sum() <= pd[b_].sum() else b_
                        forced = sorted(set(forced) - {a_, b_} | {keep})
                        log.setdefault('merged_plane_ends', []).append({'pos': self.Pl[keep].round(2).tolist(), 'gap_mm': float(self._dist(a_, b_))})
                        merged = True
                        break
        cs = list(forced)
        for i in np.argsort(-np.abs(self.tang)):
            if abs(self.tang[i]) < p['corner_turn_deg']:
                break
            if all(self._dist(i, c) > sep for c in cs):
                cs.append(int(i))
        if len(cs) > 4:
            free = sorted([c for c in cs if c not in forced], key=lambda c: -abs(self.tang[c]))
            if len(forced) > 4:
                raise WorkerError('SHELL_FIT_LAYOUT', 'The domain has more than 4 plane-side ends; use fewer cut planes.', {'plane_ends': len(forced)})
            cs = forced + free[:4 - len(forced)]
        self.forced = forced
        self.corners0 = sorted(cs)
        log['corners_detected'] = [{'pos': self.Pl[c].round(2).tolist(), 'turn_deg': float(self.tang[c]), 'plane_end': c in forced} for c in self.corners0]

    def _dist(self, i, j):
        a = abs(self.s[i] - self.s[j])
        return min(a, self.tot - a)

    def sides(self, cs):
        out = []
        for k in range(len(cs)):
            a, b = cs[k], cs[(k + 1) % len(cs)]
            ids = np.arange(a, b + 1) if b > a else np.r_[np.arange(a, len(self.loop)), np.arange(0, b + 1)]
            P = self.Pl[ids]
            cut = None
            for kk, pl in enumerate(self.planes):
                if self.onp[ids, kk].mean() >= 0.8:
                    cut = pl
            out.append({'ids': ids, 'length': float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum()), 'cut': cut['name'] if cut else None,
                        'plane': (np.asarray(cut['n'], float), float(cut['d'])) if cut else None, 'sym': bool(cut is not None and cut['symmetry'])})
        return out

    def free_side(self, cs):
        si = self.sides(cs)
        cand = [i for i in range(len(si)) if si[i]['cut'] is None] or list(range(len(si)))
        return max(cand, key=lambda i: si[i]['length']), si

    def setup(self, cs):
        SI = self.sides(cs)
        ks = [i for i in range(4) if SI[i]['sym']]
        r = ks[0] if ks else 0
        self.corners = cs[r:] + cs[:r]
        self.SI = SI[r:] + SI[:r]
        self.UV, self.bside = harmonic_square(self.V, self.F, self.loop, self.corners, self.Lap)
        dist_, flip, tri_area = distortion(self.V, self.F, self.UV)
        self.fix = (np.isin(self.bside, [1, 3]), np.isin(self.bside, [0, 2]))
        self.param = {'conformal_distortion_p50': float(np.median(dist_)), 'conformal_distortion_p95': float(np.percentile(dist_, 95)), 'flipped_triangles': int(flip.sum()),
                      'flipped_area_fraction': float(tri_area[flip].sum() / max(tri_area.sum(), 1e-12)),
                      'sides': [{'length_mm': si['length'], 'plane': si['cut'], 'mirror': si['sym']} for si in self.SI]}

    def constraints(self, S):
        nc = S.nu * S.nv
        C = []

        def row(i, j, k, val=1.0):
            r_ = np.zeros(3 * nc)
            r_[3 * S.idx(i, j) + k] = val
            return r_

        def side_ctrl(k, off=0):
            return {0: [(i, off) for i in range(S.nu)], 1: [(S.nu - 1 - off, j) for j in range(S.nv)],
                    2: [(i, S.nv - 1 - off) for i in range(S.nu)], 3: [(off, j) for j in range(S.nv)]}[k]
        for k, si in enumerate(self.SI):
            if si['plane'] is None:
                continue
            n, d = si['plane']
            for (i, j) in side_ctrl(k):
                C.append((sum(row(i, j, a, n[a]) for a in range(3)), d))
            if si['sym']:
                t1 = np.cross(n, [1, 0, 0] if abs(n[0]) < 0.9 else [0, 0, 1])
                t1 /= np.linalg.norm(t1)
                t2 = np.cross(n, t1)
                for (i0, j0), (i1, j1) in zip(side_ctrl(k, 0), side_ctrl(k, 1)):
                    for t in (t1, t2):
                        C.append((sum(row(i1, j1, a, t[a]) - row(i0, j0, a, t[a]) for a in range(3)), 0.0))
        return C

    def run(self, deg, su, sv, lam, iters):
        S = Surf(deg, deg, su, sv)
        uv = self.UV.copy()
        C = self.constraints(S)
        d = None
        for _ in range(iters):
            fit(S, uv, self.V, self.w, lam, C)
            uv, d = project(S, uv, self.V, fix=self.fix)
        return S, uv, d


def choose_layout(L: Layout, log):
    cs = list(L.corners0)
    if len(cs) < 2:                                           # smooth disk without plane sides: quarter points from the sharpest turn
        i0 = int(np.argmax(np.abs(L.tang))) if len(L.tang) else 0
        targets = [(L.s[i0] + q * L.tot / 4) % L.tot for q in range(4)]
        cs = sorted({int(np.argmin(np.abs(L.s - t))) for t in targets})
        log['corner_rule'] = 'no corners: quarter points of the boundary'
    while len(cs) == 2:
        k, si = L.free_side(cs)
        ids = si[k]['ids']
        cs = sorted(cs + [int(ids[len(ids) // 2])])
        log.setdefault('inserted_corners', []).append({'pos': L.Pl[cs[-1]].round(2).tolist(), 'rule': 'middle of the longest free side'})
    if len(cs) == 3:
        k, si = L.free_side(cs)
        ids = si[k]['ids']
        rows = []
        for fr in np.arange(0.2, 0.86, 0.05):
            c4 = int(ids[int(fr * (len(ids) - 1))])
            L.setup(sorted(cs + [c4]))
            S, uv, d = L.run(min(5, L.p['degree'] + 2), 6, 4, 1e-8, 3)
            fa = fairness(S)
            rows.append({'frac': float(fr), 'corner': c4, 'pos': L.Pl[c4].round(2).tolist(), 'p95': float(np.percentile(d[L.w > 0], 95)),
                         'max': float(d[L.w > 0].max()), **fa})
        b = min(r['dH_p95'] for r in rows) or 1e-12
        for r in rows:
            r['score'] = r['p95'] / 0.1 + r['max'] / 1.0 + r['dH_p95'] / b + max(0, 30 - r['param_angle_min_deg']) / 10
        best = min(rows, key=lambda r: r['score'])
        cs = sorted(cs + [best['corner']])
        log['corner_selection'] = [{k: v for k, v in r.items() if k != 'corner'} for r in rows]
        log.setdefault('inserted_corners', []).append({'pos': best['pos'], 'rule': 'scored 4th corner on the longest free side', 'side_fraction': best['frac']})
    L.setup(cs)
    return cs


# ------------------------------------------------------------------ frames + OCP
def aligned_frame(n, d):
    n = np.asarray(n, float) / np.linalg.norm(n)
    base = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 0, 1.0])
    ex = base - n * (base @ n)
    ex /= np.linalg.norm(ex)
    ez = np.cross(ex, n)
    R = np.vstack([ex, n, ez])
    return R, float(d)


def to_aligned(X, R, d):
    Y = X @ R.T
    Y[:, 1] -= d
    return Y


def to_input(Y, R, d):
    Z = np.asarray(Y, float).copy()
    Z[..., 1] += d
    return Z @ R


def read_symmetry(path: Path | None, p):
    if p.get('mirror_plane'):
        mp = p['mirror_plane']
        return {'normal': mp['normal'], 'd': mp['d'], 'regions': None, 'source': 'argument'}
    if path is None:
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    pl = data.get('plane') or {}
    if 'normal' not in pl or 'd' not in pl:
        raise WorkerError('SHELL_FIT_SYMMETRY', 'The symmetry report has no plane {normal, d}.')
    regs = (data.get('symmetry_test') or {}).get('regions') or data.get('regions')
    return {'normal': pl['normal'], 'd': pl['d'], 'regions': regs, 'valid': (data.get('symmetry_test') or {}).get('global', {}).get('plane_valid', True),
            'source': 'report'}


def numeric_fit(Va, F0, sel, half, R, d0, p, warnings):
    """Domain + layout + constrained fit (numpy only, no OCP / files) for the cut planes in p['cut_planes'] (input frame)."""
    planes = []
    for k, cp in enumerate(p['cut_planes']):
        n_in = np.asarray(cp['normal'], float)
        n_in /= np.linalg.norm(n_in)
        nA = R @ n_in
        dA = float(cp['d']) - d0 * nA[1]
        if half and abs(nA[1]) > 1e-3:
            warnings.append(f'cut plane {k} is not perpendicular to the mirror plane; the two halves will not meet it symmetrically.')
        planes.append({'name': f'cut{k}', 'n': nA.tolist(), 'd': dA, 'symmetry': False})
    Fs = F0[sel]
    side_info = None
    if half:
        cen = Va[Fs].mean(1)
        area = 0.5 * np.linalg.norm(np.cross(Va[Fs[:, 1]] - Va[Fs[:, 0]], Va[Fs[:, 2]] - Va[Fs[:, 0]]), axis=1)
        a_pos, a_neg = float(area[cen[:, 1] > 0].sum()), float(area[cen[:, 1] < 0].sum())
        side = {'positive': 1, 'negative': -1}.get(p['fit_side'], 1 if a_pos >= a_neg else -1)
        side_info = {'fitted_side': 'positive' if side > 0 else 'negative', 'area_positive_mm2': a_pos, 'area_negative_mm2': a_neg,
                     'rule': p['fit_side'] if p['fit_side'] != 'auto' else 'auto: side with the larger region area (fewer feature holes)'}
        planes = [{'name': 'mirror', 'n': [0.0, -float(side), 0.0], 'd': 0.0, 'symmetry': True}] + planes      # keep side * y >= 0
    V, F, w, dom = build_domain(Va, Fs, planes, p, warnings)
    log: dict[str, Any] = {}
    loop = orient_loop(V, F, dom.pop('outer_loop'))
    L = Layout(V, F, w, loop, planes, p, log)
    choose_layout(L, log)
    # spans capped by the minimum representable wavelength
    lu = 0.5 * (L.SI[0]['length'] + L.SI[2]['length'])
    lv = 0.5 * (L.SI[1]['length'] + L.SI[3]['length'])
    h = 0.5 * p['min_wavelength_mm']
    su = int(max(1, min(p['spans_u'], np.floor(lu / h))))
    sv = int(max(1, min(p['spans_v'], np.floor(lv / h))))
    if (su, sv) != (p['spans_u'], p['spans_v']):
        warnings.append(f'spans reduced from {p["spans_u"]}x{p["spans_v"]} to {su}x{sv} so the knot spacing stays >= min_wavelength_mm / 2.')
    S, uv, dist = L.run(p['degree'], su, sv, p['lam'], int(p['iterations']))
    return {'planes': planes, 'V': V, 'F': F, 'w': w, 'dom': dom, 'L': L, 'log': log, 'S': S, 'uv': uv, 'dist': dist, 'su': su, 'sv': sv,
            'lu': lu, 'lv': lv, 'side_info': side_info, 'Fs': Fs}


def fit_passes(fr, p):
    """READY criteria of the wrapper (deviation p95 / max, parameterisation, min wavelength) on a numeric fit."""
    wt = fr['w'] > 0
    d = fr['dist'][wt]
    L = fr['L']
    fa = fairness(fr['S'])
    knot = min(fr['lu'] / fr['su'], fr['lv'] / fr['sv'])
    row = {'p95_mm': float(np.percentile(d, 95)), 'max_mm': float(d.max()), 'flipped_area_fraction': L.param['flipped_area_fraction'],
           'param_angle_min_deg': fa['param_angle_min_deg'], 'min_wavelength_mm': 2 * knot}
    row['ready'] = bool(row['p95_mm'] <= p['tol_p95_mm'] and row['max_mm'] <= p['tol_max_mm'] and row['flipped_area_fraction'] <= 1e-3
                        and row['param_angle_min_deg'] >= 10 and row['min_wavelength_mm'] >= p['min_wavelength_mm'] - 1e-9)
    return row


def front_sign(Va, F0, sel, region, names):
    """+1 / -1: front along the aligned x axis = side of the click regions (labels are hints); +1 without click labels."""
    clicks = [names.index(r) for r in ('left_click', 'right_click', 'LC', 'RC') if r in names]
    cen = Va[F0].mean(1)
    if clicks and np.isin(region, clicks).any():
        return (1.0 if cen[np.isin(region, clicks), 0].mean() >= cen[sel, 0].mean() else -1.0), 'side of the click regions'
    return 1.0, 'no click regions in the labels: +x of the aligned frame'


def auto_front_cut(Va, F0, sel, region, names, half, R, d0, p):
    """With click labels: the front (clicks, lip, front wall) is built by brain_mouse_shell_solid, so the cut is at the rear end of the click
    regions minus front_cut_margin_mm, stepped back by front_cut_step_mm until the fit is READY. Without click labels: no cut first; if that is
    not READY, the most forward READY cut (coarse scan backwards in front_cut_step_mm, forward refinement in front_cut_refine_mm, at most one
    step). Cut planes are perpendicular to the front axis and the mirror plane."""
    rows = []
    q = {**p, 'cut_planes': []}

    def trial(x):
        cp = None
        if x is not None:
            n_in = sgn * R[0]
            o = to_input(np.array([[x, 0.0, 0.0]]), R, d0)[0]
            cp = {'normal': n_in.tolist(), 'd': float(n_in @ o)}
        try:
            fr = numeric_fit(Va, F0, sel, half, R, d0, {**q, 'cut_planes': [cp] if cp else []}, [])
            row = fit_passes(fr, p)
        except WorkerError as exc:
            row = {'ready': False, 'error': exc.code}
        row['cut_x_aligned'] = None if x is None else float(x)
        rows.append(row)
        return row, cp
    sgn, why = front_sign(Va, F0, sel, region, names)
    out = {'mode': 'auto', 'front_rule': why, 'candidates': rows, 'chosen': None, 'chosen_x_aligned': None}
    xs = Va[np.unique(F0[sel].ravel()), 0] * sgn
    x0, x1 = float(xs.min()), float(xs.max())
    Lx = x1 - x0
    step, fine = float(p['front_cut_step_mm']), float(p['front_cut_refine_mm'])
    clicks = [names.index(r) for r in ('left_click', 'right_click', 'LC', 'RC') if r in names]
    cm = np.isin(region, clicks) if clicks else np.zeros(len(F0), bool)
    if cm.any():
        v = float((Va[np.unique(F0[cm].ravel()), 0] * sgn).min()) - float(p['front_cut_margin_mm'])
        out['click_rear_aligned'] = float(sgn * (v + float(p['front_cut_margin_mm'])))
        while v >= x1 - p['front_cut_stop_fraction'] * Lx:
            r, cp = trial(sgn * v)
            if r['ready']:
                out['chosen'], out['chosen_x_aligned'] = cp, float(sgn * v)
                break
            v -= step
        out['rule'] = ('click regions labelled: cut at their rear end minus front_cut_margin_mm (the front is built by brain_mouse_shell_solid), '
                       'stepped back by front_cut_step_mm until READY' + ('' if out['chosen'] else '; no READY cut found'))
        return out
    r0, _ = trial(None)
    if r0['ready']:
        out['rule'] = 'the fit without a cut is READY: no cut'
        return out
    best = None
    x = x1 - p['front_cut_start_fraction'] * Lx
    while x >= x1 - p['front_cut_stop_fraction'] * Lx:
        r, cp = trial(sgn * x)
        if r['ready']:
            best = (x, cp)
            break
        x -= step
    if best is None:
        out['rule'] = 'no READY cut found between the start and stop fractions of the length'
        return out
    xb, xlim = best[0] + fine, best[0] + step - 1e-9
    while xb < xlim:
        r, cp = trial(sgn * xb)
        if not r['ready']:
            break
        best = (xb, cp)
        xb += fine
    out['chosen'], out['chosen_x_aligned'] = best[1], float(sgn * best[0])
    out['rule'] = ('most forward READY cut: coarse scan backwards from the front in front_cut_step_mm, then forward refinement in '
                   'front_cut_refine_mm (cut normal = front axis, perpendicular to the mirror plane)')
    return out


def run(req: dict[str, Any]) -> dict[str, Any]:
    import trimesh
    p = {**DEFAULTS, **(req.get('params') or {})}
    inp = req['inputs']
    warnings: list[str] = []
    m = trimesh.load(inp['mesh'], process=False, force='mesh')
    m.merge_vertices()
    V0 = np.asarray(m.vertices, float) * float(p['unit_scale'])
    F0 = np.asarray(m.faces, np.int64)
    region, names = read_regions(Path(inp['labels']) if inp.get('labels') else None, len(F0))
    if inp.get('labels'):
        missing = [r for r in p['regions'] if r not in names]
        if missing:
            raise WorkerError('SHELL_FIT_REGIONS_MISSING', 'A requested region is not in the label file.', {'missing': missing, 'available': names[1:]})
        sel = np.isin(region, [names.index(r) for r in p['regions']])
    else:
        sel = np.ones(len(F0), bool)
        warnings.append('No labels: the whole mesh is the fitting domain (give cut planes to open it).')
    sym = read_symmetry(Path(inp['symmetry']) if inp.get('symmetry') else None, p)
    mode = p['mode']
    sym_ok, why = False, 'no symmetry source'
    if sym is not None:
        regs = sym.get('regions')
        if not sym.get('valid', True):
            why = 'symmetry report: no usable mirror plane'
        elif regs is None:
            sym_ok, why = True, 'mirror plane given as argument'
        else:
            bad = [r for r in (p['regions'] if inp.get('labels') else list(regs)) if r in regs and not regs[r].get('symmetric')]
            unknown = [r for r in p['regions'] if r not in regs] if inp.get('labels') else []
            sym_ok = not bad and not unknown
            why = 'all domain regions symmetric in the report' if sym_ok else f'asymmetric or untested regions: {bad + unknown}'
    if mode == 'half' and not sym_ok:
        raise WorkerError('SHELL_FIT_NOT_SYMMETRIC', 'mode half needs a mirror-symmetric domain; symmetry is never forced.', {'reason': why})
    half = (mode == 'half') or (mode == 'auto' and sym_ok)
    if sym is not None:
        R, d0 = aligned_frame(sym['normal'], sym['d'])
    else:
        R, d0 = np.eye(3), 0.0
    Va = to_aligned(V0, R, d0)
    front_cut = None
    if p.get('front_cut', 'none') == 'auto' and not p['cut_planes']:
        front_cut = auto_front_cut(Va, F0, sel, region, names, half, R, d0, p)
        if front_cut['chosen'] is not None:
            p = {**p, 'cut_planes': [front_cut['chosen']]}
    fr = numeric_fit(Va, F0, sel, half, R, d0, p, warnings)
    planes, V, F, w, dom, L, log = fr['planes'], fr['V'], fr['F'], fr['w'], fr['dom'], fr['L'], fr['log']
    S, uv, dist, su, sv, lu, lv, side_info, Fs = fr['S'], fr['uv'], fr['dist'], fr['su'], fr['sv'], fr['lu'], fr['lv'], fr['side_info'], fr['Fs']
    wt = w > 0
    interior = wt & (L.bside < 0)
    fair = fairness(S)
    # mirror border continuity (aligned frame, side 0 = v 0 is the mirror side when half)
    t = np.linspace(0, 1, 201)
    mirror = None
    if half:
        Su0, Sv0 = S.ev(t, 0 * t, 1, 0), S.ev(t, 0 * t, 0, 1)
        n0 = np.cross(Su0, Sv0)
        n0 /= np.linalg.norm(n0, axis=1)[:, None]
        P0 = S.ev(t, 0 * t)
        mirror = {'G0_gap_to_plane_mm': float(np.abs(P0[:, 1]).max()),
                  'G1_normal_angle_deg_max': float(np.degrees(2 * np.arcsin(np.clip(np.abs(n0[:, 1]), 0, 1))).max()),
                  'cross_tangent_off_normal_deg_max': float(np.degrees(np.arccos(np.clip(np.abs(Sv0[:, 1]) / np.linalg.norm(Sv0, axis=1), 0, 1))).max()),
                  'G2_note': 'the cross-boundary tangent is along the plane normal, so the mirrored half has the same normal curvature (G2 by construction).'}
    # deviation of the other half (mirrored), if half
    other = None
    if half:
        sgn = 1 if side_info['fitted_side'] == 'positive' else -1
        Vo = Va[np.unique(Fs.ravel())]
        Vo = Vo[(Vo[:, 1] * sgn) < -1e-6] * [1, -1, 1]
        keep = np.ones(len(Vo), bool)
        for pl in planes[1:]:
            keep &= Vo @ np.asarray(pl['n']) <= pl['d']
        Vo = Vo[keep]
        if len(Vo):
            from scipy.spatial import cKDTree
            j = cKDTree(V[wt]).query(Vo)[1]
            uvo, do = project(S, uv[wt][j], Vo, iters=8)
            ins = ((uvo > 1e-4) & (uvo < 1 - 1e-4)).all(1)
            other = {**_st(do[ins]), 'note': 'points of the other half, mirrored, against the fitted half (residual asymmetry after symmetrisation)'}
    # OCP
    from cadmcp_brain.studio import cad_brep_lib as cb
    cb.require_ocp()
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_Sewing, BRepBuilderAPI_Transform
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf
    P_in = to_input(S.P, R, d0)
    gs = cb.bsurf(P_in, S.tu, S.tv, S.p, S.q)
    face = BRepBuilderAPI_MakeFace(gs, 1e-6).Face()
    sew = BRepBuilderAPI_Sewing(1e-3)
    sew.Add(face)
    nrm = np.asarray(sym['normal'], float) / np.linalg.norm(sym['normal']) if sym else None
    if half:
        tr = gp_Trsf()
        o = nrm * d0
        tr.SetMirror(gp_Ax2(gp_Pnt(*map(float, o)), gp_Dir(*map(float, nrm))))
        sew.Add(BRepBuilderAPI_Transform(face, tr, True).Shape())
    sew.Perform()
    shell = sew.SewedShape()
    out = Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    cb.write_step(shell, out / 'shell_skin.step')
    back = cb.read_step(out / 'shell_skin.step')
    X_in = to_input(V[wt], R, d0)
    pr = GeomAPI_ProjectPointOnSurf()
    dv = []
    for q in X_in[:: max(1, len(X_in) // 3000)]:
        pr.Init(gp_Pnt(*map(float, q)), gs)
        dv.append(pr.LowerDistance() if pr.NbPoints() else np.nan)
    dv = np.asarray(dv)
    knot_u = lu / su
    knot_v = lv / sv
    surf = {'degree': [S.p, S.q], 'spans': [su, sv], 'poles_shape': [S.nu, S.nv], 'knots_u': S.tu.tolist(), 'knots_v': S.tv.tolist(),
            'poles_input_frame': P_in.tolist(), 'mirror_plane': ({'normal': nrm.tolist(), 'd': d0} if half else None),
            'v0_side': 'mirror plane' if half else L.SI[0]['cut'], 'cut_planes': p['cut_planes']}
    (out / 'shell_surface.json').write_text(json.dumps(surf), encoding='utf-8')
    return {'worker': WORKER_VERSION, 'warnings': warnings, 'mode_used': 'half' if half else 'full', 'symmetry_reason': why, 'side': side_info,
            'symmetry_source': None if sym is None else sym.get('source'), 'domain': {**dom, 'cut_planes': p['cut_planes']},
            'layout': {**log, 'corners': [L.Pl[c].round(3).tolist() for c in L.corners], 'parameterisation': L.param},
            'fit': {'degree': S.p, 'spans': [su, sv], 'poles': [S.nu, S.nv], 'lam': p['lam'], 'knot_spacing_mm': [knot_u, knot_v],
                    'min_representable_wavelength_mm': 2 * min(knot_u, knot_v), 'requested_spans': [p['spans_u'], p['spans_v']]},
            'deviation': {'all': _st(dist[wt]), 'interior': _st(dist[interior]), 'ocp_check': _st(dv[~np.isnan(dv)]), 'other_half_mirrored': other},
            'mirror_border': mirror, 'fairness': fair,
            'brep': {'faces': len(cb.faces(back)), 'valid': cb.is_valid(back), 'free_edges_after_sew': int(sew.NbFreeEdges()),
                     'multiple_edges': int(sew.NbMultipleEdges()), 'shape_type': str(shell.ShapeType()).split('.')[-1]},
            'files': {'step': 'shell_skin.step', 'surface': 'shell_surface.json'}, 'params_used': p, 'front_cut': front_cut}


def _st(a):
    a = np.abs(np.asarray(a, float))
    if a.size == 0:
        return {'p50': None, 'p95': None, 'max': None, 'n': 0}
    return {'p50': float(np.median(a)), 'p95': float(np.percentile(a, 95)), 'max': float(a.max()), 'n': int(a.size)}


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
