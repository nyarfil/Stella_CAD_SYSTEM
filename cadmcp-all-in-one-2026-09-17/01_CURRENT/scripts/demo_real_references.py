"""Offline end-to-end demo with four source-identified public CAD records.

NOT a random benchmark and NOT the complete Req2CAD corpus. This demo uses an
explicit lexical search path; Qwen model quality is not measured by this script.
"""
from __future__ import annotations
import argparse,hashlib,json,os,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from cadmcp_brain.engine import Brain
from cadmcp_brain.api import Tools
from cadmcp_brain.req2cad.catalog import Catalog
from cadmcp_brain.req2cad.assets import attach_directory
from cadmcp_brain.req2cad.common import atomic_json,file_hash

REQUEST='公開CADの構造を参考に、小型の軸案内部品と、その穴を通る軸の試作アセンブリを作る。外形・寸法は実物マウスの推奨値ではなく動作検証用とする。'

def init_cases(workspace):
    workspace=Path(workspace).resolve();marker=workspace/'.public-cases-demo'
    if workspace.exists() and any(workspace.iterdir()) and not marker.exists():
        raise ValueError('Use a NEW demo workspace. Never replace a production catalog with the four-case subset.')
    workspace.mkdir(parents=True,exist_ok=True);marker.write_text('Four selected public cases only. No Qwen model benchmark.\n',encoding='utf-8')
    examples=ROOT/'examples'/'public-cases';provenance=json.loads((examples/'provenance.json').read_text('utf-8'))
    checks=[]
    for item in provenance['cad_records']:
        p=examples/'cad_json'/(item['uid']+'.json');raw=p.read_bytes()
        git=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        assert file_hash(p)==item['sha256'] and git==item['git_blob_sha1'],'Public source content changed'
        checks.append({'uid':item['uid'],'sha256_verified':True,'git_blob_verified':True,'official_archive_matched':False})
    kb=Catalog(workspace/'knowledge'/'req2cad')
    kb.ingest(examples/'annotations.csv',source_url='subset://Req2CAD-public-labels-with-paraphrased-descriptions;see-examples/public-cases/provenance.json')
    attach_directory(kb,examples/'cad_json','deepcad_json',1000.,'Display normalization of raw coordinates only; not calibrated physical millimeters.',
                     'https://github.com/arnavagarwal05/3d_modelling/tree/432d03406b89a924b755c1826f2eb78da650e440/data/cad_json',
                     'Public mirror CAD; original data rights distinct from code. Annotation labels attributed to Qianzhi Jing et al., CC-BY-4.0.',True)
    os.environ['CADMCP_REQ2CAD_ROOT']=str(kb.root)
    brain=Brain(workspace);tools=Tools(brain)
    measured={key:tools.brain_fs_materialize(key) for key in [x['uid'] for x in provenance['cad_records']]}
    return tools,kb,measured,checks


def demo_recipe(measured):
    guide=measured['0032/00329619'];shaft=measured['0032/00321991']
    def base(id,op,func,reason,**kwargs):return {'id':id,'op':op,'function_id':func,'reason':reason,**kwargs}
    ops=[
      base('retainer_ref','reference','Guide','Keep the real flanged retainer structure as a geometric starting point.',uid=guide['uid'],evidence_digest=guide['evidence_digest'],uniform_scale=.2,adaptation_basis='Trial target: reference X span 80 display units becomes a 16 mm flange. This is a design proposal, not recovered source units.'),
      base('cavity_fill','cylinder','Guide','Replace the oversized recess with a longer load-supporting sleeve before making the new trial bore.',radius_mm=4.4,height_mm=6.,origin_mm=[0.,0.,0.],axis=[0.,0.,1.]),
      base('sleeve','union','Guide','Join the reference shell and internal fill; preserve the reference flange-and-boss organization.',operands=['retainer_ref','cavity_fill']),
      base('mount_plate','box','Mount','Provide a flat mounting face and adequate proposed edge distance for two demonstration holes.',size_mm=[22.,18.,2.],center_mm=[0.,0.,1.]),
      base('mount_blank','union','Mount','Merge the reference-derived guide with the proposed mounting plate.',operands=['sleeve','mount_plate']),
      base('shaft_bore','cylinder','Guide','Use a proposed 3.3 mm bore around the proposed 3.0 mm shaft; not a qualified printing clearance.',radius_mm=1.65,height_mm=8.,origin_mm=[0.,0.,-1.],axis=[0.,0.,1.]),
      base('mount_hole_l','cylinder','Mount','First proposed mounting hole; fastener and printer qualification remain open.',radius_mm=1.25,height_mm=4.,origin_mm=[-8.5,0.,-1.],axis=[0.,0.,1.]),
      base('mount_hole_r','cylinder','Mount','Second proposed mounting hole for the demonstration fixture only.',radius_mm=1.25,height_mm=4.,origin_mm=[8.5,0.,-1.],axis=[0.,0.,1.]),
      base('finished_guide','difference','Guide','Cut the functional bore and both mounting holes from the actual reference-derived body.',operands=['mount_blank','shaft_bore','mount_hole_l','mount_hole_r']),
      base('shaft_ref','reference','Move','The solid cylindrical example is usable as a shaft, not as a hollow guide.',uid=shaft['uid'],evidence_digest=shaft['evidence_digest'],uniform_scale=.15,adaptation_basis='Trial target: 20 display-unit diameter becomes 3.0 mm; aspect ratio retained, length 7.5 mm is only a prototype choice.'),
      base('positioned_shaft','transform','Move','Place the shaft through the guide with nominal radial clearance; do not fuse moving and fixed parts.',source='shaft_ref',translation_mm=[0.,0.,-.5]),
    ]
    return {'schema_version':1,'title':'Real-reference flanged shaft guide — geometry demonstrator',
       'original_request':REQUEST,'units':'mm','design_parameters':{'shaft_diameter':3.,'bore_diameter':3.3,'axial_motion':.5},
       'parameter_basis':{'shaft_diameter':'PROPOSAL for demonstration, not measured user hardware.',
                          'bore_diameter':'PROPOSAL: 0.3 mm diametral clearance; not calibrated for QIDI/ABS.',
                          'axial_motion':'PROPOSAL for a sampled collision test, not real encoder travel.'},
       'functions':{'Guide':'Constrain the shaft radially while allowing axial motion.','Mount':'Attach the fixed guide to a test base.','Move':'Provide the moving cylindrical interface.'},
       'operations':ops,'outputs':[{'part_id':'guide','node':'finished_guide','expected_solids':1},{'part_id':'shaft','node':'positioned_shaft','expected_solids':1}],
       'dimension_checks':[{'id':'guide_width','part':'guide','kind':'bbox','axis':'x','nominal_mm':22.,'tolerance_mm':.00001},{'id':'bore_size','part':'guide','kind':'inner_cylinder_diameter','axis':'z','nominal_mm':3.3,'tolerance_mm':.00001},{'id':'shaft_size','part':'shaft','kind':'outer_cylinder_diameter','axis':'z','nominal_mm':3.,'tolerance_mm':.00001}],
       'clearance_checks':[{'id':'guide_shaft_gap','part_a':'guide','part_b':'shaft','min_mm':.14}],
       'motion_checks':[{'id':'axial_motion_samples','moving_part':'shaft','obstacles':['guide'],'translation_end_mm':[0.,0.,.5],'samples':11,'min_mm':.14}],
       'unverified_requirements':['Not a complete mouse assembly. No actual PCB/switch/shell was supplied.',
            'FDM hole-size calibration, surface friction, wear and support removal are untested.',
            'Force capacity, creep and fatigue life have not been established.',
            'Linear-motion distance bound assumes kernel accuracy; no rotational, deformation or assembly-path proof.',
            'Fastener selection, insertion and retained assembly require further design.']}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace',type=Path,default=ROOT/'demo-workspace')
    a=p.parse_args(argv);tools,kb,measured,checks=init_cases(a.workspace)
    project_id='public-guide-'+uuid.uuid4().hex[:8];tools.brain_open(project_id,REQUEST)
    brief={'original_request':REQUEST,'protected_constraints':[],'unresolved':['Trial dimensions only; no actual mouse hardware was supplied.'],
           'functions':[{'id':'Guide','source_excerpt':'軸案内部品','function':'support rotating shaft','behavior':'Allow motion around a cylindrical shaft without material occupying its radial clearance.',
                         'queries':['support rotation','guide rotating shafts','act as guide'],'required_features':['has_cylindrical_cavity_surface']}]}
    retrieval=tools.brain_fs_search_tasks(brief,mode='lexical')
    recipe=demo_recipe(measured);built=tools.brain_studio_build(project_id,0,recipe,180)
    for role in ['requirements','mechanism','assembly','manufacturing','verification']:
        tools.brain_studio_review_packet(project_id,0,built['subject_digest'],role)
    result={'source_checks':checks,'catalog':kb.status(),'retrieval':retrieval,'build':built,
            'model_quality_benchmark':False,'independent_llm_reviews_executed':False,
            'public_cases_count':4,'full_corpus_tested':False}
    atomic_json(Path(a.workspace)/'DEMO_RESULT.json',result)
    print(json.dumps({'project_id':project_id,'source_records':len(measured),'build':built},ensure_ascii=False,indent=2))
    return 0
if __name__=='__main__':raise SystemExit(main())
