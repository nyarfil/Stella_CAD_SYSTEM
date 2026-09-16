---
name: run-reflection
description: Write the structured self-debrief every harness run produces at its terminal state, the run_reflection.md that feeds the harness self-improvement loop ("AI-age telemetry": an agentic run ships judgment, not just logs). Use when a run reaches terminal state (goals met / gave up / resume-completion), when writing or synthesizing run_reflection.md or reflection_notes.md, when an orchestrator is ending its life or checkpointing, or any time you are about to finish a design run and need to capture what failed, what the run improvised to protect the result, and what would make the next run smarter. Defines the schema (verbatim), the quality bar, and one worked example.
---

# Run Reflection: every run debriefs itself for the dev loop

## Why this exists

Classical telemetry ships logs; an agentic product can ship **judgment**.
No matter where the harness runs,
a watched dev session or a bare `claude -p` from any command line on any machine,
the run ends by writing a structured self-debrief:
what failed (exactly), what the run improvised to protect the result,
and what tactical fixes + paradigm shifts would make it unnecessary next time.
The dev side (human or agent) sweeps these debriefs and turns them into harness improvements.

This operationalizes the harness's core self-healing principle:
*when things fail, the end result should not be affected:
break the conventions, get the job done,
and catalog the improvisation so future agents can be smarter for it.*
Runs already break conventions to protect outcomes
(an env self-fix mid-run, an arc-stitch→point-sampled adaptation,
a filesystem-only crash resume).
Today those heroics surface only when a context-rich session happens to be watching.
**After this, the run itself is the witness.**

`run_reflection.md` is DEVELOPMENT feedback for the improvement loop.
It is **never load-bearing for the run itself**:
it does not gate completion, and a run is not "failed" for lacking one.
But a run that finishes without its reflection is
**invisible to the self-improvement loop; the next run repeats its failures.**
That is the whole cost, and it is enough.

## The two-file write protocol (crash-safe by design)

Designed directly from the harness's four observed death modes:
auth kill, background-dispatch orphan-kill, API stream timeout, context overflow.
Two files, two jobs:

1. **`reflection_notes.md`**: append-only raw notes, written AS-YOU-GO.
   Every orchestrator session appends to it at its checkpoint step,
   at its end-of-life step,
   AND the moment anything notable fails or gets improvised
   ("note it when you feel it").
   One-liner format:
   `[<role/session> @ phase] <what happened / what it cost / gut suggestion>`.
   This file **survives any death**:
   if the run crashes before synthesis, the notes are the salvage.
2. **`run_reflection.md`**: the synthesized debrief,
   written ONCE at **terminal state** (goals met, give-up, or resume-completion)
   by the finishing session, from:
   `reflection_notes.md` + `design_log.md` + `open_issues.md` +
   per-part `attempt_log.json` + `smoke_report.md` + your own judgment.
   **Resume sessions inherit synthesis duty**:
   a resume that completes a predecessor's run owns the reflection
   and must fold in the predecessor's `reflection_notes.md`.

**Ownership closure (who writes it: no fall-through, no duplicate):**
1. **Coupling**: whoever writes `smoke_report.md` synthesizes `run_reflection.md`
   IMMEDIATELY after it, same session, same sitting.
   Reflection rides smoke_report; it is not a separate deferrable step.
2. **Backstop (self-healing)**: if you reach terminal state
   and `smoke_report.md` exists but `run_reflection.md` does NOT,
   the writer fell through, so YOU synthesize it now.
   This closure is self-healing, not someone else's job.
3. **No-duplicate**: before synthesizing, check whether a conforming
   `run_reflection.md` already exists for this terminal state.
   If it does, do not duplicate:
   append amendments only if you hold genuinely new material.

Separation of concerns (each existing file keeps its job):
`checkpoint.md` = run-CONTINUATION state for successor orchestrators ·
`smoke_report.md` = OUTCOME summary for whoever wanted the design ·
`run_reflection.md` = DEVELOPMENT feedback for the improvement loop.

## The schema (VERBATIM: this is the contract)

A single self-contained markdown file (packageable / sendable:
it survives being tarred and sent from a customer site
because its provenance is in the frontmatter).
YAML frontmatter is machine-routable;
the sections are human-and-agent readable.

```markdown
---
schema_version: 1
project: <name>
outcome: complete | partial | failed
started: <iso>
ended: <iso>
sessions: [{n: 1, end: completed|crash-auth|crash-dispatch|overflow|...}]
parts_built: N
repair_cycles: N
conflicts: N
tags: [<component/failure-class tags for sweep-filtering>]
---
# Run Reflection: <project> (<date>)
## 1. What happened            - 2-3 lines, outcome + shape of the run
## 2. Failures & frictions     - SPECIFIC: per event: what failed, exact error class,
                                 where (phase/agent/tool), workaround taken, cost (time/retries)
## 3. Self-healing actions     - conventions broken / improvisations that protected the result
                                 (CELEBRATED, not confessed: this is the principle working)
## 4. Tactical suggestions     - concrete: tool flags, error-message enrichments, instruction edits
## 5. Strategic suggestions    - OPEN-ENDED: "this problem class dissolves under <paradigm>"
## 6. Knowledge candidates     - cookbook patterns, DFM-rule ideas, reference-gap observations
## 7. Unknowns                 - what the run could NOT diagnose (honest blind spots)
```

Canonical location: `projects/<name>/run_reflection.md`.
It travels with the run.
The v1 consumer is a sweep over `projects/*/run_reflection.md`;
the frontmatter `tags` are what a sweep filters on,
so tag by component (`gears`, `assembly`)
and failure class (`dispatch-death`, `token-ceiling`, `vision-false-positive`).

## The quality bar (this is what makes a reflection worth sweeping)

**Every section has ≥1 genuine entry, OR one honest line saying why it is empty.**
No empty-ceremony sections.
"## 3. Self-healing actions: none needed; single-pass build, no conventions broken"
is a *good* entry; a blank section is not.
An honestly-empty section is signal too
(a run with zero frictions is telling the dev loop the harness is healthy on that axis).

**Reflections describe the run, never the operator.**

Section-specific bars:

- **§2 Failures: SPECIFIC, never vague.**
  Every entry names the **error class** (the actual message or condition,
  e.g. `Model token limit (8192) exceeded`, `auth token expired`, `AttributeError`),
  the **where** (phase + agent/tool), the **workaround** taken,
  and the **cost** (minutes, retries, session death).
  "Some errors occurred and were handled" is worthless to the dev loop.
  "crankshaft DFM failed 2× on the 8192-token inner-call ceiling
  in the dfma_inspector sweep; 3rd attempt passed; cost ~8.8 min" is actionable.
- **§3 Self-healing: CELEBRATED, not confessed.**
  When the run broke a convention to protect the result,
  that is the principle *working*, not a sin.
  Write it with pride and enough detail
  that the next run can reuse the improvisation:
  what was broken, why, what it protected.
- **§4 Tactical vs §5 Strategic: keep them genuinely different.**
  §4 is concrete and small:
  a tool flag, an error-message enrichment, one instruction edit:
  things a dev could ship this week.
  §5 is **open-ended paradigm thinking**:
  "this whole *class* of problem dissolves if we <reframe>."
  §5 is NOT a restatement of §4 in fancier words.
  If §5 just says "add the flag from §4," it has failed:
  §5 should name the pattern behind the friction and the paradigm that would retire it.
- **§6 Knowledge candidates** are for durable reuse:
  a cookbook pattern the run discovered, a DFM/DFA rule idea,
  a gap in the reference docs.
  Distinct from §4 (which fixes the *harness*);
  §6 grows the *knowledge layer*.
- **§7 Unknowns: honest blind spots.**
  What the run genuinely could not diagnose.
  A reflection that claims to understand everything
  is less trustworthy than one that names what it couldn't see.

Length is not the bar: honesty and specificity are.
A clean single-pass run yields a short reflection;
a thrashing run yields a long one.
Both are correct if every populated line is real.

## Worked example (real: the `spur_gear_probe` run, 2026-07-21)

This is a lightly-trimmed real reflection from the gear-pair probe:
a single-pass build that hit one genuine geometry adaptation,
one runner-level death, and one tooling gap.
Study why each section earns its place (annotations follow).

```markdown
---
schema_version: 1
project: spur_gear_probe
outcome: complete
started: 2026-07-21T16:27:08+05:30
ended: 2026-07-21T17:16:54+05:30
sessions:
  - {n: 1, end: crash-dispatch}   # background-dispatched orchestrator, then ended turn (headless -p has no re-invoke)
  - {n: 2, end: completed}        # resume from filesystem; completed clean
parts_built: 3
repair_cycles: 0
conflicts: 0
tags: [gears, involute, dispatch-death, exporter-gap, single-pass]
---
# Run Reflection: spur_gear_probe (2026-07-21)

## 1. What happened
Meshing involute spur-gear pair (pinion 18T + gear 30T, m=2, 20° PA) + plain shaft ×2, 3D-print.
Shipped complete: 3 parts, 0 repairs, clean mesh at 48 mm centre distance. First-ever gear-class
geometry for this harness. It generalized. One death (background-dispatch in session 1) fully
recovered by filesystem resume; 0 work lost.

## 2. Failures & frictions
- **Session-1 death: background-dispatch orphan-kill.** The entry session dispatched the
  orchestrator as a BACKGROUND agent, ran a self-critique, and ended its turn ("will apply findings
  when it reports back"). In headless `claude -p` there is no re-invocation: turn-end exited the
  process and took the in-process orchestrator with it. Phase: post-design (3 parts coded, validators
  about to dispatch). Workaround: resume session reconstructed state from the filesystem. Cost:
  ~14 min death+resume overhead (design work itself was untouched: part.py mtimes unchanged).
- **Golden `cylindrical_gear.py` arc-stitching failed on BOTH gears** for these params. Not a
  hallucination: numerical fragility of the reference method. Phase: design (cad_designer). See §3.
- **Exporter cannot export an assembly.** `tools.exporter` only targets `part.py`; the assembly had
  no export path. Phase: export. Workaround in §3. Cost: minor (one improvised exec).

## 3. Self-healing actions
- **Arc-stitch → point-sampled involute.** When the golden method failed, the designers did not
  stall: they switched to a robust point-sampled polyline involute (12-14 samples/flank) and shipped
  both gears in a SINGLE design pass, 0 repairs. Convention broken (the reference workflow's golden
  example was consulted 18× and then correctly *rejected* as non-robust); result protected.
- **Assembly export via direct exec.** With no exporter path for assemblies, the run exported the
  assembly by exec'ing `assembly.py` through the same `CadQueryExecutor` + `cq.exporters` path the
  tool uses internally. Got the STEP/STL out; job done.
- **Quantitative mesh verification instead of trusting vision.** The resolver verified the half-tooth
  phase two independent ways (Z=0 section interference 18.04→0.00 mm²; full-face 3D boolean 0.0000 mm³
  vs 180.36 mm³ control) rather than trusting the false-positive-prone render.

## 4. Tactical suggestions
- **Exporter `--entry-file` flag** so assemblies (and any non-`part.py` entry) export through the
  tool instead of an improvised exec.
- **Entry-prompt MUST mandate synchronous dispatch**: "run the orchestrator to completion in THIS
  turn; never background-dispatch and end; headless has no re-invoke." (This exact line, baked into
  the resume prompt, worked.)
- **Flush the gear validator's `[validator]` design_log line**: gear validation happened but its
  summary line never reached design_log (logging gap, not a correctness gap).

## 5. Strategic suggestions
- **Reference examples are candidates, not gospel: the harness needs a "golden method failed,
  adapt" muscle as a first-class pattern, not a lucky improvisation.** The run consulted the golden
  gear example, detected its numerical fragility, and adapted. That judgment fired by luck of a
  capable designer; the paradigm shift is to make "verify the reference method on THESE params before
  committing; fall back to a robustness-ranked alternative" an explicit design step. This dissolves a
  whole class ("the golden example doesn't fit my parameters") beyond gears.
- **Runner robustness is a different axis from harness robustness.** Every death this class of run
  has seen (auth, dispatch, overflow) is a *launcher/runner* failure, not a design failure. The
  design pipeline is robust; the thin `claude -p` runner around it is where runs die. A supervisor
  that owns dispatch-mode + resume as a contract would retire the entire death class.

## 6. Knowledge candidates
- **Cookbook pattern: "point-sampled involute over arc-stitch"**: the robust involute-flank method
  this run discovered, with the sample-count guidance (12-14/flank).
- **Cookbook assembly pattern: "gear mesh = half-tooth phase + section/boolean interference verify"**:
  the −6° = 360/(z·2) phase rule plus the two-method quantitative mesh check.
- **dfm-rules note:** tooth tip-land is a feature-size to ground-truth from geometry when the render
  is scale-less (here 1.36 mm ≥ 0.5 mm FDM floor).

## 7. Unknowns
- **Why staleness-reuse fired on only 1 of 3 unchanged parts** (pinion reused; gear + shaft
  re-evaluated though also unchanged). Observed, not diagnosed: a reuse-selectivity question for the
  evaluator, not this run.
- Whether the point-sampled sample count (12-14/flank) is optimal or merely sufficient: it shipped;
  it was not swept for a minimum.
```

### Why this example passes the bar

- **§2 is specific, not vague**: each friction names the error class
  (background-dispatch orphan-kill, arc-stitch failure),
  the phase/agent, the workaround, and the cost (~14 min; minor).
  A dev can act on every line.
- **§3 celebrates** the arc-stitch adaptation and the improvised assembly export
  instead of hiding them:
  that is the self-healing principle made visible,
  which is the whole point of the artifact.
- **§4 and §5 are genuinely different.**
  §4 is three shippable-this-week fixes.
  §5 does NOT restate them:
  it names two *paradigms* (reference-as-candidate; runner-vs-harness robustness)
  that would retire whole classes of friction.
  The exporter flag lives in §4;
  the "runner is a different axis" insight lives in §5.
  That separation is the skill working.
- **§7 is honest**: the run flags the reuse-selectivity anomaly
  as *observed, not diagnosed* rather than confabulating a cause.

## Anti-patterns (do not ship a reflection that does these)

- **Empty-ceremony sections**: a heading with nothing under it.
  Either a genuine entry or an honest one-line "empty because …".
- **Vague failures**: "some errors occurred and were resolved."
  Name the error class, the where, the workaround, the cost,
  or do not write the line.
- **§5 restating §4**: strategic that just re-says the tactical fix in bigger words.
  §5 must name the pattern and the paradigm, not the patch.
- **Confessing self-healing**: writing an improvisation apologetically ("had to hack around …").
  It protected the result; write it with pride so the next run can reuse it.
- **Inheriting a predecessor's blind spot silently**:
  a resume session that completes a run
  must fold in the predecessor's `reflection_notes.md`,
  not synthesize only from what its own session saw.
