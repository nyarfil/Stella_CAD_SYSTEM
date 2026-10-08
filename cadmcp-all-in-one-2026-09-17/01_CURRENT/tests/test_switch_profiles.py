from __future__ import annotations

import pytest
from pydantic import ValidationError

from cadmcp_brain.studio.switch_profiles import (PROFILES, SOURCES, UNKNOWN, SwitchProfile, Value,
                                                  missing_for_click_referenced_stop, profile_report)


def test_every_known_value_cites_a_registered_source():
    for profile in PROFILES.values():
        for name in SwitchProfile.model_fields:
            value=getattr(profile,name)
            if isinstance(value,Value) and value.known:
                assert value.source in SOURCES,(profile.id,name)


def test_unknown_values_cannot_be_filled_without_a_source():
    with pytest.raises(ValidationError):
        Value(value=.3)
    with pytest.raises(ValidationError):
        Value(tolerance=.1)
    assert not UNKNOWN.known


def test_overtravel_is_only_a_guaranteed_minimum():
    with pytest.raises(ValidationError):
        SwitchProfile(id='x',maker='m',model='m',actuator='pin_plunger',height_datum='body_bottom',
                      overtravel=Value(value=.2,source='zippy_df_catalogue',bound='max'))


def test_report_marks_unsourced_switches_as_incomplete():
    rows={r['id']:r for r in profile_report()}
    assert not rows['zippy_df_pin']['missing_for_click_referenced_stop']
    assert not rows['omron_d2f_pin']['missing_for_click_referenced_stop']
    assert 'overtravel' in rows['huano_mouse_generic']['missing_for_click_referenced_stop']
    assert 'overtravel' in rows['kailh_gm20']['missing_for_click_referenced_stop']


def test_datasheet_values_are_as_published():
    zippy,omron=PROFILES['zippy_df_pin'],PROFILES['omron_d2f_pin']
    assert (zippy.operating_position.value,zippy.operating_position.tolerance)==(7.,.2)
    assert (zippy.pretravel.value,zippy.overtravel.value)==(.62,.2)
    assert (omron.operating_position.value,omron.operating_position.tolerance)==(5.5,.3)
    assert (omron.pretravel.value,omron.overtravel.value)==(.5,.25)
    assert missing_for_click_referenced_stop(omron)==[]
