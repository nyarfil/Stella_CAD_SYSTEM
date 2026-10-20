# Mouse scan-to-CAD MCP: lessons log

Running log for porting the owner-approved LH2 manual build into brain_mouse_* tools. One entry per finding:
what happened, root cause, rule for next time. Read before changing the chain. Newest last.

## Pipeline order
- 2026-10-16 Cutting the same boundary twice breaks B-reps. Old order click_slots (shallow groove) -> split_click
  (re-cut along the same rim) -> carve left near-coincident walls, tolerance growth to 0.11 mm and an unmeshable skin strip.
  Hours of fuzzy/tolerance tweaks did not fix it.
- 2026-10-16 Owner's order (ORDER-2): hollow the filled shell first (carve, plain 1.2 mm), then cut the click grooves THROUGH
  the wall so the plates separate by themselves, then add floor/hinge/lip, then wheel window. First try: carve READY at once
  (13042 mm3 vs official 13128), through-wall slots READY after fixes. Rule: prefer an order where every boundary is cut once.
- 2026-10-17 Through-wall slots: a centre gap ending short of the wheel window leaves a ligament joining L/R plates;
  extend gap ends into the window footprint. Gap ends that meet another band must be trimmed to that band's centre,
  otherwise zero-area junction faces appear.

## Review discipline
- 2026-10-16 The Inca seam was wrong (rode up onto the click lip at the front) and every gate said READY. The owner caught it by
  eye. Rule: open every stage image and write one line on what it shows before moving on; recognisers emit a review image and a
  sanity gate (continuity, support fraction) that returns REVIEW.
- 2026-10-16 Use the texture when the scan has one (PLY + JPG come as a pair): plate/shell colour boundary is the seam.
  Weld vertices after loading a textured PLY.
- 2026-10-16 An agent excluded about 50 % of samples as "feature bands" to pass a gate. Reject gate gaming; re-measure on the full
  visible skin.
- 2026-10-16 Two deviation numbers disagreed (tool p95 0.033 vs check p95 0.93): different populations (filled functional
  regions, nearest-vertex vs point-to-surface). State the population with every number.

## Generality and regressions
- 2026-10-16 No LH2 constants in defaults: defaults are generic process values or derived from the inputs; LH2 numbers only in
  explicit arguments and verification recipes.
- 2026-10-16 A crease-trim rule tuned on Inca shortened approved LH2 slots by about 5 mm per side. Rule: every scan-tool fix
  re-checks the other model's approved geometry; trims must be defect-driven, not rule-driven.

## OCC pitfalls
- BRepAlgoAPI_Common can silently return garbage or empty on face contact: cross-check with a mesh intersection (manifold3d).
- BRepGProp volume is inaccurate unless Eps <= 0.001: gate on mesh volume.
- STEP written with the shape's average tolerance (~1e-3) re-imports with degenerate bridging edges: write fixed 1e-4 precision.
- BRepMesh on large trimmed B-spline faces can overflow the stack: run workers on a 128 MB thread stack.
- Fillets can report IsDone and still be invalid; check validity and STEP round-trip meshability.

## Process
- 2026-10-17 Owner banned Fable (rate limit hit overnight, cost). Use Sonnet; Opus only after two Sonnet failures on the same
  subproblem.
- Two agents editing the same tool file at once caused a hidden collision (click_slots). Set file ownership before launching.

## Open
- 2026-10-17 The "MCP only" chain output is rough compared with the manual build: some step goes wrong. Investigate later,
  stage by stage, against the manual LH2 history (whole_v1..v9, carve, official v39).
- Click panel surface distortion vs the manual reference (deferred by the owner).
