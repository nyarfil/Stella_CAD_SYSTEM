# 0002. Shared canonical layer with harness symlinks

Status: Accepted (2026-07)

## Context

The agent instructions, skills, and deterministic tools are the durable product;
the harness that dispatches them is treated as substitutable substrate (ADR 0001).
Two harness front-ends exist in the tree:
`.claude/` (Claude Code) and `.opencode/` (OpenCode).
Each harness discovers agents and skills under its own directory convention,
which invites either duplicated copies or a single-harness lock-in layout.

## Decision

`.shared/` is the canonical home:
`.shared/agents/<role>/instructions.md`,
`.shared/skills/<name>/SKILL.md`,
and `.shared/tools/*.py`.
Harness directories symlink into it:
`.claude/agents` and `.claude/skills` point at the `.shared` pair,
and `.opencode/` mirrors the same two links.
A top-level `tools` symlink to `.shared/tools`
makes `python -m tools.<name>` work from the repo root.
Content is edited only in `.shared/`, never through the symlinks.

## Alternatives considered

- Per-harness copies of the agent and skill files:
  a drift engine, since every edit must be repeated once per harness.
- A `.claude/`-only layout with no shared layer:
  locks the product to one harness and abandons portability.
- A generation or build step producing per-harness artifacts:
  machinery cost and a stale-output failure mode
  for what are plain markdown files.

## Consequences

- One source of truth serves any number of harness front-ends.
  Agent discovery through the `.claude/agents` symlink is verified live:
  the harness lists every agent at its `.shared` path.
- The OpenCode shell ships;
  its parallel build is a stated open scope boundary (see the README status table).
- Windows needs explicit clone guidance, and gets it as a first-class concern:
  a default native clone (`core.symlinks=false`) materializes the symlinks
  as plain text files, breaking module imports and agent discovery.
  Clone with `git clone -c core.symlinks=true`
  (requires Developer Mode or admin rights), or work inside WSL.
  This guidance ships in the README rather than restructuring the tree,
  because the shared layer is load-bearing for the dual-harness design.
- GitHub's web UI renders a symlink as its path text; this is cosmetic only.
