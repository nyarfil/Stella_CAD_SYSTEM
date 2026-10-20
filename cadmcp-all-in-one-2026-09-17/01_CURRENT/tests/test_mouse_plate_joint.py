"""brain_mouse_plate_joint (adopted plate_top rim + bearing pads; experimental tongue joint) on synthetic geometry (a frustum 'mouse': plate blank below z = 3, hollow shell above; no scan data, no V: files).
Worker runs in this process (needs OCP + vtk + scipy: extra `geometry`; skipped when missing); one test calls the module function with a tmp workspace
(server python subprocess).  The registered tool is added by the integrator, so the module function is called directly.
"""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import mouse_plate_joint as MJ

pytest.importorskip('OCP')
pytest.importorskip('vtk')
pytest.importorskip('scipy')
from cadmcp_brain.studio import cad_brep_lib as L  # noqa: E402
from cadmcp_brain.studio import mouse_plate_joint_worker as WJ  # noqa: E402

R0, H, SLOPE, ZB = 30.0, 30.0, 0.5, 3.0          # skin radius 30 - 0.5 z, blank below z = 3 (flat bottom z = 0), shell above z = 3
WALL = 1.3


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code


def cone(r_bottom, z0, z1, r0=R0):
    """Frustum of the skin r(z) = r0 - SLOPE z between z0 and z1, radius shrunk by (r0 - r_bottom)."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCone
    from OCP.gp import gp_Ax2, gp_Pnt, gp_Dir
    sh = r0 - r_bottom
    return L.solids(BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(0, 0, z0), gp_Dir(0, 0, 1)), r0 - SLOPE * z0 - sh, r0 - SLOPE * z1 - sh, z1 - z0).Shape())[0]


def moved(shape, dx, dy):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf, gp_Vec
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(dx, dy, 0))
    return L.solids(BRepBuilderAPI_Transform(shape, t, True).Shape())[0]


def make_parts(d, k=1.0, dx=0.0, dy=0.0):
    """The frustum 'mouse' scaled by k (wall stays 1.3) and moved by (dx, dy): the plate centre is NOT on the origin."""
    r0, zb, h = R0 * k, ZB * k, H * k
    plate = cone(r0, 0.0, zb, r0)
    horiz = WALL * (1 + SLOPE ** 2) ** 0.5
    shell = cut(cone(r0, zb, h, r0), cone(r0 - horiz, zb - 0.5, h + 1.0, r0))
    L.write_step(moved(plate, dx, dy), d / 'plate.step')
    L.write_step(moved(shell, dx, dy), d / 'shell.step')
    return d


def cut(a, b):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    return L.solids(BRepAlgoAPI_Cut(a, b).Shape())[0]


@pytest.fixture(scope='module')
def parts(tmp_path_factory):
    d = tmp_path_factory.mktemp('pj')
    plate = cone(R0, 0.0, ZB)                                   # skin radius 30 -> 28.5, flat top z = 3
    horiz = WALL * (1 + SLOPE ** 2) ** 0.5                      # horizontal chord of a normal offset on this cone
    outer = cone(R0, ZB, H)
    inner = cone(R0 + 0.0 - horiz, ZB - 0.5, H + 1.0)           # inner skin, open at the bottom
    shell = cut(outer, inner)
    L.write_step(plate, d / 'plate.step')
    L.write_step(shell, d / 'shell.step')
    return d


LH2_Z0_LEVELS = [{'x_from': 76.0, 'z0': 2.0}, {'x_from': 52.0, 'z0': 2.5}, {'x_from': 36.0, 'z0': 3.1}, {'x_from': 24.0, 'z0': 4.2}, {'x_from': 12.0, 'z0': 5.5}]   # LH2 v20b, verification only
LEVELS = [{'x_from': 0.0, 'z0': 3.0}]                           # z0 = 3.0 (the blank top) for x > 0.6, ramp to the rear value below


def worker(tmp, parts_dir, **params):
    p = {'pads_mm': [], 'samples': 40000}
    if params.pop('tongue', True):
        p.update({'bearing': 'z0_profile', 'ledge_measure': 'normal', 'tongue_height_mm': 1.2, 'z0_levels_mm': LEVELS, 'z0_rear_mm': 3.0, 'stations_x_mm': [-18.0, 18.0]})
    p.update(params)
    out = tmp / 'out'
    return WJ.run({'inputs': {'shell': str(parts_dir / 'shell.step'), 'plate': str(parts_dir / 'plate.step')}, 'params': p, 'out_dir': str(out)}), out


def test_profile_ramps_and_levels():
    poly = WJ.z0_polyline(LH2_Z0_LEVELS, 6.9, 2.0, -6.0, 125.0)
    assert [tuple(round(v, 3) for v in q) for q in poly[:5]] == [(-6.0, 6.9), (10.6, 6.9), (13.4, 5.5), (22.7, 5.5), (25.3, 4.2)]
    assert [tuple(round(v, 3) for v in q) for q in poly[-3:]] == [(75.5, 2.5), (76.5, 2.0), (125.0, 2.0)]
    z = WJ.z0_at(poly, [0, 12, 30, 44, 60, 76, 100])
    assert [round(float(v), 3) for v in z] == [6.9, 6.2, 4.2, 3.1, 2.5, 2.25, 2.0]
    with pytest.raises(WJ.WorkerError):
        WJ.z0_polyline([{'x_from': 10, 'z0': 5.0}, {'x_from': 12, 'z0': 2.0}], 6.9, 2.0, -6.0, 125.0)


def test_tongue_joint_hollow_plate(parts, tmp_path):
    res, out = worker(tmp_path, parts)
    ch = res['checks']
    assert ch['one_valid_solid']['status'] == 'PASS' and ch['step_roundtrip']['status'] == 'PASS'
    assert ch['bottom_flat_z0']['status'] == 'PASS' and abs(ch['bottom_flat_z0']['min_z_mm']) < 1e-4
    assert ch['floor_thickness']['status'] == 'PASS' and abs(ch['floor_thickness']['median_mm'] - 1.2) < 0.005
    assert ch['common_with_shell']['status'] == 'PASS' and ch['common_with_shell']['common_mm3'] <= 0.01
    g = ch['tongue_gap_at_stations']
    assert g['status'] == 'PASS' and abs(g['min_mm'] - 0.15) <= 0.05 and abs(g['max_mm'] - 0.15) <= 0.05 and g['stations_measured'] == 4
    assert ch['offset_model_accuracy']['status'] == 'PASS'
    assert ch['bearing_contact']['contact_area_mm2'] > 100                                   # the ledge top meets the shell bottom
    assert res['bbox'][5] == pytest.approx(3.0 + 1.2, abs=0.03)                               # tongue top = z0 + 1.2
    # hollow: the blank minus the cavity (mass bookkeeping from the closed mesh)
    assert 0 < res['mass']['mesh_volume_mm3'] < 0.5 * res['plate_blank']['mesh_volume_mm3'] + 3000
    assert (out / 'hollow_plate.step').is_file()
    pj = json.loads((out / 'joint_params.json').read_text())
    assert pj['ledge']['width_mm'] == pytest.approx(1.45) and pj['tongue']['width_normal_mm'] == 1.1 and pj['plate_floor_mm'] == 1.2
    assert pj['z0_profile_polyline_xz'][0][1] == 3.0 and len(pj['stations']) == 4


def test_rim_only_plan_wall_and_plate_top(parts, tmp_path):
    res, _ = worker(tmp_path, parts, tongue=False, ledge_mm=1.6)                             # adopted defaults: plate_top, plan rim
    ch = res['checks']
    assert all(v['status'] in ('PASS', 'INFO') for v in ch.values()), {k: v for k, v in ch.items() if v['status'] not in ('PASS', 'INFO')}
    assert res['bbox'][5] == pytest.approx(3.0, abs=0.03) and res['clearance_mm'] is None and res['bearing'] == 'plate_top' and 'bearing_pads' not in res['checks']
    # rim wall: horizontal thickness of the section at z = 2.5 is 1.6 (plan measure)
    import numpy as np
    from cadmcp_brain.studio import mouse_parts_lib as P
    V, T = P.mesh(L.one_solid(tmp_path / 'out' / 'hollow_plate.step', 'X'), 0.01)
    rr = np.hypot(*WJ.plane_points(V, T, 2.5, 0.2).T)
    outer, inner = rr.max(), rr[rr < rr.max() - 0.5].max()
    assert outer - inner == pytest.approx(1.6, abs=0.03)


def test_front_pad_is_blank_inside_the_rectangle(parts, tmp_path):
    pad = {'x_from': 8.0, 'x_to': 22.0, 'half_width_y': 6.0}
    res, _ = worker(tmp_path, parts, tongue=False, ledge_mm=1.6, pads_mm=[pad])
    ch = res['checks']
    assert ch['bearing_pads']['status'] == 'PASS' and ch['floor_thickness']['status'] == 'PASS' and ch['common_with_shell']['status'] == 'PASS'
    p0 = ch['bearing_pads']['pads'][0]
    assert p0['top_z_min'] == pytest.approx(3.0, abs=0.01) and p0['top_z_max'] == pytest.approx(3.0, abs=0.01)      # = blank top, not the 1.2 floor
    assert p0['blank_volume_mm3'] == pytest.approx(14.0 * 12.0 * 3.0, rel=0.02)
    base, _ = worker(tmp_path / 'b', parts, tongue=False, ledge_mm=1.6)
    assert res['mass']['mesh_volume_mm3'] - base['mass']['mesh_volume_mm3'] == pytest.approx(14.0 * 12.0 * (3.0 - 1.2), rel=0.03)
    with pytest.raises(WJ.WorkerError):                                                       # a pad rectangle outside the blank is an error, not a silent no-op
        worker(tmp_path / 'c', parts, tongue=False, pads_mm=[{'x_from': 103.6, 'x_to': 113.4, 'half_width_y': 8.6}])


def test_profile_above_the_blank_is_reported_not_built(parts, tmp_path):
    res, _ = worker(tmp_path, parts, z0_rear_mm=3.6)                                          # z0 = 3.6 for x < -0.6, the blank stops at 3.0
    c = res['checks']['ledge_reaches_profile']
    assert c['status'] == 'WARN' and c['max_deficit_mm'] > 0.5
    assert res['checks']['common_with_shell']['status'] == 'PASS'


def test_validation_and_module_end_to_end(parts, tmp_path):
    rejects('PLATE_JOINT_SETTINGS', lambda: MJ.plate_joint(parts, 'shell.step', 'plate.step', ledge_measure='cube'))
    rejects('PLATE_JOINT_SETTINGS', lambda: MJ.plate_joint(parts, 'shell.step', 'plate.step', tongue_height_mm=1.2))              # tongue needs a profile (default plate_top)
    rejects('PLATE_JOINT_SETTINGS', lambda: MJ.plate_joint(parts, 'shell.step', 'plate.step', bearing='z0_profile', tongue_height_mm=1.2))   # tongue needs normal (default plan)
    rejects('PLATE_JOINT_SETTINGS', lambda: MJ.plate_joint(parts, 'shell.step', 'plate.step', pads_mm=[{'x_from': 5, 'x_to': 1, 'half_width_y': 3}]))
    rejects('PLATE_JOINT_SETTINGS', lambda: MJ.plate_joint(parts, 'shell.step', 'plate.step', pads_mm=[{'x_from': 5}]))
    rejects('PLATE_JOINT_SETTINGS', lambda: MJ.plate_joint(parts, 'shell.step', 'plate.step', z0_levels_mm=[{'x_from': 1}]))
    rejects('PLATE_JOINT_SETTINGS', lambda: MJ.plate_joint(parts, 'shell.step', 'plate.step', floor_mm=0.0))
    rejects('PLATE_JOINT_Z0_REQUIRED', lambda: MJ.plate_joint(parts, 'shell.step', 'plate.step', bearing='z0_profile', ledge_measure='normal'))       # no LH2 z0 profile default
    rejects('PLATE_JOINT_Z0_REQUIRED', lambda: MJ.plate_joint(parts, 'shell.step', 'plate.step', bearing='z0_profile', ledge_measure='normal', z0_levels_mm=LEVELS))
    rejects('PLATE_JOINT_SETTINGS', lambda: MJ.plate_joint(parts, 'shell.step', 'plate.step', pads_mm=[{'x_from': 1, 'x_to': 5, 'half_width_y': 3, 'bogus': 1}]))
    with pytest.raises(WJ.WorkerError) as exc:
        worker(tmp_path / 'z', parts, bearing='z0_profile', ledge_measure='normal', tongue_height_mm=1.2, z0_levels_mm=None, z0_rear_mm=None)
    assert exc.value.code == 'PLATE_JOINT_Z0_REQUIRED'
    (parts / 'notes.txt').write_text('x')
    rejects('PLATE_JOINT_FILE', lambda: MJ.plate_joint(parts, 'notes.txt', 'plate.step'))
    rejects('UNSAFE_PATH', lambda: MJ.plate_joint(parts, '../x.step', 'plate.step'))
    rep = MJ.plate_joint(parts, 'shell.step', 'plate.step', pads_mm=[], bearing='z0_profile', ledge_measure='normal', tongue_height_mm=1.2, z0_levels_mm=LEVELS, z0_rear_mm=3.0,
                         stations_x_mm=[-18, 18])
    assert rep['status'] == 'READY' and rep['joint']['experimental_tongue'] is True and rep['blocking_reasons'] == [] and rep['plate_joint_id'].startswith('pj_')
    assert (parts / rep['outputs']['hollow_plate']['relative_path']).is_file() and rep['outputs']['joint_params']['sha256']
    again = MJ.plate_joint(parts, 'shell.step', 'plate.step', pads_mm=[], bearing='z0_profile', ledge_measure='normal', tongue_height_mm=1.2, z0_levels_mm=LEVELS, z0_rear_mm=3.0,
                           stations_x_mm=[-18, 18])
    assert again['cached'] is True and again['plate_joint_id'] == rep['plate_joint_id']


def test_adopted_default_end_to_end(parts, tmp_path):
    rep = MJ.plate_joint(parts, 'shell.step', 'plate.step', pads_mm=[{'x_from': 8.0, 'x_to': 22.0, 'half_width_y': 6.0}], ledge_mm=1.6)
    assert rep['status'] == 'READY' and rep['joint']['bearing'] == 'plate_top' and rep['joint']['experimental_tongue'] is False and rep['joint']['ledge_measure'] == 'plan'
    assert rep['checks']['bearing_pads']['status'] == 'PASS' and 'tongue_gap_at_stations' not in rep['checks']


def test_defaults_carry_no_model_specific_pad_or_stations(parts, tmp_path):
    rep = MJ.plate_joint(parts, 'shell.step', 'plate.step', ledge_mm=1.6)                    # nothing but the process defaults
    assert rep['joint']['pads_mm'] == [] and 'bearing_pads' not in rep['checks'] and rep['status'] == 'READY'
    xs = rep['stations_x_mm']
    assert len(xs) == 8 and -30 < xs[0] < xs[-1] < 30 and abs(xs[0] - (-30 + 0.05 * 60)) < 1e-6          # derived from the plate x extent


@pytest.mark.parametrize('k,dx,dy', [(1.0, 9.0, 25.0), (0.7, -14.0, 40.0)], ids=['shifted_y', 'scaled_and_shifted'])
def test_rim_and_pad_on_a_model_shifted_in_y_and_scaled(tmp_path, k, dx, dy):
    """The mirror plane is not y = 0: pad centre and station sides follow the plate bbox; geometry scales (pad volume k^3)."""
    d = make_parts(tmp_path / 'm', k, dx, dy) if (tmp_path / 'm').mkdir() is None else None
    pad = {'x_from': dx + 8.0 * k, 'x_to': dx + 22.0 * k, 'half_width_y': 6.0 * k}              # no y_centre: the plate bbox mid plane (= dy)
    base, _ = worker(tmp_path / 'a', d, tongue=False, ledge_mm=1.6)
    res, _ = worker(tmp_path / 'b', d, tongue=False, ledge_mm=1.6, pads_mm=[pad])
    ch = res['checks']
    assert all(v['status'] in ('PASS', 'INFO') for v in ch.values()), {n: v for n, v in ch.items() if v['status'] not in ('PASS', 'INFO')}
    assert res['centre_xy'][1] == pytest.approx(dy, abs=1e-3)
    p0 = ch['bearing_pads']['pads'][0]
    assert p0['y_centre'] == pytest.approx(dy, abs=1e-3) and p0['top_z_min'] == pytest.approx(3.0 * k, abs=0.01)
    assert p0['blank_volume_mm3'] == pytest.approx(14.0 * 12.0 * 3.0 * k ** 3, rel=0.03)
    assert res['mass']['mesh_volume_mm3'] - base['mass']['mesh_volume_mm3'] == pytest.approx(14.0 * 12.0 * k * k * (3.0 * k - 1.2), rel=0.04)
    assert {r['side'] for r in res['stations']} == {'low_y', 'high_y'} and all(r['rim_top_z'] is not None for r in res['stations'])


def test_tongue_joint_on_a_model_shifted_in_y(tmp_path):
    dx, dy = 6.0, 25.0
    d = make_parts(tmp_path / 'm', 1.0, dx, dy) if (tmp_path / 'm').mkdir() is None else None
    res, _ = worker(tmp_path, d, z0_levels_mm=[{'x_from': dx, 'z0': 3.0}], stations_x_mm=[dx - 18.0, dx + 18.0])
    ch = res['checks']
    assert all(v['status'] in ('PASS', 'INFO') for v in ch.values()), {n: v for n, v in ch.items() if v['status'] not in ('PASS', 'INFO')}
    assert ch['tongue_gap_at_stations']['stations_measured'] == 4
