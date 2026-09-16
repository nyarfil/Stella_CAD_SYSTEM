# 0006. Regression-gated repair

Status: Accepted (2026-07)

## Context

Validated geometry is the system's most expensive asset.
Repair and redesign agents are stochastic,
and the vision-based DFM evaluation that judges their output
varies from run to run.
An agent that can overwrite a working part directly
can destroy validated work on one bad attempt,
with no rollback.
Stochastic evaluation therefore has to terminate
in a deterministic decision rule,
or verdict vocabulary drifts and good work gets discarded.

## Decision

Repair and redesign agents write `part.proposal.py`
and never overwrite `part.py`.
Only the DFM regression gate swaps files:
it scores stable and proposal with severity-weighted arithmetic
and promotes only when the proposal scores no worse than the stable part.
The gate is arithmetic, not judgment.
Its exact scoring contract lives in the
`.shared/tools/dfma_evaluator.py` module docstring,
and the surrounding protocol
(escalation ladder, and a one-time gate re-run
when a rejection is internally inconsistent)
lives in `.shared/agents/orchestrator/instructions.md`.
Escalation counts attempts, never tokens:
repeated failed repairs or consecutive gate rejections
escalate to a full redesign,
and if even the redesign is rejected,
the stable part is kept and the run moves on.

## Alternatives considered

- **In-place repair.**
  Destroys validated geometry on a bad repair, with no rollback.
- **LLM-judged promotion.**
  Adds stochasticity exactly where determinism is needed.
  A production run demonstrated the failure class:
  the gate once rejected a good proposal
  purely on run-to-run vision variance,
  and a re-run promoted it.
  That incident is why the re-run rule exists.
- **Token-budget escalation.**
  The predecessor PydanticAI implementation escalated on token spend;
  this harness exposes no per-part token counter,
  so attempt counts became the escalation proxy.

## Consequences

- Every repair is reversible:
  the stable part is untouched until the gate passes,
  and a rejected proposal leaves the validated state intact.
- Promotion is auditable:
  the gate verdict is a JSON artifact
  recorded in the part's attempt log.
- The self-healing path from conflict to proposal to gate to promotion
  fired end-to-end on the first harness run,
  a path the predecessor implementation never exercised.
- Gate evaluations of the stable side reuse fresh cached reports,
  which removes most of the stochastic-rejection variance
  the re-run rule was added for.
- A naming trap is worth knowing:
  the gate's judge-proposal mode promotes a repaired part,
  not a rule;
  rule promotion is a separate lifecycle (ADR 0007).
