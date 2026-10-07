"""Shell, revolve, spline loft, mirror, edge finishing and rotation clearance."""
from __future__ import annotations

import copy
import importlib.util
import math

import pytest
from pydantic import ValidationError

from cadmcp_brain.studio.planning import capabilities
from cadmcp_brain.studio.recipe import Recipe

kernel=pytest.mark.skipif(importlib.util.find_spec('cadquery') is None,
                          reason='Recipe execution requires the real CAD kernel.')


def ellipse(a, b, count=12):
    return [[a*math.cos(2*math.pi*i/count), b*math.sin(2*math.pi*i/count)] for i in range(count)]


def base(operations, outputs, **extra):
    data={
        'title':'Bounded operation trial',
        'original_request':'Build a bounded mouse-like shell and a hinged button trial.',
        'functions':{'Shell':'Provide a hollow palm-contact shell.',
                     'Button':'Provide a pivoting primary button.',
                     'Wheel':'Provide a revolved wheel trial.'},
        'design_basis':{'kind':'first_principles',
                        'summary':'Explicit trial geometry exercising the bounded recipe operations.',
                        'assumptions':['Material, fit and wall stiffness remain unqualified.']},
        'verification_plan':['Export STEP and measure solid count, bounds and clearances.'],
        'operations':operations,'outputs':outputs,
        'unverified_requirements':['Hand fit, stiffness and production remain unverified.'],
    }
    data.update(extra)
    return data


def spline_shell_ops(wall=1.5, open_faces=('<Z',)):
    return [
        {'id':'outer','op':'spline_loft','function_id':'Shell',
         'reason':'Blend smooth closed palm sections into one outer volume.',
         'sections':[{'z_mm':0.,'points_mm':ellipse(60.,32.)},
                     {'z_mm':18.,'points_mm':ellipse(55.,30.)},
                     {'z_mm':34.,'points_mm':ellipse(36.,18.)}]},
        {'id':'hollow','op':'shell','function_id':'Shell','source':'outer',
         'reason':'Hollow the shell inward while keeping the outer palm skin.',
         'wall_mm':wall,'open_faces':list(open_faces)},
    ]


@kernel
def test_spline_loft_shell_keeps_outer_skin_and_removes_material(tmp_path):
    from cadmcp_brain.studio.recipe import execute_recipe
    data=base(spline_shell_ops(),[{'part_id':'shell','node':'hollow'}],
              # A periodic spline through the ellipse points bulges slightly
              # between them, so the length is checked at the 0.5 mm level.
              dimension_checks=[{'id':'length','part':'shell','kind':'bbox','axis':'x','nominal_mm':120.,'tolerance_mm':.5},
                                {'id':'height','part':'shell','kind':'bbox','axis':'z','nominal_mm':34.,'tolerance_mm':1e-3}])
    result=execute_recipe(Recipe.model_validate(data),{},tmp_path/'shell')
    assert result['geometry_checks_verdict']=='pass', [c for c in result['checks'] if c['verdict']!='pass']
    trace={row['node']:row for row in result['trace']}
    assert 0<trace['hollow']['volume_mm3']<0.5*trace['outer']['volume_mm3']
    assert (tmp_path/'shell'/'shell'/'model.step').is_file()


@kernel
def test_revolve_mirror_and_edge_finish_build_real_solids(tmp_path):
    from cadmcp_brain.studio.recipe import execute_recipe
    operations=[
        {'id':'wheel','op':'revolve','function_id':'Wheel','reason':'Revolve a grooved wheel profile about its axle.',
         'profile_rz_mm':[[1.5,-3.5],[11.,-3.5],[12.,-1.],[11.,0.],[12.,1.],[11.,3.5],[1.5,3.5]],'angle_deg':360.},
        {'id':'key','op':'box','function_id':'Button','reason':'Create the right-hand button plate.',
         'size_mm':[20.,30.,3.],'center_mm':[30.,0.,20.]},
        {'id':'key_round','op':'fillet_edges','function_id':'Button','reason':'Round only the vertical plate corners.',
         'source':'key','selector':'|Z','size_mm':2.},
        {'id':'key_left','op':'mirror','function_id':'Button','reason':'Mirror the right button to the left side.',
         'source':'key_round','plane':'YZ'},
        {'id':'key_edge','op':'chamfer_edges','function_id':'Button','reason':'Chamfer the top finger edge of the left button.',
         'source':'key_left','selector':'>Z','size_mm':.5},
    ]
    data=base(operations,[{'part_id':'wheel','node':'wheel'},{'part_id':'right','node':'key_round'},
                          {'part_id':'left','node':'key_edge'}],
              dimension_checks=[{'id':'wheel_od','part':'wheel','kind':'bbox','axis':'x','nominal_mm':24.,'tolerance_mm':1e-3}])
    result=execute_recipe(Recipe.model_validate(data),{},tmp_path/'ops')
    assert result['geometry_checks_verdict']=='pass', [c for c in result['checks'] if c['verdict']!='pass']
    trace={row['node']:row for row in result['trace']}
    assert trace['key_round']['volume_mm3']<trace['key']['volume_mm3']
    assert trace['key_edge']['volume_mm3']<trace['key_left']['volume_mm3']
    assert math.isclose(trace['key_left']['volume_mm3'],trace['key_round']['volume_mm3'],rel_tol=1e-9)


@kernel
def test_shell_failure_is_reported_without_reducing_wall(tmp_path):
    from cadmcp_brain.errors import BrainError
    from cadmcp_brain.studio.recipe import execute_recipe
    data=base(spline_shell_ops(wall=40.),[{'part_id':'shell','node':'hollow'}])
    with pytest.raises(BrainError) as exc:
        execute_recipe(Recipe.model_validate(data),{},tmp_path/'bad')
    assert exc.value.code=='STUDIO_SHELL' and exc.value.details['wall_mm']==40.


def hinge_recipe(end_deg, gap_mm=2.):
    operations=[
        {'id':'stop','op':'box','function_id':'Shell','reason':'Fixed stop under the front of the button.',
         'size_mm':[10.,10.,2.],'center_mm':[25.,0.,-1.-gap_mm]},
        {'id':'button','op':'box','function_id':'Button','reason':'Button lever pivoting at its rear edge.',
         'size_mm':[30.,10.,2.],'center_mm':[15.,0.,1.]},
    ]
    return base(operations,[{'part_id':'stop','node':'stop'},{'part_id':'button','node':'button'}],
                rotation_checks=[{'id':'press','moving_part':'button','obstacles':['stop'],
                                  'axis_origin_mm':[0.,0.,0.],'axis_direction':[0.,1.,0.],
                                  'end_deg':end_deg,'samples':5,'max_samples':65}])


@kernel
def test_rotation_check_detects_hinge_collision_and_certifies_free_travel():
    import cadquery as cq
    from cadmcp_brain.studio.recipe import evaluate_geometry
    def shapes(gap):
        return {'stop':cq.Workplane().box(10.,10.,2.).val().translate((25.,0.,-1.-gap)),
                'button':cq.Workplane().box(30.,10.,2.).val().translate((15.,0.,1.))}
    # Rotating about +Y by a positive angle lowers +X; 2 mm gap at x=20 closes near 5.7 deg.
    free=evaluate_geometry(hinge_recipe(2.),shapes(2.))
    check=next(c for c in free['checks'] if c['id']=='press')
    assert check['kind']=='sampled_rotation_clearance' and check['verdict']=='pass'
    assert check['continuous_swept_motion']=='distance_bound_satisfied_under_stated_assumptions'
    assert 0<check['continuous_distance_lower_bound_mm']<=min(s['distance_mm'] for s in check['samples'])
    hit=evaluate_geometry(hinge_recipe(12.),shapes(2.))
    check=next(c for c in hit['checks'] if c['id']=='press')
    assert check['verdict']=='fail' and hit['geometry_checks_verdict']=='fail'
    assert check['continuous_swept_motion']=='not_proven'


@pytest.mark.parametrize('mutation',['negative_radius','spline_reverse_z','spline_winding','duplicate_face',
                                     'zero_rotation','bad_axis','unknown_selector'])
def test_new_operation_contracts_reject_invalid_input(mutation):
    data=base(spline_shell_ops(),[{'part_id':'shell','node':'hollow'}])
    ops=data['operations']
    if mutation=='negative_radius':
        data['operations']=[{'id':'w','op':'revolve','function_id':'Wheel','reason':'Profile crosses the axis.',
                             'profile_rz_mm':[[-1.,0.],[5.,0.],[5.,3.]],'angle_deg':360.}]
        data['outputs']=[{'part_id':'w','node':'w'}]
    elif mutation=='spline_reverse_z':ops[0]['sections'][2]['z_mm']=5.
    elif mutation=='spline_winding':ops[0]['sections'][1]['points_mm'].reverse()
    elif mutation=='duplicate_face':ops[1]['open_faces']=['<Z','<Z']
    elif mutation=='unknown_selector':ops[1]['open_faces']=['%PLANE']
    else:
        data=hinge_recipe(5.)
        rotation=data['rotation_checks'][0]
        if mutation=='zero_rotation':rotation['end_deg']=0.
        else:rotation['axis_direction']=[0.,2.,0.]
    with pytest.raises(ValidationError):
        Recipe.model_validate(data)


@pytest.mark.parametrize('op',[{'op':'shell','wall_mm':1.},{'op':'mirror','plane':'XY'},
                               {'op':'fillet_edges','selector':'|Z','size_mm':.5}])
def test_protected_hardware_cannot_be_reshaped(op):
    data=base([{'id':'pcb','op':'project_step','function_id':'Shell','reason':'Protected board as registered.',
                'artifact_id':'board','sha256':'0'*64,'role':'protected_hardware',
                'unit_basis':'Registered STEP in millimetres.'},
               {'id':'changed','function_id':'Shell','reason':'Attempt to reshape protected hardware.',
                'source':'pcb',**op}],
              [{'part_id':'changed','node':'changed'}])
    with pytest.raises(ValidationError,match='Protected hardware'):
        Recipe.model_validate(data)


def test_capabilities_advertise_new_operations_and_rotation_check():
    report=capabilities(['shell','revolve','spline_loft','mirror','fillet_edges','chamfer_edges'],
                        ['sampled_rotation_clearance'])
    assert report['requested_capabilities_supported'] is True
    assert capabilities(['surface_loft'])['unsupported_operations']==['surface_loft']


def test_rotation_checks_are_frozen_in_correction_lineage():
    from cadmcp_brain.studio.runtime import Studio
    original=Recipe.model_validate(hinge_recipe(5.))
    weakened=copy.deepcopy(hinge_recipe(5.));weakened['rotation_checks'][0]['end_deg']=1.
    assert (Studio._lineage_contract(original)!=
            Studio._lineage_contract(Recipe.model_validate(weakened)))


SQUARE=[[-1.,-1.],[1.,-1.],[1.,1.],[-1.,1.]]


def _single(op):
    return base([op],[{'part_id':'p','node':op['id']}])


@kernel
def test_sweep_polyline_volume_and_spline_path_build(tmp_path):
    from cadmcp_brain.studio.recipe import execute_recipe
    straight=_single({'id':'tube','op':'sweep','function_id':'Shell','reason':'Square channel along an L-shaped path.',
                      'profile_mm':SQUARE,'path_mm':[[0.,0.,0.],[0.,0.,20.],[20.,0.,20.]],
                      'path_kind':'polyline','transition':'right'})
    result=execute_recipe(Recipe.model_validate(straight),{},tmp_path/'l')
    assert result['geometry_checks_verdict']=='pass'
    # Mitred corner: 4 mm2 section times 40 mm centreline.
    assert abs(result['trace'][0]['volume_mm3']-160.)<1e-6
    curved=_single({'id':'tube','op':'sweep','function_id':'Shell','reason':'Square channel along a smooth path.',
                    'profile_mm':SQUARE,'path_mm':[[0.,0.,0.],[5.,0.,10.],[15.,5.,15.],[25.,5.,15.]],'path_kind':'spline'})
    assert execute_recipe(Recipe.model_validate(curved),{},tmp_path/'s')['geometry_checks_verdict']=='pass'


@kernel
def test_section_loft_on_non_parallel_planes(tmp_path):
    from cadmcp_brain.studio.recipe import execute_recipe
    r=2**-.5
    data=_single({'id':'bend','op':'section_loft','function_id':'Shell','reason':'Bend through perpendicular sections.',
                  'profile':'polygon','mode':'smooth','sections':[
                      {'origin_mm':[0.,0.,0.],'normal':[0.,0.,1.],'x_dir':[1.,0.,0.],'points_mm':SQUARE},
                      {'origin_mm':[5.,0.,8.],'normal':[r,0.,r],'x_dir':[r,0.,-r],'points_mm':SQUARE},
                      {'origin_mm':[14.,0.,12.],'normal':[1.,0.,0.],'x_dir':[0.,0.,-1.],'points_mm':SQUARE}]})
    result=execute_recipe(Recipe.model_validate(data),{},tmp_path/'b')
    assert result['geometry_checks_verdict']=='pass'
    bounds=next(c for c in result['checks'] if c['id']=='_system-volume-agreement-p')
    assert bounds['agree'] is True


@pytest.mark.parametrize('mutation',['skew_x_dir','shared_origin','flipped_winding','repeated_path_point','short_spline_path'])
def test_sweep_and_section_loft_contracts(mutation):
    r=2**-.5
    if mutation in ('repeated_path_point','short_spline_path'):
        op={'id':'t','op':'sweep','function_id':'Shell','reason':'Contract trial for sweep paths.','profile_mm':SQUARE,
            'path_mm':[[0.,0.,0.],[0.,0.,0.],[0.,0.,5.]] if mutation=='repeated_path_point' else [[0.,0.,0.],[0.,0.,5.]],
            'path_kind':'polyline' if mutation=='repeated_path_point' else 'spline'}
    else:
        sections=[{'origin_mm':[0.,0.,0.],'normal':[0.,0.,1.],'x_dir':[1.,0.,0.],'points_mm':SQUARE},
                  {'origin_mm':[5.,0.,8.],'normal':[r,0.,r],'x_dir':[r,0.,-r],'points_mm':copy.deepcopy(SQUARE)}]
        if mutation=='skew_x_dir':sections[1]['x_dir']=[1.,0.,0.]
        elif mutation=='shared_origin':sections[1]['origin_mm']=[0.,0.,0.]
        else:sections[1]['points_mm'].reverse()
        op={'id':'t','op':'section_loft','function_id':'Shell','reason':'Contract trial for section lofts.',
            'profile':'polygon','mode':'ruled','sections':sections}
    with pytest.raises(ValidationError):
        Recipe.model_validate(_single(op))
