"""brain_mouse_carve_shell on a synthetic filled shell (box with a click-plate recess bounded by one B-spline outline step face): roles, the one-cavity
cut with floor offset, step fillet, window + sill, gates and report. Worker in this process (needs OCP + scipy + vtk + matplotlib: extra `geometry`);
one end-to-end call of the module function (server python subprocess, tmp workspace, cached second call).
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pytest
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import mouse_carve_shell as MC

pytest.importorskip('OCP')
pytest.importorskip('vtk')
pytest.importorskip('scipy')
pytest.importorskip('matplotlib')
from cadmcp_brain.studio import cad_brep_lib as L  # noqa: E402
from cadmcp_brain.studio import mouse_carve_shell_worker as W  # noqa: E402

T = 1.2
FAST = {'grid': [121, 81], 'poles': [41, 31], 'face_samples': 120, 'floor_fill_samples': 120, 'floor_samples': 120, 'floor_poles': 31,
        'wall_face_min_area_mm2': 500.0, 'audit_samples': 6000, 'reference_samples': 1500, 'deflection_mm': 0.02}


def box(x0, y0, z0, x1, y1, z1):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    return L.solids(BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape())[0]


def filled_shell():
    """60 x 40 x 20 block (bottom z = 0 = bearing) with a 3 mm deep recess bounded by a closed B-spline outline (step face = linear extrusion)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    a = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    P = np.c_[45 + 8 * np.cos(a), 12 * np.sin(a), np.full(len(a), 17.0)]
    _, w = W.closed_curve_wire(P)
    rec = W.prism_of_wire(w, (0, 0, 10))
    return L.solids(BRepAlgoAPI_Cut(box(0, -20, 0, 60, 20, 20), rec).Shape())[0]


@pytest.fixture(scope='module')
def ws(tmp_path_factory):
    d = tmp_path_factory.mktemp('carve')
    L.write_step(filled_shell(), d / 'shell.step')
    L.write_step(box(43, -2, 5, 47, 2, 25), d / 'wheel.step')               # through the floor
    a = np.linspace(0, 2 * np.pi, 32, endpoint=False)                       # side-button window prism along +y through the -y wall
    _, w = W.closed_curve_wire(np.c_[45 + 5 * np.cos(a), np.full(len(a), -25.0), 16.25 + 2.25 * np.sin(a)])
    L.write_step(W.prism_of_wire(w, (0, 10, 0)), d / 'side.step')
    return d


@pytest.fixture(scope='module')
def carved(ws):
    req = {'inputs': {'shell': str(ws / 'shell.step'), 'window_0': str(ws / 'wheel.step'), 'window_1': str(ws / 'side.step'),
                      'reference': str(ws / 'shell.step')},
           'params': {**FAST, 'windows': [{'type': 'wheel'}, {'type': 'side_button', 'sill': {'drop_mm': 4.0, 'depth_mm': 16.0, 'margin_mm': 0.3}}]},
           'out_dir': str(ws / 'out')}
    return W.run(req), ws / 'out'


def test_roles_found_automatically(carved):
    r = carved[0]['report']['roles']
    rows = {x['index']: x for x in carved[0]['report']['face_table']}
    assert len(r['step']) == 1 and rows[r['step'][0]]['extrusion']
    assert len(r['floor']) == 1 and rows[r['floor'][0]]['mean_normal'][2] > 0.99
    assert len(r['bearing']) == 1 and rows[r['bearing'][0]]['mean_normal'][2] < -0.99
    assert len(r['wall']) == 5          # top + four sides


def test_one_valid_solid_and_outputs(carved):
    res, out = carved
    r = res['report']
    assert r['solid_count'] == 1 and r['valid'] and r['free_edges'] == 0
    assert r['step_round_trip']['solids'] == 1 and r['step_round_trip']['valid']
    for f in res['files'].values():
        assert (out / f).is_file()
    assert len(L.solids(L.read_step(out / 'cavity.step'))) == 1
    v = r['volume']
    assert 0 < v['shell_brep_mm3'] < 0.5 * v['input_brep_mm3']
    assert v['removed_by_cavity_mesh_mm3'] > 0 and v['removed_by_windows_and_fillet_mesh_mm3'] > 0


def test_wall_and_floor_thickness(carved):
    r = carved[0]['report']
    assert abs(r['wall_thickness']['p50'] - T) < 0.05
    assert abs(r['floor_thickness']['p50'] - T) < 0.03
    assert r['floor_thickness']['frac_within_0.1'] > 0.9
    assert r['outer_skin_deviation']['max'] < 0.03     # skin kept (mesh distance, deflection 0.02)


def test_floor_sheet_step_fillet_window_and_sill(carved):
    r = carved[0]['report']
    assert r['floor_K']['vertical_coverage_misses'] == 0 and r['floor_K']['height_fit_residual']['max'] < 1e-3
    assert r['step_fillet']['edges'] >= 1 and r['step_fillet']['radius_mm'] == T
    assert all(w['removed_mm3'] > 0 for w in r['windows'])
    assert r['sills'][0]['applied'] and r['sills'][0]['removed_mm3'] > 0
    assert r['cavity_G']['split_pieces'] == 2
    assert r['verdict'] in ('PASS', 'WARN') and all(r['checks'][k] == 'PASS' for k in ('one_solid', 'valid_after_round_trip', 'no_free_edges'))


def test_reference_comparison_reports_difference(carved):
    ref = carved[0]['report']['reference']       # vs the FILLED input: large volume and shape difference must show
    assert ref['volume_delta_mm3'] < -10000 and ref['deviation_max'] > 5.0


def test_window_must_cut_something(ws, tmp_path):
    L.write_step(box(200, 200, 200, 201, 201, 201), tmp_path / 'far.step')
    req = {'inputs': {'shell': str(ws / 'shell.step'), 'window_0': str(tmp_path / 'far.step')},
           'params': {**FAST, 'windows': [{'type': 'other'}]}, 'out_dir': str(tmp_path / 'out')}
    with pytest.raises(W.WorkerError) as exc:
        W.run(req)
    assert exc.value.code == 'CARVE_BOOLEAN'


def test_shell_without_click_recess_is_carved_with_the_wall_offset_everywhere(tmp_path):
    """No plate-outline step face (shell not split yet): no CARVE_ROLES error, cavity = G, floor / slot-band / fillet checks not applicable."""
    L.write_step(box(0, -20, 0, 60, 20, 20), tmp_path / 'plain.step')
    req = {'inputs': {'shell': str(tmp_path / 'plain.step')}, 'params': {**FAST}, 'out_dir': str(tmp_path / 'out')}
    res = W.run(req)
    r = res['report']
    assert r['click_recess'] is False and r['roles']['step'] == [] and r['roles']['floor'] == []
    assert r['solid_count'] == 1 and r['valid'] and r['free_edges'] == 0
    assert r['checks']['floor_p05_ge_T_minus_0.02'] == 'NA' and r['checks']['step_fillet_applied'] == 'NA' and r['verdict'] != 'FAIL'
    assert r['floor_K']['click_recess'] is False and abs(r['wall_thickness']['p50'] - T) < 0.1
    assert 0 < r['volume']['shell_brep_mm3'] < 0.5 * r['volume']['input_brep_mm3']


def test_step_without_floor_or_floor_without_step_is_refused(tmp_path):
    L.write_step(box(0, 0, 0, 30, 20, 10), tmp_path / 'plain.step')
    req = {'inputs': {'shell': str(tmp_path / 'plain.step')}, 'params': {**FAST, 'face_roles': {'floor': [0]}}, 'out_dir': str(tmp_path / 'out')}
    with pytest.raises(W.WorkerError) as exc:
        W.run(req)
    assert exc.value.code == 'CARVE_ROLES'


def test_role_hints_from_face_roles_json_and_split_report(tmp_path):
    import json
    rows = [{'index': i, 'role': 'parting' if i == 2 else 'shell' if i < 5 else 'slot'} for i in range(6)]
    fr = tmp_path / 'face_roles.json'
    fr.write_text(json.dumps({'top_shell': rows}), encoding='utf-8')
    sr = tmp_path / 'split.json'
    sr.write_text(json.dumps({'handoff': {'carve_face_roles': {'step': [3], 'floor': [4]}}}), encoding='utf-8')
    h = W.read_hints({'face_roles_json': str(fr), 'split_report': str(sr)}, 6)
    assert h['bearing'] == [2] and h['skin'] == [0, 1, 3, 4] and h['step'] == [3] and h['floor'] == [4] and h['used'] == ['face_roles_json', 'split_report']
    h = W.read_hints({'face_roles_json': str(fr), 'split_report': str(sr)}, 4)       # other face count: ignored, never trusted
    assert h['bearing'] is None and h['step'] is None and h['used'] == [] and len(h['ignored']) == 2
    sr.write_text(json.dumps({'unrelated': 1}), encoding='utf-8')
    assert W.read_hints({'split_report': str(sr)}, 6)['step'] is None


def test_hint_bearing_and_skin_are_used_when_roles_are_derived(tmp_path):
    L.write_step(box(0, -20, 0, 60, 20, 20), tmp_path / 'plain.step')
    S = L.one_solid(str(tmp_path / 'plain.step'), 'x')
    F = L.faces(S)
    rows, _ = W.face_table(S, F, 0.05)
    bot = [r['index'] for r in rows if r['mean_normal'][2] < -0.9][0]
    skin = [r['index'] for r in rows if r['index'] != bot][:2]
    R = W.roles(S, F, {**W.DEFAULTS}, rows, {'bearing': [bot], 'skin': skin})
    assert R['bearing'] == [bot] and set(R['wall']) <= set(skin) and R['sources']['bearing'] == 'hint' and R['click_recess'] is False


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code


def test_argument_validation(ws):
    root = ws
    rejects('CARVE_SETTINGS', lambda: MC.carve_shell(root, 'shell.step', wall_mm=0.0))
    rejects('CARVE_SETTINGS', lambda: MC.carve_shell(root, 'shell.step', grid=[50, 50], poles=[60, 40]))
    rejects('CARVE_SETTINGS', lambda: MC.carve_shell(root, 'shell.step', windows=[{'step': 'wheel.step', 'type': 'hole'}]))
    rejects('CARVE_SETTINGS', lambda: MC.carve_shell(root, 'shell.step', windows=[{'step': 'side.step', 'sill': {'drop_mm': 4.0}}]))
    rejects('CARVE_SETTINGS', lambda: MC.carve_shell(root, 'shell.step', face_roles={'roof': [1]}))
    rejects('CARVE_SETTINGS', lambda: MC.carve_shell(root, 'shell.step', ray_axes=[1, -1, 1]))
    (root / 'notes.txt').write_text('x', encoding='utf-8')
    rejects('CARVE_FILE', lambda: MC.carve_shell(root, 'notes.txt'))


def test_end_to_end_module_call_and_cache(ws):
    kw = dict(windows=[{'step': 'wheel.step', 'type': 'wheel'}], grid=[121, 81], poles=[41, 31], face_samples=120, floor_poles=31,
              wall_face_min_area_mm2=500.0)
    rep = MC.carve_shell(ws, 'shell.step', **kw)
    assert rep['status'] in ('READY', 'READY_WITH_WARNINGS') and rep['carve_id'].startswith('cv_')
    assert rep['solid_count'] == 1 and rep['outputs']['hollow_shell_step']['relative_path'].startswith('mouse/cad/cv_')
    assert (Path(ws) / rep['outputs']['hollow_shell_step']['relative_path']).is_file()
    again = MC.carve_shell(ws, 'shell.step', **kw)
    assert again.get('cached') and again['carve_id'] == rep['carve_id']


def test_several_step_faces_on_one_extrusion_surface_are_one_outline():
    from OCP.Geom import Geom_Circle, Geom_SurfaceOfLinearExtrusion
    from OCP.gp import gp_Ax2, gp_Pnt, gp_Dir
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    surf = Geom_SurfaceOfLinearExtrusion(Geom_Circle(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 10.0), gp_Dir(0, 0, 1))
    a = BRepBuilderAPI_MakeFace(surf, 0.0, 3.0, 0.0, 2.0, 1e-6).Face()
    b = BRepBuilderAPI_MakeFace(surf, 3.0, 6.28, 0.0, 2.0, 1e-6).Face()
    other = BRepBuilderAPI_MakeFace(Geom_SurfaceOfLinearExtrusion(Geom_Circle(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 11.0), gp_Dir(0, 0, 1)),
                                    0.0, 3.0, 0.0, 2.0, 1e-6).Face()
    assert W.same_extrusion([a, b], [0, 1])
    assert not W.same_extrusion([a, other], [0, 1])
