import json
from pathlib import Path
import pytest
from jsonschema import ValidationError
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import provider

SCHEMA={'type':'object','properties':{'answer':{'type':'string'}},'required':['answer'],'additionalProperties':False}


@pytest.fixture
def cli(tmp_path,monkeypatch):
    monkeypatch.setattr(provider,'probe_codex',lambda executable: {'command':['test-double'], 'version':'explicit test double'})
    return provider.CodexProvider(tmp_path/'runs',max_calls=1,evidence_root=tmp_path)


def respond(monkeypatch,text,change=False):
    def run(command,stdin,stdout,stderr,*,cwd,timeout):
        assert 'read-only' in command and '--ignore-user-config' in command and '--ephemeral' in command
        assert not cwd.is_relative_to(stdin.parent.parent)
        assert (stdin.parent/'input-snapshot/context.json').is_file()
        response=Path(command[command.index('--output-last-message')+1])
        response.write_text(text,encoding='utf-8')
        if change:
            (cwd/'context.json').write_text('{}',encoding='utf-8')
        return {'returncode':0}
    monkeypatch.setattr(provider,'bounded_process',run)


def test_unicode_snapshot_and_budget(cli,tmp_path,monkeypatch):
    evidence=tmp_path/'計測.json'
    evidence.write_text('{"clearance":1}',encoding='utf-8')
    respond(monkeypatch,'{"answer":"日本語を保持"}')
    assert cli.generate('Inspect',SCHEMA,{'path':str(evidence)}) == {'answer':'日本語を保持'}
    receipt=json.loads(next((tmp_path/'runs').glob('*/receipt.json')).read_text())
    assert receipt['evidence_files']==1 and receipt['response_received']
    with pytest.raises(BrainError,match='budget'):
        cli.generate('Inspect',SCHEMA,{})


def test_text_is_embedded_and_image_is_native_attachment(cli,tmp_path,monkeypatch):
    evidence=tmp_path/'measurements.json';evidence.write_text('{"clearance_mm":0.15}',encoding='utf-8')
    image=tmp_path/'assembly.png';image.write_bytes(b'not-a-real-image-test-double')
    captured={}
    def run(command,stdin,stdout,stderr,*,cwd,timeout):
        captured['command']=command;captured['prompt']=stdin.read_text('utf-8')
        response=Path(command[command.index('--output-last-message')+1])
        response.write_text('{"answer":"inspected"}',encoding='utf-8')
        return {'returncode':0}
    monkeypatch.setattr(provider,'bounded_process',run)
    assert cli.generate('Inspect',SCHEMA,{'measurement_file':str(evidence),'image_file':str(image)})=={'answer':'inspected'}
    assert 'clearance_mm' in captured['prompt'] and '0.15' in captured['prompt']
    image_index=captured['command'].index('--image')
    assert Path(captured['command'][image_index+1]).name.endswith('.png')
    receipt=json.loads(next(cli.root.glob('*/receipt.json')).read_text())
    assert receipt['embedded_text_evidence_files']==1 and receipt['attached_image_files']==1


@pytest.mark.parametrize('text',['{"answer":"first","answer":"second"}','{"answer":NaN}','{"answer":3}'])
def test_invalid_model_output_rejected(cli,monkeypatch,text):
    respond(monkeypatch,text)
    with pytest.raises((ValueError, ValidationError)):
        cli.generate('Inspect',SCHEMA,{})
    receipt=json.loads(next(cli.root.glob('*/receipt.json')).read_text())
    assert not receipt['response_received'] and receipt['error']


def test_changed_input_rejected(cli,monkeypatch):
    respond(monkeypatch,'{"answer":"ok"}',change=True)
    with pytest.raises(BrainError) as exc:
        cli.generate('Inspect',SCHEMA,{'value':'immutable'})
    assert exc.value.code=='CODEX_INPUT_CHANGED'


def test_staged_review_identity_restored_only_with_matching_hash(tmp_path):
    attachment={'source':str(tmp_path/'original.json'),'snapshot':'evidence/000.json','sha256':'a'*64}
    value={'evidence_inspections':[{'attachment_path':'evidence/000.json','attachment_sha256':'a'*64}]}
    restored=provider.restore_evidence_paths(value,[attachment],tmp_path/'sandbox')
    assert restored['evidence_inspections'][0]['attachment_path']==attachment['source']
    value={'evidence_inspections':[{'attachment_path':'evidence/000.json','attachment_sha256':'b'*64}]}
    with pytest.raises(BrainError,match='identity'):
        provider.restore_evidence_paths(value,[attachment],tmp_path/'sandbox')
