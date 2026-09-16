# 0007. Central rules lifecycle

Status: Accepted (2026-07)

## Context

The DFM/DFA rulebook is the system's compounding asset:
an accumulating, evidence-tracked knowledge base that every future run inherits.
Two failure modes threatened it.
First, fragmentation:
if rule proposals landed wherever a run happened to execute,
multi-project usage would grow per-project rule silos.
Second, stagnation:
proposals staged as probationary rules with no graduation path,
so the proposal file only ever grew.
Auto-promotion on evidence counters alone was not viable either:
a schema bug had let rules with an empty manufacturing scope
fire on every part of every process, inflating their apply counts,
while probationary rules accrue evidence only during explicit audits,
deflating theirs.

## Decision

One central ruleset, governed by an explicit lifecycle.

Rule proposals from any run, in any project directory,
write to the repo-level `rules/*.proposed.json` files.
The write path is anchored to the tool module's own location,
never the current working directory,
so no launch location can fork the ruleset.

Rules move through propose, probationary, and then active or retired states.
Proposals stage as probationary:
warn-only, and excluded from gate scoring and routine evaluation.
A deterministic recommender (`--triage-proposals`, with a `--dry-run` mode)
settles the clear cases with hard quality gates first
(policy conflicts, duplicates, out-of-scope rules)
and an evidence floor for auto-promotion;
the middle band is reserved for the dfma_inspector agent as AI arbiter,
which actuates through `--promote-rule` and `--retire-rule`.
Promotion normalizes the rule's manufacturing scope,
raises its confidence to the active floor,
and appends the decision, actor, rationale, and evidence
to `rules/rule_lifecycle_log.json`.
Human review is deferred, not deleted:
the append-only log is the review queue,
and every transition is reversible through git.
The rule tier is part of the ruleset identity hash,
so a promotion automatically invalidates stale cached evaluation reports
(see ADR 0009).
The mechanics live in `.shared/tools/dfma_evaluator.py`.

## Alternatives considered

- Per-project rulesets.
  Rejected: rules learned on one project would never benefit the next,
  and cross-project accumulation is the rule system's whole value.
- A current-working-directory-relative rules path.
  Rejected: it silently forks the ruleset depending on where a run launches.
- Pure numeric-threshold auto-promotion.
  Rejected: the evidence counters were both inflated and throttled,
  so volume alone could not be trusted to decide.
- Mandatory human review of every rule transition.
  Rejected: it stalls the pipeline;
  the append-only log plus git reversibility preserves oversight.
- Leaving proposals to accumulate indefinitely.
  Rejected: this was the observed failure state the lifecycle replaced.

## Consequences

- Quality gates decide regardless of corrupt counters;
  evidence volume gates only the auto-promotion path.
- The central-write invariant must be guarded in any refactor
  that re-anchors the tools tree or copies tools per project:
  a physically copied tools tree would re-anchor to itself
  and silently fork the ruleset.
- Promotion-time scope normalization is load-bearing:
  without it, a promoted rule with an empty manufacturing scope
  becomes a global rule.
- Retired rules are tombstones, not deletions;
  the retired fillet-class rules are revisitable
  if the fillet deferral is lifted (see ADR 0014).
- Apply counters are not yet wired to validator ground truth,
  so triage weighs rule quality over evidence volume by design.
