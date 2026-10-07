"""Measure vertical material chords in the ZS-F1 primary click reference.

These are samples along assembled Z, not normal wall thickness, flexure length,
actuation travel, or force measurements. The supplied mounting pose is a candidate.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from inspect_stl import RECORD


def hits(triangles, x, y):
    """Barycentric XY projection of triangle intersections with a vertical ray."""
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    ab, ac = b - a, c - a
    den = ab[:, 0] * ac[:, 1] - ab[:, 1] * ac[:, 0]
    valid = np.abs(den) > 1e-10
    u = np.full(len(den), np.nan)
    v = np.full(len(den), np.nan)
    u[valid] = ((x-a[valid, 0])*ac[valid, 1] - (y-a[valid, 1])*ac[valid, 0])/den[valid]
    v[valid] = (ab[valid, 0]*(y-a[valid, 1]) - ab[valid, 1]*(x-a[valid, 0]))/den[valid]
    inside = valid & (u >= -1e-8) & (v >= -1e-8) & (u+v <= 1+1e-8)
    z = np.sort(a[inside, 2] + u[inside]*ab[inside, 2] + v[inside]*ac[inside, 2])
    unique = []
    for value in z:
        if not unique or value - unique[-1] > 1e-5:
            unique.append(float(value))
    return unique


def measure(source, pose):
    raw = source.read_bytes()
    if len(raw) < 84:
        raise ValueError("Binary STL header missing")
    count = int.from_bytes(raw[80:84], "little")
    if len(raw) != 84 + count * RECORD.itemsize:
        raise ValueError("Unsupported binary STL")
    source_hash = hashlib.sha256(raw).hexdigest()
    expected = [(name, digest) for name, digest in pose["sources"].items()
                if Path(name).resolve() == source.resolve() and Path(name).name.lower() == "triggers-solid.stl"]
    if len(expected) != 1 or expected[0][1] != source_hash:
        raise ValueError("This ZS-F1 inspection requires the exact trigger source path and hash bound to the pose report")
    triangles = np.frombuffer(raw, dtype=RECORD, count=count, offset=84)["vertices"].astype(float)
    rotation, translation = np.asarray(pose["rotation"], dtype=float), np.asarray(pose["translation"], dtype=float)
    if (rotation.shape != (3,3) or translation.shape != (3,) or
            not np.allclose(rotation.T @ rotation, np.eye(3)) or not np.isclose(np.linalg.det(rotation), 1)):
        raise ValueError("Expected a rigid proper transform")
    triangles = triangles @ rotation.T + translation
    if not np.isfinite(triangles).all():
        raise ValueError("Nonfinite transformed geometry")
    samples = []
    for x in (-17.3, -15.0, -13.0, 13.0, 15.0, 17.3):
        for y in (0.0, -2.0, -4.0, -6.0, -8.0, -10.0, -12.0, -16.0, -20.0, -26.0, -34.0, -42.0, -50.0, -56.0):
            z = hits(triangles, x, y)
            intervals = [[z[i],z[i+1]] for i in range(0, len(z)-1, 2)] if len(z)%2 == 0 else []
            samples.append({"x":x,"y":y,"z_intersections":z,
                            "status":"even_crossings_candidate" if z and len(z)%2 == 0 else "no_hit" if not z else "ambiguous_odd_crossings",
                            "material_intervals":intervals,"vertical_chords":[hi-lo for lo,hi in intervals]})
    return {"schema_version":1,"status":"reference_vertical_chords_not_flexure_verification",
            "source_file":source.name,"source_sha256":source_hash,
            "measurement_script_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "units":"unspecified STL coordinate units", "rotation":rotation.tolist(),"translation":translation.tolist(),
            "method":"Vertical line intersections with XY-projected triangles; deduplicate Z crossings within 1e-5; pair even crossings under a closed non-self-intersecting mesh assumption.",
            "sampling":"Six fixed X lines and 14 Y stations in the mounting-pose candidate; not an exhaustive minimum-thickness analysis.",
            "assumptions":["The supplied candidate mounting transform is used, not a physically verified assembly.","Closed non-self-intersecting material boundaries are required for crossing parity."],
            "not_verified":["normal wall thickness","flexure or pivot location","material stiffness or fatigue","click force or travel","switch contact and physical fit"],"samples":samples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path)
    parser.add_argument("pose",type=Path)
    parser.add_argument("report",type=Path)
    args = parser.parse_args()
    source,output = args.source.resolve(strict=True),args.report.resolve()
    preserved_root = source.parent.parent if source.parent.name.lower() == "solid" else source.parent
    if output == args.pose.resolve() or output == source or output == preserved_root or preserved_root in output.parents:
        parser.error("Output must be outside the preserved source directory")
    pose_raw = args.pose.read_bytes()
    result = measure(source,json.loads(pose_raw))
    result["pose_report_sha256"] = hashlib.sha256(pose_raw).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"samples":len(result["samples"]),"odd_crossings":sum(s["status"]=="ambiguous_odd_crossings" for s in result["samples"]),"report":str(output)}))


if __name__ == "__main__":
    main()
