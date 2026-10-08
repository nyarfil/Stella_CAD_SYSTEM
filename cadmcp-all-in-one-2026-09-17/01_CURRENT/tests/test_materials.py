from __future__ import annotations

from cadmcp_brain.studio.materials import MATERIALS


def test_materials_cite_datasheets_and_leave_fatigue_unknown():
    for material in MATERIALS.values():
        assert material.source.url.startswith('https://') and material.source.version
        assert material.fatigue_strength_mpa is None
        for table in (material.tensile_modulus_gpa,material.flexural_modulus_gpa,material.tensile_yield_mpa,material.flexural_strength_mpa):
            assert set(table)=={'horizontal','vertical'} and all(v is None or v>0 for v in table.values())


def test_petg_values_are_as_published():
    petg=MATERIALS['prusament_petg']
    assert petg.flexural_modulus_gpa=={'horizontal':1.7,'vertical':1.6}
    assert petg.tensile_yield_mpa=={'horizontal':47.,'vertical':50.}
    assert petg.interlayer_adhesion_mpa==18.


def test_abs_is_the_project_default_and_keeps_missing_values_unknown():
    from cadmcp_brain.studio.materials import DEFAULT_MATERIAL
    abs_=MATERIALS[DEFAULT_MATERIAL]
    assert abs_.default_for_projects and abs_.flexural_modulus_gpa=={'horizontal':2.1272,'vertical':None}
    assert abs_.tensile_strength_mpa['horizontal']==33.4 and abs_.tensile_yield_mpa=={'horizontal':None,'vertical':None}
