"""Claude provider: subscription model picker and newest-Claude-Code resolution (no real CLI is run)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addin" / "STEVE"))
from steve import claude_setup as cs  # noqa: E402


def test_parse_version():
    assert cs.parse_version("2.1.293 (Claude Code)\n") == (2, 1, 293)
    assert cs.parse_version("garbage") is None
    assert cs.parse_version("") is None


def fake_versions(monkeypatch, table):
    monkeypatch.setattr(cs, "binary_version", lambda path: table.get(str(path)))


def test_newest_claude_code_wins(monkeypatch, tmp_path):
    old, new = tmp_path / "old.exe", tmp_path / "new.exe"
    old.write_text("x"); new.write_text("x")
    monkeypatch.setattr(cs, "claude_candidates", lambda env: [old, new])
    fake_versions(monkeypatch, {str(old): (2, 1, 117), str(new): (2, 1, 293)})
    assert cs.resolve_claude(env={}) == [str(new)]


def test_unversioned_candidates_are_skipped(monkeypatch, tmp_path):
    broken, ok = tmp_path / "broken.exe", tmp_path / "ok.exe"
    broken.write_text("x"); ok.write_text("x")
    monkeypatch.setattr(cs, "claude_candidates", lambda env: [broken, ok])
    fake_versions(monkeypatch, {str(ok): (2, 1, 300)})
    assert cs.resolve_claude(env={}) == [str(ok)]


def test_configured_command_overrides_search(monkeypatch, tmp_path):
    custom = tmp_path / "custom.exe"
    custom.write_text("x")
    monkeypatch.setattr(cs, "claude_candidates", lambda env: pytest.fail("must not search when configured"))
    assert cs.resolve_claude(env={"STEVE_CLAUDE_COMMAND": str(custom)}) == [str(custom)]


def picker(monkeypatch, version):
    monkeypatch.setattr(cs, "checked_environment", lambda: {})
    monkeypatch.setattr(cs, "resolve_claude", lambda command=None, env=None: ["claude"])
    monkeypatch.setattr(cs, "binary_version", lambda path: version)
    return cs.discover_models()


def test_picker_offers_exactly_the_three_55_routes(monkeypatch):
    rows = picker(monkeypatch, (2, 1, 293))["data"]
    assert [r["id"] for r in rows] == ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"]
    assert [r["displayName"] for r in rows] == ["Sonnet 5.5", "Opus 5.5", "Haiku 5.5"]
    assert rows[0]["isDefault"] and not any(r["isDefault"] for r in rows[1:])
    assert not any("[1m]" in r["id"] for r in rows)


def test_picker_refuses_a_too_old_claude_code(monkeypatch):
    with pytest.raises(RuntimeError, match="too old for Claude 5.5"):
        picker(monkeypatch, (2, 1, 117))
    with pytest.raises(RuntimeError, match="too old"):
        picker(monkeypatch, None)
