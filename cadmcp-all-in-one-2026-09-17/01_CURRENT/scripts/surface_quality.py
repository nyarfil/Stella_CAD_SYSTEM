"""CLI: measure freeform surface quality of a STEP file; optional JSON and zebra/curvature images."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from cadmcp_brain.studio.surface_quality import PROFILES,analyze_surface_quality,render_curvature,render_zebra


def main(argv=None)->int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('step')
    ap.add_argument('--profile',default='consumer_product',choices=sorted(PROFILES))
    ap.add_argument('--samples',type=int,default=24)
    ap.add_argument('--json',dest='json_out')
    ap.add_argument('--zebra')
    ap.add_argument('--curvature')
    args=ap.parse_args(argv)
    start=time.time()
    result=analyze_surface_quality(args.step,profile=args.profile,samples=args.samples)
    result['analysis_seconds']=round(time.time()-start,1)
    if args.zebra:
        result['zebra_png']=render_zebra(args.step,args.zebra)
    if args.curvature:
        result['curvature_png']=render_curvature(args.step,args.curvature)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True,exist_ok=True)
        Path(args.json_out).write_text(json.dumps(result,indent=1,default=float),encoding='utf-8')
    print(json.dumps({'status':result['surface_quality_status'],'checks':{k:v['status'] for k,v in result.get('checks',{}).items()},
                      'counts':result['counts'],'seconds':result['analysis_seconds']},indent=1))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
