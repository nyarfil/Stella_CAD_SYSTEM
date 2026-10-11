"""brain_mouse_scan_cable_fill: synthetic front walls (gentle double curvature) with a cable pocket and a parting groove. No scan data is used.

The geometry tests run the worker in this process (needs trimesh + shapely >= 2.1: extra `scan-grooves`; skipped when missing); the end-to-end
test goes through the tool and the separate scan python (skipped without one).
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import scan_cable_fill_worker as W
from cadmcp_brain.studio import scan_model as smod

trimesh = pytest.importorskip('trimesh')
shapely = pytest.importorskip('shapely')
if not hasattr(shapely, 'constrained_delaunay_triangles'):
    pytest.skip('shapely >= 2.1 needed', allow_module_level=True)

POCKET = dict(w=10.0, z0=3.0, z1=8.0, depth=4.0)
GROOVE_Z, GROOVE_W, GROOVE_D = 11.5, 0.6, 1.5


def wall(y, z):
    """Designed front wall: gentle plan R 60 and profile R 40 (x front)."""
    return 50.0 - y ** 2 / 120.0 - (z - 8.0) ** 2 / 80.0


def make_front(pocket_y=0.0, pocket=True, groove=True, wave=0.0, mirror=False, step=0.4):
    """Height-field sheet x(y, z) facing +x (or -x when mirror), labels npz codes top_shell=2 and a click region at the top (x side = front)."""
    ys = np.arange(-20.0, 20.0 + 1e-9, step)
    zs = np.arange(0.0, 16.0 + 1e-9, step)
    Y, Z = np.meshgrid(ys, zs, indexing='ij')
    X = wall(Y, Z) + wave * np.sin(2 * np.pi * Y / 5.0)
    if pocket:
        X = X - POCKET['depth'] * ((np.abs(Y - pocket_y) < POCKET['w'] / 2) & (Z > POCKET['z0']) & (Z < POCKET['z1']))
    if groove:
        X = X - GROOVE_D * (np.abs(Z - GROOVE_Z) < GROOVE_W / 2)
    V = np.c_[X.ravel(), Y.ravel(), Z.ravel()]
    ny, nz = len(ys), len(zs)
    idx = np.arange(ny * nz).reshape(ny, nz)
    a, b, c, d = idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()
    F = np.r_[np.c_[a, b, c], np.c_[a, c, d]]           # (y, z) counter-clockwise => normal +x
    # a click strip behind the top of the wall marks the front side
    lab = np.full(len(F), 2, np.uint8)
    cen = V[F].mean(1)
    lab[cen[:, 2] > 14.5] = 3
    lab[cen[:, 2] < 2.8] = 1                             # bottom plate below a straight parting line that the pocket rim crosses
    if mirror:
        V = V * np.array([-1.0, 1.0, 1.0])
        F = F[:, ::-1]
    return V, F, lab


def write_case(tmp: Path, V, F, lab, name='front'):
    tmp.mkdir(parents=True, exist_ok=True)
    trimesh.Trimesh(V, F, process=False).export(tmp / f'{name}.stl')
    np.savez(tmp / f'{name}_labels.npz', face_labels=lab, codes=np.array(['other=0', 'bottom_plate=1', 'top_shell=2', 'left_click=3']))
    return tmp / f'{name}.stl', tmp / f'{name}_labels.npz'


def run_worker(tmp: Path, V, F, lab, **params):
    stl, labels = write_case(tmp, V, F, lab)
    res = W.run({'input_path': str(stl), 'labels_path': str(labels), 'unit_scale': 1.0, 'out_dir': str(tmp / 'out'), 'params': params})
    return res, stl, labels


def filled_points(tmp: Path):
    m = trimesh.load(tmp / 'out' / 'filled.stl', process=False)
    return trimesh.sample.sample_surface_even(m, 60000, seed=3)[0], m


def test_pocket_is_filled_with_the_plain_wall_and_the_groove_is_kept(tmp_path):
    V, F, lab = make_front()
    res, _, _ = run_worker(tmp_path, V, F, lab)
    assert res['ready'] and res['applied'] and not res['blocking']
    assert len(res['pockets']) == 1, res['pockets']
    q = res['pockets'][0]
    assert abs(q['area_yz_mm2'] - POCKET['w'] * (POCKET['z1'] - POCKET['z0'])) < 20
    assert abs(q['fill_depth_mm']['max'] - POCKET['depth']) < 0.6
    assert q['ring_fit']['p95_mm'] < 0.1 and q['inferred_min_radius_mm'] > 30
    assert abs(q['centre_yz_mm'][0]) < 0.6 and abs(q['centre_yz_mm'][1] - 5.5) < 0.8
    assert q['patch']['orientation_conflicts'] == 0 and q['patch']['patch_facing_front_fraction'] == 1.0
    P, m = filled_points(tmp_path)
    inpk = (np.abs(P[:, 1]) < POCKET['w'] / 2 - 0.5) & (P[:, 2] > POCKET['z0'] + 0.5) & (P[:, 2] < POCKET['z1'] - 0.5)
    front = P[:, 0] > wall(P[:, 1], P[:, 2]) - 2.0
    assert (inpk & front).sum() > 200
    assert np.abs(P[inpk & front, 0] - wall(P[inpk & front, 1], P[inpk & front, 2])).max() < 0.1   # plain wall, no pocket left
    assert not (inpk & ~front).any()                                                                # the pocket floor is gone
    ing = (np.abs(P[:, 2] - GROOVE_Z) < 0.1) & (np.abs(P[:, 1]) < 3)
    assert (P[ing, 0] < wall(P[ing, 1], P[ing, 2]) - 1.0).any()                                     # the groove is not filled
    z = np.load(tmp_path / 'out' / 'labels.npz')
    assert len(z['face_labels']) == len(m.faces) and set(np.unique(z['face_labels'])) <= {1, 2, 3}
    fs = np.load(tmp_path / 'out' / 'cable_fill.npz')['face_source']
    pc = m.triangles_center[fs < 0]
    pl = z['face_labels'][fs < 0] == 1
    assert pc[pl, 2].max() < 3.2 and pc[~pl, 2].min() > 2.4                                       # the seam continues straight across the patch
    assert np.load(tmp_path / 'out' / 'cable_fill.npz')['face_source'].shape == (len(m.faces),)


def test_offset_pocket_on_a_mirrored_front_is_found_by_the_click_side(tmp_path):
    V, F, lab = make_front(pocket_y=7.0, mirror=True)
    res, _, _ = run_worker(tmp_path, V, F, lab)
    assert res['front']['sign'] == -1.0
    assert res['ready'] and res['applied'] and len(res['pockets']) == 1
    assert abs(res['pockets'][0]['centre_yz_mm'][0] - 7.0) < 0.6
    P, _ = filled_points(tmp_path)
    inpk = (np.abs(P[:, 1] - 7.0) < POCKET['w'] / 2 - 0.5) & (P[:, 2] > POCKET['z0'] + 0.5) & (P[:, 2] < POCKET['z1'] - 0.5)
    assert np.abs(-P[inpk, 0] - wall(P[inpk, 1], P[inpk, 2])).max() < 0.1


def test_no_pocket_is_a_ready_no_op(tmp_path):
    V, F, lab = make_front(pocket=False)
    res, stl, labels = run_worker(tmp_path, V, F, lab)
    assert res['ready'] and not res['applied'] and res['pockets'] == []
    assert (tmp_path / 'out' / 'filled.stl').read_bytes() == stl.read_bytes()
    assert (tmp_path / 'out' / 'labels.npz').read_bytes() == labels.read_bytes()


def test_wavy_surrounding_wall_is_not_ready(tmp_path):
    V, F, lab = make_front(wave=0.7)
    res, _, _ = run_worker(tmp_path, V, F, lab)
    assert not res['ready'] and 'CABLE_INFERRED_WALL_NOT_SMOOTH' in res['blocking']
    assert not (tmp_path / 'out' / 'filled.stl').exists()


def test_report_and_settings_through_the_tool(tmp_path):
    ws = tmp_path / 'ws'
    V, F, lab = make_front(pocket_y=-4.0)
    write_case(ws / 'in', V, F, lab)
    tools = Tools(Brain(ws))
    with pytest.raises(BrainError) as exc:
        tools.call('brain_mouse_scan_cable_fill', {'relative_path': 'in/front.stl', 'unit': 'mm', 'degree': 7})
    assert exc.value.code == 'CABLE_SETTINGS'
    with pytest.raises(BrainError) as exc:
        tools.call('brain_mouse_scan_cable_fill', {'relative_path': 'in/front.stl', 'unit': 'furlong'})
    assert exc.value.code == 'SCAN_UNIT'
    try:
        smod.find_scan_python(ws)
    except BrainError:
        pytest.skip('no scan python on this machine')
    args = {'relative_path': 'in/front.stl', 'unit': 'mm', 'labels_path': 'in/front_labels.npz'}
    rep = tools.call('brain_mouse_scan_cable_fill', args)
    assert rep['status'] == 'READY' and rep['applied'] and rep['summary']['pockets_filled'] == 1
    assert rep['summary']['wall_fit_p95_mm'] < 0.1 and rep['checks']['inferred_wall_smooth'] == 'PASS'
    assert (ws / rep['outputs']['filled']['relative_path']).is_file() and (ws / rep['outputs']['labels']['relative_path']).is_file()
    assert rep['downstream']['mesh'] == rep['outputs']['filled']['relative_path']
    again = tools.call('brain_mouse_scan_cable_fill', args)
    assert again.get('cached') and again['cf_id'] == rep['cf_id']
