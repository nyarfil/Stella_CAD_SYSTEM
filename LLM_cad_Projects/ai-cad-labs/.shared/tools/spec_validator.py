"""Spec validator: project state scanner + structural artifact checks (CLI).

Plain CLI (bash-first, JSON to stdout, human detail to stderr).

Usage (cwd = repo root):
    uv run python -m tools.spec_validator --query=state --project=projects/<name>
    uv run python -m tools.spec_validator --validate=design_plan --file <f>
    uv run python -m tools.spec_validator --validate=constraints --file <f>
    uv run python -m tools.spec_validator --validate=status --file <f>

JSON contract (stdout, single object):

--query=state → ProjectState-equivalent:
    {project_name, project_path, state_as_of, goals_summary,
     design_plan_exists, design_plan_summary,
     parts: [{name, path, has_code, has_renders, has_constraints, has_notes,
              has_proposal, code_executes (null = untested; tri-state
              preserved: this tool never executes code),
              validation_status: not_validated|passed|failed|pending_proposal
              (parsed from notes.md "VALIDATION: PASSED|FAILED"; a pending
              part.proposal.py overrides), repair_iterations (count of
              design_log.md lines containing "[repair]" + the part name),
              last_modified, active_conflicts}],
     parts_total, parts_designed, parts_validated, parts_failed,
     parts_with_proposals,
     assembly: {has_assembly_spec, has_assembly_code, assembly_executes,
                unresolved_interfaces},
     sub_assemblies: [{name, path, has_assembly_spec, has_assembly_code,
                       parts_count, parts_designed, parts_validated}],
     conflicts: [{conflict_id, affected_parts, description, proposal_paths,
                  status: open|resolved, resolution_attempts, created_at}]
       (from open_issues.md "### CONFLICT-NNN" headers; "[RESOLVED]" marker
        → resolved; header-only parsing means affected_parts=[],
        proposal_paths=[], resolution_attempts=0, created_at="" are
        PERMANENTLY-EMPTY placeholder fields kept for schema stability),
     active_conflicts_count, open_issues, open_issues_count,
     recent_log_entries (last 15 non-empty non-header design_log.md lines),
     external_bom_exists, checkpoint_exists, checkpoint_summary}

    NOTE: the legacy BudgetStatus block is omitted; token/spawn counters
    lived in PydanticAI orchestrator deps and are not visible to a CLI
    (attempt-count proxy replaces the legacy token budget).

--validate=design_plan → {validate, file, valid,
     checks: {has_parts_section, parts_found, parallel_safe (per-part map:
              true|false|null = annotation missing), all_parts_annotated,
              has_build_order, build_order_entries}, errors}
--validate=constraints → {validate, file, valid,
     checks: {has_overall_line, overall_dimensions_sorted (2 = cylindrical
              diameter+height, 3 = prismatic L×W×H), has_manufacturing_section,
              manufacturing_process (canonical id or null)}, errors}
--validate=status → {validate, file, valid,
     checks: {has_validation_marker, validation_status}, errors}
     (checks a notes.md for the "VALIDATION: PASSED|FAILED" filesystem-bus
      marker)

Exit codes: 0 = tool ran (the JSON carries the artifact verdict, even when
the artifact fails checks); 2 = tool malfunction (bad arguments, path
escaping the invocation root, missing file/project). Error messages are
never truncated; unexpected failures print a full traceback to stderr.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


class ToolError(Exception):
    """Controlled tool malfunction (bad path, missing input) → exit 2."""


def safe_path(root: Path, relative: str) -> Path:
    """Resolve a path safely within the invocation root.

    Prevents path traversal (e.g. ../../etc/passwd). Raises ToolError
    on escape (CLI-shaped).
    """
    resolved = (root / relative).resolve()
    root_resolved = root.resolve()
    if not resolved.is_relative_to(root_resolved):
        raise ToolError(f"Path '{relative}' escapes invocation root '{root}'")
    return resolved


# ──────────────────────────────────────────────────────────────
# State scan (port of src/tools/project.py)
# ──────────────────────────────────────────────────────────────


def _build_part_status(part_dir: Path, rel_path: str, project_root: Path) -> dict:
    """Build a PartStatus dict for a single part directory."""
    renders_dir = part_dir / "renders"
    has_renders = renders_dir.exists() and any(renders_dir.glob("*.png"))

    # Validation status from notes.md. PASSED is checked before FAILED
    # (legacy precedence: if both markers appear, passed wins).
    notes_path = part_dir / "notes.md"
    notes_content = notes_path.read_text() if notes_path.exists() else ""
    validation_status = "not_validated"
    if "VALIDATION: PASSED" in notes_content:
        validation_status = "passed"
    elif "VALIDATION: FAILED" in notes_content:
        validation_status = "failed"

    has_proposal = (part_dir / "part.proposal.py").exists()
    if has_proposal:
        validation_status = "pending_proposal"

    # Repair iterations from design_log.md. Legacy matches the part NAME
    # (directory basename) as a substring — a part named "pin" also matches
    # "wrist_pin" lines. Quirk preserved for parity.
    repair_iterations = 0
    log_path = project_root / "design_log.md"
    if log_path.exists():
        log_text = log_path.read_text()
        repair_iterations = sum(
            1 for line in log_text.splitlines()
            if "[repair]" in line.lower() and part_dir.name in line
        )

    part_py = part_dir / "part.py"
    last_mod = ""
    if part_py.exists():
        last_mod = datetime.fromtimestamp(
            part_py.stat().st_mtime, tz=timezone.utc
        ).isoformat()

    return {
        "name": part_dir.name,
        "path": rel_path,
        "has_code": part_py.exists(),
        "has_renders": has_renders,
        "has_constraints": (part_dir / "constraints.md").exists(),
        "has_notes": notes_path.exists(),
        "has_proposal": has_proposal,
        "code_executes": None,  # tri-state: null = untested (executor's job)
        "validation_status": validation_status,
        "repair_iterations": repair_iterations,
        "last_modified": last_mod,
        "active_conflicts": [],
    }


def _scan_parts_recursive(
    directory: Path, prefix: str, project_root: Path
) -> tuple[list[dict], list[dict]]:
    """Recursively scan for parts and sub-assemblies.

    A directory is a PART if it contains part.py or constraints.md.
    A directory is a SUB-ASSEMBLY if it contains subdirectories with parts
    (but no part.py of its own). Sub-assemblies may have their own
    assembly.py and assembly.md. parts_count counts ALL parts in the
    subtree (flattened), matching legacy behavior.
    """
    parts: list[dict] = []
    sub_assemblies: list[dict] = []

    for entry in sorted(directory.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".") or entry.name in (
            "renders", "exports", "__pycache__"
        ):
            continue

        rel_path = f"{prefix}/{entry.name}"
        is_part = (entry / "part.py").exists() or (entry / "constraints.md").exists()

        if is_part:
            parts.append(_build_part_status(entry, rel_path, project_root))
        else:
            nested_parts, nested_subs = _scan_parts_recursive(entry, rel_path, project_root)
            if nested_parts or nested_subs:
                sub_assemblies.append(
                    {
                        "name": entry.name,
                        "path": rel_path,
                        "has_assembly_spec": (entry / "assembly.md").exists(),
                        "has_assembly_code": (entry / "assembly.py").exists(),
                        "parts_count": len(nested_parts),
                        "parts_designed": sum(1 for p in nested_parts if p["has_code"]),
                        "parts_validated": sum(
                            1 for p in nested_parts if p["validation_status"] == "passed"
                        ),
                    }
                )
                parts.extend(nested_parts)
                sub_assemblies.extend(nested_subs)

    return parts, sub_assemblies


def read_project_state(root: Path) -> dict:
    """Scan a project directory and return the ProjectState-equivalent dict.

    Scans the actual directory to determine state; never trusts cached
    data. For top-level projects, parts live under assembly/. For
    sub-orchestrator scopes (no assembly/ dir), parts live directly in root.
    """
    goals_path = root / "goals.md"
    goals_summary = goals_path.read_text() if goals_path.exists() else ""

    plan_path = root / "design_plan.md"
    design_plan_exists = plan_path.exists()
    design_plan_summary = plan_path.read_text() if design_plan_exists else ""

    assembly_dir = root / "assembly"
    if assembly_dir.exists():
        parts, sub_assemblies = _scan_parts_recursive(assembly_dir, "assembly", root)
    else:
        parts, sub_assemblies = _scan_parts_recursive(root, ".", root)

    assembly_spec_dir = assembly_dir if assembly_dir.exists() else root
    assembly = {
        "has_assembly_spec": (assembly_spec_dir / "assembly.md").exists(),
        "has_assembly_code": (assembly_spec_dir / "assembly.py").exists(),
        "assembly_executes": None,
        "unresolved_interfaces": [],
    }

    # Open issues + conflicts from open_issues.md
    issues_path = root / "open_issues.md"
    open_issues: list[str] = []
    conflicts: list[dict] = []
    if issues_path.exists():
        content = issues_path.read_text()
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- [") or stripped.startswith("### "):
                open_issues.append(stripped)
            if stripped.startswith("### CONFLICT-"):
                conflict_id = stripped.split("[")[0].strip() if "[" in stripped else stripped
                status = "resolved" if "[RESOLVED]" in stripped else "open"
                conflicts.append(
                    {
                        "conflict_id": conflict_id.replace("### ", ""),
                        "affected_parts": [],
                        "description": stripped,
                        "proposal_paths": [],
                        "status": status,
                        "resolution_attempts": 0,
                        "created_at": "",
                    }
                )

    # Recent log entries: last 15 non-empty, non-header lines
    log_path = root / "design_log.md"
    recent_log: list[str] = []
    if log_path.exists():
        lines = log_path.read_text().splitlines()
        recent_log = [l for l in lines if l.strip() and not l.startswith("#")][-15:]

    checkpoint_path = root / "checkpoint.md"
    checkpoint_exists = checkpoint_path.exists()
    checkpoint_summary = checkpoint_path.read_text() if checkpoint_exists else None

    return {
        "project_name": root.name,
        "project_path": str(root),
        "state_as_of": datetime.now(timezone.utc).isoformat(),
        "goals_summary": goals_summary,
        "design_plan_exists": design_plan_exists,
        "design_plan_summary": design_plan_summary,
        "parts": parts,
        "parts_total": len(parts),
        "parts_designed": sum(1 for p in parts if p["has_code"]),
        "parts_validated": sum(1 for p in parts if p["validation_status"] == "passed"),
        "parts_failed": sum(1 for p in parts if p["validation_status"] == "failed"),
        "parts_with_proposals": sum(1 for p in parts if p["has_proposal"]),
        "assembly": assembly,
        "sub_assemblies": sub_assemblies,
        "conflicts": conflicts,
        "active_conflicts_count": sum(1 for c in conflicts if c["status"] == "open"),
        "open_issues": open_issues,
        "open_issues_count": len(open_issues),
        "recent_log_entries": recent_log,
        "external_bom_exists": (root / "external" / "bom.md").exists(),
        "checkpoint_exists": checkpoint_exists,
        "checkpoint_summary": checkpoint_summary,
    }


# ──────────────────────────────────────────────────────────────
# Constraints validation (ports of _parse_overall_dimensions,
# _parse_manufacturing)
# ──────────────────────────────────────────────────────────────

# Canonical manufacturing process IDs and keyword aliases
# (port of src/tools/dfma.py _PROCESS_KEYWORDS).
_PROCESS_KEYWORDS: dict[str, str] = {
    "cnc milling": "CNC_milling",
    "cnc machining": "CNC_milling",
    "milling": "CNC_milling",
    "cnc turning": "CNC_turning",
    "turning": "CNC_turning",
    "lathe": "CNC_turning",
    "injection molding": "injection_molding",
    "injection moulding": "injection_molding",
    "sheet metal": "sheet_metal",
    "stamping": "sheet_metal",
    "3d printing": "3D_printing",
    "fdm": "3D_printing",
    "sla": "3D_printing",
    "additive": "3D_printing",
    "casting": "casting",
    "sand casting": "casting",
    "die casting": "casting",
}

CANONICAL_PROCESSES = (
    "CNC_milling", "CNC_turning", "injection_molding",
    "sheet_metal", "3D_printing", "casting",
)

_MFG_SECTION_RE = re.compile(
    r"##\s*(?:Material\s*/\s*)?Manufacturing(.*?)(?=\n##|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def parse_overall_dimensions(text: str) -> list[float] | None:
    """Extract dimensions from the 'Overall:' line in constraints.md.

    Handles real-world formats found across E2E projects:
      - '150 x 100 x 25 mm'            (prismatic, 3 dims)
      - '150mm diameter x 20mm height' (cylindrical, 2 dims)
      - '45mm outer diameter x 60mm height'
      - 'Approx. 10mm diameter, 5mm height'
      - '300 x 200 x 150 mm (L x W x H)'

    Returns sorted list of dimensions (2 or 3 floats), or None.
    """
    match = re.search(r"Overall:\s*(.+)", text, re.IGNORECASE)
    if not match:
        return None

    line = match.group(1)

    # Extract all numbers immediately followed by 'mm'
    dims = re.findall(r"([\d.]+)\s*mm", line, re.IGNORECASE)
    if len(dims) < 2:
        # Fallback: "N x N x N mm" format (units only at end)
        dims_match = re.findall(r"([\d.]+)\s*(?:[x×,]|mm)", line, re.IGNORECASE)
        if len(dims_match) >= 2:
            dims = dims_match

    if len(dims) < 2:
        return None

    return sorted(float(d) for d in dims)


def parse_manufacturing(text: str) -> str | None:
    """Extract the manufacturing process from constraints.md content.

    Searches for a ## Manufacturing section and matches known process
    keywords. Returns the canonical process ID (e.g. 'CNC_milling') or None.
    """
    mfg_match = _MFG_SECTION_RE.search(text)
    if not mfg_match:
        return None

    section = mfg_match.group(1).lower()
    for keyword, process_id in _PROCESS_KEYWORDS.items():
        if keyword in section:
            return process_id
    return None


def validate_constraints(text: str) -> dict:
    """Structural check of a constraints.md file."""
    has_overall_line = re.search(r"Overall:\s*(.+)", text, re.IGNORECASE) is not None
    dims = parse_overall_dimensions(text)
    has_mfg_section = _MFG_SECTION_RE.search(text) is not None
    process = parse_manufacturing(text)

    errors: list[str] = []
    if not has_overall_line:
        errors.append("missing 'Overall:' dimension line (expected under ## Dimensions)")
    elif dims is None:
        errors.append(
            "could not parse >=2 dimensions from the 'Overall:' line "
            "(expected e.g. '150 x 100 x 25 mm' or '45mm diameter x 60mm height')"
        )
    if not has_mfg_section:
        errors.append("missing '## Manufacturing' section")
    elif process is None:
        errors.append(
            "Manufacturing section present but no canonical process recognized "
            f"(canonical: {', '.join(CANONICAL_PROCESSES)})"
        )

    return {
        "validate": "constraints",
        "valid": dims is not None and process is not None,
        "checks": {
            "has_overall_line": has_overall_line,
            "overall_dimensions_sorted": dims,
            "has_manufacturing_section": has_mfg_section,
            "manufacturing_process": process,
        },
        "errors": errors,
    }


# ──────────────────────────────────────────────────────────────
# Design plan validation (structure per planner instructions template)
# ──────────────────────────────────────────────────────────────

_PARTS_SECTION_RE = re.compile(
    r"^##\s*Parts\s*$(.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL
)
_BUILD_ORDER_RE = re.compile(
    r"^##\s*(?:Assembly|Build)\s+Order\s*$(.*?)(?=^##\s|\Z)",
    re.MULTILINE | re.IGNORECASE | re.DOTALL,
)
_PARALLEL_SAFE_RE = re.compile(
    r"\*\*parallel_safe\*\*\s*:\s*(true|false)", re.IGNORECASE
)


def validate_design_plan(text: str) -> dict:
    """Structural check of a design_plan.md file.

    Verifies: a '## Parts' section with '### N. <part>' entries, a
    '## Assembly Order' (or '## Build Order') section with numbered
    entries, and a '**parallel_safe**: true|false' annotation on every
    part entry (planner's Parallel Safety Annotation contract).
    """
    errors: list[str] = []

    parts_match = _PARTS_SECTION_RE.search(text)
    has_parts_section = parts_match is not None
    parts_found: list[str] = []
    parallel_safe: dict[str, bool | None] = {}
    if parts_match:
        blocks = re.split(r"^###\s+", parts_match.group(1), flags=re.MULTILINE)[1:]
        for block in blocks:
            lines = block.splitlines()
            header = lines[0].strip() if lines else ""
            name = re.sub(r"^\d+\.\s*", "", header).strip()
            if not name:
                continue
            parts_found.append(name)
            ps = _PARALLEL_SAFE_RE.search(block)
            parallel_safe[name] = (ps.group(1).lower() == "true") if ps else None

    order_match = _BUILD_ORDER_RE.search(text)
    has_build_order = order_match is not None
    build_order_entries = 0
    if order_match:
        build_order_entries = len(
            re.findall(r"^\s*\d+\.", order_match.group(1), re.MULTILINE)
        )

    unannotated = [n for n, v in parallel_safe.items() if v is None]
    all_parts_annotated = bool(parts_found) and not unannotated

    if not has_parts_section:
        errors.append("missing '## Parts' section")
    elif not parts_found:
        errors.append("no '### N. <part>' entries found in the Parts section")
    if not has_build_order:
        errors.append("missing '## Assembly Order' (or '## Build Order') section")
    elif build_order_entries == 0:
        errors.append("build order section has no numbered entries")
    if unannotated:
        errors.append(
            f"parts missing '**parallel_safe**: true|false' annotation: {', '.join(unannotated)}"
        )

    return {
        "validate": "design_plan",
        "valid": (
            has_parts_section
            and bool(parts_found)
            and has_build_order
            and build_order_entries > 0
            and all_parts_annotated
        ),
        "checks": {
            "has_parts_section": has_parts_section,
            "parts_found": parts_found,
            "parallel_safe": parallel_safe,
            "all_parts_annotated": all_parts_annotated,
            "has_build_order": has_build_order,
            "build_order_entries": build_order_entries,
        },
        "errors": errors,
    }


# ──────────────────────────────────────────────────────────────
# Status validation (notes.md filesystem-bus marker)
# ──────────────────────────────────────────────────────────────


def validate_status(text: str) -> dict:
    """Check a notes.md for the 'VALIDATION: PASSED|FAILED' marker.

    Same precedence as the state scanner: PASSED is checked first, so if
    both markers appear, passed wins (legacy parity).
    """
    if "VALIDATION: PASSED" in text:
        status, has_marker = "passed", True
    elif "VALIDATION: FAILED" in text:
        status, has_marker = "failed", True
    else:
        status, has_marker = "not_validated", False

    errors: list[str] = []
    if not has_marker:
        errors.append(
            "no 'VALIDATION: PASSED' or 'VALIDATION: FAILED' marker found "
            "(the validator agent writes this to notes.md)"
        )

    return {
        "validate": "status",
        "valid": has_marker,
        "checks": {
            "has_validation_marker": has_marker,
            "validation_status": status,
        },
        "errors": errors,
    }


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

_VALIDATORS = {
    "design_plan": validate_design_plan,
    "constraints": validate_constraints,
    "status": validate_status,
}


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tools.spec_validator",
        description=(
            "Project state scanner + structural artifact checks. "
            "JSON to stdout; exit 0 = tool ran (JSON carries the verdict), "
            "exit 2 = tool malfunction."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--query", choices=["state"], help="Scan project state")
    mode.add_argument(
        "--validate",
        choices=sorted(_VALIDATORS),
        help="Structurally validate one artifact file",
    )
    parser.add_argument(
        "--project", help="Project directory (with --query), e.g. projects/<name>"
    )
    parser.add_argument("--file", help="Artifact file to validate (with --validate)")
    args = parser.parse_args(argv)

    if args.query and not args.project:
        parser.error("--query=state requires --project")
    if args.validate and not args.file:
        parser.error("--validate requires --file")
    return args


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: dispatch --query/--validate per the module docstring."""
    args = _parse_args(argv)
    root = Path.cwd()

    try:
        if args.query == "state":
            project = safe_path(root, args.project)
            if not project.is_dir():
                raise ToolError(f"Project directory not found: {args.project}")
            state = read_project_state(project)
            print(json.dumps(state, indent=2))
            print(
                f"[spec_validator] state: {state['parts_total']} parts, "
                f"{len(state['sub_assemblies'])} sub-assemblies, "
                f"{state['active_conflicts_count']} open conflicts",
                file=sys.stderr,
            )
        else:
            target = safe_path(root, args.file)
            if not target.is_file():
                raise ToolError(f"File not found: {args.file}")
            result = _VALIDATORS[args.validate](target.read_text())
            result["file"] = args.file
            print(json.dumps(result, indent=2))
            print(
                f"[spec_validator] {args.validate}: "
                f"{'VALID' if result['valid'] else 'INVALID — ' + '; '.join(result['errors'])}",
                file=sys.stderr,
            )
        return 0
    except ToolError as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        print(f"[spec_validator] ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
