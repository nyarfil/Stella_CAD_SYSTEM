"""Board/Shell pack registry: fail-closed mechanical hardware records, not fastener invention."""
from __future__ import annotations
import shutil
from pathlib import Path
import pytest
from pydantic import ValidationError
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio.mouse import BoardPack, ShellPack, inspect_inputs
from cadmcp_brain.util import file_hash

ROOT = Path(__file__).resolve().parents[1]
STEP = ROOT / 'examples' / 'verified_fixture' / 'frame_test_block.step'
IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def rejects(code, fn):
    with pytest.raises(BrainError) as exc:
        fn()
    assert exc.value.code == code


@pytest.fixture
def tools(tmp_path):
    dest = tmp_path / 'pcb.step'
    shutil.copyfile(STEP, dest)
    shutil.copyfile(STEP, tmp_path / 'shell.step')
    return Tools(Brain(tmp_path)), dest


def source(path: Path) -> dict:
    return {'relative_path': path.name, 'sha256': file_hash(path), 'bytes': path.stat().st_size}


def draft_pack(path: Path, **extra) -> dict:
    pack = {
        'schema_version': '0.3.2',
        'board_pack_id': 'pack_demo',
        'unit': 'mm',
        'source_step': source(path),
        'board_to_world_transform': IDENTITY,
        'sensor_reference': {
            'model_component_id': 'sensor',
            'datum_definition': 'Lens axis toward the desk plane.',
            'distance_to_contact_plane_mm': None,
            'status': 'unverified',
            'evidence': 'Not yet measured on this board.',
        },
        'mounts': [],
        'switches': [],
        'wheel_assembly': None,
        'fixed_keepouts': [],
        'motion_keepouts': [],
        'assembly_paths': [],
        'unresolved_required_fields': ['sensor_reference.distance_to_contact_plane_mm', 'mounts'],
        'status': 'draft',
    }
    pack.update(extra)
    return pack


def ready_pack(path: Path) -> dict:
    return draft_pack(
        path,
        board_pack_id='pack_ready',
        unresolved_required_fields=[],
        status='ready',
        sensor_reference={
            'model_component_id': 'sensor',
            'datum_definition': 'Lens axis toward the desk plane.',
            'distance_to_contact_plane_mm': 2.4,
            'status': 'specified',
            'evidence': 'Datasheet optical height for the fixture board.',
        },
        mounts=[{
            'id': 'm1',
            'kind': 'support',
            'hole_diameter_mm': None,
            'evidence': 'Corner pad used as a locating support, not a fastener guess.',
            'status': 'specified',
        }],
        switches=[{
            'id': 'sw_side',
            'actuation_axis': [1.0, 0.0, 0.0],
            'actuation_point_mm': [12.0, 4.0, 1.5],
            'travel_mm': 0.8,
            'overtravel_limit_mm': 1.2,
            'status': 'specified',
            'evidence': 'Switch travel from the fixture datasheet excerpt.',
        }],
    )


def draft_shell(path: Path, **extra) -> dict:
    pack = {
        'schema_version': '0.3.3',
        'shell_pack_id': 'shell_demo',
        'unit': 'mm',
        'source_step': source(path),
        'wall_thickness_mm': None,
        'thickness_status': 'unverified',
        'openings': [],
        'protected_outer': True,
        'unresolved_required_fields': ['wall_thickness_mm'],
        'status': 'draft',
    }
    pack.update(extra)
    return pack


def ready_shell(path: Path) -> dict:
    return draft_shell(
        path,
        shell_pack_id='shell_ready',
        wall_thickness_mm=1.6,
        thickness_status='specified',
        openings=[{
            'id': 'sensor_window',
            'kind': 'sensor',
            'status': 'specified',
            'evidence': 'Opening reserved for the sensor; not measured on a scan.',
        }],
        unresolved_required_fields=[],
        status='ready',
    )


def test_inspect_missing_and_mesh_are_not_solids(tmp_path):
    (tmp_path / 'shape.stl').write_bytes(b'solid dummy\nendsolid dummy\n')
    report = inspect_inputs(tmp_path, ['missing.step', 'shape.stl'])
    assert report['files'][0]['present'] is False
    assert report['files'][1]['kind'] == 'mesh' and report['files'][1]['is_cad_solid'] is False
    assert report['mechanical_start']['ready'] is False
    assert report['usable_for_structure_generation'] is False
    assert any('screw holes' in w for w in report['warnings'])
    assert all(f.get('kind') != 'screw' for f in report['files'])


def test_inspect_rejects_path_escape(tmp_path):
    rejects('UNSAFE_PATH', lambda: inspect_inputs(tmp_path, ['../secret.step']))


def test_ready_pack_refuses_unverified_sensor(tools):
    t, path = tools
    pack = ready_pack(path)
    pack['sensor_reference']['status'] = 'unverified'
    pack['sensor_reference']['distance_to_contact_plane_mm'] = None
    rejects('BOARD_PACK_INVALID', lambda: t.brain_mouse_register_board_pack(pack))


def test_ready_pack_refuses_empty_mounts(tools):
    t, path = tools
    pack = ready_pack(path)
    pack['mounts'] = []
    rejects('BOARD_PACK_INVALID', lambda: t.brain_mouse_register_board_pack(pack))


def test_cylinders_cannot_be_declared_screw_without_diameter():
    with pytest.raises(ValidationError):
        BoardPack.model_validate({
            **draft_pack(STEP),
            'source_step': {'relative_path': 'x.step', 'sha256': '0' * 64, 'bytes': 12},
            'mounts': [{'id': 'h1', 'kind': 'screw', 'hole_diameter_mm': None, 'evidence': 'Found a cylinder in the STEP.', 'status': 'unverified'}],
        })


def test_hash_mismatch_is_refused(tools):
    t, path = tools
    pack = draft_pack(path)
    pack['source_step']['sha256'] = 'a' * 64
    rejects('BOARD_HASH_MISMATCH', lambda: t.brain_mouse_register_board_pack(pack))


def test_ready_shell_refuses_unprotected_outer(tools):
    t, _ = tools
    pack = ready_shell(t.brain.store.root / 'shell.step')
    pack['protected_outer'] = False
    rejects('SHELL_PACK_INVALID', lambda: t.brain_mouse_register_shell_pack(pack))
    with pytest.raises(ValidationError):
        ShellPack.model_validate(pack)


def test_draft_then_ready_roundtrip(tools):
    t, path = tools
    draft = t.brain_mouse_register_board_pack(draft_pack(path))
    assert draft['wrote'] is True and draft['usable_for_structure_generation'] is False
    listed = t.brain_mouse_list_board_packs()
    assert listed['draft'] == 1 and listed['ready'] == 0
    again = t.brain_mouse_register_board_pack(draft_pack(path))
    assert again['wrote'] is False
    other = draft_pack(path)
    other['unresolved_required_fields'] = ['mounts']
    rejects('BOARD_PACK_EXISTS', lambda: t.brain_mouse_register_board_pack(other))
    ready = t.brain_mouse_register_board_pack(ready_pack(path))
    assert ready['ready_board_packs'] == 1
    assert ready['usable_for_structure_generation'] is False
    got = t.brain_mouse_get_board_pack('pack_ready')
    assert got['status'] == 'ready' and got['unit'] == 'mm'
    report = t.brain_mouse_inspect_inputs(['pcb.step'])
    assert report['files'][0]['is_cad_solid'] is True
    assert report['mechanical_start']['board_pack_ready'] is True
    assert report['mechanical_start']['shell_pack_ready'] is False
    assert report['usable_for_structure_generation'] is False
    gate = t.brain_mouse_structure_gate()
    assert gate['missing'] == ['ready_shell_pack']
    doctor = t.brain_doctor()
    assert doctor['version'] == '0.3.3'
    assert doctor['mouse_board_packs']['ready'] == 1
    assert doctor['mouse_structure_intake']['usable_for_structure_generation'] is False
    assert doctor['req2cad_is_not_implied_ready'] is True


def test_structure_gate_needs_ready_board_and_shell(tools):
    t, path = tools
    t.brain_mouse_register_board_pack(ready_pack(path))
    shell_path = t.brain.store.root / 'shell.step'
    draft = t.brain_mouse_register_shell_pack(draft_shell(shell_path))
    assert draft['usable_for_structure_generation'] is False
    ready = t.brain_mouse_register_shell_pack(ready_shell(shell_path))
    assert ready['usable_for_structure_generation'] is True
    assert ready['generated_cad'] is False
    gate = t.brain_mouse_structure_gate()
    assert gate['ready_board_packs'] == 1 and gate['ready_shell_packs'] == 1
    report = t.brain_mouse_inspect_inputs(['pcb.step', 'shell.step'])
    assert report['usable_for_structure_generation'] is True
    doctor = t.brain_doctor()
    assert doctor['mouse_shell_packs']['ready'] == 1
    assert doctor['mouse_structure_intake']['usable_for_structure_generation'] is True


def test_schema_and_tool_flags(tools):
    t, _ = tools
    schema = t.brain_studio_schema('BoardPack')
    assert 'draft' in schema['properties']['status']['enum']
    shell = t.brain_studio_schema('ShellPack')
    assert shell['properties']['protected_outer']['type'] == 'boolean'
    names = {row['name']: row for row in t.list()}
    assert names['brain_mouse_inspect_inputs']['annotations']['readOnlyHint'] is True
    assert names['brain_mouse_register_board_pack']['annotations']['readOnlyHint'] is False
    assert names['brain_mouse_list_board_packs']['annotations']['readOnlyHint'] is True
    assert names['brain_mouse_structure_gate']['annotations']['readOnlyHint'] is True
    assert names['brain_mouse_register_shell_pack']['annotations']['readOnlyHint'] is False
    assert len(names) == 50
