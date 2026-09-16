# Assembly validation notes — impeller_assembly

## Validation Report: 2026-08-05
- **Score**: 7.5/10
- **Volume**: 195948.16 mm^3 (compound, 6 components)
- **Bounding box**: -40..+40 x -60..+36 x -58..+60 mm

### Execution
`cadquery_executor` on assembly.py: SUCCESS, result_type Compound,
CHECK line reports components=6, bbox matches prior independent measurement exactly.

### DFMA Findings (dfa_report.json — overall_verdict: fail; 3 pass / 6 fail / 1 uncertain)
- DFA-005 [critical, fail per evaluator — DOWNGRADED to major on independent numeric review, see below]:
  wrench access. Claim 1 (base bolts under impeller) VERIFIED numerically:
  a Ø12 vertical socket path over the impeller-side foot-hole pair (x=±32, z=+5)
  intersects the impeller (1697.7 mm^3 each side) — those 2 of 4 anchors cannot be
  torqued with the impeller fitted. The pulley-side pair (x=±32, z=-21) is CLEAR (0.0).
  Claim 2 (no shaft counter-hold) is weak: the integral pulley IS the counter-hold
  (strap wrench on the grooved rim).
  Downgrade rationale: assembly/function unaffected; a valid build sequence exists;
  the impairment is installability/serviceability of 2 anchors; fix is local + parametric.
- DFA-009 [critical, uncertain per evaluator — RESOLVED numerically]: the evaluator could
  not visually resolve the impeller-backface-to-housing running clearance.
  It is 0.8 mm, measured twice by independent methods and encoded explicitly in
  assembly.py (impeller at Z=+0.8 vs housing face Z=0); required window 0.5–1.0. PASS.
- DFA-008 [major]: no lead-in chamfers at press-fit/close-tolerance interfaces
  (bearing seats, bore mouths) — legitimate improvement; sharp press entry risks
  brinelling the 6203 race. Recommend chamfer(0.5) at bearing seat + bore mouths.
- DFA-001 [major, fail per evaluator — INVALID]: proposes merging the "cyan thin washer"
  into the nut. The cyan part is NOT a washer: it is the 688-2Z inlet bearing
  (a catalog Buy part per the render legend + assembly.py). Vision misidentification;
  the evaluator also called the blue main bearing a "bearing housing". Disregard.
- DFA-003/004/006 [minor fails], DFA-002/007/010 [pass]: recorded in dfa_report.json.

### Bolt-hole question (numeric answer — settles the dispatcher's open item)
All 4 bearing_housing mounting holes are r=2.75 (Ø5.5, M5 clearance), axes along
local Y (vertical), at (x=±32, z=-21) and (x=±32, z=+5) — i.e. drilled vertically
through the base FOOT, exactly as the code comments state. The front render's
apparent "four holes in the upright plate" is a projection artifact: the front view
looks straight down the hole axes, so the foot through-holes project as 4 circles
overlaying the plate silhouette. No design deviation.

### Visual Observations (renders read: front_clean, right_clean, top_clean)
- FRONT_CLEAN: full axial stack visible left-to-right as
  shaft tail → teal inlet bearing → purple lock nut → green impeller →
  red housing plate (4 hole circles projected) with blue main bearing in its bore →
  orange grooved pulley integral with shaft → shaft end. Exactly the sketch order.
  Impeller silhouette is a credible centrifugal wheel: backplate at max diameter
  against the housing face, shroud/blade profile sweeping down to a narrowed
  inducer nose. Pulley shows a genuine concave belt groove in the rim,
  same color/part as the shaft (integral). Lock nut sits flush on the impeller nose.
  Teal inlet bearing is visibly far smaller than the impeller eye; shaft continues
  ~8 mm past it, matching the sketch's break-line intent.
- RIGHT_CLEAN: orthogonal confirmation of the same stack. Housing true profile reads
  as upright plate + perpendicular foot slab + hub boss on the pulley side —
  "a platform the assembly seats on". Blue bearing section sits in the hub bore
  between shaft and housing, behind the plate face. No visible gaps where parts
  should mate; no color overlap anywhere two parts should not share space.
- TOP_CLEAN (near-axial; per repo doctrine not used as sole failure evidence):
  every circular feature — impeller rim, pulley rim, bearing races, housing bore,
  nut, inlet bearing, shaft — shares ONE common center: perfect coaxial alignment,
  zero XY offset. Six double-walled backswept blade arcs are individually countable
  on the impeller. The teal inlet-bearing rings sit inside the hub-nose circle,
  well clear of the eye.
- Wireframe views deliberately not used (documented vision false-positive breeder).

### Interface / fit assessment (in place of part-level dimension check)
- Bearing OD ↔ housing bore: 6203 OD 40 in housing bore (big cyl r=20 found in
  housing geometry probe) — line-to-line as modeled. OK (representational).
- Bearing ID ↔ impeller spigot / shaft: encoded mates in assembly.py docstring
  are mutually consistent (nut span 34.8–43.2 inside thread span 31–45;
  inlet bearing 47–52 on Ø8 tail 45–60; impeller boss bears on inner race at Z=0).
- Running clearance: 0.8 mm — within required 0.5–1.0. PASS.
- Interference: boolean intersections previously measured 0.0 for all critical
  pairs (impeller/housing, shaft/housing, impeller/main_bearing, shaft/impeller);
  fresh execution + visual pass found nothing contradicting that.
- Inlet blockage: inlet bearing OD 16.0 < hub nose Ø18.0 < eye Ø34.0 —
  does not obstruct the inducer. Confirmed numerically and visually.
- Exports: 3 files per Make part present (goals' STEP/STL criterion satisfied).
- Cross-checks vs dispatch-supplied numbers: bbox, component count, clearance,
  impeller local bbox (72 x 72 x 48.8) all independently re-confirmed.
  NO contradictions found.

### Findings
- [ok] Composition matches the user's sketch exactly: pulley-shaft → housing-held
  main bearing → impeller shoulder on inner race → lock nut → small inlet bearing,
  all on one through-shaft on the Z axis.
- [ok] Impeller is a credible centrifugal compressor wheel (6 backswept blades,
  narrowing hub, backplate at max diameter).
- [ok] Pulley is credible and integral with the shaft (real belt groove).
- [ok] Running clearance 0.8 mm within the 0.5–1.0 window.
- [ok] Coaxiality: perfect concentricity in the axial view; all placements pure
  Z translations per the locked convention (Principle 0 respected).
- [major] Foot-bolt access: the impeller-side anchor pair (x=±32, z=+5) is
  socket-blocked by the impeller overhang once the wheel is fitted (verified by
  boolean probe). Unit can be assembled, but 2 of 4 foundation bolts cannot be
  torqued at installation with the impeller on.
- [major] Missing lead-in chamfers at the bearing seat and bore mouths (DFA-008).
- [minor] DFA-003/004/006 minor ergonomics findings, see dfa_report.json.

### Recommendations (for a future repair/refinement pass — none block this validation)
1. bearing_housing: relocate the impeller-side hole pair outside the impeller's
   projected envelope — either lengthen the foot in +Z so that pair sits at
   z ≥ ~+38 (beyond the impeller nose at +34.8), or widen the foot so the pair
   sits at |x| ≥ ~44 (impeller r36 + socket radius 6 + margin). Parametric,
   local, no interface changes.
2. Add 0.5 mm lead-in chamfers: shaft bearing seat, housing bore mouth,
   impeller spigot entry (protects the 6203 races at press-in).
3. Optional: two shaft flats or a screwdriver slot on the inlet-end tail would
   ease nut torquing without a strap wrench — cosmetic; pulley counter-hold works.

Verdict rationale: every success criterion in goals.md is met; the composition,
interfaces, and clearances are correct and independently re-verified; the DFA
report's sole verified-critical content is an installability constraint on two
anchors that does not prevent assembly or operation and has a cheap local fix.
The evaluator's other critical item was resolved numerically in the design's favor,
and one of its major fails was based on a part misidentification.

VALIDATION: PASSED
