# 0005. Frontend as a read-only filesystem consumer

Status: Accepted (2026-07)

## Context

The harness needed a visual surface:
watching a run, browsing parts, renders, and decision history.
With the filesystem already serving as the message bus (ADR 0004),
every fact the UI could want is already on disk under `projects/<name>/`.
The open question was whether the frontend should couple to the harness
through an API server, a database, or embedded control,
or stay entirely outside it.

## Decision

The frontend is a separate process in its own top-level directory (`frontend/`)
that talks to the harness only through the project filesystem.
The filesystem is the API.
It is a pure read-only consumer of `projects/<name>/**`:
a Vite middleware (`frontend/plugins/projects-api.ts`)
serves project listings and raw file bytes in-process,
with no second server, no database, and no auth.
It never imports harness code,
and it launches with one command on localhost.

## Alternatives considered

- **An API server inside the harness.**
  Couples the two release cycles
  and violates the decoupling invariant
  that the harness never changes for UI work.
- **A database mirroring project state.**
  Requires sync machinery
  and creates a second source of truth beside the files.
- **Frontend-embedded harness control.**
  Rejected as a non-goal for this frontend;
  it reads state, it does not drive runs.

## Consequences

- The harness never changes for UI work,
  and the UI can be rebuilt freely.
  This paid off immediately:
  the frontend shipped and evolved with zero harness changes.
- The frontend works against any archived run directory,
  live run or not,
  which also makes it a stable target for browser-agent QA.
- Liveness must be derived from file reads:
  the activity surfaces poll the filesystem
  rather than receiving push events.
- Probing for files that may legitimately not exist yet
  must be silent by design;
  the API exposes existence checks
  so the client fetches only files that are there.
- Time-scrubbing through a run's history is not built;
  the frontend sees only the current state of the files.
