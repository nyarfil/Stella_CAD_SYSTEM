"""Typed Recipe for the design-doc §22 side-button improvement trial.

A curved, hollow mouse-like shell gets a thumb-side window. The button is the
cut-out piece of the same skin (flush, unchanged outer surface), carried by a
pin hinge inside the shell. Its plunger presses a switch stem; the switch is an
explicitly ASSUMED placeholder envelope, not measured hardware.

Every number below is a proposal recorded in design_parameters with its basis.
Nothing here is a measured property of a real mouse, PCB or switch.
"""
from __future__ import annotations
import math

REQUEST=('このマウスのサイドボタン、もっと押しやすく。外形はできるだけ変えないで。'
         '試作では仮のスイッチ外形を使い、実スイッチ寸法・押下力・クリック感は未確定として残す。')

# Shell sections (proposal; same family as the recipe-operation trials).
SECTIONS=[(0.,60.,32.),(18.,55.,30.),(34.,36.,18.)]
P={
    'shell_wall_mm':1.5,
    'safe_offset_mm':2.1,            # internal parts stay >= this far inside the outer skin
    'window_x_min_mm':-10.,'window_x_max_mm':14.,
    'window_z_min_mm':10.,'window_z_max_mm':18.,
    'window_gap_mm':.4,
    'hinge_x_mm':-12.,'hinge_y_mm':25.,
    'pin_radius_mm':1.,'barrel_inner_radius_mm':1.3,'barrel_outer_radius_mm':2.6,
    'barrel_z_min_mm':10.5,'barrel_z_max_mm':17.5,
    'tab_gap_z_mm':.8,
    'plunger_x_min_mm':8.,'plunger_x_max_mm':11.,'plunger_tip_y_mm':24.,
    'plunger_z_min_mm':12.,'plunger_z_max_mm':16.,
    'stem_free_play_mm':.2,
    'assumed_stem_operating_travel_mm':.5,
    'housing_margin_after_operating_mm':.6,
    'stop_extra_travel_mm':.3,        # plunger travel past the operating point when the hard stop engages
    'tongue_x_min_mm':10.5,'tongue_x_max_mm':13.5,'tongue_y_min_mm':25.,'tongue_y_max_mm':27.5,
    'tongue_z_min_mm':7.8,'tongue_z_max_mm':13.,
    'stop_shelf_z_min_mm':6.,'stop_shelf_z_max_mm':7.5,'stop_y_min_mm':21.,
    'min_printed_wall_mm':1.2,
}


def _ellipse(a,b,count=12):
    return [[round(a*math.cos(2*math.pi*i/count),6),round(b*math.sin(2*math.pi*i/count),6)] for i in range(count)]


def _inset_sections(inset):
    """Outer sections shrunk by inset on both axes; first plane below z=0 opens the bottom."""
    z=[SECTIONS[0][0]-1.,SECTIONS[1][0],SECTIONS[-1][0]-inset]
    return [{'z_mm':zz,'points_mm':_ellipse(a-inset,b-inset)} for zz,(_,a,b) in zip(z,SECTIONS)]


def _box(node_id,function_id,reason,lo,hi):
    return {'id':node_id,'op':'box','function_id':function_id,'reason':reason,
            'size_mm':[hi[i]-lo[i] for i in range(3)],'center_mm':[(hi[i]+lo[i])/2 for i in range(3)]}


def _plunger_lever(p):
    return (p['plunger_x_min_mm']+p['plunger_x_max_mm'])/2-p['hinge_x_mm']


def press_angle_deg(p=P):
    """Hinge rotation that moves the plunger tip through free play plus the assumed operating travel."""
    travel=p['stem_free_play_mm']+p['assumed_stem_operating_travel_mm']
    # Negative about +Z moves the front of the button toward -Y (into the shell).
    return -math.degrees(travel/_plunger_lever(p))


def stop_angle_deg(p=P):
    """Hinge rotation at which the hard stop is designed to engage."""
    travel=p['stem_free_play_mm']+p['assumed_stem_operating_travel_mm']+p['stop_extra_travel_mm']
    return -math.degrees(travel/_plunger_lever(p))


def stop_face_y_mm(p=P):
    """Stop face placed where the tongue's farthest lower corner arrives at the stop angle."""
    radius=p['tongue_x_max_mm']-p['hinge_x_mm']
    return p['tongue_y_min_mm']-radius*math.sin(math.radians(-stop_angle_deg(p)))


def side_button_recipe(request=REQUEST,p=None):
    p=dict(P if p is None else p)
    wl,wh=p['window_x_min_mm'],p['window_x_max_mm'];zl,zh=p['window_z_min_mm'],p['window_z_max_mm'];g=p['window_gap_mm']
    hx,hy=p['hinge_x_mm'],p['hinge_y_mm']
    tip=p['plunger_tip_y_mm'];stem_top=tip-p['stem_free_play_mm']
    housing_top=stem_top-p['assumed_stem_operating_travel_mm']-p['housing_margin_after_operating_mm']
    px0,px1=p['plunger_x_min_mm'],p['plunger_x_max_mm'];pz0,pz1=p['plunger_z_min_mm'],p['plunger_z_max_mm']
    bz0,bz1=p['barrel_z_min_mm'],p['barrel_z_max_mm'];tg=p['tab_gap_z_mm']
    ops=[
        {'id':'outer','op':'spline_loft','function_id':'F6_connect_shell',
         'reason':'Smooth palm/side skin through closed periodic-spline sections; this outer surface is preserved.',
         'sections':[{'z_mm':z,'points_mm':_ellipse(a,b)} for z,a,b in SECTIONS]},
        {'id':'cavity','op':'spline_loft','function_id':'F6_connect_shell',
         'reason':'Inner cavity: the outer sections inset by the wall; open through the bottom for the PCB.',
         'sections':_inset_sections(p['shell_wall_mm'])},
        # An inset loft instead of the shell op: booleans on OCCT offset
        # surfaces did not survive STEP re-import. Wall thickness is therefore
        # not uniform and must be measured, not assumed.
        {'id':'hollow','op':'difference','function_id':'F6_connect_shell',
         'reason':'Shell skin = outer volume minus inset cavity.','operands':['outer','cavity']},
        {'id':'safe_core','op':'spline_loft','function_id':'F2_guide_button',
         'reason':'Interior region inset further, where hinge parts may live without touching the wall.',
         'sections':_inset_sections(p['safe_offset_mm'])},
        _box('window','F1_transmit_force','Button skin region cut from the existing side surface.',
             [wl,20.,zl],[wh,40.,zh]),
        _box('window_gap','F6_connect_shell','Window enlarged by the running gap around the button.',
             [wl-g,20.,zl-g],[wh+g,40.,zh+g]),
        {'id':'shell_open','op':'difference','function_id':'F6_connect_shell',
         'reason':'Open the side window in the shell with a running gap.','operands':['hollow','window_gap']},
        {'id':'skin_piece','op':'intersection','function_id':'F1_transmit_force',
         'reason':'Button face is the removed piece of the original skin, so the outer shape does not change.',
         'operands':['hollow','window']},
        _box('rib_box','F1_transmit_force','Rear rib that carries finger force from the skin piece toward the hinge arm.',
             [wl+1.,20.,zl+.5],[wl+4.,40.,zh-.5]),
        {'id':'rib','op':'intersection','function_id':'F1_transmit_force',
         'reason':'Keep the rib inside the outer skin.','operands':['rib_box','outer']},
        _box('arm_box','F2_guide_button','Hinge arm from barrel to rib.',
             [hx,hy-1.,zl+.5],[wl+4.,hy+2.,zh-.5]),
        {'id':'arm','op':'intersection','function_id':'F2_guide_button',
         'reason':'Arm stays inside the safe interior so it cannot rub the shell wall.','operands':['arm_box','safe_core']},
        {'id':'barrel_outer','op':'cylinder','function_id':'F2_guide_button','reason':'Hinge barrel outer surface.',
         'radius_mm':p['barrel_outer_radius_mm'],'height_mm':bz1-bz0,'origin_mm':[hx,hy,bz0],'axis':[0.,0.,1.]},
        {'id':'barrel_bore','op':'cylinder','function_id':'F2_guide_button','reason':'Hinge bore running on the pin.',
         'radius_mm':p['barrel_inner_radius_mm'],'height_mm':bz1-bz0+2.,'origin_mm':[hx,hy,bz0-1.],'axis':[0.,0.,1.]},
        _box('plunger_box','F3_actuate_switch','Plunger from the skin piece toward the switch stem.',
             [px0,tip,pz0],[px1,40.,pz1]),
        {'id':'plunger','op':'intersection','function_id':'F3_actuate_switch',
         'reason':'Keep the plunger inside the outer skin.','operands':['plunger_box','outer']},
        _box('tongue','F5_limit_overtravel','Stop tongue below the plunger that meets the shell stop.',
             [p['tongue_x_min_mm'],p['tongue_y_min_mm'],p['tongue_z_min_mm']],
             [p['tongue_x_max_mm'],p['tongue_y_max_mm'],p['tongue_z_max_mm']]),
        {'id':'button_solid','op':'union','function_id':'F1_transmit_force',
         'reason':'One printed button: skin face, rib, arm, barrel, plunger and stop tongue.',
         'operands':['skin_piece','rib','arm','barrel_outer','plunger','tongue']},
        {'id':'button','op':'difference','function_id':'F2_guide_button',
         'reason':'Bore the barrel so it rotates on the fixed pin.','operands':['button_solid','barrel_bore']},
        {'id':'pin','op':'cylinder','function_id':'F2_guide_button','reason':'Fixed hinge pin carried by the shell.',
         'radius_mm':p['pin_radius_mm'],'height_mm':(bz1+tg+3.)-(bz0-tg-3.),'origin_mm':[hx,hy,bz0-tg-3.],'axis':[0.,0.,1.]},
        _box('tab_low_box','F6_connect_shell','Lower pin mount tab reaching into the side wall.',
             [hx-3.,hy-2.,bz0-tg-3.],[hx+3.,40.,bz0-tg]),
        _box('tab_high_box','F6_connect_shell','Upper pin mount tab reaching into the side wall.',
             [hx-3.,hy-2.,bz1+tg],[hx+3.,40.,bz1+tg+3.]),
        {'id':'tab_low','op':'intersection','function_id':'F6_connect_shell',
         'reason':'Lower tab stays inside the outer skin.','operands':['tab_low_box','outer']},
        {'id':'tab_high','op':'intersection','function_id':'F6_connect_shell',
         'reason':'Upper tab stays inside the outer skin.','operands':['tab_high_box','outer']},
        _box('stop_shelf_box','F5_limit_overtravel','Shelf carrying the hard stop from the lower side wall.',
             [p['tongue_x_min_mm'],p['stop_y_min_mm'],p['stop_shelf_z_min_mm']],
             [p['tongue_x_max_mm'],40.,p['stop_shelf_z_max_mm']]),
        {'id':'stop_shelf','op':'intersection','function_id':'F5_limit_overtravel',
         'reason':'Shelf stays inside the outer skin.','operands':['stop_shelf_box','outer']},
        _box('stop_post','F5_limit_overtravel','Hard stop face the tongue reaches at the stop angle.',
             [p['tongue_x_min_mm'],p['stop_y_min_mm'],p['stop_shelf_z_min_mm']],
             [p['tongue_x_max_mm'],stop_face_y_mm(p),p['window_z_min_mm']-p['window_gap_mm']-.2]),
        {'id':'shell_part','op':'union','function_id':'F6_connect_shell',
         'reason':'Shell with window, pin tabs, hinge pin and hard stop as one printed part.',
         'operands':['shell_open','tab_low','tab_high','pin','stop_shelf','stop_post']},
        _box('switch_housing','F3_actuate_switch','ASSUMED switch housing envelope (placeholder, not measured).',
             [px0-1.5,housing_top-4.,pz0-1.],[px1+1.5,housing_top,pz1+1.]),
        _box('switch_stem','F4_restore_button','ASSUMED switch stem; its spring is the return element (placeholder).',
             [px0+.5,housing_top,pz0+1.],[px1-.5,stem_top,pz1-1.]),
    ]
    angle=press_angle_deg(p);stop=stop_angle_deg(p)
    return {
        'title':'Side button improvement trial (hinged flush skin button)',
        'original_request':request,
        'design_parameters':{k:float(v) for k,v in p.items()},
        'parameter_basis':{k:'Proposal for this prototype; not measured from a real mouse, switch or PCB.' for k in p},
        'functions':{
            'F1_transmit_force':'Transmit thumb force from the unchanged side skin into the button.',
            'F2_guide_button':'Guide the button on one fixed hinge axis.',
            'F3_actuate_switch':'Move the plunger onto the switch stem through its operating travel.',
            'F4_restore_button':'Return the button using the switch stem spring (assumed).',
            'F5_limit_overtravel':'Keep the plunger clear of the switch housing through the press angle.',
            'F6_connect_shell':'Carry the hinge in the shell without changing the outer surface.'},
        'protected_constraints':['Outer shell skin is not reshaped; the button face is the removed skin piece.'],
        'design_basis':{'kind':'first_principles',
                        'summary':'Pin-hinged flush side button cut from the shell skin, pressing an assumed switch stem.',
                        'assumptions':['Switch housing, stem position and operating travel are placeholders, not a datasheet.',
                                       'PLA/PETG FDM prototype; stiffness, wear and click feel are not qualified.',
                                       'Pin and barrel are printed; real hinge play depends on printer calibration.']},
        'verification_plan':['Build STEP and check single solids, automatic pair overlap and bounds.',
                             'Static clearance of plunger free play, barrel on pin and window gap.',
                             'Sampled rotation of the button about the pin through the press angle against shell and housing.',
                             'Hard stop: rigid end-pose contact at the stop angle, housing still clear.',
                             'Sampled printed wall thickness of shell and button.'],
        'operations':ops,
        'outputs':[{'part_id':'shell','node':'shell_part'},{'part_id':'button','node':'button'},
                   {'part_id':'switch_housing','node':'switch_housing'},{'part_id':'switch_stem','node':'switch_stem'}],
        'dimension_checks':[
            {'id':'shell-length','part':'shell','kind':'bbox','axis':'x','nominal_mm':120.,'tolerance_mm':.5},
            {'id':'shell-height','part':'shell','kind':'bbox','axis':'z','nominal_mm':34.,'tolerance_mm':1e-3},
            {'id':'barrel-bore','part':'button','kind':'inner_cylinder_diameter','axis':'z',
             'nominal_mm':2*p['barrel_inner_radius_mm'],'tolerance_mm':1e-3}],
        'clearance_checks':[
            {'id':'rest-button-shell','part_a':'button','part_b':'shell','min_mm':.25},
            {'id':'rest-plunger-free-play','part_a':'button','part_b':'switch_stem','min_mm':p['stem_free_play_mm']-1e-3},
            {'id':'rest-button-housing','part_a':'button','part_b':'switch_housing','min_mm':.5}],
        'rotation_checks':[
            {'id':'press-swept-clearance','moving_part':'button','obstacles':['shell','switch_housing'],
             'axis_origin_mm':[hx,hy,0.],'axis_direction':[0.,0.,1.],'end_deg':angle,
             'samples':5,'max_samples':33,'min_mm':.1},
            {'id':'overtravel-stop-engages','moving_part':'button','obstacles':['shell'],
             'axis_origin_mm':[hx,hy,0.],'axis_direction':[0.,0.,1.],'end_deg':stop,
             # Designed contact cannot earn a clearance certificate, so the
             # adaptive refinement is capped; the sampled verdict still binds.
             'samples':5,'max_samples':9,'min_mm':0.,'end_max_distance_mm':.02},
            {'id':'housing-clear-until-stop','moving_part':'button','obstacles':['switch_housing'],
             'axis_origin_mm':[hx,hy,0.],'axis_direction':[0.,0.,1.],'end_deg':stop,
             'samples':5,'max_samples':33,'min_mm':.2}],
        'wall_checks':[
            {'id':'shell-printed-wall','part':'shell','min_mm':p['min_printed_wall_mm'],'samples_per_face':10},
            {'id':'button-printed-wall','part':'button','min_mm':p['min_printed_wall_mm'],'samples_per_face':10}],
        'unverified_requirements':[
            '押しやすさ（押下力・ストローク感・クリック感）は実機試験していない。',
            'Switch housing, stem position, operating force and travel are assumed placeholders, not a measured switch.',
            'PCB position and the real mouse shell were not measured; this is a stand-in shell.',
            'Hinge play, wear, print tolerance and stiffness of the 1.5 mm skin are not qualified.',
            'Hard-stop stiffness, impact and wear are not modeled; only rigid end-pose contact is checked.',
            'Wall checks are sampled minima of the stated parts, not a proof of minimum wall or of strength.'],
    }
