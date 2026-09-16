"""stdio MCP entry for Cursor and Codex. Same 109 tools Claude Code used.

Stdout is the MCP protocol only. Start with:

    python -m stella_cad.mcp
"""
from __future__ import annotations

import os
import sys

from stella_cad.runtime import apply_windows_env, ensure_confined_server, log


def main() -> int:
    root = apply_windows_env()
    agentcad = root / "agentcad-for-windows"
    if str(agentcad) not in sys.path:
        sys.path.insert(0, str(agentcad))

    port, health = ensure_confined_server()
    sandbox = (health.get("sandbox") or {}).get("status")
    log(f"mcp proxy -> {os.environ['AGENTCAD_URL']} kernel={health.get('kernel')} sandbox={sandbox}")

    from agentcad.agent.mcp_server import run_mcp_server

    run_mcp_server()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
