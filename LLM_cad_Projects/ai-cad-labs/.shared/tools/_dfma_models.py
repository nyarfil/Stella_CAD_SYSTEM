"""Typed Pydantic models for DFMA evaluation (the tool layer stays typed Python).

DFMAEvaluation is the output schema for the inner evaluation engine, which
evaluates rules against rendered part/assembly view images. The LLM MUST produce
valid JSON matching this schema; validation failures are retried.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DFMARuleResult(BaseModel):
    """Result of evaluating a single DFMA rule against rendered images."""

    rule_id: str = Field(description="Rule ID (e.g., DFM-CNC-003)")
    rule_description: str = Field(description="One-line rule description")
    verdict: Literal["pass", "fail", "uncertain"] = Field(
        description="Whether the part passes this rule"
    )
    severity: str = Field(description="Rule severity: critical, major, or minor")
    tier: str = Field(description="Rule tier: active or probationary")
    observation: str = Field(
        description="What the evaluator actually saw in the rendered images"
    )
    recommendation: str = Field(
        default="",
        description="How to fix the issue (only if verdict is fail or uncertain)",
    )


class DFMAEvaluation(BaseModel):
    """Complete result of a DFM or DFA evaluation pass."""

    eval_type: Literal["dfm", "dfa"] = Field(
        description="Whether this is a DFM (part) or DFA (assembly) evaluation"
    )
    target_path: str = Field(description="Path evaluated (e.g., assembly/bracket)")
    manufacturing_process: str = Field(
        default="", description="Manufacturing process from constraints.md"
    )
    pass_label: str = Field(
        default="",
        description="Which pass produced this: manufacturing_technique or engineering_domain",
    )
    rules_evaluated: int = Field(description="Total rules checked in this pass")
    rules_passed: int = Field(description="Rules with verdict=pass")
    rules_failed: int = Field(description="Rules with verdict=fail")
    rules_uncertain: int = Field(description="Rules with verdict=uncertain")
    overall_verdict: Literal["pass", "conditional_pass", "fail"] = Field(
        description="Overall evaluation — derived deterministically post-validation: fail (any active-tier CRITICAL failure), conditional_pass (non-critical failures/uncertains present), pass (neither)"
    )
    results: list[DFMARuleResult] = Field(
        default_factory=list, description="Per-rule evaluation results"
    )
    proposed_rules: list[dict] = Field(
        default_factory=list,
        description="New rules the evaluator suggests adding to the ruleset",
    )
