"""Locate and start a confined AgentCAD HTTP server. Logs go to stderr only."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PORT = 8630
FALLBACK_PORT = 8640


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def health_on(port: int, timeout: float = 2.0):
    url = f"http://127.0.0.1:{port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def sandbox_active(payload) -> bool:
    return bool(payload) and (payload.get("sandbox") or {}).get("status") == "active"


def pick_port() -> int:
    """Prefer 8630 when Stella (or nothing) is there. Skip an unconfined occupant."""
    env_port = os.environ.get("AGENTCAD_PORT")
    if env_port:
        return int(env_port)
    payload = health_on(DEFAULT_PORT)
    if payload and payload.get("kernel") == "ready" and not sandbox_active(payload):
        log(f"port {DEFAULT_PORT} is AgentCAD with sandbox off; using {FALLBACK_PORT}")
        return FALLBACK_PORT
    return DEFAULT_PORT


def apply_windows_env(root: Path | None = None) -> Path:
    root = root or repo_root()
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("UV_PYTHON_INSTALL_DIR", str(root / ".python"))
    os.environ.setdefault("AGENTCAD_PROJECTS_DIR", str(root / "projects"))
    os.environ.setdefault("AGENTCAD_AGENT_ID", "stella-mcp")
    return root


def ensure_confined_server(port: int | None = None, wait: int = 300) -> tuple[int, dict]:
    """Return (port, health) for a kernel-ready server. Isolation stays on."""
    root = apply_windows_env()
    port = port or pick_port()
    payload = health_on(port)
    if payload and payload.get("kernel") == "ready":
        if sandbox_active(payload) or os.environ.get("AGENTCAD_NO_SANDBOX"):
            _export_url(port)
            return port, payload
        raise SystemExit(
            f"port {port} is AgentCAD with sandbox.status="
            f"{(payload.get('sandbox') or {}).get('status')!r}; "
            f"refusing to attach. Start Stella with --port {FALLBACK_PORT}."
        )

    script = root / "scripts" / "stella" / "serve.ps1"
    state = root / ".stella"
    state.mkdir(parents=True, exist_ok=True)
    out_log = state / "mcp-serve.out.log"
    err_log = state / "mcp-serve.err.log"
    cmd = [
        "powershell",
        "-NoProfile",
        "-File",
        str(script),
        "-Port",
        str(port),
        "-WaitSeconds",
        str(wait),
    ]
    log(f"starting confined AgentCAD on {port}")
    with out_log.open("w", encoding="utf-8") as out, err_log.open("w", encoding="utf-8") as err:
        completed = subprocess.run(cmd, cwd=str(root), stdout=out, stderr=err)
    if completed.returncode != 0:
        tail = ""
        if err_log.is_file():
            tail = err_log.read_text(encoding="utf-8", errors="replace")[-2000:]
        raise SystemExit(
            f"serve.ps1 exited {completed.returncode} starting port {port}. {tail}"
        )

    payload = health_on(port)
    if not (payload and payload.get("kernel") == "ready"):
        raise SystemExit(f"AgentCAD started but /api/health is not ready on {port}")
    if not sandbox_active(payload) and not os.environ.get("AGENTCAD_NO_SANDBOX"):
        log(f"WARNING: sandbox.status="
            f"{(payload.get('sandbox') or {}).get('status')!r} (wanted active)")
    _export_url(port)
    return port, payload


def _export_url(port: int) -> None:
    os.environ["AGENTCAD_PORT"] = str(port)
    os.environ["AGENTCAD_URL"] = f"http://127.0.0.1:{port}"
