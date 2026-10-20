"""brain_mouse_board_posts on synthetic geometry (no scan data, no V: files): a hollow box "shell" with a roof sloped 0.2 (11.31 deg), a level
"board" (pcb box with two 4.65 holes + switch body + plunger) parked away from the shell, and two sloped click-plate slabs above the roof.
The worker runs in this process (needs OCP); one end-to-end call goes through the module function and the server python subprocess.
"""
from __future__ import annotations
import math
from pathlib import Path
import numpy as np
import pytest
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import mouse_board_posts as M

pytest.importorskip('OCP')
from cadmcp_brain.studio import cad_brep_lib as L  # noqa: E402
from cadmcp_brain.studio import mouse_parts_lib as P  # noqa: E402
from cadmcp_brain.studio import mouse_board_posts_worker as W  # noqa: E402

K = 0.2                                   # roof underside z = 26 - K x
N = np.array([K, 0.0, 1.0]) / math.hypot(K, 1.0)
T_ROOF = 1.2 * math.hypot(K, 1.0)         # 1.2 normal wall -> vertical offset


def box(x0, y0, z0, x1, y1, z1):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    return BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()


def cut(a, *b):
    return L.solids(W.boolean('cut', a, list(b), 'test')[0])[0]


def fuse(a, *b):
    return L.solids(W.boolean('fuse', a, list(b), 'test', clean=True)[0])[0]


def above(z0):
    """Half-space (as a box) above the plane z = z0 - K x."""
    return W.plane_box((0, 0, z0), N, 400.0, 200.0)


def below(z0):
    return W.plane_box((0, 0, z0), -N, 400.0, 200.0)


def parts(hole_r=2.325):
    outer = cut(box(0, -20, 0, 60, 20, 40), above(26 + T_ROOF))
    cavity = cut(box(1.2, -18.8, 1.2, 58.8, 18.8, 40), above(26))
    shell = cut(outer, cavity)
    pcb = cut(box(-30, -4, 0, 0, 4, 0.8), W.cylinder((-25, 0, -1), hole_r, 3), W.cylinder((-5, 0, -1), hole_r, 3))
    switch = fuse(box(-18, -3, 0.8, -10, 3, 6), box(-14.6, -1.45, 6, -13.4, 1.45, 7))
    conn = box(-29, -2, -1.5, -27, 2, 0)
    pz = 26 + T_ROOF + 0.9
    plates = {s: cut(cut(box(15, y0, 0, 50, y1, 60), above(pz + 1.2)), below(pz)) for s, (y0, y1) in (('L', (-18, -1)), ('R', (1, 18)))}
    return {'top_shell': shell, 'main_switch_L_0': pcb, 'main_switch_L_1': switch, 'main_switch_L_2': conn,
            'click_plate_L': plates['L'], 'click_plate_R': plates['R']}, pz


def sides(pz):
    h = lambda y: [15.0, y, pz - K * 15.0]
    return [{'name': 'plateL', 'plate_part': 'click_plate_L', 'pivot': [30.0, -9.0, 18.0], 'hinge': [h(-18.0), h(-1.0)]},
            {'name': 'plateR', 'plate_part': 'click_plate_R', 'pivot': [30.0, 9.0, 18.0], 'hinge': [h(1.0), h(18.0)]}]


@pytest.fixture(scope='module')
def asm(tmp_path_factory):
    d = tmp_path_factory.mktemp('bp')
    ps, pz = parts()
    W.write(d / 'asm.step', list(ps.items()))
    return d, pz


def params(pz, stage='all', **kw):
    prm = {'stage': stage, 'shell_part': 'top_shell', 'board_parts': ['main_switch_L_0', 'main_switch_L_1', 'main_switch_L_2'],
           'pcb_part': 'main_switch_L_0', 'switch_part': 'main_switch_L_1', 'sides': sides(pz), 'board_holes': None, 'pitch_deg': None, 'mirror_y': 0.0,
           'board_prefix': 'main_switch', 'shell_out_name': 'top_shell_posts', 'posts_out_name': 'posts_tool', 'plate_suffix': '_posts', 'max_iter': 12,
           'rib_angles_deg': [60.0, 120.0, 240.0, 300.0]}
    prm.update({'board_hole_dia': None, 'post_dia': None})
    prm.update({k: v[0] for k, v in M.NUMS.items()})
    prm.update({k: list(v[0]) for k, v in M.INTS.items()})
    prm.update(kw)
    return prm


def test_board_datums_from_geometry(asm):
    d, _ = asm
    ps, _t = P.load_parts([str(d / 'asm.step')])
    D = W.board_datums(ps['main_switch_L_0'], ps['main_switch_L_1'], {'board_hole_dia': None})      # hole diameter measured, not given
    assert D['board_top_z'] == pytest.approx(0.8) and D['board_thickness'] == pytest.approx(0.8)
    assert np.allclose(D['holes'], [[-5, 0], [-25, 0]], atol=1e-6) and D['hole_dia_mm'] == pytest.approx(4.65)            # front first
    assert np.allclose(D['plunger_top'], [-14, 0, 7], atol=1e-6) and D['body_top_z'] == pytest.approx(6)
    assert np.allclose(D['body_rect'], [-18, -10, -3, 3], atol=1e-6)


def test_worker_places_boards_builds_posts_actuators(asm, tmp_path):
    d, pz = asm
    res = W.run({'inputs': {'step_0': str(d / 'asm.step')}, 'params': params(pz), 'out_dir': str(tmp_path / 'out')})
    r = res['report']
    assert r['pitch_deg'] == pytest.approx(math.degrees(math.atan(K)), abs=1e-6) and r['roll_deg'] == 0
    for s in ('plateL', 'plateR'):
        sd = r['sides'][s]
        assert sd['body_gap_mm'] == pytest.approx(0.38, abs=1e-3)               # flat roof: both sides limit, same shift
        assert sd['plunger_gap_min_mm'] == pytest.approx(0.38 - 1.0, abs=2e-3)   # plunger 1.0 above the body top (enters the floor hole)
        for b in r['posts'][s]['bosses']:
            lo, hi = b['height_board_top_to_floor_underside']
            assert 2.0 < lo <= hi < 20.0 and len(b['ribs']) == 4
        a = r['actuators'][s]
        assert a['post_len_tip_to_underside'] > 0 and a['plate_valid'] and a['lateral_at_floor_mid_mm'] > 0
    assert r['mirror']['plunger_y_mirror_dev_mm'] == pytest.approx(0, abs=1e-9) and r['post_dia_mm'] == pytest.approx(4.4)       # 4.65 hole - 0.25
    vol = r['shell_posts_volume']
    assert vol['posts_tool_mm3'] > 0 and vol['hole_material_mm3'] > 0 and r['floor_holes_volume']['hole_material_mm3'] > 0 and vol['hole_material_left_mm3'] < 1e-3
    assert r['shell']['valid'] and r['shell']['roundtrip']['solids'] == 1
    out = tmp_path / 'out'
    ps, _t = P.load_parts([str(out / res['files']['assembly'])])
    assert {'top_shell_posts', 'main_switch_plateL_0', 'main_switch_plateR_2', 'click_plate_L_posts', 'posts_tool'} <= set(ps)
    shell = ps['top_shell_posts']
    for s in ('plateL', 'plateR'):                                              # pin passes the board hole with play: no overlap
        c = W.boolean('common', ps[f'main_switch_{s}_0'], [shell], 'chk')[0]
        assert W.rec_vol(c) < 1e-3
        tip = np.array(r['posts'][s]['bosses'][0]['tip_pt'])                    # tip flush with the board bottom
        R, t = np.array(r['sides'][s]['R']), np.array(r['sides'][s]['t'])
        assert abs((R.T @ (tip - t))[2] - 0.0) < 2e-3
    assert len(L.solids(L.read_step(out / res['files']['posts_tool']))) == 4


def test_explicit_pitch_and_place_stage(asm, tmp_path):
    d, pz = asm
    res = W.run({'inputs': {'step_0': str(d / 'asm.step')}, 'params': params(pz, stage='place', pitch_deg=5.0), 'out_dir': str(tmp_path / 'o')})
    r = res['report']
    assert r['pitch_deg'] == pytest.approx(5.0) and 'posts' not in r and 'shell' not in res['files']


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code


def test_validation(asm):
    d, pz = asm
    ws, rel = d, 'asm.step'
    req = dict(shell_part='top_shell', pcb_part='main_switch_L_0', switch_part='main_switch_L_1', sides=sides(pz))
    rejects('BOARD_POSTS_SETTINGS', lambda: M.board_posts(ws, [rel], stage='bogus', **req))
    rejects('BOARD_POSTS_SETTINGS', lambda: M.board_posts(ws, [rel], nonsense=1, **req))
    rejects('BOARD_POSTS_SETTINGS', lambda: M.board_posts(ws, [rel], post_dia=-1, **req))
    rejects('BOARD_POSTS_SETTINGS', lambda: M.board_posts(ws, [rel], **{**req, 'sides': [{'name': 'a', 'pivot': [0, 0, 0]}]}))     # stage all needs a hinge
    rejects('BOARD_POSTS_SETTINGS', lambda: M.board_posts(ws, [rel], post_dia=4.4, pilot_dia=4.2, **req))
    # nothing model-specific is assumed: names and sides are required
    for k in ('shell_part', 'pcb_part', 'switch_part', 'sides'):
        rejects('BOARD_POSTS_SETTINGS', lambda k=k: M.board_posts(ws, [rel], **{a: b for a, b in req.items() if a != k}))
    rejects('BOARD_POSTS_SETTINGS', lambda: M.board_posts(ws, [rel], board_parts=['x'], **req))                         # must contain pcb + switch
    (ws / 'a.txt').write_text('x')
    rejects('BOARD_POSTS_FILE', lambda: M.board_posts(ws, ['a.txt'], **req))
    rejects('UNSAFE_PATH', lambda: M.board_posts(ws, ['missing.step'], **req))
    rejects('BOARD_POSTS_FILE', lambda: M.board_posts(ws, [], **req))


def test_end_to_end_with_cache(asm):
    d, pz = asm
    kw = dict(stage='posts', shell_part='top_shell', pcb_part='main_switch_L_0', switch_part='main_switch_L_1',
              board_parts=['main_switch_L_0', 'main_switch_L_1', 'main_switch_L_2'], board_prefix='main_switch',
              sides=[{k: v for k, v in s.items() if k in ('name', 'pivot')} for s in sides(pz)])
    r = M.board_posts(d, ['asm.step'], **kw)
    assert r['status'] == 'READY' and r['board_posts_id'].startswith('bp_')
    assert (d / r['outputs']['shell']['relative_path']).is_file()
    assert r['mirror']['plane_source'] == 'fitted from the shell' and abs(r['mirror']['plane_y_mm']) < 0.02            # fitted, not assumed
    assert r['settings']['shell_out_name'] == 'top_shell_posts'
    assert M.board_posts(d, ['asm.step'], **kw)['cached']


# ---------------------------------------------------------------- generality: the mirror plane is not at y = 0, the hole size is not 4.65
def moved(shape, dx, dy):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf, gp_Vec
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(dx, dy, 0))
    return L.solids(BRepBuilderAPI_Transform(shape, t, True).Shape())[0]


def shifted_asm(d, name, dx, dy, hole_r=2.325):
    ps, pz = parts(hole_r)
    for k in ('top_shell', 'click_plate_L', 'click_plate_R'):
        ps[k] = moved(ps[k], dx, dy)
    W.write(d / name, list(ps.items()))
    sd = sides(pz)
    for s in sd:
        s['pivot'] = [s['pivot'][0] + dx, s['pivot'][1] + dy, s['pivot'][2]]
        s['hinge'] = [[p[0] + dx, p[1] + dy, p[2]] for p in s['hinge']]
    return sd


def test_model_shifted_in_y_gives_the_same_result_with_a_fitted_mirror_plane(asm, tmp_path):
    d, pz = asm
    base = W.run({'inputs': {'step_0': str(d / 'asm.step')}, 'params': params(pz, mirror_y=None), 'out_dir': str(tmp_path / 'o0')})['report']
    sd = shifted_asm(tmp_path, 'shift.step', 17.0, 41.5)
    res = W.run({'inputs': {'step_0': str(tmp_path / 'shift.step')}, 'params': params(pz, sides=sd, mirror_y=None), 'out_dir': str(tmp_path / 'o1')})
    r = res['report']
    assert r['mirror']['plane_source'] == 'fitted from the shell' and r['mirror']['plane_y_mm'] == pytest.approx(41.5, abs=0.02)
    assert r['mirror']['plunger_y_mirror_dev_mm'] < 0.05
    assert r['pitch_deg'] == pytest.approx(base['pitch_deg'], abs=1e-6)
    assert r['shell_posts_volume']['posts_tool_mm3'] == pytest.approx(base['shell_posts_volume']['posts_tool_mm3'], rel=1e-6)
    assert r['floor_holes_volume']['hole_material_mm3'] == pytest.approx(base['floor_holes_volume']['hole_material_mm3'], rel=1e-5)
    # the old assumption (mirror plane y = 0) is now an explicit argument and would flag this model
    bad = W.run({'inputs': {'step_0': str(tmp_path / 'shift.step')}, 'params': params(pz, sides=sd, mirror_y=0.0, stage='place'), 'out_dir': str(tmp_path / 'o2')})['report']
    assert bad['mirror']['plunger_y_mirror_dev_mm'] == pytest.approx(83.0, abs=0.05)


def test_post_diameter_follows_the_measured_board_hole(tmp_path):
    ps, pz = parts(hole_r=3.0)                              # 6.0 mm board holes instead of 4.65
    W.write(tmp_path / 'big.step', list(ps.items()))
    res = W.run({'inputs': {'step_0': str(tmp_path / 'big.step')}, 'params': params(pz, stage='posts'), 'out_dir': str(tmp_path / 'o')})
    r = res['report']
    assert r['board']['hole_dia_mm'] == pytest.approx(6.0) and r['post_dia_mm'] == pytest.approx(5.75)
    assert r['board']['post_dia_source'].startswith('measured hole')
    small = W.run({'inputs': {'step_0': str(tmp_path / 'big.step')}, 'params': params(pz, stage='posts', post_dia=5.0), 'out_dir': str(tmp_path / 'o2')})['report']
    assert small['post_dia_mm'] == 5.0 and small['board']['post_dia_source'] == 'argument'
    assert r['shell_posts_volume']['posts_tool_mm3'] > small['shell_posts_volume']['posts_tool_mm3']


# ---------------------------------------------------------------- derived sides: pivots from in-place switch seeds, hinges from the plate rear edge
def placed(shape, dx=0.0, dy=0.0, dz=0.0, rot_y_deg=0.0, about=(0.0, 0.0, 0.0)):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf, gp_Vec, gp_Ax1, gp_Pnt, gp_Dir
    t = gp_Trsf()
    t.SetRotation(gp_Ax1(gp_Pnt(*about), gp_Dir(0, 1, 0)), math.radians(rot_y_deg))
    m = gp_Trsf()
    m.SetTranslation(gp_Vec(dx, dy, dz))
    return L.solids(BRepBuilderAPI_Transform(shape, m.Multiplied(t), True).Shape())[0]


def seed_asm(d, name, tops, rot_y_deg=0.0):
    """parts() + one in-place copy of the switch per plunger top (master plunger top (-14, 0, 7))."""
    ps, pz = parts()
    for i, (x, y, z) in enumerate(tops):
        ps[f'seed_{i}'] = placed(ps['main_switch_L_1'], x + 14, y, z - 7, rot_y_deg, (-14, 0, 7))
    W.write(d / name, list(ps.items()))
    return pz


def derive(**kw):
    dv = {'seed_switch_parts': ['seed_0', 'seed_1'], 'plate_parts': ['click_plate_L', 'click_plate_R'], 'seed_shift_mm': [0.0, 0.0],
          'side_names': None, 'pivot_z_rule': 'seed', 'symmetrise': True}
    dv.update(kw)
    return dv


def test_derived_sides_reproduce_the_explicit_sides(asm, tmp_path):
    d, pz = asm
    seed_asm(tmp_path, 's.step', [(30, -9, 18), (30, 9, 18)])
    ref = W.run({'inputs': {'step_0': str(d / 'asm.step')}, 'params': params(pz), 'out_dir': str(tmp_path / 'o0')})['report']
    res = W.run({'inputs': {'step_0': str(tmp_path / 's.step')}, 'params': params(pz, sides=None, derive=derive()), 'out_dir': str(tmp_path / 'o1')})
    r = res['report']
    dv = r['derived_sides']
    by = {s['name']: s for s in dv['sides']}
    assert set(by) == {'click_plate_L', 'click_plate_R'}                            # names default to the plates above the seeds
    assert np.allclose(by['click_plate_L']['pivot'], [30, -9, 18], atol=1e-6) and np.allclose(by['click_plate_R']['pivot'], [30, 9, 18], atol=1e-6)
    zr = pz - K * 15.0                                                              # rear edge underside of the sloped plate
    assert np.allclose(by['click_plate_L']['hinge'], [[15, -1, zr], [15, -18, zr]], atol=1e-6)        # inner end first, then outer
    assert np.allclose(by['click_plate_R']['hinge'], [[15, 1, zr], [15, 18, zr]], atol=1e-6)
    assert all(s['match_residual_mm'] < 1e-6 and s['tilt_deg'] == 0 for s in dv['seeds']) and dv['symmetrised']
    assert r['pitch_deg'] == pytest.approx(ref['pitch_deg'], abs=1e-9)
    for a, b in (('click_plate_L', 'plateL'), ('click_plate_R', 'plateR')):
        assert np.allclose(r['sides'][a]['plunger_top'], ref['sides'][b]['plunger_top'], atol=1e-6)
        assert r['actuators'][a]['lever_mm'] == pytest.approx(ref['actuators'][b]['lever_mm'], abs=1e-6)


def test_derived_shift_symmetrise_and_plunger_gap_rule(tmp_path):
    pz = seed_asm(tmp_path, 's.step', [(30, -9.4, 18), (30, 9, 18)])
    prm = params(pz, stage='place', sides=None, derive=derive(seed_shift_mm=[-1.0, 1.0], plate_parts=None, side_names=['a', 'b']))
    r = W.run({'inputs': {'step_0': str(tmp_path / 's.step')}, 'params': prm, 'out_dir': str(tmp_path / 'o')})['report']
    sd = r['derived_sides']['sides']
    assert np.allclose(sd[0]['pivot'], [29, -8.2, 18], atol=1e-6) and np.allclose(sd[1]['pivot'], [29, 8.2, 18], atol=1e-6)   # mean of side + mirror
    # level seeds, rule auto -> plunger_gap: vertical move until the min plunger-top -> floor-underside distance along the normal is 0.80
    prm = params(pz, stage='place', sides=None, derive=derive(pivot_z_rule='auto', plate_parts=None, side_names=['a', 'b']))
    r = W.run({'inputs': {'step_0': str(tmp_path / 's.step')}, 'params': prm, 'out_dir': str(tmp_path / 'o2')})['report']
    dv = r['derived_sides']
    assert [s['z_rule'] for s in dv['seeds']] == ['plunger_gap', 'plunger_gap']
    ps, _t = P.load_parts([str(tmp_path / 's.step')])
    D = W.board_datums(ps['main_switch_L_0'], ps['main_switch_L_1'], {'board_hole_dia': None})
    R = W.pitch_rot(math.radians(r['pitch_deg']))
    P0 = np.array(D['plunger_top'])
    x0, x1, y0, y1 = D['plunger_rect']
    for s in dv['sides']:
        pts = [R @ (np.array([x, y, P0[2]]) - P0) + np.array(s['pivot']) for x in (x0, x1) for y in (y0, y1)]
        gap = min((26 - K * p[0] - p[2]) / math.hypot(K, 1.0) for p in pts)        # u = roof normal (pitch fitted to the roof)
        assert gap == pytest.approx(0.80, abs=1e-3)
    assert dv['sides'][0]['pivot'][2] == pytest.approx(dv['sides'][1]['pivot'][2])


def test_derived_pitched_seed_and_seed_errors(tmp_path):
    pz = seed_asm(tmp_path, 's.step', [(30, -9, 18), (30, 9, 18)], rot_y_deg=8.0)
    r = W.run({'inputs': {'step_0': str(tmp_path / 's.step')}, 'params': params(pz, stage='place', sides=None, derive=derive(pivot_z_rule='auto')),
               'out_dir': str(tmp_path / 'o')})['report']
    for s in r['derived_sides']['seeds']:
        assert s['tilt_deg'] == pytest.approx(8.0, abs=1e-6) and s['z_rule'] == 'seed' and s['match_residual_mm'] < 1e-6
    assert np.allclose(r['derived_sides']['sides'][0]['pivot'], [30, -9, 18], atol=1e-6)    # plunger top is the rotation centre: unchanged
    ps, pz = parts()                                                                         # a seed that is not a copy of the switch
    ps['seed_0'], ps['seed_1'] = box(20, -10, 10, 28, -4, 16), placed(ps['main_switch_L_1'], 44, 9, 11)
    W.write(tmp_path / 'bad.step', list(ps.items()))
    with pytest.raises(W.WorkerError) as e:
        W.run({'inputs': {'step_0': str(tmp_path / 'bad.step')}, 'params': params(pz, stage='place', sides=None, derive=derive()), 'out_dir': str(tmp_path / 'o2')})
    assert e.value.code == 'BOARD_POSTS_SEED'
    seed_asm(tmp_path, 'off.step', [(30, -9, 18), (55, 9, 18)])                              # second seed is not under a plate
    with pytest.raises(W.WorkerError) as e:
        W.run({'inputs': {'step_0': str(tmp_path / 'off.step')}, 'params': params(pz, stage='place', sides=None, derive=derive()), 'out_dir': str(tmp_path / 'o3')})
    assert e.value.code == 'BOARD_POSTS_SEED'


def test_derived_sides_validation(asm):
    d, pz = asm
    req = dict(shell_part='top_shell', pcb_part='main_switch_L_0', switch_part='main_switch_L_1')
    S = 'BOARD_POSTS_SETTINGS'
    rejects(S, lambda: M.board_posts(d, ['asm.step'], sides=sides(pz), seed_switch_parts=['a', 'b'], **req))      # override and derivation together
    rejects(S, lambda: M.board_posts(d, ['asm.step'], **req))                                                       # neither
    rejects(S, lambda: M.board_posts(d, ['asm.step'], seed_switch_parts=['a', 'b'], **req))                          # stage all needs plates
    rejects(S, lambda: M.board_posts(d, ['asm.step'], seed_switch_parts=['a', 'b'], plate_parts=['p'], **req))       # one plate per seed
    rejects(S, lambda: M.board_posts(d, ['asm.step'], stage='place', seed_switch_parts=['a'], seed_shift_mm=[1], **req))
    rejects(S, lambda: M.board_posts(d, ['asm.step'], stage='place', seed_switch_parts=['a'], seed_shift_mm=[0, 99], **req))
    rejects(S, lambda: M.board_posts(d, ['asm.step'], stage='place', seed_switch_parts=['a'], pivot_z_rule='x', **req))
    rejects(S, lambda: M.board_posts(d, ['asm.step'], stage='place', seed_switch_parts=['a'], side_names=['a b'], **req))
    rejects(S, lambda: M.board_posts(d, ['asm.step'], stage='place', seed_switch_parts=['a'], symmetrise='yes', **req))


# ---------------------------------------------------------------- brain_mouse_board_place: pose of a board pack by rules, residuals, NOT_READY
from cadmcp_brain.studio import mouse_board_place as MP  # noqa: E402
from cadmcp_brain.studio import mouse_board_place_worker as WP  # noqa: E402

OFF = np.array([-100.0, 7.0, 3.0])                    # the pack is parked here; the expected translation is -OFF


def place_parts(solid_skin=False, pcb_half_width=10.0):
    """Shell 60 x 40 x 30 (hollow: open bottom, 1.2 walls, roof window x 30..40 / y +-3, cable slot y +-1.5 in the front wall; or a closed solid
    skin from z 1). Pack in place: helper bottom z 0, sensor centred on y 0, level PCB, wheel in the window, bush whose 30 deg end face has its
    centre on the front skin x 60, one switch (copy of the posts master) under a plate; then parked by OFF."""
    if solid_skin:
        shell = box(0, -20, 1, 60, 20, 30)
    else:
        shell = cut(box(0, -20, 0, 60, 20, 30), box(1.2, -18.8, -1, 58.8, 18.8, 28.8), box(30, -3, 25, 40, 3, 35), box(55, -1.5, 2, 65, 1.5, 8))
    n = np.array([math.cos(math.radians(30)), 0.0, -math.sin(math.radians(30))])
    bush = cut(box(50, -5, 3, 62, 5, 7), W.plane_box((60, 0, 5), n, 100.0, 100.0))
    ps0, _pz = parts()
    pack = {'helper': box(18, -5, 0, 28, 5, 1.5), 'sensor': box(20, -3, 2, 26, 3, 5), 'pcb': box(10, -pcb_half_width, 5, 50, pcb_half_width, 5.8),
            'wheel': box(33, -1, 6, 37, 1, 29.5), 'bush': bush, 'seed': placed(ps0['main_switch_L_1'], 54, 10, 13)}
    out = {'topcase': shell, 'plate': box(10, 5, 31, 55, 18, 32), 'm_pcb': ps0['main_switch_L_0'], 'm_sw': ps0['main_switch_L_1']}
    out.update({k: placed(v, *OFF) for k, v in pack.items()})
    return out


def place_params(**kw):
    prm = {'shell_part': 'topcase', 'pack_parts': ['helper', 'sensor', 'pcb', 'wheel', 'bush', 'seed'], 'sensor_part': 'sensor', 'floor_datum_part': 'helper',
           'pcb_part': 'pcb', 'floor_z': 0.0, 'floor_part': None, 'x_rule': 'auto', 'bush_part': 'bush', 'wheel_parts': ['wheel'],
           'seed_switch_parts': ['seed'], 'switch_part': 'm_sw', 'switch_pcb_part': 'm_pcb', 'plate_parts': ['plate'], 'report_only_parts': ['bush'],
           'mirror_y': None, 'shell_kind': 'auto'}
    prm.update({k: v[0] for k, v in MP.NUMS.items()})
    prm.update(kw)
    return prm


def run_place(tmp_path, name, ps, **kw):
    W.write(tmp_path / name, list(ps.items()))
    return WP.run({'inputs': {'step_0': str(tmp_path / name)}, 'params': place_params(**kw), 'out_dir': str(tmp_path / (name + '.o'))})


def test_board_place_recovers_the_pose_by_rules(tmp_path):
    res = run_place(tmp_path, 'h.step', place_parts())
    r = res['report']
    assert r['shell_kind'] == 'hollow' and r['x_rule'] == 'bush_flush' and r['blocking_reasons'] == [], r['blocking_reasons']
    assert np.allclose(r['translation_mm'], -OFF, atol=0.03)                      # bush flush (x), sensor on the fitted plane (y), helper on the floor (z)
    rs = r['residuals']
    assert abs(rs['sensor_y_to_plane_mm']) < 1e-6 and abs(rs['floor_datum_z_mm']) < 1e-6 and rs['pcb_tilt_deg'] < 1e-6
    assert abs(rs['bush_flush']['offset_median_mm']) < 0.02 and rs['bush_flush']['found'] < rs['bush_flush']['samples']   # slot points find no skin
    assert r['wheel_window']['source'] == 'rays on the mirror line' and abs(rs['wheel']['dx_mm']) < 0.3 and abs(rs['wheel']['dy_mm']) < 0.05
    sw = r['switches'][0]
    assert sw['under'] == ['plate'] and np.allclose(sw['plunger_top'], [40, 10, 20], atol=0.05) and sw['vertical_gap_to_ceiling_mm'] == pytest.approx(8.8, abs=0.05)
    assert r['clearance']['pcb']['min_clearance_mm'] > 0.3 and r['clearance']['bush']['report_only']
    assert res['files']['pack'] == 'placed_pack.step'
    ps, _t = P.load_parts([str(tmp_path / 'h.step.o' / 'placed_pack.step')])
    assert set(ps) == {'helper', 'sensor', 'pcb', 'wheel', 'bush', 'seed'} and abs(L.bbox(ps['helper'], optimal=False)[2]) < 0.05
    # x by the wheel rule: same pose here (the wheel sits in the window centre)
    rw = run_place(tmp_path, 'h2.step', place_parts(), x_rule='wheel')['report']
    assert rw['translation_mm'][0] == pytest.approx(100.0, abs=0.3)


def test_board_place_not_ready_and_solid_skin(tmp_path):
    r = run_place(tmp_path, 'wide.step', place_parts(pcb_half_width=18.7))['report']        # PCB 0.1 from the side walls: no room, never forced
    assert any(m.startswith('NO_ROOM: pcb') for m in r['blocking_reasons'])
    s = run_place(tmp_path, 'solid.step', place_parts(solid_skin=True), report_only_parts=['bush', 'wheel'])
    r = s['report']
    assert r['shell_kind'] == 'solid_skin' and 'centre_xy' not in r['wheel_window'] and r['residuals']['wheel'] is None
    assert np.allclose(r['translation_mm'], -OFF, atol=0.03) and r['blocking_reasons'] == [], r['blocking_reasons']
    assert r['switches'][0]['vertical_gap_to_ceiling_mm'] == pytest.approx(30 - 20 - 1.2, abs=0.05)     # outer skin - planned wall
    assert r['clearance']['wheel']['min_clearance_mm'] < 0                                   # through the uncut window: reported only
    tilted = place_parts()
    tilted['pcb'] = placed(tilted['pcb'], rot_y_deg=2.0)
    r = run_place(tmp_path, 't.step', tilted)['report']
    assert any(m.startswith('PCB_NOT_LEVEL') for m in r['blocking_reasons']) and run_place(tmp_path, 't2.step', tilted)['files']['pack'] == 'candidate_pack.step'


def write_stl(path, V, T):
    import struct
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    n = np.cross(b - a, c - a)
    n /= np.linalg.norm(n, axis=1)[:, None] + 1e-12
    with open(path, 'wb') as f:
        f.write(b'\0' * 80 + struct.pack('<I', len(T)))
        for k in range(len(T)):
            f.write(struct.pack('<12fH', *n[k], *a[k], *b[k], *c[k], 0))


def test_board_place_flush_on_a_scanned_bottom_plate_region(tmp_path):
    """Closed top-shell skin from z 8 (above the bush) + the bottom plate only as a scan region mesh: the bush flushes on the mesh front, the
    floor is the region's low z, the PCB under the top shell is bottom-plate territory (not checked)."""
    ps = place_parts(solid_skin=True)
    ps['topcase'] = box(0, -20, 8, 60, 20, 30)
    V, T = WP.outward_mesh(box(0, -20, 0, 60, 20, 8), 0.05)
    write_stl(tmp_path / 'bottom.stl', V, T)
    W.write(tmp_path / 'r.step', list(ps.items()))
    prm = place_params(floor_z=None, report_only_parts=['bush', 'wheel'])
    r = WP.run({'inputs': {'step_0': str(tmp_path / 'r.step'), 'floor_region': str(tmp_path / 'bottom.stl')}, 'params': prm, 'out_dir': str(tmp_path / 'o')})['report']
    assert r['floor']['source'] == 'p1 z of floor_region_path' and r['blocking_reasons'] == [], r['blocking_reasons']
    assert np.allclose(r['translation_mm'], -OFF, atol=0.03) and r['residuals']['bush_flush']['found'] >= 6
    assert r['clearance']['pcb']['checked_points'] == 0 and r['clearance']['pcb']['below_shell_points'] > 0


def test_board_place_validation_and_end_to_end(tmp_path):
    W.write(tmp_path / 'h.step', list(place_parts().items()))
    kw = {k: v for k, v in place_params().items() if k in ('shell_part', 'pack_parts', 'sensor_part', 'floor_datum_part', 'pcb_part', 'floor_z', 'bush_part',
                                                           'wheel_parts', 'seed_switch_parts', 'switch_part', 'switch_pcb_part', 'plate_parts', 'report_only_parts')}
    S = 'BOARD_PLACE_SETTINGS'
    rejects(S, lambda: MP.board_place(tmp_path, ['h.step'], **{**kw, 'floor_z': None}))                      # a floor source is required
    rejects(S, lambda: MP.board_place(tmp_path, ['h.step'], **kw, floor_part='plate'))                      # only one floor source
    rejects(S, lambda: MP.board_place(tmp_path, ['h.step'], **{**kw, 'sensor_part': 'topcase'}))             # datum parts move with the pack
    rejects(S, lambda: MP.board_place(tmp_path, ['h.step'], **{**kw, 'plate_parts': None}))                  # seeds need a click source
    rejects(S, lambda: MP.board_place(tmp_path, ['h.step'], **{**kw, 'bush_part': None}, x_rule='bush_flush'))
    rejects(S, lambda: MP.board_place(tmp_path, ['h.step'], **kw, x_rule='bogus'))
    rejects(S, lambda: MP.board_place(tmp_path, ['h.step'], **kw, nonsense=1))
    for k in ('shell_part', 'sensor_part', 'floor_datum_part', 'pcb_part'):
        rejects(S, lambda k=k: MP.board_place(tmp_path, ['h.step'], **{a: b for a, b in kw.items() if a != k}))
    r = MP.board_place(tmp_path, ['h.step'], **kw)
    assert r['status'] == 'READY' and r['board_place_id'].startswith('pl_') and (tmp_path / r['outputs']['pack']['relative_path']).is_file()
    assert MP.board_place(tmp_path, ['h.step'], **kw)['cached']
