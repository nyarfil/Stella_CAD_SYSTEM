"""Scan intake, step 2: functional-region recognition on a READY scan (brain_mouse_recognize_regions).

Finds left click, right click, scroll wheel, side button 1 and 2 (and the remaining palm shell) on a closed scan mesh from
its SURFACE geometry only: hinges, switches and the wheel axle are not visible in a surface scan and are never inferred.
Pipeline (numpy / scipy / Pillow, no mesh library):
  1. frame: from the mesh itself (area-weighted PCA, flat-base plane, hump position), right- or left-hand mouse;
  2. v4 engine (scan_segment): raster stacks of the top, the thumb flank and the thumb shoulder with a groove / normal-discontinuity map;
     markers are generated from mouse-frame priors (never from a stored label file); marker watershed; the wheel well is the dense knurl
     response; the side-button pads are the plateau edge (crest of the slope ring round the raised pad);
  3. smoothed outlines: true corners kept, smoothing splines between, left and right click share ONE centre-line chain;
  4. outline masks are mapped back to face ids (the side pads combine the flank view with the thumb-shoulder view);
  5. every boundary is checked against the boundary cue; unsupported stretches are listed as inferred.
Results are stored with hashes under mouse/scans/<scan_id>/regions/<run_id>/ and never overwritten.
"""
from __future__ import annotations
import time
from pathlib import Path
from typing import Any
import numpy as np
import scipy.sparse as sp
import scipy.sparse.csgraph as cg
from scipy.spatial import cKDTree
from . import scan_segment, scan_shell
from .. import __version__
from ..errors import BrainError
from ..req2cad.common import atomic_json, json_load
from ..util import digest, file_hash, safe_id

REGIONS_VERSION = 'R2.0'
PIX = scan_segment.PIX
H_SEAM = 0.06                 # groove strength scale (mm) of the handedness probe and the palm / base split
K_COST = 30.0                 # groove crossing penalty of the palm / base split
LENGTH_RANGE_MM = (95.0, 145.0)
CALIBRATED_ON = 'OP1-class ergonomic mouse, 118 x 60 x 37 mm, thumb buttons on the +y flank'

# The shape priors (seed windows, flank envelopes) were authored in the frame of the reference scan, which differs from
# this module's flat-base frame by a fixed rotation and shift. They are re-expressed from the mouse's own frame:
#   W = q @ R_PRIOR.T + T_PRIOR,   q = (x from the rear end, y from the mid-line, z above the base plane).
R_PRIOR = np.array([[0.9995824, -0.0040866, 0.0286079], [0.0015284, 0.9960412, 0.0888794], [-0.0288579, -0.0887986, 0.9956315]])
T_PRIOR = np.array([-71.782996, -2.927099, -10.111034])

NAMES = ['LC', 'RC', 'WH', 'B1', 'B2', 'PALM', 'BASE']        # the first five are the scan_segment region indices
OUT_NAMES = {'LC': 'left_click', 'RC': 'right_click', 'WH': 'wheel', 'B1': 'side_button_1', 'B2': 'side_button_2', 'PALM': 'palm_shell'}
LABEL_CODES = {'other': 0, 'left_click': 1, 'right_click': 2, 'wheel': 3, 'side_button_1': 4, 'side_button_2': 5, 'palm_shell': 6}


# ------------------------------------------------------------------ frame
def _face_geometry(v: np.ndarray, f: np.ndarray):
    t = v[f]
    cr = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    a2 = np.linalg.norm(cr, axis=1)
    return t.mean(1), cr / (a2[:, None] + 1e-300), a2 / 2


def canonical_frame(v: np.ndarray, f: np.ndarray) -> dict[str, Any]:
    """Mouse frame from the mesh alone. x = rear -> front, z = base -> top, y = z cross x (a proper frame).
    Returns the rotation (rows = axes in scan coordinates), the centroid, the bbox shift and the decisions with their evidence."""
    cen, fn, a = _face_geometry(v, f)
    mu = (cen * a[:, None]).sum(0) / a.sum()
    c = (cen - mu)
    w, u = np.linalg.eigh((c.T * a) @ c / a.sum())
    z = u[:, 0]

    def flat_area(zv, sg):
        zc = c @ zv * sg
        return float(a[(zc > zc.max() - 3) & (fn @ zv * sg > 0.95)].sum())
    fa_up, fa_dn = flat_area(z, 1), flat_area(z, -1)
    if fa_up > fa_dn:                       # the flat base must be at -z
        z = -z
    for _ in range(4):                      # refine z to the base plane normal
        zc = c @ z
        sel = (zc < zc.min() + 2.5) & (fn @ z < -0.9)
        if sel.sum() < 20:
            break
        n = -(fn[sel] * a[sel, None]).sum(0)
        z = n / np.linalg.norm(n)
    h = np.eye(3) - np.outer(z, z)
    ch = c @ h
    w2, u2 = np.linalg.eigh((ch.T * a) @ ch / a.sum())
    x = u2[:, 2] - z * (u2[:, 2] @ z)
    x /= np.linalg.norm(x)
    zc, xc = c @ z, c @ x
    top = np.argsort(zc)[-max(20, int(0.02 * len(zc))):]
    peak_frac = float((xc[top].mean() - xc.min()) / np.ptp(xc))        # hump position measured from the -x end
    half = xc < np.median(xc)
    hh_a = float(np.average(zc[half], weights=a[half]))
    hh_b = float(np.average(zc[~half], weights=a[~half]))               # mean height of each half
    vote_peak = 'rear_is_minus_x' if peak_frac < 0.5 else 'rear_is_plus_x'
    vote_mass = 'rear_is_minus_x' if hh_a > hh_b else 'rear_is_plus_x'
    rear_minus = peak_frac < 0.5
    if not rear_minus:
        x = -x
    y = np.cross(z, x)
    rot = np.vstack([x, y, z])
    q = (v - mu) @ rot.T
    qmin, qmax = q.min(0), q.max(0)
    shift = np.array([qmin[0], (qmin[1] + qmax[1]) / 2, qmin[2]])
    return {'rotation': rot, 'centroid': mu, 'shift': shift, 'extents_mm': (qmax - qmin).tolist(),
            'eigenvalues': w.tolist(), 'flat_area_mm2': {'base_end': max(fa_up, fa_dn), 'opposite_end': min(fa_up, fa_dn)},
            'orientation': {'hump_position_from_rear': peak_frac if rear_minus else 1 - peak_frac, 'vote_hump': vote_peak, 'vote_height_mass': vote_mass,
                            'agree': vote_peak == vote_mass, 'mean_height_halves_mm': [hh_a, hh_b]}}


def canonical_coords(v: np.ndarray, fr: dict[str, Any]) -> np.ndarray:
    return (v - fr['centroid']) @ fr['rotation'].T - fr['shift']


def working_coords(q: np.ndarray, mirrored: bool) -> np.ndarray:
    """Prior frame coordinates; a left-hand mouse is mirrored across its mid-line so the thumb buttons sit at +y."""
    if mirrored:
        q = q * np.array([1.0, -1.0, 1.0])
    return q @ R_PRIOR.T + T_PRIOR


# ------------------------------------------------------------------ mesh features
def _adjacency(f: np.ndarray, nv: int):
    i = np.r_[f[:, 0], f[:, 1], f[:, 2], f[:, 1], f[:, 2], f[:, 0]]
    j = np.r_[f[:, 1], f[:, 2], f[:, 0], f[:, 0], f[:, 1], f[:, 2]]
    A = sp.coo_matrix((np.ones(len(i)), (i, j)), shape=(nv, nv)).tocsr()
    A.data[:] = 1
    return sp.diags(1 / np.maximum(np.asarray(A.sum(1)).ravel(), 1)) @ A


def _hfeat(P, vn, L, it1: int, it2: int):
    Q = P.copy()
    for _ in range(it1):
        Q = Q + 0.6 * (L @ Q - Q)
    d = ((P - Q) * vn).sum(1)
    bg = d.copy()
    for _ in range(it2):
        bg = bg + 0.6 * (L @ bg - bg)
    return d - bg


class _Mesh:
    """Working copy of the scan in the prior frame (faces may be re-wound: ids never change)."""

    def __init__(self, P: np.ndarray, F: np.ndarray):
        self.P, self.F = P, F.copy()
        self.nV, self.nF = len(P), len(F)
        self.geom()
        for _ in range(2):   # a few scan triangles are folded against the surface: flip them to agree with the smoothed normal
            bad = (self.fnv / self.fa2[:, None] * self.vn[self.F].mean(1)).sum(1) < 0
            self.flipped = int(bad.sum())
            if not bad.any():
                break
            self.F[bad] = self.F[bad][:, [0, 2, 1]]
            self.geom()
        self.fn = self.fnv / self.fa2[:, None]
        self.farea = self.fa2 / 2
        self.L = _adjacency(self.F, self.nV)

    def geom(self):
        P, F = self.P, self.F
        self.tri = P[F]
        self.cen = self.tri.mean(1)
        self.fnv = np.cross(self.tri[:, 1] - self.tri[:, 0], self.tri[:, 2] - self.tri[:, 0])
        self.fa2 = np.linalg.norm(self.fnv, axis=1) + 1e-300
        vn = np.zeros_like(P)
        for k in range(3):
            np.add.at(vn, F[:, k], self.fnv)
        self.vn = vn / (np.linalg.norm(vn, axis=1)[:, None] + 1e-12)


# ------------------------------------------------------------------ palm / base split, confidence
def _palm_base(M: _Mesh, sv: np.ndarray, fixed: np.ndarray) -> np.ndarray:
    """Remainder of the scan: palm shell (rear top) versus base (flat underside) by groove-penalised growth over the face graph from
    two prior seeds. Faces already taken by a functional region (fixed >= 0) act as palm sources. Returns 5 (palm) / 6 (base) per face."""
    F, cen, fn, nF = M.F, M.cen, M.fn, M.nF
    sf = sv[F].max(1)
    E = np.sort(np.r_[F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]], axis=1)
    fid = np.r_[np.arange(nF), np.arange(nF), np.arange(nF)]
    o = np.lexsort((E[:, 1], E[:, 0]))
    E, fid = E[o], fid[o]
    same = (E[1:] == E[:-1]).all(1)
    ea, eb = fid[:-1][same], fid[1:][same]
    w = np.linalg.norm(cen[ea] - cen[eb], axis=1) * (1 + K_COST * 0.5 * (sf[ea] + sf[eb]))
    G = sp.coo_matrix((np.r_[w, w], (np.r_[ea, eb], np.r_[eb, ea])), shape=(nF, nF)).tocsr()
    x, y, z = cen.T
    palm = (x > -55) & (x < -15) & (np.abs(y) < 18) & (fn[:, 2] > 0.5)
    base = z < -11.5
    lab0 = np.full(nF, 5)
    lab0[base] = 6
    src = palm | base | (fixed >= 0)
    lab0[fixed >= 0] = 5                      # functional regions are sources too, labelled palm so growth stops at them, then overridden
    idx = np.flatnonzero(src)
    _, _, srcs = cg.dijkstra(G, directed=True, indices=idx, return_predecessors=True, min_only=True)
    lab = lab0[np.maximum(srcs, 0)]
    unr = srcs < 0
    if unr.any():
        _, nn = cKDTree(cen[~unr]).query(cen[unr])
        lab[unr] = lab[~unr][nn]
    return lab


def _confidence(frac: float, extra_down: int = 0) -> str:
    level = 2 if frac >= 0.70 else (1 if frac >= 0.45 else 0)
    level = max(0, level - extra_down)
    return ('low', 'med', 'high')[level]


# ------------------------------------------------------------------ driver
def _not_ready(scan_id: str, reasons: list[str], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {'schema': 'scan_regions_report/1', 'scan_id': scan_id, 'status': 'NOT_READY', 'blocking_reasons': reasons, 'surface_only': True,
            'limitations': _LIMITS, **(extra or {}), 'execution': {'completed': True}}


_LIMITS = ['Region recognition is surface-only: hinges, switches, the wheel axle and encoder, PCB and screw bosses are not visible in a scan and are not inferred.',
           'Boundaries come from tiny seam grooves, the slope ring round the side-button pads and mouse-shape markers; stretches without a cue are listed per region as inferred.',
           f'Calibrated on: {CALIBRATED_ON}. Other mouse shapes may fail the priors (REGIONS_PRIORS_NOT_FOUND) or give low confidence.']


def recognize_regions(workspace: Path, scan_id: str, handedness: str = 'auto', overlay: bool = True) -> dict[str, Any]:
    if handedness not in ('auto', 'right', 'left'):
        raise BrainError('REGIONS_SETTINGS', "handedness must be 'auto', 'right' (thumb buttons on the left flank) or 'left'.", {'given': handedness})
    t0 = time.time()
    scan_id = safe_id(scan_id)
    d = scan_shell.scan_dir(workspace, scan_id)
    rp = d / 'prepare_report.json'
    if not rp.is_file():
        raise BrainError('SCAN_NOT_FOUND', 'No prepared scan with this id. Run brain_mouse_prepare_scan first.')
    prep = json_load(rp)
    if prep.get('prepared_status') != 'READY':
        return _not_ready(scan_id, ['SCAN_NOT_READY'] + list(prep.get('blocking_reasons') or []),
                          {'note': 'Region recognition needs a welded, closed, single-component scan. Fix the blocking reasons of brain_mouse_prepare_scan first.'})
    d, prep = scan_shell.load_prepared(workspace, scan_id)
    v, f = scan_shell.load_prepared_mesh(d)
    run_id = 'reg_' + digest({'npz': prep['prepared_npz_sha256'], 'handedness': handedness, 'overlay': bool(overlay), 'version': REGIONS_VERSION})[:12]
    out = d / 'regions' / run_id
    if (out / 'regions_report.json').is_file():
        return _stored(out, scan_id)
    fr = canonical_frame(v, f)
    ext = fr['extents_mm']
    blockers: list[str] = []
    if not LENGTH_RANGE_MM[0] <= ext[0] <= LENGTH_RANGE_MM[1]:
        blockers.append('LENGTH_OUTSIDE_CALIBRATED_RANGE')
    if not fr['orientation']['agree']:
        blockers.append('FRONT_REAR_AMBIGUOUS')
    frame_info = {'axes_in_scan_coordinates': fr['rotation'].round(6).tolist(), 'centroid': fr['centroid'].round(4).tolist(), 'extents_mm': [round(e, 2) for e in ext],
                  'convention': 'x rear -> front, y mouse-left (mirror-free, proper frame), z base -> top; origin at rear end / mid-line / base plane',
                  'decisions': fr['orientation']}
    if blockers:
        return _not_ready(scan_id, blockers, {'frame': frame_info, 'calibrated_range_length_mm': list(LENGTH_RANGE_MM)})
    q = canonical_coords(v, fr)
    # handedness: which flank carries the side-button recesses (groove energy in the thumb-button window)
    probe = _Mesh(working_coords(q, False), f)
    hs = _hfeat(probe.P, probe.vn, probe.L, 8, 25)
    svp = np.clip(np.abs(hs) / H_SEAM, 0, 1)
    wq = working_coords(q, False)
    wm = working_coords(q, True)

    def flank_energy(w):
        sel = (w[:, 1] > 22) & (w[:, 0] > -27) & (w[:, 0] < 10) & (w[:, 2] > 3) & (w[:, 2] < 14)
        return int(((svp > 0.4) & sel).sum())
    e_left, e_right = flank_energy(wq), flank_energy(wm)
    detected = 'right' if e_left > e_right else 'left'
    ratio = max(e_left, e_right) / max(min(e_left, e_right), 1)
    hand_info = {'requested': handedness, 'detected': detected, 'groove_energy_left_flank': e_left, 'groove_energy_right_flank': e_right, 'ratio': round(float(ratio), 2),
                 'meaning': "'right' = right-hand mouse, thumb buttons on the left flank (+y of the frame); 'left' = mirrored mouse, thumb buttons on the right flank"}
    use = detected if handedness == 'auto' else handedness
    if handedness == 'auto' and (max(e_left, e_right) < 150 or ratio < 1.5):
        return _not_ready(scan_id, ['HANDEDNESS_UNDETERMINED'], {'frame': frame_info, 'handedness': hand_info,
                                                              'note': "No flank shows clearly more side-button recess grooves. Pass handedness='right' or 'left' explicitly."})
    mirrored = use == 'left'
    M = _Mesh(working_coords(q, mirrored), np.ascontiguousarray(f[:, [0, 2, 1]]) if mirrored else f)
    hv = _hfeat(M.P, M.vn, M.L, 8, 25)
    sv = np.clip(np.abs(hv) / H_SEAM, 0, 1)
    ft = scan_segment.surface_features(M.P, M.F, M.L, M.vn, M.fn)
    try:
        seg = scan_segment.segment_regions(M, ft)
    except scan_segment.SegmentError as exc:
        raise BrainError('REGIONS_PRIORS_NOT_FOUND', str(exc) + '. This mesh does not look like the calibrated mouse layout.', {**exc.detail, 'calibrated_on': CALIBRATED_ON}) from exc
    palm_base = _palm_base(M, sv, seg['lab'])
    lab = np.where(seg['lab'] >= 0, seg['lab'], palm_base)
    # ------------------------------------------------------------ report
    names_out = dict(OUT_NAMES)
    if mirrored:     # positional names: the physical left button of a mirrored mouse is the region on the mirrored model's right
        names_out['LC'], names_out['RC'] = 'right_click', 'left_click'
    keys = ['LC', 'RC', 'WH', 'B1', 'B2', 'PALM']
    area = M.farea
    regions: dict[str, Any] = {}
    view_for = {'LC': 'top', 'RC': 'top', 'WH': 'top', 'B1': 'side', 'B2': 'side'}
    sec_top = ['front', 'rear', 'thumb-side', 'far-side']
    sec_side = ['front', 'rear', 'lower', 'upper']      # raster v = -z, so +v is downward
    cue_top = np.maximum(seg['cues']['top']['geo'], seg['cues']['top']['ang'])
    cue_side = seg['cues']['side']['slope']
    face_codes = np.zeros(len(f), np.uint8)
    for k in keys:
        mk = lab == NAMES.index(k)
        face_codes[mk] = LABEL_CODES[OUT_NAMES[k] if k not in ('LC', 'RC') else names_out[k]]
        qq = q[f[mk]].reshape(-1, 3) if mk.any() else np.zeros((1, 3))
        row: dict[str, Any] = {'key': names_out[k], 'face_count': int(mk.sum()), 'area_mm2': round(float(area[mk].sum()), 1),
                               'bbox_min_mm': np.round(qq.min(0), 2).tolist(), 'bbox_max_mm': np.round(qq.max(0), 2).tolist(), 'bbox_frame': 'canonical (x from rear end, y from mid-line, z above base)'}
        if k in view_for:
            top = view_for[k] == 'top'
            ev = scan_segment.outline_evidence(seg['outlines'][k], cue_top if top else cue_side, seg['stacks']['top' if top else 'side'], sec_top if top else sec_side)
            down = 0
            extra = []
            if k in ('B1', 'B2'):
                o = seg['outlines'][k]
                w_mm = float(min(np.ptp(o[:, 0]), np.ptp(o[:, 1])))
                if w_mm < 3.2:
                    down += 1
                    extra.append(f'narrow pad ({w_mm:.1f} mm): the outline error of a few tenths of a mm is a large share of its width')
                extra.append('the pad edge is the crest of the surface-slope ring round the raised pad, not a groove.')
            crv = seg['curves'][k]
            row['outline'] = {'frame': 'top view (x, y), mm' if top else 'flank view (x, v = -z), mm', 'points': int(len(seg['outlines'][k])),
                              'max_fit_deviation_mm': max(c['maxdev_mm'] for c in crv), 'shared_with': sorted({c['kind'][12:] for c in crv if c['kind'].startswith('shared_with_')})}
            row['boundary_mm'] = ev['boundary_mm']
            row['groove_supported_fraction'] = ev['supported_fraction']
            row['inferred_boundaries'] = ev['inferred']
            row['confidence'] = _confidence(ev['supported_fraction'], down)
            notes = [f"{int(ev['supported_fraction'] * 100)}% of the {ev['boundary_mm']} mm outline lies on a boundary cue (<= 0.3 mm) or on the silhouette."]
            for it in ev['inferred']:
                notes.append(f"{it['edge']} edge: {it['inferred_mm']} of {it['edge_mm']} mm inferred (no groove), placed by the watershed between the markers.")
            row['note'] = ' '.join(notes + extra)
        else:
            row.update({'confidence': 'low', 'groove_supported_fraction': None, 'inferred_boundaries': [{'edge': 'all', 'note': 'remainder region'}],
                        'note': 'Remainder shell behind and around the functional regions (grown from rear and base seeds); its boundaries follow no groove. Not a verified mechanical region.'})
        regions[names_out[k]] = row
    other = int((face_codes == 0).sum())
    status = 'READY'
    warnings: list[dict[str, Any]] = []
    if min(regions[names_out[k]]['face_count'] for k in ('LC', 'RC', 'WH', 'B1', 'B2')) < 30:
        status = 'NOT_READY'
        blockers.append('REGION_TOO_SMALL')
    if seg['defect_faces'] > 0.01 * len(f):
        warnings.append({'code': 'MANY_FOLDED_FACES', 'count': seg['defect_faces']})
    if M.flipped:
        warnings.append({'code': 'FOLDED_FACES_REORIENTED_IN_WORK_COPY', 'count': M.flipped, 'note': 'only the internal work copy; the prepared mesh and face ids are untouched'})
    # ------------------------------------------------------------ write
    out.mkdir(parents=True, exist_ok=False)
    npz = out / 'face_labels.npz'
    with npz.open('wb') as fh:
        np.savez_compressed(fh, face_labels=face_codes, codes=np.array([f'{n}={c}' for n, c in LABEL_CODES.items()]))
    files = {'face_labels': {'file': 'face_labels.npz', 'sha256': file_hash(npz), 'faces': int(len(f)), 'codes': LABEL_CODES}}
    ol = {}
    for k in ('LC', 'RC', 'WH', 'B1', 'B2'):
        ol[names_out[k] + '_outline_2d'] = seg['outlines'][k]
        ol[names_out[k] + '_outline_3d'] = seg['outlines_3d'][k]
    for k in seg['shoulder_outlines']:
        ol[names_out[k] + '_shoulder_outline_2d'] = seg['shoulder_outlines'][k]
        ol[names_out[k] + '_shoulder_outline_3d'] = seg['shoulder_outlines_3d'][k]
    with (out / 'outlines.npz').open('wb') as fh:
        np.savez_compressed(fh, **ol)
    files['outlines'] = {'file': 'outlines.npz', 'sha256': file_hash(out / 'outlines.npz'),
                         'frame': 'work frame (x front, y thumb side, z up, mm; the mirrored model for a left-hand mouse); _2d in the view named in regions.*.outline.frame, _3d lifted onto the surface'}
    sets = {}
    for k, alt in seg['alt_face_sets'].items():
        for mode, ids_ in alt.items():
            sets[f'{names_out[k]}_{mode}'] = ids_.astype(np.int64)
    with (out / 'button_face_sets.npz').open('wb') as fh:
        np.savez_compressed(fh, **sets)
    files['button_face_sets'] = {'file': 'button_face_sets.npz', 'sha256': file_hash(out / 'button_face_sets.npz'),
                                 'note': 'face ids of each side-button pad when the flank view alone decides (side_priority), the thumb-shoulder view is weighted (top_priority) or both are balanced (the labels in face_labels)'}
    ov = None
    if overlay:
        try:
            ov = _overlay(M, lab, seg, out, names_out, mirrored)
        except ImportError:
            warnings.append({'code': 'OVERLAY_SKIPPED', 'note': 'Pillow is not installed (geometry extra).'})
    if ov:
        files['overlays'] = ov
    report = {
        'schema': 'scan_regions_report/1', 'run_id': run_id, 'scan_id': scan_id, 'status': status, 'blocking_reasons': blockers, 'warnings': warnings,
        'code_version': {'scan_regions': REGIONS_VERSION, 'package': __version__}, 'settings': {'handedness': handedness, 'overlay': bool(overlay)},
        'scan': {'prepared_npz_sha256': prep['prepared_npz_sha256'], 'source_sha256': prep['source']['sha256'], 'faces': int(len(f))},
        'surface_only': True, 'limitations': _LIMITS, 'frame': frame_info, 'handedness': {**hand_info, 'used': use, 'mirrored_for_detection': mirrored},
        'regions': regions, 'other_faces': other, 'files': files, 'method': 'scan_segment v4 (geometry only: no texture, no label files)', 'seconds': round(time.time() - t0, 1),
        'region_naming': 'positional: left_click is the button on the mouse-left (+y) side of the frame; for a left-hand mouse the thumb-side main button is therefore right_click',
        'checks': {'prepared_scan_ready': 'PASS', 'frame_orientation_consistent': 'PASS', 'every_region_nonempty': 'PASS' if status == 'READY' else 'FAIL', 'physical_function': 'UNVERIFIED'},
        'execution': {'completed': True},
    }
    atomic_json(out / 'regions_report.json', report)
    return report


def _stored(out: Path, scan_id: str) -> dict[str, Any]:
    rep = json_load(out / 'regions_report.json')
    items = [v for k, v in rep['files'].items() if k != 'overlays'] + list(rep['files'].get('overlays') or [])
    for it in items:
        p = out / it['file']
        if not p.is_file() or file_hash(p) != it['sha256']:
            raise BrainError('REGIONS_OUTPUT_CHANGED', 'A stored region result no longer matches its recorded hash; it is not overwritten.', {'file': it['file']})
    return {**rep, 'cached': True}


# ------------------------------------------------------------------ overlay png
def _overlay(M: _Mesh, lab: np.ndarray, seg: dict[str, Any], out: Path, names_out: dict[str, str], mirrored: bool) -> list[dict[str, Any]]:
    from PIL import Image, ImageDraw, ImageFont
    cols = {'LC': (224, 32, 42), 'RC': (31, 95, 214), 'WH': (18, 160, 74), 'B1': (255, 138, 0), 'B2': (208, 32, 200)}
    ss, ppm = 2, 7.0                       # 2x supersampling, 7 px per mm
    result = []
    light = np.array([-0.5, 0.6, 0.6])
    light /= np.linalg.norm(light)
    for view in ('top', 'side'):
        if view == 'top':
            r, u, t = np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0])
        else:
            r, u, t = np.array([-1.0, 0, 0]), np.array([0, 0, 1.0]), np.array([0, 1.0, 0])
        pr = np.stack([M.P @ r, M.P @ u, M.P @ t], -1)
        lo, hi = pr[:, :2].min(0) - 4, pr[:, :2].max(0) + 4
        wpx, hpx = int((hi[0] - lo[0]) * ppm * ss), int((hi[1] - lo[1]) * ppm * ss)
        img = Image.new('RGB', (wpx, hpx), (250, 250, 250))
        dr = ImageDraw.Draw(img)
        trp = pr[M.F]
        vis = (M.fn @ t) > 0.02
        ii = np.flatnonzero(vis)
        ii = ii[np.argsort(trp[ii, :, 2].mean(1))]
        shade = np.clip(0.28 + 0.42 * np.abs(M.fn @ t) + 0.4 * np.clip(M.fn @ (light[0] * r + light[1] * u + light[2] * t), 0, 1), 0, 1)
        base = (shade * 0.86 + 0.06)[:, None] * np.array([255.0, 255.0, 255.0])
        for k, c in cols.items():
            mk = lab == NAMES.index(k)
            base[mk] = base[mk] * 0.8 + np.array(c) * 0.2
        px = (trp[:, :, :2] - lo) * ppm * ss
        px[:, :, 1] = hpx - px[:, :, 1]
        for i in ii:
            dr.polygon([tuple(p) for p in px[i]], fill=tuple(int(x) for x in base[i]))
        keys = ('LC', 'RC', 'WH') if view == 'top' else ('B1', 'B2')
        for k in keys:
            o3 = seg['outlines_3d'][k]
            o3 = np.vstack([o3, o3[:1]])
            q = np.stack([o3 @ r, o3 @ u], -1)
            sx_ = (q[:, 0] - lo[0]) * ppm * ss
            sy_ = hpx - (q[:, 1] - lo[1]) * ppm * ss
            dr.line(list(zip(sx_.tolist(), sy_.tolist())), fill=cols[k], width=max(1, ss))
        img = img.resize((wpx // ss, hpx // ss), Image.LANCZOS)
        d2 = ImageDraw.Draw(img)
        try:
            font = ImageFont.load_default(size=13)
        except TypeError:
            font = ImageFont.load_default()
        y0 = 8
        d2.text((8, y0), f"{'top view (front right)' if view == 'top' else 'thumb flank (front left)'}  {'[mirrored model]' if mirrored else ''}", fill=(30, 30, 30), font=font)
        for k in keys:
            y0 += 16
            d2.line([(8, y0 + 7), (28, y0 + 7)], fill=cols[k], width=2)
            d2.text((34, y0), names_out[k], fill=(30, 30, 30), font=font)
        bar = int(10 * ppm)
        d2.line([(img.width - 16 - bar, img.height - 14), (img.width - 16, img.height - 14)], fill=(0, 0, 0), width=1)
        d2.text((img.width - 16 - bar, img.height - 30), '10 mm', fill=(0, 0, 0), font=font)
        name = f'overlay_{view}.png'
        img.save(out / name)
        result.append({'file': name, 'sha256': file_hash(out / name), 'view': view})
    return result
