"""Published planning/review contracts must match all runtime schemas, not only tools/list."""
import json
import pytest
from pathlib import Path
from scripts.generate_schemas import documents


def test_all_published_schemas_match_runtime():
    folder=Path(__file__).resolve().parents[1]/'schemas'
    for name,value in documents().items():
        assert (folder/name).is_file(),name
        assert json.loads((folder/name).read_text('utf-8'))==value,name


def test_check_does_not_rewrite_corrupt_schema_and_generation_recovers(tmp_path,monkeypatch):
    from scripts import generate_schemas as generator
    folder=tmp_path/'schemas'
    folder.mkdir()
    target=folder/'Example.schema.json'
    target.write_bytes(b'{broken')
    monkeypatch.setattr(generator,'ROOT',tmp_path)
    monkeypatch.setattr(generator,'documents',lambda:{target.name:{'type':'object'}})
    assert generator.main(['--check'])==1
    assert target.read_bytes()==b'{broken'
    assert generator.main([])==0
    assert json.loads(target.read_text('utf-8'))=={'type':'object'}
    assert generator.main(['--check'])==0


def test_failed_schema_replace_preserves_existing_file(tmp_path,monkeypatch):
    from scripts import generate_schemas as generator
    from cadmcp_brain.req2cad import common
    folder=tmp_path/'schemas'
    folder.mkdir()
    target=folder/'Example.schema.json'
    target.write_bytes(b'{"old":true}')
    monkeypatch.setattr(generator,'ROOT',tmp_path)
    monkeypatch.setattr(generator,'documents',lambda:{target.name:{'type':'object'}})
    def denied(*args):
        raise PermissionError('simulated replacement failure')
    monkeypatch.setattr(common.os,'replace',denied)
    with pytest.raises(PermissionError):
        generator.main([])
    assert target.read_bytes()==b'{"old":true}'
    assert list(folder.iterdir())==[target]
