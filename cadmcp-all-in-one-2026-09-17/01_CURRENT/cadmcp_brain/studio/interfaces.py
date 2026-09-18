"""Measured B-rep surfaces, not names inferred from a language annotation.

Face identifiers are local to one immutable evidence digest. They must never be
reused after rebuilding a part. Surface classification is NOT a claim of a
complete bearing, sliding fit, material strength or assembly feasibility.
"""
from __future__ import annotations
import math
import numpy as np


def extract_interfaces(shape):
    """Inspect analytic planar/cylindrical surfaces and their oriented normals."""
    items, unresolved = [], []
    for i, face in enumerate(shape.Faces()):
        fid = f'F{i}'
        kind = face.geomType()
        base = {'face_id': fid, 'surface_type': kind,
                'area_mm2': float(face.Area()),
                'center_mm': list(face.Center().toTuple()),
                'evidence_kind': 'OCCT_BRep_measurement'}
        if kind == 'PLANE':
            items.append({**base, 'port_kind': 'planar_surface',
                          'normal': list(face.normalAt().toTuple())})
        elif kind == 'CYLINDER':
            # normalAt() respects the TopoDS face orientation, unlike a bare
            # surface normal. The radial dot product distinguishes cavity walls
            # from the exterior of a solid shaft.
            surf = face._geomAdaptor(); cylinder = surf.Cylinder()
            u0, u1, v0, v1 = face._uvBounds()
            p = np.asarray(surf.Value((u0+u1)/2, (v0+v1)/2).Coord())
            origin = np.asarray(cylinder.Location().Coord())
            axis = np.asarray(cylinder.Axis().Direction().Coord())
            radial = p - origin - np.dot(p-origin, axis)*axis
            n = np.asarray(face.normalAt(tuple(float(x) for x in p)).toTuple())
            dot = float(np.dot(n, radial) / np.linalg.norm(radial))
            orientation = 'inner_cylinder' if dot < -.9 else ('outer_cylinder' if dot > .9 else 'unresolved_cylinder')
            items.append({**base, 'port_kind': orientation,
                          'axis_origin_mm': origin.tolist(), 'axis_direction': axis.tolist(),
                          'radius_mm': float(cylinder.Radius()),
                          'axial_parameter_range_mm': [float(v0), float(v1)],
                          'axial_span_mm': float(abs(v1-v0)),
                          'angular_span_rad': float(abs(u1-u0)),
                          'full_parameter_wrap': abs(abs(u1-u0)-2*math.pi) < 1e-6,
                          'normal_radial_dot': dot,
                          'through_bore': 'not_determined',
                          'fit_and_load_capacity': 'not_determined'})
        else:
            unresolved.append({'face_id': fid, 'surface_type': kind})
    def count(k): return sum(x['port_kind'] == k for x in items)
    return {'version': 1, 'ports': items, 'unclassified_faces': unresolved,
            'capabilities': {
                'has_cylindrical_cavity_surface': count('inner_cylinder') > 0,
                'has_cylindrical_outer_surface': count('outer_cylinder') > 0,
                'has_planar_surface': count('planar_surface') > 0,
            },
            'scope': 'Analytic surfaces in this B-rep only. No automatic mechanism-function, through-hole, fit, wear or strength certification.'}


def screen_interfaces(geometry, required_features):
    """Reject only explicitly required measured features, not general semantics."""
    allowed = {'has_cylindrical_cavity_surface', 'has_cylindrical_outer_surface', 'has_planar_surface'}
    if any(k not in allowed for k in required_features):
        from ..errors import BrainError
        raise BrainError('STRUCTURE_FEATURE', 'Unsupported feature predicate; do not reinterpret it as another feature.')
    info = (geometry or {}).get('interfaces', {})
    known = info.get('capabilities', {})
    results = [{'feature': key,
                'verdict': 'unknown' if key not in known else ('pass' if known[key] else 'fail'),
                'basis': 'measured analytic B-rep surface; not source annotation'}
               for key in required_features]
    status = 'fail' if any(r['verdict'] == 'fail' for r in results) else ('unknown' if any(r['verdict'] == 'unknown' for r in results) else 'pass')
    return {'verdict': status, 'checks': results, 'scope': 'Feature preconditions only, not overall design acceptance.'}
