# impeller — notes

## Provenance
Designed by cad_designer (S1), dispatched solo after a 3-way parallel wave died. The agent
completed part.py and self-verified it numerically, then died of context overflow before writing
its own notes. The orchestrator salvaged the work and re-verified by direct execution.

## Verified by direct execution (orchestrator S1)
- Solids: 1 · valid: True · 46 faces · volume 33617.4 mm3
- Bounding box 72.000 x 72.000 x 48.800 mm — matches the locked spec exactly
- Z range -14.800 .. +34.000 — spigot end face at -14.8 and hub nose face at +34.0,
  exactly as constraints.md mandates. Grip length 48.8 (L_IMP_GRIP) confirmed.

## Datum
Local Z = 0 is the BACKPLATE BACKFACE (the running-clearance datum), per constraints.md.
The assembly resolver places this part at global +0.8, which is what realizes the 0.8 mm
running clearance against the housing face at global 0.

## Construction
Built with the repo's proven primitive chain for this geometry (a pre-launch probe confirmed it):
spline path -> thin blade profile swept along it -> 6x circular pattern -> union onto the hub,
with the Ø10 through-bore cut LAST. Cutting the bore last is what avoids the common failure where
a boolean union across a hollow hub yields an invalid or multi-solid result.
The single-solid result (not 7 solids) confirms the blades fused to the hub correctly.
part.py carries its own CHECK print lines for solids / validity / bbox / volume — re-run it to
re-verify cheaply without an agent.

## Load-bearing feature a repair agent must not simplify away
The Ø22.0 x 0.8 standoff boss at the spigot root is not decoration. It bears on the 6203's INNER
RACE FACE and its 0.8 mm thickness IS the running clearance. It must contact the inner race only
(race land approx Ø22.5, housing material starts at Ø40). Removing or resizing it breaks the
user's stated 0.5-1.0 mm clearance requirement.

## Deferred
No fillets or chamfers anywhere — deferred project-wide.

---

## Validation Report: 2026-08-05
- **Score**: 9/10
- **Volume**: 33,617.44 mm^3
- **Bounding box**: -36.000..36.000 x -36.000..36.000 x -14.800..34.000 mm
  (72.000 x 72.000 x 48.800) — matches the locked spec exactly
- **Execution**: success, 1 solid, valid=True, 545 ms
- **Placeholder detector**: clean (real design, not a stub)
- **dimension_checker**: PASS — expected [48.8, 72.0], actual [48.8, 72.0, 72.0]

### Measured geometry (direct probes on the built solid)
Every number below was measured by intersecting the built solid with analytic
probe volumes, not read off the source parameters.

| Check | Measured | Spec | Verdict |
|---|---|---|---|
| Standoff boss diameter | 22.000 mm | 22.0 (max 23) | ok |
| **Standoff boss thickness** | **0.8000 mm** | 0.5-1.0 window | **ok** |
| Boss Z span | -0.8000 .. 0.0000 | -0.8 .. 0 | ok |
| Backface clearance zone r20..36 below Z=0 | 0 solids | must be empty | ok |
| Spigot diameter | 17.000 mm | 17.0 | ok |
| Spigot Z span | -14.800 .. -0.8 | -14.8 .. -0.8 | ok |
| Through-bore clear inside r=4.99 | 0 solids, full length | Ø10 through | ok |
| Bore Z span / grip length | -14.8 .. +34.0 = 48.8 | 48.8 | ok |
| Backplate diameter | 72.000 mm | 72.0 | ok |
| Hub nose diameter | 18.034 mm | >= 18.0 | ok |
| Blade height above backplate at rim | 6.155 mm | 6.0 | ok |
| Blade count | 6 | 6 | ok |
| Blade angular spacing | 60.00 deg x6 at r=20, 28, 34 | equal | ok |
| Backsweep (plan-view curvature) | 10.5 deg shift r20 -> r34 | backswept | ok |

**The 0.8 mm running clearance is CONFIRMED and structural.**
The boss measures 0.8000 mm thick at Ø22.000, spanning Z = -0.8 .. 0,
and the annulus from r=20 to r=36 below Z=0 contains zero material.
The clearance therefore cannot drift:
the boss lands on the 6203 inner-race face and the backplate backface stands off
by exactly the boss thickness.

**Six backswept blades CONFIRMED.**
A cylindrical-shell section cut at three separate radii (r = 20, 28, 34)
each returned exactly six disjoint solids at 60.00 deg spacing.
The blades are genuinely backswept, not radial:
each blade centroid shifts 10.5 deg in plan between r=20 and r=34
(a purely radial blade would shift 0 deg).
All six are fused to the hub — the whole part is ONE valid solid,
not seven disconnected bodies.

### Visual Observations
- TOP_CLEAN (plan view, looking down the bore axis): the outer circle is the O72
  backplate rim. At centre sits a thick ring, the O18 hub nose face, with the O10
  bore as a smaller circle inside it. SIX curved blade traces radiate from the hub
  out to the rim, each rendered as a DOUBLE line — the two edges of the 2 mm blade
  thickness seen in projection. Every blade bows in the same rotational direction
  instead of running straight out radially, and the six flow passages between them
  are identical in shape. Counting blades directly in this view gives SIX, matching
  the numeric section cuts. (The part sits left of centre in the frame; that is
  renderer framing, not geometry.)
- FRONT_WIREFRAME (elevation, axis HORIZONTAL in this view with +Z to the LEFT):
  a tall vertical bar is the O72 backplate seen edge-on. A stepped cylinder projects
  to the RIGHT of it — the O17 spigot — ending in a flat face. To the LEFT the hub
  contour sweeps inward as a smooth concave curve with no undercut, down to a small
  flat nose face. The concave curves running above and below the axis are the blade
  top edges: tall at the inducer end and dropping to short at the rim, the expected
  meridional sweep. Grey dotted hidden lines run horizontally the full length and
  continue through the spigot to its end face, confirming the through-bore is open
  at both ends rather than blind. At this scale the 0.8 mm standoff boss is a
  sliver barely one or two pixels wide at the backplate right face and is not
  reliably resolvable by eye; it is confirmed numerically instead.
- ISO_CLEAN (near-plan isometric from the nose side): the part reads as a
  centrifugal compressor wheel. The six blades now show visible HEIGHT and
  THICKNESS, standing proud of the backplate disc, each with a top-surface band
  between its two edges, and their trailing edges terminate at the rim. The annular
  nose face around the bore is clear of blade material — the leading edges stop
  short of it, which is the 1.5 mm setback that keeps the M10 lock nut across-corners
  overhang off the blades. The camera tilt is modest, so the axial depth of the
  inducer is only weakly conveyed in this particular view.
- Not discernible in any view: the 0.8 mm boss thickness and the blade-to-hub fusion
  quality. Both were settled by analytic probes rather than by eye.

### DFMA Findings (dfma_report.json — verdict: conditional_pass, 3 pass / 3 fail / 4 uncertain)
**DISPOSITIONED AS WRONG-RULESET ARTIFACTS — these do NOT drive the verdict:**
- DFM-CNC-002 [major] fail: inter-blade passages read as deep narrow pockets.
- DFM-CNC-004 [major] fail: curved concave meridional profile reads as a restricted-access overhang.
- DFM-CNC-006 [major] fail: blades read as tall thin unsupported ribs.
- DFM-GEN-002 [critical] uncertain: no tool orientation reaches every surface.
- DFM-CNC-007 [minor] uncertain: blade-to-backplate junction sits at the bottom of a pocket.

All five are correct statements about **3-axis** milling and are inevitable for any
backswept centrifugal wheel evaluated under that ruleset.
constraints.md declares the process as `5_axis_milling`,
but a confirmed harness bug (no alias-map entry for 5-axis, and an empty 5-axis rulebook)
silently flattens the declaration to `CNC_milling` (3-axis) —
the report header itself shows `"manufacturing_process": "CNC_milling"`.
The evaluator's own top recommendation on its two largest findings is to
re-declare the process as 5-axis milling, i.e. the tool agrees the PROCESS is
mis-declared, not that the geometry is wrong.
Real centrifugal impellers are 5-axis milled (or investment cast).
**The report also carries a recommendation to cut the blade count to 4 and straighten
the blades into radial vertical walls. That recommendation is REJECTED.**
Six curved backswept blades are the explicit user requirement in goals.md and are
drawn curved in the user hand sketch; complying would mean the harness overwriting
the user design intent with the output of a mis-configured rulebook.
The blade geometry is deliberately RETAINED as designed.
- DFM-CNC-001 [critical] uncertain / DFM-GEN-003 [minor] pass: the vision evaluator
  reported **five** blades and 5-fold symmetry. This is a VISION MISCOUNT, refuted
  numerically — section cuts at three radii each return exactly six solids at 60 deg.
  Wireframe renders are a known false-positive source in this repo; the analytic
  probe is ground truth. No missing or duplicated blade exists.
- DFM-CNC-005 [major] pass, DFM-CNC-008 [critical] pass: holes and threads clean.
- PROPOSED-ASSY-004 [major] uncertain: continuous closed ring over a captive shaft —
  not applicable, the impeller slides onto a free shaft end and is clamped by the M10 nut.

### Findings
- [ok] Geometry: single valid solid, 46 faces, correct centrifugal compressor topology.
  All six blades fused to the hub.
- [ok] Dimensions: bounding box and every probed feature match the locked axial stack.
- [ok] Coordinate convention (Principle 0): bore axis on Z, part centred on XY
  (x and y both -36..+36). Z=0 is the backplate backface running-clearance datum,
  which is the intended assembly datum for this part, per constraints.md.
- [ok] Headline requirement: 0.8000 mm backface running clearance, structurally realized.
- [ok] Features: 6 backswept blades, Ø10 through-bore, Ø17 spigot, Ø22x0.8 boss,
  Ø72 backplate, Ø18 hub nose seat all present and correctly placed.
- [ok] Backface clearance zone (r 20..36 below Z=0) is completely clear of material.
- [dispositioned] Manufacturability: all 3-axis DFM failures are wrong-ruleset artifacts
  as detailed above. Under the declared 5-axis process this geometry is standard practice.
- [minor] Blade height at the exducer rim measures 6.155 mm against a nominal 6.0 mm,
  a consequence of the sloping blade top edge being sampled over a finite radial band.
  Cosmetic; no action.
- [note] No fillets anywhere — deferred project-wide by explicit doctrine, not a defect.
  No keyway, balance features, or splitters — deliberate scope decisions;
  torque is carried by clamp friction.

### Recommendations
- No geometric repair required. Do not modify part.py.
- Harness-level (NOT a part defect): fix the DFMA alias map so `5_axis_milling`
  resolves, and populate the 5-axis rulebook. Until then, this part will keep
  generating the same five spurious 3-axis findings on every re-evaluation.
- Any future repair agent must preserve the Ø22.0 x 0.8 standoff boss verbatim —
  its thickness IS the running clearance.

VALIDATION: PASSED
