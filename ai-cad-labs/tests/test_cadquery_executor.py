"""Tests for tools.cadquery_executor — execution, errors, timeout, hints, CLI contract.

Ported from legacy tests/test_executor.py + tests/test_safe_path.py, adapted
to the bash-first tool API (module functions + CLI JSON contract).
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.cadquery_executor import (  # noqa: E402
    CadQueryExecutor,
    execute_in_subprocess,
    match_hint,
    run,
    safe_path,
)

BOX_CODE = """
import cadquery as cq
result = cq.Workplane("XY").box(10, 10, 10)
"""

JSON_KEYS = {"success", "volume", "bbox", "execution_time_ms",
             "error_message", "enriched_hint", "result_type"}


# ---------------------------------------------------------------- executor core

def test_execute_simple_box():
    """Valid CadQuery code should produce a solid with volume."""
    executor = CadQueryExecutor()
    result = executor.execute(BOX_CODE)
    assert result.success is True
    assert result.solid is not None
    assert result.execution_time_ms > 0


def test_execute_syntax_error():
    """Syntax errors should return failure with error message."""
    executor = CadQueryExecutor()
    result = executor.execute("def broken(")
    assert result.success is False
    assert "SyntaxError" in result.error_message


def test_execute_runtime_error():
    """Runtime errors should return failure with traceback."""
    executor = CadQueryExecutor()
    result = executor.execute("""
import cadquery as cq
result = cq.Workplane("XY").box(10, 10, 10).fillet(999)
""")
    assert result.success is False
    assert result.error_message is not None


def test_execute_no_result_variable():
    """Code without 'result' or Workplane should return failure."""
    executor = CadQueryExecutor()
    result = executor.execute("x = 42")
    assert result.success is False
    assert "no CadQuery Workplane" in result.error_message


def test_execute_finds_last_workplane():
    """If no 'result' variable, should find the last Workplane assigned."""
    executor = CadQueryExecutor()
    result = executor.execute("""
import cadquery as cq
my_shape = cq.Workplane("XY").box(10, 10, 10)
""")
    assert result.success is True
    assert result.solid is not None


def test_execute_timeout():
    """Long-running code should be stopped after timeout.

    Uses time.sleep() instead of `while True: pass` because Python threads
    can't be forcefully killed — sleep() at least releases the GIL and allows
    the timeout to fire cleanly. (sleep is 5s, not legacy 30s, so the
    abandoned thread doesn't stall interpreter shutdown.)
    """
    executor = CadQueryExecutor(timeout_s=1)
    result = executor.execute("""
import time
time.sleep(5)  # Will be interrupted by 1s timeout
result = None
""", timeout_s=1)
    assert result.success is False
    assert "timed out" in result.error_message.lower()
    assert result.execution_time_ms >= 900  # at least ~1s


def test_execute_nonexistent_method_enriched():
    """Hallucinated API calls fail with the raw error plus a corrective hint."""
    executor = CadQueryExecutor()
    result = executor.execute("""
import cadquery as cq
result = cq.Workplane("XY").box(10, 10, 10).fillet2D(1.0)
""")
    assert result.success is False
    assert "fillet2D" in result.error_message
    assert result.enriched_hint is not None
    assert ".fillet() on 3D edges" in result.enriched_hint


def test_project_path_injection(tmp_path):
    """__project_path__ is injected into the exec namespace when provided."""
    proj = tmp_path / "projX"
    proj.mkdir()
    out = run("""
import cadquery as cq
assert __project_path__.name == "projX"
result = cq.Workplane("XY").box(1, 1, 1)
""", project_path=str(proj))
    assert out["success"] is True


# ---------------------------------------------------------------- hint matching

def test_hint_matching_pure():
    """All hint patterns are string-matched without needing execution."""
    assert ".polyline()" in match_hint("AttributeError: 'Workplane' object has no attribute 'hull'")
    assert "Build123d" in match_hint("TypeError: extrude() got an unexpected keyword argument 'centered'")
    assert "%CIRCLE" in match_hint("module has no attribute 'EdgeCylinderSelector'")
    assert "Solid.makeCone" in match_hint("has no attribute 'cone'")
    assert match_hint("ValueError: some unrelated error") is None


# ---------------------------------------------------------------- run() JSON dict

def test_run_success_contract():
    """run() returns the full JSON contract with geometry for a valid box."""
    out = run(BOX_CODE)
    assert set(out.keys()) == JSON_KEYS
    assert out["success"] is True
    assert out["volume"] == pytest.approx(1000.0)
    assert out["bbox"]["xmax"] - out["bbox"]["xmin"] == pytest.approx(10.0)
    assert out["result_type"] == "Workplane"
    assert out["error_message"] is None
    assert out["enriched_hint"] is None


# ---------------------------------------------------------------- subprocess mode

def test_subprocess_mode_success():
    """Subprocess mode round-trips through STEP and still yields volume/bbox."""
    out = run(BOX_CODE, subprocess_mode=True)
    assert out["success"] is True
    assert out["volume"] == pytest.approx(1000.0, rel=0.01)
    assert out["bbox"] is not None
    assert out["result_type"] == "Workplane"


def test_subprocess_mode_survives_segfault():
    """A SIGSEGV in the child is reported cleanly; the parent survives."""
    out = run("""
import os, signal
os.kill(os.getpid(), signal.SIGSEGV)
""", subprocess_mode=True)
    assert out["success"] is False
    assert "SIGSEGV" in out["error_message"]


def test_subprocess_exec_error_propagates():
    """Python-level errors in the child come back as error text."""
    success, error_msg, step = execute_in_subprocess("raise ValueError('boom')", timeout_s=30)
    assert success is False
    assert "boom" in error_msg
    assert step is None


# ---------------------------------------------------------------- CLI contract

def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tools.cadquery_executor", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
    )


def test_cli_success_json(tmp_path):
    code_file = tmp_path / "box.py"
    code_file.write_text(BOX_CODE)
    proc = _run_cli("--code-file", str(code_file))
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data.keys()) == JSON_KEYS
    assert data["success"] is True
    assert data["volume"] == pytest.approx(1000.0)
    assert data["result_type"] == "Workplane"


def test_cli_code_failure_still_exits_zero(tmp_path):
    """Evaluated-code failure is a verdict, not a tool malfunction: exit 0 + JSON."""
    code_file = tmp_path / "broken.py"
    code_file.write_text("def broken(")
    proc = _run_cli("--code-file", str(code_file))
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["success"] is False
    assert "SyntaxError" in data["error_message"]
    assert data["enriched_hint"] is None


def test_cli_missing_code_file():
    """Missing input file is a usage error: exit 2, still machine-parseable JSON."""
    proc = _run_cli("--code-file", "/nonexistent/nope.py")
    assert proc.returncode == 2
    data = json.loads(proc.stdout)
    assert data["success"] is False
    assert "not found" in data["error_message"]


# ---------------------------------------------------------------- safe_path

def test_valid_relative_path():
    result = safe_path(Path("/tmp/project"), "assembly/bracket/part.py")
    assert result == Path("/tmp/project/assembly/bracket/part.py").resolve()


def test_nested_path():
    result = safe_path(Path("/tmp/project"), "assembly/gear/renders/iso.png")
    assert "assembly/gear/renders/iso.png" in str(result)


def test_path_traversal_blocked():
    with pytest.raises(ValueError, match="escapes project directory"):
        safe_path(Path("/tmp/project"), "../../etc/passwd")


def test_double_dot_in_middle():
    with pytest.raises(ValueError, match="escapes project directory"):
        safe_path(Path("/tmp/project"), "assembly/../../etc/passwd")


def test_simple_filename():
    result = safe_path(Path("/tmp/project"), "goals.md")
    assert result.name == "goals.md"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
