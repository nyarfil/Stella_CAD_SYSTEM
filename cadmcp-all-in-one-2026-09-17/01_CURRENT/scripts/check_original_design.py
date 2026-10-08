"""One authorized real-model proof of an original, non-catalog L-plate design."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.req2cad.common import atomic_json,file_hash,json_load
from cadmcp_brain.studio.autopilot import Autopilot
from cadmcp_brain.studio.provider import CodexProvider
from cadmcp_brain.studio.runtime import ROLES

REQUEST='ソフトウェアの幾何検証用L字プレート。XY輪郭(0,0),(20,0),(20,6),(10,6),(10,14),(0,14) mm、Z=0..2 mmの単一ソリッド。カタログ形状を流用せず新規設計。外接20x14x2、体積400 mm3、欠き取り領域を検証。実機の荷重・材料性能や製造認定は今回要求しないが未検証として残す。'
VERIFICATION_ROOT=(ROOT/'verification').resolve()
DEFAULT_RUN_ROOT=VERIFICATION_ROOT/'original-design-20260920'
PROJECT_ID='original-l-plate'


def _inside(solids,point):
    import cadquery as cq
    return any(s.isInside(cq.Vector(*point),1e-7) for s in solids)


def inspect_step(build):
    """Re-open the exported STEP; do not trust recipe claims or cached measures."""
    import cadquery as cq
    assembly=Path(build['assembly_step']).resolve()
    imported=cq.importers.importStep(str(assembly)).val()
    solids=imported.Solids();bbox=imported.BoundingBox()
    actual_bbox=[float(bbox.xlen),float(bbox.ylen),float(bbox.zlen)]
    actual_extents=[float(v) for v in (bbox.xmin,bbox.xmax,bbox.ymin,bbox.ymax,bbox.zmin,bbox.zmax)]
    volume=float(sum(s.Volume() for s in solids))
    notch_point=[15.,10.,1.]
    material_points=[[5.,10.,1.],[15.,3.,1.]]
    notch=cq.Solid.makeBox(10.,8.,2.,cq.Vector(10.,6.,0.))
    notch_overlap=float(sum(s.Volume() for s in imported.intersect(notch).Solids()))
    checks={
        'valid_brep':bool(imported.isValid()),
        'single_solid':len(solids)==1,
        'bbox_20x14x2':all(abs(a-b)<=1e-6 for a,b in zip(actual_bbox,[20.,14.,2.])),
        'bbox_exact_x0_20_y0_14_z0_2':all(abs(a-b)<=1e-6 for a,b in zip(actual_extents,[0.,20.,0.,14.,0.,2.])),
        'volume_400_mm3':abs(volume-400.)<=1e-6,
        'entire_notch_region_has_zero_overlap':notch_overlap<=1e-7,
        'notch_point_is_outside':not _inside(solids,notch_point),
        'material_points_are_inside':all(_inside(solids,p) for p in material_points),
        'removed_bbox_volume_160_mm3':abs(bbox.xlen*bbox.ylen*bbox.zlen-volume-160.)<=1e-6,
    }
    return {'assembly_step':str(assembly),'assembly_sha256':file_hash(assembly),
            'actual_bbox_mm':actual_bbox,'actual_extents_mm':actual_extents,'actual_volume_mm3':volume,
            'notch_point_mm':notch_point,'material_points_mm':material_points,
            'notch_overlap_mm3':notch_overlap,
            'removed_bbox_volume_mm3':float(bbox.xlen*bbox.ylen*bbox.zlen-volume),
            'checks':checks,'verdict':'pass' if all(checks.values()) else 'fail'}


def provider_receipts(provider):
    rows=[]
    for path in sorted(provider.root.glob('*/receipt.json')):
        value=json_load(path)
        rows.append({'path':str(path.resolve()),'sha256':file_hash(path),**value})
    return rows


def review_responses(provider):
    rows=[]
    for path in sorted(provider.root.glob('*/normalized-response.json')):
        value=json_load(path)
        if value.get('role') in ROLES:rows.append(value)
    return rows


def assess_execution(provider_calls,receipts,reviews,review_receipts):
    restored=[]
    for review in reviews:
        inspections=review.get('evidence_inspections',[])
        restored.append(bool(inspections) and all(
            item.get('attachment_path') and Path(item['attachment_path']).is_file() and
            file_hash(Path(item['attachment_path']))==item.get('attachment_sha256')
            for item in inspections))
    return {
        'model_call_budget_respected':provider_calls<=16,
        'all_call_receipts_saved':len(receipts)==provider_calls and all(r.get('response_received') for r in receipts),
        'five_roles_two_rounds_called':len(reviews)==10 and all(
            sum(r.get('role')==role for r in reviews)==2 for role in ROLES),
        'five_roles_have_rounds_one_and_two':len(reviews)==10 and all(
            sorted(r.get('discussion_round') for r in reviews if r.get('role')==role)==[1,2] for role in ROLES),
        'ten_review_submissions_saved':len(review_receipts)==10,
        'provider_restore_path_verified':len(restored)==10 and all(restored),
    }


def resolve_run_root(value):
    candidate=Path(value).resolve()
    try:candidate.relative_to(VERIFICATION_ROOT)
    except ValueError as exc:raise ValueError('Run root must stay under this code checkout verification directory.') from exc
    if candidate==VERIFICATION_ROOT:raise ValueError('Run root must be a child of the verification directory.')
    if candidate.exists():raise ValueError('Run root must be a new path; existing evidence is immutable.')
    return candidate


def result_build(state):
    if state.get('build'):return state['build']
    failure=state.get('last_failure',{})
    if failure.get('build'):return failure['build']
    raise RuntimeError('Autopilot did not preserve a completed geometry build.')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-model',action='store_true',help='Authorize this single bounded real-model run.')
    parser.add_argument('--run-root',type=Path,default=DEFAULT_RUN_ROOT,
                        help='New one-shot directory under this checkout verification folder.')
    args=parser.parse_args(argv)
    if not args.execute_model:
        parser.error('This proof makes one bounded authenticated model run; --execute-model is required.')
    try:run_root=resolve_run_root(args.run_root)
    except ValueError as exc:parser.error(str(exc))

    run_root.mkdir(parents=True)
    request_path=run_root/'original-request.txt'
    request_path.write_text(REQUEST,encoding='utf-8')
    os.environ['CADMCP_REQ2CAD_ROOT']=str((run_root/'isolated-req2cad').resolve())
    provider=None
    try:
        tools=Tools(Brain(run_root/'workspace'))
        opened=tools.brain_open(PROJECT_ID,REQUEST)
        provider=CodexProvider(run_root/'calls',model='gpt-5.6-sol',max_calls=16,
                               timeout_seconds=180,evidence_root=run_root)
        state=Autopilot(tools,provider,run_root/'autopilot',design_route='original',
                        max_repairs=0,max_replans=1,review_workers=3,debate_rounds=2).run(PROJECT_ID)
        build=result_build(state)
        recipe_path=Path(build['recipe_path']).resolve()
        recipe=json_load(recipe_path)
        independent=inspect_step(build)
        receipts=provider_receipts(provider)
        reviews=review_responses(provider)
        review_receipts=state.get('review_receipts',[])
        status=state.get('review_status') or state.get('last_failure',{}).get('review_status') or {}
        recipe_checks={
            'original_request_exact':recipe.get('original_request')==REQUEST,
            'request_file_exact':request_path.read_text('utf-8')==REQUEST,
            'no_catalog_shape_operation':not any(n.get('op') in ('reference','project_step') for n in recipe.get('operations',[])),
            'no_reference_use_claim':not recipe.get('reference_uses'),
            'polygon_extrusion_generated_by_model':any(n.get('op')=='polygon_extrusion' for n in recipe.get('operations',[])),
            'physical_unknown_retained':any(any(word in item.casefold() for word in ('荷重','材料','製造','strength','material','manufactur','load')) for item in recipe.get('unverified_requirements',[])),
        }
        execution_checks=assess_execution(provider.calls,receipts,reviews,review_receipts)
        completed=all(independent['checks'].values()) and all(recipe_checks.values()) and all(execution_checks.values())
        accepted_for_owner_review=state.get('phase')=='prototype_ready_for_owner_review' and bool(status.get('discussion_ready_for_owner'))
        proof_passed=completed and accepted_for_owner_review
        report={
            'proof_passed':proof_passed,'execution_completed':completed,
            'acceptance_status':'ready_for_owner_review' if accepted_for_owner_review else 'not_accepted',
            'overall_verdict':'unknown' if accepted_for_owner_review else 'not_accepted',
            'physical_performance_certified':False,
            'actual_model_called':provider.calls>0,'model':'gpt-5.6-sol','model_calls':provider.calls,
            'project_open_receipt':opened,'request':REQUEST,'request_path':str(request_path.resolve()),
            'request_sha256':file_hash(request_path),'isolated_req2cad_root':os.environ['CADMCP_REQ2CAD_ROOT'],
            'autopilot_state':state,'recipe_path':str(recipe_path),'recipe_sha256':file_hash(recipe_path),
            'recipe_checks':recipe_checks,'independent_step_inspection':independent,
            'review_status':status,'execution_checks':execution_checks,'provider_receipts':receipts,
            'image_paths':sorted(str(p.resolve()) for p in Path(build['folder']).rglob('*.png')),
        }
        atomic_json(run_root/'ORIGINAL_DESIGN_RESULT.json',report)
        print(json.dumps(report,ensure_ascii=True,indent=2))
        return 0 if proof_passed else 1
    except Exception as exc:
        error=exc.as_dict() if isinstance(exc,BrainError) else {'type':type(exc).__name__,'message':str(exc)}
        failure={'execution_completed':False,'acceptance_status':'not_accepted','overall_verdict':'not_accepted',
                 'physical_performance_certified':False,'actual_model_called':bool(provider and provider.calls),
                 'model_calls':provider.calls if provider else 0,'request':REQUEST,'error':error,
                 'run_root':str(run_root.resolve()),'request_path':str(request_path.resolve()),
                 'provider_receipts':provider_receipts(provider) if provider else [],
                 'image_paths':sorted(str(p.resolve()) for p in run_root.rglob('*.png'))}
        atomic_json(run_root/'ORIGINAL_DESIGN_RESULT.json',failure)
        print(json.dumps(failure,ensure_ascii=True,indent=2))
        return 1


if __name__=='__main__':raise SystemExit(main())
