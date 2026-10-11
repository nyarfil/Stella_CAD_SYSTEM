"""Bottom plate with ONE straight ruled side under a given shell (brain_mouse_plate_side).

Inputs: the shell STEP (one closed solid; its largest down-facing face is the parting face, whose outer wire is the outer parting edge) and a
base-outline source in the same frame (plate floor z = 0): a scan STL sectioned at section_z_mm, the lowest planar face of a plate STEP, or a
polyline JSON. Optional mirror plane (a brain_mouse_scan_symmetrise report or explicit mirror_normal + mirror_d): the outline gets the same coarse
per-sector symmetry test as the shell and is symmetrised only where it is near-symmetric. The geometry runs in a subprocess of the server python
(scan_plate_side_worker.py: OCP, numpy, scipy, shapely). The shell file is only read (sha256 checked before / after); outputs go once under
mouse/cad/<pl_id>/ and are never overwritten (the same inputs return the stored report).
PS1.5 default (outline_mode mesh, section_z_mm auto): the floor extrapolation also uses the mesh sections below the chosen star-shaped section,
per angle, while the wall stays continuous going down (floor_min_z_mm 0.1, floor_max_slope 4 mm/mm), so the rounded foot is measured down to
the floor instead of extrapolated from 0.5 mm up (the outline was ~0.2 mm too wide on the flanks).
"""
from __future__ import annotations
import math
from pathlib import Path
from typing import Any
from .scan_cad_common import check_file, check_range, run_job, server_python
from .. import __version__
from ..errors import BrainError
from ..req2cad.common import json_load
from ..util import file_hash

PLATE_SIDE_VERSION = 'PS1.5'
WORKER = Path(__file__).with_name('scan_plate_side_worker.py')
REPORT = 'plate_side_report.json'
TIMEOUT_S = 1800
MODES = {'mesh': ('.stl',), 'step': ('.step', '.stp'), 'polyline': ('.json',)}
DEFAULTS = {'section_z_mm': None, 'n_stations': 1500, 'n_sectors': 24, 'abs_thr_mm': 2.0, 'rel_thr': 0.015, 'similar_ratio': 0.7, 'max_change_mm': 0.1,
            'min_inset_mm': 0.0, 'front_rim_mm': 1.2}
_RANGES = {'section_z_mm': (0.01, 5.0), 'n_stations': (200, 5000), 'n_sectors': (4, 72), 'abs_thr_mm': (0.1, 20.0), 'rel_thr': (0.0, 0.2),
           'similar_ratio': (0.0, 1.0), 'max_change_mm': (0.0, 2.0), 'min_inset_mm': (0.0, 10.0), 'front_rim_mm': (0.0, 10.0)}
_INTS = ('n_stations', 'n_sectors')
# READY limits (mm, mm3)
MAX_PROTRUSION_MM = 1e-3
MAX_OVERLAP_MM3 = 1e-3
MAX_CONTACT_GAP_MM = 1e-3
MAX_EDGE_DEV_MM = 0.01
MAX_FLOOR_DEV_MM = 0.02


def plate_side(workspace: Path, shell_step_path: str, outline_mode: str, outline_path: str, symmetry_report_path: str | None = None,
               mirror_normal: list[float] | None = None, mirror_d: float | None = None, section_z_mm: float | None = DEFAULTS['section_z_mm'],
               n_stations: int = DEFAULTS['n_stations'], n_sectors: int = DEFAULTS['n_sectors'], abs_thr_mm: float = DEFAULTS['abs_thr_mm'],
               rel_thr: float = DEFAULTS['rel_thr'], similar_ratio: float = DEFAULTS['similar_ratio'], max_change_mm: float = DEFAULTS['max_change_mm'],
               min_inset_mm: float = DEFAULTS['min_inset_mm'], front_rim_mm: float = DEFAULTS['front_rim_mm'],
               front_min_corner_radius_mm: float | None = None, front_blend_deg: list[float] | None = None,
               front_direction: list[float] | None = None) -> dict[str, Any]:
    workspace = Path(workspace)
    if outline_mode not in MODES:
        raise BrainError('PLATE_SIDE_MODE', "outline_mode must be 'mesh', 'step' or 'polyline'.", {'given': outline_mode})
    given = {'section_z_mm': section_z_mm, 'n_stations': n_stations, 'n_sectors': n_sectors, 'abs_thr_mm': abs_thr_mm, 'rel_thr': rel_thr,
             'similar_ratio': similar_ratio, 'max_change_mm': max_change_mm, 'min_inset_mm': min_inset_mm, 'front_rim_mm': front_rim_mm}
    for name, val in given.items():
        if name == 'section_z_mm' and val is None:
            continue
        lo, hi = _RANGES[name]
        check_range(name, val, lo, hi, 'PLATE_SIDE_SETTINGS')
        if name in _INTS and int(val) != val:
            raise BrainError('PLATE_SIDE_SETTINGS', f'{name} must be an integer.', {'given': val})
    if int(n_sectors) % 2:
        raise BrainError('PLATE_SIDE_SETTINGS', 'n_sectors must be even (sectors are tested in mirror pairs).', {'given': n_sectors})
    if front_min_corner_radius_mm is not None:
        check_range('front_min_corner_radius_mm', front_min_corner_radius_mm, 0.0, 60.0, 'PLATE_SIDE_SETTINGS')
    fb = [38.0, 58.0] if front_blend_deg is None else front_blend_deg
    if (not isinstance(fb, (list, tuple)) or len(fb) != 2 or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in fb)
            or not 0.0 <= fb[0] < fb[1] <= 120.0):
        raise BrainError('PLATE_SIDE_SETTINGS', 'front_blend_deg must be [start, end] degrees from the front, 0 <= start < end <= 120.', {'given': front_blend_deg})
    if front_direction is not None and (not isinstance(front_direction, (list, tuple)) or len(front_direction) != 2
                                        or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in front_direction)
                                        or math.hypot(*front_direction) < 1e-9):
        raise BrainError('PLATE_SIDE_SETTINGS', 'front_direction must be a plan vector [dx, dy] (default +x = front of the standard frame).', {'given': front_direction})
    shell = check_file(workspace, shell_step_path, ('.step', '.stp'), 'PLATE_SIDE_FILE', 'shell_step_path')
    outline = check_file(workspace, outline_path, MODES[outline_mode], 'PLATE_SIDE_FILE', f'outline_path (mode {outline_mode})')
    sym = None
    mirror: dict[str, Any] | None = None
    if symmetry_report_path is not None:
        if mirror_normal is not None or mirror_d is not None:
            raise BrainError('PLATE_SIDE_SYMMETRY', 'Give either symmetry_report_path or mirror_normal + mirror_d, not both.')
        sym = check_file(workspace, symmetry_report_path, ('.json',), 'PLATE_SIDE_SYMMETRY', 'symmetry_report_path')
        try:
            pl = json_load(sym)['plane']
            mirror = {'normal': [float(x) for x in pl['normal']], 'd': float(pl['d']), 'source': 'symmetry_report'}
        except (KeyError, TypeError, ValueError) as exc:
            raise BrainError('PLATE_SIDE_SYMMETRY', 'The symmetry report needs "plane": {"normal": [nx, ny, nz], "d": d} (mirror plane n.x = d).') from exc
    elif mirror_normal is not None or mirror_d is not None:
        if mirror_normal is None or mirror_d is None:
            raise BrainError('PLATE_SIDE_SYMMETRY', 'mirror_normal and mirror_d go together.')
        mirror = {'normal': mirror_normal, 'd': mirror_d, 'source': 'arguments'}
    if mirror is not None:
        n = mirror['normal']
        if (not isinstance(n, (list, tuple)) or len(n) != 3 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in n)
                or isinstance(mirror['d'], bool) or not isinstance(mirror['d'], (int, float)) or not math.isfinite(mirror['d'])):
            raise BrainError('PLATE_SIDE_SYMMETRY', 'The mirror plane needs a finite normal [nx, ny, nz] and a finite d.', {'given': mirror})
        s = math.hypot(*n)
        if s < 1e-9 or math.hypot(n[0], n[1]) / s < 0.9:
            raise BrainError('PLATE_SIDE_SYMMETRY', 'The mirror plane must be close to vertical (|n_xy| >= 0.9 |n|).', {'normal': n})
        mirror = {'normal': [float(x) for x in n], 'd': float(mirror['d']), 'source': mirror['source']}
    settings = {**{k: (None if v is None else int(v) if k in _INTS else float(v)) for k, v in given.items()}, 'outline_mode': outline_mode, 'mirror': mirror,
                'front_min_corner_radius_mm': None if front_min_corner_radius_mm is None else float(front_min_corner_radius_mm),
                'front_blend_deg': [float(x) for x in fb], 'front_direction': None if front_direction is None else [float(x) for x in front_direction]}
    shell_sha = file_hash(shell)

    def build_report(res: dict[str, Any], folder: Path, job_id: str, hashes: dict[str, str | None]) -> dict[str, Any]:
        return _report(res, job_id, hashes, settings, shell, shell_sha, shell_step_path, outline_path, symmetry_report_path)

    return run_job(workspace=workspace, area='cad', prefix='pl_', version=PLATE_SIDE_VERSION, code='PLATE_SIDE',
                   inputs={'shell': shell, 'outline': outline, 'symmetry': sym}, settings=settings, worker=WORKER, python=server_python(),
                   report_name=REPORT, build_report=build_report, timeout_s=TIMEOUT_S)


def _pf(ok: bool | None) -> str:
    return 'UNVERIFIED' if ok is None else ('PASS' if ok else 'FAIL')


def _report(res, job_id, hashes, settings, shell: Path, shell_sha, shell_rel, outline_rel, sym_rel) -> dict[str, Any]:
    c = res['checks']
    base = res['base_outline']
    shell_now = file_hash(shell)
    ov = c.get('overlap_volume_mm3')
    checks = {
        'plate_valid_one_solid': _pf(c['plate']['valid'] and c['plate']['solids'] == 1 and c['plate']['faces'] == 3),
        'assembly_two_solids': _pf(c['assembly']['solids'] == 2),
        'no_overlap_with_shell': _pf(None if ov is None else ov <= MAX_OVERLAP_MM3),
        'contact_with_shell': _pf(c.get('min_distance_mm') is not None and c['min_distance_mm'] <= MAX_CONTACT_GAP_MM),
        'not_beyond_shell_parting_outline': _pf(c.get('plan_protrusion_mm', {}).get('max', 1.0) <= MAX_PROTRUSION_MM),
        'top_edge_matches_shell_edge': _pf(c.get('top_edge_vs_shell_edge_mm', {}).get('max', 1.0) <= MAX_EDGE_DEV_MM),
        'floor_matches_base_outline': _pf(c.get('floor_vs_base_outline_mm', {}).get('hausdorff', 1.0) <= MAX_FLOOR_DEV_MM),
        'fairing_within_max_change': _pf(base['fairing']['change_mm'].get('max', 0.0) <= settings['max_change_mm'] + 1e-6),
        'side_profile_monotonic': _pf(c.get('side_profile', {}).get('rays', 0) > 0 and c['side_profile']['rays_non_monotonic_r_of_z'] == 0),
        'rulings_do_not_cross': _pf(bool(res['side'].get('monotonic'))),
        'shell_unchanged': _pf(res['shell_sha256_before'] == res['shell_sha256_after'] == shell_sha == shell_now == hashes['shell']),
    }
    blockers = [k for k, v in checks.items() if v != 'PASS']
    return {
        'schema': 'plate_side_report/1', 'job_id': job_id, 'status': 'NOT_READY' if blockers else 'READY', 'blocking_reasons': blockers,
        'warnings': res['warnings'], 'code_version': {'plate_side': PLATE_SIDE_VERSION, 'worker': res['worker'], 'package': __version__},
        'source': {'shell_relative_path': shell_rel, 'shell_sha256': hashes['shell'], 'outline_relative_path': outline_rel, 'outline_sha256': hashes['outline'],
                   'symmetry_report_relative_path': sym_rel, 'symmetry_report_sha256': hashes['symmetry']},
        'settings': settings, 'checks': checks,
        'limits_used': {'max_protrusion_mm': MAX_PROTRUSION_MM, 'max_overlap_mm3': MAX_OVERLAP_MM3, 'max_contact_gap_mm': MAX_CONTACT_GAP_MM,
                        'max_edge_dev_mm': MAX_EDGE_DEV_MM, 'max_floor_dev_mm': MAX_FLOOR_DEV_MM},
        'parting': res['parting'], 'outline_source': res['outline_source'], 'base_outline': base, 'side': res['side'], 'measurements': c,
        'shell_sha256': {'before': res['shell_sha256_before'], 'after': res['shell_sha256_after'], 'now': shell_now},
        'outputs': {k: {'file': v} for k, v in res['files'].items()},
        'downstream': {'note': 'assembly.step = shell (unchanged) + plate as two solids; bottom_plate.step alone for printing / Fusion. Faces of the plate: '
                               'floor (z = 0), parting (copy of the shell parting surface), side (one ruled B-spline).'},
        'limits': ['The base outline must be star-shaped about its centre (polar method); PLATE_SIDE_OUTLINE_NOT_STAR_SHAPED otherwise.',
                   'Crisp edges only: no fillets, chamfers, skates, sensor recess or cable notch are modelled.',
                   'Symmetrisation is coarse and per sector (pairs of n_sectors): sectors with real asymmetry are kept as given, never forced.',
                   'The side is straight along each ruling; the profile check samples radial rays, which are not along the rulings.'],
        'seconds': res.get('seconds'), 'timing_cumulative_s': res.get('timing_cumulative'), 'execution': {'completed': True},
    }


__all__ = ['plate_side', 'PLATE_SIDE_VERSION', 'DEFAULTS', 'REPORT']
