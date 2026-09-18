"""Typed Fusion assembly handoff. Cursor may only run the issued adapter script.

cadMCP cannot call Fusion MCP. The host passes this script verbatim to
fusion_mcp_execute. A different script is not a successful assembly.
Save of .f3d is never issued here. Measurement remains CadQuery.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Literal
from pydantic import Field, model_validator
from .recipe import Name, ProjectStep, Recipe, Strict, Vec, apply_rigid_mm, evaluate_geometry
from ..errors import BrainError
from ..req2cad.common import atomic_json, digest, file_hash, json_load
from ..util import safe_path, text_hash

ADAPTER_VERSION = '1'
IDENTITY = ([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], 0.0, [0.0, 0.0, 0.0])

# Fusion's default internal unit is centimetre. cadMCP recipes are millimetre.
_ADAPTER_TEMPLATE = r'''import adsk.core, adsk.fusion, json, os

PAYLOAD = r"""<<<CADMCP_FUSION_PAYLOAD>>>"""

def run(_context: str):
    payload = json.loads(PAYLOAD)
    if payload.get("allow_save") is not False:
        raise RuntimeError("cadMCP adapter refuses save; owner must save the f3d explicitly.")
    if payload.get("adapter_version") != "1":
        raise RuntimeError("Unknown cadMCP Fusion adapter version.")
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        raise RuntimeError("No active Fusion design.")
    root = design.rootComponent
    importer = app.importManager
    mm_to_cm = 0.1
    reported = []
    for occ in payload["occurrences"]:
        extra = occ["translation_mm"]
        rot = occ["rotation_deg"]
        if occ["protected"] and (any(abs(x) > 1e-12 for x in extra) or abs(rot) > 1e-12):
            raise RuntimeError("Protected occurrence cannot be transformed: " + occ["occurrence"])
        path = occ["step_absolute_path"]
        if not os.path.isfile(path):
            raise RuntimeError("Missing STEP for " + occ["occurrence"])
        options = importer.createSTEPImportOptions(path)
        options.isViewFit = False
        importer.importToTarget(options, root)
        placed = root.occurrences.item(root.occurrences.count - 1)
        placed.component.name = occ["occurrence"]
        if not occ["protected"] and (any(abs(x) > 1e-12 for x in extra) or abs(rot) > 1e-12):
            matrix = adsk.core.Matrix3D.create()
            origin = occ["rotation_origin_mm"]
            axis = occ["rotation_axis"]
            origin_p = adsk.core.Point3D.create(origin[0] * mm_to_cm, origin[1] * mm_to_cm, origin[2] * mm_to_cm)
            axis_v = adsk.core.Vector3D.create(axis[0], axis[1], axis[2])
            if abs(rot) > 1e-12:
                matrix.setToRotation(rot * 3.141592653589793 / 180.0, axis_v, origin_p)
            matrix.translation = adsk.core.Vector3D.create(extra[0] * mm_to_cm, extra[1] * mm_to_cm, extra[2] * mm_to_cm)
            placed.transform = matrix
        box = placed.boundingBox
        reported.append({
            "occurrence": occ["occurrence"],
            "translation_mm": extra,
            "rotation_axis": occ["rotation_axis"],
            "rotation_deg": rot,
            "rotation_origin_mm": occ["rotation_origin_mm"],
            "bbox_mm": [
                box.minPoint.x / mm_to_cm, box.minPoint.y / mm_to_cm, box.minPoint.z / mm_to_cm,
                box.maxPoint.x / mm_to_cm, box.maxPoint.y / mm_to_cm, box.maxPoint.z / mm_to_cm
            ]
        })
    print(json.dumps({
        "adapter_version": payload["adapter_version"],
        "handoff_digest": payload["handoff_digest"],
        "saved": False,
        "units": "mm",
        "occurrences": reported
    }, separators=(",", ":")))
'''


class FusionOccurrence(Strict):
    occurrence: Name
    part_id: Name
    step_relative_path: str = Field(min_length=1, max_length=800)
    step_absolute_path: str = Field(min_length=1, max_length=800)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    translation_mm: Vec = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation_axis: Vec = Field(default_factory=lambda: [0.0, 0.0, 1.0])
    rotation_deg: float = Field(default=0.0, ge=-360, le=360)
    rotation_origin_mm: Vec = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    protected: bool = False
    @model_validator(mode='after')
    def unit_axis(self):
        if abs(sum(x * x for x in self.rotation_axis) - 1) > 1e-6:
            raise ValueError('Rotation axis must be a unit direction.')
        if self.protected and (any(abs(x) > 1e-12 for x in self.translation_mm) or abs(self.rotation_deg) > 1e-12):
            raise ValueError('Protected occurrences stay at their imported pose.')
        return self


class FusionHandoff(Strict):
    schema_version: Literal[1] = 1
    adapter_version: Literal['1'] = ADAPTER_VERSION
    allow_save: Literal[False] = False
    units: Literal['mm'] = 'mm'
    fusion_internal_units: Literal['cm'] = 'cm'
    subject_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    occurrences: list[FusionOccurrence] = Field(min_length=1, max_length=16)
    protected_occurrences: list[Name] = Field(default_factory=list, max_length=16)
    @model_validator(mode='after')
    def names_agree(self):
        names = [o.occurrence for o in self.occurrences]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate Fusion occurrence names.')
        parts = [o.part_id for o in self.occurrences]
        if len(parts) != len(set(parts)):
            raise ValueError('Duplicate Fusion part ids.')
        protected = {o.occurrence for o in self.occurrences if o.protected}
        declared = set(self.protected_occurrences)
        if protected != declared:
            raise ValueError('protected_occurrences must list exactly the protected occurrence names.')
        return self


class FusionReportOccurrence(Strict):
    occurrence: Name
    translation_mm: Vec
    rotation_axis: Vec = Field(default_factory=lambda: [0.0, 0.0, 1.0])
    rotation_deg: float = Field(default=0.0, ge=-360, le=360)
    rotation_origin_mm: Vec = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    bbox_mm: list[float] | None = Field(default=None, min_length=6, max_length=6)
    @model_validator(mode='after')
    def unit_axis(self):
        if abs(sum(x * x for x in self.rotation_axis) - 1) > 1e-6:
            raise ValueError('Rotation axis must be a unit direction.')
        return self


class FusionReport(Strict):
    adapter_version: Literal['1'] = ADAPTER_VERSION
    handoff_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    saved: Literal[False] = False
    units: Literal['mm'] = 'mm'
    occurrences: list[FusionReportOccurrence] = Field(min_length=1, max_length=16)


def _near(a: list[float] | float, b: list[float] | float, tol: float = 1e-12) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))
    return abs(float(a) - float(b)) <= tol


def _identity_pose(occ: FusionOccurrence | FusionReportOccurrence) -> bool:
    return (_near(occ.translation_mm, IDENTITY[0]) and _near(occ.rotation_axis, IDENTITY[1])
            and _near(occ.rotation_deg, IDENTITY[2]) and _near(occ.rotation_origin_mm, IDENTITY[3]))


def adapter_payload(handoff: FusionHandoff) -> dict[str, Any]:
    body = {
        'adapter_version': handoff.adapter_version,
        'allow_save': False,
        'units': 'mm',
        'fusion_internal_units': 'cm',
        'subject_digest': handoff.subject_digest,
        'occurrences': [o.model_dump() for o in handoff.occurrences],
        'protected_occurrences': list(handoff.protected_occurrences),
    }
    body['handoff_digest'] = digest(body)
    return body


def render_adapter_script(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if '"""' in encoded or '<<<CADMCP_FUSION_PAYLOAD>>>' in encoded:
        raise BrainError('FUSION_PAYLOAD', 'Handoff payload cannot be embedded in the Fusion adapter.')
    return _ADAPTER_TEMPLATE.replace('<<<CADMCP_FUSION_PAYLOAD>>>', encoded)


def issue_script(handoff: FusionHandoff) -> tuple[str, str, dict[str, Any]]:
    payload = adapter_payload(handoff)
    script = render_adapter_script(payload)
    return script, text_hash(script), payload


def _build_folder(studio, payload: dict) -> Path:
    folder = Path(payload['folder'])
    folder = folder if folder.is_absolute() else safe_path(studio.root, payload['folder'])
    if not folder.is_relative_to(studio.root.resolve()):
        raise BrainError('STUDIO_PATH', 'Review artifact is outside the workspace.')
    return folder


def _protected_nodes(recipe: Recipe) -> set[str]:
    return {n.id for n in recipe.operations if isinstance(n, ProjectStep) and n.role == 'protected_hardware'}


def issue_handoff(studio, project_id: str, revision: int, subject_digest: str) -> dict[str, Any]:
    target, info = studio._subject(project_id, revision, subject_digest)
    payload = info['payload']
    if payload.get('kind') != 'recipe_build':
        raise BrainError('FUSION_SUBJECT', 'Fusion handoff requires a built recipe subject.')
    folder = _build_folder(studio, payload)
    recipe = Recipe.model_validate(json_load(folder / 'recipe.json'))
    measurements = payload['measurements']
    protected_nodes = _protected_nodes(recipe)
    occurrences = []
    for output in recipe.outputs:
        export = measurements['outputs'][output.part_id]['exports']['model.step']
        relative = export['relative_path']
        step = safe_path(folder, relative)
        if file_hash(step) != export['sha256']:
            raise BrainError('STUDIO_CHANGED', 'Build STEP changed before Fusion handoff.')
        protected = output.node in protected_nodes
        occurrences.append(FusionOccurrence(
            occurrence=output.part_id, part_id=output.part_id,
            step_relative_path=relative, step_absolute_path=str(step),
            sha256=export['sha256'], protected=protected))
    handoff = FusionHandoff(
        subject_digest=subject_digest, occurrences=occurrences,
        protected_occurrences=[o.occurrence for o in occurrences if o.protected])
    script, adapter_sha256, script_payload = issue_script(handoff)
    record = {
        'handoff': handoff.model_dump(),
        'adapter_version': ADAPTER_VERSION,
        'adapter_sha256': adapter_sha256,
        'handoff_digest': script_payload['handoff_digest'],
        'allow_save': False,
        'fusion_witness': False,
    }
    atomic_json(folder / 'fusion-handoff.json', record)
    (folder / 'fusion-adapter.py').write_text(script, encoding='utf-8')
    return {
        'subject_digest': subject_digest,
        'adapter_version': ADAPTER_VERSION,
        'adapter_sha256': adapter_sha256,
        'handoff_digest': script_payload['handoff_digest'],
        'allow_save': False,
        'handoff': handoff.model_dump(),
        'script': script,
        'fusion_mcp': {'featureType': 'script', 'object': {'script': script}},
        'instructions': 'Pass script to fusion_mcp_execute unchanged. Do not invent Fusion API. Do not save f3d. Return printed JSON to brain_fusion_ingest.',
        'live_fusion_not_witnessed': True,
    }


def remesure_report(recipe: Recipe, folder: Path, issued: FusionHandoff, report: FusionReport) -> dict[str, Any]:
    import cadquery as cq
    by_name = {o.occurrence: o for o in report.occurrences}
    if set(by_name) != {o.occurrence for o in issued.occurrences}:
        raise BrainError('FUSION_OCCURRENCES', 'Fusion report occurrences must match the issued handoff.')
    part_shapes = {}
    for occ in issued.occurrences:
        placed = by_name[occ.occurrence]
        if occ.protected and not _identity_pose(placed):
            raise BrainError('FUSION_PROTECTED', 'Protected occurrence pose must stay fixed.', {'occurrence': occ.occurrence})
        step = safe_path(folder, occ.step_relative_path)
        if file_hash(step) != occ.sha256:
            raise BrainError('STUDIO_CHANGED', 'Part STEP changed before remesure.', {'part': occ.part_id})
        vals = cq.importers.importStep(str(step)).vals()
        body = vals[0] if len(vals) == 1 else cq.Compound.makeCompound(vals)
        if not _identity_pose(placed):
            body = apply_rigid_mm(body, placed.translation_mm, placed.rotation_axis, placed.rotation_deg, placed.rotation_origin_mm)
        if not body.isValid() or not body.Solids():
            raise BrainError('STUDIO_INVALID_SOLID', 'Remesure produced an empty/invalid solid.', {'part': occ.part_id})
        part_shapes[occ.part_id] = body
    return evaluate_geometry(recipe, part_shapes)


def ingest_report(studio, project_id: str, revision: int, subject_digest: str, adapter_sha256: str,
                  fusion_report: dict[str, Any], export_step_relative: str | None = None) -> dict[str, Any]:
    target, info = studio._subject(project_id, revision, subject_digest)
    payload = info['payload']
    if payload.get('kind') != 'recipe_build':
        raise BrainError('FUSION_SUBJECT', 'Fusion ingest requires a built recipe subject.')
    folder = _build_folder(studio, payload)
    issued_path = folder / 'fusion-handoff.json'
    if not issued_path.is_file():
        raise BrainError('FUSION_HANDOFF', 'Issue brain_fusion_handoff before ingest.')
    issued_record = json_load(issued_path)
    if adapter_sha256 != issued_record['adapter_sha256']:
        raise BrainError('FUSION_ADAPTER', 'Only the issued Fusion adapter script is accepted.',
                         {'expected': issued_record['adapter_sha256']})
    report = FusionReport.model_validate(fusion_report)
    if report.handoff_digest != issued_record['handoff_digest']:
        raise BrainError('FUSION_HANDOFF', 'Fusion report does not echo the issued handoff digest.')
    if report.saved:
        raise BrainError('FUSION_SAVE', 'This adapter does not save f3d.')
    issued = FusionHandoff.model_validate(issued_record['handoff'])
    recipe = Recipe.model_validate(json_load(folder / 'recipe.json'))
    measured = remesure_report(recipe, folder, issued, report)
    export_info = None
    if export_step_relative:
        export_path = safe_path(studio.brain.store.root, export_step_relative)
        export_info = {'relative_path': export_step_relative, 'sha256': file_hash(export_path), 'bytes': export_path.stat().st_size}
    record = {
        'subject_digest': subject_digest,
        'adapter_sha256': adapter_sha256,
        'handoff_digest': issued_record['handoff_digest'],
        'fusion_report': report.model_dump(),
        'export_step': export_info,
        'checks': measured['checks'],
        'geometry_checks_verdict': measured['geometry_checks_verdict'],
        'overall_verdict': 'unknown',
        'live_fusion_not_witnessed': True,
        'notes': ['CadQuery remesured the issued STEPs at the reported rigid poses.',
                  'A Fusion screenshot or successful import is not a geometry pass.',
                  'f3d was not saved by cadMCP.'],
    }
    atomic_json(folder / 'fusion-ingest.json', record)
    return {
        'subject_digest': subject_digest,
        'geometry_checks_verdict': measured['geometry_checks_verdict'],
        'overall_verdict': 'unknown',
        'checks': measured['checks'],
        'export_step': export_info,
        'canonical_backend_modified': False,
        'f3d_saved': False,
    }
