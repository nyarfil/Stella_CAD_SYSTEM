"""Project-scoped CAD backend selection and safe FreeCAD preparation.

The selector owns ``<project>/.stella/cad-backend.json`` and only the
``enabled`` keys of known CAD writer blocks in ``<project>/.codex/config.toml``.
Selecting a backend never starts or stops any CAD application or MCP.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = 1
STATE_RELATIVE_PATH = Path(".stella") / "cad-backend.json"
SUPPORTED_BACKENDS = ("freecad", "classcad", "fusion", "cadquery", "build123d")
BACKEND_MCP = {
    "freecad": "stella_freecad_mouse_b",
    "classcad": "classcad",
    "fusion": "stella-fusion-community",
    "cadquery": "cadmcp-design-brain",
    "build123d": "cadgen-cli",
}
FREECAD_MCP_REPOSITORY = "neka-nat/freecad-mcp"
FREECAD_MCP_COMMIT = "d6bbe4b38be3a622b5981d9d2afa7037ee080534"
FREECAD_RPC_PORT = 9875
WRITER_SERVERS = (
    "stella_freecad_mouse_b",
    "classcad",
    "stella-fusion-community",
    "fusion",
)
ENABLED_SERVERS_BY_BACKEND = {
    "freecad": frozenset({"stella_freecad_mouse_b"}),
    "classcad": frozenset({"classcad"}),
    "fusion": frozenset({"stella-fusion-community", "fusion"}),
    "cadquery": frozenset(),
    "build123d": frozenset(),
}


class SelectionError(RuntimeError):
    """A selection or preparation request violates the project contract."""


def _canonical_directory(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise SelectionError(f"{label} is not a directory: {path}")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SelectionError(f"Cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SelectionError(f"Expected a JSON object in {path}")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(
        "utf-8"
    )
    _write_bytes_atomic(path, encoded)


def _write_bytes_atomic(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _state_path(project: Path) -> Path:
    state = project / STATE_RELATIVE_PATH
    parent = state.parent
    if parent.exists() and not parent.resolve().is_relative_to(project):
        raise SelectionError(
            f"Project state directory escapes the project root: {parent}"
        )
    return state


def _mcp_section_pattern(server: str) -> re.Pattern[str]:
    escaped = re.escape(server)
    return re.compile(
        rf'^\s*\[mcp_servers\.(?:{escaped}|"{escaped}"|\'{escaped}\')\]\s*(?:#.*)?$'
    )


def _set_server_enabled(text: str, server: str, enabled: bool) -> str:
    lines = text.splitlines(keepends=True)
    header_pattern = _mcp_section_pattern(server)
    header_index = next(
        (index for index, line in enumerate(lines) if header_pattern.match(line.rstrip("\r\n"))),
        None,
    )
    value = "true" if enabled else "false"
    if header_index is None:
        if text and not text.endswith(("\n", "\r")):
            text += "\n"
        if text and not text.endswith("\n\n"):
            text += "\n"
        return text + f"[mcp_servers.{server}]\nenabled = {value}\n"

    end = len(lines)
    for index in range(header_index + 1, len(lines)):
        if lines[index].lstrip().startswith("["):
            end = index
            break
    enabled_pattern = re.compile(r"^(\s*enabled\s*=\s*)(?:true|false)(\s*(?:#.*)?)(\r?\n)?$")
    for index in range(header_index + 1, end):
        match = enabled_pattern.match(lines[index])
        if match:
            newline = match.group(3) or ""
            lines[index] = f"{match.group(1)}{value}{match.group(2)}{newline}"
            return "".join(lines)
    newline = "\r\n" if "\r\n" in text else "\n"
    lines.insert(header_index + 1, f"enabled = {value}{newline}")
    return "".join(lines)


def activate_project_backend(
    project: Path, backend: str
) -> tuple[dict[str, Any], bytes, bool]:
    """Apply only known MCP enable flags in this project's Codex config."""
    config_path = project / ".codex" / "config.toml"
    if config_path.parent.exists() and not config_path.parent.resolve().is_relative_to(project):
        raise SelectionError(
            f"Project Codex config directory escapes the project root: {config_path.parent}"
        )
    backup_path = config_path.with_name(config_path.name + ".before-cad-selection")
    existed = config_path.is_file()
    original_bytes = config_path.read_bytes() if existed else b""
    try:
        original_text = original_bytes.decode("utf-8-sig")
        tomllib.loads(original_text)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise SelectionError(f"Invalid project Codex config {config_path}: {exc}") from exc

    enabled_servers = ENABLED_SERVERS_BY_BACKEND[backend]
    updated_text = original_text
    for server in WRITER_SERVERS:
        updated_text = _set_server_enabled(
            updated_text, server, server in enabled_servers
        )
    try:
        parsed = tomllib.loads(updated_text)
    except tomllib.TOMLDecodeError as exc:
        raise SelectionError(f"Generated invalid project Codex config: {exc}") from exc
    server_config = parsed.get("mcp_servers", {})
    for server in WRITER_SERVERS:
        expected = server in enabled_servers
        actual = server_config.get(server, {}).get("enabled")
        if actual is not expected:
            raise SelectionError(
                f"Could not set mcp_servers.{server}.enabled={str(expected).lower()}"
            )

    if existed and not backup_path.exists():
        _write_bytes_atomic(backup_path, original_bytes)
    _write_bytes_atomic(config_path, updated_text.encode("utf-8"))
    return (
        {
            "config_path": str(config_path),
            "backup_path": str(backup_path) if existed else None,
            "enabled_writer_servers": sorted(enabled_servers),
            "reload_required": True,
        },
        original_bytes,
        existed,
    )


@contextlib.contextmanager
def _exclusive_selection_lock(project: Path):
    lock_path = _state_path(project).with_name("cad-backend.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            if lock_path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise SelectionError(
                    "Another CAD backend selection is already updating this project"
                ) from exc
        else:
            import fcntl

            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise SelectionError(
                    "Another CAD backend selection is already updating this project"
                ) from exc
        acquired = True
        yield
    finally:
        if acquired:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def read_selection(project: Path) -> dict[str, Any] | None:
    path = _state_path(project)
    if not path.exists():
        return None
    state = _read_json(path)
    if state.get("schema_version") != SCHEMA_VERSION:
        raise SelectionError(f"Unsupported backend state schema in {path}")
    if state.get("selection_mode") not in ("explicit", "capability_auto"):
        raise SelectionError(f"Unknown backend selection mode: {path}")
    if state.get("backend") not in SUPPORTED_BACKENDS:
        raise SelectionError(f"Unsupported backend in {path}: {state.get('backend')!r}")
    saved_root = state.get("project_root")
    if not isinstance(saved_root, str) or Path(saved_root).resolve() != project:
        raise SelectionError(
            f"Backend state belongs to another project root: {saved_root!r}"
        )
    backend_config = state.get("backend_config")
    if not isinstance(backend_config, dict):
        raise SelectionError(f"Invalid backend_config in {path}")
    if state["backend"] == "freecad" and not isinstance(backend_config.get("kit"), str):
        raise SelectionError(f"FreeCAD selection has no kit path in {path}")
    return state


def select_backend(
    project: Path, backend: str, kit: Path | None = None, *,
    routing_decision: dict[str, Any] | None = None,
    expected_selection: dict[str, Any] | None = None,
    expected_routing_policy: dict[str, Any] | None = None,
    routing_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if backend not in SUPPORTED_BACKENDS:
        raise SelectionError(f"Unsupported CAD backend: {backend}")
    if backend == "freecad":
        if kit is None:
            raise SelectionError("--kit is required when selecting freecad")
        inspect_freecad_kit(kit, require_valid=True)
        backend_config: dict[str, Any] = {
            "kit": str(kit),
            "mcp_server": BACKEND_MCP[backend],
        }
    else:
        if kit is not None:
            raise SelectionError("--kit is accepted only with --backend freecad")
        backend_config = {"mcp_server": BACKEND_MCP[backend]}
    state = {
        "schema_version": SCHEMA_VERSION,
        "project_root": str(project),
        "backend": backend,
        "selection_mode": "capability_auto" if routing_decision is not None else "explicit",
        "selected_at_utc": datetime.now(timezone.utc).isoformat(),
        "backend_config": backend_config,
    }
    if routing_decision is not None:
        if (routing_decision.get('status') != 'ready'
                or routing_decision.get('mode') != 'auto'
                or routing_decision.get('selected_backend') != backend):
            raise SelectionError('Routing decision does not authorize this backend')
        state['routing_decision'] = routing_decision
    with _exclusive_selection_lock(project):
        if routing_decision is not None and read_selection(project) != expected_selection:
            raise SelectionError('Project CAD selection changed during routing; replan')
        if routing_decision is not None:
            policy_path = _state_path(project).with_name('cad-routing.json')
            if (expected_routing_policy is None or not policy_path.is_file()
                    or _read_json(policy_path) != expected_routing_policy):
                raise SelectionError('Project routing policy changed during routing; replan')
            policy = _read_json(policy_path)
            if (policy.get('schema_version') != 1 or policy.get('mode') != 'auto'
                    or policy.get('project_root') != str(project)
                    or backend not in policy.get('allowed_backends', [])):
                raise SelectionError('Backend is outside the current project routing policy')
            if expected_selection and expected_selection.get('selection_mode') == 'explicit':
                raise SelectionError('Automatic routing cannot replace an explicit selection')
            if routing_request is None:
                raise SelectionError('Activation requires the original routing request')
            from cadmcp_brain.studio.backend_routing import route_backend
            request = dict(routing_request, mode='auto', selected_backend=None,
                           allowed_backends=policy['allowed_backends'])
            if backend == 'freecad':
                live = inspect_freecad_kit(kit, require_valid=True)
                if not live['ready']:
                    raise SelectionError('FreeCAD adapter stopped before activation; replan')
            refreshed = route_backend(request)
            if refreshed != routing_decision or refreshed['status'] != 'ready':
                raise SelectionError('Routing decision changed or was modified; replan')
        activation, previous_config, config_existed = activate_project_backend(
            project, backend
        )
        try:
            _write_json_atomic(_state_path(project), state)
        except Exception:
            config_path = Path(activation["config_path"])
            if config_existed:
                _write_bytes_atomic(config_path, previous_config)
            else:
                config_path.unlink(missing_ok=True)
            raise
    return {
        "selection": state,
        "activation": activation,
        "reload_required": True,
    }


def _port_is_open(port: int = FREECAD_RPC_PORT) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information, False, pid
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def _process_executable(pid: int) -> Path | None:
    """Return the executable for a live PID without changing process state."""
    if pid <= 0:
        return None
    if os.name == "nt":
        process_query_limited_information = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return None
        try:
            size = ctypes.c_ulong(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)
            ):
                return None
            return Path(buffer.value).resolve()
        finally:
            kernel32.CloseHandle(handle)
    proc_exe = Path("/proc") / str(pid) / "exe"
    try:
        return proc_exe.resolve(strict=True)
    except OSError:
        return None


def inspect_freecad_kit(kit: Path, *, require_valid: bool = False) -> dict[str, Any]:
    manifest_path = kit / "manifest.json"
    config_path = kit / "runtime" / "config.json"
    ready_path = kit / "runtime" / "ready.json"
    live_test_path = kit / "runtime" / "last-live-test.json"
    sources_lock_path = kit / "runtime" / "sources.lock.json"
    gui_pid_path = kit / "runtime" / "gui.pid"
    launcher_path = kit / "tools" / "launch_freecad.py"
    mcp_launcher_path = kit / "tools" / "launch_mcp.py"
    errors: list[str] = []

    manifest: dict[str, Any] = {}
    config: dict[str, Any] = {}
    ready: dict[str, Any] = {}
    live_test: dict[str, Any] = {}
    sources_lock: dict[str, Any] = {}
    for path, name in (
        (manifest_path, "manifest"),
        (config_path, "runtime config"),
    ):
        if not path.is_file():
            errors.append(f"missing {name}: {path}")
    if not errors:
        try:
            manifest = _read_json(manifest_path)
            config = _read_json(config_path)
        except SelectionError as exc:
            errors.append(str(exc))

    configured_root = config.get("root")
    if configured_root and Path(str(configured_root)).resolve() != kit:
        errors.append("runtime config root does not match the selected kit")
    mcp = manifest.get("mcp", {})
    if not isinstance(mcp, dict) or mcp.get("repository") != FREECAD_MCP_REPOSITORY:
        errors.append(f"manifest does not pin {FREECAD_MCP_REPOSITORY}")
    commit = mcp.get("commit") if isinstance(mcp, dict) else None
    if not isinstance(commit, str) or len(commit) != 40:
        errors.append("manifest has no 40-character FreeCAD MCP commit")
    for path in (launcher_path, mcp_launcher_path):
        if not path.is_file():
            errors.append(f"missing kit launcher: {path}")

    freecad_exe = Path(str(config.get("freecad_exe", "")))
    mcp_exe = Path(str(config.get("mcp_exe", "")))
    if config and not freecad_exe.is_file():
        errors.append(f"configured FreeCAD executable is missing: {freecad_exe}")
    if config and not mcp_exe.is_file():
        errors.append(f"configured FreeCAD MCP executable is missing: {mcp_exe}")

    if ready_path.is_file():
        try:
            ready = _read_json(ready_path)
        except SelectionError as exc:
            errors.append(str(exc))
    if live_test_path.is_file():
        try:
            live_test = _read_json(live_test_path)
        except SelectionError:
            live_test = {"status": "INVALID_JSON"}

    if sources_lock_path.is_file():
        try:
            sources_lock = _read_json(sources_lock_path)
        except SelectionError as exc:
            errors.append(str(exc))
    else:
        errors.append(f"missing sources lock: {sources_lock_path}")

    if commit != FREECAD_MCP_COMMIT:
        errors.append(f"manifest FreeCAD MCP commit is not approved: {commit!r}")
    locked_mcp = sources_lock.get("mcp", {})
    if not isinstance(locked_mcp, dict):
        locked_mcp = {}
    if locked_mcp.get("repository") != FREECAD_MCP_REPOSITORY:
        errors.append("sources lock FreeCAD MCP repository does not match")
    if locked_mcp.get("commit") != FREECAD_MCP_COMMIT:
        errors.append("sources lock FreeCAD MCP commit does not match")
    archive_sha256 = locked_mcp.get("archive_sha256")
    if not isinstance(archive_sha256, str) or not re.fullmatch(
        r"[0-9a-fA-F]{64}", archive_sha256
    ):
        errors.append("sources lock has no valid MCP archive SHA256")
    else:
        archive_path = (
            kit
            / "runtime"
            / "downloads"
            / f"mcp-{FREECAD_MCP_COMMIT}.zip"
        )
        if not archive_path.is_file():
            errors.append(f"missing pinned MCP archive: {archive_path}")
        elif _sha256_file(archive_path).casefold() != archive_sha256.casefold():
            errors.append("pinned MCP archive SHA256 does not match sources lock")

    ready_pid = ready.get("pid")
    pid_running = _pid_is_running(ready_pid) if isinstance(ready_pid, int) else False
    process_executable = (
        _process_executable(ready_pid) if isinstance(ready_pid, int) and pid_running else None
    )
    process_executable_matches = bool(
        process_executable
        and freecad_exe.is_file()
        and os.path.normcase(str(process_executable))
        == os.path.normcase(str(freecad_exe.resolve()))
    )
    gui_pid: int | None = None
    if gui_pid_path.is_file():
        try:
            gui_pid = int(gui_pid_path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            gui_pid = None
    gui_pid_matches = isinstance(ready_pid, int) and gui_pid == ready_pid
    ready_root_matches = (
        isinstance(ready.get("root"), str)
        and Path(ready["root"]).resolve() == kit
    )
    profile_matches = (
        isinstance(ready.get("profile"), str)
        and isinstance(config.get("profile"), str)
        and Path(ready["profile"]).resolve() == Path(config["profile"]).resolve()
        and Path(ready["profile"]).resolve() == (kit / "runtime" / "profile").resolve()
    )
    rpc_open = _port_is_open()
    installed = not errors
    running = bool(
        installed
        and ready.get("status") == "READY"
        and ready_root_matches
        and profile_matches
        and pid_running
        and process_executable_matches
        and gui_pid_matches
        and rpc_open
    )
    result = {
        "kit": str(kit),
        "installed": installed,
        "ready": running,
        "identity": {
            "kit_version": manifest.get("kit_version"),
            "freecad_target": manifest.get("freecad_target"),
            "mcp_repository": mcp.get("repository") if isinstance(mcp, dict) else None,
            "mcp_commit": commit,
            "mcp_archive_sha256": archive_sha256,
        },
        "runtime": {
            "ready_file_status": ready.get("status"),
            "ready_root_matches": ready_root_matches,
            "profile_matches": profile_matches,
            "pid": ready_pid,
            "pid_running": pid_running,
            "process_executable": str(process_executable) if process_executable else None,
            "process_executable_matches": process_executable_matches,
            "gui_pid_file": gui_pid,
            "gui_pid_matches": gui_pid_matches,
            "rpc_host": "127.0.0.1",
            "rpc_port": FREECAD_RPC_PORT,
            "rpc_open": rpc_open,
            "live_test_status": live_test.get("status", "NOT_RUN"),
        },
        "errors": errors,
    }
    if require_valid and not installed:
        raise SelectionError("Invalid FreeCAD kit: " + "; ".join(errors))
    return result


def status(project: Path, candidate_kit: Path | None = None) -> dict[str, Any]:
    state = read_selection(project)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project_root": str(project),
        "state_path": str(_state_path(project)),
        "selection": state,
    }
    if state is None:
        result["selection_status"] = "NOT_SELECTED"
        result["next_action"] = "Run the select command with an explicit backend."
    else:
        result["selection_status"] = "SELECTED"
        backend = state["backend"]
        if backend == "freecad":
            stored_kit = _canonical_directory(
                state["backend_config"]["kit"], "stored FreeCAD kit"
            )
            result["backend_status"] = inspect_freecad_kit(stored_kit)
            result["next_action"] = (
                "FreeCAD is ready."
                if result["backend_status"]["ready"]
                else "Run the prepare command for this project."
            )
        else:
            result["backend_status"] = {
                "backend": backend,
                "mcp_server": state["backend_config"]["mcp_server"],
                "managed_by": "selected backend integration",
                "ready": None,
            }
            result["next_action"] = (
                f"Use the {backend} project workflow; this FreeCAD helper will not launch it."
            )
    if candidate_kit is not None:
        result["candidate_freecad"] = inspect_freecad_kit(candidate_kit)
    return result


def prepare(project: Path) -> dict[str, Any]:
    state = read_selection(project)
    if state is None:
        raise SelectionError("No CAD backend is selected for this project")
    if state["backend"] != "freecad":
        return {
            "schema_version": SCHEMA_VERSION,
            "project_root": str(project),
            "backend": state["backend"],
            "action": "NO_ACTION",
            "ready": None,
            "instruction": (
                f"Dispatch to the {state['backend']} project workflow. "
                "The FreeCAD launcher was not invoked."
            ),
        }

    kit = _canonical_directory(state["backend_config"]["kit"], "stored FreeCAD kit")
    before = inspect_freecad_kit(kit, require_valid=True)
    if before["ready"]:
        return {
            "schema_version": SCHEMA_VERSION,
            "project_root": str(project),
            "backend": "freecad",
            "action": "REUSED_RUNNING_GUI",
            "ready": True,
            "backend_status": before,
        }
    if before["runtime"]["pid_running"]:
        raise SelectionError(
            "The kit's recorded FreeCAD GUI PID is still running, but its "
            "PID/executable/profile/RPC ready checks did not all match. No second "
            "GUI was launched and no process was stopped; inspect the existing GUI "
            "and kit runtime status before retrying."
        )
    if before["runtime"]["rpc_open"]:
        raise SelectionError(
            "FreeCAD RPC port 9875 is occupied, but PID/profile/kit identity did not "
            "match this project kit. No process was stopped and no launcher was run."
        )

    config = _read_json(kit / "runtime" / "config.json")
    kit_python = Path(str(config.get("python_exe", "")))
    python = kit_python if kit_python.is_file() else Path(sys.executable)
    launcher = kit / "tools" / "launch_freecad.py"
    diagnostic = ""
    try:
        # The launcher starts a long-lived GUI.  A regular capture_output pipe
        # would also be inherited by that GUI and could keep communicate()
        # waiting after the short-lived launcher exits.
        with tempfile.TemporaryFile(mode="w+b") as diagnostic_stream:
            launched = subprocess.run(
                [str(python), str(launcher)],
                cwd=kit,
                stdout=diagnostic_stream,
                stderr=subprocess.STDOUT,
                timeout=150,
                check=False,
            )
            diagnostic_stream.seek(0)
            diagnostic = diagnostic_stream.read().decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        raise SelectionError(
            "The existing FreeCAD launcher did not finish its readiness check within "
            "150 seconds. It was not asked to close the GUI; inspect the kit runtime "
            "status before retrying."
        ) from exc
    after = inspect_freecad_kit(kit)
    if launched.returncode != 0 or not after["ready"]:
        raise SelectionError(
            f"The existing FreeCAD launcher did not reach a matching ready state "
            f"(exit {launched.returncode}): {diagnostic.strip()[-1000:]}"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "project_root": str(project),
        "backend": "freecad",
        "action": "LAUNCHED_EXISTING_KIT",
        "ready": True,
        "backend_status": after,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Select and inspect a project-local StellaCAD backend."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    choose = commands.add_parser("select", help="persist an explicit project selection")
    choose.add_argument("--project", required=True)
    choose.add_argument("--backend", choices=SUPPORTED_BACKENDS, required=True)
    choose.add_argument("--kit")
    show = commands.add_parser("status", help="read selection and backend status")
    show.add_argument("--project", required=True)
    show.add_argument("--kit", help="read-only inspection of a candidate FreeCAD kit")
    start = commands.add_parser("prepare", help="prepare only the selected backend")
    start.add_argument("--project", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        project = _canonical_directory(args.project, "project")
        if args.command == "select":
            kit = _canonical_directory(args.kit, "FreeCAD kit") if args.kit else None
            selected = select_backend(project, args.backend, kit)
            result = {
                "command": "select",
                "state_path": str(_state_path(project)),
                **selected,
                "launched": False,
            }
        elif args.command == "status":
            kit = _canonical_directory(args.kit, "FreeCAD kit") if args.kit else None
            result = {"command": "status", **status(project, kit)}
        else:
            result = {"command": "prepare", **prepare(project)}
    except SelectionError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
