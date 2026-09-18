"""Deterministic CPU orthographic CAD previews, requiring only NumPy/Pillow.

The z-buffer is visual evidence, NOT the geometry measurement engine. Exact
curves remain available in SVG and the B-rep STEP. No graphics driver/browser,
Cairo DLL, model API or external image resource is required on Windows/Linux.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np

def render_shapes(shapes,path,direction=(1,1,1),*,width=800,height=600,label='CAD reference'):
    from PIL import Image,ImageDraw
    if not shapes or not 128<=width<=1600 or not 128<=height<=1600:raise ValueError('Bounded render size and at least one shape required.')
    vertices=[];triangles=[];groups=[];offset=0
    for group,shape in enumerate(shapes):
        box=shape.BoundingBox();tol=max(max(box.xlen,box.ylen,box.zlen)*.0007,1e-7)
        verts,tris=shape.tessellate(tol,.25)
        pts=np.asarray([v.toTuple() for v in verts],dtype=float)
        if pts.size==0:raise ValueError('Empty tessellation.')
        vertices.append(pts);triangles.extend(tuple(i+offset for i in t) for t in tris);groups.extend([group]*len(tris));offset+=len(pts)
    points=np.concatenate(vertices);tri=np.asarray(triangles,dtype=int)
    if len(tri)>250_000 or not np.isfinite(points).all():raise ValueError('Render mesh exceeds the bounded renderer.')
    forward=np.asarray(direction,dtype=float);norm=np.linalg.norm(forward)
    if norm<1e-12:raise ValueError('Camera direction must be nonzero.')
    forward/=norm;up=np.array([0.,0.,1.]) if abs(forward[2])<.95 else np.array([0.,1.,0.])
    right=np.cross(up,forward);right/=np.linalg.norm(right);up=np.cross(forward,right)
    projected=np.column_stack([points@right,points@up,points@forward])
    lo=projected[:,:2].min(axis=0);hi=projected[:,:2].max(axis=0)
    scale=min((width-70)/max(hi[0]-lo[0],1e-9),(height-95)/max(hi[1]-lo[1],1e-9))
    xy=(projected[:,:2]-(hi+lo)/2)*scale
    xy[:,0]+=width/2;xy[:,1]=height/2+10-xy[:,1]
    depth=np.full((height,width),-np.inf,dtype=np.float64)
    pixels=np.full((height,width,3),249,dtype=np.uint8)
    palette=[np.array([100.,142.,172.]),np.array([196.,155.,78.]),np.array([111.,155.,126.]),np.array([169.,126.,155.])]
    light=np.array([.2,-.45,.87]);light/=np.linalg.norm(light)
    for ids,group in zip(tri,groups):
        p=xy[ids];z=projected[ids,2]
        x0=max(int(np.floor(p[:,0].min())),0);x1=min(int(np.ceil(p[:,0].max())),width-1)
        y0=max(int(np.floor(p[:,1].min())),0);y1=min(int(np.ceil(p[:,1].max())),height-1)
        if x0>x1 or y0>y1:continue
        a,b,c=p;den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(den)<1e-12:continue
        xx=np.arange(x0,x1+1)[None,:]+.5;yy=np.arange(y0,y1+1)[:,None]+.5
        w0=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/den
        w1=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/den
        w2=1-w0-w1;zz=w0*z[0]+w1*z[1]+w2*z[2]
        target=depth[y0:y1+1,x0:x1+1]
        visible=(w0>=-1e-9)&(w1>=-1e-9)&(w2>=-1e-9)&(zz>target)
        n=np.cross(points[ids[1]]-points[ids[0]],points[ids[2]]-points[ids[0]])
        length=np.linalg.norm(n)
        if length<1e-20:continue
        shade=.5+.5*abs(float(np.dot(n/length,light)))
        color=np.clip(palette[group%len(palette)]*shade,0,255).astype(np.uint8)
        pixels[y0:y1+1,x0:x1+1][visible]=color;target[visible]=zz[visible]
    image=Image.fromarray(pixels);draw=ImageDraw.Draw(image)
    draw.text((20,16),label[:140],fill=(40,52,62))
    draw.text((20,height-25),'B-rep tessellation preview / inspect STEP for exact geometry',fill=(72,82,90))
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);image.save(path,format='PNG')
    return {'method':'CPU triangle z-buffer orthographic preview','triangles':len(tri),'width':width,'height':height,
            'measurement_evidence':False}
