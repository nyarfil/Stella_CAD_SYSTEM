"""No-model safety and independent-measurement tests for the one-shot proof."""
import importlib.util
from pathlib import Path

import pytest

pytestmark=pytest.mark.skipif(importlib.util.find_spec('cadquery') is None,reason='Actual CadQuery inspection is required.')

from cadmcp_brain.req2cad.common import file_hash
from cadmcp_brain.studio.runtime import ROLES
import scripts.check_original_design as proof
from scripts.check_original_design import assess_execution,inspect_step


def test_run_root_accepts_only_new_path_under_checkout_verification(tmp_path,monkeypatch):
    verification=tmp_path/'checkout'/'verification';verification.mkdir(parents=True)
    monkeypatch.setattr(proof,'VERIFICATION_ROOT',verification.resolve())
    candidate=verification/'unit-new-original-design-path'
    assert not candidate.exists()
    assert proof.resolve_run_root(candidate)==candidate.resolve()
    with pytest.raises(ValueError,match='under this code checkout'):
        proof.resolve_run_root(tmp_path/'outside')
    with pytest.raises(ValueError,match='child'):
        proof.resolve_run_root(verification)
    existing=verification/'existing';existing.mkdir()
    with pytest.raises(ValueError,match='new path'):
        proof.resolve_run_root(existing)


def test_independent_step_inspection_proves_full_l_profile(tmp_path):
    import cadquery as cq
    points=[(0.,0.),(20.,0.),(20.,6.),(10.,6.),(10.,14.),(0.,14.)]
    body=cq.Workplane('XY').polyline(points).close().extrude(2.).val()
    path=tmp_path/'assembly.step';cq.exporters.export(body,str(path))
    result=inspect_step({'assembly_step':str(path)})
    assert result['verdict']=='pass' and all(result['checks'].values())
    assert result['actual_extents_mm']==pytest.approx([0.,20.,0.,14.,0.,2.])
    assert result['actual_volume_mm3']==pytest.approx(400.)
    assert result['notch_overlap_mm3']==pytest.approx(0.,abs=1e-9)


def test_independent_step_inspection_rejects_translated_geometry(tmp_path):
    import cadquery as cq
    points=[(0.,0.),(20.,0.),(20.,6.),(10.,6.),(10.,14.),(0.,14.)]
    body=cq.Workplane('XY').polyline(points).close().extrude(2.).val().translate((1.,0.,0.))
    path=tmp_path/'assembly.step';cq.exporters.export(body,str(path))
    result=inspect_step({'assembly_step':str(path)})
    assert result['checks']['bbox_20x14x2']
    assert not result['checks']['bbox_exact_x0_20_y0_14_z0_2']
    assert result['verdict']=='fail'


def test_execution_gate_requires_each_role_in_each_round_and_restored_hash(tmp_path):
    attachment=tmp_path/'evidence.json';attachment.write_text('{}',encoding='utf-8')
    sha=file_hash(attachment);reviews=[];receipts=[]
    call=1
    for round_number in (1,2):
        for role in ROLES:
            reviews.append({'role':role,'discussion_round':round_number,'evidence_inspections':[{
                'attachment_path':str(attachment),'attachment_sha256':sha,'kind':'json',
                'status':'viewed','observation':'Measured evidence inspected.'}]})
            receipts.append({'role':role,'response_received':True});call+=1
    receipts.extend({'role':role,'response_received':True} for role in ('requirements','mechanism','mechanical_selector','geometric_architect'))
    checks=assess_execution(14,receipts,reviews,[{'review_id':str(i)} for i in range(10)])
    assert all(checks.values())
    reviews[-1]['discussion_round']=1
    assert not assess_execution(14,receipts,reviews,[{}]*10)['five_roles_have_rounds_one_and_two']
    attachment.write_text('changed',encoding='utf-8')
    assert not assess_execution(14,receipts,reviews,[{}]*10)['provider_restore_path_verified']
