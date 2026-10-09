"""brain_mouse_scan_clean: groove re-synthesis and zone repair. Synthetic closed slab with a straight groove and a loop; a gated real-scan regression."""
from __future__ import annotations
import json
import sys
from pathlib import Path
import numpy as np
import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import scan_clean as sc
from cadmcp_brain.studio import scan_clean_seeds as seeds_mod
from cadmcp_brain.studio import scan_clean_worker as W
from cadmcp_brain.studio import scan_model as smod
from cadmcp_brain.studio import scan_shell as sh

REAL_PLY = Path('V:/mouse/LH2-mouse/work/scan_clean/pymeshlab/mouse_clean_fullres.ply')
STEP = 0.25
LINE_Y, DEPTH_LINE, RING_C, RING_R, DEPTH_RING = -8.0, 0.25, (8.0, 6.0), 5.0, 0.30
HW_TOP, HW_FLOOR = 0.70, 0.20


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code
    return exc.value


def trapezoid(d, depth):
    return depth * np.clip((HW_TOP - np.abs(d)) / (HW_TOP - HW_FLOOR), 0, 1)


def slab(noise: float = 0.004, bump: bool = False, seed: int = 2):
    """Closed slab 60 x 40 x 8 mm: top surface is a gentle dome with a straight groove along x (y = LINE_Y) and a circular groove ring."""
    xs = np.arange(-30, 30 + 1e-9, STEP)
    ys = np.arange(-20, 20 + 1e-9, STEP)
    nx, ny = len(xs), len(ys)
    X, Y = np.meshgrid(xs, ys, indexing='ij')
    z = 0.0015 * X ** 2 + 0.001 * Y ** 2
    z = z - trapezoid(Y - LINE_Y, DEPTH_LINE)
    rr = np.hypot(X - RING_C[0], Y - RING_C[1])
    z = z - trapezoid(rr - RING_R, DEPTH_RING)
    rng = np.random.default_rng(seed)
    z = z + rng.normal(0, noise, z.shape)
    if bump:
        m = (np.abs(X + 18) < 3) & (np.abs(Y - 8) < 3)
        z = z + m * rng.normal(0, 0.08, z.shape)
    top = np.stack([X, Y, z], -1).reshape(-1, 3)
    bot = top.copy()
    bot[:, 2] = -8.0
    v = np.vstack([top, bot])
    idx = np.arange(nx * ny).reshape(nx, ny)
    a, b, c, d = idx[:-1, :-1], idx[1:, :-1], idx[1:, 1:], idx[:-1, 1:]
    quads = np.stack([a, b, c, d], -1).reshape(-1, 4)
    ft = np.vstack([quads[:, [0, 1, 2]], quads[:, [0, 2, 3]]])
    fb = ft[:, ::-1] + nx * ny
    ring = np.r_[idx[:-1, 0], idx[-1, :-1], idx[::-1, -1][:-1], idx[0, ::-1][:-1]]
    ring = np.r_[idx[:, 0][:-1], idx[-1, :][:-1], idx[:, -1][::-1][:-1], idx[0, :][::-1][:-1]]
    nxt = np.roll(ring, -1)
    fs = np.vstack([np.stack([ring, ring + nx * ny, nxt + nx * ny], 1), np.stack([ring, nxt + nx * ny, nxt], 1)])
    f = np.vstack([ft, fb, fs]).astype(np.int64)
    t = W.topology(v, f)
    if t['signed_volume_mm3'] < 0:
        f = f[:, [0, 2, 1]]
    return v, f


def write_stl(path: Path, v: np.ndarray, f: np.ndarray) -> None:
    W.write_stl(path, v, f)


@pytest.fixture
def scan_python():
    try:
        return smod.find_scan_python(Path('.'))
    except BrainError:
        pytest.skip('no scan python (CADMCP_SCAN_PYTHON / .venv-scan)')


def seed_line(offset: float = 0.3):
    x = np.arange(-24, 24.01, 1.0)
    return {'name': 'line', 'points': np.stack([x, np.full_like(x, LINE_Y + offset), 0.0015 * x ** 2 + 0.001 * (LINE_Y + offset) ** 2], 1).round(3).tolist(), 'closed': False}


def seed_ring(offset: float = 0.25):
    a = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    r = RING_R + offset
    x, y = RING_C[0] + r * np.cos(a), RING_C[1] + r * np.sin(a)
    return {'name': 'ring', 'points': np.stack([x, y, 0.0015 * x ** 2 + 0.001 * y ** 2], 1).round(3).tolist(), 'closed': True}


# ------------------------------------------------------------------ pure numpy pieces
def test_synthetic_slab_is_closed():
    v, f = slab()
    t = W.topology(v, f)
    assert t['watertight'] and t['manifold'] and t['winding_consistent'] and t['components'] == 1 and t['signed_volume_mm3'] > 0


def test_profile_fit_recovers_a_trapezoid():
    rng = np.random.default_rng(1)
    u = rng.uniform(-3, 3, 4000)
    h = 0.002 * u - trapezoid(u - 0.1, 0.25) + rng.normal(0, 0.004, len(u))
    th, rms = W.fit_profile2(u, h)
    assert rms < 0.01
    assert abs(W.depth_of(th) - 0.25) < 0.03
    w50 = float(W.widths(th[None, :5])[0])
    assert abs(w50 - 0.95) < 0.15           # half-depth width of the trapezoid: (HW_TOP + HW_FLOOR)


def test_segmentation_finds_a_step():
    Y = np.r_[np.full((20, 1), 1.0), np.full((20, 1), 3.0)] + np.random.default_rng(0).normal(0, 0.02, (40, 1))
    seg = W.segment_dp(Y, 5.0, minlen=4)
    assert len(seg) == 2 and seg[0][1] == 20


def test_subdivision_keeps_the_mesh_closed_and_inside_the_original_surface():
    v, f = slab()
    sel = np.zeros(len(f), bool)
    cen = v[f].mean(1)
    sel[(np.abs(cen[:, 1] - LINE_Y) < 1.0) & (np.abs(cen[:, 0]) < 10) & (cen[:, 2] > -1)] = True
    v2, f2, s2 = W.subdivide_sel(v, f, sel, 2)
    t = W.topology(v2, f2)
    assert t['watertight'] and t['manifold'] and t['winding_consistent'] and len(f2) > len(f)
    assert abs(t['signed_volume_mm3'] - W.topology(v, f)['signed_volume_mm3']) < 1e-6 * abs(t['signed_volume_mm3'])


def test_seeds_from_region_labels():
    v, f = slab()
    cen = v[f].mean(1)
    n, _ = W.fnormals(v, f)
    top = n[:, 2] > 0.5
    lab = np.zeros(len(f), np.int64)
    lab[top & (cen[:, 0] < 0)] = 1
    lab[top & (cen[:, 0] >= 0)] = 2
    ring = top & (np.hypot(cen[:, 0] - 14, cen[:, 1] - 8) < 4)
    lab[ring] = 4
    lab[top & (cen[:, 1] > 17)] = 6
    seeds = seeds_mod.seeds_from_regions(v, f, lab)
    names = {s['name']: s for s in seeds}
    gap = [s for s in seeds if s['name'].startswith('gap')]
    assert gap and abs(np.linalg.norm(np.diff(np.array(gap[0]['points']), axis=0), axis=1).sum() - 37.0) < 3.0      # the x = 0 line from y = -20 to the palm at y = 17
    pad = names['pad1_loop']
    assert pad['closed'] and pad['kind'] == 'loop'
    p = np.array(pad['points'])
    assert abs(np.hypot(p[:, 0] - 14, p[:, 1] - 8).mean() - 4.0) < 0.3


def test_zone_repair_flattens_a_bump_and_respects_the_cap():
    v, f = slab(bump=True)
    zone = np.flatnonzero((np.abs(v[:, 0] + 18) < 3.2) & (np.abs(v[:, 1] - 8) < 3.2) & (v[:, 2] > -1))
    cap = 0.2
    vn, info = W.zone_repair(v, f, zone, cap)
    d = np.linalg.norm(vn - v, axis=1)
    assert d.max() <= cap + 1e-9 and info['projected'] > 0
    assert (d[np.setdiff1d(np.arange(len(v)), zone)] == 0).all()
    inner = zone[(np.abs(v[zone, 0] + 18) < 2.5) & (np.abs(v[zone, 1] - 8) < 2.5)]
    truth = 0.0015 * v[inner, 0] ** 2 + 0.001 * v[inner, 1] ** 2
    assert np.sqrt(np.mean((vn[inner, 2] - truth) ** 2)) < np.sqrt(np.mean((v[inner, 2] - truth) ** 2))
    assert W.topology(vn, f)['watertight']


def test_pymeshlab_is_never_imported_in_the_server_process():
    src = ''.join(Path(m.__file__).read_text(encoding='utf-8') for m in (sc, seeds_mod))
    assert 'import pymeshlab' not in src
    assert 'pymeshlab' not in sys.modules


# ------------------------------------------------------------------ validation before anything runs
def test_validation_and_stop_codes(tmp_path):
    v, f = slab(noise=0.0)
    (tmp_path / 'in').mkdir()
    write_stl(tmp_path / 'in' / 's.stl', v, f)
    rejects('SCAN_CLEAN_SETTINGS', lambda: sc.scan_clean(tmp_path, relative_path='in/s.stl', unit='mm', mode='fill'))
    rejects('SCAN_CLEAN_SETTINGS', lambda: sc.scan_clean(tmp_path, relative_path='in/s.stl', unit='mm', outside_tolerance_mm=0))
    rejects('SCAN_CLEAN_SETTINGS', lambda: sc.scan_clean(tmp_path, relative_path='in/s.stl', unit='mm', max_zone_deviation_mm=9))
    rejects('SCAN_CLEAN_INPUT', lambda: sc.scan_clean(tmp_path))
    rejects('SCAN_CLEAN_INPUT', lambda: sc.scan_clean(tmp_path, scan_id='scan_000000000000', relative_path='in/s.stl', unit='mm'))
    rejects('SCAN_UNIT', lambda: sc.scan_clean(tmp_path, relative_path='in/s.stl'))
    rejects('SCAN_CLEAN_ZONES', lambda: sc.scan_clean(tmp_path, relative_path='in/s.stl', unit='mm', mode='zones'))
    rejects('SCAN_CLEAN_SETTINGS', lambda: sc.scan_clean(tmp_path, relative_path='in/s.stl', unit='mm', mode='zones', zones=[{'name': 'z', 'box': {'min': [0, 0, 0], 'max': [1, 1, 1]}}], grooves=[seed_line()]))
    rejects('SCAN_CLEAN_GROOVES', lambda: sc.scan_clean(tmp_path, relative_path='in/s.stl', unit='mm', grooves=[{'name': 'x', 'points': [[0, 0, 0]] * 3}]))
    rejects('SCAN_CLEAN_GROOVES', lambda: sc.scan_clean(tmp_path, relative_path='in/s.stl', unit='mm', grooves=[{**seed_line(), 'points': [[900, 0, 0]] * 9}]))
    rejects('SCAN_CLEAN_ZONES', lambda: sc.scan_clean(tmp_path, relative_path='in/s.stl', unit='mm', mode='zones', zones=[{'name': 'z', 'box': {'min': [1, 1, 1], 'max': [0, 0, 0]}}]))
    rejects('SCAN_NOT_FOUND', lambda: sc.scan_clean(tmp_path, scan_id='model_000000000000'))
    rejects('SCAN_NOT_FOUND', lambda: sc.scan_clean(tmp_path, scan_id='scan_000000000000'))
    rejects('SCAN_CLEAN_INPUT', lambda: sc.scan_clean(tmp_path, scan_id='bogus'))


def test_tool_is_registered(tmp_path):
    t = Tools(Brain(tmp_path))
    names = {x['name'] for x in t.list()}
    assert 'brain_mouse_scan_clean' in names
    rejects('SCAN_CLEAN_INPUT', lambda: t.call('brain_mouse_scan_clean', {}))


# ------------------------------------------------------------------ subprocess worker end to end (synthetic slab)
def test_scan_clean_grooves_end_to_end(tmp_path, scan_python, monkeypatch):
    monkeypatch.setenv(smod.ENV_PYTHON, str(scan_python))
    v, f = slab()
    (tmp_path / 'in').mkdir()
    write_stl(tmp_path / 'in' / 's.stl', v, f)
    before = (tmp_path / 'in' / 's.stl').read_bytes()
    r = sc.scan_clean(tmp_path, relative_path='in/s.stl', unit='mm', grooves=[seed_line(), seed_ring()])
    assert r['status'] == 'READY', r['blocking_reasons']
    c = r['checks']
    assert c['watertight'] == c['manifold'] == c['winding_consistent'] == c['single_component'] == 'PASS'
    assert c['outside_zone_deviation'] == 'PASS' and r['deviation']['outside_zone']['max'] <= 0.05
    gl = r['edits']['line']
    assert gl['type'] == 'open curve' and abs(gl['depth_mm_range'][1] - DEPTH_LINE) < 0.06 and gl['deviation_cleaned_to_original_mm']['max'] < 0.15
    assert r['edits']['ring']['type'] == 'closed loop' and abs(r['edits']['ring']['depth_mm_range'][1] - DEPTH_RING) < 0.08
    rl = r['roughness']['line']
    assert rl['b3_median_deg_cleaned'] <= rl['b3_median_deg_original'] + 0.5
    assert r['edit']['faces_after'] > r['edit']['faces_before']
    assert r['limits'] and r['self_intersection']['checker']
    folder = tmp_path / 'mouse' / 'scans' / r['clean_id']
    for k in ('stl', 'ply', 'groove_params'):
        assert (folder / Path(r['files'][k]['relative_path']).name).is_file()
    params = json.loads((folder / 'groove_params.json').read_text(encoding='utf-8'))
    g = params['grooves']['line']
    assert params['units'] == 'mm' and g['centerline_bspline']['control_points_mm'] and g['segments_constant_profile']
    cp = np.array(g['centerline_bspline']['control_points_mm'])
    assert abs(np.median(cp[:, 1]) - LINE_Y) < 0.1                    # the centre line was re-centred from the 0.3 mm off seed onto the groove
    assert (tmp_path / 'in' / 's.stl').read_bytes() == before        # source never modified
    p = sh.prepare_scan(tmp_path, r['files']['stl']['relative_path'], 'mm')
    assert p['prepared_status'] == 'READY'                            # the output feeds the intake gate
    again = sc.scan_clean(tmp_path, relative_path='in/s.stl', unit='mm', grooves=[seed_line(), seed_ring()])
    assert again['cached'] is True and again['clean_id'] == r['clean_id']
    (folder / 'cleaned.stl').write_bytes(b'tampered')
    rejects('SCAN_CLEAN_OUTPUT_CHANGED', lambda: sc.scan_clean(tmp_path, relative_path='in/s.stl', unit='mm', grooves=[seed_line(), seed_ring()]))


def test_scan_clean_stops_when_no_groove_is_there(tmp_path, scan_python, monkeypatch):
    monkeypatch.setenv(smod.ENV_PYTHON, str(scan_python))
    v, f = slab()
    (tmp_path / 'in').mkdir()
    write_stl(tmp_path / 'in' / 's.stl', v, f)
    x = np.arange(-24, 24.01, 1.0)
    flat = {'name': 'flat', 'closed': False, 'points': np.stack([x, np.full_like(x, -16.0), 0.0015 * x ** 2 + 0.001 * 256], 1).round(3).tolist()}
    e = rejects('SCAN_CLEAN_NOTHING_EDITED', lambda: sc.scan_clean(tmp_path, relative_path='in/s.stl', unit='mm', grooves=[flat]))
    assert e.details['not_found']
    assert not list((tmp_path / 'mouse' / 'scans').glob('clean_*'))      # nothing written


def test_scan_clean_zones_end_to_end(tmp_path, scan_python, monkeypatch):
    monkeypatch.setenv(smod.ENV_PYTHON, str(scan_python))
    v, f = slab(bump=True)
    (tmp_path / 'in').mkdir()
    write_stl(tmp_path / 'in' / 's.stl', v, f)
    zone = {'name': 'bump', 'box': {'min': [-21.2, 4.8, -1.0], 'max': [-14.8, 11.2, 5.0]}}
    r = sc.scan_clean(tmp_path, relative_path='in/s.stl', unit='mm', mode='zones', zones=[zone], max_zone_deviation_mm=0.5)
    assert r['status'] == 'READY', r['blocking_reasons']
    assert r['checks']['zone_deviation_cap'] == 'PASS' and r['edit']['max_displacement_mm'] <= 0.5 + 1e-9
    assert r['checks']['watertight'] == 'PASS' and r['edit']['faces_after'] == r['edit']['faces_before']
    rz = r['roughness']['zones']
    assert rz['b3_median_deg_cleaned'] < rz['b3_median_deg_original']
    assert r['deviation']['outside_zone']['max'] <= 0.05


# ------------------------------------------------------------------ real scan (gated; several minutes)
@pytest.mark.skipif(not REAL_PLY.is_file(), reason='real LH2 scan not available')
def test_real_scan_click_gap_and_rear_cross(tmp_path, scan_python, monkeypatch):
    """Acceptance on the real scan (mm): click gap deviation 0.023 / 0.083 / 0.167 (mean / p95 / max) in the validated trial, rear cross 0.015 / 0.050 / 0.136,
    outside the zone <= 0.010 mm, watertight and manifold, click-gap roughness 5.1 -> 1.2 degrees. The assertions leave a margin for the auto-detected seeds."""
    monkeypatch.setenv(smod.ENV_PYTHON, str(scan_python))
    (tmp_path / 'in').mkdir()
    (tmp_path / 'in' / 'scan.ply').write_bytes(REAL_PLY.read_bytes())
    m = smod.scan_model(tmp_path, 'in/scan.ply', 'mm')
    r = sc.scan_clean(tmp_path, scan_id=m['model_id'])
    assert r['status'] == 'READY', r['blocking_reasons']
    assert r['checks']['watertight'] == 'PASS' and r['checks']['manifold'] == 'PASS'
    assert r['deviation']['outside_zone']['max'] <= 0.010
    gap = next(v for k, v in r['edits'].items() if k.startswith('gap'))
    dev = gap['deviation_cleaned_to_original_mm']
    assert dev['mean'] < 0.04 and dev['p95'] < 0.12 and dev['max'] < 0.25
    rough = next(v for k, v in r['roughness'].items() if k.startswith('gap'))
    assert rough['b3_median_deg_original'] > 4.0 and rough['b3_median_deg_cleaned'] < 1.8
    rim = next(v for k, v in r['edits'].items() if k.startswith('rim'))
    assert rim['deviation_cleaned_to_original_mm']['max'] < 0.25
