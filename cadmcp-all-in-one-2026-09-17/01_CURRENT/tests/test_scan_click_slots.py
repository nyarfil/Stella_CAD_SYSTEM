"""brain_mouse_click_slots: synthetic half-ellipsoid shell solid and hand-written click_slot_layout/1 layouts (no scan data).
Slots and window are cut, the result is one valid solid, measured widths match the spec, symmetry is applied only where near-symmetric."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import scan_click_slots as cs

pytest.importorskip('OCP')
from cadmcp_brain.studio import cad_brep_lib as L  # noqa: E402

MIRROR = {'normal': [0.0, 1.0, 0.0], 'd': 0.0}


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code
    return exc.value


def make_shell(path: Path):
    """Half ellipsoid 120 x 64 x 30 (z >= 0), closed solid."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepBuilderAPI import BRepBuilderAPI_GTransform
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeSphere
    from OCP.gp import gp_GTrsf, gp_Mat, gp_Pnt
    g = gp_GTrsf()
    g.SetVectorialPart(gp_Mat(60, 0, 0, 0, 32, 0, 0, 0, 30))
    ell = BRepBuilderAPI_GTransform(BRepPrimAPI_MakeSphere(gp_Pnt(0, 0, 0), 1.0).Shape(), g, True).Shape()
    box = BRepPrimAPI_MakeBox(gp_Pnt(-70, -40, 0), gp_Pnt(70, 40, 40)).Shape()
    L.write_step(L.solids(BRepAlgoAPI_Common(ell, box).Shape())[0], path)


def layout(stretch=1.0, window=True, offset=0.0):
    th = np.radians(np.linspace(-90, -270, 120))              # clockwise half loop (0,-12) -> (-12,0) -> (0,12): left normal points outward
    P = np.c_[12 * np.cos(th) + 4, 12 * np.sin(th)]
    P = np.r_[[[14.0, -12.0]], P, [[14.0, 12.0]]]
    P[:, 1] = np.where(P[:, 1] > 0, P[:, 1] * stretch, P[:, 1])
    lay = {'schema': 'click_slot_layout/1', 'slot_width_mm': 0.5, 'slot_depth_mm': 2.0,
           'perimeter': {'points': P.tolist(), 'slot_side': 'left'},
           'centre_gap': {'segments': [[[6.0, offset], [24.0, offset]]], 'width_mm': 1.0}, 'window': None}
    if window:
        lay['window'] = {'corners_TR_TL_BL_BR': [[-20, 3.0 + offset], [-30, 3.0 + offset], [-30, -3.0 + offset], [-20, -3.0 + offset]], 'corner_radius_mm': 1.5}
    return lay


def ws(tmp: Path, **kw):
    (tmp / 'c').mkdir(parents=True, exist_ok=True)
    if not (tmp / 'c' / 'shell.step').exists():
        make_shell(tmp / 'c' / 'shell.step')
    name = 'lay_%d.json' % abs(hash(json.dumps(kw, sort_keys=True)) % 10 ** 8)
    (tmp / 'c' / name).write_text(json.dumps(layout(**kw)), encoding='utf-8')
    return 'c/' + name


def test_cut_ready_and_cached(tmp_path):
    lp = ws(tmp_path)
    rep = cs.click_slots(tmp_path, 'c/shell.step', lp)
    assert rep['status'] == 'READY', (rep['blocking_reasons'], rep['checks'], rep['measured'])
    r = rep['result']
    assert r['valid'] and r['solids_in_step'] == 1 and r['removed_mm3'] > 50
    m = rep['measured']
    assert abs(m['perimeter']['width_mm_median'] - 0.5) < 0.05
    assert abs(m['centre_gap_0']['width_mm_median'] - 1.0) < 0.05
    assert abs(m['perimeter']['floor_hit_below_neighbour_surface_mm_median'] - 2.0) < 0.3
    w = rep['window']
    assert abs(w['length_mm'] - 10) < 1e-6 and abs(w['width_mm'] - 6) < 1e-6 and w['corner_radius_mm'] == 1.5
    assert (tmp_path / rep['outputs']['slotted_shell']['relative_path']).exists()
    again = cs.click_slots(tmp_path, 'c/shell.step', lp)
    assert again['cached'] is True and again['slots_id'] == rep['slots_id']
    wider = cs.click_slots(tmp_path, 'c/shell.step', lp, slot_width_mm=0.8, window_length_mm=12.0)
    assert abs(wider['measured']['perimeter']['width_mm_median'] - 0.8) < 0.05 and abs(wider['window']['length_mm'] - 12) < 1e-6
    assert wider['result']['removed_mm3'] > r['removed_mm3']


def test_symmetry_only_where_near_symmetric(tmp_path):
    near = cs.click_slots(tmp_path, 'c/shell.step', ws(tmp_path, stretch=1.05, offset=0.4), mirror_plane=MIRROR, cut_window=True)
    s = near['symmetry']
    assert s['perimeter']['symmetric'] is True and 'averaged' in s['perimeter']['correction']
    assert s['centre_gap'][0]['symmetric'] is True and s['window']['symmetric'] is True
    assert abs(near['window']['centre'][1]) < 1e-9
    far = cs.click_slots(tmp_path, 'c/shell.step', ws(tmp_path, stretch=1.8, offset=0.0), mirror_plane=MIRROR, cut_window=False)
    assert far['symmetry']['perimeter']['symmetric'] is False and 'kept' in far['symmetry']['perimeter']['correction']
    assert far['status'] == 'READY'


def test_validation(tmp_path):
    lp = ws(tmp_path)
    rejects('CLICK_SLOTS_SETTINGS', lambda: cs.click_slots(tmp_path, 'c/shell.step', lp, depth_mm=0.0))
    rejects('CLICK_SLOTS_SETTINGS', lambda: cs.click_slots(tmp_path, 'c/shell.step', lp, cut_perimeter=False, cut_gap=False, cut_window=False))
    rejects('CLICK_SLOTS_SETTINGS', lambda: cs.click_slots(tmp_path, 'c/shell.step', lp, mirror_plane={'normal': [0, 0, 0], 'd': 0}))
    rejects('CLICK_SLOTS_SETTINGS', lambda: cs.click_slots(tmp_path, 'c/shell.step', lp, cut_gap='yes'))
    with pytest.raises(BrainError):
        cs.click_slots(tmp_path, 'c/none.step', lp)
    (tmp_path / 'c' / 'bad.json').write_text('{"schema": "other"}', encoding='utf-8')
    rejects('CLICK_SLOTS_LAYOUT', lambda: cs.click_slots(tmp_path, 'c/shell.step', 'c/bad.json'))


def test_tool_listed(tmp_path):
    tools = {t['name']: t for t in Tools(Brain(tmp_path)).list()}
    t = tools['brain_mouse_click_slots']
    assert t['annotations']['readOnlyHint'] is False
    assert 'never forced' in t['description']


def test_front_lip_run_and_gap_overreach_are_trimmed(tmp_path):
    """whole_v1 rules: the perimeter slot does not run along the front lip and the centre gap starts at the perimeter slot (no slivers)."""
    th = np.radians(np.linspace(-90, -270, 120))
    P = np.c_[12 * np.cos(th) + 4, 12 * np.sin(th)]
    front = np.c_[np.full(25, 16.0), np.linspace(12, -12, 25)]                # front run across the panel (outward normal +x)
    P = np.r_[np.c_[np.linspace(16, 4, 13), np.full(13, -12.0)][:-1], P, np.c_[np.linspace(4, 16, 13), np.full(13, 12.0)][1:], front[1:-1]]
    i0 = int(np.argmin(np.abs(P[:, 1]) + 100 * (P[:, 0] < 10)))                 # open path starting / ending at the front centre
    P = np.r_[P[i0:], P[:i0]]
    lay = {'schema': 'click_slot_layout/1', 'slot_width_mm': 0.5, 'perimeter': {'points': P.tolist(), 'slot_side': 'left'},
           'centre_gap': {'segments': [[[-14.0, 0.0], [20.0, 0.0]]], 'width_mm': 1.0}, 'window': None}
    (tmp_path / 'c').mkdir(parents=True, exist_ok=True)
    make_shell(tmp_path / 'c' / 'shell.step')
    (tmp_path / 'c' / 'lay.json').write_text(json.dumps(lay), encoding='utf-8')
    rep = cs.click_slots(tmp_path, 'c/shell.step', 'c/lay.json')
    assert rep['status'] == 'READY', (rep['blocking_reasons'], rep['checks'])
    t = rep['trim']
    ends = np.asarray(t['perimeter_lip']['ends_xy'])
    assert t['perimeter_lip']['removed_front_mm'] > 20 and (ends[:, 0] < 16.0).all()             # the front run is not cut
    g0 = np.asarray(t['centre_gap'][0]['new_end_xy'])
    assert -8.6 < g0[0] < -7.4                                                                  # gap starts at the rear of the perimeter slot
    assert rep['checks']['no_slivers'] in ('PASS', 'WARN') and rep['result']['faces_below_0p05mm2'] == 0


# ------------------------------------------------------------------ CS1.3: arc-length symmetry, window on the gap line, no step, roughness gate
def test_symmetric_average_matches_branches_by_arc_length():
    from cadmcp_brain.studio import scan_click_slots_worker as SW
    n, d = np.array([0.0, 1.0, 0.0]), 0.0
    t1, t2 = np.linspace(0, 1, 300), np.linspace(0, 1, 60)                    # one branch sampled 5x denser than the other
    lo = np.c_[20 - 20 * t1, -10.0 - 0.0 * t1]
    up = np.c_[20 * t2, np.full(60, 10.3)]                                     # 0.3 mm off the mirror image (near-symmetric)
    rear = np.c_[np.zeros(41), np.linspace(-10, 10.3, 41)]
    P = np.r_[lo, rear[1:-1], up]
    out, how = SW.symmetric_average(P, n, d, 0.1)
    assert 'arc length' in how
    mir = SW.mirror2(out, n, d)
    assert SW.seg_dist(mir, out).max() < 1e-9                                   # exactly symmetric
    ref = np.r_[np.c_[np.linspace(20, 0, 50), np.full(50, -10.15)], np.c_[np.zeros(50), np.linspace(-10.15, 10.15, 50)], np.c_[np.linspace(0, 20, 50), np.full(50, 10.15)]]
    assert SW.seg_dist(out, ref).max() < 0.05                                   # the average of the two branches, not an index mix


def _gap_window_layout(win_dy=0.4, wobble=0.0):
    th = np.radians(np.linspace(-90, -270, 160))
    P = np.c_[14 * np.cos(th) + 4, 14 * np.sin(th)]
    P = np.r_[[[24.0, -14.0]], P, [[24.0, 14.0]]]
    if wobble:
        from cadmcp_brain.studio import scan_click_slots_worker as SW
        P = SW.resample(P, 0.2)[0]
        s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
        P = P + wobble * np.sin(2 * np.pi * s / 5.0)[:, None] * SW.left_normal(P)
    return {'schema': 'click_slot_layout/1', 'slot_width_mm': 0.5, 'slot_depth_mm': 2.0, 'perimeter': {'points': P.tolist(), 'slot_side': 'left'},
            'centre_gap': {'segments': [[[-8.0, 0.0], [30.0, 0.0]]], 'width_mm': 1.0},
            'window': {'corners_TR_TL_BL_BR': [[18, 3.0 + win_dy], [8, 3.0 + win_dy], [8, -3.0 + win_dy], [18, -3.0 + win_dy]], 'corner_radius_mm': 1.5}}


def _run_layout(tmp_path, lay, name):
    (tmp_path / 'c').mkdir(parents=True, exist_ok=True)
    if not (tmp_path / 'c' / 'shell.step').exists():
        make_shell(tmp_path / 'c' / 'shell.step')
    (tmp_path / 'c' / name).write_text(json.dumps(lay), encoding='utf-8')
    return cs.click_slots(tmp_path, 'c/shell.step', 'c/' + name)


def test_window_is_moved_onto_the_gap_line_and_the_gap_enters_without_a_step(tmp_path):
    rep = _run_layout(tmp_path, _gap_window_layout(win_dy=0.4), 'gw.json')
    assert rep['status'] == 'READY', (rep['blocking_reasons'], rep['checks'])
    wg = rep['quality']['window_gap']
    assert wg['on_gap_line'] and abs(abs(wg['offset_before_mm']) - 0.4) < 1e-6
    assert abs(rep['window']['centre'][1]) < 1e-6 and rep['checks']['window_on_gap_line'] == 'PASS'
    # independent: along the gap centre line the floor runs into the window floor continuously (no step face)
    from cadmcp_brain.studio import scan_click_grooves_worker as GW
    shp = L.read_step(tmp_path / rep['outputs']['slotted_shell']['relative_path'])
    tm = L.tessellate(shp, defl=0.01, ang=0.1)
    hits = GW.VerticalHits(np.asarray(tm['V']), np.asarray(tm['T']))
    xs = np.arange(18.6, 23.0, 0.05)
    z = hits.top(np.c_[xs, np.zeros_like(xs)])
    assert np.isfinite(z).all() and np.abs(np.diff(z)).max() < 0.15, np.abs(np.diff(z)).max()


def test_rough_perimeter_is_not_ready(tmp_path):
    rep = _run_layout(tmp_path, _gap_window_layout(win_dy=0.0, wobble=0.15), 'rough.json')
    pr = rep['quality']['perimeter_roughness']
    assert pr['curvature_sign_changes'] > 0 and rep['checks']['perimeter_outline_regular'] == 'FAIL'
    assert rep['status'] == 'NOT_READY'
    clean = _run_layout(tmp_path, _gap_window_layout(win_dy=0.0), 'clean.json')
    assert clean['checks']['perimeter_outline_regular'] == 'PASS' and clean['quality']['perimeter_roughness']['curvature_sign_changes'] == 0
