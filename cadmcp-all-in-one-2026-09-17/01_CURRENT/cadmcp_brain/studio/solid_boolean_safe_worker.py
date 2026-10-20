"""Gated Boolean of two solids (brain_solid_boolean_safe). SUBPROCESS WORKER (server python: OCP) and an IMPORTABLE library for other workers:

    from cadmcp_brain.studio.solid_boolean_safe_worker import safe_boolean, gate_boolean
    out = safe_boolean(a, b, 'fuse', tol_mm=0.01)      # -> {'status', 'shape', 'attempts', 'gate', ...}; out['shape'] is None unless status is PASS / UNVERIFIED
    g = gate_boolean(a, b, 'cut', result, expected_mm3=..., va=..., vb=...)   # the gate alone, for a result you made yourself

Run as:  <server python> -I solid_boolean_safe_worker.py request.json      (result = last stdout line, JSON)

A plain BRepAlgoAPI Boolean can return None, an empty compound, a no-op (the input again), unmerged near-touching parts or sliver solids without any error
(coincident / near-coincident faces, edge tolerances up to 0.05 mm: the LH2 build, docs/SCAN_TO_HOLLOW_SHELL_PIPELINE_JA_SPEC.md section 8.1). So every
attempt is gated and the first attempt that passes is kept. Attempts: plain, then BRepAlgoAPI fuzzy values tol_mm x (1.0, 0.7, 0.5, 1.5).
Gate of one result:
  non_null / non_empty   a result without solids is rejected, unless the expected volume is itself ~0 (a cut that removes everything)
  solid_count            == expect_solids (None: any count >= 1)
  valid                  BRepCheck on every solid (an invalid result is first offered to ShapeFix once)
  volume                 closed-mesh volume of the result vs the bookkeeping: fuse a + b - common, cut a - common, common a + b - fuse (the other Boolean
                         is computed with its own gated ladder); tolerance min(volume_tol_mm3, volume_tol_rel x max(a, b)); a result equal to input a or b
                         while the bookkeeping says otherwise is reported as no_op; no bookkeeping partner -> UNVERIFIED, never PASS
  points                 N random points (half uniform in the bbox, half within near_surface_mm of the input surfaces): inside(result) must equal
                         inside(a) op inside(b); bad <= max(2, N / 500); points ON a surface are skipped and counted
Volumes are CLOSED-MESH volumes (BRepGProp on these B-spline solids moves by ~100 mm3 between methods, automation/NOTES.md of the LH2 build).
"""
from __future__ import annotations
import sys
import time
from pathlib import Path
from typing import Any

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from cadmcp_brain.studio.scan_cad_common import WorkerError, worker_main
from cadmcp_brain.studio import cad_brep_lib as L

WORKER_VERSION = 'solid_boolean_safe/1'
OPS = ('fuse', 'cut', 'common')
OTHER = {'fuse': 'common', 'cut': 'common', 'common': 'fuse'}
DEFAULTS = {'tol_mm': 0.01, 'fuzzy_multiples': (1.0, 0.7, 0.5, 1.5), 'include_plain': True, 'volume_tol_mm3': 10.0, 'volume_tol_rel': 0.001,
            'points': 2000, 'near_surface_mm': 0.5, 'seed': 0, 'expect_solids': 1, 'unify': True, 'shapefix': 'if_invalid', 'mesh_deflection_mm': 0.02,
            'class_tol_mm': 1e-6}


# ---------------------------------------------------------------- primitives
def run_op(a, b, op: str, fuzzy: float = 0.0):
    """One BRepAlgoAPI Boolean (inputs are not modified: non-destructive). -> shape or None (never raises on an OCC failure)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse, BRepAlgoAPI_Cut, BRepAlgoAPI_Common
    from OCP.TopTools import TopTools_ListOfShape
    o = {'fuse': BRepAlgoAPI_Fuse, 'cut': BRepAlgoAPI_Cut, 'common': BRepAlgoAPI_Common}[op]()
    args, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
    args.Append(a)
    tools.Append(b)
    o.SetArguments(args)
    o.SetTools(tools)
    o.SetRunParallel(True)
    o.SetNonDestructive(True)
    if fuzzy > 0:
        o.SetFuzzyValue(float(fuzzy))
    try:
        o.Build()
        if not o.IsDone():
            return None
        s = o.Shape()
        return None if s.IsNull() else s
    except Exception:  # noqa: BLE001 - OCC raises Standard_Failure for some inputs; the caller sees None and the attempt log
        return None


def mesh_volume(shape, defl: float) -> float:
    """Volume of the closed tessellation (mm3), summed over solids; 0 for a shape without solids."""
    tot = 0.0
    for s in L.solids(shape):
        m = L.tessellate(s, defl, 0.3)
        V, T = m['V'], m['T']
        tot += abs(float(np.einsum('ij,ij->i', V[T[:, 0]], np.cross(V[T[:, 1]], V[T[:, 2]])).sum() / 6.0))
    return tot


class Inside:
    """Point-in-solid classifier of a shape (any of its solids): +1 inside, 0 outside, -1 on the surface."""

    def __init__(self, shape, tol: float):
        from OCP.BRepClass3d import BRepClass3d_SolidClassifier
        self.tol, self.cl = tol, []
        for s in (L.solids(shape) if shape is not None else []):
            c = BRepClass3d_SolidClassifier()
            c.Load(s)
            self.cl.append(c)

    def __call__(self, p) -> int:
        from OCP.gp import gp_Pnt
        from OCP.TopAbs import TopAbs_IN, TopAbs_ON
        q, on = gp_Pnt(float(p[0]), float(p[1]), float(p[2])), False
        for c in self.cl:
            c.Perform(q, self.tol)
            st = c.State()
            if st == TopAbs_IN:
                return 1
            on = on or st == TopAbs_ON
        return -1 if on else 0


def _bbox(shape):
    return np.array(L.bbox(shape, optimal=False), float)


def sample_points(a, b, op: str, n: int, near: float, seed: int, defl: float) -> np.ndarray:
    ba, bb = _bbox(a), _bbox(b)
    lo, hi = (np.minimum(ba[:3], bb[:3]), np.maximum(ba[3:], bb[3:])) if op == 'fuse' else \
        (ba[:3], ba[3:]) if op == 'cut' else (np.maximum(ba[:3], bb[:3]), np.minimum(ba[3:], bb[3:]))
    if np.any(hi <= lo):
        return np.zeros((0, 3))
    rng = np.random.default_rng(seed)
    uni = rng.uniform(lo, hi, size=(n // 2, 3))
    verts = np.vstack([L.tessellate(s, max(defl, 0.05), 0.5)['V'] for s in (a, b)])
    pick = verts[rng.integers(0, len(verts), size=n - n // 2)] + rng.uniform(-near, near, size=(n - n // 2, 3))
    pts = np.vstack([uni, pick])
    return pts[np.all(pts >= lo - near, axis=1) & np.all(pts <= hi + near, axis=1)]


def point_test(a, b, op: str, result, prm: dict[str, Any], n: int | None = None) -> dict[str, Any]:
    n = int(n or prm['points'])
    pts = sample_points(a, b, op, n, prm['near_surface_mm'], prm['seed'], prm['mesh_deflection_mm'])
    ia, ib, ir = Inside(a, prm['class_tol_mm']), Inside(b, prm['class_tol_mm']), Inside(result, prm['class_tol_mm'])
    bad = skipped = used = 0
    first_bad: list[list[float]] = []
    for p in pts:
        sa, sb, sr = ia(p), ib(p), ir(p)
        if -1 in (sa, sb, sr):
            skipped += 1
            continue
        want = (sa and sb) if op == 'common' else (sa or sb) if op == 'fuse' else (sa and not sb)
        used += 1
        if bool(want) != bool(sr):
            bad += 1
            if len(first_bad) < 5:
                first_bad.append([round(float(x), 3) for x in p])
    allowed = max(2, used // 500)
    return {'requested': n, 'used': used, 'skipped_on_surface': skipped, 'bad': bad, 'allowed': allowed, 'bad_points_sample': first_bad,
            'result': 'PASS' if bad <= allowed and used > 0 else ('UNVERIFIED' if used == 0 else 'FAIL')}


def vol_tol(va: float, vb: float, prm: dict[str, Any]) -> float:
    return min(prm['volume_tol_mm3'], prm['volume_tol_rel'] * max(va, vb, 1e-9))


def expected_volume(op: str, va: float, vb: float, vother: float | None) -> float | None:
    if vother is None:
        return None
    return {'fuse': va + vb - vother, 'cut': va - vother, 'common': va + vb - vother}[op]


# ---------------------------------------------------------------- gate
def gate_boolean(a, b, op: str, result, *, va: float, vb: float, expected_mm3: float | None, params: dict[str, Any] | None = None,
                 points: int | None = None) -> dict[str, Any]:
    """Gate of ONE Boolean result (see module docstring). -> {'status': PASS|FAIL|UNVERIFIED, 'checks': {...}, 'measured_mm3', 'expected_mm3', ...}."""
    prm = {**DEFAULTS, **(params or {})}
    ss = L.solids(result) if result is not None else []
    tol = vol_tol(va, vb, prm)
    chk: dict[str, str] = {}
    info: dict[str, Any] = {'solids': len(ss), 'tol_mm3': tol, 'expected_mm3': expected_mm3}
    chk['non_null'] = 'PASS' if result is not None else 'FAIL'
    measured = mesh_volume(result, prm['mesh_deflection_mm']) if ss else 0.0
    info['measured_mm3'] = measured
    expect_empty = (expected_mm3 is not None and expected_mm3 <= tol) or bool(prm.get('partner'))      # the partner Boolean (e.g. common of two disjoint solids) may be empty: the points decide
    chk['non_empty'] = 'PASS' if ss else ('PASS' if expect_empty and result is not None else 'FAIL')
    es = prm['expect_solids']
    chk['solid_count'] = 'PASS' if (es is None and (ss or expect_empty)) or (es is not None and len(ss) == es) or (not ss and expect_empty) else 'FAIL'
    chk['valid'] = 'PASS' if all(L.is_valid(s) for s in ss) else 'FAIL'
    if expected_mm3 is None:
        chk['volume'] = 'SKIPPED' if prm.get('partner') else 'UNVERIFIED'
    else:
        chk['volume'] = 'PASS' if abs(measured - expected_mm3) <= tol else 'FAIL'
        if chk['volume'] == 'FAIL':
            for nm, v in (('a', va), ('b', vb)):
                if abs(measured - v) <= tol and abs(expected_mm3 - v) > tol:
                    info['no_op'] = f'the result equals input {nm} but the bookkeeping expects {expected_mm3:.3f} mm3'
    if result is None:
        pt = {'result': 'FAIL', 'note': 'no result'}
    elif 'FAIL' in chk.values():                       # the point test is the expensive gate (a classifier call per point): a result that already failed is not tested further
        pt = {'result': 'SKIPPED', 'note': 'another gate already failed'}
    else:
        pt = point_test(a, b, op, result, prm, points)
    chk['points'], info['points'] = pt['result'], pt
    status = 'FAIL' if 'FAIL' in chk.values() else 'UNVERIFIED' if 'UNVERIFIED' in chk.values() else 'PASS'
    return {'status': status, 'checks': chk, **info}


# ---------------------------------------------------------------- repair / clean
def shapefix(shape, tol: float):
    from OCP.ShapeFix import ShapeFix_Shape
    f = ShapeFix_Shape(shape)
    f.SetPrecision(tol)
    f.SetMaxTolerance(max(tol * 5, 0.05))
    f.Perform()
    return f.Shape()


def unify(shape, tol: float):
    """removeSplitter equivalent: merge faces / edges on the same surface (and concatenate B-splines)."""
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    u = ShapeUpgrade_UnifySameDomain(shape, True, True, True)
    u.SetLinearTolerance(tol)
    u.Build()
    return u.Shape()


def _ladder(a, b, op: str, prm: dict[str, Any], va: float, vb: float, expected: float | None, label: str) -> dict[str, Any]:
    """Run the attempts for one op until one passes. -> {'status', 'shape', 'gate', 'attempts'}; shape is the best candidate for PASS / UNVERIFIED."""
    steps = ([('plain', 0.0)] if prm['include_plain'] else []) + [(f'fuzzy x{m:g} ({m * prm["tol_mm"]:.4g} mm)', m * prm['tol_mm']) for m in prm['fuzzy_multiples']]
    attempts, fallback = [], None
    for name, fz in steps:
        t0 = time.time()
        res = run_op(a, b, op, fz)
        row: dict[str, Any] = {'op': label, 'step': name, 'fuzzy_mm': fz, 'null': res is None}
        if res is not None and prm['shapefix'] != 'never' and not all(L.is_valid(s) for s in L.solids(res)) and L.solids(res):
            fixed = shapefix(res, prm['tol_mm'])
            row['shapefix_applied'] = True
            res = fixed
        g = gate_boolean(a, b, op, res, va=va, vb=vb, expected_mm3=expected, params=prm)
        row.update({'status': g['status'], 'checks': g['checks'], 'solids': g['solids'], 'measured_mm3': g['measured_mm3'], 'points_bad': g['points'].get('bad'),
                    'no_op': g.get('no_op'), 'seconds': round(time.time() - t0, 1)})
        attempts.append(row)
        if g['status'] == 'PASS':
            return {'status': 'PASS', 'shape': res, 'gate': g, 'attempts': attempts}
        if g['status'] == 'UNVERIFIED' and res is not None:
            if expected is None:                       # no bookkeeping partner: nothing better can come from further attempts' volume, keep the first clean one
                return {'status': 'UNVERIFIED', 'shape': res, 'gate': g, 'attempts': attempts}
            fallback = fallback or (res, g)
    if fallback is not None:
        return {'status': 'UNVERIFIED', 'shape': fallback[0], 'gate': fallback[1], 'attempts': attempts}
    return {'status': 'FAIL', 'shape': None, 'gate': attempts[-1] if attempts else None, 'attempts': attempts}


# ---------------------------------------------------------------- main API
def safe_boolean(a, b, op: str, **kw) -> dict[str, Any]:
    """Gated fuse / cut / common of two solids; keyword arguments = DEFAULTS (tol_mm, fuzzy_multiples, include_plain, volume_tol_mm3, volume_tol_rel,
    points, near_surface_mm, seed, expect_solids, unify, shapefix, mesh_deflection_mm, class_tol_mm)."""
    L.require_ocp()
    if op not in OPS:
        raise WorkerError('BOOL_OP', 'op must be fuse, cut or common.', {'given': op})
    prm = {**DEFAULTS, **kw}
    va, vb = mesh_volume(a, prm['mesh_deflection_mm']), mesh_volume(b, prm['mesh_deflection_mm'])
    if va <= 0 or vb <= 0:
        raise WorkerError('BOOL_INPUT_VOLUME', 'Both inputs must be solids with a positive volume.', {'volume_a': va, 'volume_b': vb})
    attempts: list[dict[str, Any]] = []
    # bookkeeping partner: the other Boolean, gated without a volume expectation (points + validity only)
    other_prm = {**prm, 'expect_solids': None, 'partner': True}
    oth = _ladder(a, b, OTHER[op], other_prm, va, vb, None, OTHER[op])
    attempts += oth['attempts']
    vother = oth['gate']['measured_mm3'] if oth['status'] in ('PASS', 'UNVERIFIED') else None
    exp = expected_volume(op, va, vb, vother)
    main = _ladder(a, b, op, prm, va, vb, exp, op)
    attempts += main['attempts']
    out: dict[str, Any] = {'status': main['status'], 'shape': main['shape'], 'attempts': attempts, 'gate': main['gate'], 'va_mm3': va, 'vb_mm3': vb,
                           'bookkeeping': {'partner_op': OTHER[op], 'partner_status': oth['status'], 'partner_mm3': vother, 'expected_mm3': exp},
                           'faces_before_clean': None, 'faces_after_clean': None, 'clean': []}
    if main['shape'] is None:
        return out
    shape, tol = main['shape'], prm['tol_mm']
    out['faces_before_clean'] = len(L.faces(shape))
    cleaners = ([('unify', lambda s: unify(s, tol))] if prm['unify'] else []) + ([('shapefix', lambda s: shapefix(s, tol))] if prm['shapefix'] == 'always' else [])
    base_vol = main['gate']['measured_mm3']
    for nm, fn in cleaners:
        try:
            cand = fn(shape)
        except Exception as exc:  # noqa: BLE001 - a failed clean keeps the gated result
            out['clean'].append({'step': nm, 'accepted': False, 'reason': f'{type(exc).__name__}: {exc}'})
            continue
        g = gate_boolean(a, b, op, cand, va=va, vb=vb, expected_mm3=base_vol, params={**prm, 'expect_solids': len(L.solids(shape))},
                         points=max(200, prm['points'] // 4))
        ok = g['status'] == 'PASS'
        out['clean'].append({'step': nm, 'accepted': ok, 'faces_before': len(L.faces(shape)), 'faces_after': len(L.faces(cand)), 'checks': g['checks'],
                             'measured_mm3': g['measured_mm3']})
        if ok:
            shape = cand
    out['shape'] = shape
    out['faces_after_clean'] = len(L.faces(shape))
    out['solids'] = len(L.solids(shape))
    return out


# ---------------------------------------------------------------- worker
def _load(path: Path, part: str | None, what: str):
    from cadmcp_brain.studio import mouse_parts_lib as P
    parts, _ = P.load_parts([str(path)])
    if part is None:
        if len(parts) != 1:
            raise WorkerError('BOOL_PART_AMBIGUOUS', f'{what} STEP holds several parts: name one.', {'parts': sorted(parts)})
        part = next(iter(parts))
    P.require(parts, [part], what)
    ss = L.solids(parts[part])
    if len(ss) != 1:
        raise WorkerError('BOOL_NOT_ONE_SOLID', f'{what} part must be exactly one solid.', {'part': part, 'solids': len(ss)})
    return ss[0], part


def run(req: dict[str, Any]) -> dict[str, Any]:
    t0 = time.time()
    L.require_ocp()
    inp, prm, out = req['inputs'], req['params'], Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    a, na = _load(Path(inp['a']), prm.get('part_a'), 'a')
    b, nb = _load(Path(inp['b']), prm.get('part_b'), 'b')
    kw = {k: prm[k] for k in DEFAULTS if k in prm}
    r = safe_boolean(a, b, prm['op'], **kw)
    files = {}
    if r['shape'] is not None and r['status'] in ('PASS', 'UNVERIFIED'):
        ss = L.solids(r['shape'])
        L.write_step(ss[0] if len(ss) == 1 else L.compound(ss), out / 'result.step')
        back = L.solids(L.read_step(out / 'result.step'))
        rb = {'solids': len(back), 'valid': all(L.is_valid(s) for s in back), 'mesh_volume_mm3': mesh_volume(L.compound(back), kw.get('mesh_deflection_mm', DEFAULTS['mesh_deflection_mm']))}
        r['round_trip'] = rb
        if rb['solids'] != len(ss) or not rb['valid'] or abs(rb['mesh_volume_mm3'] - r['gate']['measured_mm3']) > r['gate']['tol_mm3'] + 1e-9:
            r['status'] = 'FAIL'
            r['round_trip']['reason'] = 'The written STEP does not read back as the gated result.'
        else:
            files['result.step'] = 'result.step'
    return {'files': files, 'status_worker': r['status'], 'part_a': na, 'part_b': nb, 'op': prm['op'], 'result': {k: v for k, v in r.items() if k != 'shape'},
            'seconds': round(time.time() - t0, 1), 'worker_version': WORKER_VERSION}


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
