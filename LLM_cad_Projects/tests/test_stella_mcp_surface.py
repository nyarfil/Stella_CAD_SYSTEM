from stella_cad.mcp_surface import (
    STELLA_GUIDE,
    STELLA_RUN,
    attach_schemas,
    extra_tool_schemas,
    filter_listed_tools,
    guide_plan,
    mcp_surface,
)


def test_core_lists_only_guide_and_run(monkeypatch):
    monkeypatch.delenv("STELLA_MCP_SURFACE", raising=False)
    listed = [
        {"name": "undo", "input_schema": {}},
        {"name": "create_part", "input_schema": {}},
        {"name": "part_template", "input_schema": {}},
    ]
    assert filter_listed_tools(listed) == []
    extras = extra_tool_schemas()
    assert [t["name"] for t in extras] == [STELLA_GUIDE, STELLA_RUN]


def test_all_surface_is_unfiltered(monkeypatch):
    monkeypatch.setenv("STELLA_MCP_SURFACE", "all")
    assert mcp_surface() == "all"
    listed = [
        {"name": "undo", "input_schema": {}},
        {"name": "create_part", "input_schema": {}},
    ]
    assert filter_listed_tools(listed) == listed
    assert extra_tool_schemas() == []


def test_guide_holes_and_export_japanese():
    plan = guide_plan("穴付きブラケットを作って STEP で出す")
    assert "holes" in plan["routes"]
    names = plan["tools"]
    assert "add_holes" in names
    assert "export_part" in names
    assert "create_part" in names or "update_part_script" in names
    assert len(names) <= 8


def test_guide_unknown_falls_back_to_part():
    plan = guide_plan("??")
    assert plan["route"] == "part"
    assert "part_template" in plan["tools"]
    assert "create_part" in plan["tools"]


def test_guide_empty_lists_routes_without_schemas():
    plan = guide_plan("")
    assert plan["tools"] == []
    assert any(row["id"] == "holes" for row in plan["routes"])


def test_attach_schemas_drops_unknown_names():
    plan = {"route": "holes", "how": "x", "tools": ["add_holes", "nope"]}
    listed = [
        {
            "name": "add_holes",
            "description": "append holes",
            "input_schema": {"type": "object"},
        }
    ]
    out = attach_schemas(plan, listed)
    assert [t["name"] for t in out["tools"]] == ["add_holes"]
    assert out["missing"] == ["nope"]
