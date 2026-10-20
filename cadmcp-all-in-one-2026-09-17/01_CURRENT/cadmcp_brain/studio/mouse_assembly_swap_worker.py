"""Replace labelled solids of an XCAF assembly STEP (brain_mouse_assembly_swap). SUBPROCESS WORKER (server python: OCP, extra `geometry`).

Run as:  <server python> -I mouse_assembly_swap_worker.py request.json      (result = last stdout line, JSON)

The base assembly is read with XCAF (names, placements, part and face colours). Every leaf solid becomes one component of a new FLAT AP242
assembly: untouched solids are written with the very same B-rep (same TShape and placement, names, colours); a replaced label gets the solid of
the other STEP file in its own (world) frame. The written file is read back and gated: label set and order, and for every untouched part the
change of volume, centre of mass, bounding box and face count against the base file; every replaced part against its source solid.
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Any

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from cadmcp_brain.studio.scan_cad_common import WorkerError, worker_main
from cadmcp_brain.studio import cad_brep_lib as L

WORKER_VERSION = 'mouse_assembly_swap/1'
GENERIC_NAMES = {'', 'SOLID', 'COMPOUND', 'SHELL', 'COMPSOLID', 'SHAPE'}
SCHEMAS = {'AP242': 'AP242DIS', 'AP214': 'AP214IS', 'AP203': 'AP203'}


def _name(lab) -> str | None:
    from OCP.TDataStd import TDataStd_Name
    a = TDataStd_Name()
    if lab.FindAttribute(TDataStd_Name.GetID_s(), a):
        s = a.Get().ToExtString().strip()
        return None if s.upper() in GENERIC_NAMES or s.startswith('Open CASCADE STEP translator') or s.startswith('=>[') else s      # '=>[0:1:1:2]' = OCC writer default instance name
    return None


def _colors(lab) -> dict[str, tuple[float, float, float]]:
    from OCP.XCAFDoc import XCAFDoc_ColorTool, XCAFDoc_ColorGen, XCAFDoc_ColorSurf, XCAFDoc_ColorCurv
    from OCP.Quantity import Quantity_Color, Quantity_TOC_sRGB
    out = {}
    for key, t in (('gen', XCAFDoc_ColorGen), ('surf', XCAFDoc_ColorSurf), ('curv', XCAFDoc_ColorCurv)):
        q = Quantity_Color()
        if XCAFDoc_ColorTool.GetColor_s(lab, t, q):
            out[key] = tuple(float(v) for v in q.Values(Quantity_TOC_sRGB))
    return out


def read_assembly(path: Path) -> dict[str, Any]:
    """-> {root: assembly name, parts: [{name, raw, shape (located solid), colors, face_colors: [(face, colors)]}]} in file order."""
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
    rd.SetColorMode(True)
    if rd.ReadFile(str(path)) != IFSelect_RetDone or not rd.Transfer(doc):
        raise WorkerError('SWAP_STEP_READ', 'The STEP file could not be read.', {'file': Path(path).name})
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    parts: list[dict[str, Any]] = []

    def walk(lab, loc, name, col):
        ref = TDF_Label()
        if XCAFDoc_ShapeTool.IsReference_s(lab) and XCAFDoc_ShapeTool.GetReferredShape_s(lab, ref):
            walk(ref, loc.Multiplied(XCAFDoc_ShapeTool.GetLocation_s(lab)), _name(lab) or name, {**col, **_colors(lab)})
            return
        nm, col = _name(lab) or name, {**col, **_colors(lab)}
        ch = TDF_LabelSequence()
        XCAFDoc_ShapeTool.GetComponents_s(lab, ch, False)
        if ch.Length() > 0:
            for i in range(1, ch.Length() + 1):
                walk(ch.Value(i), loc, nm, col)
            return
        sh = XCAFDoc_ShapeTool.GetShape_s(lab)
        if sh.IsNull():
            return
        ss = L.solids(sh.Moved(loc))
        fcols = []
        if len(ss) == 1:                                              # sub-shape (face) colours are kept for single-solid leaves
            subs = TDF_LabelSequence()
            XCAFDoc_ShapeTool.GetSubShapes_s(lab, subs)
            for j in range(1, subs.Length() + 1):
                c = _colors(subs.Value(j))
                f = XCAFDoc_ShapeTool.GetShape_s(subs.Value(j))
                if c and not f.IsNull():
                    fcols.append((f.Moved(loc), c))
        for k, s in enumerate(ss):
            parts.append({'raw': (nm if len(ss) == 1 else (f'{nm}_{k}' if nm else None)), 'shape': s, 'colors': col,
                          'face_colors': fcols if len(ss) == 1 else []})

    free = TDF_LabelSequence()
    st.GetFreeShapes(free)
    root = None
    for i in range(1, free.Length() + 1):
        root = root or _name(free.Value(i))
        walk(free.Value(i), TopLoc_Location(), None, {})
    if not parts:
        parts = [{'raw': None, 'shape': s, 'colors': {}, 'face_colors': []} for s in L.solids(L.read_step(Path(path)))]
    if not parts:
        raise WorkerError('SWAP_NO_SOLID', 'The STEP file holds no solid.', {'file': Path(path).name})
    stem, n_unnamed, k = Path(path).stem, sum(1 for p in parts if p['raw'] is None), 0
    seen: set[str] = set()
    for p in parts:                                                   # same naming rule as mouse_parts_lib.load_parts
        n = p['raw']
        if n is None:
            n = stem if n_unnamed == 1 else f'{stem}_{k}'
            k += 1
        base, j = n, 2
        while n in seen:
            n = f'{base}_{j}'
            j += 1
        seen.add(n)
        p['name'] = n
    return {'root': root, 'parts': parts}


def mesh_volume(shape, defl: float = 0.02) -> float:
    """Closed-tessellation volume: an independent check of the B-rep volume (BRepGProp can be off by hundreds of mm3 on B-spline skins)."""
    m = L.tessellate(shape, defl, 0.15)
    V, T = m['V'], m['T']
    return float(np.einsum('ij,ij->i', V[T[:, 0]], np.cross(V[T[:, 1]], V[T[:, 2]])).sum() / 6.0)


def props(shape) -> dict[str, Any]:
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, g)
    c = g.CentreOfMass()
    return {'volume_mm3': float(g.Mass()), 'centroid': [c.X(), c.Y(), c.Z()], 'bbox': [float(x) for x in L.bbox(shape, optimal=False)],
            'faces': len(L.faces(shape)), 'valid': bool(L.is_valid(shape))}


def delta(a: dict[str, Any], b: dict[str, Any]) -> dict[str, float]:
    return {'dvolume_mm3': abs(a['volume_mm3'] - b['volume_mm3']),
            'dcentroid_mm': float(np.linalg.norm(np.array(a['centroid']) - np.array(b['centroid']))),
            'dbbox_mm': float(np.max(np.abs(np.array(a['bbox']) - np.array(b['bbox'])))), 'dfaces': abs(a['faces'] - b['faces'])}


def write_assembly(parts: list[dict[str, Any]], path: Path, root: str, schema: str) -> None:
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ColorGen, XCAFDoc_ColorSurf, XCAFDoc_ColorCurv
    from OCP.Quantity import Quantity_Color, Quantity_TOC_sRGB
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs
    from OCP.TDataStd import TDataStd_Name
    from OCP.Interface import Interface_Static
    kinds = {'gen': XCAFDoc_ColorGen, 'surf': XCAFDoc_ColorSurf, 'curv': XCAFDoc_ColorCurv}
    doc = TDocStd_Document(TCollection_ExtendedString('XmlOcaf'))
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    ct = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    asm = st.NewShape()
    TDataStd_Name.Set_s(asm, TCollection_ExtendedString(root))

    def paint(lab, cols):
        for k, c in cols.items():
            ct.SetColor(lab, Quantity_Color(c[0], c[1], c[2], Quantity_TOC_sRGB), kinds[k])

    for p in parts:
        comp = st.AddComponent(asm, p['shape'], False)
        proto = st.FindShape(p['shape'], False)
        for lab in (comp, proto):
            if not lab.IsNull():
                TDataStd_Name.Set_s(lab, TCollection_ExtendedString(p['name']))
        if not proto.IsNull():
            paint(proto, p['colors'])
            for f, c in p['face_colors']:
                fl = st.AddSubShape(proto, f)
                if not fl.IsNull():
                    paint(fl, c)
    st.UpdateAssemblies()
    Interface_Static.SetCVal_s('write.step.schema', SCHEMAS[schema])
    w = STEPCAFControl_Writer()
    w.SetColorMode(True)
    w.SetNameMode(True)
    if not w.Transfer(doc, STEPControl_AsIs) or int(w.Write(str(path))) != 1:
        raise WorkerError('SWAP_STEP_WRITE', 'The assembly STEP could not be written.')


def schema_of(path: Path) -> str:
    head = Path(path).read_bytes()[:4000].decode('latin-1')
    i = head.find('FILE_SCHEMA')
    return head[i:i + 160].split(';')[0].replace('\n', '').strip() if i >= 0 else ''


def run(req: dict[str, Any]) -> dict[str, Any]:
    L.require_ocp()
    inp, prm, out = req['inputs'], req['params'], Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    base = read_assembly(Path(inp['assembly']))
    names = [p['name'] for p in base['parts']]
    reps = prm['replacements']
    labels = [r['label'] for r in reps]
    if len(set(labels)) != len(labels):
        raise WorkerError('SWAP_DUPLICATE_LABEL', 'A label may be replaced only once.', {'labels': labels})
    miss = [x for x in labels if x not in names]
    if miss:
        raise WorkerError('SWAP_LABEL_UNKNOWN', 'Replacement labels that are not in the assembly.', {'missing': miss, 'known': names})
    base_props = {p['name']: props(p['shape']) for p in base['parts']}
    new_parts = [dict(p) for p in base['parts']]
    replaced: dict[str, dict[str, Any]] = {}
    for i, r in enumerate(reps):
        src = read_assembly(Path(inp[f'rep_{i}']))
        pick = src['parts']
        if r.get('source_part'):
            pick = [p for p in pick if p['name'] == r['source_part']]
            if not pick:
                raise WorkerError('SWAP_SOURCE_PART', 'source_part is not in the replacement STEP.',
                                  {'label': r['label'], 'known': [p['name'] for p in src['parts']]})
        if len(pick) != 1:
            raise WorkerError('SWAP_SOURCE_AMBIGUOUS', 'The replacement STEP holds several solids: name one with source_part.',
                              {'label': r['label'], 'solids': [p['name'] for p in src['parts']]})
        k = names.index(r['label'])
        old = base['parts'][k]
        new_parts[k] = {'raw': r['label'], 'name': r['label'], 'shape': pick[0]['shape'], 'colors': pick[0]['colors'] or old['colors'],
                        'face_colors': pick[0]['face_colors']}
        replaced[r['label']] = {'source_file': Path(inp[f'rep_{i}']).name, 'source_part': pick[0]['name'], 'old': base_props[r['label']],
                                'source': props(pick[0]['shape'])}
        replaced[r['label']]['old']['mesh_volume_mm3'] = mesh_volume(old['shape'])
        replaced[r['label']]['source']['mesh_volume_mm3'] = mesh_volume(pick[0]['shape'])
    asm_path = out / 'assembly.step'
    write_assembly(new_parts, asm_path, base['root'] or Path(inp['assembly']).stem, prm['schema'])
    back = read_assembly(asm_path)
    back_names = [p['name'] for p in back['parts']]
    tv, tp = prm['tol_volume_mm3'], prm['tol_position_mm']
    rows, untouched = [], {'dvolume_mm3': 0.0, 'dcentroid_mm': 0.0, 'dbbox_mm': 0.0, 'dfaces': 0}
    back_by = {p['name']: p for p in back['parts']}
    for n in names:
        if n not in back_by:
            continue
        bp = props(back_by[n]['shape'])
        if n in replaced:
            d = delta(bp, replaced[n]['source'])
            ok = d['dvolume_mm3'] <= tv and d['dcentroid_mm'] <= tp and d['dbbox_mm'] <= tp and d['dfaces'] == 0 and bp['valid']
            replaced[n]['readback'] = bp
            replaced[n]['readback_vs_source'] = d
            rows.append({'label': n, 'role': 'replaced', 'volume_before_mm3': base_props[n]['volume_mm3'], 'volume_after_mm3': bp['volume_mm3'],
                         'faces_before': base_props[n]['faces'], 'faces_after': bp['faces'], 'valid': bp['valid'], **d,
                         'result': 'PASS' if ok else 'FAIL'})
        else:
            d = delta(bp, base_props[n])
            for k in untouched:
                untouched[k] = max(untouched[k], d[k])
            ok = d['dvolume_mm3'] <= tv and d['dcentroid_mm'] <= tp and d['dbbox_mm'] <= tp and d['dfaces'] == 0
            rows.append({'label': n, 'role': 'untouched', 'volume_mm3': bp['volume_mm3'], 'faces': bp['faces'], **d, 'result': 'PASS' if ok else 'FAIL'})
    n_un = sum(1 for r in rows if r['role'] == 'untouched')
    n_re = sum(1 for r in rows if r['role'] == 'replaced')
    lost_colour = sum(1 for n in replaced if next(p for p in base['parts'] if p['name'] == n)['colors'])
    colours = {'base_parts_with_colour': sum(1 for p in base['parts'] if p['colors']), 'out_parts_with_colour': sum(1 for p in back['parts'] if p['colors']),
               'base_coloured_faces': sum(len(p['face_colors']) for p in base['parts']), 'out_coloured_faces': sum(len(p['face_colors']) for p in back['parts'])}
    checks = {'label_set_and_order': 'PASS' if back_names == names else 'FAIL',
              'solid_count': 'PASS' if len(back['parts']) == len(names) else 'FAIL',
              'untouched_unchanged': 'PASS' if n_un == len(names) - len(replaced) and all(r['result'] == 'PASS' for r in rows if r['role'] == 'untouched') else 'FAIL',
              'replaced_match_source': 'PASS' if n_re == len(replaced) and all(r['result'] == 'PASS' for r in rows if r['role'] == 'replaced') else 'FAIL',
              'colours_kept': 'PASS' if colours['out_parts_with_colour'] >= colours['base_parts_with_colour'] - lost_colour else 'WARN'}
    return {'files': {'assembly.step': 'assembly.step'}, 'labels': names, 'labels_readback': back_names, 'schema_header': schema_of(asm_path),
            'rows': rows, 'replaced': replaced, 'untouched_max_change': untouched, 'colours': colours, 'checks': checks,
            'assembly_name': base['root'], 'worker_version': WORKER_VERSION}


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
