from copy import deepcopy
import math
import pytest
from pydantic import ValidationError
from cadmcp_brain.errors import BrainError
from cadmcp_brain.models import Brief, Concept, Plan, Constraint, Check, Mechanism
from cadmcp_brain.gates import evaluate_concept, topological_order


def rejects(code,fn):
    with pytest.raises(BrainError) as e: fn()
    assert e.value.code==code


def test_valid_schema_fixtures(data):
    Brief.model_validate(data['brief'])
    for c in data['concepts']['items']: Concept.model_validate(c)
    Plan.model_validate(data['plan'])

@pytest.mark.parametrize('field,value',[('value',True),('value','two'),('value',float('nan')),('value',float('inf'))])
def test_invalid_numeric_constraint(data,field,value):
    c=deepcopy(data['brief']['constraints'][0]);c[field]=value
    with pytest.raises(ValidationError): Constraint.model_validate(c)

@pytest.mark.parametrize('v',[-1,1.5])
def test_count_constraints_require_nonnegative_integer(data,v):
    c=deepcopy(data['brief']['constraints'][0]);c['value']=v
    with pytest.raises(ValidationError): Constraint.model_validate(c)

@pytest.mark.parametrize('v',[[0,0,0],[0,-2,0],[float('nan'),1,0],[True,0,0]])
def test_invalid_direction(data,v):
    m=deepcopy(data['concepts']['items'][0]['mechanisms'][0]);m['input_direction']=v
    with pytest.raises(ValidationError): Mechanism.model_validate(m)

@pytest.mark.parametrize('operation',['sweep','loft','extrude','exec','run_python'])
def test_unsupported_task_operation_not_silently_normalized(data,operation):
    p=deepcopy(data['plan']);p['steps'][0]['operation']=operation
    with pytest.raises(ValidationError): Plan.model_validate(p)


def test_unknown_fields_forbidden(data):
    b=deepcopy(data['brief']);b['ignore_previous_gates']=True
    with pytest.raises(ValidationError): Brief.model_validate(b)

@pytest.mark.parametrize('field,value',[('target',False),('op','le'),('tolerance',0.1)])
def test_validity_check_cannot_be_weakened(data,field,value):
    c=deepcopy(data['plan']['checks'][0]);c[field]=value
    with pytest.raises(ValidationError): Check.model_validate(c)


def test_pairwise_check_requires_two_artifacts(data):
    c=deepcopy(data['plan']['checks'][2]);c['artifact_b']=c['artifact_a']
    with pytest.raises(ValidationError): Check.model_validate(c)


def test_fabricated_quote_rejected(brain,data):
    brain.open('test',data['request']);b=deepcopy(data['brief']);b['requirements'][0]['source_refs'][0]['quote']='this was never said'
    rejects('BAD_QUOTE',lambda:brain.submit_intent('test',0,b))
    assert brain.store.get('test').revision==0


def test_unknown_source_rejected(brain,data):
    brain.open('test',data['request']);b=deepcopy(data['brief']);b['requirements'][0]['source_refs'][0]['source_id']='SRC-99'
    rejects('BAD_SOURCE',lambda:brain.submit_intent('test',0,b))


def test_dropped_source_span_rejected(brain,data):
    brain.open('test',data['request']);b=deepcopy(data['brief']);b['dispositions']=[]
    rejects('SOURCE_COVERAGE',lambda:brain.submit_intent('test',0,b))


def test_inference_not_mandatory(brain,data):
    brain.open('test',data['request']);b=deepcopy(data['brief']);b['requirements'][0]['origin']='inferred'
    rejects('INFERENCE_AS_REQUIREMENT',lambda:brain.submit_intent('test',0,b))

@pytest.mark.parametrize('a,b',[('le',1),('eq',1)])
def test_contradictory_numeric_bounds(brain,data,a,b):
    brain.open('test',data['request']);brief=deepcopy(data['brief']);base=brief['constraints'][0]
    brief['constraints']=[dict(base,op='ge',value=3),dict(base,op=a,value=b)]
    rejects('CONTRADICTORY_CONSTRAINTS',lambda:brain.submit_intent('test',0,brief))


def test_contradictory_equalities(brain,data):
    brain.open('test',data['request']);b=deepcopy(data['brief']);c=b['constraints'][1]
    b['constraints'] += [dict(c,value=True)]
    rejects('CONTRADICTORY_CONSTRAINTS',lambda:brain.submit_intent('test',0,b))


def test_unit_conflict(brain,data):
    brain.open('test',data['request']);b=deepcopy(data['brief']);c=b['constraints'][0]
    b['constraints'].append(dict(c,unit='mm'))
    rejects('UNIT_CONFLICT',lambda:brain.submit_intent('test',0,b))


def test_unresolved_intent_blocks(brain,data):
    brain.open('test',data['request']);b=deepcopy(data['brief']);b['unknowns'][0]['blocks']='intent'
    rejects('BLOCKING_UNKNOWNS',lambda:brain.submit_intent('test',0,b))


def test_unknown_resolution_needs_source(brain,data):
    brain.open('test',data['request']);b=deepcopy(data['brief']);b['unknowns'][0]['resolution']='the model says so'
    rejects('UNSOURCED_RESOLUTION',lambda:brain.submit_intent('test',0,b))

@pytest.mark.parametrize('key,value,code',[
 ('output_direction',[0,0,-1],'AXIS_MISMATCH'),('output_direction',[0,1,0],'AXIS_MISMATCH'),
 ('input_direction',None,'UNKNOWN_ACTUATION_DIRECTION'),('return_method','none','MISSING_RETURN'),
 ('hard_stop',False,'MISSING_STOP'),('return_method','metal_spring','CONSTRAINT_VIOLATION')])
def test_mechanical_concept_gates(intent,data,key,value,code):
    cs=deepcopy(data['concepts']);cs['items'][0]['mechanisms'][0][key]=value
    result=intent.submit_concepts('test',1,cs)
    errors=result['evaluations'][0]['errors']
    assert code in {e['code'] for e in errors}
    rejects('CONCEPT_REJECTED',lambda:intent.select('test',2,'C-direct'))


def test_no_fake_part_count(intent,data):
    cs=deepcopy(data['concepts']);cs['items'][0]['properties']['printed_parts_count']=1
    r=intent.submit_concepts('test',1,cs)
    assert 'PROPERTY_SPOOF' in {e['code'] for e in r['evaluations'][0]['errors']}


def test_stop_metadata_needs_interface(intent,data):
    cs=deepcopy(data['concepts']);cs['items'][0]['interfaces']=[i for i in cs['items'][0]['interfaces'] if i['kind']!='stop']
    r=intent.submit_concepts('test',1,cs)
    assert 'STOP_INTERFACE_MISSING' in {e['code'] for e in r['evaluations'][0]['errors']}


def test_catalog_pattern_must_support_function(intent,data):
    cs=deepcopy(data['concepts']);cs['items'][0]['mechanisms'][0]['pattern_id']='pcb_datum_screw'
    r=intent.submit_concepts('test',1,cs)
    assert 'PATTERN_FUNCTION_MISMATCH' in {e['code'] for e in r['evaluations'][0]['errors']}


def test_disconnected_parts_detected(intent,data):
    cs=deepcopy(data['concepts']);cs['items'][0]['interfaces']=[]
    r=intent.submit_concepts('test',1,cs)
    assert 'DISCONNECTED_ASSEMBLY' in {e['code'] for e in r['evaluations'][0]['errors']}


def test_unknown_pattern(intent,data):
    cs=deepcopy(data['concepts']);cs['items'][0]['mechanisms'][0]['pattern_id']='magic-perfect-button'
    rejects('UNKNOWN_PATTERN',lambda:intent.submit_concepts('test',1,cs))


def test_renamed_duplicate_not_alternative(intent,data):
    cs=deepcopy(data['concepts']);cs['items'][1]=deepcopy(cs['items'][0]);cs['items'][1]['id']='C-copy'
    rejects('DUPLICATE_ALTERNATIVES',lambda:intent.submit_concepts('test',1,cs))


def test_duplicate_cross_kind_ids(intent,data):
    cs=deepcopy(data['concepts']);cs['items'][0]['mechanisms'][0]['id']='R-axis'
    rejects('DUPLICATE_ID',lambda:intent.submit_concepts('test',1,cs))


def test_plan_cycle(selected,data):
    p=deepcopy(data['plan']);p['steps'][0]['depends_on']=['S-switch']
    rejects('DEPENDENCY_CYCLE',lambda:selected.submit_plan('test',3,p))


def test_missing_dependency(selected,data):
    p=deepcopy(data['plan']);p['steps'][0]['depends_on']=['S-missing']
    rejects('UNKNOWN_DEPENDENCY',lambda:selected.submit_plan('test',3,p))


def test_physical_requirement_not_geometry_only(selected,data):
    p=deepcopy(data['plan']);p['checks'][-1]['kind']='manual'
    rejects('PHYSICAL_TEST_REQUIRED',lambda:selected.submit_plan('test',3,p))


def test_unchecked_requirement(selected,data):
    p=deepcopy(data['plan']);p['checks']=[c for c in p['checks'] if c['id']!='CH-life']
    rejects('UNCHECKED_REQUIREMENT',lambda:selected.submit_plan('test',3,p))


def test_invented_user_dimension(selected,data):
    p=deepcopy(data['plan']);p['dimensions'][0]['value_mm']=21.0
    rejects('INVENTED_DIMENSION',lambda:selected.submit_plan('test',3,p))


def test_proposed_dimension_not_claimed_measurement(selected,data):
    p=deepcopy(data['plan']);p['dimensions'][0].update(value_mm=21.0,provenance='proposal',source_refs=[])
    selected.submit_plan('test',3,p)


def test_fabricated_measurement(selected,data):
    p=deepcopy(data['plan']);p['dimensions'][0].update(provenance='measurement',evidence_id='fake')
    rejects('UNVERIFIED_MEASUREMENT',lambda:selected.submit_plan('test',3,p))


def test_plan_blocking_unknown(selected,data):
    p=deepcopy(data['plan']);p['unknowns']=[{'id':'U-axis','question':'Which switch direction?','blocks':'plan'}]
    rejects('BLOCKING_UNKNOWNS',lambda:selected.submit_plan('test',3,p))


def test_geometry_requirement_needs_measured_check(selected,data):
    p=deepcopy(data['plan']);p['checks']=[c for c in p['checks'] if c['id'] not in ('CH-width','CH-brep')]
    p['checks'][2]['requirement_ids'].append('R-width')
    rejects('GEOMETRY_TEST_REQUIRED',lambda:selected.submit_plan('test',3,p))


def test_explicit_preference_cannot_become_binding(brain,data):
    import copy
    b=copy.deepcopy(data['brief'])
    b['requirements'][1]['priority']='preference'
    brain.open('test',data['request'])
    with pytest.raises(BrainError) as exc:brain.submit_intent('test',0,b)
    assert exc.value.code=='PREFERENCE_AS_CONSTRAINT'
