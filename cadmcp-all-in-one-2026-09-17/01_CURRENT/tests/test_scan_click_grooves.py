"""brain_mouse_scan_click_grooves: synthetic dome with two click panels, a wheel and a centre gap. No scan data is used or stored.

The geometry tests run the worker in this process (needs trimesh, shapely, manifold3d: extra `scan-grooves`; skipped when they are missing);
the end-to-end test goes through the tool and the separate scan python (skipped without one).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import numpy as np
import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import scan_click_grooves as scg
from cadmcp_brain.studio import scan_click_grooves_worker as W
from cadmcp_brain.studio import scan_model as smod

trimesh = pytest.importorskip('trimesh')
pytest.importorskip('shapely')
pytest.importorskip('manifold3d')

H = 0.5                                   # grid pitch of the synthetic mesh, mm
AREA = (1.0, 39.0, -13.0, 13.0)           # click area x0, x1, y0, y1 (the body is x -3..42, y -17..17)
WINDOW = (15.0, 27.0, -5.0, 3.0)          # wheel window
GAP_Y = -1.0                              # left click above, right click below


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code
    return exc.value


def dome_height(x, y):
    return 14.0 + 6.0 * (1 - ((x - 20) / 22.0) ** 2 - (y / 17.0) ** 2)


def make_dome(thin_rear: bool = False, gap_y: float = GAP_Y, window=WINDOW, noisy: bool = False):
    """Closed solid from two height fields (top dome with a raised wheel, bottom parallel 6 mm below; 1 mm only for x < 3.5 when thin_rear).
    noisy: the click label outline is jagged (rear edge +-0.4 mm steps every 2 mm, a 1 mm x 3 mm label overhang behind the right click)."""
    xs = np.arange(-3, 42 + 1e-9, H)
    ys = np.arange(-17, 17 + 1e-9, H)
    nx, ny = len(xs), len(ys)
    X, Y = np.meshgrid(xs, ys, indexing='ij')
    top = dome_height(X, Y)
    wx0, wx1, wy0, wy1 = window
    top = top + 3.0 * ((X >= wx0) & (X <= wx1) & (Y >= wy0) & (Y <= wy1))
    thick = np.where((X < 3.5) & thin_rear, 1.0, 6.0)
    bot = dome_height(X, Y) - thick
    vt = np.c_[X.ravel(), Y.ravel(), top.ravel()]
    vb = np.c_[X.ravel(), Y.ravel(), bot.ravel()]
    V = np.vstack([vt, vb])
    ti = lambda i, j: i * ny + j
    bi = lambda i, j: nx * ny + i * ny + j
    F = []
    for i in range(nx - 1):
        for j in range(ny - 1):
            F += [(ti(i, j), ti(i + 1, j), ti(i + 1, j + 1)), (ti(i, j), ti(i + 1, j + 1), ti(i, j + 1))]
    n_top = len(F)
    for i in range(nx - 1):
        for j in range(ny - 1):
            F += [(bi(i, j), bi(i + 1, j + 1), bi(i + 1, j)), (bi(i, j), bi(i, j + 1), bi(i + 1, j + 1))]
    for j in range(ny - 1):                                               # x = -3 and x = 42 walls
        F += [(ti(0, j), ti(0, j + 1), bi(0, j + 1)), (ti(0, j), bi(0, j + 1), bi(0, j))]
        F += [(ti(nx - 1, j), bi(nx - 1, j + 1), ti(nx - 1, j + 1)), (ti(nx - 1, j), bi(nx - 1, j), bi(nx - 1, j + 1))]
    for i in range(nx - 1):                                               # y = -17 and y = 17 walls
        F += [(ti(i, 0), bi(i + 1, 0), ti(i + 1, 0)), (ti(i, 0), bi(i, 0), bi(i + 1, 0))]
        F += [(ti(i, ny - 1), ti(i + 1, ny - 1), bi(i + 1, ny - 1)), (ti(i, ny - 1), bi(i + 1, ny - 1), bi(i, ny - 1))]
    F = np.array(F, np.int64)
    cen = V[F].mean(1)
    lab: dict[str, list[int]] = {k: [] for k in ('left_click', 'right_click', 'wheel', 'top_shell', 'bottom_plate')}
    for k in range(len(F)):
        x, y, z = cen[k]
        if k >= n_top and z < dome_height(x, y) - 0.5 and k < n_top + 2 * (nx - 1) * (ny - 1):
            lab['bottom_plate'].append(k)
        elif k < n_top:
            inw = wx0 <= x <= wx1 and wy0 <= y <= wy1
            ax0, ay1 = AREA[0], AREA[3]
            if noisy:
                ax0 = AREA[0] + (0.4 if int(np.floor(y / 2.0)) % 2 else -0.4) - (1.0 if -6.0 <= y <= -3.0 else 0.0)
                ay1 = AREA[3] + 0.3 * np.sin(1.3 * x)
            ina = ax0 <= x <= AREA[1] and -ay1 <= y <= ay1 if noisy else AREA[0] <= x <= AREA[1] and AREA[2] <= y <= AREA[3]
            if inw:
                lab['wheel'].append(k)
            elif ina:
                lab['left_click' if y >= gap_y else 'right_click'].append(k)
            else:
                lab['top_shell'].append(k)
    return V, F, lab


def write_case(folder: Path, thin_rear: bool = False, **kw):
    V, F, lab = make_dome(thin_rear, **kw)
    m = trimesh.Trimesh(V, F, process=False)
    folder.mkdir(parents=True, exist_ok=True)
    m.export(folder / 'dome.stl')
    (folder / 'labels.json').write_text(json.dumps({'regions': {k: {'face_ids': v} for k, v in lab.items()}}), encoding='utf-8')
    return m, lab


def request(folder: Path, **params):
    return {'input_path': str(folder / 'dome.stl'), 'labels_path': str(folder / 'labels.json'), 'unit_scale': 1.0, 'out_dir': str(folder / 'out'),
            'params': {**W.DEFAULTS, 'overlay': False, **params}}


@pytest.fixture(scope='module')
def case(tmp_path_factory):
    folder = tmp_path_factory.mktemp('dome')
    src, lab = write_case(folder)
    res = W.run(request(folder))
    return {'folder': folder, 'src': src, 'lab': lab, 'res': res, 'out': trimesh.load(folder / 'out' / 'combined_grooved.stl', process=True)}


def top_h(mesh, pts):
    return W.VerticalHits(np.asarray(mesh.vertices), np.asarray(mesh.faces)).top(np.asarray(pts, float))


def test_synthetic_dome_is_a_valid_input():
    V, F, lab = make_dome()
    m = trimesh.Trimesh(V, F, process=False)
    assert m.is_watertight and m.is_winding_consistent and m.volume > 0
    assert all(len(v) > 100 for k, v in lab.items() if k != 'top_shell')


# ------------------------------------------------------------------ slots
def test_slot_width_depth_and_floor(case):
    m = case['res']['metrics']
    per = m['slot_measure']['perimeter']
    assert per['width_mm_p5_50_95'][1] == pytest.approx(0.5, abs=0.03)                       # 0.5 mm slot, vertical walls
    assert per['depth_below_panel_side_surface_p5_50_95'][1] == pytest.approx(2.0, abs=0.15)
    assert per['floor_flatness_across_width_max_mm'] < 0.01                                  # flat floor across the width
    nf = m['new_faces']
    assert nf['wall_like'] > 100 and nf['wall_area_weighted_mean_abs_nz'] < 1e-3                       # vertical walls
    assert nf['wall_max_abs_nz'] < 0.05 or nf['wall_area_nz_gt_0p05_mm2'] < 1e-4                       # only boolean slivers may tilt
    assert case['res']['fit']['perimeter']['stations'] > 300


def test_depth_and_width_are_parameters(tmp_path):
    write_case(tmp_path)
    r = W.run(request(tmp_path, slot_depth_mm=1.0, slot_width_mm=0.8))
    per = r['metrics']['slot_measure']['perimeter']
    assert per['depth_below_panel_side_surface_p5_50_95'][1] == pytest.approx(1.0, abs=0.15)
    assert per['width_mm_p5_50_95'][1] == pytest.approx(0.8, abs=0.03)
    assert r['params_used']['slot_depth_mm'] == 1.0 and r['params_used']['slot_width_mm'] == 0.8


def test_centre_gap_is_the_union_of_two_half_slots(case):
    r = case['res']
    assert r['fit']['gap_lines_merged'] is True                                              # the clicks meet at one boundary
    cg = r['metrics']['centre_gap_width']
    assert cg['median_mm'] == pytest.approx(1.0, abs=0.06)
    # independent check on the written mesh: contiguous lowered stretch across the gap at x = 8
    yy = np.arange(-3.0, 1.0, 0.02)
    h = top_h(case['out'], np.c_[np.full_like(yy, 8.0), yy])
    low = h < h.max() - 1.0
    assert (yy[low].max() - yy[low].min()) == pytest.approx(1.0, abs=0.08)
    assert abs(0.5 * (yy[low].max() + yy[low].min()) - GAP_Y) < 0.1
    assert set(r['metrics']['slot_measure']) >= {'perimeter', 'gap_rear_left_click', 'gap_rear_right_click', 'gap_front_left_click', 'gap_front_right_click'}


# ------------------------------------------------------------------ window
def test_wheel_removed_and_window_rebuilt(case):
    r = case['res']
    win = r['fit']['window']
    # G1.5: window = envelope of the well rim and the label notch (13 x 9 mm, sharp corners here), never sharper than
    # window_min_corner_radius_mm (2 mm); the sides then grow until the box-shaped wheel footprint (12 x 8) + 0.5 mm clearance is inside
    assert 'WINDOW_RIM_FROM_LABELS' not in {w['code'] for w in r['warnings']}
    assert win['corner_radius_mm'] == pytest.approx(2.0)
    assert 13.0 - 1e-6 <= win['dims_mm']['width_x'] <= 14.3 and 9.0 - 1e-6 <= win['dims_mm']['height_y'] <= 10.3
    from shapely.geometry import Polygon
    lay = json.loads((case['folder'] / 'out' / 'slot_layout.json').read_text(encoding='utf-8'))['window']
    wpoly = Polygon(W.fillet_closed(np.asarray(lay['corners_TR_TL_BL_BR'], float), lay['corner_radius_mm']))
    hull = Polygon(win['rim_detection']['wheel_hull_xy']).buffer(0.5 - 0.02, 8)
    assert wpoly.buffer(1e-6).contains(hull)                                                   # the wheel + clearance is inside the window
    assert r['metrics']['outline_quality']['window_shape']['ok']
    assert win['rim_plane']['resid_rms_mm'] < 0.5
    wm = r['metrics']['window']
    assert wm['max_vertex_height_above_floor_inside_window_mm'] < 1e-3                         # nothing of the wheel is left above the floor
    assert wm['floor']['max_dev_from_plane_mm'] < 0.05 and wm['depth_below_rim_surface_mm']['p50'] == pytest.approx(2.0, abs=0.4)
    cx, cy = 21.0, -1.0
    src_top = top_h(case['src'], [[cx, cy + 2.0]])[0]
    new_top = top_h(case['out'], [[cx, cy + 2.0]])[0]
    assert src_top - new_top > 4.0                                                            # 3 mm bump + about 2 mm pocket below the rim
    assert r['files']['regions'].get('wheel', {'faces': 0})['faces'] < 0.05 * len(case['lab']['wheel'])     # the wheel faces are cut away


# ------------------------------------------------------------------ no encroachment, watertight
def test_perimeter_slot_never_encroaches_on_the_panel_edge(case):
    r = case['res']
    enc = r['fit']['perimeter']['encroachment']
    # G1.4: the label outline is a hint. Wide encroachment is cleared in full (robust depth after <= 0); only narrow spikes (< spike_width_mm,
    # here the sharp label corners that the regular filleted outline rounds) may stay inside, and by at most overhang_mm (deeper runs are label overhang, reported and gated)
    assert enc['inside_after_robust_mm'] <= 0.0 and enc['shift_outward_mm'] >= 0.005
    assert enc['max_inside_after_mm'] <= r['params_used']['overhang_mm']
    # independent: the panel surface just inside the click outline is untouched; the slot lies outside
    src, out = case['src'], case['out']
    ys = np.arange(4.0, 12.0, 0.5)
    inside = np.c_[np.full_like(ys, AREA[0] + 0.03), ys]
    assert np.abs(top_h(src, inside) - top_h(out, inside)).max() < 1e-3
    outside = np.c_[np.full_like(ys, AREA[0] - 0.25), ys]
    assert (top_h(src, outside) - top_h(out, outside)).min() > 1.6
    lat = np.c_[np.arange(5.0, 12.0, 0.5), np.full(14, AREA[3] - 0.03)]
    assert np.abs(top_h(src, lat) - top_h(out, lat)).max() < 1e-3
    lat_out = np.c_[np.arange(5.0, 12.0, 0.5), np.full(14, AREA[3] + 0.25)]
    assert (top_h(src, lat_out) - top_h(out, lat_out)).min() > 1.6


def test_result_is_one_watertight_body_and_region_files_exist(case):
    m = case['res']['metrics']
    assert m['watertight'] == {'before': True, 'after': True}
    assert m['bodies']['components'] == 1 and m['bodies']['winding_consistent']
    assert case['out'].is_watertight and case['out'].volume > 0
    assert m['volume']['removed_mm3'] > 50 and m['volume']['after_mm3'] < m['volume']['before_mm3']
    assert not m['cleanup']['splinters_removed'] or all(s['faces'] < 50 for s in m['cleanup']['splinters_removed'])
    regions = case['res']['files']['regions']
    assert {'left_click', 'right_click', 'top_shell', 'bottom_plate'} <= set(regions)
    for v in regions.values():
        assert (case['folder'] / 'out' / v['file']).is_file()
    assert case['res']['metrics']['cut_through']['perimeter']['cut_through_runs'] == []      # thick body: nothing cut through


# ------------------------------------------------------------------ cut-through reporting and the min-wall option
def test_cut_through_is_reported_where_the_wall_is_thin(tmp_path):
    write_case(tmp_path, thin_rear=True)
    r = W.run(request(tmp_path))
    runs = r['metrics']['cut_through']['perimeter']['cut_through_runs']
    assert runs and min(min(x['x_range']) for x in runs) < 4.0 and max(max(x['x_range']) for x in runs) < 5.0     # only the thin rear band
    assert any(w['code'] == 'CUT_THROUGH' for w in r['warnings'])
    assert r['metrics']['watertight']['after'] and r['metrics']['bodies']['components'] == 1
    assert r['metrics']['cut_through']['perimeter']['material_below_floor_min_mm'] is not None


def test_min_wall_option_raises_the_floor_instead_of_cutting_through(tmp_path):
    write_case(tmp_path, thin_rear=True)
    r = W.run(request(tmp_path, min_wall_mm=0.8))
    runs = r['metrics']['cut_through']['perimeter']['cut_through_runs']
    assert all(max(x['x_range']) - min(x['x_range']) < 0.5 for x in runs)       # at most the sliver at the bottom step edge, no thin-band run
    assert r['metrics']['cut_through']['perimeter']['depth_below_surface']['min'] < 1.5          # shallower where the wall is thin
    assert r['metrics']['cut_through']['perimeter']['depth_below_surface']['p50'] == pytest.approx(2.0, abs=0.2)


# ------------------------------------------------------------------ errors
def test_missing_kernel_library_is_a_clear_error(tmp_path, monkeypatch):
    write_case(tmp_path)
    monkeypatch.setitem(sys.modules, 'manifold3d', None)
    with pytest.raises(W.GrooveError) as exc:
        W.run(request(tmp_path))
    assert exc.value.code == 'CLICK_GROOVE_KERNEL_UNAVAILABLE' and 'manifold3d' in exc.value.message
    (tmp_path / 'req.json').write_text(json.dumps(request(tmp_path)))
    code = W.main(['w', str(tmp_path / 'req.json')])
    assert code == 2


def test_missing_regions_and_bad_labels(tmp_path):
    write_case(tmp_path)
    lab = json.loads((tmp_path / 'labels.json').read_text())
    del lab['regions']['right_click']
    (tmp_path / 'labels.json').write_text(json.dumps(lab))
    with pytest.raises(W.GrooveError) as exc:
        W.run(request(tmp_path))
    assert exc.value.code == 'CLICK_GROOVE_REGIONS_MISSING'
    lab['regions']['right_click'] = {'face_ids': [10 ** 9] * 30}
    (tmp_path / 'labels.json').write_text(json.dumps(lab))
    with pytest.raises(W.GrooveError) as exc:
        W.run(request(tmp_path))
    assert exc.value.code == 'CLICK_GROOVE_LABELS'


def test_not_watertight_input_is_refused(tmp_path):
    m, lab = write_case(tmp_path)
    open_mesh = trimesh.Trimesh(m.vertices, m.faces[:-3], process=False)
    open_mesh.export(tmp_path / 'dome.stl')
    with pytest.raises(W.GrooveError) as exc:
        W.run(request(tmp_path))
    assert exc.value.code == 'CLICK_GROOVE_MESH_NOT_WATERTIGHT'


def test_label_aliases_and_npz_labels(tmp_path):
    m, lab = write_case(tmp_path)
    codes = {'LC': 1, 'RC': 2, 'WH': 3, 'top_shell': 4}
    fl = np.zeros(len(m.faces), np.int64)
    for k, c in (('left_click', 1), ('right_click', 2), ('wheel', 3), ('top_shell', 4)):
        fl[lab[k]] = c
    np.savez(tmp_path / 'labels.npz', face_labels=fl, codes=np.array([f'{k}={v}' for k, v in codes.items()]))
    roles = W.read_labels(tmp_path / 'labels.npz', len(m.faces))
    assert set(roles) == {'left_click', 'right_click', 'wheel', 'top_shell'} and len(roles['wheel']) == len(lab['wheel'])
    (tmp_path / 'short.json').write_text(json.dumps({'LC': lab['left_click'], 'RC': lab['right_click']}))
    assert set(W.read_labels(tmp_path / 'short.json', len(m.faces))) == {'left_click', 'right_click'}


def test_without_wheel_label_the_window_is_skipped_and_the_gap_runs_through(tmp_path):
    write_case(tmp_path)
    lab = json.loads((tmp_path / 'labels.json').read_text())
    lab['regions']['top_shell'] = {'face_ids': lab['regions']['top_shell']['face_ids'] + lab['regions'].pop('wheel')['face_ids']}
    (tmp_path / 'labels.json').write_text(json.dumps(lab))
    r = W.run(request(tmp_path))
    assert r['fit']['window'] is None and {'gap_left_click', 'gap_right_click'} <= set(r['metrics']['slot_measure'])
    assert r['metrics']['bodies']['components'] == 1


# ------------------------------------------------------------------ raster / ray helpers
def test_height_field_and_vertical_hits_agree_with_the_surface(case):
    V, F = np.asarray(case['src'].vertices), np.asarray(case['src'].faces)
    xs, ys, Z = W.raster_top(V, F, 2.0, 12.0, -6.0, 6.0, 0.1)
    assert np.isfinite(Z).all()
    X, Y = np.meshgrid(xs, ys)
    assert np.abs(Z - dome_height(X, Y)).max() < 0.1                                           # triangulated dome vs the formula
    h = W.VerticalHits(V, F).hits(np.array([[8.3, 1.1]]))[0]
    assert len(h) == 2 and h[-1] == pytest.approx(dome_height(8.3, 1.1), abs=0.1) and h[0] == pytest.approx(dome_height(8.3, 1.1) - 6.0, abs=0.1)


# ------------------------------------------------------------------ tool plumbing
def test_tool_validates_before_running(tmp_path):
    (tmp_path / 'a.stl').write_text('x')
    (tmp_path / 'l.json').write_text('{}')
    rejects('SCAN_UNIT', lambda: scg.scan_click_grooves(tmp_path, 'a.stl', 'l.json', 'furlong'))
    rejects('CLICK_GROOVE_SETTINGS', lambda: scg.scan_click_grooves(tmp_path, 'a.stl', 'l.json', 'mm', slot_width_mm=0.0))
    rejects('CLICK_GROOVE_SETTINGS', lambda: scg.scan_click_grooves(tmp_path, 'a.stl', 'l.json', 'mm', slot_depth_mm=50))
    rejects('CLICK_GROOVE_SETTINGS', lambda: scg.scan_click_grooves(tmp_path, 'a.stl', 'l.json', 'mm', fillet_radius_mm=0.01))
    (tmp_path / 'a.ply').write_text('x')
    rejects('SCAN_FILE', lambda: scg.scan_click_grooves(tmp_path, 'a.ply', 'l.json', 'mm'))
    rejects('UNSAFE_PATH', lambda: scg.scan_click_grooves(tmp_path, 'nope.stl', 'l.json', 'mm'))
    rejects('UNSAFE_PATH', lambda: scg.scan_click_grooves(tmp_path, '../a.stl', 'l.json', 'mm'))
    (tmp_path / 'l.txt').write_text('x')
    rejects('CLICK_GROOVE_LABELS', lambda: scg.scan_click_grooves(tmp_path, 'a.stl', 'l.txt', 'mm'))
    t = Tools(Brain(tmp_path))
    names = {x['name']: x for x in t.list()}
    assert 'brain_mouse_scan_click_grooves' in names and names['brain_mouse_scan_click_grooves']['annotations']['readOnlyHint'] is False
    props = names['brain_mouse_scan_click_grooves']['inputSchema']['properties']
    assert props['slot_width_mm']['default'] == 0.5 and props['slot_depth_mm']['default'] == 2.0
    rejects('SCAN_UNIT', lambda: t.call('brain_mouse_scan_click_grooves', {'relative_path': 'a.stl', 'labels_path': 'l.json', 'unit': 'x'}))


def test_tool_end_to_end_in_the_scan_python(tmp_path, monkeypatch):
    try:
        python = smod.find_scan_python(Path('.'))
    except BrainError:
        pytest.skip('no scan python (CADMCP_SCAN_PYTHON / .venv-scan)')
    monkeypatch.setenv(smod.ENV_PYTHON, str(python))
    write_case(tmp_path / 'in')
    t = Tools(Brain(tmp_path))
    args = {'relative_path': 'in/dome.stl', 'labels_path': 'in/labels.json', 'unit': 'mm', 'overlay': True}
    r = t.call('brain_mouse_scan_click_grooves', args)
    assert r['status'] == 'READY' and r['checks']['watertight_after'] == 'PASS' and r['checks']['single_body'] == 'PASS'
    assert r['metrics']['slot_measure']['perimeter']['width_mm_p5_50_95'][1] == pytest.approx(0.5, abs=0.03)
    folder = tmp_path / 'mouse' / 'scans' / r['groove_id']
    for item in (r['outputs']['combined'], *r['outputs']['regions'].values(), r['outputs']['overlay']):
        assert (tmp_path / item['relative_path']).is_file() and len(item['sha256']) == 64
    assert (folder / scg.REPORT).is_file() and not list((tmp_path / 'mouse' / 'scans').glob('*.tmp-*'))
    again = t.call('brain_mouse_scan_click_grooves', args)
    assert again['cached'] is True and again['groove_id'] == r['groove_id']
    (folder / 'combined_grooved.stl').write_bytes(b'changed')
    rejects('CLICK_GROOVE_OUTPUT_CHANGED', lambda: t.call('brain_mouse_scan_click_grooves', args))
    lab = json.loads((tmp_path / 'in' / 'labels.json').read_text())
    del lab['regions']['left_click']
    (tmp_path / 'in' / 'bad.json').write_text(json.dumps(lab))
    rejects('CLICK_GROOVE_REGIONS_MISSING', lambda: t.call('brain_mouse_scan_click_grooves', {**args, 'labels_path': 'in/bad.json'}))


# ------------------------------------------------------------------ G1.4 regular outline, symmetry, window on the gap line, gates
def test_outline_roughness_measures_waves_and_kinks():
    clean = W.fillet_open(np.array([[38.0, -12.0], [2.0, -12.0], [2.0, 12.0], [38.0, 12.0]]), 2.0)
    rc = W.outline_roughness(clean)
    assert rc['curvature_sign_changes'] == 0 and rc['smooth_dev_max_mm'] < 0.005
    yy = np.linspace(-10, 10, 400)
    wavy = np.vstack([np.c_[np.linspace(38, 2, 200), np.full(200, -12.0)], np.c_[2.0 + 0.3 * np.sin(yy), yy], np.c_[np.linspace(2, 38, 200), np.full(200, 12.0)]])
    rw = W.outline_roughness(wavy)
    assert rw['curvature_sign_changes'] >= 4


def test_regular_fit_merges_noise_kinks_and_keeps_real_corners():
    rng = np.random.default_rng(3)
    t = np.linspace(0, 1, 400)
    chain = np.vstack([np.c_[30 - 28 * t, np.full(400, -10.0)], np.c_[np.full(400, 2.0), -10 + 20 * t], np.c_[2 + 28 * t, np.full(400, 10.0)]])
    chain = chain + rng.normal(0, 0.06, chain.shape)
    chain[450:520, 0] -= 0.35                                                  # a step on the rear edge
    fit = W.fit_lines_regular(chain, 0.1, min_turn_deg=W.DEFAULTS['min_turn_deg'], merge_dev_mm=W.DEFAULTS['merge_dev_mm'])
    assert len(fit['lines']) == 3 and fit['opposite_turns_kept'] == 0                 # three sides, the step and the noise merged away


def test_noisy_symmetric_outline_is_regular_mirrored_and_window_on_gap(tmp_path):
    write_case(tmp_path, gap_y=0.0, window=(15.0, 27.0, -4.0, 4.0), noisy=True)
    res = W.run(request(tmp_path))
    q = res['metrics']['outline_quality']
    assert q['perimeter']['ok'] and q['perimeter']['curvature_sign_changes'] == 0, q['perimeter']
    assert q['perimeter_symmetry']['mode'].startswith('mirrored'), q['perimeter_symmetry']
    lay = json.loads((tmp_path / 'out' / 'slot_layout.json').read_text(encoding='utf-8'))
    P = np.asarray(lay['perimeter']['points'])
    m_, b_ = res['fit']['gap_mid_line']['slope'], res['fit']['gap_mid_line']['intercept_y']
    assert abs(m_) < 0.02 and abs(b_) < 0.2
    mir = np.c_[P[:, 0], 2 * (m_ * P[:, 0] + b_) - P[:, 1]]
    assert W.seg_dist(mir, P).max() < 0.02                                             # exactly symmetric about the gap line (small slope)
    assert q['window_gap']['ok'] and abs(q['window_gap']['centre_offset_mm']) < 1e-3
    ovh = res['fit']['perimeter']['encroachment']['label_overhang']
    assert ovh['runs'] and 0.5 < ovh['max_mm'] <= 1.5                                 # the 1 mm label overhang is reported, not followed
    assert scg.gate_blockers(res['metrics'], res['params_used']) == []


def test_rough_outline_or_offset_window_is_not_ready(case):
    import copy
    m = copy.deepcopy(case['res']['metrics'])
    m['outline_quality']['perimeter']['ok'] = False
    m['outline_quality']['window_gap'] = {'ok': False}
    b = scg.gate_blockers(m, case['res']['params_used'])
    assert 'PERIMETER_OUTLINE_ROUGH' in b and 'WINDOW_OFF_GAP_LINE' in b
    m2 = copy.deepcopy(case['res']['metrics'])
    m2['encroachment']['label_overhang'] = {'max_mm': 3.0, 'total_length_mm': 2.0}
    assert 'PANEL_LABEL_OVERHANG_TOO_LARGE' in scg.gate_blockers(m2, case['res']['params_used'])
    assert scg.gate_blockers(case['res']['metrics'], case['res']['params_used']) == []


def test_window_radius_rule_covers_the_wheel_and_sharp_window_is_not_ready(tmp_path):
    """G1.5: without a drawn label notch the corner radius is window_corner_frac x half the short side (near obround) and the sides grow
    until the wheel + clearance is inside; a sharp window (override below window_min_corner_radius_mm) is gated."""
    from shapely.geometry import Polygon
    write_case(tmp_path)
    r = W.run(request(tmp_path, window_source='rim'))
    win = r['fit']['window']
    L_, H_ = win['dims_mm']['width_x'], win['dims_mm']['height_y']
    assert win['corner_radius_mm'] == pytest.approx(0.8 * 0.5 * min(L_, H_), abs=1e-6) and win['corner_radius_mm'] > 3.0
    wpoly = Polygon(W.fillet_closed(np.asarray(win['corners_TR_TL_BL_BR'], float), win['corner_radius_mm']))
    assert wpoly.buffer(1e-6).contains(Polygon(win['rim_detection']['wheel_hull_xy']).buffer(0.48, 8))
    assert r['metrics']['outline_quality']['window_shape']['ok'] and scg.gate_blockers(r['metrics'], r['params_used']) == []
    json.dumps(r, allow_nan=False, default=W._json_default)                                     # the worker result is strict JSON
    sharp = W.run(request(tmp_path, window_corner_radius_mm=0.5))
    assert sharp['fit']['window']['corner_radius_mm'] == 0.5
    assert 'WINDOW_SHAPE_IRREGULAR' in scg.gate_blockers(sharp['metrics'], sharp['params_used'])


def test_mirrored_mesh_gives_the_mirrored_layout(tmp_path):
    """Genericity (left-/right-handed scans): the same mouse mirrored about y = 0 (labels swapped with it) gives the mirrored perimeter,
    gap and window; the branch that is mirrored is chosen by geometry, not by side."""
    def run(folder, flip):
        V, F, lab = make_dome(gap_y=0.0, window=(15.0, 27.0, -4.0, 4.0), noisy=True)
        if flip:
            V = V * [1.0, -1.0, 1.0]
            F = F[:, ::-1]
            lab = {**lab, 'left_click': lab['right_click'], 'right_click': lab['left_click']}
        folder.mkdir(parents=True, exist_ok=True)
        trimesh.Trimesh(V, F, process=False).export(folder / 'dome.stl')
        (folder / 'labels.json').write_text(json.dumps({'regions': {k: {'face_ids': v} for k, v in lab.items()}}), encoding='utf-8')
        res = W.run(request(folder))
        return res, np.asarray(json.loads((folder / 'out' / 'slot_layout.json').read_text(encoding='utf-8'))['perimeter']['points'])
    a, Pa = run(tmp_path / 'a', False)
    b, Pb = run(tmp_path / 'b', True)
    assert W.seg_dist(Pb * [1.0, -1.0], Pa).max() < 0.05
    wa, wb = a['fit']['window'], b['fit']['window']
    assert wa['corner_radius_mm'] == pytest.approx(wb['corner_radius_mm'], abs=1e-6)
    assert wa['dims_mm']['width_x'] == pytest.approx(wb['dims_mm']['width_x'], abs=0.05) and wa['dims_mm']['height_y'] == pytest.approx(wb['dims_mm']['height_y'], abs=0.05)
    assert scg.gate_blockers(a['metrics'], a['params_used']) == scg.gate_blockers(b['metrics'], b['params_used']) == []
