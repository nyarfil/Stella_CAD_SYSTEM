"""Persistent owner protection survives restarts and is enforced before CAD work."""
import importlib.util
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.req2cad.common import file_hash
from scripts.demo_real_references import REQUEST, demo_recipe, init_cases


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec('cadquery') is None,
    reason='Actual CAD kernel is required for protected STEP import/build tests.',
)


@pytest.fixture(scope='module')
def materialized(tmp_path_factory):
    with pytest.MonkeyPatch.context() as env:
        # setenv records even an absent original key; delenv on an absent key
        # would not undo the direct assignment made by init_cases.
        env.setenv('CADMCP_REQ2CAD_ROOT', str(tmp_path_factory.mktemp('protection-env')))
        _, catalog, measured, _ = init_cases(tmp_path_factory.mktemp('project-protection') / 'references')
        yield catalog.root, measured


@pytest.fixture
def protected_project(materialized, tmp_path, monkeypatch):
    import cadquery as cq
    catalog_root, measured = materialized
    monkeypatch.setenv('CADMCP_REQ2CAD_ROOT', str(catalog_root))
    brain = Brain(tmp_path / 'workspace'); tools = Tools(brain)
    tools.brain_open('protected', REQUEST)
    incoming = brain.store.root / 'incoming'; incoming.mkdir()
    source = incoming / 'pcb.step'
    cq.exporters.export(cq.Workplane('XY').box(2, 2, 2).val().translate((100, 0, 0)), str(source))
    tools.brain_import_step('protected', 0, 'PCB', 'incoming/pcb.step', purpose='reference')
    artifact = brain.store.get('protected').artifacts['PCB']
    policy = {'assets': [{'artifact_id': 'PCB', 'sha256': artifact.sha256,
                          'placement': 'as_registered', 'required_output_id': 'hardware'}],
              'editable_references': []}
    configured = brain.set_project_protection('protected', 1, policy, 'Freeze the measured PCB location for this prototype.')
    return tools, brain, measured, artifact, configured


def recipe_with_protected_hardware(measured, artifact):
    recipe = demo_recipe(measured)
    recipe['functions']['Hardware'] = 'Preserve the owner-protected PCB at its registered coordinate placement.'
    recipe['operations'].append({'id': 'fixed_hardware', 'op': 'project_step', 'function_id': 'Hardware',
                                 'reason': 'Keep the registered owner hardware unchanged in the exported assembly.',
                                 'artifact_id': 'PCB', 'sha256': artifact.sha256, 'role': 'protected_hardware',
                                 'unit_basis': 'Registered millimetre STEP coordinates; no physical unit claim.'})
    recipe['outputs'].append({'part_id': 'hardware', 'node': 'fixed_hardware', 'expected_solids': 1})
    return recipe


def test_persistent_protection_reloads_and_records_owner_reason(protected_project):
    tools, brain, measured, artifact, configured = protected_project
    assert configured['revision'] == 2 and configured['persistent_asset_count'] == 1
    restored = Brain(brain.store.root).get_project_protection('protected')
    assert restored['protection']['assets'][0]['sha256'] == artifact.sha256
    event = brain.store.history('protected')[-1]
    assert event['kind'] == 'project_protection_changed'
    assert event['payload']['detail']['reason'].startswith('Freeze the measured PCB')
    built = tools.brain_studio_build('protected', 2, recipe_with_protected_hardware(measured, artifact), 180)
    assert (Path(built['folder']) / 'hardware' / 'model.step').is_file()
    assert file_hash(brain.store.root / artifact.filename) == artifact.sha256


def test_protection_rejects_ambiguous_stale_and_conflicting_configuration(protected_project):
    _, brain, _, artifact, _ = protected_project
    with pytest.raises(BrainError, match='current registered'):
        brain.set_project_protection('protected', 2, {'assets': [{'artifact_id': 'PCB', 'sha256': '0' * 64,
            'placement': 'as_registered', 'required_output_id': 'hardware'}]}, 'Use a deliberately stale asset hash.')
    with pytest.raises(ValidationError, match='cannot be protected and editable'):
        brain.set_project_protection('protected', 2, {'assets': [{'artifact_id': 'PCB', 'sha256': artifact.sha256,
            'placement': 'as_registered', 'required_output_id': 'hardware'}], 'editable_references': [{'artifact_id': 'PCB', 'sha256': artifact.sha256}]}, 'Conflicting owner authority must fail.')
    with pytest.raises(BrainError, match='Editable CAD must name'):
        brain.set_project_protection('protected', 2, {'assets': [],
            'editable_references': [{'artifact_id': 'Unknown', 'sha256': 'a' * 64}]}, 'Unknown CAD must never receive mutable permission.')
    assert brain.get('protected')['summary']['revision'] == 2


def test_build_rejects_protected_drop_boolean_transform_and_stale_bytes(protected_project):
    tools, brain, measured, artifact, _ = protected_project
    missing = recipe_with_protected_hardware(measured, artifact)
    missing['outputs'][-1]['part_id'] = 'renamed_hardware'
    with pytest.raises(BrainError, match='required output'):
        tools.brain_studio_build('protected', 2, missing, 180)

    boolean = recipe_with_protected_hardware(measured, artifact)
    boolean['operations'].append({'id': 'fused_hardware', 'op': 'union', 'function_id': 'Guide',
                                  'reason': 'Negative control attempts to fuse the protected hardware into new geometry.',
                                  'operands': ['finished_guide', 'fixed_hardware']})
    boolean['outputs'][0]['node'] = 'fused_hardware'
    with pytest.raises(ValidationError, match='Protected hardware'):
        tools.brain_studio_build('protected', 2, boolean, 180)

    transformed = recipe_with_protected_hardware(measured, artifact)
    transformed['operations'].append({'id': 'moved_hardware', 'op': 'transform', 'function_id': 'Hardware',
                                      'reason': 'Negative control moves the frozen hardware from its registered placement.',
                                      'source': 'fixed_hardware', 'translation_mm': [1., 0., 0.]})
    transformed['outputs'][-1]['node'] = 'moved_hardware'
    with pytest.raises(ValidationError, match='Protected hardware'):
        tools.brain_studio_build('protected', 2, transformed, 180)

    target = brain.store.root / artifact.filename
    target.write_text('tampered protected STEP', encoding='utf-8')
    with pytest.raises(BrainError, match='bytes changed'):
        tools.brain_studio_build('protected', 2, recipe_with_protected_hardware(measured, artifact), 180)


def test_protected_cad_can_be_a_read_only_difference_cutter(protected_project):
    tools, brain, measured, artifact, _ = protected_project
    recipe = recipe_with_protected_hardware(measured, artifact)
    recipe['operations'].append({'id': 'guide_cut_by_hardware', 'op': 'difference', 'function_id': 'Guide',
                                 'reason': 'Use the fixed PCB only as a read-only obstacle while preserving its output.',
                                 'operands': ['finished_guide', 'fixed_hardware']})
    recipe['outputs'][0]['node'] = 'guide_cut_by_hardware'
    built = tools.brain_studio_build('protected', 2, recipe, 180)
    assert built['geometry_checks_verdict'] == 'pass'
    assert file_hash(brain.store.root / artifact.filename) == artifact.sha256


def test_protected_asset_cannot_be_reimported_and_other_project_is_independent(protected_project):
    tools, brain, measured, artifact, _ = protected_project
    with pytest.raises(BrainError, match='cannot be replaced'):
        tools.brain_import_step('protected', 2, 'PCB', 'incoming/pcb.step', purpose='reference')
    tools.brain_open('separate', REQUEST)
    separate = brain.get_project_protection('separate')
    assert separate['protection']['assets'] == [] and separate['effective_protected_ids'] == []
    assert file_hash(brain.store.root / artifact.filename) == artifact.sha256


def test_reimport_revokes_hash_bound_edit_permission(protected_project):
    import cadquery as cq
    _, brain, _, artifact, _ = protected_project
    brain.import_step('protected', 2, 'Fixture', 'incoming/pcb.step', purpose='reference')
    fixture = brain.store.get('protected').artifacts['Fixture']
    policy = {'assets': [{'artifact_id': 'PCB', 'sha256': artifact.sha256,
                          'placement': 'as_registered', 'required_output_id': 'hardware'}],
              'editable_references': [{'artifact_id': 'Fixture', 'sha256': fixture.sha256}]}
    brain.set_project_protection('protected', 3, policy, 'Allow this exact fixture revision to be an editable design reference.')
    replacement = brain.store.root / 'incoming' / 'fixture-replacement.step'
    cq.exporters.export(cq.Workplane('XY').box(3, 3, 3).val(), str(replacement))
    brain.import_step('protected', 4, 'Fixture', 'incoming/fixture-replacement.step', purpose='reference')
    current = brain.get_project_protection('protected')
    assert current['protection']['editable_references'] == []
    event = brain.store.history('protected')[-1]
    assert event['payload']['detail']['revoked_editable_reference'][0]['artifact_id'] == 'Fixture'
