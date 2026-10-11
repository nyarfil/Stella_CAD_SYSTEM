"""PyMeshLab backend of brain_mesh_ops; runs in the separate scan python (PyMeshLab is GPL-3.0, never imported by the server).
Request: {"op": "hausdorff" | "simplify", "a": stl, "b": stl | null, "params": {...}, "out_dir": dir}. Last stdout line = JSON result.
simplify uses the same quadric edge-collapse settings as brain_mouse_scan_model."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

WORKER_VERSION = 'mesh_ops_pymeshlab/1'


def _load(ms, path: str) -> int:
    ms.load_new_mesh(path)
    ms.meshing_remove_duplicate_vertices()
    return ms.current_mesh_id()


def _one_way(ms, pm, a: int, b: int, n: int) -> float:
    r = ms.get_hausdorff_distance(sampledmesh=a, targetmesh=b, samplevert=True, sampleedge=False, sampleface=True, samplenum=int(n),
                                  maxdist=pm.PercentageValue(100), savesample=False)
    return float(r['max'])


def run(req: dict) -> dict:
    import pymeshlab as pm
    ms = pm.MeshSet()
    p = req['params']
    a = _load(ms, req['a'])
    if req['op'] == 'hausdorff':
        b = _load(ms, req['b'])
        t = time.time()
        ab, ba = _one_way(ms, pm, a, b, p['samples']), _one_way(ms, pm, b, a, p['samples'])
        return {'status': 'OK', 'worker': WORKER_VERSION, 'metrics': {'hausdorff_mm': max(ab, ba), 'a_to_b_max_mm': ab, 'b_to_a_max_mm': ba},
                'compute_s': round(time.time() - t, 3), 'pymeshlab': getattr(pm, '__version__', None)}
    if req['op'] == 'simplify':
        t = time.time()
        ms.meshing_decimation_quadric_edge_collapse(targetfacenum=int(p['target_faces']), qualitythr=0.5, preserveboundary=True,
                                                    preservenormal=True, optimalplacement=True)
        m = ms.current_mesh()
        out = Path(req['out_dir'])
        out.mkdir(parents=True, exist_ok=True)
        np.save(out / 'v.npy', np.asarray(m.vertex_matrix(), dtype=np.float64))
        np.save(out / 'f.npy', np.asarray(m.face_matrix(), dtype=np.int64))
        return {'status': 'OK', 'worker': WORKER_VERSION, 'compute_s': round(time.time() - t, 3), 'pymeshlab': getattr(pm, '__version__', None)}
    raise ValueError(f'unknown op {req["op"]}')


def main(argv: list[str]) -> int:
    try:
        res = run(json.loads(Path(argv[1]).read_text(encoding='utf-8')))
    except Exception as exc:  # noqa: BLE001 - reported to the server
        res = {'status': 'ERROR', 'error': {'code': 'MESH_OPS_PYMESHLAB', 'message': f'{type(exc).__name__}: {exc}'[:1500]}}
    print(json.dumps(res))
    return 0 if res.get('status') == 'OK' else 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
