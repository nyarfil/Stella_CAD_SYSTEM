"""Which AgentCAD tools Cursor/Codex see over MCP.

Upstream lists all ~109. Stella defaults to one guide plus one runner.
The guide names a small set; only those are meant to be called via stella_run.
Set STELLA_MCP_SURFACE=all to list the whole registry.
"""

from __future__ import annotations

import os
from typing import Any

STELLA_GUIDE = "stella_guide"
STELLA_RUN = "stella_run"
STELLA_DESCRIBE = "stella_describe"  # kept so old clients fail closed, not listed

SURFACE_CORE = "core"
SURFACE_ALL = "all"

MAX_GUIDE_TOOLS = 8

# Default "make / edit a part" set. Not listed on MCP; the guide returns it.
CORE_TOOLS: tuple[str, ...] = (
    "part_template",
    "list_skills",
    "load_skill",
    "create_project",
    "open_project",
    "create_part",
    "update_part_script",
    "export_part",
)

# Each row: id, when (keywords, EN+JA), tools, how (what the agent should do).
ROUTES: tuple[tuple[str, tuple[str, ...], tuple[str, ...], str], ...] = (
    (
        "part",
        (
            "part",
            "部品",
            "作",
            "モデリング",
            "model",
            "cube",
            "box",
            "bracket",
            "script",
            "params",
            "build(p)",
            "build123d",
        ),
        (
            "part_template",
            "create_project",
            "open_project",
            "create_part",
            "update_part_script",
            "export_part",
        ),
        "Call part_template first. Then create_project or open_project, "
        "create_part or update_part_script, fix rebuild JSON, export_part "
        "format=step. You write PARAMS and build(p). Do not call generate_*.",
    ),
    (
        "skill",
        ("skill", "技能", "holes skill", "sheet-metal", "enclosure", "cookbook"),
        ("list_skills", "load_skill", "part_template"),
        "list_skills, then load_skill with the matching name. Do not copy "
        "skills into .cursor/skills.",
    ),
    (
        "params",
        ("set_params", "パラメータ", "寸法を変", "slider", "override"),
        ("get_part", "set_params", "get_metrics"),
        "get_part then set_params. Rebuild JSON is the answer.",
    ),
    (
        "look",
        (
            "render",
            "画面",
            "見て",
            "metrics",
            "体積",
            "質量",
            "analyze",
            "spec",
            "検査",
        ),
        ("get_metrics", "render_view", "analyze_part", "run_specs"),
        "get_metrics / render_view / analyze_part / run_specs on the live part.",
    ),
    (
        "holes",
        ("穴", "hole", "tap", "ねじ穴", "clearance", "counterbore", "m8", "m6"),
        ("load_skill", "add_holes", "update_part_script", "get_metrics"),
        "load_skill name=holes. Prefer add_holes, or write toolkit.holes in "
        "the script via update_part_script.",
    ),
    (
        "assembly",
        (
            "組み立て",
            "assembly",
            "mate",
            "メイト",
            "joint",
            "干渉",
            "interference",
        ),
        ("get_assembly", "set_mate", "check_interference", "export_assembly"),
        "get_assembly, set_mate on named connectors, check_interference, "
        "export_assembly if needed.",
    ),
    (
        "drawing",
        ("図面", "drawing", "pdf", "svg", "dxf", "sheet"),
        ("generate_drawing", "set_drawing_fields"),
        "generate_drawing with project and part_id. format svg or pdf.",
    ),
    (
        "import",
        ("取り込み", "import", "stepファイル", "stl", "参照部品"),
        ("import_cad_file", "get_part"),
        "import_cad_file with project and source path. Reference parts have "
        "no script.",
    ),
    (
        "export",
        ("書き出", "export", "step", "stl出し"),
        ("export_part", "export_assembly"),
        "export_part format=step for one part; export_assembly for the tree.",
    ),
    (
        "undo",
        ("undo", "redo", "戻す", "やり直し"),
        ("undo",),
        "undo. Do not invent a redo tool name if it is missing from tools[].",
    ),
)


def mcp_surface() -> str:
    raw = (os.environ.get("STELLA_MCP_SURFACE") or SURFACE_CORE).strip().lower()
    if raw == SURFACE_ALL:
        return SURFACE_ALL
    return SURFACE_CORE


def _score(task: str, keywords: tuple[str, ...]) -> int:
    text = task.casefold()
    return sum(1 for key in keywords if key.casefold() in text)


def guide_plan(task: str) -> dict[str, Any]:
    """Pick a small tool set from the task text. No HTTP."""
    raw = (task or "").strip()
    if not raw:
        return {
            "route": None,
            "how": "Pass task (Japanese or English). Example: "
            "「穴付きブラケットを作って STEP で出す」.",
            "routes": [
                {"id": rid, "tools": list(tools)} for rid, _kw, tools, _how in ROUTES
            ],
            "tools": [],
        }

    scored = [(_score(raw, kw), rid, tools, how) for rid, kw, tools, how in ROUTES]
    scored.sort(key=lambda row: (-row[0],))
    best = scored[0][0]
    if best <= 0:
        rid, _kw, tools, how = ROUTES[0]
        return {
            "route": rid,
            "how": how,
            "tools": list(tools),
        }

    names: list[str] = []
    routes_hit: list[str] = []
    how_parts: list[str] = []
    for score, rid, tools, how in scored:
        if score <= 0:
            continue
        routes_hit.append(rid)
        how_parts.append(how)
        for name in tools:
            if name not in names:
                names.append(name)
            if len(names) >= MAX_GUIDE_TOOLS:
                break
        if len(names) >= MAX_GUIDE_TOOLS:
            break

    return {
        "route": routes_hit[0],
        "routes": routes_hit,
        "how": " ".join(how_parts[:2]),
        "tools": names[:MAX_GUIDE_TOOLS],
        "call": "stella_run",
    }


def attach_schemas(plan: dict[str, Any], listed: list[dict]) -> dict[str, Any]:
    by_name = {t.get("name"): t for t in listed if t.get("name")}
    missing: list[str] = []
    tools: list[dict] = []
    for name in plan.get("tools") or []:
        row = by_name.get(name)
        if row is None:
            missing.append(name)
            continue
        tools.append(
            {
                "name": row["name"],
                "description": row.get("description") or "",
                "input_schema": row.get("input_schema") or {"type": "object"},
            }
        )
    out = dict(plan)
    out["tools"] = tools
    if missing:
        out["missing"] = missing
    return out


def filter_listed_tools(listed: list[dict]) -> list[dict]:
    """core: list nothing from the registry. all: pass through."""
    if mcp_surface() == SURFACE_ALL:
        return list(listed)
    return []


def extra_tool_schemas() -> list[dict]:
    if mcp_surface() == SURFACE_ALL:
        return []
    return [
        {
            "name": STELLA_GUIDE,
            "description": (
                "案内役。やりたいことを日本語か英語で渡すと、今回使ってよい "
                "AgentCAD 工具だけ（名前・説明・引数の形）を返す。"
                "返ってきた tools 以外は呼ばない。次は stella_run。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "What you want to do. Japanese or English.",
                    }
                },
                "required": ["task"],
            },
        },
        {
            "name": STELLA_RUN,
            "description": (
                "案内役が返した AgentCAD 工具を、その名前と引数で実行する。"
                "stella_guide の tools[] に無い名前は使わない。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "AgentCAD tool name."},
                    "arguments": {
                        "type": "object",
                        "description": "Arguments for that tool. Default empty.",
                    },
                },
                "required": ["name"],
            },
        },
    ]
