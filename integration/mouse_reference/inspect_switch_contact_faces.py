"""Measure planar contact candidates; do not infer switch travel from a static STEP."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from cadgen import read_scene, build123d as bd

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    rows = []
    scene = read_scene(args.step)
    for leaf in scene.leaves():
        for selection in scene.resolve(leaf.ref).entities('shape'):
            shape = selection.shape()
            faces = []
            for i, face in enumerate(shape.faces()):
                b = face.bounding_box()
                faces.append({'face_index': i, 'geometry_type': str(face.geom_type), 'area_mm2': face.area,
                              'center': list(face.center()), 'normal': list(face.normal_at()),
                              'bbox_minimum': list(b.min), 'bbox_maximum': list(b.max)})
            rows.append({'shape_ref': selection.ref, 'is_valid': shape.is_valid,
                         'volume_mm3': shape.volume, 'faces': faces})
    output = {'source': args.step.name, 'source_sha256': hashlib.sha256(args.step.read_bytes()).hexdigest(),
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'method': 'Unit-aware STEP reader; BRep face types, areas, centers, sampled outward normals and bounds.',
              'units': 'mm and mm^2', 'shapes': rows,
              'limitations': ['Face enumeration bound to this source hash and reader; not a portable CAD selector.',
                             'A topmost face is only a geometric contact candidate, not verified FP/OP, actuation direction or stroke.',
                             'No shape moved or changed; no fit or switch operation certified.']}
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    for row in rows:
        candidates = [f for f in row['faces'] if f['bbox_maximum'][2] > 7.94]
        print(json.dumps({'ref':row['shape_ref'], 'valid':row['is_valid'], 'topmost_faces':candidates}, ensure_ascii=False))

if __name__ == '__main__':
    main()
