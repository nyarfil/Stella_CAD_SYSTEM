"""stdio MCP entry for Cursor and Codex as Stella_Agentcad.

Default surface is stella_guide + stella_run. The guide returns a small
tool set with schemas; the runner calls those AgentCAD tools. Set
STELLA_MCP_SURFACE=all to list the whole registry.

Stdout is the MCP protocol only.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from stella_cad.mcp_surface import (
    STELLA_GUIDE,
    STELLA_RUN,
    attach_schemas,
    extra_tool_schemas,
    filter_listed_tools,
    guide_plan,
    mcp_surface,
)
from stella_cad.runtime import apply_windows_env, ensure_confined_server, log


def _tool_result(payload) -> object:
    from mcp import types

    content: list = []
    if isinstance(payload, dict) and isinstance(payload.get("png_base64"), str):
        content.append(
            types.ImageContent(
                type="image", data=payload["png_base64"], mimeType="image/png"
            )
        )
        payload = {k: v for k, v in payload.items() if k != "png_base64"}
    content.append(
        types.TextContent(type="text", text=json.dumps(payload, indent=2, default=str))
    )
    return types.CallToolResult(content=content)


def _as_mcp_tools(rows: list[dict]):
    from mcp import types

    return [
        types.Tool(
            name=t["name"],
            description=t.get("description", ""),
            input_schema=t["input_schema"],
        )
        for t in rows
    ]


async def _serve(base: str) -> None:
    import httpx
    from mcp import types
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server

    import agentcad
    from agentcad.agent.mcp_server import REQUEST_TIMEOUT, _client_headers

    http = httpx.AsyncClient(
        base_url=base,
        timeout=REQUEST_TIMEOUT,
        headers=_client_headers(),
    )
    surface = mcp_surface()

    async def listed_registry() -> list[dict]:
        try:
            resp = await http.get("/api/tools")
            resp.raise_for_status()
            return list(resp.json()["tools"])
        except Exception as exc:  # noqa: BLE001
            log(f"mcp list failed: {exc}")
            return []

    async def on_list_tools(ctx, params) -> types.ListToolsResult:
        listed = await listed_registry()
        rows = filter_listed_tools(listed) + extra_tool_schemas()
        return types.ListToolsResult(tools=_as_mcp_tools(rows))

    async def on_call_tool(ctx, params) -> types.CallToolResult:
        args = params.arguments or {}
        name = params.name
        try:
            if name == STELLA_GUIDE:
                plan = guide_plan(str(args.get("task") or ""))
                listed = await listed_registry()
                payload = attach_schemas(plan, listed)
            elif name == STELLA_RUN:
                want = str(args.get("name") or "").strip()
                inner = args.get("arguments") or {}
                if not want:
                    payload = {
                        "error": {
                            "type": "validation_error",
                            "message": "stella_run needs name",
                        }
                    }
                elif want in {STELLA_GUIDE, STELLA_RUN}:
                    payload = {
                        "error": {
                            "type": "validation_error",
                            "message": "stella_run cannot call itself",
                        }
                    }
                elif not isinstance(inner, dict):
                    payload = {
                        "error": {
                            "type": "validation_error",
                            "message": "arguments must be an object",
                        }
                    }
                else:
                    resp = await http.post(f"/api/tools/{want}", json=inner)
                    payload = resp.json()
            else:
                resp = await http.post(f"/api/tools/{name}", json=args)
                payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            payload = {
                "error": {
                    "type": "transport_error",
                    "message": f"could not reach AgentCAD at {base}: {exc}",
                }
            }
        return _tool_result(payload)

    instructions = (
        "Stella AgentCAD. First call stella_guide with the user's task. "
        "Then call only the tools it returned, via stella_run. "
        "Parts are build123d Python (PARAMS + build(p)). "
        "Do not call generate_*. Fix rebuilds from error.line and hint."
    )
    if surface == "all":
        instructions = (
            "Agentic-first parametric CAD. Parts are build123d Python scripts; "
            "call part_template before writing your first script, then "
            "load_skill for the craft guide that matches the task."
        )

    server = Server(
        "Stella_Agentcad",
        version=agentcad.__version__,
        instructions=instructions,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )
    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        await http.aclose()


def main() -> int:
    root = apply_windows_env()
    agentcad = root / "agentcad-for-windows"
    if str(agentcad) not in sys.path:
        sys.path.insert(0, str(agentcad))

    port, health = ensure_confined_server()
    sandbox = (health.get("sandbox") or {}).get("status")
    log(
        f"mcp proxy -> {os.environ['AGENTCAD_URL']} kernel={health.get('kernel')} "
        f"sandbox={sandbox} surface={mcp_surface()}"
    )
    asyncio.run(_serve(os.environ["AGENTCAD_URL"]))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
