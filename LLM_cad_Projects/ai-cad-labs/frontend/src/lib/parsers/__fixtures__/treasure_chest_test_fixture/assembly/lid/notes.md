# Design Notes: lid

**Status**: fresh design, executed + rendered + visually verified (2026-07-13).

## Approach
Feature-decomposed part (cookbook Pattern 10), 4 features: `dome_blank` (semicircular
profile on a YZ workplane, extruded ±90 along X), `interior_cavity` (R57 x 174
semicylindrical cutter — leaves 3 mm curved wall, 3 mm end caps at X=±87..90, and opens
the flat rim), `hinge_lugs` (two boxes unioned to the shell), `hinge_pin_bores` (one
⌀3.4 cylinder along X through both lugs). Profile-extrude was chosen over shell()
because the open face is the FLAT face of a half-cylinder — shell() face-selection on
a semicircular solid is fragile; a profile cut is exact and robust.

## Key dimensions (all per constraints.md — none invented)
- Outer R60, wall 3 (inner R57), length 180 (X -90..+90), cavity length 174
- Rim face local Z=0 (== global Z=80 when closed); dome in +Z; rear = -Y
- Lugs: 15 wide, centered X=±37 (spans |X| 29.5..44.5), Z=-4..+4, rear face Y=-74
- Bores: ⌀3.4 through, axis local (Y=-66, Z=0) — nominal, NO FDM compensation (sourcing:
  ISO 2338 ⌀3x35 pin ROTATES in these lugs, ~0.4 mm running clearance)
- Verified bbox: 180.0 x 134.0 x 64.0 (X -90..90, Y -74..60, Z -4..60) — exact match
- Volume 133,317 mm³ (analytic cross-check 133,309 — agreement to 0.006%)

## Constraint discovered during design (deviation, deliberate)
Constraints say the lug body spans Y=-74..-60, "merged with the shell at Y≈-60". A lug
ending exactly at Y=-60 touches the dome's curved outer surface only along the tangent
line at Z=0 (at Z=4 the dome surface is at Y≈-59.87) → degenerate/non-manifold union.
**Fix: the lug body extends internally to Y=-57 (the inner radius)**, burying 3 mm of
lug inside the wall material for a solid merge. This does NOT intrude into the interior
cavity (the inner surface curves inward for Z>0, cavity boundary is Y>-57 there) and
does NOT change the visible lug (still Y=-74..-60 outside the dome) or the bbox.
Validators: cross-sections through the lugs will show lug material continuing to Y=-57
inside the wall — this is intentional.

## Tool issue found (for orchestrator/validator — not a geometry problem)
The renderer's automatic dimension check FAILED with expected [4, 14, 64]: the
dimension parser grabbed the numbers from the PARENTHETICAL in the constraints
"Overall:" line ("...projecting 14 mm rearward ... and 4 mm below...") instead of
"180 x 134 x 64 mm". The executor bbox proves the part is exactly 180 x 134 x 64.
Recommend fixing dimension_checker to stop parsing at "(" on the Overall line.

## What adjacent parts should know
- Hinge axis: local (Y=-66, Z=0) == global (Y=-66, Z=80). Same axis as hinge_block
  ⌀3.1 press-fit bores. Lug outer faces at |X|=44.5 → 0.5 mm axial gap to block inner
  faces at |X|=45.
- Rim face (local Z=0) is flat and open (3 mm ring + end-cap footprint) — rests on the
  base_box rim at global Z=80, footprints aligned 180 x 120.
- Assembly placement of this part: `cq.Location(cq.Vector(0, 0, 80))` in the global frame.
- Lugs hang 4 mm below the rim (global Z=76..80 when closed) — base_box rear wall must
  stay clear of Y=-74..-60 above Z=76 (it does: base outer wall is at Y=-60).

## Trade-offs / print notes
- No fillets (deferred project-wide). Sharp lug-to-shell junction is a stress riser at
  the hinge — candidate for fillet phase later.
- Print rim-face-down (dome up); lugs need small supports (4 mm below rim) — accepted
  in constraints. Lug walls around the bore: (8-3.4)/2 = 2.3 mm — above plastic floor.

---

## Validation Report — 2026-07-13
- **Score**: 9/10
- **Volume**: 133316.98 mm^3
- **Bounding box**: -90.0-90.0 x -74.0-60.0 x -4.0-60.0 mm (= 180 x 134 x 64, exact match to spec)

### DFMA Findings
- [tool-failure] DFM check DID NOT RUN — `tools.dfma_evaluator --mode=dfm` exited 1 before evaluating any rules: the inner LLM provider raised an authentication error (`UserError`): the evaluator API key was not set in the environment. No `EVALUATOR_API_KEY` in the shell environment (this repo takes API keys from the shell env per CLAUDE.md). No dfma_report.json was produced. This is a tool/environment malfunction, NOT a part finding — the orchestrator should re-run the DFM check once the key is available.
- Manual manufacturability spot-checks in lieu (see Findings): 3 mm walls, 2.3 mm plastic around bores, print orientation per constraints — no red flags found by inspection.

### Visual Observations
(All 8 renders at renders/*.png read individually. In these projections the X axis is rendered vertically in the FRONT views and horizontally in the TOP/ISO views.)
- FRONT_WIREFRAME: I see a long rectangle (aspect ~0.36, consistent with 64 wide x 180 tall) with a dashed inner rectangle inset uniformly from the outline — the hollow interior behind uniform-thickness walls. Two small solid rectangles protrude slightly past the right-hand (rim-side) edge at roughly 1/3 and 2/3 of the length, positioned symmetric about the midpoint — the two hinge lugs projecting past the rim plane (Z=-4). Each lug contains dashed lines running lengthwise — the hidden ⌀3.4 bores along X.
- FRONT_CLEAN: Same silhouette without hidden lines: clean rectangle with two small lug tabs breaking the rim-side edge; lug offsets from center look equal (≈ ±37/90 of the half-length).
- TOP_WIREFRAME: A 3:2 rectangle (180 x 120 dome footprint) with a dashed inner rectangle (the 174 x 114 cavity — 3 mm walls all round visible as the offset). Two tabs protrude from the rear (bottom) edge, symmetric about center at the expected ±37 positions, each ~15 mm wide and projecting ~14 mm (proportions match 100 px and 93 px at the view scale). Inside each tab, two parallel dashed lines run along X — the hidden bore walls at Y=-66.
- TOP_CLEAN: Clean 180 x 120 rectangle + two rear lug tabs; no other features on the outline — flat end caps confirmed (no protrusions at X=±90).
- RIGHT_WIREFRAME: A "D" profile — vertical flat edge (the rim face) with a semicircular dome bulging to one side. A dashed semicircle runs concentric just inside the outer arc — the R57 cavity, i.e., a uniform 3 mm curved wall. A small rectangular tab sits at the rear end of the flat edge, protruding ~4 mm past the rim plane, containing a small SOLID circle — the ⌀3.4 bore seen end-on, centered in the lug beyond the dome's rear extent (consistent with axis at Y=-66, Z=0). Both lugs and their bores are coaxial, so they overlap into one tab/circle in this projection.
- RIGHT_CLEAN: Same D-silhouette + lug tab with the bore circle visible end-on. The flat rim edge is a single straight line — rim is planar.
- ISO_WIREFRAME: Half-cylinder shell lying axis-horizontal, flat rim down. Dashed lines show: the interior cavity surface, inner arcs offset ~3 mm inboard of BOTH end faces (the flat 3 mm end caps at X=±87..90), and dashed bore lines passing through each lug. Lugs hang below the rim edge on the rear side with visible bore openings on their outer X faces.
- ISO_CLEAN: Clean half-cylinder with the two rear lugs below the rim; bore openings visible as small ellipses on the lug faces. No fillets/chamfers anywhere on the silhouette — sharp edges throughout, as specified.
- NOT visible in any view: wall thickness at the rim ring itself (edge-on in TOP), and the intentional lug embedment to Y=-57 (buried inside the wall — per designer's note this is deliberate and is NOT flagged).

### Dimension check
- `tools.dimension_checker`: reports FAIL, expected [4.0, 14.0, 64.0] vs actual [64.0, 134.0, 180.0]. This is the KNOWN parser artifact (it reads the parenthetical "…14 mm rearward… 4 mm below…" in the constraints "Overall:" line instead of "180 x 134 x 64 mm"). The checker's own measured dims [64, 134, 180] equal the spec set {180, 134, 64} exactly.
- Authoritative check from executor JSON: X -90..90 → 180.0 ✓; Y -74..60 → 134.0 ✓ (dome -60..60 = 120 + 14 mm lug projection); Z -4..60 → 64.0 ✓ (dome 60 + 4 mm lug drop). Per-axis: PASS / PASS / PASS, 0% deviation.

### Findings
- [ok] Geometry: half-cylinder shell R60 x 180 with open flat rim at Z=0, dome in +Z — matches description and all views; topology correct (single shell + 2 lugs, hollow interior visible in wireframes)
- [ok] Dimensions: bbox exactly 180 x 134 x 64; volume 133,317 mm³ agrees with the designer's analytic value (133,309, 0.006% off) and with a rough independent estimate (~133.3k: half-annulus shell + caps + lugs − bores)
- [ok] Wall/caps: uniform 3 mm curved wall (concentric dashed R57 arc in RIGHT_WIREFRAME); 3 mm flat end caps (inner arcs offset from end faces in ISO_WIREFRAME; cavity length 174 in code)
- [ok] Features — lugs: 2 lugs, 15 mm wide, centered X=±37 (verified proportionally in TOP/FRONT views and in code: spans |X| 29.5..44.5), projecting to Y=-74 and Z=-4..+4
- [ok] Features — bores: ⌀3.4 through-bores along X at local (Y=-66, Z=0) — visible end-on centered in the lug in RIGHT views, as hidden lines in FRONT/TOP/ISO; single coaxial cutter guarantees the two bores are aligned
- [ok] Features — no fillets present (project-wide deferral honored; none flagged)
- [ok] Known-issue 1 handled: lug embedment to Y=-57 inside the wall is the designer's documented intentional manifold-union fix — NOT flagged as interference
- [ok] Known-issue 2 handled: auto dimension-check FAIL is a parser artifact — bbox verified from executor JSON instead
- [ok] Manufacturability (manual, FDM): 3 mm walls >> 0.8 mm floor; 2.3 mm plastic around bores; rim-face-down print with small lug supports per constraints; no impossible geometry
- [ok] Coordinate convention (Principle 0): part follows its constraints-specified local frame — centered on XY, functional rim plane at Z=0 (lugs deliberately dip to Z=-4 per spec), hinge axis exactly where the interface contract requires; correct for downstream assembly placement at (0,0,80)
- [minor] DFM rules check unavailable this run (tool/env failure, EVALUATOR_API_KEY missing) — no dfma_report.json deliverable; needs a re-run when the environment is fixed

### Recommendations
- No geometry changes required — part meets every constraint checked.
- Orchestrator: re-run `uv run python -m tools.dfma_evaluator --mode=dfm --part-path projects/treasure_chest_cc/assembly/lid` once `EVALUATOR_API_KEY` is set in the shell env, to produce the missing dfma_report.json deliverable.
- Toolsmith: fix the dimension parser to stop at "(" on the constraints "Overall:" line (also noted by the designer above) — it currently harvests numbers from the parenthetical.

VALIDATION: PASSED
