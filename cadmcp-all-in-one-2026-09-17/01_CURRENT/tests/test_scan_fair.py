"""brain_mouse_scan_fair: synthetic closed ellipsoid mesh + sinusoidal ripple + one deliberate step feature (no scan data).
Ripple removed, step kept, volume kept, face order unchanged. Worker runs in this process; end-to-end goes through the tool + scan python."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import scan_fair as sf
from cadmcp_brain.studio import scan_fair_worker as W
from cadmcp_brain.studio import scan_model as smod

trimesh = pytest.importorskip('trimesh')
pytest.importorskip('scipy')

RIPPLE_A = 0.25      # mm, wavelength ~ 8 mm
STEP_H = 3.0         # mm raised compact pad (a feature, not ripple)


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code


def make(tmp: Path):
    s = trimesh.creation.icosphere(subdivisions=5)                      # ~20k faces
    V0 = np.asarray(s.vertices) * [45.0, 30.0, 20.0]
    F = np.asarray(s.faces)
    nrm = V0 / [45.0 ** 2, 30.0 ** 2, 20.0 ** 2]
    nrm /= np.linalg.norm(nrm, axis=1)[:, None]
    ripple = RIPPLE_A * np.sin(V0[:, 0] * 2 * np.pi / 8.0) * np.sin(V0[:, 1] * 2 * np.pi / 8.0)
    pad = (np.hypot(V0[:, 0] - 10, V0[:, 1] - 5) < 7) & (V0[:, 2] > 5)
    step = np.where(pad, STEP_H, 0.0)
    V = V0 + nrm * (ripple + step)[:, None]
    tmp.mkdir(parents=True, exist_ok=True)
    trimesh.Trimesh(V, F, process=False).export(tmp / 'in.stl')
    return V0, V, F, nrm, pad


def faired_vertices(path, F, n):
    """Per-vertex positions of an exported STL (soup) in the input vertex order, via the face order (unchanged)."""
    T = np.asarray(trimesh.load(str(path), process=False).triangles)
    Vo = np.zeros((n, 3))
    Vo[F.ravel()] = T.reshape(-1, 3)
    return Vo


def vol(V, F):
    return W.signed_volume(V, F)


def run_worker(tmp, **params):
    return W.run({'inputs': {'mesh': str(tmp / 'in.stl')}, 'params': {'plate_freeze': 'off', **params}, 'out_dir': str(tmp / 'out')})


def test_ripple_removed_step_kept_volume_kept(tmp_path):
    V0, V, F, nrm, pad = make(tmp_path)
    r = run_worker(tmp_path, min_wavelength_mm=14.0)
    Vo = faired_vertices(tmp_path / 'out' / 'faired.stl', F, len(V0))
    assert r['mesh']['watertight_after'] is True
    assert abs(r['volume']['change_pct']) < 0.5
    # ripple part of the error (off the pad) is cut by at least 2.5x
    off = ~pad & (np.linalg.norm(V0[:, :2] - [10, 5], axis=1) > 14)
    err_in = np.einsum('ij,ij->i', V - V0, nrm)[off]
    err_out = np.einsum('ij,ij->i', Vo - V0, nrm)[off]
    assert np.sqrt((err_out ** 2).mean()) < 0.4 * np.sqrt((err_in ** 2).mean())
    # the raised pad keeps most of its height (a plain filter would flatten a 14 mm pad)
    centre = (np.hypot(V0[:, 0] - 10, V0[:, 1] - 5) < 3) & (V0[:, 2] > 5)
    kept = np.einsum('ij,ij->i', Vo - V0, nrm)[centre].mean()
    assert kept > 0.6 * STEP_H
    assert r['ripple_rms_mm']['wavelength_7_mm']['ratio'] < 0.6
    assert r['protected']['auto_features'] > 0
    comps = r['protected']['feature_components']
    assert comps and abs(comps[0]['centre_mm'][0] - 10) < 6 and comps[0]['sign'] == 'raised'
    assert r['ripple_rms_mm']['wavelength_7_mm']['unprotected_ratio'] < 0.6


def test_feature_protection_off_flattens_more(tmp_path):
    V0, V, F, nrm, pad = make(tmp_path)
    a = run_worker(tmp_path, min_wavelength_mm=14.0)
    b = run_worker(tmp_path, min_wavelength_mm=14.0, feature_protection='off')
    assert b['protected']['auto_features'] == 0
    assert b['deviation_mm']['max'] > a['deviation_mm']['max']


def test_labels_fixed_region_is_frozen(tmp_path):
    V0, V, F, nrm, pad = make(tmp_path)
    fpad = np.flatnonzero(pad[F].all(1))
    (tmp_path / 'labels.json').write_text(json.dumps({'wheel': fpad.tolist()}), encoding='utf-8')
    r = W.run({'inputs': {'mesh': str(tmp_path / 'in.stl'), 'labels': str(tmp_path / 'labels.json')},
               'params': {'plate_freeze': 'off', 'min_wavelength_mm': 14.0, 'fixed_regions': ['wheel', 'nothere']}, 'out_dir': str(tmp_path / 'out2')})
    Vo = faired_vertices(tmp_path / 'out2' / 'faired.stl', F, len(V0))
    ids = np.unique(F[fpad])
    assert np.abs(Vo[ids] - V[ids]).max() < 1e-2
    assert r['labels']['regions_frozen'] == ['wheel'] and r['labels']['regions_missing'] == ['nothere']


def test_plate_found_generic_orientation(tmp_path):
    s = trimesh.creation.box(extents=[60, 40, 20])
    s = s.subdivide().subdivide().subdivide().subdivide()
    R = trimesh.transformations.rotation_matrix(0.7, [1, 1, 0])
    s.apply_transform(R)
    s.export(tmp_path / 'in.stl')
    V, F = np.asarray(s.vertices), np.asarray(s.faces)
    pl = W.find_plate(V, F, 0.02, 3.0)
    assert pl is not None and pl[3] > 0.2


def test_validation(tmp_path):
    make(tmp_path / 'c')
    ws = tmp_path
    rejects('SCAN_UNIT', lambda: sf.scan_fair(ws, 'c/in.stl', 'px'))
    rejects('FAIR_SETTINGS', lambda: sf.scan_fair(ws, 'c/in.stl', 'mm', min_wavelength_mm=0.5))
    rejects('FAIR_SETTINGS', lambda: sf.scan_fair(ws, 'c/in.stl', 'mm', feature_protection='yes'))
    rejects('FAIR_SETTINGS', lambda: sf.scan_fair(ws, 'c/in.stl', 'mm', fixed_regions='wheel'))
    rejects('UNSAFE_PATH', lambda: sf.scan_fair(ws, 'c/missing.stl', 'mm'))


def test_tool_listed(tmp_path):
    t = {t['name']: t for t in Tools(Brain(tmp_path)).list()}['brain_mouse_scan_fair']
    assert t['annotations']['readOnlyHint'] is False
    assert 'unit' in t['inputSchema']['required'] and 'same face order' in t['description']


def _scan_python(ws):
    try:
        p = smod.find_scan_python(ws)
    except BrainError:
        return None
    import subprocess
    return p if subprocess.run([str(p), '-c', 'import trimesh, scipy'], capture_output=True).returncode == 0 else None


def test_end_to_end_cached(tmp_path):
    if _scan_python(tmp_path) is None:
        pytest.skip('no scan python with trimesh + scipy')
    make(tmp_path / 'c')
    rep = sf.scan_fair(tmp_path, 'c/in.stl', 'mm', min_wavelength_mm=14.0, plate_freeze='off', tol_p95_mm=1.0)
    assert rep['status'] == 'READY', rep['blocking_reasons']
    assert rep['checks']['face_order_unchanged'] == 'PASS'
    assert (tmp_path / rep['outputs']['faired']['relative_path']).is_file()
    again = sf.scan_fair(tmp_path, 'c/in.stl', 'mm', min_wavelength_mm=14.0, plate_freeze='off', tol_p95_mm=1.0)
    assert again['cached'] is True and again['fair_id'] == rep['fair_id']
