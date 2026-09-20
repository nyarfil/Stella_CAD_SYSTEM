"""No model calls: verify planning controls and real-kernel original-design route."""
import copy
import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio.planning import capabilities,recovery_for
from cadmcp_brain.studio.autopilot import Autopilot
from test_studio import review

REQUEST='幅20 mm、奥行き10 mm、厚さ2 mmの検査用プレートを新規設計する。'


def recipe():
    return {'title':'Original geometry test plate','original_request':REQUEST,
            'functions':{'Plate':'Represent the specified measured plate'},
            'operations':[{'id':'plate','op':'box','function_id':'Plate','reason':'Construct the owner-specified envelope.',
                           'size_mm':[20.,10.,2.],'center_mm':[0.,0.,1.]}],
            'outputs':[{'part_id':'plate','node':'plate'}],
            'dimension_checks':[{'id':'size_'+axis,'part':'plate','kind':'bbox','axis':axis,
                                 'nominal_mm':value,'tolerance_mm':.001} for axis,value in zip('xyz',[20.,10.,2.])],
            'design_basis':{'kind':'first_principles','summary':'Construct dimensions directly from the owner request.',
                            'assumptions':['A static dimensional coupon; no load requirement supplied.']},
            'verification_plan':['Measure all three STEP bounding dimensions.'],
            'unverified_requirements':['Manufacturing tolerance and material strength untested.']}


class OriginalFixture:
    def __init__(self):self.calls=[]
    def generate(self,task,schema,context,*,role):
        self.calls.append(role)
        if 'subject_digest' in schema.get('properties',{}):
            value=review(context['subject_digest'],role,attachments=context['subject']['payload']['evidence_attachments'])
            value.update(discussion_round=context['discussion_round'],challenged_review_ids=context.get('required_challenged_review_ids',[]))
            return value
        if role=='requirements':return {'original_request':REQUEST,'functions':[{'id':'Plate','source_excerpt':REQUEST,
            'function':'dimension coupon','behavior':'Represent a static dimensional envelope.','queries':['rectangular plate']}]}
        if role=='mechanism':
            option={'id':'A','name':'Direct plate','covers':['Plate'],'mechanism_principle':'Static plate constructed to the required envelope.',
                    'proposed_parts':['plate'],'force_path':'No owner load requirement; this is a dimensional coupon.',
                    'assembly_method':'Single piece with no assembly required.','risks':['Physical manufacturing is untested.'],
                    'design_basis':{'kind':'first_principles','principles':['Prismatic volume with prescribed dimensions.'],
                                    'assumptions':['No mechanical load or joining requirement supplied.'],
                                    'verification_plan':['Measure all three output STEP dimensions.'],
                                    'unknowns':['Manufacturing and material properties untested.']}}
            other=copy.deepcopy(option);other.update(id='B',name='Profile extrusion',mechanism_principle='Extrude a rectangular planar profile to the required thickness.')
            return {'options':[option,other],'incompatibilities':[]}
        if role=='mechanical_selector':return {'candidate_index':0,'reason':'A direct measured envelope satisfies the scoped geometry request.','remaining_risks':['Physical production untested.']}
        return recipe()


def test_capability_boundaries(tmp_path):
    t=Tools(Brain(tmp_path))
    result=t.brain_studio_capabilities(['polygon_extrusion','loft','sweep'],['sampled_translation_clearance','rotational_clearance'])
    assert 'loft' in result['operations']
    assert result['unsupported_operations']==['sweep']
    assert result['unsupported_checks']==['rotational_clearance']
    assert not result['requested_capabilities_supported'] and not result['design_feasibility_certified']
    assert next(x for x in t.list() if x['name']=='brain_studio_capabilities')['annotations']['readOnlyHint']


def test_invalid_matrix_is_replanned_once_with_frozen_brief(tmp_path):
    t=Tools(Brain(tmp_path/'workspace'));t.brain_open('matrix-correction',REQUEST)
    class InvalidPair(OriginalFixture):
        def __init__(self):super().__init__();self.matrix_contexts=[]
        def generate(self,task,schema,context,*,role):
            result=super().generate(task,schema,context,role=role)
            if role=='mechanism' and 'options' in schema.get('properties',{}):
                self.matrix_contexts.append(copy.deepcopy(context))
                if len(self.matrix_contexts)==1:
                    result=copy.deepcopy(result)
                    result['incompatibilities']=[{'option_a':result['options'][0]['id'],
                        'option_b':'Rejected_but_not_defined','reason':'This rejected idea is not an offered option.'}]
            return result
    provider=InvalidPair()
    result=Autopilot(t,provider,tmp_path/'run',design_route='original',max_repairs=0,max_replans=1).run('matrix-correction')
    assert result['phase']=='prototype_ready_for_owner_review'
    assert len(provider.matrix_contexts)==2
    first,second=provider.matrix_contexts
    assert first['frozen_brief']==second['frozen_brief']
    assert first['references']==second['references']
    assert second['previous_invalid_matrix']['incompatibilities'][0]['option_b']=='Rejected_but_not_defined'
    assert 'Invalid incompatible pair' in second['validation_error']
    assert result['rejected_matrix']==second['previous_invalid_matrix']


@pytest.mark.parametrize('budget',[0,1,2])
def test_matrix_validation_failure_respects_shared_replanning_budget(tmp_path,monkeypatch,budget):
    from pydantic import ValidationError
    t=Tools(Brain(tmp_path/'workspace'));t.brain_open('matrix-stop',REQUEST)
    class AlwaysInvalid(OriginalFixture):
        def __init__(self):super().__init__();self.mechanism_calls=0
        def generate(self,task,schema,context,*,role):
            result=super().generate(task,schema,context,role=role)
            if role=='mechanism' and 'options' in schema.get('properties',{}):
                self.mechanism_calls+=1
                result=copy.deepcopy(result)
                result['incompatibilities']=[{'option_a':'missing_a','option_b':'missing_b',
                                             'reason':'Neither of these IDs is an offered option.'}]
            return result
    provider=AlwaysInvalid()
    monkeypatch.setattr(t,'brain_studio_build',lambda *a,**k:pytest.fail('Invalid matrix must never build CAD'))
    run=Autopilot(t,provider,tmp_path/'run',design_route='original',max_repairs=0,max_replans=budget)
    with pytest.raises(ValidationError,match='Invalid incompatible pair'):
        run.run('matrix-stop')
    assert provider.mechanism_calls==budget+1
    assert run.state['phase']=='stopped_with_evidence'
    assert run.state['rejected_matrix']['incompatibilities'][0]['option_a']=='missing_a'


@pytest.mark.parametrize('route',['original','auto'])
def test_original_design_without_catalog_shape(tmp_path,monkeypatch,route):
    t=Tools(Brain(tmp_path/'workspace'));t.brain_open('original-test',REQUEST)
    def search(*args,**kwargs):
        if route=='original':raise AssertionError('Explicit original route must not search.')
        return {'functions':[],'mode':'semantic'}
    monkeypatch.setattr(t,'brain_fs_search_tasks',search)
    provider=OriginalFixture()
    result=Autopilot(t,provider,tmp_path/'calls',design_route=route,max_repairs=0).run('original-test')
    assert result['phase']=='prototype_ready_for_owner_review'
    assert result['reference_uids']==[] and result['build']['geometry_checks_verdict']=='pass'
    assert not result['physical_performance_certified'] and len(provider.calls)==14


def test_schema_correction_resolves_check_to_output_part_id(tmp_path):
    t=Tools(Brain(tmp_path/'workspace'));t.brain_open('check-target-test',REQUEST)

    class WrongCheckTargetFixture(OriginalFixture):
        def __init__(self):
            super().__init__();self.tasks=[]
        def generate(self,task,schema,context,*,role):
            self.tasks.append(task)
            result=super().generate(task,schema,context,role=role)
            if role in ('geometric_architect','geometric_architect_correction'):
                result=copy.deepcopy(result)
                result['outputs'][0]['part_id']='part_plate'
                for check in result['dimension_checks']:
                    check['part']='plate' if role=='geometric_architect' else 'part_plate'
            return result

    provider=WrongCheckTargetFixture()
    result=Autopilot(t,provider,tmp_path/'calls',design_route='original',max_repairs=0).run('check-target-test')
    assert result['phase']=='prototype_ready_for_owner_review'
    initial=next(task for task in provider.tasks if task.startswith('Produce an executable typed recipe'))
    correction=next(task for task in provider.tasks if task.startswith('Correct the previous Recipe'))
    assert 'outputs[].part_id' in initial and 'operation/node id' in initial
    assert 'same intended outputs[].part_id' in correction
    assert 'do not change numbers, requirements, or add/remove checks' in correction


def test_schema_correction_rejects_numeric_check_relaxation_before_build(tmp_path,monkeypatch):
    t=Tools(Brain(tmp_path/'workspace'));t.brain_open('weakened-check-test',REQUEST)

    class WeakenedCheckFixture(OriginalFixture):
        def generate(self,task,schema,context,*,role):
            result=super().generate(task,schema,context,role=role)
            if role in ('geometric_architect','geometric_architect_correction'):
                result=copy.deepcopy(result)
                result['outputs'][0]['part_id']='part_plate'
                for check in result['dimension_checks']:
                    check['part']='plate' if role=='geometric_architect' else 'part_plate'
                if role=='geometric_architect_correction':result['dimension_checks'][0]['tolerance_mm']=.01
            return result

    monkeypatch.setattr(t,'brain_studio_build',lambda *args,**kwargs: pytest.fail('worker must not run'))
    with pytest.raises(BrainError) as caught:
        Autopilot(t,WeakenedCheckFixture(),tmp_path/'calls',design_route='original',max_repairs=0).run('weakened-check-test')
    assert caught.value.code=='AUTOPILOT_WEAKENED_CHECK'


def test_auto_rejects_unselected_reference_use_before_build(tmp_path,monkeypatch):
    t=Tools(Brain(tmp_path/'workspace'));t.brain_open('unselected-reference-test',REQUEST)
    monkeypatch.setattr(t,'brain_fs_search_tasks',lambda *args,**kwargs: {'functions':[],'mode':'semantic'})

    class UnselectedReferenceFixture(OriginalFixture):
        def generate(self,task,schema,context,*,role):
            result=super().generate(task,schema,context,role=role)
            if role=='geometric_architect':
                result=copy.deepcopy(result)
                result['reference_uses']=[{
                    'function_id':'Plate','use':'principle_reference',
                    'uid':'9999/99999999','evidence_digest':'a'*64,'cad_sha256':'b'*64,
                    'application':'Use a hypothetical catalog principle for this new plate.',
                }]
            return result

    monkeypatch.setattr(t,'brain_studio_build',lambda *args,**kwargs: pytest.fail('worker must not run'))
    with pytest.raises(BrainError) as caught:
        Autopilot(t,UnselectedReferenceFixture(),tmp_path/'calls',design_route='auto',max_repairs=0).run('unselected-reference-test')
    assert caught.value.code=='AUTOPILOT_REFERENCE'


def test_integrity_failure_is_not_generic_retry():
    recovery=recovery_for(BrainError('STUDIO_STALE','Changed evidence.'))
    assert recovery['category']=='integrity_or_contract'
    assert not recovery['automatic_retry'] and not recovery['requirements_relaxed']
def test_schema_correction_rejects_ambiguous_node_and_part_identity():
    from cadmcp_brain.studio.autopilot import _resolve_check_part
    from cadmcp_brain.errors import BrainError
    import pytest
    with pytest.raises(BrainError, match='ambiguous'):
        _resolve_check_part('a', {'a': 'b', 'b': 'a'})
