from __future__ import annotations

from pathlib import Path
import pytest

from cadmcp_brain.engine import Brain
from cadmcp_brain.req2cad.common import atomic_json,digest,file_hash
from cadmcp_brain.studio.evidence_state import build_evidence_state
from cadmcp_brain.studio.runtime import Studio


class NoReferences:
    def evidence(self,uid):raise AssertionError(uid)


def payload(subject='a'*64,record='b'*64):
    return {'subject_digest':subject,'build_record_sha256':record,
            'file_hashes':{'measurements.json':'c'*64},
            'measurements':{
                'unverified_requirements':['Input image is absent; material strength is untested.',
                                           'Input image is absent; material strength is untested.'],
                'checks':[{'id':'bbox','kind':'bbox','verdict':'pass','actual_candidates_mm':[10.0],
                           'scope':'Geometry envelope only.','samples':[{'distance_mm':index} for index in range(500)]}]}}


def test_declarations_are_preserved_with_stable_distinct_ids():
    source=payload();before=list(source['measurements']['unverified_requirements'])
    state=build_evidence_state(source,'a'*64)
    declarations=state['historical_declarations']
    assert [item['text'] for item in declarations]==before
    assert declarations[0]['declaration_id']!=declarations[1]['declaration_id']
    assert all(item['declaration_preserved'] is True and item['resolution_assessment']=='not_assessed'
               for item in declarations)
    assert source['measurements']['unverified_requirements']==before
    assert build_evidence_state(source,'a'*64)['historical_declarations']==declarations


def test_supplement_origin_is_stable_and_observations_stay_separate():
    source=payload(subject='d'*64,record='e'*64)
    source['supplement']={'source_subject_digest':'1'*64,'base_build_record_sha256':'2'*64}
    source['file_hashes']={'source-measurements.json':'3'*64,'supplement-report.json':'4'*64}
    source['measurements']['supplemental_acceptance']={'checks':[
        {'id':'expected_prism','kind':'extruded_section','passed':True,'verified':False,
         'status':'not_specified','note':'No prism oracle was supplied.'},
        {'id':'volume','passed':True,'actual_mm3':100.0,'expected_mm3':100.0}]}
    other=dict(source);other['subject_digest']='f'*64
    first=build_evidence_state(source,'d'*64);second=build_evidence_state(other,'f'*64)
    assert first['historical_declarations'][0]['declaration_id']==second['historical_declarations'][0]['declaration_id']
    assert first['historical_declarations'][0]['origin_subject_digest']=='1'*64
    observations=first['current_observations']
    assert [item['origin'] for item in observations]==['source_check','supplemental_check','supplemental_check']
    unverified=next(item for item in observations if item['check_id']=='expected_prism')
    assert unverified['reported_verdict']=='pass'
    assert unverified['effective_verdict']=='unverified' and unverified['evidence_status']=='unverified'
    assert observations[-1]['provenance']=={
        'relative_path':'supplement-report.json','registered_sha256':'4'*64,'integrity':'registered_hash'}


def test_large_measurement_arrays_are_not_copied_into_view():
    state=build_evidence_state(payload(),'a'*64)
    observation=state['current_observations'][0]
    assert 'samples' not in observation['result_summary']
    assert observation['result_summary']['actual_candidates_mm']==[10.0]
    assert state['resolution_boundary']['automatic_resolution'] is False
    assert 'not a completed resolution ledger' in state['resolution_boundary']['next_step']


@pytest.mark.parametrize('check,expected',[
    ({'id':'missing'},'unverified'),
    ({'id':'unknown','verdict':'unknown'},'unverified'),
    ({'id':'skipped','passed':True,'status':'not_requested'},'unverified'),
    ({'id':'conflicting','passed':False,'verdict':'pass'},'inconsistent'),
    ({'id':'conflicting','passed':True,'verdict':'fail'},'inconsistent'),
    ({'id':'negative','passed':False},'fail'),
])
def test_incomplete_or_contradictory_results_are_not_measured_pass(check,expected):
    source=payload();source['measurements']['checks']=[check]
    observation=build_evidence_state(source,'a'*64)['current_observations'][0]
    assert observation['effective_verdict']==expected
    assert observation['evidence_status']==('measured' if expected=='fail' else expected)


def test_view_array_mutation_cannot_modify_source_measurement():
    source=payload()
    view=build_evidence_state(source,'a'*64)
    view['current_observations'][0]['result_summary']['actual_candidates_mm'].append(999)
    assert source['measurements']['checks'][0]['actual_candidates_mm']==[10.0]


def test_packet_compaction_does_not_change_evidence_view():
    from cadmcp_brain.studio.packets import compact_subject
    source=payload();source.update(kind='recipe_build',folder='unused')
    source['measurements']['checks'][0]['samples']=[
        {'distance_mm':1.0,'overlap_mm3':0.0,'verdict':'pass'}]
    expected=build_evidence_state(source,'a'*64)
    packet=compact_subject({'subject_digest':'a'*64,'payload':source})
    assert packet['payload']['evidence_state']==expected
    assert 'samples' in source['measurements']['checks'][0]


def registered_subject(tmp_path:Path):
    brain=Brain(tmp_path/'workspace');brain.open('evidence','Keep the historical unknown separate from geometry checks.')
    studio=Studio(brain,NoReferences());snapshot=studio._snapshot('evidence',0)
    context={'snapshot':snapshot,
             'recipe':{'title':'Evidence state fixture','functions':{'Body':'Synthetic body'},
                       'original_request':'Keep the historical unknown separate from geometry checks.'},
             'reference_digests':{},'lineage':{},'protection':{}}
    subject=digest({'fixture':'evidence-state'});folder=studio.root/'evidence'/'build';folder.mkdir(parents=True)
    (folder/'assembly.step').write_bytes(b'test-double-not-cad')
    measurements={'geometry_checks_verdict':'pass',
                  'unverified_requirements':['Input image is unavailable and physical strength remains untested.'],
                  'checks':[{'id':'bbox','verdict':'pass','scope':'Synthetic geometry only.'}],
                  'outputs':{},'assembly':{'relative_path':'assembly.step','sha256':file_hash(folder/'assembly.step')}}
    atomic_json(folder/'measurements.json',measurements);atomic_json(folder/'recipe.json',context['recipe'])
    record={'subject_digest':subject,'kind':'recipe_build','context':context,'measurements':measurements,
            'attempt_id':'a'*32,'recipe_context_digest':digest(context),'folder':str(folder),
            'file_hashes':{path.relative_to(folder).as_posix():file_hash(path) for path in folder.rglob('*')}}
    atomic_json(folder/'build-record.json',record);record['build_record_sha256']=file_hash(folder/'build-record.json')
    studio.register_subject('evidence',0,subject,record)
    return studio,subject


def test_status_packet_and_delivery_expose_same_read_only_boundary(tmp_path):
    studio,subject=registered_subject(tmp_path)
    status=studio.status('evidence',0,subject)
    packet=studio.packet('evidence',0,subject,'verification')
    delivery=studio.delivery('evidence',0,subject)
    assert status['evidence_state']==packet['subject']['payload']['evidence_state']==delivery['evidence_state']
    assert status['evidence_state']['historical_declarations'][0]['text'].startswith('Input image')
    assert any('Missing input images' in rule for rule in packet['review_rules'])
    markdown=Path(delivery['delivery_markdown']).read_text(encoding='utf-8')
    assert '## Historical unverified declarations' in markdown
    assert 'Resolution of each declaration remains unassessed.' in markdown
    assert 'source_check / bbox: pass (measurements.json)' in markdown
