"""Thin HTTP bridge from Cursor / Codex to AgentCAD.

Five commands only. Tool failures are AgentCAD JSON, unmodified.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8630


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def state_dir() -> Path:
    path = repo_root() / ".stella"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pid_file() -> Path:
    return state_dir() / "server.pid"


def base_url(port: int | None = None) -> str:
    env_port = os.environ.get("AGENTCAD_PORT")
    resolved = port or (int(env_port) if env_port else DEFAULT_PORT)
    return f"http://{DEFAULT_HOST}:{resolved}"


def emit(payload) -> int:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def http_json(method: str, url: str, body=None, timeout: float = 120.0):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {"error": {"type": "http_error", "message": raw}}
        except json.JSONDecodeError:
            parsed = {"error": {"type": "http_error", "message": raw or str(exc)}}
        return exc.code, parsed
    except urllib.error.URLError as exc:
        return None, {
            "error": {
                "type": "bridge_error",
                "message": f"cannot reach AgentCAD at {url}: {exc.reason}. "
                           "Start it with: uv run python -m stella_cad.bridge serve",
            }
        }


def cmd_health(args) -> int:
    port = args.port or DEFAULT_PORT
    status, payload = http_json("GET", f"{base_url(args.port)}/api/health", timeout=15.0)
    if status is None:
        from stella_cad.identify import stella_listen_pid
        occupant = stella_listen_pid(port)
        if occupant:
            payload = {
                "error": {
                    "type": "bridge_error",
                    "message": (
                        f"Stella is listening on port {port} (pid {occupant}) "
                        "but /api/health timed out. Kernel is busy, not an unknown "
                        "process. Wait and retry; do not start a second server."
                    ),
                }
            }
        return emit(payload) or 1
    emit(payload)
    if payload.get("kernel") == "ready":
        from stella_cad.identify import sync_pid_file
        sync_pid_file(port)
        return 0
    return 1


def cmd_list(args) -> int:
    status, payload = http_json("GET", f"{base_url(args.port)}/api/tools", timeout=30.0)
    if status is None:
        emit(payload)
        return 1
    tools = []
    for tool in payload.get("tools") or []:
        description = str(tool.get("description") or "").strip().splitlines()
        first = description[0] if description else ""
        tools.append({"name": tool.get("name"), "description": first})
    return emit({"tools": tools, "count": len(tools)})


def cmd_call(args) -> int:
    raw_args = args.args or "{}"
    try:
        parsed_args = json.loads(raw_args)
    except json.JSONDecodeError as exc:
        return emit({
            "error": {
                "type": "bridge_error",
                "message": f"--args is not JSON: {exc}",
            }
        }) or 1
    if not isinstance(parsed_args, dict):
        return emit({
            "error": {
                "type": "bridge_error",
                "message": "--args must be a JSON object",
            }
        }) or 1
    timeout = float(args.timeout)
    _status, payload = http_json(
        "POST",
        f"{base_url(args.port)}/api/tools/{args.name}",
        body=parsed_args,
        timeout=timeout,
    )
    emit(payload)
    if isinstance(payload, dict) and payload.get("error"):
        return 1
    if isinstance(payload, dict) and payload.get("ok") is False:
        return 1
    return 0


def _health_payload(port: int | None):
    status, payload = http_json("GET", f"{base_url(port)}/api/health", timeout=15.0)
    if status is None:
        return None
    return payload


def cmd_serve(args) -> int:
    from stella_cad.identify import sync_pid_file

    existing = _health_payload(args.port)
    if existing and existing.get("kernel") == "ready":
        sync_pid_file(args.port or DEFAULT_PORT)
        return emit(existing)

    script = repo_root() / "scripts" / "stella" / "serve.ps1"
    cmd = [
        "powershell",
        "-NoProfile",
        "-File",
        str(script),
        "-Port",
        str(args.port or DEFAULT_PORT),
        "-WaitSeconds",
        str(args.wait),
    ]
    if args.no_sandbox:
        cmd.append("-NoSandbox")
    completed = subprocess.run(cmd, cwd=str(repo_root()))
    if completed.returncode != 0:
        return emit({
            "error": {
                "type": "bridge_error",
                "message": f"serve.ps1 exited {completed.returncode}",
            }
        }) or completed.returncode

    # serve.ps1 already waited; re-read so the agent gets the health JSON.
    for _ in range(10):
        payload = _health_payload(args.port)
        if payload and payload.get("kernel") == "ready":
            sync_pid_file(args.port or DEFAULT_PORT)
            return emit(payload)
        time.sleep(0.5)
    return emit({
        "error": {
            "type": "bridge_error",
            "message": "server started but /api/health did not report kernel: ready",
        }
    }) or 1


def _pid_from_file() -> int | None:
    path = pid_file()
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if not text.isdigit():
        return None
    return int(text)


def _process_alive(pid: int) -> bool:
    # 0 signal does not exist on Windows; OpenProcess via tasklist is enough.
    completed = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out = (completed.stdout or "").strip()
    return str(pid) in out and "No tasks" not in out and "INFO:" not in out


def cmd_stop(args) -> int:
    from stella_cad.identify import (
        is_stella_command_line,
        process_command_line,
        stella_listen_pid,
        sync_pid_file,
    )

    port = args.port or DEFAULT_PORT
    recorded = _pid_from_file()
    listener = stella_listen_pid(port)
    target = None
    note = None

    if recorded and _process_alive(recorded):
        cmd = process_command_line(recorded)
        if is_stella_command_line(cmd) or recorded == listener:
            target = recorded
        else:
            return emit({
                "stopped": False,
                "reason": "pid file is not Stella; refusing to kill an unknown process",
                "pid": recorded,
            })
    elif listener is not None:
        # venv launcher PID goes stale; the TCP listener is the real Stella.
        target = listener
        note = "pid file was stale; stopping Stella listen pid"
        sync_pid_file(port)
    else:
        pid_file().unlink(missing_ok=True)
        return emit({
            "stopped": False,
            "reason": "pid not running",
            "pid": recorded,
        })

    subprocess.run(
        ["taskkill", "/PID", str(target), "/T", "/F"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False,
    )
    pid_file().unlink(missing_ok=True)
    out = {"stopped": True, "pid": target}
    if note:
        out["note"] = note
    return emit(out)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stella_cad.bridge",
        description="HTTP fallback when AgentCAD MCP is not connected.",
    )
    parser.add_argument("--port", type=int, default=None, help="AgentCAD port (default 8630)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_health = sub.add_parser("health", help="GET /api/health")
    p_health.set_defaults(func=cmd_health)

    p_list = sub.add_parser("list", help="GET /api/tools (name + one-line description)")
    p_list.set_defaults(func=cmd_list)

    p_call = sub.add_parser("call", help="POST /api/tools/{name}")
    p_call.add_argument("name")
    p_call.add_argument("--args", default="{}", help="JSON object of tool arguments")
    p_call.add_argument("--timeout", type=float, default=180.0)
    p_call.set_defaults(func=cmd_call)

    p_serve = sub.add_parser("serve", help="start AgentCAD and wait until kernel: ready")
    p_serve.add_argument("--no-sandbox", action="store_true",
                         help="opt out of AppContainer (quotas stay on)")
    p_serve.add_argument("--wait", type=int, default=300)
    p_serve.set_defaults(func=cmd_serve)

    p_stop = sub.add_parser("stop", help="stop the process recorded in .stella/server.pid")
    p_stop.set_defaults(func=cmd_stop)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
