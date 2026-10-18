"""Stella viewer MCP (stdio). Gives Claude Code eyes and a ruler on STEP/mesh files.

Run with the interpreter that carries OCP + mcp + trimesh + pillow (the build123d-mcp venv).
Tools: viewer_snapshot (PNG via headless Edge on the local viewer), step_info, step_distance, step_thickness.
No network use; the viewer server is started on a free loopback port per snapshot and stopped afterwards.
"""
import json
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

from mcp.server.mcpserver import Image, MCPServer

HERE = Path(__file__).resolve().parent
EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
VIEWS = {"iso", "front", "rear", "left", "right", "top", "bottom"}
mcp = MCPServer("stella-viewer")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _load_step(path):
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader

    rd = STEPControl_Reader()
    if rd.ReadFile(str(path)) != IFSelect_RetDone:
        raise ValueError(f"cannot read STEP: {path}")
    rd.TransferRoots()
    return rd.OneShape()


def _solids(shape):
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    ex, out = TopExp_Explorer(shape, TopAbs_SOLID), []
    while ex.More():
        out.append(TopoDS.Solid_s(ex.Current()))
        ex.Next()
    return out


def _bbox(shape):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    b = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, b, False, False)
    lo, hi = b.CornerMin(), b.CornerMax()
    return [round(v, 4) for v in (lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z())]


def _props(shape):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    v, a = GProp_GProps(), GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, v)
    BRepGProp.SurfaceProperties_s(shape, a)
    c = v.CentreOfMass()
    return {"volume": round(v.Mass(), 3), "area": round(a.Mass(), 3),
            "centroid": [round(c.X(), 3), round(c.Y(), 3), round(c.Z(), 3)]}


@mcp.tool()
def viewer_snapshot(path: str, view: str = "iso", clip: str = "", width: int = 1000, height: int = 720) -> Image:
    """Render a STEP/STL/PLY file in the Stella viewer and return a PNG.

    view: iso|front|rear|left|right|top|bottom. clip: optional section, e.g. "z:18" or "z:18,x:0" (model units).
    STEP files are shown with CAD edges and section caps (three-cad-viewer)."""
    p = Path(path).resolve()
    if not p.is_file():
        raise ValueError(f"file not found: {p}")
    if view not in VIEWS:
        raise ValueError(f"view must be one of {sorted(VIEWS)}")
    edge = next((e for e in EDGE_CANDIDATES if Path(e).is_file()), None)
    if not edge:
        raise RuntimeError("Microsoft Edge not found")
    page = "cad.html" if p.suffix.lower() in (".step", ".stp") else "index.html"
    port = _free_port()
    srv = subprocess.Popen([sys.executable, "-I", str(HERE / "server.py"), "--root", str(p.parent), "--port", str(port),
                            "--step-python", sys.executable], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = Path(tempfile.gettempdir()) / "stella-viewer-snap" / f"{p.stem}_{int(time.time())}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        if page == "cad.html":  # warm the conversion cache so the headless page does not wait on it
            import urllib.request
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/shapes?path={quote(p.name)}", timeout=700).read()
        q = f"path={quote(p.name)}&view={view}&ui=0"
        if clip:
            q += f"&clip={quote(clip, safe=':,')}"
        url = f"http://127.0.0.1:{port}/static/{page}?{q}"
        subprocess.run([edge, "--headless=new", "--disable-gpu", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                        "--hide-scrollbars", f"--window-size={width},{height}", "--virtual-time-budget=25000",
                        f"--screenshot={out}", url], capture_output=True, timeout=180)
    finally:
        srv.terminate()
    if not out.is_file():
        raise RuntimeError("snapshot failed (no PNG written)")
    return Image(path=str(out))


@mcp.tool()
def step_info(path: str) -> str:
    """STEP summary: overall bbox, per-solid bbox/volume/area/centroid (model units, normally mm)."""
    shape = _load_step(path)
    sol = _solids(shape)
    return json.dumps({"bbox": _bbox(shape), "solid_count": len(sol),
                       "solids": [{"index": i, "bbox": _bbox(s), **_props(s)} for i, s in enumerate(sol[:200])]})


@mcp.tool()
def step_distance(path: str, solid_a: int, solid_b: int, path_b: str = "") -> str:
    """Exact minimum distance between two solids (indices from step_info). path_b: take solid_b from another STEP.
    distance 0 with overlap_volume>0 means interference."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    a = _solids(_load_step(path))[solid_a]
    b = _solids(_load_step(path_b or path))[solid_b]
    d = BRepExtrema_DistShapeShape(a, b)
    d.Perform()
    pa, pb = d.PointOnShape1(1), d.PointOnShape2(1)
    res = {"distance": round(d.Value(), 5),
           "point_a": [round(pa.X(), 4), round(pa.Y(), 4), round(pa.Z(), 4)],
           "point_b": [round(pb.X(), 4), round(pb.Y(), 4), round(pb.Z(), 4)]}
    if d.Value() < 1e-6:
        com = BRepAlgoAPI_Common(a, b)
        res["overlap_volume"] = round(_props(com.Shape())["volume"], 4) if com.IsDone() else None
    return json.dumps(res)


@mcp.tool()
def step_thickness(path: str, solid: int = 0, samples: int = 4000) -> str:
    """Wall thickness statistics of one solid (mesh ray method): min/p5/median/p95/max in model units."""
    import numpy as np
    import trimesh
    from OCP.BRepMesh import BRepMesh_IncrementalMesh

    s = _solids(_load_step(path))[solid]
    BRepMesh_IncrementalMesh(s, 0.1, False, 0.3, True)
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    V, F, off = [], [], 0
    ex = TopExp_Explorer(s, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face_s(ex.Current())
        loc = TopLoc_Location()
        t = BRep_Tool.Triangulation_s(f, loc)
        if t is not None:
            tr = loc.Transformation()
            V += [(lambda p: (p.X(), p.Y(), p.Z()))(t.Node(k).Transformed(tr)) for k in range(1, t.NbNodes() + 1)]
            rev = f.Orientation() == TopAbs_REVERSED
            for k in range(1, t.NbTriangles() + 1):
                a, b, c = t.Triangle(k).Get()
                F.append((a - 1 + off, c - 1 + off, b - 1 + off) if rev else (a - 1 + off, b - 1 + off, c - 1 + off))
            off += t.NbNodes()
        ex.Next()
    m = trimesh.Trimesh(np.array(V), np.array(F), process=True)
    pts, fi = trimesh.sample.sample_surface(m, samples, seed=0)
    n = m.face_normals[fi]
    org = pts - n * 1e-3
    hits_loc, idx_ray, _ = m.ray.intersects_location(org, -n, multiple_hits=False)
    th = np.linalg.norm(hits_loc - pts[idx_ray], axis=1)
    if not len(th):
        return json.dumps({"error": "no ray hits", "watertight": bool(m.is_watertight)})
    q = np.percentile(th, [0, 5, 50, 95, 100])
    return json.dumps({"watertight": bool(m.is_watertight), "samples": int(len(th)),
                       "min": round(q[0], 3), "p5": round(q[1], 3), "median": round(q[2], 3),
                       "p95": round(q[3], 3), "max": round(q[4], 3)})


if __name__ == "__main__":
    mcp.run()
