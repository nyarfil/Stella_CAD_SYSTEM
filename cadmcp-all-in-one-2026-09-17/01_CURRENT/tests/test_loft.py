"""Bounded parallel-section lofts for original Studio geometry."""
from __future__ import annotations

import importlib.util

import pytest
from pydantic import ValidationError

pytestmark=pytest.mark.skipif(importlib.util.find_spec('cadquery') is None,
                              reason='Loft generation requires the real CAD kernel.')

from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio.recipe import Recipe, execute_recipe


def loft_recipe(mode='smooth'):
    return {
        'title':'Parallel-section ergonomic shell trial',
        'original_request':'Create a bounded, curved mouse-shell trial volume from stated sections.',
        'functions':{'Shell':'Provide a bounded palm-contact outer trial volume.'},
        'design_basis':{'kind':'first_principles',
                        'summary':'Parallel measured-style sections define an explicit trial palm volume.',
                        'assumptions':['Wall thickness, fit and material behavior remain unqualified.']},
        'verification_plan':['Export the STEP and measure its bounded dimensions and solid count.'],
        'operations':[{
            'id':'shell','op':'loft','function_id':'Shell',
            'reason':'Blend explicit parallel XY palm sections into one bounded trial solid.',
            'mode':mode,
            'sections':[
                {'z_mm':0.,'points_mm':[[-20.,-30.],[20.,-30.],[20.,30.],[-20.,30.]]},
                {'z_mm':12.,'points_mm':[[-28.,-25.],[28.,-25.],[24.,31.],[-24.,31.]]},
                {'z_mm':24.,'points_mm':[[-16.,-18.],[16.,-18.],[14.,22.],[-14.,22.]]},
            ],
        }],
        'outputs':[{'part_id':'shell','node':'shell','expected_solids':1}],
        'dimension_checks':[
            {'id':'shell_height','part':'shell','kind':'bbox','axis':'z','nominal_mm':24.,'tolerance_mm':1e-6},
        ],
        'unverified_requirements':['Shell wall thickness, hand fit and physical production remain unverified.'],
    }


@pytest.mark.parametrize('mode',['smooth','ruled'])
def test_parallel_polygon_loft_exports_one_real_solid(tmp_path,mode):
    result=execute_recipe(Recipe.model_validate(loft_recipe(mode)),{},tmp_path/mode)
    assert result['geometry_checks_verdict']=='pass'
    assert (tmp_path/mode/'shell'/'model.step').is_file()
    assert next(check for check in result['checks'] if check['id']=='solid-count-shell')['verdict']=='pass'
    assert next(check for check in result['checks'] if check['id']=='shell_height')['verdict']=='pass'


@pytest.mark.parametrize('mutation',["one_section","same_z","reverse_z","mismatched_vertices","reverse_winding","self_intersection","out_of_range"])
def test_loft_rejects_invalid_section_contracts(mutation):
    data=loft_recipe(); sections=data['operations'][0]['sections']
    if mutation=='one_section':data['operations'][0]['sections']=sections[:1]
    elif mutation=='same_z':sections[1]['z_mm']=0.
    elif mutation=='reverse_z':sections[2]['z_mm']=6.
    elif mutation=='mismatched_vertices':sections[1]['points_mm']=sections[1]['points_mm'][:3]
    elif mutation=='reverse_winding':sections[1]['points_mm'].reverse()
    elif mutation=='self_intersection':sections[1]['points_mm']=[[-28.,-25.],[28.,31.],[24.,-25.],[-24.,31.]]
    else:sections[0]['points_mm'][0]=[1_000_001.,-30.]
    with pytest.raises(ValidationError):Recipe.model_validate(data)


def test_identical_xy_sections_remain_a_valid_constant_section_loft():
    data=loft_recipe('ruled')
    data['operations'][0]['sections'][1]['points_mm']=data['operations'][0]['sections'][0]['points_mm']
    Recipe.model_validate(data)


def test_loft_kernel_failure_is_rejected_without_fallback(tmp_path,monkeypatch):
    import cadquery as cq
    def rejected(*args,**kwargs):
        raise RuntimeError('forced kernel failure')
    monkeypatch.setattr(cq.Solid,'makeLoft',rejected)
    with pytest.raises(BrainError,match='no fallback geometry') as exc:
        execute_recipe(loft_recipe(),{},tmp_path/'failed')
    assert exc.value.code=='STUDIO_INVALID_SOLID'


@pytest.mark.parametrize('failure',['wire','empty','multiple_solids'])
def test_loft_invalid_kernel_results_are_actionable_not_substituted(tmp_path,monkeypatch,failure):
    import cadquery as cq
    if failure=='wire':
        def invalid_wire(*args,**kwargs):raise ValueError('invalid section wire')
        monkeypatch.setattr(cq.Wire,'makePolygon',invalid_wire)
    elif failure=='empty':
        monkeypatch.setattr(cq.Solid,'makeLoft',lambda *a,**kw:None)
    else:
        bodies=[cq.Solid.makeBox(1,1,1),cq.Solid.makeBox(1,1,1,cq.Vector(3,0,0))]
        monkeypatch.setattr(cq.Solid,'makeLoft',lambda *a,**kw:cq.Compound.makeCompound(bodies))
    with pytest.raises(BrainError,match='no fallback geometry') as exc:
        execute_recipe(loft_recipe(),{},tmp_path/'invalid')
    assert exc.value.code=='STUDIO_INVALID_SOLID'
