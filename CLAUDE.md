@AGENTS.md

# Claude Code notes (StellaCAD)

- Shared project config: `.mcp.json` (cadmcp-design-brain, cgal-mcp, mouse-library), `.claude/settings.json` (read-only brain tools pre-allowed; writes still prompt), `.claude/agents/cadmcp-*` (five review roles), `.claude/skills/stella-cad-design`, commands `/cad-check` `/cad-design` `/cad-review`. Guide: `docs/CLAUDE_CODE_JA.md`.
- Where AGENTS.md says "Cursor / Codex", Claude Code follows the same rules via the skill above. The CAD design steps apply to product CAD only, not to cadMCP software development.
- MCP tools are deferred in Claude Code: load schemas with ToolSearch (`select:mcp__cadmcp-design-brain__brain_doctor,...`) before calling.
- Optional external writers (classcad, stella-fusion-community, stella_freecad_mouse_b) are intentionally NOT in `.mcp.json`; add them only after the owner selects that backend for a project (see docs/CLAUDE_CODE_JA.md).
