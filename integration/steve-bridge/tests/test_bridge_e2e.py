"""End to end: Gateway -> loopback seam -> vendored STEVE FusionTools/runner -> fake Fusion."""
import hashlib
import http.client
import json
import os
import time

import pytest
from steve import stella_seam

GOOD_EXEC = ("def run(context):\n"
             "    context['design'].log.append('made-box')\n"
             "    return {'cm': to_cm(25.4), 'mm': to_mm(2.54)}\n")


def audit_lines(env_):
    path = os.path.join(str(env_.home), "audit.jsonl")
    return [json.loads(line) for line in open(path, encoding="utf-8")] if os.path.exists(path) else []


def raw(env_, route, body=None, headers=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", env_.port, timeout=10)
    base = {"Authorization": "Bearer " + env_.token, "Content-Type": "application/json"}
    base.update(headers or {})
    if host:
        base["Host"] = host
    for key in [k for k, v in base.items() if v is None]:
        del base[key]
    conn.request("POST", "/v1/" + route, json.dumps(body or {}), base)
    response = conn.getresponse()
    data = json.loads(response.read())
    conn.close()
    return response.status, data


# ---- health / token
def test_health(env):
    payload, is_error = env.gateway().handle("stella_fusion_health", {})
    assert not is_error and payload["ok"] and payload["seam"]["steve"]
    assert payload["policy"]["allowed_documents"] == ["SANDBOX"]


def test_token_required(env):
    assert raw(env, "health")[0] == 200
    assert raw(env, "health", headers={"Authorization": None})[0] == 401
    assert raw(env, "health", headers={"Authorization": "Bearer wrong"})[0] == 401
    assert raw(env, "health", headers={"Authorization": env.token})[0] == 401          # missing "Bearer "
    assert raw(env, "health", headers={"Origin": "http://evil.example"})[0] == 401     # browser CSRF
    assert raw(env, "health", host="evil.example:%d" % env.port)[0] == 401             # DNS rebinding
    assert raw(env, "nope")[0] == 404


def test_token_file_not_in_logs_or_responses(env):
    status, data = raw(env, "health")
    assert env.token not in json.dumps(data)
    env.gateway().handle("stella_fusion_health", {})
    assert env.token not in json.dumps(audit_lines(env))


def test_seam_disabled_by_default(env, tmp_path):
    stella_seam.stop()
    other = tmp_path / "off"
    other.mkdir()
    assert stella_seam.start(env.tools, home=other) is None


# ---- allow-list
def test_execute_allowed_document_runs_in_command_and_reports_pin(env):
    payload, is_error = env.gateway().handle("stella_fusion_execute", {"title": "box", "code": GOOD_EXEC})
    assert not is_error, payload
    assert payload["result"] == {"cm": pytest.approx(2.54), "mm": pytest.approx(25.4)}
    assert env.doc.design.log == ["made-box"]
    assert payload["executionMode"] == "command" and payload["commandCompleted"] is True
    assert payload["pinned"]["before"]["name"] == "SANDBOX"
    assert payload["pinned"]["after"]["name"] == "SANDBOX" and payload["pinned"]["unchanged"] is True
    assert env.app.execute_failed_flags == [False]


def test_execute_denied_on_non_allowed_document(env):
    env.app.switch_to(env.other)
    payload, is_error = env.gateway().handle("stella_fusion_execute", {"title": "x", "code": GOOD_EXEC})
    assert is_error and payload["errorCode"] == "denied_document_not_allowed"
    assert env.other.design.log == [] and env.app.execute_failed_flags == []


def test_exact_name_match_only(env):
    env.doc.name = "SANDBOX2"
    payload, is_error = env.gateway().handle("stella_fusion_execute", {"title": "x", "code": GOOD_EXEC})
    assert is_error and payload["errorCode"] == "denied_document_not_allowed"
    env.doc.name = "sandbox"
    payload, is_error = env.gateway().handle("stella_fusion_execute", {"title": "x", "code": GOOD_EXEC})
    assert is_error and payload["errorCode"] == "denied_document_not_allowed"


def test_no_allowlist_means_no_modeling(env):
    payload, is_error = env.gateway(allow_documents=[]).handle("stella_fusion_execute", {"title": "x", "code": GOOD_EXEC})
    assert is_error and payload["errorCode"] == "denied_no_allowlist"


def test_query_non_allowed_refused_unless_allow_read_any(env):
    env.app.switch_to(env.other)
    code = "def run(context):\n    return context['document'].name\n"
    payload, is_error = env.gateway().handle("stella_fusion_query", {"title": "q", "code": code})
    assert is_error and payload["errorCode"] == "denied_document_not_allowed"
    payload, is_error = env.gateway().handle("stella_fusion_inspect", {})
    assert is_error and payload["errorCode"] == "denied_document_not_allowed"
    payload, is_error = env.gateway(allow_read_any=True).handle("stella_fusion_query", {"title": "q", "code": code})
    assert not is_error and payload["result"] == "PRODUCTION"
    assert payload["executionMode"] == "query" and payload["undoGrouped"] is False
    # allow_read_any never opens writes
    payload, is_error = env.gateway(allow_read_any=True).handle("stella_fusion_execute", {"title": "x", "code": GOOD_EXEC})
    assert is_error and payload["errorCode"] == "denied_document_not_allowed"


def test_inspect_on_allowed_document(env):
    payload, is_error = env.gateway().handle("stella_fusion_inspect", {})
    assert not is_error and payload["name"] == "SANDBOX" and payload["document_id"]


# ---- read-only
def test_read_only_refuses_execute_but_allows_query(env):
    gw = env.gateway(read_only=True)
    payload, is_error = gw.handle("stella_fusion_execute", {"title": "x", "code": GOOD_EXEC})
    assert is_error and payload["errorCode"] == "denied_read_only"
    assert env.doc.design.log == []
    payload, is_error = gw.handle("stella_fusion_query", {"title": "q", "code": "def run(c):\n    return 7\n"})
    assert not is_error and payload["result"] == 7


# ---- code policy through the gateway
def test_code_policy_blocks_before_forwarding(env):
    payload, is_error = env.gateway().handle("stella_fusion_execute", {
        "title": "x", "code": "import socket\ndef run(c):\n    return 1\n"})
    assert is_error and payload["errorCode"] == "denied_code_policy"
    assert payload["violations"][0]["code"] == "banned_import"
    assert env.app.execute_failed_flags == []


# ---- pinned document
def test_stale_document_id_rejected_on_main_thread(env):
    """Even if a caller bypasses the gateway pre-check, STEVE re-checks document_id on the Fusion thread."""
    status, inspected = raw(env, "inspect")
    env.app.switch_to(env.other)
    status, result = raw(env, "execute", {"document_id": inspected["document_id"], "title": "t", "code": GOOD_EXEC})
    assert result["ok"] is False and result["errorCode"] == "document_changed"
    assert env.other.design.log == [] and env.doc.design.log == []


def test_document_switch_between_inspect_and_execute_is_caught(env):
    """Switch happens after the gateway identified SANDBOX: the execute must not run on PRODUCTION."""
    gw = env.gateway()
    real = gw._open_documents

    def snapshot_then_switch(doc_id, timeout=30):
        value = real(doc_id, timeout)
        env.app.switch_to(env.other)      # switch lands after the snapshot, before the execute is forwarded
        return value

    gw._open_documents = snapshot_then_switch
    payload, is_error = gw.handle("stella_fusion_execute", {"title": "x", "code": GOOD_EXEC})
    assert is_error and payload["errorCode"] == "document_changed"
    assert env.other.design.log == [] and env.doc.design.log == []


def test_document_switch_before_snapshot_fails_closed(env):
    gw = env.gateway()
    real = gw._identify

    def identify_then_switch(timeout):
        payload = real(timeout)
        env.app.switch_to(env.other)
        return payload

    gw._identify = identify_then_switch
    payload, is_error = gw.handle("stella_fusion_execute", {"title": "x", "code": GOOD_EXEC})
    assert is_error and payload["errorCode"] == "denied_document_snapshot_failed"
    assert env.other.design.log == [] and env.doc.design.log == []


# ---- rollback flag
def test_failure_sets_execute_failed_for_rollback(env):
    code = ("def run(context):\n"
            "    context['design'].log.append('half-done')\n"
            "    raise RuntimeError('boom')\n")
    payload, is_error = env.gateway().handle("stella_fusion_execute", {"title": "x", "code": code})
    assert is_error and payload["ok"] is False and payload["transactionAborted"] is True
    assert env.app.execute_failed_flags == [True]        # Fusion would abort the command transaction


# ---- units
def test_to_cm_rejects_strings_in_script(env):
    code = "def run(c):\n    return to_cm('5')\n"
    payload, is_error = env.gateway().handle("stella_fusion_query", {"title": "q", "code": code})
    assert is_error and "finite number" in payload["error"]


# ---- timeouts / sizes
def test_seam_timeout_returns_cancelled(env, tmp_path):
    stella_seam.stop()
    env.app._drop = True       # Fusion never services the custom event
    stella_seam.start(env.tools, home=env.home)
    env.port = json.loads((env.home / "endpoint.json").read_text())["port"]
    started = time.time()
    status, data = raw(env, "inspect", {"_timeout_seconds": 1})
    assert status == 504 and data["errorCode"] == "cancelled" and time.time() - started < 6


def test_result_truncated_by_runner_and_render_cap(env):
    code = "def run(c):\n    return 'x' * 200000\n"
    payload, is_error = env.gateway().handle("stella_fusion_query", {"title": "q", "code": code})
    assert not is_error and payload["resultTruncated"] is True
    small = env.gateway()
    small.cfg.max_text = 1000
    text = small.render({"ok": True, "result": "y" * 5000})
    assert json.loads(text)["truncated"] is True and len(text) < 1500


def test_request_body_cap(env):
    conn = http.client.HTTPConnection("127.0.0.1", env.port, timeout=10)
    conn.request("POST", "/v1/query", b"{}", {"Authorization": "Bearer " + env.token, "Content-Length": str(10 ** 7)})
    assert conn.getresponse().status == 400


def test_invalid_arguments_rejected_by_steve_validation(env):
    status, data = raw(env, "query", {"document_id": "x", "title": "t", "code": "def run(:\n"})
    assert status == 400 and data["ok"] is False
    status, data = raw(env, "execute", {"document_id": "x", "title": "t", "code": GOOD_EXEC, "execution_mode": "application"})
    assert status == 400


# ---- viewport / api help
def test_viewport_returns_path_and_size_only(env):
    payload, is_error = env.gateway().handle("stella_fusion_viewport", {"view": "current"})
    assert not is_error, payload
    assert os.path.isfile(payload["path"]) and payload["bytes"] > 8 and "imageUrl" not in payload
    assert payload["width"] > 0 and set(payload) <= {"ok", "path", "bytes", "width", "height", "view", "isolated", "document"}


def test_api_help_offline_and_path_validation(env):
    payload, is_error = env.gateway().handle("stella_fusion_api_help", {"path": "adsk"})
    assert not is_error and "namespaces" in payload
    payload, is_error = env.gateway().handle("stella_fusion_api_help", {"path": "adsk.__builtins__"})
    assert is_error and payload["errorCode"] == "invalid_arguments"


# ---- audit
def test_audit_log_content(env):
    gw = env.gateway()
    gw.handle("stella_fusion_execute", {"title": "ok-run", "code": GOOD_EXEC})
    gw.handle("stella_fusion_execute", {"title": "bad", "code": "import socket\ndef run(c):\n    pass\n"})
    env.app.switch_to(env.other)
    gw.handle("stella_fusion_execute", {"title": "wrong-doc", "code": GOOD_EXEC})
    lines = audit_lines(env)
    sha = hashlib.sha256(GOOD_EXEC.encode()).hexdigest()
    allow = [l for l in lines if l.get("decision") == "allow" and l["tool"] == "stella_fusion_execute"]
    assert len(allow) == 1 and allow[0]["code"] == GOOD_EXEC and allow[0]["code_sha256"] == sha
    assert allow[0]["document"]["name"] == "SANDBOX" and allow[0]["ts"].endswith("Z")
    results = [l for l in lines if l.get("phase") == "result" and l["tool"] == "stella_fusion_execute"]
    assert results and results[0]["status"] == "ok"
    denies = {l["reason"] for l in lines if l.get("decision") == "deny"}
    assert denies == {"code_policy", "document_not_allowed"}
    assert all("code_sha256" in l for l in lines if l.get("code"))


def test_bridge_unavailable_has_no_fallback(env, tmp_path):
    gw = env.gateway()
    gw.cfg.port = 1  # nothing listens
    payload, is_error = gw.handle("stella_fusion_health", {})
    assert is_error and payload["errorCode"] == "bridge_unavailable" and "No other route was tried" in payload["error"]
