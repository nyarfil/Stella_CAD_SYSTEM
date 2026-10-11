"""brain_mouse_face_roles: synthetic dome shell with a perimeter slot, a centre gap, a window pocket and a side pad, plus a plate. No scan data.

The geometry tests run the worker in this process (needs OCP: extra `geometry`; skipped when missing); the end-to-end test goes through the tool
and the server python subprocess.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import scan_face_roles as sfr

pytest.importorskip('OCP')
from cadmcp_brain.studio import cad_brep_lib as L  # noqa: E402
from cadmcp_brain.studio import scan_face_roles_worker as W  # noqa: E402

R, ZC = 60.0, -35.0          # dome sphere radius / centre z


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code
    return exc.value


def _box(x0, y0, z0, x1, y1, z1):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    return BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()


def _sphere(r):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeSphere
    from OCP.gp import gp_Pnt
    return BRepPrimAPI_MakeSphere(gp_Pnt(0, 0, ZC), r).Shape()


def _cyl(x, y, r, z0, h):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Pnt, gp_Dir
    return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(x, y, z0), gp_Dir(0, 0, 1)), r, h).Shape()


def _op(kind, a, b):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    m = {'common': BRepAlgoAPI_Common, 'cut': BRepAlgoAPI_Cut, 'fuse': BRepAlgoAPI_Fuse}[kind](a, b)
    assert m.IsDone()
    return m.Shape()


def _unify(s):
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    u = ShapeUpgrade_UnifySameDomain(s, True, True, False)
    u.Build()
    return u.Shape()


def make_shell():
    body = _op('common', _sphere(R), _box(-40, -25, 0, 40, 25, 30))
    deep = _sphere(R - 2.0)                                                      # slot floors 2 mm below the dome
    slots = _box(4.5, -18.5, 0, 5.0, 18.5, 40)                                   # 0.5 mm perimeter slot (U, open at the nose)
    for y0 in (-18.5, 18.0):
        slots = _op('fuse', slots, _box(4.5, y0, 0, 41, y0 + 0.5, 40))
    slots = _op('fuse', slots, _box(5.0, -0.5, 0, 41, 0.5, 40))                  # 1 mm centre gap -> two panels
    body = _op('cut', body, _op('cut', slots, deep))
    win = _op('fuse', _box(17, -4, 16, 25, 4, 40), _box(15, -2, 16, 27, 2, 40))  # rounded-rect window pocket, flat floor z 16
    for x in (17, 25):
        for y in (-2, 2):
            win = _op('fuse', win, _cyl(x, y, 2.0, 16, 24))
    body = _op('cut', body, _unify(win))
    body = _op('fuse', body, _box(-20, 24, 8, -8, 26, 14))                       # raised side pad on the left flank
    sol = L.solids(_unify(body))
    assert len(sol) == 1
    return sol[0]


def write_stl(path: Path, V, T):
    tri = V[T].astype('<f4')
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]).astype('<f4')
    rec = np.zeros(len(T), dtype=np.dtype([('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')]))
    rec['n'], rec['v'] = n, tri
    path.write_bytes(b'\0' * 80 + np.uint32(len(T)).tobytes() + rec.tobytes())


@pytest.fixture(scope='module')
def case(tmp_path_factory):
    d = tmp_path_factory.mktemp('fr')
    (d / 'in').mkdir()
    shell = make_shell()
    L.write_step(shell, d / 'in' / 'shell.step')
    L.write_step(L.solids(_box(-40, -25, -3, 40, 25, 0))[0], d / 'in' / 'plate.step')
    L.write_step(L.compound([shell, L.solids(_box(-40, -25, -9, 40, 25, -6))[0]]), d / 'in' / 'two.step')
    m = L.tessellate(shell, 0.05, 0.2)
    write_stl(d / 'in' / 'hint.stl', m['V'], m['T'])
    res = W.run(request(d, d / 'out0'))
    return {'dir': d, 'mesh': m, 'res': res, 'roles': json.loads((d / 'out0' / 'face_roles.json').read_text(encoding='utf-8'))}


def request(d: Path, out: Path, plate=True, hints=None, **params):
    inp = {'shell': str(d / 'in' / 'shell.step'), 'plate': str(d / 'in' / 'plate.step') if plate else None, 'hint_mesh': None, 'hint_labels': None}
    if hints is not None:
        (d / 'in' / 'labels.json').write_text(json.dumps(hints), encoding='utf-8')
        inp.update(hint_mesh=str(d / 'in' / 'hint.stl'), hint_labels=str(d / 'in' / 'labels.json'))
    return {'inputs': inp, 'params': {**W.DEFAULTS, **params}, 'out_dir': str(out)}


def by_role(roles, role, sub=None):
    return [r for r in roles['top_shell'] if r['role'] == role and (sub is None or r['sub'] == sub)]


def test_geometry_roles(case):
    res, roles = case['res'], case['roles']
    c = res['counts']['top_shell']
    assert c['panel'] == 2 and c['sidebutton'] == 1 and c['sidebutton_wall'] == 4 and c['parting'] == 1
    panels = by_role(roles, 'panel')
    assert sorted(np.sign(p['point'][1]) for p in panels) == [-1, 1] and all(p['point'][0] > 5 for p in panels)
    assert len(by_role(roles, 'slot', 'floor')) >= 2 and len(by_role(roles, 'slot', 'wall')) >= 4
    win_walls, win_floor = by_role(roles, 'window', 'wall'), by_role(roles, 'window', 'floor')
    assert len(win_floor) == 1 and abs(win_floor[0]['point'][2] - 16) < 1e-6 and len(win_walls) >= 8
    assert {r['type'] for r in win_walls} == {'Plane', 'Cylinder'}
    pad = by_role(roles, 'sidebutton')[0]
    assert abs(pad['point'][1] - 26) < 1e-6
    assert all(r['role'] == 'shell' for r in roles['top_shell'] if r['role'] not in ('panel', 'slot', 'window', 'sidebutton', 'sidebutton_wall', 'parting'))
    assert by_role(roles, 'parting')[0]['mean_nz'] < -0.99
    for p in res['panels'].values():
        assert p['samples_outside_groove_loop'] == 0 and p['samples'] > 50
        b = p['boundary_len_by_neighbour']
        assert b['slot'] > 40 and b['window'] > 5 and 17.5 < b['shell'] < 19.0        # crisp front lip to the nose wall (arc, y 0.5..18)
    assert res['window_loops'][0]['closed'] is True
    assert sorted(r['sub'] for r in roles['bottom_plate']) == ['floor', 'parting', 'side', 'side', 'side', 'side']
    assert all(v in ('PASS', 'UNVERIFIED') for v in res['checks'].values()) and res['checks']['hint_agreement'] == 'UNVERIFIED'
    cc = res['colour_counts']
    assert cc['expected'] == {k: v for k, v in cc['read_back'].items() if k != 'none'}
    assert cc['expected']['0.95,0.50,0.10'] == 2 and cc['expected']['0.15,0.65,0.25'] == 1 and cc['expected']['0.20,0.40,0.85'] == 6
    rec = roles['top_shell'][0]
    assert {'index', 'role', 'sub', 'type', 'area', 'point', 'bbox', 'neighbours'} <= set(rec) and 'Fusion' in roles['note']


def _tri_ids(case, faces):
    return np.flatnonzero(np.isin(case['mesh']['FID'], faces)).tolist()


def test_correct_hints_agree(case, tmp_path):
    roles = case['roles']['top_shell']
    pan = [r['index'] for r in roles if r['role'] == 'panel']
    pad = [r['index'] for r in roles if r['role'] == 'sidebutton']
    res = W.run(request(case['dir'], tmp_path / 'o', plate=False, hints={'left_click': _tri_ids(case, pan[:1]), 'right_click': _tri_ids(case, pan[1:]),
                                                                        'side_button_1': _tri_ids(case, pad), 'logo': [0]}))
    assert res['hints_used'] and res['checks']['hint_agreement'] == 'PASS'
    assert not [w for w in res['warnings'] if w['code'] == 'FACE_ROLE_HINT_DISAGREES']
    assert any(w['code'] == 'FACE_ROLES_HINT_NAMES_IGNORED' for w in res['warnings'])


def test_wrong_hint_is_only_a_warning(case, tmp_path):
    roles = case['roles']['top_shell']
    dome = max((r for r in roles if r['role'] == 'shell'), key=lambda r: r['area'])['index']
    res = W.run(request(case['dir'], tmp_path / 'o', plate=False, hints={'regions': {'left_click': {'face_ids': _tri_ids(case, [dome])}}}))
    dis = [w for w in res['warnings'] if w['code'] == 'FACE_ROLE_HINT_DISAGREES']
    assert [w['face'] for w in dis] == [dome] and dis[0]['geometry_role'] == 'shell' and dis[0]['hint_role'] == 'panel'
    assert res['counts']['top_shell'] == case['res']['counts']['top_shell'] and res['checks']['hint_agreement'] == 'FAIL'


def test_hint_in_another_frame_is_ignored(case, tmp_path):
    d = case['dir']
    m = case['mesh']
    write_stl(d / 'in' / 'hint.stl', m['V'] + [0, 0, 50.0], m['T'])
    try:
        res = W.run(request(d, tmp_path / 'o', plate=False, hints={'left_click': [0, 1]}))
    finally:
        write_stl(d / 'in' / 'hint.stl', m['V'], m['T'])
    assert not res['hints_used'] and any(w['code'] == 'FACE_ROLES_HINT_FRAME' for w in res['warnings'])


def test_shell_must_be_one_solid(case, tmp_path):
    req = request(case['dir'], tmp_path / 'o', plate=False)
    req['inputs']['shell'] = str(case['dir'] / 'in' / 'two.step')
    with pytest.raises(W.WorkerError) as exc:
        W.run(req)
    assert exc.value.code == 'FACE_ROLES_SHELL_SOLIDS'


def test_tool_validates_before_running(tmp_path):
    (tmp_path / 's.step').write_text('x')
    (tmp_path / 'h.stl').write_text('x')
    (tmp_path / 'h.json').write_text('{}')
    rejects('FACE_ROLES_SETTINGS', lambda: sfr.face_roles(tmp_path, 's.step', slot_max_mm=0.0))
    rejects('FACE_ROLES_SETTINGS', lambda: sfr.face_roles(tmp_path, 's.step', slot_max_mm=5.0, window_max_mm=4.0))
    rejects('FACE_ROLES_SETTINGS', lambda: sfr.face_roles(tmp_path, 's.step', crisp_edge_deg=True))
    rejects('FACE_ROLES_SETTINGS', lambda: sfr.face_roles(tmp_path, 's.step', colors={'panel': [1, 2, 3]}))
    rejects('FACE_ROLES_SETTINGS', lambda: sfr.face_roles(tmp_path, 's.step', colors={'logo': [0, 0, 0]}))
    rejects('FACE_ROLES_HINTS', lambda: sfr.face_roles(tmp_path, 's.step', hint_mesh_path='h.stl'))
    rejects('FACE_ROLES_HINTS', lambda: sfr.face_roles(tmp_path, 's.step', hint_mesh_path='h.json', hint_labels_path='h.json'))
    rejects('FACE_ROLES_FILE', lambda: sfr.face_roles(tmp_path, 'h.stl'))
    rejects('FACE_ROLES_FILE', lambda: sfr.face_roles(tmp_path, 's.step', plate_step_path='h.json'))
    rejects('UNSAFE_PATH', lambda: sfr.face_roles(tmp_path, 'nope.step'))
    rejects('UNSAFE_PATH', lambda: sfr.face_roles(tmp_path, '../s.step'))
    t = Tools(Brain(tmp_path))
    names = {x['name']: x for x in t.list()}
    assert 'brain_mouse_face_roles' in names and names['brain_mouse_face_roles']['annotations']['readOnlyHint'] is False
    props = names['brain_mouse_face_roles']['inputSchema']['properties']
    assert props['slot_max_mm']['default'] == 2.5 and props['window_max_mm']['default'] == 30.0 and 'plate_step_path' in props
    rejects('FACE_ROLES_SETTINGS', lambda: t.call('brain_mouse_face_roles', {'shell_step_path': 's.step', 'window_max_mm': 0.1}))


def test_tool_end_to_end_and_cache(case, tmp_path):
    (tmp_path / 'in').mkdir()
    for n in ('shell.step', 'plate.step'):
        (tmp_path / 'in' / n).write_bytes((case['dir'] / 'in' / n).read_bytes())
    t = Tools(Brain(tmp_path))
    args = {'shell_step_path': 'in/shell.step', 'plate_step_path': 'in/plate.step'}
    r = t.call('brain_mouse_face_roles', args)
    assert r['status'] == 'READY' and r['face_roles_id'].startswith('fr_') and r['counts'] == case['res']['counts']
    assert r['checks']['colour_readback'] == 'PASS' and 'Fusion' in r['note']
    folder = tmp_path / 'mouse' / 'cad' / r['face_roles_id']
    for item in r['outputs'].values():
        assert (tmp_path / item['relative_path']).is_file() and len(item['sha256']) == 64
    assert (folder / sfr.REPORT).is_file() and not list((tmp_path / 'mouse' / 'cad').glob('*.tmp-*'))
    again = t.call('brain_mouse_face_roles', args)
    assert again['cached'] is True and again['face_roles_id'] == r['face_roles_id']
    other = t.call('brain_mouse_face_roles', {**args, 'colors': {'panel': [1.0, 0.0, 0.0]}})
    assert other['face_roles_id'] != r['face_roles_id'] and other['colour_counts']['read_back']['1.00,0.00,0.00'] == 2
    (folder / 'face_roles.json').write_text('changed')
    rejects('FACE_ROLES_OUTPUT_CHANGED', lambda: t.call('brain_mouse_face_roles', args))
