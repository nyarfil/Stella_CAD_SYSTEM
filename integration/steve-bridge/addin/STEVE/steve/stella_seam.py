"""STELLA ADDITION (not part of upstream STEVE; see integration/steve-bridge/NOTICE.md).

Minimal loopback control seam. A 127.0.0.1 HTTP server with a bearer token that
validates a call with STEVE's own validate_call and hands it to the existing
FusionTools.submit() path (custom-event marshalling, command-based Undo grouping,
document/command gating). It adds no model, network or UI behaviour.

Opt-in: it starts only when <STEVE data home>/stella-seam/config.json contains
{"enabled": true}. The token is generated on first start and stored next to it;
it is never logged. This is NOT a sandbox and does not apply the Stella MCP
guards (allow-list, code policy); those live in the Stella-side server.
"""
import base64
import hmac
import json
import os
import secrets
import socket
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from uuid import uuid4

from .loopback_http import ThreadingLoopbackHTTPServer
from .tool_protocol import ToolError, tool_failure, validate_call
from .transport import data_home
from .version import VERSION

SEAM_VERSION = "1"
MAX_BODY = 256 * 1024
MAX_RESPONSE = 256 * 1024
DEFAULT_TIMEOUT = 60.0
MAX_TIMEOUT = 120.0
ROUTES = {
    "inspect": "fusion_inspect_document",
    "query": "fusion_query_python",
    "execute": "fusion_execute_python",
    "viewport": "fusion_capture_viewport",
    "api_help": "fusion_api_help",
}
_state = {"server": None, "thread": None, "home": None}


class ExclusiveLoopbackServer(ThreadingLoopbackHTTPServer):
    """No address sharing: on Windows SO_REUSEADDR would let another process bind the same port."""
    allow_reuse_address = False

    def server_bind(self):
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def log_error(home, message):
    """Seam failures never abort STEVE; they go to stderr and a local file only."""
    print("[stella-seam] " + message, file=sys.stderr)
    try:
        Path(home).mkdir(parents=True, exist_ok=True)
        with open(Path(home) / "seam-error.log", "a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except OSError:
        pass


def restrict_to_owner(path):
    """Owner-only access. POSIX: chmod 600. Windows: protected DACL with one ACE for the current user
    (SetNamedSecurityInfoW). Returns True on success; False means the default profile ACL still applies."""
    if sys.platform != "win32":
        os.chmod(path, 0o600)
        return True
    import ctypes
    from ctypes import wintypes
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    k32.LocalFree.restype = ctypes.c_void_p
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD)]
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    adv.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
                                              ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    adv.SetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p,
                                          ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    adv.SetNamedSecurityInfoW.restype = wintypes.DWORD
    token, sid_text, descriptor = wintypes.HANDLE(), ctypes.c_void_p(), ctypes.c_void_p()
    if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
        return False
    try:
        size = wintypes.DWORD()
        adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser, size probe
        if size.value == 0:
            return False
        buffer = ctypes.create_string_buffer(size.value)
        if not adv.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            return False
        user_sid = ctypes.c_void_p.from_buffer(buffer).value  # TOKEN_USER.User.Sid
        if not adv.ConvertSidToStringSidW(user_sid, ctypes.byref(sid_text)):
            return False
        sid = ctypes.wstring_at(sid_text.value)
        k32.LocalFree(sid_text)
        sddl = "D:PAI(A;;FA;;;%s)" % sid  # protected, no inheritance, full access for this user only
        if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            return False
        present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        if not adv.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
            return False
        # SE_FILE_OBJECT=1; DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION
        return adv.SetNamedSecurityInfoW(str(path), 1, 0x00000004 | 0x80000000, None, None, dacl, None) == 0
    finally:
        if descriptor.value:
            k32.LocalFree(descriptor)
        k32.CloseHandle(token)


def seam_home(home=None):
    return Path(home) if home else data_home() / "stella-seam"


ADDIN_CONFIG = Path(__file__).resolve().parents[1] / "stella-seam.json"


def load_config(home):
    """<STEVE data>/stella-seam/config.json wins; the add-in folder's stella-seam.json is the fallback.
    The fallback travels with the install, so the seam does not depend on a data-folder file the host process may not see."""
    for path in (Path(home) / "config.json", ADDIN_CONFIG):
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(config, dict):
            return config
    return {}


def panel_policy(config):
    """Guard for STEVE's own chat panel (the Stella MCP guards never see those calls).
    {"panel": {"allowedDocuments": ["name", ...], "readOnly": false}}; absent or empty means upstream behaviour."""
    panel = config.get("panel")
    if not isinstance(panel, dict):
        return None
    names = panel.get("allowedDocuments")
    names = [name for name in names if isinstance(name, str) and name] if isinstance(names, list) else []
    read_only = panel.get("readOnly") is True
    return {"allowedDocuments": names, "readOnly": read_only} if names or read_only else None


PANEL_GUARDED_TOOLS = ("fusion_query_python", "fusion_execute_python", "fusion_dfm_check")
MODIFYING_TOOLS = ("fusion_execute_python",)


def install_panel_guard(fusion_tools, policy):
    """Wrap run_script (Fusion main thread) so panel-originated code runs only on an allowed document."""
    if policy is None or getattr(fusion_tools, "_stella_panel_guard", False):
        return
    inner = fusion_tools.run_script

    def run_script(job):
        if not getattr(job.get("complete"), "stella", False) and job.get("tool") in PANEL_GUARDED_TOOLS:
            if policy["readOnly"] and job["tool"] in MODIFYING_TOOLS:
                raise ToolError("panel_read_only", "Stella policy: the STEVE panel is read-only; changes are not allowed here.")
            if policy["allowedDocuments"]:
                document = fusion_tools.document if fusion_tools.task else fusion_tools.app.activeDocument
                name = document.name if document is not None else None
                if name not in policy["allowedDocuments"]:
                    raise ToolError("panel_document_not_allowed",
                                    "Stella policy: the STEVE panel may only work on " + ", ".join(policy["allowedDocuments"])
                                    + f" (current document: {name!r}). Open an allowed document or ask the owner to extend the allow-list.")
        return inner(job)

    fusion_tools.run_script = run_script
    fusion_tools._stella_panel_guard = True


def ensure_token(home):
    path = home / "token"
    if path.is_file():
        token = path.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token
    token = secrets.token_urlsafe(32)
    home.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.close(fd)  # empty file first: restrict the ACL before the secret is written
    try:
        restricted = restrict_to_owner(path)
    except Exception:
        restricted = False
    if not restricted:
        log_error(home, "token file ACL could not be restricted; relying on the user-profile default ACL")
    path.write_text(token, encoding="utf-8")
    return token


def _save_png(result, folder):
    """Replace the base64 imageUrl by a local file path (path + size only)."""
    url = result.pop("imageUrl", None)
    if not isinstance(url, str) or not url.startswith("data:image/png;base64,"):
        return result
    data = base64.b64decode(url.split(",", 1)[1], validate=True)
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > 8 * 1024 * 1024:
        return tool_failure(ToolError("viewport_capture_failed", "Invalid or oversized PNG."))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (uuid4().hex + ".png")
    path.write_bytes(data)
    result["path"] = str(path)
    result["bytes"] = len(data)
    return result


def make_handler(fusion_tools, token, port_getter, captures):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *args):  # never log request lines
            pass

        def _send(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if len(body) > MAX_RESPONSE:
                body = json.dumps({"ok": False, "errorCode": "response_too_large",
                                   "error": "Result exceeded the bridge response cap.",
                                   "executionStarted": True}).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self):
            port = port_getter()
            if self.headers.get("Origin") is not None:
                return False
            if self.headers.get("Host") not in ("127.0.0.1:%d" % port, "localhost:%d" % port):
                return False
            supplied = self.headers.get("Authorization", "")
            return hmac.compare_digest(supplied.encode("utf-8"), ("Bearer " + token).encode("utf-8"))

        def _dispatch(self, name, arguments):
            if name == "health":
                return 200, {"ok": True, "seam": SEAM_VERSION, "steve": VERSION,
                             "closed": bool(fusion_tools.closed), "queued": fusion_tools.queue.qsize()}
            tool = ROUTES.get(name)
            if tool is None:
                return 404, {"ok": False, "errorCode": "unknown_route", "error": "Unknown route."}
            timeout = arguments.pop("_timeout_seconds", DEFAULT_TIMEOUT)
            if type(timeout) not in (int, float) or not 1 <= timeout <= MAX_TIMEOUT:
                timeout = DEFAULT_TIMEOUT
            if tool == "fusion_execute_python":
                if arguments.get("execution_mode", "command") != "command":
                    return 400, tool_failure(ToolError("invalid_arguments", "Only command mode is exposed (Undo-grouped)."))
                arguments["execution_mode"] = "command"
            try:
                validate_call(tool, arguments)
            except ToolError as exc:
                return 400, tool_failure(exc)
            except (ValueError, SyntaxError) as exc:
                return 400, tool_failure(ToolError("invalid_arguments", str(exc)[:500]))
            done, box, cancelled = threading.Event(), {}, threading.Event()

            def complete(result):
                box["result"] = result
                done.set()

            complete.stella = True  # lets the run_script wrapper recognise Stella-originated jobs

            try:
                fusion_tools.submit(tool, arguments, complete, cancelled.is_set)
            except Exception as exc:
                return 503, tool_failure(ToolError("bridge_unavailable", str(exc)[:300]))
            if not done.wait(timeout):
                cancelled.set()
                return 504, tool_failure(ToolError("cancelled", "Bridge timeout; a started operation cannot be interrupted."))
            result = box["result"]
            if tool == "fusion_capture_viewport" and result.get("ok"):
                result = _save_png(result, captures)
            return 200, result

        def do_POST(self):
            self._handle()

        def do_GET(self):
            self._handle()

        def _handle(self):
            if not self._authorized():
                self._send(401, {"ok": False, "errorCode": "unauthorized", "error": "Unauthorized."})
                return
            parts = self.path.strip("/").split("/")
            if len(parts) != 2 or parts[0] != "v1":
                self._send(404, {"ok": False, "errorCode": "unknown_route", "error": "Unknown route."})
                return
            arguments = {}
            if self.command == "POST":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 <= length <= MAX_BODY:
                        raise ValueError
                    arguments = json.loads(self.rfile.read(length) or b"{}")
                    if not isinstance(arguments, dict):
                        raise ValueError
                except ValueError:
                    self._send(400, {"ok": False, "errorCode": "invalid_arguments", "error": "Bad JSON body."})
                    return
            status, payload = self._dispatch(parts[1], arguments)
            self._send(status, payload)

    return Handler


def start(fusion_tools, home=None):
    """One-line hook called from STEVE.run(). Returns the server, or None when not enabled."""
    home = seam_home(home)
    config = load_config(home)
    install_panel_guard(fusion_tools, panel_policy(config))
    if config.get("enabled") is not True or _state["server"] is not None:
        return None
    token = ensure_token(home)
    port = config.get("port", 0)
    if type(port) is not int or not 0 <= port <= 65535:
        port = 0
    server = ExclusiveLoopbackServer(("127.0.0.1", port), make_handler(
        fusion_tools, token, lambda: server.server_address[1], home / "captures"))
    thread = threading.Thread(target=server.serve_forever, name="Stella-Seam", daemon=True)
    thread.start()
    _state.update(server=server, thread=thread, home=home)  # set first so stop() can clean up a partial start
    try:
        (home / "endpoint.json").write_text(json.dumps(
            {"host": "127.0.0.1", "port": server.server_address[1], "pid": os.getpid(), "seam": SEAM_VERSION}),
            encoding="utf-8")
    except Exception:
        stop()
        raise
    original_close = fusion_tools.close
    original_run_script = fusion_tools.run_script

    def close():
        stop()
        original_close()

    def run_script(job):
        """Stella-originated jobs run with context['data'] (Data Panel / cloud) removed. Runs on the Fusion main thread."""
        if not getattr(job.get("complete"), "stella", False):
            return original_run_script(job)
        original_context = fusion_tools.context

        def context():
            value = original_context()
            value["data"] = None
            return value

        fusion_tools.context = context
        try:
            return original_run_script(job)
        finally:
            del fusion_tools.context

    fusion_tools.close = close
    fusion_tools.run_script = run_script
    return server


def safe_start(fusion_tools, home=None):
    """The hook used by STEVE.py: a seam failure must never abort STEVE's run()."""
    try:
        return start(fusion_tools, home)
    except Exception:
        log_error(seam_home(home), "seam failed to start:\n" + traceback.format_exc())
        return None


def stop():
    server, _state["server"] = _state["server"], None
    home, _state["home"] = _state["home"], None
    if server is not None:
        try:
            server.shutdown()
            server.server_close()
        finally:
            if home is not None:
                try:
                    (home / "endpoint.json").unlink()
                except OSError:
                    pass
