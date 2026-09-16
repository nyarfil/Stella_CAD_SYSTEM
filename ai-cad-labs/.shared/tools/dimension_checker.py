"""Dimension checker: deterministic bbox-vs-constraints verification.

Besides the dimension checks, this module hosts `execute_cad_script`, the
lightweight CadQuery script runner shared with `tools.renderer` (kept here so
this module stays cairo-free; dimension checking needs cadquery only).

CLI:
    uv run python -m tools.dimension_checker --part-path <dir> --constraints-file <f>

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

Field mapping from the legacy in-process dict: expected_sorted -> expected,
actual_sorted -> actual, violations -> deviations, status PASS/FAIL -> pass.

Exit 0 on tool-success even when pass=false (the JSON carries the verdict);
exit != 0 only on tool malfunction. Error messages are never truncated.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import traceback
from pathlib import Path

import cadquery as cq

DEFAULT_TIMEOUT_S = 30

# 15% tolerance — catches major errors without false-flagging rounding
DIMENSION_TOLERANCE = 0.15


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def execute_cad_script(
    code: str,
    project_path: Path | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> tuple[object | None, dict | None, str | None]:
    """Execute CadQuery code in a controlled namespace with a timeout.

    Ports the legacy executor's result discovery: the `result` variable first,
    else the last `cq.Workplane` found in the namespace. Runs in a daemon
    thread so a hung script cannot block CLI process exit.

    This is the lightweight, cairo-free runner; for OCCT SEGFAULT isolation
    or the full JSON contract, use the runners in tools.cadquery_executor.

    Returns (solid, namespace, error_message); solid is None on failure.
    """
    namespace: dict = {"cq": cq, "cadquery": cq}
    if project_path is not None:
        namespace["__project_path__"] = Path(project_path).resolve()

    outcome: dict = {}

    def _run() -> None:
        try:
            exec(code, namespace)  # noqa: S102 — sandboxed by namespace, as in legacy
            outcome["ok"] = True
        except Exception:
            outcome["error"] = traceback.format_exc()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout_s)

    if thread.is_alive():
        return None, None, (
            f"Execution timed out after {timeout_s}s. "
            "The code may contain an infinite loop or very expensive operations."
        )
    if "error" in outcome:
        return None, None, outcome["error"]

    solid = namespace.get("result")
    if solid is None:
        for val in reversed(list(namespace.values())):
            if isinstance(val, cq.Workplane):
                solid = val
                break

    if solid is None:
        return None, namespace, (
            "Code executed successfully but produced no CadQuery Workplane. "
            "Assign your final shape to a variable named 'result'."
        )
    return solid, namespace, None


def bbox_of(solid: object) -> dict | None:
    """Bounding box of a Workplane/Shape as a rounded dict, or None on failure."""
    try:
        val = solid.val() if hasattr(solid, "val") else solid
        bb = val.BoundingBox()
        return {
            "xmin": round(bb.xmin, 2), "xmax": round(bb.xmax, 2),
            "ymin": round(bb.ymin, 2), "ymax": round(bb.ymax, 2),
            "zmin": round(bb.zmin, 2), "zmax": round(bb.zmax, 2),
        }
    except Exception:
        return None


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


def check_dimensions(bbox: dict, constraints_text: str) -> dict | None:
    """Compare a bounding box against the constraints 'Overall:' spec.

    Handles both prismatic (3D) and cylindrical (2D diameter+height) parts.
    Sorts expected and actual dimensions before comparing to handle axis
    ambiguity. Uses 15% tolerance.

    Returns {"pass", "expected", "actual", "deviations"} or None when the
    constraints text has no parseable 'Overall:' line.
    """
    expected = parse_overall_dimensions(constraints_text)
    if not expected:
        return None

    actual_dims = sorted([
        round(bbox["xmax"] - bbox["xmin"], 1),
        round(bbox["ymax"] - bbox["ymin"], 1),
        round(bbox["zmax"] - bbox["zmin"], 1),
    ])

    # For cylindrical parts (2 dims: diameter + height), compare smallest
    # actual (height) against smallest expected, and largest actual (diameter)
    # against largest expected. The middle actual dim equals diameter for
    # true cylinders — we skip it to avoid double-counting.
    if len(expected) == 2:
        actual_compare = [actual_dims[0], actual_dims[2]]  # smallest + largest
    else:
        actual_compare = actual_dims

    deviations = []
    for i, (exp, act) in enumerate(zip(expected, actual_compare)):
        if exp > 0 and abs(act - exp) / exp > DIMENSION_TOLERANCE:
            pct = abs(act - exp) / exp * 100
            deviations.append(
                f"Dim[{i}]: expected ~{exp}mm, got {act}mm ({pct:.0f}% off)"
            )

    return {
        "pass": not deviations,
        "expected": expected,
        "actual": [round(d, 1) for d in actual_dims],
        "deviations": deviations,
    }


def _emit(result: dict) -> None:
    print(json.dumps(result, indent=2))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: check part.py's bounding box against constraints.md.

    Asymmetry note: this CLI executes part.py WITHOUT __project_path__
    injection (there is no --project-path flag), so parts that import
    sibling project files cannot be checked here; tools.renderer's
    in-process call to execute_cad_script does pass the project path.
    """
    parser = argparse.ArgumentParser(
        prog="python -m tools.dimension_checker",
        description="Compare a part's bounding box against its constraints.md 'Overall:' spec.",
    )
    parser.add_argument("--part-path", required=True,
                        help="Part directory containing part.py")
    parser.add_argument("--constraints-file", required=True,
                        help="Path to constraints.md with an 'Overall:' line")
    args = parser.parse_args(argv)

    not_evaluable = {"pass": None, "expected": None, "actual": None, "deviations": []}

    part_dir = Path(args.part_path)
    part_py = part_dir / "part.py"
    if not part_py.exists():
        _emit({**not_evaluable, "error_message": f"No part.py found at {part_py}"})
        return 0

    constraints_path = Path(args.constraints_file)
    if not constraints_path.exists():
        _emit({**not_evaluable, "error_message": f"No constraints file at {constraints_path}"})
        return 0

    _log(f"[dimension_checker] Executing {part_py}")
    solid, _namespace, error = execute_cad_script(part_py.read_text())
    if solid is None:
        _emit({**not_evaluable, "error_message": f"part.py failed to execute: {error}"})
        return 0

    bbox = bbox_of(solid)
    if bbox is None:
        _emit({**not_evaluable,
               "error_message": "Could not compute bounding box for the executed solid"})
        return 0

    result = check_dimensions(bbox, constraints_path.read_text())
    if result is None:
        _emit({**not_evaluable,
               "error_message": f"No parseable 'Overall:' line in {constraints_path}"})
        return 0

    _log(f"[dimension_checker] {'PASS' if result['pass'] else 'FAIL'} — "
         f"expected {result['expected']}, actual {result['actual']}")
    _emit({**result, "error_message": None})
    return 0


if __name__ == "__main__":
    sys.exit(main())
