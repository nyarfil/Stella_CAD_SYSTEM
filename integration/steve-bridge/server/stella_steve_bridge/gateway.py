"""Guard layer: every Stella-originated Fusion call passes through Gateway.handle().

Order for query/execute: read-only check -> identify the active document ->
allow-list -> code policy -> forward (document_id binds the call to that exact
document on Fusion's main thread) -> report the document before AND after.
There is NO fallback to any other CAD or Fusion route on failure.
"""
import json
import os
import re
import sys
import time

from . import policy
from .audit import AuditLog
from .client import BridgeUnavailable, SeamClient

TOOL_NAMES = ("stella_fusion_health", "stella_fusion_inspect", "stella_fusion_query",
              "stella_fusion_execute", "stella_fusion_viewport", "stella_fusion_api_help")
# Trusted, Stella-authored snapshot script (never user code, so not subject to the user-code policy).
OPEN_DOCS_SCRIPT = (
    "def run(context):\n"
    "    docs = context['app'].documents\n"
    "    return [{'name': docs.item(i).name, 'saved': bool(docs.item(i).isSaved),\n"
    "             'modified': bool(docs.item(i).isModified)} for i in range(docs.count)]\n")
API_PATH_RE = re.compile(r"^(adsk|steve)(\.[A-Za-z][A-Za-z0-9_]*){0,6}$")
VIEWS = ("current", "front", "top", "right", "left", "back", "bottom", "isometric")


def default_home():
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "STEVE", "stella-seam")


class Config:
    def __init__(self, allow_documents=(), read_only=False, allow_read_any=False, home=None, port=None,
                 token_file=None, audit_path=None, scratch_dir=None, default_timeout=60.0,
                 max_text=100000):
        self.allow_documents = tuple(allow_documents)
        self.read_only = read_only
        self.allow_read_any = allow_read_any
        self.home = home or default_home()
        self.port = port
        self.token_file = token_file or os.path.join(self.home, "token")
        self.audit_path = audit_path or os.path.join(self.home, "audit.jsonl")
        self.scratch_dir = scratch_dir or os.path.join(self.home, "scratch")
        self.default_timeout = default_timeout
        self.max_text = max_text


def error(code, message, **extra):
    return {"ok": False, "errorCode": code, "error": message, **extra}


class Gateway:
    def __init__(self, config, client=None, audit=None):
        self.cfg = config
        self._client = client
        self.audit = audit or AuditLog(config.audit_path)

    # ---- connection
    def client(self):
        if self._client is not None:
            return self._client
        port = self.cfg.port
        if port is None:
            with open(os.path.join(self.cfg.home, "endpoint.json"), encoding="utf-8") as handle:
                port = json.load(handle)["port"]
        with open(self.cfg.token_file, encoding="utf-8") as handle:
            token = handle.read().strip()
        return SeamClient(int(port), token)

    def _call(self, route, body=None, timeout=None):
        timeout = timeout or self.cfg.default_timeout
        try:
            client = self.client()
        except (OSError, ValueError, KeyError) as exc:
            raise BridgeUnavailable("seam endpoint/token not available: %s" % type(exc).__name__)
        status, payload = client.call(route, body, timeout=timeout + 5)
        return status, payload

    # ---- helpers
    def _identity(self, payload):
        return {"name": payload.get("name"), "id": payload.get("document_id")}

    def _allowed_write(self, name):
        return name is not None and name in self.cfg.allow_documents

    def _allowed_read(self, name):
        return self.cfg.allow_read_any or self._allowed_write(name)

    def _finish(self, tool, started, payload, doc=None, **audit_extra):
        self.audit.write(tool=tool, phase="result", document=doc, status="ok" if payload.get("ok") else "error",
                         error_code=payload.get("errorCode"), duration_ms=int((time.time() - started) * 1000),
                         **audit_extra)
        return payload

    def _deny(self, tool, reason, doc=None, code=None, message=None, **extra):
        self.audit.write(tool=tool, phase="decision", decision="deny", reason=reason, document=doc, code=code)
        return error("denied_" + reason, message or reason, document=doc, **extra), True

    # ---- dispatch
    def handle(self, tool, args):
        """Return (payload, is_error). Never raises for expected failures."""
        started = time.time()
        try:
            if tool == "stella_fusion_health":
                payload = self._health(started)
            elif tool == "stella_fusion_inspect":
                payload = self._inspect(started)
            elif tool in ("stella_fusion_query", "stella_fusion_execute"):
                payload = self._python(tool, args, started)
            elif tool == "stella_fusion_viewport":
                payload = self._viewport(args, started)
            elif tool == "stella_fusion_api_help":
                payload = self._api_help(args, started)
            else:
                return error("unknown_tool", tool), True
        except BridgeUnavailable as exc:
            self.audit.write(tool=tool, phase="result", status="error", error_code="bridge_unavailable",
                             reason=str(exc))
            payload = error("bridge_unavailable", "STEVE seam is not reachable (%s). Is Fusion running with the "
                            "STEVE add-in and stella-seam enabled? No other route was tried." % exc)
        is_error = isinstance(payload, tuple)
        if is_error:
            payload = payload[0]
        return payload, (is_error or not payload.get("ok", False))

    # ---- tools
    def _health(self, started):
        self.audit.write(tool="stella_fusion_health", phase="decision", decision="allow")
        status, seam = self._call("health", timeout=10)
        payload = {"ok": bool(seam.get("ok")), "seam": seam,
                   "policy": {"read_only": self.cfg.read_only, "allow_read_any": self.cfg.allow_read_any,
                              "allowed_documents": list(self.cfg.allow_documents)}}
        return self._finish("stella_fusion_health", started, payload)

    def _open_documents(self, doc_id, timeout=30):
        """Names + saved/modified flags of every open Fusion document, or None if it cannot be read."""
        body = {"document_id": doc_id, "title": "stella: list open documents", "code": OPEN_DOCS_SCRIPT,
                "_timeout_seconds": timeout}
        status, result = self._call("query", body, timeout=timeout)
        value = result.get("result") if result.get("ok") else None
        return value if isinstance(value, list) else None

    @staticmethod
    def _documents_diff(before, after, pinned_name):
        """Differences in the open-document list, ignoring the pinned document's own modified/saved flags."""
        def strip(items):
            items = [dict(i) for i in items]
            for item in items:
                if item["name"] == pinned_name:
                    item.pop("modified", None)
                    item.pop("saved", None)
                    break
            return sorted(json.dumps(i, sort_keys=True) for i in items)

        a, b = strip(before), strip(after)
        return {"removed_or_changed": [x for x in a if x not in b], "added_or_changed": [x for x in b if x not in a]} \
            if a != b else None

    def _identify(self, timeout):
        status, payload = self._call("inspect", {"_timeout_seconds": timeout}, timeout=timeout)
        return payload

    def _inspect(self, started):
        tool = "stella_fusion_inspect"
        payload = self._identify(30)
        if not payload.get("ok"):
            return self._finish(tool, started, payload)
        doc = self._identity(payload)
        if not self._allowed_read(doc["name"]):
            return self._deny(tool, "document_not_allowed", doc, message=(
                "Active document %r is not on the allow-list; inspection details withheld." % doc["name"]))
        self.audit.write(tool=tool, phase="decision", decision="allow", document=doc)
        return self._finish(tool, started, payload, doc)

    def _python(self, tool, args, started):
        mode = "execute" if tool.endswith("execute") else "query"
        title, code = args.get("title"), args.get("code")
        if not isinstance(title, str) or not 1 <= len(title) <= 100 or not isinstance(code, str):
            return error("invalid_arguments", "title (1..100 chars) and code (string) are required."), True
        timeout = args.get("timeout_seconds", self.cfg.default_timeout)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 120:
            return error("invalid_arguments", "timeout_seconds must be 1..120."), True
        if mode == "execute" and self.cfg.read_only:
            return self._deny(tool, "read_only", None, code, "Server started with --read-only; execute is refused.")
        if mode == "execute" and not self.cfg.allow_documents:
            return self._deny(tool, "no_allowlist", None, code,
                              "Modeling is disabled until the owner passes --allow-document.")
        violations = policy.check(code, mode, self.cfg.scratch_dir)
        if violations:
            first = "; ".join("line %s: %s" % (v["line"], v["message"]) for v in violations[:5])
            return self._deny(tool, "code_policy", None, code, "Code policy rejected the code: " + first,
                              violations=violations[:20])
        ident = self._identify(30)
        if not ident.get("ok"):
            return self._finish(tool, started, ident)
        before = self._identity(ident)
        allowed = self._allowed_write(before["name"]) if mode == "execute" else self._allowed_read(before["name"])
        if not allowed:
            return self._deny(tool, "document_not_allowed", before, code,
                              "Active document %r is not on the allow-list." % before["name"])
        docs_before = None
        if mode == "execute":
            docs_before = self._open_documents(before["id"])
            if docs_before is None:   # fail closed: cannot prove other documents stay untouched
                return self._deny(tool, "document_snapshot_failed", before, code,
                                  "Could not read the open-document list before execution; execute refused.")
        self.audit.write(tool=tool, phase="decision", decision="allow", document=before, code=code, title=title,
                         open_documents_before=docs_before)
        body = {"document_id": before["id"], "title": title,
                "code": policy.with_unit_helpers(code), "_timeout_seconds": timeout}
        try:
            status, result = self._call(mode, body, timeout=timeout)
        except BridgeUnavailable as exc:
            if mode != "execute":
                raise
            self.audit.write(tool=tool, phase="result", status="error", error_code="outcome_unknown",
                             document=before, outcome_unknown=True, reason=str(exc))
            return error("outcome_unknown", "The bridge connection failed during execute; the outcome is unknown. "
                         "Inspect the document before retrying. No other route was tried.", outcome="unknown")
        if mode == "execute" and status == 504:
            self.audit.write(tool=tool, phase="result", status="error", error_code="outcome_unknown",
                             document=before, outcome_unknown=True)
            return error("outcome_unknown", "Bridge timeout: the script may still be running or may have been applied. "
                         "Outcome unknown - inspect the document before retrying. No other route was tried.",
                         outcome="unknown")
        after = self._identity(result.get("document") or {})
        pinned = {"before": before, "after": after,
                  "unchanged": bool(after["id"]) and after["id"] == before["id"] and after["name"] == before["name"]}
        result.pop("document", None)
        result["pinned"] = pinned
        result["units_note"] = "Fusion API lengths are centimetres; use to_cm(mm) / to_mm(cm). No silent conversion."
        if not pinned["unchanged"] and result.get("ok"):
            result["warning"] = "The active document differs from the pinned one after execution; verify before continuing."
        extra = {}
        if mode == "execute":
            docs_after = self._open_documents(after["id"] or before["id"])
            diff = None if docs_after is not None and docs_before is not None else {"unverifiable": True}
            if docs_after is not None:
                diff = self._documents_diff(docs_before, docs_after, before["name"])
            result["open_documents"] = {"before": docs_before, "after": docs_after, "changed": diff is not None}
            extra = {"open_documents_before": docs_before, "open_documents_after": docs_after}
            if diff == {"unverifiable": True} and not result.get("ok"):
                # execute already failed/was refused (e.g. document_changed); keep that error, flag the gap
                result["open_documents"]["unverified"] = True
                diff = None
            if diff is not None:
                result["policy_violation"] = {"code": "other_documents_changed", "diff": diff, "message": (
                    "Open documents other than the pinned one differ before/after execution (or could not be "
                    "verified). Treat the session as compromised and inspect every open document.")}
                result["original_ok"] = result.get("ok")
                result["ok"] = False
                result["errorCode"] = "policy_violation_other_documents_changed"
                result["error"] = result["policy_violation"]["message"]
                self.audit.write(tool=tool, phase="violation", document=before, violation="other_documents_changed",
                                 diff=diff)
        return self._finish(tool, started, result, before, **extra)

    def _viewport(self, args, started):
        tool = "stella_fusion_viewport"
        view = args.get("view", "current")
        if view not in VIEWS:
            return error("invalid_arguments", "view must be one of %s" % ", ".join(VIEWS)), True
        ident = self._identify(30)
        if not ident.get("ok"):
            return self._finish(tool, started, ident)
        doc = self._identity(ident)
        if not self._allowed_read(doc["name"]):
            return self._deny(tool, "document_not_allowed", doc, message=(
                "Active document %r is not on the allow-list." % doc["name"]))
        self.audit.write(tool=tool, phase="decision", decision="allow", document=doc)
        body = {"document_id": doc["id"], "view": view, "_timeout_seconds": 60}
        for key, typ in (("selection_index", int), ("entity_token", str), ("isolate", bool)):
            if key in args:
                body[key] = args[key]
        status, result = self._call("viewport", body, timeout=60)
        if result.get("ok"):
            path = result.get("path", "")
            captures = os.path.normcase(os.path.abspath(os.path.join(self.cfg.home, "captures")))
            if not os.path.normcase(os.path.abspath(path)).startswith(captures + os.sep):
                result = error("viewport_capture_failed", "Capture path outside the capture folder was rejected.")
            else:
                result = {k: result[k] for k in ("ok", "path", "bytes", "width", "height", "view", "isolated") if k in result}
                result["document"] = doc
        return self._finish(tool, started, result, doc)

    def _api_help(self, args, started):
        tool = "stella_fusion_api_help"
        path = args.get("path")
        if not isinstance(path, str) or not API_PATH_RE.match(path):
            return error("invalid_arguments", "path must look like 'adsk.core.Application' (no leading underscores)."), True
        self.audit.write(tool=tool, phase="decision", decision="allow", path=path)
        status, result = self._call("api_help", {"path": path, "_timeout_seconds": 30}, timeout=30)
        return self._finish(tool, started, result)

    # ---- output shaping
    def render(self, payload):
        text = json.dumps(payload, ensure_ascii=False)
        if len(text) > self.cfg.max_text:
            text = json.dumps({"ok": payload.get("ok", False), "truncated": True, "originalChars": len(text),
                               "preview": text[: self.cfg.max_text // 2]}, ensure_ascii=False)
        return text
