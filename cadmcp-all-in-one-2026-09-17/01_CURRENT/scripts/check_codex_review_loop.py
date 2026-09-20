"""Bounded real-model five-role debate and typed repair on an isolated public-CAD fixture."""
from __future__ import annotations
import argparse,copy,json,os,sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.req2cad.common import atomic_json,digest
from cadmcp_brain.studio.provider import CodexProvider
from cadmcp_brain.studio.runtime import ROLES,Review
from scripts.demo_real_references import demo_recipe

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-model',action='store_true')
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--project',required=True)
    parser.add_argument('--timeout',type=int,default=300)
    args=parser.parse_args(argv)
    if not args.execute_model:parser.error('This run makes bounded authenticated model calls; --execute-model is required.')
    workspace=args.workspace.resolve()
    if not (workspace/'.public-cases-demo').is_file():parser.error('Only a marked isolated public-case workspace is accepted.')
    os.environ['CADMCP_REQ2CAD_ROOT']=str(workspace/'knowledge/req2cad')
    tools=Tools(Brain(workspace));revision=tools.brain_get(args.project)['project']['revision']
    measured={uid:tools.brain_fs_materialize(uid) for uid in ('0032/00329619','0032/00321991')}
    original=demo_recipe(measured);original.setdefault('protected_constraints',[]);broken=copy.deepcopy(original)
    next(node for node in broken['operations'] if node['id']=='shaft_bore')['radius_mm']=1.30
    failed=tools.brain_studio_build(args.project,revision,broken,180)
    if failed['geometry_checks_verdict']!='fail':raise RuntimeError('Negative control did not fail geometry checks.')
    run_root=workspace/'codex-review-loop';provider=CodexProvider(run_root/'calls',max_calls=22,timeout_seconds=args.timeout,evidence_root=workspace)

    def review_subject(build):
        all_reports=[];receipts=[]
        for round_number in (1,2):
            first_ids=[item['review_id'] for item in receipts if item['discussion_round']==1]
            def one(role):
                packet=tools.brain_studio_review_packet(args.project,revision,build['subject_digest'],role)
                packet['discussion_round']=round_number
                if round_number==2:
                    packet['peer_findings']=copy.deepcopy(all_reports)
                    packet['required_challenged_review_ids']=first_ids
                    packet['instructions']+=' Challenge the saved first-round findings against the evidence. Return every required_challenged_review_id in challenged_review_ids. Do not clear a measured failure by vote.'
                result=Review.model_validate(provider.generate(packet['instructions'],Review.model_json_schema(),packet,role=role))
                if result.role!=role or result.discussion_round!=round_number:raise RuntimeError('Reviewer returned the wrong role or round.')
                if round_number==2 and set(result.challenged_review_ids)!=set(first_ids):raise RuntimeError('Peer challenge IDs were incomplete.')
                if not result.evidence_inspections:raise RuntimeError('Reviewer did not record evidence inspection.')
                return result.model_dump()
            with ThreadPoolExecutor(max_workers=3) as pool:reports=list(pool.map(one,ROLES))
            submitted=[]
            for report in reports:
                receipt=tools.brain_studio_submit_review(args.project,revision,build['subject_digest'],report)
                receipt['discussion_round']=round_number;submitted.append(receipt)
            all_reports.extend(reports);receipts.extend(submitted)
        return {'reports':all_reports,'receipts':receipts,'status':tools.brain_studio_review_status(args.project,revision,build['subject_digest'])}

    failed_review=review_subject(failed)
    packet=tools.brain_studio_review_packet(args.project,revision,failed['subject_digest'],'verification')
    frozen={key:broken[key] for key in ('original_request','functions','protected_constraints','dimension_checks','clearance_checks','motion_checks','unverified_requirements')}
    patch_schema={'type':'object','additionalProperties':False,'properties':{
        'operation_id':{'const':'shaft_bore'},'radius_mm':{'type':'number','minimum':1.3,'maximum':2.0},
        'reason':{'type':'string','minLength':12},'checks_changed':{'const':False}},
        'required':['operation_id','radius_mm','reason','checks_changed']}
    patch=provider.generate('Repair only the shaft_bore radius so the existing 3.3 mm bore dimension check and 3.0 mm shaft clearance can pass. Do not change checks, thresholds, request, functions, protected constraints or unknowns. Return one typed patch.',
                            patch_schema,{'failed_recipe':broken,'failed_build':failed,'frozen_contract_digest':digest(frozen),
                                          'evidence_attachments':packet['subject']['payload']['evidence_attachments']},role='repair')
    repaired=copy.deepcopy(broken);next(node for node in repaired['operations'] if node['id']==patch['operation_id'])['radius_mm']=patch['radius_mm']
    if any(repaired[key]!=value for key,value in frozen.items()):raise RuntimeError('Repair weakened a frozen condition.')
    rebuilt=tools.brain_studio_build(args.project,revision,repaired,180)
    repaired_review=review_subject(rebuilt)
    delivery=tools.brain_studio_delivery(args.project,revision,rebuilt['subject_digest'])
    report={'actual_model_called':True,'test_double':False,'source_recipe':'existing hand-written public demo recipe',
            'failed_subject':failed['subject_digest'],'failed_geometry':failed['geometry_checks_verdict'],'failed_review':failed_review,
            'repair_patch':patch,'frozen_contract_digest':digest(frozen),'repaired_subject':rebuilt['subject_digest'],
            'repaired_geometry':rebuilt['geometry_checks_verdict'],'repaired_review':repaired_review,'delivery':delivery,
            'physical_performance_certified':False,'canonical_cad_modified':False,'model_calls':provider.calls}
    atomic_json(run_root/'CODEX_REVIEW_LOOP_RESULT.json',report)
    # Windows PowerShell may still expose a CP932 stdout even when the JSON
    # evidence itself is UTF-8.  Keep console output ASCII-safe; the durable
    # result above retains the original Unicode strings.
    print(json.dumps(report,ensure_ascii=True,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
