import io
import json
import os
import subprocess
import sys
import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.protocol import Protocol, serve, strict_json, PROTOCOL, MAX_FRAME


def request(method,params=None,rid=1):
    return {'jsonrpc':'2.0','id':rid,'method':method,'params':params or {}}


def initialize(protocol):
    ans=protocol.handle(request('initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'test-client','version':'1'}}))
    protocol.handle({'jsonrpc':'2.0','method':'notifications/initialized'})
    return ans


def test_lifecycle_requires_initialized(brain):
    p=Protocol(Tools(brain))
    assert p.handle(request('tools/list'))['error']['code']==-32002
    result=initialize(p)
    assert result['result']['protocolVersion']==PROTOCOL
    assert len(p.handle(request('tools/list'))['result']['tools'])==50
    assert p.handle(request('initialize'))['error']['code']==-32600


def test_protocol_negotiation(brain):
    p=Protocol(Tools(brain))
    result=p.handle(request('initialize',{'protocolVersion':'2099-01-01','capabilities':{},'clientInfo':{'name':'new','version':'1'}}))
    assert result['result']['protocolVersion']==PROTOCOL


def test_published_tool_schema_matches_runtime(brain):
    from pathlib import Path
    published=Path(__file__).resolve().parents[1]/'schemas/mcp-tools.json'
    assert json.loads(published.read_text('utf-8'))==Tools(brain).list()


@pytest.mark.parametrize('raw',['{"a":1,"a":2}','{"x":NaN}','{"x":Infinity}','{"a":'])
def test_strict_json_rejects_ambiguity(raw):
    with pytest.raises(ValueError): strict_json(raw)


@pytest.mark.parametrize('msg',[[],{}, {'jsonrpc':'1.0','id':1,'method':'ping'}, {'jsonrpc':'2.0','id':True,'method':'ping'}])
def test_invalid_envelopes(brain,msg):
    assert Protocol(Tools(brain)).handle(msg)['error']['code']==-32600


def test_tool_errors_are_not_success(brain):
    p=Protocol(Tools(brain));initialize(p)
    response=p.handle(request('tools/call',{'name':'brain_get','arguments':{'project_id':'missing'}}))
    assert response['result']['isError'] is True
    assert response['result']['structuredContent']['error']['code']=='NOT_FOUND'
    response=p.handle(request('tools/call',{'name':'brain_open','arguments':{'project_id':'A','request':'X','bad':1}}))
    assert response['result']['structuredContent']['error']['code']=='SCHEMA_VALIDATION'


def test_resources_prompts_and_unknowns(brain,data):
    brain.open('test',data['request'])
    p=Protocol(Tools(brain));initialize(p)
    resources=p.handle(request('resources/list'))['result']['resources']
    for r in resources:
        assert p.handle(request('resources/read',{'uri':r['uri']}))['result']['contents']
    assert p.handle(request('resources/read',{'uri':'file:///etc/passwd'}))['error']
    assert p.handle(request('prompts/list'))['result']['prompts']
    prompt=p.handle(request('prompts/get',{'name':'design_stage','arguments':{'project_id':'test'}}))
    assert json.loads(prompt['result']['messages'][0]['content']['text'])['stage']=='intent'
    assert p.handle(request('prompts/get',{'name':'missing'}))['error']
    assert p.handle(request('tools/call',{'name':'invented'}))['error']
    assert p.handle(request('server/magic'))['error']['code']==-32601
    assert p.handle({'jsonrpc':'2.0','method':'notifications/cancelled','params':{'requestId':9}}) is None


def test_invalid_utf8_and_frame_limit(brain):
    out=io.BytesIO();assert serve(Tools(brain),io.BytesIO(b'\xff\n'),out)==0
    assert json.loads(out.getvalue())['error']['code']==-32700
    out=io.BytesIO();assert serve(Tools(brain),io.BytesIO(b'x'*(MAX_FRAME+1)),out)==2
    assert b'2 MiB' in out.getvalue()


def test_real_stdio_subprocess_end_to_end(tmp_path,data):
    messages=[request('initialize',{'protocolVersion':PROTOCOL,'capabilities':{},'clientInfo':{'name':'wire-test','version':'1'}},0),{'jsonrpc':'2.0','method':'notifications/initialized'}]
    def call(name,args): messages.append(request('tools/call',{'name':name,'arguments':args},len(messages)))
    call('brain_open',{'project_id':'wire','request':data['request']})
    call('brain_submit_intent',{'project_id':'wire','expected_revision':0,'brief':data['brief']})
    call('brain_submit_concepts',{'project_id':'wire','expected_revision':1,'concepts':data['concepts']})
    call('brain_select',{'project_id':'wire','expected_revision':2,'concept_id':'C-direct'})
    call('brain_submit_plan',{'project_id':'wire','expected_revision':3,'plan':data['plan']})
    call('brain_export',{'project_id':'wire','expected_revision':4})
    call('brain_verify',{'project_id':'wire','expected_revision':4})
    call('brain_doctor',{})
    payload=''.join(json.dumps(m,ensure_ascii=False)+'\n' for m in messages)
    proc=subprocess.run([sys.executable,'-m','cadmcp_brain','--workspace',str(tmp_path/'wire space_日本語'),'serve'],input=payload,capture_output=True,text=True,encoding='utf-8',timeout=30,env=dict(os.environ,PYTHONUTF8='1'))
    assert proc.returncode==0,proc.stderr
    replies=[json.loads(s) for s in proc.stdout.splitlines()]
    assert len(replies)==len(messages)-1
    assert all('error' not in r for r in replies)
    assert all(not r['result'].get('isError',False) for r in replies)
    report=replies[-2]['result']['structuredContent']['result']['report']
    assert report['overall']=='unknown' and report['geometry_status']=='unknown'
    assert proc.stderr==''
