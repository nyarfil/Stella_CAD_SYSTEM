# API reference (tool layer)

> **These pages are generated from the tool-layer docstrings. Never hand-edit them.**
> The reference covers the tool layer, the `tools` package, and nothing else;
> tests consume that API rather than define it, so they stay out of scope.
> Regenerate with `uv run --frozen python tests/test_api_docs.py --write`,
> and edit the docstring in `.shared/tools/` when a page reads wrong.
> Freshness is enforced by `tests/test_api_docs.py`:
> the suite fails until a changed docstring is regenerated here.

Every capability underneath the agents is a deterministic Python tool,
invoked as `uv run python -m tools.<name>` from the repo root.
Each module docstring is that tool's full contract,
covering its modes, its output shape, and its exit semantics.
This folder is that contract rendered to markdown and committed,
so browsing the repo is enough to read the reference.

This index is the one authored page here.
It is not produced by the regeneration command,
and it is deliberately outside the snapshot comparison,
so it is safe to edit by hand.

## The modules

| Module | Purpose | Reference |
|---|---|---|
| `cadquery_executor` | CadQuery executor tool: runs CadQuery Python code in a controlled namespace. | [cadquery_executor.md](cadquery_executor.md) |
| `spec_validator` | Spec validator: project state scanner + structural artifact checks (CLI). | [spec_validator.md](spec_validator.md) |
| `renderer` | Renders a part or assembly to the standard engineering-view PNGs, with per-part colors and a legend in assembly mode. | [renderer.md](renderer.md) |
| `dimension_checker` | Dimension checker: deterministic bbox-vs-constraints verification. | [dimension_checker.md](dimension_checker.md) |
| `exporter` | CAD exporter tool: exports a part to manufacturable file formats. | [exporter.md](exporter.md) |
| `placeholder_detector` | Placeholder detector: is a part.py a real design or a stub? (CLI). | [placeholder_detector.md](placeholder_detector.md) |
| `dfma_evaluator` | DFMA evaluator: bash-callable Design for Manufacturing / Assembly evaluation. | [dfma_evaluator.md](dfma_evaluator.md) |
| `_dfma_models` | Typed Pydantic models for DFMA evaluation (the tool layer stays typed Python). | [_dfma_models.md](_dfma_models.md) |

The pages render the public surface of each module:
the module contract, then every public class and function with its signature.
Private helpers are implementation detail and stay out.

## Keeping this current

Change a docstring in `.shared/tools/`, then run the regeneration command.
The suite fails on any page that drifts from its source,
names the pages that went stale,
and repeats the command in the failure message.

## Pointers

- [`../README.md`](../README.md): the docs index, including what a run writes.
- [`../dev/local-setup.md`](../dev/local-setup.md): contributor environment setup and the test suites.
- [`../glossary.md`](../glossary.md): the domain language behind the names on these pages.
