"""Nominal B-rep measurement, independent of cached display triangulation."""


def nominal_bounds(shape):
    """Return xmin,ymin,zmin,xmax,ymax,zmax from underlying geometry.

    OCCT still uses its numerical algorithms; this is not physical metrology.
    Cached tessellation can expand CadQuery's default box by mesh deflection.
    Do not let rendering change a dimensional verdict on the same solid.
    """
    from OCP.BRepBndLib import BRepBndLib
    from OCP.Bnd import Bnd_Box
    box=Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped,box,False,False)
    return tuple(float(value) for value in box.Get())


# OCCT's default volume integration (fixed-order Gauss, as used by
# CadQuery's Shape.Volume()) is several percent off on B-spline lofts and can
# be wildly wrong on offset surfaces left by inward shelling, while the
# B-rep itself is valid.  Volumes that decide a verdict are therefore taken
# from adaptive integration and must agree with an independent triangulated
# estimate; the default value is reported only for comparison.
VOLUME_ADAPTIVE_EPS=1e-6


def adaptive_volume(shape):
    """Adaptive-precision B-rep volume of all solids in shape (mm3)."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    total=0.
    for solid in shape.Solids():
        props=GProp_GProps()
        BRepGProp.VolumeProperties_s(solid.wrapped,props,VOLUME_ADAPTIVE_EPS,True,False)
        total+=float(props.Mass())
    return total


def triangulated_volume(shape,deflection_mm):
    """Closed-mesh volume of a private copy; never caches a mesh on the measured shape."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.GProp import GProp_GProps
    total=0.
    for solid in shape.Solids():
        copy=BRepBuilderAPI_Copy(solid.wrapped).Shape()
        BRepMesh_IncrementalMesh(copy,deflection_mm,False,.1,True)
        props=GProp_GProps()
        BRepGProp.VolumeProperties_s(copy,props,True,False,True)
        total+=float(props.Mass())
    return total


def volume_cross_check(shape):
    """Compare adaptive B-rep integration with a triangulated estimate.

    A mesh whose vertices lie on the surface deviates from it by at most the
    chordal deflection, so the two volumes may differ by about area*deflection.
    The allowance is that bound plus a tiny relative term; it is a measurement
    agreement test, not a design tolerance, and it is never relaxed on failure.
    """
    import math
    bounds=nominal_bounds(shape)
    diagonal=math.dist(bounds[:3],bounds[3:])
    deflection=min(.05,max(1e-3,1e-4*diagonal))
    area=float(sum(face.Area() for solid in shape.Solids() for face in solid.Faces()))
    adaptive=adaptive_volume(shape);mesh=triangulated_volume(shape,deflection)
    default=float(sum(solid.Volume() for solid in shape.Solids()))
    allowance=area*deflection+1e-6*max(abs(adaptive),abs(mesh))
    agree=all(math.isfinite(v) for v in (adaptive,mesh)) and abs(adaptive-mesh)<=allowance
    return {'adaptive_brep_mm3':adaptive,'triangulated_mm3':mesh,'default_brep_mm3':default,
            'mesh_deflection_mm':deflection,'surface_area_mm2':area,'allowance_mm3':allowance,
            'absolute_disagreement_mm3':abs(adaptive-mesh),'agree':bool(agree)}


WALL_OPPOSING_COS=.5


def _outward_normal(face_shape,surface,u,v):
    from OCP.BRepLProp import BRepLProp_SLProps
    from OCP.TopAbs import TopAbs_REVERSED
    props=BRepLProp_SLProps(surface,u,v,1,1e-9)
    if not props.IsNormalDefined():return None
    normal=props.Normal()
    if face_shape.Orientation()==TopAbs_REVERSED:normal.Reverse()
    return normal


def sampled_wall_thickness(shape,samples_per_face=8,start_offset_mm=1e-4):
    """Sampled opposing-wall thickness along the inward surface normal.

    Each sample is a point on a face; a ray is cast from it into the material
    and the first boundary crossing beyond start_offset_mm is examined.  It
    counts as a wall sample when the ray leaves through a roughly opposing face
    (exit outward normal within 60 degrees of the ray).  Oblique exits are
    wedges at edges, whose thickness tends to zero by construction; their
    smallest value is reported separately and does not decide the verdict.
    This is a sampled minimum: thinner material between samples is possible,
    so the result is an observation, never a proof of minimum wall.
    """
    import math
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.BRepTools import BRepTools
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    from OCP.TopAbs import TopAbs_IN
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt2d
    minimum=None;oblique=None;evaluated=0;missed=0;oblique_count=0;faces=0
    for solid in shape.Solids():
        intersector=IntCurvesFace_ShapeIntersector()
        intersector.Load(solid.wrapped,1e-7)
        for face in solid.Faces():
            faces+=1
            surface=BRepAdaptor_Surface(face.wrapped)
            u0,u1,v0,v1=BRepTools.UVBounds_s(face.wrapped)
            for i in range(samples_per_face):
                for j in range(samples_per_face):
                    u=u0+(i+.5)*(u1-u0)/samples_per_face;v=v0+(j+.5)*(v1-v0)/samples_per_face
                    if BRepClass_FaceClassifier(face.wrapped,gp_Pnt2d(u,v),1e-7).State()!=TopAbs_IN:continue
                    normal=_outward_normal(face.wrapped,surface,u,v)
                    if normal is None:continue
                    point=surface.Value(u,v);ray=(-normal.X(),-normal.Y(),-normal.Z())
                    intersector.Perform(gp_Lin(point,gp_Dir(*ray)),start_offset_mm,1e6)
                    hits=[]
                    if intersector.IsDone():
                        for k in range(1,intersector.NbPnt()+1):
                            w=intersector.WParameter(k)
                            if math.isfinite(w) and w>start_offset_mm:hits.append((w,k))
                    if not hits:
                        missed+=1;continue
                    w,k=min(hits)
                    exit_face=intersector.Face(k)
                    exit_normal=_outward_normal(exit_face,BRepAdaptor_Surface(exit_face),intersector.UParameter(k),intersector.VParameter(k))
                    row=(float(w),[point.X(),point.Y(),point.Z()],list(ray))
                    if exit_normal is not None and (ray[0]*exit_normal.X()+ray[1]*exit_normal.Y()+ray[2]*exit_normal.Z())>=WALL_OPPOSING_COS:
                        evaluated+=1
                        if minimum is None or row[0]<minimum[0]:minimum=row
                    else:
                        oblique_count+=1
                        if oblique is None or row[0]<oblique[0]:oblique=row
    return {'sampled_min_mm':None if minimum is None else minimum[0],
            'location_mm':None if minimum is None else minimum[1],
            'ray_direction':None if minimum is None else minimum[2],
            'oblique_exit_min_mm':None if oblique is None else oblique[0],
            'oblique_exit_location_mm':None if oblique is None else oblique[1],
            'faces':faces,'rays_evaluated':evaluated,'rays_oblique_exit':oblique_count,
            'rays_without_exit':missed,'samples_per_face':samples_per_face,
            'opposing_face_cos_min':WALL_OPPOSING_COS}
