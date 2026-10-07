"""Install a built local wheel in a temporary target and exercise its MCP.

No package index, source checkout imports, global install, CAD or project writes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    with zipfile.ZipFile(wheel) as archive:
        bundled = archive.namelist()
        for name in ("mouse_library/data/library.json", "mouse_library/data/measurements.json"):
            if name not in bundled:
                raise RuntimeError(f"Wheel omits {name}")
        source_root = Path(__file__).resolve().parents[1]
        checked_files = ["mouse_library/__init__.py", "mouse_library/__main__.py",
                         "mouse_library/click_window.py",
                         "mouse_library/data/library.json", "mouse_library/data/measurements.json"]
        source_hashes = {}
        for name in checked_files:
            source_digest = hashlib.sha256((source_root / name).read_bytes()).hexdigest()
            if hashlib.sha256(archive.read(name)).hexdigest() != source_digest:
                raise RuntimeError(f"Wheel is stale relative to source: {name}")
            source_hashes[name] = source_digest
    frames = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "portable-wheel-check", "version": "0.1.0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "mouse_library_status", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 3, "method": "resources/read", "params": {
            "uri": "mouse-library://measurements"}},
        {"jsonrpc":"2.0","id":4,"method":"tools/call","params":{
            "name":"mouse_library_click_window","arguments":{
                "hardware_id":"Portable generic hardware; unmeasured",
                "coordinate_basis":"Common u=0, unknown actual measurements; no default dimensions",
                "quantities":{},"state_context":{}}}},
    ]
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    with tempfile.TemporaryDirectory(prefix="mouse-library-wheel-") as tmp:
        target = Path(tmp) / "installed"
        install = subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps",
                                  "--target", str(target), str(wheel)],
                                 capture_output=True, text=True, encoding="utf-8", timeout=60, env=env)
        if install.returncode:
            raise RuntimeError(install.stderr[:2000])
        # Isolated Python: only the newly installed package is added to sys.path.
        runner = "import sys,runpy;sys.path.insert(0,sys.argv[1]);runpy.run_module('mouse_library',run_name='__main__')"
        run = subprocess.run([sys.executable, "-I", "-c", runner, str(target)], cwd=tmp, env=env,
                             input="".join(json.dumps(frame) + "\n" for frame in frames),
                             capture_output=True, text=True, encoding="utf-8", timeout=30)
        if run.returncode or run.stderr:
            raise RuntimeError(f"Installed MCP failed: {run.stderr[:2000]}")
        replies = [json.loads(line) for line in run.stdout.splitlines()]
        status_result = replies[1]["result"]
        if status_result.get("isError"):
            raise RuntimeError(status_result)
        status = status_result["structuredContent"]["result"]
        measurements = json.loads(replies[2]["result"]["contents"][0]["text"])
        click_result = replies[3]["result"]
        if click_result.get("isError") or click_result["structuredContent"]["result"]["status"] != "not_evaluated_missing_inputs":
            raise RuntimeError("Installed click tool did not preserve missing inputs")
        expected_entries = len(json.loads((source_root / "mouse_library/data/library.json").read_text(encoding="utf-8"))["entries"])
        expected_reports = len(json.loads((source_root / "mouse_library/data/measurements.json").read_text(encoding="utf-8"))["reports"])
        if status["entry_count"] != expected_entries or len(measurements["reports"]) != expected_reports:
            raise RuntimeError("Unexpected package content counts")
    result = {
        "status": "passed",
        "scope": "wheel contents, temporary offline installation, isolated MCP initialization/status/measurement resource/generic click missing-input evaluation",
        "wheel": wheel.name,
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "wheel_source_files_match": True,
        "source_file_sha256": source_hashes,
        "library_provenance": status["library_provenance"],
        "entry_count": status["entry_count"],
        "measurement_report_count": len(measurements["reports"]),
        "cad_or_existing_project_writes": False,
        "not_verified": ["Other operating systems and MCP host applications", "Complete mouse CAD or physical fit/performance"],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("status", "wheel", "wheel_sha256", "entry_count", "measurement_report_count")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
