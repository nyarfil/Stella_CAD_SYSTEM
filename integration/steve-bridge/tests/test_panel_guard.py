"""Stella policy for STEVE's own chat panel: allow-listed documents, optional read-only."""
import json
import threading

import pytest
from steve import stella_seam
from steve.fusion_tools import FusionTools

import fakes

EXEC = {"title": "box", "code": "def run(context):\n    context['design'].log.append('panel-edit')\n    return {}\n",
        "execution_mode": "command"}
QUERY = {"title": "q", "code": "def run(context):\n    return {'n': 1}\n"}


@pytest.fixture
def guarded(tmp_path):
    def build(panel, config_extra=None):
        doc, other = fakes.Document("SANDBOX"), fakes.Document("PRODUCTION")
        app = fakes.FakeApp([doc, other])
        home = tmp_path / "seam"
        home.mkdir(exist_ok=True)
        (home / "config.json").write_text(json.dumps({"panel": panel, **(config_extra or {})}), encoding="utf-8")
        stella_seam.stop()
        tools = FusionTools(app, home=tmp_path / "steve-data")
        stella_seam.start(tools, home=home)  # not enabled: only the panel guard is installed
        return doc, other, app, tools
    built = []
    yield lambda *a, **k: built.append(build(*a, **k)) or built[-1]
    for _, _, app, tools in built:
        tools.close()
        app.stop()
    stella_seam.stop()


def panel_call(tools, tool, args):
    """A call as the chat panel makes it: plain completion callback, no `stella` marker."""
    done, box = threading.Event(), {}

    def complete(result):
        box["r"] = result
        done.set()
    arguments = dict(args, document_id=tools.selection_context()["document_id"])  # the panel pins the document at Send
    tools.submit(tool, arguments, complete, lambda: False)
    assert done.wait(10), "panel call did not complete"
    return box["r"]


def test_panel_blocked_on_non_allowed_document(guarded):
    doc, other, app, tools = guarded({"allowedDocuments": ["SANDBOX"]})
    app.switch_to(other)
    result = panel_call(tools, "fusion_execute_python", EXEC)
    assert result["ok"] is False and result["errorCode"] == "panel_document_not_allowed"
    assert other.design.log == []
    assert panel_call(tools, "fusion_query_python", QUERY)["errorCode"] == "panel_document_not_allowed"


def test_panel_allowed_on_listed_document(guarded):
    doc, other, app, tools = guarded({"allowedDocuments": ["SANDBOX"]})
    result = panel_call(tools, "fusion_execute_python", EXEC)
    assert result.get("ok") is True, result
    assert doc.design.log == ["panel-edit"]


def test_read_only_panel_can_query_but_not_modify(guarded):
    doc, other, app, tools = guarded({"readOnly": True})
    assert panel_call(tools, "fusion_execute_python", EXEC)["errorCode"] == "panel_read_only"
    assert doc.design.log == []
    assert panel_call(tools, "fusion_query_python", QUERY).get("ok") is True


def test_no_panel_config_keeps_upstream_behaviour(guarded):
    doc, other, app, tools = guarded(None)
    app.switch_to(other)
    assert panel_call(tools, "fusion_execute_python", EXEC).get("ok") is True


def test_guard_not_installed_twice(guarded):
    doc, other, app, tools = guarded({"allowedDocuments": ["SANDBOX"]})
    first = tools.run_script
    stella_seam.install_panel_guard(tools, stella_seam.panel_policy({"panel": {"allowedDocuments": ["SANDBOX"]}}))
    assert tools.run_script is first


def test_addin_folder_config_is_the_fallback(tmp_path, monkeypatch):
    fallback = tmp_path / "stella-seam.json"
    fallback.write_text(json.dumps({"enabled": True, "port": 1}), encoding="utf-8")
    monkeypatch.setattr(stella_seam, "ADDIN_CONFIG", fallback)
    empty = tmp_path / "home"
    empty.mkdir()
    assert stella_seam.load_config(empty) == {"enabled": True, "port": 1}
    (empty / "config.json").write_text(json.dumps({"enabled": False}), encoding="utf-8")
    assert stella_seam.load_config(empty) == {"enabled": False}
