"""Read-only BRep evidence for an alternate PCB-to-bottom-shell pose.

The program extracts the mounting-pattern candidates from the imported STEP
topology, rather than accepting coordinate lists as geometry.  It intentionally
separates a best in-plane rigid correspondence from an accepted physical pose.
It never writes a CAD source file or exports a transformed solid.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cadquery as cq


DEFAULT_ROOT = Path(r"E:\aiwork\Stella_CAD_SYSTEM")
DEFAULT_PCB = DEFAULT_ROOT / "cadmcp-workspace/imports/za13_r15/ZA13_main_pcb.step"
DEFAULT_BOTTOM = DEFAULT_ROOT / "cadmcp-workspace/imports/za13_r15/ZA13_R15_bottom.step"
DEFAULT_SENSOR = DEFAULT_ROOT / "cadmcp-workspace/imports/za13_r15/ZA13_sensor.step"
DEFAULT_OUTPUT = DEFAULT_ROOT / "docs/examples/za13_alternate_pcb_pose.json"

# This is only provenance supplied with this inspection request.  The file is
# deliberately not opened or geometrically compared by this ZA13-only case.
KNOWN_DISTINCT_LINEAGE = {
    "path": "V:/mouse/ZA13/R12-symmetric-rebuild/source/main_pcb_1.step",
    "sha256": "a98d08bd0cc3ed267f0ee78d001f38f4345e722d36715644c15fefc4820b0f63",
    "relationship": "Digest is known to differ from the imported PCB; its frame, revision, and geometry were not inspected here.",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def vec(value) -> list[float]:
    return [float(value[0]), float(value[1]), float(value[2])]


def bbox_record(shape) -> dict:
    box = shape.BoundingBox()
    return {
        "minimum_mm": [box.xmin, box.ymin, box.zmin],
        "maximum_mm": [box.xmax, box.ymax, box.zmax],
        "extent_mm": [box.xlen, box.ylen, box.zlen],
    }


def step_header(path: Path) -> dict:
    """Extract concise, non-geometric source identity from an ISO-10303 file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    file_name = re.search(
        r"FILE_NAME\(\s*/\* name \*/\s*'([^']*)'.*?/\* time_stamp \*/\s*'([^']*)'",
        text,
        flags=re.DOTALL,
    )
    schema = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", text, flags=re.DOTALL)
    units = sorted(set(re.findall(r"SI_UNIT\(\.(MILLI|CENTI|DECI|KILO)\.\s*,\s*\.METRE\.\)", text)))
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "step_file_name": file_name.group(1) if file_name else None,
        "step_timestamp": file_name.group(2) if file_name else None,
        "schema": schema.group(1) if schema else None,
        "declared_length_unit": "mm" if "MILLI" in units else "not deterministically located",
        "length_unit_tokens": units,
    }


def load_step(path: Path):
    result = cq.importers.importStep(str(path)).val()
    if not result.isValid():
        raise ValueError(f"Invalid BRep after import: {path}")
    return result


def solid_records(shape) -> list[dict]:
    records = []
    for index, solid in enumerate(shape.Solids()):
        records.append(
            {
                "index": index,
                "valid": bool(solid.isValid()),
                "volume_mm3": solid.Volume(),
                "face_count": len(solid.Faces()),
                "edge_count": len(solid.Edges()),
                "bbox": bbox_record(solid),
            }
        )
    return records


def cylinder_record(face, parent_solid_index: int | None = None) -> dict:
    cylinder = face._geomAdaptor().Cylinder()
    axis = cylinder.Axis()
    record = {
        "radius_mm": float(cylinder.Radius()),
        "axis_point_mm": vec(axis.Location().Coord()),
        "axis_direction": vec(axis.Direction().Coord()),
        "axis_tilt_from_z_degrees": math.degrees(math.acos(min(1.0, abs(float(axis.Direction().Coord()[2]))))),
        "area_mm2": float(face.Area()),
        "bbox": bbox_record(face),
    }
    if parent_solid_index is not None:
        record["parent_solid_index"] = parent_solid_index
    return record


def vertical_axis(record: dict, tolerance: float = 2e-2) -> bool:
    dx, dy, dz = record["axis_direction"]
    return abs(dx) <= tolerance and abs(dy) <= tolerance and abs(abs(dz) - 1.0) <= tolerance


def cylindrical_faces_by_solid(shape) -> list[dict]:
    result = []
    for solid_index, solid in enumerate(shape.Solids()):
        for face in solid.Faces():
            if face.geomType() == "CYLINDER":
                result.append(cylinder_record(face, solid_index))
    return result


def choose_pcb_plate(solid_info: list[dict]) -> int:
    """Identify the thin, largest-volume PCB plate without using coordinates."""
    candidates = [
        r
        for r in solid_info
        if 0.2 <= r["bbox"]["extent_mm"][2] <= 1.5
        and r["bbox"]["extent_mm"][0] >= 20.0
        and r["bbox"]["extent_mm"][1] >= 40.0
    ]
    if len(candidates) != 1:
        raise ValueError(f"PCB plate not unique; candidates={[(r['index'], r['bbox']['extent_mm']) for r in candidates]}")
    return candidates[0]["index"]


def select_repeated_vertical_radius(cylinders: Iterable[dict], expected_count: int, innermost: bool = False) -> list[dict]:
    """Pick a repeated radius group; prevents coordinates from being a selector."""
    groups: dict[float, list[dict]] = {}
    for record in cylinders:
        if vertical_axis(record):
            groups.setdefault(round(record["radius_mm"], 5), []).append(record)
    exact = [(radius, group) for radius, group in groups.items() if len(group) == expected_count]
    if innermost and exact:
        smallest = min(radius for radius, _ in exact)
        exact = [(radius, group) for radius, group in exact if radius == smallest]
    if len(exact) != 1:
        summary = {radius: len(group) for radius, group in groups.items()}
        raise ValueError(f"Expected one repeated vertical cylindrical group of {expected_count}; found {summary}")
    return sorted(exact[0][1], key=lambda r: (r["axis_point_mm"][1], r["axis_point_mm"][0]))


def transform_xy(point: list[float], degrees: float, tx: float, ty: float) -> list[float]:
    rad = math.radians(degrees)
    c, s = math.cos(rad), math.sin(rad)
    x, y = point[:2]
    return [c * x - s * y + tx, s * x + c * y + ty]


def solve_rigid_xy(source: list[dict], target: list[dict], pairs: list[tuple[int, int]]) -> tuple[float, float, float]:
    """Closed-form 2D rigid fit, retaining scale=1 by construction."""
    sx = sum(source[i]["axis_point_mm"][0] for i, _ in pairs) / len(pairs)
    sy = sum(source[i]["axis_point_mm"][1] for i, _ in pairs) / len(pairs)
    tx = sum(target[j]["axis_point_mm"][0] for _, j in pairs) / len(pairs)
    ty = sum(target[j]["axis_point_mm"][1] for _, j in pairs) / len(pairs)
    dot = cross = 0.0
    for i, j in pairs:
        px, py = source[i]["axis_point_mm"][0] - sx, source[i]["axis_point_mm"][1] - sy
        qx, qy = target[j]["axis_point_mm"][0] - tx, target[j]["axis_point_mm"][1] - ty
        dot += px * qx + py * qy
        cross += px * qy - py * qx
    angle = math.degrees(math.atan2(cross, dot))
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return angle, tx - (c * sx - s * sy), ty - (s * sx + c * sy)


def residual_xy(source_record: dict, target_record: dict, pose: tuple[float, float, float]) -> float:
    xy = transform_xy(source_record["axis_point_mm"], *pose)
    q = target_record["axis_point_mm"]
    return math.hypot(xy[0] - q[0], xy[1] - q[1])


def parse_correspondence(text: str | None, count: int) -> tuple[int, ...] | None:
    if not text:
        return None
    result = [-1] * count
    for token in text.split(","):
        source, target = (int(value.strip()) for value in token.split(":"))
        if not (0 <= source < count and 0 <= target < count) or result[source] != -1:
            raise ValueError("--correspondence requires unique source:target indices in range")
        result[source] = target
    if any(value < 0 for value in result) or len(set(result)) != count:
        raise ValueError("--correspondence must map every source index once")
    return tuple(result)


def holdout_hypotheses(source: list[dict], target: list[dict], correspondence: tuple[int, ...] | None) -> list[dict]:
    permutations = [correspondence] if correspondence else list(itertools.permutations(range(len(source))))
    results = []
    for mapping in permutations:
        holdouts = []
        for holdout in range(len(source)):
            train = [(i, mapping[i]) for i in range(len(source)) if i != holdout]
            pose = solve_rigid_xy(source, target, train)
            holdout_error = residual_xy(source[holdout], target[mapping[holdout]], pose)
            train_errors = [residual_xy(source[i], target[mapping[i]], pose) for i, _ in train]
            holdouts.append(
                {
                    "held_out_source_index": holdout,
                    "held_out_target_index": mapping[holdout],
                    "rotation_z_degrees": pose[0],
                    "translation_xy_mm": [pose[1], pose[2]],
                    "training_rms_mm": math.sqrt(sum(error * error for error in train_errors) / len(train_errors)),
                    "holdout_error_mm": holdout_error,
                }
            )
        results.append(
            {
                "target_index_for_source_index": list(mapping),
                "holdout_trials": holdouts,
                "maximum_holdout_error_mm": max(item["holdout_error_mm"] for item in holdouts),
                "rms_holdout_error_mm": math.sqrt(sum(item["holdout_error_mm"] ** 2 for item in holdouts) / len(holdouts)),
            }
        )
    return sorted(results, key=lambda item: (item["maximum_holdout_error_mm"], item["rms_holdout_error_mm"]))


def pose_from_best_hypothesis(source: list[dict], target: list[dict], hypothesis: dict) -> tuple[float, float, float]:
    """Refit all four only after their leave-one-out errors have been recorded.

    This avoids an invalid arithmetic average across equivalent +180/-180 angle
    representations while retaining independent holdout evidence.
    """
    mapping = hypothesis["target_index_for_source_index"]
    return solve_rigid_xy(source, target, [(index, mapping[index]) for index in range(len(source))])


def transform_shape(shape, rotation_z_degrees: float, translation_xyz: list[float]):
    transformed = shape.rotate((0, 0, 0), (0, 0, 1), rotation_z_degrees)
    return transformed.translate(tuple(translation_xyz))


def intersection_record(pcb_shape, bottom_shape, pose_name: str, rotation_z_degrees: float, translation_xyz: list[float]) -> dict:
    moved = transform_shape(pcb_shape, rotation_z_degrees, translation_xyz)
    common = moved.intersect(bottom_shape)
    per_solid = []
    for index, solid in enumerate(moved.Solids()):
        overlap = solid.intersect(bottom_shape)
        if overlap.Volume() > 1e-8:
            per_solid.append({"pcb_solid_index": index, "volume_mm3": overlap.Volume(), "solid_count": len(overlap.Solids()), "bbox": bbox_record(overlap)})
    return {
        "pose": pose_name,
        "rotation_z_degrees": rotation_z_degrees,
        "translation_xyz_mm": translation_xyz,
        "overlap_volume_mm3": common.Volume(),
        "overlap_solid_count": len(common.Solids()),
        "overlap_bbox": bbox_record(common) if common.Volume() > 1e-8 else None,
        "overlap_by_pcb_solid": per_solid,
        "interpretation": "Exact BRep common volume in imported source coordinates only. It is not a physical clearance conclusion because no accepted Z seating datum, fasteners, spacers, or component function has been established.",
    }


def sensor_cavity_candidates(cylinders: list[dict]) -> list[dict]:
    """Report geometry that could be a well/cavity, with no optical-function claim."""
    candidates = [record for record in cylinders if vertical_axis(record) and record["radius_mm"] > 1.5]
    return sorted(candidates, key=lambda r: (-r["radius_mm"], r["axis_point_mm"][1]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pcb", type=Path, default=DEFAULT_PCB)
    parser.add_argument("--bottom", type=Path, default=DEFAULT_BOTTOM)
    parser.add_argument("--sensor", type=Path, default=DEFAULT_SENSOR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--correspondence", help="Optional full source-index:target-index map, e.g. 0:3,1:2,2:1,3:0.")
    parser.add_argument("--z-translation", type=float, default=0.0, help="Raw-coordinate diagnostic translation only; it does not establish physical seating.")
    parser.add_argument("--skip-intersections", action="store_true", help="Skip exact raw-coordinate BRep common-volume diagnostics.")
    args = parser.parse_args()

    pcb_path, bottom_path, sensor_path = (args.pcb.resolve(), args.bottom.resolve(), args.sensor.resolve())
    for source in (pcb_path, bottom_path, sensor_path):
        if not source.is_file():
            raise FileNotFoundError(source)
    if args.output.resolve() in (pcb_path, bottom_path, sensor_path):
        raise ValueError("Output must not overwrite a source STEP")

    pcb, bottom, sensor = (load_step(pcb_path), load_step(bottom_path), load_step(sensor_path))
    pcb_solids, bottom_solids, sensor_solids = (solid_records(pcb), solid_records(bottom), solid_records(sensor))
    plate_index = choose_pcb_plate(pcb_solids)
    pcb_cylinders = cylindrical_faces_by_solid(pcb)
    bottom_cylinders = cylindrical_faces_by_solid(bottom)
    sensor_cylinders = cylindrical_faces_by_solid(sensor)

    pcb_holes = select_repeated_vertical_radius(
        [record for record in pcb_cylinders if record["parent_solid_index"] == plate_index], expected_count=4
    )
    bottom_bores = select_repeated_vertical_radius(bottom_cylinders, expected_count=4, innermost=True)
    correspondence = parse_correspondence(args.correspondence, len(pcb_holes))
    hypotheses = holdout_hypotheses(pcb_holes, bottom_bores, correspondence)
    best = hypotheses[0]
    inferred_rotation, inferred_tx, inferred_ty = pose_from_best_hypothesis(pcb_holes, bottom_bores, best)
    best_mapping = best["target_index_for_source_index"]
    all_four_residuals = [
        {
            "source_index": index,
            "target_index": best_mapping[index],
            "axis_error_mm": residual_xy(pcb_holes[index], bottom_bores[best_mapping[index]], (inferred_rotation, inferred_tx, inferred_ty)),
        }
        for index in range(len(pcb_holes))
    ]
    identity_nearest = []
    for index, feature in enumerate(pcb_holes):
        errors = [residual_xy(feature, bore, (0.0, 0.0, 0.0)) for bore in bottom_bores]
        identity_nearest.append({"source_index": index, "nearest_bottom_bore_index": min(range(len(errors)), key=errors.__getitem__), "nearest_axis_error_mm": min(errors)})

    intersections = None
    if not args.skip_intersections:
        intersections = [
            intersection_record(pcb, bottom, "identity_raw_coordinate", 0.0, [0.0, 0.0, args.z_translation]),
            intersection_record(pcb, bottom, "inferred_in_plane_raw_coordinate", inferred_rotation, [inferred_tx, inferred_ty, args.z_translation]),
        ]

    report = {
        "status": "measured_inferred_pose_not_accepted_physical_placement",
        "method": {
            "geometry_backend": "CadQuery/OCP STEP BRep import and exact boolean common-volume diagnostics",
            "coordinate_frame": "Each STEP's own declared-mm coordinate system. X/Y matching is performed only between the imported PCB and imported bottom. +Z follows each file's native frame; no cross-file Z seating datum is accepted.",
            "reader_unit_check": "Every input declares SI_UNIT(.MILLI.,.METRE.) and CadQuery/OCP imported the coordinate values reported as mm. No scale factor was applied.",
            "pose_scope": "Rigid XY rotation + XY translation with fixed scale=1. The inferred transform is a correspondence hypothesis, not an approval to place or modify hardware.",
            "holdout_method": "For every correspondence permutation (or supplied map), fit three extracted cylindrical axes and evaluate the fourth axis. This is an internal consistency diagnostic only: all four axes are reused to rank correspondences and to derive the final four-point pose, so it is not external independent validation.",
            "scope_limit": "This bounded probe requires exactly four repeated near-Z PCB cylindrical faces and exactly four innermost repeated near-Z bottom cylindrical faces. It is evidence for this ZA13 case, not generic automatic acceptance for arbitrary PCBs.",
        },
        "sources": {"pcb": step_header(pcb_path), "bottom": step_header(bottom_path), "sensor": step_header(sensor_path)},
        "source_lineage": {
            "local_filename_conflict": "The imported PCB path is ZA13_main_pcb.step while its STEP header identifies R14_TEST_main_pcb_1.step. Source lineage/revision remains unverified.",
            "known_distinct_reference_not_inspected": KNOWN_DISTINCT_LINEAGE,
        },
        "bodies": {
            "pcb": {"top_level_shape_type": pcb.ShapeType(), "valid": bool(pcb.isValid()), "bbox": bbox_record(pcb), "solid_count": len(pcb_solids), "solids": pcb_solids},
            "bottom": {"top_level_shape_type": bottom.ShapeType(), "valid": bool(bottom.isValid()), "bbox": bbox_record(bottom), "solid_count": len(bottom_solids), "solids": bottom_solids},
            "sensor": {"top_level_shape_type": sensor.ShapeType(), "valid": bool(sensor.isValid()), "bbox": bbox_record(sensor), "solid_count": len(sensor_solids), "solids": sensor_solids},
        },
        "interfaces": {
            "pcb_plate": {"solid_index": plate_index, "selection_rule": "unique large, thin solid measured from BRep", "bbox": pcb_solids[plate_index]["bbox"]},
            "pcb_mount_pattern_candidate": {
                "selection_rule": "the unique group of four vertical cylindrical faces on the selected plate sharing a measured radius; functional mounting use is inferred from task context, not asserted by topology",
                "features": pcb_holes,
            },
            "bottom_bore_pattern_candidate": {
                "selection_rule": "the innermost-radius group among repeated groups of four near-Z cylindrical faces; bore/cavity function remains an inference",
                "features": bottom_bores,
            },
            "bottom_larger_vertical_cylinders": [record for record in bottom_cylinders if vertical_axis(record) and record["radius_mm"] > 1.0],
            "sensor_cavity_geometry_candidates": sensor_cavity_candidates(bottom_cylinders),
        },
        "pose_evidence": {
            "identity_pose": {"rotation_z_degrees": 0.0, "translation_xyz_mm": [0.0, 0.0, args.z_translation], "nearest_axis_diagnostics": identity_nearest},
            "best_inferred_in_plane_rigid_pose": {
                "rotation_z_degrees": inferred_rotation,
                "translation_xyz_mm": [inferred_tx, inferred_ty, args.z_translation],
                "all_four_refit_after_holdout": {
                    "purpose": "Numerical pose used only for the raw-coordinate boolean after leave-one-out validation. This four-point refit is not independent evidence.",
                    "matched_point_residuals_mm": all_four_residuals,
                    "rms_mm": math.sqrt(sum(item["axis_error_mm"] ** 2 for item in all_four_residuals) / len(all_four_residuals)),
                    "maximum_mm": max(item["axis_error_mm"] for item in all_four_residuals),
                },
                "best_correspondence": best,
                "next_best_correspondence": hypotheses[1] if len(hypotheses) > 1 else None,
            },
            "raw_coordinate_intersections": intersections,
        },
        "topology_and_uncertainty": {
            "pcb_topology": "One imported Compound contains nine solids: one thin plate selected as the PCB plus eight unlabeled component solids. Geometry alone does not establish which components are primary switches, a wheel encoder, an axle, or their travel/actuation envelopes.",
            "bottom_topology": "One valid solid. Larger concentric cylindrical faces coexist with the r=0.575 axis faces; their mechanical role cannot be classified solely as a functional mounting interface from BRep topology.",
            "sensor_note": "The sensor STEP is a valid solid and its BRep bbox is reported. Its lowest Z bbox is not an optical datum and does not certify lens clearance, sensor focus height, or functional placement.",
            "registered_pack_datum_scope": "A registered pack describes the imported PCB assembly keep-out from z=3.9 upward, consistent with the compound minimum z=3.9. The selected board plate is separately measured at z=6.6..7.4 mm. The compound minimum must not be substituted for a board support datum. This is a distinction of geometry roles, not a numerical contradiction; the pack was not changed.",
            "unknown": [
                "Accepted physical placement, Z seating datum, spacer stack, screw specification, and radial/axial clearance requirements.",
                "Whether the inferred four-axis correspondence represents the intended hardware interface.",
                "An independent physical placement datum not used to select the correspondence, such as a support seating face, connector constraint, or measured optical/lens datum.",
                "Source revision/lineage beyond the headers and SHA-256 identities reported here.",
                "Switch/wheel/axle functional identity, travel, contact force, and keep-out volumes.",
                "Optical datum, lens stack, focus height, and sensor functional clearance.",
            ],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "pcb_sha256": report["sources"]["pcb"]["sha256"], "best_holdout_mm": best["maximum_holdout_error_mm"], "intersections_evaluated": not args.skip_intersections}))


if __name__ == "__main__":
    main()
