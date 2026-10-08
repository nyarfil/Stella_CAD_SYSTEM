"""Derive a ZS-F1 click mounting pose from measured circular planar rims.

This is reference inspection, not a fit-certified assembly or printable output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from inspect_stl import RECORD
from measure_planar_interfaces import circles_on_planes


def records(path):
    data = path.read_bytes()
    count = int.from_bytes(data[80:84], "little")
    if len(data) != 84 + count * RECORD.itemsize:
        raise ValueError("Unsupported STL")
    return np.frombuffer(data, dtype=RECORD, count=count, offset=84).copy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("preview_stl", type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    for output in (args.report.resolve(), args.preview_stl.resolve()):
        if source == output or source in output.parents:
            parser.error("outputs must be outside the preserved source directory")
    top_path = source / "Solid/top-solid.stl"
    trigger_path = source / "Solid/triggers-solid.stl"
    top_rims = [item for item in circles_on_planes(top_path)
                if item["axis"] == "Z" and abs(item["radius"] - 1.1) < 0.002]
    trigger_rims = [item for item in circles_on_planes(trigger_path)
                    if item["axis"] == "Y" and abs(item["radius"] - 0.925) < 0.002]
    if len(top_rims) != 2 or len(trigger_rims) != 4:
        raise ValueError("Expected ZS-F1 mounting rim candidates not found; do not reuse for other designs")
    # Two trigger planes bound the tab. The lower assembled face is the smaller saved Y.
    lowest_y = min(item["center"][1] for item in trigger_rims)
    trigger_rims = [item for item in trigger_rims if abs(item["center"][1] - lowest_y) < 0.002]
    top_rims.sort(key=lambda item: item["center"][0])
    trigger_rims.sort(key=lambda item: item["center"][0])
    target = np.array([item["center"] for item in top_rims])
    moving = np.array([item["center"] for item in trigger_rims])
    rotation = np.array([[1., 0., 0.], [0., 0., -1.], [0., 1., 0.]])
    translation = (target - moving @ rotation.T).mean(axis=0)
    residual = moving @ rotation.T + translation - target
    top = records(top_path)
    triggers = records(trigger_path)
    triggers["vertices"] = triggers["vertices"] @ rotation.T + translation
    triggers["normal"] = triggers["normal"] @ rotation.T
    combined = np.concatenate([top, triggers])
    preview = args.preview_stl.resolve()
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"ZS-F1 reference mounting pose candidate; NOT fit verified".ljust(80, b" ")
                        + len(combined).to_bytes(4, "little") + combined.tobytes())
    vertices = triggers["vertices"].reshape(-1, 3)
    report = {
        "status": "mounting_pose_candidate_not_fit_verified", "units": "unspecified STL coordinate units",
        "sources": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in [top_path, trigger_path]},
        "rotation": rotation.tolist(), "translation": translation.tolist(),
        "coordinate_rule": "assembled = rotation @ saved + translation; X-axis rotation +90 degrees",
        "target_top_rims": top_rims, "moving_trigger_rims": trigger_rims,
        "mounting_center_residuals": residual.tolist(), "maximum_center_residual": float(np.linalg.norm(residual, axis=1).max()),
        "assembled_trigger_minimum": vertices.min(axis=0).tolist(), "assembled_trigger_maximum": vertices.max(axis=0).tolist(),
        "preview_stl": str(preview), "preview_sha256": hashlib.sha256(preview.read_bytes()).hexdigest(),
        "assumptions": ["Rim pair selected from matching X centers and photo-supported rear retention features.",
                        "The lower trigger tab face is placed flush on the top-shell boss face.",
                        "No fastener, washer or stand-off thickness has been inserted."],
        "not_verified": ["full bore profiles", "source physical units", "shell/trigger collision or operational clearance",
                         "switch contact and preload", "elastic deformation and return", "fasteners and physical assembly"],
    }
    args.report.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"translation": translation.tolist(), "maximum_center_residual": report["maximum_center_residual"], "preview": str(preview)}))


if __name__ == "__main__":
    main()
