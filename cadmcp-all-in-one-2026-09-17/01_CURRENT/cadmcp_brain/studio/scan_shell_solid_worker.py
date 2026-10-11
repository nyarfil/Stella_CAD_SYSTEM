"""Worker of brain_mouse_shell_solid (server python: numpy, scipy, trimesh, OCP).

Closes the open shell_fit skin (rear/top B-spline half + mirror, cut by a front plane) into the top-shell SOLID. Generic port of the
manual OP1 whole_v1 steps (w2 crease, w4 tube, w5 cap + closing), with every mouse-specific constant replaced by a measurement:
- frame: mirror plane (y), front axis = cut-plane normal (x, front = removed side), z up (flushed frame, plate floor z = 0);
- skin R: poles from shell_surface.json, re-oriented to u = 0 on the cut plane, v = 0 on the mirror plane; the two free (bottom)
  sides are extended exactly (polynomial continuation) by extension_mm so the parting surface trims them cleanly;
- parting surface: seam between shell and plate faces of the label file (labels are hints); 'seam' = fair B-spline height field
  through the seam points (mirror-symmetric when the skin is half + mirror), 'plane' = z-const (parting_z_mm or the seam median);
  'auto' = plane when the seam height range is <= flat_tolerance_mm, else seam; seam_to_crest (SS1.2): a seam point that lies on the
  lower / upper flank of a wall bulge (interior maximum of the outward wall profile within crest_window_mm, the wall dropping by
  >= crest_prominence_mm on both sides within crest_half_mm) moves onto the crest (the widest line = the parting line of a moulded
  shell; label seams there are only interpolated), the shifts are averaged over crest_smooth_mm along the seam; heightfield
  smoothing seam_smoothing (1e-2: a fair parting surface, the interior does not sag between the seam sides);
- front plan: silhouette of the front section (polar about the cut-plane centre point), stations by arc length, inward normals,
  profile planes exactly in the cut plane at both ends;
- crease Gamma (panel side / front lip) per station: quadratic top + straight wall fitted on the profile, intersected (groove bands
  next to the slot layout paths excluded); stations without a crisp turn are bridged; Gamma snaps to R's cut curve at S0 and is
  blended there; symmetric;
- tube W (flanks + front wall below Gamma): ONE B-spline strip, end columns = R's cut curve (exact G0) and R's cross derivative
  (exact G1); top row = Gamma; front sector stiffer and the lip band below Gamma excluded -> plain front wall (cable hole,
  under-lip groove ignored); inward outliers trimmed;
- cap C (panel tops in front of the cut): BRepOffsetAPI_MakeFilling, G1 to R / mirrored R on the cut curve, G1 to the tube on the
  first / last g1_end_mm of Gamma, C0 elsewhere = crisp lip by intersection of two faces; point constraints from a fair height
  field of the top data (window / centre gap / slot grooves excluded);
- closing: sew R, R mirrored, W, C; BOPAlgo_MakerVolume with the parting face; the solid that contains an interior point; ShapeFix;
  STEP write + re-import check (valid, one solid, face count, smallest face, volume).
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path
from typing import Any
import numpy as np

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cadmcp_brain.studio.scan_cad_common import WorkerError, worker_main  # noqa: E402

WORKER_VERSION = 'shell_solid/4'
DEFAULTS = {'shell_regions': ['top_shell', 'left_click', 'right_click'], 'plate_regions': ['bottom_plate', 'base_plate', 'plate', 'bottom'],
            'exclude_regions': ['wheel', 'WH', 'side_button_1', 'side_button_2', 'B1', 'B2', 'sensor'], 'exclude_margin_mm': 2.5,
            'parting_mode': 'auto', 'parting_z_mm': None, 'flat_tolerance_mm': 0.3, 'extension_mm': 3.0,
            'seam_to_crest': True, 'crest_window_mm': 1.0, 'crest_prominence_mm': 0.08, 'crest_half_mm': 0.75, 'crest_smooth_mm': 4.0,
            'seam_smoothing': 1e-2,
            'station_mm': 1.0, 'profile_halfwidth_mm': 0.35, 'crease_min_turn_deg': 20.0, 'groove_margin_mm': 1.2,
            'lip_band_mm': 4.2, 'front_sector_deg': 60.0, 'plain_front': True, 'robust_start_stiffness': 300.0, 'tube_spans': 40, 'tube_smoothing': 1e-5,
            'front_stiffness': 20.0, 'trim_inward_mm': 0.4, 'snap_blend_mm': 10.0, 'g1_end_mm': 3.0, 'cap_grid_mm': 2.5,
            'cap_smoothing': 0.5, 'cap_gamma_clear_mm': 1.5, 'fill_max_degree': 8, 'fill_max_segments': 48, 'min_face_area_mm2': 0.5,
            'unit_scale': 1.0, 'cut_planes': []}


# ------------------------------------------------------------------ B-spline helpers (numpy; clamped, polynomial extrapolation outside)
def bbasis(t, n, p, x, der=0):
    from scipy.interpolate import BSpline
    x = np.atleast_1d(np.asarray(x, float))
    B = np.zeros((len(x), n))
    for i in range(n):
        c = np.zeros(n)
        c[i] = 1
        b = BSpline(t, c, p, extrapolate=True)
        B[:, i] = (b.derivative(der) if der else b)(x)
    return B


def bs_eval(P, tu, tv, u, v, p=3, q=3, du=0, dv=0):
    u = np.atleast_1d(np.asarray(u, float))
    v = np.atleast_1d(np.asarray(v, float))
    if len(u) == 1 and len(v) > 1:
        u = np.full(len(v), u[0])
    if len(v) == 1 and len(u) > 1:
        v = np.full(len(u), v[0])
    Bu = bbasis(tu, P.shape[0], p, u, du)
    Bv = bbasis(tv, P.shape[1], q, v, dv)
    return np.einsum('ni,ijk,nj->nk', Bu, P, Bv)


def extend_max(P, tu, tv, eu, ev, p=3, q=3):
    """Exact polynomial continuation of a clamped B-spline surface at u = umax by eu and v = vmax by ev (parameter units)."""
    tu2 = np.r_[tu[:-p - 1], [tu[-1]], [tu[-1] + eu] * (p + 1)] if eu > 0 else np.asarray(tu, float)
    tv2 = np.r_[tv[:-q - 1], [tv[-1]], [tv[-1] + ev] * (q + 1)] if ev > 0 else np.asarray(tv, float)
    nu2, nv2 = len(tu2) - p - 1, len(tv2) - q - 1
    us = np.linspace(tu2[0], tu2[-1], 6 * nu2)
    vs = np.linspace(tv2[0], tv2[-1], 6 * nv2)
    UU, VV = np.meshgrid(us, vs, indexing='ij')
    X = bs_eval(P, tu, tv, UU.ravel(), VV.ravel(), p, q).reshape(len(us), len(vs), 3)
    Cu = np.linalg.lstsq(bbasis(tu2, nu2, p, us), np.eye(len(us)), rcond=None)[0]
    Cv = np.linalg.lstsq(bbasis(tv2, nv2, q, vs), np.eye(len(vs)), rcond=None)[0]
    return np.einsum('ai,ijk,bj->abk', Cu, X, Cv), tu2, tv2


def d2mat(n):
    D = np.zeros((max(n - 2, 0), n))
    for i in range(n - 2):
        D[i, i:i + 3] = [1, -2, 1]
    return D


def smooth1d(x, y, lam):
    from scipy.interpolate import make_smoothing_spline
    return make_smoothing_spline(x, y, lam=lam)


# ------------------------------------------------------------------ frame
def frame_of(mirror_n, mirror_d, cut_n):
    """Aligned frame: y = mirror normal, x = cut normal projected into the mirror plane (front = removed side), z = x cross y."""
    n = np.asarray(mirror_n, float)
    n /= np.linalg.norm(n)
    d = float(mirror_d)
    c = np.asarray(cut_n, float)
    c /= np.linalg.norm(c)
    ex = c - n * (c @ n)
    if np.linalg.norm(ex) < 0.5:
        raise WorkerError('SHELL_SOLID_FRAME', 'The front cut plane is not across the mirror plane (normals nearly parallel).')
    ex /= np.linalg.norm(ex)
    ez = np.cross(ex, n)
    if ez[2] < 0:                                            # keep z up (flushed frame): flip the mirror normal instead
        n, d = -n, -d
        ez = np.cross(ex, n)
    if ez[2] < 0.9:
        raise WorkerError('SHELL_SOLID_FRAME', 'The skin is not in a z-up frame (flushed frame, plate floor z = 0, is required).', {'ez': ez.tolist()})
    R = np.vstack([ex, n, ez])
    return R, d


def to_q(X, R, d):
    Y = np.asarray(X, float) @ R.T
    Y[..., 1] -= d
    return Y


def from_q(Y, R, d):
    Z = np.asarray(Y, float).copy()
    Z[..., 1] += d
    return Z @ R


# ------------------------------------------------------------------ skin R
def canonical_skin(P, tu, tv, xc, tol=1e-4):
    """Re-orient poles so that u = 0 is the cut side (x = xc) and v = 0 the mirror side (y = 0). Returns P, tu, tv, info."""
    sides = {'u0': P[0], 'u1': P[-1], 'v0': P[:, 0], 'v1': P[:, -1]}
    cut = [k for k, s in sides.items() if np.abs(s[:, 0] - xc).max() < tol]
    mir = [k for k, s in sides.items() if np.abs(s[:, 1]).max() < tol]
    if len(cut) != 1 or len(mir) != 1:
        raise WorkerError('SHELL_SOLID_SKIN', 'The skin has no single side on the cut plane and one on the mirror plane (needs a shell_fit half skin '
                          'with a front cut).', {'cut_sides': cut, 'mirror_sides': mir})
    cut, mir = cut[0], mir[0]
    if cut[0] == mir[0]:
        raise WorkerError('SHELL_SOLID_SKIN', 'The cut side lies opposite the mirror side; the cut must meet the mirror plane.', {'cut': cut, 'mirror': mir})
    if cut[0] == 'v':                                        # transpose: cut becomes a u side
        P = P.transpose(1, 0, 2)
        tu, tv = tv, tu
        cut, mir = 'u' + cut[1], 'v' + mir[1]
    if cut == 'u1':
        P = P[::-1]
        tu = 1 - tu[::-1]
    if mir == 'v1':
        P = P[:, ::-1]
        tv = 1 - tv[::-1]
    return np.ascontiguousarray(P), np.asarray(tu, float), np.asarray(tv, float)


# ------------------------------------------------------------------ mesh data
def load_mesh(path, scale):
    import trimesh
    m = trimesh.load(path, process=False, force='mesh')
    m.merge_vertices()
    return np.asarray(m.vertices, float) * scale, np.asarray(m.faces, np.int64)


def read_labels(path, nf):
    if path is None:
        return None, []
    path = Path(path)
    if path.suffix.lower() == '.npz':
        d = np.load(path, allow_pickle=False)
        lab = np.asarray(d['face_labels']).astype(int)
        names = {}
        for c in d['codes']:
            k, v = str(c).split('=')
            names[k] = int(v)
    else:
        data = json.loads(path.read_text(encoding='utf-8'))
        regs = data.get('regions', data)
        lab = np.zeros(nf, int)
        names = {'other': 0}
        for k, (nm, ids) in enumerate(sorted(regs.items()), 1):
            if isinstance(ids, dict):
                ids = ids.get('faces', [])
            lab[np.asarray(ids, int)] = k
            names[nm] = k
    if len(lab) != nf:
        raise WorkerError('SHELL_SOLID_LABELS', 'The label file does not match the mesh face count.', {'labels': len(lab), 'faces': nf})
    return lab, names


def region_mask(lab, names, wanted):
    ids = [names[r] for r in wanted if r in names]
    return np.isin(lab, ids) if ids else np.zeros(len(lab), bool)


def seam_points(V, F, shell_mask, plate_mask):
    """Vertices of mesh edges shared by a shell face and a plate face."""
    e = np.vstack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    fid = np.tile(np.arange(len(F)), 3)
    es = np.sort(e, axis=1)
    key = es[:, 0] * (len(V) + 1) + es[:, 1]
    o = np.argsort(key)
    key, fid, es = key[o], fid[o], es[o]
    same = key[1:] == key[:-1]
    a, b = fid[:-1][same], fid[1:][same]
    seam = (shell_mask[a] & plate_mask[b]) | (shell_mask[b] & plate_mask[a])
    vid = np.unique(es[:-1][same][seam].ravel())
    return V[vid]


def seam_to_crest(V, F, S, p):
    """Move seam points that sit on the flank of a wall bulge onto its crest. Per seam point: outward horizontal direction n = mean vertex
    normal within 1.5 mm (z part removed); outer wall profile r(z) = max (V - s) . n over 0.05 mm z bins of the vertices within 0.6 mm of
    the vertical plane through s and n; crest = the maximum of r over |z - z_s| <= crest_window_mm; it counts only when r drops by
    >= crest_prominence_mm both below and above it within crest_half_mm (an interior bulge, not a wall that keeps leaning out). The
    shifts are averaged over crest_smooth_mm (xy) along the seam. Returns the new points and a log."""
    from scipy.spatial import cKDTree
    win, prom, half, dz = float(p['crest_window_mm']), float(p['crest_prominence_mm']), float(p['crest_half_mm']), 0.05
    e1, e2 = V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]
    fn = np.cross(e1, e2)
    VN = np.zeros_like(V)
    for k in range(3):
        np.add.at(VN, F[:, k], fn)
    VN /= np.maximum(np.linalg.norm(VN, axis=1), 1e-12)[:, None]
    tree = cKDTree(V)
    zb = np.arange(-(win + half), win + half + 1e-9, dz)
    zc = zb + dz / 2
    inw = np.abs(zc) <= win
    shift = np.zeros(len(S))
    for i, s in enumerate(S):
        n = VN[tree.query_ball_point(s, 1.5)].mean(0)
        n[2] = 0.0
        nn = np.linalg.norm(n)
        if nn < 1e-6:
            continue
        n /= nn
        P = V[tree.query_ball_point(s, win + half + 1.5)] - s
        P = P[np.abs(P @ np.array([-n[1], n[0], 0.0])) < 0.6]
        idx = np.floor((P[:, 2] - zb[0]) / dz).astype(int)
        ok = (idx >= 0) & (idx < len(zb))
        prof = np.full(len(zb), -np.inf)
        np.maximum.at(prof, idx[ok], P[ok] @ n)
        if not np.isfinite(prof[inw]).any():
            continue
        j = np.flatnonzero(inw)[int(np.argmax(np.where(np.isfinite(prof[inw]), prof[inw], -np.inf)))]
        lo = prof[(zc >= zc[j] - half) & (zc <= zc[j] - half + 0.25)]
        hi = prof[(zc >= zc[j] + half - 0.25) & (zc <= zc[j] + half)]
        lo, hi = lo[np.isfinite(lo)], hi[np.isfinite(hi)]
        if len(lo) and len(hi) and prof[j] - lo.max() >= prom and prof[j] - hi.max() >= prom:
            shift[i] = zc[j]
    moved = shift != 0
    sm = float(p['crest_smooth_mm'])
    if sm > 0 and moved.any():
        st = cKDTree(S[:, :2])
        shift = np.array([shift[st.query_ball_point(q, sm)].mean() for q in S[:, :2]])
    out = S.copy()
    out[:, 2] += shift
    log = {'applied': True, 'points_on_a_crest': int(moved.sum()), 'points': int(len(S)), 'shift_mm': {**_st(shift[np.abs(shift) > 1e-9]), 'mean_signed': float(shift[np.abs(shift) > 1e-9].mean())} if (np.abs(shift) > 1e-9).any() else None,
           'rule': 'seam point on the flank of a wall bulge -> crest (widest line) when the wall drops >= crest_prominence_mm on both sides '
                   'within crest_half_mm; search |dz| <= crest_window_mm; shifts averaged over crest_smooth_mm along the seam',
           'window_mm': win, 'prominence_mm': prom, 'half_mm': half, 'smooth_mm': sm}
    return out, log


# ------------------------------------------------------------------ parting surface
def fit_heightfield(X, box, spacing, lam, symmetric):
    """Fair cubic B-spline height field z(x, y) through X over box = (x0, x1, y0, y1). Returns coefficient grid and knots."""
    from scipy.interpolate import BSpline
    x0, x1, y0, y1 = box
    nx = int(max(4, np.ceil((x1 - x0) / spacing) + 3))
    ny = int(max(4, np.ceil((y1 - y0) / spacing) + 3))
    kx = np.r_[[x0] * 3, np.linspace(x0, x1, nx - 2), [x1] * 3]
    ky = np.r_[[y0] * 3, np.linspace(y0, y1, ny - 2), [y1] * 3]
    Bx = BSpline.design_matrix(np.clip(X[:, 0], x0, x1), kx, 3).toarray()
    By = BSpline.design_matrix(np.clip(X[:, 1], y0, y1), ky, 3).toarray()
    A = np.einsum('ni,nj->nij', Bx, By).reshape(len(X), -1)
    Pen = np.kron(d2mat(nx).T @ d2mat(nx), np.eye(ny)) + np.kron(np.eye(nx), d2mat(ny).T @ d2mat(ny))
    cf = np.linalg.solve(A.T @ A + lam * len(X) * Pen + 1e-12 * np.eye(nx * ny), A.T @ X[:, 2]).reshape(nx, ny)
    if symmetric:
        cf = 0.5 * (cf + cf[:, ::-1])
    return cf, kx, ky


def eval_heightfield(cf, kx, ky, x, y):
    from scipy.interpolate import BSpline
    Bx = BSpline.design_matrix(np.clip(x, kx[0], kx[-1]), kx, 3).toarray()
    By = BSpline.design_matrix(np.clip(y, ky[0], ky[-1]), ky, 3).toarray()
    return np.einsum('ni,ij,nj->n', Bx, cf, By)


def heightfield_poles(cf, kx, ky):
    gx = np.array([kx[i + 1:i + 4].mean() for i in range(cf.shape[0])])
    gy = np.array([ky[j + 1:j + 4].mean() for j in range(cf.shape[1])])
    P = np.zeros(cf.shape + (3,))
    P[..., 0] = gx[:, None]
    P[..., 1] = gy[None, :]
    P[..., 2] = cf
    return P


# ------------------------------------------------------------------ front plan
class Plan:
    """Front plan curve (aligned frame, half y <= 0 mirrored): stations by arc length from the right cut point (s = 0) round the front
    to the left cut point (s = LS); outward normal per station; profile direction exactly -y / +y at the ends."""

    def __init__(self, Pxy, xc, blend_mm=4.0, n_bins=181):
        rel = Pxy - [xc, 0.0]
        phi = np.arctan2(rel[:, 1], rel[:, 0])
        r = np.hypot(rel[:, 0], rel[:, 1])
        ok = rel[:, 0] >= -1e-9
        phi, r = phi[ok], r[ok]
        phi = -np.abs(phi)                                   # fold to the right half (y <= 0)
        edges = np.linspace(-np.pi / 2, 0, n_bins)
        cen = 0.5 * (edges[1:] + edges[:-1])
        k = np.clip(np.digitize(phi, edges) - 1, 0, len(cen) - 1)
        rm = np.full(len(cen), np.nan)
        for i in range(len(cen)):
            s = r[k == i]
            if len(s) >= 3:
                rm[i] = np.percentile(s, 99.5)
        good = np.isfinite(rm)
        if good.sum() < 10:
            raise WorkerError('SHELL_SOLID_PLAN', 'The front section has too few points for a plan outline.')
        rm = np.interp(cen, cen[good], rm[good])
        from scipy.ndimage import gaussian_filter1d
        rm = gaussian_filter1d(np.r_[rm[::-1], rm], 2.0, mode='nearest')[len(rm):]
        ph = np.r_[-np.pi / 2, cen, 0.0]
        rr = np.r_[rm[0], rm, rm[-1]]
        half = np.c_[xc + rr * np.cos(ph), rr * np.sin(ph)]
        half[0, 0] = xc
        full = np.vstack([half, (half * [1, -1])[::-1][1:]])
        seg = np.linalg.norm(np.diff(full, axis=0), axis=1)
        s = np.r_[0, np.cumsum(seg)]
        self.LS = float(s[-1])
        self.s_ref, self.xy_ref = s, full
        ns = int(max(50, np.ceil(self.LS / 0.25)))
        self.ss = np.linspace(0, self.LS, ns + 1)
        self.xy = np.c_[np.interp(self.ss, s, full[:, 0]), np.interp(self.ss, s, full[:, 1])]
        t = np.gradient(self.xy, self.ss, axis=0)
        t /= np.linalg.norm(t, axis=1)[:, None]
        nrm = np.c_[t[:, 1], -t[:, 0]]                       # right of the travel direction = outward for a ccw-from-right path
        if nrm[0, 1] > 0:
            nrm = -nrm
        w = np.clip(np.minimum(self.ss, self.LS - self.ss) / blend_mm, 0, 1)
        w = w * w * (3 - 2 * w)
        end = np.where(self.ss[:, None] < self.LS / 2, [[0.0, -1.0]], [[0.0, 1.0]])
        nrm = (1 - w)[:, None] * end + w[:, None] * nrm
        self.n = nrm / np.linalg.norm(nrm, axis=1)[:, None]
        self.xc = xc
        from scipy.spatial import cKDTree
        self._tree = cKDTree(self.xy)

    def at(self, s):
        s = np.atleast_1d(s)
        O = np.c_[np.interp(s, self.ss, self.xy[:, 0]), np.interp(s, self.ss, self.xy[:, 1])]
        n = np.c_[np.interp(s, self.ss, self.n[:, 0]), np.interp(s, self.ss, self.n[:, 1])]
        return O, n / np.linalg.norm(n, axis=1)[:, None]

    def s_h(self, Pxy):
        """Station s (nearest plan point) and outward offset h of plan points."""
        _, j = self._tree.query(Pxy)
        s = self.ss[j]
        h = ((Pxy - self.xy[j]) * self.n[j]).sum(1)
        return s, h

    def front_weight(self, s, sector_deg):
        """1 where the outward normal is within sector_deg of the front axis, smooth 0 elsewhere."""
        _, n = self.at(s)
        ang = np.degrees(np.arccos(np.clip(n[:, 0], -1, 1)))
        w = np.clip((sector_deg + 5 - ang) / 10.0, 0, 1)
        return w * w * (3 - 2 * w)


def crease_at(h, z, nh, nz, top_ok, min_turn=20.0):
    """Two-line crease of one profile: h outward, z up, (nh, nz) the outward / up normal components of each point, top_ok = point may
    be used for the top fit (not in a groove band). Quadratic top (h -> z) + straight wall (z -> h), intersected; the initial guess is the
    top end of the outward-facing wall. Returns (h0, z0, turn_deg) or None (no crisp crease)."""
    wall = (np.abs(nz) < 0.45) & (nh > 0.5)
    topc = (nz > 0.5) & top_ok
    if wall.sum() < 10 or topc.sum() < 10:
        return None
    hw, zw = h[wall], z[wall]
    outer = hw > np.percentile(hw, 60) - 1.0
    z0 = float(np.percentile(zw[outer], 98))
    sel = outer & (zw > z0 - 2.5)
    h0 = float(np.median(hw[sel])) if sel.sum() >= 3 else float(np.percentile(hw, 90))
    a1 = a2 = None
    for _ in range(6):
        top = topc & (h < h0 - 0.4) & (h > h0 - 5.0) & (z > z0 - 2.0)
        wal = wall & (z < z0 - 0.4) & (z > z0 - 3.5) & (h > h0 - 1.5)
        if top.sum() < 8 or wal.sum() < 8:
            return None
        a1 = np.polyfit(h[top] - h0, z[top], 2)
        a2 = np.polyfit(z[wal], h[wal], 1)
        zz = np.linspace(z0 - 3, z0 + 3, 3001)
        hh = a2[0] * zz + a2[1]
        g = np.polyval(a1, hh - h0) - zz
        k = int(np.argmin(np.abs(g)))
        if abs(g[k]) > 0.05:
            return None
        h1, z1 = float(hh[k]), float(zz[k])
        done = abs(h1 - h0) < 0.01 and abs(z1 - z0) < 0.01
        h0, z0 = h1, z1
        if done:
            break
    sl = np.polyval(np.polyder(a1), 0.0)
    tt = np.r_[-1.0, -sl] / np.hypot(1, sl)                 # top tangent going inward
    tw = np.r_[-a2[0], -1.0] / np.hypot(a2[0], 1)            # wall tangent going down
    turn = 180.0 - np.degrees(np.arccos(np.clip(tt @ tw, -1, 1)))
    if turn < min_turn:
        return None
    return h0, z0, float(turn)


def sample_faces(tri, idx, density, seed=0):
    """Deterministic area sampling of triangles idx (points per mm2), with the face normal of each sample."""
    rng = np.random.default_rng(seed)
    T = tri[idx]
    area = 0.5 * np.linalg.norm(np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1)
    n = np.maximum(1, np.round(area * density).astype(int))
    fi = np.repeat(np.arange(len(idx)), n)
    a = rng.random((len(fi), 2))
    m = a.sum(1) > 1
    a[m] = 1 - a[m]
    P = T[fi, 0] + a[:, :1] * (T[fi, 1] - T[fi, 0]) + a[:, 1:] * (T[fi, 2] - T[fi, 0])
    fn = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    fn /= np.maximum(np.linalg.norm(fn, axis=1), 1e-12)[:, None]
    w = (area / n)[fi]
    return P, fn[fi], w, idx[fi]


def layout_paths(layout, R, d):
    """Plan polylines (aligned frame) of every slot path, centre-gap segment and window outline of a click_slot_layout/1."""
    out, window = [], None
    if not layout:
        return out, window

    def q(P):
        P = np.asarray(P, float).reshape(-1, 2)
        return to_q(np.c_[P, np.zeros(len(P))], R, d)[:, :2]
    per = (layout.get('perimeter') or {}).get('points')
    if per:
        out.append(q(per))
    for sg in (layout.get('centre_gap') or {}).get('segments') or []:
        a_, b_ = q(sg)
        out.append(np.c_[np.linspace(a_[0], b_[0], 200), np.linspace(a_[1], b_[1], 200)])
    wc = (layout.get('window') or {}).get('corners_TR_TL_BL_BR')
    if wc:
        c = q(wc)
        window = c
        out.append(np.vstack([np.c_[np.linspace(c[i, 0], c[(i + 1) % 4, 0], 100), np.linspace(c[i, 1], c[(i + 1) % 4, 1], 100)] for i in range(4)]))
    return out, window


def inside_poly(P, poly):
    from matplotlib.path import Path as MPath
    return MPath(poly).contains_points(P)


def measure_gamma(plan, Pt, Nt, top_ok, p, log):
    """Crease per station -> robust smoothing -> symmetric (h(s), z(s))."""
    st = np.arange(p['station_mm'], plan.LS - p['station_mm'] + 1e-9, p['station_mm'])
    rows = []
    for s in st:
        O, nn = plan.at(s)
        O, nn = O[0], nn[0]
        t = np.r_[-nn[1], nn[0]]
        rel = Pt[:, :2] - O
        on = (np.abs(rel @ t) < p['profile_halfwidth_mm']) & (rel @ nn > -15) & (rel @ nn < 3)
        r = crease_at(rel[on] @ nn, Pt[on, 2], Nt[on, :2] @ nn, Nt[on, 2], top_ok[on], p['crease_min_turn_deg'])
        rows.append([s, np.nan, np.nan, np.nan] if r is None else [s, *r])
    rows = np.array(rows)
    ok = np.isfinite(rows[:, 1])
    log['stations'] = int(len(rows))
    log['stations_with_crisp_crease'] = int(ok.sum())
    if ok.sum() < max(10, 0.3 * len(rows)):
        raise WorkerError('SHELL_SOLID_CREASE', 'Too few profiles show a crisp crease (panel side / front lip) in front of the cut.',
                          {'stations': int(len(rows)), 'crisp': int(ok.sum())})
    s_ok, h_ok, z_ok = rows[ok, 0], rows[ok, 1], rows[ok, 2]
    s_all = np.r_[s_ok, plan.LS - s_ok]                      # symmetric data (mirror: s -> LS - s)
    h_all, z_all = np.r_[h_ok, h_ok], np.r_[z_ok, z_ok]
    o = np.argsort(s_all)
    s_all, h_all, z_all = s_all[o], h_all[o], z_all[o]
    _, uq = np.unique(np.round(s_all, 6), return_index=True)
    s_all, h_all, z_all = s_all[uq], h_all[uq], z_all[uq]
    keep = np.ones(len(s_all), bool)
    for _ in range(5):                                       # robust: drop > 3 MAD outliers
        fh = smooth1d(s_all[keep], h_all[keep], 3.0)
        fz = smooth1d(s_all[keep], z_all[keep], 3.0)
        rh, rz = h_all - fh(s_all), z_all - fz(s_all)
        mh = 1.4826 * np.median(np.abs(rh[keep])) + 0.02
        mz = 1.4826 * np.median(np.abs(rz[keep])) + 0.02
        nk = (np.abs(rh) < 3 * mh) & (np.abs(rz) < 3 * mz)
        if (nk == keep).all():
            break
        keep = nk
    ss = plan.ss
    hG, zG = fh(ss), fz(ss)
    sym = lambda a_: 0.5 * (a_ + a_[::-1])
    log['crease_outliers_dropped'] = int((~keep).sum())
    log['crease_turn_deg'] = {'p50': float(np.median(rows[ok, 3])), 'min': float(rows[ok, 3].min()), 'max': float(rows[ok, 3].max())}
    return sym(hG), sym(zG), rows


def skin_split_v(PR, tuR, tvR, plan, hG, zG, log):
    """S0 = point of R's cut curve (u = 0) nearest to the crease extrapolated to s = 0 (cut-plane coordinates y, z)."""
    O, nn = plan.at(0.0)
    G0 = np.r_[O[0] + hG[0] * nn[0], zG[0]]
    vv = np.linspace(tvR[0], tvR[-1], 4001)
    C = bs_eval(PR, tuR, tvR, np.zeros_like(vv), vv)
    k = int(np.argmin(np.linalg.norm(C[:, 1:] - G0[1:], axis=1)))
    log['S0'] = {'v': float(vv[k]), 'point_aligned': C[k].tolist(), 'crease_extrapolated_aligned': [float(plan.xc), *G0[1:].tolist()],
                 'snap_mm': float(np.linalg.norm(C[k, 1:] - G0[1:]))}
    return float(vv[k]), C[k]


def build_gamma(plan, hG, zG, S0, p):
    """Snap Gamma to S0 at both ends (blend over snap_blend_mm) -> 3D polyline on plan.ss."""
    ss = plan.ss
    O, nn = plan.at(ss)
    e_h = float((S0[:2] - O[0]) @ nn[0]) - hG[0]             # S0 in profile coordinates of station 0 (in the cut plane)
    e_z = S0[2] - zG[0]
    b = np.clip(1 - ss / p['snap_blend_mm'], 0, 1)
    b = b * b * (3 - 2 * b)
    b = np.maximum(b, b[::-1])
    h = hG + e_h * b
    z = zG + e_z * b
    G = np.c_[O + h[:, None] * nn, z]
    G[0] = S0
    G[-1] = S0 * [1, -1, 1]
    return G, h, z
def fit_tube(PR, tuR, tvR, vS0, plan, G, zGs, D, Dw, p, log):
    """Tube strip (w4 port). D = front samples (aligned), Dw = weights; wall data = below Gamma. Returns poles Q (nu, nv, 3), knots."""
    LS = plan.LS
    ss = plan.ss
    vend = tvR[-1]
    inner = np.unique(tvR[(tvR > vS0) & (tvR < vend)])
    kn = np.r_[vS0, inner, vend]
    vk = np.sort(np.r_[kn, 0.5 * (kn[1:] + kn[:-1])])
    tvT = np.r_[[0] * 3, (vend - vk[::-1]) / (vend - vS0), [1] * 3]
    nvT = len(tvT) - 4
    vR_of = lambda vt: vend - vt * (vend - vS0)
    gv = np.linspace(0, 1, 8 * nvT)
    BvT = bbasis(tvT, nvT, 3, gv)
    Rb = bs_eval(PR, tuR, tvR, np.zeros_like(gv), vR_of(gv))
    C0 = np.linalg.lstsq(BvT, Rb, rcond=None)[0]
    Ru = bs_eval(PR, tuR, tvR, np.zeros_like(gv), vR_of(gv), du=1)
    D0 = np.linalg.lstsq(BvT, Ru, rcond=None)[0]
    log['tube_end_column_fit_error_mm'] = float(np.abs(BvT @ C0 - Rb).max())
    NUs = int(p['tube_spans'])
    tuT = np.r_[[0] * 3, np.linspace(0, 1, NUs + 1), [1] * 3]
    nuT = len(tuT) - 4
    mu = LS / np.median(np.linalg.norm(Ru, axis=1))
    # R_u points away from the cut (rearward); the tube's u runs forward from the right cut end -> S_u(0) = -mu R_u (exact G1)
    C1 = C0 - mu * tuT[4] / 3.0 * D0
    fixed = {0: C0, 1: C1, nuT - 1: C0 * [1, -1, 1], nuT - 2: C1 * [1, -1, 1]}
    zb_end = C0[0, 2]
    fz_end = (Rb[:, 2] - zb_end) / (G[0, 2] - zb_end)
    s_d, _ = plan.s_h(D[:, :2])
    zGi = np.interp(s_d, ss, zGs)

    def vparam(s, z):
        f = np.clip((z - zb_end) / (np.interp(s, ss, zGs) - zb_end), 0, 1)
        ve = np.interp(f, fz_end, gv) if np.all(np.diff(fz_end) > 0) else f
        bb = np.clip(1 - np.minimum(s, LS - s) / 12.0, 0, 1)
        bb = bb * bb * (3 - 2 * bb)
        return (1 - bb) * f + bb * ve
    sel = (D[:, 2] < zGi - 0.8) & (D[:, 0] >= plan.xc)
    if p['plain_front']:
        fw = plan.front_weight(s_d, p['front_sector_deg'])
        sel &= ~((fw > 0.5) & (D[:, 2] > zGi - p['lip_band_mm']))
    Pd, sd, wd = D[sel], s_d[sel], Dw[sel]
    if len(Pd) < 100:
        raise WorkerError('SHELL_SOLID_TUBE', 'Too few wall points below the crease in front of the cut.', {'points': int(len(Pd))})
    ud, vd = sd / LS, vparam(sd, Pd[:, 2])
    ug = ss / LS
    FS = float(p['front_stiffness'])
    sc_ = np.array([np.mean(tuT[i + 1:i + 4]) for i in range(nuT)]) * LS
    wcol = 1 + (FS - 1) * plan.front_weight(sc_, p['front_sector_deg'])
    idx = np.arange(nuT * nvT).reshape(nuT, nvT)
    fx = np.zeros(nuT * nvT, bool)
    X0 = np.zeros((nuT * nvT, 3))
    for i, Cc in fixed.items():
        fx[idx[i]] = True
        X0[idx[i]] = Cc
    Du = np.kron(d2mat(nuT) * np.sqrt(wcol[1:-1])[:, None], np.eye(nvT))
    Dv = np.kron(np.diag(np.sqrt(wcol)), d2mat(nvT))
    Pen = Du.T @ Du + Dv.T @ Dv
    Bug = bbasis(tuT, nuT, 3, ug)
    Bvg = bbasis(tvT, nvT, 3, np.ones_like(ug))
    Ag = np.einsum('ni,nj->nij', Bug, Bvg).reshape(len(ug), -1)
    WG = 50.0

    def solve(ud, vd, Pd, wd, stiff=1.0):
        Bu = bbasis(tuT, nuT, 3, ud)
        Bv = bbasis(tvT, nvT, 3, vd)
        A = np.einsum('ni,nj->nij', Bu, Bv).reshape(len(ud), -1)
        w_ = wd / wd.mean()
        H = (A * w_[:, None]).T @ A + WG * Ag.T @ Ag + stiff * p['tube_smoothing'] * len(ud) * Pen
        rhs = (A * w_[:, None]).T @ Pd + WG * Ag.T @ G
        X = X0.copy()
        fr = ~fx
        X[fr] = np.linalg.solve(H[np.ix_(fr, fr)], rhs[fr] - H[np.ix_(fr, fx)] @ X[fx])
        return X.reshape(nuT, nvT, 3)

    def normals(Q, ud, vd):
        nrm = np.cross(bs_eval(Q, tuT, tvT, ud, vd, du=1), bs_eval(Q, tuT, tvT, ud, vd, dv=1))
        return nrm / np.maximum(np.linalg.norm(nrm, axis=1), 1e-12)[:, None]

    keep = np.ones(len(Pd), bool)
    for it in range(7):
        # whole_v1 rule (cable-filled plain front wall): the first passes are stiff (robust_start_stiffness x smoothing) so recesses such as the
        # cable hole cannot pull the wall in; points more than trim_inward_mm inside are dropped from the second pass on
        Q = solve(ud[keep], vd[keep], Pd[keep], wd[keep], float(p['robust_start_stiffness']) if it < 3 else 1.0)
        for _ in range(2):                                   # Gauss-Newton parameter correction
            X = bs_eval(Q, tuT, tvT, ud, vd)
            Su = bs_eval(Q, tuT, tvT, ud, vd, du=1)
            Sv = bs_eval(Q, tuT, tvT, ud, vd, dv=1)
            r = Pd - X
            a11, a12, a22 = (Su * Su).sum(1), (Su * Sv).sum(1), (Sv * Sv).sum(1)
            b1, b2 = (Su * r).sum(1), (Sv * r).sum(1)
            det = a11 * a22 - a12 ** 2 + 1e-12
            ud = np.clip(ud + np.clip((a22 * b1 - a12 * b2) / det, -0.01, 0.01), 0, 1)
            vd = np.clip(vd + np.clip((a11 * b2 - a12 * b1) / det, -0.05, 0.05), 0, 1)
        if it >= 1 and p['trim_inward_mm'] > 0:              # recesses (cable hole, under-lip groove) are not followed
            X = bs_eval(Q, tuT, tvT, ud, vd)
            nrm = normals(Q, ud, vd)
            _, nn = plan.at(sd)
            sg = np.sign((nrm[:, :2] * nn).sum(1).mean())
            keep = ((Pd - X) * nrm).sum(1) * sg > -p['trim_inward_mm']
    Q = 0.5 * (Q + Q[::-1] * [1, -1, 1])                     # exact symmetry (data and ends are mirror-symmetric)
    X = bs_eval(Q, tuT, tvT, ud, vd)
    dist = np.abs(((Pd - X) * normals(Q, ud, vd)).sum(1))
    gtop = bs_eval(Q, tuT, tvT, ug, np.ones_like(ug))
    log['tube'] = {'spans_u': NUs, 'poles': [nuT, nvT], 'data_points': int(len(Pd)), 'trimmed_inward': int((~keep).sum()),
                   'deviation_kept': _st(dist[keep]), 'deviation_all': _st(dist), 'gamma_fit_error_mm': float(np.linalg.norm(gtop - G, axis=1).max()),
                   'symmetry_error_mm': 0.0}
    return Q, tuT, tvT


def cap_points(D, plan, hGs, zGs, G, layout_xy, window, p, log):
    """Point constraints of the cap: fair height field of the top data inside Gamma, sampled on a cap_grid_mm grid."""
    from scipy.interpolate import BSpline
    from scipy.spatial import cKDTree
    from matplotlib.path import Path as MPath
    sd, hd = plan.s_h(D[:, :2])
    hGi, zGi = np.interp(sd, plan.ss, hGs), np.interp(sd, plan.ss, zGs)
    cap = (D[:, 0] > plan.xc - 0.5) & (hd < hGi - 1.0) & (D[:, 2] > zGi + 0.3)
    if layout_xy:
        pp = np.vstack(layout_xy)
        pp = np.vstack([pp, pp * [1, -1]])
        cap &= cKDTree(pp).query(D[:, :2])[0] > p['groove_margin_mm']
    if window is not None:
        cap &= ~MPath(window).contains_points(D[:, :2]) & ~MPath(window * [1, -1]).contains_points(D[:, :2])
    C = D[cap]
    if len(C) < 50:
        raise WorkerError('SHELL_SOLID_CAP', 'Too few top points in front of the cut for the cap.', {'points': int(len(C))})
    X0, X1 = plan.xc - 1.0, float(G[:, 0].max()) + 2.0
    Y1 = float(np.abs(G[:, 1]).max()) + 2.0
    NX = NY = 22
    kx = np.r_[[X0] * 3, np.linspace(X0, X1, NX - 2), [X1] * 3]
    ky = np.r_[[-Y1] * 3, np.linspace(-Y1, Y1, NY - 2), [Y1] * 3]
    Bx = BSpline.design_matrix(np.clip(C[:, 0], X0, X1), kx, 3).toarray()
    By = BSpline.design_matrix(np.clip(C[:, 1], -Y1, Y1), ky, 3).toarray()
    A = np.einsum('ni,nj->nij', Bx, By).reshape(len(C), -1)
    Pen = np.kron(d2mat(NX).T @ d2mat(NX), np.eye(NY)) + np.kron(np.eye(NX), d2mat(NY).T @ d2mat(NY))
    cf = np.linalg.solve(A.T @ A + p['cap_smoothing'] * Pen, A.T @ C[:, 2]).reshape(NX, NY)
    cf = 0.5 * (cf + cf[:, ::-1])

    def Hz(x, y):
        return np.einsum('ni,ij,nj->n', BSpline.design_matrix(np.clip(x, X0, X1), kx, 3).toarray(), cf,
                         BSpline.design_matrix(np.clip(y, -Y1, Y1), ky, 3).toarray())
    res = C[:, 2] - Hz(C[:, 0], C[:, 1])
    GS = p['cap_grid_mm']
    gx, gy = np.meshgrid(np.arange(plan.xc + GS / 2, X1, GS), np.arange(-Y1, Y1 + 1e-9, GS))
    gp = np.c_[gx.ravel(), gy.ravel()]
    s_, h_ = plan.s_h(gp)
    ins = (h_ < np.interp(s_, plan.ss, hGs) - p['cap_gamma_clear_mm']) & (gp[:, 0] > plan.xc + p['cap_gamma_clear_mm'])
    ins &= MPath(np.vstack([G[:, :2], G[:1, :2]])).contains_points(gp)
    gp = gp[ins]
    gp = gp[cKDTree(G[:, :2]).query(gp)[0] > p['cap_gamma_clear_mm']]
    pts = np.c_[gp, Hz(gp[:, 0], gp[:, 1])]
    log['cap_heightfield'] = {'points': int(len(C)), 'residual': _st(res), 'constraints': int(len(pts))}
    return pts, C


def _st(a):
    a = np.abs(np.asarray(a, float))
    a = a[np.isfinite(a)]
    if a.size == 0:
        return {'p50': None, 'p95': None, 'max': None, 'n': 0}
    return {'p50': float(np.median(a)), 'p95': float(np.percentile(a, 95)), 'max': float(a.max()), 'n': int(a.size)}


# ------------------------------------------------------------------ main
def prepare(req, p, log, warnings):
    """Everything up to the B-spline geometry (numpy only). Returns a dict of arrays used by build()."""
    from scipy.spatial import cKDTree
    inp = req['inputs']
    srf = json.loads(Path(inp['surface']).read_text(encoding='utf-8'))
    mp = srf.get('mirror_plane')
    if not mp:
        raise WorkerError('SHELL_SOLID_NEEDS_HALF', 'The skin is one full face (asymmetric domain); this version closes half + mirror skins only.')
    cuts = p.get('cut_planes') or []
    if not cuts:
        raise WorkerError('SHELL_SOLID_NO_CUT', 'The shell_fit run has no front cut plane; nothing in front of the skin to build.')
    if len(cuts) > 1:
        raise WorkerError('SHELL_SOLID_CUTS', 'Exactly one front cut plane is supported.', {'cut_planes': len(cuts)})
    cut = cuts[0]
    R, d = frame_of(mp['normal'], mp['d'], cut['normal'])
    cn = np.asarray(cut['normal'], float)
    nq = R @ (cn / np.linalg.norm(cn))
    dq = float(cut['d']) / np.linalg.norm(cn) - d * nq[1]
    if abs(nq[1]) > 1e-3 or abs(nq[2]) > 1e-2:
        raise WorkerError('SHELL_SOLID_FRAME', 'The front cut plane must be perpendicular to the mirror plane and vertical.', {'normal_aligned': nq.tolist()})
    xc = dq / nq[0]
    if list(srf['degree']) != [3, 3]:
        raise WorkerError('SHELL_SOLID_SKIN', 'The skin must be bicubic (shell_fit degree 3).', {'degree': srf['degree']})
    P = to_q(np.asarray(srf['poles_input_frame'], float), R, d)
    P, tu, tv = canonical_skin(P, np.asarray(srf['knots_u'], float), np.asarray(srf['knots_v'], float), xc)
    if P[..., 1].mean() > 0:                                 # build on the y <= 0 half; the other half is its mirror
        P = P * [1, -1, 1]
    su = np.linalg.norm(bs_eval(P, tu, tv, np.ones(9), np.linspace(0, 1, 9), du=1), axis=1).mean()
    sv = np.linalg.norm(bs_eval(P, tu, tv, np.linspace(0, 1, 9), np.ones(9), dv=1), axis=1).mean()
    PR, tuR, tvR = extend_max(P, tu, tv, p['extension_mm'] / su, p['extension_mm'] / sv)
    log['skin'] = {'cut_x_aligned': float(xc), 'extension_mm': p['extension_mm'], 'poles': list(P.shape[:2])}
    V, F = load_mesh(inp['mesh'], float(p['unit_scale']))
    V = to_q(V, R, d)
    lab, names = read_labels(inp.get('labels'), len(F))
    if lab is None:
        raise WorkerError('SHELL_SOLID_LABELS', 'labels are required (shell / plate regions; labels are hints for the data selection).')
    shell = region_mask(lab, names, p['shell_regions'])
    plate = region_mask(lab, names, p['plate_regions'])
    excl = region_mask(lab, names, p['exclude_regions'])
    if not shell.any() or not plate.any():
        raise WorkerError('SHELL_SOLID_LABELS', 'The label file needs shell and plate regions.', {'available': sorted(names)})
    tri = V[F]
    cen = tri.mean(1)
    # parting surface from the shell / plate seam
    S = seam_points(V, F, shell | excl, plate)
    if len(S) < 30:
        raise WorkerError('SHELL_SOLID_SEAM', 'Too few seam points between shell and plate faces.', {'points': int(len(S))})
    crest_log = {'applied': False}
    if p['seam_to_crest'] and p['parting_mode'] != 'plane':
        S, crest_log = seam_to_crest(V, F, S, p)
    S2 = np.vstack([S, S * [1, -1, 1]])
    ymax = float(np.abs(V[:, 1]).max())
    box = (float(V[:, 0].min()) - 8, float(V[:, 0].max()) + 8, -ymax - 8, ymax + 8)
    cfI, kxI, kyI = fit_heightfield(S2, box, 12.0, float(p['seam_smoothing']), True)
    res = S2[:, 2] - eval_heightfield(cfI, kxI, kyI, S2[:, 0], S2[:, 1])
    # range of the fitted seam height AT the seam points (2-98 %), not over the extrapolated box corners
    zr = eval_heightfield(cfI, kxI, kyI, S2[:, 0], S2[:, 1])
    span = float(np.percentile(zr, 98) - np.percentile(zr, 2))
    mode = p['parting_mode']
    if mode == 'auto':
        mode = 'plane' if span <= p['flat_tolerance_mm'] else 'seam'
    zp = float(p['parting_z_mm']) if p['parting_z_mm'] is not None else float(np.median(S[:, 2]))
    log['parting'] = {'mode_used': mode, 'seam_points': int(len(S)), 'seam_fit_residual': _st(res), 'seam_height_range_mm': span,
                      'plane_z_mm': zp if mode == 'plane' else None, 'rule': 'auto: plane when the seam height range <= flat_tolerance_mm, else seam'
                      if p['parting_mode'] == 'auto' else p['parting_mode'], 'seam_to_crest': crest_log, 'seam_smoothing': float(p['seam_smoothing'])}
    if mode == 'plane':
        cfI = np.full_like(cfI, zp)
    # front samples (shell faces; excluded regions + margin removed), mirrored
    keep = shell & (cen[:, 0] > xc - 3)
    if excl.any():
        keep &= cKDTree(cen[excl]).query(cen)[0] > p['exclude_margin_mm']
    Pt, Nt, Wt, _ = sample_faces(tri, np.flatnonzero(keep), 20.0)
    Pt, Nt, Wt = np.vstack([Pt, Pt * [1, -1, 1]]), np.vstack([Nt, Nt * [1, -1, 1]]), np.r_[Wt, Wt]
    layout = json.loads(Path(inp['layout']).read_text(encoding='utf-8')) if inp.get('layout') else None
    paths, window = layout_paths(layout, R, d)
    if paths:
        pp = np.vstack(paths)
        pp = np.vstack([pp, pp * [1, -1]])
        top_ok = cKDTree(pp).query(Pt[:, :2])[0] > p['groove_margin_mm']
    else:
        top_ok = np.ones(len(Pt), bool)
        warnings.append('No slot layout: groove bands next to the click slots are not excluded from the crease and cap fits.')
    plan = Plan(Pt[:, :2], xc)
    log['plan'] = {'length_mm': plan.LS, 'front_x_aligned': float(plan.xy[:, 0].max())}
    hG, zG, rows = measure_gamma(plan, Pt, Nt, top_ok, p, log)
    vS0, S0 = skin_split_v(PR, tuR, tvR, plan, hG, zG, log)
    G, hGs, zGs = build_gamma(plan, hG, zG, S0, p)
    Q, tuT, tvT = fit_tube(PR, tuR, tvR, vS0, plan, G, zGs, Pt, Wt, p, log)
    pts, Cdat = cap_points(Pt[top_ok], plan, hGs, zGs, G, paths, window, p, log)
    return {'R': R, 'd': d, 'xc': xc, 'PR': PR, 'tuR': tuR, 'tvR': tvR, 'vS0': vS0, 'S0': S0, 'G': G, 'Q': Q, 'tuT': tuT, 'tvT': tvT,
            'pts': pts, 'Cdat': Cdat, 'plan': plan, 'rows': rows, 'cfI': cfI, 'kxI': kxI, 'kyI': kyI, 'mode': mode, 'zp': zp,
            'V': V, 'F': F, 'shell': shell, 'excl': excl}


def build(g, p, log, out):
    """B-rep: faces, cap filling, sewing, closing with the parting surface, STEP write + re-import checks."""
    from cadmcp_brain.studio import cad_brep_lib as cb
    cb.require_ocp()
    from OCP.gp import gp_Pnt, gp_Pnt2d, gp_Dir2d, gp_Dir
    from OCP.Geom import Geom_Plane
    from OCP.Geom2d import Geom2d_Line
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeVertex
    from OCP.BRepLib import BRepLib
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeFilling
    from OCP.GeomAbs import GeomAbs_G1, GeomAbs_C0
    from OCP.BOPAlgo import BOPAlgo_MakerVolume
    from OCP.TopTools import TopTools_ListOfShape
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_IN
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.TopoDS import TopoDS
    from OCP.BRep import BRep_Tool
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    R, d, plan = g['R'], g['d'], g['plan']
    Pin = lambda X: from_q(X, R, d)
    SR = cb.bsurf(Pin(g['PR']), g['tuR'], g['tvR'])
    SL = cb.bsurf(Pin(g['PR'] * [1, -1, 1]), g['tuR'], g['tvR'])
    ST = cb.bsurf(Pin(g['Q']), g['tuT'], g['tvT'])
    fR = BRepBuilderAPI_MakeFace(SR, 1e-7).Face()
    fL = BRepBuilderAPI_MakeFace(SL, 1e-7).Face()
    fT = BRepBuilderAPI_MakeFace(ST, 1e-7).Face()

    def iso_edge(Sf, fixed_u, val, a_, b_):
        ln = Geom2d_Line(gp_Pnt2d(val, 0), gp_Dir2d(0, 1)) if fixed_u else Geom2d_Line(gp_Pnt2d(0, val), gp_Dir2d(1, 0))
        e = BRepBuilderAPI_MakeEdge(ln, Sf, a_, b_).Edge()
        BRepLib.BuildCurves3d_s(e)
        return e
    vS0 = g['vS0']
    u1 = p['g1_end_mm'] / plan.LS
    fl = BRepOffsetAPI_MakeFilling(3, 40, 4, False, 1e-5, 1e-4, 1e-3, 0.1, int(p['fill_max_degree']), int(p['fill_max_segments']))
    fl.Add(iso_edge(SR, True, 0.0, 0.0, vS0), fR, GeomAbs_G1, True)
    fl.Add(iso_edge(ST, False, 1.0, 0.0, u1), fT, GeomAbs_G1, True)
    fl.Add(iso_edge(ST, False, 1.0, u1, 1 - u1), fT, GeomAbs_C0, True)
    fl.Add(iso_edge(ST, False, 1.0, 1 - u1, 1.0), fT, GeomAbs_G1, True)
    fl.Add(iso_edge(SL, True, 0.0, 0.0, vS0), fL, GeomAbs_G1, True)
    for q in Pin(g['pts']):
        fl.Add(gp_Pnt(*map(float, q)))
    fl.Build()
    if not fl.IsDone():
        raise WorkerError('SHELL_SOLID_CAP', 'The cap filling (MakeFilling) failed.')
    fC = TopoDS.Face_s(fl.Shape())
    log['cap'] = {'G0_error_mm': float(fl.G0Error()), 'G1_error_deg': float(np.degrees(fl.G1Error())), 'point_constraints': int(len(g['pts']))}
    Scap = BRep_Tool.Surface_s(fC)
    Cd = g['Cdat']
    sub = Pin(Cd[np.random.default_rng(0).choice(len(Cd), min(3000, len(Cd)), replace=False)])
    pr = GeomAPI_ProjectPointOnSurf()
    dv = []
    for q in sub:
        pr.Init(gp_Pnt(*map(float, q)), Scap)
        dv.append(pr.LowerDistance() if pr.NbPoints() else np.nan)
    log['cap']['deviation_top_data'] = _st(dv)
    sew = BRepBuilderAPI_Sewing(1e-3)
    for f in (fR, fL, fT, fC):
        sew.Add(f)
    sew.Perform()
    skin = sew.SewedShape()
    log['sewing'] = {'free_edges': int(sew.NbFreeEdges()), 'multiple_edges': int(sew.NbMultipleEdges())}
    if g['mode'] == 'plane':
        o = Pin(np.array([[0.0, 0.0, g['zp']]]))[0]
        fI = BRepBuilderAPI_MakeFace(Geom_Plane(gp_Pnt(*map(float, o)), gp_Dir(*map(float, R[2]))), -1e3, 1e3, -1e3, 1e3, 1e-7).Face()
    else:
        fI = BRepBuilderAPI_MakeFace(cb.bsurf(Pin(heightfield_poles(g['cfI'], g['kxI'], g['kyI'])), g['kxI'], g['kyI']), 1e-7).Face()
    mv = BOPAlgo_MakerVolume()
    L = TopTools_ListOfShape()
    for f in cb.faces(skin):
        L.Append(f)
    L.Append(fI)
    mv.SetArguments(L)
    mv.SetRunParallel(True)
    mv.SetIntersect(True)
    mv.Perform()
    if mv.HasErrors():
        raise WorkerError('SHELL_SOLID_CLOSE', 'Closing the skin with the parting surface (MakerVolume) failed.')
    top_mid = bs_eval(g['PR'], g['tuR'], g['tvR'], 0.5, 0.0)[0]
    zi = eval_heightfield(g['cfI'], g['kxI'], g['kyI'], np.r_[top_mid[0]], np.r_[0.0])[0]
    ip = Pin(np.array([[top_mid[0], 0.0, 0.5 * (top_mid[2] + zi)]]))[0]
    sols = cb.solids(mv.Shape())
    pick = None
    for so in sols:
        if BRepClass3d_SolidClassifier(so, gp_Pnt(*map(float, ip)), 1e-6).State() == TopAbs_IN:
            pick = so
    if pick is None:
        raise WorkerError('SHELL_SOLID_CLOSE', 'No closed volume contains the interior point.', {'volumes': len(sols)})
    sf = ShapeFix_Solid(pick)
    sf.Perform()
    top = TopoDS.Solid_s(sf.Solid())
    if cb.volume(top) < 0:
        top = TopoDS.Solid_s(top.Reversed())
    cb.write_step(top, out / 'top_shell_solid.step')
    back = cb.read_step(out / 'top_shell_solid.step')
    bs = cb.solids(back)
    fa = [cb.area(f) for f in cb.faces(back)]
    brep = {'valid': bool(cb.is_valid(back)), 'solids': len(bs), 'faces': len(fa), 'volume_mm3': float(cb.volume(bs[0])) if bs else None,
            'min_face_area_mm2': float(min(fa)) if fa else None, 'face_areas_mm2': [round(a_, 3) for a_ in fa], 'volumes_found': len(sols),
            'bbox': [float(x) for x in cb.bbox(back)]}
    tess = cb.tessellate(back, 0.03, 0.15)
    brep['tessellates'] = bool(tess is not None and len(tess['T']) > 0)
    # deviation vs the scan shell (all shell samples, excluded regions removed)
    tri = g['V'][g['F']]
    Ps, _, _, _ = sample_faces(tri, np.flatnonzero(g['shell'] & ~g['excl']), 2.0, seed=1)
    Ps = Ps[np.random.default_rng(1).choice(len(Ps), min(4000, len(Ps)), replace=False)]
    dd_ = []
    for q in Pin(Ps):
        ds = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, q))).Vertex(), back)
        dd_.append(ds.Value() if ds.IsDone() else np.nan)
    dd_ = np.asarray(dd_)
    front = Ps[:, 0] > g['xc']
    dev = {'all': _st(dd_), 'front': _st(dd_[front]), 'rear_skin': _st(dd_[~front]),
           'note': 'scan shell samples (excluded regions removed) to the solid; the front includes the cable hole, lip groove and slot grooves that are '
                   'not followed on purpose'}
    return brep, dev


def run(req: dict[str, Any]) -> dict[str, Any]:
    t0 = time.time()
    p = {**DEFAULTS, **(req.get('params') or {})}
    out = Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    log: dict[str, Any] = {}
    g = prepare(req, p, log, warnings)
    t1 = time.time()
    brep, dev = build(g, p, log, out)
    t2 = time.time()
    R, d = g['R'], g['d']
    np.savez(out / 'front_construction.npz', gamma=from_q(g['G'], R, d), crease_rows=g['rows'],
             plan_xy=from_q(np.c_[g['plan'].xy, np.zeros(len(g['plan'].xy))], R, d))
    scan_front = float(g['V'][g['F'][g['shell']].ravel(), 0].max())
    return {'worker': WORKER_VERSION, 'warnings': warnings, 'log': log, 'brep': brep, 'deviation': dev,
            'timing': {'prepare_s': round(t1 - t0, 1), 'brep_s': round(t2 - t1, 1)},
            'frame': {'R': R.tolist(), 'd': d, 'cut_x_aligned': g['xc']},
            'front': {'solid_front_x_aligned': float(g['G'][:, 0].max()), 'scan_front_x_aligned': scan_front,
                      'front_length_error_mm': float(g['G'][:, 0].max() - scan_front)},
            'files': {'step': 'top_shell_solid.step', 'construction': 'front_construction.npz'}}


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
