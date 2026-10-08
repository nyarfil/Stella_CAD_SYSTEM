"""Freeform surface quality measurement (G0/G1/G2, internal knots, curvature, zebra images).

Numbers come from OCCT surface derivatives; images are review aids only and never decide a verdict.
Profile thresholds are ASSUMED (no cited standard). Waviness is information only.
Orientation convention: normals follow the face orientation, so on a closed solid they point out of
the material. Curvature is signed against that normal: convex (material side bulges) is negative.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np


class SurfaceQualityError(RuntimeError):
    """Raised when analysis input or the rendering backend is unusable."""


PROFILES: dict[str, dict[str, Any]] = {
    'class_a': {'g0_mm': .005, 'g1_deg': .05, 'g2_relative': .05, 'crease_deg': 10., 'knot_level': 'c1'},
    'consumer_product': {'g0_mm': .01, 'g1_deg': .1, 'g2_relative': .10, 'crease_deg': 10., 'knot_level': 'c0'},
    'mechanical': {'g0_mm': .02, 'g1_deg': .5, 'g2_relative': None, 'crease_deg': 10., 'knot_level': None},
}
PROFILE_STATUS = 'ASSUMED: no cited standard; owner may override'
K_FLOOR = 1e-3          # 1/mm: curvatures below this (R > 1000 mm) never give large relative jumps
WAVINESS_NOISE = .05    # turning points must swing by this fraction of the line's curvature range
WAVINESS_ABS_FLOOR = 1e-6
WORST_N = 20
EDGE_END_FRACTION = .02
STEP_MM = .005          # physical step used for in-face tests and normal finite differences


def _name(enum) -> str:
    return str(enum).split('_')[-1]


def _vec(v):
    return np.array([v.X(), v.Y(), v.Z()])


def _load(shape_or_path):
    if isinstance(shape_or_path, (str, Path)):
        import cadquery as cq
        path = Path(shape_or_path)
        if not path.is_file():
            raise SurfaceQualityError(f'STEP file not found: {path}')
        return cq.importers.importStep(str(path)).val().wrapped
    wrapped = getattr(shape_or_path, 'wrapped', None)
    if wrapped is None and hasattr(shape_or_path, 'val'):
        wrapped = shape_or_path.val().wrapped
    if wrapped is None:
        raise SurfaceQualityError('expected a CadQuery shape/workplane or a STEP path')
    return wrapped


class _Ctx:
    """Oriented derivative evaluator and trim classifier for one face."""

    def __init__(self, face):
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.BRepLProp import BRepLProp_SLProps
        from OCP.BRepTopAdaptor import BRepTopAdaptor_FClass2d
        from OCP.TopAbs import TopAbs_REVERSED
        self.face = face
        self.ad = BRepAdaptor_Surface(face, True)
        self.sign = -1. if face.Orientation() == TopAbs_REVERSED else 1.
        self.props = BRepLProp_SLProps(self.ad, 2, 1e-9)
        self.cls = BRepTopAdaptor_FClass2d(face, 1e-7)
        self.bounds = (self.ad.FirstUParameter(), self.ad.LastUParameter(),
                       self.ad.FirstVParameter(), self.ad.LastVParameter())

    def inside(self, u, v) -> bool:
        from OCP.TopAbs import TopAbs_IN
        from OCP.gp import gp_Pnt2d
        return self.cls.Perform(gp_Pnt2d(u, v)) == TopAbs_IN

    def at(self, u, v):
        """(P, n, Du, Dv, Duu, Duv, Dvv) or None where the normal is singular."""
        p = self.props
        p.SetParameters(u, v)
        if not p.IsNormalDefined():
            return None
        du, dv = _vec(p.D1U()), _vec(p.D1V())
        n = np.cross(du, dv)
        length = np.linalg.norm(n)
        if length < 1e-12:
            return None
        return (_vec(p.Value()), self.sign * n / length, du, dv, _vec(p.D2U()), _vec(p.DUV()), _vec(p.D2V()))


def _fundamental(d):
    _, n, du, dv, duu, duv, dvv = d
    return du @ du, du @ dv, dv @ dv, duu @ n, duv @ n, dvv @ n


def _principal(d):
    e, f, g, l, m, nn = _fundamental(d)
    det = e * g - f * f
    if det < 1e-18:
        return None
    k = (l * nn - m * m) / det
    h = (e * nn - 2 * f * m + g * l) / (2 * det)
    s = math.sqrt(max(h * h - k, 0.))
    return h + s, h - s, h, k, math.sqrt(det)


def _normal_curvature(d, c) -> float:
    """Normal curvature along the 3D tangent direction c (II/I of the projected direction)."""
    e, f, g, l, m, nn = _fundamental(d)
    du, dv = d[2], d[3]
    sol = np.linalg.lstsq(np.array([[e, f], [f, g]]), np.array([c @ du, c @ dv]), rcond=None)[0]
    a, b = float(sol[0]), float(sol[1])
    den = a * a * e + 2 * a * b * f + b * b * g
    return (a * a * l + 2 * a * b * m + b * b * nn) / den if den > 1e-18 else 0.


def _uv_dir(d, c):
    e, f, g = d[2] @ d[2], d[2] @ d[3], d[3] @ d[3]
    sol = np.linalg.lstsq(np.array([[e, f], [f, g]]), np.array([c @ d[2], c @ d[3]]), rcond=None)[0]
    return float(sol[0]), float(sol[1])


def _extrema_count(values: np.ndarray, noise: float) -> int:
    """Turning points of a sampled curvature profile, ignoring swings below noise*range (zigzag filter)."""
    rng = float(values.max() - values.min())
    if len(values) < 5 or rng < WAVINESS_ABS_FLOOR:
        return 0
    thr = noise * rng
    count, direction, pivot = 0, 0, values[0]
    for x in values[1:]:
        if direction >= 0 and x > pivot:
            if direction < 0:
                count += 1
            pivot, direction = x, 1
        elif direction <= 0 and x < pivot:
            if direction > 0:
                count += 1
            pivot, direction = x, -1
        elif direction >= 0 and pivot - x >= thr:
            if direction > 0:
                count += 1
            pivot, direction = x, -1
        elif direction <= 0 and x - pivot >= thr:
            if direction < 0:
                count += 1
            pivot, direction = x, 1
    return count


def _knot_findings(adaptor, ctx_bounds) -> tuple[dict | None, list[dict], int]:
    """B-spline/Bezier description, interior-knot findings, count of findings outside the trimmed range."""
    from OCP.GeomAbs import GeomAbs_BezierSurface, GeomAbs_BSplineSurface
    kind = adaptor.GetType()
    if kind == GeomAbs_BSplineSurface:
        s = adaptor.BSpline()
    elif kind == GeomAbs_BezierSurface:
        s = adaptor.Bezier()
    else:
        return None, [], 0
    info: dict[str, Any] = {'u_degree': s.UDegree(), 'v_degree': s.VDegree(), 'u_poles': s.NbUPoles(),
                            'v_poles': s.NbVPoles(), 'rational': bool(s.IsURational() or s.IsVRational())}
    findings: list[dict] = []
    outside = 0
    if kind == GeomAbs_BSplineSurface:
        u0, u1, v0, v1 = ctx_bounds
        for axis, knots, mults, degree, lo, hi, periodic in (
                ('u', s.UKnots(), s.UMultiplicities(), s.UDegree(), u0, u1, s.IsUPeriodic()),
                ('v', s.VKnots(), s.VMultiplicities(), s.VDegree(), v0, v1, s.IsVPeriodic())):
            values = [knots.Value(i) for i in range(knots.Lower(), knots.Upper() + 1)]
            mult = [mults.Value(i) for i in range(mults.Lower(), mults.Upper() + 1)]
            info[f'{axis}_knots'] = [round(x, 9) for x in values]
            info[f'{axis}_multiplicities'] = mult
            span = max(hi - lo, 1e-12)
            for i, (k, m) in enumerate(zip(values, mult)):
                if not periodic and i in (0, len(values) - 1):
                    continue
                level = 'c0_crease' if m >= degree else ('c1_only' if degree >= 2 and m == degree - 1 else None)
                if level is None:
                    continue
                if not lo + 1e-9 * span < k < hi - 1e-9 * span:
                    outside += 1
                    continue
                findings.append({'direction': axis, 'knot': round(k, 9), 'multiplicity': m, 'degree': degree,
                                 'level': level})
    return info, findings, outside


def analyze_surface_quality(shape_or_step_path, profile: str = 'consumer_product', faces: list[int] | None = None,
                            samples: int = 24) -> dict:
    """Measure surface smoothness of a B-rep against a declared profile. `faces` restricts to face ids."""
    if profile not in PROFILES:
        raise SurfaceQualityError(f'unknown profile {profile!r}; choose from {sorted(PROFILES)}')
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape, TopTools_IndexedMapOfShape
    spec = PROFILES[profile]
    shape = _load(shape_or_step_path)
    face_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, face_map)
    wanted = set(faces) if faces else None
    ctxs: dict[int, _Ctx] = {}
    planes: list[int] = []
    face_records: list[dict] = []
    findings_all: list[dict] = []
    curved_ids: list[int] = []
    spline_ids: list[int] = []
    outside_total = 0
    for fid in range(1, face_map.Extent() + 1):
        ctx = _Ctx(TopoDS.Face_s(face_map.FindKey(fid)))
        ctxs[fid] = ctx
        if ctx.ad.GetType() == GeomAbs_Plane:
            planes.append(fid)
            continue
        curved_ids.append(fid)
    if not curved_ids:
        return {'surface_quality_status': 'NOT_APPLICABLE', 'profile': {'name': profile, **spec, 'status': PROFILE_STATUS},
                'reason': 'all faces are planar (faceted model); freeform smoothness is not defined',
                'counts': {'faces': face_map.Extent(), 'planar': len(planes), 'curved': 0}}
    for fid in curved_ids:
        if wanted is not None and fid not in wanted:
            continue
        ctx = ctxs[fid]
        info, knot_findings, outside = _knot_findings(ctx.ad, ctx.bounds)
        outside_total += outside
        if info is not None:
            spline_ids.append(fid)
        for finding in knot_findings:
            findings_all.append({'face': fid, **finding})
        rec = _sample_face(ctx, fid, samples)
        rec['surface'] = _name(ctx.ad.GetType())
        rec['spline'] = info
        rec['internal_knots'] = knot_findings
        rec['continuity'] = {'u': _name(ctx.ad.UContinuity()), 'v': _name(ctx.ad.VContinuity())}
        face_records.append(rec)

    edge_map = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, edge_map)
    counts = {'edges': edge_map.Extent(), 'seam_skipped': 0, 'degenerated_skipped': 0, 'nonmanifold_skipped': 0,
              'free_edges': 0, 'shared_edges': 0, 'planar_pair_edges': 0}
    edge_records: list[dict] = []
    for eid in range(1, edge_map.Extent() + 1):
        edge = TopoDS.Edge_s(edge_map.FindKey(eid))
        rec = _edge_pair(edge, [TopoDS.Face_s(x) for x in edge_map.FindFromIndex(eid)], eid, face_map, ctxs, wanted,
                         samples, spec, counts)
        if rec is not None:
            edge_records.append(rec)

    smooth = [r for r in edge_records if r['class'] == 'smooth']
    counts['shared_edges'] = len(edge_records)
    counts['crease'] = len(edge_records) - len(smooth)
    counts['smooth_assessed'] = len(smooth)
    counts['smooth_assessed_with_curved_face'] = sum(1 for r in smooth if not r['planar_pair'])

    def edge_check(key, thr, label):
        if thr is None:
            return {'status': 'UNVERIFIED', 'reason': f'{label} not assessed by profile {profile}'}
        if not smooth:
            return {'status': 'UNVERIFIED', 'reason': 'no smooth shared edges to assess', 'threshold': thr}
        vals = [r[key] for r in smooth if r[key] is not None]
        if not vals:
            return {'status': 'UNVERIFIED', 'reason': 'no resolvable samples', 'threshold': thr}
        worst = max(vals)
        return {'status': 'PASS' if worst <= thr else 'FAIL', 'threshold': thr, 'worst': worst,
                'assessed_edges': len(vals)}

    checks: dict[str, Any] = {
        'g0_smooth_edges': edge_check('g0_max_mm', spec['g0_mm'], 'G0'),
        'g1_smooth_edges': edge_check('g1_max_deg', spec['g1_deg'], 'G1'),
        'g2_smooth_edges': edge_check('g2_rel_max', spec['g2_relative'], 'G2'),
    }
    level = spec['knot_level']
    bad = [f for f in findings_all if level == 'c1' or (level == 'c0' and f['level'] == 'c0_crease')]
    if level is None:
        checks['internal_knots'] = {'status': 'UNVERIFIED', 'reason': f'not assessed by profile {profile}'}
    elif not spline_ids:
        checks['internal_knots'] = {'status': 'UNVERIFIED', 'reason': 'no B-spline/Bezier faces in scope'}
    else:
        checks['internal_knots'] = {'status': 'FAIL' if bad else 'PASS', 'rule': 'mult>=degree' if level == 'c0' else 'mult>=degree-1',
                                    'assessed_faces': len(spline_ids), 'findings': len(bad),
                                    'findings_all_levels': len(findings_all), 'ignored_outside_trim': outside_total}
    wav = [r['waviness_max'] for r in face_records if r.get('waviness_max') is not None]
    checks['waviness'] = {'status': 'INFO', 'reason': 'no cited threshold; reported only',
                          'max_extrema_per_line': max(wav) if wav else None,
                          'mean_of_face_means': float(np.mean([r['waviness_mean'] for r in face_records
                                                               if r.get('waviness_mean') is not None])) if wav else None}
    states = [c['status'] for c in checks.values() if c['status'] in ('PASS', 'FAIL')]
    overall = 'FAIL' if 'FAIL' in states else ('PASS' if states else 'UNVERIFIED')

    def top(rows, key, extra=()):
        ranked = sorted((r for r in rows if r.get(key) is not None), key=lambda r: -r[key])[:WORST_N]
        return ranked

    face_view = [{k: v for k, v in r.items() if k not in ('radius_min_samples',)} for r in face_records]
    return {
        'surface_quality_status': overall,
        'unassessed_checks': [k for k, c in checks.items() if c['status'] == 'UNVERIFIED'],
        'profile': {'name': profile, **spec, 'status': PROFILE_STATUS, 'k_floor_per_mm': K_FLOOR,
                    'waviness_noise': WAVINESS_NOISE},
        'conventions': 'normals follow face orientation (outward on a closed solid); convex curvature is negative; '
                       'open shells make convex/concave relative to the face normal',
        'checks': checks,
        'counts': {'faces': face_map.Extent(), 'planar': len(planes), 'curved': len(curved_ids),
                   'spline_faces': len(spline_ids), 'faces_analyzed': len(face_records), **counts},
        'worst_g0_edges': top(smooth, 'g0_max_mm'),
        'worst_g1_edges': top(smooth, 'g1_max_deg'),
        'worst_g2_edges': top(smooth, 'g2_rel_max'),
        'worst_zebra_phase_edges': top(smooth, 'zebra_phase_max_deg'),
        'worst_zebra_kink_edges': top(smooth, 'zebra_kink_max'),
        'internal_knot_findings': findings_all[:200],
        'worst_waviness_faces': top(face_records, 'waviness_max'),
        'smallest_radius_faces': sorted((r for r in face_records if r.get('radius_min_mm') is not None),
                                        key=lambda r: r['radius_min_mm'])[:WORST_N],
        'faces': face_view,
        'planar_face_ids': planes,
    }


def _sample_face(ctx: _Ctx, fid: int, samples: int) -> dict:
    u0, u1, v0, v1 = ctx.bounds
    n = max(int(samples), 4)
    rec: dict[str, Any] = {'id': fid, 'samples_inside': 0, 'samples_singular': 0}
    k1s, k2s, hs, ks, ws = [], [], [], [], []
    mid = None
    for i in range(n):
        u = u0 + (i + .5) / n * (u1 - u0)
        for j in range(n):
            v = v0 + (j + .5) / n * (v1 - v0)
            if not ctx.inside(u, v):
                continue
            d = ctx.at(u, v)
            pr = _principal(d) if d is not None else None
            if pr is None:
                rec['samples_singular'] += 1
                continue
            rec['samples_inside'] += 1
            if mid is None or (i == n // 2 and j == n // 2):
                mid = d[0]
            k1s.append(pr[0]); k2s.append(pr[1]); hs.append(pr[2]); ks.append(pr[3]); ws.append(pr[4])
    if mid is not None:
        rec['location'] = [round(float(x), 4) for x in mid]
    if k1s:
        k1, k2, h, k, w = map(np.array, (k1s, k2s, hs, ks, ws))
        convex = -float(k2.min())
        concave = float(k1.max())
        rec.update({'k_max': float(k1.max()), 'k_min': float(k2.min()), 'mean_h_range': [float(h.min()), float(h.max())],
                    'gauss_k_range': [float(k.min()), float(k.max())],
                    'min_convex_radius_mm': 1. / convex if convex > 1e-9 else None,
                    'min_concave_radius_mm': 1. / concave if concave > 1e-9 else None,
                    'saddle_area_fraction': float((w * (k < 0)).sum() / w.sum())})
        radii = [r for r in (rec['min_convex_radius_mm'], rec['min_concave_radius_mm']) if r]
        rec['radius_min_mm'] = min(radii) if radii else None
    lines = []
    for axis in (0, 1):
        for q in range(1, 7):
            frac = q / 7.
            fixed = (u0 + frac * (u1 - u0)) if axis == 0 else (v0 + frac * (v1 - v0))
            runs, run = [], []
            for t in np.linspace(0., 1., 2 * n + 1)[1:-1]:
                u, v = (fixed, v0 + t * (v1 - v0)) if axis == 0 else (u0 + t * (u1 - u0), fixed)
                d = ctx.at(u, v) if ctx.inside(u, v) else None
                if d is None:
                    if run:
                        runs.append(run)
                    run = []
                    continue
                e, f, g, l, m, nn = _fundamental(d)
                kk = (nn / g if g > 1e-18 else 0.) if axis == 0 else (l / e if e > 1e-18 else 0.)
                run.append(kk)
            if run:
                runs.append(run)
            runs = [r for r in runs if len(r) >= 5]
            if runs:
                lines.append(sum(_extrema_count(np.array(r), WAVINESS_NOISE) for r in runs))
    rec['waviness_lines'] = len(lines)
    rec['waviness_max'] = max(lines) if lines else None
    rec['waviness_mean'] = float(np.mean(lines)) if lines else None
    return rec


def _edge_pair(edge, adjacent, eid, face_map, ctxs, wanted, samples, spec, counts):
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Curve2d
    from OCP.GeomAbs import GeomAbs_Plane
    if BRep_Tool.Degenerated_s(edge):
        counts['degenerated_skipped'] += 1
        return None
    unique = []
    for f in adjacent:
        if not any(f.IsSame(x) for x in unique):
            unique.append(f)
    if len(unique) == 1:
        counts['seam_skipped' if len(adjacent) > 1 else 'free_edges'] += 1
        return None
    if len(unique) != 2:
        counts['nonmanifold_skipped'] += 1
        return None
    ids = [face_map.FindIndex(f) for f in unique]
    if wanted is not None and not (set(ids) & wanted):
        return None
    # Oriented copies from the ancestor list keep the orientation inside the parent shape.
    fa, fb = unique
    ca, cb = ctxs[ids[0]], ctxs[ids[1]]
    # contexts were built from the map key; rebuild with the ancestor orientation when it differs
    if fa.Orientation() != ca.face.Orientation():
        ca = _Ctx(fa)
    if fb.Orientation() != cb.face.Orientation():
        cb = _Ctx(fb)
    planar_pair = ca.ad.GetType() == GeomAbs_Plane and cb.ad.GetType() == GeomAbs_Plane
    if planar_pair:
        counts['planar_pair_edges'] += 1
    n = 3 if planar_pair else max(int(samples), 4)
    curve = BRepAdaptor_Curve(edge)
    t0, t1 = curve.FirstParameter(), curve.LastParameter()
    dense = np.linspace(t0, t1, 129)
    pts = np.array([_vec(curve.Value(t)) for t in dense])
    cum = np.concatenate([[0.], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    length = float(cum[-1])
    if length < 1e-9:
        counts['degenerated_skipped'] += 1
        return None
    params = np.interp(np.linspace(EDGE_END_FRACTION, 1 - EDGE_END_FRACTION, n) * length, cum, dense)
    pca, pcb = BRepAdaptor_Curve2d(edge, fa), BRepAdaptor_Curve2d(edge, fb)
    g0, g1, g2a, g2r, samples_ok = [], [], [], [], 0
    uvs = []
    for t in params:
        tan = _vec(curve.DN(t, 1))
        if np.linalg.norm(tan) < 1e-12:
            continue
        tan /= np.linalg.norm(tan)
        uva, uvb = pca.Value(t), pcb.Value(t)
        da, db = ca.at(uva.X(), uva.Y()), cb.at(uvb.X(), uvb.Y())
        if da is None or db is None:
            continue
        samples_ok += 1
        g0.append(float(np.linalg.norm(da[0] - db[0])))
        g1.append(math.degrees(math.acos(max(-1., min(1., float(da[1] @ db[1]))))))
        ka = _normal_curvature(da, np.cross(da[1], tan))
        kb = _normal_curvature(db, np.cross(db[1], tan))
        jump = abs(ka - kb)
        g2a.append(jump)
        g2r.append(jump / max(abs(ka), abs(kb), K_FLOOR))
        uvs.append((t, tan, (uva.X(), uva.Y()), (uvb.X(), uvb.Y())))
    mid = pts[len(pts) // 2]
    rec: dict[str, Any] = {'edge': eid, 'faces': ids, 'length_mm': length, 'planar_pair': planar_pair,
                           'location': [round(float(x), 4) for x in mid], 'samples': samples_ok}
    if not samples_ok:
        rec.update({'class': 'unresolved', 'g0_max_mm': None, 'g1_max_deg': None, 'g2_rel_max': None})
        return rec
    median_g1 = float(np.median(g1))
    rec.update({'g0_max_mm': max(g0), 'g1_max_deg': max(g1), 'g1_median_deg': median_g1,
                'g2_abs_max': max(g2a), 'g2_rel_max': max(g2r),
                'class': 'crease' if median_g1 > spec['crease_deg'] else 'smooth'})
    rec.setdefault('zebra_phase_max_deg', None)
    rec.setdefault('zebra_kink_max', None)
    if rec['class'] == 'smooth':
        _zebra_edge(rec, ca, cb, uvs)
    return rec


def _step_into(ctx: _Ctx, uv, d, c):
    """Return (sign, d_step) so that moving sign*c from uv stays inside the face; None when ambiguous."""
    a, b = _uv_dir(d, c)
    found = []
    for s in (1., -1.):
        u, v = uv[0] + s * STEP_MM * a, uv[1] + s * STEP_MM * b
        if ctx.inside(u, v):
            found.append((s, u, v))
    if len(found) != 1:
        return None
    s, u, v = found[0]
    ds = ctx.at(u, v)
    return None if ds is None else (s, ds)


LIGHT_DIRS = (np.array([1., 0., 0.]), np.array([0., 1., 0.]), np.array([0., 0., 1.]))


def _zebra_edge(rec, ca, cb, uvs):
    """Stripe-phase break (G1-type) and phase-derivative kink (G2-type) for three fixed light directions."""
    offsets, kinks = [], []
    for _, tan, uva, uvb in uvs:
        da, db = ca.at(*uva), cb.at(*uvb)
        if da is None or db is None:
            continue
        ia = _step_into(ca, uva, da, np.cross(da[1], tan))
        ib = _step_into(cb, uvb, db, np.cross(db[1], tan))
        for light in LIGHT_DIRS:
            sa = math.acos(max(-1., min(1., float(da[1] @ light))))
            sb = math.acos(max(-1., min(1., float(db[1] @ light))))
            offsets.append(math.degrees(abs(sa - sb)))
            if ia is None or ib is None or min(math.sin(sa), math.sin(sb)) < .05:
                continue
            slope = []
            for (s, dn), phase in ((ia, sa), (ib, sb)):
                step_phase = math.acos(max(-1., min(1., float(dn[1] @ light))))
                slope.append((step_phase - phase) / STEP_MM)
            kinks.append(abs(slope[0] + slope[1]))
    rec['zebra_phase_max_deg'] = max(offsets) if offsets else None
    rec['zebra_kink_max'] = max(kinks) if kinks else None
    rec['zebra_kink_unit'] = 'rad/mm'


# ---------------------------------------------------------------- images (review aids only)

VIEWS = {
    'top': ((0., 0., 1.), (0., 1., 0.)),
    'left': ((-1., 0., 0.), (0., 0., 1.)),
    'right': ((1., 0., 0.), (0., 0., 1.)),
    'front_iso': ((1., -1.2, .8), (0., 0., 1.)),
}


def _mesh(shape, deflection: float | None, curvature: bool):
    """Per-vertex positions, exact surface normals, triangles (and mean curvature) of a private copy."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.Bnd import Bnd_Box
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape
    copy = BRepBuilderAPI_Copy(shape).Shape()
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(copy, box, False, False)
    lo = box.Get()
    diag = math.dist(lo[:3], lo[3:])
    BRepMesh_IncrementalMesh(copy, deflection or max(.01, 2e-4 * diag), False, .15, True)
    fmap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(copy, TopAbs_FACE, fmap)
    pos, nrm, tri, curv = [], [], [], []
    base = 0
    for fid in range(1, fmap.Extent() + 1):
        face = TopoDS.Face_s(fmap.FindKey(fid))
        loc = TopLoc_Location()
        poly = BRep_Tool.Triangulation_s(face, loc)
        if poly is None:
            continue
        trsf = loc.Transformation()
        ctx = _Ctx(face)
        planar = ctx.ad.GetType() == GeomAbs_Plane
        n_nodes = poly.NbNodes()
        flat = None
        if planar:
            u, v = (ctx.bounds[0] + ctx.bounds[1]) / 2, (ctx.bounds[2] + ctx.bounds[3]) / 2
            d = ctx.at(u, v)
            flat = d[1] if d is not None else None
        for i in range(1, n_nodes + 1):
            p = poly.Node(i).Transformed(trsf)
            pos.append((p.X(), p.Y(), p.Z()))
            n, h = flat, 0.
            if not planar and poly.HasUVNodes():
                uv = poly.UVNode(i)
                d = ctx.at(uv.X(), uv.Y())
                if d is not None:
                    n = d[1]
                    if curvature:
                        pr = _principal(d)
                        h = pr[2] if pr else 0.
            nrm.append(tuple(n) if n is not None else (0., 0., 1.))
            curv.append(h)
        flip = face.Orientation() == TopAbs_REVERSED
        for i in range(1, poly.NbTriangles() + 1):
            a, b, c = poly.Triangle(i).Get()
            tri.append((base + a - 1, base + (c if flip else b) - 1, base + (b if flip else c) - 1))
        base += n_nodes
    if not tri:
        raise SurfaceQualityError('tessellation produced no triangles')
    return np.array(pos), np.array(nrm), np.array(tri), np.array(curv)


def _polydata(pos, tri, tcoords=None, scalars=None):
    import vtk
    from vtk.util import numpy_support as ns
    pts = vtk.vtkPoints()
    pts.SetData(ns.numpy_to_vtk(np.ascontiguousarray(pos, dtype=np.float64), deep=True))
    cells = vtk.vtkCellArray()
    conn = np.hstack([np.full((len(tri), 1), 3), tri]).astype(np.int64).ravel()
    cells.ImportLegacyFormat(ns.numpy_to_vtkIdTypeArray(conn, deep=True))
    poly = vtk.vtkPolyData()
    poly.SetPoints(pts)
    poly.SetPolys(cells)
    if tcoords is not None:
        poly.GetPointData().SetTCoords(ns.numpy_to_vtk(np.ascontiguousarray(tcoords, dtype=np.float32), deep=True))
    if scalars is not None:
        poly.GetPointData().SetScalars(ns.numpy_to_vtk(np.ascontiguousarray(scalars, dtype=np.float32), deep=True))
    return poly


def _render_views(builders, out_png, size):
    """builders: view name -> (polydata, texture|None, lut|None). Renders a 2x2 montage offscreen."""
    try:
        import vtk
        window = vtk.vtkRenderWindow()
        window.SetOffScreenRendering(1)
        window.SetSize(2 * size[0], 2 * size[1])
        window.SetMultiSamples(0)
        slots = [(0., .5, .5, 1.), (.5, .5, 1., 1.), (0., 0., .5, .5), (.5, 0., 1., .5)]
        for (name, (data, texture, lut, srange)), vp in zip(builders.items(), slots):
            direction, up = VIEWS[name]
            ren = vtk.vtkRenderer()
            ren.SetViewport(*vp)
            ren.SetBackground(.62, .70, .80)
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(data)
            if lut is not None:
                mapper.SetLookupTable(lut)
                mapper.SetScalarRange(*srange)
                mapper.InterpolateScalarsBeforeMappingOn()
            else:
                mapper.ScalarVisibilityOff()
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetLighting(False)
            if texture is not None:
                actor.SetTexture(texture)
            ren.AddActor(actor)
            bounds = data.GetBounds()
            centre = np.array([(bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2, (bounds[4] + bounds[5]) / 2])
            d = np.array(direction) / np.linalg.norm(direction)
            cam = ren.GetActiveCamera()
            cam.ParallelProjectionOn()
            cam.SetFocalPoint(*centre)
            cam.SetPosition(*(centre + d * 1000.))
            cam.SetViewUp(*up)
            ren.ResetCamera()
            window.AddRenderer(ren)
        window.Render()
        grab = vtk.vtkWindowToImageFilter()
        grab.SetInput(window)
        grab.Update()
        image = grab.GetOutput()
        if image.GetDimensions()[0] < 2 or image.GetPointData().GetScalars() is None:
            raise SurfaceQualityError('offscreen render returned an empty image')
        writer = vtk.vtkPNGWriter()
        Path(out_png).parent.mkdir(parents=True, exist_ok=True)
        writer.SetFileName(str(out_png))
        writer.SetInputData(image)
        writer.Write()
    except SurfaceQualityError:
        raise
    except Exception as exc:  # no silent skip: callers must know the image does not exist
        raise SurfaceQualityError(f'vtk offscreen rendering failed: {exc}') from exc
    if not Path(out_png).is_file() or Path(out_png).stat().st_size < 1000:
        raise SurfaceQualityError('vtk offscreen rendering wrote no usable PNG')
    return str(out_png)


def render_zebra(shape_or_step_path, out_png, stripes: int = 24, size=(800, 600), deflection: float | None = None) -> str:
    """Reflection-stripe image from exact normals (stripe = sin(freq*angle(reflect(view,n), up)) > 0). Review aid."""
    import vtk
    from vtk.util import numpy_support as ns
    pos, nrm, tri, _ = _mesh(_load(shape_or_step_path), deflection, False)
    tex_img = vtk.vtkImageData()
    tex_img.SetDimensions(2, 1, 1)
    arr = np.array([[255, 255, 255], [20, 20, 20]], dtype=np.uint8)
    tex_img.GetPointData().SetScalars(ns.numpy_to_vtk(arr, deep=True))
    texture = vtk.vtkTexture()
    texture.SetInputData(tex_img)
    texture.InterpolateOff()
    texture.RepeatOn()
    builders = {}
    for name, (direction, up) in VIEWS.items():
        view = -np.array(direction, dtype=float) / np.linalg.norm(direction)   # direction camera looks along
        axis = np.array(up, dtype=float) / np.linalg.norm(up)
        dots = nrm @ view
        refl = view - 2. * dots[:, None] * nrm
        theta = np.arccos(np.clip(refl @ axis, -1., 1.))
        tc = np.column_stack([theta * stripes / (2 * math.pi), np.full(len(theta), .5)])
        builders[name] = (_polydata(pos, tri, tcoords=tc), texture, None, None)
    return _render_views(builders, out_png, size)


def render_curvature(shape_or_step_path, out_png, clip_radius_mm: float = 2., size=(800, 600),
                     deflection: float | None = None) -> str:
    """Mean-curvature colour map clipped at +-1/clip_radius_mm (red convex, blue concave, white flat). Review aid."""
    import vtk
    pos, _, tri, curv = _mesh(_load(shape_or_step_path), deflection, True)
    limit = 1. / clip_radius_mm
    lut = vtk.vtkLookupTable()
    lut.SetNumberOfTableValues(256)
    for i in range(256):
        x = i / 255. * 2 - 1.      # -1 (concave, blue) .. +1 (convex, red)
        r, g, b = (1., 1. + x, 1. + x) if x > 0 else (1. + x, 1. + x, 1.)
        lut.SetTableValue(i, r, g, b, 1.)
    lut.SetRange(-limit, limit)
    lut.Build()
    scalars = np.clip(-curv, -limit, limit)      # outward-normal convention: convex curvature is negative
    data = _polydata(pos, tri, scalars=scalars)
    builders = {name: (data, None, lut, (-limit, limit)) for name in VIEWS}
    return _render_views(builders, out_png, size)
