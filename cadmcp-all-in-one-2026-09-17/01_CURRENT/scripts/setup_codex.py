"""Install project-scoped Codex MCP and existing CAD skills without global changes."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tomllib
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cursor_setup_shared', ROOT / 'scripts/setup_cursor.py')
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
SERVER = 'cadmcp-design-brain'
BEGIN = '# BEGIN cadMCP managed configuration'
END = '# END cadMCP managed configuration'


def render_config(original, python, workspace):
    """Preserve unrelated TOML verbatim; refuse an unmanaged conflicting server."""
    doc = tomllib.loads(original)
    servers = doc.get('mcp_servers', {})
    if not isinstance(servers, dict):
        raise ValueError('mcp_servers must be a TOML table')
    if original.count(BEGIN) != original.count(END) or original.count(BEGIN) > 1:
        raise ValueError('Malformed cadMCP managed block')
    prefix, suffix = original, ''
    previous = servers.get(SERVER, {})
    if BEGIN in original:
        start, stop = original.index(BEGIN), original.index(END) + len(END)
        if stop <= start:
            raise ValueError('Malformed cadMCP managed block order')
        prefix, suffix = original[:start], original[stop:]
        remainder = tomllib.loads(prefix + suffix)
        if remainder.get('mcp_servers', {}).get(SERVER) is not None:
            raise ValueError('cadMCP server also exists outside managed block')
        if {k:v for k,v in doc.items() if k != 'mcp_servers'} != {k:v for k,v in remainder.items() if k != 'mcp_servers'}:
            raise ValueError('Unrelated configuration inside managed block')
        if {k:v for k,v in servers.items() if k != SERVER} != remainder.get('mcp_servers', {}):
            raise ValueError('Unrelated MCP inside managed block')
    elif SERVER in servers:
        raise ValueError('Existing unmanaged cadMCP server: review and migrate this entry explicitly')
    env = previous.get('env', {})
    if not isinstance(env, dict) or not all(isinstance(v, str) for v in env.values()):
        raise ValueError('cadMCP environment must contain strings')
    enabled = previous.get('enabled', False)
    if not isinstance(enabled, bool):
        raise ValueError('cadMCP enabled must be a boolean')
    # Preserve owner policy and custom environment on repeated installations.
    env = {'CADMCP_REQ2CAD_ROOT': str(workspace / 'knowledge/req2cad'),
           'CADMCP_REQUIRE_CAD_REFERENCES': '1', **env,
           'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
    # New project-scoped installs are opt-in: the host must not start cadMCP
    # during ordinary development.  An existing explicit setting is retained.
    entry = {**previous, 'enabled': enabled, 'command': str(python),
             'args': ['-m', 'cadmcp_brain', '--workspace', str(workspace), 'serve'],
             'cwd': str(ROOT), 'startup_timeout_sec': 60, 'tool_timeout_sec': 600}
    if 'url' in entry:
        raise ValueError('Remote cadMCP entry cannot be replaced by local configuration')
    lines = [BEGIN, f'[mcp_servers.{SERVER}]']
    for key, value in entry.items():
        if key == 'env':
            continue
        if not isinstance(value, (str, int, float, bool, list)):
            raise ValueError('Unsupported custom server field: ' + key)
        lines.append(json.dumps(key) + ' = ' + json.dumps(value, ensure_ascii=False, allow_nan=False))
    lines += ['', f'[mcp_servers.{SERVER}.env]']
    lines += [json.dumps(k) + ' = ' + json.dumps(v, ensure_ascii=False) for k,v in env.items()]
    lines += [END]
    result = prefix.rstrip() + ('\n\n' if prefix.strip() else '') + '\n'.join(lines) + '\n' + suffix.lstrip('\r\n')
    tomllib.loads(result)
    return result


def configure_codex(project, python, workspace, *, dry_run=False, replace_managed=False):
    project, python, workspace = Path(project).resolve(), Path(python).absolute(), Path(workspace).absolute()
    if not project.is_dir() or not python.is_file():
        raise ValueError('An existing project directory and Python executable are required')
    config = shared.safe_target(project, '.codex/config.toml')
    manifest_path = shared.safe_target(project, '.codex/cadmcp-install.json')
    manifest = shared.json_object(manifest_path.read_bytes()) if manifest_path.exists() else {}
    known = manifest.get('managed_sha256', {})
    updates = {}
    for source in sorted((ROOT / '.agents/skills/cadmcp-design-brain').rglob('*')):
        if source.is_file():
            rel = source.relative_to(ROOT).as_posix()
            data = source.read_bytes()
            target = shared.safe_target(project, rel)
            if target.exists() and target.read_bytes() != data and shared.sha(target.read_bytes()) != known.get(rel) and not replace_managed:
                raise ValueError('Customized skill conflict: ' + rel)
            updates[rel] = data
    hashes = {rel: shared.sha(data) for rel,data in updates.items()}
    original = config.read_text('utf-8-sig') if config.exists() else ''
    updates['.codex/config.toml'] = render_config(original, python, workspace).encode('utf-8')
    updates['.codex/cadmcp-install.json'] = (json.dumps({'format': 1, 'managed_sha256': hashes,
        'workspace': str(workspace), 'python': str(python)}, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    changed = [rel for rel,data in updates.items() if not shared.safe_target(project,rel).exists() or shared.safe_target(project,rel).read_bytes() != data]
    result = {'project': str(project), 'changed': changed, 'dry_run': dry_run, 'backups': [], 'model_called': False}
    if dry_run:
        return result
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    for rel in changed:
        target = shared.safe_target(project, rel)
        if target.exists():
            backup = target.with_name(target.name + '.backup-' + stamp)
            with backup.open('xb') as stream:
                stream.write(target.read_bytes())
            result['backups'].append(str(backup))
    for rel in changed:
        shared.bootstrap.atomic_text(shared.safe_target(project, rel), updates[rel].decode('utf-8'))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--python', type=Path, default=shared.bootstrap.python_in(ROOT / '.venv'))
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--replace-managed', action='store_true')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(configure_codex(**vars(args)), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print('Codex setup stopped: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
