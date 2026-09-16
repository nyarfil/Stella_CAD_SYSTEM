# 0012. Mortal orchestrator with filesystem-only resume

Status: Accepted (2026-07)

## Context

Long autonomous design runs die mid-flight:
cloud auth token expiry, context exhaustion, and crashes
were all observed in the first weeks of production runs.
An orchestrator designed to live for the whole run
loses whatever state it holds when it dies.
Because all inter-agent state already lives on the filesystem
(see [ADR 0004](0004-filesystem-is-the-message-bus.md)),
death can be designed for instead of merely survived.

## Decision

The orchestrator is deliberately mortal.
A session is finite, with declared end-of-life triggers:
goals met, budget exhausted, human input needed,
or a spawn-count self-checkpoint
(`.shared/agents/orchestrator/instructions.md`).
At end of life it writes `checkpoint.md` for its successor.

The resume contract is stronger than the checkpoint:
a resume session must reconstruct full state from the filesystem alone
(the design log tail, open issues, and spec-validator state),
even when NO checkpoint exists.
`checkpoint.md` is a courtesy baton that speeds a successor up,
never a dependency the resume path requires.

In headless launches, the entry prompt mandates
dispatching the orchestrator synchronously within the turn:
a headless process exits at turn end
and would orphan-kill an in-process backgrounded child.

## Alternatives considered

- An immortal, long-running orchestrator.
  Rejected: it dies to context growth and cloud auth token expiry anyway,
  taking unpersisted state with it.
- Checkpoint-file-dependent resume only.
  Proven insufficient in production:
  a crashed run left no checkpoint on disk
  and was resumed cleanly from filesystem state alone.
- An external process supervisor re-driving the run.
  Rejected: infrastructure the filesystem contract makes unnecessary.

## Consequences

- The resume recipe is part of the operating manual
  (the runbook in [`AGENTS.md`](../../AGENTS.md)).
- Escalation budgets are counted in attempts, not tokens,
  because the harness exposes no per-part token counters to the orchestrator.
- Unattended run duration remains ceilinged by cloud auth token expiry;
  the design converts that death into a resume rather than a restart.
- Crash-resume and checkpoint succession have been exercised on real runs;
  the run gallery
  (`ai-cad-labs/ai-cad-example-projects`)
  publishes runs that completed across orchestrator generations.
