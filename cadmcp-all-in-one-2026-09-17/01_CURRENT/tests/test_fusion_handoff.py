"""Fusion handoff/ingest without a live Fusion session.

Kernel tests remesure CadQuery solids. They do not attest that Autodesk Fusion ran.
"""
import importlib.util
from pydantic import ValidationError
import pytest
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio.fusion import (
    ADAPTER_VERSION, FusionHandoff, FusionOccurrence, FusionReport, FusionReportOccurrence,
    adapter_payload, issue_script, remesure_report, render_adapter_script,
)
from cadmcp_brain.studio.recipe import Recipe
from cadmcp_brain.util import text_hash

HAS_CQ = importlib.util.find_spec('cadquery') is not None


def _origin_recipe(sha_a, sha_b):
    return {
        'schema_version': 1, 'title': 'Customer two-block fixture',
        'original_request': 'Place a spacer next to this imported block.',
        'units': 'mm', 'design_parameters': {}, 'parameter_basis': {},
        'functions': {'Keep': 'Keep the imported solid as the locating body.',
                      'Add': 'Add a second solid the customer asked for.'},
        'operations': [
            {'id': 'block', 'op': 'project_step', 'function_id': 'Keep',
             'reason': 'Customer-supplied STEP is the real locating geometry.',
             'artifact_id': 'Block', 'sha256': sha_a, 'role': 'protected_hardware',
             'unit_basis': 'Authored millimetre fixture; not physical hardware.'},
            {'id': 'spacer', 'op': 'project_step', 'function_id': 'Add',
             'reason': 'Second registered STEP is the designed neighbour.',
             'artifact_id': 'Spacer', 'sha256': sha_b, 'role': 'design_reference',
             'unit_basis': 'Authored millimetre fixture; not physical hardware.'},
        ],
        'outputs': [{'part_id': 'block', 'node': 'block'}, {'part_id': 'spacer', 'node': 'spacer'}],
        'clearance_checks': [{'id': 'gap', 'part_a': 'block', 'part_b': 'spacer', 'min_mm': 1.0}],
        'unverified_requirements': ['No Fusion document was open for this unit remesure.'],
    }


def test_recipe_project_step_is_sufficient_origin():
    Recipe.model_validate(_origin_recipe('a' * 64, 'b' * 64))


def test_recipe_without_import_or_explicit_design_basis_is_refused():
    with pytest.raises(ValidationError, match='explicit design basis and verification plan'):
        Recipe.model_validate({
            'schema_version': 1, 'title': 'Boxes only',
            'original_request': 'Just make two boxes from numbers.',
            'units': 'mm', 'functions': {'Make': 'Invent geometry with no imported solid.'},
            'operations': [{'id': 'a', 'op': 'box', 'function_id': 'Make',
                            'reason': 'A guessed box is not customer geometry.',
                            'size_mm': [10.0, 10.0, 10.0], 'center_mm': [0.0, 0.0, 0.0]}],
            'outputs': [{'part_id': 'a', 'node': 'a'}],
            'unverified_requirements': ['No real STEP was supplied.'],
        })


def test_protected_occurrence_cannot_carry_extra_pose():
    with pytest.raises(ValidationError, match='Protected'):
        FusionOccurrence(
            occurrence='pcb', part_id='pcb', step_relative_path='pcb/model.step',
            step_absolute_path='/tmp/pcb.step', sha256='c' * 64, protected=True,
            translation_mm=[1.0, 0.0, 0.0])


def test_adapter_script_is_versioned_and_refuses_save():
    occ = FusionOccurrence(
        occurrence='block', part_id='block', step_relative_path='block/model.step',
        step_absolute_path=r'E:\tmp\block.step', sha256='d' * 64, protected=True)
    handoff = FusionHandoff(subject_digest='e' * 64, occurrences=[occ], protected_occurrences=['block'])
    script, sha, payload = issue_script(handoff)
    assert sha == text_hash(script)
    assert payload['adapter_version'] == ADAPTER_VERSION
    assert payload['allow_save'] is False
    assert 'cadMCP adapter refuses save' in script
    assert 'mm_to_cm = 0.1' in script
    assert 'def run(_context: str):' in script
    assert 'except' not in script
    assert text_hash(render_adapter_script(adapter_payload(handoff))) == sha


def test_fusion_report_cannot_claim_save():
    with pytest.raises(ValidationError):
        FusionReport(handoff_digest='f' * 64, saved=True, occurrences=[
            FusionReportOccurrence(occurrence='block', translation_mm=[0.0, 0.0, 0.0])])


def test_ingest_rejects_wrong_adapter_sha(tmp_path):
    from cadmcp_brain.req2cad.common import atomic_json
    from cadmcp_brain.studio.fusion import ingest_report
    studio_root = tmp_path / 'studio'
    folder = studio_root / 'build'
    folder.mkdir(parents=True)
    atomic_json(folder / 'fusion-handoff.json', {
        'adapter_sha256': 'a' * 64, 'handoff_digest': 'b' * 64, 'handoff': {}})

    class Studio:
        root = studio_root
        def _subject(self, *_args):
            return folder, {'payload': {'kind': 'recipe_build', 'folder': str(folder)}}

    with pytest.raises(BrainError) as exc:
        ingest_report(Studio(), 'p', 0, 'c' * 64, 'd' * 64, {})
    assert exc.value.code == 'FUSION_ADAPTER'


def test_studio_schema_lists_fusion_handoff(tmp_path):
    from cadmcp_brain.api import Tools
    from cadmcp_brain.engine import Brain
    tools = Tools(Brain(tmp_path/'ws'))
    schema = tools.brain_studio_schema('FusionHandoff')
    allow = schema['properties']['allow_save']
    assert allow.get('const') is False or allow.get('enum') == [False]
    names = {row['name'] for row in tools.list()}
    assert 'brain_fusion_handoff' in names and 'brain_fusion_ingest' in names
    assert len(names) == 50


@pytest.mark.skipif(not HAS_CQ, reason='Actual CAD kernel not installed; remesure not claimed executed.')
def test_cadquery_clearance_pass_and_overlap_fail(tmp_path):
    import cadquery as cq
    from cadmcp_brain.req2cad.common import file_hash
    folder = tmp_path / 'asm'
    (folder / 'block').mkdir(parents=True)
    (folder / 'spacer').mkdir()
    cq.exporters.export(cq.Workplane('XY').box(10, 10, 10).val(), str(folder / 'block' / 'model.step'))
    far = cq.Workplane('XY').box(10, 10, 10).val().translate((20, 0, 0))
    cq.exporters.export(far, str(folder / 'spacer' / 'model.step'))
    sha_a = file_hash(folder / 'block' / 'model.step')
    sha_b = file_hash(folder / 'spacer' / 'model.step')
    recipe = Recipe.model_validate(_origin_recipe(sha_a, sha_b))
    occs = [
        FusionOccurrence(occurrence='block', part_id='block', step_relative_path='block/model.step',
                         step_absolute_path=str(folder / 'block' / 'model.step'), sha256=sha_a, protected=True),
        FusionOccurrence(occurrence='spacer', part_id='spacer', step_relative_path='spacer/model.step',
                         step_absolute_path=str(folder / 'spacer' / 'model.step'), sha256=sha_b),
    ]
    handoff = FusionHandoff(subject_digest='a' * 64, occurrences=occs, protected_occurrences=['block'])
    passed = remesure_report(recipe, folder, handoff, FusionReport(
        handoff_digest=adapter_payload(handoff)['handoff_digest'],
        occurrences=[FusionReportOccurrence(occurrence=o.occurrence, translation_mm=[0.0, 0.0, 0.0]) for o in occs]))
    assert passed['geometry_checks_verdict'] == 'pass'
    overlap = next(c for c in passed['checks'] if c['kind'] == 'automatic_output_pair_interference')
    assert overlap['overlap_mm3'] == 0
    colliding = FusionReport(
        handoff_digest=adapter_payload(handoff)['handoff_digest'],
        occurrences=[
            FusionReportOccurrence(occurrence='block', translation_mm=[0.0, 0.0, 0.0]),
            FusionReportOccurrence(occurrence='spacer', translation_mm=[-15.0, 0.0, 0.0]),
        ])
    failed = remesure_report(recipe, folder, handoff, colliding)
    assert failed['geometry_checks_verdict'] == 'fail'
    hit = next(c for c in failed['checks'] if c['kind'] == 'automatic_output_pair_interference')
    assert hit['overlap_mm3'] > 0
    with pytest.raises(BrainError) as exc:
        remesure_report(recipe, folder, handoff, FusionReport(
            handoff_digest=adapter_payload(handoff)['handoff_digest'],
            occurrences=[
                FusionReportOccurrence(occurrence='block', translation_mm=[2.0, 0.0, 0.0]),
                FusionReportOccurrence(occurrence='spacer', translation_mm=[0.0, 0.0, 0.0]),
            ]))
    assert exc.value.code == 'FUSION_PROTECTED'
