"""B-rep reconstruction and independent measured structural signatures.

Geometry descriptor: normalized surface-distance histograms (D2/radial) + moments.
This is explicitly NOT Req2CAD's learned cross-attention point-cloud embedding.
Topology: face-type-labeled adjacency graph + WL subtree feature map.
"""
from __future__ import annotations
import hashlib, json, math
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
from .common import *


def vector(data,dim=3):
    if not isinstance(data,dict): raise BrainError('FS_CAD_SCHEMA','Expected a coordinate dictionary.')
    return np.array([finite(data[k],k) for k in ('x','y','z')[:dim]],dtype=float)


def classify_profile_wires(wires, claimed_outer):
    """Resolve loop nesting using planar area containment, never the parser flag alone.

    Onshape-derived records can label BOTH rings of an annulus ``is_outer=true``.
    A filled face is built for every closed wire. Partial overlap/touching is an
    error; strict containment defines a forest, with even-depth material regions.
    This recovers topology from the actual curves and records all flag conflicts.
    """
    import cadquery as cq
    faces = [cq.Face.makeFromWires(w) for w in wires]
    areas = [float(f.Area()) for f in faces]
    if any(not f.isValid() or a <= 0 for f, a in zip(faces, areas)):
        raise BrainError('FS_CAD_PROFILE', 'A profile loop is invalid or has zero area.')
    containers = [[] for _ in wires]
    # Absolute tolerance is in the active CAD coordinate system, not printer accuracy.
    length_eps = max(1e-8, max(math.sqrt(a) for a in areas) * 1e-8)
    for i in range(len(wires)):
        for j in range(i + 1, len(wires)):
            if wires[i].distance(wires[j]) <= length_eps:
                raise BrainError('FS_CAD_PROFILE', 'Profile boundaries touch or intersect; nesting is ambiguous.')
            overlap = float(faces[i].intersect(faces[j]).Area())
            area_eps = max(1e-14, min(areas[i], areas[j]) * 1e-6)
            if overlap <= area_eps:
                continue
            if abs(overlap - min(areas[i], areas[j])) > area_eps:
                raise BrainError('FS_CAD_PROFILE', 'Profile interiors partially overlap.')
            smaller, larger = (i, j) if areas[i] < areas[j] else (j, i)
            containers[smaller].append(larger)
    parent = [min(c, key=lambda j: areas[j]) if c else None for c in containers]
    depths = []
    for i in range(len(wires)):
        depth, j, seen = 0, i, {i}
        while parent[j] is not None:
            j = parent[j]
            if j in seen:
                raise BrainError('FS_CAD_PROFILE', 'Cyclic containment.')
            seen.add(j); depth += 1
        depths.append(depth)
    groups = [(wires[i], [wires[j] for j in range(len(wires))
                         if parent[j] == i and depths[j] % 2 == 1])
              for i in range(len(wires)) if depths[i] % 2 == 0]
    return groups, {'method': 'OCCT planar-area containment / even-odd nesting',
                    'loop_depths': depths,
                    'flag_disagreements': [i for i, d in enumerate(depths)
                                           if claimed_outer[i] != (d % 2 == 0)]}


def reconstruct(data, scale_to_mm):
    """Replay raw DeepCAD JSON. Coordinates are scaled only as explicitly supplied.

    Unsupported operations/taper/extents are rejected. NewBody remains separate;
    profiles belonging to one feature are combined before its boolean operation.
    This is geometry replay, not evidence of the annotation's functional accuracy.
    """
    import cadquery as cq
    scale = finite(scale_to_mm, positive=True)
    if not isinstance(data, dict) or not isinstance(data.get('entities'), dict) or not isinstance(data.get('sequence'), list):
        raise BrainError('FS_CAD_SCHEMA', 'Expected original DeepCAD entities + sequence JSON.')
    if len(data['sequence']) > 512 or len(data['entities']) > 2048:
        raise BrainError('FS_CAD_LIMIT', 'Too many entities/operations.')
    body = None
    steps, sketch_graphs, loop_inferences = [], [], []
    for item in data['sequence']:
        if item['type'] == 'Sketch':
            continue
        if item['type'] != 'ExtrudeFeature':
            raise BrainError('FS_CAD_UNSUPPORTED', 'Unsupported operation: ' + str(item['type']))
        ext = data['entities'][item['entity']]
        if ext['start_extent']['type'] != 'ProfilePlaneStartDefinition':
            raise BrainError('FS_CAD_UNSUPPORTED', 'Unsupported extrusion start.')
        op, extent = ext['operation'], ext['extent_type']
        if op not in ('NewBodyFeatureOperation', 'JoinFeatureOperation', 'CutFeatureOperation', 'IntersectFeatureOperation'):
            raise BrainError('FS_CAD_UNSUPPORTED', 'Unsupported boolean operation.')
        if extent not in ('OneSideFeatureExtentType', 'TwoSidesFeatureExtentType', 'SymmetricFeatureExtentType'):
            raise BrainError('FS_CAD_UNSUPPORTED', 'Unsupported extrusion extent.')
        for key in ('extent_one', 'extent_two'):
            ex = ext.get(key, {})
            if ex.get('type', 'DistanceExtentDefinition') != 'DistanceExtentDefinition':
                raise BrainError('FS_CAD_UNSUPPORTED', 'Only distance extents are supported.')
            taper = ex.get('taper_angle', {}).get('value', 0.)
            if abs(finite(taper)) > 1e-12:
                raise BrainError('FS_CAD_UNSUPPORTED', 'Nonzero taper is not silently replaced by straight extrusion.')
        d1 = finite(ext['extent_one']['distance']['value']) * scale
        d2 = finite(ext['extent_two']['distance']['value']) * scale if extent == 'TwoSidesFeatureExtentType' else (d1 if extent == 'SymmetricFeatureExtentType' else 0.)
        if abs(d1) < 1e-10 and abs(d2) < 1e-10:
            raise BrainError('FS_CAD_EMPTY', 'Zero length extrusion.')
        refs = ext['profiles']
        if not isinstance(refs, list) or not 1 <= len(refs) <= 64:
            raise BrainError('FS_CAD_LIMIT', 'Invalid profile count.')
        feature_solids = []
        for ref in refs:
            sk = data['entities'][ref['sketch']]; transform = sk['transform']
            origin = vector(transform['origin']) * scale
            x, y, z = [vector(transform[k]) for k in ('x_axis', 'y_axis', 'z_axis')]
            basis = np.stack([x, y, z], axis=1)
            if not np.allclose(basis.T @ basis, np.eye(3), atol=1e-6) or np.linalg.det(basis) < .99999:
                raise BrainError('FS_CAD_FRAME', 'Sketch basis must be orthonormal and right-handed.')
            loops = sk['profiles'][ref['profile']]['loops']
            if not 1 <= len(loops) <= 64:
                raise BrainError('FS_CAD_LIMIT', 'Invalid loop count.')
            wires, flags, graph_nodes, endpoints = [], [], [], []
            def world(p):
                return cq.Vector(*(origin + (x * p[0] + y * p[1]) * scale))
            for loop in loops:
                curves = loop['profile_curves']
                if not 1 <= len(curves) <= 512:
                    raise BrainError('FS_CAD_LIMIT', 'Invalid curve count.')
                edges = []
                for c in curves:
                    t = c['type']
                    if t == 'Line3D':
                        a, b = vector(c['start_point'], 2), vector(c['end_point'], 2)
                        if np.linalg.norm(a-b) * scale < 1e-9:
                            raise BrainError('FS_CAD_DEGENERATE', 'Zero-length line.')
                        edges.append(cq.Edge.makeLine(world(a), world(b))); ends = [a, b]
                    elif t == 'Circle3D':
                        center = vector(c['center_point'], 2); r = finite(c['radius'], positive=True)
                        edges.append(cq.Edge.makeCircle(r * scale, world(center), cq.Vector(*z))); ends = []
                    elif t == 'Arc3D':
                        a, b = vector(c['start_point'], 2), vector(c['end_point'], 2)
                        center = vector(c['center_point'], 2); r = finite(c['radius'], positive=True)
                        v = vector(c['reference_vector'], 2)
                        angle = (finite(c['start_angle']) + finite(c['end_angle'])) / 2
                        rot = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
                        mid = center + rot @ v * r
                        if abs(np.linalg.norm(v) - 1.) > 1e-5:
                            raise BrainError('FS_CAD_SCHEMA', 'Arc reference direction must be a unit vector.')
                        edges.append(cq.Edge.makeThreePointArc(world(a), world(mid), world(b))); ends = [a, b]
                    else:
                        raise BrainError('FS_CAD_UNSUPPORTED', 'Unsupported curve: ' + str(t))
                    graph_nodes.append({'id': len(graph_nodes), 'label': t, 'sketch': ref['sketch'], 'profile': ref['profile']})
                    endpoints.append(ends)
                wire = cq.Wire.assembleEdges(edges)
                if not wire.IsClosed():
                    raise BrainError('FS_CAD_OPEN', 'Profile wire is not closed.')
                if type(loop.get('is_outer')) is not bool:
                    raise BrainError('FS_CAD_SCHEMA', 'Loop is_outer must be an explicit boolean.')
                wires.append(wire); flags.append(loop['is_outer'])
            regions, inference = classify_profile_wires(wires, flags)
            loop_inferences.append({'sketch': ref['sketch'], 'profile': ref['profile'], **inference})
            for outer, inner in regions:
                pieces = []
                if abs(d1) > 1e-10:
                    pieces.append(cq.Solid.extrudeLinear(outer, inner, cq.Vector(*(z * d1))))
                if abs(d2) > 1e-10:
                    pieces.append(cq.Solid.extrudeLinear(outer, inner, cq.Vector(*(-z * d2))))
                solid = pieces[0]
                for piece in pieces[1:]:
                    solid = solid.fuse(piece)
                if not solid.isValid() or not solid.Solids():
                    raise BrainError('FS_CAD_INVALID', 'Extrusion did not produce a valid solid.')
                feature_solids.append(solid)
            adjacency = [[i, j] for i in range(len(graph_nodes)) for j in range(i + 1, len(graph_nodes))
                         if any(np.linalg.norm(a-b) * scale < 1e-6 for a in endpoints[i] for b in endpoints[j])]
            sketch_graphs.append({'nodes': graph_nodes, 'edges': adjacency, 'connection': 'shared curve endpoints'})
            steps.append({'entity': item['entity'], 'operation': op, 'extent_type': extent,
                          'distance_forward_mm': d1, 'distance_backward_mm': d2,
                          'sketch': ref['sketch'], 'profile': ref['profile']})
        tool = feature_solids[0]
        for solid in feature_solids[1:]:
            tool = tool.fuse(solid)
        if body is None:
            if op in ('CutFeatureOperation', 'IntersectFeatureOperation'):
                raise BrainError('FS_CAD_OPERATION', 'First operation cannot cut/intersect an absent body.')
            body = tool
        elif op == 'NewBodyFeatureOperation':
            body = cq.Compound.makeCompound([*body.Solids(), *tool.Solids()])
        elif op == 'JoinFeatureOperation':
            body = body.fuse(tool)
        elif op == 'CutFeatureOperation':
            body = body.cut(tool)
        else:
            body = body.intersect(tool)
        if not body.isValid() or not body.Solids():
            raise BrainError('FS_CAD_INVALID', 'Boolean operation produced no valid solid.')
    if body is None:
        raise BrainError('FS_CAD_EMPTY', 'No extrusion found.')
    return body, {'operations': steps, 'sketch_graphs': sketch_graphs, 'loop_inference': loop_inferences,
                  'units_scale_to_mm': scale, 'replay_version': 3,
                  'new_body_semantics': 'separate solids; profiles of one feature are fused before applying the operation',
                  'merge_scope': 'Join/Cut/Intersect apply to prior geometry; raw data has no body ownership map'}


def wl_features(nodes,edges,iterations=3):
    bounded_int(iterations,0,8,'WL iterations')
    ids=[n['id'] for n in nodes]
    if len(ids)!=len(set(ids)): raise BrainError('FS_GRAPH','Duplicate node IDs.')
    labels={n['id']:str(n['label']) for n in nodes};neighbors={n:set() for n in ids}
    for a,b in edges:
        if a not in neighbors or b not in neighbors: raise BrainError('FS_GRAPH','Dangling graph edge.')
        if a!=b: neighbors[a].add(b);neighbors[b].add(a)
    features=Counter('0:'+l for l in labels.values())
    for depth in range(1,iterations+1):
        labels={n:hashlib.sha256(canonical([labels[n],sorted(labels[v] for v in neighbors[n])]).encode()).hexdigest() for n in ids}
        features.update(str(depth)+':'+l for l in labels.values())
    return dict(features)


def wl_similarity(a,b):
    dot=sum(v*b.get(k,0) for k,v in a.items());aa=sum(v*v for v in a.values());bb=sum(v*v for v in b.values())
    return {'kernel':dot,'distance':math.sqrt(max(0,aa+bb-2*dot)),
            'normalized_similarity':dot/math.sqrt(aa*bb) if aa and bb else 0.}


def shape_features(shape,point_count=2048):
    import cadquery as cq
    bounded_int(point_count,128,16384,'point_count')
    if not shape.isValid() or not shape.Solids(): raise BrainError('FS_CAD_INVALID','Expected a valid B-rep with at least one solid.')
    faces=shape.Faces();nodes=[];edge_faces=defaultdict(list)
    edge_representatives={}
    for i,face in enumerate(faces):
        nodes.append({'id':i,'label':face.geomType(),'area_mm2':float(face.Area()),'center_mm':face.Center().toTuple()})
        # hash buckets + isSame check avoid relying on hash uniqueness.
        for edge in face.Edges():
            h=edge.hashCode();bucket=edge_representatives.setdefault(h,[])
            found=None
            for j,e in enumerate(bucket):
                if edge.isSame(e):found=(h,j);break
            if found is None: bucket.append(edge);found=(h,len(bucket)-1)
            if i not in edge_faces[found]: edge_faces[found].append(i)
    adjacency=set();nonmanifold=0
    for linked in edge_faces.values():
        if len(linked)>2: nonmanifold+=1
        for i,a in enumerate(linked):
            for b in linked[i+1:]: adjacency.add(tuple(sorted((a,b))))
    edges=[list(e) for e in sorted(adjacency)]
    bbox=shape.BoundingBox();sizes=np.array([bbox.xlen,bbox.ylen,bbox.zlen]);diag=float(np.linalg.norm(sizes))
    if diag<=1e-12: raise BrainError('FS_CAD_DEGENERATE','Zero bounding diagonal.')
    verts,triangles=shape.tessellate(max(diag*0.0005,0.0001),0.1)
    if len(triangles)>1000000: raise BrainError('FS_CAD_LIMIT','Tessellation too large.')
    v=np.array([p.toTuple() for p in verts]);t=np.asarray(triangles,dtype=np.int64)
    if not len(t): raise BrainError('FS_CAD_EMPTY','No surface triangles.')
    tri=v[t];areas=np.linalg.norm(np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]),axis=1)/2
    if not np.isfinite(areas).all() or areas.sum()<=0: raise BrainError('FS_CAD_INVALID','Invalid surface mesh.')
    rng=np.random.default_rng(20260916);idx=rng.choice(len(t),size=point_count,p=areas/areas.sum())
    chosen=tri[idx];uv=rng.random((point_count,2));u=np.sqrt(uv[:,0]);w=uv[:,1]
    pts=(1-u)[:,None]*chosen[:,0]+(u*(1-w))[:,None]*chosen[:,1]+(u*w)[:,None]*chosen[:,2]
    center=pts.mean(axis=0);p=(pts-center)/diag
    # Rotation-insensitive shape distributions, not correspondence or proof of fit.
    radii=np.linalg.norm(p,axis=1);pair=rng.integers(0,len(p),size=(8192,2));d2=np.linalg.norm(p[pair[:,0]]-p[pair[:,1]],axis=1)
    h1=np.histogram(radii,bins=32,range=(0,1))[0].astype(float);h1/=h1.sum()
    h2=np.histogram(d2,bins=32,range=(0,1.01))[0].astype(float);h2/=h2.sum()
    eig=np.linalg.eigvalsh(np.cov(p.T));eig=np.maximum(eig,0)
    descriptor=np.r_[h1,h2,eig].tolist()
    volume=float(sum(s.Volume() for s in shape.Solids()))
    return {'valid':True,'solids':len(shape.Solids()),'faces':len(faces),'unique_edges':len(shape.Edges()),'vertices':len(shape.Vertices()),
       'bbox_mm':sizes.tolist(),'volume_mm3':volume,'area_mm2':float(shape.Area()),
       'face_types':dict(Counter(n['label'] for n in nodes)),'topology':{'nodes':nodes,'edges':edges,'nonmanifold_edges':nonmanifold},
       'wl_iterations':3,'wl_features':wl_features(nodes,edges),
       'geometry_descriptor':{'method':'surface-D2-radial-covariance-v1','learned':False,'sample_count':point_count,'vector':descriptor},
       'surface_points_mm':pts.tolist(),'interfaces': __import__('cadmcp_brain.studio.interfaces',fromlist=['extract_interfaces']).extract_interfaces(shape),'strength':'unknown','function_validation':'unknown'}


def compare_records(a,b):
    top=wl_similarity(a['wl_features'],b['wl_features'])
    da=a['geometry_descriptor'];db=b['geometry_descriptor']
    if da['method']!=db['method']: raise BrainError('FS_GEOMETRY_VERSION','Descriptors use different methods.')
    av=np.asarray(da['vector']);bv=np.asarray(db['vector']);cos=float(av@bv/(np.linalg.norm(av)*np.linalg.norm(bv)))
    return {'topology':top,'geometry':{'method':da['method'],'cosine_similarity':cos,'euclidean_distance':float(np.linalg.norm(av-bv))},
      'interpretation':'Similarity of face adjacency / sampled shape, NOT functional equivalence, fit, joint design or strength.'}
