# Unreleased — Generic Fusion assembly bridge

- cadMCP is the control plane for a customer's solid parts, not a mouse-only
  factory. Mouse Board/Shell packs stay optional for PCB-and-shell jobs.
- Typed `FusionHandoff` plus `brain_fusion_handoff` / `brain_fusion_ingest`.
  Cursor may only run the issued Fusion adapter script (sha-checked). The
  adapter imports STEP, applies millimetre poses as centimetres, refuses to
  move protected occurrences, and never saves f3d (43 tools).
- After a Fusion print JSON, CadQuery remesures overlap, clearance and motion
  on the issued part STEPs. A Fusion screenshot is not a geometry pass.
- Recipe origin is real STEP: a Req2CAD `reference` or a registered
  `project_step`. Primitive boxes alone are still refused.

# Unreleased — Req2CAD corpus helpers

- Resume DeepCAD/CSV downloads from a stable `.partial` file with HTTP Range.
  A failed transfer keeps the partial; it is not deleted. A complete destination
  with a matching SHA is reused. The four-case demo is not a substitute catalog.

# 0.3.3 — Shell pack and structure intake gate

- Add a typed prepared-shell pack. Ready status needs a protected outer
  envelope, a positive wall thickness, matching STEP hash, and a valid B-rep.
- `brain_mouse_structure_gate` opens only when a ready board pack AND a ready
  shell pack exist. A STEP file on disk is not a shell pack. The gate does not
  generate bosses, click parts, or scan-to-shell geometry (41 tools).
- Install the package editable so Cursor MCP (cwd = project root) loads this
  tree instead of a stale site-packages 0.3.1 copy.
- Force UTF-8 on bounded CLI child processes so Windows cp932 logs cannot
  masquerade as UTF-8 JSON.

# 0.3.2 — Mouse Board Pack intake

- Add a typed Board Pack for reusable PCB mechanical interfaces (sensor datum,
  mounts, switches, keepouts) with draft vs ready status.
- Refuse ready packs that still have unverified required fields, hash mismatch,
  or an invalid STEP B-rep. Do not classify cylindrical CAD features as screws.
- Add `brain_mouse_inspect_inputs`, `brain_mouse_register_board_pack`,
  `brain_mouse_get_board_pack`, `brain_mouse_list_board_packs` (37 tools).
- Inspection never starts mechanical design from a mesh or an empty catalog.
  Req2CAD corpus install remains a separate owner step.

# 0.3.1 — Cursor support


- Add CursorProvider and explicit `--provider cursor` without removing CodexProvider.
- Handle native terminal result JSON, native engineering maps, schema failures,
  duplicate keys, non-finite numbers, errors, fresh sessions and process budgets.
- Add bounded immutable evidence snapshots, ask mode, deny rules, default sandbox
  request, and an explicit owner-controlled permissions-only option.
- Add non-generative Cursor CLI capability probe.
- Add IDE Skill, five read-only foreground subagent definitions and three commands.
- Add configuration installer preserving unrelated MCP entries/custom env, with
  managed-file conflict detection, preflight, backups and update journal.
- Record actual test-double transport/CAD results separately from live Cursor tests.

# 0.3.0 — Function → real structure → adapted prototype

- Four source-hash-checked public CAD records, actual B-rep replay and reproducible demo.
- Geometric loop containment instead of trusting inconsistent is_outer metadata.
- Safe nested/compressed DeepCAD archive normalization.
- Grouped function retrieval; paraphrases do not create extra coverage votes.
- Measured inner/outer cylindrical and planar interfaces; evidence-bound face IDs.
- Typed morphological matrix and bounded compatible functional covers.
- Typed source-bound CAD adaptation; protected hardware and editing authority.
- Automatic output-pair interference, dimensions, clearances and bounded linear-motion checks.
- Native portable z-buffer PNG views + SVG/STEP, read-only local evidence report.
- Five-role review and peer-challenge orchestration; frozen-check repair.
- Optional bounded owner-authenticated Codex CLI provider; no implicit new API calls.
- 260 passing tests in the final Linux source run; live-model/full-corpus/Windows/physical tests remain outstanding.

0.2-era test totals and intermediate failed runs are not used as this release's results.
