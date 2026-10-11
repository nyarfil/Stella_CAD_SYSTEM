"""brain_mesh_backend / brain_mesh_ops: user-selected mesh backend, synthetic spheres only (no scan data).

numpy tests always run; pymeshlab tests need the separate scan python (skipped without it); cgal tests need a registered,
startable cgal-mcp service (skipped with the reason from cgal_link.status() otherwise). Equal-result checks compare each backend
against the studio numpy result on the same input."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.studio import cgal_link
from cadmcp_brain.studio import mesh_backend as mb

trimesh = pytest.importorskip('trimesh')
CGAL = cgal_link.status()
needs_cgal = pytest.mark.skipif(not CGAL.get('available'), reason=f'cgal-mcp not installed/registered: {CGAL.get("reason")}')


def _pml_ok(ws) -> bool:
    return bool(mb.availability('pymeshlab', ws).get('available'))


@pytest.fixture
def ws(tmp_path):
    sph = trimesh.creation.icosphere(2, 10.0)  # 320 faces, r 10 mm
    (tmp_path / 'm').mkdir()
    (tmp_path / 'm/a.stl').write_bytes(mb._stl_bytes(sph.vertices, sph.faces))
    (tmp_path / 'm/b.stl').write_bytes(mb._stl_bytes(sph.vertices * 1.01, sph.faces))
    holed = np.delete(sph.faces, [0, 50, 100], axis=0)  # three 3-edge holes
    (tmp_path / 'm/holed.stl').write_bytes(mb._stl_bytes(sph.vertices, holed))
    big = trimesh.creation.icosphere(3, 10.0)  # 1280 faces
    (tmp_path / 'm/big.stl').write_bytes(mb._stl_bytes(big.vertices, big.faces))
    return tmp_path


def T(ws):
    return Tools(Brain(ws))


def test_no_choice_asks_the_user_and_selection_stays_in_this_workspace(ws, tmp_path_factory):
    t = T(ws)
    r = t.call('brain_mesh_ops', {'operation': 'hausdorff', 'relative_path': 'm/a.stl', 'other_path': 'm/b.stl', 'unit': 'mm'})
    assert r['status'] == 'NEEDS_USER_CHOICE' and r['executed'] is False and r['automatic_choice'] is False
    assert [o['backend'] for o in r['options']] == ['numpy', 'pymeshlab', 'cgal']
    assert all({'offers', 'licence', 'limits', 'cost', 'available'} <= set(o) for o in r['options'])
    s = t.call('brain_mesh_backend', {'action': 'select', 'operation': 'hausdorff', 'backend': 'numpy', 'reason': 'user chose'})
    assert s['selections']['hausdorff']['backend'] == 'numpy'
    assert json.loads((ws / '.cadmcp/mesh-backend.json').read_text())['selections']['hausdorff']['backend'] == 'numpy'
    other = tmp_path_factory.mktemp('other')
    assert T(other).call('brain_mesh_backend', {})['selections']['hausdorff'] is None  # another project is untouched
    r = t.call('brain_mesh_ops', {'operation': 'hausdorff', 'relative_path': 'm/a.stl', 'other_path': 'm/b.stl', 'unit': 'mm'})
    assert r['status'] == 'READY' and r['backend_from'] == 'saved_selection' and r['cgal_used'] is False
    t.call('brain_mesh_backend', {'action': 'clear', 'operation': 'hausdorff'})
    assert t.call('brain_mesh_backend', {'operation': 'hausdorff'})['selections']['hausdorff'] is None


def test_unsupported_pairs_are_refused(ws):
    t = T(ws)
    with pytest.raises(Exception):
        t.call('brain_mesh_backend', {'action': 'select', 'operation': 'simplify', 'backend': 'numpy'})
    with pytest.raises(Exception):
        t.call('brain_mesh_ops', {'operation': 'simplify', 'relative_path': 'm/a.stl', 'unit': 'mm', 'backend': 'numpy', 'target_faces': 100})


def test_numpy_hausdorff_and_fill_holes(ws):
    t = T(ws)
    h = t.call('brain_mesh_ops', {'operation': 'hausdorff', 'relative_path': 'm/a.stl', 'other_path': 'm/b.stl', 'unit': 'mm', 'backend': 'numpy'})
    assert h['metrics']['hausdorff_mm'] == pytest.approx(0.1, abs=2e-3)  # vertices move 0.1 mm radially
    f = t.call('brain_mesh_ops', {'operation': 'fill_holes', 'relative_path': 'm/holed.stl', 'unit': 'mm', 'backend': 'numpy'})
    assert f['status'] == 'READY' and f['result']['boundary_loops'] == 0 and f['backend_metrics']['filled_hole_count'] == 3
    assert (ws / f['outputs']['mesh']['relative_path']).is_file()
    again = t.call('brain_mesh_ops', {'operation': 'fill_holes', 'relative_path': 'm/holed.stl', 'unit': 'mm', 'backend': 'numpy'})
    assert again.get('cached') is True


def test_absent_cgal_is_reported_without_fallback(ws, monkeypatch):
    monkeypatch.setenv(cgal_link.ENV_DISABLE, '1')
    r = T(ws).call('brain_mesh_ops', {'operation': 'fill_holes', 'relative_path': 'm/holed.stl', 'unit': 'mm', 'backend': 'cgal'})
    assert r['status'] == 'BACKEND_UNAVAILABLE' and r['executed'] is False and 'none' in r['fallback']


@needs_cgal
def test_cgal_equals_numpy_on_hausdorff_and_fill_holes(ws):
    t = T(ws)
    args = {'operation': 'hausdorff', 'relative_path': 'm/a.stl', 'other_path': 'm/b.stl', 'unit': 'mm'}
    n, c = t.call('brain_mesh_ops', {**args, 'backend': 'numpy'}), t.call('brain_mesh_ops', {**args, 'backend': 'cgal'})
    assert c['status'] == 'READY' and c['cgal_used'] is True and c['cgal']['cgal_version'] and c['cgal']['validation_status'] == 'passed'
    assert c['metrics']['hausdorff_mm'] == pytest.approx(n['metrics']['hausdorff_mm'], rel=0.02)
    a = {'operation': 'fill_holes', 'relative_path': 'm/holed.stl', 'unit': 'mm'}
    fn, fc = t.call('brain_mesh_ops', {**a, 'backend': 'numpy'}), t.call('brain_mesh_ops', {**a, 'backend': 'cgal'})
    assert fc['status'] == 'READY' and fc['result']['boundary_loops'] == 0 and fc['backend_metrics']['filled_hole_count'] == 3
    assert fc['result']['faces'] == 320 and fn['result']['faces'] == 320 + 6  # CGAL: one triangle per 3-edge hole; numpy: fan of 3
    assert fc['result']['independent_check_numpy']['b_to_a_mm']['max'] < 1e-9  # every source point stays on the result
    assert fc['result']['independent_check_numpy']['a_to_b_mm']['max'] == pytest.approx(fn['result']['independent_check_numpy']['a_to_b_mm']['max'], abs=0.05)


@needs_cgal
def test_cgal_simplify_validated_and_large_input_refused(ws):
    t = T(ws)
    s = t.call('brain_mesh_ops', {'operation': 'simplify', 'relative_path': 'm/a.stl', 'unit': 'mm', 'backend': 'cgal', 'target_faces': 160, 'max_deviation_mm': 1.0})
    assert s['status'] == 'READY' and s['result']['faces'] <= 160 and s['result']['boundary_loops'] == 0
    assert s['result']['independent_check_numpy']['hausdorff_mm'] <= 1.0
    big = t.call('brain_mesh_ops', {'operation': 'simplify', 'relative_path': 'm/big.stl', 'unit': 'mm', 'backend': 'cgal', 'target_faces': 600})
    assert big['status'] == 'REFUSED' and big['executed'] is False and not (ws / 'mouse/mesh_ops' / big['job_id']).exists()


def test_pymeshlab_matches_numpy_and_cgal(ws):
    if not _pml_ok(ws):
        pytest.skip('no separate scan python (CADMCP_SCAN_PYTHON) for pymeshlab')
    t = T(ws)
    args = {'operation': 'hausdorff', 'relative_path': 'm/a.stl', 'other_path': 'm/b.stl', 'unit': 'mm'}
    n, p = t.call('brain_mesh_ops', {**args, 'backend': 'numpy'}), t.call('brain_mesh_ops', {**args, 'backend': 'pymeshlab'})
    assert p['metrics']['hausdorff_mm'] == pytest.approx(n['metrics']['hausdorff_mm'], rel=0.02)
    s = t.call('brain_mesh_ops', {'operation': 'simplify', 'relative_path': 'm/a.stl', 'unit': 'mm', 'backend': 'pymeshlab', 'target_faces': 160, 'max_deviation_mm': 1.0})
    assert s['status'] == 'READY' and s['result']['faces'] <= 160
