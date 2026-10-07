"""Volume agreement, Boolean volume sanity, sampled wall thickness, stop engagement and the §22 recipe."""
from __future__ import annotations

import copy
import importlib.util
import math
import sys
import types
from pathlib import Path

import pytest

from cadmcp_brain.studio.planning import capabilities
from cadmcp_brain.studio.recipe import Recipe

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))

kernel=pytest.mark.skipif(importlib.util.find_spec('cadquery') is None,
                          reason='Measurement requires the real CAD kernel.')


def _ellipse(a,b,count=12):
    return [(a*math.cos(2*math.pi*i/count),b*math.sin(2*math.pi*i/count)) for i in range(count)]


def _spline_loft(sections):
    import cadquery as cq
    return cq.Solid.makeLoft([cq.Wire.assembleEdges([cq.Edge.makeSpline(
        [cq.Vector(x,y,z) for x,y in _ellipse(a,b)],periodic=True)]) for z,a,b in sections],ruled=False)


@kernel
def test_offset_shell_volume_disagreement_is_detected():
    """OCCT mis-integrates offset surfaces left by hollow(); the cross-check must see it."""
    import cadquery as cq
    from cadmcp_brain.studio.measurement import volume_cross_check
    outer=_spline_loft([(0.,60.,32.),(18.,55.,30.),(34.,36.,18.)])
    raw=outer.hollow(cq.Workplane().add(outer).faces('<Z').vals(),-1.5,kind='intersection')
    report=volume_cross_check(raw)
    assert report['agree'] is False
    # The triangulated volume is the plausible one: about wall x skin area.
    assert 15000<report['triangulated_mm3']<20000


@kernel
def test_shell_operation_output_has_agreeing_volumes(tmp_path):
    from cadmcp_brain.studio.recipe import execute_recipe
    from test_recipe_operations import base,spline_shell_ops
    result=execute_recipe(Recipe.model_validate(base(spline_shell_ops(),[{'part_id':'shell','node':'hollow'}])),{},tmp_path/'s')
    check=next(c for c in result['checks'] if c['id']=='_system-volume-agreement-shell')
    assert check['verdict']=='pass' and check['kind']=='volume_integration_agreement'
    assert 15000<check['adaptive_brep_mm3']<20000


def test_boolean_volume_sanity_rejects_growth_under_cut(monkeypatch):
    from cadmcp_brain.errors import BrainError
    import cadmcp_brain.studio.measurement as measurement
    from cadmcp_brain.studio import recipe as recipe_module
    volumes={'a':100.,'b':10.,'grown':130.,'ok':90.}
    monkeypatch.setattr(measurement,'adaptive_volume',lambda shape:volumes[shape])
    node=types.SimpleNamespace(id='cut',op='difference')
    recipe_module._boolean_volume_sanity(node,'ok',['a','b'])
    with pytest.raises(BrainError) as exc:
        recipe_module._boolean_volume_sanity(node,'grown',['a','b'])
    assert exc.value.code=='STUDIO_INVALID_SOLID'
    union=types.SimpleNamespace(id='u',op='union')
    with pytest.raises(BrainError):recipe_module._boolean_volume_sanity(union,'b',['a','b'])
    intersection=types.SimpleNamespace(id='i',op='intersection')
    with pytest.raises(BrainError):recipe_module._boolean_volume_sanity(intersection,'ok',['a','b'])


@kernel
def test_sampled_wall_thickness_measures_known_walls():
    import cadquery as cq
    from cadmcp_brain.studio.measurement import sampled_wall_thickness
    tube=cq.Solid.makeCylinder(5.,10.).cut(cq.Solid.makeCylinder(4.2,10.))
    assert abs(sampled_wall_thickness(tube)['sampled_min_mm']-.8)<1e-6
    box=cq.Solid.makeBox(10.,10.,10.).cut(cq.Solid.makeBox(8.,8.,9.,cq.Vector(1.,1.,1.)))
    assert abs(sampled_wall_thickness(box)['sampled_min_mm']-1.)<1e-6
    # A leaning spline wall: the vertical rim ray exits obliquely and is a wedge,
    # reported separately instead of being called the wall.
    shell=_spline_loft([(0.,60.,32.),(18.,55.,30.),(34.,36.,18.)]).cut(
        _spline_loft([(-1.,58.5,30.5),(18.,53.5,28.5),(32.5,34.5,16.5)]))
    report=sampled_wall_thickness(shell,12)
    assert 1.<report['sampled_min_mm']<1.5
    assert report['oblique_exit_min_mm']<report['sampled_min_mm'] and report['rays_oblique_exit']>0


def _wall_recipe(min_mm):
    return {'title':'Wall trial','original_request':'Tube wall trial.','functions':{'Tube':'Carry a thin printed wall.'},
            'design_basis':{'kind':'first_principles','summary':'Explicit tube for wall measurement.',
                            'assumptions':['Material and strength are unqualified.']},
            'verification_plan':['Measure the sampled wall thickness of the tube.'],
            'operations':[{'id':'outer','op':'cylinder','function_id':'Tube','reason':'Outer tube surface.',
                           'radius_mm':5.,'height_mm':10.,'origin_mm':[0.,0.,0.],'axis':[0.,0.,1.]},
                          {'id':'bore','op':'cylinder','function_id':'Tube','reason':'Tube bore leaving a 0.8 mm wall.',
                           'radius_mm':4.2,'height_mm':10.,'origin_mm':[0.,0.,0.],'axis':[0.,0.,1.]},
                          {'id':'tube','op':'difference','function_id':'Tube','reason':'Hollow tube.',
                           'operands':['outer','bore']}],
            'outputs':[{'part_id':'tube','node':'tube'}],
            'wall_checks':[{'id':'wall','part':'tube','min_mm':min_mm,'samples_per_face':6}],
            'unverified_requirements':['Strength is not verified.']}


@kernel
@pytest.mark.parametrize('min_mm,verdict',[(1.,'fail'),(.75,'pass')])
def test_wall_check_verdict_follows_measurement(min_mm,verdict):
    import cadquery as cq
    from cadmcp_brain.studio.recipe import evaluate_geometry
    tube=cq.Solid.makeCylinder(5.,10.).cut(cq.Solid.makeCylinder(4.2,10.))
    result=evaluate_geometry(_wall_recipe(min_mm),{'tube':tube})
    check=next(c for c in result['checks'] if c['id']=='wall')
    assert check['kind']=='sampled_wall_thickness' and check['verdict']==verdict
    assert check['minimum_proven'] is False


def test_wall_checks_validate_and_freeze_in_lineage():
    from pydantic import ValidationError
    from cadmcp_brain.studio.runtime import Studio
    bad=_wall_recipe(1.);bad['wall_checks'][0]['part']='missing'
    with pytest.raises(ValidationError):Recipe.model_validate(bad)
    weakened=_wall_recipe(.5)
    assert Studio._lineage_contract(Recipe.model_validate(_wall_recipe(1.)))!=Studio._lineage_contract(Recipe.model_validate(weakened))


def _stop_recipe(end_deg,end_max):
    from test_recipe_operations import hinge_recipe
    data=hinge_recipe(end_deg)
    data['rotation_checks'][0]['end_max_distance_mm']=end_max
    return data


@kernel
def test_rotation_end_engagement_requires_reaching_the_stop():
    import cadquery as cq
    from cadmcp_brain.studio.recipe import evaluate_geometry
    shapes={'stop':cq.Workplane().box(10.,10.,2.).val().translate((25.,0.,-3.)),
            'button':cq.Workplane().box(30.,10.,2.).val().translate((15.,0.,1.))}
    # The button's far corner (x=30) reaches the 2 mm-lower stop face first,
    # at asin(2/30) = 3.82 deg about the rear hinge.
    contact=math.degrees(math.asin(2./30.))
    reached=evaluate_geometry(_stop_recipe(contact,.02),shapes)
    check=next(c for c in reached['checks'] if c['id']=='press')
    assert check['end_pose_engagement']['verdict']=='pass' and check['verdict']=='pass'
    short=evaluate_geometry(_stop_recipe(contact/2,.02),shapes)
    check=next(c for c in short['checks'] if c['id']=='press')
    assert check['end_pose_engagement']['verdict']=='fail' and check['verdict']=='fail'


def test_end_engagement_cannot_be_tighter_than_clearance():
    from pydantic import ValidationError
    data=_stop_recipe(5.,.1);data['rotation_checks'][0]['min_mm']=.5
    with pytest.raises(ValidationError):Recipe.model_validate(data)


def test_capabilities_advertise_measurement_checks():
    report=capabilities([],['sampled_wall_thickness','volume_integration_agreement'])
    assert report['requested_capabilities_supported'] is True


@kernel
def test_polygonal_svg_drawing_is_bounded_on_spline_skins():
    import time
    from cadmcp_brain.studio.render import drawing_svg
    shell=_spline_loft([(0.,60.,32.),(18.,55.,30.),(34.,36.,18.)])
    started=time.monotonic();svg=drawing_svg(shell,(0,0,1))
    assert svg.startswith('<?xml') and '<path' in svg and time.monotonic()-started<30


def test_side_button_recipe_is_a_valid_contract():
    from side_button_recipe import side_button_recipe,press_angle_deg,stop_angle_deg
    recipe=Recipe.model_validate(side_button_recipe())
    assert stop_angle_deg()<press_angle_deg()<0
    assert {c.id for c in recipe.rotation_checks}=={'press-swept-clearance','overtravel-stop-engages','housing-clear-until-stop'}
    assert recipe.wall_checks and all(f in recipe.functions for f in ('F1_transmit_force','F5_limit_overtravel'))
    assert any('Switch' in item for item in recipe.unverified_requirements)


def test_side_button_flow_brief_and_matrix_are_valid():
    from check_side_button_flow import function_brief,morphology_matrix
    from cadmcp_brain.studio.synthesis import FunctionBrief,Matrix
    FunctionBrief.model_validate(function_brief())
    matrix=Matrix.model_validate(morphology_matrix())
    assert {f.id for f in matrix.brief.functions}==set(__import__('side_button_recipe').side_button_recipe()['functions'])


@kernel
def test_side_button_revision4_builds_and_passes_every_check(tmp_path):
    from cadmcp_brain.studio.recipe import execute_recipe
    from side_button_recipe import side_button_recipe_v4
    result=execute_recipe(Recipe.model_validate(side_button_recipe_v4()),{},tmp_path/'sb4')
    failed=[c['id'] for c in result['checks'] if c['verdict']!='pass']
    assert result['geometry_checks_verdict']=='pass',failed
    checks={c['id']:c for c in result['checks']}
    assert checks['hard-stop-blocks-within-play']['start_deg']==-1.
    assert all(x['first_blocked_angle_deg']<-1. for x in checks['hard-stop-blocks-within-play']['blocking']['per_offset'])
    assert checks['tilt-down-with-axial-drop']['start_translation_mm'][2]<0<checks['tilt-up-with-axial-rise']['start_translation_mm'][2]


def test_side_button_revision4_is_a_valid_contract():
    from side_button_recipe import angles_v4,side_button_recipe_v4
    recipe=Recipe.model_validate(side_button_recipe_v4())
    a=angles_v4()
    assert 0<a['tilt']<.5 and a['rest_play']>a['stop_play']
    assert {o.part_id for o in recipe.outputs}>={'shell','button','hinge_pin','return_spring','spring_plug'}
    assert any('17 / (x+15)' in item for item in recipe.unverified_requirements)


def test_side_button_revision3_is_a_valid_contract():
    from side_button_recipe import P3,angles_v3,inward_gap_v3,side_button_recipe_v3
    recipe=Recipe.model_validate(side_button_recipe_v3())
    a=angles_v3()
    assert a['stop']<a['press']<a['contact']<0 and 0<a['stop_play']<.5
    # Stops act at least as far from the axis as the plunger, so play shifts them no more than it shifts actuation.
    assert P3['hinge_y_mm']-P3['arm_tip_y_mm']>=(P3['plunger_x_min_mm']+P3['plunger_x_max_mm'])/2-P3['hinge_x_mm']
    assert inward_gap_v3()>0
    assert {o.part_id for o in recipe.outputs}>={'shell','button','hinge_pin','return_spring'}
    assert not any('filament' in str(op.reason) for op in recipe.operations)


def test_side_button_revision2_is_a_valid_contract():
    from side_button_recipe import angles_v2,side_button_recipe_v2
    recipe=Recipe.model_validate(side_button_recipe_v2())
    a=angles_v2()
    assert a['stop']<a['press']<a['contact']<0
    assert {o.part_id for o in recipe.outputs}>={'shell','button','hinge_pin'}
    assert any('spring' in item for item in recipe.unverified_requirements)


@kernel
def test_side_button_thin_barrel_is_caught_by_wall_check(tmp_path):
    """The first draft's 0.7 mm barrel wall must fail the frozen 1.2 mm wall check."""
    import cadquery as cq
    from cadmcp_brain.studio.recipe import evaluate_geometry
    from side_button_recipe import P,side_button_recipe
    p=copy.deepcopy(P);p['barrel_outer_radius_mm']=2.
    recipe=side_button_recipe(p=p)
    recipe['rotation_checks']=[];recipe['clearance_checks']=[];recipe['dimension_checks']=[]
    recipe['wall_checks']=[w for w in recipe['wall_checks'] if w['part']=='button']
    barrel=cq.Solid.makeCylinder(2.,7.,cq.Vector(-12.,25.,10.5)).cut(cq.Solid.makeCylinder(1.3,9.,cq.Vector(-12.,25.,9.5)))
    shapes={'shell':cq.Solid.makeBox(1.,1.,1.,cq.Vector(100.,100.,100.)),'button':barrel,
            'switch_housing':cq.Solid.makeBox(1.,1.,1.,cq.Vector(110.,100.,100.)),
            'switch_stem':cq.Solid.makeBox(1.,1.,1.,cq.Vector(120.,100.,100.))}
    check=next(c for c in evaluate_geometry(recipe,shapes)['checks'] if c['id']=='button-printed-wall')
    assert check['verdict']=='fail' and abs(check['sampled_min_mm']-.7)<1e-6


def _hinge_shapes(gap=2.):
    import cadquery as cq
    return {'stop':cq.Workplane().box(10.,10.,2.).val().translate((25.,0.,-1.-gap)),
            'button':cq.Workplane().box(30.,10.,2.).val().translate((15.,0.,1.))}


@kernel
def test_blocked_rotation_proves_a_stop_and_fails_when_motion_is_free():
    from cadmcp_brain.studio.recipe import evaluate_geometry
    from test_recipe_operations import hinge_recipe
    blocked=hinge_recipe(8.);blocked['rotation_checks'][0].update(expect='blocked',samples=5,max_samples=33)
    check=next(c for c in evaluate_geometry(blocked,_hinge_shapes())['checks'] if c['id']=='press')
    assert check['verdict']=='pass' and check['blocking']['per_offset'][0]['first_blocking_obstacle']=='stop'
    assert check['continuous_swept_motion']=='not_applicable_blocking_expected'
    free=hinge_recipe(2.);free['rotation_checks'][0].update(expect='blocked',samples=5,max_samples=9)
    check=next(c for c in evaluate_geometry(free,_hinge_shapes())['checks'] if c['id']=='press')
    assert check['verdict']=='fail' and check['blocking']['verdict']=='fail'


@kernel
def test_axis_play_envelope_catches_collision_hidden_at_nominal_axis():
    from cadmcp_brain.studio.recipe import evaluate_geometry
    from test_recipe_operations import hinge_recipe
    # Nominal: the far corner closes the 2 mm gap at 3.82 deg; 3.5 deg leaves about 0.17 mm.
    nominal=hinge_recipe(3.5)
    check=next(c for c in evaluate_geometry(nominal,_hinge_shapes())['checks'] if c['id']=='press')
    assert check['verdict']=='pass' and check['axis_offsets_evaluated']==1
    played=hinge_recipe(3.5);played['rotation_checks'][0]['axis_play_mm']=.5
    check=next(c for c in evaluate_geometry(played,_hinge_shapes())['checks'] if c['id']=='press')
    assert check['verdict']=='fail' and check['axis_offsets_evaluated']==9


def test_blocked_check_cannot_also_claim_end_engagement():
    from pydantic import ValidationError
    from test_recipe_operations import hinge_recipe
    data=hinge_recipe(5.);data['rotation_checks'][0].update(expect='blocked',end_max_distance_mm=.1)
    with pytest.raises(ValidationError):Recipe.model_validate(data)


def test_evidence_summary_keeps_nested_sub_verdicts():
    from cadmcp_brain.studio.evidence_state import _summary
    summary=_summary({'id':'x','verdict':'pass','end_pose_engagement':{'verdict':'pass','end_min_distance_mm':0.,'scope':'long'},
                      'blocking':None})
    assert summary['end_pose_engagement']=={'verdict':'pass','end_min_distance_mm':0.}


@kernel
def test_motion_start_offset_chains_a_second_leg():
    import cadquery as cq
    from cadmcp_brain.studio.recipe import evaluate_geometry
    data=_wall_recipe(.5);data['wall_checks']=[]
    data['operations'].append({'id':'post','op':'box','function_id':'Tube','reason':'Obstacle beside the second leg.',
                               'size_mm':[2.,2.,2.],'center_mm':[24.5,0.,-10.]})
    data['operations'].append({'id':'both','op':'union','function_id':'Tube','reason':'Keep the obstacle in the graph.',
                               'operands':['tube','post']})
    data['outputs']=[{'part_id':'tube','node':'tube'},{'part_id':'post','node':'post'}]
    data['operations'].pop()
    tube=cq.Solid.makeCylinder(5.,10.).cut(cq.Solid.makeCylinder(4.2,10.))
    post=cq.Solid.makeBox(2.,2.,2.,cq.Vector(23.5,-1.,-11.))  # meets the tube wall, not its bore
    def leg(start):
        d=copy.deepcopy(data)
        d['motion_checks']=[{'id':'leg','moving_part':'tube','obstacles':['post'],'start_translation_mm':start,
                             'translation_end_mm':[0.,0.,-20.],'samples':9,'max_samples':17}]
        return next(c for c in evaluate_geometry(d,{'tube':tube,'post':post})['checks'] if c['id']=='leg')
    assert leg([0.,0.,0.])['verdict']=='pass'
    assert leg([20.,0.,0.])['verdict']=='fail'


@kernel
def test_rotation_start_angle_and_offset_shift_the_sweep():
    from cadmcp_brain.studio.recipe import evaluate_geometry
    from test_recipe_operations import hinge_recipe
    # From 4.5 deg onward the far corner is already in the stop: a sweep that
    # starts there is blocked from its first sample.
    late=hinge_recipe(5.);late['rotation_checks'][0].update(start_deg=4.5,expect='blocked',samples=3,max_samples=3)
    check=next(c for c in evaluate_geometry(late,_hinge_shapes())['checks'] if c['id']=='press')
    assert check['blocking']['per_offset'][0]['first_blocked_angle_deg']==4.5
    # Lifting the button 3 mm first moves it clear of the stop over the same sweep.
    lifted=hinge_recipe(5.);lifted['rotation_checks'][0].update(start_translation_mm=[0.,0.,3.])
    check=next(c for c in evaluate_geometry(lifted,_hinge_shapes())['checks'] if c['id']=='press')
    assert check['verdict']=='pass'
    unlifted=hinge_recipe(5.)
    assert next(c for c in evaluate_geometry(unlifted,_hinge_shapes())['checks'] if c['id']=='press')['verdict']=='fail'


def test_rotation_needs_a_nonzero_sweep():
    from pydantic import ValidationError
    from test_recipe_operations import hinge_recipe
    data=hinge_recipe(5.);data['rotation_checks'][0]['start_deg']=5.
    with pytest.raises(ValidationError):Recipe.model_validate(data)
