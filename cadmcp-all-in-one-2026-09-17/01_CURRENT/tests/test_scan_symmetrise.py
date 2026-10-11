"""brain_mouse_scan_symmetrise: synthetic mouse-like dome (no scan data). Symmetry is never forced: scan-error bias is corrected, a shifted half
or a one-sided bulge is kept as scanned. Geometry tests run the worker in this process (needs trimesh + scipy); the end-to-end test goes through
the tool and the separate scan python (skipped without one)."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import scan_symmetrise as ss
from cadmcp_brain.studio import scan_symmetrise_worker as W
from cadmcp_brain.studio import scan_model as smod

trimesh = pytest.importorskip('trimesh')
pytest.importorskip('scipy')

PLANE_Y = 1.5          # true mirror plane y = 1.5, rotated 2 deg about z
ROT_DEG = 2.0


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code
    return exc.value


def dome(sub=4):
    """Half-ellipsoid-like mouse dome 120 x 64 x 36, symmetric about y = 0 (before the frame change)."""
    s = trimesh.creation.icosphere(subdivisions=sub)
    V = np.asarray(s.vertices) * [60.0, 32.0, 18.0]
    V[:, 2] = np.where(V[:, 2] < 0, V[:, 2] * 0.15, V[:, 2])           # flat-ish bottom
    V[:, 0] += 6.0 * (V[:, 2] / 18.0) ** 2                             # hump toward the rear
    return V, np.asarray(s.faces)


def frame(V):
    a = np.radians(ROT_DEG)
    R = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    return V @ R.T + [0, PLANE_Y, 0], R @ np.array([0, 1.0, 0])


def labels_for(V, F):
    c = V[F].mean(1)
    top = np.flatnonzero(c[:, 2] > 0.5)
    bottom = np.flatnonzero(c[:, 2] <= 0.5)
    return {'top_shell': top.tolist(), 'bottom_plate': bottom.tolist()}


def case(tmp: Path, kind: str):
    V, F = dome()
    V = V.copy()
    rng = np.random.default_rng(3)
    if kind == 'bias':                       # scan error only: 0.6 mm smooth one-side bias + 0.05 mm noise -> symmetric
        s = V[:, 1] > 0
        V[s, 1] += 0.6 * (0.5 + 0.5 * np.sin(V[s, 0] / 15.0))
        V += rng.normal(0, 0.05, V.shape)
    elif kind == 'shift':                    # asymmetric design: one half shifted 8 mm forward -> must NOT be forced
        s = V[:, 1] > 0
        V[s, 0] += 8.0 * np.clip(V[s, 1] / 6.0, 0, 1)
    elif kind == 'bulge':                    # asymmetric design: thumb-rest bulge up to 8 mm on one flank
        s = V[:, 1] > 5
        g = np.exp(-((V[s, 0] + 10) ** 2 / (2 * 18 ** 2) + (V[s, 2] - 8) ** 2 / (2 * 7 ** 2)))
        V[s, 1] += 8.0 * g
    Vf, n_true = frame(V)
    tmp.mkdir(parents=True, exist_ok=True)
    trimesh.Trimesh(Vf, F, process=False).export(tmp / 'in.stl')
    (tmp / 'labels.json').write_text(json.dumps(labels_for(V, F)), encoding='utf-8')
    return Vf, F, n_true


def run_worker(tmp: Path, **params):
    return W.run({'inputs': {'mesh': str(tmp / 'in.stl'), 'labels': str(tmp / 'labels.json')}, 'params': params, 'out_dir': str(tmp / 'out')})


def mirror_residual(V, F, n, d):
    return W.closest_on_surface(V, F, W.mirror_pts(V, n, d))[1]


def test_scan_error_is_symmetrised(tmp_path):
    Vf, F, n_true = case(tmp_path, 'bias')
    res = run_worker(tmp_path)
    n = np.asarray(res['plane']['normal'])
    assert np.degrees(np.arccos(min(1.0, abs(n @ n_true)))) < 0.5
    assert abs(res['plane']['d'] - PLANE_Y * (n @ n_true) / abs(n @ n_true) * (n_true @ [0, 1, 0])) < 0.5
    t = res['symmetry_test']
    assert t['global']['plane_valid'] and t['regions']['top_shell']['symmetric']
    assert 'top_shell' in res['symmetrise']['symmetrised_regions'] and 'bottom_plate' not in res['symmetrise']['symmetrised_regions']
    out = trimesh.load(tmp_path / 'out' / 'symmetrised.stl', process=False)
    out.merge_vertices()
    assert len(out.faces) == len(F)
    sy = res['symmetrise']
    assert sy['residual_after']['p95'] < 0.6 * sy['residual_before']['p95']
    assert sy['displacement']['max'] <= 1.0 + 1e-6 and sy['max_displacement_kept_faces_mm'] == 0.0
    plane = json.loads((tmp_path / 'out' / 'mirror_plane.json').read_text(encoding='utf-8'))
    assert plane['plane']['equation'] == 'normal . x = d'


@pytest.mark.parametrize('kind', ['shift', 'bulge'])
def test_real_asymmetry_is_not_forced(tmp_path, kind):
    Vf, F, n_true = case(tmp_path, kind)
    res = run_worker(tmp_path)
    t = res['symmetry_test']
    reg = t['regions']['top_shell']
    assert reg['asym_cells'] > 0 or not reg['symmetric']
    mask = np.load(tmp_path / 'out' / 'symmetry_mask.npz')
    asym = mask['asymmetric_face']
    assert asym.any()
    n, d = np.asarray(res['plane']['normal']), res['plane']['d']
    P = Vf[F].reshape(-1, 3)                                            # per face corner (vertex order of the STL may differ)
    resid = W.closest_on_surface(Vf, F, W.mirror_pts(P, n, d))[1].reshape(-1, 3)
    far = np.flatnonzero(resid.min(1) > 1.5 * t['threshold_mm'])          # clearly asymmetric faces
    assert len(far) > 0
    assert mask['face_displacement_mm'][far].max() == 0.0               # never moved toward the other side
    assert asym[far].mean() >= 0.8                                       # mostly in failing cells; the rest is beyond the correspondence cap
    assert res['symmetrise']['max_displacement_kept_faces_mm'] == 0.0


def test_fixed_region_and_mirror_landing_kept(tmp_path):
    Vf, F, _ = case(tmp_path, 'bias')
    lab = json.loads((tmp_path / 'labels.json').read_text(encoding='utf-8'))
    c = Vf[F].mean(1)
    btn = np.flatnonzero((c[:, 1] > 20) & (np.abs(c[:, 0]) < 15) & (c[:, 2] > 3)).tolist()
    lab['top_shell'] = sorted(set(lab['top_shell']) - set(btn))
    lab['side_button_1'] = btn
    (tmp_path / 'labels.json').write_text(json.dumps(lab), encoding='utf-8')
    res = run_worker(tmp_path)
    mask = np.load(tmp_path / 'out' / 'symmetry_mask.npz')
    assert not mask['symmetrised_face'][btn].any()
    assert res['symmetrise']['faces_mirroring_onto_fixed'] > 0
    assert 'side_button_1' in res['symmetrise']['fixed_regions_present']


def test_no_plane_written_unchanged(tmp_path):
    rng = np.random.default_rng(0)
    m = trimesh.creation.icosphere(subdivisions=3)
    V = np.asarray(m.vertices) * [40, 25, 15] + rng.normal(0, 0.0, (len(m.vertices), 3))
    V[V[:, 0] > 0] *= [1.0, 1.0, 2.5]                                    # strongly lopsided blob
    V[(V[:, 1] > 0) & (V[:, 0] < 0)] *= [1.8, 1.0, 1.0]
    tmp_path.mkdir(exist_ok=True)
    trimesh.Trimesh(V, m.faces, process=False).export(tmp_path / 'in.stl')
    res = W.run({'inputs': {'mesh': str(tmp_path / 'in.stl'), 'labels': None}, 'params': {'abs_threshold_mm': 0.2, 'rel_threshold': 0.0, 'plane_gate_factor': 1.0, 'plane_search': 'pca'},
                 'out_dir': str(tmp_path / 'out')})
    if not res['symmetry_test']['global']['plane_valid']:
        assert res['symmetrise']['moved_vertices'] == 0
    assert res['warnings']


def test_validation(tmp_path):
    case(tmp_path / 'c', 'bias')
    ws = tmp_path
    rejects('SCAN_UNIT', lambda: ss.scan_symmetrise(ws, 'c/in.stl', 'px'))
    rejects('SYMMETRISE_SETTINGS', lambda: ss.scan_symmetrise(ws, 'c/in.stl', 'mm', abs_threshold_mm=0.0))
    rejects('SYMMETRISE_SETTINGS', lambda: ss.scan_symmetrise(ws, 'c/in.stl', 'mm', passes=2.5))
    rejects('SYMMETRISE_SETTINGS', lambda: ss.scan_symmetrise(ws, 'c/in.stl', 'mm', normal_hint=[0, 0, 0], plane_search='hint'))
    rejects('SYMMETRISE_SETTINGS', lambda: ss.scan_symmetrise(ws, 'c/in.stl', 'mm', normal_hint=[0, 1, 0]))
    rejects('SYMMETRISE_SETTINGS', lambda: ss.scan_symmetrise(ws, 'c/in.stl', 'mm', plane_search='auto'))
    rejects('SYMMETRISE_SETTINGS', lambda: ss.scan_symmetrise(ws, 'c/in.stl', 'mm', fixed_regions='wheel'))
    rejects('SCAN_FILE', lambda: ss.scan_symmetrise(ws, 'c/labels.json', 'mm'))
    rejects('SYMMETRISE_LABELS', lambda: ss.scan_symmetrise(ws, 'c/in.stl', 'mm', labels_path='c/in.stl'))


def test_tool_listed(tmp_path):
    tools = {t['name']: t for t in Tools(Brain(tmp_path)).list()}
    t = tools['brain_mouse_scan_symmetrise']
    assert t['annotations']['readOnlyHint'] is False
    assert 'never forced' in t['description']


def _scan_python(ws):
    try:
        p = smod.find_scan_python(ws)
    except BrainError:
        return None
    import subprocess
    ok = subprocess.run([str(p), '-c', 'import trimesh, scipy'], capture_output=True).returncode == 0
    return p if ok else None


def test_end_to_end_cached(tmp_path):
    if _scan_python(tmp_path) is None:
        pytest.skip('no scan python with trimesh + scipy')
    case(tmp_path / 'c', 'bias')
    rep = ss.scan_symmetrise(tmp_path, 'c/in.stl', 'mm', labels_path='c/labels.json')
    assert rep['status'] == 'READY', rep['blocking_reasons']
    assert rep['checks']['kept_faces_unmoved'] == 'PASS' and rep['checks']['face_order_unchanged'] == 'PASS'
    assert 'top_shell' in rep['symmetric_regions']
    assert (tmp_path / rep['outputs']['symmetrised']['relative_path']).is_file()
    again = ss.scan_symmetrise(tmp_path, 'c/in.stl', 'mm', labels_path='c/labels.json')
    assert again['cached'] is True and again['symmetry_id'] == rep['symmetry_id']
