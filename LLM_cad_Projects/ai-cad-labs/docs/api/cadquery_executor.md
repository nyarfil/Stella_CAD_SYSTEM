> Generated from the `tools/cadquery_executor.py` docstrings, never hand-edited.
> Regenerate with `uv run --frozen python tests/test_api_docs.py --write`.
<a id="tools.cadquery_executor"></a>

# tools.cadquery\_executor

CadQuery executor tool: runs CadQuery Python code in a controlled namespace.

Bash-first tool. Invoke from repo root:

```
uv run python -m tools.cadquery_executor --code-file <f>         [--part-path <p>] [--project-path <p>] [--subprocess] [--timeout N]
```

JSON contract (single object on stdout; human detail goes to stderr):

```
{
  "success": bool,              # code ran AND produced a solid
  "volume": float | null,       # mm^3 (null if not extractable)
  "bbox": {"xmin","xmax","ymin","ymax","zmin","zmax"} | null,
  "execution_time_ms": float,
  "error_message": str | null,  # full traceback, NEVER truncated
  "enriched_hint": str | null,  # corrective hint for known LLM hallucinations
  "result_type": str | null     # e.g. "Workplane", "Assembly", "Compound"
}
```

Exit codes: 0 = tool ran (even if the evaluated code failed; the JSON carries
the verdict); 2 = usage error (e.g. code file missing); 1 = tool malfunction.

Two execution modes:
1. In-process (ThreadPoolExecutor): fast. Cannot survive OCCT kernel SEGFAULTs.
2. --subprocess (multiprocessing.Process): ~500ms overhead via a STEP-file
   round-trip, but survives SEGFAULT crashes cleanly. Note: the STEP round-trip
   loses the original object type (result_type is the re-imported Workplane).

Namespace sandbox: `cq` and `cadquery` are pre-imported; `__project_path__`
(a Path) is injected when a project path is given or derivable, so assembly
code can locate part.py files. The result is taken from namespace["result"],
falling back to the last cq.Workplane bound in the namespace.

This module never imports cairosvg; rendering is a separate tool.

A third, lighter script runner (`execute_cad_script`, daemon-thread timeout,
cairo-free) lives in tools.dimension_checker and is shared with tools.renderer;
prefer this module's runners when SEGFAULT isolation or the JSON contract
above is needed.

<a id="tools.cadquery_executor.ExecutionResult"></a>

## ExecutionResult Objects

```python
@dataclass
class ExecutionResult()
```

Result of executing CAD code.

<a id="tools.cadquery_executor.ExecutionResult.namespace"></a>

#### namespace

Raw exec namespace, used for assembly part extraction

<a id="tools.cadquery_executor.safe_path"></a>

#### safe\_path

```python
def safe_path(project_path: Path, relative: str) -> Path
```

Resolve a relative path safely within the project directory.

Prevents path traversal attacks (e.g., ../../etc/passwd).
Every tool that resolves project-relative paths MUST use this.

<a id="tools.cadquery_executor.match_hint"></a>

#### match\_hint

```python
def match_hint(error_msg: str) -> str | None
```

Return the corrective hint for a known hallucination pattern, else None.

<a id="tools.cadquery_executor.CadQueryExecutor"></a>

## CadQueryExecutor Objects

```python
class CadQueryExecutor()
```

Execute CadQuery code strings and return the resulting solid.

Enforces execution timeout to prevent infinite loops.

<a id="tools.cadquery_executor.CadQueryExecutor.execute"></a>

#### execute

```python
def execute(code: str,
            timeout_s: int | None = None,
            project_path: Path | None = None) -> ExecutionResult
```

Execute CadQuery code with timeout enforcement.

<a id="tools.cadquery_executor.execute_in_subprocess"></a>

#### execute\_in\_subprocess

```python
def execute_in_subprocess(
        code: str,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        project_path: Path | None = None
) -> tuple[bool, str | None, Path | None]
```

Execute CadQuery code in an isolated subprocess.

If the OCCT C++ kernel SEGFAULTs, the child process dies but the parent
survives and returns a clean error. The solid crosses the process boundary
as a STEP file (OCCT objects can't be pickled).

Returns:
    (success, error_message, step_file_path)
    - On success: (True, None, Path to STEP file)
    - On failure: (False, error_message, None)

Cleanup caveat: the returned STEP file is a PERSISTENT temp file
(it outlives this call); the caller must delete it. run() does this
after re-import; a direct caller that skips deletion leaks temp files.

<a id="tools.cadquery_executor.derive_project_path"></a>

#### derive\_project\_path

```python
def derive_project_path(part_path: Path) -> Path | None
```

Derive the project root from a part path.

Walks up looking for the ancestor whose parent directory is named
'projects' (spec §1: project state lives under projects/&lt;name&gt;/).

<a id="tools.cadquery_executor.run"></a>

#### run

```python
def run(code: str,
        part_path: str | None = None,
        project_path: str | None = None,
        subprocess_mode: bool = False,
        timeout_s: int = DEFAULT_TIMEOUT_S) -> dict
```

Execute CadQuery code and return the JSON-contract output dict.

Project-path precedence: an explicit project_path wins; otherwise the
project root is derived from part_path via derive_project_path.
In subprocess mode the persistent temp STEP file returned by
execute_in_subprocess is deleted here after re-import.

<a id="tools.cadquery_executor.main"></a>

#### main

```python
def main(argv: list[str] | None = None) -> int
```

CLI entry point: read --code-file, execute via run(), print the JSON verdict.

