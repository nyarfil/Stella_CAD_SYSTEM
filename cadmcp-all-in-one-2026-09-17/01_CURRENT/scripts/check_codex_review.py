"""One real Codex review of an existing isolated public-case demo; not a design benchmark."""
import argparse
import json
import os
from pathlib import Path

from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.req2cad.common import atomic_json
from cadmcp_brain.studio.provider import CodexProvider
from cadmcp_brain.studio.runtime import Review


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-model',action='store_true')
    parser.add_argument('--workspace',type=Path,required=True)
    args=parser.parse_args(argv)
    if not args.execute_model:
        parser.error('One authenticated model call requires --execute-model.')
    workspace=args.workspace.resolve()
    if not (workspace/'.public-cases-demo').is_file():
        parser.error('Only a marked isolated demo workspace is accepted.')
    demo=json.loads((workspace/'DEMO_RESULT.json').read_text('utf-8'))
    subject=demo['build']['subject_digest']
    os.environ['CADMCP_REQ2CAD_ROOT']=str(workspace/'knowledge/req2cad')
    tools=Tools(Brain(workspace))
    projects=tools.brain_projects()['projects']
    matches=[p for p in projects if any(s['subject_digest']==subject for s in tools.brain_studio_attempts(p['project_id'])['subjects'])]
    if len(matches)!=1:
        raise ValueError('Demo subject must belong to exactly one project.')
    project=matches[0];project_id=project['project_id'];revision=project['revision']
    packet=tools.brain_studio_review_packet(project_id,revision,subject,'verification')
    provider=CodexProvider(workspace/'codex-review-calls',max_calls=1,timeout_seconds=180,evidence_root=workspace)
    result=Review.model_validate(provider.generate(packet['instructions'],Review.model_json_schema(),packet,role='verification'))
    if result.role!='verification' or result.discussion_round!=1:
        raise ValueError('Unexpected role or discussion round.')
    receipt=tools.brain_studio_submit_review(project_id,revision,subject,result.model_dump())
    status=tools.brain_studio_review_status(project_id,revision,subject)
    report={'integration_passed':True,'actual_model_called':True,'all_five_roles_tested':False,
            'physical_performance_certified':False,'review':result.model_dump(),
            'receipt':receipt,'review_status':status}
    atomic_json(workspace/'CODEX_REVIEW_RESULT.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
