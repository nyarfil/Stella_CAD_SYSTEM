"""STEP -> three-cad-viewer `Shapes` JSON (data format v3). Needs OCP + numpy.

Usage: python step_to_shapes.py in.step out.json [linear_deflection_mm] [angular_deflection_rad]
Keeps the STEP assembly tree, instance names, locations and colours (XCAF). Every face keeps its own
triangle range (triangles_per_face) and every edge its segment range (segments_per_edge), so the
viewer can pick faces/edges. Units are unchanged.
"""
import json
import sys
from pathlib import Path

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.GCPnts import GCPnts_QuasiUniformDeflection
from OCP.IFSelect import IFSelect_RetDone
from OCP.Quantity import Quantity_Color
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED, TopAbs_VERTEX
from OCP.TopExp import TopExp
from OCP.TopLoc import TopLoc_Location
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.TopoDS import TopoDS
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

PALETTE = ["#c9d1dc", "#e8b024", "#6fa8dc", "#93c47d", "#e06666", "#b4a7d6", "#f6b26b", "#76a5af"]


def label_name(label):
    attr = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attr):
        return attr.Get().ToExtString()
    return ""


def label_color(ct, *labels):
    for lab in labels:
        if lab is None:
            continue
        for kind in (XCAFDoc_ColorType.XCAFDoc_ColorSurf, XCAFDoc_ColorType.XCAFDoc_ColorGen):
            c = Quantity_Color()
            try:
                ok = ct.GetColor(lab, kind, c)
            except TypeError:
                ok = False
            if ok:
                return "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in (c.Red(), c.Green(), c.Blue()))
        # some OCP builds only expose the shape-based overload
        try:
            shp = XCAFDoc_ShapeTool.GetShape_s(lab)
            for kind in (XCAFDoc_ColorType.XCAFDoc_ColorSurf, XCAFDoc_ColorType.XCAFDoc_ColorGen):
                c = Quantity_Color()
                if ct.GetColor(shp, kind, c):
                    return "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in (c.Red(), c.Green(), c.Blue()))
        except TypeError:
            pass
    return None


def tessellate_leaf(shape, lin):
    """Return the viewer `shape` dict for one B-rep (already carrying its world location)."""
    verts, norms, tris, tpf = [], [], [], []
    off = 0
    faces = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, faces)
    for i in range(1, faces.Extent() + 1):
        face = TopoDS.Face_s(faces.FindKey(i))
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is None:
            tpf.append(0)
            continue
        trsf = loc.Transformation()
        n = tri.NbNodes()
        pts = np.empty((n, 3))
        for k in range(1, n + 1):
            p = tri.Node(k).Transformed(trsf)
            pts[k - 1] = (p.X(), p.Y(), p.Z())
        rev = face.Orientation() == TopAbs_REVERSED
        m = tri.NbTriangles()
        t = np.empty((m, 3), dtype=np.int64)
        for k in range(1, m + 1):
            a, b, c = tri.Triangle(k).Get()
            t[k - 1] = (a - 1, c - 1, b - 1) if rev else (a - 1, b - 1, c - 1)
        fn = np.cross(pts[t[:, 1]] - pts[t[:, 0]], pts[t[:, 2]] - pts[t[:, 0]])
        vn = np.zeros((n, 3))
        for j in range(3):
            np.add.at(vn, t[:, j], fn)
        ln = np.linalg.norm(vn, axis=1, keepdims=True)
        vn = np.divide(vn, ln, out=np.zeros_like(vn), where=ln > 1e-12)
        verts.append(pts)
        norms.append(vn)
        tris.append(t + off)
        tpf.append(int(m))
        off += n

    edges_pts, spe = [], []
    emap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_EDGE, emap)
    for i in range(1, emap.Extent() + 1):
        edge = TopoDS.Edge_s(emap.FindKey(i))
        try:
            ad = BRepAdaptor_Curve(edge)
            d = GCPnts_QuasiUniformDeflection(ad, lin * 2)
            if not d.IsDone() or d.NbPoints() < 2:
                spe.append(0)
                continue
            line = [(d.Value(k).X(), d.Value(k).Y(), d.Value(k).Z()) for k in range(1, d.NbPoints() + 1)]
        except Exception:
            spe.append(0)
            continue
        for a, b in zip(line[:-1], line[1:]):
            edges_pts.extend([a, b])
        spe.append(len(line) - 1)

    vmap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_VERTEX, vmap)
    objv = []
    for i in range(1, vmap.Extent() + 1):
        p = BRep_Tool.Pnt_s(TopoDS.Vertex_s(vmap.FindKey(i)))
        objv.extend([p.X(), p.Y(), p.Z()])

    V = np.vstack(verts) if verts else np.zeros((0, 3))
    N = np.vstack(norms) if norms else np.zeros((0, 3))
    T = np.vstack(tris) if tris else np.zeros((0, 3), dtype=np.int64)
    E = np.array(edges_pts).reshape(-1, 3) if edges_pts else np.zeros((0, 3))
    return {
        "vertices": np.round(V, 4).ravel().tolist(),
        "triangles": T.ravel().tolist(),
        "normals": np.round(N, 4).ravel().tolist(),
        "edges": np.round(E, 4).ravel().tolist(),
        "obj_vertices": np.round(objv, 4).tolist(),
        "face_types": [0] * len(tpf),
        "edge_types": [0] * len(spe),
        "triangles_per_face": tpf,
        "segments_per_edge": spe,
    }, V


def main():
    src, dst = sys.argv[1], sys.argv[2]
    lin = float(sys.argv[3]) if len(sys.argv) > 3 else 0.05
    ang = float(sys.argv[4]) if len(sys.argv) > 4 else 0.3
    stem = Path(src).stem

    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    app.NewDocument(TCollection_ExtendedString("MDTV-XCAF"), doc)
    rd = STEPCAFControl_Reader()
    rd.SetColorMode(True)
    rd.SetNameMode(True)
    if rd.ReadFile(src) != IFSelect_RetDone:
        sys.exit("cannot read STEP")
    if not rd.Transfer(doc):
        sys.exit("cannot transfer STEP")
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    ct = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())

    free = TDF_LabelSequence()
    st.GetFreeShapes(free)
    for i in range(1, free.Length() + 1):
        BRepMesh_IncrementalMesh(XCAFDoc_ShapeTool.GetShape_s(free.Value(i)), lin, False, ang, True)

    counter = [0]
    allv = []

    def build(label, loc, path, inherited_color):
        name = label_name(label) or f"part{counter[0]}"
        counter[0] += 1
        node_id = f"{path}/{name}_{counter[0]}"
        color = label_color(ct, label) or inherited_color
        if XCAFDoc_ShapeTool.IsAssembly_s(label):
            comps = TDF_LabelSequence()
            XCAFDoc_ShapeTool.GetComponents_s(label, comps)
            parts = []
            for k in range(1, comps.Length() + 1):
                comp = comps.Value(k)
                ref = TDF_Label()
                if XCAFDoc_ShapeTool.IsReference_s(comp) and XCAFDoc_ShapeTool.GetReferredShape_s(comp, ref):
                    cloc = loc.Multiplied(XCAFDoc_ShapeTool.GetLocation_s(comp))
                    nm = label_name(comp) or label_name(ref)
                    sub = build(ref, cloc, node_id, label_color(ct, comp) or color)
                    if nm:
                        sub["name"] = nm
                    parts.append(sub)
            return {"version": 3, "name": name, "id": node_id, "parts": parts, "loc": [[0, 0, 0], [0, 0, 0, 1]]}
        shape = XCAFDoc_ShapeTool.GetShape_s(label).Located(loc)
        geo, V = tessellate_leaf(shape, lin)
        if len(V):
            allv.append(V)
        return {
            "version": 3, "id": node_id, "name": name, "type": "shapes", "subtype": "solid", "shape": geo,
            "state": [1, 1], "color": color or PALETTE[counter[0] % len(PALETTE)], "alpha": 1.0,
            "texture": None, "loc": [[0, 0, 0], [0, 0, 0, 1]], "renderback": False, "accuracy": None, "bb": None,
        }

    roots = [build(free.Value(i), TopLoc_Location(), "/" + stem, None) for i in range(1, free.Length() + 1)]
    A = np.vstack(allv) if allv else np.zeros((1, 3))
    lo, hi = A.min(axis=0), A.max(axis=0)
    data = {
        "version": 3, "name": stem, "id": "/" + stem, "parts": roots, "loc": [[0, 0, 0], [0, 0, 0, 1]],
        "normal_len": 0,
        "bb": {"xmin": float(lo[0]), "xmax": float(hi[0]), "ymin": float(lo[1]), "ymax": float(hi[1]),
               "zmin": float(lo[2]), "zmax": float(hi[2])},
    }
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    print(json.dumps({"leaves": counter[0], "bbox": [float(x) for x in (*lo, *hi)]}))


if __name__ == "__main__":
    main()
