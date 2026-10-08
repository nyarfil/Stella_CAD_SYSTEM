"""Depth-gauge calibration for the side-button stop setting, measured on exported STEP parts.

The gauge foot rests on the skin beside the window front edge (its tangent
plane); the rod is normal to that plane and touches the button face a stated
distance in from the face front edge. The reading is the rod depth below the
foot plane. Everything here is a rigid CAD measurement: printed surface
cusps, contact flex and hinge play while gauging are not included.
"""
from __future__ import annotations
import math

import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepLProp import BRepLProp_SLProps
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Pnt


def _skin_point_and_normal(shell,probe):
    v=BRepBuilderAPI_MakeVertex(gp_Pnt(*probe)).Vertex()
    ext=BRepExtrema_DistShapeShape(v,shell.wrapped);ext.Perform()
    if not ext.IsDone() or ext.NbSolution()<1 or not ext.SupportTypeShape2(1).name.endswith('IsInFace'):
        raise ValueError('skin point beside the front edge is not on a face')
    face=TopoDS.Face_s(ext.SupportOnShape2(1));u,w=ext.ParOnFaceS2(1)
    n=BRepLProp_SLProps(BRepAdaptor_Surface(face),u,w,1,1e-6).Normal()
    if face.Orientation().name=='TopAbs_REVERSED':n.Reverse()
    q=ext.PointOnShape2(1)
    return (q.X(),q.Y(),q.Z()),(n.X(),n.Y(),n.Z())


def _depth(shape,base,n,reach):
    """Distance along -n from base to the first point of shape on that ray, or None."""
    end=[base[i]-reach*n[i] for i in range(3)]
    edge=cq.Edge.makeLine(cq.Vector(*base),cq.Vector(*end))
    sec=BRepAlgoAPI_Section(shape.wrapped,edge.wrapped);sec.Build()
    hits=[v.toTuple() for v in cq.Shape.cast(sec.Shape()).Vertices()]
    if not hits:return None
    return min(sum((base[i]-h[i])*n[i] for i in range(3)) for h in hits)


def gauge_calibration(button_step,shell_step,hinge_xy,stop_deg,*,skin_probe,inset_mm=1.,lift_mm=1.,
                      edge_depth_mm=.3,offsets_deg=(0.,.5,-.5)):
    """Measure the gauge reading at rest and around the stop angle.

    skin_probe is a point outside the shell beside the window front edge; the
    nearest skin point sets the foot plane. The face front edge is found by
    walking along -X in that plane until the rest-pose button lies within
    edge_depth_mm of the plane; the rod stands inset_mm further in.
    """
    button=cq.importers.importStep(str(button_step)).val()
    shell=cq.importers.importStep(str(shell_step)).val()
    foot,n=_skin_point_and_normal(shell,skin_probe)
    t=[1-n[0]*n[0],-n[0]*n[1],-n[0]*n[2]];tl=math.sqrt(sum(c*c for c in t));t=[c/tl for c in t]
    def line(s):return [foot[i]+s*t[i]+lift_mm*n[i] for i in range(3)]
    def touches(s):
        d=_depth(button,line(s),n,lift_mm+3.)
        return d is not None and d-lift_mm<edge_depth_mm
    outside,inside=0.,-4.
    if touches(outside) or not touches(inside):raise ValueError('front edge not bracketed')
    while outside-inside>.002:
        mid=(outside+inside)/2
        if touches(mid):inside=mid
        else:outside=mid
    s_edge=inside;base=line(s_edge-inset_mm)
    hx,hy=hinge_xy
    def reading(angle):
        moved=button.rotate(cq.Vector(hx,hy,0),cq.Vector(hx,hy,1),angle) if angle else button
        d=_depth(moved,base,n,lift_mm+4.)
        if d is None:raise ValueError(f'gauge ray misses the face at {angle} deg')
        return d-lift_mm
    readings={round(stop_deg+o,6):reading(stop_deg+o) for o in offsets_deg}
    a,b=stop_deg+offsets_deg[1],stop_deg+offsets_deg[2]
    return {'foot_point_mm':list(foot),'skin_normal':list(n),'front_edge_offset_mm':s_edge,
            'read_point_mm':[base[i]-lift_mm*n[i] for i in range(3)],'rest_reading_mm':reading(0.),
            'stop_reading_mm':readings[round(stop_deg,6)],'mm_per_deg':(readings[round(b,6)]-readings[round(a,6)])/(a-b),
            'readings_mm':readings}
