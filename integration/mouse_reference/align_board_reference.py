"""Compare four G305 board fixing features with ZS-F1 bottom screw-axis rims.

Uses a rigid fit only; the hardware is never scaled to force agreement.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np

from align_primary_clicks import records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board_measurements", type=Path)
    parser.add_argument("bottom_measurements", type=Path)
    parser.add_argument("board_stl", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("preview_stl", type=Path)
    args = parser.parse_args()
    board = json.loads(args.board_measurements.read_text(encoding="utf-8"))
    bottom = json.loads(args.bottom_measurements.read_text(encoding="utf-8"))
    source_root = Path(bottom["source_root"]).resolve()
    bottom_path = source_root / "Solid/bottom-solid.stl"
    for output in (args.report.resolve(), args.preview_stl.resolve()):
        if output == source_root or source_root in output.parents:
            parser.error("output must be outside the preserved source directory")
    if hashlib.sha256(bottom_path.read_bytes()).hexdigest() != bottom["source_sha256"]["Solid/bottom-solid.stl"]:
        raise ValueError("Bottom source changed; measure again")
    if hashlib.sha256(Path(board["source"]).read_bytes()).hexdigest() != board["source_sha256"]:
        raise ValueError("Board STEP source changed; measure again")
    board_candidates = [shape for shape in board["shapes"] if shape["extent"][1] > 80 and shape["extent"][2] < 1]
    if len(board_candidates) != 1:
        raise ValueError("Reference PCB shape is not unique")
    edges = [edge for edge in board_candidates[0]["circular_edges"]
             if abs(edge["radius"] - 1.45) < 0.001 and abs(edge["center"][2]) < 0.001]
    target_rims = [rim for rim in bottom["files"]["Solid/bottom-solid.stl"]
                   if rim["axis"] == "Z" and abs(rim["radius"] - 0.65) < 0.001
                   and abs(rim["center"][2] - 5.159756) < 0.001]
    if len(edges) != 4 or len(target_rims) != 4:
        raise ValueError("Expected four source features and four target screw axes")
    source = np.array([edge["center"] for edge in edges])
    target = np.array([rim["center"] for rim in target_rims])
    fits = []
    for permutation in itertools.permutations(range(4)):
        a, b = source[:, :2], target[list(permutation), :2]
        ac, bc = a.mean(axis=0), b.mean(axis=0)
        u, _, vt = np.linalg.svd((a - ac).T @ (b - bc))
        rotation = vt.T @ u.T
        if np.linalg.det(rotation) < 0:
            vt[-1] *= -1
            rotation = vt.T @ u.T
        translation = bc - rotation @ ac
        residuals = np.linalg.norm(a @ rotation.T + translation - b, axis=1)
        fits.append((float(np.sqrt((residuals ** 2).mean())), permutation, rotation, translation, residuals))
    fits.sort(key=lambda item: item[0])
    rms, permutation, xy_rotation, xy_translation, residuals = fits[0]
    rotation = np.eye(3)
    rotation[:2, :2] = xy_rotation
    translation = np.r_[xy_translation, target[:, 2].mean()]
    moving = records(args.board_stl)
    moving["vertices"] = moving["vertices"] @ rotation.T + translation
    moving["normal"] = moving["normal"] @ rotation.T
    merged = np.concatenate([records(bottom_path), moving])
    args.preview_stl.parent.mkdir(parents=True, exist_ok=True)
    args.preview_stl.write_bytes(b"G305 reference board pose candidate; NOT fit verified".ljust(80, b" ")
                                + len(merged).to_bytes(4, "little") + merged.tobytes())
    result = {
        "status": "reference_board_pose_candidate_not_fit_verified",
        "unit_assumption": "One source STEP mm is treated as one ZS-F1 STL coordinate unit for this comparison only.",
        "board_step_sha256": board["source_sha256"], "bottom_stl_sha256": bottom["source_sha256"]["Solid/bottom-solid.stl"],
        "board_stl_sha256": hashlib.sha256(args.board_stl.read_bytes()).hexdigest(),
        "source_board_selector": board_candidates[0]["ref"], "source_features": edges,
        "matched_target_rims": [target_rims[i] for i in permutation],
        "rotation": rotation.tolist(), "translation": translation.tolist(),
        "xy_rotation_degrees": float(np.degrees(np.arctan2(xy_rotation[1, 0], xy_rotation[0, 0]))),
        "xy_center_residuals": residuals.tolist(), "xy_rms_residual": rms,
        "xy_maximum_residual": float(residuals.max()), "next_best_correspondence_rms": fits[1][0],
        "assumptions": ["Two closed circular holes and two open semicircular fixing slots are paired by their circular centers.",
                        "All four features receive equal weight in a visualization fit, not a tolerance analysis.",
                        "Reference PCB underside is placed at the measured screw-boss top level."],
        "not_verified": ["actual G305 revision and source CAD accuracy", "STL physical unit declaration", "fastener dimensions and fit",
                         "whole-board and component interference", "lens optical working height", "wheel support and motion", "physical assembly"],
        "preview_stl": str(args.preview_stl.resolve()),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rms": rms, "maximum": float(residuals.max()), "rotation_degrees": result["xy_rotation_degrees"], "preview": result["preview_stl"]}))


if __name__ == "__main__":
    main()
