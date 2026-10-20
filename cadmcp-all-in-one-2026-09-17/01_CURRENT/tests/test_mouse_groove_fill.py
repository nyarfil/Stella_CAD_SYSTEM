"""brain_mouse_groove_fill on a synthetic block with a C-shaped click groove (no scan data, no V: files).
The worker runs in this process; one end-to-end call of the module function goes through the server python subprocess (needs OCP: skipped when missing).
"""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import mouse_groove_fill as MG

pytest.importorskip('OCP')
from cadmcp_brain.studio import cad_brep_lib as L  # noqa: E402
from cadmcp_brain.studio import mouse_groove_fill_worker as WG  # noqa: E402

def prism_xz(pts, y0, y1):
    """Polygon in the XZ plane extruded along y from y0 to y1."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Pnt, gp_Vec
    poly = BRepBuilderAPI_MakePolygon()
    for x, z in pts:
        poly.Add(gp_Pnt(x, y0, z))
    poly.Close()
    return BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(poly.Wire()).Face(), gp_Vec(0, y1 - y0, 0)).Shape()


def cut(a, b):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    return BRepAlgoAPI_Cut(a, b).Shape()


def box(x0, y0, z0, x1, y1, z1):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    return BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()


# 60 wide block, top z 20 up to x = 80, then a slope down to (90, 0): the groove runs out through the slope (not through a vertical wall).
PROFILE = [(0, 0), (90, 0), (80, 20), (0, 20)]


def plain_block():
    return L.solids(prism_xz(PROFILE, -30, 30))[0]


def c_groove_block():
    """0.5 wide, 1.5 deep U groove (x 19.5..81, y +-10.5 around an island x 20..81, y +-10) running out through the slope."""
    ring = cut(box(19.5, -10.5, 18.5, 81, 10.5, 21), box(20, -10, 18, 82, 10, 22))
    return L.solids(cut(plain_block(), ring))[0]


def ring_groove_block():
    """Closed rectangular groove ring on the flat top: refused by the tool."""
    ring = cut(box(19.5, -10.5, 18.5, 60.5, 10.5, 21), box(20, -10, 18, 60, 10, 21))
    return L.solids(cut(plain_block(), ring))[0]


def run_worker(tmp, solid, params=None):
    src = tmp / 'in.step'
    L.write_step(solid, src)
    return WG.run({'inputs': {'shell': str(src)}, 'params': params or {}, 'out_dir': str(tmp / 'out')}), tmp / 'out'


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code


def test_c_groove_is_filled_back_to_the_plain_block(tmp_path):
    res, out = run_worker(tmp_path, c_groove_block())
    expect = WG.mesh_volume(plain_block(), 0.003)
    assert res['free_edges'] == 0 and res['multiple_edges'] == 0 and res['valid']
    assert res['volume_after_mm3'] > res['volume_before_mm3']
    assert abs(res['volume_after_mm3'] - expect) < 1.0
    assert res['round_trip']['solids'] == 1 and res['round_trip']['free_edges'] == 0
    back = L.solids(L.read_step(out / 'filled_skin.step'))
    assert len(back) == 1
    top = sum(L.area(f) for f in L.faces(back[0]) if abs(L.bbox(f)[2] - 20) < 1e-6 and abs(L.bbox(f)[5] - 20) < 1e-6)
    assert abs(top - 80 * 60) < 0.5                       # the caps restore the plain skin: no groove floor is left


def test_closed_ring_groove_is_refused_not_filled_partially(tmp_path):
    with pytest.raises(WG.WorkerError) as exc:
        run_worker(tmp_path, ring_groove_block())
    assert exc.value.code in ('GROOVE_FILL_UNSUPPORTED', 'GROOVE_FILL_NOT_FOUND')


def test_block_without_groove_is_not_found(tmp_path):
    with pytest.raises(WG.WorkerError) as exc:
        run_worker(tmp_path, L.solids(box(0, 0, 0, 40, 40, 10))[0])
    assert exc.value.code == 'GROOVE_FILL_NOT_FOUND'


def test_argument_validation(tmp_path):
    L.write_step(plain_block(), tmp_path / 'a.step')
    rejects('GROOVE_FILL_SETTINGS', lambda: MG.groove_fill(tmp_path, 'a.step', floor_min_nz=2.0))
    rejects('GROOVE_FILL_SETTINGS', lambda: MG.groove_fill(tmp_path, 'a.step', groove_faces=[]))
    rejects('GROOVE_FILL_SETTINGS', lambda: MG.groove_fill(tmp_path, 'a.step', groove_faces=[-1]))
    rejects('GROOVE_FILL_SETTINGS', lambda: MG.groove_fill(tmp_path, 'a.step', part=''))
    with pytest.raises(BrainError) as exc:
        MG.groove_fill(tmp_path, 'missing.step')
    assert exc.value.code == 'UNSAFE_PATH'


def test_module_end_to_end_and_cache(tmp_path):
    L.write_step(c_groove_block(), tmp_path / 'shell.step')
    r1 = MG.groove_fill(tmp_path, 'shell.step')
    assert r1['status'] == 'READY' and r1['evidence']['free_edges'] == 0
    out = list(tmp_path.glob('mouse/cad/gf_*/filled_skin.step'))
    assert len(out) == 1
    r2 = MG.groove_fill(tmp_path, 'shell.step')
    assert r2['groove_fill_id'] == r1['groove_fill_id']
    assert list(tmp_path.glob('mouse/cad/gf_*/groove_fill_report.json'))


def frame_blocks(k, dx, dy):
    """plain block and the C-groove block scaled by k and moved by (dx, dy) (the groove and the block keep their proportions)."""
    prof = [(dx + x * k, z * k) for x, z in PROFILE]
    plain = L.solids(prism_xz(prof, dy - 30 * k, dy + 30 * k))[0]
    ring = cut(box(dx + 19.5 * k, dy - 10.5 * k, 18.5 * k, dx + 81 * k, dy + 10.5 * k, 21 * k), box(dx + 20 * k, dy - 10 * k, 18 * k, dx + 82 * k, dy + 10 * k, 22 * k))
    return plain, L.solids(cut(plain, ring))[0]


@pytest.mark.parametrize('k,dx,dy', [(1.0, -20.0, 55.0), (2.0, 0.0, 0.0), (0.6, 13.0, -40.0)], ids=['shifted', 'scaled_up', 'scaled_down'])
def test_threshold_defaults_scale_with_the_shell_bbox(tmp_path, k, dx, dy):
    """No absolute 20 mm / 300 mm2: the groove length and skin area thresholds follow the bbox; the mirror plane / origin are irrelevant."""
    plain, grooved = frame_blocks(k, dx, dy)
    res, _ = run_worker(tmp_path, grooved, {'max_floor_width_mm': 1.2 * max(k, 1.0)})
    assert res['free_edges'] == 0 and res['valid'] and abs(res['volume_after_mm3'] - WG.mesh_volume(plain, 0.003)) < 1.0 * k ** 3
    used = res['settings_used']
    bb = L.bbox(grooved)
    assert used['min_groove_length_mm'] == pytest.approx(0.17 * max(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]))
    assert used['min_patch_area_mm2'] == pytest.approx(0.04 * (bb[3] - bb[0]) * (bb[4] - bb[1]))


def test_explicit_thresholds_override_the_derived_ones(tmp_path):
    _, grooved = frame_blocks(1.0, 0.0, 0.0)
    res, _ = run_worker(tmp_path, grooved, {'min_groove_length_mm': 20.0, 'min_patch_area_mm2': 300.0})          # the LH2 verification values
    assert res['settings_used']['min_groove_length_mm'] == 20.0 and res['settings_used']['min_patch_area_mm2'] == 300.0 and res['free_edges'] == 0
    with pytest.raises(WG.WorkerError) as exc:                                                                    # groove shorter than an explicit minimum: not found
        (tmp_path / 'x').mkdir() or run_worker(tmp_path / 'x', grooved, {'min_groove_length_mm': 500.0})
    assert exc.value.code == 'GROOVE_FILL_NOT_FOUND'
