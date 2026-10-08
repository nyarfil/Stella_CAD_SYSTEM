"""Find circular boundaries on axis-aligned STL faces; do not infer hole use."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from inspect_stl import RECORD


def circles_on_planes(path: Path):
    raw = path.read_bytes()
    count = int.from_bytes(raw[80:84], "little")
    if len(raw) != 84 + count * RECORD.itemsize:
        raise ValueError("Unsupported binary STL")
    triangles = np.frombuffer(raw, dtype=RECORD, count=count, offset=84)["vertices"].astype(float)
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    normals /= np.where(lengths > 0, lengths, 1)[:, None]
    results = []
    for axis in range(3):
        other_axes = [i for i in range(3) if i != axis]
        mask = (np.abs(normals[:, axis]) > 1 - 1e-7) & (np.ptp(triangles[:, :, axis], axis=1) < 1e-4)
        faces = triangles[mask]
        plane_keys = np.rint(faces[:, :, axis].mean(axis=1) / 1e-4).astype(np.int64)
        for key in np.unique(plane_keys):
            subset = faces[plane_keys == key]
            flat = subset.reshape(-1, 3)
            vertices, inverse = np.unique(np.rint(flat / 1e-5).astype(np.int64), axis=0, return_inverse=True)
            vertices = vertices.astype(float) * 1e-5
            ids = inverse.reshape(-1, 3)
            edges = np.concatenate([ids[:, [0, 1]], ids[:, [1, 2]], ids[:, [2, 0]]])
            edges.sort(axis=1)
            unique_edges, multiplicity = np.unique(edges, axis=0, return_counts=True)
            adjacency = {}
            for a, b in unique_edges[multiplicity == 1]:
                adjacency.setdefault(int(a), set()).add(int(b))
                adjacency.setdefault(int(b), set()).add(int(a))
            pending = set(adjacency)
            while pending:
                start = min(pending)
                cluster, todo = set(), [start]
                while todo:
                    node = todo.pop()
                    if node not in cluster:
                        cluster.add(node)
                        todo.extend(adjacency[node] - cluster)
                pending -= cluster
                if len(cluster) < 12 or any(len(adjacency[n]) != 2 for n in cluster):
                    continue
                points = vertices[sorted(cluster)][:, other_axes]
                # Shift before fitting to avoid loss of precision far from the origin.
                origin = points.mean(axis=0)
                centered = points - origin
                coeff, *_ = np.linalg.lstsq(np.column_stack([2 * centered, np.ones(len(points))]), (centered ** 2).sum(axis=1), rcond=None)
                center = origin + coeff[:2]
                radius_squared = coeff[2] + (coeff[:2] ** 2).sum()
                if radius_squared <= 0:
                    continue
                radius = float(np.sqrt(radius_squared))
                deviations = np.abs(np.linalg.norm(points - center, axis=1) - radius)
                if radius < 0.3 or deviations.max() > 0.002:
                    continue
                angles = np.sort(np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0]))
                largest_angular_gap = float(np.diff(np.r_[angles, angles[0] + 2 * np.pi]).max())
                # A curved sliver or semicircular U can fit a circle without being a circular rim.
                if largest_angular_gap > np.pi / 3:
                    continue
                position = np.zeros(3)
                position[axis] = subset[:, :, axis].mean()
                position[other_axes] = center
                results.append({"axis": "XYZ"[axis], "center": position.tolist(), "radius": radius,
                                "max_radial_fit_error": float(deviations.max()), "boundary_vertices": len(points),
                                "largest_angular_gap_radians": largest_angular_gap,
                                "classification": "circular planar boundary; bore versus outer perimeter not classified"})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--files", nargs="+", help="Relative STL files; default is the five Solid reference parts")
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    output = args.output.resolve()
    if output == source or source in output.parents:
        parser.error("output must be outside the preserved source folder")
    names = args.files or [f"Solid/{name}.stl" for name in ["top-solid", "bottom-solid", "triggers-solid", "front-button", "back-button"]]
    for name in names:
        if not (source / name).resolve().is_relative_to(source):
            parser.error("input files must stay inside the preserved source folder")
    result = {"units": "unspecified STL coordinate units", "source_root": str(source),
              "source_sha256": {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in names},
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "method": "axis-aligned planar face boundary loops and least-squares circle fits",
              "limitations": ["Circular boundaries may be bore rims or outer boss perimeters.",
                              "Axis alignment is checked in each file's saved coordinate frame.",
                              "A rim is not proof of a full cylinder or a functional screw interface."],
              "files": {name: circles_on_planes(source / name)
                        for name in names}}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "boundaries": {key: len(value) for key, value in result["files"].items()}}))


if __name__ == "__main__":
    main()
