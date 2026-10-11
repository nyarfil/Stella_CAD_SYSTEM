"""brain_mouse_scan_side_buttons: synthetic curved-flank shell (cylinder x box B-rep) + a synthetic 'scan' patch of the flank with raised pads.
No scan data. Geometry tests run the worker in this process (needs OCP: extra `geometry`); the end-to-end test goes through the tool and the
server python subprocess, then brain_mouse_face_roles on the result.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import scan_side_buttons as ssb

pytest.importorskip('OCP')
from cadmcp_brain.studio import cad_brep_lib as L  # noqa: E402
from cadmcp_brain.studio import scan_side_buttons_worker as W  # noqa: E402

RC, ZA = 28.0, 5.0            # flank cylinder radius / axis height
# pads: (x0, x1, z0, z1, corner radius, proud) in the flank (x, z) plan
PADS = {'side_button_1': (-18.0, -4.0, 15.0, 20.0, 1.0, 0.9), 'side_button_2': (0.0, 12.0, 12.5, 17.5, 1.0, 0.8)}


def make_shell():
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    cyl = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(-40, 0, ZA), gp_Dir(1, 0, 0)), RC, 80).Shape()
    box = BRepPrimAPI_MakeBox(gp_Pnt(-40, -30, 0), gp_Pnt(40, 30, 40)).Shape()
    s = L.solids(BRepAlgoAPI_Common(cyl, box).Shape())
    assert len(s) == 1
    return s[0]


def _sdf(x, z, pad):
    x0, x1, z0, z1, r, _ = pad
    cx, cz, hx, hz = (x0 + x1) / 2, (z0 + z1) / 2, (x1 - x0) / 2 - r, (z1 - z0) / 2 - r
    qx, qz = np.abs(x - cx) - hx, np.abs(z - cz) - hz
    return np.hypot(np.maximum(qx, 0), np.maximum(qz, 0)) + np.minimum(np.maximum(qx, qz), 0) - r


def make_scan(side=1.0, pads=PADS, noise=0.02, seed=1):
    """Open flank patch on the cylinder (side +1: +y flank, -1: -y flank) with raised pads; labels = pad + 0.8 mm slope ring."""
    xs = np.arange(-38, 38.001, 0.25)
    ph = np.arange(np.radians(20), np.radians(90), 0.25 / RC)
    X, PH = np.meshgrid(xs, ph, indexing='ij')
    Z = ZA + RC * np.cos(PH)
    rad = np.full(X.shape, RC)
    lab = np.zeros(X.shape, int)
    for k, (name, pad) in enumerate(sorted(pads.items())):
        sd = _sdf(X, Z, pad)
        ramp = np.clip(-sd / 0.3, 0, 1)
        rad += pad[5] * ramp * ramp * (3 - 2 * ramp)
    rad += np.random.default_rng(seed).normal(0, noise, rad.shape)
    V = np.c_[X.ravel(), side * (rad * np.sin(PH)).ravel(), (ZA + rad * np.cos(PH)).ravel()]
    n0, n1 = X.shape
    idx = np.arange(n0 * n1).reshape(n0, n1)
    q = np.stack([idx[:-1, :-1], idx[1:, :-1], idx[1:, 1:], idx[:-1, 1:]], -1).reshape(-1, 4)
    F = np.vstack([q[:, [0, 1, 2]], q[:, [0, 2, 3]]])
    if side < 0:
        F = F[:, ::-1]
    C = V[F].mean(1)
    labels = {}
    for name, pad in sorted(pads.items()):
        labels[name] = np.flatnonzero(_sdf(C[:, 0], C[:, 2], pad) < 0.8).tolist()
    return V, F, labels


def write_stl(path: Path, V, T):
    tri = V[T].astype('<f4')
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]).astype('<f4')
    rec = np.zeros(len(T), dtype=np.dtype([('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')]))
    rec['n'], rec['v'] = n, tri
    path.write_bytes(b'\0' * 80 + np.uint32(len(T)).tobytes() + rec.tobytes())


def write_case(d: Path, side=1.0, pads=PADS, labels=True):
    d.mkdir(parents=True, exist_ok=True)
    if not (d / 'shell.step').is_file():
        L.write_step(make_shell(), d / 'shell.step')
    V, F, lab = make_scan(side, pads)
    write_stl(d / 'scan.stl', V, F)
    if labels:
        (d / 'labels.json').write_text(json.dumps(lab), encoding='utf-8')
    return d


def request(d: Path, out: Path, labels=True, **params):
    inp = {'shell': str(d / 'shell.step'), 'mesh': str(d / 'scan.stl'), 'labels': str(d / 'labels.json') if labels else None}
    return {'inputs': inp, 'params': {**W.DEFAULTS, **params}, 'out_dir': str(out)}


@pytest.fixture(scope='module')
def case(tmp_path_factory):
    d = write_case(tmp_path_factory.mktemp('sb') / 'in')
    res = W.run(request(d, d.parent / 'out0'))
    return {'dir': d, 'res': res}


def by_name(res, name):
    return next(b for b in res['buttons'] if b['name'] == name)


def test_two_pads_on_one_flank(case):
    res = case['res']
    assert not res['blockers'] and res['per_flank'] == {'+y': 2} and res['handedness_from_buttons'] == 'right'
    r = res['result']
    assert r['valid'] and r['solids_in_step'] == 1 and r['modified'] and r['tessellates'] and r['faces_below_0p05mm2'] == 0
    assert r['faces'] in (r['faces_before'] + 7, r['faces_before'] + 8)    # per pad: top, pad wall, groove floor, groove outer wall (seam faces may unify)
    for name, pad in PADS.items():
        b = by_name(res, name)
        assert b['confidence'] == 'high' and b['top_mode'] == 'scan_fit' and b['flank'] == '+y'
        o = b['outline']
        assert abs(o['length_u_mm'] - (pad[1] - pad[0])) < 0.5          # slope-ring crest outline ~ the pad
        assert all(0.5 <= rr <= 1.0 + 1e-6 for rr, t in zip(o['corner_radii_mm'], o['turns_deg']) if t >= 30)
        m = b['measured']
        assert abs(m['groove_width_mm']['p50'] - 0.4) < 0.02 and abs(m['groove_depth_mm']['p50'] - 1.5) < 0.05
        assert abs(m['proud_mm']['p50'] - pad[5]) < 0.15
        assert b['bspline_outline_dev_mm'] < 0.01
        cz = o['centre_3d'][2]
        assert pad[2] < cz < pad[3] and pad[0] < o['centre_3d'][0] < pad[1]


def test_left_hand_mirror_one_pad_is_not_mirrored(tmp_path):
    pads = {'side_button_1': PADS['side_button_1']}
    d = write_case(tmp_path / 'in', side=-1.0, pads=pads)
    res = W.run(request(d, tmp_path / 'o'))
    assert not res['blockers'] and res['per_flank'] == {'-y': 1} and res['handedness_from_buttons'] == 'left'
    b = res['buttons'][0]
    assert b['outline']['centre_3d'][1] < -20 and b['confidence'] == 'high' and res['result']['valid']


def test_no_labels_detects_pads_from_geometry_and_marks_review(tmp_path):
    d = write_case(tmp_path / 'in', labels=False)
    res = W.run(request(d, tmp_path / 'o', labels=False))
    assert not res['blockers'] and res['per_flank'] == {'+y': 2}
    assert all(b['confidence'] != 'high' and b['top_mode'] == 'default_proud' for b in res['buttons'])
    assert any(w['code'] == 'SIDE_BUTTONS_FROM_GEOMETRY' for w in res['warnings']) and res['result']['valid']
    assert all(abs(b['measured']['proud_mm']['p50'] - 1.0) < 0.05 for b in res['buttons'])


def test_three_pads_on_one_flank_is_not_ready(tmp_path):
    pads = {**PADS, 'side_button_3': (16.0, 24.0, 14.0, 18.0, 1.0, 0.8)}
    d = write_case(tmp_path / 'in', pads=pads)
    res = W.run(request(d, tmp_path / 'o'))
    assert [b['code'] for b in res['blockers']] == ['SIDE_BUTTONS_TOO_MANY'] and not res['result']['modified']


def test_overlapping_pads_are_not_ready(tmp_path):
    pads = {'side_button_1': (-18.0, -4.0, 15.0, 20.0, 1.0, 0.9), 'side_button_2': (-3.3, 8.0, 15.0, 20.0, 1.0, 0.9)}
    d = write_case(tmp_path / 'in', pads=pads)
    res = W.run(request(d, tmp_path / 'o'))
    assert 'SIDE_BUTTONS_OVERLAP' in [b['code'] for b in res['blockers']]


def test_mesh_in_another_frame_is_refused(tmp_path):
    d = write_case(tmp_path / 'in')
    V, F, _ = make_scan()
    write_stl(d / 'scan.stl', V + [0, 0, 20.0], F)
    with pytest.raises(W.WorkerError) as exc:
        W.run(request(d, tmp_path / 'o'))
    assert exc.value.code == 'SIDE_BUTTONS_FRAME'


def test_outline_regularisation_straightens_noise():
    rng = np.random.default_rng(3)
    t = rng.uniform(0, 1, 4000)
    Q = np.c_[rng.uniform(-6, 6, 4000), rng.uniform(-2.5, 2.5, 4000)] + rng.normal(0, 0.05, (4000, 2))
    poly, hull = W.regular_outline(Q, 0.35, 8.0)
    assert len(poly) == 4 and len(hull) > 4 and t.size
    plan = W.fillet_plan(poly, 1.0)
    assert all(abs(c['r'] - 1.0) < 1e-9 for c in plan)
    O = W.rounded(plan)
    assert abs(W._poly_area(O) - 12 * 5 + (4 - np.pi)) < 2.5


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code


def test_tool_validates_before_running(tmp_path):
    (tmp_path / 's.step').write_text('x')
    (tmp_path / 'm.stl').write_text('x')
    (tmp_path / 'r.json').write_text('{"regions": {}}')
    rejects('SIDE_BUTTONS_SETTINGS', lambda: ssb.side_buttons(tmp_path, 's.step', 'm.stl', groove_width_mm=5.0))
    rejects('SIDE_BUTTONS_SETTINGS', lambda: ssb.side_buttons(tmp_path, 's.step', 'm.stl', groove_depth_mm=True))
    rejects('SIDE_BUTTONS_SETTINGS', lambda: ssb.side_buttons(tmp_path, 's.step', 'm.stl', reference_images=['nope.png']))
    rejects('SIDE_BUTTONS_FILE', lambda: ssb.side_buttons(tmp_path, 'm.stl', 'm.stl'))
    rejects('SIDE_BUTTONS_LABELS', lambda: ssb.side_buttons(tmp_path, 's.step', 'm.stl', labels_path='m.stl'))
    rejects('UNSAFE_PATH', lambda: ssb.side_buttons(tmp_path, '../s.step', 'm.stl'))
    t = Tools(Brain(tmp_path))
    names = {x['name']: x for x in t.list()}
    props = names['brain_mouse_scan_side_buttons']['inputSchema']['properties']
    assert props['groove_width_mm']['default'] == 0.4 and props['groove_depth_mm']['default'] == 1.5 and 'reference_images' in props


def test_tool_end_to_end_review_cache_and_face_roles(tmp_path):
    d = write_case(tmp_path / 'in')
    regions = {'regions': {'side_button_1': {'confidence': 'high'}, 'side_button_2': {'confidence': 'medium'}}, 'handedness': {'detected': 'right'}}
    (d / 'regions.json').write_text(json.dumps(regions), encoding='utf-8')
    t = Tools(Brain(tmp_path))
    args = {'shell_step_path': 'in/shell.step', 'mesh_path': 'in/scan.stl', 'labels_path': 'in/labels.json', 'regions_report_path': 'in/regions.json'}
    r = t.call('brain_mouse_scan_side_buttons', args)
    assert r['status'] == 'REVIEW' and r['side_buttons_id'].startswith('sb_') and not r['blocking_reasons']
    assert {b['name']: b['confidence'] for b in r['buttons']} == {'side_button_1': 'high', 'side_button_2': 'medium'}
    assert r['checks']['brep_valid'] == 'PASS' and r['checks']['no_slivers'] == 'PASS' and r['checks']['reimport'] == 'PASS'
    step = r['outputs']['shell']['relative_path']
    assert (tmp_path / step).is_file() and len(r['outputs']['shell']['sha256']) == 64
    again = t.call('brain_mouse_scan_side_buttons', args)
    assert again['cached'] is True
    fr = t.call('brain_mouse_face_roles', {'shell_step_path': step})
    c = fr['counts']['top_shell']
    assert c.get('sidebutton') == 2 and c.get('sidebutton_wall') == 2 and fr['checks']['sidebutton_walls'] == 'PASS'
    assert fr['colour_counts']['read_back']['0.15,0.65,0.25'] == 2
