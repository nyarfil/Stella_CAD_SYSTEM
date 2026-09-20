"""Supplemental acceptance preserves source evidence and adds a fresh oracle."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
from pydantic import ValidationError

cq = pytest.importorskip("cadquery", reason="Supplemental acceptance requires the real CAD kernel.")

from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.req2cad.common import atomic_json, digest, file_hash, json_load
from cadmcp_brain.studio.acceptance import AcceptanceSpec,inspect_step
from cadmcp_brain.studio.runtime import ROLES, Studio
from cadmcp_brain.studio.supplement import _delivery_manifest,supplement_subject_digest, verify_artifact


REQUEST = "Create a 10 x 5 x 2 mm rectangular verification solid."


class NoReferences:
    def evidence(self, uid):  # pragma: no cover - references are deliberately absent
        raise AssertionError(f"unexpected reference lookup: {uid}")


def acceptance_spec(request=REQUEST):
    return {
        "schema_version": 1,
        "case_id": "box_acceptance",
        "original_request": request,
        "expected_solids": 1,
        "lower_mm": [0.0, 0.0, 0.0],
        "upper_mm": [10.0, 5.0, 2.0],
        "coordinate_tolerance_mm": 1e-6,
        "volume_mm3": 100.0,
        "volume_tolerance_mm3": 1e-6,
        "regions": [],
        "expected_prism": {
            "points_mm": [[0.0, 0.0], [10.0, 0.0], [10.0, 5.0], [0.0, 5.0]],
            "z_min_mm": 0.0,
            "z_max_mm": 2.0,
            "max_symmetric_difference_mm3": 1e-6,
        },
        "unverified_requirements": ["Original load case remains unknown.", "Material performance and production remain unverified."],
    }


def source_subject(tmp_path: Path, *, geometry_verdict="pass", output_mode="valid"):
    brain = Brain(tmp_path / "workspace")
    brain.open("supplement-test", REQUEST)
    studio = Studio(brain, NoReferences())
    snapshot = studio._snapshot("supplement-test", 0)
    context = {
        "snapshot": snapshot,
        "recipe": {"title": "Test box", "original_request": REQUEST},
        "reference_digests": {},
        "lineage": {"baseline_subject_digest": None, "is_correction": False},
        "protection": {},
    }
    attempt_id = "a" * 32
    subject = digest({"context": context, "attempt_id": attempt_id})
    folder = studio.root / "supplement-test" / "source-build"
    folder.mkdir(parents=True)
    assembly_shape=cq.Workplane("XY").box(10, 5, 2, centered=(False, False, False)).val()
    cq.exporters.export(assembly_shape,str(folder / "assembly.step"))
    (folder/'body').mkdir()
    part_shape=(cq.Workplane('XY').box(9,5,2,centered=(False,False,False)).val()
                if output_mode=='different' else assembly_shape)
    cq.exporters.export(part_shape,str(folder/'body'/'model.step'))
    check = {"id": "source_dimension", "verdict": geometry_verdict,
             "actual": 10.0, "expected": 10.0}
    measurements = {
        "geometry_checks_verdict": geometry_verdict,
        "checks": [check],
        "unverified_requirements": ["Original load case remains unknown."],
        "assembly": {"relative_path": "assembly.step", "sha256": file_hash(folder / "assembly.step")},
        "artifact_pointer": str(folder / "assembly.step"),
        "outputs": {} if output_mode=='empty' else {
            'body':{'features':{},'exports':{'model.step':{
                'relative_path':'missing/model.step' if output_mode=='unregistered' else 'body/model.step',
                'sha256':'0'*64 if output_mode=='unregistered' else file_hash(folder/'body'/'model.step')}}}},
    }
    atomic_json(folder / "measurements.json", measurements)
    atomic_json(folder / "recipe.json", context["recipe"])
    manifest = {path.relative_to(folder).as_posix(): file_hash(path)
                for path in folder.rglob("*") if path.is_file()}
    record = {
        "subject_digest": subject,
        "kind": "recipe_build",
        "context": context,
        "measurements": measurements,
        "attempt_id": attempt_id,
        "recipe_context_digest": digest(context),
        "folder": str(folder),
        "file_hashes": manifest,
    }
    atomic_json(folder / "build-record.json", record)
    record["build_record_sha256"] = file_hash(folder / "build-record.json")
    studio.register_subject("supplement-test", 0, subject, record)
    return studio, subject, folder, copy.deepcopy(record)


def test_supplement_remeasures_copy_and_registers_fresh_unreviewed_subject(tmp_path):
    studio, source, source_folder, source_record = source_subject(tmp_path)
    source_hashes = {path.relative_to(source_folder).as_posix(): file_hash(path)
                     for path in source_folder.rglob("*") if path.is_file()}

    result = verify_artifact(studio, "supplement-test", 0, source, acceptance_spec(), 60)

    derived_folder = Path(result["folder"])
    _, info = studio._subject("supplement-test", 0, result["subject_digest"])
    payload = info["payload"]
    status = studio.status("supplement-test", 0, result["subject_digest"])
    packet = studio.packet("supplement-test", 0, result["subject_digest"], "verification")
    assert result["geometry_checks_verdict"] == "pass"
    assert result["supplemental_geometry_acceptance"] == "pass"
    assert result["cad_regenerated"] is False
    assert status["reports"] == 0 and status["reviewed_roles"] == []
    assert status['evidence_state']==packet['subject']['payload']['evidence_state']
    assert {item['origin'] for item in status['evidence_state']['current_observations']}=={
        'source_check','supplemental_check'}
    assert {item['provenance']['relative_path'] for item in status['evidence_state']['current_observations']}=={
        'source-measurements.json','supplement-report.json'}
    assert status["missing_roles"] == sorted(ROLES)
    assert payload["recipe_context_digest"] == source_record["recipe_context_digest"]
    assert payload["source_subject_digest"] == source
    assert payload["supplement"]["cad_regenerated"] is False
    assert payload["supplement"]["base_build_record_sha256"] == source_record["build_record_sha256"]
    assert set(payload["supplement"]["evaluator_file_hashes"]) == {
        "acceptance.py", "measurement.py",'recipe.py','supplement.py'}
    assert payload['supplement']['contract_version']==2
    assert payload['supplement']['delivery_consistency_required'] is True
    assert payload["supplement"]["source_review_status"] == {
        "open_blockers": [], "revision_requested_roles": []}
    assert payload["measurements"]["checks"] == source_record["measurements"]["checks"]
    assert payload["measurements"]["unverified_requirements"] == source_record["measurements"]["unverified_requirements"]
    assert payload["measurements"]["supplemental_acceptance"]["geometry_acceptance"] == "pass"
    delivery=payload['measurements']['supplemental_acceptance']['delivery_consistency']
    assert delivery['verified'] is True and delivery['verdict']=='pass'
    assert delivery['check']['id']=='_system-delivery-step-geometry-consistency'
    assert delivery['check']['passed'] is True
    assert status['delivery_step_consistency']==delivery
    assert payload["measurements"]["artifact_pointer"] == str(derived_folder / "assembly.step")
    assert json_load(derived_folder / "source-measurements.json") == source_record["measurements"]
    assert file_hash(derived_folder / "source-build-record.json") == source_record["build_record_sha256"]
    assert (derived_folder / "supplement-spec.json").is_file()
    assert (derived_folder / "supplement-report.json").is_file()
    assert (derived_folder / 'delivery-manifest.json').is_file()
    assert all(file_hash(derived_folder / name) == sha for name, sha in payload["file_hashes"].items())
    assert source_hashes == {path.relative_to(source_folder).as_posix(): file_hash(path)
                             for path in source_folder.rglob("*") if path.is_file()}

    with pytest.raises(BrainError, match="cannot be supplemented again"):
        verify_artifact(studio, "supplement-test", 0, result["subject_digest"], acceptance_spec(), 60)


def test_source_geometry_failure_cannot_be_overwritten_by_passing_supplement(tmp_path):
    studio, source, _, _ = source_subject(tmp_path, geometry_verdict="fail")
    result = verify_artifact(studio, "supplement-test", 0, source, acceptance_spec(), 60)
    _, info = studio._subject("supplement-test", 0, result["subject_digest"])
    assert result["supplemental_geometry_acceptance"] == "pass"
    assert result["geometry_checks_verdict"] == "fail"
    assert info["payload"]["measurements"]["checks"][0]["verdict"] == "fail"


def test_spec_request_strictness_timeout_and_stale_source_are_rejected(tmp_path):
    studio, source, folder, _ = source_subject(tmp_path)
    wrong = acceptance_spec("A different request")
    with pytest.raises(BrainError, match="exactly match"):
        verify_artifact(studio, "supplement-test", 0, source, wrong)
    extra = acceptance_spec()
    extra["invented"] = True
    with pytest.raises(ValidationError):
        verify_artifact(studio, "supplement-test", 0, source, extra)
    missing_unknown=acceptance_spec()
    missing_unknown['unverified_requirements']=['Only a different unknown.']
    with pytest.raises(BrainError,match='retain all source'):
        verify_artifact(studio,'supplement-test',0,source,missing_unknown)
    with pytest.raises(BrainError, match=r"\[5, 300\]"):
        verify_artifact(studio, "supplement-test", 0, source, acceptance_spec(), 4)
    with (folder / "assembly.step").open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(BrainError, match="changed"):
        verify_artifact(studio, "supplement-test", 0, source, acceptance_spec())


def test_changed_registered_part_step_is_rejected(tmp_path):
    studio,source,folder,_=source_subject(tmp_path)
    with (folder/'body'/'model.step').open('ab') as stream:
        stream.write(b'tampered part')
    with pytest.raises(BrainError,match='evidence changed'):
        verify_artifact(studio,'supplement-test',0,source,acceptance_spec())


def test_subject_identity_binds_each_attempt_nonce():
    common = ("a" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64)
    assert supplement_subject_digest(*common, "1" * 32) != \
        supplement_subject_digest(*common, "2" * 32)


def test_additional_failure_prevents_combined_pass(tmp_path):
    studio, source, _, _ = source_subject(tmp_path)
    spec=acceptance_spec()
    spec['volume_mm3']=101.0
    result=verify_artifact(studio,'supplement-test',0,source,spec,60)
    assert result['supplemental_geometry_acceptance']=='fail'
    assert studio.status('supplement-test',0,result['subject_digest'])['geometry_checks_verdict']=='fail'


def test_delivery_difference_prevents_supplement_pass(tmp_path):
    studio,source,_,_=source_subject(tmp_path,output_mode='different')
    result=verify_artifact(studio,'supplement-test',0,source,acceptance_spec(),60)
    assert result['supplemental_geometry_acceptance']=='fail'
    _,info=studio._subject('supplement-test',0,result['subject_digest'])
    delivery=info['payload']['measurements']['supplemental_acceptance']['delivery_consistency']
    assert delivery['verdict']=='fail' and delivery['check']['passed'] is False


@pytest.mark.parametrize('mode',['empty','unregistered'])
def test_missing_or_unregistered_part_delivery_is_rejected_before_worker(tmp_path,mode,monkeypatch):
    import cadmcp_brain.studio.supplement as module
    studio,source,_,_=source_subject(tmp_path,output_mode=mode)
    monkeypatch.setattr(module.subprocess,'run',lambda *args,**kwargs:pytest.fail('worker must not run'))
    with pytest.raises(BrainError,match='output model STEP|at least one output|exactly match source file_hashes'):
        verify_artifact(studio,'supplement-test',0,source,acceptance_spec(),60)


def test_delivery_registration_missing_required_key_is_typed_rejection():
    bad_entry={'relative_path':'body/model.step','invented':'b'*64}
    payload={'measurements':{
        'assembly':{'relative_path':'assembly.step','sha256':'a'*64},
        'outputs':{'body':{'exports':{'model.step':bad_entry}}}}}
    manifest={'assembly.step':'a'*64,'body/model.step':'b'*64}
    with pytest.raises(BrainError,match='must register model.step'):
        _delivery_manifest(payload,manifest)


@pytest.mark.parametrize('mutation',['boolean_version','invalid_sha'])
def test_worker_delivery_manifest_is_strictly_typed(tmp_path,mutation):
    shape=cq.Workplane('XY').box(10,5,2,centered=(False,False,False)).val()
    assembly=tmp_path/'assembly.step';part=tmp_path/'part.step'
    cq.exporters.export(shape,str(assembly));cq.exporters.export(shape,str(part))
    manifest={'schema_version':1,
              'assembly':{'relative_path':'assembly.step','sha256':file_hash(assembly)},
              'parts':{'body':{'relative_path':'part.step','sha256':file_hash(part)}}}
    if mutation=='boolean_version':manifest['schema_version']=True
    else:manifest['parts']['body']['sha256']='not-a-hash'
    path=tmp_path/'delivery-manifest.json';atomic_json(path,manifest)
    with pytest.raises(BrainError,match='strict internal schema|entries are invalid'):
        inspect_step(assembly,AcceptanceSpec.model_validate(acceptance_spec()),path,file_hash(path))


def test_new_contract_flags_cannot_be_removed_to_claim_legacy_compatibility(tmp_path):
    studio,source,_,_=source_subject(tmp_path)
    result=verify_artifact(studio,'supplement-test',0,source,acceptance_spec(),60)
    _,info=studio._subject('supplement-test',0,result['subject_digest'])
    payload=copy.deepcopy(info['payload'])
    payload['supplement'].pop('contract_version')
    payload['supplement'].pop('delivery_consistency_required')
    with pytest.raises(BrainError,match='cannot be downgraded'):
        studio._validate_supplement(payload,Path(result['folder']),result['subject_digest'])


def test_changed_delivery_report_cannot_be_reclassified_as_pass(tmp_path):
    studio,source,_,_=source_subject(tmp_path,output_mode='different')
    result=verify_artifact(studio,'supplement-test',0,source,acceptance_spec(),60)
    folder=Path(result['folder']);report=json_load(folder/'supplement-report.json')
    report['delivery_consistency']['verdict']='pass'
    report['delivery_consistency']['check']['passed']=True
    next(item for item in report['checks'] if item['id']=='_system-delivery-step-geometry-consistency')['passed']=True
    atomic_json(folder/'supplement-report.json',report)
    with pytest.raises(BrainError,match='evidence changed'):
        studio._subject('supplement-test',0,result['subject_digest'])


def test_revalidation_rejects_changed_inherited_and_supplemental_claims(tmp_path):
    studio, source, _, _ = source_subject(tmp_path)
    result=verify_artifact(studio,'supplement-test',0,source,acceptance_spec(),60)
    _,info=studio._subject('supplement-test',0,result['subject_digest'])
    for mutation in ('checks','unknowns','additional'):
        payload=copy.deepcopy(info['payload'])
        if mutation=='checks':payload['measurements']['checks']=[]
        if mutation=='unknowns':payload['measurements']['unverified_requirements']=[]
        if mutation=='additional':payload['measurements']['supplemental_acceptance']['checks']=[]
        with pytest.raises(BrainError,match='preserves'):
            studio._validate_supplement(payload,Path(result['folder']),result['subject_digest'])


def test_timeout_does_not_register_a_derived_subject(tmp_path,monkeypatch):
    import subprocess
    import cadmcp_brain.studio.supplement as module
    studio, source, _, _=source_subject(tmp_path)
    def expire(command,**kwargs):
        assert '--worker' in command  # No nested CAD subprocess left behind.
        raise subprocess.TimeoutExpired(command,kwargs['timeout'])
    monkeypatch.setattr(module.subprocess,'run',expire)
    with pytest.raises(BrainError,match='bounded runtime'):
        verify_artifact(studio,'supplement-test',0,source,acceptance_spec(),5)
    assert studio.attempts('supplement-test')['total_subjects']==1


def test_copy_budget_stops_before_running_a_worker(tmp_path,monkeypatch):
    import cadmcp_brain.studio.supplement as module
    studio, source, _, _=source_subject(tmp_path)
    monkeypatch.setattr(module,'MAX_COPY_BYTES',1)
    with pytest.raises(BrainError,match='copy budget'):
        verify_artifact(studio,'supplement-test',0,source,acceptance_spec(),5)
    assert studio.attempts('supplement-test')['total_subjects']==1
