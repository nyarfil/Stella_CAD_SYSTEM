# 0008. The claude CLI is the single model engine

Status: Accepted (2026-07)

## Context

After the harness migration,
the DFMA evaluator's inner vision call was the last part of the system
still running on the predecessor's multi-provider cloud-API routing:
provider configuration resolution, API keys, and a `.env` file.
That path carried two failure classes of its own.
Its fixed 8192-token output ceiling could kill a long evaluation mid-write
(the ceiling is recorded in the evaluator's module docstring
as a legacy limit that no longer applies),
and its credentials expired on a separate schedule
from the harness's own auth,
adding a second cloud-auth failure mode to every run.
Everything else in the system already ran through Claude Code.

## Decision

The inner evaluation engine is the `claude` CLI itself,
invoked headless with Read-only tools:
Claude reads the render PNGs directly from disk
and returns one JSON object,
which is still validated against the typed evaluation schema
(generation moved to the CLI; typing stayed).
There are no API keys and no `.env` file anywhere in the repo;
the CLI carries authentication.
Model and limits are the only environment knobs:
`CAD_EVALUATOR_MODEL` (empty means the CLI's configured default),
`CAD_EVALUATOR_TIMEOUT_S`,
and `CAD_EVALUATOR_CONCURRENCY` for sweep-mode parallelism.
A `.env.template` ships only in the predecessor repo,
ai-cad-labs/ai-cad-pydanticai.
The invocation lives in `.shared/tools/dfma_evaluator.py`.

## Alternatives considered

- Keep the predecessor's multi-provider cloud-API inner evaluator.
  Rejected: it carried the output-token ceiling,
  a second credential lifecycle,
  and a mixed-runtime system where one component
  authenticated and failed differently from everything else.
- Multi-provider configuration resolution with API-key fallbacks
  (the predecessor's layered pattern).
  Rejected: more configuration surface and key management
  for a capability the harness runtime already provides.

## Consequences

- One auth story end to end, and zero keys in the repo:
  a cloner needs only a working `claude` login.
- The single-completion output ceiling is gone in this path;
  long reports are no longer truncated by the engine.
- The typed-output retry machinery of the old framework
  is replaced by schema validation of the CLI's output,
  with one retry that feeds the validation error back.
- One model family serves evaluation;
  the predecessor's per-role cheap-model routing is lost,
  a consciously accepted cost of the unification.
- Inner evaluations are slow per call on the CLI path,
  which makes caching, single-pass defaults, and the parallel sweep
  the latency levers (see ADR 0009).
