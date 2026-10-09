"""Scan PLY -> cleaned/decimated STL (subprocess worker) and region recognition. Synthetic meshes; the real-scan probe is skipped when absent."""
from __future__ import annotations
import json
import sys
from pathlib import Path
import numpy as np
import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import scan_model as smod
from cadmcp_brain.studio import scan_model_worker as W
from cadmcp_brain.studio import scan_regions as sr
from cadmcp_brain.studio import scan_segment as sg
from cadmcp_brain.studio import scan_shell as sh
from cadmcp_brain.studio import scan_shellparts as sp

sys.path.insert(0, str(Path(__file__).parent))
import scan_shapes as S  # noqa: E402

REAL_PLY = Path('E:/WINDOWS/Y/Download/endgame-gear-op1-8k-v2-3d-model/endgame-gear-op1-8k-v2-scan.ply')
GT_JSON = Path('V:/mouse/LH2-mouse/work/scan_clean/user_ref/user_regions_raw.json')


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code
    return exc.value


def write_soup_ply(path: Path, v: np.ndarray, f: np.ndarray) -> None:
    """Triangle soup PLY: every face corner is its own vertex, like a textured scan with a UV seam at every edge."""
    tri = v[f].reshape(-1, 3)
    with open(path, 'w', encoding='ascii') as fh:
        fh.write(f'ply\nformat ascii 1.0\nelement vertex {len(tri)}\nproperty float x\nproperty float y\nproperty float z\n'
                 f'element face {len(f)}\nproperty list uchar int vertex_indices\nend_header\n')
        for p in tri:
            fh.write('%.6f %.6f %.6f\n' % tuple(p))
        for i in range(len(f)):
            fh.write(f'3 {3 * i} {3 * i + 1} {3 * i + 2}\n')


@pytest.fixture
def scan_python():
    try:
        return smod.find_scan_python(Path('.'))
    except BrainError:
        pytest.skip('no scan python (CADMCP_SCAN_PYTHON / .venv-scan)')


# ------------------------------------------------------------------ plumbing without pymeshlab
def test_scan_python_missing_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv(smod.ENV_PYTHON, str(tmp_path / 'nope.exe'))
    rejects('SCAN_PYTHON_MISSING', lambda: smod.find_scan_python(tmp_path))
    monkeypatch.delenv(smod.ENV_PYTHON)
    monkeypatch.setattr(smod, 'FALLBACKS', [])
    monkeypatch.setattr(smod.shutil, 'which', lambda _n: None)
    rejects('SCAN_PYTHON_MISSING', lambda: smod.find_scan_python(tmp_path / 'ws'))


def test_scan_model_validates_before_running(tmp_path):
    (tmp_path / 'a.ply').write_text('ply\n')
    (tmp_path / 'a.stl').write_text('x')
    rejects('SCAN_UNIT', lambda: smod.scan_model(tmp_path, 'a.ply', 'furlong'))
    rejects('SCAN_MODEL_SETTINGS', lambda: smod.scan_model(tmp_path, 'a.ply', 'mm', target_max_error_mm=0.2, hard_limit_error_mm=0.1))
    rejects('SCAN_MODEL_SETTINGS', lambda: smod.scan_model(tmp_path, 'a.ply', 'mm', target_max_error_mm=0))
    rejects('SCAN_FILE', lambda: smod.scan_model(tmp_path, 'a.stl', 'mm'))
    rejects('UNSAFE_PATH', lambda: smod.scan_model(tmp_path, 'missing.ply', 'mm'))


def test_pymeshlab_is_never_imported_in_the_server_process():
    src = Path(smod.__file__).read_text(encoding='utf-8') + Path(sr.__file__).read_text(encoding='utf-8')
    assert 'import pymeshlab' not in src
    assert 'pymeshlab' not in sys.modules


def test_worker_numpy_helpers():
    v, f = S.sphere(10.0, 6)
    t = W.topology(v, f)
    assert t['watertight'] and t['manifold'] and t['winding_consistent'] and t['components'] == 1 and t['signed_volume_mm3'] > 0
    g = f[1:]
    assert W.topology(v, g)['watertight'] is False
    v2, f2, n = W.patch_small_holes(v, g, 8)
    assert n >= 1 and W.topology(v2, f2)['watertight'] and W.topology(v2, f2)['winding_consistent']


def test_tools_register_both_new_tools(tmp_path):
    t = Tools(Brain(tmp_path))
    names = {x['name'] for x in t.list()}
    assert {'brain_mouse_scan_model', 'brain_mouse_recognize_regions'} <= names
    rejects('UNSAFE_PATH', lambda: t.call('brain_mouse_scan_model', {'relative_path': 'x.ply', 'unit': 'mm'}))


# ------------------------------------------------------------------ subprocess worker end to end
def test_scan_model_on_soup_ply(tmp_path, scan_python, monkeypatch):
    monkeypatch.setenv(smod.ENV_PYTHON, str(scan_python))
    v, f = S.sphere(20.0, 24)
    (tmp_path / 'scans').mkdir()
    write_soup_ply(tmp_path / 'scans' / 's.ply', v, f)
    before = (tmp_path / 'scans' / 's.ply').read_bytes()
    r = smod.scan_model(tmp_path, 'scans/s.ply', 'mm')
    assert r['status'] == 'READY', r
    for o in (r['outputs']['target'], r['outputs']['hard_limit'], r['cleaned_fullres']):
        assert o['topology']['watertight'] and o['topology']['manifold'] and o['topology']['winding_consistent']
    assert r['outputs']['target']['faces'] < r['cleaned_fullres']['faces']
    assert r['outputs']['target']['error_vs_welded_original_mm']['budget']['max_mm'] <= 0.05 + 1e-9
    folder = tmp_path / 'mouse' / 'scans' / r['model_id']
    assert (folder / Path(r['outputs']['target']['relative_path']).name).is_file()
    assert (tmp_path / 'scans' / 's.ply').read_bytes() == before        # source never modified
    p = sh.prepare_scan(tmp_path, f'mouse/scans/{r["model_id"]}/cleaned_fullres.stl', 'mm')
    assert p['prepared_status'] == 'READY'                                # output feeds the existing intake gate
    again = smod.scan_model(tmp_path, 'scans/s.ply', 'mm')
    assert again['cached'] is True and again['model_id'] == r['model_id']
    (folder / Path(r['outputs']['target']['relative_path']).name).write_bytes(b'tampered')
    rejects('SCAN_MODEL_OUTPUT_CHANGED', lambda: smod.scan_model(tmp_path, 'scans/s.ply', 'mm'))


# ------------------------------------------------------------------ regions: synthetic
def mouse_blob(n=40):
    v, f = S.superellipsoid(60.0, 33.0, 20.0, 0.6, n)
    v = v + np.array([0, 0, 20.0])
    v[:, 2] = np.maximum(v[:, 2], 4.0)            # flat base
    return v, f


def test_canonical_frame_is_pose_invariant_and_proper():
    v, f = mouse_blob()
    Rm, _ = np.linalg.qr(np.random.default_rng(3).normal(size=(3, 3)))
    if np.linalg.det(Rm) < 0:
        Rm[:, 0] *= -1
    v2 = v @ Rm.T + 7.0
    f1, f2 = sr.canonical_frame(v, f), sr.canonical_frame(v2, f)
    q1, q2 = sr.canonical_coords(v, f1), sr.canonical_coords(v2, f2)
    assert np.linalg.det(f1['rotation']) > 0 and np.linalg.det(f2['rotation']) > 0
    assert np.allclose(f1['extents_mm'], f2['extents_mm'], atol=1e-6)
    assert abs(q1[:, 2].min()) < 1e-6 and abs(q2[:, 2].min()) < 1e-6


def test_regions_refuse_unclosed_and_wrong_size_meshes(tmp_path):
    v, f = mouse_blob(12)
    S.write_stl(tmp_path / 'open.stl', v, f[5:])
    p = sh.prepare_scan(tmp_path, 'open.stl', 'mm')
    r = sr.recognize_regions(tmp_path, p['scan_id'])
    assert r['status'] == 'NOT_READY' and r['surface_only'] is True and 'SCAN_NOT_READY' in r['blocking_reasons']
    S.write_stl(tmp_path / 'ball.stl', *S.sphere(20.0, 8))
    p = sh.prepare_scan(tmp_path, 'ball.stl', 'mm')
    r = sr.recognize_regions(tmp_path, p['scan_id'])
    assert r['status'] == 'NOT_READY' and 'LENGTH_OUTSIDE_CALIBRATED_RANGE' in r['blocking_reasons']
    rejects('REGIONS_SETTINGS', lambda: sr.recognize_regions(tmp_path, p['scan_id'], handedness='both'))
    rejects('SCAN_NOT_FOUND', lambda: sr.recognize_regions(tmp_path, 'scan_000000000000'))


def test_regions_on_generic_blob_never_invent_regions(tmp_path):
    v, f = mouse_blob(30)
    S.write_stl(tmp_path / 'blob.stl', v, f)
    p = sh.prepare_scan(tmp_path, 'blob.stl', 'mm')
    try:
        r = sr.recognize_regions(tmp_path, p['scan_id'])
    except BrainError as e:                       # priors not found is the honest answer for a non-mouse
        assert e.code == 'REGIONS_PRIORS_NOT_FOUND'
        return
    assert r['status'] in ('READY', 'NOT_READY') and r['surface_only'] is True


# ------------------------------------------------------------------ real scan + ground truth (skipped when absent)
def _iou(a, b):
    return float((a & b).sum() / max((a | b).sum(), 1))


@pytest.mark.skipif(not (REAL_PLY.is_file() and GT_JSON.is_file()), reason='licensed real scan / ground truth not available')
def test_real_scan_end_to_end_and_ground_truth(tmp_path, scan_python, monkeypatch):
    from PIL import Image, ImageDraw
    monkeypatch.setenv(smod.ENV_PYTHON, str(scan_python))
    (tmp_path / 'scans').mkdir()
    (tmp_path / 'scans' / 'op1.ply').write_bytes(REAL_PLY.read_bytes())
    t = Tools(Brain(tmp_path))
    m = t.call('brain_mouse_scan_model', {'relative_path': 'scans/op1.ply', 'unit': 'mm'})
    assert m['status'] == 'READY'
    tgt = m['outputs']['target']
    assert tgt['error_vs_welded_original_mm']['budget']['max_mm'] <= 0.05 and tgt['topology']['watertight']
    p = t.call('brain_mouse_prepare_scan', {'relative_path': f'mouse/scans/{m["model_id"]}/cleaned_fullres.stl', 'unit': 'mm'})
    assert p['prepared_status'] == 'READY'
    r = t.call('brain_mouse_recognize_regions', {'scan_id': p['scan_id']})
    assert r['status'] == 'READY'
    d = sh.scan_dir(tmp_path, p['scan_id'])
    v, f = sh.load_prepared_mesh(d)
    out = d / 'regions' / r['run_id']
    codes = np.load(out / 'face_labels.npz')['face_labels']
    assert (out / 'overlay_top.png').is_file() and (out / 'overlay_side.png').is_file()
    # ground truth in the authoring frame (regression only: the pipeline never reads it)
    fr = sr.canonical_frame(v, f)
    Wc = sr.working_coords(sr.canonical_coords(v, fr), False)
    GT = json.load(open(GT_JSON, encoding='utf-8'))
    PIX = 0.05

    def poly(pg, x0, x1, y0, y1):
        xs = np.arange(x0, x1, PIX) + PIX / 2
        ys = np.arange(y0, y1, PIX) + PIX / 2
        im = Image.new('1', (len(xs), len(ys)), 0)
        ImageDraw.Draw(im).polygon([tuple(q) for q in (np.array(pg) - [xs[0] - PIX / 2, ys[0] - PIX / 2]) / PIX], fill=1)
        return np.array(im).T.astype(bool)

    def tris(t2, x0, x1, y0, y1):
        xs = np.arange(x0, x1, PIX) + PIX / 2
        ys = np.arange(y0, y1, PIX) + PIX / 2
        im = Image.new('1', (len(xs), len(ys)), 0)
        dr = ImageDraw.Draw(im)
        for q in (t2 - [xs[0] - PIX / 2, ys[0] - PIX / 2]) / PIX:
            dr.polygon([tuple(a) for a in q], fill=1)
        return np.array(im).T.astype(bool)
    gt = {}
    for g in GT['top']:
        k = {'red': 'LC', 'blue': 'RC'}.get(g['color'])
        if k:
            gt[k] = g['polygon_mm']
    sides = sorted(GT['side'], key=lambda g: np.array(g['polygon_mm'])[:, 0].mean())
    gt['B1'], gt['B2'] = sides[0]['polygon_mm'], sides[1]['polygon_mm']
    code = {'LC': 1, 'RC': 2, 'B1': 4, 'B2': 5}
    tri = Wc[f]
    up = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])[:, 2] > 0
    iou = {}
    for k in ('LC', 'RC'):
        iou[k] = _iou(tris(tri[(codes == code[k]) & up][:, :, :2], -3, 50, -31, 29), poly(gt[k], -3, 50, -31, 29))
    t2 = np.stack([tri[:, :, 0], -tri[:, :, 2]], -1)
    for k in ('B1', 'B2'):
        iou[k] = _iou(tris(t2[codes == code[k]], -30, 12, -15, 0), poly(gt[k], -30, 12, -15, 0))
    print('IoU', iou)
    # measured (R2.0, geometry only): LC 0.936, RC 0.938, B1 0.838, B2 0.874. Goals: LC, RC >= 0.93, side button 1 >= 0.8, 2 >= 0.7.
    assert iou['LC'] >= 0.93 and iou['RC'] >= 0.93 and iou['B1'] >= 0.8 and iou['B2'] >= 0.7
    # shell / sensor step on the same prepared scan (offline reference, full-resolution raster: aperture centre x -8.68, y -2.82 mm,
    # rounded rectangle 5.31 x 3.70 mm, floor depth 2.9 mm in this frame; no ground truth is read by the tool)
    s2 = t.call('brain_mouse_recognize_shell', {'scan_id': p['scan_id']})
    assert s2['status'] == 'READY' and s2['sensor']['found'] and s2['surface_only'] is True
    cx, cy = s2['sensor']['centre_mm']['x'], s2['sensor']['centre_mm']['y']
    assert abs(cx + 8.68) < 0.35 and abs(cy + 2.82) < 0.35
    assert 2.0 < s2['sensor']['depth_mm'] < 3.6
    ap = s2['sensor']['aperture']
    print('SENSOR', cx, cy, ap['shape'], ap['major_mm'], ap['minor_mm'], ap['superellipse_exponent'], s2['sensor']['depth_mm'], s2['sensor']['confidence'],
          s2['sensor']['uncertainty_mm'], [(c['score'], c.get('centroid_mm')) for c in s2['sensor']['candidates']])
    assert ap['shape'] in ('rounded_rectangle', 'ellipse') and 4.6 < ap['major_mm'] < 6.0 and 3.2 < ap['minor_mm'] < 4.2
    assert s2['sensor']['confidence'] in ('high', 'medium') and s2['sensor']['evidence'] == {'geometry': True, 'texture': False, 'pcb': False}
    ol = s2['sensor']['outline']            # mesh-rim line + arc outline; user-drawn reference (offline only): D shape, centre about (-8.62, -2.85)
    print('OUTLINE', ol['family'], ol['residuals_mm'], s2['sensor']['window_size_mm'])
    assert ol['found'] and ol['residuals_mm']['rms_mm'] < 0.08 and ol['polyline_points'] >= 100
    assert 'ellipse (reference only)' in ol['families'] and not ol['family'].startswith('ellipse')
    assert s2['regions']['bottom_plate']['components'] == 1 and s2['seam']['supported_fraction'] > 0.5
    assert t.call('brain_mouse_recognize_shell', {'scan_id': p['scan_id']})['cached'] is True


# ------------------------------------------------------------------ scan_segment helpers and shell step: synthetic
def test_segment_helpers_contour_watershed_and_outline():
    yy, xx = np.mgrid[0:80, 0:100]
    disk = (xx - 50) ** 2 + (yy - 40) ** 2 < 20 ** 2
    cs = sg.find_contours(disk.astype(float), 0.5)
    assert len(cs) == 1 and abs(np.ptp(cs[0][:, 0]) - 40) < 2
    cost = np.zeros((100, 80))
    mk = np.zeros((100, 80), int)
    mk[10, 40], mk[90, 40] = 1, 2
    cost[50, :] = 5.0                                  # a ridge halfway between the markers
    lab = sg.watershed(cost, mk)
    assert lab[20, 40] == 1 and lab[80, 40] == 2


def test_shell_refuses_not_ready_scan(tmp_path):
    v, f = mouse_blob(12)
    S.write_stl(tmp_path / 'open.stl', v, f[5:])
    p = sh.prepare_scan(tmp_path, 'open.stl', 'mm')
    r = sp.recognize_shell(tmp_path, p['scan_id'])
    assert r['status'] == 'NOT_READY' and 'REGIONS_NOT_READY' in r['blocking_reasons'] and r['surface_only'] is True
    rejects('SCAN_NOT_FOUND', lambda: sp.recognize_shell(tmp_path, 'scan_000000000000'))


def test_shell_on_generic_blob_never_invents_parts(tmp_path):
    v, f = mouse_blob(30)
    S.write_stl(tmp_path / 'blob.stl', v, f)
    p = sh.prepare_scan(tmp_path, 'blob.stl', 'mm')
    try:
        r = sp.recognize_shell(tmp_path, p['scan_id'])
    except BrainError as e:
        assert e.code in ('REGIONS_PRIORS_NOT_FOUND', 'SHELL_WALL_NOT_FOUND', 'SHELL_SEAM_NOT_FOUND')
        return
    assert r['status'] in ('READY', 'NOT_READY') and r['surface_only'] is True


# ------------------------------------------------------------------ sensor window: geometry only, synthetic
def _slab_with_pockets(pocket=True, screws=True, step=0.4, shape='rrect'):
    """Closed mouse-like slab: flat base 120 x 60 mm with an optional rounded-rectangle sensor pocket and two rear screw holes, domed top."""
    xs = np.arange(-60, 60 + 1e-9, step)
    ys = np.arange(-30, 30 + 1e-9, step)
    X, Y = np.meshgrid(xs, ys, indexing='ij')
    zb = np.zeros_like(X)
    if pocket and shape == 'rrect':
        zb[(np.abs((X + 8) / 2.6) ** 3.4 + np.abs((Y + 3) / 1.85) ** 3.4) <= 1] = 2.8
    elif pocket:                                               # D shape: flat end with square corners at x = -11, semicircle r 1.9 centred at x = -7
        zb[((X >= -11) & (X <= -7) & (np.abs(Y + 3) <= 1.9)) | (np.hypot(X + 7, Y + 3) <= 1.9)] = 2.8
    if screws:
        for cy in (-18, 18):
            zb[np.hypot(X + 48, Y - cy) <= 2.4] = 1.2
    zt = 5 + 20 * np.maximum(0, 1 - (X / 60) ** 2 - (Y / 30) ** 2)
    nx, ny = X.shape
    idx = np.arange(nx * ny).reshape(nx, ny)
    a, b, c, d = idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()
    bot = np.r_[np.c_[a, c, b], np.c_[a, d, c]]               # normals -z
    top = np.r_[np.c_[a, b, c], np.c_[a, c, d]] + nx * ny      # normals +z
    ring = np.r_[idx[:, 0], idx[-1, 1:], idx[-2::-1, -1], idx[0, -2:0:-1]]
    r2 = np.roll(ring, -1)
    walls = np.r_[np.c_[ring, r2, r2 + nx * ny], np.c_[ring, r2 + nx * ny, ring + nx * ny]]
    P = np.r_[np.c_[X.ravel(), Y.ravel(), zb.ravel()], np.c_[X.ravel(), Y.ravel(), zt.ravel()]]
    return P, np.r_[bot, top, walls].astype(np.int64)


def _sensor_on(P, F):
    M = sr._Mesh(P, F)
    ft = sg.surface_features(M.P, M.F, M.L, M.vn, M.fn)
    return sp.sensor_window(M, ft)


def test_sensor_window_geometry_only_finds_rounded_rect_pocket():
    r = _sensor_on(*_slab_with_pockets())
    assert r['found'] and r['shape'] == 'rounded_rectangle' and r['confidence'] == 'high'
    assert abs(r['centre_xy'][0] + 8) < 0.25 and abs(r['centre_xy'][1] + 3) < 0.25
    # the faceted pocket wall spans one grid step (0.4 mm), so the traced rim lies up to a step outside the nominal 5.2 x 3.7 outline
    assert 5.0 < r['size_xy'][0] < 6.0 and 3.5 < r['size_xy'][1] < 4.5
    assert abs(r['depth_mm'] - 2.8) < 0.3
    assert len(r['candidates']) == 3 and r['candidates'][0]['score'] > 10 * r['candidates'][1]['score']   # the rear screw holes rank far below
    assert all(u < 0.5 for u in r['unc_centre'])
    mo = r['mesh_outline']
    assert mo['found'] and mo['residuals_mm']['rms_mm'] < 0.15 and mo['primitive']['straight_edges'] >= 2


def test_sensor_window_d_shaped_pocket_outline_is_lines_and_arcs():
    r = _sensor_on(*_slab_with_pockets(shape='d', step=0.2))
    mo = r['mesh_outline']
    print('D', r['centre_xy'], r['size_xy'], mo['family'], mo['residuals_mm'], [a['radius_mm'] for a in mo['primitive']['arcs']])
    # area centroid of the D (rectangle 4 x 3.8 + half disc r 1.9): x = -8.24; bbox centre -8.05
    assert r['found'] and mo['found'] and abs(r['centre_xy'][1] + 3) < 0.2 and -8.45 < r['centre_xy'][0] < -8.05
    assert 5.6 < r['size_xy'][0] < 6.4 and 3.6 < r['size_xy'][1] < 4.4
    assert mo['residuals_mm']['rms_mm'] < 0.1 and mo['family'] != 'ellipse'


def test_sensor_window_absent_is_reported_not_invented():
    r = _sensor_on(*_slab_with_pockets(pocket=False, screws=False))
    assert r['found'] is False and r['candidates'] == [] and r['reason']
