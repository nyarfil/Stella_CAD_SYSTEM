"""Versioned intermediate representations; all distances are explicitly in mm.

These schemas validate declared design intent, not truth or mechanical fitness.
A geometrically valid model and a physically validated product are different states.
"""
from __future__ import annotations

import math
from typing import Annotated, Any, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, field_validator, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")]
Text = Annotated[str, Field(min_length=1, max_length=12000)]
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Positive = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
Scalar = StrictBool | StrictInt | StrictFloat | StrictStr
Vec3 = tuple[Number, Number, Number]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_assignment=True)


class SourceRef(Model):
    source_id: Identifier
    quote: Text  # Must occur verbatim in the identified source; never inferred.


class Source(Model):
    id: Identifier
    text: Text
    sha256: str


class Unknown(Model):
    id: Identifier
    question: Text
    blocks: Literal["intent", "concepts", "plan", "release"]
    resolution: str | None = None
    source_refs: list[SourceRef] = Field(default_factory=list)


class Requirement(Model):
    id: Identifier
    text: Text
    priority: Literal["must", "preference", "must_not"]
    origin: Literal["explicit", "inferred"]
    source_refs: list[SourceRef] = Field(min_length=1)
    verification: Literal["declaration", "geometry", "physical"]


class Constraint(Model):
    """A predicate over declared candidate properties, NOT a geometric certificate."""
    requirement_id: Identifier
    property: Identifier
    op: Literal["eq", "le", "ge", "ne"]
    value: Scalar
    unit: Literal["mm", "N", "g", "count", "dimensionless", "text"]

    @model_validator(mode="after")
    def consistent(self):
        if self.op in ("le", "ge") and (isinstance(self.value, bool) or not isinstance(self.value, (int, float))):
            raise ValueError("ordered comparisons require a finite number, not text/bool")
        if self.unit == "text" and not isinstance(self.value, str):
            raise ValueError("text constraints require a string")
        if self.unit in ("mm", "N", "g", "count") and (isinstance(self.value, bool) or not isinstance(self.value, (int, float))):
            raise ValueError("dimensional constraints require a numerical value")
        if self.unit == "count" and (not math.isfinite(self.value) or self.value < 0 or int(self.value) != self.value):
            raise ValueError("count must be a nonnegative integer")
        if isinstance(self.value, (int, float)) and not isinstance(self.value, bool) and not math.isfinite(self.value):
            raise ValueError("non-finite constraint")
        return self


class Disposition(Model):
    source_id: Identifier
    quote: Text
    reason: Text


class Brief(Model):
    schema_version: Literal["1.0"] = "1.0"
    objective: Text
    coordinate_frame: Text
    requirements: list[Requirement] = Field(min_length=1, max_length=100)
    constraints: list[Constraint] = Field(default_factory=list, max_length=100)
    unknowns: list[Unknown] = Field(default_factory=list, max_length=100)
    dispositions: list[Disposition] = Field(default_factory=list, max_length=100)
    manufacturing_notes: Text


class Function(Model):
    id: Identifier
    function_key: Identifier
    verb: Text
    object: Text
    requirement_ids: list[Identifier] = Field(min_length=1)
    expected_behavior: Text


class Component(Model):
    id: Identifier
    name: Text
    role: Literal["printed", "purchased", "reference"]
    material: Text
    function_ids: list[Identifier] = Field(min_length=1)
    manufacturing_orientation: Text
    assembly_access: Text


class Mechanism(Model):
    id: Identifier
    pattern_id: Identifier
    function_ids: list[Identifier] = Field(min_length=1)
    component_ids: list[Identifier] = Field(min_length=1)
    input_direction: Vec3 | None = None
    output_direction: Vec3 | None = None
    return_method: Literal["switch_internal", "printed_flexure", "metal_spring", "none", "not_applicable"]
    hard_stop: StrictBool
    force_path: Text
    failure_modes: list[Text] = Field(min_length=1)
    verification_notes: Text
    reference_ids: list[Identifier] = Field(default_factory=list)
    motion_relation: Literal["direct", "lever", "other"] | None = None

    @field_validator("input_direction", "output_direction")
    @classmethod
    def valid_direction(cls, v):
        if v is not None and abs(math.sqrt(sum(x*x for x in v))-1) > 1e-6:
            raise ValueError("direction must be a unit vector in the Brief coordinate frame")
        return v


class Interface(Model):
    id: Identifier
    component_a: Identifier
    component_b: Identifier
    kind: Literal["mount", "load", "contact", "guide", "return", "stop"]
    description: Text
    allowed_motion: Text


class CaseReference(Model):
    id: Identifier
    uid: Annotated[str, Field(pattern=r"^\d{4}/\d{8}$")]
    evidence_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    function_query: Text
    adopted_principle: Text
    required_adaptations: list[Text] = Field(min_length=1)


class Concept(Model):
    id: Identifier
    title: Text
    rationale: Text
    functions: list[Function] = Field(min_length=1, max_length=100)
    components: list[Component] = Field(min_length=1, max_length=100)
    mechanisms: list[Mechanism] = Field(min_length=1, max_length=100)
    interfaces: list[Interface] = Field(default_factory=list, max_length=200)
    properties: dict[Identifier, Scalar] = Field(default_factory=dict)
    unknowns: list[Unknown] = Field(default_factory=list)
    rejected_alternatives: list[Text] = Field(min_length=1)
    case_references: list[CaseReference] = Field(default_factory=list,max_length=50)


class Concepts(Model):
    items: list[Concept] = Field(min_length=2, max_length=4)


class PlanStep(Model):
    id: Identifier
    operation: Literal["create_part", "modify_part", "place_part", "create_joint", "inspect"]
    component_ids: list[Identifier] = Field(min_length=1)
    requirement_ids: list[Identifier] = Field(min_length=1)
    depends_on: list[Identifier] = Field(default_factory=list)
    purpose: Text
    instructions: Text
    preserves: list[Text] = Field(min_length=1)


class Dimension(Model):
    id: Identifier
    name: Text
    value_mm: Positive
    provenance: Literal["user", "measurement", "proposal"]
    source_refs: list[SourceRef] = Field(default_factory=list)
    evidence_id: Identifier | None = None
    rationale: Text


class Check(Model):
    id: Identifier
    requirement_ids: list[Identifier] = Field(min_length=1)
    kind: Literal["brep_valid", "solid_count", "bbox_x_mm", "bbox_y_mm", "bbox_z_mm", "distance_mm", "intersection_mm3", "external_geometry", "manual", "physical_test"]
    artifact_a: Identifier | None = None
    artifact_b: Identifier | None = None
    op: Literal["eq", "le", "ge"]
    target: StrictBool | Number
    tolerance: Nonnegative = 0.0
    description: Text

    @model_validator(mode="after")
    def check_shape(self):
        if self.kind not in ("manual", "physical_test", "external_geometry") and not self.artifact_a:
            raise ValueError("geometry checks need artifact_a")
        if self.kind in ("distance_mm", "intersection_mm3") and not self.artifact_b:
            raise ValueError("pairwise checks need artifact_b")
        if self.kind == "brep_valid" and (self.op != "eq" or self.target is not True or self.tolerance != 0):
            raise ValueError("B-rep validity must require true with zero tolerance")
        if self.kind not in ("brep_valid", "manual", "physical_test", "external_geometry") and isinstance(self.target, bool):
            raise ValueError("a numerical metric cannot use a boolean target")
        if self.kind == "solid_count" and (self.target < 1 or int(self.target) != self.target or self.tolerance != 0):
            raise ValueError("solid count needs an integer >= 1 and zero tolerance")
        if self.artifact_a and self.artifact_b and self.artifact_a == self.artifact_b:
            raise ValueError("a pairwise check needs two different artifacts")
        return self


class Plan(Model):
    schema_version: Literal["1.0"] = "1.0"
    concept_id: Identifier
    dimensions: list[Dimension] = Field(default_factory=list, max_length=200)
    steps: list[PlanStep] = Field(min_length=1, max_length=200)
    checks: list[Check] = Field(min_length=1, max_length=200)
    assembly_sequence: list[Text] = Field(min_length=1)
    print_strategy: Text
    unknowns: list[Unknown] = Field(default_factory=list)


class Artifact(Model):
    id: Identifier
    filename: str
    sha256: str
    bytes: int
    contract_digest: str


class ProtectedAsset(Model):
    """Owner-frozen reference geometry in its imported coordinate frame."""
    artifact_id: Identifier
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    placement: Literal["as_registered"] = "as_registered"
    required_output_id: Identifier


class EditableReference(Model):
    """A hash-pinned owner permission to modify one imported reference."""
    artifact_id: Identifier
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ProjectProtection(Model):
    """Persistent owner authority; an empty policy preserves legacy projects."""
    assets: list[ProtectedAsset] = Field(default_factory=list, max_length=64)
    editable_references: list[EditableReference] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def unambiguous(self):
        asset_ids=[item.artifact_id for item in self.assets]
        outputs=[item.required_output_id for item in self.assets]
        if len(asset_ids)!=len(set(asset_ids)): raise ValueError("Protected artifact IDs must be unique.")
        if len(outputs)!=len(set(outputs)): raise ValueError("Protected required output IDs must be unique.")
        editable_ids=[item.artifact_id for item in self.editable_references]
        if len(editable_ids)!=len(set(editable_ids)): raise ValueError("Editable reference IDs must be unique.")
        if set(asset_ids)&set(editable_ids):
            raise ValueError("An artifact cannot be protected and editable.")
        return self


class Project(Model):
    schema_version: Literal["1.0"] = "1.0"
    id: Identifier
    revision: int = 0
    sources: list[Source] = Field(default_factory=list)
    brief: Brief | None = None
    concepts: list[Concept] = Field(default_factory=list)
    selection: Identifier | None = None
    plan: Plan | None = None
    measurements: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[Identifier, Artifact] = Field(default_factory=dict)
    protection: ProjectProtection = Field(default_factory=ProjectProtection)
    verification: dict[str, Any] | None = None


SCHEMAS = {c.__name__: c for c in (Brief, Concepts, Concept, Plan, ProjectProtection)}
