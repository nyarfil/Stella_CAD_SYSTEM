# Architecture Decision Records

Each record captures one load-bearing decision and the alternatives considered;
for the rest of the documentation, see the [docs index](../README.md).

| # | Title | Decision |
|---|-------|----------|
| 0001 | [Claude Code as the agent runtime](0001-claude-code-as-the-agent-runtime.md) | Agent roles are markdown instruction files running on Claude Code |
| 0002 | [Shared canonical layer with harness symlinks](0002-shared-canonical-layer-with-harness-symlinks.md) | `.shared/` is the canonical home; harness paths symlink into it |
| 0003 | [Bash-first deterministic tool layer](0003-bash-first-deterministic-tool-layer.md) | Deterministic capabilities are plain Python modules invoked via `uv run python -m tools.<name>` |
| 0004 | [The filesystem is the message bus](0004-filesystem-is-the-message-bus.md) | All inter-agent state lives on the filesystem under `projects/<name>/` |
| 0005 | [Frontend as a read-only filesystem consumer](0005-read-only-filesystem-frontend.md) | The frontend reads the project filesystem and never writes to it |
| 0006 | [Regression-gated repair](0006-regression-gated-repair.md) | Repair agents write `part.proposal.py`; only the DFM regression gate swaps files |
| 0007 | [Central rules lifecycle](0007-central-rules-lifecycle.md) | One central ruleset governed by an explicit proposal-to-promotion lifecycle |
| 0008 | [The claude CLI is the single model engine](0008-claude-cli-as-single-model-engine.md) | The inner evaluation engine is the `claude` CLI invoked headless with Read-only tools |
| 0009 | [Evaluation authority: staleness caching and a deterministic verdict](0009-evaluation-authority-caching-and-deterministic-verdict.md) | One evaluation authority with staleness caching and a deterministic verdict |
| 0010 | [Vision-based DFMA evaluation with analytical backstops](0010-vision-based-dfma-with-analytical-backstops.md) | The evaluator judges render packages visually, backed by analytical checks |
| 0011 | [Individual view renders, never collages](0011-individual-renders-never-collages.md) | Every render call produces individual PNG views; collage generation was deleted |
| 0012 | [Mortal orchestrator with filesystem-only resume](0012-mortal-orchestrator-filesystem-resume.md) | Sessions are finite by design; resume reconstructs state from the filesystem alone |
| 0013 | [Coordinate convention (Principle 0) and direct placement](0013-coordinate-convention-and-direct-placement.md) | A single origin convention plus direct placement, saturated across all code agents |
| 0014 | [Deferred fillets policy](0014-deferred-fillets-policy.md) | Fillets and chamfers are deferred system-wide as a standing policy |
| 0015 | [Apache-2.0 with NOTICE attribution](0015-apache-2-with-notice-attribution.md) | All public repositories ship under Apache-2.0 with a NOTICE attribution file |
| 0016 | [AGENTS.md is canonical; CLAUDE.md and GEMINI.md are import shims](0016-agents-md-canonical-with-import-shims.md) | `AGENTS.md` holds the development rules; assistant-specific files import it |
| 0017 | [Run reflection: every run debriefs itself](0017-run-reflection-every-run-debriefs-itself.md) | Every run writes a structured `run_reflection.md` self-debrief at terminal state |
| 0018 | [Skills as the knowledge layer](0018-skills-as-the-knowledge-layer.md) | Domain knowledge lives in skills, consulted on demand |
