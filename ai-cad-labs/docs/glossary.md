# Glossary

The domain language of this codebase:
the terms an agent or contributor meets in run artifacts, reports, and instructions,
each with a pointer to the shipped file that owns the mechanics.
Definitions here name concepts; the pointed-at code is the contract.
On any conflict between an entry and the code, the code wins.

Sections:
[Run artifacts](#run-artifacts) ·
[Pipeline and roles](#pipeline-and-roles) ·
[DFMA and the rules lifecycle](#dfma-and-the-rules-lifecycle) ·
[Tools and CLI conventions](#tools-and-cli-conventions) ·
[Rendering and vision](#rendering-and-vision) ·
[Frontend and model](#frontend-and-model)

## Run artifacts

**run-artifact tree**
The self-describing directory a design run writes under `projects/<name>/`:
goals, plan, log, sourcing output, per-part directories,
assembly composition, and terminal telemetry.
The filesystem is the API; every consumer reads it read-only.
Authority: `AGENTS.md`

**goals.md**
The design brief expanded into measurable success criteria,
written when the project is created and before the orchestrator is dispatched,
then read by every downstream role.
Authority: `AGENTS.md`

**design_plan.md**
The planner's decomposition:
parts with Make-vs-Buy classification,
the locked dimension and interface parameter table other artifacts reference,
and build order with `parallel_safe` annotations.
Authority: `.shared/agents/planner/instructions.md`

**design_log.md**
The append-only chronological activity feed for the whole project,
written for future AI readers: state, decisions, outcomes.
One `[agent] message` line per action; unbracketed lines are continuations.
Authority: `.shared/agents/orchestrator/instructions.md`

**constraints.md**
A part's binding spec, written by the planner:
functional requirements, locked dimensions on a parseable `Overall:` line,
features, interfaces, and the manufacturing process from the canonical name list.
Sourcing appends a purchased-part interfaces block.
Authority: `.shared/agents/planner/instructions.md`

**part.py**
The stable, gate-protected CadQuery code for a part.
Fresh designs write it directly;
everything after that writes proposals,
and only the DFM regression gate may replace it.
Authority: `.shared/agents/cad_designer/instructions.md`

**part.proposal.py**
A proposed replacement for `part.py`,
written by repair, redesign, or the assembly resolver,
and judged by the regression gate.
It must never overwrite `part.py` directly.
Authority: `.shared/agents/repair/instructions.md`

**notes.md**
A part's running conversation between agents:
append, never rewrite prior findings.
Its final line is the validation verdict marker,
and repair appends its attempt sections there.
Authority: `.shared/agents/validator/instructions.md`

**VALIDATION marker**
The bare line `VALIDATION: PASSED` or `VALIDATION: FAILED`
that must end a `notes.md`.
The state scanner substring-matches it, checking PASSED before FAILED,
so stale markers are rewritten as superseded and exactly one live marker is allowed.
Authority: `.shared/tools/spec_validator.py`

**attempt_log.json**
Per-part agent attempt history, and the anti-repeat memory that makes escalation smart.
JSONL despite the `.json` extension: one JSON object per line,
with more than one entry shape coexisting in real logs
(designer and resolver entries, orchestrator gate entries, salvage entries).
Authority: `frontend/src/lib/parsers/attemptLog.ts`

**dfma_report.json / dfa_report.json**
The per-part DFM report and its assembly-level DFA counterpart,
written as a side effect of running the evaluator.
The report defines the stable score a repair must not worsen.
Consumers must tolerate partial or absent reports.
Authority: `.shared/tools/dfma_evaluator.py`

**open_issues.md and CONFLICT records**
The project-level conflict ledger.
The assembly resolver files numbered `CONFLICT-NNN` records there
(each paired with a proposal) to hand interface mismatches to the orchestrator;
a `[RESOLVED]` marker on the header flips a record's status.
The file also carries `NEEDS_HUMAN_INPUT` flags.
Authority: `.shared/agents/assembly_resolver/instructions.md`

**checkpoint.md**
The orchestrator's courtesy handover baton for a successor session:
session number, done and pending work, next steps, spawn counts.
Resume is filesystem-only by design and does not require it;
a run can be reconstructed from its files alone.
Authority: `.shared/agents/orchestrator/instructions.md`

**smoke_report.md**
The run's outcome summary:
reviewer verdict, completeness score,
and a what-was-built table with per-part geometry and validation columns.
Authority: `.shared/agents/orchestrator/instructions.md`

**reflection_notes.md**
The crash-safe half of the two-file reflection protocol:
one-liner observations appended the moment something fails or gets improvised around.
Survives any crash;
the salvage source if the run dies before synthesis.
Authority: `.shared/skills/run-reflection/SKILL.md`

**run_reflection.md**
The run's structured self-debrief, synthesized once at terminal state:
YAML front matter plus judgment prose.
Development feedback for the self-improvement loop,
never load-bearing for the run itself.
Authority: `.shared/skills/run-reflection/SKILL.md`

**external/ (bom.md and sourcing_notes.md)**
The sourcing agent's output directory.
`bom.md` is the Bill of Materials for Buy parts,
whose boundary dimensions feed named locked parameters in `design_plan.md`;
`sourcing_notes.md` records confirm-or-flag verdicts on the planner's catalog selections,
verification posture, never re-choosing.
Authority: `.shared/agents/sourcing/instructions.md`

**exports/**
Per-part STEP and STL geometry exports, the manufacturable output.
Written by the exporter tool; not consumed by the frontend.
Authority: `.shared/tools/exporter.py`

## Pipeline and roles

**mortal orchestrator**
The design principle that the orchestrator's lifecycle is
orient, work, checkpoint, end of life:
it ends when goals are met, budget runs out, or a human is needed,
and a successor resumes cold.
Resume reconstructs state from the filesystem alone;
spawn counts are the budget currency.
Authority: `.shared/agents/orchestrator/instructions.md`

**sub-orchestrator**
An orchestrator dispatched recursively on a scoped sub-assembly directory
(two or more parts needing their own design, validate, repair cycle)
with a stated spawn budget.
Its scope's `assembly.py` marks the sub-assembly done.
Authority: `.shared/agents/orchestrator/instructions.md`

**filesystem is the message bus**
The core inter-agent contract:
results travel in project files (verdicts, conflicts, logs),
not in agent summaries.
The files are the contract; the summary is a convenience.
Authority: `.shared/agents/orchestrator/instructions.md`

**knowledge layer**
The `.shared/skills/` tier of the harness:
reusable engineering knowledge (patterns, rulebook mechanics, reflection contracts)
consumed by the agent roles,
distinct from the tools layer (deterministic Python)
and the agents layer (role instructions).
Authority: `AGENTS.md`

**anti-hallucination catalog**
The curated table of CadQuery methods that do not exist
(commonly invented by language models)
paired with the correct real API for each.
Authority: `.shared/skills/cadquery-anti-hallucination/SKILL.md`

**API_SURFACE existence rule**
The definitive CadQuery method whitelist and its contract:
if a method is not listed there, it does not exist.
The final arbiter for whether generated code calls real API,
a negative existence claim code itself cannot make.
Authority: `reference/API_SURFACE.md`

**direct-Location assembly**
The production assembly method:
parts and sub-assemblies positioned with explicit `cq.Location` vectors,
loaded by executing `part.py` and `assembly.py` files under `__project_path__`.
The sanctioned alternative to constraint-solver approaches, which are banned.
Authority: `.shared/skills/cadquery-cookbook/SKILL.md`

**Principle 0 (coordinate convention)**
The mandatory part-origin convention:
revolved parts put their axis of revolution on Z through the origin;
prismatic parts center on XY with the bottom at Z=0;
primary bores align to the Z origin.
Assembly placement then reduces to a direct `cq.Location` offset.
Authority: `.shared/skills/cadquery-cookbook/SKILL.md`

**parallel_safe**
Per-part boolean annotation in `design_plan.md`:
true means dimensions are fully self-defined and the part can be designed concurrently;
false means an interface depends on another part being designed first,
so false parts are designed sequentially before true parts parallelize.
Authority: `.shared/agents/planner/instructions.md`

**Make vs Buy**
The planner's part classification.
Make parts get full per-part directories and design cycles;
Buy parts are catalog components specified in `external/bom.md`,
represented in the assembly as inline geometry with no part directory of their own.
Authority: `.shared/agents/planner/instructions.md`

**escalation ladder**
The attempt-count discipline for stuck parts:
consecutive gate rejections or repeated repair iterations escalate to a full redesign
(still written as a proposal);
if the redesign is also rejected, the stable part is accepted and the run moves on.
Authority: `.shared/agents/orchestrator/instructions.md`

**ORCHESTRATOR NOTE**
The strategic-context block the orchestrator composes into repair and redesign task strings:
attempt number, why prior approaches failed, a suggested different approach,
and danger constraints.
Repair treats it as a hard avoid-list;
nothing is auto-injected in this harness.
Authority: `.shared/agents/orchestrator/instructions.md`

**reviewer verdicts**
The four recommendations a review returns:
`ship` (complete, including assembly renders),
`continue` (converging),
`pause_for_human` (deadlock or ambiguity),
`restart_part` (a named part is stalled or diverging).
Authority: `.shared/agents/reviewer/instructions.md`

**UNVERIFIED: needs catalog lookup**
The sourcing honesty marker for any BOM row
whose spec cannot be grounded in the built-in standard-part table.
An honest UNVERIFIED row is actionable;
a fabricated part number poisons downstream parts.
Authority: `.shared/agents/sourcing/instructions.md`

**self-healing principle**
The harness convention for failure:
protect the end result, break conventions if needed, get the job done,
and catalog the improvisation so future agents get smarter for it.
Improvisations are celebrated, not confessed.
Authority: `.shared/skills/run-reflection/SKILL.md`

**ownership closure (reflection)**
The no-fall-through writer contract:
whoever writes `smoke_report.md` synthesizes `run_reflection.md` in the same sitting,
and anyone reaching terminal state without a reflection writes it themselves,
checking first that a conforming one does not already exist.
Authority: `.shared/skills/run-reflection/SKILL.md`

## DFMA and the rules lifecycle

**DFMA (DFM / DFA)**
Design-for-Manufacturing (per-part rules, `rules/dfm_rules.json`)
plus Design-for-Assembly (assembly-level rules, `rules/dfa_rules.json`),
framed as a unit-test suite for parts.
Evaluated by a vision model against rendered engineering views.
Authority: `.shared/skills/dfm-rules/SKILL.md`

**severity / severity-weighted score**
Severity is a rule's importance class: `critical`, `major`, or `minor`.
The severity-weighted score is a part's manufacturability score:
each failed rule contributes a weight by severity, summed.
It is the regression gate's comparison metric;
the weighting prevents trading a minor failure for a critical one.
Authority: `.shared/tools/dfma_evaluator.py`

**regression gate (--judge-proposal)**
The promotion mechanism:
`part.py` (stable) and `part.proposal.py` are both evaluated fresh,
and the proposal is `promoted` only if it does not worsen the severity-weighted score,
else `rejected` with the stable code and reports restored.
The return carries traceability fields
(`regression_delta`, plus `rule_diff` naming new and fixed failures).
Authority: `.shared/tools/dfma_evaluator.py`

**verdict (per rule)**
The evaluation outcome for one rule: `pass`, `fail`, or `uncertain`.
`uncertain` is mandated when the renders do not show enough to judge;
the prompt forbids passing a rule just because a problem is not clearly visible.
An `uncertain` finding is resolved by ground-truthing against the source geometry
(deterministic checks, measurements, additional views),
never by treating it as a failure or repairing the part on the strength of it.
Authority: `.shared/tools/_dfma_models.py`

**overall_verdict**
The pass-level verdict: `pass`, `conditional_pass`, or `fail`,
derived deterministically from active-tier results only
(critical failures force a fail;
lesser failures or uncertainty give a conditional pass).
Deterministic derivation exists to remove the vision model's verdict-vocabulary variance.
Authority: `.shared/tools/dfma_evaluator.py`

**tier (rule lifecycle)**
A rule's lifecycle state:
`active` (curated, counts toward verdicts),
`probationary` (unvetted, warn-only: its failures land in warnings, never sway the gate,
and are exercised only when a sweep opts in with `--include-probationary`),
or `retired` (tombstone, never loaded).
A retired proposal is moved into the main rulebook with `tier: retired`
and a retirement reason prefixed to its description,
keeping full provenance in the canonical file.
Authority: `.shared/tools/dfma_evaluator.py`

**rule proposal**
A candidate new rule.
The evaluating model may emit proposals during any evaluation
(the report's `proposed_rules` field),
and agents may submit one via `--propose-rule`;
either way it lands as probationary in the `.proposed.json` sibling
of the target rulebook, never auto-activating into the curated set.
Authority: `.shared/tools/dfma_evaluator.py`

**triage (--triage-proposals)**
The deterministic pass that drains staged proposals:
each is recommended for promotion, retirement, or keeping,
based on evidence thresholds and policy checks,
with machine-readable `criteria_hits` naming which gate fired.
Each non-dry run appends a `triage_run` summary record to the lifecycle log.
Authority: `.shared/tools/dfma_evaluator.py`

**AI arbiter**
The judgment layer above deterministic triage:
an agent reviews the dry-run recommendations,
trusts the clear cases,
applies judgment to KEEP-flagged proposals,
and actuates via `--promote-rule` and `--retire-rule`.
Human review is deferred to the lifecycle log, not deleted.
Authority: `.shared/agents/dfma_inspector/instructions.md`

**rule_lifecycle_log.json**
The append-only audit trail of every promote, retire, and triage decision:
decision, tiers, rationale, criteria hits, evidence, actor, timestamp.
The record a human reads later and reverses via git if needed.
Authority: `.shared/tools/dfma_evaluator.py`

**rule identity (rule_id, rule_type, timestamp)**
How lifecycle records are disambiguated:
a `rule_id` alone is not unique across the log,
since the same rule can appear in multiple decisions
and DFM and DFA rules are separate namespaces.
The (`rule_id`, `rule_type`, `timestamp`) triple identifies one decision record.
Authority: `.shared/tools/dfma_evaluator.py`

**evidence counters**
Per-rule counters: `times_applied` auto-increments on every evaluation touching the rule;
`true_positives` and `false_positives` are not auto-updated,
they require external validation.
Triage's evidence thresholds read these counters.
Authority: `.shared/tools/dfma_evaluator.py`

**rule fields (look_for / pass_criteria / fail_criteria / fix_hint)**
The vision-prompt fields of every rule:
what to inspect in the renders and the observable pass and fail conditions,
phrased for a model looking at images, not for geometric computation.
`fix_hint` is optional CadQuery-specific repair guidance,
consumed verbatim by the repair agent.
Authority: `.shared/skills/dfm-rules/SKILL.md`

**manufacturing scope**
A rule's `manufacturing` field lists the processes it applies to;
an empty list makes it a general rule applied to every part.
Scope is normalized at promotion time,
because an accidentally empty list silently globalizes a process-specific rule.
Authority: `.shared/tools/dfma_evaluator.py`

**canonical process id**
The normalized manufacturing-process vocabulary
(`CNC_milling`, `CNC_turning`, `injection_molding`, `sheet_metal`, `3D_printing`, `casting`),
matched by keyword aliases against the `## Manufacturing` section of a part's `constraints.md`.
Authority: `.shared/tools/spec_validator.py`

**fillet deferral policy**
The standing project rule: no fillets in new designs,
since they are the top CadQuery failure source; correct geometry first.
Consequently triage auto-retires fillet, chamfer, and sharp-corner proposals,
unless the remedy is structural (ribs, gussets, clearance),
which are kept for the arbiter.
Authority: `.shared/skills/dfm-rules/SKILL.md`

**stamped report / staleness reuse**
Every evaluation report is stamped with a hash of the ruleset actually used.
A report is fresh, and reused with zero model calls,
only if it parses, carries the current ruleset hash,
and is newer than the code file and every render;
reuse increases verdict consistency, and `--force` overrides it.
A tier flip changes the hash, so stale reports recompute on the next evaluation.
Authority: `.shared/tools/dfma_evaluator.py`

**sweep (parallel volley)**
`--mode=sweep`: one concurrent evaluation of every part's DFM plus the assembly's DFA,
reusing still-fresh reports at zero cost.
Reuse counts are machine-observable in the return by design.
The inspector's primary call; never loop over parts serially.
Authority: `.shared/tools/dfma_evaluator.py`

## Tools and CLI conventions

**tool-ran exit contract**
The uniform CLI convention across `.shared/tools/`:
exit 0 means the tool ran successfully even when the evaluated artifact failed,
with the JSON on stdout carrying the verdict.
Nonzero exits are reserved for tool malfunction (1) and usage or path errors (2);
error messages are never truncated.
Authority: `.shared/tools/cadquery_executor.py`

**result variable convention**
Executed CAD scripts communicate their output
by assigning the final shape to a variable named `result`,
with discovery falling back to the last `cq.Workplane` bound in the namespace.
"Executed successfully but produced no Workplane" means the assignment was forgotten.
Authority: `.shared/tools/cadquery_executor.py`

**__project_path__**
A resolved path injected into the execution namespace
when a project root is known or derivable,
so assembly code can locate sibling `part.py` files.
Hardcoded absolute paths are banned.
Authority: `.shared/tools/cadquery_executor.py`

**subprocess mode**
`cadquery_executor --subprocess`: runs the code in an isolated process
so a CAD-kernel segfault kills only the child.
The solid crosses the process boundary as a STEP file,
costing some time and losing the original result type.
Authority: `.shared/tools/cadquery_executor.py`

**HINT enrichment**
Corrective text appended to a failed execution's error message
when the error matches a known hallucination pattern,
naming the correct real API to use instead.
Agents seeing `HINT:` must follow it; it exists to break the hallucination loop.
Authority: `.shared/tools/cadquery_executor.py`

**safe_path (traversal guard)**
The path-resolution helper preventing directory-escape paths
from leaving a project or invocation root.
It is defined in `cadquery_executor`, `spec_validator`, and `placeholder_detector`,
and reused by `exporter`, which imports the executor's copy.
Authority: `.shared/tools/cadquery_executor.py`

**placeholder (part stub)**
A `part.py` flagged as not a real design by ordered checks:
too few substantive code lines, the default scaffold geometry, or placeholder markers.
The validator runs this gate before spending a render and vision cycle.
Authority: `.shared/tools/placeholder_detector.py`

**dimension check**
Deterministic verification comparing a part's sorted bounding-box dimensions
against the sorted `Overall:` expectation, within a 15 percent tolerance;
sorting handles axis ambiguity, and cylindrical two-dimension specs
skip the duplicate diameter axis.
The `pass` field is tri-state: true, false, or null (not evaluable).
Authority: `.shared/tools/dimension_checker.py`

**project state scan**
`spec_validator --query=state`: the read-only project inventory.
A directory is a part if it contains `part.py` or `constraints.md`;
a directory whose subdirectories contain parts is a sub-assembly.
Per-part `code_executes` stays null (untested) by design,
since only the executor establishes true or false,
and repair iterations are counted from `design_log.md` repair lines.
Authority: `.shared/tools/spec_validator.py`

**pending_proposal**
A validation-status override in the state scan:
when `part.proposal.py` exists in a part directory,
the part's status becomes `pending_proposal`
regardless of `notes.md` markers, because a gate decision is outstanding.
Authority: `.shared/tools/spec_validator.py`

**CAD_EVALUATOR_* environment knobs**
The evaluator's three env variables:
`CAD_EVALUATOR_MODEL` (model pin for the claude CLI; unset means the CLI's default),
`CAD_EVALUATOR_TIMEOUT_S` (inner-call timeout, default 300),
and `CAD_EVALUATOR_CONCURRENCY` (sweep concurrency cap, default 4).
Authority: `.shared/tools/dfma_evaluator.py`

## Rendering and vision

**standard render set**
The fixed set of engineering views every render pass emits per subject:
four viewpoints (front, top, right, iso) in two styles each,
always individual PNG files, never composites.
These are the images the vision evaluator judges.
Authority: `.shared/tools/renderer.py`

**wireframe vs clean styles**
The two render styles:
wireframe is an X-ray showing all edges including hidden ones;
clean shows only visible edges and reads more solid.
The exporter draws edges only, so clean is the closest to a solid appearance.
Authority: `.shared/tools/renderer.py`

**bbox markers**
Tiny reference cubes placed at the assembly bounding-box corners
before per-part rendering,
forcing the auto-fit to use the full assembly envelope for every part
so per-part views overlay at a common scale in colored assembly renders.
Authority: `.shared/tools/renderer.py`

**color legend**
The part-name to stroke-color mapping for colored assembly renders,
written both into the JSON output and to `assembly/renders/color_legend.txt`.
The RGB triple is authoritative; the color name is approximate.
Authority: `.shared/tools/renderer.py`

**--code-file override (proposal rendering)**
The renderer flag redirecting which script executes
(for example `part.proposal.py` instead of `part.py`)
while all outputs stay anchored to `--part-path`.
The mechanism that lets repair proposals be rendered without touching the stable part.
Authority: `.shared/tools/renderer.py`

**vision-based stochastic evaluation**
DFMA verdicts come from a model inspecting renders,
so the same part may score slightly differently across runs.
Severity weighting and report reuse mitigate but do not eliminate the variance;
this is why internally inconsistent rejections warrant one re-run.
Authority: `AGENTS.md`

## Frontend and model

**the filesystem is the API**
The frontend's founding invariant:
a read-only localhost window over `projects/`
that never imports harness code and never writes.
The Vite middleware is the only bridge,
path-traversal guarded to the projects root.
Authority: `frontend/plugins/projects-api.ts`

**project manifest (manifest-gated fetch)**
A per-project file-existence map served to the client,
so it fetches only artifact files that exist instead of probing for them.
Mid-run trees render calmly with whatever exists.
Authority: `frontend/plugins/projects-api.ts`

**terminal run**
A run is terminal when a `checkpoint.md` or `smoke_report.md` marker exists
and the design log's last agent line says the session ended.
A mid-run checkpoint alone is not terminal, since sessions resume from it.
Authority: `frontend/plugins/projects-api.ts`

**isActive**
The run liveness signal:
not terminal, and the newest modification time anywhere in the project tree
falls within the active window.
Authority: `frontend/plugins/projects-api.ts`

**activity lanes and spans**
The dashboard's per-agent timeline:
lanes of approximate time spans built from attempt timestamps and artifact
modification times, with all spans marked approximate by design.
Untimed log lines keep ordinal order at the tail.
Authority: `frontend/plugins/projects-api.ts`

**ValidationStatus**
The frontend's parsed verdict vocabulary: `passed`, `failed`, or `pending`,
extracted from a `notes.md` final `VALIDATION:` line;
absence of the line means `pending`.
Authority: `frontend/src/lib/parsers/notes.ts`
