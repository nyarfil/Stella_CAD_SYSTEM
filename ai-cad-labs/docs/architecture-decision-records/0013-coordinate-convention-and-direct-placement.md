# 0013. Coordinate convention (Principle 0) and direct placement

Status: Accepted

## Context

Language models are unreliable at spatial reasoning about unknown origins.
When each generated part placed its origin wherever its CadQuery code happened to land,
parts that executed cleanly still assembled wrong:
the assembly ran, but components visibly floated apart,
because positioning them required a mental model of
"where is the bore center relative to this part's arbitrary origin."

Assembly placement itself also needed to be debuggable.
A placement that an agent computes must be reviewable
by another agent, and by a human reading the diff,
without simulating an opaque solver in their head.

This convention was established in the predecessor PydanticAI implementation
(public at ai-cad-labs/ai-cad-pydanticai) and carried forward into this harness.

## Decision

Two coupled rules, saturated across every code-writing and code-checking agent:

1. **Principle 0, the origin convention.**
   Every revolved or cylindrical part (shafts, bores, discs, pins)
   is authored with its axis of revolution on the Z axis,
   with the cross-section center passing through the origin.
   Prismatic parts (brackets, plates, housings)
   are centered on XY with the bottom face at Z=0.
2. **Direct placement only.**
   Assembly positioning uses explicit `cq.Location` transforms,
   calculated arithmetically from part dimensions and interface specifications.
   CadQuery's `.constrain()`/`.solve()` constraint solver is banned.

## Alternatives considered

- **Arbitrary per-part origins** (the original state).
  Rejected as the root cause of floating, misaligned assemblies:
  every placement required origin bookkeeping that language models get wrong.
- **Constraint-solver assembly** (`.constrain()` + `.solve()`).
  Rejected: the solver proved unreliable with generated geometry
  and fails frequently on complex assemblies,
  and its behavior is opaque to both agents and reviewers,
  where an explicit transform is a readable arithmetic claim.

## Consequences

- With every functional axis passing through its part's origin,
  assembly reduces to aligning Z axes and offsetting along Z.
  No agent needs to reason about where a feature sits
  relative to an arbitrary origin.
- Enforcement is an instruction-layer discipline:
  the designing agents author to the convention,
  and the validating and reviewing agents check compliance against it
  (see `.shared/agents/cad_designer/instructions.md`
  and `.shared/agents/assembly_resolver/instructions.md`).
- The cookbook skill keeps a constraint-based assembly pattern
  as reference-only material,
  for reading external CadQuery code that uses mates,
  while production assemblies remain direct-placement
  (see `.shared/skills/cadquery-cookbook/SKILL.md`).
