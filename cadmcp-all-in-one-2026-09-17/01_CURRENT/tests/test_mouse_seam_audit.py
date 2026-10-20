"""brain_mouse_seam_audit on a synthetic shell with and without a split top face (module function through the worker subprocess). Needs OCP + matplotlib."""
from __future__ import annotations
import pytest
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import mouse_seam_audit as SA

pytest.importorskip('OCP')
pytest.importorskip('matplotlib')
from cadmcp_brain.studio import cad_brep_lib as L  # noqa: E402
from cadmcp_brain.studio import solid_boolean_safe_worker as BW  # noqa: E402


def box(x0, y0, z0, x1, y1, z1):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    return L.solids(BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape())[0]


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code


@pytest.fixture(scope='module')
def ws(tmp_path_factory):
    d = tmp_path_factory.mktemp('seam')
    split = L.solids(BW.run_op(box(0, -10, 0, 10, 10, 10), box(10, -10, 0, 20, 10, 10), 'fuse'))[0]          # plain fuse keeps the coplanar faces split
    assert len(L.faces(split)) == 10
    L.write_step(split, d / 'split.step')
    L.write_step(BW.unify(split, 1e-6), d / 'merged.step')
    return d


def test_split_box_has_four_smooth_seams_in_the_band(ws):
    r = SA.seam_audit(ws, 'split.step', [{'name': 'mid', 'axis': 'x', 'range': [9.5, 10.5]}, {'name': 'slot', 'axis': 'y', 'range': [-1, 1]}])
    assert r['status'] == 'FAIL' and r['part'] == 'split'
    mid = r['bands'][0]
    assert mid['flagged_edges'] == 4 and mid['by_class'] == {'smooth_seam': 4}
    assert all(e['g1_max_deg'] < 1e-6 for e in mid['edges'])
    assert mid['flagged_length_mm'] == pytest.approx(20 * 2 + 10 * 2)             # top + bottom (20 each) + two side faces (10 each)
    assert r['totals']['faces'] == 10 and r['totals']['by_class']['smooth_seam'] == 4
    assert r['bands'][1]['faces_in_band'] == 6          # |y| <= 1: top x 2, bottom x 2, the two end faces; the y = +-10 side faces do not reach it
    assert (ws / r['outputs']['seam_plan.png']['relative_path']).stat().st_size > 5000


def test_merged_box_has_no_seam_and_creases_are_not_flagged(ws):
    r = SA.seam_audit(ws, 'merged.step', [{'name': 'mid', 'axis': 'x', 'range': [9.5, 10.5]}], flag='seams')
    assert r['status'] == 'PASS' and r['flagged_total'] == 0 and r['totals']['faces'] == 6
    edge_band = SA.seam_audit(ws, 'merged.step', [{'name': 'left', 'axis': 'x', 'range': [-0.1, 0.1]}], flag='all')
    assert edge_band['bands'][0]['flagged_edges'] == 4 and edge_band['bands'][0]['by_class'] == {'crease': 4}
    assert abs(edge_band['bands'][0]['edges'][0]['g1_max_deg'] - 90.0) < 1e-6


def test_along_range_and_bad_arguments(ws):
    r = SA.seam_audit(ws, 'split.step', [{'name': 'top_only', 'axis': 'x', 'range': [9.5, 10.5], 'along_axis': 'y', 'along_range': [-10.5, 10.5]}])
    assert r['bands'][0]['edges_in_band'] == 4
    r2 = SA.seam_audit(ws, 'split.step', [{'name': 'none', 'axis': 'x', 'range': [9.5, 10.5], 'along_axis': 'z', 'along_range': [50, 60]}])
    assert r2['bands'][0]['edges_in_band'] == 0 and r2['status'] == 'PASS'
    rejects('SEAM_AUDIT_SETTINGS', lambda: SA.seam_audit(ws, 'split.step', [{'name': 'b', 'axis': 'w', 'range': [0, 1]}]))
    rejects('SEAM_AUDIT_SETTINGS', lambda: SA.seam_audit(ws, 'split.step', [{'name': 'b', 'axis': 'x', 'range': [2, 1]}]))
    rejects('SEAM_AUDIT_SETTINGS', lambda: SA.seam_audit(ws, 'split.step', flag='some'))


def shifted_split(d, name, dy, k=1.0):
    """Shell-like box split at its own mid plane y = dy (two fused halves): the 4 seam edges lie ON the symmetry plane, which is not at y = 0."""
    split = L.solids(BW.run_op(box(0, dy - 10 * k, 0, 20 * k, dy, 10 * k), box(0, dy, 0, 20 * k, dy + 10 * k, 10 * k), 'fuse'))[0]
    L.write_step(split, d / name)


def test_derived_band_follows_the_fitted_symmetry_plane_not_y0(ws):
    for name, dy, k in (('s0.step', 0.0, 1.0), ('s37.step', 37.0, 1.0), ('s_big.step', -80.0, 2.5)):
        shifted_split(ws, name, dy, k)
        r = SA.seam_audit(ws, name)                                                    # no bands: derived from the symmetry fit
        sym = r['symmetry']
        assert sym['source'] == 'fitted' and sym['plane_mm'] == pytest.approx(dy, abs=0.02 * k), name
        assert r['bands'][0]['range'][0] < dy < r['bands'][0]['range'][1]
        assert r['bands'][0]['range'][1] - r['bands'][0]['range'][0] == pytest.approx(2 * 0.015 * 20 * k, rel=1e-6)    # 1.5 % of the extent per side
        assert r['bands'][0]['flagged_edges'] == 4 and r['status'] == 'FAIL', name     # top, bottom and the two end-face seams
    # an explicit plane and half width override the fit
    r = SA.seam_audit(ws, 's37.step', mirror_plane_mm=37.0, band_half_width_mm=0.5)
    assert r['symmetry']['source'] == 'argument' and r['bands'][0]['range'] == pytest.approx([36.5, 37.5]) and r['bands'][0]['flagged_edges'] == 4
    # the LH2-style fixed band [-1, 1] misses a shifted model entirely (this is why it is no longer a default)
    miss = SA.seam_audit(ws, 's37.step', [{'name': 'old_default', 'axis': 'y', 'range': [-1.0, 1.0]}])
    assert miss['bands'][0]['flagged_edges'] == 0 and miss['symmetry']['plane_mm'] == pytest.approx(37.0, abs=0.02)


def test_mirror_axis_and_argument_errors(ws):
    shifted_split(ws, 'sx.step', 5.0)
    rejects('SEAM_AUDIT_SETTINGS', lambda: SA.seam_audit(ws, 'sx.step', mirror_axis='w'))
    rejects('SEAM_AUDIT_SETTINGS', lambda: SA.seam_audit(ws, 'sx.step', band_half_width_mm=0.0))
