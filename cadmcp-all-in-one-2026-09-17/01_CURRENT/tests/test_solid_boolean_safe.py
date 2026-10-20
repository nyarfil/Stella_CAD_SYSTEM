"""brain_solid_boolean_safe on synthetic solids (module function, worker subprocess once; library functions in this process). Needs OCP."""
from __future__ import annotations
from pathlib import Path
import pytest
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import solid_boolean_safe as SB

pytest.importorskip('OCP')
from cadmcp_brain.studio import cad_brep_lib as L  # noqa: E402
from cadmcp_brain.studio import solid_boolean_safe_worker as W  # noqa: E402


def box(x0, y0, z0, x1, y1, z1):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    return L.solids(BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape())[0]


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code


def test_overlap_fuse_cut_common_pass():
    a, b = box(0, 0, 0, 10, 10, 10), box(5, 5, 5, 15, 15, 15)
    for op, vol in (('fuse', 1875.0), ('cut', 875.0), ('common', 125.0)):
        r = W.safe_boolean(a, b, op, points=400)
        assert r['status'] == 'PASS', (op, r['attempts'])
        assert abs(r['gate']['measured_mm3'] - vol) < 1e-3 and r['solids'] == 1
        assert r['bookkeeping']['partner_status'] == 'PASS'


def test_near_touching_parts_plain_leaves_two_solids_fuzzy_merges():
    a, b = box(0, 0, 0, 10, 10, 10), box(10.004, 0, 0, 20, 10, 10)        # 0.004 mm gap: plain Boolean returns two solids = not fused
    assert len(L.solids(W.run_op(a, b, 'fuse', 0.0))) == 2
    r = W.safe_boolean(a, b, 'fuse', points=400, tol_mm=0.01)
    assert r['status'] == 'PASS' and r['solids'] == 1
    steps = [x for x in r['attempts'] if x['op'] == 'fuse']
    assert steps[0]['step'] == 'plain' and steps[0]['status'] == 'FAIL' and steps[0]['checks']['solid_count'] == 'FAIL'
    assert steps[1]['status'] == 'PASS' and steps[1]['fuzzy_mm'] == pytest.approx(0.01)
    rejects_none = W.safe_boolean(a, b, 'fuse', points=400, include_plain=False, fuzzy_multiples=[0.1], tol_mm=0.01)
    assert rejects_none['status'] == 'FAIL' and rejects_none['shape'] is None      # fuzzy 0.001 < gap: still two solids, rejected, no file


def test_gate_rejects_noop_none_and_wrong_result():
    a, b = box(0, 0, 0, 10, 10, 10), box(5, 5, 5, 15, 15, 15)
    va, vb = 1000.0, 1000.0
    noop = W.gate_boolean(a, b, 'cut', a, va=va, vb=vb, expected_mm3=875.0, params={'points': 400})
    assert noop['status'] == 'FAIL' and noop['checks']['volume'] == 'FAIL' and 'no_op' in noop and noop['checks']['points'] == 'SKIPPED'      # a - b is 875, a is 1000
    same = W.gate_boolean(a, b, 'fuse', a, va=va, vb=vb, expected_mm3=1875.0, params={'points': 400})
    assert same['status'] == 'FAIL' and 'no_op' in same
    assert W.gate_boolean(a, b, 'fuse', None, va=va, vb=vb, expected_mm3=1875.0)['status'] == 'FAIL'
    unver = W.gate_boolean(a, b, 'fuse', W.run_op(a, b, 'fuse'), va=va, vb=vb, expected_mm3=None, params={'points': 400})
    assert unver['status'] == 'UNVERIFIED' and unver['checks']['volume'] == 'UNVERIFIED'


def test_empty_cut_is_accepted_only_when_expected():
    a = box(2, 2, 2, 8, 8, 8)
    b = box(0, 0, 0, 10, 10, 10)
    r = W.safe_boolean(a, b, 'cut', points=400, expect_solids=None)
    assert r['status'] == 'PASS' and r['solids'] == 0 and r['gate']['measured_mm3'] == 0.0
    assert W.gate_boolean(b, a, 'cut', L.compound([]), va=1000.0, vb=216.0, expected_mm3=784.0, params={'points': 400})['status'] == 'FAIL'


def test_end_to_end_report_and_cache(tmp_path):
    from cadmcp_brain.studio.cad_brep_lib import write_step
    write_step(box(0, 0, 0, 10, 10, 10), tmp_path / 'a.step')
    write_step(box(10.004, 0, 0, 20, 10, 10), tmp_path / 'b.step')
    rep = SB.boolean_safe(tmp_path, 'a.step', 'b.step', 'fuse', points=400)
    assert rep['status'] == 'PASS' and rep['boolean_safe_id'].startswith('sb_') and rep['accepted_attempt'].startswith('fuzzy')
    assert rep['round_trip']['solids'] == 1 and (tmp_path / rep['outputs']['result.step']['relative_path']).is_file()
    assert SB.boolean_safe(tmp_path, 'a.step', 'b.step', 'fuse', points=400).get('cached') is True
    rejects('BOOLEAN_SAFE_SETTINGS', lambda: SB.boolean_safe(tmp_path, 'a.step', 'b.step', 'weld'))
    rejects('UNSAFE_PATH', lambda: SB.boolean_safe(tmp_path, 'missing.step', 'b.step', 'fuse'))
    miss = SB.boolean_safe(tmp_path, 'a.step', 'b.step', 'fuse', points=400, include_plain=False, fuzzy_multiples=[0.1])
    assert miss['status'] == 'FAIL' and not miss['outputs']
