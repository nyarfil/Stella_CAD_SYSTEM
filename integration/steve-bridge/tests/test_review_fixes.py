"""Tests for the security-review fixes (blocking 1 and 2, plus nits)."""
import ast
import http.client
import json
import os
import socket
import subprocess
import sys

import pytest
from steve import stella_seam
from stella_steve_bridge import policy
from stella_steve_bridge.audit import AuditLog, MAX_CODE_CHARS, sha256

from test_bridge_e2e import GOOD_EXEC, audit_lines, raw

SCRATCH = os.path.abspath(os.path.join(os.sep, "tmp_scratch_test"))


def codes(src, mode):
    return {v["code"] for v in policy.check(src, mode, SCRATCH)}


# ---------------- blocking 1a: policy rejects document/Data Panel/export access (both modes)
ATTRS = ["documents", "close", "save", "saveAs", "saveCopyAs", "dataFile", "data", "exportManager",
         "commandDefinitions", "activate"]


@pytest.mark.parametrize("mode", ["query", "execute"])
@pytest.mark.parametrize("attr", ATTRS)
def test_attribute_access_rejected(attr, mode):
    assert "document_access" in codes("def run(c):\n    return c['app'].%s\n" % attr, mode)


@pytest.mark.parametrize("mode", ["query", "execute"])
@pytest.mark.parametrize("name", [a for a in ATTRS])
def test_string_constants_rejected(name, mode):
    assert "document_access" in codes("def run(c):\n    return getattr(c['app'], '%s')\n" % name, mode)
    assert "document_access" in codes("def run(c):\n    return c['%s']\n" % name, mode)


@pytest.mark.parametrize("mode", ["query", "execute"])
def test_documents_open_and_activate_chains_rejected(mode):
    assert "document_access" in codes("def run(c):\n    c['app'].documents.open(f)\n", mode)
    assert "document_access" in codes("def run(c):\n    c['app'].documents.item(1).activate()\n", mode)
    assert "document_access" in codes("def run(c):\n    return c['data']\n", mode)
    assert "document_access" in codes("def run(c):\n    return c['document'].dataFile\n", mode)
    assert "document_access" in codes("from pathlib import Path\ndef run(c):\n    Path('a').open()\n", mode)
    assert codes("def run(c):\n    return [b.name for b in c['root'].bRepBodies]\n", mode) == set()


# ---------------- blocking 1a: 'data' removed from the Stella exec context by the seam
def test_data_removed_from_context_for_stella_jobs(env):
    _, inspected = raw(env, "inspect")
    status, result = raw(env, "query", {"document_id": inspected["document_id"], "title": "t",
                                        "code": "def run(c):\n    return [c['data'], c['app'].data.marker]\n"})
    assert result["ok"] and result["result"] == [None, "cloud-data"]   # app.data still exists: policy blocks the attribute


# ---------------- blocking 1b: open-document list before/after
SNEAKY = ("def run(context):\n"
          "    docs = getattr(context['app'], 'docu' + 'ments')\n"   # evades the static policy on purpose
          "    docs.item(1).isModified = True\n"
          "    return 'touched'\n")


def test_clean_execute_reports_open_documents_unchanged(env):
    payload, is_error = env.gateway().handle("stella_fusion_execute", {"title": "ok", "code": GOOD_EXEC})
    assert not is_error
    docs = payload["open_documents"]
    assert docs["changed"] is False
    assert [d["name"] for d in docs["before"]] == ["SANDBOX", "PRODUCTION"] == [d["name"] for d in docs["after"]]
    lines = audit_lines(env)
    decision = [l for l in lines if l.get("decision") == "allow" and l["tool"] == "stella_fusion_execute"][0]
    result = [l for l in lines if l.get("phase") == "result" and l["tool"] == "stella_fusion_execute"][0]
    assert decision["open_documents_before"] and result["open_documents_after"]


def test_other_document_change_is_flagged_as_violation(env):
    payload, is_error = env.gateway().handle("stella_fusion_execute", {"title": "x", "code": SNEAKY})
    assert is_error and payload["ok"] is False and payload["original_ok"] is True
    assert payload["errorCode"] == "policy_violation_other_documents_changed"
    assert payload["open_documents"]["changed"] is True and payload["policy_violation"]["diff"]
    assert env.other.isModified is True
    lines = audit_lines(env)
    assert any(l.get("phase") == "violation" and l["violation"] == "other_documents_changed" for l in lines)
    assert any(l.get("open_documents_after") for l in lines)


def test_closed_document_is_flagged(env):
    code = ("def run(context):\n    docs = getattr(context['app'], 'docu' + 'ments')\n"
            "    docs._items.pop()\n    return 1\n")
    payload, is_error = env.gateway().handle("stella_fusion_execute", {"title": "x", "code": code})
    assert is_error and payload["errorCode"] == "policy_violation_other_documents_changed"


def test_pinned_document_own_modification_is_not_a_violation(env):
    code = ("def run(context):\n    getattr(context['app'], 'docu' + 'ments').item(0).isModified = True\n    return 1\n")
    payload, is_error = env.gateway().handle("stella_fusion_execute", {"title": "x", "code": code})
    assert not is_error and payload["open_documents"]["changed"] is False


def test_snapshot_failure_refuses_execute(env):
    gw = env.gateway()
    gw._open_documents = lambda doc_id, timeout=30: None
    payload, is_error = gw.handle("stella_fusion_execute", {"title": "x", "code": GOOD_EXEC})
    assert is_error and payload["errorCode"] == "denied_document_snapshot_failed"
    assert env.doc.design.log == []


# ---------------- blocking 2: denial message names the active document
def test_denial_messages_contain_actual_name(env):
    env.doc.name = "My Sandbox v3"
    gw = env.gateway()
    code = "def run(c):\n    return 1\n"
    for tool, args in (("stella_fusion_execute", {"title": "t", "code": code}),
                       ("stella_fusion_query", {"title": "t", "code": code}),
                       ("stella_fusion_inspect", {}), ("stella_fusion_viewport", {})):
        payload, is_error = gw.handle(tool, args)
        assert is_error and payload["errorCode"] == "denied_document_not_allowed"
        assert "'My Sandbox v3'" in payload["error"], tool
        assert payload["document"]["name"] == "My Sandbox v3"


# ---------------- nits
def test_outcome_unknown_on_seam_timeout(env):
    gw = env.gateway()
    real = gw._call

    def call(route, body=None, timeout=None):
        if route == "execute":
            return 504, {"ok": False, "errorCode": "cancelled"}
        return real(route, body, timeout)

    gw._call = call
    payload, is_error = gw.handle("stella_fusion_execute", {"title": "x", "code": GOOD_EXEC})
    assert is_error and payload["errorCode"] == "outcome_unknown" and "inspect the document" in payload["error"]
    assert any(l.get("outcome_unknown") for l in audit_lines(env))


def test_audit_truncates_code_keeps_hash_and_rotates(tmp_path):
    path = str(tmp_path / "audit.jsonl")
    log = AuditLog(path, max_bytes=2000, keep=2)
    big = "x" * (MAX_CODE_CHARS + 500)
    log.write(tool="t", code=big)
    entry = json.loads(open(path, encoding="utf-8").read())
    assert entry["code_truncated"] is True and len(entry["code"]) == MAX_CODE_CHARS
    assert entry["code_sha256"] == sha256(big) and entry["code_chars"] == len(big)
    for i in range(10):
        log.write(tool="t", code="y" * 500, n=i)
    assert os.path.exists(path + ".1") and os.path.exists(path + ".2") and not os.path.exists(path + ".3")


def test_endpoint_json_removed_on_stop(env):
    assert (env.home / "endpoint.json").exists()
    stella_seam.stop()
    assert not (env.home / "endpoint.json").exists()


def test_failed_endpoint_write_shuts_server_down(env, tmp_path):
    stella_seam.stop()
    home = tmp_path / "broken"
    home.mkdir()
    (home / "config.json").write_text(json.dumps({"enabled": True}))
    (home / "endpoint.json").mkdir()           # writing the file will fail
    with pytest.raises(OSError):
        stella_seam.start(env.tools, home=home)
    assert stella_seam._state["server"] is None
    assert stella_seam.safe_start(env.tools, home=home) is None      # never raises into STEVE.run()
    assert "seam failed to start" in (home / "seam-error.log").read_text()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only socket option")
def test_exclusive_bind_on_windows(env):
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        with pytest.raises(OSError):
            probe.bind(("127.0.0.1", env.port))
    finally:
        probe.close()


def test_hook_in_steve_py_is_wrapped_in_try_except():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "addin", "STEVE", "STEVE.py"),
               encoding="utf-8").read()
    tree = ast.parse(src)
    run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run")
    tries = [n for n in ast.walk(run) if isinstance(n, ast.Try) and "stella_seam" in ast.unparse(n.body[0])]
    assert tries and tries[0].handlers and "safe_start" in ast.unparse(tries[0].body[0])


def test_token_file_restricted_to_owner(env):
    path = env.home / "token"
    assert path.read_text().strip() == env.token       # still readable by us
    if sys.platform == "win32":
        out = subprocess.run(["icacls", str(path)], capture_output=True, text=True).stdout
        principals = [l for l in out.splitlines() if ":(" in l]
        assert len(principals) == 1, out                # one ACE only
        assert "(I)" not in out                          # nothing inherited
        assert "Everyone" not in out and "Users" not in out and "Authenticated" not in out
    else:
        assert (os.stat(path).st_mode & 0o777) == 0o600
