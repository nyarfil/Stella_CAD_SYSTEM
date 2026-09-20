#!/usr/bin/env python3
"""Test the configured local CAD MCP stdio process, not the Cursor GUI/model."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
SERVER = 'cadmcp-design-brain'


def _configured_workspace(entry: dict) -> Path | None:
    """Return the workspace named by the host entry, when it is explicit."""
    args = entry.get('args', [])
    if isinstance(args, list) and '--workspace' in args:
        index = args.index('--workspace')
        if index + 1 < len(args) and isinstance(args[index + 1], str):
            return Path(args[index + 1]).expanduser().resolve()
    env = entry.get('env', {})
    if isinstance(env, dict) and isinstance(env.get('CADMCP_WORKSPACE'), str):
        return Path(env['CADMCP_WORKSPACE']).expanduser().resolve()
    if isinstance(env, dict) and isinstance(env.get('CADMCP_REQ2CAD_ROOT'), str):
        # The managed layout is <workspace>/knowledge/req2cad.  This fallback
        # keeps the production-root equality guard effective for older entries
        # that supplied only the Req2CAD environment variable.
        req2cad = Path(env['CADMCP_REQ2CAD_ROOT']).expanduser().resolve()
        if req2cad.name == 'req2cad' and req2cad.parent.name == 'knowledge':
            return req2cad.parent.parent
    return None


def _isolated_entry(entry: dict, workspace: Path) -> tuple[str, list[str], str, dict[str, str]]:
    """Build a known local cadmcp command without mutating host configuration."""
    workspace = workspace.expanduser().resolve()
    if workspace.exists() and not workspace.is_dir():
        raise ValueError('The isolated test workspace must be a directory: ' + str(workspace))
    production = _configured_workspace(entry)
    if production is not None and production == workspace:
        raise ValueError('The isolated test workspace must differ from the configured production workspace.')
    env = entry.get('env', {})
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise ValueError('MCP environment entries must be strings.')
    isolated_env = dict(env)
    isolated_env['CADMCP_REQ2CAD_ROOT'] = str(workspace / 'knowledge' / 'req2cad')
    # The executable is kept from the validated host entry so its installed
    # dependencies remain available; module, cwd, and all state roots are fixed.
    return (entry['command'], ['-m', 'cadmcp_brain', '--workspace', str(workspace), 'serve'],
            str(ROOT), isolated_env)


def check(project: Path, host: str='cursor', isolated_test_workspace: Path | None = None) -> dict:
    if host == 'codex':
        path = project.resolve() / '.codex/config.toml'
        config = tomllib.loads(path.read_text('utf-8-sig'))
        entry = config.get('mcp_servers', {}).get('cadmcp-design-brain')
    elif host == 'cursor':
        path = project.resolve() / '.cursor/mcp.json'
        config = json.loads(path.read_text('utf-8-sig'))
        entry = config.get('mcpServers', {}).get('cadmcp-design-brain')
    else:
        raise ValueError('host must be cursor or codex')
    if not isinstance(entry, dict): raise ValueError('cadmcp-design-brain is not configured in this project.')
    enabled = entry.get('enabled', True)
    if not isinstance(enabled, bool):
        raise ValueError('cadmcp enabled must be a boolean.')
    if not enabled and isolated_test_workspace is None:
        raise ValueError('cadmcp-design-brain is disabled; pass --isolated-test-workspace for a test-only check.')
    command, args, extra_env = entry.get('command'), entry.get('args'), entry.get('env', {})
    if not isinstance(command, str) or not isinstance(args, list) or not all(isinstance(x, str) for x in args):
        raise ValueError('Expected a local command and a string argument array.')
    if '-m' not in args or 'cadmcp_brain' not in args or 'serve' not in args or entry.get('url'):
        raise ValueError('This check only starts the known local cadmcp_brain module, not an arbitrary remote MCP.')
    if not isinstance(extra_env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in extra_env.items()):
        raise ValueError('MCP environment entries must be strings.')
    messages = [
        {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'cadmcp-cursor-config-check','version':'0.3.1'}}},
        {'jsonrpc':'2.0','method':'notifications/initialized'},
        {'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}},
        {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'brain_doctor','arguments':{}}},
        {'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'brain_fs_status','arguments':{}}},
        {'jsonrpc':'2.0','id':5,'method':'tools/call','params':{'name':'brain_studio_schema','arguments':{'name':'FunctionBrief'}}},
    ]
    production_workspace = _configured_workspace(entry)
    isolated = None
    if isolated_test_workspace is not None:
        command, args, cwd, extra_env = _isolated_entry(entry, Path(isolated_test_workspace))
        isolated = str(Path(isolated_test_workspace).expanduser().resolve())
    else:
        cwd = entry.get('cwd', project.resolve())
    proc = subprocess.run([command, *args], input=''.join(json.dumps(m)+'\n' for m in messages),
                          capture_output=True, text=True, encoding='utf-8', cwd=cwd,
                          env={**os.environ, **extra_env}, timeout=45)
    if proc.returncode: raise ValueError('MCP process failed: ' + proc.stderr[-2000:])
    replies = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    if len(replies) != 5 or {r.get('id') for r in replies} != {1,2,3,4,5}:
        raise ValueError('Expected five JSON-RPC replies; stdout may contain unexpected output.')
    by_id = {r['id']:r for r in replies}
    if any('error' in r or r.get('result', {}).get('isError') for r in replies):
        raise ValueError('MCP returned a protocol/tool error: ' + json.dumps(replies, ensure_ascii=False)[:2000])
    names = {t['name'] for t in by_id[2]['result']['tools']}
    required = {'brain_fs_search_tasks','brain_fs_materialize','brain_studio_build','brain_studio_review_packet'}
    if not required <= names: raise ValueError('Required Studio tools are missing.')
    return {'check':'configured MCP stdio process; NOT a real host GUI/model session', 'host':host,
            'mcp_protocol_ok':True,'server_info':by_id[1]['result']['serverInfo'],
            'tool_count':len(names),'required_studio_tools_present':True,
            'doctor':by_id[3]['result'].get('structuredContent'),
            'req2cad_status':by_id[4]['result'].get('structuredContent'),
            'schema_received':bool(by_id[5]['result'].get('structuredContent')),
            'model_called':False,'cursor_gui_tested':False,
            'configured_enabled':enabled,
            'isolated_test_workspace':isolated,
            'production_workspace':str(production_workspace) if production_workspace else None,
            'host_config_modified':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=Path.cwd())
    parser.add_argument('--host',choices=['cursor','codex'],default='cursor')
    parser.add_argument('--isolated-test-workspace',type=Path,
                        help='Run only the known local cadmcp module against this existing test workspace.')
    parser.add_argument('--report',type=Path)
    args=parser.parse_args(argv)
    try:
        result=check(args.project,args.host,args.isolated_test_workspace)
        text=json.dumps(result,ensure_ascii=False,indent=2)
        if args.report:
            args.report.parent.mkdir(parents=True,exist_ok=True)
            args.report.write_text(text+'\n',encoding='utf-8')
        print(text);return 0
    except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
        print(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
