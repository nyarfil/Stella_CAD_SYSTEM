"""Placeholder detector: is a part.py a real design or a stub? (CLI).

A standalone check the validator subagent calls before wasting a
render/vision cycle on a scaffold stub.

A part.py is a placeholder if (checked in this order, first hit wins,
legacy parity):
  1. it has <3 substantive code lines (non-empty, non-comment, non-'\"\"\"',
     non-import/from lines),
  2. it contains the default scaffold geometry box(10, 10, 10) (with or
     without spaces),
  3. it contains 'placeholder' (case-insensitive) or 'TODO' (case-sensitive)
     markers.

Usage (cwd = repo root):
    uv run python -m tools.placeholder_detector --part-path <part-dir>

JSON contract (stdout, single object):
    {is_placeholder: bool, reason: str | null}
    reason carries the legacy WARNING message for the first triggered check;
    null when the code looks like a real design.

Exit codes: 0 = tool ran (JSON carries the verdict, even when the part IS
a placeholder); 2 = tool malfunction (bad path, path escaping the
invocation root, missing part.py). Error messages are never truncated.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path


class ToolError(Exception):
    """Controlled tool malfunction (bad path, missing input) → exit 2."""


def safe_path(root: Path, relative: str) -> Path:
    """Resolve a path safely within the invocation root (no traversal)."""
    resolved = (root / relative).resolve()
    root_resolved = root.resolve()
    if not resolved.is_relative_to(root_resolved):
        raise ToolError(f"Path '{relative}' escapes invocation root '{root}'")
    return resolved


def detect_placeholder(code: str) -> str | None:
    """Return a warning if code looks like a placeholder, not a real design.

    Verbatim port of legacy _detect_placeholder: same filters, same check
    order, same messages.
    """
    lines = [l.strip() for l in code.splitlines()
             if l.strip() and not l.strip().startswith('#') and not l.strip().startswith('"""')]
    code_lines = [l for l in lines if not l.startswith('import') and not l.startswith('from')]
    if len(code_lines) <= 2:
        return ("WARNING: This code has very few lines and appears to be a placeholder. "
                "A real part design should have parametric dimensions, geometry operations, "
                "and feature definitions. Please write the actual part code.")
    if 'box(10, 10, 10)' in code or 'box(10,10,10)' in code:
        return ("WARNING: This code uses the default placeholder box(10,10,10). "
                "Replace with actual part geometry per the constraints.")
    if 'placeholder' in code.lower() or 'TODO' in code:
        return ("WARNING: This code contains placeholder/TODO markers. "
                "Complete the actual part design before saving.")
    return None


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: run detect_placeholder on --part-path, print the JSON verdict."""
    parser = argparse.ArgumentParser(
        prog="python -m tools.placeholder_detector",
        description=(
            "Check whether a part directory's part.py is a placeholder stub. "
            "JSON to stdout; exit 0 = tool ran (JSON carries the verdict), "
            "exit 2 = tool malfunction."
        ),
    )
    parser.add_argument(
        "--part-path", required=True,
        help="Part directory containing part.py, e.g. projects/<name>/assembly/<part>",
    )
    args = parser.parse_args(argv)
    root = Path.cwd()

    try:
        part_dir = safe_path(root, args.part_path)
        part_py = part_dir / "part.py"
        if not part_py.is_file():
            raise ToolError(f"part.py not found in part directory: {args.part_path}")

        reason = detect_placeholder(part_py.read_text())
        print(json.dumps({"is_placeholder": reason is not None, "reason": reason}, indent=2))
        print(
            f"[placeholder_detector] {part_py}: "
            f"{'PLACEHOLDER — ' + reason if reason else 'looks like a real design'}",
            file=sys.stderr,
        )
        return 0
    except ToolError as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        print(f"[placeholder_detector] ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
