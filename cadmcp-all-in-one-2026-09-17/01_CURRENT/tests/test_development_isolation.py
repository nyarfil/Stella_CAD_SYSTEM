import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('connection_isolation', ROOT / 'scripts/check_cursor_connection.py')
connection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(connection)


def _config(project, production, *, enabled=False):
    path = project / '.cursor/mcp.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'mcpServers': {
        'other': {'command': 'keep-me'},
        'cadmcp-design-brain': {
            'command': 'host-python',
            'args': ['-m', 'cadmcp_brain', '--workspace', str(production), 'serve'],
            'cwd': str(project / 'production-cwd'),
            'enabled': enabled,
            'env': {'OWNER_ENV': 'keep'},
        },
    }}, indent=2) + '\n', encoding='utf-8')
    return path


def _protocol_output():
    tools = [
        {'name': 'brain_fs_search_tasks'}, {'name': 'brain_fs_materialize'},
        {'name': 'brain_studio_build'}, {'name': 'brain_studio_review_packet'},
    ]
    replies = [
        {'jsonrpc': '2.0', 'id': 1, 'result': {'serverInfo': {'name': 'test', 'version': '0'}}},
        {'jsonrpc': '2.0', 'id': 2, 'result': {'tools': tools}},
        {'jsonrpc': '2.0', 'id': 3, 'result': {'structuredContent': {'ok': True}}},
        {'jsonrpc': '2.0', 'id': 4, 'result': {'structuredContent': {'result': {'cases': 0}}}},
        {'jsonrpc': '2.0', 'id': 5, 'result': {'structuredContent': {'schema': True}}},
    ]
    return ''.join(json.dumps(reply) + '\n' for reply in replies)


def test_disabled_entry_is_rejected_without_isolated_workspace(tmp_path, monkeypatch):
    _config(tmp_path, tmp_path / 'production')
    monkeypatch.setattr(connection.subprocess, 'run', lambda *args, **kwargs: pytest.fail('must not start disabled cadmcp'))
    with pytest.raises(ValueError, match='disabled'):
        connection.check(tmp_path, 'cursor')


def test_isolated_check_replaces_module_and_roots_without_config_write(tmp_path, monkeypatch):
    production = tmp_path / 'production'
    isolated = tmp_path / 'isolated'
    production.mkdir()
    isolated.mkdir()
    config = _config(tmp_path, production)
    before = config.read_bytes()
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=_protocol_output(), stderr='')

    monkeypatch.setattr(connection.subprocess, 'run', fake_run)
    result = connection.check(tmp_path, 'cursor', isolated_test_workspace=isolated)

    command, kwargs = calls[0]
    assert command == ['host-python', '-m', 'cadmcp_brain', '--workspace', str(isolated.resolve()), 'serve']
    assert kwargs['cwd'] == str(connection.ROOT)
    assert kwargs['env']['OWNER_ENV'] == 'keep'
    assert kwargs['env']['CADMCP_REQ2CAD_ROOT'] == str((isolated / 'knowledge/req2cad').resolve())
    assert result['configured_enabled'] is False
    assert result['isolated_test_workspace'] == str(isolated.resolve())
    assert result['host_config_modified'] is False
    assert config.read_bytes() == before


def test_production_workspace_cannot_be_reused_as_isolated_workspace(tmp_path, monkeypatch):
    production = tmp_path / 'production'
    production.mkdir()
    _config(tmp_path, production)
    monkeypatch.setattr(connection.subprocess, 'run', lambda *args, **kwargs: pytest.fail('must refuse before start'))
    with pytest.raises(ValueError, match='differ'):
        connection.check(tmp_path, 'cursor', isolated_test_workspace=production)


def test_cli_accepts_explicit_isolation_flag(tmp_path, monkeypatch, capsys):
    production = tmp_path / 'production'
    isolated = tmp_path / 'isolated'
    production.mkdir()
    isolated.mkdir()
    _config(tmp_path, production)
    monkeypatch.setattr(connection.subprocess, 'run', lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 0, stdout=_protocol_output(), stderr=''))
    assert connection.main(['--project', str(tmp_path), '--isolated-test-workspace', str(isolated)]) == 0
    assert json.loads(capsys.readouterr().out)['isolated_test_workspace'] == str(isolated.resolve())
