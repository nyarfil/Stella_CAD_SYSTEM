"""Sample inward surface-normal chords; these are not minimum wall thickness."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from inspect_stl import RECORD
from measure_click_chords import measure


def ray_hits(tri, origin, direction):
    a = tri[:, 0]
    e1, e2 = tri[:, 1]-a, tri[:, 2]-a
    h = np.cross(np.broadcast_to(direction, e2.shape), e2)
    det = np.einsum('ij,ij->i', e1, h)
    valid = np.abs(det) > 1e-10
    inv = np.zeros_like(det)
    inv[valid] = 1/det[valid]
    s = origin-a
    u = inv*np.einsum('ij,ij->i', s, h)
    q = np.cross(s, e1)
    v = inv*(q@direction)
    t = inv*np.einsum('ij,ij->i', e2, q)
    valid &= (u >= -1e-8) & (v >= -1e-8) & (u+v <= 1+1e-8)
    return [(float(t[i]), int(i), float(min(u[i], v[i], 1-u[i]-v[i])))
            for i in np.flatnonzero(valid)]


def analyze(source, pose):
    base = measure(source, pose)  # Reuse exact source/pose binding and transform checks.
    raw = source.read_bytes()
    tri = np.frombuffer(raw, dtype=RECORD, offset=84)['vertices'].astype(float)
    tri = tri@np.asarray(pose['rotation']).T + np.asarray(pose['translation'])
    cross = np.cross(tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0])
    lengths = np.linalg.norm(cross, axis=1)
    normals = np.divide(cross, lengths[:, None], out=np.zeros_like(cross), where=lengths[:, None]>1e-12)
    result = []
    above = float(tri[:, :, 2].max()+10)
    for probe in base['samples']:
        item = {'x':probe['x'], 'y':probe['y']}
        vertical = sorted(ray_hits(tri, np.array([probe['x'],probe['y'],above]), np.array([0.,0.,-1.])))
        if not vertical:
            item['status'] = 'no_top_hit'
            result.append(item)
            continue
        first = vertical[0][0]
        group = [h for h in vertical if abs(h[0]-first) <= 1e-5]
        idx = group[0][1]
        n = normals[idx].copy()
        item['top_triangle_indices'] = [h[1] for h in group]
        item['top_min_barycentric'] = min(h[2] for h in group)
        item['top_winding_normal'] = n.tolist()
        n *= 1 if n[2] >= 0 else -1
        point = np.array([probe['x'],probe['y'],above-first])
        item['top_point'] = point.tolist()
        item['inward_direction'] = (-n).tolist()
        # Coincident facets must agree geometrically before selecting a direction.
        compatible = all(abs(float(normals[h[1]]@n)) > 0.99999 for h in group)
        if not compatible or n[2] <= 1e-8:
            item['status'] = 'ambiguous_top_normal'
            result.append(item)
            continue
        exits = sorted(h for h in ray_hits(tri, point, -n) if h[0] > 1e-5)
        if not exits:
            item['status'] = 'no_exit'
            result.append(item)
            continue
        distance = exits[0][0]
        eg = [h for h in exits if abs(h[0]-distance) <= 1e-5]
        parallel = min(abs(float(normals[h[1]]@n)) for h in eg)
        signed = [float(normals[h[1]]@normals[idx]) for h in eg]
        edge = min(h[2] for h in group+eg) <= 1e-7
        item.update({'normal_direction_chord':distance, 'exit_point':(point-distance*n).tolist(),
                     'exit_triangle_indices':[h[1] for h in eg],
                     'exit_min_barycentric':min(h[2] for h in eg),
                     'exit_winding_normals':[normals[h[1]].tolist() for h in eg],
                     'opposing_surface_abs_normal_dot':parallel,
                     'top_exit_signed_winding_normal_dots':signed,
                     'edge_or_vertex_hit':edge,
                     'status':'edge_or_vertex_candidate' if edge else
                              'inconsistent_opposing_winding' if any(dot >= 0 for dot in signed) else
                              'locally_parallel_surface_candidate' if max(signed) <= -np.cos(np.deg2rad(10)) else
                              'nonparallel_feature_crossing'})
        result.append(item)
    return {'schema_version':1,'status':'reference_normal_direction_chords_not_minimum_thickness',
            'source_file':source.name,'source_sha256':base['source_sha256'],
            'measurement_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'dependency_script_sha256':hashlib.sha256(Path(__file__).with_name('measure_click_chords.py').read_bytes()).hexdigest(),
            'units':base['units'],'rotation':base['rotation'],'translation':base['translation'],
            'method':'Highest vertical intersection; derive facet normal from vertex cross product, orient upward geometrically, cast inward and retain first positive intersection beyond 1e-5. Coincident intersections grouped within 1e-5. Locally opposing parallel candidate requires raw top/exit winding normal dot <= -cos(10 degrees); this is not a manufacturing tolerance.',
            'assumptions':base['assumptions']+['Geometric upward orientation does not establish globally consistent mesh winding or solid validity.'],
            'not_verified':['global or minimum wall thickness','solid validity and self-intersections','functional region identity','hinge or flexure location','force, return, travel or fatigue','physical fit and STL physical units'],
            'degenerate_triangle_count':int((lengths<=1e-12).sum()),'samples':result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source','pose','report'):
        parser.add_argument(name,type=Path)
    args = parser.parse_args()
    source, output = args.source.resolve(strict=True), args.report.resolve()
    root = source.parent.parent if source.parent.name.lower() == 'solid' else source.parent
    if output == args.pose.resolve() or output == root or root in output.parents:
        parser.error('Output must be outside preserved source directory and pose report')
    pose_raw = args.pose.read_bytes()
    report = analyze(source,json.loads(pose_raw))
    report['pose_report_sha256'] = hashlib.sha256(pose_raw).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    statuses = {}
    for item in report['samples']:
        statuses[item['status']] = statuses.get(item['status'],0)+1
    print(json.dumps({'samples':len(report['samples']),'statuses':statuses,'report':str(output)}))


if __name__ == '__main__':
    main()
