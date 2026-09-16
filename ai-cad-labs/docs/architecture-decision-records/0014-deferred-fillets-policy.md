# 0014. Deferred fillets policy

Status: Accepted

## Context

Fillets and chamfers are the lowest-value, highest-fragility geometry class
for an autonomous first-pass design system:
edge cosmetics contribute little to whether a part functions,
while filleting is numerically fragile in generated CadQuery code
and a frequent source of execution failures.

An instruction-only ban proved insufficient on its own.
The evaluation layer kept proposing new fillet-class DFM rules,
which would have reintroduced the deliberately retired constraints
through the rules lifecycle's back door.
The policy therefore needed enforcement at the rules layer as well.

## Decision

Fillets and chamfers are deferred system-wide as a standing policy:

- Code-writing agents are instructed to omit them
  (fillets are deferred project-wide to a later optimization phase).
- The fillet-class DFM rules are retired in place:
  they stay in the ruleset at the retired tier,
  tombstoned with a "fillets deferred" marker,
  rather than being deleted.
- Deterministic rule triage treats any proposed rule
  that conflicts with the fillet-deferral policy
  as a hard retire, regardless of accumulated evidence,
  with a retirement reason that says to revisit when fillets are un-deferred.

**The un-defer trigger** is a deliberate policy reversal:
a dedicated edge-finishing phase that consciously lifts the deferral.
No amount of rule evidence can un-defer fillets through triage.

**Rule-tombstone inheritance**: when that reversal happens,
the tombstoned retired rules are the inheritance package.
The future fillet phase re-activates preserved rules
instead of rediscovering them from scratch.

## Alternatives considered

- **Allow fillets and keep the fillet rules active.**
  Rejected: it reintroduces a fragile operation class into every repair loop,
  and the fillet rule family repeatedly re-proposes itself,
  pulling attention toward cosmetics and away from function.
- **Delete the fillet rules outright.**
  Rejected: deletion loses the accumulated rule knowledge
  that the future edge-finishing phase will need.
  Retire-as-tombstone preserves it.

## Consequences

- Runs deliberately leave chamfer-class findings unrepaired,
  with the rationale documented in the project's open issues
  rather than reported as fixed.
- Triage must distinguish a genuine fillet-policy conflict
  from a fillet-adjacent rule whose real remedy is structural
  (ribs, gussets, clearance):
  those are reserved for AI adjudication, never auto-retired.
- The policy lives in two layers at once:
  the agent instructions (see `.shared/agents/cad_designer/instructions.md`)
  and the rules lifecycle tooling (see `.shared/tools/dfma_evaluator.py`
  and the retired-tier entries in `rules/dfm_rules.json`).
