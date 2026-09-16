# 0001. Claude Code as the agent runtime

Status: Accepted (2026-05)

## Context

The system began as a custom multi-agent framework built on PydanticAI:
a Python orchestrator with typed state models,
an in-framework tool registry bound to agent dependencies,
and deterministic dispatch logic routing work between the specialized CAD roles.
That implementation is preserved publicly as
[ai-cad-labs/ai-cad-pydanticai](https://github.com/ai-cad-labs/ai-cad-pydanticai).

Growing it meant hand-building every capability the agents needed:
subagent dispatch, shell access, file I/O, vision-capable reads,
long-running autonomous operation.
A custom harness grows only in proportion to what its authors anticipate,
while an external coding-agent harness ships those capabilities already
and improves with its whole user community.

## Decision

Adopt Claude Code as the agent runtime, in a fresh repository.
The agent roles become markdown instruction files
(`.shared/agents/<role>/instructions.md`) in the harness subagent format,
dispatched by the harness's native subagent mechanism.
Deterministic Python (geometry execution, rendering, export, evaluation, validation)
survives as a bash-invocable tool layer (see ADR 0003).
Domain knowledge moves into skills consulted on demand.
Orchestration state lives on the filesystem (see ADR 0004).
The predecessor PydanticAI implementation is frozen
as a point-in-time research artifact with a fix-forward posture.

## Alternatives considered

- Keep and grow the predecessor framework.
  It preserved deterministic Python-routed dispatch, typed state,
  and per-role model routing,
  but every new capability had to be built by hand,
  and building deterministic control flow on top of stochastic LLM behavior
  proved fragile in practice.
- A hybrid: keep the Python orchestrator on top
  and shell out to a coding-agent harness only for knowledge-heavy roles.
  Cheap and reversible, but the custom orchestrator remains the ceiling.
- A single-agent spike first: reimplement one agent and compare side by side.
  Rejected because the migration's value is emergent multi-agent interaction,
  which a single-agent spike cannot demonstrate;
  the meaningful comparison is full system against full system.
- Other external harnesses.
  OpenCode is retained as a parallel target rather than an alternative
  (see ADR 0002).

## Consequences

- Agent dispatch becomes prose-driven and therefore stochastic;
  deterministic gates, validation tooling, and file conventions absorb that risk.
- Typed in-memory orchestrator state is gone,
  replaced by convention-governed files on disk that tools validate.
- One model engine serves a session;
  per-role routing to cheaper models is a consciously accepted loss.
- The durable investment is harness-portable:
  agent instructions, skills, rules, and tools survive a harness swap;
  only the plumbing dissolved into harness primitives.
- The predecessor repository remains available for study and comparison.
