from __future__ import annotations
import importlib.util
import json
import os
import subprocess
import sys
from .errors import BrainError


def available():
    return importlib.util.find_spec("cadquery") is not None


def run_measurements(artifacts: dict[str,str],pairs=None,timeout=60):
    if not available():
        raise BrainError("GEOMETRY_UNAVAILABLE","Install the optional [geometry] extra. A missing kernel is not a passing check.")
    try:
        proc=subprocess.run([sys.executable,"-m","cadmcp_brain.geometry_worker"],input=json.dumps({"artifacts":artifacts,"pairs":pairs or []}),text=True,encoding="utf-8",capture_output=True,timeout=timeout,check=False,env=dict(os.environ,PYTHONUTF8="1"))
    except subprocess.TimeoutExpired as exc:
        raise BrainError("GEOMETRY_TIMEOUT","The geometry worker exceeded its wall-clock limit; no verdict was produced.") from exc
    try: response=json.loads(proc.stdout)
    except (ValueError,TypeError) as exc:
        raise BrainError("GEOMETRY_WORKER_FAILED","The worker failed to return a valid measurement report.",{"returncode":proc.returncode,"stderr":proc.stderr[-2000:]}) from exc
    if proc.returncode or not response.get("ok"):
        raise BrainError("GEOMETRY_WORKER_FAILED","B-rep measurement failed.",response.get("error",{}))
    return response["result"]
