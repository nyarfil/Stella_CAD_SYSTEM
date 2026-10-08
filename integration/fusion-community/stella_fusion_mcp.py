"""Stella's restricted MCP surface for the pinned Fusion community add-in.

The upstream server contains a useful typed Fusion toolset, plus generic Python
execution and a whole-design delete command.  Stella deliberately exposes only
the named operations below.  This program is a stdio MCP server and delegates
each call to the upstream add-in over its localhost TCP bridge.

It never starts Fusion, installs the add-in, changes its socket binding, or
falls back to arbitrary Python when a requested operation is unavailable.
"""

from __future__ import annotations

import argparse
import copy
import json
import os

import anyio
import mcp.types as types
from jsonschema import Draft202012Validator
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from fusion360_mcp.connection import FusionError, get_connection, reset_connection
from fusion360_mcp.mock import mock_command
from fusion360_mcp.server import _format_result
from fusion360_mcp.tools import get_tool_by_name, get_tool_list

READ_ONLY_TOOLS = frozenset(
    {
        "ping",
        "get_scene_info",
        "get_object_info",
        "get_bounding_box",
        "list_components",
        "get_design_type",
        "get_parameters",
        "get_physical_properties",
        "measure_distance",
        "measure_angle",
        "check_interference",
        "compare_meshes",
        "render_view",
    }
)

# The bundled add-in opens an IPv4 socket. Keeping both ends loopback-only is
# required because its JSON protocol does not authenticate clients.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1"})

# These named operations preserve Fusion's parametric feature history.  The
# wrapper intentionally excludes execute_code, delete_all, delete_parameter,
# set_design_type, and CAM operations.  Native F3D saves stay a user action in
# Fusion; STEP/STL/view-sheet exports are explicit tool calls with a path.
MODELING_TOOLS = frozenset(
    {
        "create_sketch",
        "draw_rectangle",
        "draw_circle",
        "draw_line",
        "draw_arc",
        "draw_spline",
        "create_polygon",
        "add_constraint",
        "auto_constrain",
        "add_dimension",
        "offset_curve",
        "trim_curve",
        "extend_curve",
        "project_geometry",
        "extrude",
        "revolve",
        "sweep",
        "loft",
        "fillet",
        "chamfer",
        "shell",
        "mirror",
        "create_hole",
        "rectangular_pattern",
        "circular_pattern",
        "create_thread",
        "draft_faces",
        "split_body",
        "split_face",
        "offset_faces",
        "scale_body",
        "suppress_feature",
        "unsuppress_feature",
        "move_body",
        "rename_body",
        "boolean_operation",
        "create_box",
        "create_box_parametric",
        "create_cylinder",
        "create_sphere",
        "create_torus",
        "patch_surface",
        "stitch_surfaces",
        "thicken_surface",
        "ruled_surface",
        "trim_surface",
        "create_flange",
        "create_bend",
        "flat_pattern",
        "unfold",
        "create_construction_plane",
        "create_construction_axis",
        "create_ucs",
        "create_component",
        "add_joint",
        "create_as_built_joint",
        "create_rigid_group",
        "set_appearance",
        "set_color",
        "create_parameter",
        "set_parameter",
        "export_stl",
        "export_step",
        "export_view_sheet",
        "import_mesh",
        "undo",
    }
)


def allowed_tools(profile: str) -> frozenset[str]:
    if profile == "inspection":
        return READ_ONLY_TOOLS
    if profile == "modeling":
        return READ_ONLY_TOOLS | MODELING_TOOLS
    raise ValueError(f"Unknown Stella Fusion profile: {profile}")


def filtered_tools(profile: str) -> list[types.Tool]:
    allowed = allowed_tools(profile)
    all_tools = {tool.name: tool for tool in get_tool_list()}
    missing = allowed - all_tools.keys()
    if missing:
        names = ", ".join(sorted(missing))
        raise RuntimeError(
            "Pinned Fusion community toolset changed; refusing to guess missing "
            f"operations: {names}"
        )
    return [all_tools[name] for name in sorted(allowed)]


def parse_allowed_documents(values: list[str] | None) -> frozenset[str]:
    """Read owner-selected document names without treating a string as policy."""
    names = set(values or [])
    raw = os.environ.get("STELLA_FUSION_ALLOWED_DOCUMENTS", "[]")
    try:
        from_environment = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "STELLA_FUSION_ALLOWED_DOCUMENTS must be a JSON array"
        ) from exc
    if not isinstance(from_environment, list) or not all(
        isinstance(name, str) and name for name in from_environment
    ):
        raise ValueError(
            "STELLA_FUSION_ALLOWED_DOCUMENTS must contain non-empty document names"
        )
    names.update(from_environment)
    return frozenset(names)


def validate_arguments(name: str, arguments: dict) -> str | None:
    """Validate the pinned upstream schema before sending a socket command."""
    definition = get_tool_by_name(name)
    if definition is None:
        return f"Pinned Fusion community server has no tool named {name}."
    schema = copy.deepcopy(definition["inputSchema"])
    schema.setdefault("additionalProperties", False)
    errors = sorted(Draft202012Validator(schema).iter_errors(arguments), key=str)
    if not errors:
        return None
    messages = "; ".join(error.message for error in errors[:5])
    return f"Arguments for {name} do not match the pinned schema: {messages}"


def send_command(mode: str, host: str, port: int, name: str, arguments: dict) -> dict:
    if mode == "mock":
        return mock_command(name, arguments)
    return get_connection(host=host, port=port).send_command(name, arguments)


def write_allowed(
    mode: str,
    host: str,
    port: int,
    allowed_documents: frozenset[str],
) -> str | None:
    """Fail closed unless the active document is an owner-named test document."""
    if mode == "mock":
        return "Mock mode never accepts modeling operations."
    if not allowed_documents:
        return (
            "Modeling is disabled until the owner provides --allow-document or "
            "STELLA_FUSION_ALLOWED_DOCUMENTS."
        )
    try:
        scene = send_command(mode, host, port, "get_scene_info", {})
    except Exception as exc:
        reset_connection()
        return f"Could not read the active Fusion document before modeling: {exc}"
    if scene.get("ok") is False:
        return "Fusion could not inspect the active document before modeling."
    design_name = scene.get("design_name")
    if design_name not in allowed_documents:
        return (
            "Modeling is denied for active Fusion document "
            f"{design_name!r}. Allowed documents: {sorted(allowed_documents)!r}."
        )
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=("inspection", "modeling"),
        default=os.environ.get("STELLA_FUSION_PROFILE", "modeling"),
        help=(
            "inspection exposes only read/visual checks; modeling adds typed features."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("socket", "mock"),
        default="socket",
        help="mock is for isolated protocol verification and never connects to Fusion.",
    )
    parser.add_argument(
        "--host", default=os.environ.get("FUSION_MCP_HOST", "localhost")
    )
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("FUSION_MCP_PORT", "9876"))
    )
    parser.add_argument(
        "--allow-document",
        action="append",
        help="Exact active Fusion document name allowed for non-read-only operations.",
    )
    args = parser.parse_args()
    args.host = args.host.strip().lower()
    if args.host not in LOOPBACK_HOSTS:
        parser.error(
            "--host must be localhost or 127.0.0.1; the Fusion bridge is "
            "unauthenticated and is intentionally loopback-only"
        )
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    allowed = allowed_tools(args.profile)
    try:
        allowed_documents = parse_allowed_documents(args.allow_document)
    except ValueError as exc:
        parser.error(str(exc))
    app = Server("stella-fusion-community")

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        return filtered_tools(args.profile)

    @app.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.ContentBlock]:
        if name not in allowed:
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=(
                            f"{name} is not exposed by Stella's {args.profile} "
                            "Fusion profile."
                        ),
                    )
                ],
                isError=True,
            )
        validation_error = validate_arguments(name, arguments)
        if validation_error:
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=validation_error,
                    )
                ],
                isError=True,
            )
        if name not in READ_ONLY_TOOLS:
            denied = write_allowed(
                args.mode,
                args.host,
                args.port,
                allowed_documents,
            )
            if denied:
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=denied)],
                    isError=True,
                )
        try:
            result = send_command(args.mode, args.host, args.port, name, arguments)
        except FusionError as exc:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"{name} ERROR: {exc}")],
                isError=True,
            )
        except Exception as exc:
            reset_connection()
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=(
                            f"{name} could not reach Fusion: {exc}. Start the "
                            "pinned Fusion360MCP add-in and retry the read check."
                        ),
                    )
                ],
                isError=True,
            )
        return _format_result(name, result)

    async def run() -> None:
        async with stdio_server() as streams:
            await app.run(streams[0], streams[1], app.create_initialization_options())

    anyio.run(run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
