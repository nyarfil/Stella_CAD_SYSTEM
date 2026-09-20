"""Deterministic software tests, NOT pretrained-model/design-quality benchmarks."""
import copy,csv,hashlib,io,json,math,os,subprocess,sys,tarfile
from pathlib import Path
import numpy as np
import pytest
import importlib.util
requires_cad=pytest.mark.skipif(importlib.util.find_spec("cadquery") is None,reason="Optional CadQuery kernel not installed; no geometry success claimed")
from cadmcp_brain.errors import BrainError
from cadmcp_brain.req2cad.catalog import Catalog,parse_keywords
from cadmcp_brain.req2cad.common import digest,file_hash,atomic_json,write_lock,uid
from cadmcp_brain.req2cad.semantic import SemanticIndex
from cadmcp_brain.req2cad.assets import attach_directory,attach_tar,read_asset,file_uid
from cadmcp_brain.req2cad.geometry import reconstruct,shape_features,wl_features,wl_similarity,compare_records
from cadmcp_brain.req2cad.service import Service


def csv_file(path,rows):
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['uid','function_keywords','function_description']);w.writeheader();w.writerows(rows)
    return path

@pytest.fixture
def fs(tmp_path):
    rows=[{'uid':'9000/90000001','function_keywords':"['support rotating shaft', 'reduce friction']",'function_description':'SYNTHETIC annotation for tests, not a Req2CAD example.'},
          {'uid':'9000/90000002','function_keywords':"['support rotating shaft', 'transmit motion']",'function_description':'SYNTHETIC second component.'},
          {'uid':'9000/90000003','function_keywords':"[]",'function_description':'SYNTHETIC indeterminate component.'}]
    c=Catalog(tmp_path/'kb');c.ingest(csv_file(tmp_path/'data.csv',rows),source_url='fixture://authored-unit-test')
    return c

# Only test vector/mapping plumbing. Values are deliberately authored, NOT an embedding model.
class FixtureEncoder:
    identity={'model_id':'TEST-ONLY-controlled-vectors','revision':'fixture-v1'}
    def encode(self,texts,query=False):
        table={'support rotating shaft':[1.,0.,0.],'reduce friction':[0.,1.,0.],'transmit motion':[0.,0.,1.],
               'shaft support':[1.,0.,0.],'low friction':[0.,1.,0.]}
        return np.array([table[t] for t in texts])

@pytest.mark.parametrize('raw,expected',[("['a', 'a',' B  C ']",['a','b c']),('[[]]',[]),('["a",["b"]]',['a','b']),('[]',[])])
def test_keyword_formats(raw,expected):assert parse_keywords(raw)==expected

@pytest.mark.parametrize('raw',['{"a":1}',"__import__('os').system('id')",'[1]','[null]','[true]',"['"+'a'*401+"']",'['*10+'"x"'+']'*10])
def test_keyword_reject(raw):
    with pytest.raises((ValueError,SyntaxError)):parse_keywords(raw)

@pytest.mark.parametrize('key',['../etc/passwd','9000/../../x','9000\\90000001','x','9000/90000001.py','9000/90000001\n'])
def test_uid_reject(key):
    with pytest.raises(BrainError):uid(key)

def test_status_actual_counts(fs):
    s=fs.status();assert s['cases']==3 and s['function_labeled_cases']==2 and s['distinct_functions']==3
    assert not s['semantic_ready'] and s['cad_assets_linked']==0
    assert s['meta']['full_original_sha_match'] is False
    assert 'fixture://' in fs.case('9000/90000001')['annotation_origin']

def test_invalid_row_quarantined(fs,tmp_path):
    p=csv_file(tmp_path/'mix.csv',[{'uid':'x','function_keywords':'[]','function_description':'bad'},
        {'uid':'9000/90000001','function_keywords':'["support shaft"]','function_description':'ok'}])
    fs.ingest(p);assert fs.status()['meta']['stats']['rejected_rows']==1

def test_duplicate_conflict_is_atomic(fs,tmp_path):
    old=file_hash(fs.path)
    p=csv_file(tmp_path/'dups.csv',[{'uid':'9000/90000001','function_keywords':'["a"]','function_description':'a'},
        {'uid':'9000/90000001','function_keywords':'["b"]','function_description':'b'}])
    with pytest.raises(BrainError,match='Conflicting'):fs.ingest(p)
    assert file_hash(fs.path)==old

def test_duplicate_identical_count(fs,tmp_path):
    row={'uid':'9000/90000001','function_keywords':'["a"]','function_description':'a'}
    p=csv_file(tmp_path/'dup.csv',[row,row]);fs.ingest(p)
    assert fs.status()['meta']['stats']['duplicate_identical_rows']==1

def test_hash_mismatch_keeps_old(fs,tmp_path):
    old=file_hash(fs.path)
    with pytest.raises(BrainError):fs.ingest(tmp_path/'data.csv',expected_sha256='0'*64)
    assert file_hash(fs.path)==old

def test_owner_lock(fs):
    with write_lock(fs.root):
        with pytest.raises(BrainError,match='being modified'):
            with write_lock(fs.root):pass
    assert not (fs.root/'.write.lock').exists()

def test_lexical_explicit(fs):
    r=fs.lexical(['support rotating shaft','reduce friction'])
    assert r['results'][0]['uid']=='9000/90000001' and r['results'][0]['matched_function_count']==2
    assert r['method'].startswith('lexical')
    assert fs.lexical(['no such function'])['results']==[]
    assert fs.lexical(['support'],require_asset=True)['results']==[]

def test_dense_semantic_aggregation(fs):
    idx=SemanticIndex(fs);m=idx.build(FixtureEncoder(),batch_size=2)
    assert m['rows']==3 and fs.status()['semantic_ready']
    r=idx.search(['shaft support','low friction'],FixtureEncoder(),threshold=0.7)
    assert r['results'][0]['uid']=='9000/90000001'
    assert r['results'][0]['matched_function_count']==2
    assert r['results'][1]['matched_function_count']==1
    assert r['keyword_matches_per_query']==[1,1]
    assert idx.verify()['checksums_verified']

def test_missing_index_not_faked(fs):
    with pytest.raises(BrainError,match='No silent'):SemanticIndex(fs).search(['shaft support'],FixtureEncoder())

def test_wrong_encoder_identity(fs):
    idx=SemanticIndex(fs);idx.build(FixtureEncoder())
    model=FixtureEncoder();model.identity={'model_id':'different'}
    with pytest.raises(BrainError,match='identity differs'):idx.search(['shaft support'],model)

def test_reingest_invalidates_embeddings(fs,tmp_path):
    idx=SemanticIndex(fs);idx.build(FixtureEncoder())
    csv=(tmp_path/'data.csv');text=csv.read_text();csv.write_text(text.replace('second component','altered component'))
    fs.ingest(csv)
    assert fs.status()['semantic_ready'] is False
    with pytest.raises(BrainError):idx.search(['shaft support'],FixtureEncoder())

def test_index_resume(fs):
    class Interrupt(FixtureEncoder):
        def __init__(self):self.calls=0
        def encode(self,texts,query=False):
            self.calls+=1
            if self.calls==2:raise RuntimeError('test interruption')
            return super().encode(texts,query)
    idx=SemanticIndex(fs)
    with pytest.raises(RuntimeError):idx.build(Interrupt(),batch_size=1)
    assert not fs.status()['semantic_ready']
    idx.build(FixtureEncoder(),batch_size=1)
    assert fs.status()['semantic_ready']

def test_corrupt_vectors(fs):
    idx=SemanticIndex(fs);idx.build(FixtureEncoder())
    v=np.load(idx.root/'vectors.npy');v[0]=0.;np.save(idx.root/'vectors.npy',v)
    with pytest.raises(BrainError):idx.search(['shaft support'],FixtureEncoder())

@pytest.mark.parametrize('value',[float('nan'),float('inf'),1.1,-1.1])
def test_bad_threshold(fs,value):
    with pytest.raises(BrainError):SemanticIndex(fs).search(['shaft support'],FixtureEncoder(),threshold=value)


def point(x,y,z=0.):return {'x':float(x),'y':float(y),'z':float(z)}
def circle(r):return {'type':'Circle3D','center_point':point(0,0),'normal':point(0,0,1),'radius':float(r)}
def raw_model(outer=5.,inner=2.,length=6.,extent='OneSideFeatureExtentType'):
    loops=[{'is_outer':True,'profile_curves':[circle(outer)]}]
    if inner:loops.append({'is_outer':False,'profile_curves':[circle(inner)]})
    return {'entities':{'s':{'type':'Sketch','transform':{'origin':point(0,0),'x_axis':point(1,0),'y_axis':point(0,1),'z_axis':point(0,0,1)},
         'profiles':{'p':{'loops':loops}}},
        'e':{'type':'ExtrudeFeature','start_extent':{'type':'ProfilePlaneStartDefinition'},'operation':'NewBodyFeatureOperation',
        'profiles':[{'sketch':'s','profile':'p'}],'extent_type':extent,'extent_one':{'distance':{'value':length}},'extent_two':{'distance':{'value':2.}}}},
        'sequence':[{'type':'Sketch','entity':'s'},{'type':'ExtrudeFeature','entity':'e'}]}

@pytest.mark.parametrize('extent,length,total',[('OneSideFeatureExtentType',6.,6.),('OneSideFeatureExtentType',-6.,6.),('SymmetricFeatureExtentType',6.,12.),('TwoSidesFeatureExtentType',6.,8.)])
@requires_cad
def test_deepcad_ring_replay(extent,length,total):
    s,r=reconstruct(raw_model(length=length,extent=extent),1.)
    assert s.isValid() and len(s.Solids())==1
    assert s.Volume()==pytest.approx(math.pi*(25-4)*total,rel=1e-7)
    assert s.BoundingBox().zlen==pytest.approx(total)

@requires_cad
def test_scale_not_guessed():
    s,_=reconstruct(raw_model(outer=.005,inner=.002,length=.006),1000.)
    assert s.BoundingBox().xlen==pytest.approx(10.)

@requires_cad
def test_nonorthogonal_frame_rejected():
    d=raw_model();d['entities']['s']['transform']['y_axis']=point(1,1)
    with pytest.raises(BrainError,match='orthonormal'):reconstruct(d,1.)

@requires_cad
def test_no_shape_substitution():
    d=raw_model();d['sequence'][1]['type']='LoftFeature'
    with pytest.raises(BrainError,match='Unsupported'):reconstruct(d,1.)

@requires_cad
def test_unknown_curve_rejected():
    d=raw_model();d['entities']['s']['profiles']['p']['loops'][0]['profile_curves'][0]['type']='Spline3D'
    with pytest.raises(BrainError):reconstruct(d,1.)

@requires_cad
def test_first_cut_rejected():
    d=raw_model();d['entities']['e']['operation']='CutFeatureOperation'
    with pytest.raises(BrainError):reconstruct(d,1.)

@requires_cad
def test_actual_topology_ring_vs_box():
    import cadquery as cq
    ring,_=reconstruct(raw_model(),1.);box=cq.Workplane('XY').box(10,10,6).val()
    a=shape_features(ring,256);b=shape_features(box,256)
    assert a['face_types']['CYLINDER']==2 and a['face_types']['PLANE']==2
    assert b['face_types']['PLANE']==6
    assert len(a['topology']['edges'])==4
    assert compare_records(a,a)['topology']['normalized_similarity']==pytest.approx(1.)
    assert compare_records(a,b)['topology']['normalized_similarity']<1
    assert a['geometry_descriptor']['learned'] is False

def test_wl_node_permutation():
    a=wl_features([{'id':0,'label':'PLANE'},{'id':1,'label':'CYLINDER'},{'id':2,'label':'PLANE'}],[[0,1],[1,2]])
    b=wl_features([{'id':30,'label':'PLANE'},{'id':10,'label':'CYLINDER'},{'id':20,'label':'PLANE'}],[[30,10],[10,20]])
    assert a==b and wl_similarity(a,b)['distance']==0

def test_wl_dangling_edge():
    with pytest.raises(BrainError):wl_features([{'id':0,'label':'PLANE'}],[[0,1]])

@pytest.fixture
def cad_sources(fs,tmp_path):
    root=tmp_path/'cad_json';(root/'9000').mkdir(parents=True)
    p=root/'9000'/'90000001.json';p.write_text(json.dumps(raw_model()))
    p2=root/'9000'/'90000002.json';p2.write_text(json.dumps(raw_model(outer=8.,inner=3.,length=4.)))
    attach_directory(fs,root,'deepcad_json',1.,'Authored test JSON explicitly uses millimeters','fixture://authored-CAD','MIT test fixtures')
    return root

def test_exact_uid_join(fs,cad_sources):
    assert fs.status()['cad_assets_linked']==2
    assert fs.case('9000/90000003')['asset'] is None
    assert fs.lexical(['support'],require_asset=True)['candidate_count']==2

def test_source_mutation_detected(fs,cad_sources):
    asset=fs.case('9000/90000001')['asset'];p=cad_sources/'9000'/'90000001.json';p.write_text(p.read_text()+' ')
    with pytest.raises(BrainError):read_asset(asset)

def test_no_missing_uid_geometry(fs):
    with pytest.raises(BrainError,match='No exact-UID'):Service(fs).materialize('9000/90000003')

def test_tar_index_and_read(fs,tmp_path):
    p=tmp_path/'data.tar';raw=json.dumps(raw_model()).encode()
    with tarfile.open(p,'w') as t:
        m=tarfile.TarInfo('data/cad_json/9000/90000001.json');m.size=len(raw);t.addfile(m,io.BytesIO(raw))
    out=attach_tar(fs,p,1.,'authored units mm','fixture://tar','MIT test fixture')
    assert out['linked']==1 and read_asset(fs.case('9000/90000001')['asset'])==raw

def test_tar_traversal_rejected(fs,tmp_path):
    p=tmp_path/'evil.tar'
    with tarfile.open(p,'w') as t:
        m=tarfile.TarInfo('data/cad_json/../../9000/90000001.json');m.size=2;t.addfile(m,io.BytesIO(b'{}'))
    with pytest.raises(BrainError):attach_tar(fs,p,1.,'test units','fixture://','test')

@requires_cad
def test_real_worker_and_evidence(fs,cad_sources):
    r=Service(fs).materialize('9000/90000001',60)
    assert r['geometry']['valid'] and r['geometry']['face_types']['CYLINDER']==2
    assert len(r['evidence_digest'])==64
    assert Path(r['geometry']['exports']['model.step']['absolute_path']).is_file()
    assert fs.status()['breps_measured']==1
    # Cache is portable in its evidence digest and checked again.
    again=Service(fs).materialize('9000/90000001',60)
    assert again['evidence_digest']==r['evidence_digest']
    p=Path(r['geometry']['exports']['model.step']['absolute_path']);p.write_text(p.read_text()+'CORRUPTED')
    with pytest.raises(BrainError):Service(fs).evidence('9000/90000001')

def test_tool_registration_and_no_fallback(brain):
    from cadmcp_brain.api import Tools
    from cadmcp_brain.protocol import Protocol
    t=Tools(brain);names={x['name'] for x in t.list()};assert len(names)==50
    assert t.brain_fs_status()['cases']==0
    with pytest.raises(BrainError):t.brain_fs_search(['軸を回転可能に支持する'])

@requires_cad
def test_case_refs_require_geometry_and_digest(brain,fs,cad_sources,data,monkeypatch):
    from cadmcp_brain.models import Concept
    monkeypatch.setenv('CADMCP_REQ2CAD_ROOT',str(fs.root))
    concept=Concept.model_validate(copy.deepcopy(data['concepts']['items'][0]))
    from cadmcp_brain.models import CaseReference
    ref=CaseReference(id='CASE-1',uid='9000/90000001',evidence_digest='0'*64,function_query='support rotating shaft',adopted_principle='cylindrical guide',required_adaptations=['Use actual shaft size and measured clearance'])
    concept.case_references=[ref]
    with pytest.raises(BrainError):brain._validate_case_references(concept)
    result=Service(fs).materialize(ref.uid)
    ref.evidence_digest=result['evidence_digest'];brain._validate_case_references(concept)
    ref.evidence_digest='f'*64
    with pytest.raises(BrainError):brain._validate_case_references(concept)

# Extra regression cases for changes that can otherwise silently corrupt evidence.
def test_normalized_vector_tamper_is_rejected(fs):
    idx=SemanticIndex(fs);idx.build(FixtureEncoder())
    m=np.load(idx.root/'vectors.npy');m[[0,1]]=m[[1,0]];np.save(idx.root/'vectors.npy',m)
    with pytest.raises(BrainError,match='checksum'):idx.search(['shaft support'],FixtureEncoder())

def test_custom_source_not_misattributed(fs):
    c=fs.case('9000/90000001')
    assert c['citation']['dataset']=='fixture://authored-unit-test'
    assert fs.status()['meta']['license'].startswith('custom source')

def test_duplicate_queries_do_not_inflate_coverage(fs):
    with pytest.raises(BrainError,match='Duplicate'):fs.lexical(['support shaft','  Support  shaft '])

def test_duplicate_asset_uid_rolls_back(fs,cad_sources):
    extra=cad_sources/'duplicate'/'9000';extra.mkdir(parents=True)
    (extra/'90000001.json').write_text(json.dumps(raw_model(outer=9.)))
    old=fs.case('9000/90000001')['asset']['sha256']
    with pytest.raises(BrainError,match='Multiple files'):attach_directory(fs,cad_sources,'deepcad_json',1.,'mm','fixture://','test')
    assert fs.case('9000/90000001')['asset']['sha256']==old

@requires_cad
def test_line_and_arc_replay():
    d=raw_model(inner=0)
    arc={'type':'Arc3D','start_point':point(5,0),'end_point':point(-5,0),'center_point':point(0,0),'radius':5.,'start_angle':0.,'end_angle':math.pi,'reference_vector':point(1,0)}
    line={'type':'Line3D','start_point':point(-5,0),'end_point':point(5,0)}
    d['entities']['s']['profiles']['p']['loops'][0]['profile_curves']=[arc,line]
    s,record=reconstruct(d,1.)
    assert s.Volume()==pytest.approx(math.pi*25/2*6,rel=1e-6)
    assert record['sketch_graphs'][0]['edges']==[[0,1]]

@requires_cad
def test_transformed_sketch_replay():
    d=raw_model();d['entities']['s']['transform']={'origin':point(12,3,4),'x_axis':point(1,0,0),'y_axis':point(0,0,1),'z_axis':point(0,-1,0)}
    s,_=reconstruct(d,1.);bb=s.BoundingBox()
    assert bb.ylen==pytest.approx(6.) and s.Center().toTuple()==pytest.approx((12,0,4))

@pytest.mark.parametrize('operation,expected',[('JoinFeatureOperation',math.pi*25*6),('CutFeatureOperation',math.pi*21*6),('IntersectFeatureOperation',math.pi*4*6)])
@requires_cad
def test_boolean_replay(operation,expected):
    d=raw_model(inner=0)
    second=raw_model(outer=2,inner=0)
    d['entities']['s2']=second['entities']['s'];e=second['entities']['e'];e['operation']=operation;e['profiles'][0]['sketch']='s2';d['entities']['e2']=e
    d['sequence'] += [{'type':'Sketch','entity':'s2'},{'type':'ExtrudeFeature','entity':'e2'}]
    s,_=reconstruct(d,1.);assert s.Volume()==pytest.approx(expected,rel=1e-6)

@requires_cad
def test_step_import_and_comparison(fs,tmp_path):
    import cadquery as cq
    root=tmp_path/'step';(root/'9000').mkdir(parents=True)
    for key,body in [('90000001',cq.Workplane('XY').box(10,10,6)),('90000002',cq.Workplane('XY').circle(5).extrude(6))]:
        cq.exporters.export(body,str(root/'9000'/(key+'.step')))
    attach_directory(fs,root,'step',1.,'Authored fixture STEP mm','fixture://step','MIT fixture')
    service=Service(fs)
    for u in ['9000/90000001','9000/90000002']:service.materialize(u)
    result=service.compare('9000/90000001','9000/90000002')
    assert result['topology']['normalized_similarity']<1.
    assert result['geometry']['euclidean_distance']>0.
    assert service.portfolio(['9000/90000001','9000/90000002'],limit=2)['selected']==['9000/90000001','9000/90000002']

@requires_cad
def test_req2cad_tools_over_real_stdio(fs,cad_sources,tmp_path):
    def req(method,params=None,rid=1):return {'jsonrpc':'2.0','id':rid,'method':method,'params':params or {}}
    msgs=[req('initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'FS-test','version':'1'}},0),{'jsonrpc':'2.0','method':'notifications/initialized'}]
    for name,args in [('brain_fs_status',{}),('brain_fs_search',{'functions':['support rotating shaft'],'mode':'lexical'}),('brain_fs_materialize',{'uid':'9000/90000001'}),('brain_fs_evidence',{'uid':'9000/90000001'})]:
        msgs.append(req('tools/call',{'name':name,'arguments':args},len(msgs)))
    env=dict(os.environ,CADMCP_REQ2CAD_ROOT=str(fs.root),PYTHONUTF8='1')
    proc=subprocess.run([sys.executable,'-m','cadmcp_brain','--workspace',str(tmp_path/'wire'),'serve'],input=''.join(json.dumps(m)+'\n' for m in msgs),text=True,encoding='utf-8',capture_output=True,timeout=45,env=env)
    assert proc.returncode==0,proc.stderr
    replies=[json.loads(line) for line in proc.stdout.splitlines()]
    assert len(replies)==5 and all(not r['result'].get('isError',False) for r in replies)
    last=replies[-1]['result']['structuredContent']['result']
    assert last['geometry']['valid'] is True
    assert last['function_provenance'].startswith('Imported annotation from fixture:')

def test_reingest_same_bytes_preserves_assets(fs,cad_sources,tmp_path):
    result=fs.ingest(tmp_path/'data.csv',source_url='fixture://authored-unit-test')
    assert result['import_skipped_same_source'] and fs.status()['cad_assets_linked']==2

def test_reference_first_blocks_ungrounded(data,brain,monkeypatch):
    from cadmcp_brain.models import Concept
    monkeypatch.setenv('CADMCP_REQUIRE_CAD_REFERENCES','1')
    c=Concept.model_validate(data['concepts']['items'][0])
    with pytest.raises(BrainError,match='Reference-first'):brain._validate_case_references(c)

@requires_cad
def test_uncalibrated_cad_is_not_physical_mm(fs,cad_sources):
    attach_directory(fs,cad_sources,'deepcad_json',1.,'Unknown physical scale; reference only','fixture://','MIT',reference_only=True)
    out=Service(fs).materialize('9000/90000001')
    assert out['geometry']['dimensional_status']=='reference_coordinates_only'
    assert 'bbox_model_units' in out['geometry'] and 'bbox_mm' not in out['geometry']
    assert out['geometry']['manufacturing_dimensions_verified'] is False
    assert out['geometry']['topology']['edges']
