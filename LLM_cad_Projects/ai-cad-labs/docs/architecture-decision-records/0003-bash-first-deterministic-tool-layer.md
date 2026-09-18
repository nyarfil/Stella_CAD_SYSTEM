# 0003. Bash-first deterministic tool layer

Status: Accepted (2026-07)

## Context

The agents are stochastic; the geometry work they drive must not be.
CadQuery execution, rendering, export, DFMA evaluation, spec validation,
and placeholder detection all need deterministic, testable homes
that any agent runtime can drive.
The predecessor implementation bound these capabilities
to an in-framework tool registry typed against agent dependencies;
that registry dissolved with the framework (ADR 0001).

## Decision

Every deterministic capability is a plain Python module under `.shared/tools/`,
invoked from the repo root as `uv run python -m tools.<name> <flags>`.
The contract, stated in each module's docstring:

- one machine-parseable JSON object to stdout;
- human-readable detail to stderr;
- exit 0 when the tool ran, even when the evaluated artifact fails its checks
  (the JSON carries the verdict);
- non-zero exit only on tool malfunction;
- error messages never truncated.

Simple file operations are not wrapped:
they dissolve into the harness-native Read, Write, Glob, and Bash tools.

## Alternatives considered

- The predecessor's in-framework tool registry:
  typed and validated, but bound to one framework's process and lifetime.
- MCP servers exposing the same capabilities:
  heavier machinery and another process to manage,
  for tools a shell invocation already covers.
- Harness-native tools only, with no Python layer:
  loses deterministic, unit-testable geometry and evaluation logic entirely.

## Consequences

- The tool layer is harness-agnostic:
  any agent runtime with a shell can drive it,
  and humans can run every tool at a terminal.
- Each tool is independently unit-tested;
  the pytest suite in `tests/` rides alongside the modules.
- Splitting tool-success from artifact-verdict keeps exit codes meaningful
  to wrappers and background jobs,
  while letting evaluators report artifact failures as data.
- Agent-to-tool handoffs are machine-checkable,
  since every invocation returns exactly one JSON object.
- Each module's docstring is the full contract and the API reference;
  no separate prose reference is maintained.
