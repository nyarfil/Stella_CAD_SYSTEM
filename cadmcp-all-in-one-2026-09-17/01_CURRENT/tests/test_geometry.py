import copy
import subprocess
import pytest
from cadmcp_brain import geometry
from cadmcp_brain.demo import build_fixture_geometry
from cadmcp_brain.errors import BrainError


def load_outputs(brain):
    h=brain.get('test')['summary']['contract_digest'];rev=brain.get('test')['summary']['revision']
    build_fixture_geometry(brain.store.root/'incoming')
    brain.import_step('test',rev,'A-frame','incoming/frame.step',h)
    brain.import_step('test',rev+1,'A-button','incoming/button.step',h)
    return rev+2


@pytest.fixture
def geometric(ready):
    if not geometry.available():pytest.skip('optional CadQuery kernel is not installed')
    load_outputs(ready);return ready


def test_no_artifacts_no_fake_pass(ready):
    r=ready.verify('test',4)['report']
    assert r['overall']=='unknown' and r['geometry_status']=='unknown'
    assert all(x['status']=='unknown' for x in r['results'])


def test_actual_step_brep_dimensions_clearance_intersection(geometric):
    r=geometric.verify('test',6)['report']
    results={x['check_id']:x for x in r['results']}
    assert results['CH-brep']['actual'] is True
    assert results['CH-width']['actual']==pytest.approx(20)
    assert results['CH-gap']['actual']==pytest.approx(1)
    assert results['CH-collision']['actual']==pytest.approx(0)
    assert r['geometry_status']=='pass'
    assert r['overall']=='unknown' and not r['physical_design_certified']
    assert results['CH-life']['status']=='unknown' and results['CH-design']['status']=='unknown'


def test_bad_step_becomes_unknown_not_pass(ready):
    (ready.store.root/'broken.step').write_text('Not a STEP file.')
    ready.import_step('test',4,'A-frame','broken.step',ready.get('test')['summary']['contract_digest'])
    r=ready.verify('test',5)['report']
    assert r['geometry_status']=='unknown' and r['overall']=='unknown'


def test_tampered_artifact_never_measured(geometric):
    artifact=geometric.get('test')['project']['artifacts']['A-frame']
    (geometric.store.root/artifact['filename']).write_text('modified')
    r=geometric.verify('test',6)['report']
    width=next(x for x in r['results'] if x['check_id']=='CH-width')
    assert width['status']=='unknown' and 'hash_mismatch' in width['reason']


def test_width_constraint_really_fails(geometric,data):
    p=copy.deepcopy(data['plan']);p['checks'][1]['target']=19
    geometric.submit_plan('test',6,p)
    # Existing outputs are now stale and cannot produce a pass against a changed plan.
    r=geometric.verify('test',7)['report']
    assert r['geometry_status']=='unknown'
    rev=load_outputs(geometric)
    r=geometric.verify('test',rev)['report']
    assert r['geometry_status']=='fail' and r['overall']=='fail'
    assert next(x for x in r['results'] if x['check_id']=='CH-width')['status']=='fail'


def test_reference_import_gives_measured_dimensions_and_invalidates_plan(geometric):
    r=geometric.import_step('test',6,'REF-board','incoming/frame.step',purpose='reference')
    state=geometric.get('test')['project']
    assert state['plan'] is None and state['selection'] is None
    assert state['measurements']['REF-board.bbox_x_mm']['value_mm']==pytest.approx(20)
    assert r['measurement']['engine']=='CadQuery/OpenCascade'


def test_missing_kernel_is_not_success(ready,monkeypatch):
    (ready.store.root/'stub.step').write_text('not parsed without kernel')
    ready.import_step('test',4,'A-frame','stub.step',ready.get('test')['summary']['contract_digest'])
    monkeypatch.setattr(geometry,'available',lambda:False)
    r=ready.verify('test',5)['report']
    assert r['geometry_status']=='unknown'
    assert next(x for x in r['results'] if x['check_id']=='CH-width')['error']['code']=='GEOMETRY_UNAVAILABLE'


def test_worker_timeout_is_explicit(monkeypatch):
    monkeypatch.setattr(geometry,'available',lambda:True)
    def timeout(*args,**kwargs): raise subprocess.TimeoutExpired('worker',1)
    monkeypatch.setattr(subprocess,'run',timeout)
    with pytest.raises(BrainError) as exc:geometry.run_measurements({})
    assert exc.value.code=='GEOMETRY_TIMEOUT'


def test_change_while_measuring_rejected(geometric,monkeypatch):
    original=geometry.run_measurements
    def changed(*args,**kwargs):
        result=original(*args,**kwargs)
        geometric.add_source('test',6,'測定中に変更')
        return result
    monkeypatch.setattr(geometry,'run_measurements',changed)
    with pytest.raises(BrainError) as exc:geometric.verify('test',6)
    assert exc.value.code=='REVISION_CONFLICT'
    assert geometric.get('test')['project']['verification'] is None


def test_hash_change_during_measurement_rejected(geometric,monkeypatch):
    original=geometry.run_measurements
    def changed(paths,*args,**kwargs):
        result=original(paths,*args,**kwargs)
        from pathlib import Path
        Path(paths['A-frame']).write_text('tampered during measurement')
        return result
    monkeypatch.setattr(geometry,'run_measurements',changed)
    with pytest.raises(BrainError) as exc:geometric.verify('test',6)
    assert exc.value.code=='ARTIFACT_CHANGED'


def test_reference_identifier_cannot_be_reused_as_output(geometric):
    with pytest.raises(BrainError) as exc:geometric.import_step('test',6,'A-frame','incoming/frame.step',purpose='reference')
    assert exc.value.code=='ARTIFACT_ROLE_CHANGE'


def test_external_geometry_obligation_can_be_planned_but_never_fake_passes(selected,data):
    p=copy.deepcopy(data['plan'])
    for c in p['checks']:
        if 'R-width' in c['requirement_ids']:c['kind']='external_geometry'
    selected.submit_plan('test',3,p)
    report=selected.verify('test',4)['report']
    assert report['geometry_status']=='unknown'
    assert all(r['status']=='unknown' for r in report['results'] if r['kind']=='external_geometry')


def test_measured_reference_hash_is_rechecked_before_plan(geometric,data):
    geometric.import_step('test',6,'REF-board','incoming/frame.step',purpose='reference')
    geometric.submit_concepts('test',7,data['concepts']);geometric.select('test',8,'C-direct')
    a=geometric.get('test')['project']['artifacts']['REF-board']
    (geometric.store.root/a['filename']).write_text('reference changed after measuring')
    with pytest.raises(BrainError) as exc:geometric.submit_plan('test',9,data['plan'])
    assert exc.value.code=='REFERENCE_CHANGED'
