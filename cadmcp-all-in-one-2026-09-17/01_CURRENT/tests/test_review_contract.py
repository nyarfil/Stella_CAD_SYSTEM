"""Regression tests for hash-bound Studio review evidence and correction lineage."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio.runtime import ROLES
from scripts.demo_real_references import REQUEST, demo_recipe, init_cases


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec('cadquery') is None,
    reason='Actual CAD kernel not installed; hash-bound Studio build tests are not claimed executed.',
)


@pytest.fixture(scope='module')
def measured(tmp_path_factory):
    with pytest.MonkeyPatch.context() as env:
        env.setenv('CADMCP_REQ2CAD_ROOT', str(tmp_path_factory.mktemp('review-env')))
        root = tmp_path_factory.mktemp('review-contract') / 'references'
        _, catalog, materialized, _ = init_cases(root)
        yield catalog.root, materialized


@pytest.fixture
def local(measured, tmp_path, monkeypatch):
    catalog_root, materialized = measured
    monkeypatch.setenv('CADMCP_REQ2CAD_ROOT', str(catalog_root))
    tools = Tools(Brain(tmp_path / 'project-workspace'))
    tools.brain_open('public-test', REQUEST)
    return tools, materialized


def review(subject, role, attachments, *, round_number=1, challenges=(), status='viewed', partial=False):
    selected = attachments[:-1] if partial else attachments
    inspections = [
        {'attachment_sha256': item['sha256'], 'kind': item['kind'], 'attachment_path': item['path'],
         'status': status, 'observation': 'Opened the supplied artifact and compared it to the registered hash.'}
        for item in selected
    ]
    return {
        'subject_digest': subject, 'role': role, 'discussion_round': round_number,
        'reviewer_label': 'CONTRACT TEST REVIEWER',
        'execution_description': 'Controlled fixture; it does not claim an independent reviewer or physical test.',
        'evidence_inspections': inspections, 'challenged_review_ids': list(challenges),
        'findings': [], 'remaining_uncertainties': ['Physical performance remains unverified.'],
        'conclusion': 'no_blocker_found',
    }


def build(tools, measured):
    return tools.brain_studio_build('public-test', 0, demo_recipe(measured), 180)


def attachments(tools, subject):
    return tools.brain_studio_review_packet('public-test', 0, subject, 'requirements')['subject']['payload']['evidence_attachments']


def complete_two_rounds(tools, subject, evidence):
    first = [tools.brain_studio_submit_review('public-test', 0, subject, review(subject, role, evidence)) for role in ROLES]
    ids = [item['review_id'] for item in first]
    for role in ROLES:
        tools.brain_studio_submit_review('public-test', 0, subject, review(subject, role, evidence, round_number=2, challenges=ids))
    return ids


def test_empty_partial_duplicate_and_unreadable_evidence_never_open_owner_gate(local):
    tools, measured = local
    built = build(tools, measured); subject = built['subject_digest']; evidence = attachments(tools, subject)
    assert evidence and any(item['path'].endswith('build-record.json') for item in evidence)

    duplicate = review(subject, 'requirements', evidence)
    duplicate['evidence_inspections'].append(copy.deepcopy(duplicate['evidence_inspections'][0]))
    with pytest.raises(BrainError, match='duplicate'):
        tools.brain_studio_submit_review('public-test', 0, subject, duplicate)

    first = []
    for role in ROLES:
        report = review(subject, role, evidence, partial=(role == 'mechanism'))
        if role == 'requirements':
            report['evidence_inspections'] = []
        first.append(tools.brain_studio_submit_review(
            'public-test', 0, subject, report))
    ids = [item['review_id'] for item in first]
    for role in ROLES:
        tools.brain_studio_submit_review('public-test', 0, subject, review(subject, role, evidence, round_number=2, challenges=ids))
    status = tools.brain_studio_review_status('public-test', 0, subject)
    assert status['peer_challenge_complete'] and not status['evidence_inspection_complete']
    assert not status['discussion_ready_for_owner']

    # An unreadable artifact can be recorded, but never promotes a subject.
    unreadable = review(subject, 'requirements', evidence, round_number=3, challenges=ids, status='unreadable')
    tools.brain_studio_submit_review('public-test', 0, subject, unreadable)
    assert not tools.brain_studio_review_status('public-test', 0, subject)['discussion_ready_for_owner']


def test_each_round_two_role_must_challenge_every_round_one_review(local):
    tools, measured = local
    built = build(tools, measured); subject = built['subject_digest']; evidence = attachments(tools, subject)
    first = [tools.brain_studio_submit_review('public-test', 0, subject, review(subject, role, evidence)) for role in ROLES]
    ids = [item['review_id'] for item in first]
    with pytest.raises(BrainError, match='Every round-two role'):
        tools.brain_studio_submit_review('public-test', 0, subject, review(subject, 'requirements', evidence, round_number=2, challenges=ids[:1]))
    complete_two_rounds(tools, subject, evidence)
    status = tools.brain_studio_review_status('public-test', 0, subject)
    assert status['peer_challenge_complete'] and status['discussion_ready_for_owner']
    assert status['independence_verified'] is False


def test_build_record_tamper_is_rejected_and_old_payload_is_read_only_compatible(local):
    tools, measured = local
    built = build(tools, measured); subject = built['subject_digest']; folder = Path(built['folder'])
    delivery = tools.brain_studio_delivery('public-test', 0, subject)
    manifest = json.loads(Path(delivery['delivery_json']).read_text(encoding='utf-8'))
    assert {'reference_uses', 'design_basis', 'verification_plan'} <= set(manifest)
    record = json.loads((folder / 'build-record.json').read_text(encoding='utf-8'))
    record['measurements']['geometry_checks_verdict'] = 'forged-pass'
    (folder / 'build-record.json').write_text(json.dumps(record), encoding='utf-8')
    with pytest.raises(BrainError, match='Build record'):
        tools.brain_studio_review_packet('public-test', 0, subject, 'requirements')

    # A historical subject without the new byte hash is readable only when the
    # registered payload still exactly agrees with its build record; it cannot
    # become discussion-ready under the new contract.
    second = build(tools, measured); legacy_subject = second['subject_digest']
    subject_file = Path(tools.brain.store.root) / 'studio' / 'public-test' / 'reviews' / legacy_subject / 'subject.json'
    info = json.loads(subject_file.read_text(encoding='utf-8'))
    info['payload'].pop('build_record_sha256')
    subject_file.write_text(json.dumps(info), encoding='utf-8')
    tools.brain_studio_review_packet('public-test', 0, legacy_subject, 'requirements')
    assert not tools.brain_studio_review_status('public-test', 0, legacy_subject)['evidence_contract_registered']


def test_baseline_preserves_conditions_and_unknowns(local):
    tools, measured = local
    prior = build(tools, measured)
    source = measured['0032/00329619']
    changed = demo_recipe(measured)
    changed['reference_uses'] = [{
        'function_id': 'Guide', 'use': 'fit_reference', 'uid': source['uid'],
        'evidence_digest': source['evidence_digest'],
        'cad_sha256': source['geometry']['exports']['model.step']['sha256'],
        'application': 'Use this explicitly identified cylindrical interface only as a fit reference.',
        'used_face_ids': ['F999999'],
    }]
    with pytest.raises(BrainError, match='face absent'):
        tools.brain_studio_build('public-test', 0, changed, 180)
    changed = demo_recipe(measured)
    changed['unverified_requirements'] = ['Replacement wording hides a still-unverified physical condition.']
    with pytest.raises(BrainError, match='unverified requirement'):
        tools.brain_studio_build('public-test', 0, changed, 180, prior['subject_digest'])
    changed = demo_recipe(measured)
    changed['clearance_checks'][0]['min_mm'] += .01
    with pytest.raises(BrainError, match='inspection conditions'):
        tools.brain_studio_build('public-test', 0, changed, 180, prior['subject_digest'])


def test_provided_cad_basis_must_be_a_current_registered_reference(local):
    tools, _ = local
    first_principles = {
        'kind': 'first_principles', 'principles': ['A bounded fixture shape transfers its stated reaction load.'],
        'assumptions': ['No physical load rating or material lot has been supplied.'],
        'verification_plan': ['Measure the generated STEP envelope before any physical test.'],
        'unknowns': ['Physical strength and fastening remain unverified.'],
    }
    provided = {
        'kind': 'provided_cad', 'artifact_id': 'MissingBracket', 'sha256': 'a' * 64,
        'application': 'Use the owner-provided locating envelope as a later measured constraint.',
        'verification_plan': ['Register and hash-check the STEP before inspecting its interfaces.'],
        'unknowns': ['The owner CAD interface dimensions and units remain unverified.'],
    }
    def option(identifier, basis):
        return {'id': identifier, 'name': identifier, 'covers': ['Guide'], 'references': [], 'design_basis': basis,
                'mechanism_principle': 'Use the stated geometry as a bounded guide concept.', 'proposed_parts': ['guide'],
                'force_path': 'Reaction passes through the guide body into its mounting interface.',
                'assembly_method': 'Assembly hardware and tolerances remain to be established.',
                'risks': ['No physical validation has been completed.']}
    matrix = {'brief': {'original_request': REQUEST, 'functions': [{
        'id': 'Guide', 'source_excerpt': '軸案内部品', 'function': 'guide shaft',
        'behavior': 'Constrain the shaft radially while leaving its stated motion unverified.',
        'queries': ['guide shaft']}], 'unresolved': ['Physical validation remains unverified.']},
        'options': [option('Provided', provided), option('FirstPrinciples', first_principles)]}
    with pytest.raises(BrainError, match='Provided CAD'):
        tools.brain_studio_synthesize('public-test', 0, matrix)
