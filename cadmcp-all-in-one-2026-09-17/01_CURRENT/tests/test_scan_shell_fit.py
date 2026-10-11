"""brain_mouse_shell_fit: synthetic mouse-like dome (no scan data). Half + mirror with exact mirror G1 when the symmetry report says
symmetric, one full face when it does not (never forced), short-wavelength ripple rejected, spans capped by min_wavelength_mm."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import scan_shell_fit as sf

trimesh = pytest.importorskip('trimesh')
pytest.importorskip('OCP')

ROT = np.radians(3.0)
R = np.array([[np.cos(ROT), -np.sin(ROT), 0], [np.sin(ROT), np.cos(ROT), 0], [0, 0, 1]])
SHIFT = np.array([0.0, 2.0, 0.0])
N_MIRROR = R @ [0, 1.0, 0]
D_MIRROR = float(N_MIRROR @ SHIFT)
N_CUT = R @ [1.0, 0, 0]
D_CUT = float(N_CUT @ SHIFT) + 35.0          # keep x_local <= 35 (front cut)


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code
    return exc.value


def dome_surface(V):
    """Smooth mouse-like dome, symmetric about y = 0 (local frame)."""
    V = V * [58.0, 31.0, 22.0]
    V[:, 0] += 5.0 * (np.clip(V[:, 2], 0, None) / 22.0) ** 2
    return V


def make(tmp: Path, ripple=0.0, bulge=0.0):
    s = trimesh.creation.icosphere(subdivisions=5)
    V = dome_surface(np.asarray(s.vertices, float))
    F = np.asarray(s.faces)
    if ripple:
        nrm = s.vertex_normals
        V = V + ripple * np.sin(2 * np.pi * V[:, 0] / 4.0)[:, None] * nrm
    if bulge:
        g = np.exp(-((V[:, 0] + 10) ** 2 / (2 * 15 ** 2) + (V[:, 2] - 10) ** 2 / (2 * 6 ** 2))) * (V[:, 1] > 0)
        V[:, 1] += bulge * g
    Vw = V @ R.T + SHIFT
    tmp.mkdir(parents=True, exist_ok=True)
    trimesh.Trimesh(Vw, F, process=False).export(tmp / 'in.stl')
    c = V[F].mean(1)
    lab = {'top_shell': np.flatnonzero(c[:, 2] > 3.0).tolist(), 'bottom_plate': np.flatnonzero(c[:, 2] <= 3.0).tolist()}
    (tmp / 'labels.json').write_text(json.dumps(lab), encoding='utf-8')
    rep = {'plane': {'normal': N_MIRROR.tolist(), 'd': D_MIRROR}, 'symmetry_test': {'global': {'plane_valid': True},
                                                                                   'regions': {'top_shell': {'symmetric': not bulge}, 'bottom_plate': {'symmetric': True}}}}
    (tmp / 'sym.json').write_text(json.dumps(rep), encoding='utf-8')
    return Vw, F


CUT = [{'normal': N_CUT.tolist(), 'd': D_CUT}]


def smooth_distance(tmp_ws: Path, rep, ripple_free_pts):
    """distance of points of the smooth (ripple-free) dome to the fitted skin (OCP)."""
    from cadmcp_brain.studio import cad_brep_lib as cb
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.gp import gp_Pnt
    sh = cb.read_step(tmp_ws / rep['outputs']['skin']['relative_path'])
    out = []
    for q in ripple_free_pts:
        d = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, q))).Vertex(), sh)
        out.append(d.Value())
    return np.asarray(out)


def test_half_mirror_g1(tmp_path):
    make(tmp_path / 'c')
    rep = sf.shell_fit(tmp_path, 'c/in.stl', 'mm', labels_path='c/labels.json', symmetry_report_path='c/sym.json', cut_planes=CUT)
    assert rep['mode_used'] == 'half'
    assert rep['status'] == 'READY', (rep['blocking_reasons'], rep['deviation'])
    assert rep['brep']['faces'] == 2 and rep['brep']['valid']
    assert rep['mirror_border']['G1_normal_angle_deg_max'] < 1e-6 and rep['mirror_border']['G0_gap_to_plane_mm'] < 1e-9
    assert rep['deviation']['all']['p95'] < 0.1
    assert rep['fit']['min_representable_wavelength_mm'] >= 10.0
    assert len(rep['layout']['corners']) == 4 and rep['layout'].get('inserted_corners')
    assert rep['deviation']['other_half_mirrored']['p95'] < 0.1
    again = sf.shell_fit(tmp_path, 'c/in.stl', 'mm', labels_path='c/labels.json', symmetry_report_path='c/sym.json', cut_planes=CUT)
    assert again['cached'] is True and again['fit_id'] == rep['fit_id']


def test_asymmetric_is_not_forced(tmp_path):
    make(tmp_path / 'c', bulge=8.0)
    rep = sf.shell_fit(tmp_path, 'c/in.stl', 'mm', labels_path='c/labels.json', symmetry_report_path='c/sym.json', cut_planes=CUT)
    assert rep['mode_used'] == 'full' and rep['mirror_border'] is None and rep['brep']['faces'] == 1
    assert 'asymmetric' in rep['symmetry_reason']
    rejects('SHELL_FIT_NOT_SYMMETRIC', lambda: sf.shell_fit(tmp_path, 'c/in.stl', 'mm', labels_path='c/labels.json', symmetry_report_path='c/sym.json',
                                                           cut_planes=CUT, mode='half'))


def test_ripple_rejected(tmp_path):
    Vw, F = make(tmp_path / 'c', ripple=0.25)
    rep = sf.shell_fit(tmp_path, 'c/in.stl', 'mm', labels_path='c/labels.json', symmetry_report_path='c/sym.json', cut_planes=CUT, tol_p95_mm=0.5)
    assert rep['status'] == 'READY'
    s = trimesh.creation.icosphere(subdivisions=5)
    Vs = dome_surface(np.asarray(s.vertices, float))
    loc = Vs[(Vs[:, 2] > 6) & (Vs[:, 0] < 30) & (Vs[:, 0] > -50)]
    loc = loc[:: max(1, len(loc) // 150)] @ R.T + SHIFT
    d = smooth_distance(tmp_path, rep, loc)
    assert np.percentile(d, 95) < 0.08                       # the 4 mm ripple (0.25 mm) is not followed
    assert rep['deviation']['all']['p50'] > 0.08              # ... so the deviation to the rippled scan is the ripple itself


def test_spans_capped(tmp_path):
    make(tmp_path / 'c')
    rep = sf.shell_fit(tmp_path, 'c/in.stl', 'mm', labels_path='c/labels.json', symmetry_report_path='c/sym.json', cut_planes=CUT, spans_u=40, spans_v=40,
                       min_wavelength_mm=12.0)
    assert rep['fit']['spans'][0] < 40 and rep['fit']['spans'][1] < 40
    assert rep['fit']['min_representable_wavelength_mm'] >= 12.0
    assert any('spans reduced' in w for w in rep['warnings'])


def test_validation(tmp_path):
    make(tmp_path / 'c')
    ws = tmp_path
    rejects('SCAN_UNIT', lambda: sf.shell_fit(ws, 'c/in.stl', 'px'))
    rejects('SHELL_FIT_SETTINGS', lambda: sf.shell_fit(ws, 'c/in.stl', 'mm', mode='mirror'))
    rejects('SHELL_FIT_SETTINGS', lambda: sf.shell_fit(ws, 'c/in.stl', 'mm', degree=3.0))
    rejects('SHELL_FIT_SETTINGS', lambda: sf.shell_fit(ws, 'c/in.stl', 'mm', cut_planes=[{'normal': [0, 0, 0], 'd': 1}]))
    rejects('SHELL_FIT_SETTINGS', lambda: sf.shell_fit(ws, 'c/in.stl', 'mm', regions=['top_shell']))
    rejects('SHELL_FIT_SETTINGS', lambda: sf.shell_fit(ws, 'c/in.stl', 'mm', symmetry_report_path='c/sym.json', mirror_plane={'normal': [0, 1, 0], 'd': 0}))
    rejects('SHELL_FIT_NOT_SYMMETRIC', lambda: sf.shell_fit(ws, 'c/in.stl', 'mm', mode='half'))
    rejects('SHELL_FIT_REGIONS_MISSING', lambda: sf.shell_fit(ws, 'c/in.stl', 'mm', labels_path='c/labels.json', regions=['dome'], cut_planes=CUT))


def test_tool_listed(tmp_path):
    tools = {t['name']: t for t in Tools(Brain(tmp_path)).list()}
    t = tools['brain_mouse_shell_fit']
    assert t['annotations']['readOnlyHint'] is False
    assert 'never forced' in t['description']
