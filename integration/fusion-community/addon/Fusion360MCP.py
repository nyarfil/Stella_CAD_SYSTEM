"""
Fusion360MCP Add-in (v2)

Registers a CustomEvent so all Fusion API calls run on the main thread.
A TCP socket server (daemon thread) accepts JSON commands and dispatches
them through an EventBridge.

The add-in is deliberately loopback-only because its socket protocol has no
authentication. The host is fixed to localhost; FUSION_MCP_PORT can select a
different local port when needed.
"""

import os
import traceback

import adsk.core
import adsk.fusion

# Globals — prevent GC of handler / server references
_app = None
_ui = None
_bridge = None
_server = None
_handler = None
_log = None
_LOOPBACK_HOSTS = frozenset(("localhost", "127.0.0.1"))


def run(context):
    global _app, _ui, _bridge, _server, _handler, _log

    try:
        _app = adsk.core.Application.get()
        _ui = _app.userInterface

        # Late imports so the add-in folder is on sys.path
        from .server import LOG_PATH, get_logger
        from .server.command_handler import CommandHandler
        from .server.event_bridge import EventBridge
        from .server.socket_server import Fusion360MCPServer

        _log = get_logger("main")

        host = os.environ.get("FUSION_MCP_HOST", "localhost").strip().lower()
        if host not in _LOOPBACK_HOSTS:
            raise ValueError(
                "FUSION_MCP_HOST must be localhost or 127.0.0.1; "
                "the unauthenticated bridge is loopback-only"
            )
        port = int(os.environ.get("FUSION_MCP_PORT", "9876"))
        if not 1 <= port <= 65535:
            raise ValueError("FUSION_MCP_PORT must be between 1 and 65535")

        _handler = CommandHandler()
        _bridge = EventBridge(_app, _handler)
        _server = Fusion360MCPServer(_bridge, host=host, port=port)
        _server.start()

        _log.info("Fusion360MCP loaded - server on %s:%s  (log: %s)",
                  host, port, LOG_PATH)
    except Exception:
        msg = traceback.format_exc()
        if _ui:
            _ui.messageBox(f"Fusion360MCP failed to start:\n{msg}")
        if _log:
            _log.error("Fusion360MCP startup error:\n%s", msg)


def stop(context):
    global _app, _ui, _bridge, _server, _handler, _log

    try:
        if _server:
            _server.stop()
        if _bridge:
            _bridge.stop()
    except Exception:
        if _log:
            _log.error("Fusion360MCP shutdown error:\n%s", traceback.format_exc())

    if _log:
        _log.info("Fusion360MCP stopped")

    _server = None
    _bridge = None
    _handler = None
