> Generated from the `tools/placeholder_detector.py` docstrings, never hand-edited.
> Regenerate with `uv run --frozen python tests/test_api_docs.py --write`.
<a id="tools.placeholder_detector"></a>

# tools.placeholder\_detector

Placeholder detector: is a part.py a real design or a stub? (CLI).

A standalone check the validator subagent calls before wasting a
render/vision cycle on a scaffold stub.

A part.py is a placeholder if (checked in this order, first hit wins,
legacy parity):
  1. it has &lt;3 substantive code lines (non-empty, non-comment, non-'"""',
     non-import/from lines),
  2. it contains the default scaffold geometry box(10, 10, 10) (with or
     without spaces),
  3. it contains 'placeholder' (case-insensitive) or 'TODO' (case-sensitive)
     markers.

Usage (cwd = repo root):
    uv run python -m tools.placeholder_detector --part-path &lt;part-dir&gt;

JSON contract (stdout, single object):
    {is_placeholder: bool, reason: str | null}
    reason carries the legacy WARNING message for the first triggered check;
    null when the code looks like a real design.

Exit codes: 0 = tool ran (JSON carries the verdict, even when the part IS
a placeholder); 2 = tool malfunction (bad path, path escaping the
invocation root, missing part.py). Error messages are never truncated.

<a id="tools.placeholder_detector.ToolError"></a>

## ToolError Objects

```python
class ToolError(Exception)
```

Controlled tool malfunction (bad path, missing input) → exit 2.

<a id="tools.placeholder_detector.safe_path"></a>

#### safe\_path

```python
def safe_path(root: Path, relative: str) -> Path
```

Resolve a path safely within the invocation root (no traversal).

<a id="tools.placeholder_detector.detect_placeholder"></a>

#### detect\_placeholder

```python
def detect_placeholder(code: str) -> str | None
```

Return a warning if code looks like a placeholder, not a real design.

Verbatim port of legacy _detect_placeholder: same filters, same check
order, same messages.

<a id="tools.placeholder_detector.main"></a>

#### main

```python
def main(argv: list[str] | None = None) -> int
```

CLI entry point: run detect_placeholder on --part-path, print the JSON verdict.

