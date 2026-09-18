import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from pydantic import ValidationError
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.util import safe_path, safe_id


def test_creation_reload_and_no_overwrite(brain,data):
    brain.open('test',data['request'])
    with pytest.raises(BrainError,match='already exists'): brain.open('test','changed')
    restored=Brain(brain.store.root).get('test')
    assert restored['project']['sources'][0]['text']==data['request']
    assert restored['summary']['revision']==0


def test_failed_edit_rolls_back(intent,data):
    b=copy.deepcopy(data['brief']);b['requirements'][0]['source_refs'][0]['quote']='invented'
    with pytest.raises(BrainError): intent.submit_intent('test',1,b)
    assert intent.get('test')['summary']['revision']==1
    assert len(intent.store.history('test'))==2


def test_correction_invalidates_every_downstream_design(ready):
    h=ready.get('test')['summary']['contract_digest']
    ready.verify('test',4)
    assert ready.get('test')['project']['verification'] is not None
    result=ready.add_source('test',5,'幅は変更する。')
    state=ready.get('test')['project']
    assert result['next_stage']=='intent'
    assert h and result['contract_digest'] is None
    assert state['brief'] is None and not state['concepts']
    assert state['plan'] is None and state['verification'] is None


def test_optimistic_lock_two_agents(ready):
    def attempt(text):
        try: return ready.add_source('test',4,text)['revision']
        except BrainError as exc: return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(attempt,['訂正A','訂正B']))
    assert sorted(map(str,results))==['5','REVISION_CONFLICT']
    assert len(ready.get('test')['project']['sources'])==2


def test_stale_export_does_not_write(ready):
    with pytest.raises(BrainError) as exc: ready.export('test',3)
    assert exc.value.code=='REVISION_CONFLICT'
    assert not (ready.store.root/'exports').exists()


def test_exports_repeat_and_after_evidence_revision(ready):
    first=ready.export('test',4)
    content={p:Path(p).read_bytes() for p in first['files']}
    second=ready.export('test',4)
    assert first==second
    ready.verify('test',4)
    third=ready.export('test',5)
    assert third['contract_digest']==first['contract_digest']
    assert all(Path(p).read_bytes()==raw for p,raw in content.items())
    graph=json.loads(next(raw for p,raw in content.items() if p.endswith('design_graph.json')))
    assert graph['nodes'] and graph['edges']
    ids={n['id'] for n in graph['nodes']}
    assert len(ids)==len(graph['nodes'])


@pytest.mark.parametrize('name',['../bad','/tmp/bad','a/b','a\\b','C:thing','123','x'*81,'', '猫'])
def test_identifier_paths_rejected(name):
    with pytest.raises(BrainError): safe_id(name)


@pytest.mark.parametrize('name',['../outside','/etc/passwd','a/../../file','C:\\Windows\\x','dir\\x','D:relative'])
def test_workspace_paths_rejected(brain,name):
    with pytest.raises(BrainError): safe_path(brain.store.root,name,must_exist=False)


def test_symlink_input_rejected(brain,tmp_path):
    target=tmp_path/'external';target.write_text('data')
    try: (brain.store.root/'link.step').symlink_to(target)
    except (OSError,NotImplementedError): pytest.skip('OS disallows symlink creation')
    with pytest.raises(BrainError): safe_path(brain.store.root,'link.step')


def test_missing_path_rejected(brain):
    with pytest.raises(BrainError): safe_path(brain.store.root,'missing.step')


@pytest.mark.parametrize('filename,raw',[('fake.py','x'),('fake.stl','x'),('empty.step','')])
def test_import_rejects_non_step_or_empty(ready,filename,raw):
    (ready.store.root/filename).write_text(raw)
    with pytest.raises(BrainError): ready.import_step('test',4,'A',filename,ready.get('test')['summary']['contract_digest'])
    assert ready.get('test')['summary']['revision']==4


def test_import_requires_matching_contract(ready):
    (ready.store.root/'f.step').write_text('not important: rejected before geometry')
    with pytest.raises(BrainError) as exc: ready.import_step('test',4,'A','f.step','0'*64)
    assert exc.value.code=='STALE_CONTRACT'


def test_unknown_tool_and_schema(brain):
    tools=Tools(brain)
    with pytest.raises(BrainError):tools.call('delete_everything',{})
    with pytest.raises(BrainError):tools.brain_schema('Fabrication')
    with pytest.raises(ValidationError): tools.call('brain_open',{'project_id':'A','request':'X','unexpected':True})
    with pytest.raises(ValidationError): tools.call('brain_verify',{'project_id':'A','expected_revision':True})


def test_registry_schemas_and_readonly_flags(brain):
    from jsonschema import Draft202012Validator
    tools=Tools(brain)
    assert len(tools.list())==43
    for tool in tools.list(): Draft202012Validator.check_schema(tool['inputSchema'])
    assert next(t for t in tools.list() if t['name']=='brain_get')['annotations']['readOnlyHint']


def test_catalog_source_and_filter(brain):
    found=brain.catalog.search('サイドボタン',6,'actuate_switch')
    assert found
    assert all('actuate_switch' in x['pattern']['functions'] for x in found)
    assert all(x['pattern']['evidence_level']=='authored_engineering_pattern_not_a_validated_product' for x in found)


def test_export_digest_label_cannot_hide_modified_content(ready):
    report=ready.export('test',4)
    target=Path(report['directory'])/'contract.json'
    value=json.loads(target.read_text('utf-8'));value['brief']['objective']='tampered'
    target.write_text(json.dumps(value),encoding='utf-8')
    with pytest.raises(BrainError) as exc:ready.export('test',4)
    assert exc.value.code=='EXPORT_CONFLICT'
