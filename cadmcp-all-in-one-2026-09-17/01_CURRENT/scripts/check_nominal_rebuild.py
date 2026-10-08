"""Rebuild the immutable R2 model recipe with the corrected nominal B-rep measurement."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.req2cad.common import atomic_json,digest,file_hash,json_load
from scripts.check_original_design import REQUEST,inspect_step

SOURCE_ROOT=(ROOT/'verification'/'original-design-20260920-r2').resolve()
RUN_ROOT=(ROOT/'verification'/'original-design-20260920-r2-remeasure').resolve()
PROJECT_ID='original-l-plate'


def tree_manifest(root):
    return {p.relative_to(root).as_posix():file_hash(p) for p in sorted(root.rglob('*')) if p.is_file()}


def main():
    if not SOURCE_ROOT.is_dir():raise SystemExit('Immutable R2 source evidence is missing.')
    if RUN_ROOT.exists():raise SystemExit('Refusing to reuse the one-shot remeasurement directory.')
    old_manifest=tree_manifest(SOURCE_ROOT);old_manifest_digest=digest(old_manifest)
    old_report_path=SOURCE_ROOT/'ORIGINAL_DESIGN_RESULT.json'
    old_report=json_load(old_report_path)
    old_build=old_report['autopilot_state']['last_failure']['build']
    source_recipe_path=Path(old_report['recipe_path']).resolve()
    if SOURCE_ROOT not in source_recipe_path.parents:raise SystemExit('R2 recipe path escaped immutable source evidence.')
    source_recipe_hash=file_hash(source_recipe_path)
    recipe_bytes=source_recipe_path.read_bytes();recipe=json.loads(recipe_bytes)
    if recipe.get('original_request')!=REQUEST or old_report.get('request')!=REQUEST:
        raise SystemExit('R2 request does not exactly match the frozen original request.')
    if not recipe.get('dimension_checks') or any(d.get('tolerance_mm')!=0 for d in recipe['dimension_checks']):
        raise SystemExit('R2 zero-tolerance dimension-check contract changed.')

    RUN_ROOT.mkdir(parents=True)
    os.environ['CADMCP_REQ2CAD_ROOT']=str((RUN_ROOT/'isolated-req2cad').resolve())
    tools=Tools(Brain(RUN_ROOT/'workspace'))
    opened=tools.brain_open(PROJECT_ID,REQUEST)
    build=tools.brain_studio_build(PROJECT_ID,0,recipe,timeout_seconds=180)
    rebuilt_recipe_path=Path(build['recipe_path']).resolve()
    independent=inspect_step(build)
    status=tools.brain_studio_review_status(PROJECT_ID,0,build['subject_digest'])
    old_manifest_after=tree_manifest(SOURCE_ROOT)
    dimension_checks=[c for c in build['checks'] if c.get('id') in {d['id'] for d in recipe['dimension_checks']}]
    checks={
        'r2_evidence_unchanged':old_manifest_after==old_manifest,
        'request_exactly_unchanged':recipe['original_request']==REQUEST,
        'recipe_hash_exactly_unchanged':file_hash(rebuilt_recipe_path)==source_recipe_hash,
        'dimension_check_contract_unchanged':all(d['tolerance_mm']==0 for d in recipe['dimension_checks']),
        'old_r2_remains_not_accepted':old_report['acceptance_status']=='not_accepted' and old_build['geometry_checks_verdict']=='fail',
        'new_subject_is_distinct':build['subject_digest']!=old_build['subject_digest'],
        'new_nominal_geometry_passes':build['geometry_checks_verdict']=='pass' and all(c['verdict']=='pass' for c in dimension_checks),
        'independent_step_measurement_passes':independent['verdict']=='pass',
        'new_subject_has_no_copied_reviews':status.get('reviewed_roles')==[] and status.get('reports')==0 and not status.get('discussion_ready_for_owner'),
    }
    report={
        'remeasurement_passed':all(checks.values()),'actual_model_called':False,
        'source_r2_acceptance_status':'not_accepted','source_r2_geometry_verdict':old_build['geometry_checks_verdict'],
        'source_subject_digest':old_build['subject_digest'],'new_subject_digest':build['subject_digest'],
        'original_request':REQUEST,'project_open_receipt':opened,
        'source_recipe_path':str(source_recipe_path),'source_recipe_sha256':source_recipe_hash,
        'rebuilt_recipe_path':str(rebuilt_recipe_path),'rebuilt_recipe_sha256':file_hash(rebuilt_recipe_path),
        'recipe_byte_count':len(recipe_bytes),'dimension_check_contract':recipe['dimension_checks'],
        'old_r2_manifest':{'file_count':len(old_manifest),'digest_before':old_manifest_digest,
                           'digest_after':digest(old_manifest_after),'unchanged':old_manifest_after==old_manifest},
        'new_build':build,'new_geometry_verdict':build['geometry_checks_verdict'],
        'new_dimension_checks':dimension_checks,'independent_step_inspection':independent,
        'review_state':{'status':'not_run','copied_from_source':False,'reviewed_roles':status.get('reviewed_roles',[]),
                        'reports':status.get('reports',0),
                        'discussion_ready_for_owner':status.get('discussion_ready_for_owner',False)},
        'checks':checks,'physical_performance_certified':False,'overall_verdict':'unknown',
        'image_paths':sorted(str(p.resolve()) for p in Path(build['folder']).rglob('*.png')),
    }
    atomic_json(RUN_ROOT/'NOMINAL_REBUILD_RESULT.json',report)
    print(json.dumps(report,ensure_ascii=True,indent=2))
    return 0 if report['remeasurement_passed'] else 1


if __name__=='__main__':raise SystemExit(main())
