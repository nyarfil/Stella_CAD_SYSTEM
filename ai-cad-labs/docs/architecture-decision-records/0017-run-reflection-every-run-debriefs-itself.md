# 0017. Run reflection: every run debriefs itself

Status: Accepted (2026-07)

## Context

Autonomous design runs routinely improvise to protect their results:
environment self-fixes, geometry adaptations mid-design,
filesystem-only crash resumes.
Classical logs record events;
they cannot express the judgment behind those improvisations,
or what would make them unnecessary next time.
Before this decision, run-time learnings surfaced
only when a context-rich session happened to be watching the run.
The development loop needs usable feedback from every run,
wherever and however the harness executes.

## Decision

Every run synthesizes a structured self-debrief,
`projects/<name>/run_reflection.md`, when it reaches terminal state:
goals met, gave up, or resume completion.
It is backed by an append-only `reflection_notes.md`
written as the run goes, at every checkpoint and notable-failure moment,
so a crash never loses the raw notes
(the two-file write is sized to the harness's observed death modes).
Resume sessions inherit the synthesis duty from their predecessors.
The schema lives verbatim in exactly one place, the `run-reflection` skill,
which also carries the quality bar and a worked example from a real run.
Version one is instruction-layer only:
the orchestrator instructions mandate the writes;
there are no enforcement hooks and no scaffold tooling.
Reflections describe the run, never the operator.

## Alternatives considered

- Classical logging only.
  Rejected: logs record what happened;
  an agentic product can also ship judgment,
  the improvisations and paradigm suggestions that logs cannot express.
- Hook-enforced generation from day one.
  Deferred, not chosen: enforcement machinery costs build effort
  before knowing whether instruction-layer compliance suffices,
  so enforcement was explicitly gated on measuring compliance first.
- Folding the reflection into `checkpoint.md`.
  Rejected for separation of concerns:
  the checkpoint serves the next session's continuation;
  the reflection serves the development loop.

## Consequences

- Instruction is not enforcement; a run could finish without its reflection.
  That gap is accepted deliberately,
  and instruction-layer compliance has held on live runs,
  so no enforcement machinery has been built.
- The artifact travels with the run:
  YAML frontmatter makes reflections machine-routable
  and sweepable in bulk across many runs.
- The reflection is never load-bearing for the run itself:
  it does not gate completion,
  and a run is not considered failed for lacking one.
  Its whole cost is invisibility to the improvement loop.

Provenance: `.shared/skills/run-reflection/SKILL.md`
and the terminal-state steps in `.shared/agents/orchestrator/instructions.md`.
