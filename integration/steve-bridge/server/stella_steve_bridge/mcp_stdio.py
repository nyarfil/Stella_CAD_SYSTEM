"""Minimal, host-neutral MCP server over stdio (newline-delimited JSON-RPC 2.0).

Hand-written on purpose (stdlib only, no SDK/venv dependency) so the same
command works unchanged from Codex, Claude Code and Cursor. Only protocol frames
go to stdout; diagnostics go to stderr.
"""
import json
import sys

from . import __version__
from .gateway import TOOL_NAMES

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
PY_NOTE = ("Source must define def run(context). Fusion API lengths are centimetres; use the provided "
           "to_cm(mm) / to_mm(cm) helpers explicitly. Return JSON-compatible values under 24,000 characters.")

TOOLS = [
    {"name": "stella_fusion_health",
     "description": "Check that the STEVE seam inside Autodesk Fusion is reachable and report the active guard policy (read-only flag, allowed documents).",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "stella_fusion_inspect",
     "description": "Summarize the active Fusion document (name, document_id, products, design summary, selection). Refused for documents not on the allow-list.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "stella_fusion_query",
     "description": "Run read-only Python against the active Fusion document (no Undo group, mutating calls are rejected by a static policy). " + PY_NOTE,
     "inputSchema": {"type": "object", "properties": {
         "title": {"type": "string", "minLength": 1, "maxLength": 100, "description": "Short activity label."},
         "code": {"type": "string", "maxLength": 60000, "description": "Python source defining run(context)."},
         "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 120, "description": "Bridge wait limit (default 60)."}},
         "required": ["title", "code"], "additionalProperties": False}},
    {"name": "stella_fusion_execute",
     "description": "Run Python that modifies the active Fusion document inside one Undo-grouped command (rolled back as a unit on failure). Only for documents on the server's allow-list; refused in --read-only mode. The document is re-pinned right before and reported after execution. " + PY_NOTE,
     "inputSchema": {"type": "object", "properties": {
         "title": {"type": "string", "minLength": 1, "maxLength": 100, "description": "Short activity label."},
         "code": {"type": "string", "maxLength": 60000, "description": "Python source defining run(context)."},
         "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 120, "description": "Bridge wait limit (default 60)."}},
         "required": ["title", "code"], "additionalProperties": False}},
    {"name": "stella_fusion_viewport",
     "description": "Capture the Fusion viewport to a PNG file on disk and return only its path and size.",
     "inputSchema": {"type": "object", "properties": {
         "view": {"type": "string", "enum": ["current", "front", "top", "right", "left", "back", "bottom", "isometric"], "default": "current"},
         "selection_index": {"type": "integer", "minimum": 0, "maximum": 11},
         "entity_token": {"type": "string"},
         "isolate": {"type": "boolean", "default": False}},
         "additionalProperties": False}},
    {"name": "stella_fusion_api_help",
     "description": "Offline help for the installed Autodesk Fusion Python API (signature, docstring, members). Example path: adsk.core.Application. No web access.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "maxLength": 250, "description": "Dotted path such as 'adsk' or 'adsk.fusion.ExtrudeFeatures'."}},
         "required": ["path"], "additionalProperties": False}},
]
assert tuple(t["name"] for t in TOOLS) == TOOL_NAMES


def _log(message):
    print("[stella-steve-bridge] " + message, file=sys.stderr, flush=True)


class McpServer:
    def __init__(self, gateway):
        self.gateway = gateway

    def _ok(self, request_id, result):
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _err(self, request_id, code, message):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def handle_message(self, message):
        """Return a response dict, or None for notifications."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return self._err(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid Request")
        method, params = message.get("method"), message.get("params") or {}
        has_id = "id" in message
        request_id = message.get("id")
        if not isinstance(method, str):
            return self._err(request_id, -32600, "Invalid Request") if has_id else None
        if not has_id:  # notification (initialized, cancelled, ...)
            return None
        if method == "initialize":
            wanted = params.get("protocolVersion") if isinstance(params, dict) else None
            version = wanted if wanted in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
            return self._ok(request_id, {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                                         "serverInfo": {"name": "stella-steve-bridge", "version": __version__}})
        if method == "ping":
            return self._ok(request_id, {})
        if method == "tools/list":
            return self._ok(request_id, {"tools": TOOLS})
        if method == "tools/call":
            name = params.get("name") if isinstance(params, dict) else None
            args = params.get("arguments") if isinstance(params, dict) else None
            if name not in TOOL_NAMES:
                return self._err(request_id, -32602, "Unknown tool: %s" % name)
            if args is None:
                args = {}
            if not isinstance(args, dict):
                return self._ok(request_id, self._result({"ok": False, "errorCode": "invalid_arguments",
                                                          "error": "arguments must be an object"}, True))
            schema = next(t for t in TOOLS if t["name"] == name)["inputSchema"]
            unknown = set(args) - set(schema["properties"])
            missing = [k for k in schema.get("required", []) if k not in args]
            if unknown or missing:
                return self._ok(request_id, self._result({"ok": False, "errorCode": "invalid_arguments",
                                "error": "unknown=%s missing=%s" % (sorted(unknown), missing)}, True))
            try:
                payload, is_error = self.gateway.handle(name, args)
            except Exception as exc:  # last resort: never crash the protocol loop
                _log("internal error in %s: %s" % (name, type(exc).__name__))
                payload, is_error = {"ok": False, "errorCode": "internal_error", "error": type(exc).__name__}, True
            return self._ok(request_id, self._result(payload, is_error))
        return self._err(request_id, -32601, "Method not found: %s" % method)

    def _result(self, payload, is_error):
        return {"content": [{"type": "text", "text": self.gateway.render(payload)}], "isError": bool(is_error)}

    def serve(self, stdin=None, stdout=None):
        stdin = stdin or sys.stdin.buffer
        stdout = stdout or sys.stdout.buffer
        for raw in stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                message = json.loads(raw.decode("utf-8"))
            except ValueError:
                responses = [self._err(None, -32700, "Parse error")]
            else:
                batch = message if isinstance(message, list) else [message]
                responses = [r for r in (self.handle_message(m) for m in batch) if r is not None]
                if not isinstance(message, list):
                    responses = responses[:1]
            for response in responses:
                stdout.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
                stdout.flush()
