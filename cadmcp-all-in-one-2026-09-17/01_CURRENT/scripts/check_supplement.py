"""No-model formal supplemental verification of the isolated R2 nominal rebuild."""
from pathlib import Path
import argparse
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.req2cad.common import atomic_json,file_hash,json_load


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-name',default='SUPPLEMENT_RESULT.json')
    args=parser.parse_args()
    if not re.fullmatch(r'SUPPLEMENT_RESULT(?:_[A-Z0-9]+)?\.json',args.report_name):
        raise ValueError('Use a bounded result name, not an arbitrary output path.')
    run=ROOT/'verification'/'original-design-20260920-r2-remeasure'
    result_path=run/args.report_name
    if result_path.exists():
        raise ValueError('Keep the existing proof; this one-shot script refuses to overwrite it.')
    old=json_load(run/'NOMINAL_REBUILD_RESULT.json')
    source=old['new_build']['subject_digest']
    source_folder=Path(old['new_build']['folder'])
    if not source_folder.resolve().is_relative_to((run/'workspace').resolve()):
        raise ValueError('The source must be inside this isolated test workspace.')
    before={p.relative_to(source_folder).as_posix():file_hash(p) for p in source_folder.rglob('*') if p.is_file()}
    tools=Tools(Brain(run/'workspace'))
    project_id='original-l-plate'
    revision=tools.brain.store.get(project_id).revision
    spec=json_load(ROOT/'benchmarks'/'development'/'l_plate.acceptance.json')
    source_unknowns=json_load(source_folder/'measurements.json')['unverified_requirements']
    spec['unverified_requirements']=list(dict.fromkeys(source_unknowns+spec['unverified_requirements']))
    outcome=tools.brain_studio_verify_artifact(project_id,revision,source,spec,60)
    status=tools.brain_studio_review_status(project_id,revision,outcome['subject_digest'])
    packet=tools.brain_studio_review_packet(project_id,revision,outcome['subject_digest'],'verification')
    delivery=tools.brain_studio_delivery(project_id,revision,outcome['subject_digest'])
    supplement_report=json_load(Path(outcome['supplement_report']))
    consistency=supplement_report.get('delivery_consistency',{})
    after={p.relative_to(source_folder).as_posix():file_hash(p) for p in source_folder.rglob('*') if p.is_file()}
    checks={'source_unchanged':before==after,'new_subject':outcome['subject_digest']!=source,
            'no_review_copy':status['reports']==0,'not_owner_ready':not status['discussion_ready_for_owner'],
            'geometry_pass':outcome['geometry_checks_verdict']=='pass',
            'no_cad_regeneration':outcome['cad_regenerated'] is False,
            'step_bytes_unchanged':file_hash(Path(outcome['assembly_step']))==before['assembly.step'],
            'delivery_geometry_pass':consistency.get('verdict')=='pass',
            'delivery_check_in_acceptance':any(c.get('id')=='_system-delivery-step-geometry-consistency'
                and c.get('passed') is True for c in supplement_report.get('checks',[])),
            'supplement_report_attached':any(Path(a['path']).name=='supplement-report.json'
                for a in packet['subject']['payload']['evidence_attachments'])}
    report={'checks':checks,'passed':all(checks.values()),'actual_model_called':False,
            'source_subject_digest':source,'result':outcome,'review_status':status,'delivery':delivery,
            'scope':'Development acceptance added after generation; not held-out, physical or completed reviewer acceptance.'}
    atomic_json(result_path,report)
    print({'passed':report['passed'],'checks':checks,'report':str(result_path)})
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
