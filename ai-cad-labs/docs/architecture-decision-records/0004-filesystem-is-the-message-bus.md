# 0004. The filesystem is the message bus

Status: Accepted

## Context

The harness runs many agents across many spawns,
and any of them can crash, time out, or be replaced mid-run.
Inter-agent state passed in memory dies with the process that holds it.
The system also needs its decision history to be auditable by humans,
diffable in git,
and readable by tooling that is not part of the harness at all.

## Decision

All inter-agent state lives on the filesystem under `projects/<name>/`.
Project files are the communication channel:
`design_log.md` is an append-only decision log written for future AI readers,
`notes.md` carries each part's validation verdict as a machine-greppable final line,
`open_issues.md` carries numbered conflict negotiation records,
and `checkpoint.md` carries session-end state for a successor orchestrator.
The exact conventions are encoded in `.shared/agents/*/instructions.md`,
which is the canonical home for them.

Writers hand state forward rather than reading their own writes back;
the next agent in the flow is the reader.
Read-only roles write no project files at all,
and their verdicts travel in their returned summaries.
Inter-agent messaging may augment coordination,
but it never replaces filesystem state.

## Alternatives considered

- **In-memory state passing with typed state objects.**
  The predecessor PydanticAI implementation
  (ai-cad-labs/ai-cad-pydanticai)
  used typed state models,
  which bring validation and IDE support
  but are session-bound and harness-specific.
- **A message bus or database service.**
  Adds infrastructure and breaks the zero-config local story.
- **Agent messaging as the primary state channel.**
  Rejected because filesystem state is load-bearing
  for auditability, crash-resume, and the frontend;
  messaging is coordination-only.

## Consequences

- Crash-resume works from disk alone:
  a successor orchestrator rebuilds full state from project files.
- Every decision is a readable, git-diffable artifact,
  and any archived run directory can be replayed or inspected offline.
- The web frontend exists with zero harness coupling
  because it reads the same project files (see ADR 0005).
- State is less typed than in the predecessor implementation;
  a mistyped status field is not caught automatically,
  so validator tooling and JSON artifacts carry that burden.
- Log discipline becomes a correctness surface:
  a decision that never reaches `design_log.md` is invisible to every later reader,
  and parsers keyed on file conventions must track those conventions exactly.
