"""Mouse Board/Shell pack registry: reusable mechanical interfaces, not CAD generation.

A pack records measured or specified hardware. Cylinders found in a STEP file are
never classified as screw holes. Incomplete packs stay draft. Structure generation
does not start until a ready board pack AND a ready shell pack exist. Physical
click-feel, fatigue and scan-to-shell conversion stay unverified.
"""
from __future__ import annotations
import math
from typing import Any, Literal
from pydantic import Field, ValidationError, model_validator
from .recipe import Name, Strict
from .. import geometry
from ..errors import BrainError
from ..req2cad.common import atomic_json, json_load, write_lock
from ..util import digest, file_hash, safe_id, safe_path

SCHEMA_VERSION = '0.3.3'
STEP_MAX = 100 * 1024 * 1024
Vec3 = list[float]


def _unit(v: Vec3, label: str) -> None:
    if len(v) != 3 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in v):
        raise ValueError(f'{label} must be three finite millimetre-frame components.')
    n = math.sqrt(sum(x * x for x in v))
    if abs(n - 1) > 1e-6:
        raise ValueError(f'{label} must be a unit vector.')


def _affine(m: list[float]) -> None:
    if len(m) != 16 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in m):
        raise ValueError('board_to_world_transform must be 16 finite numbers (column-vector 4x4, row-major, mm).')
    if abs(m[12]) > 1e-9 or abs(m[13]) > 1e-9 or abs(m[14]) > 1e-9 or abs(m[15] - 1) > 1e-9:
        raise ValueError('Transform last row must be [0, 0, 0, 1].')
    a, b, c, d, e, f, g, h, i = m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-12:
        raise ValueError('Transform is singular; a board pose cannot be recovered.')


def bind_source_step(workspace, source: 'SourceFile', pack_id: str, status: str, *, invalid_code: str, invalid_message: str) -> None:
    src = safe_path(workspace, source.relative_path)
    if src.suffix.lower() not in ('.step', '.stp'):
        raise BrainError('BOARD_PACK_STEP', 'Packs bind a STEP/BREP, not a mesh.')
    if src.stat().st_size != source.bytes:
        raise BrainError('BOARD_HASH_MISMATCH', 'Declared STEP size does not match the workspace file.')
    sha = file_hash(src)
    if sha != source.sha256:
        raise BrainError('BOARD_HASH_MISMATCH', 'Declared STEP hash does not match the workspace file.')
    if status == 'ready' and geometry.available():
        measured = geometry.run_measurements({pack_id: str(src)})
        if not measured['metrics'][pack_id].get('brep_valid'):
            raise BrainError(invalid_code, invalid_message)


class SourceFile(Strict):
    relative_path: str = Field(min_length=1, max_length=400)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    bytes: int = Field(gt=0, le=STEP_MAX)


class SensorReference(Strict):
    model_component_id: Name
    datum_definition: str = Field(min_length=8, max_length=2000)
    distance_to_contact_plane_mm: float | None = None
    status: Literal['measured', 'specified', 'unverified']
    evidence: str = Field(min_length=8, max_length=2000)

    @model_validator(mode='after')
    def distance_matches_status(self):
        if self.status == 'unverified':
            if self.distance_to_contact_plane_mm is not None:
                raise ValueError('An unverified sensor datum cannot carry a contact-plane distance.')
        else:
            if self.distance_to_contact_plane_mm is None or not math.isfinite(self.distance_to_contact_plane_mm):
                raise ValueError('A measured/specified sensor datum needs a finite contact-plane distance in mm.')
        return self


class MountRecord(Strict):
    id: Name
    kind: Literal['screw', 'support', 'unverified']
    hole_diameter_mm: float | None = None
    evidence: str = Field(min_length=8, max_length=2000)
    status: Literal['measured', 'specified', 'unverified']

    @model_validator(mode='after')
    def screw_needs_diameter(self):
        if self.kind == 'screw':
            if self.status == 'unverified' or self.hole_diameter_mm is None or self.hole_diameter_mm <= 0:
                raise ValueError('A screw mount needs a positive hole diameter and must not be unverified.')
        if self.kind == 'unverified' and self.status != 'unverified':
            raise ValueError('An unverified mount kind cannot claim measured or specified status.')
        return self


class SwitchRecord(Strict):
    id: Name
    actuation_axis: Vec3
    actuation_point_mm: Vec3
    travel_mm: float | None = None
    overtravel_limit_mm: float | None = None
    status: Literal['measured', 'specified', 'unverified']
    evidence: str = Field(min_length=8, max_length=2000)

    @model_validator(mode='after')
    def actuation_known(self):
        _unit(self.actuation_axis, 'actuation_axis')
        if len(self.actuation_point_mm) != 3 or any(not math.isfinite(x) for x in self.actuation_point_mm):
            raise ValueError('actuation_point_mm must be three finite millimetre coordinates.')
        if self.status == 'unverified':
            if self.travel_mm is not None or self.overtravel_limit_mm is not None:
                raise ValueError('Unverified switch travel cannot be stored as a number.')
        else:
            if self.travel_mm is None or self.travel_mm <= 0:
                raise ValueError('A measured/specified switch needs a positive travel_mm.')
        return self


class WheelAssembly(Strict):
    axis_direction: Vec3
    encoder_connection: str = Field(min_length=4, max_length=2000)
    status: Literal['measured', 'specified', 'unverified']
    evidence: str = Field(min_length=8, max_length=2000)

    @model_validator(mode='after')
    def axis_unit(self):
        _unit(self.axis_direction, 'axis_direction')
        return self


class Keepout(Strict):
    id: Name
    kind: Literal['fixed', 'motion']
    description: str = Field(min_length=8, max_length=2000)
    status: Literal['measured', 'specified', 'unverified']


class AssemblyPath(Strict):
    id: Name
    description: str = Field(min_length=8, max_length=2000)
    status: Literal['measured', 'specified', 'unverified']


class BoardPack(Strict):
    schema_version: Literal['0.3.2', '0.3.3'] = '0.3.3'
    board_pack_id: Name
    unit: Literal['mm']
    source_step: SourceFile
    board_to_world_transform: list[float] = Field(min_length=16, max_length=16)
    sensor_reference: SensorReference
    mounts: list[MountRecord] = Field(default_factory=list, max_length=64)
    switches: list[SwitchRecord] = Field(default_factory=list, max_length=32)
    wheel_assembly: WheelAssembly | None = None
    fixed_keepouts: list[Keepout] = Field(default_factory=list, max_length=64)
    motion_keepouts: list[Keepout] = Field(default_factory=list, max_length=64)
    assembly_paths: list[AssemblyPath] = Field(default_factory=list, max_length=32)
    unresolved_required_fields: list[str] = Field(default_factory=list, max_length=64)
    status: Literal['draft', 'ready']

    @model_validator(mode='after')
    def complete_when_ready(self):
        _affine(self.board_to_world_transform)
        ids = [m.id for m in self.mounts] + [s.id for s in self.switches] + [k.id for k in self.fixed_keepouts] + [k.id for k in self.motion_keepouts] + [a.id for a in self.assembly_paths]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate ids inside the board pack.')
        if self.status != 'ready':
            return self
        if self.unresolved_required_fields:
            raise ValueError('A ready board pack cannot list unresolved required fields.')
        if not self.mounts:
            raise ValueError('A ready board pack needs at least one locating mount.')
        if self.sensor_reference.status == 'unverified':
            raise ValueError('A ready board pack cannot leave the sensor datum unverified.')
        if any(m.status == 'unverified' or m.kind == 'unverified' for m in self.mounts):
            raise ValueError('A ready board pack cannot contain unverified mounts.')
        if any(s.status == 'unverified' for s in self.switches):
            raise ValueError('A ready board pack cannot contain unverified switches.')
        if self.wheel_assembly is not None and self.wheel_assembly.status == 'unverified':
            raise ValueError('A ready board pack cannot contain an unverified wheel assembly.')
        if any(k.status == 'unverified' for k in (*self.fixed_keepouts, *self.motion_keepouts)):
            raise ValueError('A ready board pack cannot contain unverified keepouts.')
        if any(a.status == 'unverified' for a in self.assembly_paths):
            raise ValueError('A ready board pack cannot contain unverified assembly paths.')
        return self


class Opening(Strict):
    id: Name
    kind: Literal['sensor', 'switch', 'usb', 'wheel', 'cable', 'other']
    status: Literal['measured', 'specified', 'unverified']
    evidence: str = Field(min_length=8, max_length=2000)


class ShellPack(Strict):
    schema_version: Literal['0.3.3'] = SCHEMA_VERSION
    shell_pack_id: Name
    unit: Literal['mm']
    source_step: SourceFile
    wall_thickness_mm: float | None = None
    thickness_status: Literal['measured', 'specified', 'unverified']
    openings: list[Opening] = Field(default_factory=list, max_length=64)
    protected_outer: bool
    unresolved_required_fields: list[str] = Field(default_factory=list, max_length=64)
    status: Literal['draft', 'ready']

    @model_validator(mode='after')
    def complete_when_ready(self):
        ids = [o.id for o in self.openings]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate opening ids inside the shell pack.')
        if self.thickness_status == 'unverified':
            if self.wall_thickness_mm is not None:
                raise ValueError('An unverified wall thickness cannot carry a millimetre value.')
        elif self.wall_thickness_mm is None or not math.isfinite(self.wall_thickness_mm) or self.wall_thickness_mm <= 0:
            raise ValueError('A measured/specified shell needs a positive wall_thickness_mm.')
        if self.status != 'ready':
            return self
        if self.unresolved_required_fields:
            raise ValueError('A ready shell pack cannot list unresolved required fields.')
        if self.thickness_status == 'unverified':
            raise ValueError('A ready shell pack cannot leave wall thickness unverified.')
        if not self.protected_outer:
            raise ValueError('A ready mouse shell must declare the outer envelope protected.')
        if any(o.status == 'unverified' for o in self.openings):
            raise ValueError('A ready shell pack cannot contain unverified openings.')
        return self


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {'count': len(rows), 'draft': sum(1 for r in rows if r['status'] == 'draft'),
            'ready': sum(1 for r in rows if r['status'] == 'ready')}


class BoardRegistry:
    def __init__(self, workspace):
        self.workspace = workspace
        self.root = workspace / 'mouse' / 'board_packs'

    def _pack_path(self, pack_id: str):
        return self.root / f'{safe_id(pack_id)}.json'

    def summary(self) -> dict[str, Any]:
        return _counts(self.list_packs()['packs'])

    def list_packs(self) -> dict[str, Any]:
        if not self.root.is_dir():
            return {'packs': []}
        packs = []
        for path in sorted(self.root.glob('*.json')):
            try:
                data = json_load(path)
                BoardPack.model_validate(data)
            except (ValidationError, ValueError, OSError) as exc:
                raise BrainError('BOARD_PACK_CORRUPT', 'A stored pack is not a valid BoardPack.', {'name': path.name}) from exc
            packs.append({'board_pack_id': data['board_pack_id'], 'status': data['status'],
                          'source_sha256': data['source_step']['sha256']})
        return {'packs': packs}

    def get(self, pack_id: str) -> dict[str, Any]:
        path = self._pack_path(pack_id)
        if not path.is_file():
            raise BrainError('BOARD_PACK_NOT_FOUND', 'Unknown board pack.', {'board_pack_id': pack_id})
        pack = BoardPack.model_validate(json_load(path))
        return pack.model_dump()

    def register(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            pack = BoardPack.model_validate(payload)
        except ValidationError as exc:
            raise BrainError('BOARD_PACK_INVALID', 'Board pack failed schema or ready-completeness rules.', {'error_count': len(exc.errors())}) from exc
        bind_source_step(self.workspace, pack.source_step, pack.board_pack_id, pack.status,
                         invalid_code='BOARD_PACK_INVALID_BREP',
                         invalid_message='A ready board pack STEP must measure as a valid B-rep.')
        dest = self._pack_path(pack.board_pack_id)
        with write_lock(self.root.parent):
            if dest.exists():
                existing = json_load(dest)
                if digest(existing) != digest(pack.model_dump()):
                    raise BrainError('BOARD_PACK_EXISTS', 'A different pack already uses this id. Choose a new id; packs are not silently overwritten.')
                wrote = False
            else:
                atomic_json(dest, pack.model_dump())
                wrote = True
        gate = structure_gate(self.workspace)
        return {'board_pack': pack.model_dump(), 'wrote': wrote, **gate}


class ShellRegistry:
    def __init__(self, workspace):
        self.workspace = workspace
        self.root = workspace / 'mouse' / 'shell_packs'

    def _pack_path(self, pack_id: str):
        return self.root / f'{safe_id(pack_id)}.json'

    def summary(self) -> dict[str, Any]:
        return _counts(self.list_packs()['packs'])

    def list_packs(self) -> dict[str, Any]:
        if not self.root.is_dir():
            return {'packs': []}
        packs = []
        for path in sorted(self.root.glob('*.json')):
            try:
                data = json_load(path)
                ShellPack.model_validate(data)
            except (ValidationError, ValueError, OSError) as exc:
                raise BrainError('SHELL_PACK_CORRUPT', 'A stored pack is not a valid ShellPack.', {'name': path.name}) from exc
            packs.append({'shell_pack_id': data['shell_pack_id'], 'status': data['status'],
                          'source_sha256': data['source_step']['sha256']})
        return {'packs': packs}

    def get(self, pack_id: str) -> dict[str, Any]:
        path = self._pack_path(pack_id)
        if not path.is_file():
            raise BrainError('SHELL_PACK_NOT_FOUND', 'Unknown shell pack.', {'shell_pack_id': pack_id})
        return ShellPack.model_validate(json_load(path)).model_dump()

    def register(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            pack = ShellPack.model_validate(payload)
        except ValidationError as exc:
            raise BrainError('SHELL_PACK_INVALID', 'Shell pack failed schema or ready-completeness rules.', {'error_count': len(exc.errors())}) from exc
        bind_source_step(self.workspace, pack.source_step, pack.shell_pack_id, pack.status,
                         invalid_code='SHELL_PACK_INVALID_BREP',
                         invalid_message='A ready shell pack STEP must measure as a valid B-rep.')
        dest = self._pack_path(pack.shell_pack_id)
        with write_lock(self.root.parent):
            if dest.exists():
                existing = json_load(dest)
                if digest(existing) != digest(pack.model_dump()):
                    raise BrainError('SHELL_PACK_EXISTS', 'A different pack already uses this id. Choose a new id; packs are not silently overwritten.')
                wrote = False
            else:
                atomic_json(dest, pack.model_dump())
                wrote = True
        gate = structure_gate(self.workspace)
        return {'shell_pack': pack.model_dump(), 'wrote': wrote, **gate}


def structure_gate(workspace) -> dict[str, Any]:
    boards = BoardRegistry(workspace).summary()
    shells = ShellRegistry(workspace).summary()
    missing = []
    if boards['ready'] < 1:
        missing.append('ready_board_pack')
    if shells['ready'] < 1:
        missing.append('ready_shell_pack')
    return {
        'ready_board_packs': boards['ready'],
        'ready_shell_packs': shells['ready'],
        'usable_for_structure_generation': not missing,
        'missing': missing,
        'generated_cad': False,
        'warnings': [
            'A STEP file on disk is not a registered shell pack.',
            'Structure CAD generation is not started by this gate.',
            'Authored mechanism patterns are not physically tested mouse parts.',
        ],
    }


def inspect_inputs(workspace, relative_paths: list[str]) -> dict[str, Any]:
    if not isinstance(relative_paths, list) or not 1 <= len(relative_paths) <= 32:
        raise BrainError('MOUSE_INPUTS', 'Provide 1–32 workspace-relative paths.')
    files = []
    seen = set()
    for rel in relative_paths:
        if rel in seen:
            raise BrainError('MOUSE_INPUTS', 'Duplicate inspection path.', {'path': rel})
        seen.add(rel)
        path = safe_path(workspace, rel, must_exist=False)
        suffix = path.suffix.lower()
        kind = {'.step': 'step', '.stp': 'step', '.stl': 'mesh', '.3mf': 'mesh'}.get(suffix, 'unknown')
        present = path.is_file() and not path.is_symlink()
        record = {'relative_path': rel, 'present': present, 'kind': kind,
                  'is_cad_solid': False, 'sha256': None, 'bytes': None}
        if present:
            record['bytes'] = path.stat().st_size
            record['sha256'] = file_hash(path)
            record['is_cad_solid'] = kind == 'step'
        files.append(record)
    boards = BoardRegistry(workspace).summary()
    shells = ShellRegistry(workspace).summary()
    gate = structure_gate(workspace)
    step_present = any(f['is_cad_solid'] for f in files)
    return {
        'files': files,
        'board_packs': boards,
        'shell_packs': shells,
        'mechanical_start': {
            'step_file': 'present' if step_present else 'missing',
            'board_pack_ready': boards['ready'] > 0,
            'shell_pack_ready': shells['ready'] > 0,
            'ready': gate['usable_for_structure_generation'],
        },
        'warnings': [
            'Inspection never classifies cylindrical features as screw holes.',
            'A mesh (STL/3MF) is not a CAD solid and cannot start mechanical design.',
            'A present STEP is not a ready shell pack until it is registered and complete.',
            'Req2CAD annotations are a separate knowledge base; this report does not search them.',
        ] + list(gate['warnings']),
        'geometry_measured': False,
        'structure_gate': gate,
        'usable_for_structure_generation': gate['usable_for_structure_generation'],
        'missing': gate['missing'],
        'generated_cad': False,
    }


class MouseToolsMixin:
    def _boards(self) -> BoardRegistry:
        return BoardRegistry(self.brain.store.root)

    def _shells(self) -> ShellRegistry:
        return ShellRegistry(self.brain.store.root)

    def brain_mouse_inspect_inputs(self, relative_paths: list[str]) -> dict[str, Any]:
        """Hash workspace files and report board/shell pack status. A STEP on disk is not a ready shell. Does not invent fasteners or a passing design."""
        return inspect_inputs(self.brain.store.root, relative_paths)

    def brain_mouse_register_board_pack(self, pack: dict[str, Any]) -> dict[str, Any]:
        """Store a typed PCB mechanical pack. Ready status is refused when required fields are unverified, hashes mismatch, or the STEP is not a valid B-rep."""
        return self._boards().register(pack)

    def brain_mouse_get_board_pack(self, board_pack_id: str) -> dict[str, Any]:
        """Read one stored board pack. Presence is not printability, optical alignment, or click-feel."""
        return self._boards().get(board_pack_id)

    def brain_mouse_list_board_packs(self) -> dict[str, Any]:
        """List draft and ready board packs in this workspace. Demo CAD cases are not listed here."""
        rows = self._boards().list_packs()
        rows.update(self._boards().summary())
        return rows

    def brain_mouse_register_shell_pack(self, pack: dict[str, Any]) -> dict[str, Any]:
        """Store a typed prepared-shell pack. Ready status needs a protected outer envelope, a positive wall thickness, matching STEP hash, and a valid B-rep. Scan-to-shell conversion is not performed."""
        return self._shells().register(pack)

    def brain_mouse_get_shell_pack(self, shell_pack_id: str) -> dict[str, Any]:
        """Read one stored shell pack. Registration is not printability, wall-thickness proof everywhere, or optical alignment."""
        return self._shells().get(shell_pack_id)

    def brain_mouse_list_shell_packs(self) -> dict[str, Any]:
        """List draft and ready prepared-shell packs. A mesh scan is not listed here."""
        rows = self._shells().list_packs()
        rows.update(self._shells().summary())
        return rows

    def brain_mouse_structure_gate(self) -> dict[str, Any]:
        """Report whether a ready board pack and a ready shell pack exist. Does not generate structure CAD, bosses, or click parts."""
        return structure_gate(self.brain.store.root)
