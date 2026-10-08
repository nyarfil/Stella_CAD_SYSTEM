"""Surface quality checks on synthetic B-reps; the OP1 shell run is skipped when the file is absent."""
from __future__ import annotations

import math
from pathlib import Path

import cadquery as cq
import pytest

from cadmcp_brain.studio.surface_quality import analyze_surface_quality, render_curvature, render_zebra

OP1=Path('V:/mouse/OP1-PCB/stock-shell/OP1_Shell_NEW.step')


def _bspline_surface(x_knots=(0.,1.,2.),x_mults=(4,1,4),rows=None):
    from OCP.Geom import Geom_BSplineSurface
    from OCP.TColStd import TColStd_Array1OfInteger,TColStd_Array1OfReal
    from OCP.TColgp import TColgp_Array2OfPnt
    from OCP.gp import gp_Pnt
    degree=3
    nu=sum(x_mults)-degree-1
    xs=rows or [(i*0.5,.3*math.sin(i*1.1)+.1*i) for i in range(nu)]
    poles=TColgp_Array2OfPnt(1,nu,1,4)
    for i,(x,z) in enumerate(xs):
        for j in range(4):
            poles.SetValue(i+1,j+1,gp_Pnt(x,j*0.5,z))
    uk=TColStd_Array1OfReal(1,len(x_knots))
    um=TColStd_Array1OfInteger(1,len(x_knots))
    for i,(k,m) in enumerate(zip(x_knots,x_mults)):
        uk.SetValue(i+1,k);um.SetValue(i+1,m)
    vk=TColStd_Array1OfReal(1,2);vm=TColStd_Array1OfInteger(1,2)
    vk.SetValue(1,0.);vk.SetValue(2,1.);vm.SetValue(1,4);vm.SetValue(2,4)
    return Geom_BSplineSurface(poles,uk,vk,um,vm,degree,3)


def _face(surface):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    return cq.Face(BRepBuilderAPI_MakeFace(surface,1e-6).Face())


def _split_pair(rotate_deg=0.):
    from OCP.gp import gp_Pnt
    a=_bspline_surface();a.Segment(0.,1.,0.,1.,1e-9,1e-9)
    b=_bspline_surface();b.Segment(1.,2.,0.,1.,1e-9,1e-9)
    if rotate_deg:
        c,s=math.cos(math.radians(rotate_deg)),math.sin(math.radians(rotate_deg))
        for j in range(1,5):
            p0,p1=b.Pole(1,j),b.Pole(2,j)
            dx,dz=p1.X()-p0.X(),p1.Z()-p0.Z()
            b.SetPole(2,j,gp_Pnt(p0.X()+c*dx-s*dz,p1.Y(),p0.Z()+s*dx+c*dz))
    return cq.Shell.makeShell([_face(a),_face(b)])


def test_filleted_box_g1_pass_g2_fail():
    box=cq.Workplane().box(20,20,20).edges().fillet(2).val()
    r=analyze_surface_quality(box)
    assert r['checks']['g1_smooth_edges']['status']=='PASS'
    assert r['checks']['g0_smooth_edges']['status']=='PASS'
    assert r['checks']['g2_smooth_edges']['status']=='FAIL'
    assert r['checks']['g2_smooth_edges']['worst']==pytest.approx(1.,abs=.05)   # 0 -> 1/r jump, relative 1
    assert r['surface_quality_status']=='FAIL'
    assert r['counts']['smooth_assessed']>0
    assert r['worst_g2_edges'][0]['g2_abs_max']==pytest.approx(.5,rel=.05)


def test_sphere_has_no_smooth_edges_and_is_not_pass_by_edges():
    r=analyze_surface_quality(cq.Workplane().sphere(5).val())
    assert r['counts']['smooth_assessed']==0
    assert r['checks']['g1_smooth_edges']['status']=='UNVERIFIED'
    assert r['surface_quality_status']!='FAIL'
    assert r['faces'][0]['min_convex_radius_mm']==pytest.approx(5.,rel=1e-3)


def test_single_smooth_patch_passes():
    r=analyze_surface_quality(_face(_bspline_surface()))
    assert r['checks']['internal_knots']['status']=='PASS'
    assert r['counts']['smooth_assessed']==0
    assert r['surface_quality_status']=='PASS'
    assert r['checks']['waviness']['status']=='INFO'


def test_c2_split_patches_pass_g2():
    r=analyze_surface_quality(_split_pair())
    assert r['counts']['smooth_assessed']>=1
    assert r['checks']['g0_smooth_edges']['status']=='PASS'
    assert r['checks']['g1_smooth_edges']['status']=='PASS'
    assert r['checks']['g2_smooth_edges']['status']=='PASS'


def test_rotated_row_reports_one_degree_g1_fail():
    r=analyze_surface_quality(_split_pair(1.))
    g1=r['checks']['g1_smooth_edges']
    assert g1['status']=='FAIL'
    assert g1['worst']==pytest.approx(1.,abs=.05)


def test_interior_knot_multiplicity_equals_degree_fails():
    face=_face(_bspline_surface((0.,1.,2.),(4,3,4)))
    r=analyze_surface_quality(face)
    assert r['checks']['internal_knots']['status']=='FAIL'
    assert r['internal_knot_findings'][0]['level']=='c0_crease'
    assert analyze_surface_quality(face,profile='mechanical')['checks']['internal_knots']['status']=='UNVERIFIED'


def test_degree_minus_one_multiplicity_only_fails_class_a():
    face=_face(_bspline_surface((0.,1.,2.),(4,2,4)))
    assert analyze_surface_quality(face)['checks']['internal_knots']['status']=='PASS'
    assert analyze_surface_quality(face,profile='class_a')['checks']['internal_knots']['status']=='FAIL'


def test_mechanical_profile_leaves_g2_unverified():
    r=analyze_surface_quality(cq.Workplane().box(20,20,20).edges().fillet(2).val(),profile='mechanical')
    assert r['checks']['g2_smooth_edges']['status']=='UNVERIFIED'
    assert 'g2_smooth_edges' in r['unassessed_checks']


def test_faceted_solid_not_applicable():
    r=analyze_surface_quality(cq.Workplane().box(5,5,5).val())
    assert r['surface_quality_status']=='NOT_APPLICABLE'


def test_images_render(tmp_path):
    shape=cq.Workplane().box(20,20,20).edges().fillet(3).val()
    z=render_zebra(shape,tmp_path/'z.png',size=(200,150))
    c=render_curvature(shape,tmp_path/'c.png',size=(200,150))
    assert Path(z).stat().st_size>1000 and Path(c).stat().st_size>1000


@pytest.mark.skipif(not OP1.is_file(),reason='OP1 shell STEP not available')
def test_op1_shell_runs_to_completion():
    r=analyze_surface_quality(OP1)
    assert r['surface_quality_status'] in ('PASS','FAIL','UNVERIFIED')
    assert r['counts']['curved']>0
