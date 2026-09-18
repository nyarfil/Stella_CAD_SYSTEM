"""Tests for tools.placeholder_detector — A2 stub detection, CLI contract."""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.placeholder_detector import detect_placeholder  # noqa: E402

# The scaffold create_part_directory writes (legacy project.py): 1 substantive
# line → the few-lines check fires BEFORE the box check (legacy order).
SCAFFOLD_STUB = (
    "import cadquery as cq\n"
    "\n"
    "result = cq.Workplane('XY').box(10, 10, 10)\n"
)

# box(10,10,10) with enough substantive lines that only the box check fires.
BOX_WITH_PADDING = (
    "import cadquery as cq\n"
    "length = 10\n"
    "width = 10\n"
    "height = 10\n"
    'result = cq.Workplane("XY").box(10, 10, 10)\n'
)

REAL_PART = (
    "import cadquery as cq\n"
    "\n"
    "diameter = 20.0\n"
    "length = 50.0\n"
    "keyway_width = 5.0\n"
    "keyway_depth = 2.5\n"
    "\n"
    'shaft = cq.Workplane("XY").circle(diameter / 2).extrude(length)\n'
    "keyway = (\n"
    '    cq.Workplane("XZ", origin=(0, 0, length / 2))\n'
    "    .rect(keyway_width, length)\n"
    "    .extrude(diameter)\n"
    ")\n"
    "result = shaft.cut(keyway)\n"
)


# ---------------------------------------------------------------- detection

def test_scaffold_stub_is_placeholder_few_lines_reason():
    reason = detect_placeholder(SCAFFOLD_STUB)
    assert reason is not None
    assert "very few lines" in reason


def test_box_10_10_10_is_placeholder():
    reason = detect_placeholder(BOX_WITH_PADDING)
    assert reason is not None
    assert "box(10,10,10)" in reason


def test_box_no_spaces_variant():
    code = BOX_WITH_PADDING.replace("box(10, 10, 10)", "box(10,10,10)")
    reason = detect_placeholder(code)
    assert reason is not None
    assert "box(10,10,10)" in reason


def test_fewer_than_3_substantive_lines_boundary():
    # Comments and imports do not count as substantive; 2 code lines → stub
    two_lines = (
        "import cadquery as cq\n"
        "# a shaft\n"
        "d = 12.0\n"
        'result = cq.Workplane("XY").cylinder(30, d / 2)\n'
    )
    assert detect_placeholder(two_lines) is not None

    # Exactly 3 substantive lines → passes the line-count gate
    three_lines = (
        "import cadquery as cq\n"
        "d = 12.0\n"
        "h = 30.0\n"
        'result = cq.Workplane("XY").cylinder(h, d / 2)\n'
    )
    assert detect_placeholder(three_lines) is None


def test_real_part_is_not_placeholder():
    assert detect_placeholder(REAL_PART) is None


def test_todo_and_placeholder_markers():
    reason = detect_placeholder(REAL_PART + "# TODO: add chamfer\n")
    assert reason is not None
    assert "placeholder/TODO markers" in reason

    reason = detect_placeholder(REAL_PART + "# Placeholder for the flange\n")
    assert reason is not None
    assert "placeholder/TODO markers" in reason


# ---------------------------------------------------------------- CLI contract

def _run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    return subprocess.run(
        [sys.executable, "-m", "tools.placeholder_detector", *args],
        cwd=cwd, env=env, capture_output=True, text=True,
    )


def _make_part(root: Path, name: str, code: str) -> str:
    part = root / "projects" / "demo" / "assembly" / name
    part.mkdir(parents=True)
    (part / "part.py").write_text(code)
    return f"projects/demo/assembly/{name}"


def test_cli_placeholder_verdict_exit_0(tmp_path):
    rel = _make_part(tmp_path, "stub", SCAFFOLD_STUB)
    proc = _run_cli(["--part-path", rel], cwd=tmp_path)
    assert proc.returncode == 0  # verdict in JSON, not exit code
    out = json.loads(proc.stdout)
    assert out["is_placeholder"] is True
    assert "very few lines" in out["reason"]


def test_cli_real_part_verdict(tmp_path):
    rel = _make_part(tmp_path, "shaft", REAL_PART)
    proc = _run_cli(["--part-path", rel], cwd=tmp_path)
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out == {"is_placeholder": False, "reason": None}


def test_cli_missing_part_py_is_malfunction(tmp_path):
    (tmp_path / "projects" / "demo" / "assembly" / "empty").mkdir(parents=True)
    proc = _run_cli(["--part-path", "projects/demo/assembly/empty"], cwd=tmp_path)
    assert proc.returncode == 2
    assert "part.py not found" in json.loads(proc.stdout)["error"]


def test_cli_path_escape_guard(tmp_path):
    inner = tmp_path / "inner"
    inner.mkdir()
    proc = _run_cli(["--part-path", "../outside"], cwd=inner)
    assert proc.returncode == 2
    assert "escapes invocation root" in json.loads(proc.stdout)["error"]
