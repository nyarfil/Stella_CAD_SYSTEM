"""CAD exporter tool: exports a part to manufacturable file formats.

Bash-first tool. Invoke from repo root:

    uv run python -m tools.exporter --part-path <p> [--formats step,stl] \
        [--project-path <p>] [--timeout N]

Executes the part directory's part.py, then exports the resulting solid:
    STEP = exact B-rep geometry (for CNC, injection molding)
    STL  = tessellated triangles (for 3D printing, visualization)
Files are written to <part-path>/exports/<part-name>.<fmt>.

JSON contract (single object on stdout; human detail goes to stderr):

    {
      "success": bool,             # at least one format exported
      "paths": {"step": str, "stl": str},   # only formats that succeeded
      "error_message": str | null  # export/exec errors, NEVER truncated
    }

Exit codes: 0 = tool ran (even if the part failed to execute/export; the
JSON carries the verdict); 2 = usage error; 1 = tool malfunction.

--part-path resolution: taken as-is (cwd-relative or absolute). If
--project-path is given and --part-path is relative, it is resolved
project-relative via safe_path (legacy semantics, traversal-guarded).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from pathlib import Path

import cadquery as cq

from tools.cadquery_executor import (
    DEFAULT_TIMEOUT_S,
    CadQueryExecutor,
    derive_project_path,
    safe_path,
)

logger = logging.getLogger(__name__)

_FORMAT_MAP = {"step": "STEP", "stl": "STL"}


def export_part(
    part_path: str,
    formats: str = "step,stl",
    project_path: str | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> dict:
    """Execute a part.py and export the solid; returns the JSON-contract dict.

    Partial-success semantics: "success" is True when AT LEAST ONE requested
    format exported; formats that failed are reported in "error_message" and
    omitted from "paths".
    """
    proj: Path | None = Path(project_path) if project_path else None
    if proj is not None and not Path(part_path).is_absolute():
        part_dir = safe_path(proj, part_path)
    else:
        part_dir = Path(part_path).resolve()
    if proj is None:
        proj = derive_project_path(part_dir)

    part_py = part_dir / "part.py"
    if not part_py.exists():
        return {"success": False, "paths": {},
                "error_message": f"No part.py found at {part_path}/part.py"}

    executor = CadQueryExecutor(timeout_s=timeout_s)
    exec_result = executor.execute(part_py.read_text(), project_path=proj)

    if not exec_result.success:
        return {"success": False, "paths": {},
                "error_message": f"part.py failed to execute: {exec_result.error_message}"}

    exports_dir = part_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    requested = [f.strip().lower() for f in formats.split(",") if f.strip()]
    exported: dict[str, str] = {}
    errors: list[str] = []

    for fmt in requested:
        cq_type = _FORMAT_MAP.get(fmt)
        if cq_type is None:
            errors.append(f"Unknown format '{fmt}'. Supported: step, stl")
            continue

        out_path = exports_dir / f"{part_dir.name}.{fmt}"
        try:
            cq.exporters.export(exec_result.solid, str(out_path), cq_type)
            exported[fmt] = str(out_path)
            logger.info(f"[export] Exported {fmt.upper()}: {out_path} ({out_path.stat().st_size} bytes)")
        except Exception as e:
            errors.append(f"{fmt.upper()} export failed: {str(e)}")
            logger.error(f"[export] {fmt.upper()} export failed: {e}")

    return {
        "success": len(exported) > 0,
        "paths": exported,
        "error_message": "; ".join(errors) if errors else None,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: parse args, run export_part, print the JSON verdict."""
    parser = argparse.ArgumentParser(
        prog="tools.exporter",
        description="Execute a part.py and export STEP/STL; JSON verdict on stdout.",
    )
    parser.add_argument("--part-path", required=True, help="Part directory containing part.py")
    parser.add_argument("--formats", default="step,stl", help="Comma-separated formats (default: step,stl)")
    parser.add_argument("--project-path", default=None,
                        help="Project root: injected as __project_path__ and used to resolve a relative --part-path")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S, help="Timeout in seconds (default 30)")
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        output = export_part(
            args.part_path,
            formats=args.formats,
            project_path=args.project_path,
            timeout_s=args.timeout,
        )
    except Exception:
        print(json.dumps({
            "success": False, "paths": {},
            "error_message": f"Tool malfunction:\n{traceback.format_exc()}",
        }))
        return 1

    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
