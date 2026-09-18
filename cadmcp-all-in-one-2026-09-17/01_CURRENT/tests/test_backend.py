import copy
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
import pytest
from cadmcp_brain.backend import AgentCADClient
from cadmcp_brain.errors import BrainError


@pytest.fixture
def upstream():
    state={'tools':[{'name':'create_part','description':'contract test only','input_schema':{'type':'object','properties':{'project':{'type':'string'},'count':{'type':'integer'},'label':{'type':'string'}},'required':['project','count']}}],'posts':[],'result':{'ok':True,'part':'fixture'},'delay':0,'redirect':False}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def reply(self,data):
            raw=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers()
            try: self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError): pass
        def do_GET(self):
            assert self.path=='/api/tools'
            if state['redirect']:
                self.send_response(302);self.send_header('Location','http://example.invalid/');self.end_headers();return
            self.reply({'tools':state['tools']})
        def do_POST(self):
            state['posts'].append((self.path,json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            time.sleep(state['delay']);self.reply(state['result'])
    class LocalTestServer(ThreadingHTTPServer):
        # HTTPServer's getfqdn() can wait for external DNS in an offline test
        # environment. The actual transport remains a local TCP HTTP server.
        def server_bind(self):
            TCPServer.server_bind(self)
            self.server_name='localhost';self.server_port=self.server_address[1]
    server=LocalTestServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    state['url']=f'http://127.0.0.1:{server.server_port}'
    yield state
    server.shutdown();server.server_close();thread.join(timeout=2)


def invoke(brain,client,call_id='call-1',dry_run=False,arguments=None,revision=4):
    h=brain.get('test')['summary']['contract_digest']
    return brain.backend_call(client,'test',revision,h,call_id,'create_part',arguments or {'project':'test','count':1},dry_run)


@pytest.mark.parametrize('url',['https://example.com','http://127.0.0.1/api','http://user@localhost','http://localhost/?x=1','file:///etc/passwd','http://localhost#fragment'])
def test_nonlocal_or_untrusted_origins_rejected(url):
    with pytest.raises(BrainError): AgentCADClient(url)


def test_disabled_backend():
    with pytest.raises(BrainError) as exc: AgentCADClient(None).probe()
    assert exc.value.code=='BACKEND_DISABLED'


def test_dry_run_and_optional_null(ready,upstream):
    client=AgentCADClient(upstream['url'],['create_part'])
    r=invoke(ready,client,dry_run=True,arguments={'project':'test','count':1,'label':None})
    assert r['prepared']['arguments']=={'project':'test','count':1}
    assert not upstream['posts'] and ready.get('test')['summary']['revision']==4


def test_owner_allowlist_is_required(ready,upstream):
    with pytest.raises(BrainError) as exc:invoke(ready,AgentCADClient(upstream['url']))
    assert exc.value.code=='BACKEND_TOOL_DENIED'
    assert not upstream['posts']


@pytest.mark.parametrize('args',[{'project':'test','count':True},{'project':'test','count':'1'},{'project':'test'},{'project':'test','count':1,'bad':1}])
def test_live_schema_argument_rejection(ready,upstream,args):
    with pytest.raises(BrainError) as exc:invoke(ready,AgentCADClient(upstream['url'],['create_part']),arguments=args)
    assert exc.value.code=='BACKEND_ARGUMENTS'
    assert not upstream['posts']


def test_at_most_one_write_and_id_conflict(ready,upstream):
    client=AgentCADClient(upstream['url'],['create_part'])
    first=invoke(ready,client)
    assert first['status']=='backend_returned' and first['summary']['revision']==5
    again=invoke(ready,client)
    assert again['replayed'] and len(upstream['posts'])==1
    assert upstream['posts'][0][0]=='/api/tools/create_part'
    with pytest.raises(BrainError) as exc:invoke(ready,client,arguments={'project':'test','count':2})
    assert exc.value.code=='IDEMPOTENCY_CONFLICT'
    assert len(upstream['posts'])==1


@pytest.mark.parametrize('failure',[{'error':{'type':'script_error','message':'bad'}},{'ok':False,'error':'not rebuilt'}])
def test_http200_error_is_not_success(ready,upstream,failure):
    upstream['result']=failure
    r=invoke(ready,AgentCADClient(upstream['url'],['create_part']))
    assert r['status']=='backend_reported_error'
    assert r['retry_allowed'] is False


def test_timeout_unknown_no_retry(ready,upstream):
    upstream['delay']=0.25
    client=AgentCADClient(upstream['url'],['create_part'],timeout=0.05)
    r=invoke(ready,client)
    assert r['status']=='outcome_unknown'
    r2=invoke(ready,client)
    assert r2['replayed'] and r2['retry_allowed'] is False
    assert len(upstream['posts'])==1


def test_schema_drift_and_external_refs(upstream):
    client=AgentCADClient(upstream['url'],['create_part'])
    upstream['tools'][0]['input_schema']={'$ref':'https://example.invalid/remote.json'}
    with pytest.raises(BrainError) as exc:client.prepare('create_part',{})
    assert exc.value.code=='BACKEND_SCHEMA_REF'
    upstream['tools']=[{'name':'create_part'}]
    with pytest.raises(BrainError) as exc:client.probe()
    assert exc.value.code=='BACKEND_SCHEMA_DRIFT'


def test_unknown_tool_cannot_be_guessed(upstream):
    upstream['tools']=[]
    with pytest.raises(BrainError) as exc:AgentCADClient(upstream['url'],['create_part']).prepare('create_part',{})
    assert exc.value.code=='BACKEND_UNKNOWN_TOOL'


def test_redirect_blocked(upstream):
    upstream['redirect']=True
    with pytest.raises(BrainError) as exc:AgentCADClient(upstream['url']).probe()
    assert exc.value.code=='BACKEND_REDIRECT'


def test_stale_revision_blocks_network_write(ready,upstream):
    with pytest.raises(BrainError) as exc:invoke(ready,AgentCADClient(upstream['url'],['create_part']),revision=3)
    assert exc.value.code=='REVISION_CONFLICT'
    assert not upstream['posts']


def test_concurrent_correction_during_probe_is_caught(ready,upstream,monkeypatch):
    client=AgentCADClient(upstream['url'],['create_part'])
    original=client.prepare
    def prepare(*args):
        result=original(*args)
        ready.add_source('test',4,'新しい指示')
        return result
    monkeypatch.setattr(client,'prepare',prepare)
    with pytest.raises(BrainError) as exc:invoke(ready,client)
    assert exc.value.code=='REVISION_CONFLICT'
    assert not upstream['posts']
