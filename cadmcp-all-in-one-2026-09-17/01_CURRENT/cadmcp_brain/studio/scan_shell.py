"""Scan -> hollow shell, stage A1 (faceted B-rep route "faceted_sdf"). See docs/design/SCAN_TO_SHELL_A1.md.

prepare_scan inspects/repairs a closed scan mesh (only allow-listed repairs, all reported).
build_shell_brep makes an open-bottom hollow faceted B-rep solid and measures it.
Every check is PASS / FAIL / UNVERIFIED; execution success is a separate field.
Nothing here is a smooth surface model (that is route A2) and nothing coarsens or falls back silently.
"""
from __future__ import annotations
import math
import time
from pathlib import Path
from typing import Any
import numpy as np
from pydantic import Field, ValidationError, model_validator
from scipy import ndimage
from . import scan_mesh as sm
from .recipe import Strict
from .. import __version__
from ..errors import BrainError
from ..req2cad.common import atomic_json, json_load
from ..util import digest, file_hash, safe_id, safe_path

SCAN_SHELL_VERSION = 'A1.0'
ROUTE = 'faceted_sdf'
LONG_AXIS_MM = (30.0, 200.0)
SAMPLES = 20_000
GRID_PHASE = np.array([0.3719, 0.2618, 0.4142])


class Repairs(Strict):
    weld_tolerance_mm: float | None = Field(default=None, gt=0, le=5)
    remove_degenerate: bool = False
    drop_components_below_fraction: float | None = Field(default=None, gt=0, lt=1)
    orient_outward: bool = False
    fill_holes_max_perimeter_mm: float | None = Field(default=None, gt=0, le=500)


class PlaneOpening(Strict):
    type: str
    point: list[float]
    normal: list[float]

    @model_validator(mode='after')
    def plane(self):
        if self.type != 'plane':
            raise ValueError('Only a plane opening is supported by route faceted_sdf.')
        for name, v in (('point', self.point), ('normal', self.normal)):
            if len(v) != 3 or any(isinstance(x, bool) or not math.isfinite(x) for x in v):
                raise ValueError(f'{name} must be three finite millimetre components.')
        if math.sqrt(sum(x * x for x in self.normal)) < 1e-9:
            raise ValueError('normal must be non-zero.')
        return self


def scan_dir(workspace: Path, scan_id: str) -> Path:
    return workspace / 'mouse' / 'scans' / safe_id(scan_id)


def _write(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_bytes(data)
    tmp.replace(path)
    return file_hash(path)


# ------------------------------------------------------------------ prepare
def prepare_scan(workspace: Path, relative_path: str, unit: str, transform: list[float] | None = None,
                 repairs: dict[str, Any] | None = None) -> dict[str, Any]:
    if unit not in sm.UNIT_MM:
        raise BrainError('SCAN_UNIT', 'unit is required and must be one of mm, cm, m, in. It is never guessed.', {'given': unit})
    try:
        rep = Repairs.model_validate(repairs or {})
    except ValidationError as exc:
        raise BrainError('SCAN_REPAIRS_INVALID', 'repairs failed validation.', {'error_count': len(exc.errors())}) from exc
    if transform is not None:
        from .mouse import _affine
        try:
            _affine(transform)
        except ValueError as exc:
            raise BrainError('SCAN_TRANSFORM_INVALID', str(exc)) from exc
    src = safe_path(workspace, relative_path)
    sha = file_hash(src)
    v, f = sm.read_mesh(src)
    if not np.isfinite(v).all():
        raise BrainError('SCAN_FILE', 'Scan contains non-finite coordinates.')
    raw = {'triangles': int(len(f)), 'vertices_indexed': int(len(v))}
    settings = {'unit': unit, 'unit_scale_to_mm': sm.UNIT_MM[unit], 'transform': transform, 'repairs': rep.model_dump()}
    scan_id = 'scan_' + digest({'sha256': sha, 'settings': settings, 'version': SCAN_SHELL_VERSION})[:12]
    v = v * sm.UNIT_MM[unit]
    applied: list[dict[str, Any]] = []
    det = None
    if transform is not None:
        m = np.array(transform, dtype=np.float64).reshape(4, 4)
        v = v @ m[:3, :3].T + m[:3, 3]
        det = float(np.linalg.det(m[:3, :3]))
        if det < 0:
            f = f[:, [0, 2, 1]]
            applied.append({'repair': 'mirror_transform_reverses_triangle_order', 'note': 'transform determinant is negative; winding reversed to keep the outward side', 'determinant': det})
    n_before_weld = len(np.unique(f))
    v, f = sm.compact(v, f)
    if rep.weld_tolerance_mm is not None:
        v, f, disp = sm.weld(v, f, rep.weld_tolerance_mm)
        v, f = sm.compact(v, f)
        applied.append({'repair': 'weld', 'tolerance_mm': rep.weld_tolerance_mm, 'vertices_before': n_before_weld, 'vertices_after': int(len(v)), 'max_vertex_displacement_mm': disp})
    if rep.remove_degenerate:
        f, n = sm.remove_degenerate(v, f)
        v, f = sm.compact(v, f)
        applied.append({'repair': 'remove_degenerate', 'triangles_removed': n})
    if rep.drop_components_below_fraction is not None and len(f):
        f, info = sm.drop_small_components(v, f, rep.drop_components_below_fraction)
        v, f = sm.compact(v, f)
        applied.append({'repair': 'drop_components_below_fraction', 'fraction': rep.drop_components_below_fraction, **info})
    if rep.orient_outward and len(f):
        f, info = sm.orient_outward(v, f)
        applied.append({'repair': 'orient_outward', **info})
    filled_area = 0.0
    if rep.fill_holes_max_perimeter_mm is not None and len(f):
        n0 = len(v)
        v, f, info = sm.fill_holes(v, f, rep.fill_holes_max_perimeter_mm)
        filled_area = info['filled_area_mm2']
        applied.append({'repair': 'fill_holes', 'max_perimeter_mm': rep.fill_holes_max_perimeter_mm, 'vertices_added': int(len(v) - n0),
                        **info, 'note': 'filled area is surface not measured by the scan'})
    insp = sm.inspect(v, f) if len(f) else {'triangles': 0}
    blockers: list[str] = []
    warnings: list[dict[str, Any]] = []
    if not len(f):
        blockers.append('EMPTY_MESH')
    else:
        if insp['boundary_edges']:
            blockers.append('HOLES_PRESENT')
        if insp['non_manifold_edges']:
            blockers.append('NON_MANIFOLD_EDGES')
        if insp['inconsistent_orientation_edges']:
            blockers.append('INCONSISTENT_ORIENTATION')
        if insp['component_count'] != 1:
            blockers.append('MULTIPLE_COMPONENTS')
        if insp['signed_volume_mm3'] <= 0:
            blockers.append('ORIENTATION_NOT_OUTWARD')
        ext = np.array(insp['bbox_max_mm']) - np.array(insp['bbox_min_mm'])
        long_axis = float(ext.max())
        if not LONG_AXIS_MM[0] <= long_axis <= LONG_AXIS_MM[1]:
            warnings.append({'code': 'UNIT_SUSPECT', 'long_axis_mm': long_axis, 'expected_range_mm': list(LONG_AXIS_MM),
                             'note': 'Not rescaled. Confirm the unit argument.'})
        if insp['degenerate_triangles']:
            warnings.append({'code': 'DEGENERATE_TRIANGLES', 'count': insp['degenerate_triangles']})
    status = 'READY' if not blockers else 'NOT_READY'
    out = scan_dir(workspace, scan_id)
    npz_sha = None
    if status == 'READY':
        npz_sha = _write(out / 'prepared.npz', sm.npz_bytes(vertices=v, faces=f.astype(np.int64)))
    report = {
        'schema': 'scan_prepare_report/1', 'scan_id': scan_id, 'code_version': {'scan_shell': SCAN_SHELL_VERSION, 'package': __version__},
        'source': {'relative_path': relative_path, 'sha256': sha, 'bytes': src.stat().st_size}, 'settings': settings,
        'input': raw, 'repairs_applied': applied, 'inspection': insp, 'warnings': warnings,
        'unmeasured_surface_mm2': filled_area, 'prepared_status': status, 'blocking_reasons': blockers,
        'prepared_npz_sha256': npz_sha, 'transform_determinant': det,
        'checks': {'closed': _chk(not insp.get('boundary_edges', 1) and len(f) > 0), 'two_manifold': _chk(len(f) > 0 and insp.get('non_manifold_edges', 1) == 0 and insp.get('boundary_edges', 1) == 0),
                   'orientation_consistent': _chk(len(f) > 0 and insp.get('inconsistent_orientation_edges', 1) == 0),
                   'single_component': _chk(insp.get('component_count') == 1), 'self_intersection': 'UNVERIFIED'},
        'execution': {'completed': True},
    }
    atomic_json(out / 'prepare_report.json', report)
    return report


def _chk(ok: bool) -> str:
    return 'PASS' if ok else 'FAIL'


# ------------------------------------------------------------------ clip volume
def _clipped_volume(v: np.ndarray, f: np.ndarray, p0: np.ndarray, n: np.ndarray) -> float:
    """Volume of closed mesh intersected with the half-space (x - p0).n <= 0. The cap lies in the plane through
    p0 (the tetra origin), so it contributes zero."""
    w = v - p0
    d = w @ n
    ins = d[f] <= 0
    k = ins.sum(1)
    vol = 0.0
    full = f[k == 3]
    vol += sm.signed_volume(w, full) if len(full) else 0.0
    tris: list[np.ndarray] = []
    for case in (1, 2):
        sel = np.flatnonzero(k == case)
        if not len(sel):
            continue
        tri = f[sel]
        flags = ins[sel]
        # rotate so vertex 0 is the odd one out (the single inside vertex for case 1, the single outside vertex for case 2)
        odd = np.where(flags if case == 1 else ~flags, 1, 0)
        shift = np.argmax(odd, axis=1)
        idx = (np.arange(3)[None, :] + shift[:, None]) % 3
        rt = np.take_along_axis(tri, idx, axis=1)
        a, b, c = w[rt[:, 0]], w[rt[:, 1]], w[rt[:, 2]]
        da, db, dc = d[rt[:, 0]], d[rt[:, 1]], d[rt[:, 2]]
        pab = a + (b - a) * (da / (da - db))[:, None]
        pac = a + (c - a) * (da / (da - dc))[:, None]
        if case == 1:
            tris.append(np.stack([a, pab, pac], axis=1))
        else:  # a is outside, b and c inside
            pab2 = b + (a - b) * (db / (db - da))[:, None]
            pac2 = c + (a - c) * (dc / (dc - da))[:, None]
            tris.append(np.stack([b, c, pac2], axis=1))
            tris.append(np.stack([b, pac2, pab2], axis=1))
    for t in tris:
        vol += float(np.einsum('ij,ij->i', t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() / 6.0)
    return vol


# ------------------------------------------------------------------ B-rep
def _ocp():
    try:
        import OCP  # noqa: F401
    except Exception as exc:
        raise BrainError('BREP_KERNEL_UNAVAILABLE', 'OCP (OpenCascade) is not importable; the faceted B-rep cannot be built.') from exc


def build_brep(verts: np.ndarray, faces: np.ndarray):
    """One planar face per triangle; vertices and edges are created once and shared (no tolerance sewing)."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeVertex, BRepBuilderAPI_MakeWire
    from OCP.gp import gp_Pnt
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.TopoDS import TopoDS, TopoDS_Shell, TopoDS_Solid
    ov = [BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, p))).Vertex() for p in verts]
    edges: dict[tuple[int, int], Any] = {}
    shell, bb = TopoDS_Shell(), BRep_Builder()
    bb.MakeShell(shell)
    for tri in faces.tolist():
        mw = BRepBuilderAPI_MakeWire()
        for i in range(3):
            a, b = tri[i], tri[(i + 1) % 3]
            key = (a, b) if a < b else (b, a)
            e = edges.get(key)
            if e is None:
                e = edges[key] = BRepBuilderAPI_MakeEdge(ov[key[0]], ov[key[1]]).Edge()
            mw.Add(e if a < b else TopoDS.Edge_s(e.Reversed()))
        if not mw.IsDone():
            raise BrainError('BREP_FIT_FAILED', 'A triangle wire could not be built.', {'triangle': tri})
        mf = BRepBuilderAPI_MakeFace(mw.Wire(), True)
        if not mf.IsDone():
            raise BrainError('BREP_FIT_FAILED', 'A triangle could not be made into a planar face.', {'triangle': tri})
        bb.Add(shell, mf.Face())
    solid = TopoDS_Solid()
    bb.MakeSolid(solid)
    bb.Add(solid, shell)
    fix = ShapeFix_Solid()
    fix.Init(solid)
    fix.Perform()
    return fix.Solid()


def _unify(shape):
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    u = ShapeUpgrade_UnifySameDomain(shape, True, True, True)
    u.Build()
    return u.Shape()


def _volume(shape) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    p = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, p)
    return float(p.Mass())


def _topology(shape, plane_p0, plane_n) -> dict[str, Any]:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID, TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.BRep import BRep_Tool

    def count(s, kind):
        ex, c = TopExp_Explorer(s, kind), 0
        while ex.More():
            c += 1
            ex.Next()
        return c
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    faces, rim_faces = 0, []
    while ex.More():
        face = TopoDS.Face_s(ex.Current())
        faces += 1
        ad = BRepAdaptor_Surface(face)
        if ad.GetType() == GeomAbs_Plane:
            pl = ad.Plane()
            nn = np.array([pl.Axis().Direction().X(), pl.Axis().Direction().Y(), pl.Axis().Direction().Z()])
            loc = pl.Location()
            off = float(np.dot(np.array([loc.X(), loc.Y(), loc.Z()]) - plane_p0, plane_n))
            if abs(abs(float(nn @ plane_n)) - 1) < 1e-9 and abs(off) < 1e-6:
                rim_faces.append(count(face, TopAbs_WIRE))
        ex.Next()
    closed = True
    sh = TopExp_Explorer(shape, TopAbs_SHELL)
    while sh.More():
        closed &= bool(BRep_Tool.IsClosed_s(sh.Current()))
        sh.Next()
    return {'valid': bool(BRepCheck_Analyzer(shape).IsValid()), 'solids': count(shape, TopAbs_SOLID), 'shells': count(shape, TopAbs_SHELL),
            'faces': faces, 'shell_closed': closed, 'opening_plane_faces_wire_counts': rim_faces}


def _write_step(shape, path: Path) -> None:
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
    w = STEPControl_Writer()
    w.Transfer(shape, STEPControl_AsIs)
    if w.Write(str(path)) != IFSelect_RetDone:
        raise BrainError('STEP_EXPORT_FAILED', 'STEP writer did not complete.')


def _read_step(path: Path):
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader
    r = STEPControl_Reader()
    if r.ReadFile(str(path)) != IFSelect_RetDone:
        raise BrainError('STEP_ROUNDTRIP_FAILED', 'Exported STEP could not be read back.')
    r.TransferRoots()
    return r.OneShape()


def _stl_bytes(v: np.ndarray, f: np.ndarray) -> bytes:
    t = v[f]
    nrm = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-300)
    rec = np.zeros(len(f), dtype=np.dtype([('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')]))
    rec['n'], rec['v'] = nrm, t
    return b'cadmcp scan_shell A1'.ljust(80, b' ') + np.uint32(len(f)).tobytes() + rec.tobytes()


def load_prepared(workspace: Path, scan_id: str) -> tuple[Path, dict[str, Any]]:
    """Scan directory and prepare report of a READY scan; shared by every build route."""
    d = scan_dir(workspace, scan_id)
    rp = d / 'prepare_report.json'
    if not rp.is_file():
        raise BrainError('SCAN_NOT_FOUND', 'No prepared scan with this id. Run brain_mouse_prepare_scan first.')
    prep = json_load(rp)
    if prep.get('prepared_status') != 'READY':
        raise BrainError('SCAN_NOT_READY', 'The scan is not READY; fix the blocking reasons first.', {'blocking_reasons': prep.get('blocking_reasons')})
    npz = d / 'prepared.npz'
    if not npz.is_file() or file_hash(npz) != prep.get('prepared_npz_sha256'):
        raise BrainError('SCAN_NOT_READY', 'prepared.npz is missing or does not match its report hash.')
    return d, prep


def load_prepared_mesh(d: Path) -> tuple[np.ndarray, np.ndarray]:
    z = np.load(d / 'prepared.npz', allow_pickle=False)
    return z['vertices'].astype(np.float64), z['faces'].astype(np.int64)


# ------------------------------------------------------------------ build
def _stats(x: np.ndarray, *pcts: float) -> dict[str, float]:
    out = {'min': float(x.min()), 'max': float(x.max()), 'mean': float(x.mean())}
    for p in pcts:
        out[f'p{p:g}'] = float(np.percentile(x, p))
    return out


def build_shell_brep(workspace: Path, scan_id: str, thickness_mm: float, opening: dict[str, Any], voxel_mm: float = 0.5,
                     outer_tolerance_mm: float = 0.15, thickness_tolerance_mm: float = 0.1, max_faces: int = 60000,
                     max_voxels: int = 40_000_000) -> dict[str, Any]:
    for name, val, lo in (('thickness_mm', thickness_mm, 0.0), ('voxel_mm', voxel_mm, 0.0), ('outer_tolerance_mm', outer_tolerance_mm, 0.0), ('thickness_tolerance_mm', thickness_tolerance_mm, 0.0)):
        if not math.isfinite(val) or val <= lo:
            raise BrainError('SHELL_SETTINGS', f'{name} must be a positive finite number.')
    if max_faces < 12 or max_voxels < 1000:
        raise BrainError('SHELL_SETTINGS', 'max_faces / max_voxels are too small.')
    try:
        op = PlaneOpening.model_validate(opening)
    except ValidationError as exc:
        raise BrainError('SHELL_OPENING_INVALID', 'opening must be {type:"plane", point:[x,y,z], normal:[x,y,z]} in mm.', {'error_count': len(exc.errors())}) from exc
    d, prep = load_prepared(workspace, scan_id)
    _ocp()
    t0 = time.perf_counter()
    v, f = load_prepared_mesh(d)
    p0 = np.array(op.point, dtype=np.float64)
    nrm = np.array(op.normal, dtype=np.float64)
    nrm /= np.linalg.norm(nrm)
    t = float(thickness_mm)
    h = float(voxel_mm)
    # 1. grid
    pad = t + 3 * h
    # Fixed sub-voxel origin offset: keeps grid nodes off round-valued planes/vertices (exact-zero field values give coincident surface-net vertices).
    lo, hi = v.min(0) - pad - h * GRID_PHASE, v.max(0) + pad
    shape = tuple(int(math.ceil((hi[i] - lo[i]) / h)) + 1 for i in range(3))
    nvox = shape[0] * shape[1] * shape[2]
    grid = {'origin_mm': lo.tolist(), 'spacing_mm': h, 'shape': list(shape), 'voxels': nvox}
    settings = {'route': ROUTE, 'scan_id': scan_id, 'thickness_mm': t, 'opening': {'type': 'plane', 'point': p0.tolist(), 'normal': nrm.tolist()},
                'voxel_mm': h, 'outer_tolerance_mm': outer_tolerance_mm, 'thickness_tolerance_mm': thickness_tolerance_mm,
                'max_faces': max_faces, 'max_voxels': max_voxels}

    def stop(code: str, message: str, details: dict[str, Any]):
        atomic_json(d / 'build_report.json', {'schema': 'scan_shell_build_report/1', 'settings': settings, 'grid': grid,
                                              'execution': {'completed': False, 'code': code, 'message': message, 'details': details}, 'design_status': 'UNVERIFIED'})
        raise BrainError(code, message, details)

    if nvox > max_voxels:
        stop('SCAN_GRID_TOO_LARGE', 'The voxel grid exceeds max_voxels; increase voxel_mm or max_voxels. Nothing was coarsened.',
             {'voxels': nvox, 'max_voxels': max_voxels, 'voxel_mm_that_would_fit': math.ceil(h * (nvox / max_voxels) ** (1 / 3) * 1000) / 1000})
    axes = tuple(lo[i] + h * np.arange(shape[i]) for i in range(3))
    # 2. inside mask
    mask, cross = sm.inside_mask(v, f, axes)
    if cross['mismatch_rate'] > 0.001:
        stop('SCAN_INSIDE_TEST_UNSTABLE', 'Ray parity along Z and X disagree; the scan is probably not a clean closed surface.', cross)
    # 3. signed distance
    sd = (nrm[0] * (axes[0] - p0[0])[:, None, None] + nrm[1] * (axes[1] - p0[1])[None, :, None] + nrm[2] * (axes[2] - p0[2])[None, None, :])
    dist = sm.MeshDistance(v, f)
    phi, n_exact = sm.signed_distance(v, f, axes, mask, (0.0, -t), sd <= 2.0 * h, h, dist)
    # 4. shell field
    inner = -(phi + t)
    psi = np.maximum(np.maximum(phi, inner), sd)
    label = np.where((sd >= phi) & (sd >= inner), 2, np.where(inner > phi, 1, 0)).astype(np.int8)
    # locally solid regions (fact, computed from the same field)
    deep = phi <= -t
    kept_inside = (phi < 0) & (sd <= 0)
    if deep.any():
        dc = ndimage.distance_transform_edt(~deep, sampling=(h, h, h))
        solid = kept_inside & (dc > math.sqrt(3.0) * t + h)
    else:
        solid = kept_inside
    lab, nsolid = ndimage.label(solid)
    solid_info = {'count': int(nsolid), 'volume_mm3': float(solid.sum() * h ** 3), 'definition':
                  'inside nodes on the kept side farther than sqrt(3)*t + voxel from the deep region {phi <= -t}; a fact, not a FAIL'}
    del lab, deep, kept_inside, solid
    # 5. surface nets
    mv, mf, vlabel, vpure = sm.surface_nets(psi, lo, h, label)
    del psi, phi, inner, label, sd, mask
    to_plane = vlabel == 2  # plane-dominated cells: the true rim lies in the plane, so the vertex belongs on it
    if to_plane.any():
        mv[to_plane] -= ((mv[to_plane] - p0) @ nrm)[:, None] * nrm
    man = sm.mesh_manifold_report(mf, len(mv))
    ar = sm.areas(mv, mf)
    if not man['closed_2_manifold']:
        _diag(d, mv, mf)
        stop('SHELL_MESH_NOT_MANIFOLD', 'The extracted shell mesh is not a closed 2-manifold; nothing was patched. Diagnostic mesh written.', man)
    ncomp, _ = sm.face_components(mf, len(mv))
    if ncomp != 1:
        _diag(d, mv, mf)
        stop('SHELL_MESH_DISCONNECTED', 'The shell surface has more than one connected part: the opening plane does not open the cavity (or the cavity is sealed). Move the plane into the cavity.', {'connected_parts': int(ncomp)})
    ndeg = int((ar < 1e-12).sum())
    if ndeg:
        _diag(d, mv, mf)
        stop('SHELL_MESH_DEGENERATE', 'The shell mesh has zero-area triangles after projection; nothing was patched.', {'degenerate_triangles': ndeg})
    ntri = int(len(mf))
    if ntri > max_faces:
        stop('BREP_FACE_BUDGET_EXCEEDED', 'Triangle count exceeds max_faces; nothing was coarsened.',
             {'triangles': ntri, 'max_faces': max_faces, 'voxel_mm_that_would_fit': math.ceil(h * math.sqrt(ntri / max_faces) * 1.02 * 1000) / 1000})
    t_mesh = time.perf_counter() - t0
    # 6. B-rep
    t1 = time.perf_counter()
    try:
        raw_shape = build_brep(mv, mf)
        shape_u = _unify(raw_shape)
    except BrainError:
        _diag(d, mv, mf)
        raise
    except Exception as exc:
        _diag(d, mv, mf)
        stop('BREP_FIT_FAILED', f'B-rep construction raised {type(exc).__name__}. Diagnostic mesh written.', {'message': str(exc)[:500]})
    topo = _topology(shape_u, p0, nrm)
    if not (topo['valid'] and topo['solids'] == 1 and topo['shells'] == 1 and topo['shell_closed']):
        _diag(d, mv, mf)
        stop('BREP_FIT_FAILED', 'The B-rep is not one valid closed solid. Diagnostic mesh written.', topo)
    t_brep = time.perf_counter() - t1
    # 7. export
    mesh_sha = _write(d / 'shell_mesh.npz', sm.npz_bytes(vertices=mv, faces=mf, vertex_label=vlabel, vertex_pure=vpure.astype(np.uint8)))
    stl_sha = _write(d / 'shell.stl', _stl_bytes(mv, mf))
    _write_step(shape_u, d / 'shell.step')
    step_sha = file_hash(d / 'shell.step')
    # 8. checks
    checks: dict[str, Any] = {}
    v_mesh = sm.signed_volume(mv, mf)
    v_brep = _volume(shape_u)
    rel = abs(v_brep - v_mesh) / max(abs(v_mesh), 1e-300)
    checks['brep_valid'] = {'status': _chk(topo['valid']), **{k: topo[k] for k in ('solids', 'shells', 'faces')}}
    checks['single_closed_solid'] = {'status': _chk(topo['solids'] == 1 and topo['shells'] == 1 and topo['shell_closed']), 'shell_closed': topo['shell_closed'], 'solids': topo['solids']}
    checks['volume_consistency'] = {'status': _chk(rel <= 1e-6 and v_brep > 0), 'brep_mm3': v_brep, 'mesh_mm3': v_mesh, 'relative_difference': rel, 'limit': 1e-6}
    rt = _read_step(d / 'shell.step')
    rt_topo = _topology(rt, p0, nrm)
    rt_vol = _volume(rt)
    checks['step_roundtrip'] = {'status': _chk(rt_topo['valid'] and rt_topo['solids'] == 1 and abs(rt_vol - v_brep) / max(v_brep, 1e-300) <= 1e-6),
                                'volume_mm3': rt_vol, 'valid': rt_topo['valid'], 'solids': rt_topo['solids']}
    tri_label = vlabel[mf]
    tri_pure = vpure[mf].all(axis=1)
    outer_ids = np.flatnonzero((tri_label == 0).all(axis=1) & tri_pure)
    inner_ids = np.flatnonzero((tri_label == 1).all(axis=1) & tri_pure)
    skin = {'outer_triangles': int(len(outer_ids)), 'inner_triangles': int(len(inner_ids)), 'total_triangles': ntri,
            'excluded_mixed_or_plane_triangles': int(ntri - len(outer_ids) - len(inner_ids)),
            'note': 'Triangles whose cells mix terms (rim between skin and opening plane) are not sampled; the rim zone is not measured by the skin checks.'}
    if len(outer_ids):
        pts, _ = sm.sample_surface(mv, mf[outer_ids], SAMPLES)
        dev = dist.distance(pts)
        fwd = _stats(dev, 99)
        fwd['samples'] = SAMPLES
    else:
        fwd = None
    rev = None
    if len(outer_ids):
        spts, _ = sm.sample_surface(v, f, SAMPLES)
        keep = (spts - p0) @ nrm < -2.0 * h
        if keep.any():
            ov, of = sm.compact(mv, mf[outer_ids])
            rd = sm.MeshDistance(ov, of).distance(spts[keep])
            rev = _stats(rd, 99)
            rev['samples'] = int(keep.sum())
            rev['excluded_within_2_voxels_of_plane'] = int((~keep).sum())
    if fwd is None:
        checks['outer_deviation'] = {'status': 'FAIL', 'reason': 'no pure outer-skin triangles were produced', 'skin': skin}
    else:
        ok = fwd['max'] <= outer_tolerance_mm and rev is not None and rev['max'] <= outer_tolerance_mm
        checks['outer_deviation'] = {'status': _chk(ok) if rev is not None else 'UNVERIFIED', 'tolerance_mm': outer_tolerance_mm,
                                     'output_to_scan': fwd, 'scan_to_output': rev, 'skin': skin}
    if len(inner_ids):
        pts, _ = sm.sample_surface(mv, mf[inner_ids], SAMPLES)
        wt = dist.distance(pts)
        st = _stats(wt, 1)
        st['samples'] = SAMPLES
        checks['wall_thickness'] = {'status': _chk(st['min'] >= t - thickness_tolerance_mm), 'target_mm': t, 'tolerance_mm': thickness_tolerance_mm, **st,
                                    'note': 'sampled minimum on the inner skin, not a global minimum'}
    else:
        checks['wall_thickness'] = {'status': 'FAIL', 'reason': 'no pure inner-skin triangles were produced'}
    scan_kept = _clipped_volume(v, f, p0, nrm)
    cavity = scan_kept - v_brep
    rim_ok = any(c >= 2 for c in topo['opening_plane_faces_wire_counts'])
    checks['opening_present'] = {'status': _chk(rim_ok and cavity > 0), 'planar_faces_on_opening_plane_wire_counts': topo['opening_plane_faces_wire_counts'],
                                 'scan_volume_kept_side_mm3': scan_kept, 'shell_volume_mm3': v_brep, 'cavity_volume_mm3': cavity}
    checks['locally_solid_regions'] = {'status': 'PASS', 'reported_as_fact': True, **solid_info}
    checks['self_intersection'] = {'status': prep.get('checks', {}).get('self_intersection', 'UNVERIFIED'),
                                   'note': 'scan self-intersection is not checked by prepare; the output mesh is not checked either'}
    checks['edit_suitability'] = {'status': 'INFO', 'note': 'faceted B-rep: boolean/export ok if checks pass; not a smooth surface model; surface-quality metrics do not apply to this route'}
    blocking = ['brep_valid', 'single_closed_solid', 'volume_consistency', 'step_roundtrip', 'outer_deviation', 'wall_thickness', 'opening_present']
    states = [checks[k]['status'] for k in blocking]
    design = 'PASS' if all(s == 'PASS' for s in states) else ('FAIL' if 'FAIL' in states else 'UNVERIFIED')
    report = {
        'schema': 'scan_shell_build_report/1', 'code_version': {'scan_shell': SCAN_SHELL_VERSION, 'package': __version__}, 'settings': settings, 'grid': grid,
        'inputs': {'prepared_npz_sha256': prep['prepared_npz_sha256'], 'source_sha256': prep['source']['sha256'], 'unmeasured_surface_mm2': prep.get('unmeasured_surface_mm2', 0.0)},
        'inside_test_crosscheck': cross, 'exact_distance_nodes': n_exact,
        'mesh': {'triangles': ntri, 'vertices': int(len(mv)), 'sha256_shell_mesh_npz': mesh_sha, 'pinch_vertices': man['pinch_vertices'],
                 'plane_projected_vertices': int(to_plane.sum())},
        'hashes': {'shell_mesh_npz': mesh_sha, 'shell_stl': stl_sha, 'shell_step': step_sha, 'note': 'shell.step contains a writer timestamp; determinism is defined on shell_mesh.npz'},
        'timing_s': {'grid_to_mesh': t_mesh, 'brep': t_brep, 'total': time.perf_counter() - t0},
        'peak_voxel_count': nvox, 'brep_faces_after_unify': topo['faces'], 'checks': checks, 'blocking_checks': blocking,
        'unverified_items': [k for k, c in checks.items() if c['status'] == 'UNVERIFIED'],
        'design_status': design, 'execution': {'completed': True}, 'files': ['shell.step', 'shell.stl', 'shell_mesh.npz', 'build_report.json'],
    }
    atomic_json(d / 'build_report.json', report)
    return report


def _diag(d: Path, mv: np.ndarray, mf: np.ndarray) -> None:
    _write(d / 'diagnostic_mesh.npz', sm.npz_bytes(vertices=mv, faces=mf))
