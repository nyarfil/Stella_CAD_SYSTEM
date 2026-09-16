# 0009. Evaluation authority: staleness caching and a deterministic verdict

Status: Accepted (2026-07)

## Context

Geometry evaluation is deterministic input passed through a stochastic function.
As originally built, the system re-evaluated the same unchanged part
at multiple call sites in one session
(validation, the regression gate's stable side, the project sweep),
so most evaluator wall-time went to redundant re-evaluation,
and every redundant call was a fresh roll of the dice.
The variance was not hypothetical:
in one production incident the regression gate rejected a good proposal
purely on run-to-run scoring variance,
and the same shape received different headline verdicts on different runs
because the inner model's verdict vocabulary drifts.

## Decision

DFMA evaluation is governed by one authority with five coupled rules,
implemented in `.shared/tools/dfma_evaluator.py`:

1. Staleness-cached reuse.
   Every report is stamped with a ruleset identity hash
   and reused, without any LLM call,
   when the report is newer than the geometry file and its renders
   and the hash matches (`--force` overrides).
   The regression gate's stable side reads the cached report
   instead of re-evaluating.
2. Single-pass by default;
   `--dual-pass` is demoted to an explicit re-check.
3. `--mode=sweep` evaluates all parts plus the assembly
   as one concurrent volley.
4. Probationary rules join only explicit `--include-probationary` audits,
   making rule staging a curated, batched event
   instead of continuous prompt inflation.
5. The report's overall verdict is derived deterministically,
   after schema validation, from active-tier results only,
   overwriting the inner model's stochastic verdict in every path.
   The derivation guarantees that no flagged or unsure active result
   can silently pass; the exact mapping lives with the code.

## Alternatives considered

- Always evaluate fresh (the as-built state).
  Rejected: re-evaluating unchanged geometry does not refresh truth,
  it injects variance; reuse increases verdict consistency
  while removing the redundant latency.
- Dual-pass evaluation as the default.
  Rejected: a full extra call per evaluation
  whose contribution could not be measured,
  because merged reports kept no per-rule provenance.
- One mega-call per project.
  Rejected: the output exceeds a single completion,
  the retry blast radius becomes the whole project,
  and per-part reports are lost.
- Trusting the inner model's overall verdict.
  Rejected: the stochastic vocabulary noise documented above.
- Replacing the inner call with a native subagent inspector.
  Considered and not adopted; the CLI engine (ADR 0008) stands.

## Consequences

- Routine post-validation sweeps approach a no-op
  when fresh reports exist for every part.
- The identity hash deliberately excludes volatile counters,
  so the counter update after every evaluation
  does not invalidate every cache immediately.
- A rule promotion flips the tier inside the hash,
  so stale reports recompute automatically after ruleset changes
  (see ADR 0007).
- Overwriting the model's verdict is safe for control flow
  because the orchestrator's repair loop keys off
  the validator's written markers, not this headline field.
- Reuse decisions must be confirmed from the report files themselves
  (stamps and timestamps), not from log greps, which undercount.
