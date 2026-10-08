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


# ---------------------------------------------------------------------------
# Revision 2: repairs the round-1/round-2 review findings on revision 1.
# - Captive hinge -> separate Ø2 stock pin through slip holes in both tabs,
#   inserted from the open bottom after the button (pin is its own part).
# - No outward rest stop -> a stop arm under the barrel runs in a slot of two
#   vertical-faced blocks on the lower tab; it rests on the outward block and
#   meets the inward block at the hard-stop angle.  Arm motion there is along
#   X, so the button still slides in along +Y from inside the shell.
# - Hinge play 0.3 mm -> 0.1 mm radial; switch clearance swept over that play.
# - Lever ratio -> plunger moved to the face centre (force factor 1.0 there).
# - Stop shelf/tongue removed; tabs trimmed to the window gap; barrel ends and
#   stop arm are the axial thrust faces (0.2 mm each).
# Return/preload is a separate small spring: a placeholder, not modeled.
# ---------------------------------------------------------------------------
P2={
    'shell_wall_mm':1.5,'safe_offset_mm':2.1,
    'window_x_min_mm':-10.,'window_x_max_mm':14.,'window_z_min_mm':10.,'window_z_max_mm':18.,'window_gap_mm':.4,
    'hinge_x_mm':-13.,'hinge_y_mm':25.,
    'pin_radius_mm':1.,'tab_hole_radius_mm':1.02,'barrel_inner_radius_mm':1.1,'barrel_outer_radius_mm':2.4,
    'barrel_z_min_mm':13.,'barrel_z_max_mm':17.5,'axial_gap_mm':.2,'tab_thickness_mm':3.,
    'stop_arm_half_width_mm':1.,'stop_arm_y_min_mm':15.,'stop_arm_z_min_mm':9.8,'stop_arm_z_max_mm':13.4,
    'stop_block_y_min_mm':14.5,'stop_block_y_max_mm':18.5,'stop_block_z_max_mm':12.,'stop_block_width_mm':1.4,
    'link_z_min_mm':12.2,
    'plunger_x_min_mm':.5,'plunger_x_max_mm':3.5,'plunger_tip_y_mm':24.,'plunger_z_min_mm':12.,'plunger_z_max_mm':16.,
    'stem_free_play_mm':.2,'assumed_stem_operating_travel_mm':.5,'housing_margin_after_operating_mm':.6,
    'stop_extra_travel_mm':.2,'contact_proof_margin_mm':.1,'hinge_radial_play_mm':.1,
    'insertion_slide_mm':15.,'insertion_drop_mm':22.,'tab_x_max_mm':-10.6,'min_printed_wall_mm':1.2,
}


def _lever2(p):
    return (p['plunger_x_min_mm']+p['plunger_x_max_mm'])/2-p['hinge_x_mm']


def angles_v2(p=P2):
    """Press, stop and stem-contact-proof angles (negative = into the shell)."""
    lever=_lever2(p)
    press=p['stem_free_play_mm']+p['assumed_stem_operating_travel_mm']
    stop=press+p['stop_extra_travel_mm']
    contact=p['stem_free_play_mm']+p['contact_proof_margin_mm']
    return {k:-math.degrees(v/lever) for k,v in (('press',press),('stop',stop),('contact',contact))}


def inward_block_gap_mm(p=P2):
    """Slot gap so the farthest stop-arm corner reaches the inward block exactly at the stop angle."""
    radius=p['hinge_y_mm']-p['stop_arm_y_min_mm']
    return radius*math.sin(math.radians(-angles_v2(p)['stop']))


def side_button_recipe_v2(request=REQUEST,p=None):
    p=dict(P2 if p is None else p)
    wl,wh=p['window_x_min_mm'],p['window_x_max_mm'];zl,zh=p['window_z_min_mm'],p['window_z_max_mm'];g=p['window_gap_mm']
    hx,hy=p['hinge_x_mm'],p['hinge_y_mm'];ag=p['axial_gap_mm'];tt=p['tab_thickness_mm']
    bz0,bz1=p['barrel_z_min_mm'],p['barrel_z_max_mm']
    tab_low_top=zl-g;tab_high_bottom=bz1+ag
    arm_w=p['stop_arm_half_width_mm'];az0,az1=p['stop_arm_z_min_mm'],p['stop_arm_z_max_mm']
    by0,by1=p['stop_block_y_min_mm'],p['stop_block_y_max_mm'];bw=p['stop_block_width_mm']
    gin=inward_block_gap_mm(p)
    tip=p['plunger_tip_y_mm'];stem_top=tip-p['stem_free_play_mm']
    housing_top=stem_top-p['assumed_stem_operating_travel_mm']-p['housing_margin_after_operating_mm']
    px0,px1=p['plunger_x_min_mm'],p['plunger_x_max_mm'];pz0,pz1=p['plunger_z_min_mm'],p['plunger_z_max_mm']
    a=angles_v2(p)
    pin_z0=tab_low_top-tt;pin_z1=tab_high_bottom+tt
    ops=[
        {'id':'outer','op':'spline_loft','function_id':'F6_connect_shell',
         'reason':'Smooth palm/side skin through closed periodic-spline sections; this outer surface is preserved.',
         'sections':[{'z_mm':z,'points_mm':_ellipse(aa,bb)} for z,aa,bb in SECTIONS]},
        {'id':'cavity','op':'spline_loft','function_id':'F6_connect_shell',
         'reason':'Inner cavity: outer sections inset by the wall; open through the bottom.',
         'sections':_inset_sections(p['shell_wall_mm'])},
        {'id':'hollow','op':'difference','function_id':'F6_connect_shell',
         'reason':'Shell skin = outer volume minus inset cavity.','operands':['outer','cavity']},
        {'id':'safe_core','op':'spline_loft','function_id':'F2_guide_button',
         'reason':'Interior region inset further, where hinge parts may live without touching the wall.',
         'sections':_inset_sections(p['safe_offset_mm'])},
        _box('window','F1_transmit_force','Button skin region cut from the existing side surface.',[wl,20.,zl],[wh,40.,zh]),
        _box('window_gap','F6_connect_shell','Window enlarged by the running gap around the button.',[wl-g,20.,zl-g],[wh+g,40.,zh+g]),
        {'id':'shell_open','op':'difference','function_id':'F6_connect_shell',
         'reason':'Open the side window in the shell with a running gap.','operands':['hollow','window_gap']},
        {'id':'skin_piece','op':'intersection','function_id':'F1_transmit_force',
         'reason':'Button face is the removed piece of the original skin, so the outer shape does not change.',
         'operands':['hollow','window']},
        _box('rib_box','F1_transmit_force','Rear rib carrying finger force from the skin piece toward the hinge link.',
             [wl+1.,20.,zl+.5],[wl+4.,40.,zh-.5]),
        {'id':'rib','op':'intersection','function_id':'F1_transmit_force','reason':'Keep the rib inside the outer skin.',
         'operands':['rib_box','outer']},
        _box('link_box','F2_guide_button','Link from barrel to rib, kept above the stop blocks for the insertion path.',
             [hx+p['barrel_outer_radius_mm']-.5,hy-1.,p['link_z_min_mm']],[wl+4.,hy+2.,zh-.5]),
        {'id':'link','op':'intersection','function_id':'F2_guide_button','reason':'Link stays inside the safe interior.',
         'operands':['link_box','safe_core']},
        {'id':'barrel_outer','op':'cylinder','function_id':'F2_guide_button','reason':'Hinge barrel; its ends are axial thrust faces.',
         'radius_mm':p['barrel_outer_radius_mm'],'height_mm':bz1-bz0,'origin_mm':[hx,hy,bz0],'axis':[0.,0.,1.]},
        _box('stop_arm','F5_limit_overtravel','Stop arm under the barrel; it moves along X in the stop slot.',
             [hx-arm_w,p['stop_arm_y_min_mm'],az0],[hx+arm_w,hy-p['barrel_inner_radius_mm']-.4,az1]),
        _box('plunger_box','F3_actuate_switch','Plunger at the face centre toward the switch stem.',[px0,tip,pz0],[px1,40.,pz1]),
        {'id':'plunger','op':'intersection','function_id':'F3_actuate_switch','reason':'Keep the plunger inside the outer skin.',
         'operands':['plunger_box','outer']},
        {'id':'button_solid','op':'union','function_id':'F1_transmit_force',
         'reason':'One printed button: skin face, rib, link, barrel, stop arm and plunger.',
         'operands':['skin_piece','rib','link','barrel_outer','stop_arm','plunger']},
        {'id':'barrel_bore','op':'cylinder','function_id':'F2_guide_button','reason':'Bore running on the stock pin with 0.1 mm radial play.',
         'radius_mm':p['barrel_inner_radius_mm'],'height_mm':bz1-bz0+2.,'origin_mm':[hx,hy,bz0-1.],'axis':[0.,0.,1.]},
        {'id':'button','op':'difference','function_id':'F2_guide_button','reason':'Bore the barrel for the pin.',
         'operands':['button_solid','barrel_bore']},
        _box('tab_low_box','F6_connect_shell','Lower tab: pin support and stop-slot base, top trimmed to the window gap.',
             [hx-4.5,by0-.5,tab_low_top-tt],[p['tab_x_max_mm'],40.,tab_low_top]),
        {'id':'tab_low','op':'intersection','function_id':'F6_connect_shell','reason':'Lower tab stays inside the outer skin.',
         'operands':['tab_low_box','outer']},
        _box('tab_high_box','F6_connect_shell','Upper tab: pin support; bottom is the barrel axial thrust face.',
             [hx-3.,hy-3.,tab_high_bottom],[p['tab_x_max_mm'],40.,tab_high_bottom+tt]),
        {'id':'tab_high','op':'intersection','function_id':'F6_connect_shell','reason':'Upper tab stays inside the outer skin.',
         'operands':['tab_high_box','outer']},
        _box('block_in','F5_limit_overtravel','Inward hard-stop block (vertical face) on the lower tab.',
             [hx-arm_w-gin-bw,by0,tab_low_top],[hx-arm_w-gin,by1,p['stop_block_z_max_mm']]),
        _box('block_out','F2_guide_button','Outward rest-stop block (vertical face) on the lower tab; the arm rests on it.',
             [hx+arm_w,by0,tab_low_top],[hx+arm_w+bw,by1,p['stop_block_z_max_mm']]),
        {'id':'shell_tabs','op':'union','function_id':'F6_connect_shell',
         'reason':'Shell with window, both tabs and both stop blocks as one printed part.',
         'operands':['shell_open','tab_low','tab_high','block_in','block_out']},
        {'id':'pin_hole','op':'cylinder','function_id':'F6_connect_shell','reason':'Slip hole for the stock pin through both tabs.',
         'radius_mm':p['tab_hole_radius_mm'],'height_mm':pin_z1-pin_z0+2.,'origin_mm':[hx,hy,pin_z0-1.],'axis':[0.,0.,1.]},
        {'id':'shell_part','op':'difference','function_id':'F6_connect_shell','reason':'Drill the pin path through both tabs.',
         'operands':['shell_tabs','pin_hole']},
        {'id':'pin','op':'cylinder','function_id':'F2_guide_button',
         'reason':'Stock Ø2 pin (steel dowel or 1.75 filament per owner choice) spanning both tabs.',
         'radius_mm':p['pin_radius_mm'],'height_mm':pin_z1-pin_z0,'origin_mm':[hx,hy,pin_z0],'axis':[0.,0.,1.]},
        _box('switch_housing','F3_actuate_switch','ASSUMED switch housing envelope (placeholder, not measured).',
             [px0-1.5,housing_top-4.,pz0-1.],[px1+1.5,housing_top,pz1+1.]),
        _box('switch_stem','F3_actuate_switch','ASSUMED switch stem (placeholder).',
             [px0+.5,housing_top,pz0+1.],[px1-.5,stem_top,pz1-1.]),
    ]
    axis={'axis_origin_mm':[hx,hy,0.],'axis_direction':[0.,0.,1.]}
    play=p['hinge_radial_play_mm']
    return {
        'title':'Side button improvement trial, revision 2 (pin hinge, slot stops, centred plunger)',
        'original_request':request,
        'design_parameters':{k:float(v) for k,v in p.items()},
        'parameter_basis':{k:'Proposal for this prototype revision; not measured from a real mouse, switch or PCB.' for k in p},
        'functions':{
            'F1_transmit_force':'Transmit thumb force from the unchanged side skin into the button.',
            'F2_guide_button':'Guide the button on one fixed hinge axis and hold its flush rest pose.',
            'F3_actuate_switch':'Move the plunger onto the switch stem through its operating travel.',
            'F4_restore_button':'Return the button to its rest stop (separate preload spring, placeholder).',
            'F5_limit_overtravel':'Stop the button at a hard stop before the switch housing is reached.',
            'F6_connect_shell':'Carry the hinge in the shell without changing the outer surface.'},
        'protected_constraints':['Outer shell skin is not reshaped; the button face is the removed skin piece.'],
        'design_basis':{'kind':'first_principles',
                        'summary':'Pin-hinged flush side button with slot rest/hard stops and a centred plunger on an assumed switch.',
                        'assumptions':['Switch housing, stem position and operating travel are placeholders, not a datasheet.',
                                       'A separate small spring preloads the stop arm against the outward block (not modeled).',
                                       'Stock Ø2 pin; tab holes are slip fits that may need reaming or adhesive.',
                                       'FDM prototype: shell printed rim-down, button printed with the bore vertical.']},
        'verification_plan':['Single solids, volume agreement, automatic pair overlap and bounds.',
                             'Outward rotation from rest must be blocked by the shell (rest stop).',
                             'Stem contact must occur by the free-play angle at every hinge-play offset.',
                             'Housing stays clear until the stop angle at every hinge-play offset.',
                             'Nothing in the shell is touched before the stop angle; the stop blocks motion just past it.',
                             'Button assembly path (in through the open bottom, slide out onto the rest stop) and pin path along Z are clear of the shell.',
                             'Sampled printed wall thickness of shell and button.'],
        'operations':ops,
        'outputs':[{'part_id':'shell','node':'shell_part'},{'part_id':'button','node':'button'},{'part_id':'hinge_pin','node':'pin'},
                   {'part_id':'switch_housing','node':'switch_housing'},{'part_id':'switch_stem','node':'switch_stem'}],
        'dimension_checks':[
            {'id':'shell-length','part':'shell','kind':'bbox','axis':'x','nominal_mm':120.,'tolerance_mm':.5},
            {'id':'shell-height','part':'shell','kind':'bbox','axis':'z','nominal_mm':34.,'tolerance_mm':1e-3}],
        'clearance_checks':[
            {'id':'rest-pin-in-bore','part_a':'button','part_b':'hinge_pin','min_mm':play-1e-3},
            {'id':'rest-plunger-free-play','part_a':'button','part_b':'switch_stem','min_mm':p['stem_free_play_mm']-1e-3},
            {'id':'rest-button-housing','part_a':'button','part_b':'switch_housing','min_mm':.5}],
        'motion_checks':[
            # Reverse of assembly: slide inward off the rest stop, then drop out of the open bottom.
            {'id':'button-insertion-slide','moving_part':'button','obstacles':['shell'],
             # Sliding contact on the rest-stop face cannot earn a clearance
             # certificate; refinement is capped and the sampled verdict binds.
             'translation_end_mm':[0.,-p['insertion_slide_mm'],0.],'samples':9,'max_samples':17,'min_mm':0.},
            {'id':'button-insertion-drop','moving_part':'button','obstacles':['shell'],
             'start_translation_mm':[0.,-p['insertion_slide_mm'],0.],
             'translation_end_mm':[0.,0.,-p['insertion_drop_mm']],'samples':9,'max_samples':33,'min_mm':.1},
            {'id':'pin-insertion-path','moving_part':'hinge_pin','obstacles':['shell'],
             'translation_end_mm':[0.,0.,-(pin_z1+1.)],'samples':9,'max_samples':17,'min_mm':.01}],
        'rotation_checks':[
            {'id':'rest-outward-blocked','moving_part':'button','obstacles':['shell'],**axis,'end_deg':.5,
             'expect':'blocked','samples':5,'max_samples':6},
            {'id':'stem-contact-by-free-play','moving_part':'button','obstacles':['switch_stem'],**axis,'end_deg':a['contact'],
             'expect':'blocked','samples':5,'max_samples':11,'axis_play_mm':play,'min_blocking_overlap_mm3':1e-4},
            {'id':'housing-clear-until-stop','moving_part':'button','obstacles':['switch_housing'],**axis,'end_deg':a['stop'],
             'samples':5,'max_samples':33,'min_mm':.2,'axis_play_mm':play},
            {'id':'shell-clear-until-stop','moving_part':'button','obstacles':['shell'],**axis,'end_deg':a['stop'],
             'samples':5,'max_samples':9,'min_mm':0.,'end_max_distance_mm':.02},
            {'id':'hard-stop-blocks-past-stop','moving_part':'button','obstacles':['shell'],**axis,'end_deg':a['stop']-.5,
             'expect':'blocked','samples':9,'max_samples':17}],
        'wall_checks':[
            {'id':'shell-printed-wall','part':'shell','min_mm':p['min_printed_wall_mm'],'samples_per_face':10},
            {'id':'button-printed-wall','part':'button','min_mm':p['min_printed_wall_mm'],'samples_per_face':10}],
        'unverified_requirements':[
            '押しやすさ（押下力・ストローク感・クリック感）は実機試験していない。押す位置による力の倍率は剛体計算の目安にすぎない。',
            'Switch housing, stem position, operating force and travel are assumed placeholders, not a measured switch.',
            'PCB position and the real mouse shell were not measured; this is a stand-in shell.',
            'The return/preload spring is a placeholder and is not modeled; its force and rest preload are unverified.',
            'Pin retention in the slip holes, print tolerance, stop stiffness and wear are not qualified.',
            'Hinge play is covered only at eight radial offsets of the stated play for switch contact and housing clearance.',
            'Wall checks are sampled minima of the stated parts, not a proof of minimum wall or of strength.'],
    }


# ---------------------------------------------------------------------------
# Revision 3: repairs the revision-2 round-1 findings.
# - Stop-arm root -> the stop arm is a full-height web as wide as the barrel
#   (wider than its diameter), joined over the whole barrel height.
# - Stop datum amplified hinge play -> stop contacts moved 17 mm from the axis
#   (equal to the plunger lever); hinge play cut to 0.05 mm radial (reamed bore,
#   h7 steel dowel) plus 0.005 mm slip in the tabs; every stop/rest/switch
#   check is swept over that play envelope, past the nominal angles.
# - Return spring -> a Ø1.5 compression spring envelope in a pocket of the
#   inward block pushes the arm onto the outward rest block (placeholder).
# - Pin is a Ø2 steel dowel only (no filament variant); the switch/PCB are
#   fitted after button, spring and pin (stated assembly order).
# - Bore spans the full barrel height (7.7 mm) to limit tilt on the pin.
# ---------------------------------------------------------------------------
P3={
    'shell_wall_mm':1.5,'safe_offset_mm':2.1,
    'window_x_min_mm':-10.,'window_x_max_mm':14.,'window_z_min_mm':10.,'window_z_max_mm':18.,'window_gap_mm':.4,
    'hinge_x_mm':-15.,'hinge_y_mm':25.,
    'pin_radius_mm':1.,'tab_hole_radius_mm':1.005,'barrel_inner_radius_mm':1.05,'barrel_outer_radius_mm':2.35,
    'axial_gap_mm':.2,'tab_thickness_mm':3.,'tab_x_max_mm':-10.6,
    'arm_half_width_mm':2.5,'arm_tip_y_mm':8.,
    'block_y_min_mm':7.5,'block_y_max_mm':11.5,'block_z_max_mm':13.6,'inward_block_width_mm':3.5,
    'link_z_min_mm':13.8,
    'spring_radius_mm':.75,'spring_pocket_radius_mm':.8,'spring_pocket_depth_mm':2.,
    'plunger_x_min_mm':.5,'plunger_x_max_mm':3.5,'plunger_tip_y_mm':24.,'plunger_z_min_mm':12.,'plunger_z_max_mm':16.,
    'stem_free_play_mm':.2,'assumed_stem_operating_travel_mm':.5,'housing_margin_after_operating_mm':.6,
    'stop_extra_travel_mm':.2,'contact_proof_margin_mm':.1,
    'hinge_radial_play_mm':.055,
    'insertion_slide_mm':22.,'insertion_drop_mm':19.,'min_printed_wall_mm':1.2,
}


def _lever3(p):
    return (p['plunger_x_min_mm']+p['plunger_x_max_mm'])/2-p['hinge_x_mm']


def _play_angle_deg(p,radius):
    """Largest change of a stop angle caused by the radial play at a contact this far from the axis."""
    return math.degrees(p['hinge_radial_play_mm']/radius)


def angles_v3(p=P3):
    lever=_lever3(p);stop_radius=p['hinge_y_mm']-p['arm_tip_y_mm']
    press=p['stem_free_play_mm']+p['assumed_stem_operating_travel_mm']
    stop=press+p['stop_extra_travel_mm']
    contact=p['stem_free_play_mm']+p['contact_proof_margin_mm']
    play=_play_angle_deg(p,stop_radius)
    return {'press':-math.degrees(press/lever),'stop':-math.degrees(stop/lever),
            'contact':-math.degrees(contact/lever),'stop_play':play}


def inward_gap_v3(p=P3):
    """Slot gap so the arm's -X tip corner reaches the inward block exactly at the nominal stop angle."""
    theta=math.radians(-angles_v3(p)['stop']);w=p['arm_half_width_mm'];r=p['hinge_y_mm']-p['arm_tip_y_mm']
    corner_x=-w*math.cos(theta)-r*math.sin(theta)
    return -corner_x-w


def side_button_recipe_v3(request=REQUEST,p=None):
    p=dict(P3 if p is None else p)
    wl,wh=p['window_x_min_mm'],p['window_x_max_mm'];zl,zh=p['window_z_min_mm'],p['window_z_max_mm'];g=p['window_gap_mm']
    hx,hy=p['hinge_x_mm'],p['hinge_y_mm'];ag=p['axial_gap_mm'];tt=p['tab_thickness_mm']
    tab_low_top=zl-g;bz0=tab_low_top+ag;bz1=zh-.5;tab_high_bottom=bz1+ag
    w=p['arm_half_width_mm'];by0,by1,bzt=p['block_y_min_mm'],p['block_y_max_mm'],p['block_z_max_mm']
    gin=inward_gap_v3(p);ibw=p['inward_block_width_mm']
    in_face=hx-w-gin;out_face=hx+w
    spring_z=(tab_low_top+bzt)/2;spring_y=(by0+by1)/2;pocket=p['spring_pocket_depth_mm']
    tip=p['plunger_tip_y_mm'];stem_top=tip-p['stem_free_play_mm']
    housing_top=stem_top-p['assumed_stem_operating_travel_mm']-p['housing_margin_after_operating_mm']
    px0,px1=p['plunger_x_min_mm'],p['plunger_x_max_mm'];pz0,pz1=p['plunger_z_min_mm'],p['plunger_z_max_mm']
    a=angles_v3(p);pin_z0=tab_low_top-tt;pin_z1=tab_high_bottom+tt;play=p['hinge_radial_play_mm']
    ops=[
        {'id':'outer','op':'spline_loft','function_id':'F6_connect_shell',
         'reason':'Smooth palm/side skin through closed periodic-spline sections; this outer surface is preserved.',
         'sections':[{'z_mm':z,'points_mm':_ellipse(aa,bb)} for z,aa,bb in SECTIONS]},
        {'id':'cavity','op':'spline_loft','function_id':'F6_connect_shell',
         'reason':'Inner cavity: outer sections inset by the wall; open through the bottom.',
         'sections':_inset_sections(p['shell_wall_mm'])},
        {'id':'hollow','op':'difference','function_id':'F6_connect_shell',
         'reason':'Shell skin = outer volume minus inset cavity.','operands':['outer','cavity']},
        {'id':'safe_core','op':'spline_loft','function_id':'F2_guide_button',
         'reason':'Interior region inset further, where hinge parts may live without touching the wall.',
         'sections':_inset_sections(p['safe_offset_mm'])},
        _box('window','F1_transmit_force','Button skin region cut from the existing side surface.',[wl,20.,zl],[wh,40.,zh]),
        _box('window_gap','F6_connect_shell','Window enlarged by the running gap around the button.',[wl-g,20.,zl-g],[wh+g,40.,zh+g]),
        {'id':'shell_open','op':'difference','function_id':'F6_connect_shell',
         'reason':'Open the side window in the shell with a running gap.','operands':['hollow','window_gap']},
        {'id':'skin_piece','op':'intersection','function_id':'F1_transmit_force',
         'reason':'Button face is the removed piece of the original skin, so the outer shape does not change.',
         'operands':['hollow','window']},
        _box('rib_box','F1_transmit_force','Rear rib carrying finger force from the skin piece toward the hinge link.',
             [wl+1.,20.,zl+.5],[wl+4.,40.,zh-.5]),
        {'id':'rib','op':'intersection','function_id':'F1_transmit_force','reason':'Keep the rib inside the outer skin.',
         'operands':['rib_box','outer']},
        _box('link_box','F2_guide_button','Link from barrel to rib, kept above the stop blocks for the insertion path.',
             [hx+p['barrel_outer_radius_mm']-.5,hy-1.,p['link_z_min_mm']],[wl+4.,hy+2.,zh-.5]),
        {'id':'link','op':'intersection','function_id':'F2_guide_button','reason':'Link stays inside the safe interior.',
         'operands':['link_box','safe_core']},
        {'id':'barrel_outer','op':'cylinder','function_id':'F2_guide_button',
         'reason':'Hinge barrel over the full height between the tabs; its ends are axial thrust faces.',
         'radius_mm':p['barrel_outer_radius_mm'],'height_mm':bz1-bz0,'origin_mm':[hx,hy,bz0],'axis':[0.,0.,1.]},
        _box('stop_arm','F5_limit_overtravel','Full-height stop web, wider than the barrel, running in the stop slot 17 mm from the axis.',
             [hx-w,p['arm_tip_y_mm'],bz0],[hx+w,hy,bz1]),
        _box('plunger_box','F3_actuate_switch','Plunger at the face centre toward the switch stem.',[px0,tip,pz0],[px1,40.,pz1]),
        {'id':'plunger','op':'intersection','function_id':'F3_actuate_switch','reason':'Keep the plunger inside the outer skin.',
         'operands':['plunger_box','outer']},
        {'id':'button_solid','op':'union','function_id':'F1_transmit_force',
         'reason':'One printed button: skin face, rib, link, barrel, stop web and plunger.',
         'operands':['skin_piece','rib','link','barrel_outer','stop_arm','plunger']},
        {'id':'barrel_bore','op':'cylinder','function_id':'F2_guide_button','reason':'Reamed bore on the h7 dowel, 0.05 mm radial play.',
         'radius_mm':p['barrel_inner_radius_mm'],'height_mm':bz1-bz0+2.,'origin_mm':[hx,hy,bz0-1.],'axis':[0.,0.,1.]},
        {'id':'button','op':'difference','function_id':'F2_guide_button','reason':'Bore the barrel for the pin.',
         'operands':['button_solid','barrel_bore']},
        _box('tab_low_box','F6_connect_shell','Lower tab: pin support and stop-slot base, top trimmed to the window gap.',
             [in_face-ibw-.5,by0-.5,tab_low_top-tt],[p['tab_x_max_mm'],40.,tab_low_top]),
        {'id':'tab_low','op':'intersection','function_id':'F6_connect_shell','reason':'Lower tab stays inside the outer skin.',
         'operands':['tab_low_box','outer']},
        _box('tab_high_box','F6_connect_shell','Upper tab: pin support; bottom is the barrel axial thrust face.',
             [hx-3.,hy-3.,tab_high_bottom],[p['tab_x_max_mm'],40.,tab_high_bottom+tt]),
        {'id':'tab_high','op':'intersection','function_id':'F6_connect_shell','reason':'Upper tab stays inside the outer skin.',
         'operands':['tab_high_box','outer']},
        _box('block_in_box','F5_limit_overtravel','Inward hard-stop block (vertical face) carrying the spring pocket.',
             [in_face-ibw,by0,tab_low_top],[in_face,by1,bzt]),
        {'id':'spring_pocket','op':'cylinder','function_id':'F4_restore_button','reason':'Pocket for the return spring.',
         'radius_mm':p['spring_pocket_radius_mm'],'height_mm':pocket+.5,'origin_mm':[in_face-pocket,spring_y,spring_z],'axis':[1.,0.,0.]},
        {'id':'block_in','op':'difference','function_id':'F5_limit_overtravel','reason':'Inward block with its spring pocket.',
         'operands':['block_in_box','spring_pocket']},
        _box('block_out','F2_guide_button','Outward rest-stop block (vertical face); the spring holds the arm on it.',
             [out_face,by0,tab_low_top],[p['tab_x_max_mm'],by1,bzt]),
        {'id':'shell_tabs','op':'union','function_id':'F6_connect_shell',
         'reason':'Shell with window, both tabs and both stop blocks as one printed part.',
         'operands':['shell_open','tab_low','tab_high','block_in','block_out']},
        {'id':'pin_hole','op':'cylinder','function_id':'F6_connect_shell','reason':'Hole for the dowel through both tabs.',
         'radius_mm':p['tab_hole_radius_mm'],'height_mm':pin_z1-pin_z0+2.,'origin_mm':[hx,hy,pin_z0-1.],'axis':[0.,0.,1.]},
        {'id':'shell_part','op':'difference','function_id':'F6_connect_shell','reason':'Drill the pin path through both tabs.',
         'operands':['shell_tabs','pin_hole']},
        {'id':'pin','op':'cylinder','function_id':'F2_guide_button','reason':'Ø2 h7 steel dowel spanning both tabs (purchased).',
         'radius_mm':p['pin_radius_mm'],'height_mm':pin_z1-pin_z0,'origin_mm':[hx,hy,pin_z0],'axis':[0.,0.,1.]},
        {'id':'spring','op':'cylinder','function_id':'F4_restore_button',
         'reason':'Return spring envelope (placeholder): pocket floor to the arm face, preloading the arm onto the rest block.',
         'radius_mm':p['spring_radius_mm'],'height_mm':pocket+gin,'origin_mm':[in_face-pocket,spring_y,spring_z],'axis':[1.,0.,0.]},
        _box('switch_housing','F3_actuate_switch','ASSUMED switch housing envelope (placeholder, not measured).',
             [px0-1.5,housing_top-4.,pz0-1.],[px1+1.5,housing_top,pz1+1.]),
        _box('switch_stem','F3_actuate_switch','ASSUMED switch stem (placeholder).',
             [px0+.5,housing_top,pz0+1.],[px1-.5,stem_top,pz1-1.]),
    ]
    axis={'axis_origin_mm':[hx,hy,0.],'axis_direction':[0.,0.,1.]}
    sp=a['stop_play']
    return {
        'title':'Side button improvement trial, revision 3 (full-height stop web, far stops, spring, reamed hinge)',
        'original_request':request,
        'design_parameters':{k:float(v) for k,v in p.items()},
        'parameter_basis':{k:'Proposal for this prototype revision; not measured from a real mouse, switch or PCB.' for k in p},
        'functions':{
            'F1_transmit_force':'Transmit thumb force from the unchanged side skin into the button.',
            'F2_guide_button':'Guide the button on one fixed hinge axis and hold its rest pose on the rest block.',
            'F3_actuate_switch':'Move the plunger onto the switch stem through its operating travel.',
            'F4_restore_button':'Return the button to its rest block with a compression spring (placeholder envelope).',
            'F5_limit_overtravel':'Stop the button at a hard stop before the switch housing is reached.',
            'F6_connect_shell':'Carry the hinge in the shell without changing the outer surface.'},
        'protected_constraints':['Outer shell skin is not reshaped; the button face is the removed skin piece.'],
        'design_basis':{'kind':'first_principles',
                        'summary':'Pin-hinged flush side button; far slot stops on a full-height web; spring-preloaded rest; centred plunger on an assumed switch.',
                        'assumptions':['Switch housing, stem position and operating travel are placeholders, not a datasheet.',
                                       'Return spring: Ø1.5 compression spring, rate and preload not selected (placeholder envelope).',
                                       'Ø2 h7 steel dowel; the button bore is reamed to 2.10 mm; tab holes 2.01 mm with adhesive retention.',
                                       'Assembly order: spring into pocket, button in from below and slid onto the rest block, dowel up from below, then switch/PCB.',
                                       'FDM prototype: shell printed rim-down; button printed with the bore vertical and web on the bed.']},
        'verification_plan':['Single solids, volume agreement, automatic pair overlap and bounds.',
                             'Rest band: outward motion is blocked within the hinge-play angle at every play offset (flushness bound).',
                             'Free play: no stem contact within the hinge-play angle inward of rest at every play offset.',
                             'Actuation: stem contact by the free-play angle at every play offset.',
                             'Overtravel: the hard stop blocks motion by the stop angle plus the play angle at every play offset, and the housing stays clear up to that angle.',
                             'Nothing in the shell is touched before the nominal stop angle at the nominal axis.',
                             'Assembly path (in from below, slide onto the rest block) and dowel path are clear of the shell.',
                             'Sampled printed wall thickness of shell and button.'],
        'operations':ops,
        'outputs':[{'part_id':'shell','node':'shell_part'},{'part_id':'button','node':'button'},{'part_id':'hinge_pin','node':'pin'},
                   {'part_id':'return_spring','node':'spring'},
                   {'part_id':'switch_housing','node':'switch_housing'},{'part_id':'switch_stem','node':'switch_stem'}],
        'dimension_checks':[
            {'id':'shell-length','part':'shell','kind':'bbox','axis':'x','nominal_mm':120.,'tolerance_mm':.5},
            {'id':'shell-height','part':'shell','kind':'bbox','axis':'z','nominal_mm':34.,'tolerance_mm':1e-3}],
        'clearance_checks':[
            {'id':'rest-pin-in-bore','part_a':'button','part_b':'hinge_pin','min_mm':p['barrel_inner_radius_mm']-p['pin_radius_mm']-1e-3},
            {'id':'rest-button-housing','part_a':'button','part_b':'switch_housing','min_mm':.5}],
        'motion_checks':[
            {'id':'button-insertion-slide','moving_part':'button','obstacles':['shell'],
             # Sample budgets keep the whole build inside the 300 s worker limit;
             # sliding contact cannot be certified, so these are sampled verdicts.
             'translation_end_mm':[0.,-p['insertion_slide_mm'],0.],'samples':9,'max_samples':9,'min_mm':0.},
            {'id':'button-insertion-drop','moving_part':'button','obstacles':['shell'],
             'start_translation_mm':[0.,-p['insertion_slide_mm'],0.],
             'translation_end_mm':[0.,0.,-p['insertion_drop_mm']],'samples':9,'max_samples':17,'min_mm':.1},
            {'id':'pin-insertion-path','moving_part':'hinge_pin','obstacles':['shell'],
             'translation_end_mm':[0.,0.,-(pin_z1+1.)],'samples':9,'max_samples':17,'min_mm':.001}],
        'rotation_checks':[
            {'id':'rest-outward-blocked-within-play','moving_part':'button','obstacles':['shell'],**axis,'end_deg':sp+.05,
             # Blocking is located by the end pose; three samples per offset bound the worker time.
             'expect':'blocked','samples':3,'max_samples':3,'axis_play_mm':play,'min_blocking_overlap_mm3':1e-5},
            {'id':'rest-band-stem-free','moving_part':'button','obstacles':['switch_stem'],**axis,'end_deg':-sp,
             'samples':5,'max_samples':17,'min_mm':.05,'axis_play_mm':play},
            {'id':'stem-contact-by-free-play','moving_part':'button','obstacles':['switch_stem'],**axis,'end_deg':a['contact'],
             'expect':'blocked','samples':3,'max_samples':3,'axis_play_mm':play,'min_blocking_overlap_mm3':1e-4},
            {'id':'housing-clear-past-stop','moving_part':'button','obstacles':['switch_housing'],**axis,'end_deg':a['stop']-sp,
             'samples':5,'max_samples':33,'min_mm':.2,'axis_play_mm':play},
            {'id':'hard-stop-blocks-within-play','moving_part':'button','obstacles':['shell'],**axis,'end_deg':a['stop']-sp-.05,
             'expect':'blocked','samples':3,'max_samples':3,'axis_play_mm':play,'min_blocking_overlap_mm3':1e-4},
            {'id':'shell-clear-until-stop','moving_part':'button','obstacles':['shell'],**axis,'end_deg':a['stop'],
             'samples':5,'max_samples':9,'min_mm':0.,'end_max_distance_mm':.02}],
        'wall_checks':[
            {'id':'shell-printed-wall','part':'shell','min_mm':p['min_printed_wall_mm'],'samples_per_face':10},
            {'id':'button-printed-wall','part':'button','min_mm':p['min_printed_wall_mm'],'samples_per_face':10}],
        'unverified_requirements':[
            '押しやすさ（押下力・ストローク感・クリック感）は実機試験していない。押す位置による力の倍率は剛体計算の目安にすぎない。',
            'Switch housing, stem position, operating force and travel are assumed placeholders, not a measured switch.',
            'PCB position and the real mouse shell were not measured; this is a stand-in shell.',
            'Return spring rate, preload and its effect on thumb force are not selected or verified; it is an envelope only.',
            'Dowel retention (adhesive), reamed-bore size, print tolerance, stop stiffness and wear are not qualified.',
            'Hinge play is covered at eight radial offsets of 0.055 mm; tilt on the pin and axial play are not swept.',
            'Wall checks are sampled minima of the stated parts, not a proof of minimum wall or of strength.'],
    }


# ---------------------------------------------------------------------------
# Revision 4: repairs the revision-3 round-1 major findings.
# - Pin tilt + axial play reached the window rim -> 0.025 mm radial bore play,
#   0.15 mm axial gaps, and two tilt checks with axial play taken up.
# - Spring blocked the slide-in -> through pocket; spring and plug go in after
#   the button and pin, each with a checked path.
# - Dowel fit -> line-reamed press fit, no adhesive; dowel protrudes 1 mm below.
# - Floating face for printing -> barrel, web, rib, plunger and skin share one
#   bed plane; the link is wider.
# - Blocked checks start past the rest contact; rest band uses the rest radius.
# ---------------------------------------------------------------------------
P4=dict(P3)
P4.update({'barrel_inner_radius_mm':1.025,'tab_hole_radius_mm':1.005,'hinge_radial_play_mm':.03,'axial_gap_mm':.15,
           'plunger_z_min_mm':10.,'plug_radius_mm':.795,'plug_length_mm':1.5,'pin_protrusion_mm':1.,
           'stop_extra_travel_mm':.2,'block_z_max_mm':13.8,'link_z_min_mm':14.,'link_z_max_mm':17.3})


def angles_v4(p=P4):
    a=angles_v3(p)
    a['rest_play']=_play_angle_deg(p,p['hinge_y_mm']-p['block_y_max_mm'])
    bore=(p['window_z_max_mm']-.5)-p['window_z_min_mm']
    a['tilt']=math.degrees(2*(p['barrel_inner_radius_mm']-p['pin_radius_mm'])/bore)
    return a


def side_button_recipe_v4(request=REQUEST,p=None):
    p=dict(P4 if p is None else p)
    wl,wh=p['window_x_min_mm'],p['window_x_max_mm'];zl,zh=p['window_z_min_mm'],p['window_z_max_mm'];g=p['window_gap_mm']
    hx,hy=p['hinge_x_mm'],p['hinge_y_mm'];ag=p['axial_gap_mm'];tt=p['tab_thickness_mm']
    # One bed plane: barrel, web, rib, plunger and skin all start at the window bottom.
    bz0=zl;tab_low_top=bz0-ag;bz1=zh-.5;tab_high_bottom=bz1+ag
    w=p['arm_half_width_mm'];by0,by1,bzt=p['block_y_min_mm'],p['block_y_max_mm'],p['block_z_max_mm']
    gin=inward_gap_v3(p);ibw=p['inward_block_width_mm']
    in_face=hx-w-gin;out_face=hx+w
    spring_z=(tab_low_top+bzt)/2;spring_y=(by0+by1)/2;pocket=p['spring_pocket_depth_mm']
    tip=p['plunger_tip_y_mm'];stem_top=tip-p['stem_free_play_mm']
    housing_top=stem_top-p['assumed_stem_operating_travel_mm']-p['housing_margin_after_operating_mm']
    px0,px1=p['plunger_x_min_mm'],p['plunger_x_max_mm'];pz0,pz1=p['plunger_z_min_mm'],p['plunger_z_max_mm']
    a=angles_v4(p);pin_z0=tab_low_top-tt-p['pin_protrusion_mm'];pin_z1=tab_high_bottom+tt;play=p['hinge_radial_play_mm']
    plug=p['plug_length_mm'];bzm=(bz0+bz1)/2;tilt=a['tilt'];tilt_drop=ag-.02
    ops=[
        {'id':'outer','op':'spline_loft','function_id':'F6_connect_shell',
         'reason':'Smooth palm/side skin through closed periodic-spline sections; this outer surface is preserved.',
         'sections':[{'z_mm':z,'points_mm':_ellipse(aa,bb)} for z,aa,bb in SECTIONS]},
        {'id':'cavity','op':'spline_loft','function_id':'F6_connect_shell',
         'reason':'Inner cavity: outer sections inset by the wall; open through the bottom.',
         'sections':_inset_sections(p['shell_wall_mm'])},
        {'id':'hollow','op':'difference','function_id':'F6_connect_shell',
         'reason':'Shell skin = outer volume minus inset cavity.','operands':['outer','cavity']},
        {'id':'safe_core','op':'spline_loft','function_id':'F2_guide_button',
         'reason':'Interior region inset further, where hinge parts may live without touching the wall.',
         'sections':_inset_sections(p['safe_offset_mm'])},
        _box('window','F1_transmit_force','Button skin region cut from the existing side surface.',[wl,20.,zl],[wh,40.,zh]),
        _box('window_gap','F6_connect_shell','Window enlarged by the running gap around the button.',[wl-g,20.,zl-g],[wh+g,40.,zh+g]),
        {'id':'shell_open','op':'difference','function_id':'F6_connect_shell',
         'reason':'Open the side window in the shell with a running gap.','operands':['hollow','window_gap']},
        {'id':'skin_piece','op':'intersection','function_id':'F1_transmit_force',
         'reason':'Button face is the removed piece of the original skin, so the outer shape does not change.',
         'operands':['hollow','window']},
        _box('rib_box','F1_transmit_force','Rear rib carrying finger force from the skin piece toward the hinge link.',
             [wl+1.,20.,bz0],[wl+4.,40.,zh-.5]),
        {'id':'rib','op':'intersection','function_id':'F1_transmit_force','reason':'Keep the rib inside the outer skin.',
         'operands':['rib_box','outer']},
        _box('link_box','F2_guide_button','Link from barrel to rib, kept above the stop blocks for the insertion path.',
             # Link top stays below the barrel top, so only the barrel end bears on the upper tab under tilt.
             [hx+p['barrel_outer_radius_mm']-.5,hy-2.,p['link_z_min_mm']],[wl+4.,hy+2.5,p['link_z_max_mm']]),
        {'id':'link','op':'intersection','function_id':'F2_guide_button','reason':'Link stays inside the safe interior.',
         'operands':['link_box','safe_core']},
        {'id':'barrel_outer','op':'cylinder','function_id':'F2_guide_button',
         'reason':'Hinge barrel over the full height between the tabs; its ends are axial thrust faces.',
         'radius_mm':p['barrel_outer_radius_mm'],'height_mm':bz1-bz0,'origin_mm':[hx,hy,bz0],'axis':[0.,0.,1.]},
        _box('stop_arm','F5_limit_overtravel','Full-height stop web, wider than the barrel, running in the stop slot 17 mm from the axis.',
             [hx-w,p['arm_tip_y_mm'],bz0],[hx+w,hy,bz1]),
        _box('plunger_box','F3_actuate_switch','Plunger at the face centre toward the switch stem.',[px0,tip,pz0],[px1,40.,pz1]),
        {'id':'plunger','op':'intersection','function_id':'F3_actuate_switch','reason':'Keep the plunger inside the outer skin.',
         'operands':['plunger_box','outer']},
        {'id':'button_solid','op':'union','function_id':'F1_transmit_force',
         'reason':'One printed button: skin face, rib, link, barrel, stop web and plunger.',
         'operands':['skin_piece','rib','link','barrel_outer','stop_arm','plunger']},
        {'id':'barrel_bore','op':'cylinder','function_id':'F2_guide_button','reason':'Reamed bore on the h7 dowel, 0.05 mm radial play.',
         'radius_mm':p['barrel_inner_radius_mm'],'height_mm':bz1-bz0+2.,'origin_mm':[hx,hy,bz0-1.],'axis':[0.,0.,1.]},
        {'id':'button','op':'difference','function_id':'F2_guide_button','reason':'Bore the barrel for the pin.',
         'operands':['button_solid','barrel_bore']},
        _box('tab_low_box','F6_connect_shell','Lower tab: pin support and stop-slot base, top trimmed to the window gap.',
             [in_face-ibw-.5,by0-.5,tab_low_top-tt],[p['tab_x_max_mm'],40.,tab_low_top]),
        {'id':'tab_low','op':'intersection','function_id':'F6_connect_shell','reason':'Lower tab stays inside the outer skin.',
         'operands':['tab_low_box','outer']},
        _box('tab_high_box','F6_connect_shell','Upper tab: pin support; bottom is the barrel axial thrust face.',
             [hx-3.,hy-3.,tab_high_bottom],[p['tab_x_max_mm'],40.,tab_high_bottom+tt]),
        {'id':'tab_high','op':'intersection','function_id':'F6_connect_shell','reason':'Upper tab stays inside the outer skin.',
         'operands':['tab_high_box','outer']},
        _box('block_in_box','F5_limit_overtravel','Inward hard-stop block (vertical face) carrying the spring pocket.',
             [in_face-ibw,by0,tab_low_top],[in_face,by1,bzt]),
        {'id':'spring_pocket','op':'cylinder','function_id':'F4_restore_button',
         'reason':'Through pocket: the spring and its plug go in from the outer side after the button.',
         'radius_mm':p['spring_pocket_radius_mm'],'height_mm':ibw+1.,'origin_mm':[in_face-ibw-.5,spring_y,spring_z],'axis':[1.,0.,0.]},
        {'id':'block_in','op':'difference','function_id':'F5_limit_overtravel','reason':'Inward block with its spring pocket.',
         'operands':['block_in_box','spring_pocket']},
        _box('block_out','F2_guide_button','Outward rest-stop block (vertical face); the spring holds the arm on it.',
             [out_face,by0,tab_low_top],[p['tab_x_max_mm'],by1,bzt]),
        {'id':'shell_tabs','op':'union','function_id':'F6_connect_shell',
         'reason':'Shell with window, both tabs and both stop blocks as one printed part.',
         'operands':['shell_open','tab_low','tab_high','block_in','block_out']},
        {'id':'pin_hole','op':'cylinder','function_id':'F6_connect_shell','reason':'Hole for the dowel through both tabs.',
         'radius_mm':p['tab_hole_radius_mm'],'height_mm':pin_z1-pin_z0+2.,'origin_mm':[hx,hy,pin_z0-1.],'axis':[0.,0.,1.]},
        {'id':'shell_part','op':'difference','function_id':'F6_connect_shell','reason':'Drill the pin path through both tabs.',
         'operands':['shell_tabs','pin_hole']},
        {'id':'pin','op':'cylinder','function_id':'F2_guide_button',
         'reason':'Ø2 h7 steel dowel, press fit in line-reamed tab holes, protruding below for extraction (purchased).',
         'radius_mm':p['pin_radius_mm'],'height_mm':pin_z1-pin_z0,'origin_mm':[hx,hy,pin_z0],'axis':[0.,0.,1.]},
        {'id':'spring','op':'cylinder','function_id':'F4_restore_button',
         'reason':'Return spring envelope (placeholder): pocket floor to the arm face, preloading the arm onto the rest block.',
         'radius_mm':p['spring_radius_mm'],'height_mm':pocket+gin,'origin_mm':[in_face-pocket,spring_y,spring_z],'axis':[1.,0.,0.]},
        {'id':'plug','op':'cylinder','function_id':'F4_restore_button','reason':'Press-in plug closing the spring pocket (printed).',
         'radius_mm':p['plug_radius_mm'],'height_mm':plug,'origin_mm':[in_face-pocket-plug,spring_y,spring_z],'axis':[1.,0.,0.]},
        _box('switch_housing','F3_actuate_switch','ASSUMED switch housing envelope (placeholder, not measured).',
             [px0-1.5,housing_top-4.,pz0-1.],[px1+1.5,housing_top,pz1+1.]),
        _box('switch_stem','F3_actuate_switch','ASSUMED switch stem (placeholder).',
             [px0+.5,housing_top,pz0+1.],[px1-.5,stem_top,pz1-1.]),
    ]
    axis={'axis_origin_mm':[hx,hy,0.],'axis_direction':[0.,0.,1.]}
    sp=a['stop_play']
    return {
        'title':'Side button improvement trial, revision 4 (one bed plane, through spring pocket, tilt-checked hinge)',
        'original_request':request,
        'design_parameters':{k:float(v) for k,v in p.items()},
        'parameter_basis':{k:'Proposal for this prototype revision; not measured from a real mouse, switch or PCB.' for k in p},
        'functions':{
            'F1_transmit_force':'Transmit thumb force from the unchanged side skin into the button.',
            'F2_guide_button':'Guide the button on one fixed hinge axis and hold its rest pose on the rest block.',
            'F3_actuate_switch':'Move the plunger onto the switch stem through its operating travel.',
            'F4_restore_button':'Return the button to its rest block with a compression spring (placeholder envelope).',
            'F5_limit_overtravel':'Stop the button at a hard stop before the switch housing is reached.',
            'F6_connect_shell':'Carry the hinge in the shell without changing the outer surface.'},
        'protected_constraints':['Outer shell skin is not reshaped; the button face is the removed skin piece.'],
        'design_basis':{'kind':'first_principles',
                        'summary':'Pin-hinged flush side button; far slot stops on a full-height web; spring-preloaded rest; centred plunger on an assumed switch.',
                        'assumptions':['Switch housing, stem position and operating travel are placeholders, not a datasheet.',
                                       'Return spring: Ø1.5 compression spring, rate and preload not selected (placeholder envelope).',
                                       'Ø2 h7 steel dowel; button bore reamed to 2.05 mm; tab holes printed undersize and line-reamed together, press fit, no adhesive.',
                                       'Assembly order: button in from below and slid onto the rest block, dowel up from below, spring and plug into the through pocket, then switch/PCB.',
                                       'FDM prototype: shell printed rim-down; button printed on its single bed plane (z = window bottom) with the bore vertical.']},
        'verification_plan':['Single solids, volume agreement, automatic pair overlap and bounds.',
                             'Rest band: outward motion is blocked within the hinge-play angle at every play offset (flushness bound).',
                             'Free play: no stem contact within the hinge-play angle inward of rest at every play offset.',
                             'Actuation: stem contact by the free-play angle at every play offset.',
                             'Overtravel: the hard stop blocks motion by the stop angle plus the play angle at every play offset, and the housing stays clear up to that angle.',
                             'Nothing in the shell is touched before the nominal stop angle at the nominal axis.',
                             'Assembly path (in from below, slide onto the rest block) and dowel path are clear of the shell.',
                             'Sampled printed wall thickness of shell and button.'],
        'operations':ops,
        'outputs':[{'part_id':'shell','node':'shell_part'},{'part_id':'button','node':'button'},{'part_id':'hinge_pin','node':'pin'},
                   {'part_id':'return_spring','node':'spring'},{'part_id':'spring_plug','node':'plug'},
                   {'part_id':'switch_housing','node':'switch_housing'},{'part_id':'switch_stem','node':'switch_stem'}],
        'dimension_checks':[
            {'id':'shell-length','part':'shell','kind':'bbox','axis':'x','nominal_mm':120.,'tolerance_mm':.5},
            {'id':'shell-height','part':'shell','kind':'bbox','axis':'z','nominal_mm':34.,'tolerance_mm':1e-3}],
        'clearance_checks':[
            {'id':'rest-pin-in-bore','part_a':'button','part_b':'hinge_pin','min_mm':p['barrel_inner_radius_mm']-p['pin_radius_mm']-1e-3},
            {'id':'rest-button-housing','part_a':'button','part_b':'switch_housing','min_mm':.5}],
        'motion_checks':[
            {'id':'button-insertion-slide','moving_part':'button','obstacles':['shell'],
             # Sample budgets keep the whole build inside the 300 s worker limit;
             # sliding contact cannot be certified, so these are sampled verdicts.
             'translation_end_mm':[0.,-p['insertion_slide_mm'],0.],'samples':9,'max_samples':9,'min_mm':0.},
            {'id':'button-insertion-drop','moving_part':'button','obstacles':['shell'],
             'start_translation_mm':[0.,-p['insertion_slide_mm'],0.],
             'translation_end_mm':[0.,0.,-p['insertion_drop_mm']],'samples':9,'max_samples':17,'min_mm':.1},
            {'id':'pin-insertion-path','moving_part':'hinge_pin','obstacles':['shell'],
             'translation_end_mm':[0.,0.,-(pin_z1+1.)],'samples':9,'max_samples':17,'min_mm':.001},
            # Spring and plug are fitted after the button: their paths out of the pocket must be clear.
            {'id':'plug-insertion-path','moving_part':'spring_plug','obstacles':['shell'],
             'translation_end_mm':[-8.,0.,0.],'samples':5,'max_samples':9,'min_mm':.001},
            {'id':'spring-insertion-path','moving_part':'return_spring','obstacles':['shell'],
             'start_translation_mm':[0.,0.,0.],'translation_end_mm':[-(pocket+gin+plug+6.),0.,0.],'samples':5,'max_samples':9,'min_mm':.001}],
        'rotation_checks':[
            {'id':'rest-outward-blocked-within-play','moving_part':'button','obstacles':['shell'],**axis,'end_deg':a['rest_play']+.05,
             # Blocking is located by the end pose; three samples per offset bound the worker time.
             'expect':'blocked','samples':3,'max_samples':3,'axis_play_mm':play,'min_blocking_overlap_mm3':1e-5},
            {'id':'rest-band-stem-free','moving_part':'button','obstacles':['switch_stem'],**axis,'end_deg':-a['rest_play'],
             'samples':5,'max_samples':17,'min_mm':.05,'axis_play_mm':play},
            {'id':'stem-contact-by-free-play','moving_part':'button','obstacles':['switch_stem'],**axis,'end_deg':a['contact'],
             'expect':'blocked','samples':3,'max_samples':3,'axis_play_mm':play,'min_blocking_overlap_mm3':1e-4},
            {'id':'housing-clear-past-stop','moving_part':'button','obstacles':['switch_housing'],**axis,'end_deg':a['stop']-sp,
             'samples':5,'max_samples':33,'min_mm':.2,'axis_play_mm':play},
            # Starts past the rest contact, so only the hard stop can produce the blocking overlap.
            {'id':'hard-stop-blocks-within-play','moving_part':'button','obstacles':['shell'],**axis,'start_deg':-1.,
             'end_deg':a['stop']-sp-.05,'expect':'blocked','samples':3,'max_samples':3,'axis_play_mm':play,'min_blocking_overlap_mm3':1e-4},
            {'id':'shell-clear-until-stop','moving_part':'button','obstacles':['shell'],**axis,'end_deg':a['stop'],
             'samples':5,'max_samples':9,'min_mm':0.,'end_max_distance_mm':.02},
            # Pin tilt (bore clearance over bore length) about the vertical-plane axis through the barrel,
            # combined with axial play: the face ends must stay off the window rim.
            {'id':'tilt-down-with-axial-drop','moving_part':'button','obstacles':['shell'],
             'axis_origin_mm':[hx,hy,bzm],'axis_direction':[0.,1.,0.],'start_translation_mm':[-play,0.,-tilt_drop],
             'end_deg':tilt,'samples':3,'max_samples':3,'min_mm':0.},
            {'id':'tilt-up-with-axial-rise','moving_part':'button','obstacles':['shell'],
             'axis_origin_mm':[hx,hy,bzm],'axis_direction':[0.,1.,0.],'start_translation_mm':[-play,0.,tilt_drop],
             'end_deg':-tilt,'samples':3,'max_samples':3,'min_mm':0.}],
        'wall_checks':[
            {'id':'shell-printed-wall','part':'shell','min_mm':p['min_printed_wall_mm'],'samples_per_face':10},
            {'id':'button-printed-wall','part':'button','min_mm':p['min_printed_wall_mm'],'samples_per_face':10}],
        'unverified_requirements':[
            '押しやすさ（押下力・ストローク感・クリック感）は実機試験していない。押す位置による力の倍率は剛体計算の目安にすぎない。',
            'Switch housing, stem position, operating force and travel are assumed placeholders, not a measured switch.',
            'PCB position and the real mouse shell were not measured; this is a stand-in shell.',
            'Return spring rate, preload and its effect on thumb force are not selected or verified; it is an envelope only.',
            'Dowel press fit in line-reamed tab holes, reamed bore size, print tolerance, link and tab stiffness and wear are not qualified.',
            'The skin removed by the 0.4 mm running gap around the face (about 38 mm3) and the face standing up to about 0.1 mm proud within hinge play are accepted changes to the outer form.',
            'Hinge play is covered at eight radial offsets; pin tilt is checked about one horizontal axis with axial play, not every combination.',
            'The switch is located by the owner PCB; its position relative to the hinge must stay within the measured rest and housing margins (no PCB datum modeled).',
            '押す位置による押下力の目安（剛体）: 力倍率 = 17 / (x+15)。ヒンジ側端 x=-10 で約3.4倍、中央 x=2 で1.0倍、先端 x=14 で約0.59倍。設計者の仮説であり目標値ではない。',
            'Wall checks are sampled minima of the stated parts, not a proof of minimum wall or of strength.'],
    }


# ---------------------------------------------------------------------------
# Revision 5: repairs the revision-4 round-1 major findings.
# - Fits stated as press fits but modeled as clearance -> declared press fits
#   (dowel in the upper tab, plug in the pocket) with modeled interference.
# - Sub-layer 0.15 mm axial gaps -> 0.2 mm gaps on a 0.2 mm layer grid.
# - First-layer flare on stop faces -> chamfered web bed edges.
# - Skin flexing past the hinge-side stop -> back stiffener along the face.
# - Contract text: switch window numbers, travel table, outer-form changes
#   awaiting owner acceptance, current bore play and pocket wording.
# ---------------------------------------------------------------------------
P5=dict(P4)
P5.update({'axial_gap_mm':.2,'barrel_top_below_window_mm':.4,'lower_hole_radius_mm':1.01,'upper_hole_radius_mm':.99,
           'hinge_radial_play_mm':.035,'plug_radius_mm':.81,'first_layer_chamfer_mm':.4,
           'spine_y_min_mm':26.,'spine_z_min_mm':12.6,'spine_z_max_mm':15.4})
P5.pop('tab_hole_radius_mm',None)


def angles_v5(p=P5):
    a=angles_v3(p)
    a['rest_play']=_play_angle_deg(p,p['hinge_y_mm']-p['block_y_max_mm'])
    bore=(p['window_z_max_mm']-p['barrel_top_below_window_mm'])-p['window_z_min_mm']
    a['tilt']=math.degrees(2*(p['barrel_inner_radius_mm']-p['pin_radius_mm'])/bore)
    return a


def side_button_recipe_v5(request=REQUEST,p=None):
    p=dict(P5 if p is None else p)
    wl,wh=p['window_x_min_mm'],p['window_x_max_mm'];zl,zh=p['window_z_min_mm'],p['window_z_max_mm'];g=p['window_gap_mm']
    hx,hy=p['hinge_x_mm'],p['hinge_y_mm'];ag=p['axial_gap_mm'];tt=p['tab_thickness_mm']
    # One bed plane: barrel, web, rib, plunger and skin all start at the window bottom.
    # Heights on a 0.2 mm layer grid: button bed z=10.0, barrel top 17.6, tab faces 9.8 and 17.8.
    bz0=zl;tab_low_top=bz0-ag;bz1=zh-p['barrel_top_below_window_mm'];tab_high_bottom=bz1+ag
    w=p['arm_half_width_mm'];by0,by1,bzt=p['block_y_min_mm'],p['block_y_max_mm'],p['block_z_max_mm']
    gin=inward_gap_v3(p);ibw=p['inward_block_width_mm']
    in_face=hx-w-gin;out_face=hx+w
    spring_z=(tab_low_top+bzt)/2;spring_y=(by0+by1)/2;pocket=p['spring_pocket_depth_mm']
    tip=p['plunger_tip_y_mm'];stem_top=tip-p['stem_free_play_mm']
    housing_top=stem_top-p['assumed_stem_operating_travel_mm']-p['housing_margin_after_operating_mm']
    px0,px1=p['plunger_x_min_mm'],p['plunger_x_max_mm'];pz0,pz1=p['plunger_z_min_mm'],p['plunger_z_max_mm']
    a=angles_v5(p);pin_z0=tab_low_top-tt-p['pin_protrusion_mm'];pin_z1=tab_high_bottom+tt;play=p['hinge_radial_play_mm']
    plug=p['plug_length_mm'];bzm=(bz0+bz1)/2;tilt=a['tilt']
    # Axial play taken up short of the barrel-end contact; the tilt itself lifts the barrel edge ~0.016 mm.
    tilt_drop=ag-.03
    ops=[
        {'id':'outer','op':'spline_loft','function_id':'F6_connect_shell',
         'reason':'Smooth palm/side skin through closed periodic-spline sections; this outer surface is preserved.',
         'sections':[{'z_mm':z,'points_mm':_ellipse(aa,bb)} for z,aa,bb in SECTIONS]},
        {'id':'cavity','op':'spline_loft','function_id':'F6_connect_shell',
         'reason':'Inner cavity: outer sections inset by the wall; open through the bottom.',
         'sections':_inset_sections(p['shell_wall_mm'])},
        {'id':'hollow','op':'difference','function_id':'F6_connect_shell',
         'reason':'Shell skin = outer volume minus inset cavity.','operands':['outer','cavity']},
        {'id':'safe_core','op':'spline_loft','function_id':'F2_guide_button',
         'reason':'Interior region inset further, where hinge parts may live without touching the wall.',
         'sections':_inset_sections(p['safe_offset_mm'])},
        _box('window','F1_transmit_force','Button skin region cut from the existing side surface.',[wl,20.,zl],[wh,40.,zh]),
        _box('window_gap','F6_connect_shell','Window enlarged by the running gap around the button.',[wl-g,20.,zl-g],[wh+g,40.,zh+g]),
        {'id':'shell_open','op':'difference','function_id':'F6_connect_shell',
         'reason':'Open the side window in the shell with a running gap.','operands':['hollow','window_gap']},
        {'id':'skin_piece','op':'intersection','function_id':'F1_transmit_force',
         'reason':'Button face is the removed piece of the original skin, so the outer shape does not change.',
         'operands':['hollow','window']},
        _box('rib_box','F1_transmit_force','Rear rib carrying finger force from the skin piece toward the hinge link.',
             [wl+1.,20.,bz0],[wl+4.,40.,zh-.5]),
        {'id':'rib','op':'intersection','function_id':'F1_transmit_force','reason':'Keep the rib inside the outer skin.',
         'operands':['rib_box','outer']},
        _box('link_box','F2_guide_button','Link from barrel to rib, kept above the stop blocks for the insertion path.',
             # Link top stays below the barrel top, so only the barrel end bears on the upper tab under tilt.
             [hx+p['barrel_outer_radius_mm']-.5,hy-2.,p['link_z_min_mm']],[wl+4.,hy+2.5,p['link_z_max_mm']]),
        {'id':'link','op':'intersection','function_id':'F2_guide_button','reason':'Link stays inside the safe interior.',
         'operands':['link_box','safe_core']},
        {'id':'barrel_outer','op':'cylinder','function_id':'F2_guide_button',
         'reason':'Hinge barrel over the full height between the tabs; its ends are axial thrust faces.',
         'radius_mm':p['barrel_outer_radius_mm'],'height_mm':bz1-bz0,'origin_mm':[hx,hy,bz0],'axis':[0.,0.,1.]},
        _box('stop_arm_box','F5_limit_overtravel','Full-height stop web, wider than the barrel, running in the stop slot 17 mm from the axis.',
             [hx-w,p['arm_tip_y_mm'],bz0],[hx+w,hy,bz1]),
        {'id':'stop_arm','op':'chamfer_edges','function_id':'F5_limit_overtravel','source':'stop_arm_box','selector':'<Z',
         'size_mm':p['first_layer_chamfer_mm'],
         'reason':'Chamfer the bed edges so first-layer flare cannot reach the rest and stop faces.'},
        _box('spine_box','F1_transmit_force','Back stiffener along the face so a firm press reaches the hinge-side stop without bending the skin.',
             [wl+4.,p['spine_y_min_mm'],p['spine_z_min_mm']],[wh-1.5,40.,p['spine_z_max_mm']]),
        {'id':'spine','op':'intersection','function_id':'F1_transmit_force','reason':'Keep the stiffener inside the outer skin.',
         'operands':['spine_box','outer']},
        _box('plunger_box','F3_actuate_switch','Plunger at the face centre toward the switch stem.',[px0,tip,pz0],[px1,40.,pz1]),
        {'id':'plunger','op':'intersection','function_id':'F3_actuate_switch','reason':'Keep the plunger inside the outer skin.',
         'operands':['plunger_box','outer']},
        {'id':'button_solid','op':'union','function_id':'F1_transmit_force',
         'reason':'One printed button: skin face, rib, link, barrel, stop web and plunger.',
         'operands':['skin_piece','rib','link','barrel_outer','stop_arm','plunger','spine']},
        {'id':'barrel_bore','op':'cylinder','function_id':'F2_guide_button','reason':'Reamed bore on the h7 dowel, 0.05 mm radial play.',
         'radius_mm':p['barrel_inner_radius_mm'],'height_mm':bz1-bz0+2.,'origin_mm':[hx,hy,bz0-1.],'axis':[0.,0.,1.]},
        {'id':'button','op':'difference','function_id':'F2_guide_button','reason':'Bore the barrel for the pin.',
         'operands':['button_solid','barrel_bore']},
        _box('tab_low_box','F6_connect_shell','Lower tab: pin support and stop-slot base, top trimmed to the window gap.',
             [in_face-ibw-.5,by0-.5,tab_low_top-tt],[p['tab_x_max_mm'],40.,tab_low_top]),
        {'id':'tab_low','op':'intersection','function_id':'F6_connect_shell','reason':'Lower tab stays inside the outer skin.',
         'operands':['tab_low_box','outer']},
        _box('tab_high_box','F6_connect_shell','Upper tab: pin support; bottom is the barrel axial thrust face.',
             [hx-3.,hy-3.,tab_high_bottom],[p['tab_x_max_mm'],40.,tab_high_bottom+tt]),
        {'id':'tab_high','op':'intersection','function_id':'F6_connect_shell','reason':'Upper tab stays inside the outer skin.',
         'operands':['tab_high_box','outer']},
        _box('block_in_box','F5_limit_overtravel','Inward hard-stop block (vertical face) carrying the spring pocket.',
             [in_face-ibw,by0,tab_low_top],[in_face,by1,bzt]),
        {'id':'spring_pocket','op':'cylinder','function_id':'F4_restore_button',
         'reason':'Through pocket: the spring and its plug go in from the outer side after the button.',
         'radius_mm':p['spring_pocket_radius_mm'],'height_mm':ibw+1.,'origin_mm':[in_face-ibw-.5,spring_y,spring_z],'axis':[1.,0.,0.]},
        {'id':'block_in','op':'difference','function_id':'F5_limit_overtravel','reason':'Inward block with its spring pocket.',
         'operands':['block_in_box','spring_pocket']},
        _box('block_out','F2_guide_button','Outward rest-stop block (vertical face); the spring holds the arm on it.',
             [out_face,by0,tab_low_top],[p['tab_x_max_mm'],by1,bzt]),
        {'id':'shell_tabs','op':'union','function_id':'F6_connect_shell',
         'reason':'Shell with window, both tabs and both stop blocks as one printed part.',
         'operands':['shell_open','tab_low','tab_high','block_in','block_out']},
        {'id':'pin_hole_low','op':'cylinder','function_id':'F6_connect_shell','reason':'Clearance hole for the dowel through the lower tab.',
         'radius_mm':p['lower_hole_radius_mm'],'height_mm':tab_high_bottom-pin_z0+1.,'origin_mm':[hx,hy,pin_z0-1.],'axis':[0.,0.,1.]},
        {'id':'pin_hole_high','op':'cylinder','function_id':'F6_connect_shell',
         'reason':'Reamed press-fit hole for the dowel in the upper tab only; no overrun into the dome.',
         'radius_mm':p['upper_hole_radius_mm'],'height_mm':tt+.1,'origin_mm':[hx,hy,tab_high_bottom-.1],'axis':[0.,0.,1.]},
        {'id':'shell_part','op':'difference','function_id':'F6_connect_shell','reason':'Drill the pin path through both tabs.',
         'operands':['shell_tabs','pin_hole_low','pin_hole_high']},
        {'id':'pin','op':'cylinder','function_id':'F2_guide_button',
         'reason':'Ø2 h7 steel dowel, press fit in line-reamed tab holes, protruding below for extraction (purchased).',
         'radius_mm':p['pin_radius_mm'],'height_mm':pin_z1-pin_z0,'origin_mm':[hx,hy,pin_z0],'axis':[0.,0.,1.]},
        {'id':'spring','op':'cylinder','function_id':'F4_restore_button',
         'reason':'Return spring envelope (placeholder): pocket floor to the arm face, preloading the arm onto the rest block.',
         'radius_mm':p['spring_radius_mm'],'height_mm':pocket+gin,'origin_mm':[in_face-pocket,spring_y,spring_z],'axis':[1.,0.,0.]},
        {'id':'plug','op':'cylinder','function_id':'F4_restore_button','reason':'Press-fit plug (0.01 mm radial interference) closing the spring pocket; its seated depth is the pocket mouth.',
         'radius_mm':p['plug_radius_mm'],'height_mm':plug,'origin_mm':[in_face-pocket-plug,spring_y,spring_z],'axis':[1.,0.,0.]},
        _box('switch_housing','F3_actuate_switch','ASSUMED switch housing envelope (placeholder, not measured).',
             [px0-1.5,housing_top-4.,pz0-1.],[px1+1.5,housing_top,pz1+1.]),
        _box('switch_stem','F3_actuate_switch','ASSUMED switch stem (placeholder).',
             [px0+.5,housing_top,pz0+1.],[px1-.5,stem_top,pz1-1.]),
    ]
    axis={'axis_origin_mm':[hx,hy,0.],'axis_direction':[0.,0.,1.]}
    sp=a['stop_play']
    return {
        'title':'Side button improvement trial, revision 5 (declared press fits, layer-grid gaps, stiffened face)',
        'original_request':request,
        'design_parameters':{k:float(v) for k,v in p.items()},
        'parameter_basis':{k:'Proposal for this prototype revision; not measured from a real mouse, switch or PCB.' for k in p},
        'functions':{
            'F1_transmit_force':'Transmit thumb force from the side skin (unchanged except the running gap) into the button.',
            'F2_guide_button':'Guide the button on one fixed hinge axis and hold its rest pose on the rest block.',
            'F3_actuate_switch':'Move the plunger onto the switch stem through its operating travel.',
            'F4_restore_button':'Return the button to its rest block with a compression spring (placeholder envelope).',
            'F5_limit_overtravel':'Stop the button at a hard stop before the switch housing is reached.',
            'F6_connect_shell':'Carry the hinge in the shell without changing the outer surface.'},
        'protected_constraints':['Outer shell skin is not reshaped except the 0.4 mm running gap around the button, which awaits owner acceptance; the button face is the removed skin piece.'],
        'design_basis':{'kind':'first_principles',
                        'summary':'Pin-hinged flush side button; far slot stops on a full-height web; spring-preloaded rest; centred plunger on an assumed switch.',
                        'assumptions':['Switch housing, stem position and operating travel are placeholders, not a datasheet.',
                                       'Return spring: Ø1.5 compression spring, rate and preload not selected (placeholder envelope).',
                                       'Ø2 h7 steel dowel; button bore reamed to 2.05 mm (0.025 mm radial play); lower tab hole 2.02 mm clearance; upper tab hole reamed to 1.98 mm for a press fit, no adhesive.',
                                       'FDM layer height 0.2 mm; gaps and faces lie on that grid (bed z 0 for the shell, z 10.0 for the button).',
                                       'Assembly order: button in from below and slid onto the rest block, dowel pressed up from below into the upper tab, spring and plug into the through pocket, then switch/PCB.',
                                       'FDM prototype: shell printed rim-down; button printed on its single bed plane (z = window bottom) with the bore vertical.']},
        'verification_plan':['Single solids, volume agreement, automatic pair overlap and bounds.',
                             'Rest band: outward motion is blocked within the hinge-play angle at every play offset (flushness bound).',
                             'Free play: no stem contact within the hinge-play angle inward of rest at every play offset.',
                             'Actuation: stem contact by the free-play angle at every play offset.',
                             'Overtravel: the hard stop blocks motion by the stop angle plus the play angle at every play offset, and the housing stays clear up to that angle.',
                             'Nothing in the shell is touched before the nominal stop angle at the nominal axis.',
                             'Assembly path (in from below, slide onto the rest block) and dowel path are clear of the shell.',
                             'Sampled printed wall thickness of shell and button.'],
        'operations':ops,
        'outputs':[{'part_id':'shell','node':'shell_part'},{'part_id':'button','node':'button'},{'part_id':'hinge_pin','node':'pin'},
                   {'part_id':'return_spring','node':'spring'},{'part_id':'spring_plug','node':'plug'},
                   {'part_id':'switch_housing','node':'switch_housing'},{'part_id':'switch_stem','node':'switch_stem'}],
        'dimension_checks':[
            {'id':'shell-length','part':'shell','kind':'bbox','axis':'x','nominal_mm':120.,'tolerance_mm':.5},
            {'id':'shell-height','part':'shell','kind':'bbox','axis':'z','nominal_mm':34.,'tolerance_mm':1e-3}],
        'clearance_checks':[
            {'id':'rest-pin-in-bore','part_a':'button','part_b':'hinge_pin','min_mm':p['barrel_inner_radius_mm']-p['pin_radius_mm']-1e-3},
            {'id':'rest-button-housing','part_a':'button','part_b':'switch_housing','min_mm':.5}],
        'motion_checks':[
            {'id':'button-insertion-slide','moving_part':'button','obstacles':['shell'],
             # Sample budgets keep the whole build inside the 300 s worker limit;
             # sliding contact cannot be certified, so these are sampled verdicts.
             'translation_end_mm':[0.,-p['insertion_slide_mm'],0.],'samples':9,'max_samples':9,'min_mm':0.},
            {'id':'button-insertion-drop','moving_part':'button','obstacles':['shell'],
             'start_translation_mm':[0.,-p['insertion_slide_mm'],0.],
             'translation_end_mm':[0.,0.,-p['insertion_drop_mm']],'samples':5,'max_samples':5,'min_mm':.1},
            {'id':'pin-insertion-path','moving_part':'hinge_pin','obstacles':['shell'],
             # Leg after the dowel has left its press fit in the upper tab.
             'start_translation_mm':[0.,0.,-(tt+.1)],'translation_end_mm':[0.,0.,-(pin_z1+1.-tt)],'samples':9,'max_samples':17,'min_mm':.001},
            # Spring and plug are fitted after the button: their paths out of the pocket must be clear.
            {'id':'plug-insertion-path','moving_part':'spring_plug','obstacles':['shell'],
             'start_translation_mm':[-(plug+.1),0.,0.],'translation_end_mm':[-8.,0.,0.],'samples':5,'max_samples':9,'min_mm':.001},
            {'id':'spring-insertion-path','moving_part':'return_spring','obstacles':['shell'],
             'start_translation_mm':[0.,0.,0.],'translation_end_mm':[-(pocket+gin+plug+6.),0.,0.],'samples':5,'max_samples':9,'min_mm':.001}],
        'rotation_checks':[
            {'id':'rest-outward-blocked-within-play','moving_part':'button','obstacles':['shell'],**axis,'end_deg':a['rest_play']+.05,
             # Blocking is located by the end pose; three samples per offset bound the worker time.
             'expect':'blocked','samples':2,'max_samples':2,'axis_play_mm':play,'min_blocking_overlap_mm3':1e-5},
            {'id':'rest-band-stem-free','moving_part':'button','obstacles':['switch_stem'],**axis,'end_deg':-a['rest_play'],
             'samples':5,'max_samples':17,'min_mm':.05,'axis_play_mm':play},
            {'id':'stem-contact-by-free-play','moving_part':'button','obstacles':['switch_stem'],**axis,'end_deg':a['contact'],
             'expect':'blocked','samples':3,'max_samples':3,'axis_play_mm':play,'min_blocking_overlap_mm3':1e-4},
            {'id':'housing-clear-past-stop','moving_part':'button','obstacles':['switch_housing'],**axis,'end_deg':a['stop']-sp,
             'samples':5,'max_samples':33,'min_mm':.2,'axis_play_mm':play},
            # Starts past the rest contact, so only the hard stop can produce the blocking overlap.
            {'id':'hard-stop-blocks-within-play','moving_part':'button','obstacles':['shell'],**axis,'start_deg':-1.,
             'end_deg':a['stop']-sp-.05,'expect':'blocked','samples':2,'max_samples':2,'axis_play_mm':play,'min_blocking_overlap_mm3':1e-4},
            {'id':'shell-clear-until-stop','moving_part':'button','obstacles':['shell'],**axis,'end_deg':a['stop'],
             'samples':5,'max_samples':9,'min_mm':0.,'end_max_distance_mm':.02},
            # Pin tilt (bore clearance over bore length) about the vertical-plane axis through the barrel,
            # combined with axial play: the face ends must stay off the window rim.
            {'id':'tilt-down-with-axial-drop','moving_part':'button','obstacles':['shell'],
             'axis_origin_mm':[hx,hy,bzm],'axis_direction':[0.,1.,0.],'start_translation_mm':[-play,0.,-tilt_drop],
             'end_deg':tilt,'samples':3,'max_samples':3,'min_mm':0.},
            {'id':'tilt-up-with-axial-rise','moving_part':'button','obstacles':['shell'],
             'axis_origin_mm':[hx,hy,bzm],'axis_direction':[0.,1.,0.],'start_translation_mm':[-play,0.,tilt_drop],
             'end_deg':-tilt,'samples':3,'max_samples':3,'min_mm':0.}],
        'press_fits':[
            {'id':'dowel-in-upper-tab','part_a':'hinge_pin','part_b':'shell','min_overlap_mm3':.1,'max_overlap_mm3':.3,
             'basis':'0.01 mm radial interference over the 3 mm upper tab: about 0.19 mm3 of rigid overlap.'},
            {'id':'plug-in-pocket','part_a':'spring_plug','part_b':'shell','min_overlap_mm3':.04,'max_overlap_mm3':.12,
             'basis':'0.01 mm radial interference over the 1.5 mm plug: about 0.076 mm3 of rigid overlap.'}],
        'wall_checks':[
            {'id':'shell-printed-wall','part':'shell','min_mm':p['min_printed_wall_mm'],'samples_per_face':10},
            {'id':'button-printed-wall','part':'button','min_mm':p['min_printed_wall_mm'],'samples_per_face':10}],
        'unverified_requirements':[
            '押しやすさ（押下力・ストローク感・クリック感）は実機試験していない。押す位置による力の倍率は剛体計算の目安にすぎない。',
            'Switch housing, stem position, operating force and travel are assumed placeholders, not a measured switch.',
            'PCB position and the real mouse shell were not measured; this is a stand-in shell.',
            'Return spring rate, preload and its effect on thumb force are not selected or verified; it is an envelope only.',
            'Dowel press fit in line-reamed tab holes, reamed bore size, print tolerance, link and tab stiffness and wear are not qualified.',
            'Outer-form changes awaiting owner acceptance: the 0.4 mm running gap removes about 38 mm3 of skin, and within hinge play the face may stand proud by up to the bound of the rest-outward check (about 0.06-0.12 mm).',
            'Rigid face travel at the press angle (designer estimate): about 0.21 mm at x=-10, 0.70 mm at x=2 and 1.19 mm at x=14; the return spring force adds to thumb force and is not selected.',
            'Switch window (from the measured margins): the stem top must sit within -0.20/+0.10 mm in Y of the modeled position relative to the dowel; the owner PCB must hold it (no datum modeled).',
            'Press fits are verified only as rigid overlap bands; retention force and printed hole accuracy are not verified.',
            'Skin and stiffener bending under a firm press beyond the hard stop is not analysed (no FEA).',
            'Hinge play is covered at eight radial offsets; pin tilt is checked about one horizontal axis with axial play, not every combination.',
            'The switch is located by the owner PCB; its position relative to the hinge must stay within the measured rest and housing margins (no PCB datum modeled).',
            '押す位置による押下力の目安（剛体）: 力倍率 = 17 / (x+15)。ヒンジ側端 x=-10 で約3.4倍、中央 x=2 で1.0倍、先端 x=14 で約0.59倍。設計者の仮説であり目標値ではない。',
            'Wall checks are sampled minima of the stated parts, not a proof of minimum wall or of strength.'],
    }


# ---------------------------------------------------------------------------
# Revision 6: repairs the revision-5 round-1 major findings.
# - Barrel top rim 0.067 mm from the inner skin -> chamfered rim plus a check
#   of full axial rise with hinge play in all eight directions.
# - Plug retention in an unreamed printed hole -> purchased Ø1.6 steel dowel
#   in a reamed pocket; thicker pocket walls.
# - Upper thrust face printed on support, curved lintel bridge, printed rest
#   face error -> stated support plan, gauge finishing and rest-face
#   calibration with a feeler gauge.
# - Single thin link -> link deepened to y 20.
# - Dowel depth stop: blind upper hole.  Contract text corrected.
# - Placeholder switch housing deeper (assumed overtravel), so the stated
#   switch window stays inside the design's own margins.
# ---------------------------------------------------------------------------
P6=dict(P5)
P6.update({'barrel_top_chamfer_mm':.5,'link_y_min_mm':20.,'block_y_min_mm':7.3,'block_y_max_mm':11.7,
           'block_z_max_mm':14.,'link_z_min_mm':14.2,'upper_hole_depth_mm':1.8,'housing_margin_after_operating_mm':.8})


def angles_v6(p=P6):
    return angles_v5(p)


def side_button_recipe_v6(request=REQUEST,p=None):
    p=dict(P6 if p is None else p)
    wl,wh=p['window_x_min_mm'],p['window_x_max_mm'];zl,zh=p['window_z_min_mm'],p['window_z_max_mm'];g=p['window_gap_mm']
    hx,hy=p['hinge_x_mm'],p['hinge_y_mm'];ag=p['axial_gap_mm'];tt=p['tab_thickness_mm']
    # One bed plane: barrel, web, rib, plunger and skin all start at the window bottom.
    # Heights on a 0.2 mm layer grid: button bed z=10.0, barrel top 17.6, tab faces 9.8 and 17.8.
    bz0=zl;tab_low_top=bz0-ag;bz1=zh-p['barrel_top_below_window_mm'];tab_high_bottom=bz1+ag
    w=p['arm_half_width_mm'];by0,by1,bzt=p['block_y_min_mm'],p['block_y_max_mm'],p['block_z_max_mm']
    gin=inward_gap_v3(p);ibw=p['inward_block_width_mm']
    in_face=hx-w-gin;out_face=hx+w
    spring_z=(tab_low_top+bzt)/2;spring_y=(by0+by1)/2;pocket=p['spring_pocket_depth_mm']
    tip=p['plunger_tip_y_mm'];stem_top=tip-p['stem_free_play_mm']
    housing_top=stem_top-p['assumed_stem_operating_travel_mm']-p['housing_margin_after_operating_mm']
    px0,px1=p['plunger_x_min_mm'],p['plunger_x_max_mm'];pz0,pz1=p['plunger_z_min_mm'],p['plunger_z_max_mm']
    a=angles_v6(p);pin_z0=tab_low_top-tt-p['pin_protrusion_mm'];pin_z1=tab_high_bottom+p['upper_hole_depth_mm'];play=p['hinge_radial_play_mm']
    plug=p['plug_length_mm'];bzm=(bz0+bz1)/2;tilt=a['tilt']
    # Axial play taken up short of the barrel-end contact; the tilt itself lifts the barrel edge ~0.016 mm.
    tilt_drop=ag-.03
    ops=[
        {'id':'outer','op':'spline_loft','function_id':'F6_connect_shell',
         'reason':'Smooth palm/side skin through closed periodic-spline sections; this outer surface is preserved.',
         'sections':[{'z_mm':z,'points_mm':_ellipse(aa,bb)} for z,aa,bb in SECTIONS]},
        {'id':'cavity','op':'spline_loft','function_id':'F6_connect_shell',
         'reason':'Inner cavity: outer sections inset by the wall; open through the bottom.',
         'sections':_inset_sections(p['shell_wall_mm'])},
        {'id':'hollow','op':'difference','function_id':'F6_connect_shell',
         'reason':'Shell skin = outer volume minus inset cavity.','operands':['outer','cavity']},
        {'id':'safe_core','op':'spline_loft','function_id':'F2_guide_button',
         'reason':'Interior region inset further, where hinge parts may live without touching the wall.',
         'sections':_inset_sections(p['safe_offset_mm'])},
        _box('window','F1_transmit_force','Button skin region cut from the existing side surface.',[wl,20.,zl],[wh,40.,zh]),
        _box('window_gap','F6_connect_shell','Window enlarged by the running gap around the button.',[wl-g,20.,zl-g],[wh+g,40.,zh+g]),
        {'id':'shell_open','op':'difference','function_id':'F6_connect_shell',
         'reason':'Open the side window in the shell with a running gap.','operands':['hollow','window_gap']},
        {'id':'skin_piece','op':'intersection','function_id':'F1_transmit_force',
         'reason':'Button face is the removed piece of the original skin, so the outer shape does not change.',
         'operands':['hollow','window']},
        _box('rib_box','F1_transmit_force','Rear rib carrying finger force from the skin piece toward the hinge link.',
             [wl+1.,20.,bz0],[wl+4.,40.,zh-.5]),
        {'id':'rib','op':'intersection','function_id':'F1_transmit_force','reason':'Keep the rib inside the outer skin.',
         'operands':['rib_box','outer']},
        _box('link_box','F2_guide_button','Link from barrel to rib, kept above the stop blocks for the insertion path.',
             # Link top stays below the barrel top, so only the barrel end bears on the upper tab under tilt.
             [hx+p['barrel_outer_radius_mm']-.5,p['link_y_min_mm'],p['link_z_min_mm']],[wl+4.,hy+2.5,p['link_z_max_mm']]),
        {'id':'link','op':'intersection','function_id':'F2_guide_button','reason':'Link stays inside the safe interior.',
         'operands':['link_box','safe_core']},
        {'id':'barrel_raw','op':'cylinder','function_id':'F2_guide_button',
         'reason':'Hinge barrel over the full height between the tabs; its ends and the web ends are axial faces.',
         'radius_mm':p['barrel_outer_radius_mm'],'height_mm':bz1-bz0,'origin_mm':[hx,hy,bz0],'axis':[0.,0.,1.]},
        {'id':'barrel_outer','op':'chamfer_edges','function_id':'F2_guide_button','source':'barrel_raw','selector':'>Z',
         'size_mm':p['barrel_top_chamfer_mm'],
         'reason':'Chamfer the barrel top rim, which otherwise approaches the inner skin within the hinge play.'},
        _box('stop_arm_box','F5_limit_overtravel','Full-height stop web, wider than the barrel, running in the stop slot 17 mm from the axis.',
             [hx-w,p['arm_tip_y_mm'],bz0],[hx+w,hy,bz1]),
        {'id':'stop_arm','op':'chamfer_edges','function_id':'F5_limit_overtravel','source':'stop_arm_box','selector':'<Z',
         'size_mm':p['first_layer_chamfer_mm'],
         'reason':'Chamfer the bed edges so first-layer flare cannot reach the rest and stop faces.'},
        _box('spine_box','F1_transmit_force','Back stiffener along the face that reduces skin bending under a firm press (not analysed).',
             [wl+4.,p['spine_y_min_mm'],p['spine_z_min_mm']],[wh-1.5,40.,p['spine_z_max_mm']]),
        {'id':'spine','op':'intersection','function_id':'F1_transmit_force','reason':'Keep the stiffener inside the outer skin.',
         'operands':['spine_box','outer']},
        _box('plunger_box','F3_actuate_switch','Plunger at the face centre toward the switch stem.',[px0,tip,pz0],[px1,40.,pz1]),
        {'id':'plunger','op':'intersection','function_id':'F3_actuate_switch','reason':'Keep the plunger inside the outer skin.',
         'operands':['plunger_box','outer']},
        {'id':'button_solid','op':'union','function_id':'F1_transmit_force',
         'reason':'One printed button: skin face, rib, link, barrel, stop web and plunger.',
         'operands':['skin_piece','rib','link','barrel_outer','stop_arm','plunger','spine']},
        {'id':'barrel_bore','op':'cylinder','function_id':'F2_guide_button','reason':'Bore reamed to 2.05 mm on the h7 dowel: 0.025 mm radial play.',
         'radius_mm':p['barrel_inner_radius_mm'],'height_mm':bz1-bz0+2.,'origin_mm':[hx,hy,bz0-1.],'axis':[0.,0.,1.]},
        {'id':'button','op':'difference','function_id':'F2_guide_button','reason':'Bore the barrel for the pin.',
         'operands':['button_solid','barrel_bore']},
        _box('tab_low_box','F6_connect_shell','Lower tab: pin support and stop-slot base, top trimmed to the window gap.',
             [in_face-ibw-.5,by0-.5,tab_low_top-tt],[p['tab_x_max_mm'],40.,tab_low_top]),
        {'id':'tab_low','op':'intersection','function_id':'F6_connect_shell','reason':'Lower tab stays inside the outer skin.',
         'operands':['tab_low_box','outer']},
        _box('tab_high_box','F6_connect_shell','Upper tab: pin support; bottom is the barrel axial thrust face.',
             [hx-3.,hy-3.,tab_high_bottom],[p['tab_x_max_mm'],40.,tab_high_bottom+tt]),
        {'id':'tab_high','op':'intersection','function_id':'F6_connect_shell','reason':'Upper tab stays inside the outer skin.',
         'operands':['tab_high_box','outer']},
        _box('block_in_box','F5_limit_overtravel','Inward hard-stop block (vertical face) carrying the spring pocket.',
             [in_face-ibw,by0,tab_low_top],[in_face,by1,bzt]),
        {'id':'spring_pocket','op':'cylinder','function_id':'F4_restore_button',
         'reason':'Through pocket: the spring and its plug go in from the outer side after the button.',
         'radius_mm':p['spring_pocket_radius_mm'],'height_mm':ibw+1.,'origin_mm':[in_face-ibw-.5,spring_y,spring_z],'axis':[1.,0.,0.]},
        {'id':'block_in','op':'difference','function_id':'F5_limit_overtravel','reason':'Inward block with its spring pocket.',
         'operands':['block_in_box','spring_pocket']},
        _box('block_out','F2_guide_button','Outward rest-stop block (vertical face); the spring holds the arm on it.',
             [out_face,by0,tab_low_top],[p['tab_x_max_mm'],by1,bzt]),
        {'id':'shell_tabs','op':'union','function_id':'F6_connect_shell',
         'reason':'Shell with window, both tabs and both stop blocks as one printed part.',
         'operands':['shell_open','tab_low','tab_high','block_in','block_out']},
        {'id':'pin_hole_low','op':'cylinder','function_id':'F6_connect_shell','reason':'Clearance hole for the dowel through the lower tab.',
         'radius_mm':p['lower_hole_radius_mm'],'height_mm':tab_high_bottom-pin_z0+1.,'origin_mm':[hx,hy,pin_z0-1.],'axis':[0.,0.,1.]},
        {'id':'pin_hole_high','op':'cylinder','function_id':'F6_connect_shell',
         'reason':'Blind reamed press-fit hole in the upper tab; the remaining cap is the dowel depth stop.',
         'radius_mm':p['upper_hole_radius_mm'],'height_mm':p['upper_hole_depth_mm']+.1,'origin_mm':[hx,hy,tab_high_bottom-.1],'axis':[0.,0.,1.]},
        {'id':'shell_part','op':'difference','function_id':'F6_connect_shell','reason':'Drill the pin path through both tabs.',
         'operands':['shell_tabs','pin_hole_low','pin_hole_high']},
        {'id':'pin','op':'cylinder','function_id':'F2_guide_button',
         'reason':'Ø2 h7 steel dowel (purchased): slip in the lower tab, pressed into a blind reamed hole in the upper tab whose floor is the depth stop.',
         'radius_mm':p['pin_radius_mm'],'height_mm':pin_z1-pin_z0,'origin_mm':[hx,hy,pin_z0],'axis':[0.,0.,1.]},
        {'id':'spring','op':'cylinder','function_id':'F4_restore_button',
         'reason':'Return spring envelope (purchased, placeholder): from the plug to the web face, preloading the web onto the rest block.',
         'radius_mm':p['spring_radius_mm'],'height_mm':pocket+gin,'origin_mm':[in_face-pocket,spring_y,spring_z],'axis':[1.,0.,0.]},
        {'id':'plug','op':'cylinder','function_id':'F4_restore_button',
         'reason':'Purchased Ø1.6 steel dowel used as the plug, pressed into the pocket reamed to 1.58 mm; seated flush with the pocket mouth.',
         'radius_mm':p['plug_radius_mm'],'height_mm':plug,'origin_mm':[in_face-pocket-plug,spring_y,spring_z],'axis':[1.,0.,0.]},
        _box('switch_housing','F3_actuate_switch','ASSUMED switch housing envelope (placeholder, not measured).',
             [px0-1.5,housing_top-4.,pz0-1.],[px1+1.5,housing_top,pz1+1.]),
        _box('switch_stem','F3_actuate_switch','ASSUMED switch stem (placeholder).',
             [px0+.5,housing_top,pz0+1.],[px1-.5,stem_top,pz1-1.]),
    ]
    axis={'axis_origin_mm':[hx,hy,0.],'axis_direction':[0.,0.,1.]}
    sp=a['stop_play']
    return {
        'title':'Side button improvement trial, revision 6 (process-defined fits and faces, deeper link, skin-safe barrel)',
        'original_request':request,
        'design_parameters':{k:float(v) for k,v in p.items()},
        'parameter_basis':{k:'Proposal for this prototype revision; not measured from a real mouse, switch or PCB.' for k in p},
        'functions':{
            'F1_transmit_force':'Transmit thumb force from the side skin (unchanged except the running gap) into the button.',
            'F2_guide_button':'Guide the button on one fixed hinge axis and hold its rest pose on the rest block.',
            'F3_actuate_switch':'Move the plunger onto the switch stem through its operating travel.',
            'F4_restore_button':'Return the button to its rest block with a compression spring (placeholder envelope).',
            'F5_limit_overtravel':'Stop the button at a hard stop before the switch housing is reached.',
            'F6_connect_shell':'Carry the hinge in the shell; the outer surface changes only by the running gap around the button.'},
        'protected_constraints':['Outer shell skin is not reshaped except the 0.4 mm running gap around the button, which awaits owner acceptance; the button face is the removed skin piece.'],
        'design_basis':{'kind':'first_principles',
                        'summary':'Pin-hinged flush side button; far slot stops on a full-height web; spring-preloaded rest; centred plunger on an assumed switch.',
                        'assumptions':['Switch housing, stem position and operating travel are placeholders, not a datasheet.',
                                       'Return spring: Ø1.5 compression spring, rate and preload not selected (placeholder envelope).',
                                       'Ø2 h7 steel dowel; button bore reamed to 2.05 mm (0.025 mm radial play); lower tab hole 2.02 mm clearance; upper tab hole reamed to 1.98 mm for a press fit, no adhesive.',
                                       'FDM layer height 0.2 mm; gaps and faces lie on that grid (bed z 0 for the shell, z 10.0 for the button).',
                                       'Shell support plan: printed rim-down with tree supports under the curved window lintel (supported, not bridged), the tab undersides and the cavity roof.',
                                       'Finishing: the upper-tab underside and lower-tab top are sanded to an 8.0 mm gauge block (barrel 7.6 mm + 0.2 mm each side); dowel holes and the plug pocket are reamed after printing.',
                                       'Calibration: after assembly the rest face of the outward block is sanded until a 0.20 mm feeler fits between plunger and stem (rest free play), which absorbs printed error of the rest face.',
                                       'Pressing intent: lower force over the front half of the face (rigid factor 17/(x+15) at most 1 for x of 2 mm or more), at the cost of the hinge-side end; the return spring adds to thumb force.',
                                       'Assembly order: button in from below and slid onto the rest block, dowel pressed up from below into the upper tab, spring and plug into the through pocket, then switch/PCB.',
                                       'FDM prototype: shell printed rim-down; button printed on its single bed plane (z = window bottom) with the bore vertical.']},
        'verification_plan':['Single solids, volume agreement, automatic pair overlap and bounds.',
                             'Rest band: outward motion is blocked within the hinge-play angle at every play offset (flushness bound).',
                             'Free play: no stem contact within the hinge-play angle inward of rest at every play offset.',
                             'Actuation: stem contact by the free-play angle at every play offset.',
                             'Overtravel: the hard stop blocks motion by the stop angle plus the play angle at every play offset, and the housing stays clear up to that angle.',
                             'Nothing in the shell is touched before the nominal stop angle at the nominal axis.',
                             'Assembly path (in from below, slide onto the rest block) and dowel path are clear of the shell.',
                             'Sampled printed wall thickness of shell and button.'],
        'operations':ops,
        'outputs':[{'part_id':'shell','node':'shell_part','manufacturing_process':'FDM, 0.2 mm layers, rim down, supports per design basis; parameters not qualified'},
                   {'part_id':'button','node':'button','manufacturing_process':'FDM, 0.2 mm layers, bed plane z=10.0, bore vertical; parameters not qualified'},
                   {'part_id':'hinge_pin','node':'pin','manufacturing_process':'Purchased Ø2 h7 steel dowel'},
                   {'part_id':'return_spring','node':'spring','manufacturing_process':'Purchased compression spring, rate not selected (envelope only)'},
                   {'part_id':'spring_plug','node':'plug','manufacturing_process':'Purchased Ø1.6 steel dowel used as plug'},
                   {'part_id':'switch_housing','node':'switch_housing','manufacturing_process':'Placeholder envelope of an unspecified switch, not a part'},
                   {'part_id':'switch_stem','node':'switch_stem','manufacturing_process':'Placeholder envelope of an unspecified switch, not a part'}],
        'dimension_checks':[
            {'id':'shell-length','part':'shell','kind':'bbox','axis':'x','nominal_mm':120.,'tolerance_mm':.5},
            {'id':'shell-height','part':'shell','kind':'bbox','axis':'z','nominal_mm':34.,'tolerance_mm':1e-3}],
        'clearance_checks':[
            {'id':'rest-pin-in-bore','part_a':'button','part_b':'hinge_pin','min_mm':p['barrel_inner_radius_mm']-p['pin_radius_mm']-1e-3},
            {'id':'rest-button-housing','part_a':'button','part_b':'switch_housing','min_mm':.5}],
        'motion_checks':[
            {'id':'button-insertion-slide','moving_part':'button','obstacles':['shell'],
             # Sample budgets keep the whole build inside the 300 s worker limit;
             # sliding contact cannot be certified, so these are sampled verdicts.
             'translation_end_mm':[0.,-p['insertion_slide_mm'],0.],'samples':9,'max_samples':9,'min_mm':0.},
            {'id':'button-insertion-drop','moving_part':'button','obstacles':['shell'],
             'start_translation_mm':[0.,-p['insertion_slide_mm'],0.],
             'translation_end_mm':[0.,0.,-p['insertion_drop_mm']],'samples':5,'max_samples':5,'min_mm':.1},
            {'id':'pin-insertion-path','moving_part':'hinge_pin','obstacles':['shell'],
             # Leg after the dowel has left its press fit in the upper tab.
             'start_translation_mm':[0.,0.,-(p['upper_hole_depth_mm']+.1)],
             'translation_end_mm':[0.,0.,-(pin_z1+1.-p['upper_hole_depth_mm'])],'samples':9,'max_samples':17,'min_mm':.001},
            # Spring and plug are fitted after the button: their paths out of the pocket must be clear.
            {'id':'plug-insertion-path','moving_part':'spring_plug','obstacles':['shell'],
             'start_translation_mm':[-(plug+.1),0.,0.],'translation_end_mm':[-8.,0.,0.],'samples':5,'max_samples':9,'min_mm':.001},
            {'id':'spring-insertion-path','moving_part':'return_spring','obstacles':['shell'],
             'start_translation_mm':[0.,0.,0.],'translation_end_mm':[-(pocket+gin+plug+6.),0.,0.],'samples':5,'max_samples':9,'min_mm':.001}],
        'rotation_checks':[
            {'id':'rest-outward-blocked-within-play','moving_part':'button','obstacles':['shell'],**axis,'end_deg':a['rest_play']+.05,
             # Blocking is located by the end pose; three samples per offset bound the worker time.
             'expect':'blocked','samples':2,'max_samples':2,'axis_play_mm':play,'min_blocking_overlap_mm3':1e-5},
            {'id':'rest-band-stem-free','moving_part':'button','obstacles':['switch_stem'],**axis,'end_deg':-a['rest_play'],
             'samples':5,'max_samples':17,'min_mm':.05,'axis_play_mm':play},
            {'id':'stem-contact-by-free-play','moving_part':'button','obstacles':['switch_stem'],**axis,'end_deg':a['contact'],
             'expect':'blocked','samples':3,'max_samples':3,'axis_play_mm':play,'min_blocking_overlap_mm3':1e-4},
            {'id':'housing-clear-past-stop','moving_part':'button','obstacles':['switch_housing'],**axis,'end_deg':a['stop']-sp,
             'samples':5,'max_samples':33,'min_mm':.2,'axis_play_mm':play},
            # Starts past the rest contact, so only the hard stop can produce the blocking overlap.
            {'id':'hard-stop-blocks-within-play','moving_part':'button','obstacles':['shell'],**axis,'start_deg':-1.,
             'end_deg':a['stop']-sp-.05,'expect':'blocked','samples':2,'max_samples':2,'axis_play_mm':play,'min_blocking_overlap_mm3':1e-4},
            {'id':'shell-clear-until-stop','moving_part':'button','obstacles':['shell'],**axis,'end_deg':a['stop'],
             'samples':5,'max_samples':5,'min_mm':0.,'end_max_distance_mm':.02},
            # Full axial rise (barrel end on the upper tab) with the hinge play in all eight directions,
            # starting 0.5 deg in from rest so the rest contact is open: nothing may overlap the shell,
            # i.e. the upper tab, not the inner skin, takes the rise.
            {'id':'rise-with-play-clear-of-skin','moving_part':'button','obstacles':['shell'],**axis,
             'start_translation_mm':[0.,0.,ag-.005],'start_deg':-.5,'end_deg':-.6,'samples':2,'max_samples':2,'min_mm':0.,
             'axis_play_mm':play},
            # Pin tilt (bore clearance over bore length) about the vertical-plane axis through the barrel,
            # combined with axial play: the face ends must stay off the window rim.
            {'id':'tilt-down-with-axial-drop','moving_part':'button','obstacles':['shell'],
             'axis_origin_mm':[hx,hy,bzm],'axis_direction':[0.,1.,0.],'start_translation_mm':[-play,0.,-tilt_drop],
             'end_deg':tilt,'samples':3,'max_samples':3,'min_mm':0.},
            {'id':'tilt-up-with-axial-rise','moving_part':'button','obstacles':['shell'],
             'axis_origin_mm':[hx,hy,bzm],'axis_direction':[0.,1.,0.],'start_translation_mm':[-play,0.,tilt_drop],
             'end_deg':-tilt,'samples':3,'max_samples':3,'min_mm':0.}],
        'press_fits':[
            {'id':'dowel-in-upper-tab','part_a':'hinge_pin','part_b':'shell','min_overlap_mm3':.06,'max_overlap_mm3':.18,
             'basis':'0.01 mm radial interference over the 1.8 mm blind hole: about 0.11 mm3 of rigid overlap.'},
            {'id':'plug-in-pocket','part_a':'spring_plug','part_b':'shell','min_overlap_mm3':.04,'max_overlap_mm3':.12,
             'basis':'Ø1.6 steel dowel in a pocket reamed to 1.58 mm: 0.01 mm radial interference over 1.5 mm, about 0.076 mm3.'}],
        'wall_checks':[
            {'id':'shell-printed-wall','part':'shell','min_mm':p['min_printed_wall_mm'],'samples_per_face':10},
            {'id':'button-printed-wall','part':'button','min_mm':p['min_printed_wall_mm'],'samples_per_face':10}],
        'unverified_requirements':[
            '押しやすさ（押下力・ストローク感・クリック感）は実機試験していない。押す位置による力の倍率は剛体計算の目安にすぎない。',
            'Switch housing, stem position, operating force and travel are assumed placeholders, not a measured switch.',
            'PCB position and the real mouse shell were not measured; this is a stand-in shell.',
            'Return spring rate, preload and its effect on thumb force are not selected or verified; it is an envelope only.',
            'Dowel press fit in line-reamed tab holes, reamed bore size, print tolerance, link and tab stiffness and wear are not qualified.',
            'Outer-form changes awaiting owner acceptance: the 0.4 mm running gap removes about 38 mm3 of skin, and within hinge play the face may stand proud by up to about 0.14 mm at the free edge.',
            'Rigid face travel at the press angle (designer estimate): about 0.21 mm at x=-10, 0.70 mm at x=2 and 1.19 mm at x=14; the return spring force adds to thumb force and is not selected.',
            'Switch window: the stem top must sit within -0.15/+0.05 mm in Y of the modeled position relative to the dowel (rest-band margin and stem travel at the hard stop); the owner PCB must hold it after the rest-face calibration (no datum modeled).',
            'Press fits are verified only as rigid overlap bands; retention force and printed hole accuracy are not verified.',
            'Skin and stiffener bending under a firm press beyond the hard stop is not analysed (no FEA).',
            'Hinge play is covered at eight radial offsets; pin tilt is checked about one horizontal axis with axial play, not every combination.',
            'The switch is located by the owner PCB; its position relative to the hinge must stay within the measured rest and housing margins (no PCB datum modeled).',
            '押す位置による押下力の目安（剛体）: 力倍率 = 17 / (x+15)。ヒンジ側端 x=-10 で約3.4倍、中央 x=2 で1.0倍、先端 x=14 で約0.59倍。設計者の仮説であり目標値ではない。',
            'Wall checks are sampled minima of the stated parts, not a proof of minimum wall or of strength.'],
    }


# ---------------------------------------------------------------------------
# Revision 7: repairs the revision-6 round-1 major findings.
# - One-way, out-of-order rest calibration -> M2 grub screws as adjustable
#   rest and hard stops (two-way, set from outside the blocks after assembly).
# - Plug pocket could not be finished -> the spring is closed by an M2 grub
#   screw in a 1.6 mm tap hole (no reaming; also sets spring preload).
# - Far-edge running gap closed near the stop -> the far window edge is cut
#   normal to the hinge radius, so rotation slides along it.
# - Owner-facing selection limits for switch and spring are stated.
# Built by editing the revision-6 recipe so every unchanged feature is shared.
# ---------------------------------------------------------------------------
P7=dict(P6)
P7.pop('plug_radius_mm',None);P7.pop('plug_length_mm',None)
P7.update({'screw_radius_mm':1.,'tap_radius_mm':.8,'screw_y_mm':9.5,'stop_screw_z_mm':15.2,
           'block_in_z_max_mm':17.4,'block_recess_mm':.3,'rest_recess_mm':.5,'rest_screw_length_mm':3.,
           'spring_screw_length_mm':1.5,'far_edge_ref_y_mm':29.5})


def _screw_radius7(p):
    return p['hinge_y_mm']-p['screw_y_mm']


def angles_v7(p=P7):
    a=angles_v5(p)
    # The screw tips touch the web at their outer edge farthest from (stop) or
    # nearest to (rest, conservative) the axis.
    a['stop_play']=_play_angle_deg(p,_screw_radius7(p)+p['screw_radius_mm'])
    a['rest_play']=_play_angle_deg(p,_screw_radius7(p)-p['screw_radius_mm'])
    return a


def stop_screw_tip_x7(p=P7):
    """Stop-screw tip X so the web's -X face meets it at the nominal stop angle (contact radius = screw radius)."""
    # First contact is the edge of the tip disk farthest from the axis.
    # Exact: the rotated web face (local x=-w) is a line; take its X where it
    # crosses the disk edge's Y, then step back 0.002 mm for rigid non-penetration.
    phi=math.radians(angles_v7(p)['stop']);w=p['arm_half_width_mm'];hx,hy=p['hinge_x_mm'],p['hinge_y_mm']
    y_edge=p['screw_y_mm']-p['screw_radius_mm']
    local_y=(y_edge-hy+w*math.sin(phi))/math.cos(phi)
    return hx-w*math.cos(phi)-local_y*math.sin(phi)-.002


def _far_edge_points(p,offset):
    """Far window edge normal to the hinge radius at the reference point, shifted outward by offset."""
    hx,hy=p['hinge_x_mm'],p['hinge_y_mm'];x0,y0=p['window_x_max_mm'],p['far_edge_ref_y_mm']
    n=[x0-hx,y0-hy];length=math.hypot(*n);n=[n[0]/length,n[1]/length];t=[-n[1],n[0]]
    x0+=offset*n[0];y0+=offset*n[1]
    return [[x0+(y-y0)/t[1]*t[0],y] for y in (20.,40.)]


def side_button_recipe_v7(request=REQUEST,p=None):
    p=dict(P7 if p is None else p)
    base=dict(P6);base.update({k:v for k,v in p.items() if k in P6})
    base['plug_radius_mm']=P6['plug_radius_mm'];base['plug_length_mm']=P6['plug_length_mm']
    r=side_button_recipe_v6(request,base)
    ops={o['id']:o for o in r['operations']};order=[o['id'] for o in r['operations']]
    hx,hy,w=p['hinge_x_mm'],p['hinge_y_mm'],p['arm_half_width_mm']
    zl,zh,g,wl=p['window_z_min_mm'],p['window_z_max_mm'],p['window_gap_mm'],p['window_x_min_mm']
    tab_low_top=zl-p['axial_gap_mm'];by0,by1=p['block_y_min_mm'],p['block_y_max_mm']
    sy,tap,sr=p['screw_y_mm'],p['tap_radius_mm'],p['screw_radius_mm']
    spring_z=p.get('spring_z_mm',(tab_low_top+p['block_z_max_mm'])/2);stop_z=p['stop_screw_z_mm']
    # Revision 8 may place the spring beside, not under, the stop screw.
    spring_y=p.get('spring_y_mm',sy);rest_z=p.get('rest_screw_z_mm',spring_z)
    tip=stop_screw_tip_x7(p);recess=p['block_recess_mm'];bw=p['inward_block_width_mm']
    in_x1=tip-recess;in_x0=in_x1-bw
    web_out=hx+w;out_x0=web_out+p['rest_recess_mm'];out_x1=p['tab_x_max_mm']
    a=angles_v7(p);play=p['hinge_radial_play_mm']
    def cyl_x(node_id,function_id,reason,radius,x0,length,y,z):
        return {'id':node_id,'op':'cylinder','function_id':function_id,'reason':reason,'radius_mm':radius,
                'height_mm':length,'origin_mm':[x0,y,z],'axis':[1.,0.,0.]}
    far=_far_edge_points(p,0.);far_gap=_far_edge_points(p,g)
    ops['window']={'id':'window','op':'polygon_extrusion','function_id':'F1_transmit_force',
                   'reason':'Button skin region; the far edge is cut normal to the hinge radius so pressing slides along it.',
                   'points_mm':[[wl,20.],far[0],far[1],[wl,40.]],'height_mm':zh-zl,'origin_mm':[0.,0.,zl]}
    ops['window_gap']={'id':'window_gap','op':'polygon_extrusion','function_id':'F6_connect_shell',
                       'reason':'Window enlarged by the running gap around the button, far edge parallel to the button edge.',
                       'points_mm':[[wl-g,20.],far_gap[0],far_gap[1],[wl-g,40.]],'height_mm':zh-zl+2*g,'origin_mm':[0.,0.,zl-g]}
    new={
        'block_in_box':_box('block_in_box','F5_limit_overtravel','Inward block carrying the stop screw and the spring pocket.',
                            [in_x0,by0,tab_low_top],[in_x1,by1,p['block_in_z_max_mm']]),
        'spring_pocket':cyl_x('spring_pocket','F4_restore_button','Tap hole for the spring and its closing grub screw.',
                              tap,in_x0-.5,bw+1.,spring_y,spring_z),
        'stop_hole':cyl_x('stop_hole','F5_limit_overtravel','Tap hole for the adjustable hard-stop screw.',tap,in_x0-.5,bw+1.,sy,stop_z),
        'block_in':{'id':'block_in','op':'difference','function_id':'F5_limit_overtravel',
                    'reason':'Inward block with spring pocket and stop-screw hole.','operands':['block_in_box','spring_pocket','stop_hole']},
        'block_out_box':_box('block_out_box','F2_guide_button','Outward block carrying the adjustable rest screw.',
                             [out_x0,by0,tab_low_top],[out_x1,by1,p['block_z_max_mm']]),
        'rest_hole':cyl_x('rest_hole','F2_guide_button','Tap hole for the adjustable rest screw.',tap,out_x0-.5,out_x1-out_x0+1.,sy,rest_z),
        'block_out':{'id':'block_out','op':'difference','function_id':'F2_guide_button',
                     'reason':'Outward block with the rest-screw hole.','operands':['block_out_box','rest_hole']},
        'spring':cyl_x('spring','F4_restore_button',
                       'Return spring envelope (purchased): from the closing screw to the web face, preloading the web onto the rest screw.',
                       p['spring_radius_mm'],in_x0+p['spring_screw_length_mm'],web_out-2*w-(in_x0+p['spring_screw_length_mm']),spring_y,spring_z),
        'spring_screw':cyl_x('spring_screw','F4_restore_button','M2 grub screw closing the spring pocket; its depth sets the preload.',
                             sr,in_x0,p['spring_screw_length_mm'],spring_y,spring_z),
        'stop_screw':cyl_x('stop_screw','F5_limit_overtravel','M2 grub screw whose tip is the adjustable hard stop.',
                           sr,in_x0,tip-in_x0,sy,stop_z),
        'rest_screw':cyl_x('rest_screw','F2_guide_button','M2 grub screw whose tip is the adjustable rest stop (sets flushness).',
                           sr,web_out,p['rest_screw_length_mm'],sy,rest_z),
    }
    out_order=[]
    for node in order:
        if node in ('block_in_box','spring_pocket','block_in'):
            if node=='block_in_box':out_order+=['block_in_box','spring_pocket','stop_hole','block_in']
            continue
        if node=='block_out':out_order+=['block_out_box','rest_hole','block_out'];continue
        if node=='plug':out_order+=['spring_screw','stop_screw','rest_screw'];continue
        out_order.append(node)
    ops.update(new);ops.pop('plug',None)
    r['operations']=[ops[n] for n in out_order]
    r['title']='Side button improvement trial, revision 7 (screw-adjusted stops, radial far edge)'
    r['design_parameters']={k:float(v) for k,v in p.items()}
    r['parameter_basis']={k:'Proposal for this prototype revision; not measured from a real mouse, switch or PCB.' for k in p}
    r['outputs']=[o for o in r['outputs'] if o['part_id']!='spring_plug']+[
        {'part_id':'spring_screw','node':'spring_screw','manufacturing_process':'Purchased M2 x 1.5 grub screw, self-tapped into a 1.6 mm printed hole'},
        {'part_id':'stop_screw','node':'stop_screw','manufacturing_process':'Purchased M2 x 4 grub screw, self-tapped into a 1.6 mm printed hole'},
        {'part_id':'rest_screw','node':'rest_screw','manufacturing_process':'Purchased M2 x 3 grub screw, self-tapped into a 1.6 mm printed hole'}]
    thread=lambda length:math.pi*(sr**2-tap**2)*length
    r['press_fits']=[f for f in r['press_fits'] if f['id']!='plug-in-pocket']+[
        {'id':'spring-screw-thread','part_a':'spring_screw','part_b':'shell','min_overlap_mm3':.7*thread(p['spring_screw_length_mm']),
         'max_overlap_mm3':1.3*thread(p['spring_screw_length_mm']),'basis':'M2 thread major diameter engaged in a 1.6 mm tap hole, modeled as an interference annulus.'},
        {'id':'stop-screw-thread','part_a':'stop_screw','part_b':'shell','min_overlap_mm3':.7*thread(bw),'max_overlap_mm3':1.3*thread(bw),
         'basis':'M2 thread engaged over the inward block width, modeled as an interference annulus.'},
        {'id':'rest-screw-thread','part_a':'rest_screw','part_b':'shell','min_overlap_mm3':.7*thread(out_x1-out_x0),
         'max_overlap_mm3':1.3*thread(out_x1-out_x0),'basis':'M2 thread engaged over the outward block width, modeled as an interference annulus.'}]
    axis={'axis_origin_mm':[hx,hy,0.],'axis_direction':[0.,0.,1.]}
    motion=[m for m in r['motion_checks'] if m['id'] not in ('plug-insertion-path','spring-insertion-path')]
    motion+=[
        {'id':'spring-screw-path','moving_part':'spring_screw','obstacles':['shell'],'start_translation_mm':[-(p['spring_screw_length_mm']+.1),0.,0.],
         'translation_end_mm':[-6.,0.,0.],'samples':5,'max_samples':5,'min_mm':.001},
        {'id':'spring-path','moving_part':'return_spring','obstacles':['shell'],'start_translation_mm':[-(p['spring_screw_length_mm']+.1),0.,0.],
         'translation_end_mm':[-8.,0.,0.],'samples':5,'max_samples':5,'min_mm':.001},
        {'id':'stop-screw-path','moving_part':'stop_screw','obstacles':['shell'],'start_translation_mm':[-(tip-in_x0+.1),0.,0.],
         'translation_end_mm':[-6.,0.,0.],'samples':5,'max_samples':5,'min_mm':.001},
        {'id':'rest-screw-path','moving_part':'rest_screw','obstacles':['shell'],'start_translation_mm':[out_x1-web_out+.1,0.,0.],
         'translation_end_mm':[6.,0.,0.],'samples':5,'max_samples':5,'min_mm':.001}]
    r['motion_checks']=motion
    rot={c['id']:c for c in r['rotation_checks']}
    rot['rest-outward-blocked-within-play'].update(obstacles=['rest_screw'],end_deg=a['rest_play']+.05,samples=3,max_samples=3)
    rot['rest-band-stem-free']['end_deg']=-a['rest_play']
    rot['housing-clear-past-stop']['end_deg']=a['stop']-a['stop_play']
    rot['hard-stop-blocks-within-play'].update(obstacles=['stop_screw'],end_deg=a['stop']-a['stop_play']-.05,samples=3,max_samples=3)
    rot.pop('shell-clear-until-stop')
    rot['stop-screw-reached']={'id':'stop-screw-reached','moving_part':'button','obstacles':['stop_screw'],**axis,'end_deg':a['stop'],
                               'samples':5,'max_samples':5,'min_mm':0.,'end_max_distance_mm':.02}
    rot['window-gap-kept-until-stop']={'id':'window-gap-kept-until-stop','moving_part':'button','obstacles':['shell'],**axis,
                                       'end_deg':a['stop'],'samples':3,'max_samples':3,'min_mm':.15,'axis_play_mm':play}
    r['rotation_checks']=list(rot.values())
    basis=r['design_basis']
    basis['summary']='Pin-hinged flush side button; screw-adjusted rest and hard stops on a full-height web; spring-preloaded rest; centred plunger on an assumed switch.'
    basis['assumptions']=[x for x in basis['assumptions'] if not x.startswith('Calibration:')]+[
        'Adjustment: after assembly the rest screw is set until the face is flush, then the stop screw until the switch clicks with about 0.2 mm overtravel; both are set from outside the blocks with a 0.9 mm hex key, before the PCB closes the bottom.']
    r['verification_plan']=[x for x in r['verification_plan'] if 'Nothing in the shell' not in x]+[
        'Rest and hard stops are the screw tips; the window running gap stays at least 0.2 mm up to the stop at every play offset.']
    r['unverified_requirements']=[x for x in r['unverified_requirements'] if not x.startswith('Switch window')]+[
        'Switch selection: operating point no deeper than about 0.55 mm and at least about 0.84 mm total travel before bottoming, so the hard stop, not the switch, ends the stroke; the stem must sit within -0.15/+0.05 mm in Y of the modeled position before screw adjustment (assumed placeholder overtravel 0.8 mm).',
        'Return spring selection: solid length below about 2.0 mm (it shortens from about 2.9 mm to about 2.0 mm at the stop); its preload adds to thumb force.',
        'Self-tapped M2 threads in printed plastic: holding torque and wear under repeated hard-stop loads are not qualified.']
    return r


# ---------------------------------------------------------------------------
# Revision 8: repairs the revision-7 round-1 major findings.
# - Stop raised on a free-standing post -> stop screw back at z 11.9 beside
#   the spring (side by side in Y), a 4 mm lower tab, 4 mm-thick inward block.
# - Printed threads unlocked -> square M2 jam nuts on the outer block faces
#   lock the stop and rest screws (fitted after the button).
# - Stop set "until the switch clicks" before the PCB exists -> the stop is
#   set with a 1.5 mm depth gauge at the face's front edge; the click is only
#   confirmed after the PCB is fitted.
# - Switch travel limit unrecorded -> the placeholder housing sits at the
#   stem's assumed bottoming depth (0.95 mm), and the housing check (with
#   hinge play, past the stop) proves the push stays at least 0.05 mm short.
# - Contract text: screw/nut assembly order, spring lengths, no plug.
# ---------------------------------------------------------------------------
P8=dict(P7)
P8.update({'screw_y_mm':9.3,'spring_y_mm':12.4,'stop_screw_z_mm':11.9,'spring_z_mm':11.9,'rest_screw_z_mm':11.9,
           'block_y_min_mm':7.3,'block_y_max_mm':14.4,'block_in_z_max_mm':14.,'inward_block_width_mm':4.,
           'tab_thickness_mm':4.,'nut_size_mm':4.,'nut_thickness_mm':1.6,'rest_screw_length_mm':4.,
           'housing_margin_after_operating_mm':.45,'depth_gauge_mm':1.5})


def angles_v8(p=P8):
    return angles_v7(p)


def front_edge_travel_at_stop_mm(p=P8):
    """Inward travel of the face's front edge at the nominal stop angle (depth-gauge setting)."""
    r=p['window_x_max_mm']-p['hinge_x_mm']
    return r*math.sin(math.radians(-angles_v8(p)['stop']))


def side_button_recipe_v8(request=REQUEST,p=None):
    p=dict(P8 if p is None else p)
    r=side_button_recipe_v7(request,p)
    ops={o['id']:o for o in r['operations']}
    hx,hy,w=p['hinge_x_mm'],p['hinge_y_mm'],p['arm_half_width_mm']
    sy,z=p['screw_y_mm'],p['stop_screw_z_mm'];tap,sr=p['tap_radius_mm'],p['screw_radius_mm']
    ns,nt=p['nut_size_mm'],p['nut_thickness_mm']
    in_x0=ops['block_in_box']['center_mm'][0]-ops['block_in_box']['size_mm'][0]/2
    out_x1=p['tab_x_max_mm'];tip=stop_screw_tip_x7(p);web_out=hx+w
    def nut(node_id,function_id,reason,x0):
        return [_box(node_id+'_body',function_id,reason,[x0,sy-ns/2,z-ns/2],[x0+nt,sy+ns/2,z+ns/2]),
                {'id':node_id+'_hole','op':'cylinder','function_id':function_id,'reason':'Nut thread minor bore.',
                 'radius_mm':tap,'height_mm':nt+1.,'origin_mm':[x0-.5,sy,z],'axis':[1.,0.,0.]},
                {'id':node_id,'op':'difference','function_id':function_id,'reason':reason,
                 'operands':[node_id+'_body',node_id+'_hole']}]
    stop_len=tip-(in_x0-nt-.5)
    ops['stop_screw'].update(height_mm=stop_len,origin_mm=[tip-stop_len,sy,z],
                             reason='M2 x 6 grub screw whose tip is the adjustable hard stop, locked by a jam nut.')
    ops['rest_screw'].update(reason='M2 x 4 grub screw whose tip is the adjustable rest stop (sets flushness), locked by a jam nut.')
    order=[o['id'] for o in r['operations']]
    extra=nut('stop_nut','F5_limit_overtravel','Square M2 jam nut locking the stop screw on the outer face of the inward block.',in_x0-nt)
    extra+=nut('rest_nut','F2_guide_button','Square M2 jam nut locking the rest screw on the outer face of the outward block.',out_x1)
    for o in extra:ops[o['id']]=o
    order+= [o['id'] for o in extra]
    r['operations']=[ops[n] for n in order]
    ops_skin=ops['skin_piece'];ops_skin['reason']='Button face is the removed piece of the skin; only the running gap around it is lost.'
    r['title']='Side button improvement trial, revision 8 (low stop with jam-nut screws, gauge-set stroke)'
    r['design_parameters']={k:float(v) for k,v in p.items()}
    r['parameter_basis']={k:'Proposal for this prototype revision; not measured from a real mouse, switch or PCB.' for k in p}
    for o in r['outputs']:
        if o['part_id']=='stop_screw':o['manufacturing_process']='Purchased M2 x 6 grub screw, flat point, self-tapped into a 1.6 mm printed hole'
        if o['part_id']=='rest_screw':o['manufacturing_process']='Purchased M2 x 4 grub screw, flat point, self-tapped into a 1.6 mm printed hole'
    r['outputs']+=[{'part_id':'stop_nut','node':'stop_nut','manufacturing_process':'Purchased M2 square nut (jam nut)'},
                   {'part_id':'rest_nut','node':'rest_nut','manufacturing_process':'Purchased M2 square nut (jam nut)'}]
    thread=math.pi*(sr**2-tap**2)*nt
    r['press_fits']=[f for f in r['press_fits'] if f['id']!='stop-screw-thread']+[
        {'id':'stop-screw-thread','part_a':'stop_screw','part_b':'shell','min_overlap_mm3':.7*math.pi*(sr**2-tap**2)*p['inward_block_width_mm'],
         'max_overlap_mm3':1.3*math.pi*(sr**2-tap**2)*p['inward_block_width_mm'],'basis':'M2 thread engaged over the inward block width, modeled as an interference annulus.'},
        {'id':'stop-nut-thread','part_a':'stop_screw','part_b':'stop_nut','min_overlap_mm3':.7*thread,'max_overlap_mm3':1.3*thread,
         'basis':'M2 thread engaged in the square jam nut, modeled as an interference annulus.'},
        {'id':'rest-nut-thread','part_a':'rest_screw','part_b':'rest_nut','min_overlap_mm3':.7*thread,'max_overlap_mm3':1.3*thread,
         'basis':'M2 thread engaged in the square jam nut, modeled as an interference annulus.'}]
    motion={m['id']:m for m in r['motion_checks']}
    motion['stop-screw-path'].update(start_translation_mm=[-(stop_len+.1),0.,0.])
    motion['button-insertion-slide'].update(samples=7,max_samples=7)
    motion['rest-screw-path'].update(start_translation_mm=[out_x1+nt-web_out+.1,0.,0.])
    motion['stop-nut-path']={'id':'stop-nut-path','moving_part':'stop_nut','obstacles':['shell'],'start_translation_mm':[-.1,0.,0.],
                             'translation_end_mm':[-6.,0.,0.],'samples':5,'max_samples':5,'min_mm':.05}
    motion['rest-nut-path']={'id':'rest-nut-path','moving_part':'rest_nut','obstacles':['shell'],'start_translation_mm':[.1,0.,0.],
                             'translation_end_mm':[6.,0.,0.],'samples':5,'max_samples':5,'min_mm':.05}
    r['motion_checks']=list(motion.values())
    rot={c['id']:c for c in r['rotation_checks']}
    a=angles_v8(p)
    rot['housing-clear-past-stop'].update(end_deg=a['stop']-a['stop_play']-.05,min_mm=.05)
    gap=rot.pop('window-gap-kept-until-stop')
    gap['id']='nearest-shell-gap-until-stop'
    # End and mid poses carry the information; the rest pose is covered by the rest checks.
    gap.update(samples=2,max_samples=2)
    rot['nearest-shell-gap-until-stop']=gap
    r['rotation_checks']=list(rot.values())
    travel=front_edge_travel_at_stop_mm(p)
    spring_rest=ops['spring']['height_mm'];spring_stop=spring_rest-(hy-p['spring_y_mm'])*math.sin(math.radians(-a['stop']))
    basis=r['design_basis']
    basis['assumptions']=[x for x in basis['assumptions'] if not x.startswith(('Finishing:','Assembly order:','Adjustment:'))]+[
        'Finishing: the upper-tab underside and lower-tab top are sanded to an 8.0 mm gauge block (barrel 7.6 mm + 0.2 mm each side); dowel holes are reamed (lower 2.02 mm clearance, upper 1.98 mm blind press fit); screw holes stay as printed 1.6 mm tap holes.',
        'Assembly order: button in from below and slid into the slot; dowel pressed up into the upper tab; spring then spring screw into the inward block; stop screw and its jam nut; rest screw and its jam nut; adjust; then switch/PCB.',
        f'Adjustment (no switch needed): turn the rest screw until the face is flush, lock its nut; press the face and turn the stop screw until a {p["depth_gauge_mm"]:.1f} mm depth gauge at the front edge just touches at the stop (nominal front-edge travel {travel:.2f} mm), lock its nut; then fit the PCB and confirm the click.']
    r['verification_plan']=[x for x in r['verification_plan'] if 'window running gap' not in x]+[
        'Stops are the screw tips; nearest shell feature stays at least 0.15 mm away up to the stop at every play offset (this includes the 0.2 mm axial tab gap, so it bounds the window gap from below).',
        'Placeholder housing at the assumed stem bottoming depth: the plunger stays at least 0.05 mm short of it past the stop at every play offset.']
    r['unverified_requirements']=[x for x in r['unverified_requirements'] if not x.startswith(('Switch selection','Return spring selection'))]+[
        'Switch selection: operating point no deeper than about 0.55 mm and total travel to bottoming of at least 0.95 mm (the placeholder bottoming depth checked with hinge play); stem within -0.15/+0.05 mm in Y of the modeled position before adjustment.',
        f'Return spring selection: installed length about {spring_rest:.2f} mm, about {spring_stop:.2f} mm at the stop; solid length must be below that. Its preload adds to thumb force and is set by the spring screw depth.']
    return r


# ---------------------------------------------------------------------------
# Revision 9: repairs the revision-8 round-1 major findings.
# - Stop jam nut could not turn: the lower tab overhung the inward block face
#   under the nut -> tab trimmed to the block face; both nuts are spun 90 deg
#   on their seats by a check.
# - Return spring dragging in a 0.05 mm bore clearance -> Ø1.2 spring in the
#   Ø1.6 bore (0.2 mm radial clearance), stated as a maximum spring OD.
# - Stop screw modeled at its bought length (M2 x 6); gauge reference and a
#   no-click recovery step are stated; contract numbers refreshed.
# ---------------------------------------------------------------------------
P9=dict(P8)
P9.update({'spring_radius_mm':.6,'stop_screw_bought_length_mm':6.})


def angles_v9(p=P9):
    return angles_v8(p)


def side_button_recipe_v9(request=REQUEST,p=None):
    p=dict(P9 if p is None else p)
    r=side_button_recipe_v8(request,p)
    ops={o['id']:o for o in r['operations']}
    in_x0=ops['block_in_box']['center_mm'][0]-ops['block_in_box']['size_mm'][0]/2
    tab=ops['tab_low_box'];lo=tab['center_mm'][0]-tab['size_mm'][0]/2;hi=tab['center_mm'][0]+tab['size_mm'][0]/2
    lo=in_x0  # end the tab at the inward block's outer face, under nothing but the block
    tab.update(size_mm=[hi-lo,tab['size_mm'][1],tab['size_mm'][2]],center_mm=[(hi+lo)/2,tab['center_mm'][1],tab['center_mm'][2]],
               reason='Lower tab: pin support and stop-slot base; ends at the inward block face so the jam nut can turn.')
    stop=ops['stop_screw'];tip=stop['origin_mm'][0]+stop['height_mm'];length=p['stop_screw_bought_length_mm']
    stop.update(height_mm=length,origin_mm=[tip-length,stop['origin_mm'][1],stop['origin_mm'][2]])
    r['title']='Side button improvement trial, revision 9 (turnable jam nuts, free-running spring)'
    r['design_parameters']={k:float(v) for k,v in p.items()}
    r['parameter_basis']={k:'Proposal for this prototype revision; not measured from a real mouse, switch or PCB.' for k in p}
    sy,z=p['screw_y_mm'],p['stop_screw_z_mm']
    rot={c['id']:c for c in r['rotation_checks']}
    for nut_id in ('stop_nut','rest_nut'):
        rot[nut_id+'-turns-on-seat']={'id':nut_id+'-turns-on-seat','moving_part':nut_id,'obstacles':['shell'],
                                      'axis_origin_mm':[0.,sy,z],'axis_direction':[1.,0.,0.],'end_deg':90.,
                                      'samples':3,'max_samples':3,'min_mm':0.}
    gap=rot['nearest-shell-gap-until-stop']
    # End past the deepest play-shifted stop contact, not at the nominal stop.
    gap['end_deg']=angles_v9(p)['stop']-angles_v9(p)['stop_play']
    r['rotation_checks']=list(rot.values())
    r['motion_checks']=[dict(m,start_translation_mm=[-(length+.1),0.,0.]) if m['id']=='stop-screw-path' else m for m in r['motion_checks']]
    r['verification_plan']=[x.replace('up to the stop at every play offset','at rest and at the stop at every play offset') for x in r['verification_plan']]+[
        'Both jam nuts can be turned a quarter turn while seated on their block faces.']
    basis=r['design_basis']
    basis['assumptions']=[x for x in basis['assumptions'] if not x.startswith('Adjustment')]+[
        'Adjustment (no switch needed): turn the rest screw until the face is flush with the skin beside the window front edge, lock its nut; press the face and turn the stop screw until a 1.53 mm depth gauge referenced on that skin just touches the face front edge at the stop (accept 1.48-1.58 mm), lock its nut; fit the PCB and confirm the click. If there is no click, back the stop screw out 1/8 turn (about 0.05 mm) at a time, at most 0.15 mm, keeping the housing margin.']
    r['unverified_requirements']=[x for x in r['unverified_requirements'] if not x.startswith(('Switch selection','Return spring selection','Outer-form changes'))]+[
        'Switch selection: operating point no deeper than 0.50 mm and total travel to bottoming of at least 0.95 mm; at the gauge setting the plunger pushes the stem about 0.68-0.70 mm, so the stem must sit within -0.15/+0.05 mm in Y of the modeled position.',
        f'Return spring selection: outside diameter at most 1.2 mm (0.2 mm radial clearance in the printed 1.6 mm bore); installed length about {ops["spring"]["height_mm"]:.2f} mm; solid length below the stop length. Its preload adds to thumb force and is set by the spring screw depth.',
        'Outer-form changes awaiting owner acceptance: the 0.4 mm running gap removes about 38 mm3 of skin; after flush adjustment hinge play lets the face stand proud by about 0.1 mm at the free edge.']
    return r


# ---------------------------------------------------------------------------
# Revision 10: repairs the revision-9 round-1 major findings.
# - Gauge value was the front edge's Y travel, not a depth read normal to the
#   skin -> the gauge reading is computed along the skin normal measured on
#   the revision-9 shell next to the window front edge, with a stated band.
# - The no-click recovery step (back the stop out up to 0.15 mm) went past the
#   checked housing range -> removed; a missing click now means the switch or
#   PCB is outside its selection band. The housing check ends at the deepest
#   pose the procedure accepts (band and hinge play), with margin.
# - Design-basis spring text matches the Ø1.2 spring; spring length at the
#   stop is restated; the stop nut must also turn past the spring screw.
# - Stop screw is an M2 x 8 so the adjustment has thread left behind the nut.
# ---------------------------------------------------------------------------
P10=dict(P9)
P10.update({'stop_screw_bought_length_mm':8.,'gauge_band_mm':.03,
            # Outward skin normal measured on the revision-9 shell STEP
            # at (14.6, 30.45, 12.26), beside the window front edge.
            'gauge_skin_normal_x':.1410,'gauge_skin_normal_y':.9739,'gauge_skin_normal_z':.1779,
            'gauge_check_margin_deg':.03})


def angles_v10(p=P10):
    return angles_v9(p)


def gauge_reading_mm(p=P10,angle_deg=None):
    """Depth of the face front edge below the adjacent skin, read normal to the skin, at a hinge angle."""
    a=math.radians(angles_v10(p)['stop'] if angle_deg is None else angle_deg)
    hx,hy=p['hinge_x_mm'],p['hinge_y_mm'];rx,ry=p['window_x_max_mm']-hx,p['far_edge_ref_y_mm']-hy
    dx=rx*math.cos(a)-ry*math.sin(a)-rx;dy=rx*math.sin(a)+ry*math.cos(a)-ry
    nx,ny,nz=p['gauge_skin_normal_x'],p['gauge_skin_normal_y'],p['gauge_skin_normal_z'];n=math.sqrt(nx*nx+ny*ny+nz*nz)
    return -(dx*nx+dy*ny)/n


def gauge_band_angle_deg(p=P10):
    """Hinge angle swept by the gauge acceptance band (reading per degree near the stop)."""
    s=angles_v10(p)['stop'];per_deg=gauge_reading_mm(p,s-.5)-gauge_reading_mm(p,s+.5)
    return p['gauge_band_mm']/per_deg


def deepest_accepted_angle_deg(p=P10):
    """Deepest hinge angle the adjustment procedure accepts: band, hinge play at the stop, plus a check margin."""
    a=angles_v10(p)
    return a['stop']-a['stop_play']-gauge_band_angle_deg(p)-p['gauge_check_margin_deg']


def stem_push_mm(p=P10,angle_deg=None):
    """Stem push at a hinge angle at the stem's far edge (deepest contact) minus the free play."""
    a=angles_v10(p)['stop'] if angle_deg is None else angle_deg
    lever=p['plunger_x_max_mm']-.5-p['hinge_x_mm']  # stem is 0.5 mm narrower than the plunger each side
    return lever*math.sin(math.radians(-a))-p['stem_free_play_mm']


def side_button_recipe_v10(request=REQUEST,p=None):
    p=dict(P10 if p is None else p)
    r=side_button_recipe_v9(request,p)
    ops={o['id']:o for o in r['operations']}
    stop=ops['stop_screw'];tip=stop['origin_mm'][0]+stop['height_mm'];length=p['stop_screw_bought_length_mm']
    stop.update(height_mm=length,origin_mm=[tip-length,stop['origin_mm'][1],stop['origin_mm'][2]],
                reason='M2 x 8 grub screw whose tip is the adjustable hard stop, locked by a jam nut; thread is left behind the nut for adjustment.')
    for o in r['outputs']:
        if o['part_id']=='stop_screw':o['manufacturing_process']='Purchased M2 x 8 grub screw, flat point, in a drilled 1.6 mm tap hole'
    r['title']='Side button improvement trial, revision 10 (skin-normal gauge setting, checked deepest pose)'
    r['design_parameters']={k:float(v) for k,v in p.items()}
    r['parameter_basis']={k:'Proposal for this prototype revision; not measured from a real mouse, switch or PCB.' for k in p}
    for k in ('gauge_skin_normal_x','gauge_skin_normal_y','gauge_skin_normal_z'):
        r['parameter_basis'][k]='Measured on the revision-9 shell STEP: outward skin normal at (14.6, 30.45, 12.26) beside the window front edge.'
    a=angles_v10(p);deep=deepest_accepted_angle_deg(p)
    rot={c['id']:c for c in r['rotation_checks']}
    rot['housing-clear-past-stop'].update(end_deg=deep)
    rot['stop_nut-turns-on-seat'].update(obstacles=['shell','spring_screw'],samples=7,max_samples=7)
    rot['rest_nut-turns-on-seat'].update(samples=7,max_samples=7)
    r['rotation_checks']=list(rot.values())
    r['motion_checks']=[dict(m,start_translation_mm=[-(length+.1),0.,0.]) if m['id']=='stop-screw-path' else m for m in r['motion_checks']]
    g=gauge_reading_mm(p);band=p['gauge_band_mm']
    spring=ops['spring']['height_mm'];spring_stop=spring-(p['hinge_y_mm']-p['spring_y_mm'])*math.sin(math.radians(-a['stop']))
    basis=r['design_basis']
    basis['assumptions']=[x for x in basis['assumptions'] if not x.startswith(('Return spring:','Adjustment','Finishing:','Assembly order:'))]+[
        f'Return spring: compression spring, outside diameter at most 1.2 mm, installed length about {spring:.2f} mm and about {spring_stop:.2f} mm at the stop; rate and preload not selected (placeholder envelope).',
        'Finishing: the upper-tab underside and lower-tab top are sanded to an 8.0 mm gauge block (barrel 7.6 mm + 0.2 mm each side); dowel holes are reamed (lower 2.02 mm clearance, upper 1.98 mm blind press fit); the three screw holes and the spring bore are drilled 1.6 mm after printing; the spring bore must pass a 1.45 mm pin gauge.',
        'Assembly order: button in from below and slid into the slot; dowel pressed up into the upper tab; spring then spring screw (set flush or below the inward block face) into the inward block; stop screw and its jam nut; rest screw and its jam nut; adjust; then switch/PCB. Changing spring preload later means loosening the stop nut and re-gauging the stop.',
        f'Adjustment (no switch needed): turn the rest screw until the face is flush with the skin beside the window front edge, lock its nut; press the face and turn the stop screw until a depth gauge held normal to that skin, at the face front edge at mid height, reads {g:.2f} mm (accept {g-band:.2f}-{g+band:.2f} mm); lock its nut and re-read. Fit the PCB and confirm the click; do not back the stop out to get a click.']
    r['verification_plan']=r['verification_plan']+[
        f'Placeholder housing clear (at least 0.05 mm) down to {deep:.3f} deg: the deepest gauge-accepted stop plus hinge play and a {p["gauge_check_margin_deg"]:.2f} deg margin, at every play offset.',
        'The stop jam nut turns a quarter turn on its seat past a flush spring screw.']
    r['unverified_requirements']=[x for x in r['unverified_requirements'] if not x.startswith(('Switch selection','Return spring selection'))]+[
        f'Switch selection: operating point no deeper than 0.50 mm and total travel to bottoming of at least 0.95 mm; the plunger pushes the far edge of the stem about {stem_push_mm(p):.2f} mm at the nominal stop and up to about {stem_push_mm(p,deep):.2f} mm at the deepest accepted pose; stem within -0.15/+0.05 mm in Y of the modeled position. A missing click after adjustment means the switch or PCB is outside this band.',
        f'Return spring selection: outside diameter at most 1.2 mm (0.2 mm radial clearance in the drilled 1.6 mm bore); installed length about {spring:.2f} mm, about {spring_stop:.2f} mm at the stop; solid length below the stop length. Its preload adds to thumb force and is set by the spring screw depth.',
        'Gauge reading uses the skin normal measured on the model; the printed skin and the real hinge play move it, so the first article is checked against the housing margin, not only the gauge.']
    return r


# ---------------------------------------------------------------------------
# Revision 11: repairs the revision-10 round-1 findings.
# - Spring bore cannot be drilled after printing (no tool access) -> it stays
#   as printed and is checked with a short 1.45 mm gauge pin from -X; only
#   the coaxial stop and rest tap holes are drilled, from +X, before fitting.
# - Gauge value was computed at a construction point -> the reading is the
#   value measured on the revision-10 button/shell STEP at a stated point
#   (1.0 mm in from the face front edge, z 14), linear in the hinge angle.
# - Switch window no closer than modeled (+0.00 mm), so the housing margin
#   is not spent by the switch position; setting force stated; spring screw
#   set flush; shell-gap sweep reaches the deepest accepted pose.
# - Hinge play while gauging is added to the deepest accepted pose; the
#   placeholder housing moves to a 1.00 mm stem bottoming depth so the
#   housing margin still holds there; a first-article bottoming test is set.
# ---------------------------------------------------------------------------
P11=dict(P10)
P11.update({'gauge_stop_reading_mm':1.4429,'gauge_mm_per_deg':.4694,'gauge_read_z_mm':14.,'gauge_read_inset_mm':1.,
            'gauge_setting_force_n':5.,'gauge_play_reading_mm':.035,'housing_margin_after_operating_mm':.5})


def angles_v11(p=P11):
    return angles_v10(p)


def gauge_reading_v11_mm(p=P11,angle_deg=None):
    """Depth gauge reading (normal to the skin, at the stated point) at a hinge angle; measured calibration."""
    a=angles_v11(p)['stop'] if angle_deg is None else angle_deg
    return p['gauge_stop_reading_mm']+p['gauge_mm_per_deg']*(angles_v11(p)['stop']-a)


def deepest_accepted_angle_v11_deg(p=P11):
    a=angles_v11(p)
    # Hinge play can shift the reading while gauging (up to the radial play at the read point) and the
    # stop contact in use (stop_play); both are taken on the deep side, independently.
    return a['stop']-a['stop_play']-(p['gauge_band_mm']+p['gauge_play_reading_mm'])/p['gauge_mm_per_deg']-p['gauge_check_margin_deg']


def side_button_recipe_v11(request=REQUEST,p=None):
    p=dict(P11 if p is None else p)
    p['depth_gauge_mm']=p['gauge_stop_reading_mm']
    r=side_button_recipe_v10(request,p)
    r['title']='Side button improvement trial, revision 11 (measured gauge setting, printed spring bore)'
    r['design_parameters']={k:float(v) for k,v in p.items()}
    r['parameter_basis']={k:'Proposal for this prototype revision; not measured from a real mouse, switch or PCB.' for k in p}
    for k in ('gauge_skin_normal_x','gauge_skin_normal_y','gauge_skin_normal_z'):
        r['parameter_basis'][k]='Measured on the revision-9 shell STEP (used only by the revision-10 estimate).'
    for k in ('gauge_stop_reading_mm','gauge_mm_per_deg','depth_gauge_mm'):
        r['parameter_basis'][k]=('Measured on the revision-10 button and shell STEP (same button geometry): ray along the inward skin normal '
                                 '(0.1483, 0.966, 0.2116) from the skin tangent plane at (13.895, 30.267, 13.726), 1.0 mm in from the face '
                                 'front edge at z 14; 0.047 mm at rest, 1.443 mm at the nominal stop, 0.469 mm per degree.')
    a=angles_v11(p);deep=deepest_accepted_angle_v11_deg(p)
    rot={c['id']:c for c in r['rotation_checks']}
    rot['housing-clear-past-stop'].update(end_deg=deep)
    rot['nearest-shell-gap-until-stop'].update(end_deg=deep,samples=3,max_samples=3)
    r['rotation_checks']=list(rot.values())
    for o in r['outputs']:
        if o['part_id']=='stop_screw':o['manufacturing_process']='Purchased M2 x 8 grub screw, flat point, in a 1.6 mm tap hole drilled from +X'
        if o['part_id']=='rest_screw':o['manufacturing_process']='Purchased M2 x 4 grub screw, flat point, in a 1.6 mm tap hole drilled from +X'
        if o['part_id']=='spring_screw':o['manufacturing_process']='Purchased M2 grub screw cut to 1.5 mm, self-tapped into the printed 1.6 mm spring bore'
    g=gauge_reading_v11_mm(p);band=p['gauge_band_mm'];ops={o['id']:o for o in r['operations']}
    spring=ops['spring']['height_mm'];lever=p['hinge_y_mm']-p['spring_y_mm']
    spring_stop=spring-lever*math.sin(math.radians(-a['stop']));spring_deep=spring-lever*math.sin(math.radians(-deep))
    basis=r['design_basis']
    basis['assumptions']=[x for x in basis['assumptions'] if not x.startswith(('Return spring:','Adjustment','Finishing:','Assembly order:'))]+[
        f'Return spring: compression spring, outside diameter at most 1.2 mm, installed length about {spring:.2f} mm, about {spring_stop:.2f} mm at the nominal stop and {spring_deep:.2f} mm at the deepest accepted stop; rate and preload not selected (placeholder envelope).',
        'Finishing: the upper-tab underside and lower-tab top are sanded to an 8.0 mm gauge block (barrel 7.6 mm + 0.2 mm each side); dowel holes are reamed (lower 2.02 mm clearance, upper 1.98 mm blind press fit). Before the button is fitted, the coaxial rest and stop tap holes are drilled 1.6 mm from +X through the rest hole (straight free line about 64 mm). The spring bore stays as printed and must accept a short 1.45 mm gauge pin from -X; if not, reprint with hole compensation (it cannot be drilled: no tool access).',
        'Assembly order: button in from below and slid into the slot; dowel pressed up into the upper tab; spring then spring screw, set flush with the inward block face; stop screw and its jam nut; rest screw and its jam nut; adjust; then switch/PCB. Changing spring preload later means loosening the stop nut and re-gauging the stop.',
        f'Adjustment (no switch needed): turn the rest screw until the face is flush with the skin beside the window front edge, lock its nut; press the face with about {p["gauge_setting_force_n"]:.0f} N and turn the stop screw until a depth gauge whose foot rests on the skin beside the front edge, rod normal to the skin, 1.0 mm in from the face front edge at mid height (z 14), reads {g:.2f} mm (accept {g-band:.2f}-{g+band:.2f} mm; it reads about 0.05 mm at rest); lock its nut and re-read. Fit the PCB and confirm the click; do not back the stop out to get a click.']
    r['verification_plan']=[x for x in r['verification_plan'] if not x.startswith('Placeholder housing clear (at least 0.05 mm) down to')]+[
        f'Placeholder housing clear (at least 0.05 mm) and nearest shell gap (at least 0.15 mm) down to {deep:.3f} deg: the deepest gauge-accepted stop plus hinge play while gauging and in use, and a {p["gauge_check_margin_deg"]:.2f} deg margin, at every play offset (sampled).']
    r['unverified_requirements']=[x for x in r['unverified_requirements'] if not x.startswith(('Switch selection','Return spring selection','Gauge reading'))]+[
        f'Switch selection: operating point no deeper than 0.50 mm and total travel to bottoming of at least 1.00 mm (the placeholder housing depth); the plunger pushes the far edge of the stem about {stem_push_mm(p):.2f} mm at the nominal stop and up to about {stem_push_mm(p,deep):.2f} mm at the deepest accepted pose; stem within -0.15/+0.00 mm in Y of the modeled position (never closer, which would spend the housing margin). A missing click after adjustment means the switch or PCB is outside this band.',
        f'Return spring selection: outside diameter at most 1.2 mm (0.2 mm radial clearance in the printed 1.6 mm bore); solid length below {spring_deep:.2f} mm (deepest accepted stop, spring screw flush). Its preload adds to thumb force.',
        'Gauge reading: calibrated on the CAD model; printed layer cusps (about 0.04 mm) and stop-path flex under the setting force (estimated about 0.01 mm per N) are not modeled, so the first article is tested: read the gauge at the setting force and at 10 N, with and without the switch fitted; equal readings with and without the switch show the switch does not bottom, and the 5-10 N difference is the stop-path flex.']
    return r


# ---------------------------------------------------------------------------
# Revision 12: repairs the revision-11 round-1 findings.
# - The revision-11 calibration ray hit the face at its front edge, not 1.0 mm
#   in -> the gauge is calibrated by scripts/side_button_gauge.py, which finds
#   the face front edge on the STEP and reads 1.0 mm in; the build test re-runs
#   it on the built parts, so the contract number cannot drift from the model.
# - The absolute reading moved by about 0.02 mm with the foot position on the
#   curved skin -> the gauge is zeroed on the face at rest and the stroke is
#   set as a change in reading (stable within 0.002 mm across foot positions).
# - Hinge play while zeroing and while gauging (about 0.035 + 0.062 mm of
#   reading) is added to the deepest accepted pose that the housing and shell
#   sweeps must clear; to keep the 0.15 mm shell gap and 0.05 mm housing
#   margin at that deeper pose the nominal stop moves to 0.15 mm past the
#   operating point (was 0.20) and the stop-screw tip stands 0.4 mm proud of
#   the inward block (was 0.3), so the stop web keeps its gap to the block
#   face at the deepest pose. Press point for the setting force is stated.
# - First-article flex test has a pass limit; the spring has a minimum free
#   length so it preloads the face onto the rest screw.
# ---------------------------------------------------------------------------
P12=dict(P11)
P12.update({'stop_extra_travel_mm':.15,'block_recess_mm':.4,'gauge_stroke_reading_mm':1.312,'gauge_mm_per_deg':.455,'gauge_play_reading_mm':.097,
            'gauge_skin_probe_x_mm':16.,'gauge_skin_probe_y_mm':32.,'gauge_skin_probe_z_mm':14.})
for _k in ('gauge_stop_reading_mm','gauge_skin_normal_x','gauge_skin_normal_y','gauge_skin_normal_z','gauge_read_z_mm'):
    P12.pop(_k,None)


def angles_v12(p=P12):
    return angles_v11(p)


def gauge_stroke_v12_mm(p=P12,angle_deg=None):
    """Change in gauge reading from the rest pose (zeroed there) to a hinge angle; measured calibration."""
    a=angles_v12(p)['stop'] if angle_deg is None else angle_deg
    return p['gauge_stroke_reading_mm']+p['gauge_mm_per_deg']*(angles_v12(p)['stop']-a)


def deepest_accepted_angle_v12_deg(p=P12):
    a=angles_v12(p)
    return a['stop']-a['stop_play']-(p['gauge_band_mm']+p['gauge_play_reading_mm'])/p['gauge_mm_per_deg']-p['gauge_check_margin_deg']


def side_button_recipe_v12(request=REQUEST,p=None):
    p=dict(P12 if p is None else p)
    q=dict(P11);q.update({k:v for k,v in p.items() if k in P11})
    q['gauge_play_reading_mm']=p['gauge_play_reading_mm']
    r=side_button_recipe_v11(request,q)
    p['depth_gauge_mm']=p['gauge_stroke_reading_mm']
    r['title']='Side button improvement trial, revision 12 (zeroed gauge stroke, model-checked calibration)'
    r['design_parameters']={k:float(v) for k,v in p.items()}
    r['parameter_basis']={k:'Proposal for this prototype revision; not measured from a real mouse, switch or PCB.' for k in p}
    for k in ('gauge_stroke_reading_mm','gauge_mm_per_deg','depth_gauge_mm'):
        r['parameter_basis'][k]=('Measured on the button and shell STEP by scripts/side_button_gauge.py (foot on the skin nearest the '
                                 'probe point, rod normal to it, 1.0 mm in from the face front edge): stop reading minus rest reading '
                                 '1.312 mm (1.3123-1.3132 over three foot positions), 0.455 mm per degree; re-measured by the build test.')
    r['parameter_basis']['gauge_play_reading_mm']=('Hinge radial play (0.035 mm) while zeroing at rest plus the play spread while gauging '
                                                   'at the stop (about 0.062 mm, revision-11 assembly review contact model).')
    a=angles_v12(p);deep=deepest_accepted_angle_v12_deg(p)
    rot={c['id']:c for c in r['rotation_checks']}
    rot['housing-clear-past-stop'].update(end_deg=deep)
    rot['nearest-shell-gap-until-stop'].update(end_deg=deep)
    r['rotation_checks']=list(rot.values())
    g=gauge_stroke_v12_mm(p);band=p['gauge_band_mm'];ops={o['id']:o for o in r['operations']}
    spring=ops['spring']['height_mm'];lever=p['hinge_y_mm']-p['spring_y_mm']
    spring_stop=spring-lever*math.sin(math.radians(-a['stop']));spring_deep=spring-lever*math.sin(math.radians(-deep))
    plunger_x=(p['plunger_x_min_mm']+p['plunger_x_max_mm'])/2;plunger_z=(p['plunger_z_min_mm']+p['plunger_z_max_mm'])/2
    basis=r['design_basis']
    basis['assumptions']=[x for x in basis['assumptions'] if not x.startswith(('Return spring:','Adjustment'))]+[
        f'Return spring: compression spring, outside diameter at most 1.2 mm, installed length about {spring:.2f} mm, about {spring_stop:.2f} mm at the nominal stop and {spring_deep:.2f} mm at the deepest accepted stop; rate and preload not selected (placeholder envelope).',
        f'Adjustment (no switch needed): turn the rest screw until the face is flush with the skin beside the window front edge, lock its nut. Put the depth-gauge foot on the skin beside the front edge at mid height, rod normal to the skin and 1.0 mm in from the face front edge, and zero it with the button at rest. Press the face over the plunger (x {plunger_x:.0f}, z {plunger_z:.0f}) with about {p["gauge_setting_force_n"]:.0f} N and turn the stop screw until the reading changes by {g:.2f} mm (accept {g-band:.2f}-{g+band:.2f} mm); lock its nut, release, re-zero and re-read. Fit the PCB and confirm the click; do not back the stop out to get a click.']
    r['verification_plan']=[x for x in r['verification_plan'] if not x.startswith('Placeholder housing clear (at least 0.05 mm) and nearest shell gap')]+[
        f'Placeholder housing clear (at least 0.05 mm) and nearest shell gap (at least 0.15 mm) down to {deep:.3f} deg: the deepest gauge-accepted stop including hinge play while zeroing, gauging and in use, and a {p["gauge_check_margin_deg"]:.2f} deg margin, at every play offset (sampled).',
        'The gauge calibration is re-measured on the built button and shell STEP and must match the stated stroke reading.',
        'The housing margin is checked against the placeholder housing at a 1.00 mm stem bottoming depth; a switch that bottoms sooner is outside the selection limit and is caught by the first-article bottoming test.']
    r['unverified_requirements']=[x for x in r['unverified_requirements'] if not x.startswith(('Switch selection','Return spring selection','Gauge reading'))]+[
        'Gauge reading: calibrated on the CAD model; printed layer cusps (about 0.04 mm) on the skin and face are not modeled.',
        f'Switch selection: operating point no deeper than 0.50 mm and total travel to bottoming of at least 1.00 mm (the placeholder housing depth); the plunger pushes the far edge of the stem about {stem_push_mm(p):.2f} mm at the nominal stop and up to about {stem_push_mm(p,deep):.2f} mm at the deepest accepted pose. The switch and PCB placement is accepted by the first-article bottoming test, not by a position band; the model places the stem at its nominal position.',
        f'Return spring selection: outside diameter at most 1.2 mm (0.2 mm radial clearance in the printed 1.6 mm bore); solid length below {spring_deep:.2f} mm (deepest accepted stop, spring screw flush); free length at least {spring+.3:.2f} mm so it preloads the face onto the rest screw (the face must not rattle when the shell is shaken). Its preload adds to thumb force.',
        'Stop-path flex: estimated about 0.01 mm of reading per N (printed stop-web bending, unverified). First article: re-read the gauge at 10 N; the change from the 5 N reading must be at most 0.03 mm, and with the switch fitted the 10 N reading must equal the reading without it (switch not bottomed). Thumb force above 10 N is outside the checked range.']
    return r


# ---------------------------------------------------------------------------
# Revision 13: one design for several switch types (owner: Zippy DF3, Huano
# and others offered by the board vendor).
# - Datasheets differ in operating position by about 0.5 mm while the
#   guaranteed overtravel is only 0.2-0.25 mm, so a stop set to one gauge
#   value cannot serve every switch. Both ends of the stroke are now set
#   against the fitted switch's own click, in 1/16-turn (0.025 mm) steps:
#   * an M2 dog-point actuator screw in the plunger (reached through a
#     1.6 mm hole in the face) sets the rest position just above release;
#   * the stop screw is set just past the click.
# - The switch placeholder is generated from a registered switch profile;
#   every registered profile is evaluated (switch_fit_v13) and profiles with
#   UNKNOWN datasheet values are reported as unverified, never as passing.
# ---------------------------------------------------------------------------
from cadmcp_brain.studio.switch_profiles import PROFILES as SWITCH_PROFILES, missing_for_click_referenced_stop

P13=dict(P12)
for _k in [k for k in P13 if k.startswith('gauge_')]+['depth_gauge_mm','housing_margin_after_operating_mm',
                                                       'assumed_stem_operating_travel_mm']:
    P13.pop(_k,None)
P13.update({'plunger_x_min_mm':-.5,'plunger_x_max_mm':4.5,
            'adjust_step_mm':.025,               # 1/16 turn of an M2 x 0.4 thread
            'rest_steps_back':3,'stop_steps_past':2,
            'actuator_thread_length_mm':4.,'actuator_point_radius_mm':.5,'actuator_point_length_mm':1.,
            'actuator_tip_below_plunger_mm':1.2,
            'deep_check_margin_deg':.03,'design_switch_profile':0.})
DESIGN_SWITCH='zippy_df_pin'


def _lever13(p):
    return (p['plunger_x_min_mm']+p['plunger_x_max_mm'])/2-p['hinge_x_mm']


def _stop_contact_radius13(p):
    return p['hinge_y_mm']-(p['screw_y_mm']-p['screw_radius_mm'])


def setting_windows_v13(p=P13,md_mm=.12):
    """Actuator-axis distances fixed by the click-referenced procedure (mm), before hinge play.

    Rest: turn the actuator in until the switch operates with the button at rest, out until it
    releases, then rest_steps_back steps further out: the tip sits above OP by
    [rest_steps_back*s, md + (rest_steps_back+1)*s).
    Stop: with the button pressed, turn the stop screw out one step at a time until the switch
    operates, then stop_steps_past steps more: overshoot past OP in [k*s', (k+1)*s'),
    s' the stop step referred to the actuator.
    """
    s=p['adjust_step_mm'];s_stop=s*_lever13(p)/_stop_contact_radius13(p)
    rest=(p['rest_steps_back']*s,md_mm+(p['rest_steps_back']+1)*s)
    over=(p['stop_steps_past']*s_stop,(p['stop_steps_past']+1)*s_stop)
    return {'rest_above_op_mm':rest,'overshoot_mm':over,'step_mm':s,'stop_step_at_actuator_mm':s_stop}


def _inherited_params13(p):
    """Revision-12 parameters driven by the click-referenced nominal rest offset and overshoot."""
    w=setting_windows_v13(p,max(_md_values()))
    q=dict(P12);q.update({k:v for k,v in p.items() if k in P12})
    q['stem_free_play_mm']=sum(w['rest_above_op_mm'])/2;q['assumed_stem_operating_travel_mm']=0.
    q['stop_extra_travel_mm']=sum(w['overshoot_mm'])/2;q['housing_margin_after_operating_mm']=.5
    return q


def angles_v13(p=P13):
    a=angles_v12(_inherited_params13(p))  # stop/rest play, tilt; press/stop restated below
    lever=_lever13(p);w=setting_windows_v13(p,max(_md_values()))
    rest_nom=sum(w['rest_above_op_mm'])/2;over_nom=sum(w['overshoot_mm'])/2
    a['click']=-math.degrees(rest_nom/lever)
    a['press']=a['click']
    a['stop']=-math.degrees((rest_nom+over_nom)/lever)
    deep=w['rest_above_op_mm'][1]+w['overshoot_mm'][1]
    a['deep']=-math.degrees(deep/lever)-a['stop_play']-p['deep_check_margin_deg']
    return a


def _md_values():
    return [pr.movement_differential.value for pr in SWITCH_PROFILES.values() if pr.movement_differential.known]


def _op_and_body_top(profile):
    """Operating position and body top on the profile's own height datum, with tolerances."""
    return (profile.operating_position.value,profile.operating_position.tolerance or 0.,
            profile.body_height.value,profile.body_height.tolerance or 0.)


def switch_fit_v13(profile,p=P13):
    """Check the click-referenced setting against one switch profile; UNKNOWN data gives 'unverified'."""
    missing=missing_for_click_referenced_stop(profile)
    if not (profile.operating_position.known and profile.body_height.known):
        missing=sorted(set(missing)|{k for k in ('operating_position','body_height') if not getattr(profile,k).known})
    if missing:
        return {'profile':profile.id,'verdict':'unverified','missing':missing,
                'reason':'Datasheet values needed by the setting procedure are UNKNOWN; no pass is claimed.'}
    a=angles_v13(p);lever=_lever13(p)
    w=setting_windows_v13(p,profile.movement_differential.value)
    play_rest=math.radians(a['rest_play'])*lever;play_stop=math.radians(a['stop_play'])*lever
    over_lo,over_hi=w['overshoot_mm'][0]-play_stop,w['overshoot_mm'][1]+play_stop
    rest_lo=w['rest_above_op_mm'][0]-play_rest
    ot=profile.overtravel.value
    op,op_tol,top,top_tol=_op_and_body_top(profile)
    # The dog point (radius point_r) presses the pin; the thread above it must stay clear of the body top.
    thread_above_body=(op-op_tol)-over_hi+p['actuator_point_length_mm']-(top+top_tol)
    checks={
        'no_operation_at_rest':{'value_mm':rest_lo,'required':'> 0 (tip above the release point with rest play)','pass':rest_lo>0},
        'operates_at_stop':{'value_mm':over_lo,'required':'> 0 (past OP with stop play)','pass':over_lo>0},
        'within_guaranteed_overtravel':{'value_mm':over_hi,'limit_mm':ot,'margin_mm':ot-over_hi,
                                        'required':'overshoot + stop play below the guaranteed overtravel','pass':over_hi<ot},
        'thread_clears_body':{'value_mm':thread_above_body,'required':'> 0 at the deepest pose with OP and body tolerances','pass':thread_above_body>0},
    }
    return {'profile':profile.id,'verdict':'pass' if all(c['pass'] for c in checks.values()) else 'fail',
            'checks':checks,'overtravel_left_for_flex_mm':ot-over_hi,
            'scope':'Rigid 1-D stack along the actuator axis from datasheet limits, the adjustment step and hinge play; contact flex, '
                    'thread backlash and the click-detection method are not modeled.'}


def switch_fit_report_v13(p=P13):
    return [switch_fit_v13(pr,p) for pr in SWITCH_PROFILES.values()]


def side_button_recipe_v13(request=REQUEST,p=None):
    p=dict(P13 if p is None else p)
    a=angles_v13(p);lever=_lever13(p)
    # Drive the inherited stop geometry from the click-referenced nominal stop.
    q=_inherited_params13(p);rest_nom=q['stem_free_play_mm']
    r=side_button_recipe_v12(request,q)
    ops={o['id']:o for o in r['operations']}
    order=[o['id'] for o in r['operations'] if o['id'] not in ('switch_housing','switch_stem')]
    profile=SWITCH_PROFILES[DESIGN_SWITCH]
    op,_,top,_=_op_and_body_top(profile)
    px=(p['plunger_x_min_mm']+p['plunger_x_max_mm'])/2;pz=(p['plunger_z_min_mm']+p['plunger_z_max_mm'])/2
    tip_y=p['plunger_tip_y_mm']-p['actuator_tip_below_plunger_mm']
    op_y=tip_y-rest_nom;base_y=op_y-op
    pl=ops['plunger_box'];pl.update(size_mm=[p['plunger_x_max_mm']-p['plunger_x_min_mm'],pl['size_mm'][1],pl['size_mm'][2]],
                                    center_mm=[px,pl['center_mm'][1],pl['center_mm'][2]],
                                    reason='Plunger carrying the actuator screw toward the switch pin.')
    tap=p['tap_radius_mm'];sr=p['screw_radius_mm'];pr_=p['actuator_point_radius_mm']
    thread_y0=tip_y+p['actuator_point_length_mm'];thread_len=p['actuator_thread_length_mm']
    new=[{'id':'actuator_hole','op':'cylinder','function_id':'F3_actuate_switch','reason':'Tap hole for the actuator screw, open through the face for a 0.9 mm hex key.',
          'radius_mm':tap,'height_mm':20.,'origin_mm':[px,p['plunger_tip_y_mm']-1.,pz],'axis':[0.,1.,0.]},
         {'id':'actuator_thread','op':'cylinder','function_id':'F3_actuate_switch','reason':'M2 dog-point grub screw: thread.',
          'radius_mm':sr,'height_mm':thread_len,'origin_mm':[px,thread_y0,pz],'axis':[0.,1.,0.]},
         {'id':'actuator_point','op':'cylinder','function_id':'F3_actuate_switch','reason':'M2 dog-point grub screw: Ø1.0 point pressing the switch pin.',
          'radius_mm':pr_,'height_mm':p['actuator_point_length_mm']+.01,'origin_mm':[px,tip_y,pz],'axis':[0.,1.,0.]},
         {'id':'actuator_screw','op':'union','function_id':'F3_actuate_switch','reason':'Adjustable actuator: sets the rest position against the switch release point.',
          'operands':['actuator_thread','actuator_point']},
         _box('switch_body','F3_actuate_switch',f'Switch body from profile {profile.id} ({profile.model}); placed with OP {rest_nom:.3f} mm below the actuator tip at rest.',
              [px-profile.body_length.value/2,base_y,pz-profile.body_width.value/2],[px+profile.body_length.value/2,base_y+top,pz+profile.body_width.value/2]),
         _box('switch_pin','F3_actuate_switch','Switch pin drawn at its rest pose under the actuator (pin x size UNKNOWN; 1.2 mm assumed).',
              [px-.6,base_y+top,pz-profile.plunger_width.value/2],[px+.6,tip_y,pz+profile.plunger_width.value/2])]
    for o in new:ops[o['id']]=o
    ops['button']['operands']=list(ops['button']['operands'])+['actuator_hole']
    i=order.index('button');order[i:i]=['actuator_hole']
    order+=['actuator_thread','actuator_point','actuator_screw','switch_body','switch_pin']
    r['operations']=[ops[n] for n in order]
    r['title']='Side button improvement trial, revision 13 (click-referenced stroke for several switch types)'
    r['design_parameters']={k:float(v) for k,v in p.items()}
    r['parameter_basis']={k:'Proposal for this prototype revision; not measured from a real mouse, switch or PCB.' for k in p}
    r['parameter_basis']['adjust_step_mm']='1/16 turn of an M2 x 0.4 thread.'
    r['outputs']=[o for o in r['outputs'] if o['part_id'] not in ('switch_housing','switch_stem')]+[
        {'part_id':'actuator_screw','node':'actuator_screw','manufacturing_process':'Purchased M2 x 5 dog-point grub screw (ISO 4028: point Ø1.0 x 1.0), self-tapped into the plunger'},
        {'part_id':'switch_body','node':'switch_body','manufacturing_process':f'Placeholder for a purchased switch (profile {profile.id}); not manufactured'},
        {'part_id':'switch_pin','node':'switch_pin','manufacturing_process':'Placeholder for the switch pin; part of the purchased switch'}]
    engaged=(thread_y0+thread_len)-p['plunger_tip_y_mm']
    ring=math.pi*(sr**2-tap**2)
    r['press_fits']=r['press_fits']+[
        {'id':'actuator-thread','part_a':'actuator_screw','part_b':'button','min_overlap_mm3':.7*ring*engaged,'max_overlap_mm3':1.3*ring*engaged,
         'basis':'M2 thread engaged in the printed plunger, modeled as an interference annulus.'}]
    r['clearance_checks']=[c for c in r['clearance_checks'] if c['id']!='rest-button-housing']+[
        {'id':'rest-button-switch-body','part_a':'button','part_b':'switch_body','min_mm':.5},
        {'id':'rest-actuator-thread-switch-body','part_a':'actuator_screw','part_b':'switch_body','min_mm':.3}]
    rot={c['id']:c for c in r['rotation_checks']}
    for k in ('rest-band-stem-free','stem-contact-by-free-play'):rot.pop(k,None)
    h=rot.pop('housing-clear-past-stop')
    h.update(id='switch-body-clear-to-deepest',obstacles=['switch_body'],carried_parts=['actuator_screw'],end_deg=a['deep'],min_mm=.05)
    rot['switch-body-clear-to-deepest']=h
    rot['nearest-shell-gap-until-stop'].update(end_deg=a['deep'],carried_parts=['actuator_screw'])
    rot['rise-with-play-clear-of-skin']['carried_parts']=['actuator_screw']
    r['rotation_checks']=list(rot.values())
    # Outer form: outside the side-button region the delivered shell and button must match the base skin.
    r['base_shape_checks']=[{'id':'outer-form-matches-base','base_node':'outer','parts':['shell','button'],'tolerance_mm':.05,
                             'samples_per_face':16,'regions':[
        {'id':'side-button-region','kind':'allowed_change','reason':'Owner allows outer-form changes around the side buttons (window, running gap, access hole).',
         'lo_mm':[p['window_x_min_mm']-1.,20.,p['window_z_min_mm']-1.],'hi_mm':[p['window_x_max_mm']+3.,40.,p['window_z_max_mm']+1.]},
        {'id':'open-bottom','kind':'not_in_base','reason':'The base outer form is the skin; its bottom cap is the open rim where the base plate fits.',
         'lo_mm':[-70.,-40.,-.1],'hi_mm':[70.,40.,.1]}]}]
    fits=switch_fit_report_v13(p)
    basis=r['design_basis']
    basis['assumptions']=[x for x in basis['assumptions'] if not x.startswith(('Adjustment','Switch housing'))]+[
        'Switch: any pin-plunger mouse micro switch with a registered profile; the placeholder is drawn from the Zippy DF datasheet. The owner board places it; the stroke is set against the fitted switch, so its height may vary.',
        f'Adjustment (switch fitted, its output read by the mouse software or a continuity meter; M2 x 0.4 screws turned in 1/16-turn steps, {p["adjust_step_mm"]:.3f} mm): '
        f'(1) rest screw until the face is flush, lock its nut; (2) with the button at rest, turn the actuator screw in through the face hole until the switch operates, out until it releases, then {p["rest_steps_back"]} steps further out; '
        f'(3) press the face over the plunger with about 5 N and turn the stop screw out one step at a time until the switch operates at the stop, then {p["stop_steps_past"]} steps more; lock its nut; (4) confirm click and release ten times.',
        'Face: a 1.6 mm access hole for the actuator screw at the plunger (side-button region, where the owner allows changes).']
    s=setting_windows_v13(p,max(_md_values()))
    r['verification_plan']=[x for x in r['verification_plan'] if 'gauge' not in x.lower() and not x.startswith(('Placeholder housing','The housing margin','Overtravel:','Free play:','Actuation:'))]+[
        'Overtravel: the hard stop blocks motion by the nominal stop angle plus the play angle at every play offset.',
        f'Switch body clear by at least 0.05 mm, and nearest shell gap at least 0.15 mm, down to {a["deep"]:.3f} deg (largest rest offset and overshoot over the profiles, stop play and a {p["deep_check_margin_deg"]:.2f} deg margin), with the actuator screw carried.',
        'Outer form: outside the side-button region the shell and button match the base skin (no material outside it, every sampled base-skin point within 0.05 mm of material); a deviation there is a blocker.',
        'Every registered switch profile is evaluated for the click-referenced setting (no operation at rest, operation at the stop, overshoot within the guaranteed overtravel, thread clear of the body); profiles with UNKNOWN values are reported unverified.']
    summary='; '.join(f"{f['profile']}: {f['verdict']}"+(f" (overtravel left {f['overtravel_left_for_flex_mm']:.3f} mm)" if f['verdict']!='unverified' else f" (missing {', '.join(f['missing'])})") for f in fits)
    spring=ops['spring']['height_mm'];spring_lever=p['hinge_y_mm']-p['spring_y_mm']
    spring_deep=spring-spring_lever*math.sin(math.radians(-a['deep']))
    basis['assumptions']=[x for x in basis['assumptions'] if not x.startswith('Return spring:')]+[
        f'Return spring: compression spring, outside diameter at most 1.2 mm, installed length about {spring:.2f} mm, at least {spring_deep:.2f} mm at the deepest checked pose; rate and preload not selected (placeholder envelope).']
    r['unverified_requirements']=[x for x in r['unverified_requirements'] if not x.startswith(('Switch selection','Gauge reading','Stop-path flex','The switch is located','Switch housing','Return spring selection','Rigid face travel','Outer-form changes'))]+[
        'Rigid face travel at the nominal stop (designer estimate): about '+', '.join(f'{(x+15)*math.sin(math.radians(-a["stop"])):.2f} mm at x={x}' for x in (-10,2,14))+'; the stroke is short because rest and stop are both set close to the switch operating point.',
        'Outer-form changes awaiting owner acceptance: the 0.4 mm running gap (about 38 mm3 of skin) and a 1.6 mm actuator access hole in the face; after flush adjustment hinge play lets the face stand proud by about 0.1 mm at the free edge.',
        f'Return spring selection: outside diameter at most 1.2 mm; solid length below {spring_deep:.2f} mm; free length at least {spring+.3:.2f} mm so it preloads the face onto the rest screw. Its preload and the switch force add to thumb force.',
        f'Switch profiles (rigid 1-D stack from datasheets): {summary}.',
        'Switch pin x size and the hex-key access to the stop screw with the owner PCB fitted are not known; the actuator point must land on the pin top.',
        'Stop-path and plunger flex at thumb forces above the setting force are estimated (about 0.01 mm per N) and consume the overtravel left above; first article: press at 10 N and confirm release still occurs when the face is let go and the switch shows no damage after 1000 presses.']
    return r
