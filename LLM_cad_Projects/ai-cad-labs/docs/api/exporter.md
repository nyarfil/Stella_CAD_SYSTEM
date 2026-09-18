> Generated from the `tools/exporter.py` docstrings, never hand-edited.
> Regenerate with `uv run --frozen python tests/test_api_docs.py --write`.
<a id="tools.exporter"></a>

# tools.exporter

CAD exporter tool: exports a part to manufacturable file formats.

Bash-first tool. Invoke from repo root:

```
uv run python -m tools.exporter --part-path <p> [--formats step,stl]         [--project-path <p>] [--timeout N]
```

Executes the part directory's part.py, then exports the resulting solid:
    STEP = exact B-rep geometry (for CNC, injection molding)
    STL  = tessellated triangles (for 3D printing, visualization)
Files are written to &lt;part-path&gt;/exports/&lt;part-name&gt;.&lt;fmt&gt;.

JSON contract (single object on stdout; human detail goes to stderr):

```
{
  "success": bool,             # at least one format exported
  "paths": {"step": str, "stl": str},   # only formats that succeeded
  "error_message": str | null  # export/exec errors, NEVER truncated
}
```

Exit codes: 0 = tool ran (even if the part failed to execute/export; the
JSON carries the verdict); 2 = usage error; 1 = tool malfunction.

--part-path resolution: taken as-is (cwd-relative or absolute). If
--project-path is given and --part-path is relative, it is resolved
project-relative via safe_path (legacy semantics, traversal-guarded).

<a id="tools.exporter.export_part"></a>

#### export\_part

```python
def export_part(part_path: str,
                formats: str = "step,stl",
                project_path: str | None = None,
                timeout_s: int = DEFAULT_TIMEOUT_S) -> dict
```

Execute a part.py and export the solid; returns the JSON-contract dict.

Partial-success semantics: "success" is True when AT LEAST ONE requested
format exported; formats that failed are reported in "error_message" and
omitted from "paths".

<a id="tools.exporter.main"></a>

#### main

```python
def main(argv: list[str] | None = None) -> int
```

CLI entry point: parse args, run export_part, print the JSON verdict.

