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
