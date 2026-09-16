> Generated from the `tools/dfma_evaluator.py` docstrings, never hand-edited.
> Regenerate with `uv run --frozen python tests/test_api_docs.py --write`.
<a id="tools.dfma_evaluator"></a>

# tools.dfma\_evaluator

DFMA evaluator: bash-callable Design for Manufacturing / Assembly evaluation.

Self-contained evaluation unit: loads + filters rules from rules/*.json, reads the
8 render PNGs, builds an adversarial Critical-Think prompt, and makes an independent
LLM call through the `claude` CLI (schema-validated against DFMAEvaluation).

JSON contract: single machine-parseable object to STDOUT; human detail to STDERR.
Exit 0 = tool ran (even when the evaluated artifact fails checks, or a precondition
like missing renders is unmet; the JSON carries success/verdict). Exit 1 = tool
malfunction (unhandled crash; the JSON "error" carries the FULL traceback, error
messages are never truncated).

Evaluation authority (implemented 2026-07-13):
single-pass default · staleness reuse (ruleset-hash + mtime; --force overrides) ·
--mode=sweep parallel volley · probationary-rule governor (--include-probationary).

Modes:

```
--mode=dfm --part-path <dir> [--dual-pass] [--force] [--include-probationary]
    DFM evaluation of <dir>/part.py renders. Default: ONE single-pass call over the
    full applicable rulebook. Reuses a fresh stamped dfma_report.json without any
    LLM call. --dual-pass = legacy two-call re-check:
    Pass 1: rules filtered by the manufacturing process parsed from constraints.md,
            manufacturing-technique framing.
    Pass 2: engineering-domain framing, runs ONLY if Pass 1 had no critical failure
            (active-tier, severity=critical, verdict=fail); sees Pass 1 findings.
    Merge: stricter verdict per rule wins. Writes <dir>/dfma_report.json (stamped
    with _meta.ruleset_hash for the staleness cache).

--mode=sweep --project <dir> [--force] [--include-probationary]
    PARALLEL VOLLEY: every part's DFM + the assembly's DFA concurrently
    (CAD_EVALUATOR_CONCURRENCY, default 4). Fresh reports are reused at zero cost:
    the routine post-validation sweep approaches a no-op.
    Output: {success, part_path, manufacturing_process, rules_evaluated, rules_passed,
             rules_failed, rules_uncertain, overall_verdict, pass2_skipped, failures[],
             warnings[], proposed_rules_count, report_path}

--mode=dfa --asm-path <dir>
    Single-pass DFA evaluation (global assembly rules, no process filtering, legacy
    parity). Writes <dir>/dfa_report.json. Output mirrors dfm (assembly_path key).

--propose-rule '<json>' [--rule-type dfm|dfa]
    Append a rule to rules/<type>_rules.proposed.json, forced tier=probationary,
    counters reset. rule-type may instead be a "rule_type" key in the JSON payload.
    Output: {success, rule_id, tier, file, message}

--judge-proposal --part-path <dir>
    Arithmetic DFM regression gate. The proposal side is always evaluated fresh;
    the stable side may reuse a fresh stamped dfma_report.json, else it too is
    evaluated fresh (score = sum of severity weights over failed rules:
    critical=10, major=5,
    minor=1). proposal_score <= stable_score -> PROMOTE (proposal replaces part.py);
    else REJECT (proposal deleted, stable + renders + report restored from backup).
    Output: {success, verdict, stable_score, proposal_score, regression_delta,
             rule_diff: {new_failures, fixed_failures}, ...traceability}
```

Inner engine: evaluations run on **Claude via the
`claude` CLI** (headless `-p`, Read-only tools; Claude reads the render PNGs from disk
and returns schema-validated JSON; typing still enforced by DFMAEvaluation). Model:
env CAD_EVALUATOR_MODEL if set, else the CLI's configured default. Timeout: env
CAD_EVALUATOR_TIMEOUT_S (default 300). The legacy 8192-token output ceiling is GONE
in this path.

<a id="tools.dfma_evaluator.evaluate_dfm"></a>

#### evaluate\_dfm

```python
async def evaluate_dfm(part_dir: Path,
                       part_path: str,
                       *,
                       dual_pass: bool = False,
                       include_probationary: bool = False,
                       force: bool = False) -> dict
```

DFM evaluation of the part at part_dir (evaluation authority).

Default = SINGLE-PASS over the full applicable rulebook (the Claude CLI engine
has no output ceiling; dual_pass=True preserves the legacy two-call re-check).
Staleness reuse: if a stamped dfma_report.json is newer than part.py + renders
and carries the current ruleset hash, it is RETURNED WITHOUT an LLM call
(force=True overrides). The gate inherits this automatically for the stable side.

<a id="tools.dfma_evaluator.evaluate_dfa"></a>

#### evaluate\_dfa

```python
async def evaluate_dfa(asm_dir: Path,
                       assembly_path: str,
                       *,
                       include_probationary: bool = False,
                       force: bool = False) -> dict
```

Single-pass DFA evaluation of the assembly at asm_dir (staleness-reusing).

<a id="tools.dfma_evaluator.propose_rule"></a>

#### propose\_rule

```python
def propose_rule(rule_type: str, rule_json: str) -> dict
```

Append a proposed rule to rules/&lt;type&gt;_rules.proposed.json as probationary.

<a id="tools.dfma_evaluator.promote_rule"></a>

#### promote\_rule

```python
def promote_rule(rule_id: str,
                 rule_type: str | None = None,
                 *,
                 confidence: float | None = None,
                 actor: str = "manual(--promote-rule)",
                 rationale: str | None = None,
                 criteria_hits: list | None = None) -> dict
```

Promote a probationary proposed rule into the active rule set (moves proposed→active).

Normalizes the manufacturing scope (else a manufacturing:[] rule becomes a GLOBAL rule),
sets tier=active, bumps confidence to &gt;=0.75, and logs the decision. Idempotent-safe:
unknown id or already-active → structured error, no partial write. The tier flip changes
the ruleset hash → stale stamped reports auto-recompute on next eval.

<a id="tools.dfma_evaluator.retire_rule"></a>

#### retire\_rule

```python
def retire_rule(rule_id: str,
                rule_type: str | None = None,
                *,
                reason: str = "",
                actor: str = "manual(--retire-rule)",
                rationale: str | None = None,
                criteria_hits: list | None = None) -> dict
```

Retire a rule (proposed OR active) → tier=retired tombstone in the active file.

A PROPOSED rule is MOVED proposed→active-file as retired (drains the pile, keeps a
tombstone with full provenance). An ACTIVE rule is flipped in place. Logs the decision.
Unknown id or already-retired → structured error.

<a id="tools.dfma_evaluator.triage_proposals"></a>

#### triage\_proposals

```python
def triage_proposals(dry_run: bool = False) -> dict
```

Recommend (and, unless dry_run, auto-apply the clear-cut) promote/retire decisions
for every probationary proposal. KEEP-flagged proposals stay probationary for the AI
arbiter. Every applied decision is logged to the audit trail. §5 Layer 2.

<a id="tools.dfma_evaluator.judge_proposal"></a>

#### judge\_proposal

```python
async def judge_proposal(part_dir: Path, part_path: str) -> dict
```

Compare part.proposal.py against stable part.py using DFM evaluations.

The "DFMA as unit test" gate. The proposal side is always evaluated fresh
(the code swap and re-render invalidate any cached report); the stable side
may reuse a fresh stamped dfma_report.json via evaluate_dfm's staleness cache,
else it is evaluated fresh. Either way the stable score comes from a real
evaluation (deviation from legacy, per translation contract: legacy read the
stable score from a cached dfma_report.json and scored an absent report as
0 failures). Severity-weighted scoring; promote iff proposal_score &lt;= stable_score. All file operations are
backed by on-disk backups (part.py, renders/, dfma_report.json) so a crash or
rejection restores the stable state exactly.

<a id="tools.dfma_evaluator.evaluate_sweep"></a>

#### evaluate\_sweep

```python
async def evaluate_sweep(project_dir: Path,
                         *,
                         include_probationary: bool = False,
                         force: bool = False) -> dict
```

PARALLEL VOLLEY: evaluate every part (DFM) + the assembly (DFA) concurrently.

Concurrency capped by env CAD_EVALUATOR_CONCURRENCY (default 4). With staleness
reuse on (default), parts whose stamped reports are fresh cost ZERO LLM calls;
a routine sweep after per-part validation approaches a no-op; only stale or
never-evaluated targets spend inner calls. One tool invocation replaces the
inspector's serial per-part loop entirely.

<a id="tools.dfma_evaluator.main"></a>

#### main

```python
def main(argv: list[str] | None = None) -> int
```

CLI entry point: dispatch per the mode flags in the module docstring.

