"""Rendering must not change acceptance measurements or silently widen tolerances."""
import pytest
cq=pytest.importorskip('cadquery')
from cadmcp_brain.studio.measurement import nominal_bounds
from cadmcp_brain.studio.recipe import evaluate_geometry
from test_planning_routes import recipe


def test_tessellation_does_not_change_zero_tolerance_nominal_bbox():
    data=recipe()
    for check in data['dimension_checks']:check['tolerance_mm']=0.
    shape=cq.Workplane('XY').box(20,10,2).val().translate((0,0,1))
    before=evaluate_geometry(data,{'plate':shape})
    shape.tessellate(.01)
    # This exhibits why the cached display box must not be the measurement source.
    assert shape.BoundingBox().xlen>20.
    assert nominal_bounds(shape)==(-10.,-5.,0.,10.,5.,2.)
    after=evaluate_geometry(data,{'plate':shape})
    assert before==after and after['geometry_checks_verdict']=='pass'
    checks=[c for c in after['checks'] if c['kind']=='bbox']
    assert all(c['tolerance_mm']==0. for c in checks)


def test_true_dimension_error_is_not_hidden_by_nominal_measurement():
    data=recipe()
    for check in data['dimension_checks']:check['tolerance_mm']=0.
    shape=cq.Workplane('XY').box(20.001,10,2).val()
    shape.tessellate(.01)
    result=evaluate_geometry(data,{'plate':shape})
    assert result['geometry_checks_verdict']=='fail'
    assert not next(c for c in result['checks'] if c['id']=='size_x')['verdict']=='pass'
