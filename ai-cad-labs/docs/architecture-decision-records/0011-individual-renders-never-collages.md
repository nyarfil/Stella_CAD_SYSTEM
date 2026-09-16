# 0011. Individual view renders, never collages

Status: Accepted (2026-03)

## Context

Rendered engineering views are the evaluator's and validator's primary evidence,
so how images reach the model is a correctness surface, not a cosmetic one.
The original architecture composited all views into a single collage image.
LLM vision providers tile large images differently:
a large composite gets split across processing tiles unpredictably,
destroying cross-view context,
while an individual view fits within a single tile
and receives the model's full attention.
Separately, monochrome assembly renders made part-to-part problems
(overlap, gaps, misalignment) effectively invisible to vision.

## Decision

Every render call produces individual PNG view images,
sent as one deterministic package;
collage generation was deleted outright.
Single parts render monochrome.
Assemblies render with a distinct stroke color per part
plus a text legend mapping colors to part names,
falling back to monochrome only when colored rendering fails.
The canonical mechanics of the render package
(views, styles, output paths, the color palette)
live in `.shared/tools/renderer.py`.
The decision predates the current harness
and carries over from the predecessor PydanticAI implementation
(`ai-cad-labs/ai-cad-pydanticai`),
whose renderer follows the same convention.

## Alternatives considered

- Composite collage images (the original architecture).
  Deleted: provider tiling fragments them unpredictably,
  and gaming any one provider's tile size is not portable.
- Monochrome assembly renders as the standard mode.
  Rejected: per-part color is what lets vision actually see
  interference, gaps, and misalignment between parts.
- Letting agents select which render files to attach.
  Rejected: the package is shuttled deterministically,
  never relying on an agent to find or choose images.

## Consequences

- Higher vision-token cost per render call
  (several images where one collage sufficed), accepted for quality.
- Colored assembly views are more expensive to produce:
  each view composites one SVG render per part at a shared scale.
- Cross-view reasoning now spans separate images,
  mitigated by deterministic naming and labeling of each view.
- Wireframe-style views remain a vision false-positive cluster;
  that residual is handled by the honesty conventions and analytical backstops
  of [ADR 0010](0010-vision-based-dfma-with-analytical-backstops.md).
