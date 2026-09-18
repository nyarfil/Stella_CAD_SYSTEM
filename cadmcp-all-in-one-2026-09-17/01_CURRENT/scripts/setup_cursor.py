#!/usr/bin/env python3
"""Explicit Cursor project setup; preserve unrelated MCPs and local customizations."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cadmcp_bootstrap', ROOT / 'scripts/bootstrap.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)
SERVER = 'cadmcp-design-brain'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_object(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result: raise ValueError('Duplicate JSON key: ' + k)
            result[k] = v
        return result
    def reject(value): raise ValueError('Non-finite JSON number: ' + value)
    doc = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=pairs, parse_constant=reject)
    if not isinstance(doc, dict): raise ValueError('Existing JSON must be an object; nothing was changed.')
    return doc


def managed_files(root=ROOT):
    files = [root / '.cursor/rules/cadmcp-design-brain.mdc']
    for part in ('.cursor/agents', '.cursor/commands', '.cursor/skills/cadmcp-cursor'):
        files += sorted(p for p in (root / part).rglob('*') if p.is_file())
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in files}


def safe_target(project, relative):
    target = project / relative
    if not target.resolve().is_relative_to(project): raise ValueError('Target escapes the selected project: ' + relative)
    for p in [target, *target.parents]:
        if p == project: break
        if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
            raise ValueError('Refusing symlink/junction: ' + str(p))
    if target.exists() and not target.is_file(): raise ValueError('Expected a regular file: ' + str(target))
    return target


def configure_cursor(project, python, workspace, *, replace_managed=False, dry_run=False, assets=None):
    """Preflight all managed files before writes. Back up every changed existing file.

    A journal permits diagnosis of OS interruption. This is not a transactional
    multi-file update across a crash; the preserved backups allow manual recovery.
    """
    project, python, workspace = Path(project).resolve(), Path(python).absolute(), Path(workspace).absolute()
    if not project.is_dir(): raise ValueError('--project must be an existing directory')
    if not python.is_file(): raise ValueError('Python executable does not exist: ' + str(python))
    assets = managed_files() if assets is None else assets
    manifest_path = safe_target(project, '.cursor/cadmcp-install.json')
    old_manifest = json_object(manifest_path.read_bytes()) if manifest_path.exists() else {}
    known = old_manifest.get('managed_sha256', {})
    if not isinstance(known, dict): raise ValueError('Unsupported install manifest')
    updates = {}
    for rel, data in assets.items():
        target = safe_target(project, rel)
        if target.exists() and target.read_bytes() != data:
            if sha(target.read_bytes()) != known.get(rel) and not replace_managed:
                raise ValueError('Customized/existing managed file conflicts: ' + rel + '. Review the diff; --replace-managed explicitly backs up and replaces only these managed files.')
        updates[rel] = data
    mcp_path = safe_target(project, '.cursor/mcp.json')
    doc = json_object(mcp_path.read_bytes()) if mcp_path.exists() else {}
    servers = doc.setdefault('mcpServers', {})
    if not isinstance(servers, dict): raise ValueError('Existing mcpServers must be an object')
    entry = bootstrap.config_entry(python, workspace)
    previous = servers.get(SERVER)
    if previous is not None:
        if not isinstance(previous, dict): raise ValueError('Conflicting MCP server entry')
        args = previous.get('args', [])
        if previous != entry and not (isinstance(args, list) and 'cadmcp_brain' in args and 'serve' in args and '-m' in args and 'url' not in previous):
            raise ValueError('The existing cadmcp-design-brain entry is not a recognized local module. Do not overwrite it automatically.')
        merged = dict(previous)
        env = previous.get('env', {})
        if not isinstance(env, dict): raise ValueError('Existing MCP env is not an object')
        merged.update(entry)
        merged['env'] = {**env, **entry['env']}
        entry = merged
    servers[SERVER] = entry
    updates['.cursor/mcp.json'] = (json.dumps(doc, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    changed = []
    for rel, data in updates.items():
        target = safe_target(project, rel)
        if not target.exists() or target.read_bytes() != data: changed.append(rel)
    result = {'project': str(project), 'workspace': str(workspace), 'server': SERVER,
              'changed': changed, 'dry_run': dry_run, 'backups': [], 'model_called': False,
              'existing_unrelated_mcp_entries_preserved': True}
    if dry_run: return result
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    journal_path = safe_target(project, '.cursor/cadmcp-install-journal.json')
    journal = {'started': stamp, 'planned': changed, 'written': [], 'complete': False}
    # Backups precede any content writes, including the old install manifest.
    for rel in changed + (['.cursor/cadmcp-install.json'] if manifest_path.exists() else []):
        target = safe_target(project, rel)
        if target.exists():
            backup = target.with_name(target.name + '.backup-' + stamp)
            with backup.open('xb') as f: f.write(target.read_bytes())
            result['backups'].append(str(backup))
    bootstrap.atomic_text(journal_path, json.dumps(journal, ensure_ascii=False, indent=2))
    for rel in changed:
        target = safe_target(project, rel)
        bootstrap.atomic_text(target, updates[rel].decode('utf-8'))
        journal['written'].append(rel)
        bootstrap.atomic_text(journal_path, json.dumps(journal, ensure_ascii=False, indent=2))
    manifest = {'format': 1, 'release': '0.3.1', 'managed_sha256': {rel: sha(data) for rel, data in assets.items()},
                'workspace': str(workspace), 'python': str(python), 'server': SERVER,
                'note': 'Only these managed files and the named MCP entry are updated. Existing custom environment keys are preserved.'}
    bootstrap.atomic_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    journal['complete'] = True
    bootstrap.atomic_text(journal_path, json.dumps(journal, ensure_ascii=False, indent=2))
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', type=Path, default=ROOT, help='Existing Cursor project; default is this extracted package.')
    p.add_argument('--workspace', type=Path, default=ROOT / 'workspace')
    p.add_argument('--geometry', action='store_true')
    p.add_argument('--no-install', action='store_true', help='Use an already-installed environment; no pip or test run.')
    p.add_argument('--python', type=Path, help='Python of an existing environment, used with --no-install.')
    p.add_argument('--replace-managed', action='store_true', help='Explicitly back up/replace conflicting managed rule/skill/subagent files only.')
    p.add_argument('--dry-run', action='store_true', help='Preview configuration changes, no writes or package installation.')
    args = p.parse_args(argv)
    if args.python and not args.no_install: p.error('--python requires --no-install')
    if not args.project.is_dir(): p.error('--project must already exist')
    python = args.python or bootstrap.python_in(ROOT / '.venv')
    try:
        if not args.no_install and not args.dry_run:
            command = [sys.executable, str(ROOT / 'scripts/bootstrap.py'), '--workspace', str(args.workspace.absolute())]
            if args.geometry: command.append('--geometry')
            subprocess.run(command, check=True, cwd=ROOT)
        result = configure_cursor(args.project, python, args.workspace,
                                  replace_managed=args.replace_managed, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not args.dry_run:
            print('Cursor setup files written. Reopen the project/reload MCP, then use /cad-check.')
            print('No model was called. GUI recognition and account authentication must be checked in your Cursor installation.')
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print('Cursor setup stopped: ' + str(exc), file=sys.stderr)
        return 1

if __name__ == '__main__': raise SystemExit(main())
