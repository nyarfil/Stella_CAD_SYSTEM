"""brain_mouse_scan_flush: synthetic tilted slab with two protruding skates. No scan data is used or stored.

The geometry tests run the worker in this process (needs trimesh: extra `scan-grooves`; skipped when missing); the end-to-end test goes through the
tool and the separate scan python (skipped without one).
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import scan_flush as sf
from cadmcp_brain.studio import scan_flush_worker as W
from cadmcp_brain.studio import scan_model as smod

trimesh = pytest.importorskip('trimesh')

TILT_DEG = 5.3
SKATE_H = 0.7


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code
    return exc.value


def tilt_matrix(deg, axis=(0.3, 1.0, 0.0)):
    a = np.asarray(axis, float)
    a /= np.linalg.norm(a)
    t = np.radians(deg)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(t) * K + (1 - np.cos(t)) * K @ K


def make_slab(deg=TILT_DEG, bump=False):
    """80 x 40 x 12 slab (plate at z 0) + two skates 0.7 mm below it, then tilted by deg and moved to z ~ 11. Returns (mesh, plate ids, original vertices)."""
    slab = trimesh.creation.box(extents=(80, 40, 12))
    slab.apply_translation((0, 0, 6))
    for _ in range(4):
        slab = slab.subdivide()
    n_slab = len(slab.faces)
    parts = [slab]
    for cx in (-25.0, 25.0):
        sk = trimesh.creation.box(extents=(8, 6, SKATE_H))
        sk.apply_translation((cx, 0, -SKATE_H / 2))
        parts.append(sk.subdivide().subdivide())
    m = trimesh.util.concatenate(parts)
    V = np.asarray(m.vertices, float)
    if bump:                                              # roughen the plate a little (a scan is never perfectly flat)
        rng = np.random.default_rng(1)
        down = np.abs(V[:, 2]) < 1e-9
        V[down] += np.c_[np.zeros((down.sum(), 2)), rng.normal(0, 0.01, down.sum())]
    plate = np.flatnonzero((m.face_normals[:n_slab, 2] < -0.99))
    V0 = V.copy()
    V = V @ tilt_matrix(deg).T
    V[:, 2] += 11.0
    return trimesh.Trimesh(V, m.faces, process=False), plate, V0


def write_case(folder: Path, deg=TILT_DEG, bump=False, labels=True):
    m, plate, V0 = make_slab(deg, bump)
    folder.mkdir(parents=True, exist_ok=True)
    m.export(folder / 'in.stl')
    if labels:
        (folder / 'labels.json').write_text(json.dumps({'regions': {'bottom_plate': {'face_ids': plate.tolist()}, 'top_shell': []}}), encoding='utf-8')
    return m, plate, V0


def request(folder: Path, labels=True, **params):
    return {'input_path': str(folder / 'in.stl'), 'labels_path': str(folder / 'labels.json') if labels else None, 'unit_scale': 1.0, 'out_dir': str(folder / 'out'),
            'params': {**W.DEFAULTS, **params}}


def _load(p):
    m = trimesh.load(p, process=False)
    m.merge_vertices()
    return m


@pytest.fixture(scope='module')
def case(tmp_path_factory):
    folder = tmp_path_factory.mktemp('slab')
    m, plate, V0 = write_case(folder, bump=True)
    res = W.run(request(folder))
    return {'folder': folder, 'mesh': m, 'plate': plate, 'V0': V0, 'res': res, 'out': _load(folder / 'out' / 'flushed.stl')}


def test_synthetic_slab_is_a_valid_input():
    m, plate, _ = make_slab()
    assert m.is_watertight and m.volume > 0 and len(plate) > 500


def test_tilt_removed_and_plate_on_z0(case):
    r = case['res']
    assert r['fit']['tilt_before_deg'] == pytest.approx(TILT_DEG, abs=0.05)
    assert r['after']['fit_tilt_deg'] < 0.02
    assert r['after']['within_tol_pct_area'] > 99.0
    assert abs(r['after']['mean_z_mm']) < 0.01 and r['after']['rms_z_mm'] < 0.03
    assert r['fit']['inlier_area_pct'] > 95.0 and r['fit']['inlier_area_mm2'] == pytest.approx(80 * 40, rel=0.03)
    assert r['fit']['rms_mm'] < 0.03


def test_skates_stay_below_zero_and_are_reported(case):
    ext = case['res']['extent']
    assert ext['protrusion_below_plate_mm'] == pytest.approx(SKATE_H, abs=0.03)
    assert ext['lowest_z_after_mm'] == pytest.approx(-SKATE_H, abs=0.03)


def test_transform_reproduces_the_output_and_is_rigid(case):
    t = case['res']['transform']
    Rm, shift = np.array(t['Rm']), t['z_shift']
    assert np.allclose(Rm @ Rm.T, np.eye(3), atol=1e-12) and np.linalg.det(Rm) == pytest.approx(1.0)
    m = case['mesh']
    c = np.asarray(m.vertices)[m.faces].mean(1)                                       # compare per face: the STL round trip renumbers vertices
    c2 = c @ Rm.T
    c2[:, 2] += shift
    out = case['out']
    assert np.abs(c2 - np.asarray(out.vertices)[out.faces].mean(1)).max() < 1e-3      # STL float32 precision
    T4 = np.array(t['matrix4'])
    assert np.allclose(c @ T4[:3, :3].T + T4[:3, 3], c2)
    assert t['plane_tilt_deg_removed'] == pytest.approx(TILT_DEG, abs=0.05)
    assert case['res']['mesh']['volume_mm3_after'] == pytest.approx(case['res']['mesh']['volume_mm3_before'], rel=1e-5)   # rigid


def test_face_order_and_labels_survive(case):
    assert len(case['out'].faces) == len(case['mesh'].faces)
    out = case['out']
    cen = out.vertices[out.faces].mean(1)
    assert np.abs(cen[case['plate'], 2]).max() < 0.2                                   # the labelled plate faces are the ones on z = 0
    assert (case['folder'] / 'out' / 'labels.json').read_bytes() == (case['folder'] / 'labels.json').read_bytes()


def test_flush_is_idempotent(case, tmp_path):
    out = case['folder'] / 'out'
    (tmp_path / 'in.stl').write_bytes((out / 'flushed.stl').read_bytes())
    (tmp_path / 'labels.json').write_bytes((out / 'labels.json').read_bytes())
    r = W.run(request(tmp_path))
    assert r['fit']['tilt_before_deg'] < 0.02 and abs(r['transform']['z_shift']) < 0.02


def test_works_without_labels_and_warns(tmp_path):
    write_case(tmp_path, labels=False)
    r = W.run(request(tmp_path, labels=False))
    assert r['fit']['plate_source'] == 'all_faces' and any(w['code'] == 'FLUSH_NO_LABELS' for w in r['warnings'])
    assert r['fit']['tilt_before_deg'] == pytest.approx(TILT_DEG, abs=0.05) and r['after']['within_tol_pct_area'] > 90.0


def test_unit_scale_is_applied(tmp_path):
    write_case(tmp_path)
    req = request(tmp_path)
    req['unit_scale'] = 10.0                                                            # file read as cm
    r = W.run(req)
    assert r['extent']['protrusion_below_plate_mm'] == pytest.approx(SKATE_H * 10, abs=0.3)


def test_refusals(tmp_path):
    write_case(tmp_path, deg=15.0)
    err = rejects('FLUSH_TILT_TOO_LARGE', lambda: _run(request(tmp_path, max_tilt_deg=10.0)))
    assert err.details['tilt_deg'] == pytest.approx(15.0, abs=0.2)
    lab = json.loads((tmp_path / 'labels.json').read_text())
    del lab['regions']['bottom_plate']
    (tmp_path / 'labels.json').write_text(json.dumps(lab))
    rejects('FLUSH_PLATE_LABEL_MISSING', lambda: _run(request(tmp_path)))
    (tmp_path / 'labels.json').write_text(json.dumps({'bottom_plate': [10 ** 9]}))
    rejects('FLUSH_LABELS', lambda: _run(request(tmp_path)))
    (tmp_path / 'labels.json').write_text(json.dumps({'bottom_plate': [0, 1, 2]}))
    r = _run(request(tmp_path))                      # an unusable label is only a hint: the whole mesh is used, with a warning
    assert any(w['code'] == 'FLUSH_LABEL_UNUSABLE' for w in r['warnings'])


def _run(req):
    try:
        return W.run(req)
    except W.FlushError as exc:
        raise BrainError(exc.code, exc.message, exc.details) from exc


def test_open_mesh_still_flushes_with_a_warning(tmp_path):
    m, plate, _ = make_slab()
    keep = np.ones(len(m.faces), bool)
    keep[-4:] = False                                                                 # drop faces of the last skate (plate ids stay valid)
    trimesh.Trimesh(m.vertices, m.faces[keep], process=False).export(tmp_path / 'in.stl')
    r = W.run(request(tmp_path, labels=False))
    assert any(w['code'] == 'FLUSH_MESH_NOT_WATERTIGHT' for w in r['warnings']) and r['mesh']['volume_mm3_before'] is None
    assert r['fit']['tilt_before_deg'] == pytest.approx(TILT_DEG, abs=0.05)


def test_inside_out_mesh_is_refused(tmp_path):
    m, _, _ = make_slab()
    trimesh.Trimesh(m.vertices, m.faces[:, ::-1], process=False).export(tmp_path / 'in.stl')
    rejects('FLUSH_MESH_INSIDE_OUT', lambda: _run(request(tmp_path, labels=False)))


def test_npz_labels(tmp_path):
    m, plate, _ = write_case(tmp_path)
    fl = np.zeros(len(m.faces), np.int16)
    fl[plate] = 3
    np.savez(tmp_path / 'l.npz', face_labels=fl, codes=np.array(['top_shell=1', 'bottom_plate=3']))
    assert np.array_equal(W.read_plate_ids(tmp_path / 'l.npz', len(m.faces)), plate)


def test_tool_validates_before_running(tmp_path):
    (tmp_path / 'a.stl').write_text('x')
    (tmp_path / 'l.json').write_text('{}')
    rejects('SCAN_UNIT', lambda: sf.scan_flush(tmp_path, 'a.stl', 'furlong'))
    rejects('FLUSH_SETTINGS', lambda: sf.scan_flush(tmp_path, 'a.stl', 'mm', plate_tolerance_mm=0.0))
    rejects('FLUSH_SETTINGS', lambda: sf.scan_flush(tmp_path, 'a.stl', 'mm', max_tilt_deg=90))
    (tmp_path / 'a.ply').write_text('x')
    rejects('SCAN_FILE', lambda: sf.scan_flush(tmp_path, 'a.ply', 'mm'))
    rejects('UNSAFE_PATH', lambda: sf.scan_flush(tmp_path, 'nope.stl', 'mm'))
    rejects('UNSAFE_PATH', lambda: sf.scan_flush(tmp_path, '../a.stl', 'mm'))
    (tmp_path / 'l.txt').write_text('x')
    rejects('FLUSH_LABELS', lambda: sf.scan_flush(tmp_path, 'a.stl', 'mm', labels_path='l.txt'))
    t = Tools(Brain(tmp_path))
    names = {x['name']: x for x in t.list()}
    assert 'brain_mouse_scan_flush' in names and names['brain_mouse_scan_flush']['annotations']['readOnlyHint'] is False
    props = names['brain_mouse_scan_flush']['inputSchema']['properties']
    assert props['plate_tolerance_mm']['default'] == 0.12 and 'labels_path' in props
    rejects('SCAN_UNIT', lambda: t.call('brain_mouse_scan_flush', {'relative_path': 'a.stl', 'unit': 'x'}))


def test_tool_end_to_end_in_the_scan_python(tmp_path, monkeypatch):
    try:
        python = smod.find_scan_python(Path('.'))
    except BrainError:
        pytest.skip('no scan python (CADMCP_SCAN_PYTHON / .venv-scan)')
    monkeypatch.setenv(smod.ENV_PYTHON, str(python))
    write_case(tmp_path / 'in')
    t = Tools(Brain(tmp_path))
    args = {'relative_path': 'in/in.stl', 'labels_path': 'in/labels.json', 'unit': 'mm'}
    r = t.call('brain_mouse_scan_flush', args)
    assert r['status'] == 'READY' and r['checks']['plate_on_z0'] == 'PASS' and r['checks']['residual_tilt'] == 'PASS'
    assert r['residual']['tilt_before_deg'] == pytest.approx(TILT_DEG, abs=0.05) and r['residual']['plate_within_tolerance_pct_area'] > 99
    folder = tmp_path / 'mouse' / 'scans' / r['flush_id']
    for item in r['outputs'].values():
        assert (tmp_path / item['relative_path']).is_file() and len(item['sha256']) == 64
    assert r['downstream']['mesh'].endswith('flushed.stl') and r['downstream']['labels'].endswith('labels.json')
    assert (folder / sf.REPORT).is_file() and not list((tmp_path / 'mouse' / 'scans').glob('*.tmp-*'))
    again = t.call('brain_mouse_scan_flush', args)
    assert again['cached'] is True and again['flush_id'] == r['flush_id']
    (folder / 'flushed.stl').write_bytes(b'changed')
    rejects('FLUSH_OUTPUT_CHANGED', lambda: t.call('brain_mouse_scan_flush', args))
    (tmp_path / 'in' / 'bad.json').write_text('{"top_shell": [1]}')
    rejects('FLUSH_PLATE_LABEL_MISSING', lambda: t.call('brain_mouse_scan_flush', {**args, 'labels_path': 'in/bad.json'}))


def test_label_agrees_gives_no_disagreement_warning(tmp_path):
    write_case(tmp_path)
    r = W.run(request(tmp_path))
    assert not any(w['code'] == 'FLUSH_LABEL_DISAGREES' for w in r['warnings'])


def test_wrong_label_is_only_a_hint(tmp_path):
    m, plate, _ = write_case(tmp_path, bump=True)
    down = np.where(np.asarray(m.face_normals)[:, 2] < -0.9)[0]
    other = np.setdiff1d(down, plate)
    if len(other) < 10:
        pytest.skip('synthetic slab has no other down-facing faces')
    (tmp_path / 'labels.json').write_text(json.dumps({'bottom_plate': other.tolist()}), encoding='utf-8')
    r = W.run(request(tmp_path))
    assert r['fit']['tilt_before_deg'] == pytest.approx(TILT_DEG, abs=0.1)
