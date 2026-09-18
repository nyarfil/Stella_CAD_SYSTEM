"""Optional isolated B-rep measurement worker. Accepts JSON, never Python code.

Subprocess isolation/timeout is NOT an OS security sandbox. Trusted local STEP only.
"""
from __future__ import annotations
import contextlib
import json
import sys


def measure(payload):
    import cadquery as cq
    shapes = {}
    metrics = {}
    for name,path in payload["artifacts"].items():
        obj=cq.importers.importStep(path)
        solids=obj.solids().vals()
        if not solids:
            raise ValueError(f"{name}: no solid bodies in STEP")
        shape=cq.Compound.makeCompound(solids)
        bb=shape.BoundingBox()
        shapes[name]=shape
        metrics[name]={"brep_valid":bool(shape.isValid()),"solid_count":len(solids),"bbox_x_mm":float(bb.xlen),"bbox_y_mm":float(bb.ylen),"bbox_z_mm":float(bb.zlen),"volume_mm3":float(shape.Volume())}
    pairs={}
    for pair in payload.get("pairs",[]):
        a,b=pair
        key=a+"|"+b
        if key in pairs: continue
        pairs[key]={"distance_mm":float(shapes[a].distance(shapes[b])),"intersection_mm3":float(shapes[a].intersect(shapes[b]).Volume())}
    return {"engine":"CadQuery/OpenCascade","cadquery_version":cq.__version__,"metrics":metrics,"pairs":pairs}


def main():
    try:
        payload=json.loads(sys.stdin.read())
        # Any third-party chatter belongs on stderr, never on the JSON result stream.
        with contextlib.redirect_stdout(sys.stderr):
            result={"ok":True,"result":measure(payload)}
    except Exception as exc:
        result={"ok":False,"error":{"type":type(exc).__name__,"message":str(exc)[:2000]}}
    print(json.dumps(result,ensure_ascii=False,allow_nan=False),flush=True)
    return 0 if result["ok"] else 1

if __name__=="__main__":
    raise SystemExit(main())
