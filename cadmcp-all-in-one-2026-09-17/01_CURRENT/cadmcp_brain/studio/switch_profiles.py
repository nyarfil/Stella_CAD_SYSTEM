"""Switch profile library: part-type mechanical data for mouse micro switches, with sources.

A profile is a catalogue entry for a switch type (not a placed switch; placed
switches live in a board pack). Every number carries the source it came from.
A value that no source gives is UNKNOWN (None) and is never filled with a
guess. Values derived from a drawing rather than read from a table say so.

Designs that must accept several switches check every registered profile and
report a profile whose needed values are UNKNOWN as unverified, not as passed.
"""
from __future__ import annotations
import math
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Source(_Strict):
    id: str = Field(pattern=r'^[a-z0-9_]+$')
    title: str
    publisher: str
    url: str
    location: str = Field(description='Page, table or drawing inside the document.')
    accessed: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    kind: Literal['manufacturer_datasheet', 'seller_page', 'seller_hosted_document']


class Value(_Strict):
    """One quantity. value None means UNKNOWN; bound tells how to read the number."""
    value: float | None = None
    tolerance: float | None = None
    bound: Literal['nominal', 'max', 'min'] = 'nominal'
    unit: Literal['mm', 'gf'] = 'mm'
    source: str | None = None
    note: str = ''

    @model_validator(mode='after')
    def known_values_have_sources(self):
        if self.value is None:
            if self.tolerance is not None:
                raise ValueError('An UNKNOWN value cannot carry a tolerance.')
        else:
            if not math.isfinite(self.value):
                raise ValueError('Values must be finite.')
            if not self.source:
                raise ValueError('A known value needs a source id.')
        return self

    @property
    def known(self) -> bool:
        return self.value is not None


UNKNOWN = Value()


class SwitchProfile(_Strict):
    id: str = Field(pattern=r'^[a-z0-9_]+$')
    maker: str
    model: str
    variants: str = ''
    actuator: Literal['pin_plunger']
    height_datum: Literal['body_bottom', 'mounting_hole_centre']
    body_length: Value = UNKNOWN
    body_width: Value = UNKNOWN
    body_height: Value = Field(UNKNOWN, description='Body top above the height datum.')
    mounting_hole_pitch: Value = UNKNOWN
    mounting_hole_diameter: Value = UNKNOWN
    plunger_width: Value = UNKNOWN
    free_position: Value = Field(UNKNOWN, description='FP above the height datum.')
    operating_position: Value = Field(UNKNOWN, description='OP above the height datum.')
    pretravel: Value = UNKNOWN
    overtravel: Value = UNKNOWN
    movement_differential: Value = UNKNOWN
    operating_force: Value = UNKNOWN
    release_force: Value = UNKNOWN
    status_note: str = ''

    @model_validator(mode='after')
    def bounds_are_meaningful(self):
        if self.overtravel.known and self.overtravel.bound != 'min':
            raise ValueError('Overtravel must be a guaranteed minimum.')
        if self.pretravel.known and self.pretravel.bound == 'min':
            raise ValueError('Pretravel must be a maximum or a nominal with tolerance.')
        return self


ACCESSED = '2026-10-07'
SOURCES = {s.id: s for s in [
    Source(id='zippy_df_catalogue', title='Micro Switches - DF Series', publisher='Zippy Technology Corp.',
           url='https://asset.conrad.com/media10/add/160267/c1/-/en/001094397DS01/datasheet-1094397-zippy-df-03s-1p-z-microswitch-df-03s-1p-z-125-v-ac-3-a-1-x-onon-momentary-1-pcs.pdf',
           location='Catalogue pages 39 (dimensions), 41 (operating characteristics, actuator code 0)',
           accessed=ACCESSED, kind='manufacturer_datasheet'),
    Source(id='omron_d2f_datasheet', title='D2F Ultra Subminiature Basic Switch', publisher='OMRON Corporation',
           url='https://omronfs.omron.com/en_US/ecb/products/pdf/en-d2f.pdf',
           location='Page 4, Pin Plunger Models drawing and operating-characteristics table; page 3 mounting holes',
           accessed=ACCESSED, kind='manufacturer_datasheet'),
    Source(id='huano_seller_manual', title='HUANO Micro Switch for Mouse Product Manual', publisher='Unattributed (hosted by an AliExpress seller)',
           url='https://ae-pic-a1.aliexpress-media.com/kf/Sdadc34f7b5ab4086811cfe358899d335m.pdf',
           location='Mechanical Life and Performance; Physical Specifications (general values, not per model)',
           accessed=ACCESSED, kind='seller_hosted_document'),
    Source(id='mechkeys_kailh_gm20', title='Kailh GM 2.0 Mouse Micro Switch', publisher='MechKeys (seller)',
           url='https://mechkeys.com/products/kailh-gm-2-0-mouse-micro-switch', location='Product description',
           accessed=ACCESSED, kind='seller_page'),
]}


def _v(value, source, bound='nominal', tolerance=None, unit='mm', note=''):
    return Value(value=value, source=source, bound=bound, tolerance=tolerance, unit=unit, note=note)


PROFILES = {p.id: p for p in [
    SwitchProfile(
        id='zippy_df_pin', maker='Zippy', model='DF series, pin plunger (actuator code 0)',
        variants='DF-P1/03/G1/G3/D3 rating codes; L (light) and S (standard) force',
        actuator='pin_plunger', height_datum='body_bottom',
        body_length=_v(12.7, 'zippy_df_catalogue', tolerance=.4), body_width=_v(5.8, 'zippy_df_catalogue', tolerance=.4),
        body_height=_v(6.65, 'zippy_df_catalogue', tolerance=.25),
        mounting_hole_pitch=_v(6.5, 'zippy_df_catalogue', tolerance=.4), mounting_hole_diameter=_v(2.05, 'zippy_df_catalogue'),
        plunger_width=_v(2.9, 'zippy_df_catalogue'),
        free_position=_v(7.35, 'zippy_df_catalogue', bound='max',
                         note='Datum read as the body bottom: FP 7.35 max against a 6.65 body; the drawing datum line itself is not legible.'),
        operating_position=_v(7.0, 'zippy_df_catalogue', tolerance=.2, note='Same datum as FP.'),
        pretravel=_v(.62, 'zippy_df_catalogue', bound='max'), overtravel=_v(.2, 'zippy_df_catalogue', bound='min'),
        movement_differential=_v(.12, 'zippy_df_catalogue', bound='max'),
        operating_force=_v(150., 'zippy_df_catalogue', bound='max', unit='gf', note='S force; L force is 80 gf max.'),
        release_force=_v(35., 'zippy_df_catalogue', bound='min', unit='gf', note='S force; L force is 21 gf min.'),
        status_note='The owner calls it "Zippy DF3"; read here as the DF series pin plunger. Confirm the exact part number.'),
    SwitchProfile(
        id='omron_d2f_pin', maker='OMRON', model='D2F pin plunger (D2F, D2F-01, D2F-F, D2F-01F, D2F-5)',
        variants='1.47 N or 0.74 N operating force', actuator='pin_plunger', height_datum='mounting_hole_centre',
        body_length=_v(12.7, 'omron_d2f_datasheet', tolerance=.4), body_width=_v(5.8, 'omron_d2f_datasheet', tolerance=.15),
        body_height=_v(5., 'omron_d2f_datasheet', tolerance=.4, note='Body top above the mounting-hole centres (drawing dimension 5).'),
        mounting_hole_pitch=_v(6.5, 'omron_d2f_datasheet', tolerance=.15), mounting_hole_diameter=_v(2., 'omron_d2f_datasheet'),
        plunger_width=_v(2.9, 'omron_d2f_datasheet'),
        operating_position=_v(5.5, 'omron_d2f_datasheet', tolerance=.3),
        pretravel=_v(.5, 'omron_d2f_datasheet', bound='max'), overtravel=_v(.25, 'omron_d2f_datasheet', bound='min'),
        movement_differential=_v(.12, 'omron_d2f_datasheet', bound='max'),
        operating_force=_v(150., 'omron_d2f_datasheet', bound='max', unit='gf', note='General purpose; low-force models 75 gf max.'),
        release_force=_v(20., 'omron_d2f_datasheet', bound='min', unit='gf', note='General purpose; low-force models 5 gf min.'),
        status_note='Reference form factor that common mouse switches follow; FP is not tabulated for pin plungers.'),
    SwitchProfile(
        id='huano_mouse_generic', maker='HUANO', model='Mouse micro switch (blue/red/yellow dot series), model not fixed',
        actuator='pin_plunger', height_datum='body_bottom',
        body_length=_v(12.8, 'huano_seller_manual', note='"typically"; general value, not per model.'),
        body_width=_v(5.8, 'huano_seller_manual', note='"typically".'), body_height=_v(6.5, 'huano_seller_manual', note='"typically".'),
        pretravel=_v(.5, 'huano_seller_manual', tolerance=.3, note='General value from an unattributed seller-hosted document.'),
        operating_force=_v(85., 'huano_seller_manual', bound='max', unit='gf', note='"typical range 60-85 gf".'),
        status_note='No Huano manufacturer datasheet found; operating position and overtravel are UNKNOWN. Need the exact model and its datasheet.'),
    SwitchProfile(
        id='kailh_gm20', maker='Kailh', model='GM 2.0 (side buttons of the Endgame Gear OP1 8k per its product listing)',
        actuator='pin_plunger', height_datum='body_bottom',
        operating_force=_v(80., 'mechkeys_kailh_gm20', bound='max', unit='gf', note='Seller states 65 +/- 15 gf.'),
        release_force=_v(20., 'mechkeys_kailh_gm20', bound='min', unit='gf'),
        status_note='Seller page only; dimensions, operating position, pretravel and overtravel are UNKNOWN.'),
]}


def missing_for_click_referenced_stop(profile: SwitchProfile) -> list[str]:
    """Values a click-referenced stop setting needs; empty when the profile is complete for it."""
    need = {'overtravel': profile.overtravel, 'movement_differential': profile.movement_differential,
            'pretravel': profile.pretravel, 'plunger_width': profile.plunger_width,
            'body_length': profile.body_length, 'body_width': profile.body_width}
    return sorted(k for k, v in need.items() if not v.known)


def profile_report() -> list[dict]:
    """One row per registered profile: what is known, from which sources, and what is UNKNOWN."""
    rows = []
    for p in PROFILES.values():
        values = {k: getattr(p, k) for k in SwitchProfile.model_fields if isinstance(getattr(p, k), Value)}
        rows.append({'id': p.id, 'maker': p.maker, 'model': p.model,
                     'unknown': sorted(k for k, v in values.items() if not v.known),
                     'sources': sorted({v.source for v in values.values() if v.source}),
                     'missing_for_click_referenced_stop': missing_for_click_referenced_stop(p),
                     'status_note': p.status_note})
    return rows
