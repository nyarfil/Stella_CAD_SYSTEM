# 0018. Skills as the knowledge layer

Status: Accepted (2026-07)

## Context

Code-writing agents need domain knowledge:
CadQuery patterns and API idioms, machine-design data,
and standard component dimensions.
The predecessor PydanticAI implementation auto-injected reference content
into every agent context:
the token cost was paid on every call
whether or not the content was relevant,
and the agent exercised no judgment about what to consult.
Separately, each new geometry class exposes new failure modes,
and fixing them by re-engineering agent prompts per class
is an overfitting trap.

## Decision

Domain knowledge lives in skills, consulted on demand:

- `cadquery-cookbook` is the mandatory pre-code consultation
  for every code-writing role;
  their instructions require it before any CadQuery code is written.
- `engineering-handbooks` and `sourcing-tables` ship as
  declared provisional stubs:
  reserved slots that keep the knowledge-layer layout stable,
  loudly marked non-authoritative until content lands.
- When a new geometry class exposes a failure mode,
  the class-level fix is one distilled cookbook pattern
  taken from the run's actual working code,
  never per-class prompt re-engineering.

## Alternatives considered

- Auto-inject reference content into every agent context,
  the predecessor's pattern.
  Rejected: pays the token cost always and removes agent judgment.
- Per-geometry-class prompt engineering.
  Rejected as the overfit trap:
  the system's value is generalizing to geometry it has never produced.
- Omit the empty skills until content exists.
  Rejected: the slots' existence is intentional,
  so content can land without re-wiring agent instructions.

## Consequences

- Skill invocation is an instruction-layer discipline,
  knowingly weaker than unconditional injection;
  that weakness is the accepted price of on-demand consultation.
- The knowledge loop closes through runs:
  reflections carry knowledge candidates (see ADR 0017),
  and patterns validated in real runs graduate into the cookbook.
- Reference material is deliberately duplicated
  between the cookbook skill and the `reference/` directory
  so the skill is self-contained mid-run;
  the bundled API surface and cheatsheets are kept byte-identical,
  while the skill's own `SKILL.md` is the harness-annotated variant of
  `reference/COOKBOOK.md` (frontmatter, the fillet-deferral banner,
  and the banned-pattern notes exist only in the skill copy).
  Both halves of that split are a known and monitored trade.

Provenance: `.shared/skills/cadquery-cookbook/SKILL.md`,
`.shared/skills/engineering-handbooks/SKILL.md`,
`.shared/skills/sourcing-tables/SKILL.md`,
and the consultation steps in the code-writing agents'
`.shared/agents/*/instructions.md`.
