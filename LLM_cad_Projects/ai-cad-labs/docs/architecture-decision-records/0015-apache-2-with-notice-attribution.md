# 0015. Apache-2.0 with NOTICE attribution

Status: Accepted (2026-07)

## Context

The project needed a license for its public repositories.
Two constraints shaped the choice.
First, AI-assisted CAD and engineering software is a live-patent domain:
granted patents exist in this space,
so the patent posture of the license is not academic.
Second, the project is solo-maintained at present,
with no contributor license agreement apparatus,
so the license itself must carry the contribution terms.

## Decision

All public repositories in this organization ship under Apache-2.0,
with a NOTICE file carrying attribution:

- The owner line reads "Copyright 2026 The ai-cad-labs project."
- The attribution line credits the founding developer
  and the AI-CAD Labs contributors and maintainers.
- Under section 4(d) of the license,
  anyone redistributing the work or a derivative
  must include a readable copy of the NOTICE's attribution notices,
  so the attribution travels with every redistribution.

See `LICENSE` and `NOTICE` at the repository root.

## Alternatives considered

- **MIT.** Maximum simplicity, and the same core freedoms
  (use, modify, sell, close-source, with attribution).
  Rejected because MIT carries no explicit patent grant:
  courts may imply one, but that theory is untested,
  which is the wrong bet in a live-patent domain.

## Consequences

- Every contributor grants an explicit patent license
  covering their contribution, protecting downstream users
  from patent claims by contributors.
- The patent-retaliation clause
  (suing users over patents costs the aggressor their license)
  acts as a deterrent against patent aggression.
- Contribution terms are built into the license,
  so no separate CLA is needed for a solo maintainer.
- NOTICE contents are informational only and never modify the license;
  downstream redistributors may add their own notices
  but cannot strip the project's attribution.
- The project-branded owner line is a deliberate governance choice
  over a personal name:
  the project outlives any individual maintainer.
