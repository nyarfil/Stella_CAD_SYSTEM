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


# ------------------------------------------------------------------ CS1.7: the panel ends at a crisp crease of the shell (no slot band on the lip edge)
def make_capped_shell(path: Path, z_cap: float = 22.0):
    """Half ellipsoid 120 x 64 x 30 capped flat at z_cap: a crisp crease (flat top / ellipsoid skin) runs round the whole top."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepBuilderAPI import BRepBuilderAPI_GTransform
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeSphere
    from OCP.gp import gp_GTrsf, gp_Mat, gp_Pnt
    g = gp_GTrsf()
    g.SetVectorialPart(gp_Mat(60, 0, 0, 0, 32, 0, 0, 0, 30))
    ell = BRepBuilderAPI_GTransform(BRepPrimAPI_MakeSphere(gp_Pnt(0, 0, 0), 1.0).Shape(), g, True).Shape()
    box = BRepPrimAPI_MakeBox(gp_Pnt(-70, -40, 0), gp_Pnt(70, 40, z_cap)).Shape()
    L.write_step(L.solids(BRepAlgoAPI_Common(ell, box).Shape())[0], path)


def crease_hugging_layout(z_cap: float = 22.0):
    """Open clockwise loop on the flat top: 0.99 x the crease ellipse over the front half (the band would straddle the crease round the front
    corners, where the outward normal is still sideways), shrinking smoothly to 0.8 x at the rear (clear of the crease)."""
    k = np.sqrt(1.0 - (z_cap / 30.0) ** 2)
    a, b = 60.0 * k, 32.0 * k
    t = np.radians(-np.linspace(0.75, 359.25, 240))          # clockwise from just below the front centre: left normal points outward
    s = 0.99 - 0.19 * np.maximum(0.0, -np.cos(t))
    P = np.c_[a * s * np.cos(t), b * s * np.sin(t)]
    return {'schema': 'click_slot_layout/1', 'slot_width_mm': 0.5, 'perimeter': {'points': P.tolist(), 'slot_side': 'left'},
            'centre_gap': {'segments': [[[-30.0, 0.0], [20.0, 0.0]]], 'width_mm': 1.0}, 'window': None}


def test_slot_band_on_a_crisp_crease_is_trimmed_back(tmp_path):
    """A perimeter path that hugs the shell's crisp crease round the front corners (normal < lip_angle_deg forward, so the lip-angle rule keeps
    it) is trimmed by the crease rule until its band clears the edge; the cut has no sliver faces and both ends lie behind the front."""
    (tmp_path / 'c').mkdir(parents=True, exist_ok=True)
    make_capped_shell(tmp_path / 'c' / 'shell.step')
    (tmp_path / 'c' / 'lay.json').write_text(json.dumps(crease_hugging_layout()), encoding='utf-8')
    rep = cs.click_slots(tmp_path, 'c/shell.step', 'c/lay.json')
    # CS1.9: this path never leaves the shell, so its crease-stopped ends cannot reach the outer edge: the gate must say so
    assert rep['status'] == 'NOT_READY' and rep['blocking_reasons'] == ['SLOT_END_NOT_AT_EDGE'], (rep['blocking_reasons'], rep['checks'], rep['warnings'])
    t = rep['trim']['perimeter_lip']
    assert t['crease_stations_removed'] > 0 and t['lip_angle_stations_removed'] > 0 and t['crease']['crisp_edge_samples'] > 100
    ends = np.asarray(t['ends_xy'])
    assert (ends[:, 0] < 0.0).all(), ends                                                      # both ends behind the front half
    assert not any(e['exits_shell'] for e in t['ends']) and all(e['stub_mm'] is None or e['stub_mm'] > 0.1 for e in t['ends'])
    assert rep['result']['faces_below_0p05mm2'] == 0 and rep['checks']['no_slivers'] != 'FAIL'


@pytest.mark.parametrize('mirrored', [False, True])
def test_crease_stopped_end_runs_out_through_the_shell_edge(tmp_path, mirrored):
    """CS1.9: a side slot that crosses the crease and runs on over the skirt to the shell's outer edge is not stopped at the crease: the end is
    extended to the first station whose band is off the shell, so no uncut stub is left (gate PASS, stub 0 measured on the produced solid).
    Mirrored: reversed path order and the other slot side (left-handed scan)."""
    (tmp_path / 'c').mkdir(parents=True, exist_ok=True)
    make_capped_shell(tmp_path / 'c' / 'shell.step')
    P = np.c_[np.linspace(-20.0, 70.0, 181), np.full(181, -15.0)]
    if mirrored:
        P = P[::-1]
    lay = {'schema': 'click_slot_layout/1', 'slot_width_mm': 0.5, 'perimeter': {'points': P.tolist(), 'slot_side': 'right' if mirrored else 'left'},
           'centre_gap': None, 'window': None}
    (tmp_path / 'c' / 'lay.json').write_text(json.dumps(lay), encoding='utf-8')
    rep = cs.click_slots(tmp_path, 'c/shell.step', 'c/lay.json')
    assert rep['status'] == 'READY', (rep['blocking_reasons'], rep['checks'], rep['warnings'])
    t = rep['trim']['perimeter_lip']
    ce = [e for e in t['ends'] if e['reason'] == 'crease']
    assert len(ce) == 1 and ce[0]['exits_shell'] and ce[0]['stub_mm'] == 0.0 and ce[0]['extended_mm'] > 15.0, t['ends']
    assert rep['checks']['slot_end_not_at_edge'] == 'PASS' and rep['checks']['no_slivers'] != 'FAIL'
    ex = np.asarray(t['ends_xy'])[:, 0].max()
    assert ex > 53.0, ex                                                                        # past the skirt edge at y = -15 (x = 52.9)


def test_crisp_edge_points_ignore_smooth_seams():
    from cadmcp_brain.studio import scan_click_slots_worker as SW
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeSphere
    from OCP.gp import gp_Pnt
    box = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), gp_Pnt(10, 10, 10)).Shape()
    E = SW.crisp_edge_points(box, 20.0, 0.5)
    assert E is not None and len(E) >= 12 * 20                                                 # 12 edges of 10 mm, 90 deg each
    sph = BRepPrimAPI_MakeSphere(gp_Pnt(0, 0, 0), 5.0).Shape()
    assert SW.crisp_edge_points(sph, 20.0, 0.5) is None                                        # seam edge of the sphere: 0 deg


# ------------------------------------------------------------------ CS1.8: through_wall (hollow-first order) keeps every piece
def make_hollow_shell(path: Path, wall=1.2):
    """Half-ellipsoid shell 120 x 64 x 30 hollowed by an inner half-ellipsoid (uniform axis offset `wall`), open at z = 0."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut
    from OCP.BRepBuilderAPI import BRepBuilderAPI_GTransform
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeSphere
    from OCP.gp import gp_GTrsf, gp_Mat, gp_Pnt

    def ell(a, b, c):
        g = gp_GTrsf()
        g.SetVectorialPart(gp_Mat(a, 0, 0, 0, b, 0, 0, 0, c))
        return BRepBuilderAPI_GTransform(BRepPrimAPI_MakeSphere(gp_Pnt(0, 0, 0), 1.0).Shape(), g, True).Shape()
    box = BRepPrimAPI_MakeBox(gp_Pnt(-70, -40, 0), gp_Pnt(70, 40, 40)).Shape()
    outer = BRepAlgoAPI_Common(ell(60, 32, 30), box).Shape()
    inner = BRepAlgoAPI_Common(ell(60 - wall, 32 - wall, 30 - wall), BRepPrimAPI_MakeBox(gp_Pnt(-70, -40, -1), gp_Pnt(70, 40, 40)).Shape()).Shape()
    L.write_step(L.solids(BRepAlgoAPI_Cut(outer, inner).Shape())[0], path)


def test_through_wall_keeps_every_piece(tmp_path):
    """Hollow shell (wall 1.2), default layout plus a second centre-gap segment across the front (closing the U), slot depth 2 > wall:
    the two click plates fall out as two extra solids; all three pieces are written, valid and meshable after the STEP round trip;
    the slit width is measured below the skin (not across the cavity); no end ramp is applied."""
    (tmp_path / 'c').mkdir(parents=True, exist_ok=True)
    make_hollow_shell(tmp_path / 'c' / 'hollow.step')
    lay = layout()
    lay['centre_gap']['segments'] = [[[-9.0, 0.0], [14.5, 0.0]], [[14.0, -13.0], [14.0, 13.0]]]      # full-length centre gap + front closure
    (tmp_path / 'c' / 'lay.json').write_text(json.dumps(lay), encoding='utf-8')
    rep = cs.click_slots(tmp_path, 'c/hollow.step', 'c/lay.json', through_wall=True)
    r = rep['result']
    assert rep['status'] == 'READY', (rep['blocking_reasons'], rep['checks'], rep['warnings'])
    assert r['solids_after_cut'] == 3 and r['pieces_written'] == 3 and r['pieces_valid'] is True, r
    assert rep['checks']['no_loose_pieces'] == 'NOT_APPLICABLE' and rep['checks']['pieces_valid'] == 'PASS'
    files = [f['file'] for f in rep['outputs']['pieces']]
    assert files == ['slotted_shell.step', 'piece_2.step', 'piece_3.step']
    vols = []
    for f in files:
        s = L.solids(L.read_step(tmp_path / 'mouse' / 'cad' / rep['slots_id'] / f))
        assert len(s) == 1 and L.is_valid(s[0])
        vols.append(L.volume(s[0]))
    assert vols[0] > 10000 and all(120 < v < 450 for v in vols[1:]) and abs(vols[1] - vols[2]) < 0.1 * vols[1], vols   # two mirror-equal plates
    assert abs(rep['measured']['perimeter']['width_mm_median'] - 0.5) <= 0.15
    assert rep['settings']['through_wall'] is True
