> Generated from the `tools/_dfma_models.py` docstrings, never hand-edited.
> Regenerate with `uv run --frozen python tests/test_api_docs.py --write`.
<a id="tools._dfma_models"></a>

# tools.\_dfma\_models

Typed Pydantic models for DFMA evaluation (the tool layer stays typed Python).

DFMAEvaluation is the output schema for the inner evaluation engine, which
evaluates rules against rendered part/assembly view images. The LLM MUST produce
valid JSON matching this schema; validation failures are retried.

<a id="tools._dfma_models.DFMARuleResult"></a>

## DFMARuleResult Objects

```python
class DFMARuleResult(BaseModel)
```

Result of evaluating a single DFMA rule against rendered images.

<a id="tools._dfma_models.DFMAEvaluation"></a>

## DFMAEvaluation Objects

```python
class DFMAEvaluation(BaseModel)
```

Complete result of a DFM or DFA evaluation pass.

