"""Tell Stella's listener apart from an unknown occupant. Never kill by scan."""
from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PORT = 8630
BUSY_HEALTH_TIMEOUT = 15.0


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def pid_file(root: Path | None = None) -> Path:
    root = root or repo_root()
    state = root / ".stella"
    state.mkdir(parents=True, exist_ok=True)
    return state / "server.pid"


def is_stella_command_line(cmd: str | None, root: Path | str | None = None) -> bool:
    if not cmd:
        return False
    root_s = str(Path(root or repo_root()).resolve()).lower().replace("/", "\\")
    text = cmd.lower().replace("/", "\\")
    return root_s in text and "agentcad" in text and "serve" in text


def parse_listen_pids(netstat_text: str, port: int) -> list[int]:
    found: list[int] = []
    for raw in netstat_text.splitlines():
        line = raw.strip()
        if "LISTENING" not in line.upper():
            continue
        parts = [p for p in line.split() if p]
        if len(parts) < 4:
            continue
        local = parts[1]
        _, _, port_s = local.rpartition(":")
        if port_s != str(port):
            continue
        try:
            proc_id = int(parts[-1])
        except ValueError:
            continue
        if proc_id not in found:
            found.append(proc_id)
    return found


def listen_pids(port: int = DEFAULT_PORT) -> list[int]:
    completed = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return parse_listen_pids(completed.stdout or "", port)


def process_command_line(pid: int) -> str:
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return (completed.stdout or "").strip()


def stella_listen_pid(port: int = DEFAULT_PORT, root: Path | None = None) -> int | None:
    root = root or repo_root()
    for pid in listen_pids(port):
        if is_stella_command_line(process_command_line(pid), root):
            return pid
    return None


def health_on(port: int, timeout: float = BUSY_HEALTH_TIMEOUT):
    url = f"http://127.0.0.1:{port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")), None
    except TimeoutError:
        return None, "timeout"
    except urllib.error.URLError as exc:
        reason = str(exc.reason).lower()
        if "timed out" in reason or "timeout" in reason:
            return None, "timeout"
        return None, "unreachable"
    except (json.JSONDecodeError, OSError):
        return None, "unreachable"


def wait_health(port: int, wait_s: int, probe_timeout: float = BUSY_HEALTH_TIMEOUT):
    import time

    deadline = time.monotonic() + wait_s
    last_reason = "unreachable"
    while time.monotonic() < deadline:
        payload, reason = health_on(port, timeout=probe_timeout)
        if payload and payload.get("status") == "ok" and payload.get("version"):
            if payload.get("kernel") == "ready":
                return payload, None
            last_reason = "kernel_not_ready"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(1.0, remaining))
            continue
        last_reason = reason or "unhealthy"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(1.0, remaining))
    return None, last_reason


def sync_pid_file(port: int = DEFAULT_PORT, root: Path | None = None) -> int | None:
    """Record the TCP listener, not a venv launcher that already exited."""
    root = root or repo_root()
    pid = stella_listen_pid(port, root)
    if pid is None:
        return None
    pid_file(root).write_text(f"{pid}\n", encoding="ascii")
    return pid
