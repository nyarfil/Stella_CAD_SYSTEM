"""brain_mouse_wheel_window on synthetic geometry (a flat slab as top shell, a cylinder as wheel; no scan data, no V: files).
The worker runs in this process (OCP + vtk: extra `geometry`; skipped when missing); one test goes through the module function and the server python
subprocess. The module function is called directly (the tool is registered by the integrator).
"""
from __future__ import annotations
from pathlib import Path
import pytest
from cadmcp_brain.errors import BrainError

pytest.importorskip('OCP')
pytest.importorskip('vtk')
from cadmcp_brain.studio import cad_brep_lib as L  # noqa: E402
from cadmcp_brain.studio import mouse_wheel_window as MW  # noqa: E402
from cadmcp_brain.studio import mouse_wheel_window_worker as WW  # noqa: E402
from cadmcp_brain.studio.scan_cad_common import WorkerError  # noqa: E402


def box(x0, y0, z0, x1, y1, z1):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    return L.solids(BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape())[0]


def cut(a, b):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    return L.solids(BRepAlgoAPI_Cut(a, b).Shape())[0]


def wheel_cyl(cx=30.0, cz=12.0, r=8.0, half=2.5):
    """Cylinder with its axis along Y."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Pnt, gp_Dir
    return L.solids(BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(cx, -half, cz), gp_Dir(0, 1, 0)), r, 2 * half).Shape())[0]


def write(path: Path, parts: dict) -> Path:
    grey = (0.6, 0.6, 0.6)
    L.write_colored_step([(n, s, [grey] * len(L.faces(s)), grey) for n, s in parts.items()], path)
    return path


def slab(window=None):
    s = box(0, -15, 10, 60, 15, 11.3)
    return s if window is None else cut(s, box(window[0], window[2], 0, window[1], window[3], 30))


@pytest.fixture()
def raw(tmp_path):
    """Closed slab (no window), the wheel pokes through it, one far part."""
    return write(tmp_path / 'raw.step', {'top_shell': slab(), 'wheel_part2': wheel_cyl(), 'far': box(0, -5, 0, 5, 5, 3)})


@pytest.fixture()
def windowed(tmp_path):
    """Slab with a 20 x 8.32 window at x 20..40 (rear edge 20), rounded corners are not needed for the widen test."""
    return write(tmp_path / 'win.step', {'top_shell': slab((20, 40, -4.16, 4.16)), 'wheel_part2': wheel_cyl(), 'far': box(0, -5, 0, 5, 5, 3)})


def req(step, mode, tmp_path, **kw):
    prm = dict(mode=mode, shell_part='top_shell', plate_parts=[], wheel_parts=['wheel_part2'], clearance_mm=0.3, corner_radius_mm=3.33, near_margin_mm=5.0)
    prm.update(kw)
    return {'inputs': {'step_0': str(step)}, 'params': prm, 'out_dir': str(tmp_path / 'out')}


def test_rect_from_wheel_clears_wheel_by_clearance(raw, tmp_path):
    r = WW.run(req(raw, 'rect_from_wheel', tmp_path, half_width_mm=4.16))
    assert r['gates_ok'] and r['status_window'] == 'OK'
    w = r['window']
    assert w['window_before']['found'] is False and w['window_after']['found'] is True
    x0, x1 = w['window_after']['x_range']
    # wheel + 0.3 clearance at the slab: |x - 30| <= sqrt(8.3^2 - dz^2) ~ 8.06..8.27 -> window at least 21.73 .. 38.27
    assert x0 <= 21.75 and x1 >= 38.25 and x0 > 18.0 and x1 < 42.0
    assert w['window_after']['y_range'][1] == pytest.approx(4.16, abs=0.01)
    cut_row = r['cuts'][0]
    assert cut_row['removed_mm3'] == pytest.approx(cut_row['common_volume_mm3'], abs=0.05)
    assert cut_row['gates'] == {'solid_count_1': True, 'valid': True, 'removed_equals_common': True}
    rc = r['rear_clearance']
    assert rc['clearance_met'] is True and rc['per_wheel_part_exact_mm']['wheel_part2'] >= 0.3 - 1e-3
    assert r['step_round_trip']['unchanged_max_volume_change_mm3'] < 1e-3 and r['step_round_trip']['unchanged_max_centre_shift_mm'] < 1e-3
    assert r['step_round_trip']['cut_parts'][0]['ok'] and (tmp_path / 'out' / r['files']['assembly_step']).is_file()


def test_widen_rear_moves_only_the_rear_edge(windowed, tmp_path):
    r = WW.run(req(windowed, 'widen_rear', tmp_path, delta_mm=1.0))
    w = r['window']
    assert w['window_before']['x_range'][0] == pytest.approx(20.0, abs=0.01)
    assert w['window_after']['x_range'][0] == pytest.approx(19.0, abs=0.01)
    assert w['window_after']['x_range'][1] == pytest.approx(40.0, abs=0.01)          # front edge untouched
    assert w['window_after']['y_range'][1] == pytest.approx(4.16, abs=0.01)
    assert w['tool']['rounded_corners'] == 'rear'
    assert r['gates_ok'] and r['cuts'][0]['removed_mm3'] > 0.5


def test_rect_from_wheel_without_intrusion_is_reported_not_cut(tmp_path):
    p = write(tmp_path / 'wide.step', {'top_shell': slab((10, 50, -6, 6)), 'wheel_part2': wheel_cyl(), 'far': box(0, -5, 0, 5, 5, 3)})
    r = WW.run(req(p, 'rect_from_wheel', tmp_path))
    assert r['status_window'] == 'NO_CHANGE_NEEDED' and r['cuts'] == [] and r['gates_ok']
    assert r['window']['window_after']['x_range'] == r['window']['window_before']['x_range']


def test_explicit_rect_cut_is_gated_and_plates_are_cut_too(tmp_path):
    p = write(tmp_path / 'pl.step', {'top_shell': slab(), 'plate': box(0, -15, 8.5, 60, 15, 9.6), 'wheel_part2': wheel_cyl()})
    r = WW.run(req(p, 'explicit', tmp_path, plate_parts=['plate'], rect=[22.0, 38.0, -4.0, 4.0]))
    assert r['gates_ok']
    assert [c['part'] for c in r['cuts']] == ['top_shell', 'plate'] and all(c['changed'] for c in r['cuts'])
    assert r['window']['window_after']['x_range'][0] == pytest.approx(22.0, abs=0.01)
    assert r['step_round_trip']['unchanged_max_volume_change_mm3'] < 1e-3


def test_cut_that_misses_the_shell_is_an_error_not_a_silent_no_op(raw, tmp_path):
    with pytest.raises(WorkerError) as e:
        WW.run(req(raw, 'explicit', tmp_path, rect=[100.0, 110.0, -4.0, 4.0]))
    assert e.value.code == 'WINDOW_NO_EFFECT'


def test_radius_that_does_not_fit_is_rejected(raw, tmp_path):
    with pytest.raises(WorkerError) as e:
        WW.run(req(raw, 'explicit', tmp_path, rect=[22.0, 38.0, -2.0, 2.0]))
    assert e.value.code == 'WINDOW_RADIUS'


def test_module_validation(tmp_path):
    (tmp_path / 'a.step').write_text('x', encoding='utf-8')
    for kw, code in (({'mode': 'nope'}, 'WHEEL_WINDOW_SETTINGS'), ({'mode': 'widen_rear'}, 'WHEEL_WINDOW_SETTINGS'),
                     ({'mode': 'explicit', 'rect': [3, 2, 0, 1]}, 'WHEEL_WINDOW_SETTINGS'), ({'clearance_mm': -1.0}, 'WHEEL_WINDOW_SETTINGS')):
        with pytest.raises(BrainError) as e:
            MW.wheel_window(tmp_path, ['a.step'], **kw)
        assert e.value.code == code
    with pytest.raises(BrainError) as e:
        MW.wheel_window(tmp_path, ['missing.step'])
    assert e.value.code in ('UNSAFE_PATH', 'WHEEL_WINDOW_FILE')
    with pytest.raises(BrainError) as e:                       # no hidden LH2 part names: shell_part / wheel_parts are required
        MW.wheel_window(tmp_path, ['a.step'])
    assert e.value.code == 'WHEEL_WINDOW_SETTINGS' and 'required' in e.value.message
    with pytest.raises(BrainError) as e:
        MW.wheel_window(tmp_path, ['a.step'], shell_part='s', wheel_parts=['w'], front_axis='up')
    assert e.value.code == 'WHEEL_WINDOW_SETTINGS'


def test_module_end_to_end_stores_report_and_caches(windowed, tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    (ws / 'win.step').write_bytes(windowed.read_bytes())
    rep = MW.wheel_window(ws, ['win.step'], mode='widen_rear', delta_mm=1.0, shell_part='top_shell', wheel_parts=['wheel_part2'], corner_radius_mm=3.33)
    assert rep['status'] == 'PASS' and rep['window_status'] == 'OK' and rep['wheel_window_id'].startswith('ww_')
    assert rep['window']['window_after']['x_range'][0] == pytest.approx(19.0, abs=0.01)
    folder = ws / 'mouse' / 'cad' / rep['wheel_window_id']
    assert (folder / 'wheel_window_report.json').is_file() and (folder / rep['outputs']['assembly_step']['file']).is_file()
    again = MW.wheel_window(ws, ['win.step'], mode='widen_rear', delta_mm=1.0, shell_part='top_shell', wheel_parts=['wheel_part2'], corner_radius_mm=3.33)
    assert again.get('cached') is True and again['wheel_window_id'] == rep['wheel_window_id']


# ---------------------------------------------------------------- generality: moved, scaled and rotated models (no LH2 coordinates, no front = +x)
def place(shape, scale=1.0, dx=0.0, dy=0.0, rot_deg=0.0):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf, gp_Vec, gp_Ax1, gp_Pnt, gp_Dir
    t = gp_Trsf()
    t.SetScale(gp_Pnt(0, 0, 0), scale)
    r = gp_Trsf()
    r.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), rot_deg * 3.141592653589793 / 180)
    m = gp_Trsf()
    m.SetTranslation(gp_Vec(dx, dy, 0))
    return L.solids(BRepBuilderAPI_Transform(BRepBuilderAPI_Transform(BRepBuilderAPI_Transform(shape, t).Shape(), r).Shape(), m).Shape())[0]


def moved_model(tmp_path, name, **kw):
    parts = {'my_shell': slab((20, 40, -4.16, 4.16)), 'my_wheel': wheel_cyl(), 'far': box(0, -5, 0, 5, 5, 3)}
    return write(tmp_path / name, {n: place(s, **kw) for n, s in parts.items()})


def run_widen(step, tmp_path, **kw):
    prm = dict(mode='widen_rear', shell_part='my_shell', plate_parts=[], wheel_parts=['my_wheel'], clearance_mm=0.3, near_margin_mm=5.0)
    prm.update(kw)
    return WW.run({'inputs': {'step_0': str(step)}, 'params': prm, 'out_dir': str(tmp_path / ('out_' + step.stem))})


def test_widen_rear_is_invariant_to_shift_scale_and_front_axis(tmp_path):
    base = run_widen(moved_model(tmp_path, 'base.step'), tmp_path, delta_mm=1.0, corner_radius_mm=3.33)
    assert base['gates_ok'] and base['cuts'][0]['removed_mm3'] > 0.5
    for tag, kw, extra in (('shift', dict(dx=-300.0, dy=57.0), dict(front_axis='+x')),
                           ('rot180', dict(rot_deg=180.0, dx=10.0, dy=-20.0), dict(front_axis='-x')),
                           ('rot90', dict(rot_deg=90.0, dy=33.0), dict(front_axis='+y')),
                           ('rotm90', dict(rot_deg=-90.0, dx=5.0), dict(front_axis='-y'))):
        r = run_widen(moved_model(tmp_path, tag + '.step', **kw), tmp_path, delta_mm=1.0, corner_radius_mm=3.33, **extra)
        assert r['gates_ok'], tag
        assert r['cuts'][0]['removed_mm3'] == pytest.approx(base['cuts'][0]['removed_mm3'], rel=2e-3), tag
        assert r['window']['tool']['rounded_corners'] == 'rear'
        assert r['window']['window_before'] ['found'] and r['window']['window_after']['found']
    # the argument matters: the model rotated 180 deg read with front_axis +x widens the other end (min x) of the window
    wrong = run_widen(moved_model(tmp_path, 'wrong.step', rot_deg=180.0), tmp_path, delta_mm=1.0, corner_radius_mm=3.33, front_axis='+x')
    xa, xb = wrong['window']['window_after']['x_range'], wrong['window']['window_before']['x_range']
    assert xa[0] == pytest.approx(xb[0] - 1.0, abs=0.01) and xa[1] == pytest.approx(xb[1], abs=0.01)


def test_scaled_model_with_derived_corner_radius(tmp_path):
    k = 1.6
    r = run_widen(moved_model(tmp_path, 'big.step', scale=k, dy=-41.0), tmp_path, delta_mm=1.0 * k)
    assert r['gates_ok']
    assert r['window']['corner_radius_source'].startswith('0.8')
    assert r['window']['tool']['corner_radius_mm'] == pytest.approx(0.8 * 4.16 * k, abs=1e-3)           # 0.8 x half width, follows the window
    assert r['window']['window_after']['x_range'][0] == pytest.approx(20.0 * k - 1.0 * k, abs=0.01)


def test_rect_from_wheel_follows_a_shifted_model(tmp_path):
    ref = WW.run({'inputs': {'step_0': str(write(tmp_path / 'r0.step', {'my_shell': slab(), 'my_wheel': wheel_cyl()}))},
                  'params': dict(mode='rect_from_wheel', shell_part='my_shell', plate_parts=[], wheel_parts=['my_wheel'], clearance_mm=0.3, half_width_mm=4.16,
                                 corner_radius_mm=3.33, near_margin_mm=5.0), 'out_dir': str(tmp_path / 'o_r0')})
    p = write(tmp_path / 'r1.step', {'my_shell': place(slab(), dx=120.0, dy=-60.0, rot_deg=90.0), 'my_wheel': place(wheel_cyl(), dx=120.0, dy=-60.0, rot_deg=90.0)})
    r = WW.run({'inputs': {'step_0': str(p)}, 'params': dict(mode='rect_from_wheel', shell_part='my_shell', plate_parts=[], wheel_parts=['my_wheel'], clearance_mm=0.3,
                half_width_mm=4.16, corner_radius_mm=3.33, near_margin_mm=5.0, front_axis='+y'), 'out_dir': str(tmp_path / 'o_r1')})
    assert ref['gates_ok'] and r['gates_ok']
    assert r['cuts'][0]['removed_mm3'] == pytest.approx(ref['cuts'][0]['removed_mm3'], rel=2e-3)
