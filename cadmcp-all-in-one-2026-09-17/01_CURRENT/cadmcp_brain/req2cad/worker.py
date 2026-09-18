"""Isolated geometry process. Output is a JSON file; CAD stdout never enters MCP."""
from __future__ import annotations
import json, sys, traceback
from pathlib import Path
from .common import atomic_json,json_load,file_hash
from .geometry import reconstruct,shape_features

def run(config):
    import cadquery as cq
    root=Path(config['out']);source=Path(config['source']);root.mkdir(parents=True,exist_ok=True)
    if file_hash(source)!=config['sha256']: raise ValueError('source changed')
    if config['kind']=='step':
        loaded=cq.importers.importStep(str(source));shapes=loaded.vals()
        body=cq.Compound.makeCompound(shapes) if len(shapes)>1 else shapes[0]
        scale=config['scale_to_mm']
        if scale!=1: body=body.scale(scale)
        replay={'kind':'STEP import','scale_to_mm':scale}
    else: body,replay=reconstruct(json_load(source),config['scale_to_mm'])
    features=shape_features(body)
    # Raw sampled points go to their own file to keep tool responses small.
    atomic_json(root/'points.json',features.pop('surface_points_mm'))
    cq.exporters.export(body,str(root/'model.step'))
    cq.exporters.export(body,str(root/'model.stl'),tolerance=max(0.001,max(features['bbox_mm'])*0.0005))
    for name,direction in [('iso',(1,1,1)),('top',(0,0,1)),('front',(0,-1,0)),('right',(1,0,0))]:
        from cadquery import exporters
        svg=exporters.getSVG(body,opts={'width':800,'height':600,'projectionDir':direction,'showAxes':False})
        (root/(name+'.svg')).write_text(svg,encoding='utf-8')
        from ..studio.render import render_shapes
        render_shapes([body],root/(name+'.png'),direction,label='Reference CAD / '+name.upper())
    features['replay']=replay;features['source_sha256']=config['sha256']
    features['exports']={name:{'path':name,'sha256':file_hash(root/name)} for name in ['model.step','model.stl','points.json','iso.svg','top.svg','front.svg','right.svg','iso.png','top.png','front.png','right.png']}
    features['dimensional_status']='reference_coordinates_only' if config.get('reference_only') else 'owner_supplied_unit_conversion'
    features['manufacturing_dimensions_verified']=False
    if config.get('reference_only'):
        # OCCT uses an arbitrary model scale for display/export. Do not call those
        # values physical millimeters in evidence when source units are unknown.
        def relabel(value):
            if isinstance(value,dict):return {k.replace('_mm','_model_units'):relabel(v) for k,v in value.items()}
            if isinstance(value,list):return [relabel(v) for v in value]
            return value
        features=relabel(features)
        features['export_unit_notice']='STEP/STL coordinates are reference model scale, not calibrated manufacturing dimensions. Adapt using the actual target hardware.'
    atomic_json(root/'result.json',{'ok':True,'result':features})
    return 0

def main():
    config=json_load(Path(sys.argv[1]))
    try:return run(config)
    except Exception as exc:
        atomic_json(Path(config['out'])/'result.json',{'ok':False,'error':{'type':type(exc).__name__,'message':str(exc)[:2000]}})
        print(traceback.format_exc(),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
