"""OCP helpers shared by the scan-to-CAD B-rep WORKERS (shell fit, click slots, plate side, face roles).

Imported only inside worker subprocesses (server python with OCP, extra `geometry`); the server process never imports it.
"""
from __future__ import annotations
import math
from pathlib import Path
from typing import Any
import numpy as np

from .scan_cad_common import WorkerError


def require_ocp() -> None:
    try:
        import OCP  # noqa: F401
    except ImportError as exc:
        raise WorkerError('BREP_KERNEL_UNAVAILABLE', 'OCP (extra `geometry`) is not installed in the worker python.') from exc


def clean(o: Any) -> Any:
    """JSON-safe copy: numpy -> python, NaN/inf -> None."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, np.ndarray):
        return clean(o.tolist())
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        v = float(o)
        return v if math.isfinite(v) else None
    return o


def stats(a) -> dict[str, Any]:
    a = np.asarray(a, float)
    a = a[np.isfinite(a)]
    if not len(a):
        return {'n': 0}
    return {'p50': float(np.median(a)), 'p95': float(np.percentile(a, 95)), 'max': float(a.max()), 'n': int(len(a))}


# ------------------------------------------------------------------ B-spline construction
def knots_mults(kv):
    from OCP.TColStd import TColStd_Array1OfReal, TColStd_Array1OfInteger
    u, c = np.unique(np.round(np.asarray(kv, float), 12), return_counts=True)
    a = TColStd_Array1OfReal(1, len(u))
    m = TColStd_Array1OfInteger(1, len(u))
    for k in range(len(u)):
        a.SetValue(k + 1, float(u[k]))
        m.SetValue(k + 1, int(c[k]))
    return a, m


def bsurf(P, tu, tv, p=3, q=3):
    from OCP.TColgp import TColgp_Array2OfPnt
    from OCP.gp import gp_Pnt
    from OCP.Geom import Geom_BSplineSurface
    nu, nv, _ = P.shape
    arr = TColgp_Array2OfPnt(1, nu, 1, nv)
    for i in range(nu):
        for j in range(nv):
            arr.SetValue(i + 1, j + 1, gp_Pnt(*map(float, P[i, j])))
    (ku, mu), (kv, mv) = knots_mults(tu), knots_mults(tv)
    return Geom_BSplineSurface(arr, ku, kv, mu, mv, p, q, False, False)


def interp_closed(P, prm=None):
    """Periodic interpolating B-spline curve through the closed polyline P (N,3) (first point not repeated)."""
    from OCP.TColgp import TColgp_HArray1OfPnt
    from OCP.TColStd import TColStd_HArray1OfReal
    from OCP.GeomAPI import GeomAPI_Interpolate
    from OCP.gp import gp_Pnt
    N = len(P)
    if prm is None:
        L = np.r_[0, np.cumsum(np.linalg.norm(np.diff(np.vstack([P, P[:1]]), axis=0), axis=1))]
        prm = L / L[-1]
    hP = TColgp_HArray1OfPnt(1, N)
    pa = TColStd_HArray1OfReal(1, N + 1)
    for i in range(N):
        hP.SetValue(i + 1, gp_Pnt(*map(float, P[i])))
        pa.SetValue(i + 1, float(prm[i]))
    pa.SetValue(N + 1, 1.0)
    it = GeomAPI_Interpolate(hP, pa, True, 1e-9)
    it.Perform()
    if not it.IsDone():
        raise WorkerError('BREP_INTERPOLATION_FAILED', 'Closed curve interpolation failed.')
    return it.Curve()


# ------------------------------------------------------------------ topology
def explore(sh, kind):
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_EDGE, TopAbs_SHELL
    from OCP.TopoDS import TopoDS
    t = {'solid': (TopAbs_SOLID, TopoDS.Solid_s), 'face': (TopAbs_FACE, TopoDS.Face_s), 'edge': (TopAbs_EDGE, TopoDS.Edge_s),
         'shell': (TopAbs_SHELL, TopoDS.Shell_s)}[kind]
    ex = TopExp_Explorer(sh, t[0])
    out = []
    while ex.More():
        out.append(t[1](ex.Current()))
        ex.Next()
    return out


def solids(sh):
    return explore(sh, 'solid')


def faces(sh):
    return explore(sh, 'face')


def volume(s) -> float:
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    p = GProp_GProps()
    BRepGProp.VolumeProperties_s(s, p, 1e-7, False)
    return p.Mass()


def area(f) -> float:
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    p = GProp_GProps()
    BRepGProp.SurfaceProperties_s(f, p)
    return p.Mass()


def is_valid(s) -> bool:
    from OCP.BRepCheck import BRepCheck_Analyzer
    return bool(BRepCheck_Analyzer(s).IsValid())


def bbox(s, optimal=True):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    b = Bnd_Box()
    if optimal:
        BRepBndLib.AddOptimal_s(s, b, True, False)
    else:
        BRepBndLib.Add_s(s, b)
    return np.array(b.Get())


def write_step(shape, path: Path) -> None:
    from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCP.IFSelect import IFSelect_RetDone
    w = STEPControl_Writer()
    w.Transfer(shape, STEPControl_AsIs)
    if w.Write(str(path)) != IFSelect_RetDone:
        raise WorkerError('BREP_STEP_WRITE', 'STEP write failed.', {'file': Path(path).name})


def read_step(path: Path):
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    r = STEPControl_Reader()
    if r.ReadFile(str(path)) != IFSelect_RetDone:
        raise WorkerError('BREP_STEP_READ', 'STEP read failed.', {'file': Path(path).name})
    r.TransferRoots()
    return r.OneShape()


def one_solid(path: Path, code: str):
    ss = solids(read_step(path))
    if len(ss) != 1:
        raise WorkerError(code, 'The STEP file must hold exactly one solid.', {'file': Path(path).name, 'solids': len(ss)})
    return ss[0]


def compound(shapes):
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    b = BRep_Builder()
    c = TopoDS_Compound()
    b.MakeCompound(c)
    for s in shapes:
        b.Add(c, s)
    return c


def inner_point(f):
    """A point strictly inside face f (classifier on a UV grid) and its outward normal (face orientation applied)."""
    from OCP.BRepTools import BRepTools
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_IN
    from OCP.gp import gp_Pnt2d
    a = BRepAdaptor_Surface(f)
    u0, u1, v0, v1 = BRepTools.UVBounds_s(f)
    for s in (0.5, 0.35, 0.65, 0.2, 0.8, 0.1, 0.9, 0.05, 0.95):
        for t in (0.5, 0.35, 0.65, 0.2, 0.8, 0.1, 0.9, 0.05, 0.95):
            uv = gp_Pnt2d(u0 + s * (u1 - u0), v0 + t * (v1 - v0))
            if BRepClass_FaceClassifier(f, uv, 1e-7).State() == TopAbs_IN:
                return np.array(a.Value(uv.X(), uv.Y()).Coord()), face_normal_uv(f, uv.X(), uv.Y())
    return None, None


def face_normal_uv(f, u, v):
    from OCP.BRep import BRep_Tool
    from OCP.GeomLProp import GeomLProp_SLProps
    from OCP.TopAbs import TopAbs_REVERSED
    S = BRep_Tool.Surface_s(f)
    pp = GeomLProp_SLProps(S, u, v, 1, 1e-9)
    if not pp.IsNormalDefined():
        return np.array([np.nan] * 3)
    n = np.array(pp.Normal().Coord())
    return -n if f.Orientation() == TopAbs_REVERSED else n


def face_normal_at(f, p):
    from OCP.BRep import BRep_Tool
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCP.gp import gp_Pnt
    pr = GeomAPI_ProjectPointOnSurf(gp_Pnt(*map(float, p)), BRep_Tool.Surface_s(f))
    u, v = pr.LowerDistanceParameters()
    return face_normal_uv(f, u, v)


def wire_points(f, step=0.05, outer=True):
    """Ordered points along the outer wire of face f (edge orientation respected)."""
    from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    we = BRepTools_WireExplorer(BRepTools.OuterWire_s(f))
    P = []
    while we.More():
        e = we.Current()
        c = BRepAdaptor_Curve(e)
        t0, t1 = c.FirstParameter(), c.LastParameter()
        g = GProp_GProps()
        BRepGProp.LinearProperties_s(e, g)
        ts = np.linspace(t0, t1, max(8, int(g.Mass() / step)))
        if e.Orientation() == TopAbs_REVERSED:
            ts = ts[::-1]
        P.append(np.array([c.Value(t).Coord() for t in ts[:-1]]))
        we.Next()
    return np.vstack(P)


def tessellate(shape, defl=0.03, ang=0.15):
    """-> dict(V, T, N, FID): outward triangles, per-vertex normals (area weighted), face index in faces(shape) order."""
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRep import BRep_Tool
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopAbs import TopAbs_REVERSED
    BRepMesh_IncrementalMesh(shape, defl, False, ang, False)
    V, T, N, FID = [], [], [], []
    off = 0
    for k, f in enumerate(faces(shape)):
        loc = TopLoc_Location()
        t = BRep_Tool.Triangulation_s(f, loc)
        if t is None:
            for dd in (defl * 0.5, defl * 2, defl * 0.25):
                BRepMesh_IncrementalMesh(f, dd, False, ang, False)
                t = BRep_Tool.Triangulation_s(f, loc)
                if t is not None:
                    break
        if t is None:
            continue
        tr = loc.Transformation()
        P = np.array([t.Node(j + 1).Transformed(tr).Coord() for j in range(t.NbNodes())])
        TT = np.array([[t.Triangle(j + 1).Value(i) for i in (1, 2, 3)] for j in range(t.NbTriangles())]) - 1
        if f.Orientation() == TopAbs_REVERSED:
            TT = TT[:, ::-1]
        fn = np.cross(P[TT[:, 1]] - P[TT[:, 0]], P[TT[:, 2]] - P[TT[:, 0]])
        vn = np.zeros_like(P)
        for i in range(3):
            np.add.at(vn, TT[:, i], fn)
        vn /= np.linalg.norm(vn, axis=1)[:, None] + 1e-15
        V.append(P)
        T.append(TT + off)
        N.append(vn)
        FID.append(np.full(len(TT), k))
        off += len(P)
    if not V:
        raise WorkerError('BREP_MESH_FAILED', 'Tessellation produced no triangles.')
    return {'V': np.vstack(V), 'T': np.vstack(T), 'N': np.vstack(N), 'FID': np.concatenate(FID)}


def read_stl(path: Path, scale: float = 1.0):
    """Binary or ASCII STL -> welded (V, F) by exact position. Face order kept."""
    data = Path(path).read_bytes()
    tri = None
    if len(data) >= 84:
        n = int(np.frombuffer(data[80:84], np.uint32)[0])
        if 84 + 50 * n == len(data):
            rec = np.frombuffer(data[84:], dtype=np.dtype([('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')]), count=n)
            tri = rec['v'].astype(float)
    if tri is None:
        txt = data.decode('ascii', errors='replace').split()
        pts = []
        for i, w in enumerate(txt):
            if w == 'vertex':
                pts.append((float(txt[i + 1]), float(txt[i + 2]), float(txt[i + 3])))
        tri = np.array(pts, float).reshape(-1, 3, 3)
    flat = tri.reshape(-1, 3) * scale
    V, inv = np.unique(flat, axis=0, return_inverse=True)
    return V, inv.reshape(-1, 3).astype(np.int64)


def write_colored_step(parts: list[tuple[str, Any, list[tuple[float, float, float]], tuple[float, float, float]]], path: Path) -> dict[str, Any]:
    """parts = [(name, solid, per-face sRGB colours in faces(solid) order, part colour)] -> XCAF STEP; returns read-back colour counts."""
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ColorSurf, XCAFDoc_ShapeTool, XCAFDoc_ColorTool
    from OCP.Quantity import Quantity_Color, Quantity_TOC_sRGB
    from OCP.STEPCAFControl import STEPCAFControl_Writer, STEPCAFControl_Reader
    from OCP.STEPControl import STEPControl_AsIs
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDF import TDF_LabelSequence
    doc = TDocStd_Document(TCollection_ExtendedString('XmlOcaf'))
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    ct = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    asm = st.NewShape()
    for name, sol, cols, pcol in parts:
        st.AddComponent(asm, sol, False)
        lab = st.FindShape(sol, False)
        TDataStd_Name.Set_s(lab, TCollection_ExtendedString(name))
        fs = faces(sol)
        if len(fs) != len(cols):
            raise WorkerError('COLOR_FACE_COUNT', 'Colour list does not match the face count.', {'part': name})
        for f, c in zip(fs, cols):
            fl = st.AddSubShape(lab, f)
            if not fl.IsNull():
                ct.SetColor(fl, Quantity_Color(*c, Quantity_TOC_sRGB), XCAFDoc_ColorSurf)
        ct.SetColor(lab, Quantity_Color(*pcol, Quantity_TOC_sRGB), XCAFDoc_ColorSurf)
    st.UpdateAssemblies()
    w = STEPCAFControl_Writer()
    w.SetColorMode(True)
    w.SetNameMode(True)
    if not w.Transfer(doc, STEPControl_AsIs) or int(w.Write(str(path))) != 1:
        raise WorkerError('COLOR_STEP_WRITE', 'Coloured STEP write failed.')
    d2 = TDocStd_Document(TCollection_ExtendedString('XmlOcaf'))
    rd = STEPCAFControl_Reader()
    rd.SetColorMode(True)
    rd.ReadFile(str(path))
    rd.Transfer(d2)
    st2 = XCAFDoc_DocumentTool.ShapeTool_s(d2.Main())
    seq = TDF_LabelSequence()
    st2.GetShapes(seq)
    counts: dict[str, int] = {}
    for i in range(1, seq.Length() + 1):
        subs = TDF_LabelSequence()
        XCAFDoc_ShapeTool.GetSubShapes_s(seq.Value(i), subs)
        for j in range(1, subs.Length() + 1):
            q = Quantity_Color()
            key = 'none'
            if XCAFDoc_ColorTool.GetColor_s(subs.Value(j), XCAFDoc_ColorSurf, q):
                key = '%.2f,%.2f,%.2f' % q.Values(Quantity_TOC_sRGB)
            counts[key] = counts.get(key, 0) + 1
    return counts
