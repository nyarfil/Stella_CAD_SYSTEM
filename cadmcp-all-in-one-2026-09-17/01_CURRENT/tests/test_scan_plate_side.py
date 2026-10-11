"""brain_mouse_plate_side: synthetic mouse-like shell (half ellipsoid over a gently curved, tilted parting surface) and synthetic base outlines.
No scan data is used or stored. Needs OCP (extra `geometry`), scipy and shapely in the test python; skipped otherwise.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import scan_plate_side as ps

pytest.importorskip('OCP')
pytest.importorskip('scipy')
pytest.importorskip('shapely')
from cadmcp_brain.studio import cad_brep_lib as L  # noqa: E402
from cadmcp_brain.studio import scan_plate_side_worker as W  # noqa: E402

MIRROR = {'normal': [0.0, 1.0, 0.0], 'd': 0.0, 'source': 'arguments'}


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code
    return exc.value


def make_shell(path: Path):
    """Ellipsoid 120 x 64 x 80 (centre z -5) above the parting surface z = 3 + 0.02 x + y^2 / 800 (walls flare outward going down)."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeSphere, BRepPrimAPI_MakeHalfSpace
    from OCP.gp import gp_GTrsf, gp_Mat, gp_XYZ, gp_Pnt
    from OCP.BRepBuilderAPI import BRepBuilderAPI_GTransform, BRepBuilderAPI_MakeFace
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    g = gp_GTrsf()
    g.SetVectorialPart(gp_Mat(60, 0, 0, 0, 32, 0, 0, 0, 40))
    g.SetTranslationPart(gp_XYZ(-10, 0, -5))
    ell = BRepBuilderAPI_GTransform(BRepPrimAPI_MakeSphere(gp_Pnt(0, 0, 0), 1.0).Shape(), g, True).Shape()
    xs, ys = np.linspace(-90, 70, 6), np.linspace(-50, 50, 6)
    P = np.array([[[x, y, 3 + 0.02 * x + y * y / 800] for y in ys] for x in xs])
    ck = np.r_[[0] * 3, np.linspace(0, 1, 4), [1] * 3]
    f = BRepBuilderAPI_MakeFace(L.bsurf(P, ck, ck), 1e-7).Face()
    sol = L.solids(BRepAlgoAPI_Common(ell, BRepPrimAPI_MakeHalfSpace(f, gp_Pnt(-10, 0, 30)).Solid()).Shape())[0]
    L.write_step(sol, path)


def outline(kind='sym', n=400):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ax, ay, ex = 54.0, 28.0, 2.2
    x = -10 + ax * np.sign(np.cos(t)) * np.abs(np.cos(t)) ** (2 / ex)
    y = ay * np.sign(np.sin(t)) * np.abs(np.sin(t)) ** (2 / ex)
    if kind == 'bump':                                   # 1 mm one-sided bulge on the right flank (y < 0)
        y = y - 1.0 * np.exp(-((x + 10) / 6) ** 2) * (y < 0)
    if kind == 'shift':                                  # left half moved 8 mm inward along the flank
        y = np.where(y > 0, y - 8.0 * np.exp(-((x + 10) / 25) ** 4), y)
    return np.c_[x, y]


def write_outline(path: Path, kind='sym'):
    path.write_text(json.dumps({'points': outline(kind).tolist()}), encoding='utf-8')


@pytest.fixture(scope='module')
def shell_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp('plate')
    make_shell(d / 'shell.step')
    return d


def run_worker(folder: Path, shell: Path, kind: str, n=600):
    write_outline(folder / 'outline.json', kind)
    req = {'inputs': {'shell': str(shell), 'outline': str(folder / 'outline.json'), 'symmetry': None}, 'out_dir': str(folder / 'out'),
           'params': {**ps.DEFAULTS, 'n_stations': n, 'outline_mode': 'polyline', 'mirror': MIRROR}}
    return W.run(req)


def r_of_phi(P, phi):
    """Radius of the closed loop P about (-10, 0) at the angles phi (mirror plane y = 0, phi = 0 is +x)."""
    a = np.arctan2(P[:, 1], P[:, 0] + 10)
    r = np.hypot(P[:, 0] + 10, P[:, 1])
    o = np.argsort(a)
    return np.interp(phi, a[o], r[o], period=2 * np.pi)


def test_tool_symmetric_outline_ready_and_cached(shell_dir, tmp_path):
    (tmp_path / 'in').mkdir()
    (tmp_path / 'in' / 'shell.step').write_bytes((shell_dir / 'shell.step').read_bytes())
    write_outline(tmp_path / 'in' / 'outline.json')
    sha = hashlib.sha256((tmp_path / 'in' / 'shell.step').read_bytes()).hexdigest()
    t = Tools(Brain(tmp_path))
    args = {'shell_step_path': 'in/shell.step', 'outline_mode': 'polyline', 'outline_path': 'in/outline.json', 'mirror_normal': [0, 1, 0], 'mirror_d': 0, 'front_rim_mm': 0}
    r = t.call('brain_mouse_plate_side', args)
    assert r['status'] == 'READY', r['blocking_reasons']
    assert all(v == 'PASS' for v in r['checks'].values())
    m = r['measurements']
    assert m['plate']['solids'] == 1 and m['plate']['faces'] == 3 and m['plate']['volume_mm3'] > 1000
    assert m['overlap_volume_mm3'] <= 1e-3 and m['min_distance_mm'] <= 1e-3
    assert m['plan_protrusion_mm']['max'] <= 1e-3 and m['top_edge_vs_shell_edge_mm']['max'] <= 0.01
    assert m['side_profile']['rays_non_monotonic_r_of_z'] == 0 and m['side_profile']['rays'] > 100
    assert r['side']['side_degree'] == [3, 1] and r['side']['side_u_periodic'] and r['side']['stations'] == 1500 and r['side']['monotonic']
    assert r['base_outline']['symmetry']['applied'] and not r['base_outline']['symmetry']['asymmetric_sectors']
    assert r['base_outline']['fairing']['change_mm']['max'] <= 0.1 + 1e-6
    assert m['floor_vs_source_outline_mm']['radial_max_abs'] <= 0.1 + 0.02
    assert 'shell_plate_edge_angle_deg' in m and 'side_to_floor_angle_deg' in m
    assert hashlib.sha256((tmp_path / 'in' / 'shell.step').read_bytes()).hexdigest() == sha == r['source']['shell_sha256']
    folder = tmp_path / 'mouse' / 'cad' / r['job_id']
    assert r['job_id'].startswith('pl_') and (folder / ps.REPORT).is_file()
    for name in ('bottom_plate', 'assembly', 'base_outline'):
        assert (tmp_path / r['outputs'][name]['relative_path']).is_file() and len(r['outputs'][name]['sha256']) == 64
    assert len(L.solids(L.read_step(folder / 'assembly.step'))) == 2
    B = np.array(json.loads((folder / 'base_outline.json').read_text())['points'])
    phi = np.radians(np.arange(-179, 180, 1.0))
    assert np.abs(r_of_phi(B, phi) - r_of_phi(B, -phi)).max() < 0.02
    again = t.call('brain_mouse_plate_side', args)
    assert again['cached'] is True and again['job_id'] == r['job_id']
    (folder / 'bottom_plate.step').write_bytes(b'changed')
    rejects('PLATE_SIDE_OUTPUT_CHANGED', lambda: t.call('brain_mouse_plate_side', args))


def test_one_sided_bump_is_symmetrised(shell_dir, tmp_path):
    res = run_worker(tmp_path, shell_dir / 'shell.step', 'bump')
    sym = res['base_outline']['symmetry']
    flank = [s for s in sym['sectors'] if -120 <= s['phi_deg'][0] < -60]           # the bump sits at phi ~ -90 deg
    assert flank and all(s['near_symmetric'] and s['decision'].startswith('symmetrised') for s in flank)
    assert max(s['pair_p80_mm'] for s in flank) > 0.5                               # the bump was seen
    B = np.array(json.loads((tmp_path / 'out' / 'base_outline.json').read_text())['points'])
    Q = outline('bump')
    phi = np.radians(np.arange(60, 121, 1.0))
    assert np.abs(r_of_phi(Q, phi) - r_of_phi(Q, -phi)).max() > 0.9                 # source asymmetric there
    assert np.abs(r_of_phi(B, phi) - r_of_phi(B, -phi)).max() < 0.1                  # result mirror-symmetric
    assert res['checks']['plate']['solids'] == 1 and res['checks']['side_profile']['rays_non_monotonic_r_of_z'] == 0


def test_shifted_half_is_kept_asymmetric(shell_dir, tmp_path):
    res = run_worker(tmp_path, shell_dir / 'shell.step', 'shift')
    sym = res['base_outline']['symmetry']
    flank = [s for s in sym['sectors'] if 60 <= s['phi_deg'][0] < 120 or -120 <= s['phi_deg'][0] < -60]
    assert flank and all(not s['near_symmetric'] and s['decision'] == 'asymmetric_kept' for s in flank)
    assert any(s['near_symmetric'] for s in sym['sectors'])                         # nose / tail stay testable
    B = np.array(json.loads((tmp_path / 'out' / 'base_outline.json').read_text())['points'])
    Q = outline('shift')
    phi = np.radians(np.arange(75, 106, 1.0))
    assert np.abs(r_of_phi(B, phi) - r_of_phi(Q, phi)).max() < 0.15                 # kept as given (fairing only)
    assert np.abs(r_of_phi(B, phi) - r_of_phi(B, -phi)).min() > 6.0                  # not forced symmetric
    assert res['checks']['plan_protrusion_mm']['max'] <= 1e-3


def test_front_rim_default(shell_dir, tmp_path):
    """Default front = shell parting outline minus a uniform 1.2 mm rim, symmetric; corner radius at least the requested one."""
    res = run_worker(tmp_path, shell_dir / 'shell.step', 'bump')
    fr = res['base_outline']['front']
    assert fr['rim_mm'] == 1.2 and fr['symmetry']['symmetric']
    assert abs(fr['rim_measured_mm']['p50'] - 1.2) < 0.12 and fr['rim_measured_mm']['max'] < 1.4
    B = np.array(json.loads((tmp_path / 'out' / 'base_outline.json').read_text())['points'])
    phi = np.radians(np.arange(-40, 41, 1.0))
    assert np.abs(r_of_phi(B, phi) - r_of_phi(B, -phi)).max() < 0.02
    assert res['checks']['plan_protrusion_mm']['max'] <= 1e-3 and res['checks']['plate']['solids'] == 1
    t2 = tmp_path / 'r'
    t2.mkdir()
    write_outline(t2 / 'outline.json', 'sym')
    req = {'inputs': {'shell': str(shell_dir / 'shell.step'), 'outline': str(t2 / 'outline.json'), 'symmetry': None}, 'out_dir': str(t2 / 'out'),
           'params': {**ps.DEFAULTS, 'n_stations': 600, 'outline_mode': 'polyline', 'mirror': MIRROR, 'front_min_corner_radius_mm': 25.0}}
    big = W.run(req)['base_outline']['front']
    assert big['min_corner_radius_mm'] >= 25.0 * 0.9


def test_no_mirror_means_no_symmetrisation():
    sq = np.c_[[0, 40, 40, 0], [0, 0, 20, 20]] - [20, 10]
    edge = np.c_[np.cos(np.linspace(0, 2 * np.pi, 400, endpoint=False)) * 40, np.sin(np.linspace(0, 2 * np.pi, 400, endpoint=False)) * 30]
    Q = W.resample(sq.astype(float), 200)
    res = W.process_outline(Q, edge, None, {**ps.DEFAULTS})
    assert res['report']['symmetry']['applied'] is False and 'No mirror plane' in res['report']['symmetry']['reason']
    assert res['report']['fairing']['change_mm']['max'] <= 0.1 + 1e-6


def test_outline_readers(tmp_path):
    trimesh = pytest.importorskip('trimesh')
    b = trimesh.creation.box(extents=(40, 20, 6))
    b.apply_translation((0, 0, 3))
    b.export(tmp_path / 'm.stl')
    P, info = W.mesh_section(tmp_path / 'm.stl', 0.3)
    assert info['loops'] == 1 and info['loop_area_mm2'] == pytest.approx(800, rel=1e-6)
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    L.write_step(BRepPrimAPI_MakeBox(gp_Pnt(-20, -10, 0), 40, 20, 3).Shape(), tmp_path / 'p.step')
    P, info = W.step_floor(tmp_path / 'p.step')
    assert info['z_mm'] == pytest.approx(0.0, abs=1e-9) and P[:, 0].min() == pytest.approx(-20) and P[:, 1].max() == pytest.approx(10)
    (tmp_path / 'q.json').write_text('{"points": [[0, 0], [1, 0]]}')
    with pytest.raises(W.WorkerError):
        W.polyline(tmp_path / 'q.json')
    nonstar = np.array([[0, 0], [10, 0], [10, 10], [1, 10], [1, 1], [9, 1], [9, 9], [0, 9]], float)   # spiral-like, not star-shaped
    with pytest.raises(W.WorkerError):
        W.radial_grid(nonstar, W.make_frame(np.array([[0, 0], [10, 0], [10, 10], [0, 10.]]), None))


def test_tool_validates_before_running(tmp_path):
    (tmp_path / 's.step').write_text('x')
    (tmp_path / 'o.json').write_text('{}')
    (tmp_path / 'o.stl').write_text('x')
    (tmp_path / 'sym.json').write_text(json.dumps({'plane': {'normal': [0, 1, 0], 'd': 0}}))
    (tmp_path / 'bad.json').write_text(json.dumps({'normal': [0, 1, 0]}))
    f = lambda **k: ps.plate_side(tmp_path, **{'shell_step_path': 's.step', 'outline_mode': 'polyline', 'outline_path': 'o.json', **k})  # noqa: E731
    rejects('PLATE_SIDE_MODE', lambda: f(outline_mode='scan'))
    rejects('PLATE_SIDE_SETTINGS', lambda: f(n_stations=10))
    rejects('PLATE_SIDE_SETTINGS', lambda: f(n_sectors=23))
    rejects('PLATE_SIDE_SETTINGS', lambda: f(n_stations=1500.5))
    rejects('PLATE_SIDE_SETTINGS', lambda: f(max_change_mm=-0.1))
    rejects('PLATE_SIDE_SETTINGS', lambda: f(section_z_mm=True))
    rejects('PLATE_SIDE_FILE', lambda: f(outline_mode='mesh'))                   # .json given for a mesh
    rejects('PLATE_SIDE_FILE', lambda: f(shell_step_path='o.stl'))
    rejects('UNSAFE_PATH', lambda: f(outline_path='nope.json'))
    rejects('UNSAFE_PATH', lambda: f(shell_step_path='../s.step'))
    rejects('PLATE_SIDE_SYMMETRY', lambda: f(symmetry_report_path='sym.json', mirror_normal=[0, 1, 0], mirror_d=0))
    rejects('PLATE_SIDE_SYMMETRY', lambda: f(symmetry_report_path='bad.json'))
    rejects('PLATE_SIDE_SYMMETRY', lambda: f(mirror_normal=[0, 1, 0]))
    rejects('PLATE_SIDE_SYMMETRY', lambda: f(mirror_normal=[0, 0, 1], mirror_d=0))
    rejects('PLATE_SIDE_SYMMETRY', lambda: f(mirror_normal=[0, 1], mirror_d=0))


def test_tool_registered(tmp_path):
    t = Tools(Brain(tmp_path))
    names = {x['name']: x for x in t.list()}
    assert 'brain_mouse_plate_side' in names and names['brain_mouse_plate_side']['annotations']['readOnlyHint'] is False
    props = names['brain_mouse_plate_side']['inputSchema']['properties']
    assert props['n_stations']['default'] == 1500 and props['section_z_mm'].get('default') is None and props['max_change_mm']['default'] == 0.1
    assert {'symmetry_report_path', 'mirror_normal', 'mirror_d', 'min_inset_mm'} <= set(props)
    rejects('PLATE_SIDE_MODE', lambda: t.call('brain_mouse_plate_side', {'shell_step_path': 'a.step', 'outline_mode': 'x', 'outline_path': 'b.json'}))


def test_auto_section_extrapolates_a_chamfered_foot_to_the_floor(tmp_path):
    """whole_v1 rule: the base outline is the outline AT z = 0. A 45 deg, 1 mm chamfer at the foot: the auto section (above the chamfer
    transition) is moved inward towards the z = 0 outline, never outward."""
    trimesh = pytest.importorskip('trimesh')
    from shapely.geometry import Polygon

    th = np.linspace(0, 2 * np.pi, 240, endpoint=False)
    rings = [(0.0, 1.0), (0.25, 0.75), (0.5, 0.5), (0.75, 0.25), (1.0, 0.0), (10.0, 0.0)]        # (z, inset): chamfer below z = 1
    V = [np.c_[(50 - k) * np.cos(th), (25 - k) * np.sin(th), np.full(len(th), z)] for z, k in rings]
    V = np.vstack(V + [[[0, 0, 0]], [[0, 0, 10.0]]])
    n, R = len(th), len(rings)
    F = []
    for r in range(R - 1):
        for i in range(n):
            a, b, c, d = r * n + i, r * n + (i + 1) % n, (r + 1) * n + (i + 1) % n, (r + 1) * n + i
            F += [(a, b, c), (a, c, d)]
    bc, tc = R * n, R * n + 1
    F += [(bc, (i + 1) % n, i) for i in range(n)] + [(tc, (R - 1) * n + i, (R - 1) * n + (i + 1) % n) for i in range(n)]
    m = trimesh.Trimesh(V, np.asarray(F), process=True)
    assert m.is_watertight
    m.export(tmp_path / 'foot.stl')
    p = {**ps.DEFAULTS, 'outline_mode': 'mesh', 'section_z_mm': None}
    Q, info = W.auto_section(tmp_path / 'foot.stl', (np.array([0.0, 1.0]), 0.0), p)
    z = info['z_mm']
    ext = info['floor_extrapolation']
    assert ext['applied'] and ext['inward_shift_mm']['median'] > 0.25
    a0 = Polygon(np.c_[49 * np.cos(th), 24 * np.sin(th)]).area
    a_sec = Polygon(np.c_[(50 - max(0.0, 1 - z)) * np.cos(th), (25 - max(0.0, 1 - z)) * np.sin(th)]).area
    assert a0 - 50 < Polygon(Q).area < a_sec - 20                                              # moved towards the z = 0 outline


def test_ray_far_takes_the_outer_wall_of_a_non_star_loop():
    """PS1.5 floor extrapolation reads r(phi) of the low (non star-shaped) sections as the FARTHEST ray hit."""
    import numpy as np
    from cadmcp_brain.studio import scan_plate_side_worker as w
    t = np.linspace(0, 2 * np.pi, 400, endpoint=False)
    Q = np.c_[10 * np.cos(t), 10 * np.sin(t)]
    D = np.c_[np.cos([0.5, 2.0]), np.sin([0.5, 2.0])]
    assert np.allclose(w.ray_far(np.zeros(2), D, Q), 10.0, atol=0.05)
    # a C-shaped loop: the ray through the mouth hits the inner and the outer wall; the outer one is returned
    a = np.linspace(0.3, 2 * np.pi - 0.3, 300)
    C = np.r_[np.c_[10 * np.cos(a), 10 * np.sin(a)], np.c_[6 * np.cos(a[::-1]), 6 * np.sin(a[::-1])]]
    assert w.ray_far(np.array([0.0, 0.0]), np.array([[-1.0, 0.0]]), C)[0] == pytest.approx(10.0, abs=0.05)
