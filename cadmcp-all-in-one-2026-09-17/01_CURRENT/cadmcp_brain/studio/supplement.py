"""Hash-bound supplemental acceptance for an existing Studio CAD artifact.

The source Recipe is never executed here.  A derived review subject receives
byte-identical copies of the registered evidence and independently reimports
the copied assembly STEP through the bounded acceptance CLI.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from ..errors import BrainError
from ..req2cad.common import atomic_json, bounded_int, digest, file_hash, json_load
from ..util import safe_id, safe_path
from .acceptance import AcceptanceSpec


SPEC_NAME = "supplement-spec.json"
REPORT_NAME = "supplement-report.json"
SOURCE_RECORD_NAME = "source-build-record.json"
SOURCE_MEASUREMENTS_NAME = "source-measurements.json"
DELIVERY_MANIFEST_NAME = "delivery-manifest.json"
MAX_COPY_BYTES = 512 * 1024 * 1024
MAX_COPY_FILES = 4096
_SHA256 = re.compile(r"[0-9a-f]{64}")
_RESERVED = {SPEC_NAME, REPORT_NAME, SOURCE_RECORD_NAME, SOURCE_MEASUREMENTS_NAME, DELIVERY_MANIFEST_NAME,
             "build-record.json"}


def supplement_subject_digest(source_subject_digest: str, base_build_record_sha256: str,
                              source_manifest_digest: str, spec_digest: str,
                              report_sha256: str, attempt_id: str) -> str:
    """Canonical derived-subject identity shared with runtime revalidation."""
    return digest({
        "kind": "recipe_build_supplement_v1",
        "source_subject_digest": source_subject_digest,
        "base_build_record_sha256": base_build_record_sha256,
        "source_manifest_digest": source_manifest_digest,
        "acceptance_spec_digest": spec_digest,
        "report_sha256": report_sha256,
        "attempt_id": attempt_id,
    })


def _source_folder(studio, payload: dict) -> Path:
    raw = payload.get("folder")
    if not isinstance(raw, str) or not raw:
        raise BrainError("STUDIO_SUPPLEMENT_SOURCE", "Source build has no artifact folder.")
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            relative = candidate.relative_to(studio.root)
        except ValueError as exc:
            raise BrainError("STUDIO_PATH", "Source build is outside the Studio workspace.") from exc
        folder = safe_path(studio.root, relative.as_posix())
    else:
        folder = safe_path(studio.root, raw)
    if folder.is_symlink() or not folder.is_dir():
        raise BrainError("STUDIO_PATH", "Source build folder must be a real Studio directory.")
    return folder


def _validated_manifest(folder: Path, payload: dict) -> tuple[dict[str, str], int]:
    manifest = payload.get("file_hashes")
    if not isinstance(manifest, dict) or not manifest or len(manifest) > MAX_COPY_FILES:
        raise BrainError("STUDIO_SUPPLEMENT_MANIFEST", "Source file manifest is missing or exceeds the copy budget.")
    if not {"assembly.step", "measurements.json", "recipe.json"} <= set(manifest):
        raise BrainError("STUDIO_SUPPLEMENT_MANIFEST", "Source manifest must bind assembly.step, measurements.json and recipe.json.")
    total = 0
    checked: dict[str, str] = {}
    for name, expected in manifest.items():
        if not isinstance(name, str) or name in _RESERVED or not isinstance(expected, str) or not _SHA256.fullmatch(expected):
            raise BrainError("STUDIO_SUPPLEMENT_MANIFEST", "Source manifest contains an invalid or reserved entry.", {"path": name})
        source = safe_path(folder, name)
        if not source.is_file():
            raise BrainError("STUDIO_CHANGED", "A source evidence file is missing.", {"path": name})
        total += source.stat().st_size
        if total > MAX_COPY_BYTES:
            raise BrainError("STUDIO_SUPPLEMENT_SIZE", "Source evidence exceeds the supplemental copy budget.")
        if file_hash(source) != expected:
            raise BrainError("STUDIO_CHANGED", "Source evidence changed before supplemental verification.", {"path": name})
        checked[name] = expected
    return checked, total


def _copy_manifest(folder: Path, target: Path, manifest: dict[str, str]) -> None:
    for name, expected in manifest.items():
        source = safe_path(folder, name)
        destination = safe_path(target, name, must_exist=False)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if file_hash(destination) != expected:
            raise BrainError("STUDIO_SUPPLEMENT_COPY", "Copied evidence does not match its registered hash.", {"path": name})


def _verify_copies(target: Path, manifest: dict[str, str]) -> None:
    for name, expected in manifest.items():
        if file_hash(safe_path(target, name)) != expected:
            raise BrainError("STUDIO_SUPPLEMENT_COPY", "Copied evidence changed during supplemental verification.", {"path": name})


def _rebase_paths(value, source_folder: Path, target_folder: Path):
    """Move absolute artifact pointers to the derived folder without touching claims."""
    if isinstance(value, dict):
        return {key: _rebase_paths(item, source_folder, target_folder) for key, item in value.items()}
    if isinstance(value, list):
        return [_rebase_paths(item, source_folder, target_folder) for item in value]
    if not isinstance(value, str):
        return value
    source_text = str(source_folder.resolve())
    for separator in ("\\", "/"):
        prefix = source_text.replace("\\", separator).rstrip(separator)
        candidate = value.replace("\\", separator)
        if candidate == prefix:
            return str(target_folder.resolve())
        if candidate.startswith(prefix + separator):
            relative = candidate[len(prefix) + 1:].replace("\\", "/")
            return str(safe_path(target_folder, relative, must_exist=False).resolve())
    return value


def _evaluator_hashes() -> dict[str, str]:
    from . import acceptance, measurement, recipe, supplement
    return {
        "acceptance.py": file_hash(Path(acceptance.__file__).resolve()),
        "measurement.py": file_hash(Path(measurement.__file__).resolve()),
        "recipe.py": file_hash(Path(recipe.__file__).resolve()),
        "supplement.py": file_hash(Path(supplement.__file__).resolve()),
    }


def _delivery_manifest(payload: dict, manifest: dict[str,str]) -> dict:
    measurements=payload.get('measurements')
    outputs=measurements.get('outputs') if isinstance(measurements,dict) else None
    if not isinstance(outputs,dict) or not outputs:
        raise BrainError('STUDIO_SUPPLEMENT_DELIVERY','Source build must register at least one output model STEP.')
    assembly=measurements.get('assembly')
    if not isinstance(assembly,dict) or not {'relative_path','sha256'} <= set(assembly):
        raise BrainError('STUDIO_SUPPLEMENT_DELIVERY','Source assembly registration is incomplete.')
    result={'schema_version':1,'assembly':{'relative_path':assembly['relative_path'],'sha256':assembly['sha256']},
            'parts':{}}
    for part_id,output in outputs.items():
        safe_id(part_id)
        exports=output.get('exports') if isinstance(output,dict) else None
        entry=exports.get('model.step') if isinstance(exports,dict) else None
        if not isinstance(entry,dict) or not {'relative_path','sha256'} <= set(entry):
            raise BrainError('STUDIO_SUPPLEMENT_DELIVERY','Every source output must register model.step.',{'part_id':part_id})
        result['parts'][part_id]={'relative_path':entry['relative_path'],'sha256':entry['sha256']}
    for entry in [result['assembly'],*result['parts'].values()]:
        path=entry['relative_path'];sha=entry['sha256']
        if not isinstance(path,str) or manifest.get(path)!=sha:
            raise BrainError('STUDIO_SUPPLEMENT_DELIVERY','Delivery STEP registration must exactly match source file_hashes.',{'path':path})
    return result


def verify_artifact(studio, project_id: str, revision: int, source_subject_digest: str,
                    spec: dict, timeout_seconds: int = 60) -> dict:
    """Create a derived recipe-build subject with independent STEP acceptance."""
    bounded_int(timeout_seconds, 5, 300, "timeout_seconds")
    safe_id(project_id)
    if type(spec) is not dict:
        raise BrainError("STUDIO_SUPPLEMENT_SPEC", "spec must be a strict AcceptanceSpec object.")
    accepted_spec = AcceptanceSpec.model_validate(spec)

    _, source_info = studio._subject(project_id, revision, source_subject_digest)
    source_payload = source_info.get("payload", {})
    if source_payload.get("kind") != "recipe_build":
        raise BrainError("STUDIO_SUPPLEMENT_SOURCE", "Supplemental acceptance requires a recipe_build subject.")
    if source_payload.get("supplement") or source_payload.get("source_subject_digest") or \
            source_payload.get("measurements", {}).get("supplemental_acceptance"):
        raise BrainError("STUDIO_SUPPLEMENT_RECURSIVE", "A supplemental subject cannot be supplemented again.")
    base_record_sha = source_payload.get("build_record_sha256")
    if not isinstance(base_record_sha, str) or not _SHA256.fullmatch(base_record_sha):
        raise BrainError("STUDIO_SUPPLEMENT_SOURCE", "Source build must have a registered build-record byte hash.")
    recipe = source_payload.get("context", {}).get("recipe")
    original_request = recipe.get("original_request") if isinstance(recipe, dict) else None
    project_request = "\n\n".join(item["text"] for item in source_info["snapshot"]["sources"])
    if not isinstance(original_request, str) or original_request != project_request:
        raise BrainError("STUDIO_REQUEST", "Source Recipe no longer exactly preserves the project request.")
    if accepted_spec.original_request != original_request:
        raise BrainError("STUDIO_REQUEST", "AcceptanceSpec original_request must exactly match the source Recipe.")
    inherited_unknowns = source_payload.get('measurements',{}).get('unverified_requirements',[])
    if not set(inherited_unknowns) <= set(accepted_spec.unverified_requirements):
        raise BrainError('STUDIO_SUPPLEMENT_SCOPE', 'Additional criteria must retain all source unverified requirements; new uncertainties may be added.')
    if source_payload.get("recipe_context_digest") != digest(source_payload["context"]):
        raise BrainError("STUDIO_CHANGED", "Source Recipe context digest does not match its registered context.")

    source_folder = _source_folder(studio, source_payload)
    manifest, _ = _validated_manifest(source_folder, source_payload)
    source_manifest_digest = digest(manifest)
    source_measurements_path = safe_path(source_folder, "measurements.json")
    if json_load(source_measurements_path) != source_payload.get("measurements"):
        raise BrainError("STUDIO_CHANGED", "Source measurements file does not match the registered subject payload.")
    if json_load(safe_path(source_folder, "recipe.json")) != recipe:
        raise BrainError("STUDIO_CHANGED", "Source recipe file does not match the registered Recipe context.")
    source_assembly_hash = manifest["assembly.step"]
    registered_assembly_hash = source_payload.get("measurements", {}).get("assembly", {}).get("sha256")
    if registered_assembly_hash != source_assembly_hash:
        raise BrainError("STUDIO_CHANGED", "Source assembly hash disagrees with registered measurements.")
    delivery_manifest=_delivery_manifest(source_payload,manifest)
    source_record_path = source_folder / "build-record.json"
    if file_hash(source_record_path) != base_record_sha:
        raise BrainError("STUDIO_CHANGED", "Source build-record bytes changed before supplemental verification.")

    parent = studio.root / safe_id(project_id)
    parent.mkdir(parents=True, exist_ok=True)
    attempt_id = uuid.uuid4().hex
    folder = parent / ("supplement-" + attempt_id)
    folder.mkdir()
    _copy_manifest(source_folder, folder, manifest)
    shutil.copyfile(source_record_path, folder / SOURCE_RECORD_NAME)
    shutil.copyfile(source_measurements_path, folder / SOURCE_MEASUREMENTS_NAME)
    if file_hash(folder / SOURCE_RECORD_NAME) != base_record_sha or \
            file_hash(folder / SOURCE_MEASUREMENTS_NAME) != manifest["measurements.json"]:
        raise BrainError("STUDIO_SUPPLEMENT_COPY", "Source audit copies do not match the registered bytes.")

    atomic_json(folder / SPEC_NAME, accepted_spec.model_dump())
    atomic_json(folder / DELIVERY_MANIFEST_NAME, delivery_manifest)
    spec_sha = file_hash(folder / SPEC_NAME)
    delivery_manifest_sha=file_hash(folder / DELIVERY_MANIFEST_NAME)
    delivery_manifest_digest=digest(delivery_manifest)
    spec_digest = digest(accepted_spec.model_dump())
    evaluator_hashes = _evaluator_hashes()
    command = [sys.executable, "-m", "cadmcp_brain.studio.acceptance",
               "--worker", "--spec", str(folder / SPEC_NAME), "--spec-sha256", spec_sha,
               "--step", str(folder / "assembly.step"), "--report", str(folder / REPORT_NAME),
               "--delivery-manifest",str(folder / DELIVERY_MANIFEST_NAME),
               "--delivery-manifest-sha256",delivery_manifest_sha,
               "--timeout", str(timeout_seconds)]
    try:
        process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        atomic_json(folder / "supplement-timeout.json", {"timeout_seconds": timeout_seconds,
                                                          "source_subject_digest": source_subject_digest})
        raise BrainError("STUDIO_SUPPLEMENT_TIMEOUT", "Supplemental acceptance exceeded its bounded runtime.",
                         {"folder": str(folder)}) from exc
    (folder / "supplement.stderr.log").write_text(process.stderr, encoding="utf-8")
    if process.returncode not in (0, 1) or not (folder / REPORT_NAME).is_file():
        raise BrainError("STUDIO_SUPPLEMENT_WORKER", "Supplemental acceptance did not produce a valid report.",
                         {"returncode": process.returncode, "stderr": process.stderr[-2000:], "folder": str(folder)})
    try:
        stdout_report = json.loads(process.stdout)
        report = json_load(folder / REPORT_NAME)
    except (ValueError, OSError) as exc:
        raise BrainError("STUDIO_SUPPLEMENT_REPORT", "Supplemental acceptance report is unreadable.") from exc
    if stdout_report != report:
        raise BrainError("STUDIO_SUPPLEMENT_REPORT", "CLI output and saved supplemental report disagree.")
    if (report.get("acceptance_spec_file_sha256") != spec_sha or
            report.get("acceptance_spec_digest") != spec_digest or
            report.get("original_request") != original_request or
            report.get("step_sha256") != source_assembly_hash or
            report.get("geometry_acceptance") not in {"pass", "fail"}):
        raise BrainError("STUDIO_SUPPLEMENT_REPORT", "Supplemental report is not bound to the fixed inputs.")
    report_checks = report.get("checks")
    delivery=report.get('delivery_consistency')
    delivery_checks=[item for item in report_checks or []
                     if item.get('id')=='_system-delivery-step-geometry-consistency']
    delivery_check=delivery_checks[0] if len(delivery_checks)==1 else None
    expected_step_hashes={'assembly':delivery_manifest['assembly']['sha256'],
                          'parts':{part_id:entry['sha256'] for part_id,entry in delivery_manifest['parts'].items()}}
    expected_returncode = 0 if report["geometry_acceptance"] == "pass" else 1
    if (process.returncode != expected_returncode or not isinstance(report_checks, list) or not report_checks or
            any(not isinstance(item, dict) or type(item.get("passed")) is not bool for item in report_checks) or
            (report["geometry_acceptance"] == "pass") != all(item["passed"] for item in report_checks) or
            report.get("overall_verdict") != "unknown" or
            report.get("physical_performance_certified") is not False or
            report.get("unverified_requirements") != accepted_spec.unverified_requirements or
            not isinstance(delivery,dict) or delivery.get('verified') is not True or
            delivery.get('verdict') not in {'pass','fail'} or
            delivery.get('manifest_file_sha256')!=delivery_manifest_sha or
            delivery.get('manifest_digest')!=delivery_manifest_digest or
            delivery.get('step_hashes')!=expected_step_hashes or
            delivery_check is None or delivery.get('check')!=delivery_check or
            delivery_check.get('verdict')!=delivery.get('verdict') or
            delivery_check.get('passed') is not (delivery.get('verdict')=='pass') or
            (report['geometry_acceptance']=='pass' and delivery.get('verdict')!='pass')):
        raise BrainError("STUDIO_SUPPLEMENT_REPORT", "Supplemental report verdict is internally inconsistent.")
    if (file_hash(folder / SPEC_NAME) != spec_sha or
            file_hash(folder / DELIVERY_MANIFEST_NAME)!=delivery_manifest_sha or
            _evaluator_hashes() != evaluator_hashes):
        raise BrainError("STUDIO_SUPPLEMENT_CHANGED", "Acceptance specification or evaluator changed during verification.")

    # Revalidate both the immutable source subject and every copied byte after
    # the worker.  Only measurements.json is changed below, after this proof.
    _verify_copies(folder, manifest)
    studio._subject(project_id, revision, source_subject_digest)
    source_review = studio.status(project_id, revision, source_subject_digest)
    source_review_status = {
        "open_blockers": copy.deepcopy(source_review["open_blockers"]),
        "revision_requested_roles": copy.deepcopy(source_review["revision_requested_roles"]),
    }
    if file_hash(source_record_path) != base_record_sha:
        raise BrainError("STUDIO_CHANGED", "Source build record changed during supplemental verification.")

    report_sha = file_hash(folder / REPORT_NAME)
    measurements = _rebase_paths(copy.deepcopy(source_payload["measurements"]), source_folder, folder)
    inherited_checks = copy.deepcopy(source_payload["measurements"].get("checks", []))
    inherited_unknowns = copy.deepcopy(source_payload["measurements"].get("unverified_requirements", []))
    measurements["supplemental_acceptance"] = {
        "source_subject_digest": source_subject_digest,
        "spec_path": SPEC_NAME,
        "spec_sha256": spec_sha,
        "report_path": REPORT_NAME,
        "report_sha256": report_sha,
        "geometry_acceptance": report["geometry_acceptance"],
        "geometry_acceptance_scope": report.get("geometry_acceptance_scope"),
        "checks": copy.deepcopy(report.get("checks", [])),
        "unverified_requirements": copy.deepcopy(report.get("unverified_requirements", [])),
        "overall_verdict": report.get("overall_verdict", "unknown"),
        "physical_performance_certified": False,
        "delivery_consistency": copy.deepcopy(delivery),
        "cad_regenerated": False,
    }
    original_geometry = source_payload["measurements"].get("geometry_checks_verdict")
    measurements["geometry_checks_verdict"] = (
        "pass" if original_geometry == "pass" and report["geometry_acceptance"] == "pass" else "fail"
    )
    # Existing inspection obligations remain byte-for-byte equivalent values;
    # a supplemental oracle is additional evidence, never a replacement.
    if measurements.get("checks", []) != inherited_checks or \
            measurements.get("unverified_requirements", []) != inherited_unknowns:
        raise BrainError("STUDIO_SUPPLEMENT_SCOPE", "Supplemental acceptance altered inherited checks or unknowns.")
    atomic_json(folder / "measurements.json", measurements)

    supplement = {
        "source_subject_digest": source_subject_digest,
        "spec_sha256": spec_sha,
        "report_sha256": report_sha,
        "cad_regenerated": False,
        "base_build_record_sha256": base_record_sha,
        "source_manifest_digest": source_manifest_digest,
        "source_measurements_sha256": manifest["measurements.json"],
        "evaluator_file_hashes": evaluator_hashes,
        "source_review_status": source_review_status,
        "contract_version": 2,
        "delivery_consistency_required": True,
        "delivery_manifest_sha256": delivery_manifest_sha,
        "delivery_manifest_digest": delivery_manifest_digest,
    }
    subject = supplement_subject_digest(source_subject_digest, base_record_sha,
                                        source_manifest_digest, spec_digest, report_sha, attempt_id)
    file_hashes = {path.relative_to(folder).as_posix(): file_hash(path)
                   for path in folder.rglob("*") if path.is_file()}
    record = {
        "subject_digest": subject,
        "kind": "recipe_build",
        "context": copy.deepcopy(source_payload["context"]),
        "measurements": measurements,
        "attempt_id": attempt_id,
        "recipe_context_digest": source_payload["recipe_context_digest"],
        "folder": str(folder),
        "file_hashes": file_hashes,
        "source_subject_digest": source_subject_digest,
        "acceptance_spec_digest": spec_digest,
        "supplement": supplement,
    }
    atomic_json(folder / "build-record.json", record)
    record["build_record_sha256"] = file_hash(folder / "build-record.json")
    studio.register_subject(project_id, revision, subject, record)
    return {
        "subject_digest": subject,
        "source_subject_digest": source_subject_digest,
        "folder": str(folder),
        "assembly_step": str(folder / "assembly.step"),
        "supplement_spec": str(folder / SPEC_NAME),
        "supplement_report": str(folder / REPORT_NAME),
        "geometry_checks_verdict": measurements["geometry_checks_verdict"],
        "supplemental_geometry_acceptance": report["geometry_acceptance"],
        "source_review_status": source_review_status,
        "cad_regenerated": False,
        "canonical_backend_modified": False,
        "overall_verdict": "unknown",
        "unverified_requirements": inherited_unknowns,
    }
