> Generated from the `tools/spec_validator.py` docstrings, never hand-edited.
> Regenerate with `uv run --frozen python tests/test_api_docs.py --write`.
<a id="tools.spec_validator"></a>

# tools.spec\_validator

Spec validator: project state scanner + structural artifact checks (CLI).

Plain CLI (bash-first, JSON to stdout, human detail to stderr).

Usage (cwd = repo root):
    uv run python -m tools.spec_validator --query=state --project=projects/&lt;name&gt;
    uv run python -m tools.spec_validator --validate=design_plan --file &lt;f&gt;
    uv run python -m tools.spec_validator --validate=constraints --file &lt;f&gt;
    uv run python -m tools.spec_validator --validate=status --file &lt;f&gt;

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

```
NOTE: the legacy BudgetStatus block is omitted; token/spawn counters
lived in PydanticAI orchestrator deps and are not visible to a CLI
(attempt-count proxy replaces the legacy token budget).
```

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

<a id="tools.spec_validator.ToolError"></a>

## ToolError Objects

```python
class ToolError(Exception)
```

Controlled tool malfunction (bad path, missing input) → exit 2.

<a id="tools.spec_validator.safe_path"></a>

#### safe\_path

```python
def safe_path(root: Path, relative: str) -> Path
```

Resolve a path safely within the invocation root.

Prevents path traversal (e.g. ../../etc/passwd). Raises ToolError
on escape (CLI-shaped).

<a id="tools.spec_validator.read_project_state"></a>

#### read\_project\_state

```python
def read_project_state(root: Path) -> dict
```

Scan a project directory and return the ProjectState-equivalent dict.

Scans the actual directory to determine state; never trusts cached
data. For top-level projects, parts live under assembly/. For
sub-orchestrator scopes (no assembly/ dir), parts live directly in root.

<a id="tools.spec_validator.parse_overall_dimensions"></a>

#### parse\_overall\_dimensions

```python
def parse_overall_dimensions(text: str) -> list[float] | None
```

Extract dimensions from the 'Overall:' line in constraints.md.

Handles real-world formats found across E2E projects:
  - '150 x 100 x 25 mm'            (prismatic, 3 dims)
  - '150mm diameter x 20mm height' (cylindrical, 2 dims)
  - '45mm outer diameter x 60mm height'
  - 'Approx. 10mm diameter, 5mm height'
  - '300 x 200 x 150 mm (L x W x H)'

Returns sorted list of dimensions (2 or 3 floats), or None.

<a id="tools.spec_validator.parse_manufacturing"></a>

#### parse\_manufacturing

```python
def parse_manufacturing(text: str) -> str | None
```

Extract the manufacturing process from constraints.md content.

Searches for a ## Manufacturing section and matches known process
keywords. Returns the canonical process ID (e.g. 'CNC_milling') or None.

<a id="tools.spec_validator.validate_constraints"></a>

#### validate\_constraints

```python
def validate_constraints(text: str) -> dict
```

Structural check of a constraints.md file.

<a id="tools.spec_validator.validate_design_plan"></a>

#### validate\_design\_plan

```python
def validate_design_plan(text: str) -> dict
```

Structural check of a design_plan.md file.

Verifies: a '## Parts' section with '### N. &lt;part&gt;' entries, a
'## Assembly Order' (or '## Build Order') section with numbered
entries, and a '**parallel_safe**: true|false' annotation on every
part entry (planner's Parallel Safety Annotation contract).

<a id="tools.spec_validator.validate_status"></a>

#### validate\_status

```python
def validate_status(text: str) -> dict
```

Check a notes.md for the 'VALIDATION: PASSED|FAILED' marker.

Same precedence as the state scanner: PASSED is checked first, so if
both markers appear, passed wins (legacy parity).

<a id="tools.spec_validator.main"></a>

#### main

```python
def main(argv: list[str] | None = None) -> int
```

CLI entry point: dispatch --query/--validate per the module docstring.

