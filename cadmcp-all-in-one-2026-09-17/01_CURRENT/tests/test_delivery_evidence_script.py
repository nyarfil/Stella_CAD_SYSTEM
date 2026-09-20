"""Script orchestration tests use a worker double, not geometry evidence."""
import json
from types import SimpleNamespace
import pytest
from scripts import check_delivery_evidence as script


@pytest.fixture
def trial(tmp_path,monkeypatch):
    monkeypatch.setattr(script,'ROOT',tmp_path)
    base=tmp_path/'verification'
    folder=base/'source'
    folder.mkdir(parents=True)
    (folder/'evidence.json').write_text('{}',encoding='utf-8')
    source=base/'result.json'
    source.write_text(json.dumps({'result':{'folder':str(folder)}}),encoding='utf-8')
    evaluator=tmp_path/'cadmcp_brain/studio'
    evaluator.mkdir(parents=True)
    for name in ('recipe.py','measurement.py'):
        (evaluator/name).write_text('# test double',encoding='utf-8')
    return source,folder,base/'comparison.json'


def test_bounded_worker_report_and_source_preservation(trial,monkeypatch):
    source,folder,target=trial
    def run(command,**kwargs):
        assert '--worker' in command
        assert kwargs['timeout']==90 and kwargs['check']
        return SimpleNamespace(stdout=json.dumps({'verdict':'pass'}))
    monkeypatch.setattr(script.subprocess,'run',run)
    assert script.main(['--source-result',str(source),'--report',str(target)])==0
    result=json.loads(target.read_text('utf-8'))
    assert result['source_unchanged'] and result['model_calls']==0
    assert not result['cad_regenerated'] and not result['historical_review_modified']


def test_existing_report_is_not_overwritten(trial,monkeypatch):
    source,folder,target=trial
    target.write_bytes(b'preserve')
    monkeypatch.setattr(script.subprocess,'run',lambda *a,**k:pytest.fail('worker must not start'))
    with pytest.raises(ValueError):
        script.main(['--source-result',str(source),'--report',str(target)])
    assert target.read_bytes()==b'preserve'


def test_changed_source_cannot_receive_report(trial,monkeypatch):
    source,folder,target=trial
    def changed(*args,**kwargs):
        (folder/'evidence.json').write_text('{"changed":true}',encoding='utf-8')
        return SimpleNamespace(stdout=json.dumps({'verdict':'pass'}))
    monkeypatch.setattr(script.subprocess,'run',changed)
    with pytest.raises(RuntimeError,match='changed'):
        script.main(['--source-result',str(source),'--report',str(target)])
    assert not target.exists()


def test_changed_evaluator_cannot_receive_report(trial,monkeypatch):
    source,folder,target=trial
    def changed(*args,**kwargs):
        (script.ROOT/'cadmcp_brain/studio/recipe.py').write_text('# changed',encoding='utf-8')
        return SimpleNamespace(stdout=json.dumps({'verdict':'pass'}))
    monkeypatch.setattr(script.subprocess,'run',changed)
    with pytest.raises(RuntimeError,match='Evaluator changed'):
        script.main(['--source-result',str(source),'--report',str(target)])
    assert not target.exists()
