"""STEP -> GLB worker. Run with an interpreter that has OCP (OpenCascade), numpy and trimesh.

Usage: python step_to_glb.py in.step out.glb [linear_deflection_mm] [angular_deflection_rad]
Reads every solid/shell, meshes the B-rep faces and writes one GLB (units unchanged).
Prints one JSON line: faces, triangles, bbox.
"""
import json
import sys

import numpy as np
import trimesh
from OCP.BRep import BRep_Tool
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS


def main():
    src, dst = sys.argv[1], sys.argv[2]
    lin = float(sys.argv[3]) if len(sys.argv) > 3 else 0.05
    ang = float(sys.argv[4]) if len(sys.argv) > 4 else 0.3
    rd = STEPControl_Reader()
    if rd.ReadFile(src) != IFSelect_RetDone:
        sys.exit("cannot read STEP")
    rd.TransferRoots()
    shape = rd.OneShape()
    BRepMesh_IncrementalMesh(shape, lin, False, ang, True)

    verts, tris, off, nfaces = [], [], 0, 0
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        exp.Next()
        if tri is None:
            continue
        nfaces += 1
        trsf = loc.Transformation()
        n = tri.NbNodes()
        pts = np.empty((n, 3))
        for i in range(1, n + 1):
            p = tri.Node(i).Transformed(trsf)
            pts[i - 1] = (p.X(), p.Y(), p.Z())
        rev = face.Orientation() == TopAbs_REVERSED
        t = np.empty((tri.NbTriangles(), 3), dtype=np.int64)
        for i in range(1, tri.NbTriangles() + 1):
            a, b, c = tri.Triangle(i).Get()
            t[i - 1] = (a, c, b) if rev else (a, b, c)
        verts.append(pts)
        tris.append(t - 1 + off)
        off += n
    if not verts:
        sys.exit("no triangulated faces")
    m = trimesh.Trimesh(np.vstack(verts), np.vstack(tris), process=False)
    with open(dst, "wb") as f:
        f.write(m.export(file_type="glb"))
    print(json.dumps({"faces": nfaces, "triangles": int(len(m.faces)),
                      "bbox": [round(float(x), 4) for x in m.bounds.ravel()]}))


if __name__ == "__main__":
    main()
