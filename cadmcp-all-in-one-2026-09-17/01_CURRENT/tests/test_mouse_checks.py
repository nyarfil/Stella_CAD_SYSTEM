"""brain_mouse_interference_report / brain_mouse_wall_audit / brain_mouse_section_render on synthetic boxes (no scan data, no V: files).
Worker runs are in this process (needs OCP + vtk: extra `geometry`; skipped when missing); one test per tool goes through Tools and the server
python subprocess.
"""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import mouse_checks as MC

pytest.importorskip('OCP')
pytest.importorskip('vtk')
pytest.importorskip('matplotlib')
from cadmcp_brain.studio import cad_brep_lib as L  # noqa: E402
from cadmcp_brain.studio import mouse_parts_lib as P  # noqa: E402
from cadmcp_brain.studio import mouse_interference_worker as WI  # noqa: E402
from cadmcp_brain.studio import mouse_wall_audit_worker as WW  # noqa: E402
from cadmcp_brain.studio import mouse_section_render_worker as WS  # noqa: E402


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code


def box(x0, y0, z0, x1, y1, z1):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    return L.solids(BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape())[0]


def cut(a, b):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    return L.solids(BRepAlgoAPI_Cut(a, b).Shape())[0]


def hollow(t):
    """Closed 20 x 20 x 10 box with a 20 - 2t cavity: every wall is t thick."""
    return cut(box(0, 0, 0, 20, 20, 10), box(t, t, t, 20 - t, 20 - t, 10 - t))


def named_step(path: Path, parts: dict) -> Path:
    grey = (0.6, 0.6, 0.6)
    L.write_colored_step([(n, s, [grey] * len(L.faces(s)), grey) for n, s in parts.items()], path)
    return path


@pytest.fixture(scope='module')
def asm(tmp_path_factory):
    d = tmp_path_factory.mktemp('asm')
    named_step(d / 'asm.step', {
        'base': box(0, 0, 0, 10, 10, 10),
        'near': box(10.5, 0, 0, 20, 10, 10),          # 0.5 gap to base
        'touch': box(-5, 0, 0, 0, 10, 10),            # face contact with base
        'over': box(5, 5, 9, 15, 15, 19),             # 5 x 5 x 1 = 25 mm3 into base
        'cross': box(-30, 4.5, 4.5, -10, 5.5, 5.5)})  # far away (moved into base by the second file)
    L.write_step(box(-2, 4.5, 4.5, 12, 5.5, 5.5), d / 'rod.step')   # crosses base: no rod vertex lies inside base
    return d


def run_worker(W, tmp, inputs, params):
    out = tmp / 'out'
    return W.run({'inputs': {k: str(v) for k, v in inputs.items()}, 'params': params, 'out_dir': str(out)}), out


def test_parts_named_from_labels_and_file_stem(asm):
    parts, table = P.load_parts([str(asm / 'asm.step'), str(asm / 'rod.step')], {'beam': ['rod*']})
    assert set(parts) == {'base', 'near', 'touch', 'over', 'cross', 'beam'}
    assert {r['name']: r['file'] for r in table}['beam'] == 'rod.step'


def test_interference_rows_gap_contact_overlap_and_crossing(asm, tmp_path):
    pairs = [{'a': 'base', 'b': 'near'}, {'a': 'base', 'b': 'touch', 'clearance_mm': 0.0}, {'a': 'base', 'b': 'over'}, {'a': 'base', 'b': 'rod'},
             {'a': 'base', 'b': 'cross'}, {'a': 'base', 'b': 'near', 'clearance_mm': 0.6}]
    res, out = run_worker(WI, tmp_path, {'step_0': asm / 'asm.step', 'step_1': asm / 'rod.step'}, {'pairs': pairs})
    r = res['rows']
    assert r[0]['result'] == 'PASS' and abs(r[0]['min_dist_mm'] - 0.5) < 0.01 and r[0]['overlap_mm3'] == 0.0
    assert r[1]['result'] == 'PASS' and r[1]['min_dist_mm'] < 0.01 and r[1]['overlap_mm3'] < 0.01           # intended contact
    assert r[2]['result'] == 'FAIL' and abs(r[2]['overlap_mm3'] - 25.0) < 0.05 and r[2]['min_dist_mm'] == 0.0
    assert r[3]['result'] == 'FAIL' and abs(r[3]['overlap_mm3'] - 10.0) < 0.05                               # crossing rod (1 x 1 x 10)
    assert r[4]['result'] == 'PASS' and r[4]['method'] == 'bbox' and r[4]['min_dist_mm'] >= 10.0
    assert r[5]['result'] == 'FAIL' and r[5]['required_mm'] == 0.6
    assert res['summary'] == {'pairs': 6, 'pass': 3, 'fail': 3}
    assert (out / 'interference_table.md').is_file() and (out / 'interference_table.png').is_file()


def test_interference_all_pairs_wildcard_and_within(asm, tmp_path):
    res, _ = run_worker(WI, tmp_path, {'step_0': asm / 'asm.step'}, {'parts': ['base', 'near', 'touch']})
    assert [(x['part_a'], x['part_b']) for x in res['rows']] == [('base', 'near'), ('base', 'touch'), ('near', 'touch')]
    res, _ = run_worker(WI, tmp_path / 'b', {'step_0': asm / 'asm.step'}, {'pairs': [{'a': 'base', 'b': '*', 'within_mm': 1.0}]})
    assert sorted(x['part_b'] for x in res['rows']) == ['near', 'over', 'touch']


def test_wall_audit_finds_the_wall_and_mass(tmp_path):
    L.write_step(hollow(1.2), tmp_path / 'shell.step')
    res, out = run_worker(WW, tmp_path, {'shell': tmp_path / 'shell.step'}, {'target_thickness_mm': 1.2, 'samples': 4000})
    s = res['stats']
    assert abs(s['mode_mm'] - 1.2) < 0.01 and abs(s['median_mm'] - 1.2) < 0.01 and s['rays_without_exit'] == 0
    assert res['checks']['dominant_wall_is_target'] == 'PASS' and res['checks']['dominant_wall_is_line_width_multiple'] == 'PASS'
    vol = 20 * 20 * 10 - 17.6 * 17.6 * 7.6
    assert abs(res['mass']['mesh_volume_mm3'] - vol) < 0.5 and abs(res['mass']['mass_g'] - vol * 1.04 / 1000) < 0.002
    assert (out / 'wall_heatmap.png').is_file()


def test_wall_audit_flags_wrong_target_and_off_grid_wall(tmp_path):
    L.write_step(hollow(1.1), tmp_path / 'shell.step')
    res, _ = run_worker(WW, tmp_path, {'shell': tmp_path / 'shell.step'}, {'target_thickness_mm': 1.2, 'samples': 3000})
    assert res['checks']['dominant_wall_is_target'] == 'FAIL' and res['checks']['dominant_wall_is_line_width_multiple'] == 'FAIL'
    assert res['stats']['off_line_width_grid_pct'] > 80


def test_section_fills_loops_and_reports_misses(asm, tmp_path):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Pnt, gp_Dir
    holed = cut(box(0, 0, 0, 10, 10, 10), BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(5, -1, 5), gp_Dir(0, 1, 0)), 2.0, 12).Shape())
    named_step(tmp_path / 'h.step', {'holed': holed, 'away': box(0, 30, 0, 5, 35, 5)})
    res, out = run_worker(WS, tmp_path, {'step_0': tmp_path / 'h.step'},
                          {'plane': {'kind': 'XZ', 'offset': 5.0}, 'dimensions': [{'from': [0, 5, 0], 'to': [0, 5, 10]}]})
    rows = {r['part']: r for r in res['parts_shown']}
    assert rows['holed']['closed_loops'] == 2 and rows['away']['cut'] is False
    assert abs(rows['holed']['loop_area_sum_mm2'] - (100 + 3.14159 * 4)) < 0.2         # outer + hole loop
    assert res['dimensions'][0]['label'] == '10.00' and res['plane']['axis_labels'] == ['x', 'z']
    assert (out / 'section.png').is_file()
    fr = WS.plane_frame({'kind': 'axis', 'point': [0, 0, 0], 'direction': [0, 0, 2], 'normal': [0, 1, 1]})
    assert abs(fr['n'] @ fr['v']) < 1e-12 and abs(fr['v'][2] - 1) < 1e-12


def test_tools_validate_before_running(tmp_path):
    t = Tools(Brain(tmp_path))
    (tmp_path / 'a.step').write_text('x')
    (tmp_path / 'a.txt').write_text('x')
    rejects('INTERFERENCE_FILE', lambda: t.call('brain_mouse_interference_report', {'step_paths': ['a.txt']}))
    rejects('INTERFERENCE_FILE', lambda: t.call('brain_mouse_interference_report', {'step_paths': []}))
    rejects('INTERFERENCE_SETTINGS', lambda: t.call('brain_mouse_interference_report', {'step_paths': ['a.step'], 'pairs': [{'a': 'x'}]}))
    rejects('INTERFERENCE_SETTINGS', lambda: t.call('brain_mouse_interference_report', {'step_paths': ['a.step'], 'clearance_mm': -1}))
    rejects('WALL_AUDIT_SETTINGS', lambda: t.call('brain_mouse_wall_audit', {'shell_step_path': 'a.step', 'target_thickness_mm': 0}))
    rejects('SECTION_PLANE', lambda: t.call('brain_mouse_section_render', {'step_paths': ['a.step'], 'plane': {'kind': 'ZZ'}}))
    rejects('SECTION_PLANE', lambda: t.call('brain_mouse_section_render', {'step_paths': ['a.step'], 'plane': {'kind': 'axis', 'point': [0, 0]}}))


def test_tools_end_to_end_with_cache(asm, tmp_path):
    (tmp_path / 'in').mkdir()
    (tmp_path / 'in' / 'asm.step').write_bytes((asm / 'asm.step').read_bytes())
    L.write_step(hollow(1.2), tmp_path / 'in' / 'shell.step')
    t = Tools(Brain(tmp_path))
    args = {'step_paths': ['in/asm.step'], 'pairs': [{'a': 'base', 'b': 'near'}, {'a': 'base', 'b': 'over'}]}
    r = t.call('brain_mouse_interference_report', args)
    assert r['status'] == 'FAIL' and r['summary']['fail'] == 1 and r['interference_id'].startswith('if_')
    for item in r['outputs'].values():
        assert (tmp_path / item['relative_path']).is_file() and len(item['sha256']) == 64
    assert t.call('brain_mouse_interference_report', args)['cached'] is True
    w = t.call('brain_mouse_wall_audit', {'shell_step_path': 'in/shell.step', 'target_thickness_mm': 1.2, 'samples': 2000})
    assert w['status'] in ('PASS', 'WARN') and w['checks']['dominant_wall_is_target'] == 'PASS' and 'heatmap_png' in w['outputs']
    s = t.call('brain_mouse_section_render', {'step_paths': ['in/asm.step'], 'parts': ['base', 'over'], 'plane': {'kind': 'YZ', 'offset': 7.0}})
    assert s['status'] == 'READY' and json.loads(json.dumps(s['parts_shown']))[0]['cut'] is True
    assert (tmp_path / s['outputs']['section_png']['relative_path']).is_file()
    assert not list((tmp_path / 'mouse' / 'checks').glob('*.tmp-*'))
    names = {x['name'] for x in t.list()}
    assert {'brain_mouse_interference_report', 'brain_mouse_wall_audit', 'brain_mouse_section_render'} <= names
    assert MC.CHECKS_VERSION == 'MC1.0'


def test_mesh_intersection_cross_check(asm):
    parts, _ = P.load_parts([str(asm / 'asm.step')])
    prm = dict(WI.DEFAULTS)
    a, b, c = WI.Part('base', parts['base'], prm), WI.Part('over', parts['over'], prm), WI.Part('touch', parts['touch'], prm)
    assert abs(WI.mesh_common_volume(a, b) - 25.0) < 0.05          # the fallback used when the OCC common fails or exceeds a part
    assert WI.mesh_common_volume(a, c) < 0.01                       # face contact is no overlap
