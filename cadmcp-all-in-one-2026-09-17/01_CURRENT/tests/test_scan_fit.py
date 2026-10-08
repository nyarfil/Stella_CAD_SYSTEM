"""Scan -> hollow shell, stage A2 (route smooth_fit): synthetic meshes, no network, no private files."""
from __future__ import annotations
import json
import sys
from pathlib import Path
import numpy as np
import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import scan_fit as sf
from cadmcp_brain.studio import scan_mesh as sm
from cadmcp_brain.studio import scan_shell as sh

sys.path.insert(0, str(Path(__file__).parent))
import scan_shapes as S  # noqa: E402


def opening(z: float) -> dict:
    return {'type': 'plane', 'point': [0.0, 0.0, z], 'normal': [0.0, 0.0, -1.0]}


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code
    return exc.value


def prep(tmp_path, v, f, name='a.stl'):
    S.write_stl(tmp_path / name, v, f)
    return sh.prepare_scan(tmp_path, name, 'mm')


def _mouse(tmp_path, n=14):
    v, f = S.superellipsoid(24.0, 14.0, 9.0, 0.6, n)
    return prep(tmp_path, v, f), v, f


def _u_scan():
    occ = np.ones((12, 12, 8), bool)
    occ[4:8, 4:, :] = False  # U shape in the XY section, open towards +y
    return S.lattice_union(occ, 3.0, (-18.0, -18.0, -12.0))


# ------------------------------------------------------------------ pure geometry
def test_hemisphere_map_boundary_is_the_equator_and_has_no_pole_at_the_top():
    d, bnd = sf.hemisphere_directions(21)
    assert np.allclose(np.linalg.norm(d, axis=-1), 1.0, atol=1e-12)
    assert (d[bnd][:, 2] == 0).all() and (d[~bnd][:, 2] > 0).all()
    assert d[10, 10].tolist() == pytest.approx([0, 0, 1.0])  # the square centre is the top, an ordinary regular point
    corners = d[[0, 0, -1, -1], [0, -1, 0, -1]]
    assert np.allclose(np.abs(corners[:, :2]), np.sqrt(0.5))  # four distinct rim corners at 45 degrees


def test_section_centroid_and_ray_grid_on_a_box_hit_the_surface_exactly():
    v, f = S.box((40.0, 30.0, 20.0), 3)
    vl = v + np.array([6.0, 0.0, 5.0])  # local plane z = 0 cuts the box 5 mm above its bottom face (box spans z -5..15)
    rg = sf.ray_grid(vl, f, 15)
    assert not rg['fail_mask'].any() and (rg['hit_counts'] == 1).all()
    assert rg['centre_local_mm'][0] == pytest.approx(6.0, abs=1e-9) and rg['section_area_mm2'] == pytest.approx(40 * 30)
    pts = rg['points'].reshape(-1, 3)
    assert sm.MeshDistance(vl, f).distance(pts).max() < 1e-9
    assert (pts[rg['boundary'].reshape(-1)][:, 2] == 0).all()


def test_non_star_shaped_scan_stops_with_a_code_and_a_report(tmp_path):
    v, f = _u_scan()
    r = prep(tmp_path, v, f)
    assert r['prepared_status'] == 'READY', r['blocking_reasons']
    e = rejects('SMOOTH_FIT_NOT_STAR_SHAPED', lambda: sf.build_shell_smooth(tmp_path, r['scan_id'], 2.0, opening(-6.0), grid=21))
    assert e.details['failing_rays'] > 0 and 0 < e.details['failing_fraction'] <= 1 and e.details['examples']
    assert e.details['sampled_on_grid_only'] is True
    rep = json.loads((tmp_path / 'mouse' / 'scans' / r['scan_id'] / 'build_report_smooth.json').read_text('utf-8'))
    assert rep['execution']['code'] == 'SMOOTH_FIT_NOT_STAR_SHAPED' and rep['design_status'] == 'UNVERIFIED'


def test_settings_and_prerequisites_are_validated(tmp_path):
    r, _, _ = _mouse(tmp_path, 6)
    sid = r['scan_id']
    rejects('SCAN_NOT_FOUND', lambda: sf.build_shell_smooth(tmp_path, 'scan_missing', 2.0, opening(-5)))
    rejects('SHELL_SETTINGS', lambda: sf.build_shell_smooth(tmp_path, sid, 0.0, opening(-5)))
    rejects('SHELL_SETTINGS', lambda: sf.build_shell_smooth(tmp_path, sid, 2.0, opening(-5), grid=400))
    rejects('SHELL_SETTINGS', lambda: sf.build_shell_smooth(tmp_path, sid, 2.0, opening(-5), degree_min=2))
    rejects('SHELL_SETTINGS', lambda: sf.build_shell_smooth(tmp_path, sid, 2.0, opening(-5), degree_min=5, degree_max=3))
    rejects('SHELL_SETTINGS', lambda: sf.build_shell_smooth(tmp_path, sid, 2.0, opening(-5), smoothing=-1.0))
    rejects('SHELL_OPENING_INVALID', lambda: sf.build_shell_smooth(tmp_path, sid, 2.0, {'type': 'cone', 'point': [0, 0, 0], 'normal': [0, 0, 1]}))
    rejects('SMOOTH_FIT_NO_SECTION', lambda: sf.build_shell_smooth(tmp_path, sid, 2.0, opening(50.0)))  # plane above the whole scan


# ------------------------------------------------------------------ mouse-like body
@pytest.fixture(scope='module')
def mouse_build(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('fit')
    r, v, f = _mouse(tmp, 14)
    b = sf.build_shell_smooth(tmp, r['scan_id'], 2.0, opening(-5.0), grid=41)
    return tmp, r, v, f, b


def test_mouse_like_fit_is_a_valid_smooth_solid_and_checks_are_honest(mouse_build):
    tmp, r, v, f, b = mouse_build
    c = b['checks']
    assert b['route'] == 'smooth_fit' and b['execution']['completed'] and b['star_shape']['status'] == 'PASS'
    fr = b['fit_report']
    assert 3 <= min(fr['degree']) and max(fr['degree']) <= 5 and fr['pole_count'] == fr['poles'][0] * fr['poles'][1]
    mm = fr['max_interior_knot_multiplicity']
    assert mm['u'] < fr['degree'][0] and mm['v'] < fr['degree'][1] and c['fit_knots']['status'] == 'PASS'
    assert fr['residual_at_grid_points_mm']['max'] < 0.15 and fr['rim_corner_singular_points']
    for name in ('brep_valid', 'single_closed_solid', 'step_roundtrip', 'face_structure', 'opening_present'):
        assert c[name]['status'] == 'PASS', name
    assert b['brep_faces'] <= 4 and c['face_structure']['planar_faces'] == 1
    sq = c['surface_quality']
    assert sq['status'] == 'PASS' and sq['checks']['internal_knots']['status'] == 'PASS' and sq['profile'] == 'consumer_product'
    assert 'g1_smooth_edges' in sq['unassessed_checks']  # the rim is a crease: no smooth edge to assess, reported, not passed
    od = c['outer_deviation']
    ok = od['output_to_scan']['max'] <= od['tolerance_mm'] and od['scan_to_output']['max'] <= od['tolerance_mm']
    assert (od['status'] == 'PASS') == ok and od['grid_used'] == 41  # status follows its own numbers
    assert 'not a global minimum' in c['wall_thickness']['note']
    assert c['self_intersection']['status'] == 'UNVERIFIED'
    blocking = [c[k]['status'] for k in b['blocking_checks']]
    assert b['design_status'] == ('PASS' if all(s == 'PASS' for s in blocking) else 'FAIL')
    d = tmp / 'mouse' / 'scans' / r['scan_id']
    for name in ('shell_smooth.step', 'shell_smooth.stl', 'fit_surface.npz', 'build_report_smooth.json'):
        assert (d / name).is_file()
    assert not (d / 'build_report.json').exists()  # the A1 report is never written or overwritten by A2


def test_two_surface_solid_is_valid_without_any_repair(mouse_build):
    b = mouse_build[4]
    c = b['checks']
    assert b['repairs_applied'] == [] and c['brep_valid']['status'] == 'PASS' and b['brep_faces'] == 3
    fr = b['fit_report']
    assert fr['inner_surface']['same_parametrisation_as_outer'] and fr['inner_surface']['crossing_residual_mm']['max_abs'] < 1e-3
    assert 'MakeThickSolid' not in json.dumps(b)
    ext = c['inner_skin_extent']
    assert ext['status'] == 'PASS' and ext['min_height_above_opening_plane_mm'] >= -1e-3
    wt = c['wall_thickness']
    ok = wt['vs_scan']['min'] >= 2.0 - 0.1 and wt['vs_outer_bspline']['min'] >= 2.0 - 0.1
    assert (wt['status'] == 'PASS') == ok  # status follows its own numbers; the wall is the target thickness up to the fit error


def test_locally_solid_scan_stops_without_fallback(tmp_path):
    r, v, f = _mouse(tmp_path, 14)  # inscribed radius <= 9 mm: no inner skin exists for a 12 mm wall
    e = rejects('SMOOTH_FIT_LOCALLY_SOLID', lambda: sf.build_shell_smooth(tmp_path, r['scan_id'], 12.0, opening(-5.0), grid=21))
    assert e.details['failing_rays'] > 0 and e.details['examples'] and e.details['grid'] == 21
    rep = json.loads((tmp_path / 'mouse' / 'scans' / r['scan_id'] / 'build_report_smooth.json').read_text(encoding='utf-8'))
    assert rep['execution']['code'] == 'SMOOTH_FIT_LOCALLY_SOLID' and rep['design_status'] == 'UNVERIFIED'


def test_mouse_like_default_grid_121_with_tighter_fit_passes(tmp_path):
    v, f = S.superellipsoid(24.0, 14.0, 9.0, 0.6, 40)
    r = prep(tmp_path, v, f)
    b = sf.build_shell_smooth(tmp_path, r['scan_id'], 2.0, opening(-5.0), fit_tolerance_mm=0.03)
    assert b['settings']['grid'] == 121 and b['repairs_applied'] == []
    assert {k: b['checks'][k]['status'] for k in b['blocking_checks']} == {k: 'PASS' for k in b['blocking_checks']}
    assert b['design_status'] == 'PASS' and b['checks']['outer_deviation']['tolerance_mm'] == 0.15


def test_mouse_scale_120x64x38_numbers_are_honest(tmp_path):
    v, f = S.superellipsoid(60.0, 32.0, 19.0, 0.6, 40)
    r = prep(tmp_path, v, f)
    b = sf.build_shell_smooth(tmp_path, r['scan_id'], 2.0, opening(-8.5), fit_tolerance_mm=0.04)
    c = b['checks']
    assert b['repairs_applied'] == [] and b['brep_faces'] == 3 and c['brep_valid']['status'] == 'PASS' and c['wall_thickness']['status'] == 'PASS'
    od = c['outer_deviation']
    ok = od['output_to_scan']['max'] <= 0.15 and od['scan_to_output']['max'] <= 0.15
    assert (od['status'] == 'PASS') == ok and od['output_to_scan']['max'] < 0.25 and od['scan_to_output']['max'] < 0.25
    assert b['design_status'] == ('PASS' if ok else 'FAIL')  # at this size and grid 121 the outer tolerance is reported FAIL, not loosened


def test_tolerance_too_tight_is_reported_as_fail_not_loosened(tmp_path):
    r, v, f = _mouse(tmp_path, 14)
    b = sf.build_shell_smooth(tmp_path, r['scan_id'], 2.0, opening(-5.0), grid=21, outer_tolerance_mm=0.001, fit_tolerance_mm=0.05)
    od = b['checks']['outer_deviation']
    assert od['status'] == 'FAIL' and od['tolerance_mm'] == 0.001 and od['code'] == 'SMOOTH_FIT_OUT_OF_TOLERANCE'
    assert od['grid_used'] == 21 and 'worst_point_mm' in od['output_to_scan'] and b['codes'].count('SMOOTH_FIT_OUT_OF_TOLERANCE') == 1
    assert b['settings']['outer_tolerance_mm'] == 0.001 and b['design_status'] == 'FAIL'


def test_fit_is_deterministic(mouse_build):
    tmp, r, v, f, a = mouse_build
    b = sf.build_shell_smooth(tmp, r['scan_id'], 2.0, opening(-5.0), grid=41)
    assert a['hashes']['poles_sha256'] == b['hashes']['poles_sha256'] == a['fit_report']['poles_sha256']
    c = sf.build_shell_smooth(tmp, r['scan_id'], 2.0, opening(-5.0), grid=45)
    assert c['hashes']['poles_sha256'] != a['hashes']['poles_sha256']


# ------------------------------------------------------------------ tool wiring
def test_tool_route_argument_dispatch_and_schema(tmp_path):
    t = Tools(Brain(tmp_path))
    names = {row['name']: row for row in t.list()}
    props = names['brain_mouse_build_shell_brep']['inputSchema']['properties']
    assert props['route']['default'] == 'faceted_sdf' and props['voxel_mm']['default'] == 0.5
    for k in ('grid', 'degree_min', 'degree_max', 'fit_tolerance_mm', 'smoothing'):
        assert k in props
    v, f = _u_scan()
    S.write_stl(tmp_path / 'u.stl', v, f)
    sid = t.call('brain_mouse_prepare_scan', {'relative_path': 'u.stl', 'unit': 'mm'})['scan_id']
    base = {'scan_id': sid, 'thickness_mm': 2.0, 'opening': opening(-6.0)}
    rejects('SMOOTH_FIT_NOT_STAR_SHAPED', lambda: t.call('brain_mouse_build_shell_brep', {**base, 'route': 'smooth_fit', 'grid': 15}))
    rejects('SHELL_SETTINGS', lambda: t.call('brain_mouse_build_shell_brep', {**base, 'route': 'faceted_sdf', 'grid': 15}))  # no silent ignoring
    rejects('SHELL_SETTINGS', lambda: t.call('brain_mouse_build_shell_brep', {**base, 'route': 'magic'}))
