#!/usr/bin/env python3
"""Owner-run installer. Never edits a CAD repository unless --cursor-project is given."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import venv

ROOT=Path(__file__).resolve().parents[1]


def python_in(venv_dir: Path) -> Path:
    return venv_dir/('Scripts/python.exe' if os.name=='nt' else 'bin/python')


def run(argv: list[str],cwd: Path=ROOT) -> None:
    subprocess.run(argv,cwd=cwd,check=True,env=dict(os.environ,PYTHONUTF8='1'))


def config_entry(python: Path,workspace: Path) -> dict:
    return {'type':'stdio','command':str(python.absolute()),'args':['-m','cadmcp_brain','--workspace',str(workspace.absolute()),'serve'],'env':{'PYTHONUTF8':'1'}}


def atomic_text(path: Path,text: str) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink(): raise ValueError(f'Refusing symlink: {path}')
    tmp=path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
    try:
        with tmp.open('x',encoding='utf-8',newline='\n') as f:f.write(text)
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)


def merge_cursor(path: Path,entry: dict) -> dict:
    """Preserve all unrelated keys. Refuse comments/invalid JSON instead of destroying it."""
    if path.is_symlink():raise ValueError(f'Refusing symlink: {path}')
    if path.exists():
        original=path.read_bytes()
        doc=json.loads(original.decode('utf-8-sig'))
        if not isinstance(doc,dict) or not isinstance(doc.get('mcpServers',{}),dict):
            raise ValueError('Existing mcp.json has an unsupported structure; no changes made')
    else: original=None;doc={}
    current=doc.setdefault('mcpServers',{})
    if current.get('cadmcp-design-brain')==entry:return {'changed':False,'file':str(path),'backup':None}
    current['cadmcp-design-brain']=entry
    backup=None
    if original is not None:
        backup=path.with_name(path.name+'.backup-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:6])
        with backup.open('xb') as f:f.write(original)
    atomic_text(path,json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
    return {'changed':True,'file':str(path),'backup':str(backup) if backup else None}


def write_configs(python: Path,workspace: Path,destination: Path) -> dict:
    entry=config_entry(python,workspace)
    destination.mkdir(parents=True,exist_ok=True)
    atomic_text(destination/'cursor.mcp.json',json.dumps({'mcpServers':{'cadmcp-design-brain':entry}},ensure_ascii=False,indent=2)+'\n')
    # JSON basic strings/arrays are valid TOML for these path/argument values.
    toml='[mcp_servers.cadmcp-design-brain]\ncommand = '+json.dumps(entry['command'],ensure_ascii=False)+'\nargs = '+json.dumps(entry['args'],ensure_ascii=False)+'\nstartup_timeout_sec = 20\ntool_timeout_sec = 120\n\n[mcp_servers.cadmcp-design-brain.env]\nPYTHONUTF8 = "1"\n'
    atomic_text(destination/'codex.config.toml',toml)
    return entry


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description='Install and test CAD MCP design brain; optional explicit Cursor config merge')
    parser.add_argument('--geometry',action='store_true',help='Install CadQuery and run actual STEP tests')
    parser.add_argument('--workspace',type=Path,default=ROOT/'workspace')
    parser.add_argument('--cursor-project',type=Path,help='Explicitly merge one MCP entry into this project .cursor/mcp.json, retaining a backup')
    args=parser.parse_args(argv)
    if sys.version_info < (3,11):parser.error('Python 3.11 or newer is required; Python 3.13 was tested on Linux')
    if args.cursor_project and not args.cursor_project.is_dir():parser.error('--cursor-project must be an existing directory')
    target=ROOT/'.venv';python=python_in(target)
    try:
        if not python.exists():venv.EnvBuilder(with_pip=True).create(target)
        extras='test,geometry' if args.geometry else 'test'
        run([str(python),'-m','pip','install',str(ROOT)+'['+extras+']'])
        run([str(python),'-m','pytest','-q'])
        run([str(python),'-m','cadmcp_brain','--workspace',str(args.workspace.absolute()),'doctor'])
        entry=write_configs(python,args.workspace,ROOT/'integration/generated')
        if args.cursor_project:
            print(json.dumps(merge_cursor(args.cursor_project/'.cursor/mcp.json',entry),ensure_ascii=False,indent=2))
        print('READY: integration/generated/cursor.mcp.json and codex.config.toml')
        print('Read README_JA.md and INSTALL_INTEGRATE_JA.md before enabling backend writes.')
        return 0
    except (OSError,ValueError,subprocess.CalledProcessError) as exc:
        print('Installation stopped: '+str(exc),file=sys.stderr)
        print('Existing unrelated MCP entries are not removed. Installation has not been declared successful.',file=sys.stderr)
        return 1

if __name__=='__main__':raise SystemExit(main())
