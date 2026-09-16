> Generated from the `tools/dimension_checker.py` docstrings, never hand-edited.
> Regenerate with `uv run --frozen python tests/test_api_docs.py --write`.
<a id="tools.dimension_checker"></a>

# tools.dimension\_checker

Dimension checker: deterministic bbox-vs-constraints verification.

Besides the dimension checks, this module hosts `execute_cad_script`, the
lightweight CadQuery script runner shared with `tools.renderer` (kept here so
this module stays cairo-free; dimension checking needs cadquery only).

CLI:
    uv run python -m tools.dimension_checker --part-path &lt;dir&gt; --constraints-file &lt;f&gt;

`--part-path` is the part DIRECTORY containing part.py (executed to obtain the
bounding box). `--constraints-file` is the constraints.md whose "Overall:" line
holds the expected envelope.

JSON contract (single object on stdout; human detail on stderr):
    {
      "pass": true | false | null,   # null = not evaluable (missing/broken part.py,
                                     #        missing constraints, no "Overall:" line)
      "expected": [sorted mm floats] | null,
      "actual":   [sorted mm floats] | null,
      "deviations": ["Dim[0]: expected ~150mm, got 80mm (47% off)", ...],
      "error_message": str | null
    }

Field mapping from the legacy in-process dict: expected_sorted -&gt; expected,
actual_sorted -&gt; actual, violations -&gt; deviations, status PASS/FAIL -&gt; pass.

Exit 0 on tool-success even when pass=false (the JSON carries the verdict);
exit != 0 only on tool malfunction. Error messages are never truncated.

<a id="tools.dimension_checker.execute_cad_script"></a>

#### execute\_cad\_script

```python
def execute_cad_script(
    code: str,
    project_path: Path | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S
) -> tuple[object | None, dict | None, str | None]
```

Execute CadQuery code in a controlled namespace with a timeout.

Ports the legacy executor's result discovery: the `result` variable first,
else the last `cq.Workplane` found in the namespace. Runs in a daemon
thread so a hung script cannot block CLI process exit.

This is the lightweight, cairo-free runner; for OCCT SEGFAULT isolation
or the full JSON contract, use the runners in tools.cadquery_executor.

Returns (solid, namespace, error_message); solid is None on failure.

<a id="tools.dimension_checker.bbox_of"></a>

#### bbox\_of

```python
def bbox_of(solid: object) -> dict | None
```

Bounding box of a Workplane/Shape as a rounded dict, or None on failure.

<a id="tools.dimension_checker.parse_overall_dimensions"></a>

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

<a id="tools.dimension_checker.check_dimensions"></a>

#### check\_dimensions

```python
def check_dimensions(bbox: dict, constraints_text: str) -> dict | None
```

Compare a bounding box against the constraints 'Overall:' spec.

Handles both prismatic (3D) and cylindrical (2D diameter+height) parts.
Sorts expected and actual dimensions before comparing to handle axis
ambiguity. Uses 15% tolerance.

Returns {"pass", "expected", "actual", "deviations"} or None when the
constraints text has no parseable 'Overall:' line.

<a id="tools.dimension_checker.main"></a>

#### main

```python
def main(argv: list[str] | None = None) -> int
```

CLI entry point: check part.py's bounding box against constraints.md.

Asymmetry note: this CLI executes part.py WITHOUT __project_path__
injection (there is no --project-path flag), so parts that import
sibling project files cannot be checked here; tools.renderer's
in-process call to execute_cad_script does pass the project path.

