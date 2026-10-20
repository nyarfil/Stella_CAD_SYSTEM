"""Clearance / interference table of an assembly (brain_mouse_interference_report). SUBPROCESS WORKER (server python: OCP + vtk, extra `geometry`).

Run as:  <server python> -I mouse_interference_worker.py request.json      (result = last stdout line, JSON)

Method per pair (A, B): a bounding-box gap larger than near_mm is reported as a lower bound (method "bbox"; it already clears any sane clearance).
Otherwise both parts are tessellated (fine deflection for small parts, coarse for parts above large_volume_mm3; BRepExtrema hangs on large
B-splines), every triangle is densified to sample_mm, and the samples of each part are evaluated against the other part's surface with
vtkImplicitPolyDataDistance (signed: negative = inside). min distance = smallest |distance| over both directions; penetration = deepest sample inside
the other part. When the parts come closer than sample_mm or a sample lies inside the other part, the overlap volume is the exact OCC
Boolean common, and the Boolean outranks the mesh sign test (a sign is unreliable next to sharp B-rep edges). The OCC common can fail on face
contact between scanned B-splines (no result, or a "common" larger than either part): then the closed tessellations are intersected with manifold3d
(method "mesh+mesh_boolean"), and that mesh overlap counts only together with a penetration above penetration_tol_mm (contact slivers do not fail).
A pair passes when the overlap volume is below overlap_tol_mm3 and the min distance is at least the required clearance (minus 1e-3).
"""
from __future__ import annotations
import math
import sys
from pathlib import Path
from typing import Any

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from cadmcp_brain.studio.scan_cad_common import WorkerError, worker_main
from cadmcp_brain.studio import mouse_parts_lib as P

WORKER_VERSION = 'mouse_interference/1'
DEFAULTS = {'clearance_mm': 0.3, 'overlap_tol_mm3': 0.01, 'near_mm': 2.5, 'fine_deflection_mm': 0.005, 'coarse_deflection_mm': 0.02,
            'large_volume_mm3': 5000.0, 'sample_mm': 0.5, 'penetration_tol_mm': 0.01, 'mesh_overlap_floor_mm3': 0.5}
MAX_SUBDIV = 60


def samples(V: np.ndarray, T: np.ndarray, step: float) -> np.ndarray:
    """Mesh vertices plus barycentric grid points on every triangle whose longest edge exceeds step."""
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    e = np.max([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)], axis=0)
    n = np.minimum(np.ceil(e / step).astype(int), MAX_SUBDIV)
    out = [V]
    for k in np.unique(n[n > 1]):
        m = n == k
        w = np.array([(i / k, j / k) for i in range(k + 1) for j in range(k + 1 - i)])
        w = w[(w.sum(1) > 0) & (w[:, 0] < 1) & (w[:, 1] < 1)]           # skip the three corners (already vertices)
        A, B, C = a[m], b[m], c[m]
        pts = A[:, None, :] + w[None, :, 0:1] * (B - A)[:, None, :] + w[None, :, 1:2] * (C - A)[:, None, :]
        out.append(pts.reshape(-1, 3))
    return np.vstack(out)


class Part:
    def __init__(self, name: str, shape, prm: dict[str, Any]):
        from cadmcp_brain.studio import cad_brep_lib as L
        self.name, self.shape = name, shape
        self.volume = abs(P.volume(shape))
        self.defl = prm['coarse_deflection_mm'] if self.volume > prm['large_volume_mm3'] else prm['fine_deflection_mm']
        self.bbox = L.bbox(shape, optimal=False)
        self._prm, self._mesh, self._imp, self._pts = prm, None, None, None

    def mesh(self):
        if self._mesh is None:
            V, T = P.mesh(self.shape, self.defl)
            if P.mesh_volume(V, T) < 0:                   # a mirrored / reversed solid: turn the triangles outward so the sign test holds
                T = T[:, ::-1].copy()
            self._mesh = (V, T)
            self._pts = samples(V, T, self._prm['sample_mm'])
        return self._mesh

    def implicit(self):
        if self._imp is None:
            import vtk
            V, T = self.mesh()
            pd = P.polydata(V, T)
            nf = vtk.vtkPolyDataNormals()                   # cell normals from the outward triangle order (no flipping, no splitting)
            nf.SetInputData(pd)
            nf.ComputeCellNormalsOn()
            nf.ComputePointNormalsOn()
            nf.SplittingOff()
            nf.ConsistencyOff()
            nf.AutoOrientNormalsOff()
            nf.Update()
            imp = vtk.vtkImplicitPolyDataDistance()
            imp.SetInput(nf.GetOutput())
            self._imp = imp
        return self._imp

    def points_near(self, box: np.ndarray, margin: float) -> np.ndarray:
        self.mesh()
        lo, hi = box[:3] - margin, box[3:] + margin
        m = np.all((self._pts >= lo) & (self._pts <= hi), axis=1)
        return self._pts[m]


def signed(imp, pts: np.ndarray) -> np.ndarray:
    if len(pts) == 0:
        return np.zeros(0)
    import vtk
    from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy
    inp = numpy_to_vtk(np.ascontiguousarray(pts, dtype=float), deep=True)
    out = vtk.vtkDoubleArray()
    imp.FunctionValue(inp, out)
    return vtk_to_numpy(out).copy()


def common_volume(a, b) -> float | None:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    c = BRepAlgoAPI_Common(a, b)
    c.Build()
    if not c.IsDone():
        return None
    return abs(P.volume(c.Shape()))


def mesh_common_volume(A: Part, B: Part) -> float | None:
    """Intersection volume of the two closed tessellations (manifold3d), the cross-check when the OCC Boolean fails or is impossible."""
    try:
        import manifold3d as m3
        import trimesh
    except ImportError:
        return None
    ms = []
    for p in (A, B):
        V, T = p.mesh()
        tm = trimesh.Trimesh(V, T, process=True)          # weld the per-face tessellation into one closed surface
        tm.merge_vertices(digits_vertex=6)
        mm = m3.Manifold(m3.Mesh(vert_properties=np.asarray(tm.vertices, dtype=np.float32), tri_verts=np.asarray(tm.faces, dtype=np.uint32)))
        if mm.status() != m3.Error.NoError or mm.is_empty():
            return None
        ms.append(mm)
    return float(abs((ms[0] ^ ms[1]).volume()))


def measure(A: Part, B: Part, prm: dict[str, Any]) -> dict[str, Any]:
    gap = P.bbox_gap(A.shape, B.shape)
    if gap > prm['near_mm']:
        return {'min_dist_mm': round(gap, 3), 'overlap_mm3': 0.0, 'penetration_mm': 0.0, 'method': 'bbox'}
    reach = prm['near_mm'] + 1.0
    pa = A.points_near(B.bbox, reach)
    pb = B.points_near(A.bbox, reach)
    da, db = signed(B.implicit(), pa), signed(A.implicit(), pb)
    d_all = np.concatenate([np.abs(da), np.abs(db)])
    if len(d_all) == 0:                                    # no sample within reach: the bbox gap is the honest lower bound
        return {'min_dist_mm': round(max(gap, prm['near_mm']), 3), 'overlap_mm3': 0.0, 'penetration_mm': 0.0, 'method': 'bbox'}
    dmin = float(d_all.min())
    pen = float(max(0.0, -(da.min() if len(da) else 0.0), -(db.min() if len(db) else 0.0)))
    row = {'min_dist_mm': round(dmin, 3), 'overlap_mm3': 0.0, 'penetration_mm': round(pen, 4), 'method': 'mesh'}
    if pen > prm['penetration_tol_mm'] or dmin < prm['sample_mm']:     # samples are sample_mm apart: a crossing shows up below it
        cv = common_volume(A.shape, B.shape)
        row['method'] = 'mesh+boolean'
        if cv is not None and cv > min(A.volume, B.volume) * 1.001 + prm['overlap_tol_mm3']:   # a common larger than either part is a failed Boolean
            mv = mesh_common_volume(A, B)
            row['note'] = f'OCC Boolean common returned {cv:.1f} mm3, more than the smaller part; replaced by the mesh intersection'
            row['method'] = 'mesh+mesh_boolean'
            cv = mv
        elif cv < prm['overlap_tol_mm3'] and pen > prm['sample_mm']:     # deep mesh penetration but an empty common: OCC can also miss a real overlap
            mv = mesh_common_volume(A, B)
            if mv is not None and mv > max(prm['overlap_tol_mm3'], prm['mesh_overlap_floor_mm3']):
                row['method'] = 'mesh+mesh_boolean'
                row['note'] = f'OCC Boolean common is empty but the mesh intersection holds {mv:.2f} mm3 at {pen:.2f} mm penetration; mesh wins'
                cv = mv
        elif cv is None:
            cv = mesh_common_volume(A, B)
            if cv is not None:
                row['method'] = 'mesh+mesh_boolean'
                row['note'] = 'OCC Boolean common failed; overlap is the mesh intersection'
        if cv is None:
            row['overlap_mm3'] = None
            row['note'] = 'OCC and mesh Booleans failed; overlap judged from the penetration depth only'
        else:
            row['overlap_mm3'] = round(cv, 4)
        if pen > prm['penetration_tol_mm'] and (cv is None or cv >= prm['overlap_tol_mm3']):
            row['min_dist_mm'] = 0.0
        elif pen > prm['penetration_tol_mm']:              # the exact Boolean finds no overlap: the mesh sign was wrong, keep the distance
            row['note'] = 'mesh sign test reported penetration but the exact Boolean common is empty; Boolean wins'
    return row


def expand_pairs(req_pairs, names: list[str], default_clear: float) -> list[dict[str, Any]]:
    if not req_pairs:
        return [{'a': names[i], 'b': names[j], 'clearance_mm': default_clear} for i in range(len(names)) for j in range(i + 1, len(names))]
    out = []
    for p in req_pairs:
        cl = p.get('clearance_mm', default_clear)
        bs = [n for n in names if n != p['a']] if p['b'] == '*' else [p['b']]
        for b in bs:
            out.append({'a': p['a'], 'b': b, 'clearance_mm': float(cl), 'within_mm': p.get('within_mm'),
                        'label_a': p.get('label_a'), 'label_b': p.get('label_b')})
    return out


def run(req: dict[str, Any]) -> dict[str, Any]:
    prm = {**DEFAULTS, **{k: v for k, v in req['params'].items() if k in DEFAULTS}}
    paths = [req['inputs'][k] for k in sorted(req['inputs'], key=lambda s: int(s.split('_')[1]))]
    parts, table = P.load_parts(paths, req['params'].get('groups'))
    sel = req['params'].get('parts') or list(parts)
    P.require(parts, sel, 'parts')
    pairs = expand_pairs(req['params'].get('pairs'), sel, prm['clearance_mm'])
    P.require(parts, sorted({p['a'] for p in pairs} | {p['b'] for p in pairs}), 'pairs')
    cache: dict[str, Part] = {}

    def part(n: str) -> Part:
        if n not in cache:
            cache[n] = Part(n, parts[n], prm)
        return cache[n]

    rows = []
    for p in pairs:
        if p['a'] == p['b']:
            raise WorkerError('INTERFERENCE_PAIR', 'A pair names the same part twice.', {'pair': [p['a'], p['b']]})
        m = measure(part(p['a']), part(p['b']), prm)
        if p.get('within_mm') is not None and m['min_dist_mm'] >= float(p['within_mm']):
            continue
        need = float(p['clearance_mm'])
        ov = m['overlap_mm3']
        if ov is None:
            ok_overlap = m['penetration_mm'] <= prm['penetration_tol_mm']
        elif m['method'] == 'mesh+mesh_boolean':             # tessellated faces in contact give a sliver of mesh overlap: it counts only with real penetration
            ok_overlap = ov < prm['overlap_tol_mm3'] or m['penetration_mm'] <= prm['penetration_tol_mm']
        else:
            ok_overlap = ov < prm['overlap_tol_mm3']
        ok = m['min_dist_mm'] >= need - 1e-3 and ok_overlap
        rows.append({'a': p.get('label_a') or p['a'], 'b': p.get('label_b') or p['b'], 'part_a': p['a'], 'part_b': p['b'], **m,
                     'required_mm': need, 'result': 'PASS' if ok else 'FAIL'})
        print(rows[-1], file=sys.stderr, flush=True)
    out = Path(req['out_dir'])
    out.mkdir(parents=True, exist_ok=True)
    n_pass = sum(r['result'] == 'PASS' for r in rows)
    write_md(out / 'interference_table.md', rows, n_pass)
    png = write_png(out / 'interference_table.png', rows, n_pass)
    files = {'table_md': 'interference_table.md'}
    if png:
        files['table_png'] = 'interference_table.png'
    return {'rows': rows, 'parts': table, 'summary': {'pairs': len(rows), 'pass': n_pass, 'fail': len(rows) - n_pass},
            'settings_used': prm, 'files': files, 'worker_version': WORKER_VERSION}


def write_md(path: Path, rows, n_pass) -> None:
    lines = [f'# Interference / clearance table: {n_pass}/{len(rows)} PASS', '',
             '| A | B | min dist mm | overlap mm3 | penetration mm | required mm | method | result |', '|---|---|---|---|---|---|---|---|']
    for r in rows:
        lines.append(f"| {r['a']} | {r['b']} | {r['min_dist_mm']} | {r['overlap_mm3']} | {r['penetration_mm']} | {r['required_mm']} | {r['method']} | {r['result']} |")
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def write_png(path: Path, rows, n_pass) -> bool:
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    fig, ax = plt.subplots(figsize=(11, 0.32 * max(1, len(rows)) + 1.2))
    ax.axis('off')
    cells = [[r['a'], r['b'], f"{r['min_dist_mm']:.3f}", '-' if r['overlap_mm3'] is None else f"{r['overlap_mm3']:.3f}", f"{r['required_mm']:.2f}",
              r['result']] for r in rows] or [['-', '-', '-', '-', '-', '-']]
    tb = ax.table(cells, colLabels=['A', 'B', 'min dist mm', 'overlap mm3', 'required mm', 'result'], loc='center', cellLoc='left')
    tb.auto_set_font_size(False)
    tb.set_fontsize(8)
    tb.scale(1, 1.15)
    for i, r in enumerate(rows):
        tb[i + 1, 5].set_facecolor('#c8f0c8' if r['result'] == 'PASS' else '#f5b5b5')
    ax.set_title(f'Clearance / interference: {n_pass}/{len(rows)} PASS')
    fig.savefig(path, dpi=110, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return True


if __name__ == '__main__':
    raise SystemExit(worker_main(run, WorkerError, sys.argv))
