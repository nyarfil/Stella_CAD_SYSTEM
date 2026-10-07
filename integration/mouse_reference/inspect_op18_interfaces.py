"""Read-only XCAF/BRep interface evidence for the fixed OP18K v2 STEP.

Run with the cadgen 0.6.5 interpreter named in the report.  The inspection
uses occurrence labels and source-bound selectors; it never identifies a part
by global compound/solid enumeration and never writes source geometry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

from cadgen import read_scene


DEFAULT_STEP = Path(r"V:\mouse\op18kv2pcb_251212.step")
DEFAULT_OUTPUT = Path(r"E:\aiwork\Stella_CAD_SYSTEM\docs\examples\op18_hardware_interfaces.json")
EXPECTED_SHA256 = "94e3e7bcd46503b0c135d2e229bf7d35d33ca935456e67450282dceb3cc9be4f"
EXPECTED_LABELS = ("lens:1", "around lens:1", "sensor:1", "main_pcb:1", "wheel:1", "main_switch:1", "side_switch:1", "bush:1")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def vector(value) -> list[float]:
    return [float(value.X), float(value.Y), float(value.Z)]


def bbox(shape) -> dict:
    box = shape.bounding_box()
    return {
        "minimum_mm": vector(box.min),
        "maximum_mm": vector(box.max),
        "extent_mm": vector(box.size),
    }


def header_identity(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    name = re.search(r"FILE_NAME\(\s*/\* name \*/\s*'([^']*)'.*?/\* time_stamp \*/\s*'([^']*)'", text, re.DOTALL)
    products = re.findall(r"PRODUCT\('([^']*)','([^']*)'", text)
    units = sorted(set(re.findall(r"SI_UNIT\(\.(MILLI|CENTI|DECI|KILO)\.\s*,\s*\.METRE\.\)", text)))
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "step_file_name": name.group(1) if name else None,
        "step_timestamp": name.group(2) if name else None,
        "declared_length_unit": "mm" if "MILLI" in units else "not deterministically located",
        "products": [{"id": product_id, "description": description} for product_id, description in products],
    }


def occurrence_shapes(scene, label: str) -> tuple[object, list[tuple[str, object]]]:
    leaves = [leaf for leaf in scene.leaves() if leaf.label == label]
    if len(leaves) != 1:
        raise ValueError(f"Expected exactly one XCAF occurrence named {label!r}, got {len(leaves)}")
    leaf = leaves[0]
    entities = list(leaf.entities("shape"))
    if not entities:
        raise ValueError(f"No BRep shape entities for {label}")
    return leaf, [(entity.ref, entity.shape()) for entity in entities]


def shape_record(selector: str, shape) -> dict:
    return {
        "selector": selector,
        "valid": bool(shape.is_valid),
        "bbox": bbox(shape),
        "solid_count": len(shape.solids()),
        "face_count": len(shape.faces()),
        "edge_count": len(shape.edges()),
        "volume_mm3": float(shape.volume),
    }


def is_plane(face) -> bool:
    return str(face.geom_type).endswith("PLANE")


def is_cylinder(face) -> bool:
    return str(face.geom_type).endswith("CYLINDER")


def plane_record(face) -> dict:
    return {"area_mm2": float(face.area), "center_mm": vector(face.center()), "normal": vector(face.normal_at()), "bbox": bbox(face)}


def cylindrical_record(face) -> dict:
    cylinder = face.geom_adaptor().Cylinder()
    axis = cylinder.Axis()
    return {
        "radius_mm": float(cylinder.Radius()),
        "axis_point_mm": [float(v) for v in axis.Location().Coord()],
        "axis_direction": [float(v) for v in axis.Direction().Coord()],
        "axis_tilt_from_z_degrees": math.degrees(math.acos(min(1.0, abs(float(axis.Direction().Coord()[2]))))),
        "area_mm2": float(face.area),
        "bbox": bbox(face),
        "edge_lengths_mm": [{"geometry": str(edge.geom_type), "length_mm": float(edge.length)} for edge in face.edges()],
    }


def thin_large_plate(records: list[tuple[str, object]], minimum_xy: tuple[float, float]) -> tuple[str, object]:
    candidates = []
    for selector, shape in records:
        extent = bbox(shape)["extent_mm"]
        if 0.2 <= extent[2] <= 1.5 and extent[0] >= minimum_xy[0] and extent[1] >= minimum_xy[1]:
            candidates.append((selector, shape))
    if len(candidates) != 1:
        raise ValueError(f"Thin plate selector is not unique: {[selector for selector, _ in candidates]}")
    return candidates[0]


def radial_material_classification(face, owner_shape, probe_mm: float = 0.05) -> dict:
    """Classify a cylinder as cavity-wall or external material with solid probes.

    Full circular edges only establish a closed rim.  The two radial probes,
    displaced from an actual point on the face, establish where BRep material
    lies.  They avoid assigning a mounting-hole role to an exterior boss wall.
    """
    cylinder = face.geom_adaptor().Cylinder()
    axis = cylinder.Axis()
    point = axis.Location().Coord()
    direction = axis.Direction().Coord()
    center = face.center()
    offset = [center.X - point[0], center.Y - point[1], center.Z - point[2]]
    axial = sum(offset[index] * direction[index] for index in range(3))
    radial = [offset[index] - axial * direction[index] for index in range(3)]
    radial_length = math.sqrt(sum(component * component for component in radial))
    if radial_length <= 1e-9:
        return {"classification": "ambiguous: face center lies on cylinder axis", "probe_mm": probe_mm}
    radial = [component / radial_length for component in radial]
    axis_at_face = [point[index] + axial * direction[index] for index in range(3)]
    radius = float(cylinder.Radius())
    inward = tuple(axis_at_face[index] + radial[index] * (radius - probe_mm) for index in range(3))
    outward = tuple(axis_at_face[index] + radial[index] * (radius + probe_mm) for index in range(3))
    inward_material, outward_material = bool(owner_shape.is_inside(inward)), bool(owner_shape.is_inside(outward))
    if not inward_material and outward_material:
        classification = "cavity-wall: material is radially outside; closed rim may be a through-hole or blind cavity, not distinguished by this probe"
    elif inward_material and not outward_material:
        classification = "external cylindrical material: closed rim is not a hole"
    else:
        classification = "ambiguous radial material state; do not use as a mounting interface"
    normal = face.normal_at()
    normal_radial_dot = sum(vector(normal)[index] * radial[index] for index in range(3))
    return {
        "classification": classification,
        "probe_mm": probe_mm,
        "inward_probe_mm": list(inward),
        "outward_probe_mm": list(outward),
        "inward_probe_in_material": inward_material,
        "outward_probe_in_material": outward_material,
        "face_normal_radial_dot": normal_radial_dot,
    }


def cylindrical_pattern(selector: str, plate, expected_pattern_count: int) -> dict:
    """Select a repeated cylindrical pattern from topology, then classify material."""
    records = []
    for face in plate.faces():
        if not is_cylinder(face):
            continue
        record = cylindrical_record(face)
        axis = record["axis_direction"]
        if abs(axis[0]) > 1e-6 or abs(axis[1]) > 1e-6 or abs(abs(axis[2]) - 1.0) > 1e-6:
            continue
        circumference = 2.0 * math.pi * record["radius_mm"]
        circle_edges = [item["length_mm"] for item in record["edge_lengths_mm"] if item["geometry"].endswith("CIRCLE")]
        record["source_selector"] = selector
        record["full_circular_boundary_count"] = sum(abs(length - circumference) <= 1e-5 for length in circle_edges)
        record["has_full_circular_rims"] = len(circle_edges) >= 2 and record["full_circular_boundary_count"] >= 2
        record["radial_material"] = radial_material_classification(face, plate)
        records.append(record)
    groups = {}
    for record in records:
        groups.setdefault(round(record["radius_mm"], 6), []).append(record)
    candidates = [(radius, group) for radius, group in groups.items() if len(group) == expected_pattern_count]
    if not candidates:
        raise ValueError(f"No repeated mounting pattern of {expected_pattern_count} vertical cylindrical faces for {selector}")
    best_full_count = max(sum(item["has_full_circular_rims"] for item in group) for _, group in candidates)
    candidates = [(radius, group) for radius, group in candidates if sum(item["has_full_circular_rims"] for item in group) == best_full_count]
    if len(candidates) != 1:
        raise ValueError(f"Ambiguous repeated mounting pattern for {selector}: {[radius for radius, _ in candidates]}")
    radius, selected = candidates[0]
    full = [record for record in selected if record["has_full_circular_rims"]]
    nonfull = [record for record in selected if not record["has_full_circular_rims"]]
    return {
        "selection_rule": "Repeated near-Z cylindrical face group with requested count; ties resolve by the greatest count of BRep full-circle rims. Rim closure is subsequently separated from radial material classification.",
        "nominal_radius_mm": radius,
        "pattern_face_count": len(selected),
        "closed_circular_rims": full,
        "nonfull_cylindrical_faces": nonfull,
        "slot_classification": "No elongated slot is asserted. A non-full cylinder is reported as an edge-clipped cylindrical face unless tangent-wall topology is separately measured.",
    }


def z_support_planes(selector: str, shape) -> list[dict]:
    records = []
    for face in shape.faces():
        if is_plane(face) and abs(face.normal_at().Z) > 0.999999:
            item = plane_record(face)
            item["source_selector"] = selector
            records.append(item)
    return sorted(records, key=lambda item: (item["center_mm"][2], item["normal"][2]))


def top_upward_face(selector: str, shape) -> dict | None:
    candidates = []
    for face in shape.faces():
        if is_plane(face) and face.normal_at().Z > 0.999999:
            candidate = plane_record(face)
            candidate["source_selector"] = selector
            candidates.append(candidate)
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item["center_mm"][2], item["area_mm2"]))


def bottom_downward_face(selector: str, shape) -> dict | None:
    candidates = []
    for face in shape.faces():
        if is_plane(face) and face.normal_at().Z < -0.999999:
            candidate = plane_record(face)
            candidate["source_selector"] = selector
            candidates.append(candidate)
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item["center_mm"][2], -item["area_mm2"]))


def large_housing_signature(selector: str, shape) -> dict | None:
    """A geometry-only signature for comparing possible primary click housings."""
    top, bottom = top_upward_face(selector, shape), bottom_downward_face(selector, shape)
    if not top or not bottom:
        return None
    envelope = bbox(shape)
    return {
        "selector": selector,
        "bbox": envelope,
        "top_upward_face": top,
        "bottom_downward_face": bottom,
        "z_span_mm": envelope["extent_mm"][2],
    }


def select_large_housing(shapes: list[tuple[str, object]], excluded_selector: str | None = None) -> tuple[str, object, dict]:
    candidates = []
    for selector, shape in shapes:
        if selector == excluded_selector:
            continue
        signature = large_housing_signature(selector, shape)
        if signature:
            candidates.append((selector, shape, signature))
    # This ranks the BRep contact face, not an occurrence/product label.
    candidates.sort(key=lambda item: (item[2]["top_upward_face"]["area_mm2"], item[2]["z_span_mm"]), reverse=True)
    if not candidates or (len(candidates) > 1 and abs(candidates[0][2]["top_upward_face"]["area_mm2"] - candidates[1][2]["top_upward_face"]["area_mm2"]) < 1e-8):
        raise ValueError("Large primary housing cannot be selected uniquely by BRep top-contact signature")
    return candidates[0]


def match_housing_by_geometry(shapes: list[tuple[str, object]], reference: dict, excluded_selector: str) -> tuple[str, object, dict, dict]:
    """Find the source child with the closest independently measured housing signature."""
    candidates = []
    for selector, shape in shapes:
        if selector == excluded_selector:
            continue
        signature = large_housing_signature(selector, shape)
        if not signature:
            continue
        top = signature["top_upward_face"]
        bottom = signature["bottom_downward_face"]
        ref_top = reference["top_upward_face"]
        ref_bottom = reference["bottom_downward_face"]
        residual = {
            "top_face_area_difference_mm2": abs(top["area_mm2"] - ref_top["area_mm2"]),
            "top_face_z_difference_mm": abs(top["center_mm"][2] - ref_top["center_mm"][2]),
            "bottom_face_area_difference_mm2": abs(bottom["area_mm2"] - ref_bottom["area_mm2"]),
            "bottom_face_z_difference_mm": abs(bottom["center_mm"][2] - ref_bottom["center_mm"][2]),
            "z_span_difference_mm": abs(signature["z_span_mm"] - reference["z_span_mm"]),
        }
        score = sum(residual.values())
        candidates.append((score, selector, shape, signature, residual))
    candidates.sort(key=lambda item: item[0])
    if not candidates or (len(candidates) > 1 and abs(candidates[0][0] - candidates[1][0]) < 1e-8):
        raise ValueError("Main PCB large housing match is ambiguous")
    _, selector, shape, signature, residual = candidates[0]
    return selector, shape, signature, residual


def x_normal_faces(selector: str, shape) -> list[dict]:
    results = []
    for face in shape.faces():
        if is_plane(face) and abs(face.normal_at().X) > 0.999999:
            item = plane_record(face)
            item["source_selector"] = selector
            results.append(item)
    return sorted(results, key=lambda item: (-item["area_mm2"], item["normal"][0]))


def axial_cylinders(records: list[tuple[str, object]], axis_index: int) -> list[dict]:
    result = []
    for selector, shape in records:
        for face in shape.faces():
            if not is_cylinder(face):
                continue
            item = cylindrical_record(face)
            direction = item["axis_direction"]
            if abs(abs(direction[axis_index]) - 1.0) <= 1e-6 and all(abs(direction[i]) <= 1e-6 for i in range(3) if i != axis_index):
                item["source_selector"] = selector
                result.append(item)
    return result


def line_consensus(cylinders: list[dict], axis_index: int) -> dict | None:
    if not cylinders:
        return None
    points = [item["axis_point_mm"] for item in cylinders]
    average = [sum(point[i] for point in points) / len(points) for i in range(3)]
    perpendicular = [i for i in range(3) if i != axis_index]
    max_deviation = max(math.hypot(*(point[i] - average[i] for i in perpendicular)) for point in points)
    return {
        "axis": "XYZ"[axis_index],
        "mean_axis_point_mm": average,
        "maximum_perpendicular_axis_point_deviation_mm": max_deviation,
        "radii_mm": sorted(set(round(item["radius_mm"], 6) for item in cylinders)),
        "face_count": len(cylinders),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step", type=Path, default=DEFAULT_STEP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    source = args.step.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if args.output.resolve() == source:
        raise ValueError("Output must not overwrite the source STEP")
    identity = header_identity(source)
    if identity["sha256"] != EXPECTED_SHA256:
        raise ValueError("OP18 source SHA-256 differs from the fixed inspected revision")

    scene = read_scene(source)
    leaves = list(scene.leaves())
    labels = tuple(leaf.label for leaf in leaves)
    if labels != EXPECTED_LABELS:
        raise ValueError(f"Unexpected XCAF occurrence membership/order: {labels}")
    membership = []
    all_shapes = {}
    for leaf in leaves:
        _, shapes = occurrence_shapes(scene, leaf.label)
        all_shapes[leaf.label] = shapes
        membership.append({
            "occurrence_ref": leaf.ref,
            "occurrence_label": leaf.label,
            "prototype_id": leaf.prototype_id,
            "shape_records": [shape_record(selector, shape) for selector, shape in shapes],
        })

    main_pcb_selector, main_pcb_plate = thin_large_plate(all_shapes["main_pcb:1"], (20.0, 40.0))
    main_switch_selector, main_switch_plate = thin_large_plate(all_shapes["main_switch:1"], (6.0, 20.0))
    dedicated_primary_selector, dedicated_primary_shape, dedicated_primary = select_large_housing(all_shapes["main_switch:1"], main_switch_selector)
    main_primary_selector, main_primary_shape, main_primary, housing_alignment = match_housing_by_geometry(
        all_shapes["main_pcb:1"], dedicated_primary, main_pcb_selector
    )
    auxiliary_candidates = [
        (selector, shape)
        for selector, shape in all_shapes["main_switch:1"]
        if selector not in (main_switch_selector, dedicated_primary_selector)
    ]
    if len(auxiliary_candidates) != 1:
        raise ValueError("Expected exactly one non-plate, non-primary auxiliary main_switch child")
    auxiliary_selector, auxiliary_shape = auxiliary_candidates[0]
    auxiliary_contact = top_upward_face(auxiliary_selector, auxiliary_shape)
    if not auxiliary_contact:
        raise ValueError("Auxiliary main_switch child lacks an upward planar face")
    for record, classification in ((dedicated_primary["top_upward_face"], "large primary-housing top contact candidate"), (main_primary["top_upward_face"], "large primary-housing top contact candidate"), (auxiliary_contact, "auxiliary top contact candidate; not a second primary click")):
        record["classification"] = classification + "; functional click role remains unverified by BRep"
        record["proposed_roof_approach_direction"] = [0.0, 0.0, -1.0]

    wheel_x_cylinders = axial_cylinders(all_shapes["wheel:1"], 0)
    bush_y_cylinders = axial_cylinders(all_shapes["bush:1"], 1)
    side_upward = []
    side_x_faces = []
    for selector, shape in all_shapes["side_switch:1"]:
        top = top_upward_face(selector, shape)
        if top:
            top["classification"] = "topmost +Z planar face; contact function is unverified"
            side_upward.append(top)
        side_x_faces.extend(x_normal_faces(selector, shape))

    report = {
        "status": "fixed_op18k_v2_measured_interfaces_not_operationally_accepted",
        "scope": "Fixed OP18K v2 source only. No arbitrary-hardware generalization, CAD generation, source edit, mirroring, or pose mutation occurred.",
        "coordinate_frame": "Native assembly world frame after XCAF occurrence placements; values are Cadgen/OCP imported STEP coordinates in declared mm. +X/+Y/+Z are source axes, with no left/right human-use convention inferred.",
        "source": identity,
        "source_lineage_limit": "The STEP header supplies a filename and timestamp only. It does not certify physical OP18K v2 revision, electrical population, or hardware provenance.",
        "reader": {"runtime": "C:/Users/nikis/.codex/user-runtimes/cadgen-0.6.5/Scripts/python.exe", "method": "cadgen.read_scene XCAF occurrence traversal plus build123d/OCP BRep faces"},
        "assembly_membership": membership,
        "main_pcb_support": {
            "occurrence_label": "main_pcb:1",
            "plate_selector": main_pcb_selector,
            "plate_support_planes": z_support_planes(main_pcb_selector, main_pcb_plate),
            "cylindrical_pattern": cylindrical_pattern(main_pcb_selector, main_pcb_plate, expected_pattern_count=4),
            "protected_source_pose": "Preserve the exact XCAF occurrence placement and source shape; do not mirror main_pcb:1 or substitute a global-solid identity.",
        },
        "main_click_roof_support": {
            "occurrence_label": "main_switch:1",
            "plate_selector": main_switch_selector,
            "plate_support_planes": z_support_planes(main_switch_selector, main_switch_plate),
            "cylindrical_pattern": cylindrical_pattern(main_switch_selector, main_switch_plate, expected_pattern_count=2),
            "primary_contacts": [
                {"occurrence_label": "main_pcb:1", "housing_signature": main_primary, "roof_contact_face": main_primary["top_upward_face"], "role": "large primary-housing candidate carried by protected main PCB"},
                {"occurrence_label": "main_switch:1", "housing_signature": dedicated_primary, "roof_contact_face": dedicated_primary["top_upward_face"], "role": "large primary-housing candidate carried by the dedicated daughterboard occurrence"},
            ],
            "large_housing_geometry_alignment": {
                "method": "Selected independently from BRep signature: largest unique upward planar contact face in non-plate main_switch children, then closest main_pcb child by top/bottom plane areas and Z positions plus Z span.",
                "main_pcb_selector": main_primary_selector,
                "dedicated_daughterboard_selector": dedicated_primary_selector,
                "residuals": housing_alignment,
                "interpretation": "Matching top-contact area, lower contact area, Z extrema, and height are measured geometry evidence for a large-housing pair. Electrical terminal function and physical left/right naming remain unverified.",
            },
            "aux_contact": {"occurrence_label": "main_switch:1", "selector": auxiliary_selector, "contact_face": auxiliary_contact, "role": "auxiliary candidate only"},
            "roof_support_proposal": {
                "source_pose_rule": "Keep main_pcb:1 protected in its recorded XCAF pose. Keep main_switch:1 as its own source occurrence and do not mirror either occurrence. This is asymmetric: the large housing in main_pcb:1 moves only with the protected main board, while the large housing in main_switch:1 is carried by the separate thin-plate occurrence. XCAF grouping alone is not proof of electrical membership or of a physical left/right role.",
                "measured_roof_mating_plane": "Use the measured +Z plane of the selected thin click-board as the source-side datum; a new roof mate must face -Z. Its final roof location is a target-shell design decision.",
                "measured_cylindrical_boundaries": "The report records two radius-2.325 mm closed circular rims (diameter 4.650 mm) together with material-side probes. Carrier use is prohibited until those probes establish cavity-wall material rather than external cylindrical material; clearance, fastener type, and production tolerance are unspecified.",
                "contact_axis_rule": "For the two measured large-housing +Z faces, a roof feature would approach along -Z. The auxiliary face is kept separate. Stroke, preload, force, and physical left/right click labels remain unknown.",
            },
        },
        "wheel_and_bush": {
            "wheel_occurrence_label": "wheel:1",
            "wheel_x_axis_cylinders": wheel_x_cylinders,
            "wheel_coaxial_x_axis_evidence": line_consensus(wheel_x_cylinders, 0),
            "bush_occurrence_label": "bush:1",
            "bush_y_axis_cylinders": bush_y_cylinders,
            "bush_coaxial_y_axis_evidence": line_consensus(bush_y_cylinders, 1),
            "middle_click_note": "The named wheel occurrence and its X-coaxial BRep surfaces establish a geometric axis. They do not establish encoder coupling, detent, middle-click switch, travel, force, or an allowable support clearance.",
        },
        "side_switch": {
            "occurrence_label": "side_switch:1",
            "top_upward_face_candidates": side_upward,
            "x_normal_face_candidates": side_x_faces,
            "relocation_rule": "If repositioned for a left-handed target, use one rigid transform of the source occurrence and transform both points and normals. Mirroring is prohibited by this evidence package.",
            "unknown": "No functional metadata identifies which face is the button actuation face, reaction face, travel direction, or allowable enclosure. The BRep records candidate faces only.",
        },
        "lens": {
            "occurrence_label": "lens:1",
            "extent_only": membership[0]["shape_records"],
            "limit": "The lens bbox is geometry only. It is not an optical datum and does not certify sensor focus, lens seating, or clearance.",
        },
        "topology_and_unknowns": {
            "validity": "Each source-bound shape record reports BRep validity. The assembly contains 8 named XCAF occurrences and 21 source-bound leaf solids.",
            "functional_unknowns": [
                "Click, wheel, and side-button travel; preload; force; contact sequence; and required clearances.",
                "Electrical, optical, fastener, and tolerance specifications.",
                "Mapping of named main_switch child shapes to physical left/right click functions.",
                "ZA13 roof, sidewall, and shell datum relationship; these must be established against the separate shell geometry.",
            ],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "sha256": identity["sha256"], "occurrences": len(membership), "main_pcb_valid": bool(main_pcb_plate.is_valid)}))


if __name__ == "__main__":
    main()
