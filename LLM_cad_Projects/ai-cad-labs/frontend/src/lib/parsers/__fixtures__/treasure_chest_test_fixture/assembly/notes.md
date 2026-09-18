# Assembly Notes — treasure_chest_cc

## Validation Report — 2026-07-13
- **Score**: 9/10
- **Volume**: 348586.18 mm^3 (compound, sum of 5 placed solids)
- **Bounding box**: -90.0–90.0 x -74.0–75.0 x 0.0–140.0 mm (matches expected X ±90, Y -74..75, Z 0..140 exactly)
- **Execution**: assembly.py ran clean (209 ms, result_type Compound)

### DFMA Findings
- DFA evaluator **could not run** (tool infrastructure failure, NOT a geometry finding — per dispatch instruction, validation not blocked on it). Invocation: `CAD_VALIDATOR_MODEL=evaluator-model uv run python -m tools.dfma_evaluator --mode=dfa --asm-path projects/treasure_chest_cc/assembly`. This was NOT the prior session's evaluator auth expiry (token expired); it was a model token-limit failure. Exact terminal error:
  ```
  pydantic_ai.exceptions.UnexpectedModelBehavior: Model token limit (8192) exceeded before any response was generated. Increase the `max_tokens` model setting, or simplify the prompt to result in a shorter response that will fit within the limit.
  ```
  Tool JSON: `{"success": false, "assembly_path": "projects/treasure_chest_cc/assembly", "error": "DFA evaluation LLM call failed (model=evaluator-model). See stderr for the full traceback."}`
  (Full traceback ran through pydantic_ai `_agent_graph.py:1112` `_run_stream` → `UnexpectedModelBehavior`; the override model's default max_tokens=8192 is too small for the DFA prompt/response.)

### Deterministic interference check (CONFLICT-001 confirmation)
Wrote and executed `assembly/interference_check.py` (validator tool-input scratch file): loads all 4 parts, applies the exact assembly.py placements, intersects **all 10 pairs** of placed solids. Result: `success: true`, marker volume 1.0 → **every pairwise intersection volume ≤ 0.001 mm^3**. In particular **lid ∩ base_box = 0** — the 360 mm^3 lug-slab interpenetration of CONFLICT-001 is gone with the promoted lid (`lug_underhang_trim` applied at lid/part.py line 142). Closed-lid contact is flush/rest only.

### Visual Observations (8 colored views, renders/ of 2026-07-13 13:42; legend: base_box red, lid blue, hinge_block_R green, hinge_block_L orange, hasp_plate purple)
- FRONT_CLEAN (projected along Y; image axes: horizontal = Z decreasing rightward, vertical = X): blue lid region (Z 80..140) and red base region (Z 0..80) meet at a single shared line at Z=80 — no gap, no area overlap. Green and orange hinge blocks straddle Z=80 symmetrically at X=+55/-55, each showing 2 screw-hole circles at its measured Z≈62..86 span. Purple hasp centered at X=0 spanning Z 40..80 with 2 mount holes measuring at Z≈48 and Z≈72 — matches the plan's front-wall hole spec exactly. Small blue lug rectangles sit immediately inboard of each block on the hinge-axis line.
- FRONT_WIREFRAME: adds dashed interior cavity outline (red) inside the base and dashed shell lines (blue) in the lid; purple dashed square at hasp center = the ⌀8 shackle bore through the boss. No blue hidden lines appear inside the red wall band.
- TOP_CLEAN (looking down -Z; rear = image bottom): blue lid footprint (180x120 dome) and red base footprint coincide — only the base's inner cavity rim (≈174x114) shows inset in red, meaning the 180x120 outer rects overlay exactly. X/Y centered, no offset. Two blue lug tabs project rearward past Y=-60, flanked by the orange block (left, X=-55) and green block (right, X=+55). Purple hasp boss protrudes outward (+Y) at top center — outward-facing as required.
- TOP_WIREFRAME: red dashed base rim runs coincident just inside the blue lid outline all the way around — footprint alignment confirmed. Hidden red screw-hole lines pass from the rear wall straight through both hinge-block hole patterns (wall holes and block holes aligned in X). Block internals show the pin bore dashed along X.
- RIGHT_CLEAN (projected along X; rear = image top, +Z = image right): the money view. Blue lid semicircular dome (R60) with its flat rim chord exactly coincident with the base's Z=80 edge — flush rest contact, no gap. Orange hinge block sits fully OUTSIDE the red base rectangle (Y beyond -60), flush on the rear wall line. The pin bore appears as ONE concentric circle set centered at (Y=-66, Z=80): orange block bore and blue lug bore project to the same circle with no doubling/offset — both blocks and both lugs are coaxial on the hinge axis. Purple hasp plate flush on the front wall line (Y=+60), boss outward, ⌀8 shackle hole circle horizontal along X.
- RIGHT_WIREFRAME: no blue hidden lines intrude inside the red base wall band near the top rear corner — the trimmed lug slab region (Y -60..-57, Z 76..80) is empty of lid material, visually consistent with the interference-check zero. Block screw holes dashed through the wall.
- ISO_CLEAN: chest reads correctly as a whole — hollow open-top box, dome lid seated on the rim, dome end-arcs at both X ends, hasp plate + boss centered on the front face, two hinge blocks with lid lugs between them along the rear bottom edge (rear faces viewer's lower edge in this projection). Base rear-wall hole circles (red) land directly on the block hole positions.
- ISO_WIREFRAME: red and blue rim rectangles run parallel-adjacent (lid on rim); dashed pin-bore lines in blocks and lugs lie on one line; screw-hole dashed cylinders pass block→wall on both sides; hasp mount holes align plate→wall.

### Findings
- [ok] Execution: clean; compound bbox exactly matches derivation (X ±90, Y -74 lug rear..+75 hasp boss front, Z 0..140 dome crest).
- [ok] Interference: 10/10 pairwise intersections = 0 (≤1e-3 mm^3 tolerance). CONFLICT-001 resolution confirmed at assembly level.
- [ok] lid ↔ base_box: flush rest contact on rim plane Z=80, footprints coincident (TOP views), no gap (RIGHT/FRONT views).
- [ok] Hinge axis: block bores and lid lug bores concentric at (Y=-66, Z=80) — single un-doubled circle in RIGHT view; per coordinate convention any misalignment would show as offset colors, none present.
- [ok] hinge_block placement: X=±55, flush on rear wall Y=-60, Z 62..86; screw holes align with base rear-wall holes at (X=±50/±60, Z=68).
- [ok] hasp_plate: centered X=0 on front wall Y=+60, plate Z 40..80, mount holes at Z=48/72 aligned with wall holes, boss + ⌀8 shackle hole pointing outward (+Y).
- [ok] Goals compliance: 180x120x80 base, half-cylinder lid matching footprint, 2 hinge blocks on rear top edge, 1 centered front hasp — all present and proportioned per goals.md.
- [minor] assembly.py docstring lines 27–31 still describe CONFLICT-001 as a "KNOWN ISSUE ... Fix proposed in assembly/lid/part.proposal.py" — stale now that the fix is PROMOTED into lid/part.py (open_issues.md already says RESOLVED). Comment-only drift; no geometric effect.
- [minor] DFA rules check missing from this validation (evaluator token-limit failure, above) — geometry/visual validation is complete, but the DFA rule sweep should be re-run once the evaluator's max_tokens setting is fixed.

### Recommendations
- Update assembly.py docstring (lines 27–31) to state CONFLICT-001 is resolved via the promoted lid `lug_underhang_trim` — one-comment edit, no geometry change.
- Re-run `tools.dfma_evaluator --mode=dfa` after raising the inner LLM `max_tokens` (8192 was exceeded before any response) or once EVALUATOR_API_KEY/default model is available; attach dfma_report to this file.
- `assembly/interference_check.py` is a validator scratch input; keep as a regression probe or delete at orchestrator's discretion.

VALIDATION: PASSED
