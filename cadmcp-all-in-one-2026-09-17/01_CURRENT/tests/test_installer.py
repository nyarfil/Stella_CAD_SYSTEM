import importlib.util
import json
from pathlib import Path
import tomllib
import pytest

spec=importlib.util.spec_from_file_location('bootstrap',Path(__file__).parents[1]/'scripts/bootstrap.py')
bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)


def test_configs_preserve_spaces_unicode_and_toml(tmp_path):
    python=tmp_path/'Python space_日本語'/'python.exe';work=tmp_path/'workspace 日本語'
    entry=bootstrap.write_configs(python,work,tmp_path/'generated')
    c=json.loads((tmp_path/'generated/cursor.mcp.json').read_text('utf-8'))
    t=tomllib.loads((tmp_path/'generated/codex.config.toml').read_text('utf-8'))
    assert c['mcpServers']['cadmcp-design-brain']==entry
    assert t['mcp_servers']['cadmcp-design-brain']['command']==str(python.absolute())
    assert t['mcp_servers']['cadmcp-design-brain']['args']==entry['args']


def test_cursor_merge_preserves_others_and_backup(tmp_path):
    path=tmp_path/'mcp.json'
    original={'mcpServers':{'existing-fusion':{'command':'do-not-change'}},'other':True}
    path.write_text(json.dumps(original),encoding='utf-8');before=path.read_bytes()
    entry={'command':'python','args':['a']}
    r=bootstrap.merge_cursor(path,entry)
    assert Path(r['backup']).read_bytes()==before
    after=json.loads(path.read_text('utf-8'))
    assert after['mcpServers']['existing-fusion']==original['mcpServers']['existing-fusion']
    assert after['other'] is True
    assert bootstrap.merge_cursor(path,entry)['changed'] is False


@pytest.mark.parametrize('content',['// commented json\n{}','[]','{"mcpServers":[]}','{not json'])
def test_bad_config_is_not_overwritten(tmp_path,content):
    path=tmp_path/'mcp.json';path.write_text(content)
    with pytest.raises(ValueError):bootstrap.merge_cursor(path,{'command':'python'})
    assert path.read_text()==content


def test_new_cursor_config(tmp_path):
    target=tmp_path/'.cursor/mcp.json'
    r=bootstrap.merge_cursor(target,{'command':'python'})
    assert r['changed'] and r['backup'] is None
    assert json.loads(target.read_text())['mcpServers']['cadmcp-design-brain']['command']=='python'
