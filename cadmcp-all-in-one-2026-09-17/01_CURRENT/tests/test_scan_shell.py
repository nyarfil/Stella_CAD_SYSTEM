"""Scan -> hollow shell, stage A1: synthetic meshes, no network, no private files (except one skipped V: probe)."""
from __future__ import annotations
import math
import sys
from pathlib import Path
import numpy as np
import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import scan_mesh as sm
from cadmcp_brain.studio import scan_shell as sh

sys.path.insert(0, str(Path(__file__).parent))
import scan_shapes as S  # noqa: E402

BOTTOM = {'type': 'plane', 'point': [0.0, 0.0, 0.0], 'normal': [0.0, 0.0, -1.0]}


def opening(z: float) -> dict:
    return {'type': 'plane', 'point': [0.0, 0.0, z], 'normal': [0.0, 0.0, -1.0]}


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code
    return exc.value


def prep(tmp_path, v, f, name='a.stl', unit='mm', **kw):
    S.write_stl(tmp_path / name, v, f)
    return sh.prepare_scan(tmp_path, name, unit, **kw)


# ------------------------------------------------------------------ mesh library
def test_exact_triangle_distance_matches_brute_force():
    rng = np.random.default_rng(1)
    v, f = S.sphere(10.0, 6)
    md = sm.MeshDistance(v, f)
    pts = rng.uniform(-18, 18, (300, 3))
    got = md.distance(pts)
    # independent brute force over all triangles
    best = np.full(len(pts), np.inf)
    for t in f:
        a, b, c = (np.repeat(v[i][None], len(pts), 0) for i in t)
        best = np.minimum(best, np.sqrt(sm._closest_d2(pts, a, b, c)))
    assert np.allclose(got, best, atol=1e-9)
    # a point on a vertex and a far point
    assert md.distance(v[:1])[0] == pytest.approx(0, abs=1e-12)
    assert md.distance(np.array([[100.0, 0, 0]]))[0] == pytest.approx(100 - 10, abs=0.6)


def test_inside_mask_box_and_crosscheck():
    v, f = S.box((20.0, 16.0, 10.0), 3)
    h = 1.0
    axes = tuple(-14 + 0.3 + h * np.arange(29) for _ in range(3))
    mask, cc = sm.inside_mask(v, f, axes)
    assert cc['mismatched_nodes'] == 0 and cc['checked_nodes'] > 0
    X, Y, Z = np.meshgrid(*axes, indexing='ij')
    ref = (np.abs(X) < 10) & (np.abs(Y) < 8) & (np.abs(Z) < 5)
    assert (mask == ref).all()


def test_clipped_volume_is_analytic_for_a_box():
    v, f = S.box((20.0, 16.0, 10.0), 2)
    vol = sh._clipped_volume(v, f, np.array([0, 0, -2.0]), np.array([0, 0, -1.0]))  # keep z >= -2
    assert vol == pytest.approx(20 * 16 * 7, rel=1e-9)
    vol = sh._clipped_volume(v, f, np.array([3.3, 0, 0.0]), np.array([1.0, 0, 0]))  # keep x <= 3.3
    assert vol == pytest.approx(13.3 * 16 * 10, rel=1e-9)


def test_surface_nets_is_closed_and_deterministic():
    n = 24
    ax = np.linspace(-12, 12, n) + 0.013
    X, Y, Z = np.meshgrid(ax, ax, ax, indexing='ij')
    psi = np.sqrt(X ** 2 + Y ** 2 + Z ** 2) - 8.0
    lab = np.zeros(psi.shape, np.int8)
    v1, f1, _, _ = sm.surface_nets(psi, np.full(3, ax[0]), ax[1] - ax[0], lab)
    v2, f2, _, _ = sm.surface_nets(psi, np.full(3, ax[0]), ax[1] - ax[0], lab)
    assert sm.mesh_manifold_report(f1, len(v1))['closed_2_manifold']
    assert sm.signed_volume(v1, f1) == pytest.approx(4 / 3 * math.pi * 512, rel=0.02)
    assert np.array_equal(v1, v2) and np.array_equal(f1, f2)
    assert np.abs(np.linalg.norm(v1, axis=1) - 8.0).max() < 0.1


def test_npz_bytes_are_deterministic():
    a = sm.npz_bytes(x=np.arange(5.0), y=np.eye(2))
    assert a == sm.npz_bytes(y=np.eye(2), x=np.arange(5.0))


# ------------------------------------------------------------------ prepare_scan
def test_prepare_sphere_ready_and_reports_numbers(tmp_path):
    v, f = S.sphere(30.0, 12)
    r = prep(tmp_path, v, f)
    assert r['prepared_status'] == 'READY' and r['blocking_reasons'] == []
    i = r['inspection']
    assert i['boundary_edges'] == 0 and i['non_manifold_edges'] == 0 and i['inconsistent_orientation_edges'] == 0
    assert i['component_count'] == 1 and i['signed_volume_mm3'] > 0
    assert i['triangles'] == len(f) and i['vertices'] == len(v)
    assert i['bbox_max_mm'][0] == pytest.approx(30.0, abs=1e-3)
    assert r['checks']['self_intersection'] == 'UNVERIFIED'
    assert r['source']['sha256'] and r['prepared_npz_sha256']
    assert (tmp_path / 'mouse' / 'scans' / r['scan_id'] / 'prepared.npz').is_file()
    assert (tmp_path / 'mouse' / 'scans' / r['scan_id'] / 'prepare_report.json').is_file()
    assert r['repairs_applied'] == []


def test_prepare_requires_a_known_unit_and_flags_suspect_scale(tmp_path):
    v, f = S.sphere(30.0, 6)
    S.write_stl(tmp_path / 'a.stl', v, f)
    rejects('SCAN_UNIT', lambda: sh.prepare_scan(tmp_path, 'a.stl', 'furlong'))
    r = sh.prepare_scan(tmp_path, 'a.stl', 'm')  # 60 "metres" -> 60000 mm
    assert [w['code'] for w in r['warnings']] == ['UNIT_SUSPECT']
    assert r['inspection']['bbox_max_mm'][0] == pytest.approx(30000.0, rel=1e-6)  # never rescaled automatically
    r2 = prep(tmp_path, v * 0.001, f, 'b.stl')  # file is metres but declared mm
    assert [w['code'] for w in r2['warnings']] == ['UNIT_SUSPECT']
    r3 = prep(tmp_path, v * 0.001, f, 'c.stl', unit='m')
    assert not r3['warnings'] and r3['inspection']['bbox_max_mm'][0] == pytest.approx(30.0, abs=1e-3)


def test_prepare_ascii_stl_obj_and_transform(tmp_path):
    v, f = S.sphere(30.0, 6)
    S.write_stl(tmp_path / 'a.stl', v, f, ascii_=True)
    r = sh.prepare_scan(tmp_path, 'a.stl', 'mm', transform=[1, 0, 0, 5, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
    assert r['prepared_status'] == 'READY'
    assert r['inspection']['bbox_max_mm'][0] == pytest.approx(35.0, abs=1e-3)
    obj = '\n'.join([f'v {x} {y} {z}' for x, y, z in v] + [f'f {a + 1} {b + 1} {c + 1}' for a, b, c in f])
    (tmp_path / 'a.obj').write_text(obj)
    assert sh.prepare_scan(tmp_path, 'a.obj', 'mm')['prepared_status'] == 'READY'
    rejects('SCAN_TRANSFORM_INVALID', lambda: sh.prepare_scan(tmp_path, 'a.stl', 'mm', transform=[1.0] * 16))
    mirror = [-1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    rm = sh.prepare_scan(tmp_path, 'a.stl', 'mm', transform=mirror)
    assert rm['prepared_status'] == 'READY' and rm['repairs_applied'][0]['repair'].startswith('mirror')
    rejects('UNSAFE_PATH', lambda: sh.prepare_scan(tmp_path, '../a.stl', 'mm'))
    (tmp_path / 'a.txt').write_text('x')
    rejects('SCAN_FILE', lambda: sh.prepare_scan(tmp_path, 'a.txt', 'mm'))


def test_hole_is_not_ready_and_fill_is_an_explicit_reported_repair(tmp_path):
    v, f = S.sphere(30.0, 8)
    holed = np.delete(f, [0, 64], axis=0)  # both triangles of one quad (n=8 -> 64 quads per face)
    r = prep(tmp_path, v, holed)
    assert r['prepared_status'] == 'NOT_READY' and 'HOLES_PRESENT' in r['blocking_reasons']
    assert r['inspection']['boundary_edges'] > 0 and len(r['inspection']['boundary_loops']) >= 1
    assert r['prepared_npz_sha256'] is None
    rejects('SCAN_NOT_READY', lambda: sh.build_shell_brep(tmp_path, r['scan_id'], 2.0, BOTTOM))
    small = prep(tmp_path, v, holed, 'b.stl', repairs={'fill_holes_max_perimeter_mm': 1.0})
    assert small['prepared_status'] == 'NOT_READY'  # loop is longer than the declared limit
    assert small['repairs_applied'][0]['loops_skipped_too_long'] >= 1
    big = prep(tmp_path, v, holed, 'c.stl', repairs={'fill_holes_max_perimeter_mm': 50.0})
    assert big['prepared_status'] == 'READY'
    fill = big['repairs_applied'][0]
    assert fill['repair'] == 'fill_holes' and fill['loops_filled'] >= 1 and fill['filled_area_mm2'] > 0
    assert big['unmeasured_surface_mm2'] == pytest.approx(fill['filled_area_mm2'])


def test_non_manifold_edge_blocks(tmp_path):
    v, f = S.sphere(30.0, 6)
    v2 = np.vstack([v, [[0, 0, 60.0]]])
    a, b = f[0][0], f[0][1]
    f2 = np.vstack([f, [[a, b, len(v)]]])  # third face on an existing edge
    r = prep(tmp_path, v2, f2)
    assert r['prepared_status'] == 'NOT_READY' and 'NON_MANIFOLD_EDGES' in r['blocking_reasons']
    assert r['inspection']['non_manifold_edges'] == 1


def test_flipped_triangles_need_orient_outward(tmp_path):
    v, f = S.sphere(30.0, 6)
    g = f.copy()
    g[::7] = g[::7][:, [0, 2, 1]]
    r = prep(tmp_path, v, g)
    assert 'INCONSISTENT_ORIENTATION' in r['blocking_reasons'] and r['prepared_status'] == 'NOT_READY'
    fixed = prep(tmp_path, v, g, 'b.stl', repairs={'orient_outward': True})
    assert fixed['prepared_status'] == 'READY'
    rep = fixed['repairs_applied'][0]
    assert rep['repair'] == 'orient_outward' and rep['triangles_flipped_for_consistency'] > 0
    inward = prep(tmp_path, v, f[:, [0, 2, 1]], 'c.stl')
    assert inward['blocking_reasons'] == ['ORIENTATION_NOT_OUTWARD']
    both = prep(tmp_path, v, f[:, [0, 2, 1]], 'd.stl', repairs={'orient_outward': True})
    assert both['prepared_status'] == 'READY' and both['repairs_applied'][0]['components_flipped_to_outward'] == 1


def test_two_components_and_drop_fraction(tmp_path):
    v, f = S.sphere(30.0, 6)
    v2, f2 = S.sphere(2.0, 3)
    vv = np.vstack([v, v2 + [80, 0, 0]])
    ff = np.vstack([f, f2 + len(v)])
    r = prep(tmp_path, vv, ff)
    assert 'MULTIPLE_COMPONENTS' in r['blocking_reasons'] and r['inspection']['component_count'] == 2
    d = prep(tmp_path, vv, ff, 'b.stl', repairs={'drop_components_below_fraction': 0.05})
    assert d['prepared_status'] == 'READY'
    assert d['repairs_applied'][0]['components_dropped'] == 1 and d['repairs_applied'][0]['area_dropped_mm2'] > 0


def test_weld_tolerance_and_degenerate_removal(tmp_path):
    v, f = S.sphere(30.0, 6)
    rng = np.random.default_rng(3)
    soup = v[f] + rng.normal(0, 1e-5, (len(f), 3, 3))  # triangle soup with duplicated, slightly different vertices
    path = tmp_path / 's.stl'
    S.write_stl(path, soup.reshape(-1, 3), np.arange(len(f) * 3).reshape(-1, 3))
    r0 = sh.prepare_scan(tmp_path, 's.stl', 'mm')
    assert r0['prepared_status'] == 'NOT_READY'  # un-welded soup is open everywhere
    r = sh.prepare_scan(tmp_path, 's.stl', 'mm', repairs={'weld_tolerance_mm': 1e-3})
    assert r['prepared_status'] == 'READY'
    w = r['repairs_applied'][0]
    assert w['repair'] == 'weld' and w['vertices_after'] < w['vertices_before'] and 0 < w['max_vertex_displacement_mm'] < 1e-3
    g = np.vstack([f, [[f[0][0], f[0][0], f[0][1]]]])  # a zero-area triangle
    warn = prep(tmp_path, v, g, 'g.stl')
    assert any(x['code'] == 'DEGENERATE_TRIANGLES' for x in warn['warnings'])
    rm = prep(tmp_path, v, g, 'h.stl', repairs={'remove_degenerate': True})
    assert rm['prepared_status'] == 'READY' and rm['repairs_applied'][0]['triangles_removed'] == 1


def test_invalid_repairs_rejected(tmp_path):
    v, f = S.sphere(30.0, 4)
    S.write_stl(tmp_path / 'a.stl', v, f)
    rejects('SCAN_REPAIRS_INVALID', lambda: sh.prepare_scan(tmp_path, 'a.stl', 'mm', repairs={'weld_tolerance_mm': -1}))
    rejects('SCAN_REPAIRS_INVALID', lambda: sh.prepare_scan(tmp_path, 'a.stl', 'mm', repairs={'smooth': True}))


# ------------------------------------------------------------------ build refusals (no B-rep needed)
def test_build_refusals(tmp_path):
    v, f = S.sphere(15.0, 8)
    r = prep(tmp_path, v, f)
    sid = r['scan_id']
    rejects('SCAN_NOT_FOUND', lambda: sh.build_shell_brep(tmp_path, 'scan_missing', 2.0, opening(-5)))
    rejects('SHELL_SETTINGS', lambda: sh.build_shell_brep(tmp_path, sid, 0.0, opening(-5)))
    rejects('SHELL_OPENING_INVALID', lambda: sh.build_shell_brep(tmp_path, sid, 2.0, {'type': 'cone', 'point': [0, 0, 0], 'normal': [0, 0, 1]}))
    e = rejects('SCAN_GRID_TOO_LARGE', lambda: sh.build_shell_brep(tmp_path, sid, 2.0, opening(-5), voxel_mm=0.5, max_voxels=10_000))
    assert e.details['voxels'] > 10_000 and e.details['voxel_mm_that_would_fit'] > 0.5
    e = rejects('BREP_FACE_BUDGET_EXCEEDED', lambda: sh.build_shell_brep(tmp_path, sid, 2.0, opening(-5), voxel_mm=1.0, max_faces=500))
    assert e.details['triangles'] > 500 and e.details['voxel_mm_that_would_fit'] > 1.0
    rep = (tmp_path / 'mouse' / 'scans' / sid / 'build_report.json').read_text()
    assert 'BREP_FACE_BUDGET_EXCEEDED' in rep and '"design_status":"UNVERIFIED"' in rep.replace(' ', '')
    # tampered prepared mesh is refused
    npz = tmp_path / 'mouse' / 'scans' / sid / 'prepared.npz'
    npz.write_bytes(npz.read_bytes() + b'x')
    rejects('SCAN_NOT_READY', lambda: sh.build_shell_brep(tmp_path, sid, 2.0, opening(-5)))


# ------------------------------------------------------------------ builds
def _check(rep, name):
    return rep['checks'][name]


def test_sphere_shell_known_volume_deviation_thickness_and_determinism(tmp_path):
    R, t, z0 = 14.0, 2.0, -6.0
    v, f = S.sphere(R, 14)
    r = prep(tmp_path, v, f)
    b1 = sh.build_shell_brep(tmp_path, r['scan_id'], t, opening(z0), voxel_mm=0.9, max_faces=100_000)
    assert b1['execution']['completed'] and b1['design_status'] == 'PASS', {k: c['status'] for k, c in b1['checks'].items()}
    for name in ('brep_valid', 'single_closed_solid', 'volume_consistency', 'step_roundtrip', 'outer_deviation', 'wall_thickness', 'opening_present'):
        assert _check(b1, name)['status'] == 'PASS', name
    # analytic shell volume: spherical cap shell between R and R-t above the cut (sphere is polyhedral, so allow a few percent)
    def cap_vol(rr):  # volume of the part of a sphere of radius rr above z = z0 (z0 < 0): sphere minus the low cap of height rr + z0
        h = rr + z0
        return 4 / 3 * math.pi * rr ** 3 - math.pi * h * h * (3 * rr - h) / 3
    expected = cap_vol(R) - cap_vol(R - t)
    assert _check(b1, 'volume_consistency')['brep_mm3'] == pytest.approx(expected, rel=0.03)
    od = _check(b1, 'outer_deviation')
    assert od['output_to_scan']['max'] <= 0.15 and od['scan_to_output']['max'] <= 0.15
    wt = _check(b1, 'wall_thickness')
    assert wt['min'] >= t - 0.1 and 'not a global minimum' in wt['note']
    assert _check(b1, 'opening_present')['cavity_volume_mm3'] > 0
    assert _check(b1, 'opening_present')['planar_faces_on_opening_plane_wire_counts'] == [2]
    assert _check(b1, 'locally_solid_regions')['count'] == 0
    assert _check(b1, 'self_intersection')['status'] == 'UNVERIFIED' and 'self_intersection' in b1['unverified_items']
    assert _check(b1, 'edit_suitability')['status'] == 'INFO'
    d = tmp_path / 'mouse' / 'scans' / r['scan_id']
    for name in ('shell.step', 'shell.stl', 'shell_mesh.npz', 'build_report.json'):
        assert (d / name).is_file()
    assert b1['hashes']['shell_mesh_npz'] and b1['inside_test_crosscheck']['mismatch_rate'] <= 0.001
    # deterministic: same inputs -> identical mesh file hash
    b2 = sh.build_shell_brep(tmp_path, r['scan_id'], t, opening(z0), voxel_mm=0.9, max_faces=100_000)
    assert b2['hashes']['shell_mesh_npz'] == b1['hashes']['shell_mesh_npz']


def test_box_sharp_edges_are_measured_not_hidden(tmp_path):
    v, f = S.box((30.0, 24.0, 16.0), 4)
    r = prep(tmp_path, v, f)
    h = 1.0
    b = sh.build_shell_brep(tmp_path, r['scan_id'], 2.0, opening(-3.0), voxel_mm=h, max_faces=100_000)
    for name in ('brep_valid', 'single_closed_solid', 'volume_consistency', 'step_roundtrip', 'opening_present'):
        assert _check(b, name)['status'] == 'PASS', name
    od = _check(b, 'outer_deviation')
    # Flat faces are exact; surface nets round sharp convex edges/corners by at most about one voxel. The status must follow the numbers.
    assert od['output_to_scan']['max'] < 1.0 * h
    assert (od['status'] == 'PASS') == (od['output_to_scan']['max'] <= 0.15 and od['scan_to_output']['max'] <= 0.15)
    assert b['design_status'] == ('PASS' if all(_check(b, k)['status'] == 'PASS' for k in b['blocking_checks']) else 'FAIL')
    assert _check(b, 'wall_thickness')['min'] >= 2.0 - 0.1 - 1e-9 or _check(b, 'wall_thickness')['status'] == 'FAIL'


def test_mouse_like_superellipsoid(tmp_path):
    v, f = S.superellipsoid(24.0, 14.0, 9.0, 0.6, 14)
    r = prep(tmp_path, v, f)
    b = sh.build_shell_brep(tmp_path, r['scan_id'], 2.0, opening(-5.0), voxel_mm=0.9, max_faces=100_000)
    assert b['design_status'] == 'PASS', {k: c['status'] for k, c in b['checks'].items()}
    assert _check(b, 'outer_deviation')['output_to_scan']['max'] <= 0.15
    assert _check(b, 'wall_thickness')['min'] >= 1.9


def _fin_scan():
    u = 1.5
    occ = np.zeros((12, 12, 10), bool)
    occ[:] = True
    fin = np.zeros((12 + 8, 12, 10), bool)
    fin[:12] = occ
    fin[12:, 4:5, 1:9] = True  # one unit (1.5 mm) thick, 8 units long, 8 units high
    return S.lattice_union(fin, u, (-9.0, -9.0, -7.5))


def test_thin_fin_is_reported_as_locally_solid(tmp_path):
    v, f = _fin_scan()
    r = prep(tmp_path, v, f)
    assert r['prepared_status'] == 'READY', r['blocking_reasons']
    # plane at z=-6 would leave a 0.5 mm floor slab above it: the cavity is sealed, which must be refused, not passed
    e = rejects('SHELL_MESH_DISCONNECTED', lambda: sh.build_shell_brep(tmp_path, r['scan_id'], 2.0, opening(-6.0), voxel_mm=1.0, max_faces=100_000))
    assert e.details['connected_parts'] == 2
    b = sh.build_shell_brep(tmp_path, r['scan_id'], 2.0, opening(-4.0), voxel_mm=1.0, max_faces=100_000)
    solid = _check(b, 'locally_solid_regions')
    assert solid['count'] >= 1 and solid['volume_mm3'] > 0
    assert _check(b, 'brep_valid')['status'] == 'PASS'


# ------------------------------------------------------------------ tool wiring
def test_tools_registered_and_callable(tmp_path):
    t = Tools(Brain(tmp_path))
    names = {row['name']: row for row in t.list()}
    for n in ('brain_mouse_prepare_scan', 'brain_mouse_build_shell_brep'):
        assert n in names and names[n]['annotations']['readOnlyHint'] is False
        assert names[n]['annotations']['destructiveHint'] is False
    props = names['brain_mouse_build_shell_brep']['inputSchema']['properties']
    assert props['voxel_mm']['default'] == 0.5 and props['max_faces']['default'] == 60000 and props['max_voxels']['default'] == 40_000_000
    assert props['outer_tolerance_mm']['default'] == 0.15 and props['thickness_tolerance_mm']['default'] == 0.1
    v, f = S.sphere(30.0, 5)
    S.write_stl(tmp_path / 'a.stl', v, f)
    r = t.call('brain_mouse_prepare_scan', {'relative_path': 'a.stl', 'unit': 'mm'})
    assert r['prepared_status'] == 'READY'
    rejects('SCAN_NOT_FOUND', lambda: t.call('brain_mouse_build_shell_brep', {'scan_id': 'scan_nope', 'thickness_mm': 2.0, 'opening': BOTTOM}))
    with pytest.raises(Exception):
        t.call('brain_mouse_prepare_scan', {'relative_path': 'a.stl'})  # unit is required


V_SHELL = Path('V:/mouse/OP1-PCB/stock-shell/Lightweight Mod.stl')


@pytest.mark.skipif(not V_SHELL.is_file(), reason='private scan file not present')
def test_private_hollow_shell_is_inspected_not_passed(tmp_path):
    import shutil
    shutil.copyfile(V_SHELL, tmp_path / 'shell.stl')
    r = sh.prepare_scan(tmp_path, 'shell.stl', 'mm')
    assert r['prepared_status'] in ('READY', 'NOT_READY')
    assert r['checks']['self_intersection'] == 'UNVERIFIED'
