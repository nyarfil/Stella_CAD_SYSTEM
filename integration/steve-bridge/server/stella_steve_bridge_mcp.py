"""Entry point: stdio MCP server for the Stella <-> STEVE Fusion bridge.

  python stella_steve_bridge_mcp.py --allow-document NAME [--read-only] [--allow-read-any]
         [--home DIR] [--port N] [--token-file FILE] [--audit-log FILE] [--scratch-dir DIR]

Allowed documents may also come from STELLA_FUSION_ALLOWED_DOCUMENTS (JSON array).
Stdout carries MCP frames only; everything else goes to stderr.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stella_steve_bridge.gateway import Config, Gateway  # noqa: E402
from stella_steve_bridge.mcp_stdio import McpServer  # noqa: E402


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--allow-document", action="append", default=[],
                        help="exact document name allowed for execute (repeatable)")
    parser.add_argument("--read-only", action="store_true", help="refuse stella_fusion_execute")
    parser.add_argument("--allow-read-any", action="store_true", help="allow inspect/query/viewport on any document")
    parser.add_argument("--home", help="seam data folder (default: %%LOCALAPPDATA%%/STEVE/stella-seam)")
    parser.add_argument("--port", type=int, help="seam port (default: read endpoint.json)")
    parser.add_argument("--token-file", help="bearer token file (default: <home>/token)")
    parser.add_argument("--audit-log", help="audit JSONL path (default: <home>/audit.jsonl)")
    parser.add_argument("--scratch-dir", help="only directory where submitted code may write files")
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser.parse_args(argv)


def build_config(args):
    allowed = list(args.allow_document)
    env = os.environ.get("STELLA_FUSION_ALLOWED_DOCUMENTS")
    if env:
        value = json.loads(env)
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise SystemExit("STELLA_FUSION_ALLOWED_DOCUMENTS must be a JSON array of strings")
        allowed += value
    return Config(allow_documents=allowed, read_only=args.read_only, allow_read_any=args.allow_read_any,
                  home=args.home, port=args.port, token_file=args.token_file, audit_path=args.audit_log,
                  scratch_dir=args.scratch_dir, default_timeout=args.timeout)


def main(argv=None):
    config = build_config(parse_args(argv))
    # Anything printed by library code must not corrupt the protocol stream.
    out = sys.stdout.buffer
    sys.stdout = sys.stderr
    McpServer(Gateway(config)).serve(sys.stdin.buffer, out)


if __name__ == "__main__":
    main()
