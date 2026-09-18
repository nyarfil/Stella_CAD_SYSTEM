from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
from .api import Tools
from .backend import AgentCADClient
from .engine import Brain
from .errors import BrainError
from .protocol import serve


def main(argv=None):
    parser=argparse.ArgumentParser(description="CAD design decision MCP sidecar; host LLM supplies semantic reasoning")
    parser.add_argument("--workspace",default=os.environ.get("CADMCP_WORKSPACE",str(Path.home()/".cadmcp-brain")))
    sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("serve",help="Run the MCP stdio transport")
    sub.add_parser("doctor",help="Show capabilities without making a backend call")
    schema=sub.add_parser("schema"); schema.add_argument("name",choices=["Brief","Concept","Concepts","Plan"])
    demo=sub.add_parser("demo",help="Replay supplied authored fixtures, not an LLM benchmark")
    demo.add_argument("--geometry",action="store_true")
    args=parser.parse_args(argv)
    try:
        allowed=json.loads(os.environ.get("CADMCP_AGENTCAD_ALLOWED_TOOLS","[]"))
        if not isinstance(allowed,list) or not all(isinstance(x,str) for x in allowed): raise BrainError("BACKEND_CONFIG","CADMCP_AGENTCAD_ALLOWED_TOOLS must be a JSON string array")
        tools=Tools(Brain(args.workspace),AgentCADClient(os.environ.get("CADMCP_AGENTCAD_URL"),allowed))
        if args.command=="serve": return serve(tools)
        if args.command=="doctor": result=tools.brain_doctor()
        elif args.command=="schema": result=tools.brain_schema(args.name)
        else:
            from .demo import run_demo
            result=run_demo(tools.brain,args.geometry)
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        return 0
    except (BrainError,ValueError) as exc:
        print(json.dumps({"error":exc.as_dict() if isinstance(exc,BrainError) else str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
