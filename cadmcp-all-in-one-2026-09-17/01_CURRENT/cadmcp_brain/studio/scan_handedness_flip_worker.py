"""Handedness flip of a finished mouse (top shell + bottom plate + face roles). SUBPROCESS WORKER (server python with OCP, extra `geometry`).

Run as:  <server python> -I scan_handedness_flip_worker.py request.json      (result = last stdout line, JSON)

Method: the WHOLE model is mirrored about the mouse mirror plane n.x = d (given, never assumed) with one rigid map T = Tz . Tr . Tm:
  Tm = plane mirror; Tr = the smallest rigid rotation about the mirrored plate floor centroid that turns the best-fit plane of the mirrored floor face
  horizontal (a tilted mirror plane tips the floor; a rigid rotation keeps the shape and the symmetry); Tz = the shift that puts the floor at z = 0.
Nothing is re-designed: faces keep their order and roles (point / bbox are re-measured on the new STEP files), a mirrored solid with a negative volume is
reversed to a valid orientation, and all gates are measured on the STEP files that were written and read back (valid one solid, floor z = 0, volume
equal to the source, side-button flank swapped, face / role counts, face-to-face correspondence, colours read back, assembly contact).
"""
from __future__ import annotations
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from cadmcp_brain.studio.scan_cad_common import WorkerError, worker_main
from cadmcp_brain.studio import cad_brep_lib as L

WORKER_VERSION = 'scan_handedness_flip/1'
COLORS = {'panel': (0.95, 0.50, 0.10), 'sidebutton': (0.15, 0.65, 0.25), 'plate': (0.20, 0.40, 0.85), 'rest': (0.62, 0.63, 0.66)}
DEFAULTS = {'floor_tol_mm': 1e-3, 'volume_tol_pct': 0.1, 'front_direction': None, 'face_tol_mm': 1e-4}
BUTTON_ROLES = ('sidebutton', 'sidebutton_wall')
MAX_FLOOR_TILT_DEG = 25.0


def _pnt(p):
    from OCP.gp import gp_Pnt
    return gp_Pnt(*[float(x) for x in p])


def _tr(T, p) -> np.ndarray:
    return np.array(_pnt(p).Transformed(T).Coord())


def apply(shape, T):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    ss = L.solids(BRepBuilderAPI_Transform(shape, T, True).Shape())
    if len(ss) != 1:
        raise WorkerError('HANDEDNESS_FLIP_SOLIDS', 'The mirrored shape is not exactly one solid.', {'solids': len(ss)})
    s = ss[0]
    if L.volume(s) < 0:                                   # a mirror reverses the orientation: restore the outward-facing solid
        from OCP.TopoDS import TopoDS
        s = TopoDS.Solid_s(s.Reversed())
    return s


def bbox_list(f) -> list[float]:
    return [round(float(x), 2) for x in L.bbox(f)]


def area_acc(f) -> float:
    """Face area with an adaptive tolerance (the default integration is off by up to ~2 % on large trimmed B-spline faces)."""
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    g = GProp_GProps()
    BRepGProp.SurfaceProperties_s(f, g, 1e-6)
    return g.Mass()


def exact_zrange(s) -> list[float]:
    """z range of the exact geometry (no mesh enlargement, which L.bbox picks up once the shape was tessellated)."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    b = Bnd_Box()
    BRepBndLib.AddOptimal_s(s, b, False, False)
    g = b.Get()
    return [float(g[2]), float(g[5])]


def floor_plane(mirrored_plate, idx: int) -> tuple[np.ndarray, np.ndarray, float]:
    """Best-fit plane of the mirrored floor face -> (centroid, unit normal with n_z > 0, max |distance| of its mesh vertices)."""
    m = L.tessellate(mirrored_plate, 0.02, 0.2)
    sel = np.unique(m['T'][m['FID'] == idx].ravel())
    if len(sel) < 3:
        raise WorkerError('HANDEDNESS_FLIP_FLOOR', 'The plate floor face has no mesh.', {'face': idx})
    P = m['V'][sel]
    c = P.mean(0)
    n = np.linalg.svd(P - c)[2][-1]
    n = n if n[2] > 0 else -n
    return c, n, float(np.abs((P - c) @ n).max())


def run(req: dict[str, Any]) -> dict[str, Any]:
    L.require_ocp()
    from OCP.gp import gp_Trsf, gp_Ax1, gp_Ax2, gp_Dir, gp_Vec
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    prm = {**DEFAULTS, **(req.get('params') or {})}
    inp = req['inputs']
    out = Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    warnings: list[dict[str, Any]] = []
    shell0 = L.one_solid(Path(inp['shell']), 'HANDEDNESS_FLIP_SHELL_SOLIDS')
    plate0 = L.one_solid(Path(inp['plate']), 'HANDEDNESS_FLIP_PLATE_SOLIDS')
    roles = json.loads(Path(inp['roles']).read_text(encoding='utf-8'))
    srec, prec = roles.get('top_shell'), roles.get('bottom_plate')
    if not isinstance(srec, list) or not isinstance(prec, list):
        raise WorkerError('HANDEDNESS_FLIP_ROLES', 'face_roles.json needs "top_shell" and "bottom_plate" face lists (brain_mouse_face_roles with a plate).')
    colors = {**COLORS, **{k: tuple(v) for k, v in (prm.get('colors') or {}).items()}}
    mir = prm['mirror']
    n = np.array(mir['normal'], float)
    nn = float(np.linalg.norm(n))
    n = n / nn
    d = float(mir['d']) / nn
    p0 = n * d

    f_shell0, f_plate0 = L.faces(shell0), L.faces(plate0)
    if len(f_shell0) != len(srec) or len(f_plate0) != len(prec):
        raise WorkerError('HANDEDNESS_FLIP_ROLES_MISMATCH', 'face_roles.json does not match the STEP files (face counts differ).',
                          {'shell_faces': len(f_shell0), 'roles_shell': len(srec), 'plate_faces': len(f_plate0), 'roles_plate': len(prec)})
    floors = [r for r in prec if r.get('sub') == 'floor']
    if not floors:
        raise WorkerError('HANDEDNESS_FLIP_FLOOR', 'face_roles.json lists no plate face with sub "floor".')
    fidx = int(max(floors, key=lambda r: r.get('area', 0.0))['index'])

    # ---- transform
    Tm = gp_Trsf()
    Tm.SetMirror(gp_Ax2(_pnt(p0), gp_Dir(*[float(x) for x in n])))
    fc, fn, fdev = floor_plane(apply(plate0, Tm), fidx)
    tilt = math.degrees(math.acos(max(-1.0, min(1.0, float(fn[2])))))
    if tilt > MAX_FLOOR_TILT_DEG:
        raise WorkerError('HANDEDNESS_FLIP_FLOOR', 'The mirrored floor is tilted too far from horizontal; the mirror plane is not a lateral mouse plane.',
                          {'tilt_deg': tilt})
    ax = np.cross(fn, [0.0, 0.0, 1.0])
    s = float(np.linalg.norm(ax))
    Tr = gp_Trsf()
    if s > 1e-12:
        Tr.SetRotation(gp_Ax1(_pnt(fc), gp_Dir(*[float(x) for x in ax / s])), math.atan2(s, float(fn[2])))
    Tz = gp_Trsf()
    Tz.SetTranslation(gp_Vec(0.0, 0.0, -float(fc[2])))
    Rg = Tz.Multiplied(Tr)
    T = Rg.Multiplied(Tm)
    shell1, plate1 = apply(shell0, T), apply(plate0, T)
    L.write_step(shell1, out / 'top_shell.step')
    L.write_step(plate1, out / 'bottom_plate.step')
    shell2 = L.one_solid(out / 'top_shell.step', 'HANDEDNESS_FLIP_REREAD')
    plate2 = L.one_solid(out / 'bottom_plate.step', 'HANDEDNESS_FLIP_REREAD')
    L.write_step(L.compound([shell2, plate2]), out / 'assembly.step')
    asm = L.read_step(out / 'assembly.step')
    f_shell, f_plate = L.faces(shell2), L.faces(plate2)

    # ---- face roles carried over (index, role, sub, type, area, neighbours kept; point / bbox re-measured)
    def carry(recs, faces_):
        res = []
        for r, f in zip(recs, faces_):
            q = dict(r)
            p, _ = L.inner_point(f)
            q['point'] = [round(float(c), 4) for c in p] if p is not None else None
            q['bbox'] = bbox_list(f)
            res.append(q)
        return res

    nshell, nplate = carry(srec, f_shell), carry(prec, f_plate)
    # correspondence: every output face i must be the image of source face i (same area, image of the source point on it)
    dev, area_dev = 0.0, 0.0
    for recs, f0s, f1s in ((srec, f_shell0, f_shell), (prec, f_plate0, f_plate)):
        for r, a, b in zip(recs, f0s, f1s):
            aa = area_acc(a)
            area_dev = max(area_dev, abs(aa - area_acc(b)) / max(aa, 1e-9))
            if r.get('point') is None:
                continue
            dd = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(_pnt(_tr(T, r['point']))).Vertex(), b)
            dev = max(dev, dd.Value() if dd.IsDone() else 1e9)

    # ---- colours
    def pcol(r):
        return colors['panel'] if r['role'] == 'panel' else colors['sidebutton'] if r['role'] == 'sidebutton' else colors['rest']

    parts = [('top_shell', shell2, [tuple(pcol(r)) for r in nshell], tuple(colors['rest'])),
             ('bottom_plate', plate2, [tuple(colors['plate'])] * len(nplate), tuple(colors['plate']))]
    readback = L.write_colored_step(parts, out / 'assembly_colored.step')
    expected: dict[str, int] = {}
    for _, _, cols, _ in parts:
        for c in cols:
            k = '%.2f,%.2f,%.2f' % tuple(c)
            expected[k] = expected.get(k, 0) + 1
    rb = {k: v for k, v in readback.items() if k != 'none'}

    # ---- measurements
    v0 = {'top_shell': L.volume(shell0), 'bottom_plate': L.volume(plate0)}
    v1 = {'top_shell': L.volume(shell2), 'bottom_plate': L.volume(plate2)}
    vdiff = {k: abs(v1[k] - v0[k]) / v0[k] * 100.0 for k in v0}
    fm = L.tessellate(plate2, 0.02, 0.2)
    fv = fm['V'][np.unique(fm['T'][fm['FID'] == fidx].ravel())]
    floor_z = [float(fv[:, 2].min()), float(fv[:, 2].max())]
    pz = exact_zrange(plate2)
    # side-button flank: signed distance to the mirror plane (source plane vs its image under the rigid part of T)
    pi0, qi = _tr(Rg, p0), _tr(Rg, p0 + n)
    ni = qi - pi0
    fd = prm.get('front_direction') or [1.0, 0.0]
    fdv = np.array([fd[0], fd[1], 0.0]) / math.hypot(fd[0], fd[1])
    left = np.cross([0.0, 0.0, 1.0], fdv)
    lsign = 1.0 if float(n @ left) >= 0 else -1.0

    def flank(sv: float) -> str:
        return 'left' if sv * lsign > 0 else 'right'

    btn = [k for k, r in enumerate(srec) if r['role'] in BUTTON_ROLES and r.get('point') is not None]
    s_src = [float(n @ np.array(srec[k]['point']) - d) for k in btn]
    s_out = [float(ni @ (np.array(nshell[k]['point']) - pi0)) for k in btn]
    swapped = bool(btn) and all(abs(a) > 1e-6 and abs(b) > 1e-6 and a * b < 0 for a, b in zip(s_src, s_out))
    flank_src, flank_out = Counter(flank(a) for a in s_src), Counter(flank(b) for b in s_out)
    ov = dist0 = dist1 = None
    try:
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
        ov = float(sum(L.volume(x) for x in L.solids(BRepAlgoAPI_Common(shell2, plate2).Shape())))
        dist0 = float(BRepExtrema_DistShapeShape(shell0, plate0).Value())
        dist1 = float(BRepExtrema_DistShapeShape(shell2, plate2).Value())
    except Exception as exc:  # noqa: BLE001 - reported as UNVERIFIED
        ov = None
        warnings.append({'code': 'HANDEDNESS_FLIP_CONTACT_UNMEASURED', 'message': f'{type(exc).__name__}: {exc}'})
    c0, c1 = Counter(r['role'] for r in srec), Counter(r['role'] for r in nshell)
    ft = float(prm['floor_tol_mm'])

    def pf(ok):
        return 'UNVERIFIED' if ok is None else ('PASS' if ok else 'FAIL')

    checks = {
        'shell_valid_one_solid': pf(L.is_valid(shell2) and len(L.solids(shell2)) == 1 and v1['top_shell'] > 0),
        'plate_valid_one_solid': pf(L.is_valid(plate2) and len(L.solids(plate2)) == 1 and v1['bottom_plate'] > 0),
        'assembly_two_valid_solids': pf(L.is_valid(asm) and len(L.solids(asm)) == 2),
        'floor_at_z0': pf(max(abs(z) for z in floor_z) <= ft and abs(pz[0]) <= ft),
        'volume_equal_to_source': pf(max(vdiff.values()) <= float(prm['volume_tol_pct'])),
        'sidebutton_flank_swapped': pf(swapped if btn else None),
        'face_count_equal': pf(len(f_shell) == len(srec) and len(f_plate) == len(prec)),
        'role_counts_equal': pf(c0 == c1 and Counter(r.get('sub') for r in prec) == Counter(r.get('sub') for r in nplate)),
        'faces_correspond_to_source': pf(dev <= float(prm['face_tol_mm']) and area_dev <= 1e-6),
        'colours_read_back': pf(rb == expected),
        'assembly_contact_preserved': pf(None if ov is None else ov <= 1e-3 and abs(dist1 - dist0) <= 1e-4),
    }
    meas = {
        'transform': {'mirror_normal': [float(x) for x in n], 'mirror_d': d, 'floor_tilt_deg': tilt, 'floor_fit_max_dev_mm': fdev,
                      'rotation_axis': [float(x) for x in (ax / s if s > 1e-12 else [0, 0, 1])], 'dz_mm': -float(fc[2])},
        'volumes_mm3': {'source': v0, 'result': v1}, 'volume_rel_diff_pct': vdiff,
        'floor_z_range_mm': floor_z, 'plate_z_range_mm': pz,
        'sidebutton': {'faces': btn, 'signed_distance_source_mm': s_src, 'signed_distance_result_mm': s_out, 'source_flank': dict(flank_src),
                       'result_flank': dict(flank_out), 'front_direction': [float(fdv[0]), float(fdv[1])],
                       'inferred_source_handedness': None if not btn else ('right' if flank_src.most_common(1)[0][0] == 'left' else 'left')},
        'faces': {'top_shell': len(f_shell), 'bottom_plate': len(f_plate), 'max_point_to_face_mm': dev, 'max_area_rel_dev': area_dev},
        'role_counts': dict(c1), 'overlap_mm3': ov, 'min_distance_mm': {'source': dist0, 'result': dist1},
        'colour_counts': {'expected': expected, 'read_back': readback},
    }
    roles_doc = {'top_shell': nshell, 'bottom_plate': nplate, 'worker': WORKER_VERSION,
                 'note': 'Handedness flip: same face order and roles as the source face_roles.json; point / bbox re-measured on the mirrored STEP files. '
                         'index = TopExp_Explorer order of top_shell.step / bottom_plate.step; match faces by point / bbox in other CAD.',
                 'handedness_flip': meas['transform']}
    (out / 'face_roles.json').write_text(json.dumps(L.clean(roles_doc), indent=1), encoding='utf-8')
    (out / 'check_handedness_flip.json').write_text(json.dumps(L.clean({'checks': checks, 'measurements': meas, 'warnings': warnings}), indent=1),
                                                    encoding='utf-8')
    return L.clean({'checks': checks, 'measurements': meas, 'warnings': warnings,
                    'files': {'top_shell': 'top_shell.step', 'bottom_plate': 'bottom_plate.step', 'assembly': 'assembly.step',
                              'colored_step': 'assembly_colored.step', 'face_roles': 'face_roles.json', 'check': 'check_handedness_flip.json'}})


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
