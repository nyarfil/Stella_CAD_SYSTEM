"""Owner-launched bounded multi-role run. MCP mode never spawns agents itself."""
from __future__ import annotations
import argparse,json,sys,uuid,os
from pathlib import Path
from ..engine import Brain
from ..api import Tools
from ..errors import BrainError
from .autopilot import Autopilot
from .provider import CodexProvider, probe_codex
from .cursor_provider import CursorProvider, probe_cursor

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',type=Path,required=True)
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('status')
    s=sub.add_parser('schema');s.add_argument('kind',choices=['brief','matrix','recipe','review','reply'])
    check=sub.add_parser('provider-check',help='Probe CLI flags/version only; no model call or login.').add_argument_group('Cursor')
    check.add_argument('--cursor-agent',default=None)
    check.add_argument('--provider',choices=['cursor','codex'],default='cursor')
    check.add_argument('--codex',default='codex')
    check.add_argument('--cursor-permissions-only',action='store_true',help='Owner explicitly chooses ask/deny rules without requesting an OS sandbox.')
    a=sub.add_parser('autopilot')
    a.add_argument('--project',required=True)
    a.add_argument('--request-file',type=Path,help='UTF-8 request to open a NEW project. Omit for an existing project.')
    a.add_argument('--execute-model',action='store_true',help='Explicitly authorize calls through the selected, already-authenticated CLI.')
    a.add_argument('--provider',choices=['codex','cursor'],default='codex',help='Choose a provider explicitly; never fall back to another provider.')
    a.add_argument('--codex',default='codex');a.add_argument('--model')
    a.add_argument('--cursor-agent',default=None,help='Cursor Agent executable (auto: cursor-agent, then agent); not the cursor editor launcher.')
    a.add_argument('--cursor-permissions-only',action='store_true',help='Explicitly omit --sandbox enabled for Cursor; ask mode and deny rules remain. No OS isolation guarantee.')
    a.add_argument('--search-mode',choices=['semantic','lexical'],default='semantic')
    a.add_argument('--design-route',choices=['auto','reference_required','original'],default='auto',help='References inform design; original explicitly skips catalog retrieval.')
    a.add_argument('--max-replans',type=int,choices=[0,1,2],default=1)
    a.add_argument('--max-calls',type=int,default=32)
    a.add_argument('--per-call-seconds',type=int,default=600)
    a.add_argument('--max-reference-builds',type=int,default=8)
    a.add_argument('--max-repairs',type=int,default=1)
    a.add_argument('--debate-rounds',type=int,choices=[1,2,3],default=2)
    a.add_argument('--protect-artifact',action='append',default=[])
    a.add_argument('--editable-reference',action='append',default=[])
    a.add_argument('--review-workers',type=int,choices=[1,2,3],default=1)
    args=p.parse_args(argv)
    if args.command=='autopilot' and not args.execute_model:
        p.error('No model was called. Supply --execute-model to authorize an owner-side run, or use host-driven MCP tools.')
    try:
        if args.command=='provider-check':
            value=probe_codex(args.codex) if args.provider=='codex' else probe_cursor(args.cursor_agent,require_sandbox=not args.cursor_permissions_only)
            print(json.dumps(value,ensure_ascii=False,indent=2));return 0
        if args.command=='autopilot' and args.provider!='cursor' and (args.cursor_agent or args.cursor_permissions_only):
            raise BrainError('PROVIDER_OPTIONS','Cursor options require --provider cursor.')
        tools=Tools(Brain(args.workspace))
        if args.command=='status':value=tools.brain_fs_status()
        elif args.command=='schema':value=tools.brain_studio_schema({'brief':'FunctionBrief','matrix':'Matrix','recipe':'Recipe','review':'Review','reply':'Reply'}[args.kind])
        else:
            if args.protect_artifact:os.environ['CADMCP_PROTECTED_ARTIFACT_IDS']=json.dumps(args.protect_artifact)
            if args.editable_reference:os.environ['CADMCP_EDITABLE_REFERENCE_IDS']=json.dumps(args.editable_reference)
            folder=args.workspace.resolve()/'agent-runs'/uuid.uuid4().hex
            if args.provider=='cursor':
                provider=CursorProvider(folder/'calls',executable=args.cursor_agent,model=args.model,max_calls=args.max_calls,timeout_seconds=args.per_call_seconds,evidence_root=args.workspace,require_sandbox=not args.cursor_permissions_only)
            else:
                provider=CodexProvider(folder/'calls',executable=args.codex,model=args.model,max_calls=args.max_calls,timeout_seconds=args.per_call_seconds,evidence_root=args.workspace)
            if args.request_file:
                if args.request_file.stat().st_size>128*1024:raise BrainError('REQUEST_SIZE','Request file exceeds 128 KiB.')
                tools.brain_open(args.project,args.request_file.read_text('utf-8'))
            run=Autopilot(tools,provider,folder,search_mode=args.search_mode,max_reference_builds=args.max_reference_builds,
                          max_repairs=args.max_repairs,review_workers=args.review_workers,debate_rounds=args.debate_rounds,
                          design_route=args.design_route,max_replans=args.max_replans)
            value=run.run(args.project)
        print(json.dumps(value,ensure_ascii=False,indent=2));return 0
    except (BrainError,ValueError,OSError) as exc:
        print(json.dumps({'ok':False,'error':exc.as_dict() if isinstance(exc,BrainError) else {'type':type(exc).__name__,'message':str(exc)}},ensure_ascii=False),file=sys.stderr)
        return 1
if __name__=='__main__':raise SystemExit(main())
