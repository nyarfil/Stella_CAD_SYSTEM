"""Read-only binary STL measurements. No assembly pose or unit is inferred."""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

import numpy as np

RECORD = np.dtype([("normal", "<f4", (3,)), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")])


def inspect(path: Path, weld_tolerance: float) -> dict:
    raw = path.read_bytes()
    if len(raw) < 84:
        raise ValueError(f"STL header missing: {path}")
    count = struct.unpack_from("<I", raw, 80)[0]
    if len(raw) != 84 + count * RECORD.itemsize:
        raise ValueError(f"Not a supported binary STL: {path}")
    triangles = np.frombuffer(raw, dtype=RECORD, count=count, offset=84)["vertices"].astype(np.float64)
    if not np.isfinite(triangles).all():
        raise ValueError(f"Non-finite STL coordinates: {path}")
    vertices = triangles.reshape(-1, 3)
    _, inverse = np.unique(np.rint(vertices / weld_tolerance).astype(np.int64), axis=0, return_inverse=True)
    face_ids = inverse.reshape(-1, 3)
    parent = np.arange(inverse.max() + 1)

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b, c in face_ids:
        ra, rb, rc = find(a), find(b), find(c)
        parent[rb] = ra
        parent[rc] = ra
    roots = np.array([find(i) for i in range(len(parent))])
    face_roots = roots[face_ids[:, 0]]
    components = []
    for root in np.unique(face_roots):
        selection = face_roots == root
        points = triangles[selection].reshape(-1, 3)
        lo, hi = points.min(axis=0), points.max(axis=0)
        components.append({"triangles": int(selection.sum()), "minimum": lo.tolist(), "maximum": hi.tolist(), "extent": (hi - lo).tolist()})
    edges = np.concatenate([face_ids[:, [0, 1]], face_ids[:, [1, 2]], face_ids[:, [2, 0]]])
    edges.sort(axis=1)
    _, multiplicities = np.unique(edges, axis=0, return_counts=True)
    lo, hi = vertices.min(axis=0), vertices.max(axis=0)
    return {
        "sha256": hashlib.sha256(raw).hexdigest(), "triangles": count,
        "minimum": lo.tolist(), "maximum": hi.tolist(), "extent": (hi - lo).tolist(),
        "connected_component_count": len(components),
        "components": sorted(components, key=lambda item: item["triangles"], reverse=True),
        "boundary_edges_after_weld": int(np.count_nonzero(multiplicities == 1)),
        "nonmanifold_edges_after_weld": int(np.count_nonzero(multiplicities > 2)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--weld-tolerance", type=float, default=1e-5)
    args = parser.parse_args()
    if args.weld_tolerance <= 0:
        parser.error("weld tolerance must be positive")
    source = args.source.resolve(strict=True)
    files = sorted(source.rglob("*.stl"))
    if not files:
        parser.error("source has no STL files")
    result = {
        "source_root": str(source), "units": "unspecified STL coordinate units",
        "weld_tolerance": args.weld_tolerance,
        "limitations": ["Connectivity uses rounded coordinate welding; it is not a BRep validity check.", "No assembly transform, material, interface fit, elasticity, or manufacturing tolerance is inferred."],
        "files": {path.relative_to(source).as_posix(): inspect(path, args.weld_tolerance) for path in files},
    }
    output = args.output.resolve()
    if output == source or source in output.parents:
        parser.error("output must be outside the preserved source folder")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "files": len(files)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
