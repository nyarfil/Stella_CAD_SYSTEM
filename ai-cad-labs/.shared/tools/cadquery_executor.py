"""CadQuery executor tool: runs CadQuery Python code in a controlled namespace.

Bash-first tool. Invoke from repo root:

    uv run python -m tools.cadquery_executor --code-file <f> \
        [--part-path <p>] [--project-path <p>] [--subprocess] [--timeout N]

JSON contract (single object on stdout; human detail goes to stderr):

    {
      "success": bool,              # code ran AND produced a solid
      "volume": float | null,       # mm^3 (null if not extractable)
      "bbox": {"xmin","xmax","ymin","ymax","zmin","zmax"} | null,
      "execution_time_ms": float,
      "error_message": str | null,  # full traceback, NEVER truncated
      "enriched_hint": str | null,  # corrective hint for known LLM hallucinations
      "result_type": str | null     # e.g. "Workplane", "Assembly", "Compound"
    }

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
"""

from __future__ import annotations

import argparse
import json
import logging
import multiprocessing
import sys
import tempfile
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass
from pathlib import Path

import cadquery as cq

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 30


@dataclass
class ExecutionResult:
    """Result of executing CAD code."""

    success: bool
    solid: object | None = None
    error_message: str | None = None
    execution_time_ms: float = 0.0
    namespace: dict | None = None  # Raw exec namespace, used for assembly part extraction
    enriched_hint: str | None = None


def safe_path(project_path: Path, relative: str) -> Path:
    """Resolve a relative path safely within the project directory.

    Prevents path traversal attacks (e.g., ../../etc/passwd).
    Every tool that resolves project-relative paths MUST use this.
    """
    resolved = (project_path / relative).resolve()
    project_resolved = project_path.resolve()
    if not resolved.is_relative_to(project_resolved):
        raise ValueError(f"Path '{relative}' escapes project directory '{project_path}'")
    return resolved


# Corrective hints for common LLM hallucinations. When an LLM generates code
# using a non-existent CadQuery method, the error alone ("has no attribute
# 'hull'") doesn't tell it what to use instead. Matching a hint breaks the
# hallucination loop. Patterns + hint text ported verbatim from the legacy
# executor's _enrich_error.
_HINTS = {
    "has no attribute 'hull'": (
        "HINT: .hull() does not exist in CadQuery. "
        "To create an I-beam or H-beam cross section, use .polyline() to draw "
        "the profile shape, then .close().extrude(). For connecting two circular "
        "ends with a tapered beam, use boolean operations: create each cylinder "
        "separately, then .union() them with a rectangular beam body."
    ),
    "has no attribute 'fillet2D'": (
        "HINT: .fillet2D() does not exist. Use .fillet() on 3D edges AFTER extrude."
    ),
    "has no attribute 'cone'": (
        "HINT: .cone() does not exist as a Workplane method. "
        "Use cq.Solid.makeCone(radius1, radius2, height) instead."
    ),
    "has no attribute 'And'": (
        "HINT: cadquery.selectors.And does not exist. "
        "Use string selector combinations: .edges('|Z and >Y') or "
        "cadquery.selectors.AndSelector(sel1, sel2)."
    ),
    "has no attribute 'OrSelector'": (
        "HINT: cadquery.selectors.OrSelector does not exist. "
        "Use string selectors with 'or': .edges('|Z or |X')."
    ),
    "has no attribute 'Circle'": (
        "HINT: cq.Circle does not exist. Use .circle(radius) on a Workplane."
    ),
    "has no attribute 'makeHull'": (
        "HINT: Wire.makeHull() does not exist. "
        "Use .polyline() and .close() to create custom profiles."
    ),
    "Unknown color name": (
        "HINT: Valid CadQuery color names: red, green, blue, gray, lightgray, "
        "white, black, yellow, orange, cyan, magenta, brown, pink. "
        "Do NOT use 'silver', 'gold', or other CSS color names."
    ),
    "unexpected keyword argument 'centered'": (
        "HINT: CadQuery's .extrude() does NOT have a 'centered' kwarg. "
        "That's a Build123d API. Use .extrude(length) + .translate() to center. "
        "CadQuery extrude signature: extrude(until, combine=True, clean=True, both=False, taper=None)."
    ),
    "has no attribute 'EdgeCylinderSelector'": (
        "HINT: cq.selectors.EdgeCylinderSelector does not exist. "
        'Use the string selector "%CIRCLE" to select circular edges.'
    ),
}


def match_hint(error_msg: str) -> str | None:
    """Return the corrective hint for a known hallucination pattern, else None."""
    for pattern, hint in _HINTS.items():
        if pattern in error_msg:
            return hint
    return None


class CadQueryExecutor:
    """Execute CadQuery code strings and return the resulting solid.

    Enforces execution timeout to prevent infinite loops.
    """

    def __init__(self, timeout_s: int = DEFAULT_TIMEOUT_S):
        self.timeout_s = timeout_s

    def execute(
        self,
        code: str,
        timeout_s: int | None = None,
        project_path: Path | None = None,
    ) -> ExecutionResult:
        """Execute CadQuery code with timeout enforcement."""
        timeout = timeout_s or self.timeout_s
        start = time.perf_counter()

        logger.debug(f"[executor] Starting execution — {len(code.splitlines())} lines, timeout={timeout}s")

        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self._exec_in_namespace, code, project_path)
        try:
            result = future.result(timeout=timeout)
            elapsed = (time.perf_counter() - start) * 1000
            result.execution_time_ms = elapsed
            if result.success:
                logger.debug(f"[executor] Success — {elapsed:.0f}ms")
            else:
                logger.warning(f"[executor] Failed — {elapsed:.0f}ms — {result.error_message or ''}")
            return result
        except FuturesTimeout:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(f"[executor] TIMEOUT after {timeout}s — killing execution")
            # Don't wait for the hung thread — abandon it as a daemon
            pool.shutdown(wait=False, cancel_futures=True)
            return ExecutionResult(
                success=False,
                error_message=f"Execution timed out after {timeout}s. "
                "The code may contain an infinite loop or very expensive operations.",
                execution_time_ms=elapsed,
            )
        except Exception:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(f"[executor] Unexpected error — {traceback.format_exc()[:200]}")
            return ExecutionResult(
                success=False,
                error_message=traceback.format_exc(),
                execution_time_ms=elapsed,
            )
        finally:
            pool.shutdown(wait=False)

    def _exec_in_namespace(self, code: str, project_path: Path | None = None) -> ExecutionResult:
        """Execute code in a controlled namespace. Runs in a separate thread."""
        namespace: dict = {"cq": cq, "cadquery": cq}
        if project_path is not None:
            namespace["__project_path__"] = Path(project_path).resolve()

        try:
            exec(code, namespace)  # noqa: S102
        except Exception:
            error_msg = traceback.format_exc()
            return ExecutionResult(
                success=False,
                error_message=error_msg,
                enriched_hint=match_hint(error_msg),
            )

        # Find the result: look for 'result' variable, then last Workplane assigned
        solid = namespace.get("result")
        if solid is None:
            for val in reversed(list(namespace.values())):
                if isinstance(val, cq.Workplane):
                    solid = val
                    break

        if solid is None:
            return ExecutionResult(
                success=False,
                error_message="Code executed successfully but produced no CadQuery Workplane. "
                "Assign your final shape to a variable named 'result'.",
            )

        return ExecutionResult(
            success=True,
            solid=solid,
            namespace=namespace,
        )


def _worker(code: str, project_path_str: str | None, step_path: str, result_path: str):
    """Worker function that runs in a subprocess."""
    import cadquery as cq  # noqa: F811

    namespace: dict = {"cq": cq, "cadquery": cq}
    if project_path_str:
        namespace["__project_path__"] = Path(project_path_str).resolve()

    try:
        exec(code, namespace)  # noqa: S102
    except Exception:
        Path(result_path).write_text(f"EXEC_ERROR\n{traceback.format_exc()}")
        return

    solid = namespace.get("result")
    if solid is None:
        for val in reversed(list(namespace.values())):
            if isinstance(val, cq.Workplane):
                solid = val
                break

    if solid is None:
        Path(result_path).write_text("EXEC_ERROR\nNo 'result' variable found")
        return

    try:
        if hasattr(solid, "toCompound"):
            solid = solid.toCompound()
        cq.exporters.export(solid, step_path, "STEP")
        Path(result_path).write_text("SUCCESS")
    except Exception:
        Path(result_path).write_text(f"EXPORT_ERROR\n{traceback.format_exc()}")


def execute_in_subprocess(
    code: str,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    project_path: Path | None = None,
) -> tuple[bool, str | None, Path | None]:
    """Execute CadQuery code in an isolated subprocess.

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
    """
    start = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="cad_subprocess_") as tmpdir:
        step_path = str(Path(tmpdir) / "result.step")
        result_path = str(Path(tmpdir) / "result.txt")
        project_str = str(project_path.resolve()) if project_path else None

        proc = multiprocessing.Process(
            target=_worker,
            args=(code, project_str, step_path, result_path),
        )
        proc.start()
        proc.join(timeout=timeout_s)

        elapsed = (time.perf_counter() - start) * 1000

        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=5)
            if proc.is_alive():
                proc.kill()
            logger.error(f"[subprocess-executor] TIMEOUT after {timeout_s}s — killed")
            return False, f"Subprocess timed out after {timeout_s}s", None

        if proc.exitcode != 0:
            exit_code = proc.exitcode
            if exit_code == -11 or exit_code == 139:
                logger.error(f"[subprocess-executor] SEGFAULT (exit {exit_code}) — {elapsed:.0f}ms")
                return False, (
                    f"CadQuery/OCCT kernel crashed (SIGSEGV, exit code {exit_code}). "
                    "This geometry is too complex or triggers a kernel bug. "
                    "Try simplifying the geometry: fewer boolean operations, "
                    "simpler fillets, or break the part into sub-components."
                ), None
            else:
                logger.error(f"[subprocess-executor] Process died (exit {exit_code}) — {elapsed:.0f}ms")
                return False, f"Subprocess exited with code {exit_code}", None

        # Read result status
        result_file = Path(result_path)
        if not result_file.exists():
            return False, "Subprocess completed but produced no result file", None

        status = result_file.read_text()
        if status == "SUCCESS":
            step_file = Path(step_path)
            if step_file.exists():
                # Copy STEP to a persistent location (tmpdir will be deleted)
                persistent_step = Path(tempfile.mktemp(suffix=".step", prefix="cad_"))
                persistent_step.write_bytes(step_file.read_bytes())
                logger.info(f"[subprocess-executor] Success — {elapsed:.0f}ms, STEP={persistent_step.stat().st_size}B")
                return True, None, persistent_step
            return False, "Subprocess succeeded but STEP file not found", None
        else:
            error_msg = status.split("\n", 1)[1] if "\n" in status else status
            logger.warning(f"[subprocess-executor] Failed — {elapsed:.0f}ms")
            return False, error_msg, None


def _extract_geometry(solid: object) -> tuple[float | None, dict | None]:
    """Extract (volume, bbox) from a solid; (None, None) if not extractable."""
    try:
        val = solid.val() if hasattr(solid, "val") else solid
        volume = round(val.Volume(), 2)
        bb = val.BoundingBox()
        bbox = {
            "xmin": round(bb.xmin, 2),
            "xmax": round(bb.xmax, 2),
            "ymin": round(bb.ymin, 2),
            "ymax": round(bb.ymax, 2),
            "zmin": round(bb.zmin, 2),
            "zmax": round(bb.zmax, 2),
        }
        return volume, bbox
    except Exception:
        return None, None


def derive_project_path(part_path: Path) -> Path | None:
    """Derive the project root from a part path.

    Walks up looking for the ancestor whose parent directory is named
    'projects' (spec §1: project state lives under projects/<name>/).
    """
    resolved = part_path.resolve()
    for ancestor in [resolved, *resolved.parents]:
        if ancestor.parent.name == "projects":
            return ancestor
    return None


# Backward-compat alias for the pre-rename private name.
_derive_project_path = derive_project_path


def run(
    code: str,
    part_path: str | None = None,
    project_path: str | None = None,
    subprocess_mode: bool = False,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> dict:
    """Execute CadQuery code and return the JSON-contract output dict.

    Project-path precedence: an explicit project_path wins; otherwise the
    project root is derived from part_path via derive_project_path.
    In subprocess mode the persistent temp STEP file returned by
    execute_in_subprocess is deleted here after re-import.
    """
    proj: Path | None = Path(project_path) if project_path else None
    if proj is None and part_path:
        proj = derive_project_path(Path(part_path))

    output: dict = {
        "success": False,
        "volume": None,
        "bbox": None,
        "execution_time_ms": 0.0,
        "error_message": None,
        "enriched_hint": None,
        "result_type": None,
    }

    if subprocess_mode:
        start = time.perf_counter()
        success, error_msg, step_path = execute_in_subprocess(code, timeout_s, proj)
        output["execution_time_ms"] = round((time.perf_counter() - start) * 1000, 1)

        if not success:
            output["error_message"] = error_msg
            output["enriched_hint"] = match_hint(error_msg or "")
            return output

        # Re-import STEP to get the solid (needed for volume/bbox).
        # The round-trip loses the original type — result_type reflects the re-import.
        try:
            solid = cq.importers.importStep(str(step_path))
            output["success"] = True
            output["result_type"] = type(solid).__name__
            output["volume"], output["bbox"] = _extract_geometry(solid)
        except Exception as e:
            # Legacy behavior: code DID execute — report success with a note.
            output["success"] = True
            output["error_message"] = f"Code executed but STEP re-import failed: {e}"
        finally:
            if step_path and step_path.exists():
                step_path.unlink(missing_ok=True)
        return output

    executor = CadQueryExecutor(timeout_s=timeout_s)
    result = executor.execute(code, project_path=proj)

    output["success"] = result.success
    output["execution_time_ms"] = round(result.execution_time_ms, 1)
    output["error_message"] = result.error_message
    output["enriched_hint"] = result.enriched_hint

    if result.success and result.solid is not None:
        output["result_type"] = type(result.solid).__name__
        output["volume"], output["bbox"] = _extract_geometry(result.solid)

    return output


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: read --code-file, execute via run(), print the JSON verdict."""
    parser = argparse.ArgumentParser(
        prog="tools.cadquery_executor",
        description="Execute CadQuery code in a sandboxed namespace; JSON verdict on stdout.",
    )
    parser.add_argument("--code-file", required=True, help="Path to file containing CadQuery Python code")
    parser.add_argument("--part-path", default=None,
                        help="Part directory (used to derive the project root for __project_path__)")
    parser.add_argument("--project-path", default=None,
                        help="Project root injected as __project_path__ (overrides derivation from --part-path)")
    parser.add_argument("--subprocess", action="store_true",
                        help="Run in an isolated subprocess (survives OCCT SEGFAULTs; ~500ms overhead)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S, help="Timeout in seconds (default 30)")
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(message)s")

    code_file = Path(args.code_file)
    if not code_file.exists():
        print(json.dumps({
            "success": False, "volume": None, "bbox": None, "execution_time_ms": 0.0,
            "error_message": f"Code file not found: {code_file}",
            "enriched_hint": None, "result_type": None,
        }))
        return 2

    try:
        output = run(
            code_file.read_text(),
            part_path=args.part_path,
            project_path=args.project_path,
            subprocess_mode=args.subprocess,
            timeout_s=args.timeout,
        )
    except Exception:
        print(json.dumps({
            "success": False, "volume": None, "bbox": None, "execution_time_ms": 0.0,
            "error_message": f"Tool malfunction:\n{traceback.format_exc()}",
            "enriched_hint": None, "result_type": None,
        }))
        return 1

    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
