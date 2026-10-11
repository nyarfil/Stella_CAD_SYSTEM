"""brain_mouse_handedness_flip: synthetic dome shell with a side pad on the +y flank over a box plate; roles are written by hand from the geometry.
No scan data. The worker tests run in this process (needs OCP: extra `geometry`; skipped when missing); one test goes through the tool and the
server python subprocess.
"""
from __future__ import annotations
import json
import math
from pathlib import Path
import numpy as np
import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import scan_handedness_flip as shf

pytest.importorskip('OCP')
from cadmcp_brain.studio import cad_brep_lib as L  # noqa: E402
from cadmcp_brain.studio import scan_handedness_flip_worker as W  # noqa: E402

PAD_Y = 25.0


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code
    return exc.value


def _box(x0, y0, z0, x1, y1, z1):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    return BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()


def _op(kind, a, b):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Fuse
    m = {'common': BRepAlgoAPI_Common, 'fuse': BRepAlgoAPI_Fuse}[kind](a, b)
    assert m.IsDone()
    return m.Shape()


def make_parts():
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeSphere
    from OCP.gp import gp_Pnt
    dome = _op('common', BRepPrimAPI_MakeSphere(gp_Pnt(0, 0, -35), 60.0).Shape(), _box(-40, -25, 3, 40, 25, 30))
    shell = L.solids(_op('fuse', dome, _box(-20, 24, 8, -8, PAD_Y + 1.0, 14)))
    plate = L.solids(_box(-40, -25, 0, 40, 25, 3))
    assert len(shell) == 1 and len(plate) == 1
    return shell[0], plate[0]


def make_roles(shell, plate) -> dict:
    """Hand-written roles from the geometry: pad outer face + its walls = side button, the highest face = panel."""
    top, recs = max(L.bbox(f)[5] for f in L.faces(shell)), []
    for k, f in enumerate(L.faces(shell)):
        p, nrm = L.inner_point(f)
        bb = L.bbox(f)
        role, sub = 'shell', None
        if bb[1] >= 23.9 and bb[0] >= -20.1 and bb[3] <= -7.9 and bb[2] >= 7.9:       # pad faces (y >= 24, x in -20..-8, z 8..14)
            role, sub = ('sidebutton', 'top') if bb[4] >= PAD_Y + 0.99 and bb[1] >= PAD_Y + 0.99 else ('sidebutton_wall', 'wall')
        elif bb[5] >= top - 1e-6 and nrm[2] > 0.9:
            role, sub = 'panel', 'top'
        elif nrm[2] < -0.9:
            role, sub = 'parting', None
        recs.append({'index': k, 'role': role, 'sub': sub, 'type': 'x', 'area': L.area(f), 'point': [float(c) for c in p], 'bbox': [float(x) for x in bb],
                     'neighbours': []})
    prec = []
    for k, f in enumerate(L.faces(plate)):
        p, nrm = L.inner_point(f)
        prec.append({'index': k, 'role': 'plate', 'sub': 'floor' if nrm[2] < -0.9 else 'parting' if nrm[2] > 0.9 else 'side', 'type': 'Plane',
                     'area': L.area(f), 'point': [float(c) for c in p], 'bbox': [float(x) for x in L.bbox(f)]})
    assert any(r['role'] == 'sidebutton' for r in recs) and any(r['role'] == 'panel' for r in recs)
    return {'top_shell': recs, 'bottom_plate': prec}


@pytest.fixture(scope='module')
def case(tmp_path_factory):
    d = tmp_path_factory.mktemp('hf')
    shell, plate = make_parts()
    L.write_step(shell, d / 'shell.step')
    L.write_step(plate, d / 'plate.step')
    roles = make_roles(shell, plate)
    (d / 'roles.json').write_text(json.dumps(roles), encoding='utf-8')
    return {'dir': d, 'roles': roles}


def request(case, out: Path, normal=(0.0, 1.0, 0.0), d=0.0, **params):
    c = case['dir']
    return {'inputs': {'shell': str(c / 'shell.step'), 'plate': str(c / 'plate.step'), 'roles': str(c / 'roles.json')},
            'params': {**W.DEFAULTS, 'mirror': {'normal': list(normal), 'd': d}, **params}, 'out_dir': str(out)}


def test_plain_flip_gates_and_outputs(case, tmp_path):
    res = W.run(request(case, tmp_path / 'o'))
    assert all(v == 'PASS' for v in res['checks'].values()), res['checks']
    m = res['measurements']
    assert max(m['volume_rel_diff_pct'].values()) < 1e-6
    assert set(m['sidebutton']['source_flank']) == {'left'} and set(m['sidebutton']['result_flank']) == {'right'}
    assert m['sidebutton']['inferred_source_handedness'] == 'right'
    assert abs(m['floor_z_range_mm'][0]) <= 1e-6 and abs(m['floor_z_range_mm'][1]) <= 1e-6 and m['transform']['floor_tilt_deg'] < 1e-6
    roles = json.loads((tmp_path / 'o' / 'face_roles.json').read_text(encoding='utf-8'))
    btn = [r for r in roles['top_shell'] if r['role'] == 'sidebutton']
    assert btn and all(r['point'][1] < -PAD_Y + 0.5 for r in btn)
    assert [r['role'] for r in roles['top_shell']] == [r['role'] for r in case['roles']['top_shell']]
    cc = res['measurements']['colour_counts']
    assert cc['read_back']['0.95,0.50,0.10'] == 1 and cc['read_back']['0.20,0.40,0.85'] == 6
    for f in res['files'].values():
        assert (tmp_path / 'o' / f).is_file()
    bb = L.bbox(L.one_solid(tmp_path / 'o' / 'top_shell.step', 'X'))
    assert bb[1] < -PAD_Y and bb[4] < 26.0 + 1e-6            # pad now on the -y flank (source pad ymax 26)


def test_tilted_mirror_plane_is_relevelled(case, tmp_path):
    n = np.array([-0.17, 0.98, 0.05])
    res = W.run(request(case, tmp_path / 'o', normal=n / np.linalg.norm(n), d=0.5))
    assert all(v == 'PASS' for v in res['checks'].values()), res['checks']
    m = res['measurements']
    assert m['transform']['floor_tilt_deg'] > 1.0                                  # roll of the mirror plane tipped the mirrored floor
    assert max(abs(z) for z in m['floor_z_range_mm']) <= 1e-3 and abs(m['plate_z_range_mm'][0]) <= 1e-3
    assert set(m['sidebutton']['result_flank']) == {'right'}


def test_flip_twice_returns_the_model(case, tmp_path):
    first = W.run(request(case, tmp_path / 'a'))
    c2 = {'dir': tmp_path / 'a', 'roles': None}
    for nm in ('top_shell', 'bottom_plate'):
        (tmp_path / 'a' / (nm + '.step')).replace(tmp_path / 'a' / ({'top_shell': 'shell', 'bottom_plate': 'plate'}[nm] + '.step'))
    (tmp_path / 'a' / 'roles.json').write_text((tmp_path / 'a' / 'face_roles.json').read_text(encoding='utf-8'), encoding='utf-8')
    second = W.run(request(c2, tmp_path / 'b'))
    assert first['checks'] == second['checks'] and all(v == 'PASS' for v in second['checks'].values())
    a, b = L.bbox(L.one_solid(case['dir'] / 'shell.step', 'X')), L.bbox(L.one_solid(tmp_path / 'b' / 'top_shell.step', 'X'))
    assert np.abs(a - b).max() < 1e-6
    assert set(second['measurements']['sidebutton']['result_flank']) == {'left'}


def test_gate_fails_when_faces_do_not_correspond(case, tmp_path):
    roles = json.loads(json.dumps(case['roles']))
    a, b = roles['top_shell'][0], roles['top_shell'][1]
    a['point'], b['point'] = b['point'], a['point']
    bad = tmp_path / 'in'
    bad.mkdir()
    for n in ('shell.step', 'plate.step'):
        (bad / n).write_bytes((case['dir'] / n).read_bytes())
    (bad / 'roles.json').write_text(json.dumps(roles), encoding='utf-8')
    res = W.run(request({'dir': bad}, tmp_path / 'o'))
    assert res['checks']['faces_correspond_to_source'] == 'FAIL'


def test_roles_must_match_the_step_files(case, tmp_path):
    roles = {'top_shell': case['roles']['top_shell'][:-1], 'bottom_plate': case['roles']['bottom_plate']}
    bad = tmp_path / 'in'
    bad.mkdir()
    for n in ('shell.step', 'plate.step'):
        (bad / n).write_bytes((case['dir'] / n).read_bytes())
    (bad / 'roles.json').write_text(json.dumps(roles), encoding='utf-8')
    with pytest.raises(W.WorkerError) as exc:
        W.run(request({'dir': bad}, tmp_path / 'o'))
    assert exc.value.code == 'HANDEDNESS_FLIP_ROLES_MISMATCH'


def test_no_sidebuttons_is_unverified_not_blocking(case, tmp_path):
    roles = json.loads(json.dumps(case['roles']))
    for r in roles['top_shell']:
        if r['role'].startswith('sidebutton'):
            r['role'], r['sub'] = 'shell', None
    bad = tmp_path / 'in'
    bad.mkdir()
    for n in ('shell.step', 'plate.step'):
        (bad / n).write_bytes((case['dir'] / n).read_bytes())
    (bad / 'roles.json').write_text(json.dumps(roles), encoding='utf-8')
    res = W.run(request({'dir': bad}, tmp_path / 'o'))
    assert res['checks']['sidebutton_flank_swapped'] == 'UNVERIFIED' and not [k for k, v in res['checks'].items() if v == 'FAIL']


def test_tool_validates_before_running(tmp_path):
    for n in ('s.step', 'p.step', 'r.json', 'sym.json'):
        (tmp_path / n).write_text('{}')
    a = ('s.step', 'p.step', 'r.json')
    rejects('HANDEDNESS_FLIP_SYMMETRY', lambda: shf.handedness_flip(tmp_path, *a))
    rejects('HANDEDNESS_FLIP_SYMMETRY', lambda: shf.handedness_flip(tmp_path, *a, symmetry_report_path='sym.json', mirror_normal=[0, 1, 0], mirror_d=0.0))
    rejects('HANDEDNESS_FLIP_SYMMETRY', lambda: shf.handedness_flip(tmp_path, *a, mirror_normal=[0, 0, 1], mirror_d=0.0))
    rejects('HANDEDNESS_FLIP_SYMMETRY', lambda: shf.handedness_flip(tmp_path, *a, mirror_normal=[0, math.nan, 1], mirror_d=0.0))
    rejects('HANDEDNESS_FLIP_SETTINGS', lambda: shf.handedness_flip(tmp_path, *a, mirror_normal=[0, 1, 0], mirror_d=0.0, floor_tol_mm=0.0))
    rejects('HANDEDNESS_FLIP_SETTINGS', lambda: shf.handedness_flip(tmp_path, *a, mirror_normal=[0, 1, 0], mirror_d=0.0, front_direction=[0, 0]))
    rejects('FACE_ROLES_SETTINGS', lambda: shf.handedness_flip(tmp_path, *a, mirror_normal=[0, 1, 0], mirror_d=0.0, colors={'logo': [0, 0, 0]}))
    rejects('HANDEDNESS_FLIP_FILE', lambda: shf.handedness_flip(tmp_path, 'r.json', 'p.step', 'r.json', mirror_normal=[0, 1, 0], mirror_d=0.0))
    rejects('UNSAFE_PATH', lambda: shf.handedness_flip(tmp_path, '../s.step', 'p.step', 'r.json', mirror_normal=[0, 1, 0], mirror_d=0.0))
    t = Tools(Brain(tmp_path))
    names = {x['name']: x for x in t.list()}
    row = names['brain_mouse_handedness_flip']
    assert row['annotations']['readOnlyHint'] is False and row['inputSchema']['properties']['floor_tol_mm']['default'] == 0.001
    assert {'shell_step_path', 'plate_step_path', 'face_roles_path'} <= set(row['inputSchema']['required'])


def test_tool_end_to_end_report_roles_and_cache(case, tmp_path):
    (tmp_path / 'in').mkdir()
    for n in ('shell.step', 'plate.step', 'roles.json'):
        (tmp_path / 'in' / n).write_bytes((case['dir'] / n).read_bytes())
    (tmp_path / 'in' / 'sym.json').write_text(json.dumps({'plane': {'normal': [0, 3.0, 0], 'd': 0.0}}), encoding='utf-8')
    t = Tools(Brain(tmp_path))
    args = {'shell_step_path': 'in/shell.step', 'plate_step_path': 'in/plate.step', 'face_roles_path': 'in/roles.json', 'symmetry_report_path': 'in/sym.json'}
    r = t.call('brain_mouse_handedness_flip', args)
    assert r['status'] == 'READY' and r['blocking_reasons'] == [] and r['handedness_flip_id'].startswith('hf_')
    assert r['settings']['mirror']['normal'] == [0.0, 1.0, 0.0] and r['settings']['mirror']['source'] == 'symmetry_report'
    folder = tmp_path / 'mouse' / 'cad' / r['handedness_flip_id']
    for item in r['outputs'].values():
        assert (tmp_path / item['relative_path']).is_file() and len(item['sha256']) == 64
    assert (folder / shf.REPORT).is_file() and not list((tmp_path / 'mouse' / 'cad').glob('*.tmp-*'))
    again = t.call('brain_mouse_handedness_flip', args)
    assert again['cached'] is True and again['handedness_flip_id'] == r['handedness_flip_id']
    # a face_roles_report.json (names face_roles under outputs) is accepted in place of face_roles.json
    (tmp_path / 'in' / 'rep.json').write_text(json.dumps({'outputs': {'face_roles': {'relative_path': 'in/roles.json'}}}), encoding='utf-8')
    viarep = t.call('brain_mouse_handedness_flip', {**args, 'face_roles_path': 'in/rep.json'})
    assert viarep['status'] == 'READY' and viarep['inputs']['face_roles_path'] == 'in/roles.json'
    (folder / 'face_roles.json').write_text('changed')
    rejects('HANDEDNESS_FLIP_OUTPUT_CHANGED', lambda: t.call('brain_mouse_handedness_flip', args))
