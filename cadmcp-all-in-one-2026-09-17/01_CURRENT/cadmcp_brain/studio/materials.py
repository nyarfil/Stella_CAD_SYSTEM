"""Printed-material library for elastic checks: every number cites its datasheet.

Values are typical properties of 3D-printed ISO test specimens as published by
the material maker. Fatigue strength is not published for these grades and is
UNKNOWN (None); a static check never claims fatigue life.
"""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Orientation = Literal['horizontal', 'vertical']


class MaterialSource(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    title: str
    publisher: str
    url: str
    version: str
    location: str
    accessed: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')


class PrintedMaterial(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    id: str = Field(pattern=r'^[a-z0-9_]+$')
    name: str
    source: MaterialSource
    # A None entry is UNKNOWN (the datasheet gives no value for that orientation); it is never substituted.
    tensile_modulus_gpa: dict[Orientation, float | None]
    flexural_modulus_gpa: dict[Orientation, float | None]
    tensile_yield_mpa: dict[Orientation, float | None] = Field(default_factory=lambda: {'horizontal': None, 'vertical': None})
    tensile_strength_mpa: dict[Orientation, float | None] = Field(default_factory=lambda: {'horizontal': None, 'vertical': None})
    flexural_strength_mpa: dict[Orientation, float | None]
    elongation_at_yield_pct: dict[Orientation, float | None] = Field(default_factory=lambda: {'horizontal': None, 'vertical': None})
    elongation_at_break_pct: dict[Orientation, float | None] = Field(default_factory=lambda: {'horizontal': None, 'vertical': None})
    interlayer_adhesion_mpa: float | None = None
    fatigue_strength_mpa: float | None = None  # UNKNOWN unless a source gives it
    orientation_note: str = ('"horizontal" and "vertical xz" are the datasheet specimen print directions; a printed '
                             'feature uses the one whose bending stress runs along its extrusion lines.')
    default_for_projects: bool = False


ACCESSED = '2026-10-07'
DEFAULT_MATERIAL = 'polymaker_polylite_abs'  # owner policy: ABS only
MATERIALS = {m.id: m for m in [
    PrintedMaterial(
        id='polymaker_polylite_abs', name='Polymaker PolyLite ABS',
        source=MaterialSource(title='Technical Data Sheet - PolyLite ABS', publisher='Polymaker',
                              url='https://polymaker.com/wp-content/uploads/lana-downloads/TDS_Polymaker_PolyLite-ABS_V5.6_2025-12-30_EN.pdf',
                              version='V5.6 (2025-12-30)', location='Mechanical properties table (ISO 527 / ISO 178, 100% infill specimens)',
                              accessed=ACCESSED),
        tensile_modulus_gpa={'horizontal': 2.2466, 'vertical': 2.0809}, flexural_modulus_gpa={'horizontal': 2.1272, 'vertical': None},
        tensile_strength_mpa={'horizontal': 33.4, 'vertical': 29.7}, flexural_strength_mpa={'horizontal': 56.2, 'vertical': None},
        elongation_at_break_pct={'horizontal': 17.9, 'vertical': 3.1},
        orientation_note='"horizontal" is the datasheet X-Y direction (in the layer plane); "vertical" is Z (across layers). '
                         'Z bending values are N/A in the datasheet and stay UNKNOWN. Tensile yield is not published; tensile strength is.',
        default_for_projects=True),
    PrintedMaterial(
        id='prusament_petg', name='Prusament PETG',
        source=MaterialSource(title='Technical datasheet - Prusament PETG by Prusa Polymers', publisher='Prusa Polymers a.s.',
                              url='https://prusament.com/wp-content/uploads/2022/10/PETG_Prusament_TDS_2021_10_EN.pdf',
                              version='1.1 (last update 16-02-2022)',
                              location='Page 2, Mechanical properties of 3D printed testing specimens; Typical material properties',
                              accessed=ACCESSED),
        tensile_modulus_gpa={'horizontal': 1.5, 'vertical': 1.6}, flexural_modulus_gpa={'horizontal': 1.7, 'vertical': 1.6},
        tensile_yield_mpa={'horizontal': 47., 'vertical': 50.}, flexural_strength_mpa={'horizontal': 66., 'vertical': 70.},
        elongation_at_yield_pct={'horizontal': 5.1, 'vertical': 5.1}, interlayer_adhesion_mpa=18.),
    PrintedMaterial(
        id='prusament_pla', name='Prusament PLA',
        source=MaterialSource(title='Technical datasheet - Prusament PLA by Prusa Polymers', publisher='Prusa Polymers a.s.',
                              url='https://prusament.com/wp-content/uploads/2022/10/PLA_Prusament_TDS_2021_10_EN.pdf',
                              version='1.1 (last update 16-02-2022)',
                              location='Page 2, Mechanical properties of 3D printed testing specimens; Typical material properties',
                              accessed=ACCESSED),
        tensile_modulus_gpa={'horizontal': 2.3, 'vertical': 2.4}, flexural_modulus_gpa={'horizontal': 3.1, 'vertical': 3.2},
        tensile_yield_mpa={'horizontal': 51., 'vertical': 59.}, flexural_strength_mpa={'horizontal': 83., 'vertical': 99.},
        elongation_at_yield_pct={'horizontal': 2.9, 'vertical': 3.2}, interlayer_adhesion_mpa=17.),
]}
