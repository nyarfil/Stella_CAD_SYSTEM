"""Inspect the canonical BRep shapes of a public G305 reference STEP."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from cadgen import read_scene, build123d as bd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-url", default="https://github.com/you-wouldnt-reverse-engineer-a-rat/g305-re/blob/main/cad/G305_PCB.step")
    args = parser.parse_args()
    scene = read_scene(args.step)
    shapes = []
    for leaf in scene.leaves():
        for selection in scene.resolve(leaf.ref).entities("shape"):
            shape = selection.shape()
            box = shape.bounding_box()
            circular_edges = []
            for edge in shape.edges():
                if edge.geom_type == bd.GeomType.CIRCLE:
                    circular_edges.append({"center": list(edge.arc_center), "radius": edge.radius,
                                           "length": edge.length,
                                           "full_circle": abs(edge.length - 2 * math.pi * edge.radius) < 1e-5})
            shapes.append({"ref": selection.ref, "bbox_minimum": list(box.min), "bbox_maximum": list(box.max),
                           "extent": list(box.size), "solid_count": len(shape.solids()), "circular_edges": circular_edges})
    result = {"source": str(args.step.resolve()), "source_sha256": hashlib.sha256(args.step.read_bytes()).hexdigest(),
              "source_url": args.source_url,
              "coordinate_units": "mm after STEP unit-aware read; source unit declaration must be checked separately",
              "shapes": shapes,
              "limitations": ["Third-party reference geometry, not measured owner hardware.",
                              "BRep selectors are bound to the recorded source hash.",
                              "Circular edges include fillets and cutout arcs; only full_circle boundaries are full rims.",
                              "No physical part labels are inferred from solid enumeration order."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"source_sha256": result["source_sha256"], "shapes": len(shapes), "output": str(args.output)}))


if __name__ == "__main__":
    main()
