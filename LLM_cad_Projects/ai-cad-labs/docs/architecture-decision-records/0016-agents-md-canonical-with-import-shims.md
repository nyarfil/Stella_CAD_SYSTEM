# 0016. AGENTS.md is canonical; CLAUDE.md and GEMINI.md are import shims

Status: Accepted (2026-07)

## Context

Coding assistants look for repository instructions under different filenames.
AGENTS.md is a widely adopted cross-assistant convention;
Claude Code reads CLAUDE.md and supports importing another file via an `@` line;
other assistants read their own named files.
Maintaining full parallel rule files is a drift engine:
two rule surfaces that disagree leave an agent unable to tell which one is real.
Before this decision, CLAUDE.md held the full rules,
and an assistant that read AGENTS.md first and exclusively received only a stub,
never the rules. That gap was observed live.

## Decision

`AGENTS.md` holds the complete cross-assistant development rules for this repository.
`CLAUDE.md` is a real file that opens with an `@AGENTS.md` import line,
followed by at most a line or two of Claude-specific notes.
`GEMINI.md` is a one-line `@./AGENTS.md` import.
All three are regular files; there are no symlinks anywhere in the trio.

## Alternatives considered

- Keep CLAUDE.md canonical.
  Rejected: assistants that read AGENTS.md first and exclusively
  would keep receiving only a pointer stub.
- Symlink the shim files to AGENTS.md.
  Rejected: GitHub renders a symlinked markdown file as raw path text,
  and a native Windows clone without symlink support
  materializes it as a broken path-text file.
- Full per-assistant mirror files.
  Rejected as a drift engine:
  every rule change would need synchronized edits across three files,
  held together only by manual discipline.

## Consequences

- Exactly one maintained rules surface;
  the shims cannot drift because they carry no rules of their own.
- The trio renders correctly on GitHub and survives native Windows clones.
- The standing discipline is that shims stay thin:
  a rule added only to CLAUDE.md would silently recreate
  the exact gap this decision closed.
- Rule coverage was diffed section by section at the migration
  to confirm no content was lost moving the canon.

Provenance: `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` at the repository root.
