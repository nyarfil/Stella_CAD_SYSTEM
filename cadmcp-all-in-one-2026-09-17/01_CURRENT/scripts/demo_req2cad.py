"""Reproducible geometry/UID pipeline demo using AUTHOR-CREATED fixtures only.

No fake pretrained embeddings; lexical retrieval is explicitly selected. The
isolated default destination is NOT the actual production Req2CAD knowledge root.
"""
from __future__ import annotations
import argparse,csv,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from cadmcp_brain.req2cad.catalog import Catalog
from cadmcp_brain.req2cad.assets import attach_directory
from cadmcp_brain.req2cad.service import Service
from cadmcp_brain.req2cad.common import atomic_json

def p(x,y,z=0.):return {'x':float(x),'y':float(y),'z':float(z)}
def ring(outer=5.,inner=2.,length=6.,square=False):
    def circle(r):return {'type':'Circle3D','center_point':p(0,0),'normal':p(0,0,1),'radius':r}
    curves=[circle(outer)]
    if square:
        points=[p(-5,-5),p(5,-5),p(5,5),p(-5,5)]
        curves=[{'type':'Line3D','start_point':points[i],'end_point':points[(i+1)%4]} for i in range(4)]
    loops=[{'is_outer':True,'profile_curves':curves}]
    if inner:loops.append({'is_outer':False,'profile_curves':[circle(inner)]})
    return {'entities':{'s':{'type':'Sketch','transform':{'origin':p(0,0),'x_axis':p(1,0),'y_axis':p(0,1),'z_axis':p(0,0,1)},'profiles':{'p':{'loops':loops}}},
      'e':{'type':'ExtrudeFeature','start_extent':{'type':'ProfilePlaneStartDefinition'},'operation':'NewBodyFeatureOperation','profiles':[{'sketch':'s','profile':'p'}],
       'extent_type':'OneSideFeatureExtentType','extent_one':{'distance':{'value':length}},'extent_two':{'distance':{'value':0.}}}},
      'sequence':[{'type':'Sketch','entity':'s'},{'type':'ExtrudeFeature','entity':'e'}]}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--destination',type=Path,default=ROOT/'workspace'/'_test_req2cad');a=parser.parse_args(argv)
    root=a.destination.resolve();root.mkdir(parents=True,exist_ok=True);catalog=Catalog(root/'kb')
    origin='fixture://cadmcp-authored-demo-not-Req2CAD'
    if catalog.path.exists() and catalog.status()['meta']['source_url']!=origin:raise ValueError('Refusing to overwrite a non-fixture catalog.')
    rows=[('9000/90000001',['support rotating shaft','reduce friction'],'Authored hollow cylinder TEST fixture; annotations are illustrative, NOT proven capabilities.'),
          ('9000/90000002',['support rotating shaft','reduce friction'],'Authored larger ring TEST fixture.'),
          ('9000/90000003',['support structure'],'Authored rectangular block TEST fixture.')]
    csv_path=root/'fixture_annotations.csv'
    with csv_path.open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(['uid','function_keywords','function_description'])
        for uid,words,desc in rows:w.writerow([uid,json.dumps(words),desc])
    sources=root/'fixture_cad_json'/'9000';sources.mkdir(parents=True,exist_ok=True)
    for name,shape in [('90000001',ring()),('90000002',ring(outer=8.,inner=3.,length=4.)),('90000003',ring(inner=0.,square=True))]:atomic_json(sources/(name+'.json'),shape)
    catalog.ingest(csv_path,source_url=origin)
    attach_directory(catalog,sources.parent,'deepcad_json',1.,'Author-created fixture coordinates explicitly defined in mm; not original dataset units',origin,'MIT author-created fixtures')
    service=Service(catalog);evidence=[service.materialize(uid) for uid,_,_ in rows]
    report={'fixture_only':True,'not_original_req2cad_data':True,'pretrained_embedding_model_executed':False,
      'explicit_lexical_demo':catalog.lexical(['support rotating shaft','reduce friction']),
      'status':catalog.status(),'evidence':evidence,'ring_vs_block':service.compare(rows[0][0],rows[2][0]),
      'diverse_cases':service.portfolio([r[0] for r in rows],limit=3)}
    atomic_json(root/'fixture_report.json',report)
    print(json.dumps({'fixture_only':True,'report':str(root/'fixture_report.json'),'cases':3,'topology_comparison':report['ring_vs_block']['topology']},ensure_ascii=False,indent=2))
    return 0
if __name__=='__main__':raise SystemExit(main())
