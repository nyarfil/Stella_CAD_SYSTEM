"""Read-only STEP intake; geometry presence is not functional readiness."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import cadquery as cq
from OCP.Interface import Interface_Static


def inspect(source: Path) -> dict:
    payload = source.read_bytes()
    text = payload.decode("utf-8", errors="replace")
    obj = cq.importers.importStep(str(source))
    target_unit = Interface_Static.CVal_s("xstep.cascade.unit")
    if target_unit.upper() != "MM":
        raise RuntimeError(f"Reader target unit is {target_unit!r}; cannot label measurements mm.")
    rows = []
    for index, solid in enumerate(obj.solids().vals()):
        box = solid.BoundingBox()
        rows.append({
            "solid_index": index, "valid": solid.isValid(),
            "volume_mm3": solid.Volume(),
            "bbox_min_mm": [box.xmin, box.ymin, box.zmin],
            "bbox_max_mm": [box.xmax, box.ymax, box.zmax],
            "functional_identity": "unresolved; not inferred from index",
        })
    if source.read_bytes() != payload:
        raise RuntimeError("Input changed during inspection; discard this measurement.")
    return {
        "source_name": source.name,
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "source_bytes": len(payload), "header": text.split("ENDSEC;")[0],
        "unit_declarations": re.findall(
            r"#[0-9]+\s*=\s*[^;]*(?:SI_UNIT|CONVERSION_BASED_UNIT)[^;]*;", text),
        "coordinate_basis": "CadQuery STEP reader normalized millimetres; declarations listed separately, not scanner calibration",
        "reader_target_unit": target_unit,
        "solid_count": len(rows), "solids": rows,
        "role": "candidate hardware CAD; not registered ready pack",
        "limits": [
            "No physical hardware version confirmed.",
            "No scan origin declared for this CAD.",
            "No functional identity, switch specification, optical datum or accepted placement inferred.",
            "Shape validity alone does not certify manufactured part or completed mouse.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.source.resolve() == args.output.resolve() or args.output.suffix.lower() != ".json":
        parser.error("Output must be a separate JSON file.")
    result = inspect(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"source_sha256": result["source_sha256"],
                      "solid_count": result["solid_count"],
                      "all_valid": bool(result["solids"]) and all(r["valid"] for r in result["solids"]),
                      "output": str(args.output)}))


if __name__ == "__main__":
    main()
