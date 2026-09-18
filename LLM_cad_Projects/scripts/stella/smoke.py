"""Box -> rebuild -> STEP. Isolation must stay active."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from stella_cad.bridge import cmd_health, cmd_serve

REPO = Path(__file__).resolve().parents[2]
BOX_SCRIPT = """from build123d import *

PARAMS = {
    "size": {"type": "number", "default": 10.0, "min": 1.0, "max": 100.0, "unit": "mm",
             "description": "Cube edge"},
}

def build(p):
    return Box(p.size, p.size, p.size)
"""


class Args:
    def __init__(self, **kwargs) -> None:
        self.port = kwargs.get("port")
        self.no_sandbox = False
        self.wait = 300
        self.name = kwargs.get("name")
        self.args = kwargs.get("args", "{}")
        self.timeout = 180.0


def health_on(port: int):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def pick_port() -> int:
    payload = health_on(8630)
    if payload and payload.get("kernel") == "ready" and (
            (payload.get("sandbox") or {}).get("status") != "active"):
        print("port 8630 is an unconfined server; using 8640", flush=True)
        return 8640
    return 8630


def call(port: int, name: str, payload: dict, *, allow_error: bool = False) -> dict:
    from stella_cad.bridge import base_url, http_json
    _status, body = http_json(
        "POST", f"{base_url(port)}/api/tools/{name}", body=payload, timeout=180.0)
    print(json.dumps(body, ensure_ascii=False, indent=2), flush=True)
    if isinstance(body, dict) and body.get("error") and not allow_error:
        raise SystemExit(f"{name} failed")
    return body


def main() -> int:
    sys.path.insert(0, str(REPO))
    port = pick_port()
    print("=== serve ===", flush=True)
    rc = cmd_serve(Args(port=port))
    if rc != 0:
        return rc
    print("=== health ===", flush=True)
    rc = cmd_health(Args(port=port))
    if rc != 0:
        return rc
    payload = health_on(port)
    sandbox = (payload or {}).get("sandbox") or {}
    if sandbox.get("status") != "active":
        raise SystemExit(f"sandbox.status is {sandbox.get('status')!r}, expected active")
    print(f"sandbox.active mechanism={sandbox.get('mechanism')}", flush=True)

    print("=== create_project stella_smoke ===", flush=True)
    created = call(port, "create_project", {"name": "stella_smoke"}, allow_error=True)
    if created.get("error"):
        print("create_project returned an error; continuing if the project exists", flush=True)

    print("=== create_part box ===", flush=True)
    part = call(port, "create_part", {
        "project": "stella_smoke",
        "part_id": "box",
        "label": "smoke box",
        "script": BOX_SCRIPT,
    }, allow_error=True)
    if part.get("error"):
        print("create_part failed, trying update_part_script", flush=True)
        part = call(port, "update_part_script", {
            "project": "stella_smoke",
            "part_id": "box",
            "script": BOX_SCRIPT,
        })

    print("=== export_part step ===", flush=True)
    exported = call(port, "export_part", {
        "project": "stella_smoke",
        "part_id": "box",
        "format": "step",
    })
    size = exported.get("size_bytes") or 0
    if size <= 0:
        raise SystemExit(f"STEP export had no size_bytes: {exported}")

    step = REPO / "projects" / "stella_smoke" / "exports" / "box.step"
    if not step.is_file():
        print(f"warning: {step} not on disk (export may have used another path)", flush=True)
    print(f"SMOKE OK  sandbox={sandbox.get('status')}  bytes={size}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
