"""New structural pipeline tests. Public four-case tests are NOT a full-corpus benchmark.

Scripted model responses below test orchestration/guards, NOT actual Codex/Qwen
reasoning. The kernel is real for builds, collisions, surfaces and exports.
"""
import copy,io,json,os,sys,tarfile,hashlib,subprocess
from pathlib import Path
import pytest
import importlib.util
pytestmark=pytest.mark.skipif(importlib.util.find_spec("cadquery") is None,reason="Actual CAD kernel not installed; Studio geometry/orchestration tests not claimed executed.")
import jsonschema
from pydantic import ValidationError
from cadmcp_brain.errors import BrainError
from cadmcp_brain.engine import Brain
from cadmcp_brain.api import Tools
from cadmcp_brain.req2cad.common import file_hash
from cadmcp_brain.req2cad.assets import prepare_cad_archive
from cadmcp_brain.req2cad.geometry import reconstruct,shape_features,classify_profile_wires
from cadmcp_brain.studio.recipe import Recipe,execute_recipe
from cadmcp_brain.studio.synthesis import Matrix,FunctionBrief,synthesize
from cadmcp_brain.studio.runtime import ROLES,Review
from cadmcp_brain.studio.provider import bounded_process,resolve_codex
from cadmcp_brain.studio.wire import output_schema,decode,map_value_schema
from cadmcp_brain.studio.autopilot import Autopilot
from scripts.demo_real_references import init_cases,demo_recipe,REQUEST
ROOT=Path(__file__).resolve().parents[1]
PUBLIC=ROOT/'examples'/'public-cases'

@pytest.fixture(scope='module')
def actual(tmp_path_factory):
    old=os.environ.get('CADMCP_REQ2CAD_ROOT')
    root=tmp_path_factory.mktemp('public-studio')/'workspace'
    value=init_cases(root)
    yield value
    if old is None:os.environ.pop('CADMCP_REQ2CAD_ROOT',None)
    else:os.environ['CADMCP_REQ2CAD_ROOT']=old

@pytest.fixture
def local(actual,tmp_path,monkeypatch):
    _,kb,measured,_=actual
    monkeypatch.setenv('CADMCP_REQ2CAD_ROOT',str(kb.root))
    tools=Tools(Brain(tmp_path/'project-workspace'));tools.brain_open('public-test',REQUEST)
    return tools,measured

def brief():
    return {'original_request':REQUEST,'functions':[{
        'id':'Guide','source_excerpt':'軸案内部品','function':'guide shaft','behavior':'Constrain the shaft radially with a cylindrical cavity surface.',
        'queries':['support rotation','guide rotating shafts'],'required_features':['has_cylindrical_cavity_surface']}],
        'protected_constraints':[],'unresolved':['Physical printing and source unit calibration remain unknown.']}

def matrix(measured):
    b=brief();e=measured['0032/00329619']
    face=next(p['face_id'] for p in e['geometry']['interfaces']['ports'] if p['port_kind']=='inner_cylinder')
    def option(i,method):
        return {'id':i,'name':i,'covers':['Guide'],'mechanism_principle':'Use a cylindrical guide surface with a flange to transfer the reaction to the mount.',
          'references':[{'uid':e['uid'],'evidence_digest':e['evidence_digest'],'used_face_ids':[face],
                         'adopted_principle':'Reuse cylindrical constraint and flanged support relationship, not original dimensions.',
                         'adaptations':['Select bore diameter from measured user shaft; proposed dimensions are not measured hardware.']}],
          'proposed_parts':['guide'],'force_path':'Shaft reaction passes through the sleeve wall to its mounting flange.',
          'assembly_method':method,'risks':['Nominal reference structure does not prove fit, wear or stiffness.']}
    return {'brief':b,'options':[option('AxialInsert','Insert the shaft axially through the proposed bore.'),
                               option('SplitAssembly','Rebuild as separable guide halves; separation and fastening remain design work.')],
            'incompatibilities':[]}

def review(subject,role,conclusion='no_blocker_found',attachments=()):
    return {'subject_digest':subject,'role':role,'reviewer_label':'SCRIPTED TEST RESPONSE',
        'execution_description':'Controlled fixture, not an independent LLM or human review.',
        'findings':[],'remaining_uncertainties':['Physical performance remains unverified.'],'conclusion':conclusion,
        'evidence_inspections':[{'attachment_path':a['path'],'attachment_sha256':a['sha256'],'kind':a['kind'],'status':'viewed',
                                 'observation':'SCRIPTED TEST evidence receipt, not actual model visual inspection.'} for a in attachments]}

@pytest.mark.parametrize('uid',['0032/00329619','0032/00325917','0032/00321991','0032/00325799'])
def test_public_source_git_identity_and_valid_brep(actual,uid):
    _,_,m,checks=actual
    assert next(c for c in checks if c['uid']==uid)['git_blob_verified']
    g=m[uid]['geometry'];assert g['valid'] and g['solids']==1
    assert g['dimensional_status']=='reference_coordinates_only'
    assert g['exports']['model.step']['sha256']

def test_cup_has_measured_cavity_while_rods_do_not(actual):
    m=actual[2]
    assert m['0032/00329619']['geometry']['interfaces']['capabilities']['has_cylindrical_cavity_surface']
    for uid in ['0032/00325917','0032/00321991','0032/00325799']:
        assert not m[uid]['geometry']['interfaces']['capabilities']['has_cylindrical_cavity_surface']

def test_raw_incorrect_outer_flags_recovered_and_recorded():
    raw=json.loads((PUBLIC/'cad_json/0032/00329619.json').read_text())
    shape,metadata=reconstruct(raw,1000.)
    assert shape.isValid()
    assert any(i['flag_disagreements'] for i in metadata['loop_inference'])
    assert sum(s.Volume() for s in shape.Solids())==pytest.approx(24892.605740259576,rel=1e-7)

def test_nested_holes_and_island():
    import cadquery as cq
    wires=[cq.Wire.makeCircle(r,(0,0,0),(0,0,1)) for r in [10,6,2]]
    groups,record=classify_profile_wires(wires,[True]*3)
    assert record['loop_depths']==[0,1,2] and len(groups)==2
    assert record['flag_disagreements']==[1]

def test_touching_profile_refused():
    import cadquery as cq
    wires=[cq.Wire.makeCircle(2,(0,0,0),(0,0,1)),cq.Wire.makeCircle(1,(1,0,0),(0,0,1))]
    with pytest.raises(BrainError):classify_profile_wires(wires,[True,True])

def test_taper_not_replaced_by_straight_extrusion():
    raw=json.loads((PUBLIC/'cad_json/0032/00321991.json').read_text())
    for e in raw['entities'].values():
        if e['type']=='ExtrudeFeature':e['extent_one']['taper_angle']['value']=.1
    with pytest.raises(BrainError,match='taper'):reconstruct(raw,1000.)

def tar_bytes(entries,gz=False):
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w:gz' if gz else 'w') as tar:
        for name,value in entries:
            member=tarfile.TarInfo(name);member.size=len(value);tar.addfile(member,io.BytesIO(value))
    return stream.getvalue()

def test_nested_compressed_real_cad_archive(tmp_path):
    raw=(PUBLIC/'cad_json/0032/00321991.json').read_bytes()
    inner=tar_bytes([('cad_json/0032/00321991.json',raw)],gz=True)
    outer=tmp_path/'data.tar';outer.write_bytes(tar_bytes([('cad_json.tar.gz',inner)]))
    normalized,receipt=prepare_cad_archive(outer,tmp_path/'cache')
    assert receipt['nested_archives']==1 and receipt['json_members']==1
    with tarfile.open(normalized,'r:') as tar:assert tar.extractfile('cad_json/0032/00321991.json').read()==raw
    assert prepare_cad_archive(outer,tmp_path/'cache')[0]==normalized

@pytest.mark.parametrize('bad',['../cad_json/0032/00321991.json','/cad_json/0032/00321991.json','C:/cad_json/0032/00321991.json','cad_json\\0032\\00321991.json'])
def test_archive_bad_paths_never_extracted(tmp_path,bad):
    path=tmp_path/'bad.tar';path.write_bytes(tar_bytes([(bad,b'{}')]))
    with pytest.raises(BrainError):prepare_cad_archive(path,tmp_path/'cache')
    assert not list((tmp_path/'cache').glob('*.tar'))

def test_archive_duplicate_budget_and_empty_errors(tmp_path):
    good='cad_json/0032/00321991.json'
    for label,entries,budget in [('duplicate',[(good,b'{}'),(good,b'{}')],1000),('budget',[(good,b'{}')],1),('empty',[('readme.txt',b'ok')],1000)]:
        path=tmp_path/(label+'.tar');path.write_bytes(tar_bytes(entries))
        with pytest.raises(BrainError):prepare_cad_archive(path,tmp_path/label,max_expanded_bytes=budget)

def test_grouped_lexical_retrieval_geometry_rejects_solid_shaft(local):
    t,_=local;r=t.brain_fs_search_tasks(brief(),mode='lexical')
    rows=r['functions'][0]['candidates'];assert rows
    assert rows[0]['uid']=='0032/00329619' and rows[0]['feature_screen']['verdict']=='pass'
    rods=[r for r in rows if r['uid']=='0032/00321991'];assert rods and rods[0]['feature_screen']['verdict']=='fail'

def test_source_quote_and_paraphrase_validation():
    b=brief();b['functions'][0]['source_excerpt']='not present in original request'
    with pytest.raises(ValidationError):FunctionBrief.model_validate(b)
    b=brief();b['functions'][0]['queries']=['guide shaft',' Guide  Shaft ']
    with pytest.raises(ValidationError):FunctionBrief.model_validate(b)

def test_morphological_covers_actual_reference_faces(local):
    t,m=local;r=t.brain_studio_synthesize('public-test',0,matrix(m))
    assert len(r['candidates'])==2 and not r['insufficient_diversity']
    assert all(c['function_coverage']['Guide'] for c in r['candidates'])

def test_citing_plane_as_bore_is_rejected(local):
    t,m=local;data=matrix(m)
    plane=next(p['face_id'] for p in m['0032/00329619']['geometry']['interfaces']['ports'] if p['port_kind']=='planar_surface')
    for o in data['options']:o['references'][0]['used_face_ids']=[plane]
    result=t.brain_studio_synthesize('public-test',0,data)
    assert not result['candidates'] and len(result['rejected_options'])==2

def test_stale_or_invented_reference_faces(local):
    t,m=local;data=matrix(m);data['options'][0]['references'][0]['used_face_ids']=['F99999']
    with pytest.raises(BrainError):t.brain_studio_synthesize('public-test',0,data)
    data=matrix(m);data['options'][0]['references'][0]['evidence_digest']='0'*64
    with pytest.raises(BrainError):t.brain_studio_synthesize('public-test',0,data)

@pytest.mark.parametrize('mutation',['nan','zero_axis','forward_reference','duplicate_id','orphan','missing_basis','no_unknowns'])
def test_recipe_contract_negative_controls(actual,mutation):
    r=demo_recipe(actual[2])
    if mutation=='nan':r['operations'][1]['radius_mm']=float('nan')
    elif mutation=='zero_axis':r['operations'][1]['axis']=[0.,0.,0.]
    elif mutation=='forward_reference':r['operations'][2]['operands'][0]='finished_guide'
    elif mutation=='duplicate_id':r['operations'][1]['id']=r['operations'][0]['id']
    elif mutation=='orphan':r['operations'].append({'id':'unused','op':'box','function_id':'Mount','reason':'Orphan geometry is not allowed.','size_mm':[1.,1.,1.],'center_mm':[0.,0.,0.]})
    elif mutation=='missing_basis':r['parameter_basis'].pop('shaft_diameter')
    else:r['unverified_requirements']=[]
    with pytest.raises(ValidationError):Recipe.model_validate(r)

def test_protected_hardware_cannot_move_or_be_boolean_target(actual):
    r=demo_recipe(actual[2]);r['operations'][-2]={'id':'shaft_ref','op':'project_step','function_id':'Move','reason':'Use an existing protected hardware object.','artifact_id':'PCB','sha256':'0'*64,'role':'protected_hardware','unit_basis':'Measured export in millimeters.'}
    with pytest.raises(ValidationError):Recipe.model_validate(r)

def test_actual_recipe_export_and_gap(local):
    t,m=local;r=t.brain_studio_build('public-test',0,demo_recipe(m),180)
    assert r['geometry_checks_verdict']=='pass' and r['overall_verdict']=='unknown'
    gap=next(c for c in r['checks'] if c['kind']=='static_clearance')
    assert gap['distance_mm']==pytest.approx(.15,abs=1e-7) and gap['overlap_mm3']==0
    assert Path(r['assembly_step']).is_file() and Path(r['report_html']).is_file()
    motion=next(c for c in r['checks'] if c['kind']=='sampled_translation_clearance')
    assert len(motion['samples'])==41 and motion['continuous_swept_motion']=='distance_bound_satisfied_under_stated_assumptions'
    assert motion['continuous_distance_lower_bound_mm']>=.14

def test_delivery_keeps_geometry_review_and_physical_states_separate(local):
    t,m=local;built=t.brain_studio_build('public-test',0,demo_recipe(m),180)
    delivery=t.brain_studio_delivery('public-test',0,built['subject_digest'])
    manifest=json.loads(Path(delivery['delivery_json']).read_text('utf-8'))
    assert manifest['states']=={'geometry':'pass','review':'not_accepted','physical_performance':'unknown','overall':'unknown'}
    assert manifest['bom']['status']=='not_created' and manifest['physical_performance_certified'] is False
    assert set(manifest['parts'])=={'guide','shaft'} and Path(manifest['assembly_step']['path']).is_file()

def test_actual_motion_collision_detected(local):
    t,m=local;r=demo_recipe(m);r['motion_checks'][0]['translation_end_mm']=[1.,0.,0.]
    built=t.brain_studio_build('public-test',0,r,180)
    assert built['geometry_checks_verdict']=='fail'
    motion=next(c for c in built['checks'] if c['kind']=='sampled_translation_clearance')
    assert any(s['overlap_mm3']>0 for s in motion['samples'])

def test_review_revision_hash_and_no_majority_override(local):
    t,m=local;built=t.brain_studio_build('public-test',0,demo_recipe(m),180);subject=built['subject_digest']
    attachments=t.brain_studio_review_packet('public-test',0,subject,'verification')['subject']['payload']['evidence_attachments']
    first=[t.brain_studio_submit_review('public-test',0,subject,review(subject,role,attachments=attachments)) for role in ROLES]
    assert not t.brain_studio_review_status('public-test',0,subject)['discussion_ready_for_owner']
    for role in ROLES:
        second=review(subject,role,attachments=attachments);second['discussion_round']=2;second['challenged_review_ids']=[x['review_id'] for x in first]
        t.brain_studio_submit_review('public-test',0,subject,second)
    assert t.brain_studio_review_status('public-test',0,subject)['discussion_ready_for_owner']
    new=review(subject,'assembly','revise');new['findings']=[{'id':'Blocked','severity':'blocking','claim':'The actual retention method is not yet validated.','evidence':['unverified_requirements in the build result'],'proposed_change':'Design and inspect the axial retention method.','required_test':'Measure both assembly and removal paths with the chosen retainers.'}]
    receipt=t.brain_studio_submit_review('public-test',0,subject,new)
    assert not t.brain_studio_review_status('public-test',0,subject)['discussion_ready_for_owner']
    reply={'review_id':receipt['review_id'],'finding_id':'Blocked','responder_label':'Fixture rebuttal','disposition':'disagree_with_evidence','explanation':'A disagreement does not replace the required test.','evidence':['No physical test result exists.']}
    assert not t.brain_studio_reply('public-test',0,subject,reply)['blocker_automatically_cleared']
    t.brain.add_source('public-test',0,'A new owner requirement invalidates old reviews.')
    with pytest.raises(BrainError):t.brain_studio_review_status('public-test',1,subject)

def test_two_identical_builds_are_separate_review_attempts(local):
    t,m=local;r=demo_recipe(m)
    a=t.brain_studio_build('public-test',0,r,180);b=t.brain_studio_build('public-test',0,r,180)
    assert a['subject_digest']!=b['subject_digest']

def test_recipe_request_must_match_owner(local):
    t,m=local;r=demo_recipe(m);r['original_request']='Make something else instead.'
    with pytest.raises(BrainError):t.brain_studio_build('public-test',0,r,180)

def test_review_revise_without_blocker_still_prevents_completion(local):
    t,m=local;b=t.brain_studio_build('public-test',0,demo_recipe(m),180);s=b['subject_digest']
    for role in ROLES:t.brain_studio_submit_review('public-test',0,s,review(s,role,'revise' if role=='manufacturing' else 'no_blocker_found'))
    status=t.brain_studio_review_status('public-test',0,s)
    assert status['revision_requested_roles']==['manufacturing'] and not status['discussion_ready_for_owner']

def wire_encode(value,schema,root=None):
    root=root or schema
    if '$ref' in schema:return wire_encode(value,root['$defs'][schema['$ref'].split('/')[-1]],root)
    choices=schema.get('anyOf',schema.get('oneOf'))
    if choices:
        for s in choices:
            if jsonschema.Draft202012Validator({'$defs':root.get('$defs',{}),**s}).is_valid(value):return wire_encode(value,s,root)
        raise AssertionError('Fixture has no schema choice.')
    if schema.get('type')=='object':
        if 'properties' not in schema and map_value_schema(schema)[0] is not None:return [{'key':k,'value':wire_encode(v,map_value_schema(schema)[0],root)} for k,v in value.items()]
        return {k:wire_encode(v,schema['properties'][k],root) for k,v in value.items()}
    if schema.get('type')=='array':return [wire_encode(v,schema['items'],root) for v in value]
    return value

def test_closed_model_wire_schema_roundtrip(actual):
    native=Recipe.model_validate(demo_recipe(actual[2])).model_dump();schema=Recipe.model_json_schema()
    wire=wire_encode(native,schema);jsonschema.validate(wire,output_schema(schema))
    assert decode(wire,schema)==native
    def check(node):
        if isinstance(node,dict):
            if node.get('type')=='object':assert node.get('additionalProperties') is False
            for v in node.values():check(v)
        if isinstance(node,list):
            for v in node:check(v)
    check(output_schema(schema))

def test_wire_duplicate_map_keys_refused():
    s={'type':'object','additionalProperties':{'type':'number'}}
    with pytest.raises(ValueError):decode([{'key':'a','value':1},{'key':'a','value':2}],s)

def test_external_agent_missing_and_explicit_authorization(tmp_path):
    with pytest.raises(BrainError):resolve_codex('codex-that-is-not-installed-0099')
    proc=subprocess.run([sys.executable,'-m','cadmcp_brain.studio','--workspace',str(tmp_path),'autopilot','--project','x'],capture_output=True,text=True)
    assert proc.returncode!=0 and '--execute-model' in proc.stderr

@pytest.mark.parametrize('mode',['normal','timeout','oversized'])
def test_external_process_budgets(tmp_path,mode):
    inp=tmp_path/'in';inp.write_text('fixture')
    code={'normal':'print("test fixture")','timeout':'import time;time.sleep(10)','oversized':'print("x"*20000)'}[mode]
    call=lambda:bounded_process([sys.executable,'-c',code],inp,tmp_path/'out',tmp_path/'err',cwd=tmp_path,timeout=(.3 if mode=='timeout' else 5),max_log_bytes=1000)
    if mode=='normal':assert call()['returncode']==0
    else:
        with pytest.raises(BrainError):call()

class ScriptedOrchestrationFixture:
    """Deliberately scripted test provider, never shipped as an agent fallback."""
    def __init__(self,measured,break_first=False,weaken_repair=False):
        self.measured=measured;self.calls=[];self.contexts=[];self.break_first=break_first;self.weaken_repair=weaken_repair
    def generate(self,task,schema,context,*,role):
        self.calls.append(role);self.contexts.append(context)
        if 'subject_digest' in schema.get('properties',{}):
            value=review(context['subject_digest'],role,attachments=context['subject']['payload'].get('evidence_attachments',[]));value['discussion_round']=context.get('discussion_round',1);value['challenged_review_ids']=context.get('required_challenged_review_ids',[]);return value
        if role=='requirements':return brief()
        if role=='mechanism':
            data=matrix(self.measured);data.pop('brief')
            rod=self.measured['0032/00321991']
            for option in data['options']:
                option['references'].append({'uid':rod['uid'],'evidence_digest':rod['evidence_digest'],
                    'used_face_ids':[rod['geometry']['interfaces']['ports'][0]['face_id']],
                    'adopted_principle':'A separate solid shaft supplies the moving cylindrical mate.',
                    'adaptations':['Explicit scale to a proposed prototype shaft diameter.']})
            return data
        if role=='mechanical_selector':return {'candidate_index':0,'reason':'SCRIPTED TEST selection, not a model judgment.','remaining_risks':['Physical fit remains unqualified.']}
        result=demo_recipe(self.measured)
        if role=='geometric_architect' and self.break_first:
            next(n for n in result['operations'] if n['id']=='shaft_bore')['radius_mm']=1.3
        if role=='repair' and self.weaken_repair:result['dimension_checks'][0]['tolerance_mm']=10.
        return result

def test_full_orchestration_with_real_cad_and_scripted_provider(local,tmp_path):
    t,m=local;provider=ScriptedOrchestrationFixture(m)
    run=Autopilot(t,provider,tmp_path/'calls',search_mode='lexical',max_repairs=0,debate_rounds=2)
    result=run.run('public-test')
    assert result['phase']=='prototype_ready_for_owner_review'
    assert result['physical_performance_certified'] is False and result['overall_verdict']=='unknown'
    assert len(provider.calls)==14 and set(provider.calls[-5:])==set(ROLES)
    assert result['model_provider']=='ScriptedOrchestrationFixture'

def test_orchestrator_repairs_geometry_not_checks(local,tmp_path):
    t,m=local;provider=ScriptedOrchestrationFixture(m,break_first=True)
    result=Autopilot(t,provider,tmp_path/'calls',search_mode='lexical',max_repairs=1,debate_rounds=2).run('public-test')
    assert result['phase']=='prototype_ready_for_owner_review' and result['attempt']==1
    # Four orchestration calls, 5 roles x 2 rounds on both the failed and
    # repaired subjects, plus one repair call.
    assert 'repair' in provider.calls and len(provider.calls)==25

def test_orchestrator_refuses_weakened_repair_condition(local,tmp_path):
    t,m=local;provider=ScriptedOrchestrationFixture(m,break_first=True,weaken_repair=True)
    with pytest.raises(BrainError) as exc:Autopilot(t,provider,tmp_path/'calls',search_mode='lexical',max_repairs=1,debate_rounds=1).run('public-test')
    assert exc.value.code=='AUTOPILOT_WEAKENED_CHECK'
    assert json.loads((tmp_path/'calls/run-state.json').read_text(encoding='utf-8'))['phase']=='stopped_with_evidence'

def test_dimension_mismatch_is_not_overall_pass(local):
    t,m=local;r=demo_recipe(m);r['dimension_checks'][0]['nominal_mm']=23.
    built=t.brain_studio_build('public-test',0,r,180)
    assert next(c for c in built['checks'] if c['id']=='guide_width')['verdict']=='fail'
    assert built['geometry_checks_verdict']=='fail'

def test_continuous_clearance_bound_can_remain_unproven(local):
    t,m=local;r=demo_recipe(m);r['motion_checks'][0]['max_samples']=11
    built=t.brain_studio_build('public-test',0,r,180)
    motion=next(c for c in built['checks'] if c['kind']=='sampled_translation_clearance')
    assert motion['verdict']=='pass' and motion['continuous_swept_motion']=='not_proven'
    assert motion['continuous_distance_lower_bound_mm']<.14

def test_peer_challenge_round_with_scripted_responses(local,tmp_path):
    t,m=local;provider=ScriptedOrchestrationFixture(m)
    result=Autopilot(t,provider,tmp_path/'calls',search_mode='lexical',max_repairs=0,debate_rounds=2).run('public-test')
    assert result['phase']=='prototype_ready_for_owner_review' and len(provider.calls)==14
    contexts=provider.contexts[-5:]
    assert all(c['discussion_round']==2 and len(c['peer_findings'])==5 for c in contexts)
    assert result['review_status']['independence_verified'] is False

def test_owner_hardware_cannot_be_omitted(local,monkeypatch):
    t,m=local;monkeypatch.setenv('CADMCP_PROTECTED_ARTIFACT_IDS','["PCB"]')
    with pytest.raises(BrainError) as exc:t.brain_studio_build('public-test',0,demo_recipe(m),180)
    assert exc.value.code=='STUDIO_PROTECTED'

def test_original_input_source_and_build_files_are_immutable(local):
    t,m=local;b=t.brain_studio_build('public-test',0,demo_recipe(m),180)
    Path(b['assembly_step']).write_text('modified after verification',encoding='utf-8')
    with pytest.raises(BrainError):t.brain_studio_review_status('public-test',0,b['subject_digest'])

def test_grouped_dense_search_counts_one_function_not_paraphrases(tmp_path):
    import csv,numpy as np
    from cadmcp_brain.req2cad.catalog import Catalog
    from cadmcp_brain.req2cad.semantic import SemanticIndex
    p=tmp_path/'synthetic.csv'
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['uid','function_keywords','function_description']);w.writeheader()
        w.writerows([{'uid':'9000/90000001','function_keywords':"['support shaft']",'function_description':'Controlled numerical fixture; not public Req2CAD.'},
                     {'uid':'9000/90000002','function_keywords':"['stop motion']",'function_description':'Controlled numerical fixture; not public Req2CAD.'}])
    c=Catalog(tmp_path/'kb');c.ingest(p,source_url='fixture://controlled-grouped-embeddings')
    class Encoder:
        identity={'provider':'controlled vectors; NOT a language model'}
        def encode(self,words,query=False):return np.array([[0.,1.] if 'stop' in x else [1.,0.] for x in words])
    index=SemanticIndex(c);enc=Encoder();index.build(enc)
    r=index.search_groups([{'id':'Guide','queries':['support shaft','guide rod']},{'id':'Stop','queries':['stop motion']}],enc,require_asset=False)
    assert r['index_scans']==1 and r['encoded_query_count']==3
    assert r['groups']['Guide']['results'][0]['matched_function_count']==1
    assert r['groups']['Guide']['results'][0]['uid']=='9000/90000001'

def test_png_is_real_raster_not_placeholder(actual):
    from PIL import Image
    import numpy as np
    path=actual[2]['0032/00329619']['geometry']['exports']['iso.png']['absolute_path']
    image=np.asarray(Image.open(path).convert('RGB'))
    assert image.shape==(600,800,3)
    assert np.mean(np.any(image<200,axis=2))>.2

def test_fusion_handoff_sha_and_remeasure(local):
    t,m=local;built=t.brain_studio_build('public-test',0,demo_recipe(m),180)
    issued=t.brain_fusion_handoff('public-test',0,built['subject_digest'])
    assert issued['allow_save'] is False and issued['adapter_sha256']
    with pytest.raises(BrainError) as exc:
        t.brain_fusion_ingest('public-test',0,built['subject_digest'],'0'*64,{
            'adapter_version':'1','handoff_digest':issued['handoff_digest'],'saved':False,'units':'mm',
            'occurrences':[{'occurrence':'guide','translation_mm':[0.,0.,0.]},{'occurrence':'shaft','translation_mm':[0.,0.,0.]}]})
    assert exc.value.code=='FUSION_ADAPTER'
    ok=t.brain_fusion_ingest('public-test',0,built['subject_digest'],issued['adapter_sha256'],{
        'adapter_version':'1','handoff_digest':issued['handoff_digest'],'saved':False,'units':'mm',
        'occurrences':[{'occurrence':'guide','translation_mm':[0.,0.,0.]},{'occurrence':'shaft','translation_mm':[0.,0.,0.]}]})
    assert ok['geometry_checks_verdict']=='pass' and ok['f3d_saved'] is False
    moved=t.brain_fusion_ingest('public-test',0,built['subject_digest'],issued['adapter_sha256'],{
        'adapter_version':'1','handoff_digest':issued['handoff_digest'],'saved':False,'units':'mm',
        'occurrences':[{'occurrence':'guide','translation_mm':[0.,0.,0.]},{'occurrence':'shaft','translation_mm':[8.,0.,0.]}]})
    assert moved['geometry_checks_verdict']=='fail'


def test_registered_owner_protected_step_stays_fixed(local,tmp_path,monkeypatch):
    import cadquery as cq
    t,m=local;root=t.brain.store.root;incoming=root/'incoming';incoming.mkdir()
    source=incoming/'hardware.step'
    cq.exporters.export(cq.Workplane('XY').box(2,2,2).val().translate((100,0,0)),str(source))
    t.brain_import_step('public-test',0,'PCB','incoming/hardware.step',purpose='reference')
    artifact=t.brain.store.get('public-test').artifacts['PCB']
    monkeypatch.setenv('CADMCP_PROTECTED_ARTIFACT_IDS','["PCB"]')
    r=demo_recipe(m);r['functions']['Hardware']='Keep this authored hardware fixture fixed; it is not an actual mouse PCB.'
    r['operations'].append({'id':'fixed_hardware','op':'project_step','function_id':'Hardware','reason':'Preserve the source hardware pose and shape.','artifact_id':'PCB','sha256':artifact.sha256,'role':'protected_hardware','unit_basis':'Authored test fixture in millimeters; not physical user hardware.'})
    r['outputs'].append({'part_id':'hardware','node':'fixed_hardware','expected_solids':1})
    b=t.brain_studio_build('public-test',1,r,180)
    exported=cq.importers.importStep(str(Path(b['folder'])/'hardware/model.step')).val().BoundingBox()
    assert exported.xmin==pytest.approx(99.) and exported.xmax==pytest.approx(101.)
    assert file_hash(root/artifact.filename)==artifact.sha256
