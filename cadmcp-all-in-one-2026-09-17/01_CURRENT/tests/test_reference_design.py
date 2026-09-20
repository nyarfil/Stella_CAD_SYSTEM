"""Reference-use provenance and honest non-catalog design routes."""
import importlib.util
from pathlib import Path

import pytest
from pydantic import ValidationError

pytestmark=pytest.mark.skipif(importlib.util.find_spec('cadquery') is None,reason='Actual CadQuery generation is required.')

from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio.recipe import Recipe,execute_recipe
from cadmcp_brain.studio.synthesis import Matrix,synthesize

REQUEST='Create an L-shaped mounting plate from explicit dimensions.'

def first_principles_recipe():
    return {
        'title':'L mounting plate',
        'original_request':REQUEST,
        'functions':{'Mount':'Carry a fixture load through a bounded polygon plate.'},
        'design_parameters':{'height':4.0},
        'parameter_basis':{'height':'Proposed prototype thickness; not a measured interface.'},
        'design_basis':{
            'kind':'first_principles',
            'summary':'A constant-section L profile provides the requested mounting envelope.',
            'assumptions':['Static fixture loads and material strength remain unqualified.'],
        },
        'verification_plan':['Measure the generated STEP bounding box and solid volume.'],
        'operations':[{
            'id':'plate','op':'polygon_extrusion','function_id':'Mount',
            'reason':'Create a non-rectangular plate from the explicit bounded profile.',
            'points_mm':[[0.,0.],[10.,0.],[10.,4.],[6.,4.],[6.,8.],[0.,8.]],
            'height_mm':4.,'origin_mm':[2.,3.,1.],
        }],
        'outputs':[{'part_id':'plate','node':'plate'}],
        'dimension_checks':[
            {'id':'width','part':'plate','kind':'bbox','axis':'x','nominal_mm':10.,'tolerance_mm':1e-6},
            {'id':'height','part':'plate','kind':'bbox','axis':'z','nominal_mm':4.,'tolerance_mm':1e-6},
        ],
        'unverified_requirements':['Material, loads, fasteners and physical manufacturing remain unknown.'],
    }

def brief():
    return {'original_request':REQUEST,'functions':[{
        'id':'Mount','source_excerpt':'mounting plate','function':'support fixture',
        'behavior':'Transfer fixture load into the mounting surface.',
        'queries':['support fixture'],'required_features':['has_planar_surface'],
    }],'unresolved':['Actual loads are unknown.']}

def option(name,basis):
    return {'id':name,'name':name,'covers':['Mount'],
            'mechanism_principle':'Use a plate section to carry load into the mounting surface.',
            'references':[],'design_basis':basis,'proposed_parts':['plate'],
            'force_path':'Fixture reaction passes through the plate into its mounting face.',
            'assembly_method':'Fastener selection and insertion direction remain to be verified.',
            'risks':['No catalog surface evidence or physical load proof exists.']}

def first_basis(label):
    return {'kind':'first_principles','principles':[f'{label}: constant sections transfer load through their area.'],
            'assumptions':['Material and applied loads are not yet specified.'],
            'verification_plan':['Generate the solid, measure interfaces, then perform load validation.'],
            'unknowns':[f'{label}: strength and fastening remain unknown.']}

class NoCatalogService:
    def evidence(self,uid):
        raise AssertionError(f'catalog evidence must not be requested for {uid}')

def test_first_principles_polygon_generates_and_measures_real_cad(tmp_path):
    recipe=Recipe.model_validate(first_principles_recipe())
    result=execute_recipe(recipe,{},tmp_path/'build')
    assert result['geometry_checks_verdict']=='pass'
    assert result['references']==[] and result['reference_uses']==[]
    import cadquery as cq
    shape=cq.importers.importStep(str(tmp_path/'build'/'plate'/'model.step')).val()
    assert shape.Volume()==pytest.approx(256.,rel=1e-7)
    box=shape.BoundingBox()
    assert (box.xmin,box.xmax,box.ymin,box.ymax,box.zmin,box.zmax)==pytest.approx((2.,12.,3.,11.,1.,5.))

def test_principle_reference_records_hash_without_reusing_shape(tmp_path):
    data=first_principles_recipe()
    data['design_basis']['kind']='reference_informed'
    data['reference_uses']=[{
        'function_id':'Mount','use':'principle_reference','uid':'0032/00329619',
        'evidence_digest':'a'*64,'cad_sha256':'b'*64,
        'application':'Adopt only the flanged load-path principle; generate a new L profile.',
    }]
    result=execute_recipe(data,{},tmp_path/'build')
    assert result['reference_uses'][0]['use']=='principle_reference'
    assert result['reference_uses'][0]['cad_sha256']=='b'*64
    assert result['references']==[]


def test_principle_reference_real_catalog_build_preserves_source_without_import(tmp_path,monkeypatch):
    """Hand-authored recipe, real public CAD and worker; no model-quality claim."""
    import cadquery as cq
    from cadmcp_brain.api import Tools
    from cadmcp_brain.engine import Brain
    from cadmcp_brain.req2cad.common import file_hash,json_load
    from scripts.demo_real_references import init_cases

    # Register the original env state even when absent: init_cases sets it directly.
    monkeypatch.setenv('CADMCP_REQ2CAD_ROOT',str(tmp_path/'isolated-catalog'))
    _,catalog,measured,_=init_cases(tmp_path/'reference-workspace')
    monkeypatch.setenv('CADMCP_REQ2CAD_ROOT',str(catalog.root))
    evidence=measured['0032/00329619']
    source=Path(evidence['geometry']['exports']['model.step']['absolute_path'])
    before=file_hash(source)
    tools=Tools(Brain(tmp_path/'design-workspace'))
    tools.brain_open('principle-only',REQUEST)
    data=first_principles_recipe();data['design_basis']['kind']='reference_informed'
    data['reference_uses']=[{
        'function_id':'Mount','use':'principle_reference','uid':evidence['uid'],
        'evidence_digest':evidence['evidence_digest'],'cad_sha256':before,
        'application':'Use the support load-path principle only; author the requested L profile instead of copying the cylindrical guide.',
    }]
    result=tools.brain_studio_build('principle-only',0,data,timeout_seconds=90)
    assert result['geometry_checks_verdict']=='pass'
    record=json_load(Path(result['folder'])/'build-record.json')
    assert record['context']['reference_digests']=={evidence['uid']:evidence['evidence_digest']}
    assert record['measurements']['references']==[]
    assert record['measurements']['reference_uses'][0]['cad_sha256']==before
    page=Path(result['report_html']).read_text(encoding='utf-8')
    assert '原理の参考（形状流用を意味しない）' in page
    assert data['reference_uses'][0]['application'] in page
    assert before in page
    assert file_hash(source)==before
    generated=cq.importers.importStep(result['assembly_step']).val()
    assert len(generated.Solids())==1
    assert generated.Volume()==pytest.approx(256.,rel=1e-7)
    expected=cq.Workplane('XY').polyline(data['operations'][0]['points_mm']).close().extrude(4).val().translate((2,3,1))
    assert generated.cut(expected).Volume()+expected.cut(generated).Volume()<1e-7
    source_shape=cq.importers.importStep(str(source)).val()
    assert generated.cut(source_shape).Volume()+source_shape.cut(generated).Volume()>1e-4
    # A stale reference claim must not be accepted merely because it is not imported.
    data['reference_uses'][0]['cad_sha256']='0'*64
    with pytest.raises(BrainError,match='Reference use must match'):
        tools.brain_studio_build('principle-only',0,data,timeout_seconds=90)

@pytest.mark.parametrize('missing',['basis','plan'])
def test_new_shape_requires_explicit_basis_plan_and_unknown(missing):
    data=first_principles_recipe()
    if missing=='basis':data.pop('design_basis')
    else:data.pop('verification_plan')
    with pytest.raises(ValidationError):Recipe.model_validate(data)

def test_reference_use_is_not_a_nominal_attachment():
    data=first_principles_recipe()
    data['reference_uses']=[{
        'function_id':'Mount','use':'direct_reuse','uid':'0032/00329619',
        'evidence_digest':'a'*64,'cad_sha256':'b'*64,
        'application':'Claim direct reuse without importing matching geometry.',
    }]
    with pytest.raises(ValidationError,match='matching imported reference'):
        Recipe.model_validate(data)

def test_fit_reference_requires_faces():
    data=first_principles_recipe()
    data['reference_uses']=[{
        'function_id':'Mount','use':'fit_reference','uid':'0032/00329619',
        'evidence_digest':'a'*64,'cad_sha256':'b'*64,
        'application':'Use a measured interface to constrain the new profile.',
    }]
    with pytest.raises(ValidationError,match='measured faces'):
        Recipe.model_validate(data)

@pytest.mark.parametrize('mutation',['unknown_op','self_intersection','unbounded'])
def test_polygon_operation_rejects_unsupported_or_invalid_profiles(mutation):
    data=first_principles_recipe();node=data['operations'][0]
    if mutation=='unknown_op':node['op']='loft'
    elif mutation=='self_intersection':node['points_mm']=[[0.,0.],[4.,4.],[0.,4.],[4.,0.]]
    else:node['points_mm'][0]=[1_000_001.,0.]
    with pytest.raises(ValidationError):Recipe.model_validate(data)

def test_matrix_accepts_first_principles_and_keeps_required_feature_unknown():
    matrix={'brief':brief(),'options':[option('PlateA',first_basis('A')),option('PlateB',first_basis('B'))]}
    result=synthesize(Matrix.model_validate(matrix),NoCatalogService())
    assert len(result['candidates'])==2 and result['grounded_reference_count']==0
    assert not result['insufficient_diversity']
    assert all(c['options'][0]['design_basis']['kind']=='first_principles' for c in result['candidates'])
    assert all(any('strength and fastening remain unknown' in u for u in c['unresolved']) for c in result['candidates'])

def test_matrix_represents_provided_cad_without_claiming_req2cad_faces():
    provided={'kind':'provided_cad','artifact_id':'OwnerBracket','sha256':'c'*64,
              'application':'Use the owner-provided mounting envelope as a later measured constraint.',
              'verification_plan':['Register and hash-check the STEP, then inspect the required faces.'],
              'unknowns':['Provided CAD faces and units have not yet been inspected.']}
    matrix={'brief':brief(),'options':[option('ProvidedA',provided),option('FreshB',first_basis('B'))]}
    result=synthesize(matrix,NoCatalogService())
    candidate=next(c for c in result['candidates'] if c['options'][0]['id']=='ProvidedA')
    assert candidate['options'][0]['design_basis']['sha256']=='c'*64
    assert candidate['source_digests']=={}

def test_matrix_without_reference_or_design_basis_is_rejected():
    raw=option('Unsupported',first_basis('X'));raw.pop('design_basis')
    with pytest.raises(ValidationError,match='without Req2CAD references'):
        Matrix.model_validate({'brief':brief(),'options':[raw,option('FreshB',first_basis('B'))]})

def test_catalog_reference_still_requires_current_digest_and_faces():
    ref={'uid':'0032/00329619','evidence_digest':'a'*64,'used_face_ids':['F7'],
         'adopted_principle':'Use a measured planar support relationship.',
         'adaptations':['Generate new dimensions from owner requirements.']}
    raw=option('CatalogA',first_basis('unused'));raw['references']=[ref];raw['design_basis']=None
    raw2=dict(raw);raw2={**raw,'id':'CatalogB','name':'CatalogB'}
    class Stale:
        def evidence(self,uid):return {'geometry':{},'evidence_digest':'d'*64}
    with pytest.raises(BrainError,match='inspect every referenced CAD'):
        synthesize({'brief':brief(),'options':[raw,raw2]},Stale())
