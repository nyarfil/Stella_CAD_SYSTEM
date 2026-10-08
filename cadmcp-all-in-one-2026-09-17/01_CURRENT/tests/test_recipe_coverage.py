"""Tolerance coverage audit and stop-travel checks (system lessons from the r18 review). Synthetic, fast."""
from __future__ import annotations

import copy
import importlib.util
import math

import pytest
from pydantic import ValidationError

from cadmcp_brain.studio.recipe import Recipe, evaluate_geometry

kernel=pytest.mark.skipif(importlib.util.find_spec('cadquery') is None,reason='Requires the real CAD kernel.')

# block: x 0..10, y 0..2, z 0..2 (plunger reference point at x=2 on its underside). post top at y=-1 under x 6..10.
SIN2=math.sin(math.radians(2.))
YAW_TRAVEL=1.-8*SIN2  # corner (10,0) drops 10 sin(2deg); the reference point at x=2 drops 2 sin(2deg)


def box(node_id,lo,hi):
    return {'id':node_id,'op':'box','function_id':'F','reason':'Synthetic block for a check trial.',
            'size_mm':[h-l for l,h in zip(lo,hi)],'center_mm':[(h+l)/2 for l,h in zip(lo,hi)]}


def stop_check(**extra):
    check={'id':'stop','moving_part':'block','stop_obstacles':['post'],'reference_point':[2.,0.,1.],'reference_direction':[0.,-1.,0.],
           'required_min_travel_mm':.9,'requirement_source':'synthetic requirement for the trial',
           'load_cases':[{'id':'centre','direction':[0.,-1.,0.],'max_travel_mm':3.},
                         {'id':'yaw','direction':[0.,-1.,0.],'max_travel_mm':3.,
                          'rotation':{'axis_point':[0.,0.,0.],'axis_direction':[0.,0.,1.],'angle_deg':-2.}}]}
    check.update(extra)
    return check


def recipe(**extra):
    data={'title':'Coverage trial','original_request':'Synthetic block on a stop post.',
          'functions':{'F':'Trial function.'},
          'design_basis':{'kind':'first_principles','summary':'Synthetic trial geometry.','assumptions':['None; trial only.']},
          'verification_plan':['Measure the stop travel of the block.'],
          'operations':[box('block',[0,0,0],[10,2,2]),box('post',[6,-5,0],[10,-1,2]),box('wall',[0,-5,0],[1,-4,2]),box('beam',[0,6,0],[10,8,2])],
          'outputs':[{'part_id':p,'node':p} for p in ('block','post','wall','beam')],
          'unverified_requirements':['Trial only.']}
    data.update(extra)
    return data


def shapes(data):
    import cadquery as cq
    out={}
    for op in data['operations']:
        out[op['id']]=cq.Workplane('XY').box(*op['size_mm']).val().translate(tuple(op['center_mm']))
    return {o['part_id']:out[o['node']] for o in data['outputs']}


def run(data):
    return {c['id']:c for c in evaluate_geometry(Recipe.model_validate(data),shapes(data))['checks']}


TOL={'id':'place','part':'block','translation_mm':[0.,.1,0.],'basis':'synthetic placement tolerance of the block'}
GAP='declared placement tolerance not applied: place'


@kernel
def test_pure_translation_passes_but_yaw_case_fails_with_analytic_number():
    centre=run(recipe(stop_travel_checks=[stop_check(load_cases=[stop_check()['load_cases'][0]])]))['stop']
    assert centre['verdict']=='pass' and abs(centre['min_reference_travel_mm']-1.)<.01
    both=run(recipe(stop_travel_checks=[stop_check()]))['stop']
    assert both['verdict']=='fail' and both['governing_load_case']=='yaw'
    assert abs(both['min_reference_travel_mm']-YAW_TRAVEL)<.01
    assert both['governing_stop_obstacle']=='post' and both['margin_left_mm']<0
    case=next(c for c in both['cases'] if c['load_case']=='yaw')
    assert case['s_contact_mm']-case['s_clear_mm']<=.005+1e-9
    assert 'elastic' in both['scope']


@kernel
def test_requirement_met_by_every_case_passes_and_margin_is_subtracted():
    ok=run(recipe(stop_travel_checks=[stop_check(required_min_travel_mm=.6)]))['stop']
    assert ok['verdict']=='pass' and abs(ok['margin_left_mm']-(YAW_TRAVEL-.6))<.01
    tight=run(recipe(stop_travel_checks=[stop_check(required_min_travel_mm=.6,margin_mm=.2)]))['stop']
    assert tight['verdict']=='fail'


@kernel
def test_placement_corner_yaw_reduces_travel():
    yaw={'id':'place-yaw','part':'block','rotation_deg':2.,'rotation_axis':[0.,0.,1.],'rotation_origin_mm':[0.,0.,0.],'basis':'synthetic yaw tolerance of the block'}
    data=recipe(placement_tolerances=[yaw],stop_travel_checks=[stop_check(required_min_travel_mm=.9,tolerance_ids=['place-yaw'],
                                                                         load_cases=[stop_check()['load_cases'][0]])])
    check=run(data)['stop']
    assert check['cases_evaluated']==3 and check['verdict']=='fail'  # nominal and both yaw corners
    assert abs(check['min_reference_travel_mm']-YAW_TRAVEL)<.01
    assert check['governing_placement']['place-yaw']['rotation_deg']==-2.
    # a pure Y shift of the block moves the reference with it: the stop is fixed on the shell, so the travel is unchanged
    shift=recipe(placement_tolerances=[TOL],stop_travel_checks=[stop_check(tolerance_ids=['place'],load_cases=[stop_check()['load_cases'][0]])])
    assert abs(run(shift)['stop']['min_reference_travel_mm']-1.)<.01


@kernel
def test_stop_not_reached_fails():
    check=run(recipe(stop_travel_checks=[stop_check(load_cases=[{'id':'short','direction':[0.,-1.,0.],'max_travel_mm':.5}])]))['stop']
    assert check['verdict']=='fail' and 'stop not reached' in check['cases'][0]['reason']


@kernel
def test_other_obstacle_touched_before_stop_fails():
    # a second obstacle is under the block's near end: touching it at 0.4 mm happens before the post at 1.0 mm
    data=recipe(stop_travel_checks=[stop_check(other_obstacles=['wall'],load_cases=[stop_check()['load_cases'][0]])])
    data['operations'][2]=box('wall',[0,-5,0],[3,-.4,2])
    check=run(data)['stop']
    assert check['verdict']=='fail' and check['cases'][0]['other_obstacle']=='wall'
    assert abs(check['cases'][0]['reference_travel_mm']-.4)<.02


@kernel
def test_missing_tolerance_id_is_unverified_and_never_pass():
    data=recipe(placement_tolerances=[TOL],stop_travel_checks=[stop_check(required_min_travel_mm=.6)])
    check=run(data)['stop']
    assert check['verdict']=='unverified' and check['reason']==GAP and check['computed_verdict']=='pass'
    result=evaluate_geometry(Recipe.model_validate(data),shapes(data))
    assert result['geometry_checks_verdict']!='pass' and result['unverified_checks']==['stop']


@kernel
def test_audit_applies_to_clearance_translation_and_rotation_checks():
    data=recipe(placement_tolerances=[TOL],
                clearance_checks=[{'id':'clr','part_a':'block','part_b':'beam','min_mm':1.},
                                  {'id':'clr-far','part_a':'wall','part_b':'beam','min_mm':1.}],
                motion_checks=[{'id':'move','moving_part':'block','obstacles':['beam'],'translation_end_mm':[0.,1.,0.],'samples':2,'max_samples':3}],
                rotation_checks=[{'id':'turn','moving_part':'block','obstacles':['beam'],'axis_origin_mm':[0.,0.,0.],'axis_direction':[0.,0.,1.],
                                  'end_deg':1.,'samples':2,'max_samples':3}])
    checks=run(data)
    for name in ('clr','move','turn'):
        assert checks[name]['verdict']=='unverified' and checks[name]['reason']==GAP,name
    assert checks['clr-far']['verdict']=='pass' and checks['clr-far']['waived_tolerances']==[]  # does not touch the toleranced part


@kernel
def test_waiver_is_reported_and_not_unverified():
    waiver={'id':'place','reason':'the block does not move in this synthetic check'}
    data=recipe(placement_tolerances=[TOL],
                clearance_checks=[{'id':'clr','part_a':'block','part_b':'beam','min_mm':1.,'tolerance_waivers':[waiver]}],
                stop_travel_checks=[stop_check(required_min_travel_mm=.6,tolerance_waivers=[waiver])])
    checks=run(data)
    assert checks['clr']['verdict']=='pass' and checks['clr']['waived_tolerances']==[waiver]
    assert checks['stop']['verdict']=='pass' and checks['stop']['waived_tolerances']==[waiver]


@kernel
def test_applied_tolerance_has_no_gap_and_eight_ids_are_allowed():
    data=recipe(placement_tolerances=[TOL],clearance_checks=[{'id':'clr','part_a':'block','part_b':'beam','min_mm':1.,'tolerance_ids':['place']}])
    check=run(data)['clr']
    assert check['verdict']=='pass' and 'reason' not in check
    tolerances=[{**TOL,'id':f'place{i}'} for i in range(8)]
    Recipe.model_validate(recipe(placement_tolerances=tolerances,clearance_checks=[
        {'id':'clr','part_a':'block','part_b':'beam','min_mm':1.,'tolerance_ids':[t['id'] for t in tolerances]}]))


def test_validation_errors():
    def bad(match,**extra):
        with pytest.raises(ValidationError,match=match):Recipe.model_validate(recipe(**extra))
    good=stop_check()
    Recipe.model_validate(recipe(stop_travel_checks=[good]))
    bad('output parts',stop_travel_checks=[stop_check(stop_obstacles=['nowhere'])])
    bad('distinct',stop_travel_checks=[stop_check(other_obstacles=['post'])])
    bad('distinct',stop_travel_checks=[stop_check(carried_parts=['post'])])
    bad('distinct',stop_travel_checks=[stop_check(stop_obstacles=['block'])])
    bad('unit vector',stop_travel_checks=[stop_check(reference_direction=[0.,-2.,0.])])
    bad('unit vector',stop_travel_checks=[stop_check(load_cases=[{'id':'c','direction':[0.,-2.,0.],'max_travel_mm':1.}])])
    bad('unit direction',stop_travel_checks=[stop_check(load_cases=[{'id':'c','direction':[0.,-1.,0.],'max_travel_mm':1.,
                                                                       'rotation':{'axis_point':[0,0,0],'axis_direction':[0,0,2],'angle_deg':1.}}])])
    bad('Duplicate load-case',stop_travel_checks=[stop_check(load_cases=[stop_check()['load_cases'][0]]*2)])
    bad('undeclared placement tolerance',stop_travel_checks=[stop_check(tolerance_ids=['place'])])
    bad('Waiver names an undeclared',stop_travel_checks=[stop_check(tolerance_waivers=[{'id':'place','reason':'a long enough reason'}])])
    bad('Field required|at least 1',stop_travel_checks=[stop_check(stop_obstacles=[])])
    bad('greater than 0',stop_travel_checks=[stop_check(required_min_travel_mm=0.)])
    bad('at least 10',placement_tolerances=[TOL],stop_travel_checks=[stop_check(tolerance_waivers=[{'id':'place','reason':'short'}])])
    bad('applied or waived once',placement_tolerances=[TOL],stop_travel_checks=[stop_check(tolerance_ids=['place'],
                                                                                             tolerance_waivers=[{'id':'place','reason':'a long enough reason'}])])
    bad('Duplicate check IDs',stop_travel_checks=[good,copy.deepcopy(good)])
    bad('at most 6|too_long',stop_travel_checks=[stop_check(load_cases=[{**good['load_cases'][0],'id':f'c{i}'} for i in range(7)])])
