"""Tests for tools.dimension_checker — constraint parsing against the
real-world 'Overall:' formats cataloged from legacy E2E projects, prismatic +
cylindrical comparison, the 15% tolerance boundary, script execution
(result discovery + timeout), and the CLI JSON contract.

Note: no constraints.md files survive in the legacy repo's projects/ tree, so
the "real formats" here are the five formats the legacy docstring catalogs
verbatim from past E2E runs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.dimension_checker import (  # noqa: E402
    check_dimensions,
    execute_cad_script,
    parse_overall_dimensions,
)


def bbox(dx: float, dy: float, dz: float) -> dict:
    """Symmetric-ish bbox helper: origin-cornered box of the given extents."""
    return {"xmin": 0.0, "xmax": dx, "ymin": 0.0, "ymax": dy,
            "zmin": 0.0, "zmax": dz}


# ------------------------------------------------- parse_overall_dimensions

@pytest.mark.parametrize("line,expected", [
    # The five real-world formats from legacy E2E projects (docstring catalog):
    ("Overall: 150 x 100 x 25 mm", [25.0, 100.0, 150.0]),
    ("Overall: 150mm diameter x 20mm height", [20.0, 150.0]),
    ("Overall: 45mm outer diameter x 60mm height", [45.0, 60.0]),
    ("Overall: Approx. 10mm diameter, 5mm height", [5.0, 10.0]),
    ("Overall: 300 x 200 x 150 mm (L x W x H)", [150.0, 200.0, 300.0]),
    # Per-number units, prismatic:
    ("Overall: 80mm x 40mm x 20mm", [20.0, 40.0, 80.0]),
])
def test_parse_real_world_formats(line, expected):
    text = f"# Constraints\n{line}\nMaterial: aluminum\n"
    assert parse_overall_dimensions(text) == expected


def test_parse_case_insensitive():
    assert parse_overall_dimensions("overall: 10 x 20 x 30 mm") == [10.0, 20.0, 30.0]


@pytest.mark.parametrize("text", [
    "No dimensions specified here",          # no Overall: line
    "Overall: about the size of a hand",     # no numbers
    "Overall: 50mm wide",                    # single dim — not enough
])
def test_parse_unparseable_returns_none(text):
    assert parse_overall_dimensions(text) is None


# --------------------------------------------------------- check_dimensions

def test_prismatic_exact_pass():
    result = check_dimensions(bbox(80, 40, 20), "Overall: 80 x 40 x 20 mm")
    assert result["pass"] is True
    assert result["expected"] == [20.0, 40.0, 80.0]
    assert result["actual"] == [20.0, 40.0, 80.0]
    assert result["deviations"] == []


def test_prismatic_axis_ambiguity_sorted_compare():
    # Same box, dims delivered on different axes — sorting must absorb it.
    result = check_dimensions(bbox(20, 80, 40), "Overall: 80 x 40 x 20 mm")
    assert result["pass"] is True


def test_prismatic_within_15pct_tolerance_passes():
    # 10% off on every dim — inside the 15% band.
    result = check_dimensions(bbox(110, 44, 22), "Overall: 100 x 40 x 20 mm")
    assert result["pass"] is True


def test_prismatic_over_15pct_tolerance_fails():
    # 20% off on one dim only.
    result = check_dimensions(bbox(120, 40, 20), "Overall: 100 x 40 x 20 mm")
    assert result["pass"] is False
    assert len(result["deviations"]) == 1
    assert "120" in result["deviations"][0] and "20% off" in result["deviations"][0]


def test_cylindrical_pass_skips_middle_dim():
    # d=150 cylinder bbox is 150x150x20: middle actual dim (the duplicate
    # diameter) must be skipped, comparing [20,150] against [20,150].
    result = check_dimensions(bbox(150, 150, 20),
                              "Overall: 150mm diameter x 20mm height")
    assert result["pass"] is True
    assert result["actual"] == [20.0, 150.0, 150.0]


def test_cylindrical_wrong_diameter_fails():
    result = check_dimensions(bbox(80, 80, 20),
                              "Overall: 150mm diameter x 20mm height")
    assert result["pass"] is False
    assert len(result["deviations"]) == 1
    assert "150" in result["deviations"][0]


def test_no_parseable_overall_returns_none():
    assert check_dimensions(bbox(80, 40, 20), "Material: steel") is None


# ------------------------------------------------------- execute_cad_script

def test_execute_finds_result_variable():
    solid, namespace, error = execute_cad_script(
        'import cadquery as cq\nresult = cq.Workplane("XY").box(10, 10, 10)\n')
    assert error is None
    assert solid is namespace["result"]


def test_execute_falls_back_to_last_workplane():
    solid, _, error = execute_cad_script(
        'import cadquery as cq\n'
        'a = cq.Workplane("XY").box(1, 1, 1)\n'
        'b = cq.Workplane("XY").box(2, 2, 2)\n')
    assert error is None
    assert solid is not None  # picked up a Workplane despite no `result`


def test_execute_no_workplane_reports_error():
    solid, _, error = execute_cad_script("x = 42\n")
    assert solid is None
    assert "result" in error


def test_execute_broken_script_reports_full_traceback():
    solid, _, error = execute_cad_script("raise ValueError('boom boom boom')\n")
    assert solid is None
    assert "boom boom boom" in error  # never truncated


def test_execute_timeout():
    solid, _, error = execute_cad_script("while True:\n    pass\n", timeout_s=1)
    assert solid is None
    assert "timed out" in error


# ------------------------------------------------------------- CLI contract

def run_checker(*flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tools.dimension_checker", *flags],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
    )


CLI_KEYS = {"pass", "expected", "actual", "deviations", "error_message"}


def test_cli_pass_verdict(tmp_path):
    (tmp_path / "part.py").write_text(
        'import cadquery as cq\n'
        'result = cq.Workplane("XY").box(80, 40, 20)\n')
    constraints = tmp_path / "constraints.md"
    constraints.write_text("Overall: 80 x 40 x 20 mm\n")
    proc = run_checker("--part-path", str(tmp_path),
                       "--constraints-file", str(constraints))
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert set(out) == CLI_KEYS
    assert out["pass"] is True
    assert out["error_message"] is None


def test_cli_fail_verdict_still_exits_zero(tmp_path):
    (tmp_path / "part.py").write_text(
        'import cadquery as cq\n'
        'result = cq.Workplane("XY").box(80, 40, 20)\n')
    constraints = tmp_path / "constraints.md"
    constraints.write_text("Overall: 150 x 100 x 25 mm\n")
    proc = run_checker("--part-path", str(tmp_path),
                       "--constraints-file", str(constraints))
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["pass"] is False
    assert len(out["deviations"]) == 3


def test_cli_missing_part_not_evaluable(tmp_path):
    constraints = tmp_path / "constraints.md"
    constraints.write_text("Overall: 80 x 40 x 20 mm\n")
    proc = run_checker("--part-path", str(tmp_path),
                       "--constraints-file", str(constraints))
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["pass"] is None
    assert "part.py" in out["error_message"]
