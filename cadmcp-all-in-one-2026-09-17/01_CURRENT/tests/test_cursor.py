"""Cursor compatibility tests using an EXPLICIT script stand-in, not a real model.

The stand-in implements the documented terminal JSON envelope and process flags.
No test below claims Cursor login, real LLM quality, or sandbox enforcement.
"""
from __future__ import annotations
import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio import cursor_provider as cp
from cadmcp_brain.studio.autopilot import Autopilot

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('cursor_setup_test', ROOT / 'scripts/setup_cursor.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
SCHEMA = {'type': 'object', 'additionalProperties': False,
          'properties': {'answer': {'type': 'string'}, 'values': {'type': 'object', 'additionalProperties': {'type': 'number'}}},
          'required': ['answer', 'values']}
VALUE = {'answer': '実例CADの構造を参照する', 'values': {'diameter': 3.0}}


def envelope(content=None, **updates):
    v = {'type': 'result', 'subtype': 'success', 'is_error': False,
         'session_id': 'session-1', 'result': json.dumps(VALUE, ensure_ascii=False) if content is None else content}
    v.update(updates)
    return json.dumps(v, ensure_ascii=False)


@pytest.mark.parametrize('fenced', [False, True])
def test_native_envelope_and_maps(fenced):
    content = json.dumps(VALUE, ensure_ascii=False)
    if fenced: content = '```json\n' + content + '\n```'
    result, meta = cp.parse_cursor_result(envelope(content), SCHEMA)
    assert result == VALUE and isinstance(result['values'], dict)
    assert meta['session_id'] == 'session-1'


@pytest.mark.parametrize('text', [
    '{}', '[]', 'not-json',
    envelope(is_error=True), envelope(is_error=0), envelope(subtype='error'),
    envelope(result={}), envelope(result=''), envelope(session_id=''),
    envelope('Explanation before JSON\n' + json.dumps(VALUE)),
    envelope('```python\n{}\n```'),
    envelope('{"answer":"one","answer":"two","values":{}}'),
    envelope('{"answer":"x","values":{"x":NaN}}'),
    envelope('{"answer":"x","values":{},"fabricated":true}'),
    envelope('{"answer":"x","values":[]}'),
    '{"type":"result","type":"result"}',
])
def test_malformed_or_errored_outputs_stop(text):
    with pytest.raises(BrainError): cp.parse_cursor_result(text, SCHEMA)


def test_output_size_limit(monkeypatch):
    monkeypatch.setattr(cp, 'MAX_RESPONSE', 10)
    with pytest.raises(BrainError) as e: cp.parse_cursor_result(envelope(), SCHEMA)
    assert e.value.code == 'AGENT_OUTPUT_LIMIT'


def test_cli_detection_does_not_use_editor(monkeypatch):
    seen = []
    def which(s):
        seen.append(s)
        return '/bin/agent' if s == 'agent' else None
    monkeypatch.setattr(cp.shutil, 'which', which)
    assert cp.resolve_cursor() == [str(Path('/bin/agent').absolute())]
    assert seen == ['cursor-agent', 'agent']
    monkeypatch.setattr(cp.shutil, 'which', lambda s: None)
    with pytest.raises(BrainError) as e: cp.resolve_cursor()
    assert e.value.code == 'CURSOR_MISSING'


def test_windows_cmd_uses_native_sibling_not_shell(tmp_path, monkeypatch):
    cmd = tmp_path / 'agent.cmd'; cmd.write_text('@echo off')
    exe = tmp_path / 'agent.exe'; exe.write_bytes(b'test-file-NOT-an-executable')
    monkeypatch.setattr(cp.shutil, 'which', lambda s: str(cmd))
    assert cp.resolve_cursor('agent', platform='nt') == [str(exe)]


def test_windows_cmd_uses_ps_file_without_policy_bypass(tmp_path, monkeypatch):
    cmd = tmp_path / 'agent.cmd'; cmd.write_text('@echo off')
    ps = tmp_path / 'agent.ps1'; ps.write_text('# controlled fixture')
    monkeypatch.setattr(cp.shutil, 'which', lambda s: 'pwsh.exe' if s == 'pwsh' else str(cmd))
    resolved = cp.resolve_cursor('agent', platform='nt')
    assert resolved == ['pwsh.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(ps)]
    assert not any(s in resolved for s in ('-Command', '-ExecutionPolicy', 'cmd.exe'))


def test_unsupported_windows_wrapper_is_not_executed(tmp_path, monkeypatch):
    cmd = tmp_path / 'agent.cmd'; cmd.write_text('@echo off')
    monkeypatch.setattr(cp.shutil, 'which', lambda s: str(cmd))
    with pytest.raises(BrainError) as e: cp.resolve_cursor('agent', platform='nt')
    assert e.value.code == 'CURSOR_WRAPPER'


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    """A real child process with scripted response; NOT Cursor's binary."""
    fake = tmp_path / 'cursor_cli_STAND_IN.py'
    fake.write_text('''import sys,json,os,pathlib,uuid
if '--help' in sys.argv:
 print('--print --mode --output-format --workspace --trust --sandbox --model');sys.exit(0)
if '--version' in sys.argv:
 print('TEST-DOUBLE-1.0 (not Cursor)');sys.exit(0)
mode=os.environ.get('FAKE_CURSOR_MODE','ok')
assert '--print' in sys.argv and sys.argv[sys.argv.index('--mode')+1]=='ask'
assert sys.argv[sys.argv.index('--output-format')+1]=='json'
assert '--force' not in sys.argv and '--approve-mcps' not in sys.argv and '--resume' not in sys.argv
cwd=pathlib.Path.cwd()
assert pathlib.Path(sys.argv[sys.argv.index('--workspace')+1])==cwd
policy=json.loads((cwd/'.cursor/cli.json').read_text())
assert 'Shell(*)' in policy['permissions']['deny'] and 'Mcp(*:*)' in policy['permissions']['deny']
prompt=sys.stdin.read();assert 'JSON SCHEMA:' in prompt and 'CONTEXT JSON:' in prompt
if mode=='exit':
 print('scripted authentication error',file=sys.stderr);sys.exit(7)
if mode=='tamper': (cwd/'schema.json').write_text('{}')
if mode=='bad': print('{}');sys.exit(0)
if mode=='slow':
 import time;time.sleep(3)
response=json.loads(pathlib.Path(os.environ['FAKE_CURSOR_RESPONSE']).read_text(encoding='utf-8'))
session='fixed-session' if mode=='reuse' else str(uuid.uuid4())
print(json.dumps({'type':'result','subtype':'success','is_error':False,'session_id':session,'result':json.dumps(response,ensure_ascii=False)},ensure_ascii=False))
''', encoding='utf-8')
    response = tmp_path / 'fake_response.json'; response.write_text(json.dumps(VALUE), encoding='utf-8')
    monkeypatch.setenv('FAKE_CURSOR_RESPONSE', str(response))
    monkeypatch.setattr(cp, 'resolve_cursor', lambda executable=None: [sys.executable, str(fake)])
    return response


def test_cursor_provider_real_process_native_json_and_receipt(fake_cli, tmp_path):
    provider = cp.CursorProvider(tmp_path / 'calls', model='owner-selected-model')
    result = provider.generate('Check the geometry.', SCHEMA, {'original_request': '外形は変更しない。'}, role='requirements')
    assert result == VALUE
    receipt = json.loads(next((tmp_path / 'calls').glob('*/receipt.json')).read_text(encoding='utf-8'))
    assert receipt['response_received'] and receipt['requested_mode'] == 'ask'
    assert receipt['provider_version'].startswith('TEST-DOUBLE')
    assert receipt['actual_sandbox_enforcement_verified'] is False
    assert not any('cadmcp-cursor-' in p.name for p in (tmp_path / 'calls').iterdir())


@pytest.mark.parametrize('mode,code', [('exit', 'AGENT_FAILED'), ('tamper', 'CURSOR_INPUT_CHANGED'), ('bad', 'CURSOR_RESULT')])
def test_cursor_process_errors_preserve_receipt(fake_cli, tmp_path, monkeypatch, mode, code):
    monkeypatch.setenv('FAKE_CURSOR_MODE', mode)
    p = cp.CursorProvider(tmp_path / 'calls')
    with pytest.raises(BrainError) as e: p.generate('Test.', SCHEMA, {})
    assert e.value.code == code
    receipt = json.loads(next((tmp_path / 'calls').glob('*/receipt.json')).read_text(encoding='utf-8'))
    assert receipt['response_received'] is False
    assert receipt['error']['code'] == code


def test_cursor_budget_and_fresh_sessions(fake_cli, tmp_path, monkeypatch):
    monkeypatch.setenv('FAKE_CURSOR_MODE', 'reuse')
    p = cp.CursorProvider(tmp_path / 'calls', max_calls=2)
    p.generate('Test.', SCHEMA, {})
    with pytest.raises(BrainError) as e: p.generate('Test.', SCHEMA, {})
    assert e.value.code == 'CURSOR_SESSION_REUSED'
    with pytest.raises(BrainError) as e: p.generate('Test.', SCHEMA, {})
    assert e.value.code == 'AGENT_BUDGET'
    assert len(list((tmp_path / 'calls').glob('*/receipt.json'))) == 2


def test_parallel_role_receipts_are_distinct(fake_cli, tmp_path):
    p = cp.CursorProvider(tmp_path / 'calls', max_calls=3)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda role: p.generate('Test.', SCHEMA, {}, role=role), ['mechanism','assembly','verification']))
    assert all(r == VALUE for r in results)
    receipts = [json.loads(f.read_text(encoding='utf-8')) for f in (tmp_path / 'calls').glob('*/receipt.json')]
    assert len({r['session_id'] for r in receipts}) == 3
    assert {r['call_number'] for r in receipts} == {1, 2, 3}


def test_cursor_capability_check_never_generates(fake_cli, tmp_path):
    info = cp.probe_cursor()
    assert not info['generation_executed'] and not info['authentication_verified']


def test_capability_failure_stops_without_restricted_mode_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, 'resolve_cursor', lambda executable=None: [sys.executable, '-c', 'print("--print")'])
    with pytest.raises(BrainError) as e: cp.probe_cursor()
    assert e.value.code == 'CURSOR_CAPABILITY'


def test_explicit_permissions_only_does_not_claim_sandbox(fake_cli, tmp_path):
    p = cp.CursorProvider(tmp_path / 'calls', require_sandbox=False)
    p.generate('Test.', SCHEMA, {})
    r = json.loads(next((tmp_path / 'calls').glob('*/receipt.json')).read_text(encoding='utf-8'))
    assert r['requested_sandbox'] == 'owner_selected_permissions_only'


def test_snapshot_copies_only_explicit_regular_files_and_preserves_request(tmp_path):
    root = tmp_path / 'workspace'; root.mkdir()
    file = root / 'picture.png'; file.write_bytes(b'fixture')
    outside = tmp_path / 'external.png'; outside.write_bytes(b'private-not-copied')
    target = tmp_path / 'snapshot'; target.mkdir()
    ctx = {'original_request': str(file), 'exports': {'absolute_path': str(file)}, 'outside': str(outside)}
    staged, index = cp.snapshot_context(ctx, target, root)
    assert staged['original_request'] == ctx['original_request']
    assert staged['exports']['absolute_path'].startswith('evidence/')
    assert staged['outside'] == str(outside)
    assert len(index) == 1
    assert (target / index[0]['snapshot']).read_bytes() == b'fixture'


def test_snapshot_symlink_and_budget(tmp_path, monkeypatch):
    root = tmp_path / 'workspace'; root.mkdir()
    original = root / 'original.png'; original.write_bytes(b'0123456789')
    link = root / 'link.png'
    try: link.symlink_to(original)
    except OSError: pytest.skip('This OS does not permit symlinks')
    output = tmp_path / 'out'; output.mkdir()
    staged, index = cp.snapshot_context({'image': str(link)}, output, root)
    assert index == [] and staged['image'] == str(link)
    monkeypatch.setattr(cp, 'MAX_EVIDENCE', 2)
    with pytest.raises(BrainError) as e: cp.snapshot_context({'image': str(original)}, output, root)
    assert e.value.code == 'CURSOR_EVIDENCE_LIMIT'


def test_cursor_cli_is_opt_in_before_provider_probe(tmp_path):
    result = subprocess.run([sys.executable, '-m', 'cadmcp_brain.studio', '--workspace', str(tmp_path / 'workspace'),
                             'autopilot', '--provider', 'cursor', '--project', 'mouse'], capture_output=True, text=True)
    assert result.returncode != 0 and 'No model was called' in result.stderr
    assert not (tmp_path / 'workspace').exists()


def test_cursor_setup_preserves_mcp_env_and_does_not_modify_global(tmp_path):
    project = tmp_path / '日本語 project'; project.mkdir()
    (project / '.cursor').mkdir()
    prior = {'mcpServers': {'fusion': {'command': 'untouched'}, 'cadmcp-design-brain': {
             'command': 'old-python', 'args': ['-m', 'cadmcp_brain', '--workspace', 'old-workspace', 'serve'],
             'env': {'CADMCP_PROTECTED_ARTIFACT_IDS': '["PCB"]'}, 'disabled': False}}, 'custom': 10}
    path = project / '.cursor/mcp.json'; path.write_text(json.dumps(prior)); before = path.read_bytes()
    result = setup.configure_cursor(project, Path(sys.executable), tmp_path / 'space 日本語', assets={'docs/owned.md': b'owned'})
    after = json.loads(path.read_text(encoding='utf-8'))
    assert after['mcpServers']['fusion'] == prior['mcpServers']['fusion']
    assert after['custom'] == 10
    assert after['mcpServers']['cadmcp-design-brain']['env']['CADMCP_PROTECTED_ARTIFACT_IDS'] == '["PCB"]'
    assert any(Path(x).read_bytes() == before for x in result['backups'])
    again = setup.configure_cursor(project, Path(sys.executable), tmp_path / 'space 日本語', assets={'docs/owned.md': b'owned'})
    assert again['changed'] == [] and not again['model_called']


def test_install_preflight_preserves_local_changes_then_explicit_backup(tmp_path):
    project = tmp_path / 'project'; project.mkdir()
    file = project / 'rule.md'; file.write_text('local customization')
    kwargs = dict(project=project, python=Path(sys.executable), workspace=tmp_path / 'w', assets={'rule.md': b'release-content'})
    with pytest.raises(ValueError): setup.configure_cursor(**kwargs)
    assert file.read_text() == 'local customization' and not (project / '.cursor/mcp.json').exists()
    result = setup.configure_cursor(**kwargs, replace_managed=True)
    assert file.read_text() == 'release-content'
    assert any(Path(x).read_text() == 'local customization' for x in result['backups'])
    # An unmodified, installer-managed file can be upgraded without force.
    kwargs['assets'] = {'rule.md': b'new-release'}
    setup.configure_cursor(**kwargs)
    assert file.read_text() == 'new-release'


@pytest.mark.parametrize('bad', ['[]', '{"mcpServers":[]}', '{"mcpServers":{},"mcpServers":{}}', '// JSONC\n{}'])
def test_install_refuses_invalid_mcp_before_any_asset_write(tmp_path, bad):
    (tmp_path / '.cursor').mkdir()
    path = tmp_path / '.cursor/mcp.json'; path.write_text(bad)
    with pytest.raises(ValueError): setup.configure_cursor(tmp_path, sys.executable, tmp_path / 'w', assets={'new.md': b'new'})
    assert path.read_text() == bad and not (tmp_path / 'new.md').exists()


def test_dry_run_writes_nothing(tmp_path):
    result = setup.configure_cursor(tmp_path, sys.executable, tmp_path / 'w', assets={'new.md': b'new'}, dry_run=True)
    assert result['dry_run'] and not list(tmp_path.iterdir())


def test_real_cursor_asset_set_has_five_readonly_roles_and_no_codex_dependency():
    assets = setup.managed_files()
    agents = {p: v.decode('utf-8') for p, v in assets.items() if p.startswith('.cursor/agents/')}
    assert len(agents) == 5
    for role in ('requirements','mechanism','assembly','manufacturing','verification'):
        content = agents[f'.cursor/agents/cadmcp-{role}.md']
        assert 'model: inherit' in content and 'readonly: true' in content and 'is_background: false' in content
    assert '.cursor/skills/cadmcp-cursor/SKILL.md' in assets
    assert '.cursor/commands/cad-check.md' in assets


# Reuse only the real-CAD fixture and explicit scripted data from the baseline.
# The added transport still starts a child process for EVERY generated reply.
from test_studio import actual, local, ScriptedOrchestrationFixture


@pytest.mark.skipif(importlib.util.find_spec("cadquery") is None, reason="Actual CAD kernel not installed; Cursor transport CAD test not executed.")
def test_full_cad_pipeline_and_peer_round_via_cursor_transport(local, fake_cli, tmp_path):
    tools, fixture = local
    scripted = ScriptedOrchestrationFixture(fixture)
    actual = cp.CursorProvider(tmp_path / 'cursor_calls', evidence_root=tools.brain.store.root)
    class CursorTransportWithScriptedAnswers:
        def generate(self, task, schema, context, *, role='designer'):
            answer = scripted.generate(task, schema, context, role=role)
            fake_cli.write_text(json.dumps(answer, ensure_ascii=False), encoding='utf-8')
            return actual.generate(task, schema, context, role=role)
    result = Autopilot(tools, CursorTransportWithScriptedAnswers(), tmp_path / 'orchestration',
                       search_mode='lexical', max_repairs=0, debate_rounds=2).run('public-test')
    assert result['phase'] == 'prototype_ready_for_owner_review'
    assert result['overall_verdict'] == 'unknown' and actual.calls == 14
    receipts = list((tmp_path / 'cursor_calls').glob('*/receipt.json'))
    assert len(receipts) == 14
    assert Path(result['build']['assembly_step']).is_file()
