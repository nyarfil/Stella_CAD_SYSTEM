"""Explicit one-call Codex structured-output smoke test; not a CAD quality benchmark."""
import argparse
import json
from pathlib import Path
import sys

from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio.provider import CodexProvider
from cadmcp_brain.req2cad.common import atomic_json


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-model',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=120)
    args=parser.parse_args(argv)
    if not args.execute_model:
        parser.error('This test makes one authenticated model call; --execute-model is required.')
    schema={'type':'object','additionalProperties':False,'properties':{
        'original_request':{'type':'string'},'physical_test_passed':{'type':'boolean'},
        'reason':{'type':'string'}},'required':['original_request','physical_test_passed','reason']}
    request='センサー台座の内側を変更せず、外形を維持してください。'
    context={'original_request':request,'physical_test_evidence':None}
    try:
        provider=CodexProvider(args.output/'calls',max_calls=1,timeout_seconds=args.timeout)
        result=provider.generate('Copy original_request exactly. No physical test was performed, so physical_test_passed must be false. Explain this in Japanese.',schema,context)
        passed=result['original_request']==request and result['physical_test_passed'] is False
        report={'passed':passed,'actual_model_called':True,'cad_quality_tested':False,
                'provider_version':provider.version,'response':result}
        atomic_json(args.output/'result.json',report)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 0 if passed else 1
    except (BrainError,OSError,ValueError) as exc:
        report={'passed':False,'error':exc.as_dict() if isinstance(exc,BrainError) else type(exc).__name__}
        atomic_json(args.output/'result.json',report)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
