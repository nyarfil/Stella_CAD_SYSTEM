import importlib.util
import json
from pathlib import Path
import sys
import tomllib
import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('codex_setup', ROOT / 'scripts/setup_codex.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def test_install_preserves_config_and_is_idempotent(tmp_path):
    cfg = tmp_path / '.codex/config.toml'
    cfg.parent.mkdir()
    original = '# keep comment\nmodel = "owner-model"\n[mcp_servers.fusion]\ncommand = "keep"\n'
    cfg.write_text(original, encoding='utf-8')
    result = setup.configure_codex(tmp_path, sys.executable, tmp_path / '日本語 data')
    parsed = tomllib.loads(cfg.read_text('utf-8'))
    assert parsed['model'] == 'owner-model'
    assert parsed['mcp_servers']['fusion']['command'] == 'keep'
    assert cfg.read_text('utf-8').startswith(original.rstrip())
    assert Path(result['backups'][0]).read_text('utf-8') == original
    entry = parsed['mcp_servers'][setup.SERVER]
    assert entry['enabled'] is False
    assert entry['env']['CADMCP_REQ2CAD_ROOT'].endswith('req2cad')
    assert entry['cwd'] == str(ROOT)
    assert setup.configure_codex(tmp_path, sys.executable, tmp_path / '日本語 data')['changed'] == []
    assert (tmp_path / '.agents/skills/cadmcp-design-brain/SKILL.md').is_file()


def test_dry_run_and_invalid_config_do_not_write(tmp_path):
    result = setup.configure_codex(tmp_path, sys.executable, tmp_path / 'data', dry_run=True)
    assert result['changed'] and list(tmp_path.iterdir()) == []
    path = tmp_path / '.codex/config.toml'
    path.parent.mkdir()
    path.write_text('invalid [')
    with pytest.raises(ValueError):
        setup.configure_codex(tmp_path, sys.executable, tmp_path / 'data')
    assert path.read_text() == 'invalid ['
    assert not (tmp_path / '.agents').exists()


def test_unmanaged_server_and_custom_skill_fail_before_writes(tmp_path):
    path = tmp_path / '.codex/config.toml'
    path.parent.mkdir()
    path.write_text('[mcp_servers.cadmcp-design-brain]\ncommand="owner"\n')
    before = path.read_bytes()
    with pytest.raises(ValueError, match='unmanaged'):
        setup.configure_codex(tmp_path, sys.executable, tmp_path / 'data')
    assert path.read_bytes() == before


def test_custom_env_preserved(tmp_path):
    text = setup.render_config('', Path(sys.executable), tmp_path)
    text = text.replace('"PYTHONUTF8" = "1"', '"PYTHONUTF8" = "1"\nOWNER_POLICY = "keep"')
    updated = setup.render_config(text, Path(sys.executable), tmp_path)
    assert tomllib.loads(updated)['mcp_servers'][setup.SERVER]['env']['OWNER_POLICY'] == 'keep'


def test_existing_disabled_setting_is_retained(tmp_path):
    original = setup.render_config('', Path(sys.executable), tmp_path)
    original = original.replace('"enabled" = false', '"enabled" = false\n"owner_field" = "keep"')
    rendered = setup.render_config(original, Path(sys.executable), tmp_path)
    entry = tomllib.loads(rendered)['mcp_servers'][setup.SERVER]
    assert entry['enabled'] is False
    assert entry['owner_field'] == 'keep'


@pytest.mark.parametrize('extra', ['\n[unrelated]\nvalue=1\n', '\n[mcp_servers.other]\ncommand="keep"\n'])
def test_unrelated_managed_block_content_refused(tmp_path, extra):
    text = setup.render_config('', Path(sys.executable), tmp_path).replace(setup.END, extra + setup.END)
    with pytest.raises(ValueError, match='Unrelated'):
        setup.render_config(text, Path(sys.executable), tmp_path)


def test_actual_codex_config_stdio(tmp_path):
    setup.configure_codex(tmp_path, sys.executable, tmp_path / '日本語 workspace')
    isolated = tmp_path / 'isolated-test'
    isolated.mkdir()
    spec = importlib.util.spec_from_file_location('connection', ROOT / 'scripts/check_cursor_connection.py')
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    result = check.check(tmp_path, 'codex', isolated_test_workspace=isolated)
    assert result['mcp_protocol_ok'] and result['host'] == 'codex'
    assert result['req2cad_status']['result']['cases'] == 0
    assert result['model_called'] is False
