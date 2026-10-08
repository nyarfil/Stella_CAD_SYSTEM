from __future__ import annotations

import importlib.util

import pytest

from cadmcp_brain.studio.mechanism_templates import (cantilever_main_click, flexure_side_carrier, main_click_switch_fit)
from cadmcp_brain.studio.recipe import Recipe
from cadmcp_brain.studio.switch_profiles import PROFILES

kernel=pytest.mark.skipif(importlib.util.find_spec('cadquery') is None,reason='CadQuery kernel is not installed')


def _build(recipe,tmp_path,name):
    from cadmcp_brain.studio.recipe import execute_recipe
    result=execute_recipe(Recipe.model_validate(recipe),{},tmp_path/name)
    failed=[c['id'] for c in result['checks'] if c['verdict']!='pass']
    assert result['geometry_checks_verdict']=='pass',failed
    return {c['id']:c for c in result['checks']}


def test_templates_refuse_switches_without_the_needed_datasheet_values():
    # A fixed (non-adjustable) gap needs the free position; OMRON D2F does not tabulate it for pin plungers.
    assert main_click_switch_fit(PROFILES['omron_d2f_pin'])['verdict']=='unverified'
    with pytest.raises(ValueError,match='free_position'):
        cantilever_main_click('omron_d2f_pin')
    with pytest.raises(ValueError):
        flexure_side_carrier('kailh_gm20')


def test_templates_are_valid_contracts_with_elastic_checks():
    main=Recipe.model_validate(cantilever_main_click())
    assert [f.beam_node for f in main.flexure_checks]==['tongue'] and main.press_fits[0].part_b=='shell'
    pins=Recipe.model_validate(flexure_side_carrier())
    assert {f.beam_node for f in pins.flexure_checks}=={'bar_1','bar_2'}
    assert {f.part_a for f in pins.press_fits}=={'rear_pin','front_pin'} and len(pins.motion_checks)==2
    hooks=Recipe.model_validate(flexure_side_carrier(retention='snap_hooks'))
    assert {f.beam_node for f in hooks.flexure_checks}=={'bar_1','bar_2','rear_hook_arm','front_hook_arm'}
    assert not hooks.press_fits


@kernel
def test_cantilever_main_click_builds_and_passes(tmp_path):
    checks=_build(cantilever_main_click(),tmp_path,'main')
    tongue=checks['tongue-beam']
    assert tongue['fatigue']=='UNKNOWN' and tongue['checks']['stress']['peak_mpa']<tongue['checks']['stress']['allowed_mpa']


@kernel
@pytest.mark.parametrize('retention',['insert_pins','snap_hooks'])
def test_flexure_side_carrier_builds_and_passes(tmp_path,retention):
    checks=_build(flexure_side_carrier(retention=retention),tmp_path,retention)
    assert checks['bar-1-beam']['verdict']=='pass' and checks['cap-2-press-to-pin-flush']['verdict']=='pass'
    if retention=='insert_pins':
        fits={c['press_fit_id'] for c in checks.values() if c['kind']=='declared_press_fit_interference'}
        assert {'rear-pin-in-post','front-pin-in-post'}<=fits
        assert checks['rear-pin-insertion']['verdict']=='pass'


@kernel
def test_snap_hook_check_catches_an_overstrained_hook(tmp_path):
    from cadmcp_brain.studio.recipe import execute_recipe
    from cadmcp_brain.studio.mechanism_templates import SIDE_CARRIER_DEFAULTS
    # 1 mm PETG arm, 6 mm long, 0.5 mm undercut: about 33 MPa, above half of the 50 MPa yield.
    recipe=flexure_side_carrier(retention='snap_hooks',p={**SIDE_CARRIER_DEFAULTS,'hook_arm_length_mm':6.,'hook_undercut_mm':.5})
    result=execute_recipe(Recipe.model_validate(recipe),{},tmp_path/'hooks')
    hook=next(c for c in result['checks'] if c['id']=='rear-hook-arm')
    assert hook['verdict']=='fail' and not hook['checks']['stress']['pass']
    assert result['geometry_checks_verdict']=='fail'
