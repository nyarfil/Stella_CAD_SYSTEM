# 0010. Vision-based DFMA evaluation with analytical backstops

Status: Accepted

## Context

The system must judge manufacturability (DFM) and assembly quality (DFA)
of arbitrary generated geometry.
Two broad approaches exist:
deterministic geometry analysis
(code that extracts features from the solid and measures them against rules),
or vision:
an LLM judging rendered engineering views against the rulebook.
Deterministic feature extraction is brittle on curved and complex geometry
and cannot judge qualitative manufacturability concerns.
Vision generalizes across geometry classes no rule-coded analyzer anticipates,
but it has structural failure classes of its own:
it cannot measure from scale-less 2D renders,
wireframe views breed false positives,
and it miscounts features.

## Decision

DFMA evaluation is vision-based:
the evaluator judges each part's standard render package against the rulebook
(`.shared/tools/dfma_evaluator.py`).
Honesty conventions are part of the contract:

- The verdict vocabulary includes `uncertain` as a first-class outcome.
  When the images do not provide enough information to evaluate a rule,
  the evaluator marks it `uncertain` rather than `fail`,
  and the finding is resolved by ground-truthing against the source geometry.
- Validators describe what they see before comparing it to expectations
  (`.shared/agents/validator/instructions.md`).

Deterministic analytical checks backstop vision rather than replace it:
dimensional verification against each part's constraints envelope
(`.shared/tools/dimension_checker.py`, also run as part of rendering)
ships as agent-invokable tooling that agents choose to apply.
The explicit ruling rejects building a deterministic
feature-extraction scaffold in front of the evaluator.

## Alternatives considered

- Pure deterministic geometry analysis.
  Rejected: brittle on curved and complex geometry,
  and unable to judge qualitative manufacturability.
- Prescriptive feature-extraction pipelines feeding the vision evaluator.
  Rejected in favor of analytical tools the agents invoke on judgment.
- Trusting vision for countable and metrical questions.
  Disproven in practice:
  vision miscounts features and cannot measure scale-less renders,
  so countable and measurable facts are derived analytically
  and handed to the vision pass as givens.

## Consequences

- `uncertain` is load-bearing:
  a rule that cannot be judged from renders resolves by ground-truthing
  instead of false-failing validated geometry.
- Wireframe false positives are a named failure class;
  agent instructions require ground-truthing against analytics
  and multiple views before repairing
  (see the hardening notes in [`AGENTS.md`](../../AGENTS.md)).
- The generalization payoff is the point:
  new geometry classes are evaluated without writing new analyzers,
  at the cost of policing vision's known limits through conventions and backstops.
