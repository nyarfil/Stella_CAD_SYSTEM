"""One bounded real Codex call proving exact JSON ingestion and native image viewing."""
from __future__ import annotations
import argparse,json,uuid
from pathlib import Path

from cadmcp_brain.req2cad.common import atomic_json
from cadmcp_brain.studio.provider import CodexProvider

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-model',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--evidence-root',type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=180)
    args=parser.parse_args(argv)
    if not args.execute_model:parser.error('One authenticated model call requires --execute-model.')
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    nonce='CADMCP-EVIDENCE-'+uuid.uuid4().hex
    evidence=output/'nonce-evidence.json';atomic_json(evidence,{'nonce':nonce,'source':'direct text attachment; not present in the summary'})
    schema={'type':'object','additionalProperties':False,'properties':{
        'nonce':{'type':'string'},'mounting_holes_visible':{'type':'integer','minimum':0,'maximum':10},
        'central_shaft_visible':{'type':'boolean'},'image_observation':{'type':'string'},
        'shell_command_used':{'type':'boolean'}},
        'required':['nonce','mounting_holes_visible','central_shaft_visible','image_observation','shell_command_used']}
    provider=CodexProvider(output/'calls',max_calls=1,timeout_seconds=args.timeout,evidence_root=args.evidence_root)
    result=provider.generate(
        'Read the exact attached JSON and copy its nonce. Inspect the attached assembly image directly. Count only the two small mounting holes in the rectangular plate; do not count the central guide bore. State whether the gold central shaft is visible. Do not run a shell command.',
        schema,{'nonce_evidence_file':str(evidence),'assembly_image_file':str(args.image.resolve())},role='evidence_probe')
    call=next((output/'calls').glob('*/receipt.json'));receipt=json.loads(call.read_text('utf-8'))
    stderr=(call.parent/'stderr.log').read_text('utf-8',errors='replace')
    passed=(result['nonce']==nonce and result['mounting_holes_visible']==2 and result['central_shaft_visible'] is True
            and result['shell_command_used'] is False and 'blocked by policy' not in stderr
            and receipt['embedded_text_evidence_files']==1 and receipt['attached_image_files']==1)
    report={'passed':passed,'actual_model_called':True,'json_directly_supplied':True,'image_natively_attached':True,
            'step_directly_inspected':False,'physical_performance_certified':False,'result':result,'receipt':receipt}
    atomic_json(output/'EVIDENCE_PROBE_RESULT.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
