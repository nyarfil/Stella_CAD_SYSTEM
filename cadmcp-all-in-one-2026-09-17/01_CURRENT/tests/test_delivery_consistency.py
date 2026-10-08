from pathlib import Path

import pytest

cq=pytest.importorskip('cadquery',reason='Delivery consistency requires the actual CAD kernel.')

from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio.recipe import execute_recipe,verify_delivery_steps


def export(path,shape):
    cq.exporters.export(shape,str(path))
    return path


def box(x=0):
    return cq.Workplane('XY').box(4,4,4).val().translate((x,0,0))


def report(tmp_path,parts,assembly):
    paths={name:export(tmp_path/(name+'.step'),shape) for name,shape in parts.items()}
    assembly_path=export(tmp_path/'assembly.step',assembly)
    return verify_delivery_steps(paths,assembly_path)


def test_exact_positioned_part_steps_match_assembly(tmp_path):
    parts={'left':box(-4),'right':box(4)}
    result=report(tmp_path,parts,cq.Compound.makeCompound(list(parts.values())))
    assert result['verdict']=='pass'
    assert result['part_solid_count']==result['assembly_solid_count']==2
    assert result['unmatched_part_solids']==result['unmatched_assembly_solids']==[]
    assert 'not a design or manufacturing tolerance' in result['tolerance_interpretation']


def test_same_bbox_and_volume_but_different_shape_fails(tmp_path):
    base=cq.Workplane('XY').box(6,6,6).val()
    corner_a=cq.Workplane('XY').box(2,2,2).val().translate((2,2,2))
    corner_b=cq.Workplane('XY').box(2,2,2).val().translate((-2,-2,-2))
    expected=base.cut(corner_a);different=base.cut(corner_b)
    assert expected.BoundingBox().xlen==pytest.approx(different.BoundingBox().xlen)
    assert expected.Volume()==pytest.approx(different.Volume())
    result=report(tmp_path,{'part':expected},different)
    assert result['verdict']=='fail'
    assert result['unmatched_part_solids']==[{'part_id':'part','solid_index':0}]


@pytest.mark.parametrize('assembly_factory',[lambda a,b:cq.Compound.makeCompound([a.translate((1,0,0)),b]),
                                                       lambda a,b:a,
                                                       lambda a,b:cq.Compound.makeCompound([a,b,box(12)]),
                                                       lambda a,b:cq.Compound.makeCompound([a,b,b])],
                         ids=['moved','missing','extra','duplicate'])
def test_moved_missing_extra_or_duplicate_solid_fails(tmp_path,assembly_factory):
    left,right=box(-4),box(4)
    result=report(tmp_path,{'left':left,'right':right},assembly_factory(left,right))
    assert result['verdict']=='fail'
    assert result['unmatched_part_solids'] or result['unmatched_assembly_solids']


def test_non_solid_delivery_is_rejected(tmp_path):
    edge=cq.Edge.makeLine(cq.Vector(0,0,0),cq.Vector(1,0,0))
    export(tmp_path/'part.step',edge)
    export(tmp_path/'assembly.step',edge)
    with pytest.raises(BrainError) as exc:
        verify_delivery_steps({'part':tmp_path/'part.step'},tmp_path/'assembly.step')
    assert exc.value.code=='STUDIO_INVALID_DELIVERY_STEP'


def test_invalid_boolean_result_is_rejected(tmp_path,monkeypatch):
    part=export(tmp_path/'part.step',box())
    assembly=export(tmp_path/'assembly.step',box())
    class NullWrapped:
        def IsNull(self):return True
    class InvalidDifference:
        wrapped=NullWrapped()
        def isValid(self):return False
    monkeypatch.setattr(cq.Shape,'cut',lambda self,other:InvalidDifference())
    with pytest.raises(BrainError) as exc:
        verify_delivery_steps({'part':part},assembly)
    assert exc.value.code=='STUDIO_DELIVERY_BOOLEAN'


def simple_recipe():
    return {'schema_version':1,'title':'Delivery integration fixture',
            'original_request':'Create a positioned delivery consistency fixture.',
            'functions':{'Body':'Provide the bounded fixture body.'},
            'design_basis':{'kind':'first_principles','summary':'A hand-authored test body isolates the STEP delivery contract.',
                            'assumptions':['The dimensions are synthetic test values, not owner hardware measurements.']},
            'verification_plan':['Re-import the part and assembly STEP files and compare every solid.'],
            'operations':[{'id':'body','op':'box','function_id':'Body','reason':'Create a synthetic positive-volume solid.',
                           'size_mm':[4.,5.,6.],'center_mm':[3.,2.,1.]}],
            'outputs':[{'part_id':'body','node':'body'}],
            'unverified_requirements':['Physical manufacturing and material performance are outside this fixture.']}


def test_execute_recipe_records_real_delivery_check(tmp_path):
    result=execute_recipe(simple_recipe(),{},tmp_path)
    check=next(item for item in result['checks'] if item['id']=='_system-delivery-step-geometry-consistency')
    assert check['verdict']=='pass'
    assert result['geometry_checks_verdict']=='pass'
    assert (tmp_path/'measurements.json').is_file()


def test_execute_recipe_delivery_failure_controls_geometry_verdict(tmp_path,monkeypatch):
    import cadmcp_brain.studio.recipe as module
    monkeypatch.setattr(module,'verify_delivery_steps',lambda *_:{
        'id':'_system-delivery-step-geometry-consistency','kind':'negative_control','verdict':'fail'})
    result=execute_recipe(simple_recipe(),{},tmp_path)
    assert result['checks'][-1]['verdict']=='fail'
    assert result['geometry_checks_verdict']=='fail'
