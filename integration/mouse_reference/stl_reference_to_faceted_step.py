"""Serialize unchanged, closed binary STL triangles as an AP203 faceted BRep.

This is input-format conversion, with no surface fitting, repair or new geometry.
Units are an explicit caller assumption; conversion does not calibrate a scan.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct


def convert(source: Path, output: Path, unit_basis: str) -> dict:
    raw = source.read_bytes()
    if len(raw) < 84:
        raise ValueError("Missing binary STL header")
    count = struct.unpack_from("<I", raw, 80)[0]
    if not 1 <= count <= 100000 or len(raw) != 84 + count * 50:
        raise ValueError("Expected bounded binary STL, at most 100000 triangles")
    vertices, index, triangles = [], {}, []
    edges, directions = Counter(), Counter()
    signed_volume = 0.0
    for record in struct.iter_unpack("<12fH", raw[84:]):
        xyz = [tuple(record[3+i*3:6+i*3]) for i in range(3)]
        import math
        if not all(math.isfinite(v) for p in xyz for v in p):
            raise ValueError("Nonfinite coordinate")
        a, b, c = xyz
        u = tuple(b[i]-a[i] for i in range(3)); v = tuple(c[i]-a[i] for i in range(3))
        cross = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
        if sum(k*k for k in cross) == 0:
            raise ValueError("Degenerate triangle; no automatic repair allowed")
        ids=[]
        for p in xyz:
            if p not in index:
                index[p]=len(vertices); vertices.append(p)
            ids.append(index[p])
        triangles.append(ids)
        for j in range(3):
            first,last=ids[j],ids[(j+1)%3]
            edge=(min(first,last),max(first,last));edges[edge]+=1
            directions[edge]+=1 if first<last else -1
        signed_volume += (a[0]*(b[1]*c[2]-b[2]*c[1]) + a[1]*(b[2]*c[0]-b[0]*c[2]) + a[2]*(b[0]*c[1]-b[1]*c[0]))/6
    if any(n != 2 for n in edges.values()) or any(n != 0 for n in directions.values()):
        raise ValueError("Exact vertices do not form a closed consistently oriented mesh; no welding/repair performed")
    if signed_volume <= 0:
        raise ValueError("Positive signed volume required; no automatic reorientation performed")
    lines=[]
    def entity(value):
        number=len(lines)+1;lines.append(f"#{number}={value};");return number
    refs=lambda values: '('+','.join(f'#{v}' for v in values)+')'
    app=entity("APPLICATION_CONTEXT('configuration controlled 3d designs of mechanical parts and assemblies')")
    entity(f"APPLICATION_PROTOCOL_DEFINITION('international standard','config_control_design',1994,#{app})")
    pc=entity(f"PRODUCT_CONTEXT('',#{app},'mechanical')")
    product=entity(f"PRODUCT('source_mesh','Unchanged STL reference','',({refs([pc])[1:-1]}))")
    formation=entity(f"PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE('','',#{product},.NOT_KNOWN.)")
    dc=entity(f"PRODUCT_DEFINITION_CONTEXT('part definition',#{app},'design')")
    pd=entity(f"PRODUCT_DEFINITION('design','',#{formation},#{dc})")
    pds=entity(f"PRODUCT_DEFINITION_SHAPE('','',#{pd})")
    unit=entity("(LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.))")
    angle=entity("(NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.))")
    solid_angle=entity("(NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT())")
    context=entity(f"(GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNIT_ASSIGNED_CONTEXT({refs([unit,angle,solid_angle])}) REPRESENTATION_CONTEXT('',''))")
    points=[entity("CARTESIAN_POINT('',("+','.join(format(v,'.17e') for v in p)+"))") for p in vertices]
    faces=[]
    for triangle in triangles:
        loop=entity(f"POLY_LOOP('',{refs([points[v] for v in triangle])})")
        bound=entity(f"FACE_OUTER_BOUND('',#{loop},.T.)")
        a,b,c=[vertices[v] for v in triangle]
        u=tuple(b[i]-a[i] for i in range(3));v=tuple(c[i]-a[i] for i in range(3))
        normal=(u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0])
        normal_length=math.sqrt(sum(k*k for k in normal));u_length=math.sqrt(sum(k*k for k in u))
        axis=entity("DIRECTION('',("+','.join(format(k/normal_length,'.17e') for k in normal)+"))")
        reference=entity("DIRECTION('',("+','.join(format(k/u_length,'.17e') for k in u)+"))")
        placement=entity(f"AXIS2_PLACEMENT_3D('',#{points[triangle[0]]},#{axis},#{reference})")
        plane=entity(f"PLANE('',#{placement})")
        faces.append(entity(f"FACE_SURFACE('',{refs([bound])},#{plane},.T.)"))
    shell=entity(f"CLOSED_SHELL('',{refs(faces)})")
    brep=entity(f"FACETED_BREP('source_triangles',#{shell})")
    representation=entity(f"FACETED_BREP_SHAPE_REPRESENTATION('',{refs([brep])},#{context})")
    entity(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{representation})")
    header="ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('Unchanged binary STL reference triangles'),'2;1');\nFILE_NAME('reference.step','',(''),(''),'Stella reference serializer','','');\nFILE_SCHEMA(('CONFIG_CONTROL_DESIGN'));\nENDSEC;\nDATA;\n"
    output.write_text(header+'\n'.join(lines)+'\nENDSEC;\nEND-ISO-10303-21;\n',encoding='ascii')
    if source.read_bytes() != raw:
        raise RuntimeError("Source changed during conversion")
    report={'source_name':source.name,'source_sha256':hashlib.sha256(raw).hexdigest(),
        'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
        'triangles_preserved':count,'unique_vertices_exact':len(vertices),
        'closed_edge_count':len(edges),'signed_mesh_volume_coordinate_units3':signed_volume,
        'output_unit':'mm','unit_basis':unit_basis,'unit_status':'caller_assumption_not_independent_calibration',
        'transforms':'identity; no scaling, mirroring, smoothing, vertex welding, repair or reorientation',
        'validation_status':'serialization only; kernel validity, self-intersection and shape equivalence unverified'}
    output.with_suffix('.conversion.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--unit-basis',required=True)
    args=p.parse_args()
    if args.output.suffix.lower() not in ['.step','.stp'] or args.output.resolve()==args.source.resolve():
        p.error('Separate STEP output required')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    print(json.dumps(convert(args.source,args.output,args.unit_basis),ensure_ascii=False))


if __name__=='__main__':main()
