"""Named-part loading and mesh helpers for the mouse check tools (interference report, wall audit, section render). WORKER SIDE (needs OCP; the
distance helpers need vtk, which comes with cadquery = extra `geometry`).

Parts come from STEP files: every leaf solid of an XCAF assembly is one part named by its label (assembly instances keep their placement);
a STEP without names gives one part per solid named after the file stem (stem, stem_1, ...). A name used twice gets a suffix _2, _3 ...
`groups` merge several parts into one named part (a compound), e.g. {"plateL board": ["main_switch_plateL_0"]} renames one part.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
import numpy as np
from .scan_cad_common import WorkerError
from . import cad_brep_lib as L

GENERIC_NAMES = {'', 'SOLID', 'COMPOUND', 'SHELL', 'COMPSOLID', 'SHAPE'}

def _label_name(lab) -> str | None:
    from OCP.TDataStd import TDataStd_Name
    a = TDataStd_Name()
    if lab.FindAttribute(TDataStd_Name.GetID_s(), a):
        s = a.Get().ToExtString().strip()
        return None if s.upper() in GENERIC_NAMES or s.startswith('Open CASCADE STEP translator') else s       # writer defaults are no names: such a part is named after the file
    return None


def read_named_solids(path: Path) -> list[tuple[str | None, Any]]:
    """STEP -> [(label name or None, located solid)] in file order (XCAF reader; plain reader as a fallback)."""
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
    from OCP.TDF import TDF_LabelSequence, TDF_Label
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.TopLoc import TopLoc_Location
    doc = TDocStd_Document(TCollection_ExtendedString('XmlOcaf'))
    rd = STEPCAFControl_Reader()
    rd.SetNameMode(True)
    if rd.ReadFile(str(path)) != IFSelect_RetDone or not rd.Transfer(doc):
        raise WorkerError('PARTS_STEP_READ', 'The STEP file could not be read.', {'file': Path(path).name})
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    out: list[tuple[str | None, Any]] = []

    def walk(lab, loc, name):
        ref = TDF_Label()
        if XCAFDoc_ShapeTool.IsReference_s(lab) and XCAFDoc_ShapeTool.GetReferredShape_s(lab, ref):
            walk(ref, loc.Multiplied(XCAFDoc_ShapeTool.GetLocation_s(lab)), _label_name(lab) or name)
            return
        nm = _label_name(lab) or name
        ch = TDF_LabelSequence()
        XCAFDoc_ShapeTool.GetComponents_s(lab, ch, False)
        if ch.Length() > 0:
            for i in range(1, ch.Length() + 1):
                walk(ch.Value(i), loc, nm)
            return
        sh = XCAFDoc_ShapeTool.GetShape_s(lab)
        if sh.IsNull():
            return
        sh = sh.Moved(loc)
        ss = L.solids(sh)
        if len(ss) == 1:
            out.append((nm, ss[0]))
        else:
            for k, s in enumerate(ss):
                out.append((f'{nm}_{k}' if nm else None, s))

    free = TDF_LabelSequence()
    st.GetFreeShapes(free)
    for i in range(1, free.Length() + 1):
        walk(free.Value(i), TopLoc_Location(), None)
    if not out:
        out = [(None, s) for s in L.solids(L.read_step(Path(path)))]
    if not out:
        raise WorkerError('PARTS_NO_SOLID', 'The STEP file holds no solid.', {'file': Path(path).name})
    return out


def load_parts(paths: list[str], groups: dict[str, list[str]] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """-> ({part name: shape}, [{name, file, solids}]) in a stable order. Single-solid assemblies keep the leaf label; unnamed solids get the file stem."""
    parts: dict[str, Any] = {}
    src: dict[str, str] = {}
    for p in paths:
        stem = Path(p).stem
        rows = read_named_solids(Path(p))
        n_unnamed, k = sum(1 for n, _ in rows if n is None), 0
        for n, s in rows:
            if n is None:
                n = stem if n_unnamed == 1 else f'{stem}_{k}'
                k += 1
            base, j = n, 2
            while n in parts:
                n = f'{base}_{j}'
                j += 1
            parts[n], src[n] = s, Path(p).name
    if groups:
        used: set[str] = set()
        groups = {g: [x for m in members for x in ([n for n in parts if n.startswith(m[:-1])] if m.endswith('*') else [m])] or members
                  for g, members in groups.items()}               # a member "stem*" takes every part whose name starts with "stem"
        for g, members in groups.items():
            miss = [m for m in members if m not in parts]
            if miss:
                raise WorkerError('PARTS_GROUP_UNKNOWN', f'Group "{g}" names parts that are not in the STEP files.', {'missing': miss, 'known': sorted(parts)})
            used.update(members)
        merged = {g: (parts[m[0]] if len(m) == 1 else L.compound([parts[x] for x in m])) for g, m in groups.items()}
        gsrc = {g: ', '.join(sorted({src[x] for x in m})) for g, m in groups.items()}
        for g in groups:
            if g in parts and g not in groups[g]:
                raise WorkerError('PARTS_GROUP_NAME', f'Group name "{g}" collides with a part name.', {'group': g})
        parts = {**{k: v for k, v in parts.items() if k not in used}, **merged}
        src = {**{k: v for k, v in src.items() if k not in used}, **gsrc}
    table = [{'name': n, 'file': src[n], 'solids': len(L.solids(s)) or 1} for n, s in parts.items()]
    return parts, table


def require(parts: dict[str, Any], names: list[str], what: str) -> None:
    miss = [n for n in names if n not in parts]
    if miss:
        raise WorkerError('PARTS_UNKNOWN', f'{what} names parts that are not in the STEP files.', {'missing': miss, 'known': sorted(parts)})


def volume(shape) -> float:
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, g)
    return float(g.Mass())


def bbox_gap(a, b) -> float:
    A, B = L.bbox(a), L.bbox(b)
    d = [max(0.0, A[i] - B[i + 3], B[i] - A[i + 3]) for i in range(3)]
    return float(np.sqrt(sum(x * x for x in d)))


def mesh(shape, defl: float, ang: float = 0.1) -> tuple[np.ndarray, np.ndarray]:
    m = L.tessellate(shape, defl, ang)
    return m['V'], m['T']


def polydata(V: np.ndarray, T: np.ndarray):
    import vtk
    from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray
    pts = vtk.vtkPoints()
    pts.SetData(numpy_to_vtk(np.ascontiguousarray(V, dtype=float), deep=True))
    cells = np.hstack([np.full((len(T), 1), 3, dtype=np.int64), T.astype(np.int64)]).ravel()
    ca = vtk.vtkCellArray()
    ca.SetCells(len(T), numpy_to_vtkIdTypeArray(cells, deep=True))
    pd = vtk.vtkPolyData()
    pd.SetPoints(pts)
    pd.SetPolys(ca)
    return pd


def mesh_volume(V: np.ndarray, T: np.ndarray) -> float:
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    return float(np.einsum('ij,ij->i', a, np.cross(b, c)).sum() / 6.0)


__all__ = ['read_named_solids', 'load_parts', 'require', 'volume', 'bbox_gap', 'mesh', 'polydata', 'mesh_volume']
