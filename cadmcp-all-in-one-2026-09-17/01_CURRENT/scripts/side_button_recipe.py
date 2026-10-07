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
