"""Geometry worker for the bounded recipe interpreter."""
from __future__ import annotations
import sys,traceback
from pathlib import Path
from ..req2cad.common import json_load,atomic_json
from .recipe import execute_recipe

def main():
    cfg=json_load(Path(sys.argv[1]));out=Path(cfg['out'])
    try:
        result=execute_recipe(cfg['recipe'],cfg['sources'],out)
        atomic_json(out/'worker-result.json',{'ok':True,'result':result});return 0
    except Exception as exc:
        atomic_json(out/'worker-result.json',{'ok':False,'error':{'type':type(exc).__name__,'message':str(exc)[:2000]}})
        print(traceback.format_exc(),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
