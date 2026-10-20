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
from . import scan_clean, scan_click_grooves, scan_fit, scan_flush, scan_model, scan_regions, scan_shell, scan_shellparts
from . import scan_face_roles
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
        from . import scan_origin
        result = inspect_inputs(self.brain.store.root, relative_paths)
        if isinstance(result, dict):  # scan-origin branch: the user decides real scan vs fused original
            result = {'scan_origin': scan_origin.hint(self.brain.store.root), **result}
        return result

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

    def brain_mouse_prepare_scan(self, relative_path: str, unit: str, transform: list[float] | None = None, repairs: dict[str, Any] | None = None) -> dict[str, Any]:
        """Inspect a closed scan mesh (STL/OBJ) for scan-to-shell stage A1: unit (required, never guessed), topology, orientation, components, holes. Only allow-listed repairs run (all default off) and each is reported. Writes mouse/scans/<scan_id>/; READY or NOT_READY with reasons. Self-intersection stays UNVERIFIED."""
        return scan_shell.prepare_scan(self.brain.store.root, relative_path, unit, transform, repairs)

    def brain_mouse_scan_model(self, relative_path: str, unit: str, target_max_error_mm: float = 0.05, hard_limit_error_mm: float = 0.10, min_component_faces: int = 100, close_holes_max_edges: int = 30, thin_wall_mm: float = 1.0) -> dict[str, Any]:
        """Turn a PLY scan into cleaned, decimated, watertight STL files for brain_mouse_prepare_scan. unit is required (never guessed); output is mm. Vertices are welded by exact position first (textured PLY files carry fake UV seams), then topology-only cleanup, then quadric decimation searched to the smallest face count within target_max_error_mm (two-sided Hausdorff vs the welded original; hard_limit_error_mm is the fallback). Watertight, manifold and winding are verified on the written STL; thin-wall zones are reported separately and are not part of the budget. Runs PyMeshLab (GPL-3.0) as a subprocess in a separate python (env CADMCP_SCAN_PYTHON), never in this process; SCAN_PYTHON_MISSING when absent. Never modifies the source and never overwrites outputs (mouse/scans/<model_id>/). Self-intersection stays UNVERIFIED."""
        return scan_model.scan_model(self.brain.store.root, relative_path, unit, target_max_error_mm, hard_limit_error_mm, min_component_faces, close_holes_max_edges, thin_wall_mm)

    def brain_mouse_scan_flush(self, relative_path: str, unit: str, labels_path: str | None = None, plate_tolerance_mm: float = 0.12, min_down_nz: float = 0.95, ransac_iterations: int = 3000, max_tilt_deg: float = 20.0, max_protrusion_pct: float = 5.0) -> dict[str, Any]:
        """Flush a welded scan mesh onto its bottom plate (mesh stage; no CAD is generated). Inputs: relative_path = watertight welded STL already in the standard frame (x front, y left, z up; unit required, never guessed; output mm), optional labels_path = .json {region: [face ids]} or .npz face_labels + codes with a bottom_plate region (without it the dominant down-facing plane of the whole mesh is used, with a warning). Method: area-weighted RANSAC plane on the down-facing plate faces (inlier band plate_tolerance_mm, default 0.12), refit on the inliers, minimal rotation that makes the plate normal +z, plate shifted onto z = 0; skates/feet that protrude below end up at negative z (reported, never clipped). Rigid transform only; face order is unchanged so the same labels stay valid. Returns the transform (Rm, z_shift, 4x4) and residual stats: plane-fit area and rms, tilt before/after, percentage of plate area within plate_tolerance_mm of z = 0, protrusion below the plate. Writes flushed.stl, flush_transform.json, a copy of the labels and flush_report.json once under mouse/scans/<flush_id>/ (never overwritten; same inputs return the stored report). Pass flushed.stl and the copied labels to brain_mouse_scan_click_grooves. Runs in the separate scan python (numpy, trimesh); PyMeshLab is not used. Flat plates use the dominant plane (>=50% of the area); recessed / ribbed undersides use a support plane through the lowest contact rim (max_protrusion_pct of the area may poke below it); reports recessed / protruding fractions (warnings FLUSH_UNDERSIDE_RECESSED / _PROTRUDES). Tilted or warped bases still fail plate_on_z0."""
        return scan_flush.scan_flush(self.brain.store.root, relative_path, unit, labels_path, plate_tolerance_mm, min_down_nz, ransac_iterations, max_tilt_deg, max_protrusion_pct)

    def brain_mouse_scan_cable_fill(self, relative_path: str, unit: str, labels_path: str | None = None, exclude_regions: list[str] | None = None, grid_mm: float = 0.25, front_depth_mm: float = 20.0, front_nx: float = 0.5, detect_sigma_mm: float = 4.0, min_depth_mm: float = 0.8, min_width_mm: float = 2.0, min_area_mm2: float = 4.0, max_area_mm2: float = 600.0, ring_mm: float = 4.0, degree: int = 3, smooth_tol_mm: float = 0.3, min_radius_mm: float = 8.0, margin_mm: float = 0.5, patch_edge_mm: float = 0.6, blend_mm: float = 1.5) -> dict[str, Any]:
        """Fill the cable hole / USB pocket of the scan front wall with the PLAIN wall inferred from the trusted wall around it (mesh stage, optional; no CAD is generated). The scanned pocket is grade-C data and the designed front wall is straight or a gentle R, so the pocket is discarded, not followed. Generic: any mouse, wired or wireless, any pocket position, asymmetric allowed; no mouse-specific coordinates. Inputs: relative_path = welded STL in the standard frame (x front, y left, z up; typically flushed.stl of brain_mouse_scan_flush; unit required, never guessed; output mm), optional labels_path = .json {region: [face ids]} or .npz face_labels + codes (hints only: exclude_regions, default wheel / side buttons / sensor, are never trusted wall nor filled; the click labels choose the front side, default +x). Method: front height field x(y, z) by rays over a grid_mm grid (faces within front_depth_mm of the front); trusted wall = front-facing hits (n_x > front_nx); wall S = Gaussian-weighted local quadratic regression (detect_sigma_mm) with one-sided trimming; recess = S - x >= min_depth_mm (or an enclosed no-hit cell = through hole); opening with a min_width_mm disk keeps grooves / parting slits out; pockets = components >= min_area_mm2. Per pocket: polynomial wall x = P(y, z) of total degree `degree` fitted robustly to the ring_mm trusted ring (recesses trimmed); pocket faces (footprint + margin_mm and the connected walls below P) removed, the boundary loop (must be simple in the front view; folded rim faces are removed until it is) triangulated (constrained Delaunay + longest-edge bisection to patch_edge_mm), lifted onto P with the loop residual blended out over blend_mm, oriented outward and labelled with the nearest rim region. Report per pocket: area (front view), y / z range, fill depth max / mean, fill volume, ring fit p50 / p95 / max, wall vs surrounding p95, minimum principal radius of P, faces removed / patch faces, seam dihedral, loop residual. READY = no pocket (no-op: mesh and labels copied unchanged) or every pocket filled; NOT_READY (no filled mesh written): CABLE_FRONT_WALL_NOT_FOUND, CABLE_INFERRED_WALL_NOT_SMOOTH (ring fit p95 > smooth_tol_mm or radius < min_radius_mm), CABLE_RING_INCOMPLETE, CABLE_POCKET_TOO_LARGE (> max_area_mm2), CABLE_LOOP_NOT_SIMPLE. Writes filled.stl (kept faces in input order, then the patch), labels (.npz or .json like the input), cable_fill.npz (grid, height field, wall, pocket mask, face_source) and cable_fill_report.json once under mouse/scans/<cf_id>/ (never overwritten; same inputs return the stored report). Next: brain_mouse_scan_symmetrise on filled.stl + labels, then brain_mouse_shell_fit / brain_mouse_shell_solid; brain_mouse_plate_side outline_path = filled.stl. Runs in the separate scan python (env CADMCP_SCAN_PYTHON; numpy, scipy, trimesh, shapely >= 2.1); SCAN_PYTHON_MISSING without it."""
        from . import scan_cable_fill
        return scan_cable_fill.scan_cable_fill(self.brain.store.root, relative_path, unit, labels_path, exclude_regions, grid_mm=grid_mm, front_depth_mm=front_depth_mm, front_nx=front_nx, detect_sigma_mm=detect_sigma_mm, min_depth_mm=min_depth_mm, min_width_mm=min_width_mm, min_area_mm2=min_area_mm2, max_area_mm2=max_area_mm2, ring_mm=ring_mm, degree=degree, smooth_tol_mm=smooth_tol_mm, min_radius_mm=min_radius_mm, margin_mm=margin_mm, patch_edge_mm=patch_edge_mm, blend_mm=blend_mm)

    def brain_mouse_plate_side(self, shell_step_path: str, outline_mode: str, outline_path: str, symmetry_report_path: str | None = None, mirror_normal: list[float] | None = None, mirror_d: float | None = None, section_z_mm: float | None = None, n_stations: int = 1500, n_sectors: int = 24, abs_thr_mm: float = 2.0, rel_thr: float = 0.015, similar_ratio: float = 0.7, max_change_mm: float = 0.1, min_inset_mm: float = 0.0, front_rim_mm: float = 1.2, front_min_corner_radius_mm: float | None = None, front_blend_deg: list[float] | None = None, front_direction: list[float] | None = None) -> dict[str, Any]:
        """Build the bottom plate under a given shell with ONE straight ruled side (CAD stage; the shell is never modified). Inputs: shell_step_path = STEP with one closed solid in the plate frame (floor z = 0); its parting face = the largest down-facing face (n_z < -0.5), the outer parting edge = that face's outer wire. Base outline source (same frame) by outline_mode: 'mesh' = scan STL sectioned at section_z_mm (largest closed loop; default auto = the lowest of 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.2, 1.5, 2.0 mm whose section is star-shaped about its centre and within 2 % in area of the next star-shaped one; every candidate is reported in outline_source), 'step' = lowest planar z = const face of a plate STEP (outer wire), 'polyline' = JSON {"points": [[x, y], ...]}. Optional mirror plane n.x = d: symmetry_report_path (JSON "plane": {"normal", "d"}, e.g. from brain_mouse_scan_symmetrise) or mirror_normal + mirror_d; without one nothing is symmetrised (the report says so). Method: the outline is split into n_sectors (default 24, even) angular sectors about its centroid on the mirror line, tested in mirror pairs with the same coarse test as the shell (p80 of the distance from mirrored points to the outline <= max(abs_thr_mm 2.0, rel_thr 0.015 x bbox diagonal)); near-symmetric pairs take the better side mirrored (lower curvature roughness) or the average when similar (ratio > similar_ratio 0.7), asymmetric pairs (side-button bulge, shifted half) stay as given, transitions blended; then a whole-loop polar LP fairing (min total variation of u + u'', u = 1/r, |delta r| <= max_change_mm 0.1), a periodic cubic spline and a clip inside the shell parting outline (inset >= min_inset_mm). Front (whole_v6 default): within front_blend_deg (default [38, 58] deg from the front, front = front_direction, default +x of the standard frame) the outline is replaced by the shell parting outline offset inward by a uniform front_rim_mm (default 1.2; 0 = follow the given outline), convex corners at least front_min_corner_radius_mm (default none = what the rim gives, ~10.3 mm on OP1), averaged with its mirror only when it passes the same coarse test; the measured rim and front corner radius are reported. Plate = floor z = 0 + exact copy of the shell parting surface (extended, general fuse) + ONE ruled side face (B-spline degree 3 x 1, periodic, n_stations rulings, default 1500, from the parting edge along its inward plan normal to the base outline; ruling order checked). Crisp edges: no fillets, hooks or waist. Checks on the re-imported STEP: plate valid, 1 solid, 3 faces, volume; overlap with the shell (0) and contact; plan protrusion beyond the shell parting outline <= 0.001 mm; plate top edge vs shell edge <= 0.01 mm; floor vs base outline; z = 0 outline change vs the source (radial, Hausdorff) and per-sector decisions; side profile r(z) monotonic on every ray; shell/plate edge angle and side-to-floor angle statistics; shell sha256 unchanged. READY only when every check passes. Writes bottom_plate.step, assembly.step (shell + plate), base_outline.json and plate_side_report.json once under mouse/cad/<pl_id>/ (never overwritten; same inputs return the stored report). Runs in a subprocess of the server python (OCP, scipy, shapely). Stop codes: PLATE_SIDE_NO_PARTING_FACE, PLATE_SIDE_OUTLINE, PLATE_SIDE_OUTLINE_NOT_STAR_SHAPED, PLATE_SIDE_RULINGS_CROSS, PLATE_SIDE_BUILD, PLATE_SIDE_SYMMETRY."""
        from . import scan_plate_side
        return scan_plate_side.plate_side(self.brain.store.root, shell_step_path, outline_mode, outline_path, symmetry_report_path, mirror_normal, mirror_d, section_z_mm, n_stations, n_sectors, abs_thr_mm, rel_thr, similar_ratio, max_change_mm, min_inset_mm, front_rim_mm, front_min_corner_radius_mm, front_blend_deg, front_direction)

    def brain_mouse_face_roles(self, shell_step_path: str, plate_step_path: str | None = None, hint_mesh_path: str | None = None, hint_labels_path: str | None = None, slot_max_mm: float = 2.5, window_max_mm: float = 30.0, panel_min_groove_fraction: float = 0.6, crisp_edge_deg: float = 15.0, hint_max_dist_mm: float = 1.5, colors: dict[str, list[float]] | None = None) -> dict[str, Any]:
        """Assign a role to every face of a mouse top-shell B-rep (and optional bottom plate) by GEOMETRY and write a colour-coded STEP (CAD stage; geometry is not changed). Inputs: shell_step_path = STEP with exactly one solid (workspace-relative), optional plate_step_path = STEP with one solid in the same frame (z up), optional hint_mesh_path (.stl) + hint_labels_path (.json {name: [triangle ids]} or .npz face_labels + codes 'name=code' as written by brain_mouse_recognize_shell / brain_mouse_scan_flush, names like left_click / right_click / side_button_1 / side_button_2 / wheel / top_shell, also LC RC B1 B2 WH; same frame), optional colors {panel|sidebutton|plate|rest: [r, g, b] sRGB 0..1} (defaults panel orange 0.95,0.50,0.10, side-button green 0.15,0.65,0.25, plate blue 0.20,0.40,0.85, rest grey 0.62,0.63,0.66). Method: samples on every face; a ray from p + 0.02 n along the outward normal against the same solid: most samples hit within slot_max_mm (default 2.5) => slot wall, within window_max_mm (default 30) => window wall; floors = faces bounded mostly by walls that rise above them (slot floor / window floor); every face rising from a window floor closes the pocket loop; walls without a floor or partner are demoted (warning). Side-button top = near-horizontal face bounded only by crisp edges (dihedral > crisp_edge_deg, default 15) to small walls that descend from it (protruding pad) => sidebutton + sidebutton_wall. parting = remaining down-facing faces (n_z < -0.5). panel = up-facing face bounded at least panel_min_groove_fraction (default 0.6) by groove / window walls that descend from it with the groove outside (a crisp front lip to the shell is allowed); the report gives its boundary length by neighbour role and the count of sample points outside its groove loop (must be 0). shell = the rest. Plate faces: role plate with sub floor (n_z < -0.9), parting (n_z > 0.3) or side. Hints: nearest labelled triangle of the face samples (within hint_max_dist_mm, default 1.5); a majority hint naming another top role is a FACE_ROLE_HINT_DISAGREES warning, the geometry role is kept. Writes face_roles.json (per solid: index in TopExp_Explorer order, role, sub, surface type, area, inner point, bbox, neighbours with shared length and dihedral), assembly_colored.step (XCAF face colours, read back and counted) and face_roles_report.json (counts per role, panel boundary composition, window loops, side-button pads, warnings, checks PASS / FAIL / UNVERIFIED) once under mouse/cad/<fr_id>/; never overwritten; the same inputs return the stored report. Fusion face indices may differ from the STEP order: match by point / bbox. Runs OCP in a subprocess of the server python (extra geometry); BREP_KERNEL_UNAVAILABLE without it. Stop codes: FACE_ROLES_FILE, FACE_ROLES_HINTS, FACE_ROLES_SETTINGS, FACE_ROLES_SHELL_SOLIDS, FACE_ROLES_PLATE_SOLIDS. Limits: flush or recessed side buttons stay shell; a groove wider than slot_max_mm reads as a window."""
        return scan_face_roles.face_roles(self.brain.store.root, shell_step_path, plate_step_path, hint_mesh_path, hint_labels_path, slot_max_mm, window_max_mm, panel_min_groove_fraction, crisp_edge_deg, hint_max_dist_mm, colors)

    def brain_mouse_handedness_flip(self, shell_step_path: str, plate_step_path: str, face_roles_path: str, symmetry_report_path: str | None = None, mirror_normal: list[float] | None = None, mirror_d: float | None = None, floor_tol_mm: float = 0.001, volume_tol_pct: float = 0.1, front_direction: list[float] | None = None, colors: dict[str, list[float]] | None = None) -> dict[str, Any]:
        """Flip a finished mouse between right-hand and left-hand by mirroring the WHOLE model about the mouse mirror plane (CAD stage; nothing is re-designed, the inputs are never modified). Inputs: shell_step_path = top shell STEP (one solid, e.g. side_buttons_shell.step), plate_step_path = bottom plate STEP (one solid, floor z = 0), face_roles_path = face_roles.json (or face_roles_report.json) of brain_mouse_face_roles for exactly these two files, and the mirror plane n.x = d given by symmetry_report_path (brain_mouse_scan_symmetrise report; JSON \"plane\") or mirror_normal + mirror_d (required; a built-in plane is never assumed; must be close to vertical). Method: plane mirror of both solids, then one rigid re-level (smallest rotation about the floor centroid that makes the best-fit mirrored floor plane horizontal, then a z shift so the floor is z = 0; a rigid map keeps shape and symmetry); a mirrored solid of negative volume is reversed to a valid orientation; the STEP files are written and read back and every gate is measured on them. Outputs under mouse/cad/<hf_id>/: top_shell.step, bottom_plate.step, assembly.step, assembly_colored.step (XCAF face colours from the roles: panel, side button, plate, rest; colors optional as in brain_mouse_face_roles), face_roles.json (same face order and roles, point / bbox re-measured; side-button roles now on the opposite flank), check_handedness_flip.json, handedness_flip_report.json. Gates (NOT_READY on FAIL): shell / plate valid one solid, assembly two valid solids, floor z = 0 within floor_tol_mm (default 0.001), volume within volume_tol_pct (default 0.1 %) of the source, side-button flank swapped (flank named left / right from front_direction, default +x front), face and role counts equal, every face the image of its source face, colours read back, shell-plate contact and non-overlap preserved. Generic: any handedness, any mirror plane tilt, no mouse constants. Same inputs return the stored report."""
        from . import scan_handedness_flip
        return scan_handedness_flip.handedness_flip(self.brain.store.root, shell_step_path, plate_step_path, face_roles_path, symmetry_report_path, mirror_normal, mirror_d, floor_tol_mm, volume_tol_pct, front_direction, colors)

    def brain_mouse_interference_report(self, step_paths: list[str], pairs: list[dict[str, Any]] | None = None, parts: list[str] | None = None, groups: dict[str, list[str]] | None = None, clearance_mm: float = 0.3, overlap_tol_mm3: float = 0.01, near_mm: float = 2.5, sample_mm: float = 0.5, fine_deflection_mm: float = 0.005, coarse_deflection_mm: float = 0.02) -> dict[str, Any]:
        """Clearance / interference table of an assembly (check stage; the STEP files are only read). Inputs: step_paths = 1-16 STEP files in the workspace (an XCAF assembly gives one part per leaf solid named by its label; an unnamed solid is named after the file stem), optional groups {new name: [part names, "stem*" = prefix]} to merge or rename parts, and pairs [{a, b, clearance_mm?, within_mm?, label_a?, label_b?}] (b "*" = every other part; within_mm keeps the row only when closer) or omitted = every pair of parts (or of the listed parts). Per pair: min distance (densified mesh samples vs the other surface, both ways, signed), overlap volume (exact OCC Boolean common when closer than sample_mm) and PASS when overlap < overlap_tol_mm3 and distance >= the required clearance (default clearance_mm 0.3; give 0 for intended contact). Pairs farther than near_mm by bounding box report the bbox gap (a lower bound). Writes interference_table.md / .png under mouse/checks/<id>/; the same inputs return the stored report."""
        from . import mouse_checks
        return mouse_checks.interference_report(self.brain.store.root, step_paths, pairs, parts, groups, clearance_mm, overlap_tol_mm3, near_mm, sample_mm, fine_deflection_mm, coarse_deflection_mm)

    def brain_mouse_wall_audit(self, shell_step_path: str, target_thickness_mm: float, part: str | None = None, line_width_mm: float = 0.4, tol_mm: float = 0.05, max_over_mm: float = 0.2, density_g_cm3: float = 1.04, samples: int = 40000, deflection_mm: float = 0.02) -> dict[str, Any]:
        """Printed-wall audit of a shell solid (check stage; the STEP is only read). Wall thickness is measured along the inward SKIN NORMAL by ray tests from area-uniform surface samples (not vertical sections). Returns min / p5 / median / p95 / max and the dominant wall (histogram mode), the share near target_thickness_mm, thick zones (> T + max_over_mm: posts, ribs) and thin zones (< T - tol_mm) with locations, the share of walls that are not a multiple of line_width_mm (0.4 nozzle), mass in grams (closed-mesh volume x density_g_cm3, ABS 1.04; exact B-rep volume alongside) and a thickness heatmap PNG (4 views + histogram). Status PASS / WARN / FAIL: FAIL when the dominant wall is not T or T / the dominant wall is not a line-width multiple; WARN when p95 or max exceed T + max_over_mm or p5 is below T - tol_mm. part names one solid when the STEP holds several."""
        from . import mouse_checks
        return mouse_checks.wall_audit(self.brain.store.root, shell_step_path, target_thickness_mm, part, line_width_mm, tol_mm, max_over_mm, density_g_cm3, samples, deflection_mm)

    def brain_mouse_section_render(self, step_paths: list[str], plane: dict[str, Any], parts: list[str] | None = None, groups: dict[str, list[str]] | None = None, colors: dict[str, str] | None = None, dimensions: list[dict[str, Any]] | None = None, window: list[float] | None = None, title: str | None = None, curve_step_mm: float = 0.05) -> dict[str, Any]:
        """Opaque, colour-coded section picture of chosen parts (check stage; the STEP files are only read). Inputs: step_paths (as brain_mouse_interference_report, with optional groups), parts = names to show (default all), plane = {"kind": "XZ"|"YZ"|"XY", "offset": mm along the missing axis} or {"kind": "axis", "point", "direction", "normal"} (plane through a point holding the axis; the axis is drawn vertical) or {"kind": "plane", "origin", "normal", "up"?}. Each part is cut by the exact B-rep section; closed loops are filled (cavities stay white) with mm axes, a legend and optional colors {part: "#rrggbb"}. dimensions [{from: [x,y,z], to: [x,y,z], label?, color?}] are drawn as <-> arrows (label defaults to the 3D distance). window = [u_min, u_max, v_min, v_max] in plane coordinates. Writes section.png under mouse/checks/<id>/; parts the plane misses are listed as warnings."""
        from . import mouse_checks
        return mouse_checks.section_render(self.brain.store.root, step_paths, plane, parts, groups, colors, dimensions, window, title, curve_step_mm)

    def brain_mouse_groove_fill(self, shell_step_path: str, part: str | None = None, groove_faces: list[int] | None = None, max_floor_width_mm: float = 1.2, floor_min_nz: float = 0.8, wall_max_abs_nz: float = 0.2, min_groove_length_mm: float | None = None, min_patch_area_mm2: float | None = None, sew_tol_mm: float = 0.02, planar_tol_mm: float = 0.02, mesh_deflection_mm: float = 0.003) -> dict[str, Any]:
        """Close the click groove of a mouse top-shell solid on the shared skin surface (CAD stage; the STEP is only read). Generic for any mouse (+z up, the skin faces up). Detection (or groove_faces = face indices in explorer order of the solid): a narrow upward floor (width < max_floor_width_mm 1.2, normal z > floor_min_nz 0.8, length > min_groove_length_mm) with near-vertical walls (|nz| < wall_max_abs_nz 0.2) next to a big skin face (> min_patch_area_mm2). The two size thresholds scale with the shell: default (omitted) min_groove_length_mm = 17 % of the longest bbox side and min_patch_area_mm2 = 4 % of the plan bbox area; the actually used values are reported in settings_used; pass numbers to override (LH2 verification used 20 mm and 300 mm2). Method is B-rep surgery, no Boolean: the groove faces are removed, the hole loops are cut into runs by whether the kept neighbour lies on the skin surface; the skin cap is built on the skin surface from the skin edges' own pcurves plus one straight chord per non-skin run (groove end, slot end), each run cap on the neighbours' common surface or a plane (planar within planar_tol_mm 0.02); anything else is refused (GROOVE_FILL_UNSUPPORTED, e.g. a closed groove ring), never filled partially. Then sew (sew_tol_mm 0.02), fix, and gate: one valid solid, free and multiple edges 0, STEP round trip, volume bookkeeping (closed-mesh volume at mesh_deflection_mm 0.003). Writes filled_skin.step and groove_fill_report.json once under mouse/cad/<gf_id>/ (never overwritten; same inputs return the stored report). part names one solid when the STEP holds several. Next: brain_mouse_split_click_region. Runs in the server python (OCP)."""
        from . import mouse_groove_fill
        return mouse_groove_fill.groove_fill(self.brain.store.root, shell_step_path, part, groove_faces, max_floor_width_mm, floor_min_nz, wall_max_abs_nz, min_groove_length_mm, min_patch_area_mm2, sew_tol_mm, planar_tol_mm, mesh_deflection_mm)

    def brain_mouse_split_click_region(self, shell_step_path: str, shell_part: str | None = None, skin_step_path: str | None = None, skin_part: str | None = None, patch_faces: list[int] | None = None, plate_thickness_mm: float = 1.1, gap_mm: float = 1.0, outer_groove_mm: float = 0.5, centre_slot_mm: float = 1.0, centre_mm: float | None = None, outline_margin_mm: float = 0.1, cut_window: bool = True, window: dict[str, float] | None = None, slab_top_mm: float = 5.0, fit_n: int = 161, fit_tol_mm: float = 2e-5, mesh_deflection_mm: float = 0.003, book_tol_mm3: float = 30.0, sym_tol: float = 0.02, interference_tol_mm3: float = 0.01, ray_n: int = 400, ray_tol_thickness_mm: float = 0.002, ray_tol_gap_mm: float = 0.01, ray_pass: float = 0.97, min_patch_area_mm2: float | None = None, sew_tol_mm: float = 0.02, wheel_step_path: str | None = None, wheel_part: str | None = None, wheel_margin_mm: float = 0.0, window_corner_r_mm: float = 0.0, lateral_axis: str = 'auto', centre_source: str = 'patches', uv_margin: float | None = None, min_groove_length_mm: float | None = None) -> dict[str, Any]:
        """Carve the two click plates out of a mouse top shell and open the shell for them (CAD stage; STEPs only read; generic port of the owner-approved LH2 v17 process, any left-right symmetric mouse, +z up). Inputs: shell_step_path = shell solid WITH the click groove (the groove is filled here by the brain_mouse_groove_fill method), or with skin_step_path = an already filled skin (shell_step_path then only locates the groove), or with patch_faces = two face indices of the filled skin (shell_step_path IS the filled skin). The two big patches next to the groove are detected from the groove walls (size thresholds min_patch_area_mm2 / min_groove_length_mm default to fractions of the shell bbox, see brain_mouse_groove_fill); the plate outline is the smooth periodic spline of the projected patch outline +outline_margin_mm 0.1 (plate) and +0.6 (shell cut). The mirror plane is MEASURED: lateral_axis 'auto' = the plan axis (x or y) along which the two patches are separated (or 'x' / 'y'); centre_mm = the mirror plane coordinate on that axis (default centre_source 'patches' = midpoint of the gap between the patches; 'shell_bbox' = mid plane of the shell bbox; a warning is reported when they differ by > 1 % of the lateral extent); plate_L is the side with the smaller lateral coordinate, plate_R the larger (naming by side, no handedness claim). Plates are plate_thickness_mm 1.1 thick measured along the skin normal (C2 B-spline fit of the true normal offset, fit_n x fit_n, fit_tol_mm 2e-5; fit domain = patch uv bounds + uv_margin, default one patch span), shell and plate keep gap_mm 1.0, outer_groove_mm 0.5 around, centre_slot_mm 1.0 between the plates. Wheel window: NO default. With cut_window true give wheel_step_path (+ wheel_part): the window is the x/y plan bbox of the wheel part grown by wheel_margin_mm 0 on every side with corner radius window_corner_r_mm 0; or an explicit window {w (along x), h (along y), cx, cy[, r]}; or cut_window false. Otherwise the call is refused (SPLIT_WINDOW_REQUIRED). Every Boolean is gated (non-empty, one valid solid) and then: volume bookkeeping residual <= book_tol_mm3 30, L/R plate symmetry <= sym_tol 2 %, interference <= interference_tol_mm3, plate thickness 1.1 +-0.002 and gap 1.0 +-0.01 on >= ray_pass 97 % of ray_n rays. Writes shell_open.step, plate_L.step, plate_R.step, click_split_parts.step (Top_Shell, click_plate_L, click_plate_R), filled_skin.step (when filled here) and split_click_report.json (lateral_axis, centre_mm, window and its source, uv_margin_used) once under mouse/cad/<sc_id>/ (never overwritten; same inputs return the stored report). LH2 verification arguments: window {w 19.12, h 8.32, r 3.33, cx 97.325, cy -0.01}, uv_margin 3.0, min_patch_area_mm2 300, min_groove_length_mm 20. Runs in the server python (OCP); minutes on a full shell (run in the background)."""
        from . import mouse_split_click
        return mouse_split_click.split_click_region(self.brain.store.root, shell_step_path, shell_part, skin_step_path, skin_part, patch_faces, plate_thickness_mm, gap_mm, outer_groove_mm, centre_slot_mm, centre_mm, outline_margin_mm, cut_window, window, slab_top_mm, fit_n, fit_tol_mm, mesh_deflection_mm, book_tol_mm3, sym_tol, interference_tol_mm3, ray_n, ray_tol_thickness_mm, ray_tol_gap_mm, ray_pass, min_patch_area_mm2, sew_tol_mm, wheel_step_path=wheel_step_path, wheel_part=wheel_part, wheel_margin_mm=wheel_margin_mm, window_corner_r_mm=window_corner_r_mm, lateral_axis=lateral_axis, centre_source=centre_source, uv_margin=uv_margin, min_groove_length_mm=min_groove_length_mm)

    def brain_mouse_plate_joint(self, shell_step_path: str, plate_step_path: str, shell_part: str | None = None, plate_part: str | None = None, wall_mm: float = 1.3, clearance_mm: float = 0.15, ledge_mm: float | None = None, ledge_measure: str = 'plan', tongue_width_mm: float = 1.1, tongue_height_mm: float = 0.0, floor_mm: float = 1.2, bearing: str = 'plate_top', pads_mm: list[dict[str, float]] | None = None, z0_levels_mm: list[dict[str, float]] | None = None, z0_rear_mm: float | None = None, ramp_factor: float = 2.0, stations_x_mm: list[float] | None = None, density_g_cm3: float = 1.04, gap_tol_mm: float = 0.05, deflection_mm: float = 0.005) -> dict[str, Any]:
        """Hollow bottom plate that mates the top shell: the ADOPTED design (owner v20a / official v39) with generic defaults (CAD stage; both STEP files are only read; any mouse, plate bottom flat on z 0). Inputs: shell_step_path = the hollow top shell / foundation (wall wall_mm 1.3), plate_step_path = the SOLID plate blank (bottom flat on z 0; its own skin is the plate outer face; shell_part / plate_part name one solid when a STEP holds several). Default (bearing plate_top, tongue_height_mm 0): the blank keeps its own top, the cavity is the skin offset inward by ledge_mm measured in plan (ledge_measure plan; default ledge_mm = wall_mm + clearance_mm = 1.45; the official v39 plate uses ledge_mm 1.6, the v24 printed-wall rim) above a floor_mm 1.2 floor. Model-specific numbers have NO default: pads_mm (default none = rim only) lists bearing pads [{x_from, x_to, half_width_y[, y_centre]}] in model x/y, the blank up to its own top inside each rectangle (y_centre defaults to the plate bbox mid plane in y; a pad rectangle that holds no blank is an error); stations_x_mm (evidence positions along x) default to 8 stations spread over 5 %..85 % of the plate x extent, with sides low_y / high_y split at the plate bbox mid plane. The ledge + tongue joint (bearing z0_profile, ledge_measure normal, tongue_height_mm > 0, pads_mm []; owner-rejected v20b / v22d) is EXPERIMENTAL and not READY on the real shells: the radial offset model folds on the steep rear, so its gates fail instead of being relaxed; it REQUIRES z0_levels_mm [{x_from, z0}] and z0_rear_mm (no default; PLATE_JOINT_Z0_REQUIRED), plus ramp_factor / tongue_width_mm. The blank is never raised and the shell never trimmed: any overlap with the shell is reported. Every Boolean is gated (non-null, valid, one solid, mesh-volume bookkeeping). LH2 verification arguments (official v39): ledge_mm 1.6, pads_mm [{x_from 103.6, x_to 113.4, half_width_y 8.6, y_centre 0}], stations_x_mm [5, 18, 30, 44, 60, 70, 80, 100]. Writes hollow_plate.step, joint_params.json and plate_joint_report.json once under mouse/cad/<pj_id>/ (never overwritten; same inputs return the stored report). Checks: one valid solid, STEP round trip, bottom flat z 0, floor thickness by vertical rays, bearing pads stand above the floor, common volume with the shell (<= 0.01 mm3), bearing contact areas, offset-model accuracy, mass (density_g_cm3 1.04); tongue mode adds tongue gap at the stations within gap_tol_mm of the clearance and ledge reaches z0(x). READY only when no check fails. Runs in the server python (OCP, numpy, scipy, vtk)."""
        from . import mouse_plate_joint
        return mouse_plate_joint.plate_joint(self.brain.store.root, shell_step_path, plate_step_path, shell_part, plate_part, wall_mm, clearance_mm, ledge_mm, ledge_measure, tongue_width_mm, tongue_height_mm, floor_mm, bearing, pads_mm, z0_levels_mm, z0_rear_mm, ramp_factor, stations_x_mm, density_g_cm3, gap_tol_mm, deflection_mm)

    def brain_mouse_wheel_window(self, step_paths: list[str], mode: str = 'rect_from_wheel', shell_part: str | None = None, plate_parts: list[str] | None = None, wheel_parts: list[str] | None = None, clearance_mm: float = 0.3, corner_radius_mm: float | None = None, delta_mm: float | None = None, rear_edge_mm: float | None = None, half_width_mm: float | None = None, centre_y_mm: float | None = None, rect: list[float] | None = None, groups: dict[str, list[str]] | None = None, near_margin_mm: float = 5.0, front_axis: str = '+x') -> dict[str, Any]:
        """Cut or widen the wheel window of a mouse top shell (CAD stage; works for any mouse; the input STEP files are only read, the result is a new assembly STEP). Inputs: step_paths = STEP file(s) with the shell, the wheel and the other parts (assembly part labels are kept; groups as in brain_mouse_interference_report), shell_part and wheel_parts (REQUIRED part names; no model-specific default), plate_parts (click plates etc. cut by the same tool; a plate the tool does not touch stays unchanged). front_axis = the world direction the mouse front points to: +x (default convention), -x, +y or -y; 'rear' is the opposite side and everything (rear edge, widening, rounded corners) follows it; the cutter is a Z-parallel prism. corner_radius_mm: given, or (omitted) 0.8 x the window half width (the owner's v23f ratio 3.33 / 4.16). mode: rect_from_wheel (default) offsets the wheel parts by clearance_mm (0.3, owner rule v23c2), takes the part of the shell inside that body, and cuts the bounding rectangle (half width = max(intrusion, half_width_mm), centre_y_mm optional = world coordinate across front_axis) with the corner radius on all four corners, enlarged in 0.05 mm steps until the rounded corners leave no intrusion; when nothing intrudes the status is NO_CHANGE_NEEDED and no Boolean runs (use widen_rear for a shell that already has a window). widen_rear measures the existing window by vertical ray scan at the wheel centre (or takes rear_edge_mm / half_width_mm) and cuts a prism that starts delta_mm (required, > 0; owner v23f: 0.8) behind the rear edge with only the two rear corners rounded. explicit takes rect = [x_min, x_max, y_min, y_max] (world). Every Boolean is gated: non-null, exactly one valid solid, removed volume = common(part, tool) (adaptive B-rep volumes), a tool that misses the shell is WINDOW_NO_EFFECT, never a silent no-op. The assembly is written as STEP, read back (names, cut parts one valid solid with the same volume) and every other part is compared with the input (volume, centre of mass). Report: window x/y range before and after, tool rectangle and corner radius (and its source), removed volumes, and for every part near the window (bbox within near_margin_mm, wheel parts always) the shell common volume before and after, the exact B-rep and the mesh min distance (mouse_interference_worker on the window neighbourhood, parts cropped to the tool box + near_margin_mm) and PASS / FAIL against clearance_mm; rear_clearance = distance to the wheel parts. Writes <stem>_wheelwindow.step, <part>_wheelwindow.step, window_neighbourhood.step and wheel_window_report.json once under mouse/cad/<ww_id>/ (never overwritten; same inputs return the stored report). Limits: colours are not kept; parts that already overlapped the shell before the cut show as FAIL rows (compare common before / after). Runs in the server python (OCP, vtk)."""
        from . import mouse_wheel_window
        return mouse_wheel_window.wheel_window(self.brain.store.root, step_paths, mode, shell_part, plate_parts, wheel_parts, clearance_mm, corner_radius_mm, delta_mm, rear_edge_mm, half_width_mm, centre_y_mm, rect, groups, near_margin_mm, front_axis)

    def brain_mouse_board_place(self, step_paths: list[str], shell_part: str | None = None, pack_parts: list[str] | None = None, sensor_part: str | None = None, floor_datum_part: str | None = None, pcb_part: str | None = None, floor_z: float | None = None, floor_part: str | None = None, floor_region_path: str | None = None, x_rule: str = 'auto', bush_part: str | None = None, wheel_parts: list[str] | None = None, wheel_region_path: str | None = None, seed_switch_parts: list[str] | None = None, switch_part: str | None = None, switch_pcb_part: str | None = None, plate_parts: list[str] | None = None, click_region_paths: list[str] | None = None, report_only_parts: list[str] | None = None, mirror_y: float | None = None, shell_kind: str = 'auto', clearance_mm: float = 0.3, wall_mm: float = 1.2, level_tol_deg: float = 0.5, parting_band_mm: float = 3.0, wheel_tol_mm: float = 1.0) -> dict[str, Any]:
        """Compute the pose of a board pack (main PCB + sensor + lens + wheel + bush, optionally in-place switch boards) inside a top shell by the owner's universal internals rules and report the residuals (CAD stage; input STEPs are only read; nothing is forced). World convention x = front, y = lateral (mirror normal), z = up; the pose is a TRANSLATION, the pack frame must have its PCB level (PCB_NOT_LEVEL otherwise). REQUIRED (no model-specific default): shell_part (hollow shell or closed solid skin; shell_kind auto by a point test), pack_parts, sensor_part, floor_datum_part (the around-lens helper), pcb_part, and exactly one floor source (floor_z, floor_part = bottom plate, or floor_region_path = bottom-plate STL). Rules: ty = sensor_part bbox centre on the mirror plane (fitted from the shell, mirror_y overrides); tz = floor_datum_part min z on the bottom-plate bottom face; tx by x_rule: bush_flush (the angled end face(s) of bush_part, planar faces 5-75 deg to the front axis, on the OUTER skin of the shell / floor_part: median signed offset along the face normal = 0, exits only, downward parting faces ignored), wheel (wheel_parts centre on the wheel window centre), auto = bush_flush when bush_part is given. Wheel window: wheel_region_path (area centroid) or an opening found by vertical rays on the mirror line; residual dx/dy reported, WHEEL_OFF_WINDOW when |dy| > wheel_tol_mm or the centre is outside the window. Switches: seed_switch_parts (in-place switch parts in the pack, rigid copies of switch_part with switch_pcb_part) must each lie under exactly one click plate (plate_parts) or click region (click_region_paths); vertical gap to the ceiling reported (solid skin: outer skin - wall_mm). Clearance: every pack part vs the shell (hollow: distance to the material; solid skin: depth below the skin - wall_mm; points below the shell bottom + parting_band_mm are bottom-plate territory, not checked); NO_ROOM below clearance_mm unless the part is in report_only_parts (wheel / bush through openings not cut yet, switch boards that brain_mouse_board_posts re-places). Writes placed_pack.step (READY) or candidate_pack.step (NOT_READY, inspection only) with the original part names, and board_place_report.json (status, blocking_reasons, translation, residuals, wheel window, switches, clearance per part) once under mouse/cad/<pl_id>/ (never overwritten; same inputs return the stored report). Next: brain_mouse_board_posts with seed_switch_parts = the placed switch copies and plate_parts. Runs in the server python (OCP, vtk, scipy)."""
        from . import mouse_board_place
        return mouse_board_place.board_place(self.brain.store.root, step_paths, shell_part, pack_parts, sensor_part, floor_datum_part, pcb_part, floor_z, floor_part, floor_region_path, x_rule, bush_part, wheel_parts, wheel_region_path, seed_switch_parts, switch_part, switch_pcb_part, plate_parts, click_region_paths, report_only_parts, mirror_y, shell_kind, clearance_mm=clearance_mm, wall_mm=wall_mm, level_tol_deg=level_tol_deg, parting_band_mm=parting_band_mm, wheel_tol_mm=wheel_tol_mm)

    def brain_mouse_board_posts(self, step_paths: list[str], stage: str = 'all', shell_part: str | None = None, board_parts: list[str] | None = None, pcb_part: str | None = None, switch_part: str | None = None, sides: list[dict[str, Any]] | None = None, board_holes: list[list[float]] | None = None, pitch_deg: float | None = None, mirror_y: float | None = None, rib_angles_deg: list[float] | None = None, board_hole_dia: float | None = None, post_dia: float | None = None, post_hole_clearance_mm: float = 0.25, board_prefix: str = 'board', shell_out_name: str | None = None, plate_parts: list[str] | None = None, seed_switch_parts: list[str] | None = None, seed_shift_mm: list[float] | None = None, side_names: list[str] | None = None, pivot_z_rule: str = 'auto', symmetrise: bool = True, plunger_gap_mm: float = 0.80, hinge_band_frac: float = 0.02, hinge_cluster_frac: float = 0.025, seed_match_tol_mm: float = 0.01, body_gap_mm: float = 0.38, post_embed_mm: float = 0.6, top_margin_mm: float = 0.3, rib_width: float = 0.8, rib_beyond_mm: float = 0.95, rib_overlap_mm: float = 0.3, pilot_dia: float = 1.4, pilot_depth_mm: float = 4.5, chamfer_mm: float = 0.3, act_w: float = 3.4, act_h: float = 5.0, act_corner_r: float = 0.2, act_root_fillet: float = 0.3, act_into_plate_mm: float = 1.0, act_top_margin_mm: float = 0.3, tip_gap_mm: float = 0.1, hole_clear_mm: float = 0.32, travel_mm: float = 0.5, density_g_cm3: float = 1.04) -> dict[str, Any]:
        """Place the main-click switch boards under a hollow top shell and build the board posts on the shell, plus the actuator posts on the click plates and their floor holes (CAD stage; works for any left-right-symmetric mouse; the process is the owner-approved LH2 v34 -> v39 one; the input STEPs are only read). World convention: x = front/back, y = lateral (mirror normal), z = up. REQUIRED (no model-specific default): shell_part (one hollow solid), pcb_part (level board part in its own frame), switch_part (topmost horizontal face = plunger top, largest face below = switch body top), sides = explicit override [{name, pivot, plate_part, hinge}]. Omitted, the sides are DERIVED: seed_switch_parts (required then) = one in-place rigid copy of switch_part per side (e.g. the placed switches of brain_mouse_board_place); pivot = the seed plunger top (rigid match) + seed_shift_mm [front, inward] (default [0, 0]; owner design input); z by pivot_z_rule: plunger_gap (v37: vertical move until the min plunger-top -> floor underside distance along the board normal is plunger_gap_mm 0.80, lowest side for all), seed (keep), auto (level seed -> plunger_gap, pitched -> seed). plate_parts (required for stage all) = the click plates, each paired with the seed below it; hinge = the plate's rear-edge underside corners (vertices within hinge_band_frac x length of the rearmost, end clusters hinge_cluster_frac x width, inner end projected on the mirror plane). symmetrise (default true) averages two mirrored sides. side_names optional (default the plate names). Report: derived_sides. board_parts = the parked board set copied rigidly to every side (default [pcb_part, switch_part]; add the connector etc.), output names <board_prefix>_<side>_<i> and <shell_part>_posts (or shell_out_name). MEASURED from the geometry: the board mounting holes (concave vertical cylinders of the PCB, the largest diameter group; board_hole_dia picks another size, board_holes [[x, y]] gives them in the board frame), board top and thickness, plunger top and body footprint, the floor underside and top, and the mirror plane (fitted from the shell; mirror_y overrides) used to check that the sides are mirror images. The post diameter FOLLOWS THE MEASURED HOLE: post_dia = hole diameter - post_hole_clearance_mm (0.25, slip fit) unless post_dia is given. stage place | posts | all. Placement: pitch about +Y fitted to the floor underside over the switch-body footprint (mean of the sides; or pitch_deg), roll 0; the plunger top moves only along the board normal until the minimum switch-body-top -> floor distance along the normal is body_gap_mm (0.38 print gap); the smallest shift of all sides is applied to all (mirror kept). Board posts: plain cylinder perpendicular to the board, tip flush with the board bottom, 4 stop ribs (rib_width 0.8 = two lines, rib_beyond_mm 0.95, rib_angles_deg 60/120/240/300) from the board top to the ceiling, columns trimmed top_margin_mm below the fitted floor-top plane, M1.6 self-tapping pilot pilot_dia 1.4 x pilot_depth_mm 4.5 with chamfer_mm 0.3. Actuators (stage all): act_w x act_h (3.4 x 5.0 = plunger footprint + margin, r act_corner_r 0.2) post on the plunger axis fused into the plate with root fillet act_root_fillet 0.3, tip gap tip_gap_mm 0.10 (no pre-load); floor hole = post + hole_clear_mm 0.32 per side grown by the lateral sweep over travel_mm 0.5 about the hinge. Every Boolean is gated (solid count, validity, volume bookkeeping, no silent no-op). Writes boards_<side>.step, <shell>_posts.step, posts_tool.step, click plates <plate>_posts.step, actuator_post_<side>.step, floor_hole_tool.step, board_posts_parts.step (all new parts, named) and board_posts_report.json (pitch, shifts, body / plunger gaps, measured hole and post diameter, mirror plane, post heights, rib lengths, hole sizes, volumes, round trip) once under mouse/cad/<bp_id>/ (never overwritten; same inputs return the stored report). Next: brain_mouse_interference_report on the input assembly + board_posts_parts.step. Runs in the server python (OCP)."""
        from . import mouse_board_posts
        return mouse_board_posts.board_posts(self.brain.store.root, step_paths, stage, shell_part, board_parts, pcb_part, switch_part, sides, board_holes, pitch_deg, mirror_y, rib_angles_deg, board_hole_dia=board_hole_dia, post_dia=post_dia, post_hole_clearance_mm=post_hole_clearance_mm, board_prefix=board_prefix, shell_out_name=shell_out_name, plate_parts=plate_parts, seed_switch_parts=seed_switch_parts, seed_shift_mm=seed_shift_mm, side_names=side_names, pivot_z_rule=pivot_z_rule, symmetrise=symmetrise, plunger_gap_mm=plunger_gap_mm, hinge_band_frac=hinge_band_frac, hinge_cluster_frac=hinge_cluster_frac, seed_match_tol_mm=seed_match_tol_mm, body_gap_mm=body_gap_mm, post_embed_mm=post_embed_mm, top_margin_mm=top_margin_mm, rib_width=rib_width, rib_beyond_mm=rib_beyond_mm, rib_overlap_mm=rib_overlap_mm, pilot_dia=pilot_dia, pilot_depth_mm=pilot_depth_mm, chamfer_mm=chamfer_mm, act_w=act_w, act_h=act_h, act_corner_r=act_corner_r, act_root_fillet=act_root_fillet, act_into_plate_mm=act_into_plate_mm, act_top_margin_mm=act_top_margin_mm, tip_gap_mm=tip_gap_mm, hole_clear_mm=hole_clear_mm, travel_mm=travel_mm, density_g_cm3=density_g_cm3)

    def brain_mouse_assembly_swap(self, assembly_step_path: str, replacements: list[dict[str, Any]], tol_volume_mm3: float = 1e-6, tol_position_mm: float = 1e-6, step_schema: str = 'AP242') -> dict[str, Any]:
        """Replace one or several labelled solids of an assembly STEP by solids of other STEP files and keep every other solid unchanged (CAD stage; the input STEP files are only read). Inputs: assembly_step_path = XCAF assembly (every leaf solid is a part named by its label; assembly instances keep their placement), replacements = [{"label": part name in the assembly, "step_path": STEP holding the new solid, "source_part"?: name of the solid when that STEP holds several}] (the new solid keeps its own frame, e.g. the official top shell in the shell frame), tol_volume_mm3 / tol_position_mm = gate tolerances (default 1e-6: only STEP write / read residues), step_schema AP242 (default) | AP214 | AP203. The result is a FLAT assembly STEP with the same labels and order, the same B-rep and placement for every untouched part and the part / face colours of the base (a replacement keeps its own colours, else the old part colour). It is written, read back and gated: label set and order, solid count, and for every untouched part the change of volume, centre of mass, bounding box and face count against the base file (max reported; PASS only within the tolerances), every replaced part against its source solid (volume, centre, bbox, face count, valid), colours kept. Replaced parts report old / new volume as BRepGProp and as closed-mesh volume (the two can differ by hundreds of mm3 on B-spline shells: use the mesh value for bookkeeping). Writes assembly.step and assembly_swap_report.json once under mouse/cad/<as_id>/ (never overwritten; same inputs return the stored report). Limits: nested sub-assemblies, layers, PMI and product properties of the base are not carried over; an XCAF part literally named SOLID / SHELL / COMPOUND is read as unnamed. Runs in the server python (OCP)."""
        from . import mouse_assembly_swap
        return mouse_assembly_swap.assembly_swap(self.brain.store.root, assembly_step_path, replacements, tol_volume_mm3, tol_position_mm, step_schema)

    def brain_mouse_seam_audit(self, shell_step_path: str, bands: list[dict[str, Any]] | None = None, part: str | None = None, g1_tol_deg: float = 1.0, samples: int = 9, flag: str = 'seams', band_tol_mm: float = 1e-6, deflection_mm: float = 0.1, view: str = 'XY', max_listed: int = 300, mirror_axis: str = 'y', mirror_plane_mm: float | None = None, band_half_width_mm: float | None = None) -> dict[str, Any]:
        """Seam audit of a shell solid (check stage; the STEP is only read): lists the B-rep edges inside given bands and measures the G1 deviation across each seam edge. bands = [{"name", "axis": "x"|"y"|"z", "range": [lo, hi] mm, "along_axis"?, "along_range"?}]; when omitted ONE slot band is derived: centred on the left-right symmetry plane of the shell (normal = mirror_axis, default y; the plane is fitted from the shell tessellation, mirror_plane_mm overrides it; nothing assumes the plane is at 0) with half width band_half_width_mm (default 1.5 % of the shell extent along the mirror axis); the fitted plane and residual are in the report (SEAM_NOT_SYMMETRIC when the shell has no symmetry plane and no bands are given). Give along_* for the click range, a second band for the rear skin line on the plane; part names one solid when the STEP holds several. Every edge is classified from its adjacent faces and the angle between the two outward face normals at `samples` points: smooth_seam (<= g1_tol_deg, a split of one smooth surface), crease (a real edge), closed_surface_seam (periodic face), free (open boundary), non_manifold. An edge is in a band when all its samples are inside the slab (and its mid point inside along_range). Flagged = in a band and smooth_seam / free / non_manifold (flag all: every in-band edge). Per band: edges in band, count per class, flagged count and length, faces in band (tessellation overlap, deflection_mm) and faces owning an in-band edge, the edges (id, class, faces, G1 max deg, length, mid, bbox; first max_listed); totals: faces, edges, edges per class. Status PASS only when no edge is flagged. Writes seam_plan.png (plan view of all edges, flagged edges red, bands blue; view XY | XZ | YZ) and seam_audit_report.json once under mouse/checks/<sa_id>/ (never overwritten; same inputs return the stored report). Limits: G1 is sampled; a smooth_seam can be designed; faces_in_band can miss slivers thinner than deflection_mm. Runs in the server python (OCP, matplotlib, scipy)."""
        from . import mouse_seam_audit
        return mouse_seam_audit.seam_audit(self.brain.store.root, shell_step_path, bands, part, g1_tol_deg, samples, flag, band_tol_mm, deflection_mm, view, max_listed, mirror_axis, mirror_plane_mm, band_half_width_mm)

    def brain_solid_boolean_safe(self, a_step_path: str, b_step_path: str, op: str, part_a: str | None = None, part_b: str | None = None, tol_mm: float = 0.01, fuzzy_multiples: list[float] | None = None, include_plain: bool = True, volume_tol_mm3: float = 10.0, volume_tol_rel: float = 0.001, points: int = 2000, near_surface_mm: float = 0.5, seed: int = 0, expect_solids: int | None = 1, unify: bool = True, shapefix: str = 'if_invalid', mesh_deflection_mm: float = 0.02) -> dict[str, Any]:
        """Gated Boolean (op fuse | cut | common) of two STEP solids (CAD stage; inputs only read; each STEP must hold one solid, or name it with part_a / part_b). A plain OCC Boolean can return None, an empty compound, the input again (no-op), two unmerged near-touching parts or sliver solids without an error, so every attempt is gated and the first that passes is kept. Attempts: plain, then BRepAlgoAPI fuzzy tol_mm x fuzzy_multiples (default [1.0, 0.7, 0.5, 1.5], tol_mm 0.01) ; include_plain false skips the plain attempt. Gate per attempt: result not null / not empty (empty only when the bookkeeping says ~0), solid count == expect_solids (null = any), valid (an invalid result is offered once to ShapeFix; shapefix always | never also available), volume = closed-mesh volume vs bookkeeping (fuse a + b - common, cut a - common, common a + b - fuse; the partner Boolean has its own gated ladder; tolerance min(volume_tol_mm3, volume_tol_rel x larger input)), a result equal to an input while the bookkeeping differs is named no_op, and a random point-in-solid test (points N, half uniform in the bbox, half within near_surface_mm of the input surfaces, seed for reproducibility): inside(result) == inside(a) op inside(b), bad <= max(2, N / 500), points ON a surface skipped. The accepted result is cleaned with ShapeUpgrade_UnifySameDomain (unify; merged faces / edges / B-splines) and re-gated; a clean that fails the gate is rejected and reported. Status PASS | UNVERIFIED (every gate passed but the volume partner Boolean failed) | FAIL (no result file). Writes result.step (read back: solids, valid, volume) and boolean_safe_report.json (attempts with checks, bookkeeping, point test numbers, clean log) once under mouse/cad/<sb_id>/ (never overwritten; same inputs return the stored report). Volumes are mesh volumes (BRepGProp moves by ~100 mm3 on B-spline solids); the partner Boolean is not an independent exact volume. Library use inside workers: solid_boolean_safe.safe_boolean_shapes / gate_boolean_result. Runs in the server python (OCP)."""
        from . import solid_boolean_safe
        return solid_boolean_safe.boolean_safe(self.brain.store.root, a_step_path, b_step_path, op, part_a, part_b, tol_mm, fuzzy_multiples, include_plain, volume_tol_mm3, volume_tol_rel, points, near_surface_mm, seed, expect_solids, unify, shapefix, mesh_deflection_mm)

    def brain_mouse_carve_shell(self, shell_step_path: str, windows: list[dict[str, Any]] | None = None, wall_mm: float = 1.2, floor_mm: float = 1.2, step_fillet_mm: float | None = None, face_roles: dict[str, list[int]] | None = None, ray_center: list[float] | None = None, ray_axes: list[float] | None = None, grid: list[int] | None = None, poles: list[int] | None = None, smoothing: float = 1e-7, floor_poles: int = 121, floor_smoothing: float = 1e-6, floor_edge_exclude_mm: float = 2.0, floor_domain: list[float] | None = None, floor_fill_lift_mm: float = 0.3, envelope_tol_mm: float = 0.1, face_samples: int = 700, wall_face_min_area_mm2: float | None = None, outline_kink_deg: float = 20.0, outline_kink_mm: float = 1.6, slot_band_mm: float = 1.0, compact_step: bool = True, reference_step_path: str | None = None, reference_part: str | None = None, offset_source_step_path: str | None = None, pocket_margin_mm: float | None = None, mirror_y: float | None = None, wall_face_min_area_frac: float = 0.05) -> dict[str, Any]:
        """Carve-from-solid hollowing of a FILLED mouse top-shell solid in ONE cavity cut (CAD stage, spec section 8; port of the owner-approved LH2 carve v26, defaults wall_mm / floor_mm 1.2 from c5_gpts / c5_floff2). Inputs: shell_step_path = one filled solid whose outer skin is kept (standard frame z up / x front, mirror plane y = mirror_y, default bbox centre, either handedness; wall faces = faces >= wall_face_min_area_frac 0.05 of the area unless wall_face_min_area_mm2, the click-plate floor recess, one vertical linear-extrusion step face = plate outline, the bottom bearing face; roles found automatically or given as face_roles {wall|floor|step|bearing: [face index]}), optional offset_source_step_path (solid whose wall / floor faces are offset, default the shell; v26 offset c5_clean_b and cut v18), windows [{step, type: wheel|side_button|other, sill?: {drop_mm, depth_mm, margin_mm?} (v26 window B: 4.0, 9.0, 0.3), label?}] cut after the cavity. Method: G = one LSQ B-spline (poles 161 x 121, smoothing 1e-7) of the inward wall offsets on a star ray grid (grid 481 x 361 from ray_center with ray_axes; auto from the bbox), side-button pockets filled by the neighbouring skin surface within the window outline + pocket_margin_mm (default 2 x wall) and the sill rectangle, inner envelope; K = plate outline (kink removed, offset by wall) prism above the floor offset sheet (heightfield LSQ floor_poles 121, floor_smoothing 1e-6, edge exclusion 2 mm) minus window sills; cavity = G - K; shell = S - cavity - windows; fillet R = step_fillet_mm (default wall) on the K lateral / sheet edge. Every boolean is gated (non-null, one valid solid, volume decreases, each window removes material). Report: solid count, validity, free edges, faces, slot-band seams, STEP round trip, wall / floor thickness (inward-normal rays), cavity and outer-skin deviation, volume bookkeeping, optional reference comparison (reference_step_path / reference_part); PASS / WARN / FAIL. Writes hollow_shell.step, cavity.step, cavity_fit.npz and carve_report.json once under mouse/cad/<cv_id>/ (never overwritten; same inputs return the stored report). Protected parts are not inputs: check them with brain_mouse_interference_report. Runs in the server python (OCP, scipy, vtk, matplotlib)."""
        from . import mouse_carve_shell
        return mouse_carve_shell.carve_shell(self.brain.store.root, shell_step_path, windows, wall_mm, floor_mm, step_fillet_mm, face_roles, ray_center, ray_axes, grid, poles, smoothing, floor_poles, floor_smoothing, floor_edge_exclude_mm, floor_domain, floor_fill_lift_mm, envelope_tol_mm, face_samples, wall_face_min_area_mm2, outline_kink_deg, outline_kink_mm, slot_band_mm, compact_step, reference_step_path, reference_part, offset_source_step_path, pocket_margin_mm, mirror_y, wall_face_min_area_frac)

    def brain_mouse_scan_symmetrise(self, relative_path: str, unit: str, labels_path: str | None = None, abs_threshold_mm: float = 2.0, rel_threshold: float = 0.015, cell_mm: float | None = None, correspondence_cap_mm: float = 1.0, fixed_regions: list[str] | None = None, exclude_regions: list[str] | None = None, normal_hint: list[float] | None = None, passes: int = 3, ramp_mm: float = 2.0, plane_search: str = 'lateral') -> dict[str, Any]:
        """Detect the mirror plane of a welded scan mesh and correct scan error ONLY where the part is really symmetric (mesh stage; no CAD is generated). Symmetry is never forced. Inputs: relative_path = welded STL (any frame, typically the flushed frame of brain_mouse_scan_flush; unit required, never guessed; output mm), optional labels_path = .json {region: [face ids]} or .npz face_labels + codes; labels are hints only (they group faces for the report and pair a region with its mirror counterpart), the geometry test decides. Method: robust best-fit mirror plane (plane_search lateral = start from the y axis of the standard frame x front / y left / z up, default; pca = try the three principal axes, best median residual wins; hint = start from normal_hint), soft-L1 point-to-tangent-plane residual of mirrored samples plus a trimmed refit, so one-sided features barely bias it); coarse test per region AND per local cell (cell_mm, default max(8 mm, 8 % of the bbox diagonal), cells on folded coordinates): statistic = p80 of the unbounded vertex-to-mirrored-surface distance, threshold = max(abs_threshold_mm 2.0, rel_threshold 0.015 x bbox diagonal); a region is ASYMMETRIC when its statistic exceeds the threshold or more than half of its cells fail; no usable plane when the global statistic exceeds 2 x threshold (NOT_READY, mesh unchanged). Only passing regions and cells are corrected: vertices move along their normal toward the mirrored counterpart (average both sides when their roughness is similar, otherwise mirror the better side; correspondences farther than correspondence_cap_mm 1.0 ignored; passes 3; displacement ramps to 0 over ramp_mm next to kept faces). Kept as scanned: failing cells and regions (real design asymmetry such as a thumb rest, a shifted half, side buttons), fixed_regions (default wheel, side buttons, sensor) and faces whose mirror image lands on them, exclude_regions (default bottom_plate). Face order and topology are unchanged, so the input labels stay valid. Writes symmetrised.stl, symmetry_mask.npz (asymmetric / fixed / symmetrised faces, vertex displacement), mirror_plane.json and symmetry_report.json (plane normal . x = d in the input frame, threshold, per-region statistic / cells / counterpart / decision, per-pair correction and residual before / after) once under mouse/scans/<sy_id>/ (never overwritten; same inputs return the stored report). The report is the symmetry source of brain_mouse_plate_side and brain_mouse_shell_fit. Runs in the separate scan python (env CADMCP_SCAN_PYTHON; numpy, scipy, trimesh); SCAN_PYTHON_MISSING without it."""
        from . import scan_symmetrise
        return scan_symmetrise.scan_symmetrise(self.brain.store.root, relative_path, unit, labels_path, abs_threshold_mm, rel_threshold, cell_mm, correspondence_cap_mm, fixed_regions, exclude_regions, normal_hint, passes, ramp_mm, plane_search)

    def brain_mouse_scan_fair(self, relative_path: str, unit: str, min_wavelength_mm: float = 12.0, labels_path: str | None = None, fixed_regions: list[str] | None = None, feature_protection: str = 'auto', feature_tol_mm: float | None = None, plate_freeze: str = 'auto', rim_height_mm: float | None = None, tol_p95_mm: float = 0.5, volume_tol_pct: float = 0.5) -> dict[str, Any]:
        """Belongs to the fused_original branch (see brain_mouse_scan_origin; no labels needed; may also be used on real scans optionally). Fair a welded scan mesh: remove ripples, facets and dents shorter than min_wavelength_mm and keep the shape (mesh stage; no CAD, no labels required). Only bumps / distortion are removed: same vertices, same faces, same face order (no remesh, no inflation or shrink; the input labels stay valid). Inputs: relative_path = welded STL (any frame, typically symmetrised.stl or flushed.stl; unit required, never guessed; output mm), min_wavelength_mm (default 12; the shortest wavelength to keep = half-gain point of the filter; 8 = light, 16-18 = strong), optional labels_path = .json {region: [face ids]} or .npz face_labels + codes with fixed_regions (default wheel / side buttons / sensor; frozen, never moved). Method: thin-plate (bi-Laplacian) low-pass on the fine mesh, solve (diag(wd) + lam L^T diag(wb) L) V = wd V0 with L the graph Laplacian and lam = 16 (w / (2 pi h))^4 (h = mean edge length), one sparse LU. Protection, all derived from the geometry and reported: (1) plate_freeze auto = the dominant flat face-normal cluster (>= 2 % of the surface; the bottom plate in any orientation) and the band within rim_height_mm (default min_wavelength_mm / 3) above it are frozen, so the parting rim and the plate stay as scanned; (2) feature_protection auto = after the plain pass, vertices it moved by more than feature_tol_mm (default min_wavelength_mm / 40) are shape (steps, button pads, wheel, click steps) and get a low bending weight in a second solve, so they are kept instead of crushed; off = plain filter; (3) fixed_regions via labels. Report: volume change, deviation p50 / p95 / max (free vertices to the input surface), displacement, ripple RMS before / after at min_wavelength_mm / 2 and at min_wavelength_mm (normal component of the high-pass residual), curvature roughness (mean-curvature RMS, curvature-Laplacian RMS, face-normal jitter p95), protected vertex counts / fraction (plate rim, labels, auto features), watertight / face-order checks. READY only when the mesh stays watertight, |volume change| <= volume_tol_pct (0.5) and deviation p95 <= tol_p95_mm (0.5). Writes faired.stl, fair_mask.npz (displacement, protection masks, feature weights) and fair_report.json once under mouse/scans/<fa_id>/ (never overwritten; same inputs return the stored report). Limits: positions only, no remesh; auto protection also keeps ripples whose amplitude exceeds feature_tol_mm; plate rim frozen only when a dominant flat cluster exists. Runs in the separate scan python (env CADMCP_SCAN_PYTHON; numpy, scipy, trimesh); SCAN_PYTHON_MISSING without it."""
        from . import scan_fair
        return scan_fair.scan_fair(self.brain.store.root, relative_path, unit, min_wavelength_mm, labels_path, fixed_regions, feature_protection, feature_tol_mm, plate_freeze, rim_height_mm, tol_p95_mm, volume_tol_pct)

    def brain_mouse_shell_fit(self, relative_path: str, unit: str, labels_path: str | None = None, regions: list[str] | None = None, symmetry_report_path: str | None = None, mirror_plane: dict[str, Any] | None = None, mode: str = 'auto', fit_side: str = 'auto', cut_planes: list[dict[str, Any]] | None = None, degree: int = 3, spans_u: int = 10, spans_v: int = 6, smoothing: float = 1e-7, min_wavelength_mm: float = 10.0, tol_p95_mm: float = 0.2, tol_max_mm: float = 1.0, front_cut: str = 'auto', front_cut_step_mm: float = 3.0) -> dict[str, Any]:
        """Fit the outer skin of a scan shell region as a fair, CAD-grade B-spline surface (no scan copy: short waviness is rejected on purpose). Inputs: relative_path = welded STL (typically symmetrised.stl of brain_mouse_scan_symmetrise; unit required, never guessed; output mm), labels_path + regions (default ['top_shell']; labels are hints that select the domain), symmetry source = symmetry_report_path (brain_mouse_scan_symmetrise report: plane normal . x = d and per-region decisions) or mirror_plane {normal, d}, optional cut_planes [{normal, d}] (keep normal . x <= d; at most 3; e.g. a front cut where another tool builds the front). front_cut auto (default; used only when cut_planes is empty): the full domain is fitted first; when that is not READY, the most forward cut plane perpendicular to the mirror plane along the input x axis (standard frame, x front; front side = side of the click labels) whose fit is READY is chosen by a coarse scan backwards in front_cut_step_mm (default 3) and a 0.5 mm forward refinement; the chosen cut and every candidate are reported (front_cut, cut_planes_used) and stored in shell_surface.json for brain_mouse_shell_solid; front_cut none keeps the full domain. Symmetry is never forced: mode auto fits HALF + mirror only when every domain region is symmetric in the report (mode half refuses otherwise: SHELL_FIT_NOT_SYMMETRIC), else ONE face over the full region; fit_side auto takes the half with the larger region area (fewer feature holes). Method: domain cut exactly at the mirror / cut planes, ears removed, jagged label boundary smoothed and re-projected, feature holes bridged with zero fit weight; four corners = ends of the plane sides + boundary turning > 35 deg (>= 5 mm apart), a 3-corner domain gets a scored 4th corner on its longest free side; harmonic (cotan) map to the unit square; KKT-constrained least squares, degree (default 3), spans_u x spans_v (default 10 x 6) capped so the knot spacing is >= min_wavelength_mm / 2 (default 10 mm: no ripple shorter than about 10 mm can be represented), thin-plate smoothing (default 1e-7), plane sides exactly on their plane, mirror G0 + G1 (cross tangent along the plane normal, so G2 across the mirror), Gauss-Newton parameter correction; OCP Geom_BSplineSurface, mirror copy, sewing, STEP. Checks: deviation p95 <= tol_p95_mm (0.2) and max <= tol_max_mm (1.0) against the domain points, independent OCP projection check, other half mirrored vs the fit, mirror G0 / G1, flipped parameter area <= 0.1 %, minimum parameter angle >= 10 deg, fairness (mean-curvature gradient, kmax), valid sewn B-rep; READY only when all pass. Writes shell_skin.step (open skin) and shell_surface.json (degree, knots, poles in the input frame) and shell_fit_report.json once under mouse/cad/<sf_id>/ (never overwritten; same inputs return the stored report). Limits: one four-sided face per half (no interior crease split), the skin is not closed to a solid and has no crisp lip (brain_mouse_shell_solid closes it). Runs in the server python (OCP, scipy, trimesh)."""
        from . import scan_shell_fit
        return scan_shell_fit.shell_fit(self.brain.store.root, relative_path, unit, labels_path, regions, symmetry_report_path, mirror_plane, mode, fit_side, cut_planes, degree, spans_u, spans_v, smoothing, min_wavelength_mm, tol_p95_mm, tol_max_mm, front_cut, front_cut_step_mm)

    def brain_mouse_shell_solid(self, shell_fit_report_path: str, layout_path: str | None = None, labels_path: str | None = None, shell_regions: list[str] | None = None, plate_regions: list[str] | None = None, exclude_regions: list[str] | None = None, parting_mode: str = 'auto', parting_z_mm: float | None = None, flat_tolerance_mm: float = 0.3, plain_front: bool = True, lip_band_mm: float = 4.2, front_stiffness: float = 20.0, trim_inward_mm: float = 0.4, min_face_area_mm2: float = 0.5, tol_p95_mm: float = 0.3) -> dict[str, Any]:
        """Close a brain_mouse_shell_fit skin to a CLOSED top-shell solid (B-rep, mm). Input: shell_fit_report_path = a half + mirror shell_fit report with exactly one front cut (front_cut auto or one cut_planes entry); the mesh, labels (override labels_path), unit and cut are taken from it. layout_path (optional) = slot_layout.json or the brain_mouse_scan_click_grooves report: the groove bands next to the click slots and the wheel window are kept out of the crease and cap fits. Labels are hints: shell_regions (default top_shell, left_click, right_click), plate_regions (bottom_plate ...), exclude_regions (wheel, side buttons, sensor; exclude margin 2.5 mm). Method in the frame of the mirror plane and the cut: plan silhouette of the front from the trusted scan, crease line (side panel / front lip) measured per 1 mm station from the normals (top quadratic x wall line), robust symmetric smoothing, snapped to the skin; front tube (flanks + PLAIN front wall: lip band of lip_band_mm below the crease and recesses deeper than trim_inward_mm such as the cable hole are not followed; front_stiffness) with exact G0 / G1 to the skin at both ends; cap = MakeFilling, G1 to the skin and to the tube near the ends, C0 along the rest of the crease = a crisp lip edge made by intersecting faces; parting surface: parting_mode auto = z-const plane (median seam height or parting_z_mm) when the fitted shell / plate seam is flat within flat_tolerance_mm (0.3), else the fitted seam height field; seam | plane force one. The skin + tube + cap are sewn and closed with the parting surface (MakerVolume); the interior volume is kept. Checks: skin READY, valid, one closed solid, no face smaller than min_face_area_mm2, STEP re-import valid + tessellates, no multiple edges, scan deviation p95 <= tol_p95_mm (front includes the cable hole and grooves on purpose). Writes top_shell_solid.step, front_construction.npz (crease, plan) and shell_solid_report.json once under mouse/cad/<ss_id>/ (never overwritten; same inputs return the stored report). Next: brain_mouse_click_slots on top_shell_solid.step. Limits: half + mirror skins and one front cut only; slots, wheel window and side buttons are not cut here. Runs in the server python (OCP, scipy)."""
        from . import scan_shell_solid
        return scan_shell_solid.shell_solid(self.brain.store.root, shell_fit_report_path, layout_path, labels_path, shell_regions, plate_regions, exclude_regions, parting_mode, parting_z_mm, flat_tolerance_mm, plain_front, lip_band_mm, front_stiffness, trim_inward_mm, min_face_area_mm2, tol_p95_mm)

    def brain_mouse_click_slots(self, shell_step_path: str, layout_path: str, slot_width_mm: float | None = None, gap_width_mm: float | None = None, depth_mm: float = 2.0, window_depth_mm: float | None = None, window_length_mm: float | None = None, window_width_mm: float | None = None, window_radius_mm: float | None = None, mirror_plane: dict[str, Any] | None = None, abs_threshold_mm: float = 2.0, rel_threshold: float = 0.015, cut_perimeter: bool = True, cut_gap: bool = True, cut_window: bool = True, smooth_mm: float = 1.5, symmetry_report_path: str | None = None, through_wall: bool = False, lip_height_mm: float | None = None) -> dict[str, Any]:
        """Cut the click-panel slots and the wheel window into a closed shell solid STEP (B-rep). Layout = the brain_mouse_scan_click_grooves report (its slot_layout.json is used) or slot_layout.json written by it (click_slot_layout/1: open perimeter path + slot side, centre-gap segments, window corners) or a hand-written one in the same schema; geometry comes from the spec parameters (slot width, centre-gap width, depth below the local B-rep surface, window length/width/corner radius/depth), defaults from the layout. Floors follow the shell top surface minus the depth (smoothed), walls vertical, edges crisp; the window is a rounded-rectangle pocket with a flat floor parallel to its rim plane. Optional mirror plane: symmetry_report_path (brain_mouse_scan_symmetrise report, mirror_plane.json, or a report naming its symmetry report such as shell_fit) or mirror_plane {normal, d}, not both: the layout is symmetrised only where it passes the coarse mirror test (p80 residual <= max(abs_threshold_mm, rel_threshold x diag)); symmetry is never forced. Writes slotted_shell.step, slot_cutters.step and click_slots_report.json (checks: valid, one solid, removed volume, measured widths) once under mouse/cad/<cs_id>/; cached; the input STEP is never modified. Units mm. through_wall=true (hollow-first order: the input is already a hollow shell): the groove floors are not ramped at the open ends, the cut is expected to split the shell and every piece is kept, healed, gated and written (slotted_shell.step = largest, piece_k.step the others; result.solids_after_cut, pieces_written); the slot width is measured 0.4 mm below the skin. lip_height_mm (through_wall only, explicit design value, mm above the shell's lowest point): the front lip line = intersection of the skin with the plane through the two trimmed perimeter ends and the nose point at that height is cut as one more band of slot width, so the plates separate from the shell along the front lip (report trim.lip_line)."""
        from . import scan_click_slots
        return scan_click_slots.click_slots(self.brain.store.root, shell_step_path, layout_path, slot_width_mm, gap_width_mm, depth_mm, window_depth_mm, window_length_mm, window_width_mm, window_radius_mm, mirror_plane, abs_threshold_mm, rel_threshold, cut_perimeter, cut_gap, cut_window, smooth_mm, symmetry_report_path, through_wall, lip_height_mm)

    def brain_mouse_scan_side_buttons(self, shell_step_path: str, mesh_path: str, labels_path: str | None = None, regions_report_path: str | None = None, reference_images: list[str] | None = None, groove_width_mm: float = 0.4, groove_depth_mm: float = 1.5, corner_radius_mm: float = 1.0, proud_mm: float | None = None, default_proud_mm: float = 1.0, top_threshold_mm: float = 0.35, outline_tol_mm: float = 0.35, max_per_flank: int = 2, min_area_mm2: float = 15.0, min_land_mm: float = 1.0) -> dict[str, Any]:
        """Build the side-button pads (raised, crisp) with a groove round each on a closed top-shell STEP (CAD stage; normally slotted_shell.step of brain_mouse_click_slots) and write a NEW STEP. Inputs: shell_step_path (one solid, mm), mesh_path = scan STL in the same frame (e.g. flushed.stl of brain_mouse_scan_flush; a report path pairs its STL + labels) and labels_path (.npz face_labels + codes or .json {name: [triangle ids]}; names side_button_1 / side_button_2 / sidebutton* / B1..B4; labels.npz next to the mesh is paired automatically; labels are hints), optional regions_report_path (brain_mouse_recognize_regions report: per-button confidence + handedness), optional reference_images (workspace image paths, recorded for the reviewer, not analysed). Generic: 0..max_per_flank (default 2) buttons per flank, any handedness, never mirrored; without labels raised flank patches (> top_threshold_mm above the skin) are detected (confidence medium). Per button: push direction = mean skin normal; outline = convex hull of the scan points > top_threshold_mm (default 0.35) above the skin, simplified (outline_tol_mm 0.35), straight edges re-fitted, corners filleted (corner_radius_mm 1.0; mild turns blended), one periodic B-spline edge; top = quadratic fit of the scan pad top when the confidence is high, else skin + default_proud_mm (1.0; v6-style default, status REVIEW); proud_mm forces a fixed protrusion; groove = outline offset groove_width_mm (0.4) to groove_depth_mm (1.5) below the skin (both 0 = plain raised pad). Existing slots / grooves of the shell (click slots) are detected from the skin (narrow dips and wall steps along the push direction) and never moved: the pad outline is clipped by half-planes so that the groove ring keeps min_land_mm (default 1.0, minimum intact skin between groove and slot; 0 = groove edge may touch the detected slot) of skin to every slot (warning SIDE_BUTTON_CLIPPED_BY_SLOT, per-button slot_clearance), NOT_READY SIDE_BUTTON_BLOCKED_BY_SLOT only when less than 40 % of the pad area (or min_area_mm2) is left. Gates (NOT_READY): SIDE_BUTTONS_TOO_MANY, SIDE_BUTTON_NOT_ON_FLANK, SIDE_BUTTON_SKIN_DISCONTINUOUS (edge / slot / hole under the button), SIDE_BUTTON_PROUD_OUT_OF_RANGE, SIDE_BUTTONS_OVERLAP, brep_valid, one_solid, reimport, no_slivers, outline_regular, groove_as_specified, pad_proud. Writes side_buttons_shell.step, side_buttons.json (per-button frame + outline) and side_buttons_report.json (per button: flank, confidence + reasons, outline size / radii, scan vs used protrusion, measured groove width / depth and protrusion on the re-imported STEP) once under mouse/cad/<sb_id>/; cached; the input STEP is never modified. Next: brain_mouse_plate_side / brain_mouse_face_roles on outputs.shell (pads read as sidebutton + sidebutton_wall). Units mm."""
        from . import scan_side_buttons
        return scan_side_buttons.side_buttons(self.brain.store.root, shell_step_path, mesh_path, labels_path, regions_report_path, reference_images, groove_width_mm, groove_depth_mm, corner_radius_mm, proud_mm, default_proud_mm, top_threshold_mm, outline_tol_mm, max_per_flank, min_area_mm2, min_land_mm)

    def brain_mouse_scan_click_grooves(self,relative_path: str, labels_path: str, unit: str, slot_width_mm: float = 0.5, slot_depth_mm: float = 2.0, panel_overlap_mm: float = 0.2, perimeter_clearance_mm: float = 0.005, fit_tolerance_mm: float = 0.2, fillet_radius_mm: float | None = None, min_wall_mm: float = 0.0, rebuild_window: bool = True, overlay: bool = True, gap_clear_mm: float = 2.0, gap_front_margin_mm: float = 2.5, gap_overshoot_mm: float = 0.5, symmetry_report_path: str | None = None) -> dict[str, Any]:
        """Rebuild the click-panel grooves of a welded scan mesh as clean rectangular slots (mesh stage; no CAD is generated). Inputs: relative_path = watertight welded STL in the standard frame (x front, y left, z up, bottom plate at z 0; unit required, never guessed; output mm) and labels_path = .json {region: [face ids]} (names left_click / right_click / wheel, optional top_shell, bottom_plate, side_button_1/2; also LC RC WH B1 B2) or .npz face_labels + codes from the recognition steps. Method: fit the start lines from the data (centre gap = one averaged straight line per click, merged when the clicks meet; perimeter = outer ring of the closed click outline as averaged straight pieces with fillets, radius fitted unless fillet_radius_mm is given), cut vertical-walled flat-floor slots of slot_width_mm per panel side (default 0.5 mm; the centre gap is the union, about 1.0 mm; panel_overlap_mm 0.2 reaches into the panel so the edge is cut clean) to slot_depth_mm below the smoothed panel surface (default 2.0 mm), shift the perimeter slot outward until it cannot encroach on the panel edge (perimeter_clearance_mm margin), remove the wheel and rebuild its window as a rounded rectangle fitted to the RIM of the wheel well (geometry: top height field without the wheel faces, pixels deeper than 0.8 mm below the plane of a ring round the label hole, opened by 1 mm so the centre gap does not leak in; falls back to the label hole with warning WINDOW_RIM_FROM_LABELS) with a floor parallel to the rim (rebuild_window, needs the wheel label; brain_mouse_click_slots window_length_mm / window_width_mm / window_radius_mm override it), exact boolean (manifold3d), weld, drop degenerate faces / zero-volume flaps / detached splinters, verify one watertight body. Cut-through (slot floor leaving the original solid) is allowed and reported per run; min_wall_mm > 0 raises floors instead. Writes combined_grooved.stl, one STL per labelled region, slot_layout.json (plan start lines of the perimeter slot and centre gap, slot side, window corners / radius / rim and floor planes; input of brain_mouse_click_slots), click_grooves_report.json (widths, depths, flatness, wall verticality, centre-gap width, cut-through list, bodies, watertight before / after, volume removed, fit results) and optional before_after.png under mouse/scans/<groove_id>/; never overwrites; the same inputs return the stored report. Runs in the separate scan python (env CADMCP_SCAN_PYTHON) with numpy, scipy, trimesh, shapely and manifold3d (extra scan-grooves); CLICK_GROOVE_KERNEL_UNAVAILABLE when a library is missing, SCAN_PYTHON_MISSING without the python. Stop codes: CLICK_GROOVE_REGIONS_MISSING, CLICK_GROOVE_MESH_NOT_WATERTIGHT, CLICK_GROOVE_NO_GAP, CLICK_GROOVE_FRAME, CLICK_GROOVE_CUTTER_INVALID. G1.4: the perimeter start line is regularised (straight pieces merged against noise kinks / waves, per-vertex fillet radii = tangent arcs, G1), mirrored from the better click branch where near-symmetric (coarse test per piece, symmetry_tol 1.5 mm; never forced), the window is a rounded rectangle centred on the centre-gap line; optional symmetry_report_path (brain_mouse_scan_symmetrise report) snaps the gap line onto the mirror plane when within 2 mm. Gates (NOT_READY): PERIMETER_OUTLINE_ROUGH (smoothed-fit deviation > 0.02 mm or curvature sign changes), WINDOW_OFF_GAP_LINE, PANEL_LABEL_OVERHANG_TOO_LARGE."""
        return scan_click_grooves.scan_click_grooves(self.brain.store.root, relative_path, labels_path, unit, slot_width_mm, slot_depth_mm, panel_overlap_mm, perimeter_clearance_mm, fit_tolerance_mm, fillet_radius_mm, min_wall_mm, rebuild_window, overlay, gap_clear_mm, gap_front_margin_mm, gap_overshoot_mm, symmetry_report_path)

    def brain_mouse_scan_clean(self, scan_id: str | None = None, relative_path: str | None = None, unit: str | None = None, mode: str = 'grooves', grooves: list[dict[str, Any]] | None = None, zones: list[dict[str, Any]] | None = None, max_zone_deviation_mm: float = 0.6, outside_tolerance_mm: float = 0.05, design_intent: bool = False) -> dict[str, Any]:
        """Re-cut under-resolved grooves, or fill explicit messy zones, on a READY scan (give scan_id = a prepared scan or a brain_mouse_scan_model model_id, or relative_path + unit of an STL/OBJ; the full-resolution cleaned STL gives the best result). mode grooves: each groove (0.6-1.2 mm wide, about the mesh edge length) is fitted as a 3D B-spline centre line (open or closed) with a piecewise-constant width / depth profile (trapezoid cut between two quadratic skins; steps explicit), faces round it are subdivided and moved along the surface normal to the fitted profile. Seeds are the region boundaries of brain_mouse_recognize_regions (click gap, click rim, side-button pad rings; wheel excluded), or the grooves override [{name, points [[x, y, z] mm], closed}]. Stations whose fit fails or whose groove is shallower than 0.05 mm are left original. design_intent=true (open grooves only; optional per-groove straight in the grooves override) REPLACES the groove by a clean one: smoothed low-curvature centre line (straight where the fitted centres are), one constant width / depth (robust median of the trusted stations, reported), skins refitted from the trusted surface, displacement up to max_zone_deviation_mm; the report lists stations fitted / rebuilt by intent / left original and whether the cap binds; undercut slits behind a lip are not rebuilt. mode zones: zones [{name, box {min, max} and / or faces [ids]}] are filled from their surroundings (moving least squares, tapered, displacement capped at max_zone_deviation_mm, default 0.6); it smooths and can erase real features and does not rebuild grooves. Writes cleaned.stl, cleaned.ply, groove_params.json (centre-line control points, widths, depths, step positions; mm, prepared-scan frame) and a report with per-groove deviation, roughness before / after, watertight / manifold / winding verified on the written STL, outside-zone deviation against outside_tolerance_mm (default 0.05) and self-intersection counts (UNVERIFIED unless zero) under mouse/scans/<clean_id>/. Runs numpy / scipy / PyMeshLab (GPL-3.0) in a subprocess from a separate python (env CADMCP_SCAN_PYTHON; SCAN_PYTHON_MISSING when absent). Never modifies the source and never overwrites outputs; stop codes (SCAN_CLEAN_NO_GROOVE_SEEDS, SCAN_CLEAN_NOTHING_EDITED, ...) replace loosening. Limits are listed in the report (floor shape unresolved at the edge length, loops and steps only partly clean, no CAD is generated)."""
        return scan_clean.scan_clean(self.brain.store.root, scan_id, relative_path, unit, mode, grooves, zones, max_zone_deviation_mm, outside_tolerance_mm, design_intent)

    def brain_mouse_recognize_regions(self, scan_id: str, handedness: str = 'auto', overlay: bool = True) -> dict[str, Any]:
        """Find left click, right click, scroll wheel, side button 1 and 2 and the palm shell on a READY prepared scan (best on the full-resolution cleaned STL). Frame, front/rear, base and right/left-hand mouse are detected from the mesh (handedness auto|right|left). Returns per-region face count, area, bbox, a high/med/low confidence and a note for every boundary stretch that is inferred rather than supported by a groove; writes face labels (hashed) and optional top/flank overlay PNGs under mouse/scans/<scan_id>/regions/. NOT_READY for a mesh that is not welded/closed. Surface-only: hinges, switches and the wheel axle are not visible and are not inferred. Calibrated on an OP1-class mouse; no CAD is generated."""
        return scan_regions.recognize_regions(self.brain.store.root, scan_id, handedness, overlay)

    def brain_mouse_recognize_shell(self, scan_id: str, handedness: str = 'auto') -> dict[str, Any]:
        """Find the bottom plate, top shell, parting seam and sensor window on a READY prepared scan (runs brain_mouse_recognize_regions first; the click, wheel and side-button faces are excluded from the top shell). Geometry only (no texture): the seam is the groove of the outer wall found by a circular path search over 1 degree azimuth bins; bins without a clear groove (typically the rear) are interpolated and listed as inferred, with a supported fraction and a confidence. The sensor window is the deep pocket in the underside (centre and size in the work frame mm and in the canonical frame, depth above the fitted plate plane). Writes hashed face labels (bottom_plate=1, top_shell=2) and seam / sensor outlines under mouse/scans/<scan_id>/shell/. S1.3 hand-off: labels.npz (one file: bottom_plate, top_shell, left_click, right_click, wheel, side_button_1, side_button_2) and canonical.stl (the prepared mesh in the mesh-derived canonical frame x front, y mouse-left, z up, same face order; 4x4 scan_to_canonical in the report) are the inputs of brain_mouse_scan_flush. Surface-only: the sensor PCB and chip behind the window are not visible. No CAD is generated."""
        try:
            return scan_shellparts.recognize_shell(self.brain.store.root, scan_id, handedness)
        except BrainError as exc:
            if exc.code == 'SHELL_SEAM_NOT_FOUND':  # code, message and existing details stay; only a hint is added
                exc.details = {**exc.details, 'next': 'No parting seam: this looks like a fused / original model (e.g. a findmymouse blend), not a real scan. Ask the user which it is and see brain_mouse_scan_origin (fused_original branch: brain_mouse_scan_fair).'}
            raise

    def brain_mouse_build_shell_brep(self, scan_id: str, thickness_mm: float, opening: dict[str, Any], route: str = 'faceted_sdf', voxel_mm: float = 0.5, outer_tolerance_mm: float = 0.15, thickness_tolerance_mm: float = 0.1, max_faces: int = 60000, max_voxels: int = 40000000, grid: int | None = None, degree_min: int | None = None, degree_max: int | None = None, fit_tolerance_mm: float | None = None, smoothing: float | None = None) -> dict[str, Any]:
        """Hollow a READY scan into an open-bottom solid. route faceted_sdf (default): signed-distance shell, surface nets, one planar face per triangle (voxel_mm, max_faces, max_voxels). route smooth_fit: two fitted B-spline surfaces (outer skin = scan, inner skin = phi=-thickness) on the same rays + a planar ring on the opening plane; needs a scan that is star-shaped from the opening-section centroid and locally thicker than 2 x thickness (grid default 121, max 201; degree_min, degree_max, fit_tolerance_mm, smoothing). Routes never fall back to each other; checks report PASS/FAIL/UNVERIFIED and stop codes replace coarsening or loosening."""
        smooth_args = {'grid': grid, 'degree_min': degree_min, 'degree_max': degree_max, 'fit_tolerance_mm': fit_tolerance_mm, 'smoothing': smoothing}
        if route == 'faceted_sdf':
            given = [k for k, x in smooth_args.items() if x is not None]
            if given:
                raise BrainError('SHELL_SETTINGS', 'These arguments belong to route smooth_fit and are not accepted by faceted_sdf.', {'arguments': given})
            return scan_shell.build_shell_brep(self.brain.store.root, scan_id, thickness_mm, opening, voxel_mm, outer_tolerance_mm, thickness_tolerance_mm, max_faces, max_voxels)
        if route == 'smooth_fit':
            return scan_fit.build_shell_smooth(self.brain.store.root, scan_id, thickness_mm, opening, 121 if grid is None else grid, 3 if degree_min is None else degree_min,
                                               5 if degree_max is None else degree_max, outer_tolerance_mm, thickness_tolerance_mm, fit_tolerance_mm, 0.0 if smoothing is None else smoothing)
        raise BrainError('SHELL_SETTINGS', "route must be 'faceted_sdf' or 'smooth_fit'.", {'route': route})
