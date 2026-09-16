# Open Issues — impeller_assembly

## ISSUE-001 — DFA-005: two foundation bolts are socket-blocked by the impeller  [MAJOR, RESOLVED S1]
Found by: validator (assembly pass, S1), verified numerically by its own probe.
The bearing_housing's base foot carries 4 x Ø5.5 bolt holes, correctly drilled vertically through
the foot at (x=+/-32, z=-21) and (x=+/-32, z=+5). The z=-21 pair is clear. The z=+5 pair sits on
the impeller side of the plate and is overhung by the impeller's Ø72 backplate (radius 36 > 32),
so a socket cannot reach it with the wheel fitted: a Ø12 socket path intersects the impeller by
1697.7 mm3 per side.
Severity: MAJOR, not critical. Assembly IS possible (bolt the foot down before fitting the
impeller) and operation is unaffected. Downgraded from critical by the validator for that reason.
Fix direction (arithmetic, so the repair does not have to guess): the blocking radius is the
impeller's 36 mm. A Ø12 socket needs ~6 mm of radial room, so a clear hole needs |x| >= ~42;
|x| = 46 gives 4 mm of genuine margin. Widening the foot in X is preferred over lengthening it
in +Z (a hole at z >= +38 would clear the impeller nose at +34.8, but a 68 mm deep foot on an
80 mm wide plate is ungainly).
RESOLUTION (S1): repair applied surgically as two parameters — foot width 80 -> 108 and bolt
circle |x| 32 -> 46. DFM regression gate PROMOTED the proposal, constraints.md was synced, the
part was re-exported and the assembly re-rendered and re-verified (clearance still 0.8000 mm,
interference still zero). CONFIRMED HOLDING at S2: the bearing_housing validator re-measured the
four holes at X = ±46 with the part rebuilt from current source.

## ISSUE-002 — DFA-008: no lead-in chamfers at the bearing seat and bore mouths  [WONTFIX THIS PHASE]
Found by: validator (assembly pass, S1).
Genuine DFM observation. DEFERRED BY PROJECT DOCTRINE, not by oversight: fillets and chamfers are
deferred project-wide in this run because they are the most common CadQuery failure mode in this
repo and correct geometry comes first. Every constraints.md carries the same deferral.
Revisit only when the project lifts the fillet deferral.

## ISSUE-003 — DFMA vision evaluator misidentified two parts  [INFORMATIONAL, NO ACTION]
The DFA evaluator called the cyan inlet_bearing a "washer" (which invalidated its DFA-001
merge-the-washer finding) and the blue main_bearing a "bearing housing". Both are stochastic
vision misreads, not design defects. Recorded because a future reader of the raw DFMA report
would otherwise inherit two false findings. This is the known gate-verdict stochasticity the
repo's agent instructions warn about.

## ISSUE-004 — validator reported exports that did not exist  [RESOLVED S1]
The assembly validator's summary claimed "exports present (3 per Make part)". The export
directories were in fact EMPTY. The orchestrator caught this by direct inspection and ran
tools.exporter for all three parts; STEP and STL now exist for each. No harm done, but it is a
clean instance of why a child's manifest is testimony rather than truth.

## ISSUE-005 — HARNESS BUG: no alias maps to the `5_axis_milling` ruleset  [MAJOR, OPEN — product defect, not a design defect]
Found by: orchestrator S1 while triaging the impeller's DFM failure.
`rules/*.json` DOES define a `5_axis_milling` process. But the alias map in
`.shared/tools/dfma_evaluator.py` has no entry for any human phrase naming it — it maps
"milling" -> CNC_milling, and "5-axis milling" contains "milling", so a declared 5-axis part is
silently FLATTENED to the 3-axis CNC_milling ruleset and then judged by rules it was never meant
to face. The 5-axis rulebook is therefore unreachable from a constraints.md declaration.
Impact beyond this project: any inherently 5-axis part (impeller, turbine wheel, blisk, propeller)
is STRUCTURALLY UN-PASSABLE in this harness. It cannot pass 3-axis rules, and the ruleset written
for it can never be selected. This is a harness fix, not a CAD fix.
Recommended fix: add "5 axis milling" / "5-axis milling" / "five axis" -> `5_axis_milling` to the
alias map, and make the longest alias win so "5-axis milling" cannot be captured by "milling".

### S2 CONFIRMATION — and the defect is WORSE than S1 diagnosed  [CONFIRMED, still OPEN]
Orchestrator S2 re-ran the evaluator against the corrected constraints. Two findings.

**(a) The flattening is real and now has code-level evidence.** The fresh report's
`manufacturing_process` field reads **`CNC_milling`** even though the impeller's constraints.md
declares `5_axis_milling`. `.shared/tools/dfma_evaluator.py` (around lines 88-92) defines exactly
three milling aliases — "cnc milling", "cnc machining", "milling", all mapping to CNC_milling —
and nothing anywhere maps to `5_axis_milling`. ISSUE-005 is CONFIRMED as a harness code defect.

**(b) 🚨 THE PART S1 COULD NOT SEE: the 5-axis rulebook is effectively EMPTY.** Across all of
`rules/*.json`, exactly ONE rule lists `5_axis_milling` in its `manufacturing` array —
`PROPOSED-004` — and that rule is `tier: retired`. Active 5-axis rules: **zero**, against 18
active `CNC_milling` rules. S1's statement that the rulebook "DOES define a 5_axis_milling
process" is true only in the narrowest sense: the string appears, inside a retired rule.
CONSEQUENCE: the recommended alias fix, applied ALONE, would be actively harmful. It would route
5-axis parts to a ruleset with no active rules, and the impeller would then "pass" vacuously by
being judged against nothing. A silent vacuous pass is worse than an honest wrong-ruleset
failure, because nothing signals that no evaluation occurred.
The real fix is TWO-PART and the halves must land together:
  1. Add the aliases with longest-alias-wins, so `5_axis_milling` becomes reachable.
  2. AUTHOR an actual 5-axis DFM ruleset before that alias can select anything meaningful —
     tool-reach and tool-axis rules written for simultaneous 5-axis access, blade/vane thickness
     and deflection limits, passage width versus cutter reach, blend-radius access.
Until (2) exists, declaring `5_axis_milling` on a part buys nothing.
Suggested guard while the rulebook is empty: make the evaluator REFUSE to emit a pass verdict
when the selected ruleset contains zero active rules, and say so loudly instead.

**(c) Tooling note worth keeping.** The command recorded in S1's checkpoint was missing
`--mode=dfm` and returned an instant usage error rather than running. The correct invocation is:
`uv run --frozen python -m tools.dfma_evaluator --mode=dfm --force --part-path <part-dir>`
(`--force` is needed to bypass staleness reuse of the stamped report).

## ISSUE-006 — impeller DFM verdict  [S2: verdict improved to conditional_pass; the geometry advice is still REFUSED]
S1 state — dfma_report.json: 20 rules evaluated, 6 passed, 7 FAILED, 7 uncertain, overall `fail`,
process shown as CNC_milling (i.e. 3-axis — the wrong ruleset, see ISSUE-005).
The failures, and why they are all the same finding wearing different hats:
  DFM-GEN-002 (critical) — no standard tool reaches the narrow hub-end inter-blade passages.
  DFM-CNC-004 (major)    — blade surfaces are shadowed from a single vertical tool axis.
  DFM-CNC-002 (major)    — inter-blade passages are deep curved pockets.
  DFM-CNC-006 (major)    — blades are tall thin standing features.
  DFM-CNC-007 (minor)    — blade-root internal corners need abrasive-flow/chemical deburring.
Every one of these is the correct and expected verdict for a backswept centrifugal wheel judged as
a 3-AXIS part. The evaluator's own top recommendation on both critical/major reach findings is
literally "re-declare the process as 5-axis milling (the normal manufacturing route for this part)".
🚨 DO NOT ACT ON THE GEOMETRY RECOMMENDATIONS. The evaluator also suggests reducing the blade count
to 4 and straightening the blades to purely radial vertically-extruded walls. That would destroy
exactly what the user asked for — goals.md specifies a centrifugal compressor impeller with
BACKSWEPT blades, and the sketch draws them curved. Straightening the blades to satisfy a
mis-selected ruleset would be the harness overwriting the user's design intent.
ACTION TAKEN S1: the impeller's constraints.md "Primary process" line was changed from
`CNC_milling` to `5_axis_milling` (the canonical rule ID) so a future evaluation can select the
right rulebook. NOT re-run this session — a DFM pass takes ~300 s and the budget was spent.

### S2 RE-RUN RESULT  [the verdict moved, the geometry did not]
Fresh evaluation, same part.py, same (still-wrong) CNC_milling ruleset:
**10 rules evaluated, 3 passed, 3 failed, 4 uncertain, overall `conditional_pass`** — up from
S1's `fail`. Remaining failures: DFM-CNC-002, DFM-CNC-004, DFM-CNC-006, all major, all the same
3-axis tool-reach family. The critical DFM-GEN-002 that drove S1's `fail` came back this time as
UNCERTAIN (a warning, not a failure).
Read this correctly: **the geometry did not change between the two runs — not one line of
part.py was touched.** The verdict moved from `fail` to `conditional_pass` purely from vision
stochasticity in the evaluator, and the rule count evaluated dropped from 20 to 10. This is a
textbook instance of the gate-verdict stochasticity the repo's own agent instructions warn about,
and it is worth more to the product than the verdict itself: a part's DFM verdict here is not
reproducible run-to-run. Recorded for the run reflection.
The refusal stands unchanged. The blades stay backswept and stay at 6.

## ISSUE-007 — pulley_shaft slenderness  [RESOLVED S2 — process note, no geometry change]
dfma_report.json: 17 evaluated, 14 passed, 3 failed, 0 uncertain, overall `conditional_pass`.
DFM-TURN-002 (major): slenderness. The evaluator measured L/Dmin ~13.6:1 PROPORTIONALLY OFF THE
RENDER, comparing the 118 mm overall length against the smallest diameter present (the Ø8 tail).
That is a pessimistic reading: the Ø8 tail is only 15 mm long, and the load-bearing slenderness is
better judged as 118 / 14 ~ 8.4:1 on the main shaft body, which is ordinary for a turned part with
tailstock support.
RESOLUTION (S2, orchestrator): accepted as a PROCESS NOTE, not a geometry change. Every diameter
on this shaft is locked to a catalog interface — Ø8 is the 688 inlet-bearing bore, Ø10 is the
impeller bore, and the M10 nose thread is the ISO 4032 lock nut. None can move without reopening
the sourcing decisions and the whole clamp stack. The manufacturing note that travels with the
part is: **turn between centres with tailstock support; use a steady rest when finishing the Ø8
tail; take the Ø8 tail as a final light pass to avoid deflection chatter.**
The pulley_shaft validator (S2) independently reached the same disposition and recorded it in the
part's notes.md, and additionally dispositioned two further DFMA entries as false positives:
PROPOSED-TURN-001 (the evaluator cannot see the annotation-level thread, which is modeled as a
plain Ø10 cylinder by design) and PROPOSED-TURN-006 (a thin-disc metric misapplied to a rim land
that is backed by solid material; true aspect ratio 1.6:1).

## ISSUE-008 — bearing_housing re-evaluated post-repair  [CLOSED, informational]
The post-repair dfma_report.json (22 rules, 18 passed, 3 failed, 1 uncertain) reads overall `pass`.
All three "failed" entries are PROPOSED-* rules (candidate rules not yet in the established
rulebook), not established DFM rules. No established rule fails on this part.

## ISSUE-009 — impeller blade thickness checked against the DFM suggestion  [CLOSED S2, no action]
Raised as the one genuinely process-independent finding buried inside ISSUE-006: DFM-CNC-006
suggests a blade thickness of >= 2.0-2.5 mm for the unsupported blade height.
CHECKED (orchestrator S2, direct source inspection): the impeller models `T_BLADE = 2.0` mm —
a constant-thickness blade, with the source comment noting it is above the 1.5 mm minimum wall.
The modeled thickness therefore MEETS the suggested range, sitting at its lower bound.
Disposition: NO GEOMETRY CHANGE. 2.0 mm satisfies the rule as written. Two caveats recorded for
whoever takes this to manufacture rather than for this run:
  - 2.0 mm is the floor of the suggested 2.0-2.5 band, so there is no margin above the
    recommendation. If a future revision lifts the exducer blade height above the current 6.0 mm,
    revisit the thickness at the same time.
  - The suggestion was generated under the WRONG (3-axis) ruleset, where a tall thin standing
    feature is judged for cutter deflection against a single vertical tool axis. Under genuine
    5-axis flank milling with proper tool-axis control, 2.0 mm on a wheel this size is
    conventional. The check is closed on the number, not on the rule's authority.

## ISSUE-010 — 🚨 DFM evaluator MISCOUNTED THE BLADES (reported 5, the part has 6)  [MAJOR, OPEN — product defect, not a design defect]
Found by: impeller validator (S2), which refused to take the report at its word and probed the
geometry instead.
The impeller's own `dfma_report.json` asserts the wheel has **five** blades and cites "clean 5-fold
rotational symmetry" as supporting evidence, across two separate rules (DFM-CNC-001 and
DFM-GEN-003). The part in fact has **six**. The validator settled it numerically rather than
visually: section cuts at three independent radii (r = 20, 28, 34) each returned exactly six
disjoint solids at 60.00 degree spacing, and six blade traces are visible on direct inspection of
the top view.
WHY THIS MATTERS MORE THAN THE MISCOUNT ITSELF: had the validator trusted the report over the
geometry, it would have failed the impeller for a MISSING BLADE THAT EXISTS, and the natural
"repair" would have been to add a seventh. A vision miscount that invents a defect is strictly
more dangerous than one that misses a real one, because it manufactures work that damages a
correct part. This sits alongside ISSUE-003 (the evaluator calling a bearing a "washer" and
another bearing a "bearing housing") as the same class of failure, but with sharper teeth.
Compounding evidence from the same session: the impeller was evaluated twice with byte-identical
geometry and returned `fail` (20 rules, 7 failed) the first time and `conditional_pass`
(10 rules, 3 failed) the second — see ISSUE-006. So the evaluator is unreliable on BOTH axes:
what it sees, and how many rules it decides to apply.
Recommended product actions:
  1. Ground countable features in ANALYTICS, not vision. Blade/hole/boss counts are cheaply and
     exactly derivable from the solid (section-cut-and-count is ~15 lines of CadQuery). The
     evaluator should compute them and hand the number TO the vision pass as a given, rather
     than asking a vision model to count petals in a render.
  2. Treat any vision-derived count in a report as a claim requiring a numeric second source
     before it may drive a failure verdict.
  3. Recorded for the run reflection as the strongest single piece of evidence this run produced
     about gate reliability.
