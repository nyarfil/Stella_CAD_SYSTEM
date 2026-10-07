"""Isolated MCP protocol probe for Stella's Fusion wrapper.

This uses the wrapper's mock transport.  It neither starts Fusion nor talks to
the local Fusion socket, so it is safe to run while a user has an unsaved model.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

FORBIDDEN = {"execute_code", "delete_all", "delete_parameter", "set_design_type"}


async def probe(profile: str, output: Path) -> None:
    command = Path(__file__).with_name("stella_fusion_mcp.py")
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(command), "--mode", "mock", "--profile", profile],
        cwd=str(command.parent),
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = sorted(tool.name for tool in listed.tools)
            exposed_forbidden = sorted(FORBIDDEN & set(names))
            if exposed_forbidden:
                raise RuntimeError(f"forbidden tools exposed: {exposed_forbidden}")
            response = await session.call_tool("ping", {})
            forbidden_response = await session.call_tool("execute_code", {"code": "1"})
            if not forbidden_response.isError:
                raise RuntimeError(
                    "execute_code was accepted by the restricted wrapper"
                )
            mutation_response = await session.call_tool(
                "create_sketch", {"plane": "xy"}
            )
            if not mutation_response.isError:
                raise RuntimeError("mock mode accepted a modeling operation")
    output.mkdir(parents=True, exist_ok=True)
    (output / f"wrapper-{profile}-tools.json").write_text(
        json.dumps(
            {
                "profile": profile,
                "tool_count": len(names),
                "tools": names,
                "ping_is_error": bool(response.isError),
                "execute_code_is_error": bool(forbidden_response.isError),
                "create_sketch_is_error": bool(mutation_response.isError),
                "probe_mode": "mock",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "profile": profile,
                "tool_count": len(names),
                "ping_is_error": bool(response.isError),
                "execute_code_is_error": bool(forbidden_response.isError),
                "create_sketch_is_error": bool(mutation_response.isError),
            }
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile", choices=("inspection", "modeling"), default="modeling"
    )
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).with_name("verification")
    )
    args = parser.parse_args()
    asyncio.run(probe(args.profile, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
