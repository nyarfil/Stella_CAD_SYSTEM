"""Tests for tools.spec_validator — state scan + artifact validators, CLI contract.

Fixture content mirrors REAL artifact shapes from production design runs:
  - notes.md marker:   '- **VALIDATION: PASSED**'  (bold, list-item)
  - constraints.md:    '- Overall: 20mm diameter x 50mm length'
                       '## Material / Manufacturing'
  - design_plan.md:    '## Parts' / '### 1. driving_shaft' / '## Assembly Order'
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.spec_validator import (  # noqa: E402
    read_project_state,
    validate_constraints,
    validate_design_plan,
    validate_status,
)

# Real constraints.md content (verbatim from history: shaft_coupling/driving_shaft)
REAL_CONSTRAINTS = """\
# Constraints: driving_shaft

## Functional Requirements
- Transmit torque from a motor or other driving element.

## Dimensions
- Overall: 20mm diameter x 50mm length

## Interfaces
- Connects to `coupling_sleeve` via a slip fit into the 20mm bore.

## Material / Manufacturing
- Material: Steel (default, e.g., 1045)
- Manufacturing: Turning, Milling (for the keyway)
"""

PART_CODE = 'import cadquery as cq\nresult = cq.Workplane("XY").cylinder(50, 10)\n'


def _make_part(project: Path, name: str, *, code: bool = True, notes: str | None = None,
               constraints: bool = False, proposal: bool = False, renders: bool = False) -> Path:
    part = project / "assembly" / name
    part.mkdir(parents=True, exist_ok=True)
    if code:
        (part / "part.py").write_text(PART_CODE)
    if notes is not None:
        (part / "notes.md").write_text(notes)
    if constraints:
        (part / "constraints.md").write_text(REAL_CONSTRAINTS)
    if proposal:
        (part / "part.proposal.py").write_text(PART_CODE)
    if renders:
        (part / "renders").mkdir()
        (part / "renders" / "front_clean.png").write_bytes(b"\x89PNG")
    return part


# ---------------------------------------------------------------- state scan

def test_empty_project(tmp_path):
    state = read_project_state(tmp_path)
    assert state["project_name"] == tmp_path.name
    assert state["parts_total"] == 0
    assert state["parts"] == []
    assert state["design_plan_exists"] is False
    assert state["goals_summary"] == ""
    assert state["conflicts"] == []
    assert state["checkpoint_exists"] is False
    assert state["checkpoint_summary"] is None
    assert state["external_bom_exists"] is False


def test_planned_project(tmp_path):
    (tmp_path / "goals.md").write_text("# Goals\nA rigid coupling.\n")
    (tmp_path / "design_plan.md").write_text("# Design Plan\n## Parts\n")
    state = read_project_state(tmp_path)
    assert state["design_plan_exists"] is True
    assert "Design Plan" in state["design_plan_summary"]
    assert "rigid coupling" in state["goals_summary"]
    assert state["parts_total"] == 0


def test_designed_part_flags_and_tristate(tmp_path):
    _make_part(tmp_path, "shaft", notes="Design notes, no marker yet.",
               constraints=True, renders=True)
    state = read_project_state(tmp_path)
    assert state["parts_total"] == 1
    p = state["parts"][0]
    assert p["name"] == "shaft"
    assert p["path"] == "assembly/shaft"
    assert p["has_code"] is True
    assert p["has_renders"] is True
    assert p["has_constraints"] is True
    assert p["has_notes"] is True
    assert p["has_proposal"] is False
    assert p["validation_status"] == "not_validated"
    assert p["code_executes"] is None  # tri-state: never executes code
    assert p["last_modified"] != ""
    assert state["parts_designed"] == 1
    assert state["parts_validated"] == 0


def test_validation_markers_real_format(tmp_path):
    # Real historical shape is bold + list-item; substring match must catch it.
    _make_part(tmp_path, "shaft", notes="- **VALIDATION: PASSED**\n")
    _make_part(tmp_path, "gear", notes="VALIDATION: FAILED — bore undersized\n")
    state = read_project_state(tmp_path)
    by_name = {p["name"]: p for p in state["parts"]}
    assert by_name["shaft"]["validation_status"] == "passed"
    assert by_name["gear"]["validation_status"] == "failed"
    assert state["parts_validated"] == 1
    assert state["parts_failed"] == 1


def test_passed_wins_when_both_markers(tmp_path):
    _make_part(tmp_path, "shaft",
               notes="VALIDATION: FAILED\nlater re-run:\nVALIDATION: PASSED\n")
    state = read_project_state(tmp_path)
    assert state["parts"][0]["validation_status"] == "passed"


def test_proposal_overrides_validation_status(tmp_path):
    _make_part(tmp_path, "shaft", notes="- **VALIDATION: PASSED**\n", proposal=True)
    state = read_project_state(tmp_path)
    p = state["parts"][0]
    assert p["has_proposal"] is True
    assert p["validation_status"] == "pending_proposal"
    assert state["parts_with_proposals"] == 1
    assert state["parts_validated"] == 0


def test_repair_iterations_from_design_log(tmp_path):
    _make_part(tmp_path, "shaft")
    _make_part(tmp_path, "gear")
    (tmp_path / "design_log.md").write_text(
        "# Design Log\n"
        "[planner] plan written\n"
        "[repair] shaft attempt 1: fixed keyway\n"
        "[Repair] shaft attempt 2: fixed chamfer\n"  # tag match is case-insensitive
        "[repair] gear attempt 1: fixed bore\n"
        "[validator] shaft render reviewed\n"
    )
    state = read_project_state(tmp_path)
    by_name = {p["name"]: p for p in state["parts"]}
    assert by_name["shaft"]["repair_iterations"] == 2
    assert by_name["gear"]["repair_iterations"] == 1


def test_conflicts_open_and_resolved(tmp_path):
    (tmp_path / "open_issues.md").write_text(
        "# Open Issues\n"
        "### CONFLICT-001 [shaft, gear]\n"
        "Bore mismatch between shaft OD and gear bore.\n"
        "### CONFLICT-002 [RESOLVED]\n"
        "Old keyway clash.\n"
        "- [ ] check tolerance stack\n"
    )
    state = read_project_state(tmp_path)
    assert [c["conflict_id"] for c in state["conflicts"]] == ["CONFLICT-001", "CONFLICT-002"]
    assert [c["status"] for c in state["conflicts"]] == ["open", "resolved"]
    assert state["active_conflicts_count"] == 1
    # open_issues collects '### ' headers and '- [' checkbox lines
    assert state["open_issues_count"] == 3
    assert "- [ ] check tolerance stack" in state["open_issues"]


def test_recent_log_entries_last_15_no_headers(tmp_path):
    lines = ["# Design Log"] + [f"[orchestrator] step {i}" for i in range(20)]
    (tmp_path / "design_log.md").write_text("\n".join(lines) + "\n")
    state = read_project_state(tmp_path)
    assert len(state["recent_log_entries"]) == 15
    assert state["recent_log_entries"][0] == "[orchestrator] step 5"
    assert state["recent_log_entries"][-1] == "[orchestrator] step 19"
    assert not any(l.startswith("#") for l in state["recent_log_entries"])


def test_sub_assembly_scan_flattens_parts(tmp_path):
    # assembly/drivetrain/{pinion,layshaft} — drivetrain is a sub-assembly
    for name in ("pinion", "layshaft"):
        d = tmp_path / "assembly" / "drivetrain" / name
        d.mkdir(parents=True)
        (d / "part.py").write_text(PART_CODE)
    (tmp_path / "assembly" / "drivetrain" / "assembly.md").write_text("# Drivetrain\n")
    _make_part(tmp_path, "housing")
    state = read_project_state(tmp_path)
    assert state["parts_total"] == 3  # flattened: housing + pinion + layshaft
    assert len(state["sub_assemblies"]) == 1
    sub = state["sub_assemblies"][0]
    assert sub["name"] == "drivetrain"
    assert sub["path"] == "assembly/drivetrain"
    assert sub["has_assembly_spec"] is True
    assert sub["has_assembly_code"] is False
    assert sub["parts_count"] == 2
    assert sub["parts_designed"] == 2


def test_checkpoint_and_bom(tmp_path):
    (tmp_path / "checkpoint.md").write_text("# Checkpoint\nResume from part 2.\n")
    (tmp_path / "external").mkdir()
    (tmp_path / "external" / "bom.md").write_text("| item |\n")
    state = read_project_state(tmp_path)
    assert state["checkpoint_exists"] is True
    assert "Resume from part 2" in state["checkpoint_summary"]
    assert state["external_bom_exists"] is True


def test_suborchestrator_scope_without_assembly_dir(tmp_path):
    # No assembly/ dir → parts scanned directly under root
    d = tmp_path / "bracket"
    d.mkdir()
    (d / "part.py").write_text(PART_CODE)
    state = read_project_state(tmp_path)
    assert state["parts_total"] == 1
    assert state["parts"][0]["path"] == "./bracket"


# ---------------------------------------------------------------- validators

def test_validate_design_plan_valid():
    text = (
        "# Design Plan\n\n## Overview\nTwo-shaft rigid coupling.\n\n"
        "## Parts\n\n"
        "### 1. driving_shaft\n- **parallel_safe**: true — fully defined\n\n"
        "### 2. coupling_sleeve\n- **parallel_safe**: false — bore depends on shaft OD\n\n"
        "## Assembly Order\n1. `driving_shaft`\n2. `coupling_sleeve`\n"
    )
    out = validate_design_plan(text)
    assert out["valid"] is True
    assert out["checks"]["parts_found"] == ["driving_shaft", "coupling_sleeve"]
    assert out["checks"]["parallel_safe"] == {"driving_shaft": True, "coupling_sleeve": False}
    assert out["checks"]["all_parts_annotated"] is True
    assert out["checks"]["build_order_entries"] == 2
    assert out["errors"] == []


def test_validate_design_plan_legacy_era_missing_annotations():
    # Real historical plans predate the parallel_safe contract → invalid, nulls
    text = (
        "# Design Plan\n\n## Parts\n\n### 1. driving_shaft\n- 20mm dia\n\n"
        "## Assembly Order\n1. `driving_shaft`\n"
    )
    out = validate_design_plan(text)
    assert out["valid"] is False
    assert out["checks"]["parallel_safe"] == {"driving_shaft": None}
    assert out["checks"]["all_parts_annotated"] is False
    assert any("parallel_safe" in e for e in out["errors"])


def test_validate_design_plan_missing_sections():
    out = validate_design_plan("# Design Plan\nJust prose.\n")
    assert out["valid"] is False
    assert out["checks"]["has_parts_section"] is False
    assert out["checks"]["has_build_order"] is False
    assert len(out["errors"]) == 2


def test_validate_constraints_real_cylindrical():
    out = validate_constraints(REAL_CONSTRAINTS)
    assert out["valid"] is True
    assert out["checks"]["has_overall_line"] is True
    assert out["checks"]["overall_dimensions_sorted"] == [20.0, 50.0]
    assert out["checks"]["has_manufacturing_section"] is True
    # Real line 'Turning, Milling' → 'milling' wins by keyword-dict order
    assert out["checks"]["manufacturing_process"] == "CNC_milling"
    assert out["errors"] == []


def test_validate_constraints_prismatic_fallback():
    text = (
        "## Dimensions\n- Overall: 300 x 200 x 150 mm (L x W x H)\n\n"
        "## Manufacturing\n- 3D printing (FDM)\n"
    )
    out = validate_constraints(text)
    assert out["valid"] is True
    assert out["checks"]["overall_dimensions_sorted"] == [150.0, 200.0, 300.0]
    assert out["checks"]["manufacturing_process"] == "3D_printing"


def test_validate_constraints_invalid():
    out = validate_constraints("# Constraints\nNo dims here.\n")
    assert out["valid"] is False
    assert out["checks"]["has_overall_line"] is False
    assert out["checks"]["manufacturing_process"] is None
    assert len(out["errors"]) == 2


def test_validate_status_variants():
    passed = validate_status("- **VALIDATION: PASSED**\n")
    assert passed["valid"] is True
    assert passed["checks"]["validation_status"] == "passed"

    failed = validate_status("VALIDATION: FAILED — silhouette mismatch\n")
    assert failed["valid"] is True
    assert failed["checks"]["validation_status"] == "failed"

    missing = validate_status("Notes without a marker.\n")
    assert missing["valid"] is False
    assert missing["checks"]["has_validation_marker"] is False
    assert missing["errors"]


# ---------------------------------------------------------------- CLI contract

def _run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    return subprocess.run(
        [sys.executable, "-m", "tools.spec_validator", *args],
        cwd=cwd, env=env, capture_output=True, text=True,
    )


def test_cli_query_state(tmp_path):
    project = tmp_path / "projects" / "demo"
    _make_part(project, "shaft", notes="- **VALIDATION: PASSED**\n")
    proc = _run_cli(["--query=state", "--project=projects/demo"], cwd=tmp_path)
    assert proc.returncode == 0
    state = json.loads(proc.stdout)
    assert state["parts_total"] == 1
    assert state["parts"][0]["validation_status"] == "passed"
    assert "1 parts" in proc.stderr


def test_cli_path_escape_guard(tmp_path):
    (tmp_path / "projects").mkdir()
    proc = _run_cli(["--query=state", "--project=../outside"], cwd=tmp_path / "projects")
    assert proc.returncode == 2
    assert "escapes invocation root" in json.loads(proc.stdout)["error"]


def test_cli_missing_project(tmp_path):
    proc = _run_cli(["--query=state", "--project=projects/nope"], cwd=tmp_path)
    assert proc.returncode == 2
    assert "not found" in json.loads(proc.stdout)["error"]


def test_cli_validate_status_file(tmp_path):
    (tmp_path / "notes.md").write_text("- **VALIDATION: PASSED**\n")
    proc = _run_cli(["--validate=status", "--file=notes.md"], cwd=tmp_path)
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["valid"] is True
    assert out["file"] == "notes.md"
