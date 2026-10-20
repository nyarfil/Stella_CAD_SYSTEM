@AGENTS.md

# Claude Code notes (StellaCAD)

- Shared project config: `.mcp.json` (cadmcp-design-brain, cgal-mcp [CGAL Master, the only CGAL server; call `cgal_get_guide` first, see `docs/CGAL_INTEGRATION_JA.md`], mouse-library), `.claude/settings.json` (read-only brain tools pre-allowed; writes still prompt), `.claude/agents/cadmcp-*` (five review roles), `.claude/skills/stella-cad-design`, commands `/cad-check` `/cad-design` `/cad-review`. Guide: `docs/CLAUDE_CODE_JA.md`.
- Where AGENTS.md says "Cursor / Codex", Claude Code follows the same rules via the skill above. The CAD design steps apply to product CAD only, not to cadMCP software development.
- MCP tools are deferred in Claude Code: load schemas with ToolSearch (`select:mcp__cadmcp-design-brain__brain_doctor,...`) before calling.
- Optional external writers (classcad, stella-fusion-community, stella_freecad_mouse_b) are intentionally NOT in `.mcp.json`; add them only after the owner selects that backend for a project (see docs/CLAUDE_CODE_JA.md).

## Lessons (evolve 2026-10-15)
- Scan import: weld vertices by position right after loading a textured PLY (trimesh merge_vertices / pymeshlab remove_duplicate_vertices); per-corner UV splits create fake seams and break every mesh gate. PyMeshLab is the scan->mesh pipeline of record.
- Mesh quality gates: max Hausdorff alone is not enough; add visual review and a watertight check. Shell reports include a thickness heatmap, max thickness (<= T+0.2 mm) and mass in grams.
- Region recognisers take mesh (+optional texture) only; never PCB/STEP or part-tuned constants as inputs. For region truth, render a gridded plain view, let the owner draw, then digitise.
- Before building structure (joints, click plates, side buttons), get the owner's explicit design instructions and pin down which part fails; do not invent structure or iterate blind.
- Fusion: import big STEPs one at a time with Fusion idle; never several in one script call. STEVE is not used for main creation/modification (read/inspect only); fix tool bugs in the tool source plus a test, not with workarounds.
- Every fix lives in MCP tools + gates and is proven by a from-raw one-shot rerun; use targeted tests, full suite only at integration.
