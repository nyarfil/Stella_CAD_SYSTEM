"""Typed Recipe for the §22 side-button test subject, leaf-spring (compliant) variant.

This is a pipeline test subject, not a product. The hinge variant
(side_button_recipe.side_button_recipe_v13) stays available as an alternative;
nothing falls back from one to the other.

Mechanism (ASSUMED, following the common production-mouse construction of a
button carried by the elasticity of a plastic arm): the button face is the
removed piece of the skin, carried by a printed leaf spring rooted on a block
of the shell. There is no pin, return spring, rest screw or hard stop: the leaf
is the guide and the return element, and the switch takes the overtravel. An
M2 dog-point actuator screw sets the rest position against the fitted switch's
release point (click-referenced, 1/16-turn steps), so several switch types fit.

Rigid checks rotate the button about the leaf's pseudo-rigid-body pivot
(Howell, Compliant Mechanisms, 2001: characteristic radius factor 0.85 for an
end-loaded cantilever) with a stated pivot-play envelope; the leaf itself is
checked by beam theory. Every number is a proposal unless a source is named.
"""
from __future__ import annotations
import math

from side_button_recipe import REQUEST, SECTIONS, _box, _ellipse, _inset_sections
from cadmcp_brain.studio.recipe import PRBM_GAMMA
from cadmcp_brain.studio.switch_profiles import PROFILES as SWITCH_PROFILES, missing_for_click_referenced_stop

DESIGN_SWITCH = 'zippy_df_pin'
PL = {
    'shell_wall_mm': 1.5, 'safe_offset_mm': 2.1,
    'window_x_min_mm': -10., 'window_x_max_mm': 14., 'window_z_min_mm': 10., 'window_z_max_mm': 18., 'window_gap_mm': .4,
    'leaf_root_x_mm': -19., 'leaf_free_x_mm': -9., 'leaf_y_min_mm': 26., 'leaf_thickness_mm': 1.,
    'leaf_z_min_mm': 11., 'leaf_z_max_mm': 16., 'root_block_x_mm': 3., 'pad_x_mm': 2.5,
    'pivot_play_mm': .05,
    'plunger_x_min_mm': -.5, 'plunger_x_max_mm': 4.5, 'plunger_tip_y_mm': 24., 'plunger_z_min_mm': 10., 'plunger_z_max_mm': 16.,
    'spine_z_min_mm': 12.6, 'spine_z_max_mm': 15.4, 'spine_y_min_mm': 26.,
    'tap_radius_mm': .8, 'screw_radius_mm': 1.,
    'adjust_step_mm': .025, 'rest_steps_back': 3,
    'actuator_thread_length_mm': 4., 'actuator_point_radius_mm': .5, 'actuator_point_length_mm': 1.,
    'actuator_tip_below_plunger_mm': 1.2,
    'deep_check_margin_deg': .03, 'min_printed_wall_mm': 1.2,
    'force_band_min_n': .3, 'force_band_max_n': 3., 'stress_allowance': .5,
}
ASSUMED = {
    'force_band': 'ASSUMED press-force band for the test subject (0.3-3 N at the plunger); no product target is set.',
    'stress_allowance': 'ASSUMED half of the datasheet tensile yield for a static check; fatigue strength is UNKNOWN.',
    'pivot_play': 'ASSUMED 0.05 mm pivot shift envelope for the pseudo-rigid-body approximation at these small angles.',
    'leaf_material': 'ASSUMED Prusament PETG, printed rim-down so the leaf bending stress runs along the extrusion lines in each layer.',
}


def pivot_xy(p=PL):
    length = p['leaf_free_x_mm'] - p['leaf_root_x_mm']
    return p['leaf_root_x_mm'] + (1 - PRBM_GAMMA) * length, p['leaf_y_min_mm'] + p['leaf_thickness_mm'] / 2


def _lever(p):
    return (p['plunger_x_min_mm'] + p['plunger_x_max_mm']) / 2 - pivot_xy(p)[0]


def _md_values():
    return [pr.movement_differential.value for pr in SWITCH_PROFILES.values() if pr.movement_differential.known]


def rest_window_mm(p=PL, md_mm=.12):
    s = p['adjust_step_mm']
    return p['rest_steps_back'] * s, md_mm + (p['rest_steps_back'] + 1) * s


def deepest_travel_mm(profile, p=PL):
    """Actuator travel from rest until the dog point reaches the switch body top (pin fully pressed).

    Bounds any real bottoming: the pin bottoms at or before flush with the body.
    """
    op, op_tol = profile.operating_position.value, profile.operating_position.tolerance or 0.
    top, top_tol = profile.body_height.value, profile.body_height.tolerance or 0.
    return rest_window_mm(p, profile.movement_differential.value)[1] + (op + op_tol) - (top - top_tol)


def angles_leaf(p=PL):
    lever = _lever(p)
    complete = [pr for pr in SWITCH_PROFILES.values() if not missing_for_click_referenced_stop(pr)
                and pr.operating_position.known and pr.body_height.known]
    deep = max(deepest_travel_mm(pr, p) for pr in complete)
    rest = rest_window_mm(p, max(_md_values()))
    return {'click_nominal': -math.degrees(sum(rest) / 2 / lever), 'click_latest': -math.degrees(rest[1] / lever),
            'deep': -math.degrees(deep / lever) - p['deep_check_margin_deg'], 'deep_travel_mm': deep}


def switch_fit_leaf(profile, p=PL):
    missing = missing_for_click_referenced_stop(profile)
    missing = sorted(set(missing) | {k for k in ('operating_position', 'body_height') if not getattr(profile, k).known})
    if missing:
        return {'profile': profile.id, 'verdict': 'unverified', 'missing': missing,
                'reason': 'Datasheet values needed by the setting procedure are UNKNOWN; no pass is claimed.'}
    lever = _lever(p); rest = rest_window_mm(p, profile.movement_differential.value)
    play = p['pivot_play_mm']
    checks = {'no_operation_at_rest': {'value_mm': rest[0] - play, 'pass': rest[0] - play > 0,
                                       'required': '> 0 (tip above the release point with pivot play)'},
              'deepest_pose_inside_checked_range': {'travel_mm': deepest_travel_mm(profile, p),
                                                    'checked_deg': angles_leaf(p)['deep'],
                                                    'pass': -math.degrees(deepest_travel_mm(profile, p) / lever) >= angles_leaf(p)['deep'] - 1e-12}}
    return {'profile': profile.id, 'verdict': 'pass' if all(c['pass'] for c in checks.values()) else 'fail', 'checks': checks,
            'scope': 'No hard stop: the switch takes the overtravel. The deepest checked pose has the dog point at the switch body '
                     'top (pin fully pressed), which bounds any real bottoming; switch bottoming force is the switch maker\'s rating.'}


def switch_fit_report_leaf(p=PL):
    return [switch_fit_leaf(pr, p) for pr in SWITCH_PROFILES.values()]


def _far_edge(p, offset):
    hx, hy = pivot_xy(p); x0, y0 = p['window_x_max_mm'], 29.5
    n = [x0 - hx, y0 - hy]; length = math.hypot(*n); n = [n[0] / length, n[1] / length]; t = [-n[1], n[0]]
    x0 += offset * n[0]; y0 += offset * n[1]
    return [[x0 + (y - y0) / t[1] * t[0], y] for y in (20., 40.)]


def side_button_leaf_recipe(request=REQUEST, p=None):
    p = dict(PL if p is None else p)
    wl, zl, zh, g = p['window_x_min_mm'], p['window_z_min_mm'], p['window_z_max_mm'], p['window_gap_mm']
    hx, hy = pivot_xy(p); a = angles_leaf(p); lever = _lever(p)
    profile = SWITCH_PROFILES[DESIGN_SWITCH]
    rest = rest_window_mm(p, max(_md_values())); rest_nom = sum(rest) / 2
    px = (p['plunger_x_min_mm'] + p['plunger_x_max_mm']) / 2; pz = (p['plunger_z_min_mm'] + p['plunger_z_max_mm']) / 2
    tip_y = p['plunger_tip_y_mm'] - p['actuator_tip_below_plunger_mm']; base_y = tip_y - rest_nom - profile.operating_position.value
    top = profile.body_height.value
    ly0, ly1 = p['leaf_y_min_mm'], p['leaf_y_min_mm'] + p['leaf_thickness_mm']
    lz0, lz1 = p['leaf_z_min_mm'], p['leaf_z_max_mm']
    far, far_gap = _far_edge(p, 0.), _far_edge(p, g)
    tap, sr = p['tap_radius_mm'], p['screw_radius_mm']
    thread_y0 = tip_y + p['actuator_point_length_mm']; thread_len = p['actuator_thread_length_mm']
    ops = [
        {'id': 'outer', 'op': 'spline_loft', 'function_id': 'F6_connect_shell',
         'reason': 'Base outer skin (stand-in for a scanned shell); preserved outside the side-button region.',
         'sections': [{'z_mm': z, 'points_mm': _ellipse(a_, b_)} for z, a_, b_ in SECTIONS]},
        {'id': 'cavity', 'op': 'spline_loft', 'function_id': 'F6_connect_shell', 'reason': 'Inner cavity, open at the bottom.',
         'sections': _inset_sections(p['shell_wall_mm'])},
        {'id': 'hollow', 'op': 'difference', 'function_id': 'F6_connect_shell', 'reason': 'Shell skin = outer minus cavity.',
         'operands': ['outer', 'cavity']},
        {'id': 'window', 'op': 'polygon_extrusion', 'function_id': 'F1_transmit_force',
         'reason': 'Button skin region; the far edge is cut normal to the pivot radius so pressing slides along it.',
         'points_mm': [[wl, 20.], far[0], far[1], [wl, 40.]], 'height_mm': zh - zl, 'origin_mm': [0., 0., zl]},
        {'id': 'window_gap', 'op': 'polygon_extrusion', 'function_id': 'F6_connect_shell',
         'reason': 'Window enlarged by the running gap on all four sides; the button hangs on the leaf only.',
         'points_mm': [[wl - g, 20.], far_gap[0], far_gap[1], [wl - g, 40.]], 'height_mm': zh - zl + 2 * g, 'origin_mm': [0., 0., zl - g]},
        {'id': 'shell_open', 'op': 'difference', 'function_id': 'F6_connect_shell', 'reason': 'Open the window with the running gap.',
         'operands': ['hollow', 'window_gap']},
        _box('root_box', 'F2_guide_button', 'Leaf root block grown from the shell side wall.',
             [p['leaf_root_x_mm'] - p['root_block_x_mm'], ly0, lz0], [p['leaf_root_x_mm'], 40., lz1]),
        {'id': 'root', 'op': 'intersection', 'function_id': 'F2_guide_button', 'reason': 'Root block stays inside the outer skin.',
         'operands': ['root_box', 'outer']},
        {'id': 'shell_part', 'op': 'union', 'function_id': 'F6_connect_shell', 'reason': 'Shell with the leaf root block, one print.',
         'operands': ['shell_open', 'root']},
        _box('leaf', 'F2_guide_button', 'Printed leaf spring: guide and return element (cantilever from the root block).',
             [p['leaf_root_x_mm'], ly0, lz0], [p['leaf_free_x_mm'], ly1, lz1]),
        {'id': 'skin_piece', 'op': 'intersection', 'function_id': 'F1_transmit_force',
         'reason': 'Button face is the removed piece of the skin.', 'operands': ['hollow', 'window']},
        _box('pad_box', 'F2_guide_button', 'Pad joining the leaf free end to the button face.',
             [p['leaf_free_x_mm'], ly0, lz0], [p['leaf_free_x_mm'] + p['pad_x_mm'], 40., lz1]),
        {'id': 'pad', 'op': 'intersection', 'function_id': 'F2_guide_button', 'reason': 'Pad stays inside the outer skin.',
         'operands': ['pad_box', 'outer']},
        _box('spine_box', 'F1_transmit_force', 'Spine stiffening the face from the pad to the far edge.',
             [p['leaf_free_x_mm'], p['spine_y_min_mm'], p['spine_z_min_mm']], [p['window_x_max_mm'] - 1.5, 40., p['spine_z_max_mm']]),
        {'id': 'spine', 'op': 'intersection', 'function_id': 'F1_transmit_force', 'reason': 'Spine stays inside the outer skin.',
         'operands': ['spine_box', 'outer']},
        _box('plunger_box', 'F3_actuate_switch', 'Plunger carrying the actuator screw toward the switch pin.',
             [p['plunger_x_min_mm'], p['plunger_tip_y_mm'], p['plunger_z_min_mm']], [p['plunger_x_max_mm'], 40., p['plunger_z_max_mm']]),
        {'id': 'plunger', 'op': 'intersection', 'function_id': 'F3_actuate_switch', 'reason': 'Plunger stays inside the outer skin.',
         'operands': ['plunger_box', 'outer']},
        {'id': 'button_solid', 'op': 'union', 'function_id': 'F1_transmit_force', 'reason': 'One printed button: face, pad, spine, plunger.',
         'operands': ['skin_piece', 'pad', 'spine', 'plunger']},
        {'id': 'actuator_hole', 'op': 'cylinder', 'function_id': 'F3_actuate_switch',
         'reason': 'Tap hole for the actuator screw, open through the face for a 0.9 mm hex key.',
         'radius_mm': tap, 'height_mm': 20., 'origin_mm': [px, p['plunger_tip_y_mm'] - 1., pz], 'axis': [0., 1., 0.]},
        {'id': 'button', 'op': 'difference', 'function_id': 'F3_actuate_switch', 'reason': 'Button with the actuator tap hole.',
         'operands': ['button_solid', 'actuator_hole']},
        {'id': 'actuator_thread', 'op': 'cylinder', 'function_id': 'F3_actuate_switch', 'reason': 'M2 dog-point grub screw: thread.',
         'radius_mm': sr, 'height_mm': thread_len, 'origin_mm': [px, thread_y0, pz], 'axis': [0., 1., 0.]},
        {'id': 'actuator_point', 'op': 'cylinder', 'function_id': 'F3_actuate_switch', 'reason': 'M2 dog-point grub screw: Ø1.0 point.',
         'radius_mm': p['actuator_point_radius_mm'], 'height_mm': p['actuator_point_length_mm'] + .01, 'origin_mm': [px, tip_y, pz], 'axis': [0., 1., 0.]},
        {'id': 'actuator_screw', 'op': 'union', 'function_id': 'F3_actuate_switch',
         'reason': 'Adjustable actuator: sets the rest position against the switch release point.', 'operands': ['actuator_thread', 'actuator_point']},
        _box('switch_body', 'F3_actuate_switch', f'Switch body from profile {profile.id}; OP {rest_nom:.3f} mm below the actuator tip at rest.',
             [px - profile.body_length.value / 2, base_y, pz - profile.body_width.value / 2],
             [px + profile.body_length.value / 2, base_y + top, pz + profile.body_width.value / 2]),
        _box('switch_pin', 'F3_actuate_switch', 'Switch pin at its rest pose under the actuator (pin x size UNKNOWN; 1.2 mm assumed).',
             [px - .6, base_y + top, pz - profile.plunger_width.value / 2], [px + .6, tip_y, pz + profile.plunger_width.value / 2]),
    ]
    axis = {'axis_origin_mm': [hx, hy, 0.], 'axis_direction': [0., 0., 1.]}
    leaf_len = p['leaf_free_x_mm'] - p['leaf_root_x_mm']
    tip_deflection = math.sin(math.radians(-a['deep'])) * PRBM_GAMMA * leaf_len
    engaged = (thread_y0 + thread_len) - p['plunger_tip_y_mm']; ring = math.pi * (sr ** 2 - tap ** 2)
    fits = switch_fit_report_leaf(p)
    summary = '; '.join(f"{f['profile']}: {f['verdict']}" + (f" (missing {', '.join(f['missing'])})" if f['verdict'] == 'unverified' else '') for f in fits)
    return {
        'title': 'Side button test subject, leaf-spring variant (no pin, spring or stop screw)',
        'original_request': request,
        'design_parameters': {k: float(v) for k, v in p.items()},
        'parameter_basis': {k: 'Proposal for this test subject (ASSUMED); not measured from a real mouse, switch or PCB.' for k in p},
        'functions': {
            'F1_transmit_force': 'Transmit thumb force from the skin piece into the button.',
            'F2_guide_button': 'Guide and return the button with a printed leaf spring.',
            'F3_actuate_switch': 'Press the switch pin; rest offset set against the fitted switch.',
            'F6_connect_shell': 'Keep the outer skin; open only the side-button window.'},
        'protected_constraints': ['Outer skin outside the side-button region is not changed (checked against the base skin).'],
        'design_basis': {'kind': 'first_principles',
                         'summary': 'Compliant side button: skin piece on a printed leaf spring; the switch takes the overtravel.',
                         'assumptions': [ASSUMED['leaf_material'], ASSUMED['force_band'], ASSUMED['stress_allowance'], ASSUMED['pivot_play'],
                                         'Mechanism class: a button carried by the elasticity of a plastic arm, the common production-mouse construction (ASSUMED from general practice; no teardown of a specific mouse is cited).',
                                         f'Rigid checks rotate the button about the leaf pseudo-rigid-body pivot at ({hx:.2f}, {hy:.2f}) (Howell 2001, gamma 0.85).',
                                         'Printed in place with the shell (rim-down); the 0.4 mm running gap separates face and shell on all sides.',
                                         'Adjustment (switch fitted, output read): with the button at rest turn the actuator screw in until the switch operates, out until it releases, then '
                                         f'{p["rest_steps_back"]} steps of 1/16 turn further out.']},
        'verification_plan': [
            'Single solids, volume agreement, automatic pair overlap and bounds.',
            f'Button (actuator carried) clear of the shell by at least 0.15 mm from rest to {a["deep"]:.3f} deg, the dog point at the switch body top for the deepest registered switch, with pivot play.',
            'Leaf spring: beam-theory stiffness, press force (leaf plus largest registered switch force) inside the band, static stress inside the allowance; fatigue UNKNOWN.',
            'Outer form outside the side-button region matches the base skin.',
            'Sampled printed wall thickness of shell and button (the leaf is a deliberate flexure, checked by beam theory instead).',
            'Every registered switch profile is evaluated; profiles with UNKNOWN values are reported unverified.'],
        'operations': ops,
        'outputs': [{'part_id': 'shell', 'node': 'shell_part', 'manufacturing_process': 'FDM, PETG (ASSUMED), printed in place with leaf and button'},
                    {'part_id': 'leaf_spring', 'node': 'leaf', 'manufacturing_process': 'FDM, printed in place: continuous with shell root and button pad'},
                    {'part_id': 'button', 'node': 'button', 'manufacturing_process': 'FDM, printed in place on the leaf'},
                    {'part_id': 'actuator_screw', 'node': 'actuator_screw', 'manufacturing_process': 'Purchased M2 x 5 dog-point grub screw (ISO 4028), self-tapped'},
                    {'part_id': 'switch_body', 'node': 'switch_body', 'manufacturing_process': f'Placeholder for a purchased switch (profile {profile.id})'},
                    {'part_id': 'switch_pin', 'node': 'switch_pin', 'manufacturing_process': 'Placeholder for the switch pin'}],
        'clearance_checks': [
            {'id': 'rest-button-shell', 'part_a': 'button', 'part_b': 'shell', 'min_mm': .35},
            {'id': 'rest-actuator-thread-switch-body', 'part_a': 'actuator_screw', 'part_b': 'switch_body', 'min_mm': .3}],
        'press_fits': [{'id': 'actuator-thread', 'part_a': 'actuator_screw', 'part_b': 'button',
                        'min_overlap_mm3': .7 * ring * engaged, 'max_overlap_mm3': 1.3 * ring * engaged,
                        'basis': 'M2 thread engaged in the printed plunger, modeled as an interference annulus.'}],
        'rotation_checks': [
            {'id': 'press-to-deepest-clear-of-shell', 'moving_part': 'button', 'carried_parts': ['actuator_screw'], 'obstacles': ['shell'],
             **axis, 'end_deg': a['deep'], 'samples': 3, 'max_samples': 9, 'min_mm': .15, 'axis_play_mm': p['pivot_play_mm']},
            {'id': 'rise-clear-of-shell', 'moving_part': 'button', 'carried_parts': ['actuator_screw'], 'obstacles': ['shell'],
             **axis, 'end_deg': .3, 'samples': 3, 'max_samples': 9, 'min_mm': .15, 'axis_play_mm': p['pivot_play_mm']}],
        'wall_checks': [
            {'id': 'shell-printed-wall', 'part': 'shell', 'min_mm': p['min_printed_wall_mm'], 'samples_per_face': 10},
            {'id': 'button-printed-wall', 'part': 'button', 'min_mm': p['min_printed_wall_mm'], 'samples_per_face': 10}],
        'flexure_checks': [
            {'id': 'leaf-spring-beam', 'part': 'leaf_spring', 'beam_node': 'leaf', 'length_axis': 'x', 'fixed_end': 'min', 'bend_axis': 'y',
             'material': 'prusament_petg', 'orientation': 'horizontal', 'strength_basis': 'tensile_yield',
             'deflection_mm': tip_deflection, 'min_force_n': p['force_band_min_n'], 'max_force_n': p['force_band_max_n'],
             'force_basis': ASSUMED['force_band'], 'switch_profiles': list(SWITCH_PROFILES),
             'beam_force_ratio': PRBM_GAMMA * leaf_len / lever, 'switch_force_ratio': 1.,
             'ratio_basis': f'Moment balance about the pivot: leaf tip force acts at {PRBM_GAMMA * leaf_len:.2f} mm, the plunger (switch and press point) at {lever:.2f} mm.',
             'stress_allowance': p['stress_allowance'], 'allowance_basis': ASSUMED['stress_allowance']}],
        'base_shape_checks': [{'id': 'outer-form-matches-base', 'base_node': 'outer', 'parts': ['shell', 'button'], 'tolerance_mm': .05,
                               'samples_per_face': 16, 'regions': [
            {'id': 'side-button-region', 'kind': 'allowed_change', 'reason': 'Changes around the side buttons are allowed (window, running gap, access hole).',
             'lo_mm': [wl - 1., 20., zl - 1.], 'hi_mm': [p['window_x_max_mm'] + 3., 40., zh + 1.]},
            {'id': 'open-bottom', 'kind': 'not_in_base', 'reason': 'The base outer form is the skin; its bottom cap is the open rim.',
             'lo_mm': [-70., -40., -.1], 'hi_mm': [70., 40., .1]}]}],
        'unverified_requirements': [
            '押しやすさ（押下力・ストローク感・クリック感）は実機試験していない。',
            f'Switch profiles (rigid stack from datasheets): {summary}.',
            'Leaf spring: beam theory only (small deflection, rigid root, typical datasheet values); creep, fatigue and print-quality effects are UNKNOWN.',
            'Pseudo-rigid-body pivot is an approximation; the leaf tip also translates, covered only by the stated pivot-play envelope.',
            'Switch bottoming force is carried by the switch (no hard stop); its maximum rated force is not in the registered datasheets (UNKNOWN).',
            'Print-in-place gap and leaf thickness depend on printer calibration; PCB position and the real shell were not measured.',
            'Wall checks are sampled minima of the stated parts, not a proof of minimum wall or of strength.'],
    }


# ---------------------------------------------------------------------------
# Revision 15: separately printed flexure carrier (repairs the revision-14
# round-1 findings and follows the owner policy: ABS only, no screws except
# those supplied with the OP1).
# - No outward stop (button floated on the soft leaf, pushed out by the switch)
#   -> a rest-stop tab under a shell lug; at rest the actuator does not touch
#   the switch pin (fixed gap), so nothing pushes the button outward.
# - Print-in-place impossible (horizontal 0.4 mm gaps) -> the button, leaf and
#   mounting block are one separate print, fixed to two shell posts by two
#   separately printed insert pins (press fit in the post, clearance in the block).
# - Purchased actuator screw removed -> printed actuator insert whose length is
#   generated per switch profile (fixed gap; needs the datasheet free position).
# - Leaf: ABS (cited), wider, longer, root stress concentration ASSUMED 1.5,
#   twist from an off-axis press checked, pivot taken at the end-moment PRBM
#   point with an envelope reaching the end-force point.
# ---------------------------------------------------------------------------
from cadmcp_brain.studio.recipe import PRBM_GAMMA_END_MOMENT, beam_twist_deg
from cadmcp_brain.studio.materials import DEFAULT_MATERIAL, MATERIALS

PC = {
    'shell_wall_mm': 1.5, 'window_x_min_mm': -10., 'window_x_max_mm': 14., 'window_z_min_mm': 10., 'window_z_max_mm': 18., 'window_gap_mm': .4,
    'leaf_root_x_mm': -31., 'leaf_free_x_mm': -9., 'leaf_y_min_mm': 17.5, 'leaf_thickness_mm': 1.6, 'leaf_z_min_mm': 6.5, 'leaf_z_max_mm': 18.5,
    'pad_z_min_mm': 10.5, 'pad_z_max_mm': 17.5, 'pivot_play_mm': .05,
    'block_x_mm': 5., 'block_y_min_mm': 16.5, 'block_y_max_mm': 20., 'pad_x_mm': 2.5,
    'pin_radius_mm': 1., 'pin_clearance_mm': .1, 'pin_interference_mm': .05, 'pin_engagement_mm': 3.,
    'pin_head_radius_mm': 1.6, 'pin_head_height_mm': .8, 'post_radius_mm': 2.2, 'pin_z_mm': (9., 14.5),
    'stop_lug_y_mm': 26.5, 'stop_tab_thickness_mm': 1.5, 'stop_z_min_mm': 12., 'stop_z_max_mm': 15., 'stop_reach_mm': 2.5,
    'plunger_x_min_mm': -.5, 'plunger_x_max_mm': 4.5, 'plunger_tip_y_mm': 24., 'plunger_z_min_mm': 10.5, 'plunger_z_max_mm': 15.5,
    'spine_z_min_mm': 12.6, 'spine_z_max_mm': 15.4, 'spine_y_min_mm': 26.,
    'insert_radius_mm': 1., 'insert_hole_radius_mm': .95, 'insert_engagement_mm': 4., 'design_insert_protrusion_mm': 1.2,
    'rest_gap_mm': .05, 'deep_margin_deg': .03, 'min_printed_wall_mm': 1.2,
    'force_band_min_n': .3, 'force_band_max_n': 3., 'stress_allowance': .5, 'stress_concentration': 1.5,
    'edge_press_force_n': 3., 'edge_press_offset_mm': 4., 'poisson_ratio': .35, 'max_twist_deg': 3., 'twist_min_gap_mm': .05,
}
ASSUMED_V15 = {
    'material': f'Owner policy: ABS only; {MATERIALS[DEFAULT_MATERIAL].name} datasheet values (cited) used for the leaf.',
    'screws': 'Owner policy: no screws except those supplied with the OP1; this carrier uses printed insert pins and a printed actuator insert.',
    'stress_concentration': 'ASSUMED 1.5 at the sharp leaf root and tip corners (no fillet modeled); a fillet would lower it.',
    'twist': 'ASSUMED 3 N press at the face edge 4 mm off the leaf centreline; Poisson ratio 0.35 ASSUMED (not in the datasheet); twist limit 3 deg ASSUMED.',
    'pivot': 'Pivot at the end-moment PRBM point (gamma 0.7346, Howell 2001); the envelope reaches the end-force point (gamma 0.85).',
    'pcb': 'ASSUMED switch base plane placed for the Zippy DF profile with a 1.2 mm insert protrusion; other profiles get their own insert length.',
}


def pivot_v15(p=PC):
    length = p['leaf_free_x_mm'] - p['leaf_root_x_mm']
    return p['leaf_root_x_mm'] + (1 - PRBM_GAMMA_END_MOMENT) * length, p['leaf_y_min_mm'] + p['leaf_thickness_mm'] / 2


def pivot_envelope_v15(p=PC):
    """Distance between the end-moment and end-force PRBM pivots, used as the pivot-play envelope."""
    return (PRBM_GAMMA - PRBM_GAMMA_END_MOMENT) * (p['leaf_free_x_mm'] - p['leaf_root_x_mm'])


def _lever_v15(p):
    return (p['plunger_x_min_mm'] + p['plunger_x_max_mm']) / 2 - pivot_v15(p)[0]


def _base_y_v15(p):
    design = SWITCH_PROFILES[DESIGN_SWITCH]
    tip = p['plunger_tip_y_mm'] - p['design_insert_protrusion_mm']
    return tip - p['rest_gap_mm'] - design.free_position.value


def insert_fit_v15(profile, p=PC):
    """Printed actuator insert for one switch profile: fixed gap above the pin's free position (max)."""
    need = ('free_position', 'operating_position', 'body_height', 'plunger_width', 'body_length', 'body_width')
    missing = [k for k in need if not getattr(profile, k).known]
    if missing:
        return {'profile': profile.id, 'verdict': 'unverified', 'missing': missing,
                'reason': 'A fixed-gap insert needs the free position and body data; UNKNOWN values give no insert and no pass.'}
    if profile.height_datum != 'body_bottom':
        return {'profile': profile.id, 'verdict': 'unverified', 'missing': ['body_bottom_datum'],
                'reason': 'Datasheet heights are not referenced to the body bottom (PCB plane); no insert length is derived.'}
    base = _base_y_v15(p); fp = profile.free_position.value
    op, op_tol = profile.operating_position.value, profile.operating_position.tolerance or 0.
    top, top_tol = profile.body_height.value, profile.body_height.tolerance or 0.
    tip = base + fp + p['rest_gap_mm']; protrusion = p['plunger_tip_y_mm'] - tip
    to_operate = p['rest_gap_mm'] + fp - (op - op_tol)
    to_flush = p['rest_gap_mm'] + fp - (top - top_tol)
    ok = .3 <= protrusion <= 3.
    return {'profile': profile.id, 'verdict': 'pass' if ok else 'fail', 'insert_protrusion_mm': protrusion,
            'travel_to_operate_max_mm': to_operate, 'travel_to_pin_flush_max_mm': to_flush,
            'scope': 'Fixed gap above the datasheet maximum free position; the switch takes the overtravel. Protrusion must lie in 0.3-3 mm.'}


def angles_v15(p=PC):
    lever = _lever_v15(p)
    fits = [insert_fit_v15(pr, p) for pr in SWITCH_PROFILES.values()]
    deep = max(f['travel_to_pin_flush_max_mm'] for f in fits if f['verdict'] == 'pass')
    operate = max(f['travel_to_operate_max_mm'] for f in fits if f['verdict'] == 'pass')
    return {'operate_latest': -math.degrees(operate / lever), 'deep': -math.degrees(deep / lever) - p['deep_margin_deg'],
            'deep_travel_mm': deep}


def side_button_carrier_recipe(request=REQUEST, p=None):
    p = dict(PC if p is None else p)
    wl, zl, zh, g = p['window_x_min_mm'], p['window_z_min_mm'], p['window_z_max_mm'], p['window_gap_mm']
    hx, hy = pivot_v15(p); a = angles_v15(p); lever = _lever_v15(p)
    profile = SWITCH_PROFILES[DESIGN_SWITCH]; base_y = _base_y_v15(p)
    ly0, ly1 = p['leaf_y_min_mm'], p['leaf_y_min_mm'] + p['leaf_thickness_mm']; lz0, lz1 = p['leaf_z_min_mm'], p['leaf_z_max_mm']
    xr, xf = p['leaf_root_x_mm'], p['leaf_free_x_mm']; L = xf - xr
    bx0 = xr - p['block_x_mm']; by0, by1 = p['block_y_min_mm'], p['block_y_max_mm']
    def far_edge(offset):
        x0, y0 = p['window_x_max_mm'], 29.5; n = [x0 - hx, y0 - hy]; ln = math.hypot(*n); n = [n[0] / ln, n[1] / ln]; t = [-n[1], n[0]]
        x0 += offset * n[0]; y0 += offset * n[1]
        return [[x0 + (y - y0) / t[1] * t[0], y] for y in (20., 40.)]
    far, far_gap = far_edge(0.), far_edge(g)
    yl = p['stop_lug_y_mm']; xg = max(pt[0] for pt in far_gap)  # gap edge, outermost
    tab_x0 = p['window_x_max_mm'] - 2.; tab_x1 = xg + p['stop_reach_mm']
    px = (p['plunger_x_min_mm'] + p['plunger_x_max_mm']) / 2; pz = (p['plunger_z_min_mm'] + p['plunger_z_max_mm']) / 2
    ins_r, hole_r, eng = p['insert_radius_mm'], p['insert_hole_radius_mm'], p['insert_engagement_mm']
    tip_y = p['plunger_tip_y_mm'] - p['design_insert_protrusion_mm']
    r_pin, c, inter, peng = p['pin_radius_mm'], p['pin_clearance_mm'], p['pin_interference_mm'], p['pin_engagement_mm']
    pin_x = (bx0 + xr) / 2
    ops = [
        {'id': 'outer', 'op': 'spline_loft', 'function_id': 'F6_connect_shell', 'reason': 'Base outer skin (stand-in for a scanned shell).',
         'sections': [{'z_mm': z, 'points_mm': _ellipse(a_, b_)} for z, a_, b_ in SECTIONS]},
        {'id': 'cavity', 'op': 'spline_loft', 'function_id': 'F6_connect_shell', 'reason': 'Inner cavity, open at the bottom.',
         'sections': _inset_sections(p['shell_wall_mm'])},
        {'id': 'hollow', 'op': 'difference', 'function_id': 'F6_connect_shell', 'reason': 'Shell skin = outer minus cavity.', 'operands': ['outer', 'cavity']},
        {'id': 'window', 'op': 'polygon_extrusion', 'function_id': 'F1_transmit_force', 'reason': 'Button skin region; far edge normal to the pivot radius.',
         'points_mm': [[wl, 20.], far[0], far[1], [wl, 40.]], 'height_mm': zh - zl, 'origin_mm': [0., 0., zl]},
        {'id': 'window_gap', 'op': 'polygon_extrusion', 'function_id': 'F6_connect_shell', 'reason': 'Window with the 0.4 mm running gap on all sides.',
         'points_mm': [[wl - g, 20.], far_gap[0], far_gap[1], [wl - g, 40.]], 'height_mm': zh - zl + 2 * g, 'origin_mm': [0., 0., zl - g]},
        {'id': 'shell_open', 'op': 'difference', 'function_id': 'F6_connect_shell', 'reason': 'Open the window.', 'operands': ['hollow', 'window_gap']},
        *[_cyl_y(f'post_{i}', 'F2_mount', f'Shell post {i} for an insert pin.', p['post_radius_mm'], (pin_x, by1, z), 12.) for i, z in enumerate(p['pin_z_mm'], 1)],
        *[{'id': f'post_{i}_in', 'op': 'intersection', 'function_id': 'F2_mount', 'reason': f'Post {i} stays inside the outer skin.', 'operands': [f'post_{i}', 'outer']}
          for i in (1, 2)],
        *[_cyl_y(f'post_{i}_hole', 'F2_mount', f'Press-fit hole for insert pin {i}.', r_pin - inter, (pin_x, by1 - .01, z), peng + .01) for i, z in enumerate(p['pin_z_mm'], 1)],
        _box('stop_lug_box', 'F5_rest_stop', 'Rest-stop lug under the skin beyond the window far edge.', [xg + .3, yl, p['stop_z_min_mm'] - .5], [tab_x1 + .5, 40., p['stop_z_max_mm'] + .5]),
        {'id': 'rest_stop', 'op': 'intersection', 'function_id': 'F5_rest_stop', 'reason': 'Lug grown from the inner skin (same print as the shell).',
         'operands': ['stop_lug_box', 'cavity']},
        {'id': 'shell_raw', 'op': 'union', 'function_id': 'F6_connect_shell', 'reason': 'Shell with the two posts.', 'operands': ['shell_open', 'post_1_in', 'post_2_in']},
        {'id': 'shell', 'op': 'difference', 'function_id': 'F6_connect_shell', 'reason': 'Posts with their pin holes.', 'operands': ['shell_raw', 'post_1_hole', 'post_2_hole']},
        _box('block_raw', 'F2_mount', 'Carrier mounting block (separate print with leaf and button).', [bx0, by0, lz0], [xr, by1, lz1]),
        *[_cyl_y(f'block_hole_{i}', 'F2_mount', f'Clearance hole for insert pin {i}.', r_pin + c, (pin_x, by0 - .01, z), by1 - by0 + .02) for i, z in enumerate(p['pin_z_mm'], 1)],
        {'id': 'carrier_block', 'op': 'difference', 'function_id': 'F2_mount', 'reason': 'Mounting block with pin clearance holes.', 'operands': ['block_raw', 'block_hole_1', 'block_hole_2']},
        _box('leaf', 'F2_guide_button', 'Leaf spring: guide and return element.', [xr, ly0, lz0], [xf, ly1, lz1]),
        {'id': 'skin_piece', 'op': 'intersection', 'function_id': 'F1_transmit_force', 'reason': 'Button face is the removed skin piece.', 'operands': ['hollow', 'window']},
        _box('pad_box', 'F2_guide_button', 'Pad joining the leaf free end to the face (window height only).', [xf, ly0, p['pad_z_min_mm']], [xf + p['pad_x_mm'], 40., p['pad_z_max_mm']]),
        {'id': 'pad', 'op': 'intersection', 'function_id': 'F2_guide_button', 'reason': 'Pad inside the outer skin.', 'operands': ['pad_box', 'outer']},
        _box('spine_box', 'F1_transmit_force', 'Spine stiffening the face.', [xf, p['spine_y_min_mm'], p['spine_z_min_mm']], [p['window_x_max_mm'] - 1.5, 40., p['spine_z_max_mm']]),
        {'id': 'spine', 'op': 'intersection', 'function_id': 'F1_transmit_force', 'reason': 'Spine inside the outer skin.', 'operands': ['spine_box', 'outer']},
        _box('plunger_box', 'F3_actuate_switch', 'Plunger carrying the actuator insert.', [p['plunger_x_min_mm'], p['plunger_tip_y_mm'], p['plunger_z_min_mm']], [p['plunger_x_max_mm'], 40., p['plunger_z_max_mm']]),
        {'id': 'plunger', 'op': 'intersection', 'function_id': 'F3_actuate_switch', 'reason': 'Plunger inside the outer skin.', 'operands': ['plunger_box', 'outer']},
        _box('tab_riser_box', 'F5_rest_stop', 'Riser carrying the rest-stop tab from the face.', [tab_x0, yl - p['stop_tab_thickness_mm'], p['stop_z_min_mm']], [p['window_x_max_mm'] - .5, 40., p['stop_z_max_mm']]),
        {'id': 'tab_riser', 'op': 'intersection', 'function_id': 'F5_rest_stop', 'reason': 'Riser inside the outer skin.', 'operands': ['tab_riser_box', 'outer']},
        _box('stop_tab', 'F5_rest_stop', 'Rest-stop tab: its top meets the lug bottom at rest.', [tab_x0, yl - p['stop_tab_thickness_mm'], p['stop_z_min_mm']], [tab_x1, yl, p['stop_z_max_mm']]),
        {'id': 'button_solid', 'op': 'union', 'function_id': 'F1_transmit_force', 'reason': 'Face, pad, spine, plunger and rest-stop tab.',
         'operands': ['skin_piece', 'pad', 'spine', 'plunger', 'tab_riser', 'stop_tab']},
        _cyl_y('insert_hole', 'F3_actuate_switch', 'Press-fit hole for the printed actuator insert.', hole_r, (px, p['plunger_tip_y_mm'] - .01, pz), eng + .01),
        {'id': 'button', 'op': 'difference', 'function_id': 'F3_actuate_switch', 'reason': 'Button with the insert hole (blind: the face stays closed).', 'operands': ['button_solid', 'insert_hole']},
        _cyl_y('actuator_insert', 'F3_actuate_switch', 'Printed actuator insert (length per switch profile).', ins_r, (px, tip_y, pz), p['plunger_tip_y_mm'] + eng - tip_y),
        *[_cyl_y(f'pin_{i}_shank', 'F2_mount', f'Insert pin {i} shank.', r_pin, (pin_x, by0, z), by1 - by0 + peng) for i, z in enumerate(p['pin_z_mm'], 1)],
        *[_cyl_y(f'pin_{i}_head', 'F2_mount', f'Insert pin {i} head.', p['pin_head_radius_mm'], (pin_x, by0 - p['pin_head_height_mm'], z), p['pin_head_height_mm']) for i, z in enumerate(p['pin_z_mm'], 1)],
        *[{'id': f'pin_{i}', 'op': 'union', 'function_id': 'F2_mount', 'reason': f'Separately printed insert pin {i}.', 'operands': [f'pin_{i}_shank', f'pin_{i}_head']} for i in (1, 2)],
        _box('switch_body', 'F3_actuate_switch', f'Switch body from profile {profile.id} on the ASSUMED PCB plane.',
             [px - profile.body_length.value / 2, base_y, pz - profile.body_width.value / 2], [px + profile.body_length.value / 2, base_y + profile.body_height.value, pz + profile.body_width.value / 2]),
        _box('switch_pin', 'F3_actuate_switch', 'Switch pin at its maximum free position (pin x size UNKNOWN, 1.2 mm assumed).',
             [px - .6, base_y + profile.body_height.value, pz - profile.plunger_width.value / 2], [px + .6, base_y + profile.free_position.value, pz + profile.plunger_width.value / 2]),
    ]
    axis = {'axis_origin_mm': [hx, hy, 0.], 'axis_direction': [0., 0., 1.]}
    env = pivot_envelope_v15(p)
    material = MATERIALS[DEFAULT_MATERIAL]
    e_mpa = material.flexural_modulus_gpa['horizontal'] * 1000.
    torque = p['edge_press_force_n'] * p['edge_press_offset_mm']
    twist = beam_twist_deg(torque, L, lz1 - lz0, p['leaf_thickness_mm'], e_mpa, p['poisson_ratio'])
    tip_defl = math.sin(math.radians(-a['deep'])) * PRBM_GAMMA * L
    fits = [insert_fit_v15(pr, p) for pr in SWITCH_PROFILES.values()]
    summary = '; '.join(f"{f['profile']}: {f['verdict']}" + (f" (insert {f['insert_protrusion_mm']:.2f} mm)" if f['verdict'] == 'pass' else f" (missing {', '.join(f.get('missing', []))})") for f in fits)
    ring_ins = math.pi * (ins_r ** 2 - hole_r ** 2) * eng
    ring_pin = math.pi * (r_pin ** 2 - (r_pin - inter) ** 2) * peng
    twist_axis = {'axis_origin_mm': [0., hy, (lz0 + lz1) / 2], 'axis_direction': [1., 0., 0.]}
    return {
        'title': 'Side button test subject, revision 15 (separately printed ABS flexure carrier, insert pins)',
        'original_request': request,
        'design_parameters': {k: float(v) for k, v in p.items() if not isinstance(v, tuple)},
        'parameter_basis': {k: 'ASSUMED test-subject proposal; not measured from a real mouse, switch or PCB.' for k, v in p.items() if not isinstance(v, tuple)},
        'functions': {'F1_transmit_force': 'Transmit thumb force from the skin piece into the button.',
                      'F2_guide_button': 'Guide and return the button with a leaf spring.',
                      'F2_mount': 'Fix the carrier to the shell with printed insert pins.',
                      'F3_actuate_switch': 'Press the switch pin through a fixed gap.',
                      'F5_rest_stop': 'Hold the face flush at rest against outward motion.',
                      'F6_connect_shell': 'Keep the outer skin; open only the side-button window.'},
        'protected_constraints': ['Outer skin outside the side-button region is not changed (checked against the base skin).',
                                  'Owner policy: ABS only; no screws except those supplied with the OP1.'],
        'design_basis': {'kind': 'first_principles',
                         'summary': 'Separately printed ABS carrier: face on a leaf spring, rest stop under a shell lug, fixed by two printed insert pins; the switch takes the overtravel.',
                         'assumptions': list(ASSUMED_V15.values()) + [
                             'Printing: shell rim-down with supports under the window lintel; carrier printed with the leaf thickness along the build axis so leaf bending runs in the layer plane (ASSUMED).',
                             'Assembly: carrier in from the cavity side until the tab meets the lug, then the two pins pressed through the block into the posts; actuator insert pressed into the plunger before.',
                             'At rest the actuator does not touch the switch pin (fixed gap), so no switch force pushes the face outward; the leaf is unstressed with the tab on the lug.']},
        'verification_plan': [
            'Pair overlap and bounds; declared press fits (pins in posts, insert in plunger).',
            'Rest: outward rotation is blocked by the lug at every hinge-play offset.',
            f'Press: button with insert clear of the shell by at least 0.15 mm, and of the lug, to {a["deep"]:.3f} deg (pin flush for the deepest registered switch), about the end-moment pivot and again about the end-force pivot {env:.2f} mm further out.',
            f'Twist (abuse case, ASSUMED 3 N at the face edge): at +/-{twist:.2f} deg about the leaf axis the running gap may narrow but stays at least {p["twist_min_gap_mm"]:.2f} mm (normal presses keep 0.15 mm).',
            'Leaf: beam-theory stiffness, press force (leaf plus largest registered switch force), static stress with the root stress concentration, and twist.',
            'Outer form outside the side-button region matches the base skin; sampled printed walls of shell and button.',
            'Every registered switch profile gets an insert length or is reported unverified.'],
        'operations': ops,
        'outputs': [{'part_id': 'shell', 'node': 'shell', 'manufacturing_process': 'FDM ABS, rim-down'},
                    {'part_id': 'rest_stop', 'node': 'rest_stop', 'manufacturing_process': 'FDM ABS, same print as the shell'},
                    {'part_id': 'carrier_block', 'node': 'carrier_block', 'manufacturing_process': 'FDM ABS, one carrier print with leaf and button'},
                    {'part_id': 'leaf_spring', 'node': 'leaf', 'manufacturing_process': 'FDM ABS, same carrier print'},
                    {'part_id': 'button', 'node': 'button', 'manufacturing_process': 'FDM ABS, same carrier print'},
                    {'part_id': 'actuator_insert', 'node': 'actuator_insert', 'manufacturing_process': f'FDM ABS insert; protrusion {p["design_insert_protrusion_mm"]:.2f} mm for {profile.id}'},
                    {'part_id': 'pin_1', 'node': 'pin_1', 'manufacturing_process': 'FDM ABS insert pin (separate print)'},
                    {'part_id': 'pin_2', 'node': 'pin_2', 'manufacturing_process': 'FDM ABS insert pin (separate print)'},
                    {'part_id': 'switch_body', 'node': 'switch_body', 'manufacturing_process': f'Placeholder for a purchased switch (profile {profile.id})'},
                    {'part_id': 'switch_pin', 'node': 'switch_pin', 'manufacturing_process': 'Placeholder for the switch pin'}],
        'press_fits': [{'id': 'insert-in-plunger', 'part_a': 'actuator_insert', 'part_b': 'button', 'min_overlap_mm3': .7 * ring_ins, 'max_overlap_mm3': 1.3 * ring_ins,
                        'basis': 'ASSUMED 0.05 mm radial interference over the insert engagement.'},
                       *[{'id': f'pin-{i}-in-post', 'part_a': f'pin_{i}', 'part_b': 'shell', 'min_overlap_mm3': .7 * ring_pin, 'max_overlap_mm3': 1.3 * ring_pin,
                          'basis': f'ASSUMED {inter:.2f} mm radial interference over {peng:.1f} mm in the printed post.'} for i in (1, 2)]],
        'clearance_checks': [
            {'id': 'rest-gap-insert-to-pin', 'part_a': 'actuator_insert', 'part_b': 'switch_pin', 'min_mm': p['rest_gap_mm'] - 1e-3},
            {'id': 'rest-button-shell', 'part_a': 'button', 'part_b': 'shell', 'min_mm': .35},
            {'id': 'leaf-to-shell', 'part_a': 'leaf_spring', 'part_b': 'shell', 'min_mm': .4},
            {'id': 'pin-1-clear-of-leaf', 'part_a': 'pin_1', 'part_b': 'leaf_spring', 'min_mm': .4}],
        'motion_checks': [{'id': f'pin-{i}-insertion', 'moving_part': f'pin_{i}', 'obstacles': ['carrier_block', 'leaf_spring', 'button'],
                           'start_translation_mm': [0., -10., 0.], 'translation_end_mm': [0., 10. - c, 0.], 'samples': 9, 'max_samples': 33, 'min_mm': c - 1e-3} for i in (1, 2)],
        'rotation_checks': [
            {'id': 'rest-outward-blocked-by-lug', 'moving_part': 'button', 'carried_parts': ['actuator_insert'], 'obstacles': ['rest_stop'], **axis,
             'end_deg': .5, 'expect': 'blocked', 'samples': 5, 'max_samples': 5, 'axis_play_mm': p['pivot_play_mm']},
            {'id': 'press-to-deepest-clear-of-shell', 'moving_part': 'button', 'carried_parts': ['actuator_insert'], 'obstacles': ['shell'], **axis,
             'end_deg': a['deep'], 'samples': 3, 'max_samples': 3, 'min_mm': .15, 'axis_play_mm': p['pivot_play_mm']},
            {'id': 'press-to-deepest-end-force-pivot', 'moving_part': 'button', 'carried_parts': ['actuator_insert'], 'obstacles': ['shell'],
             'axis_origin_mm': [hx + env, hy, 0.], 'axis_direction': [0., 0., 1.],
             # This sweep is itself the pivot-location envelope, so no extra play offsets.
             'end_deg': -math.degrees(a['deep_travel_mm'] / (lever - env)) - p['deep_margin_deg'], 'samples': 3, 'max_samples': 3, 'min_mm': .15},
            {'id': 'press-leaves-the-lug', 'moving_part': 'button', 'carried_parts': ['actuator_insert'], 'obstacles': ['rest_stop'], **axis,
             'start_deg': -.05, 'end_deg': a['deep'], 'samples': 3, 'max_samples': 3, 'min_mm': 0.},
            {'id': 'twist-positive-clear', 'moving_part': 'button', 'carried_parts': ['actuator_insert'], 'obstacles': ['shell'], **twist_axis,
             'end_deg': twist, 'samples': 2, 'max_samples': 3, 'min_mm': p['twist_min_gap_mm']},
            {'id': 'twist-negative-clear', 'moving_part': 'button', 'carried_parts': ['actuator_insert'], 'obstacles': ['shell'], **twist_axis,
             'end_deg': -twist, 'samples': 2, 'max_samples': 3, 'min_mm': p['twist_min_gap_mm']}],
        'wall_checks': [{'id': 'shell-printed-wall', 'part': 'shell', 'min_mm': p['min_printed_wall_mm'], 'samples_per_face': 10},
                        {'id': 'button-printed-wall', 'part': 'button', 'min_mm': p['min_printed_wall_mm'], 'samples_per_face': 10}],
        'flexure_checks': [{'id': 'leaf-spring-beam', 'part': 'leaf_spring', 'beam_node': 'leaf', 'length_axis': 'x', 'fixed_end': 'min', 'bend_axis': 'y',
                            'material': DEFAULT_MATERIAL, 'orientation': 'horizontal', 'strength_basis': 'tensile_strength',
                            'deflection_mm': tip_defl, 'min_force_n': p['force_band_min_n'], 'max_force_n': p['force_band_max_n'],
                            'force_basis': 'ASSUMED press-force band 0.3-3 N at the plunger.', 'switch_profiles': list(SWITCH_PROFILES),
                            'beam_force_ratio': PRBM_GAMMA * L / lever, 'switch_force_ratio': 1.,
                            'ratio_basis': f'Moment balance about the pivot: leaf tip force at {PRBM_GAMMA * L:.2f} mm (end-force model, conservative for stress), plunger at {lever:.2f} mm.',
                            'stress_allowance': p['stress_allowance'], 'allowance_basis': 'ASSUMED half of the datasheet tensile strength (yield not published); fatigue UNKNOWN.',
                            'stress_concentration': p['stress_concentration'], 'stress_concentration_basis': ASSUMED_V15['stress_concentration'],
                            'torque_nmm': torque, 'poisson_ratio': p['poisson_ratio'], 'torque_basis': ASSUMED_V15['twist'], 'max_twist_deg': p['max_twist_deg']}],
        'base_shape_checks': [{'id': 'outer-form-matches-base', 'base_node': 'outer', 'parts': ['shell', 'button'], 'tolerance_mm': .05, 'samples_per_face': 12, 'regions': [
            {'id': 'side-button-region', 'kind': 'allowed_change', 'reason': 'Changes around the side buttons are allowed (window and running gap).',
             'lo_mm': [wl - 1., 20., zl - 1.], 'hi_mm': [p['window_x_max_mm'] + 3., 40., zh + 1.]},
            {'id': 'open-bottom', 'kind': 'not_in_base', 'reason': 'The base outer form is the skin; its bottom cap is the open rim.', 'lo_mm': [-70., -40., -.1], 'hi_mm': [70., 40., .1]}]}],
        'unverified_requirements': [
            '押しやすさ（押下力・ストローク感・クリック感）は実機試験していない。',
            f'Switch profiles (fixed-gap insert from datasheets): {summary}.',
            'Leaf: beam theory only (small deflection, rigid root, typical datasheet values, ASSUMED stress concentration and Poisson ratio); creep and fatigue UNKNOWN.',
            'Switch bottoming force is carried by the switch (no hard stop); its maximum rated force is not in the registered datasheets (UNKNOWN).',
            'Pin and insert retention in printed ABS, print accuracy of the 0.4 mm gaps and support removal near the leaf are not qualified.',
            'PCB plane is ASSUMED; the real board and shell were not measured. OP1-supplied screws are not used by this carrier.',
            'Wall checks are sampled minima of the stated parts, not a proof of minimum wall or of strength.'],
    }


def _cyl_y(node_id, function_id, reason, radius, origin, height):
    return {'id': node_id, 'op': 'cylinder', 'function_id': function_id, 'reason': reason,
            'radius_mm': radius, 'height_mm': height, 'origin_mm': list(origin), 'axis': [0., 1., 0.]}


# ---------------------------------------------------------------------------
# Revision 16: parallel-leaf carrier (repairs the revision-15 round-1 findings).
# - Twist: one leaf could not hold an edge press inside the 0.15 mm gap ->
#   two leaves 8 mm apart (parallel guide): the face translates, an edge
#   press is held by in-plane bending of both leaves; the 0.15 mm criterion
#   is kept for the edge-press twist.
# - Carrier not located (pins in clearance, in line) -> two pins on a
#   diagonal, press fit in both the block and the shell posts (no play), and
#   along X so the press load is shear on the pins, not pull-out.
# - Sharp leaf corners -> R1 fillets modeled at both ends on the inner faces;
#   the outer faces run flush into the block and pad (printable flat).
# - Rest gap from print accuracy -> actuator inserts in 0.05 mm length steps,
#   the longest one that does not operate the switch at rest is fitted.
# - Flow record and function ids follow the decomposition (F1-F6).
# ---------------------------------------------------------------------------
PP = dict(PC)
for _k in ('leaf_root_x_mm', 'leaf_free_x_mm', 'leaf_y_min_mm', 'leaf_thickness_mm', 'leaf_z_min_mm', 'leaf_z_max_mm',
           'block_x_mm', 'block_y_min_mm', 'block_y_max_mm', 'pin_engagement_mm', 'pin_z_mm', 'max_twist_deg',
           'twist_min_gap_mm', 'stress_concentration', 'pivot_play_mm'):
    PP.pop(_k, None)
PP.update({'leaf_root_x_mm': -31., 'leaf_free_x_mm': -9., 'leaf_thickness_mm': .7, 'leaf_z_min_mm': 8.5, 'leaf_z_max_mm': 18.5,
           'leaf_a_y_mm': 12., 'leaf_b_y_mm': 20., 'fillet_radius_mm': 1., 'block_x_mm': 4.,
           'pin_block_interference_mm': .03, 'pin_post_engagement_mm': 3., 'pin_y_mm': (15., 17.7), 'pin_z_mm': (10.5, 16.5),
           'post_x_mm': -50., 'stress_concentration': 1.5, 'insert_step_mm': .05, 'twist_min_gap_mm': .15,
           'parasitic_shortening_factor': .6})


def deep_travel_v16(p=PP):
    fits = [insert_fit_v15(pr, {**PC, **{k: v for k, v in p.items() if k in PC}}) for pr in SWITCH_PROFILES.values()]
    return max(f['travel_to_pin_flush_max_mm'] for f in fits if f['verdict'] == 'pass') + p['insert_step_mm']


def twist_v16(p=PP):
    """Edge-press twist of the parallel-leaf guide about the leaf mid-plane axis (x): in-plane bending of both leaves plus their Saint-Venant torsion."""
    E = MATERIALS[DEFAULT_MATERIAL].flexural_modulus_gpa['horizontal'] * 1000.; G = E / (2 * (1 + p['poisson_ratio']))
    L = p['leaf_free_x_mm'] - p['leaf_root_x_mm']; t = p['leaf_thickness_mm']; w = p['leaf_z_max_mm'] - p['leaf_z_min_mm']
    d = (p['leaf_b_y_mm'] - p['leaf_a_y_mm'])
    kz = 12 * E * (t * w ** 3 / 12) / L ** 3; beta = (1 - .63 * t / w) / 3
    k_twist = 2 * kz * (d / 2) ** 2 + 2 * G * beta * w * t ** 3 / L
    face_mid = (p['window_z_min_mm'] + p['window_z_max_mm']) / 2
    offset = max(abs(p['window_z_max_mm'] - (p['leaf_z_min_mm'] + w / 2)), abs(p['window_z_min_mm'] - (p['leaf_z_min_mm'] + w / 2)))
    torque = p['edge_press_force_n'] * offset
    return {'twist_deg': math.degrees(torque / k_twist), 'torque_nmm': torque, 'edge_offset_mm': offset, 'stiffness_nmm_per_rad': k_twist,
            'face_mid_z_mm': face_mid}


def _fillet(node_id, function_id, x_face, y_face, sx, sy, r, z0, z1):
    """Concave fillet of radius r in the corner at (x_face, y_face), filling toward (+sx, +sy)."""
    lo = [min(x_face, x_face + sx * r), min(y_face, y_face + sy * r), z0]; hi = [max(x_face, x_face + sx * r), max(y_face, y_face + sy * r), z1]
    return [_box(node_id + '_sq', function_id, 'Fillet square.', lo, hi),
            {'id': node_id + '_cut', 'op': 'cylinder', 'function_id': function_id, 'reason': 'Fillet radius.', 'radius_mm': r,
             'height_mm': z1 - z0 + .02, 'origin_mm': [x_face + sx * r, y_face + sy * r, z0 - .01], 'axis': [0., 0., 1.]},
            {'id': node_id, 'op': 'difference', 'function_id': function_id, 'reason': f'R{r:g} fillet at a leaf corner.', 'operands': [node_id + '_sq', node_id + '_cut']}]


def side_button_parallel_recipe(request=REQUEST, p=None):
    p = dict(PP if p is None else p)
    wl, wh, zl, zh, g = p['window_x_min_mm'], p['window_x_max_mm'], p['window_z_min_mm'], p['window_z_max_mm'], p['window_gap_mm']
    xr, xf, t, r = p['leaf_root_x_mm'], p['leaf_free_x_mm'], p['leaf_thickness_mm'], p['fillet_radius_mm']
    ya, yb = p['leaf_a_y_mm'], p['leaf_b_y_mm']; lz0, lz1 = p['leaf_z_min_mm'], p['leaf_z_max_mm']; L = xf - xr
    bx0 = xr - p['block_x_mm']; by0, by1 = ya, yb + t
    profile = SWITCH_PROFILES[DESIGN_SWITCH]; base_y = _base_y_v15({**PC, **{k: v for k, v in p.items() if k in PC}})
    px = (p['plunger_x_min_mm'] + p['plunger_x_max_mm']) / 2; pz = (p['plunger_z_min_mm'] + p['plunger_z_max_mm']) / 2
    ins_r, hole_r, eng = p['insert_radius_mm'], p['insert_hole_radius_mm'], p['insert_engagement_mm']
    tip_y = p['plunger_tip_y_mm'] - p['design_insert_protrusion_mm']
    yl = p['stop_lug_y_mm']; xg = wh + g; tab_x0 = wh - 2.; tab_x1 = xg + p['stop_reach_mm']
    r_pin, inter, binter, peng = p['pin_radius_mm'], p['pin_interference_mm'], p['pin_block_interference_mm'], p['pin_post_engagement_mm']
    pins = list(zip(p['pin_y_mm'], p['pin_z_mm']))
    deep = deep_travel_v16(p); tw = twist_v16(p)
    shortening = p['parasitic_shortening_factor'] * deep ** 2 / L
    def cyl(node_id, function_id, reason, radius, origin, height, axis):
        return {'id': node_id, 'op': 'cylinder', 'function_id': function_id, 'reason': reason, 'radius_mm': radius,
                'height_mm': height, 'origin_mm': list(origin), 'axis': list(axis)}
    fillets = []
    for name, x_face, sx, z0, z1 in (('root', xr, 1., lz0, lz1), ('tip', xf, -1., p['pad_z_min_mm'], p['pad_z_max_mm'])):
        # Concave fillets on the leaf side of each corner, on the leaves' inner faces, over the width of the part they join.
        fillets += _fillet(f'{name}_fillet_a', 'F2_guide_button', x_face, ya + t, sx, 1., r, z0, z1)
        fillets += _fillet(f'{name}_fillet_b', 'F2_guide_button', x_face, yb, sx, -1., r, z0, z1)
    ops = [
        {'id': 'outer', 'op': 'spline_loft', 'function_id': 'F6_connect_shell', 'reason': 'Base outer skin (stand-in for a scanned shell).',
         'sections': [{'z_mm': z, 'points_mm': _ellipse(a_, b_)} for z, a_, b_ in SECTIONS]},
        {'id': 'cavity', 'op': 'spline_loft', 'function_id': 'F6_connect_shell', 'reason': 'Inner cavity, open at the bottom.', 'sections': _inset_sections(p['shell_wall_mm'])},
        {'id': 'hollow', 'op': 'difference', 'function_id': 'F6_connect_shell', 'reason': 'Shell skin = outer minus cavity.', 'operands': ['outer', 'cavity']},
        _box('window', 'F1_transmit_force', 'Button skin region (edges parallel to the press direction: the face translates).', [wl, 20., zl], [wh, 40., zh]),
        _box('window_gap', 'F6_connect_shell', 'Window with the 0.4 mm running gap on all sides.', [wl - g, 20., zl - g], [wh + g, 40., zh + g]),
        {'id': 'shell_open', 'op': 'difference', 'function_id': 'F6_connect_shell', 'reason': 'Open the window.', 'operands': ['hollow', 'window_gap']},
        *[cyl(f'post_{i}', 'F6_connect_shell', f'Shell post {i} (along X) for a press-fit pin.', p['post_radius_mm'], (p['post_x_mm'], y, z), bx0 - p['post_x_mm'], (1., 0., 0.))
          for i, (y, z) in enumerate(pins, 1)],
        *[{'id': f'post_{i}_in', 'op': 'intersection', 'function_id': 'F6_connect_shell', 'reason': f'Post {i} inside the outer skin.', 'operands': [f'post_{i}', 'outer']} for i in (1, 2)],
        *[cyl(f'post_{i}_hole', 'F6_connect_shell', f'Press-fit hole for pin {i}.', r_pin - inter, (bx0 - peng, y, z), peng + .01, (1., 0., 0.)) for i, (y, z) in enumerate(pins, 1)],
        _box('stop_lug_box', 'F2_guide_button', 'Rest-stop lug under the skin beyond the window far edge.', [xg + .3, yl, p['stop_z_min_mm'] - .5], [tab_x1 + .5, 40., p['stop_z_max_mm'] + .5]),
        {'id': 'rest_stop', 'op': 'intersection', 'function_id': 'F2_guide_button', 'reason': 'Lug grown from the inner skin (same print as the shell).', 'operands': ['stop_lug_box', 'cavity']},
        {'id': 'shell_raw', 'op': 'union', 'function_id': 'F6_connect_shell', 'reason': 'Shell with the two posts.', 'operands': ['shell_open', 'post_1_in', 'post_2_in']},
        {'id': 'shell', 'op': 'difference', 'function_id': 'F6_connect_shell', 'reason': 'Posts with their pin holes.', 'operands': ['shell_raw', 'post_1_hole', 'post_2_hole']},
        _box('block_raw', 'F6_connect_shell', 'Carrier mounting block, flush with both leaves outer faces (prints flat).', [bx0, by0, lz0], [xr, by1, lz1]),
        *[cyl(f'block_hole_{i}', 'F6_connect_shell', f'Press-fit hole for pin {i} in the block.', r_pin - binter, (bx0 - .01, y, z), xr - bx0 + .02, (1., 0., 0.)) for i, (y, z) in enumerate(pins, 1)],
        *[f for f in fillets if f['id'].startswith('root') or f['id'].startswith('tip')],
        {'id': 'block_filleted', 'op': 'union', 'function_id': 'F6_connect_shell', 'reason': 'Block with the root fillets.', 'operands': ['block_raw', 'root_fillet_a', 'root_fillet_b']},
        {'id': 'carrier_block', 'op': 'difference', 'function_id': 'F6_connect_shell', 'reason': 'Block with pin holes.', 'operands': ['block_filleted', 'block_hole_1', 'block_hole_2']},
        _box('leaf_a', 'F2_guide_button', 'Lower leaf of the parallel guide (also returns the face).', [xr, ya, lz0], [xf, ya + t, lz1]),
        _box('leaf_b', 'F2_guide_button', 'Upper leaf of the parallel guide.', [xr, yb, lz0], [xf, yb + t, lz1]),
        {'id': 'leaf_a_part', 'op': 'union', 'function_id': 'F2_guide_button', 'reason': 'Leaf A with its tip fillet (continuous material with the pad).', 'operands': ['leaf_a', 'tip_fillet_a']},
        {'id': 'leaf_b_part', 'op': 'union', 'function_id': 'F2_guide_button', 'reason': 'Leaf B with its tip fillet (continuous material with the pad).', 'operands': ['leaf_b', 'tip_fillet_b']},
        {'id': 'skin_piece', 'op': 'intersection', 'function_id': 'F1_transmit_force', 'reason': 'Button face is the removed skin piece.', 'operands': ['hollow', 'window']},
        _box('pad_box', 'F2_guide_button', 'Pad joining both leaf tips to the face.', [xf, ya, p['pad_z_min_mm']], [xf + p['pad_x_mm'], 40., p['pad_z_max_mm']]),
        {'id': 'pad_in', 'op': 'intersection', 'function_id': 'F2_guide_button', 'reason': 'Pad inside the outer skin.', 'operands': ['pad_box', 'outer']},
        _box('spine_box', 'F1_transmit_force', 'Spine stiffening the face.', [xf, p['spine_y_min_mm'], p['spine_z_min_mm']], [wh - 1.5, 40., p['spine_z_max_mm']]),
        {'id': 'spine', 'op': 'intersection', 'function_id': 'F1_transmit_force', 'reason': 'Spine inside the outer skin.', 'operands': ['spine_box', 'outer']},
        _box('plunger_box', 'F3_actuate_switch', 'Plunger carrying the actuator insert.', [p['plunger_x_min_mm'], p['plunger_tip_y_mm'], p['plunger_z_min_mm']], [p['plunger_x_max_mm'], 40., p['plunger_z_max_mm']]),
        {'id': 'plunger', 'op': 'intersection', 'function_id': 'F3_actuate_switch', 'reason': 'Plunger inside the outer skin.', 'operands': ['plunger_box', 'outer']},
        _box('tab_riser_box', 'F2_guide_button', 'Riser carrying the rest-stop tab from the face.', [tab_x0, yl - p['stop_tab_thickness_mm'], p['stop_z_min_mm']], [wh - .5, 40., p['stop_z_max_mm']]),
        {'id': 'tab_riser', 'op': 'intersection', 'function_id': 'F2_guide_button', 'reason': 'Riser inside the outer skin.', 'operands': ['tab_riser_box', 'outer']},
        _box('stop_tab', 'F2_guide_button', 'Rest-stop tab: its top meets the lug bottom at rest.', [tab_x0, yl - p['stop_tab_thickness_mm'], p['stop_z_min_mm']], [tab_x1, yl, p['stop_z_max_mm']]),
        {'id': 'button_solid', 'op': 'union', 'function_id': 'F1_transmit_force', 'reason': 'Face, pad with tip fillets, spine, plunger and rest-stop tab.',
         'operands': ['skin_piece', 'pad_in', 'spine', 'plunger', 'tab_riser', 'stop_tab']},
        cyl('insert_hole', 'F3_actuate_switch', 'Press-fit hole for the printed actuator insert.', hole_r, (px, p['plunger_tip_y_mm'] - .01, pz), eng + .01, (0., 1., 0.)),
        {'id': 'button', 'op': 'difference', 'function_id': 'F3_actuate_switch', 'reason': 'Button with the blind insert hole.', 'operands': ['button_solid', 'insert_hole']},
        cyl('actuator_insert', 'F3_actuate_switch', 'Printed actuator insert (fitted from a 0.05 mm length series).', ins_r, (px, tip_y, pz), p['plunger_tip_y_mm'] + eng - tip_y, (0., 1., 0.)),
        *[cyl(f'pin_{i}_shank', 'F6_connect_shell', f'Pin {i} shank.', r_pin, (bx0 - peng, y, z), peng + (xr - bx0), (1., 0., 0.)) for i, (y, z) in enumerate(pins, 1)],
        *[cyl(f'pin_{i}_head', 'F6_connect_shell', f'Pin {i} head on the block face.', p['pin_head_radius_mm'], (xr, y, z), p['pin_head_height_mm'], (1., 0., 0.)) for i, (y, z) in enumerate(pins, 1)],
        *[{'id': f'pin_{i}', 'op': 'union', 'function_id': 'F6_connect_shell', 'reason': f'Separately printed ABS pin {i}.', 'operands': [f'pin_{i}_shank', f'pin_{i}_head']} for i in (1, 2)],
        _box('switch_body', 'F3_actuate_switch', f'Switch body from profile {profile.id} on the ASSUMED PCB plane.',
             [px - profile.body_length.value / 2, base_y, pz - profile.body_width.value / 2], [px + profile.body_length.value / 2, base_y + profile.body_height.value, pz + profile.body_width.value / 2]),
        _box('switch_pin', 'F3_actuate_switch', 'Switch pin at its maximum free position (pin x size UNKNOWN, 1.2 mm assumed).',
             [px - .6, base_y + profile.body_height.value, pz - profile.plunger_width.value / 2], [px + .6, base_y + profile.free_position.value, pz + profile.plunger_width.value / 2]),
    ]
    moving = {'moving_part': 'button', 'carried_parts': ['actuator_insert']}
    tw_axis = {'axis_origin_mm': [0., (ya + yb + t) / 2, (lz0 + lz1) / 2], 'axis_direction': [1., 0., 0.]}
    E = MATERIALS[DEFAULT_MATERIAL].flexural_modulus_gpa['horizontal'] * 1000.
    fits = [insert_fit_v15(pr, {**PC, **{k: v for k, v in p.items() if k in PC}}) for pr in SWITCH_PROFILES.values()]
    summary = '; '.join(f"{f['profile']}: {f['verdict']}" + (f" (insert {f['insert_protrusion_mm']:.2f} mm)" if f['verdict'] == 'pass' else f" (missing {', '.join(f.get('missing', []))})") for f in fits)
    ring_ins = math.pi * (ins_r ** 2 - hole_r ** 2) * eng
    ring_post = math.pi * (r_pin ** 2 - (r_pin - inter) ** 2) * peng
    ring_block = math.pi * (r_pin ** 2 - (r_pin - binter) ** 2) * (xr - bx0)
    params = {k: float(v) for k, v in p.items() if not isinstance(v, tuple)}
    beam_force = 2 * 12 * E * ((lz1 - lz0) * t ** 3 / 12) / L ** 3 * deep
    return {
        'title': 'Side button test subject, revision 16 (parallel-leaf ABS carrier, press-fit pins)',
        'original_request': request,
        'design_parameters': params,
        'parameter_basis': {k: 'ASSUMED test-subject proposal; not measured from a real mouse, switch or PCB.' for k in params},
        'functions': {'F1_transmit_force': 'Transmit thumb force from the skin piece into the button.',
                      'F2_guide_button': 'Guide the face on two parallel leaves; hold it flush at rest against the lug.',
                      'F3_actuate_switch': 'Press the switch pin through a gap set at assembly.',
                      'F4_restore_button': 'Return the face with the elastic leaves (no separate spring).',
                      'F5_limit_overtravel': 'The switch takes the overtravel (no hard stop); travel is checked to the pin fully pressed.',
                      'F6_connect_shell': 'Fix the carrier to the shell posts with press-fit pins; keep the outer skin outside the window.'},
        'protected_constraints': ['Outer skin outside the side-button region is not changed (checked against the base skin).',
                                  'Owner policy: ABS only; no screws except those supplied with the OP1.'],
        'design_basis': {'kind': 'first_principles',
                         'summary': 'Separately printed ABS carrier: the face translates on two parallel leaves, rests on a shell lug, and is fixed by two diagonal press-fit pins; the switch takes the overtravel.',
                         'assumptions': [ASSUMED_V15['material'], ASSUMED_V15['screws'],
                                         'ASSUMED stress concentration 1.5 at the R1-filleted leaf corners (inner faces); outer faces run flush into block and pad.',
                                         f'Edge press (ASSUMED 3 N at the face edge {tw["edge_offset_mm"]:.1f} mm from the leaf mid-plane) twists the guide by {tw["twist_deg"]:.2f} deg (in-plane leaf bending plus torsion; Poisson ratio 0.35 ASSUMED).',
                                         'Printing: carrier flat on the outer face of leaf A with block and pad flush (no support under the leaves); shell rim-down with supports under the window lintel, the roof, the posts and the lug.',
                                         'Assembly order: carrier in from the cavity side (+Y) until the tab meets the lug, before the switch/PCB; then both pins pressed in along -X through the block into the posts.',
                                         f'Rest gap: inserts printed in {p["insert_step_mm"]:.2f} mm length steps; the longest that does not operate the switch at rest is fitted (gap 0-{p["insert_step_mm"]:.2f} mm above the release point side).',
                                         'Force is the same anywhere on the face (translation, no lever): leaf return force plus switch force.']},
        'verification_plan': [
            'Pair overlap and bounds; declared press fits (pins in block and posts, insert in plunger).',
            'Rest: outward translation of the face is blocked by the lug.',
            f'Press: face with insert clear of the shell by at least 0.15 mm to {deep:.3f} mm (pin flush for the deepest registered switch plus one insert step), including the leaf shortening.',
            f'Twist: face clear of the shell and lug by at least {p["twist_min_gap_mm"]:.2f} mm at +/-{tw["twist_deg"]:.2f} deg (edge press) 0.3 mm into the stroke and at the deepest pose; at rest the lug carries the outward side.',
            'Carrier insertion path (+Y) clear of the shell posts and lug; pin insertion paths clear of the leaves and face.',
            'Leaves: guided-beam stiffness (two leaves), press force with the largest registered switch force, root stress with stress concentration.',
            'Outer form outside the side-button region matches the base skin; sampled printed walls of shell and button.'],
        'operations': ops,
        'outputs': [{'part_id': 'shell', 'node': 'shell', 'manufacturing_process': 'FDM ABS, rim-down'},
                    {'part_id': 'rest_stop', 'node': 'rest_stop', 'manufacturing_process': 'FDM ABS, same print as the shell'},
                    {'part_id': 'carrier_block', 'node': 'carrier_block', 'manufacturing_process': 'FDM ABS, one carrier print (block, leaves, button)'},
                    {'part_id': 'leaf_a', 'node': 'leaf_a_part', 'manufacturing_process': 'FDM ABS, same carrier print'},
                    {'part_id': 'leaf_b', 'node': 'leaf_b_part', 'manufacturing_process': 'FDM ABS, same carrier print'},
                    {'part_id': 'button', 'node': 'button', 'manufacturing_process': 'FDM ABS, same carrier print'},
                    {'part_id': 'actuator_insert', 'node': 'actuator_insert', 'manufacturing_process': 'FDM ABS insert from a 0.05 mm length series'},
                    {'part_id': 'pin_1', 'node': 'pin_1', 'manufacturing_process': 'FDM ABS pin (separate print)'},
                    {'part_id': 'pin_2', 'node': 'pin_2', 'manufacturing_process': 'FDM ABS pin (separate print)'},
                    {'part_id': 'switch_body', 'node': 'switch_body', 'manufacturing_process': f'Placeholder for a purchased switch (profile {profile.id})'},
                    {'part_id': 'switch_pin', 'node': 'switch_pin', 'manufacturing_process': 'Placeholder for the switch pin'}],
        'press_fits': [{'id': 'insert-in-plunger', 'part_a': 'actuator_insert', 'part_b': 'button', 'min_overlap_mm3': .7 * ring_ins, 'max_overlap_mm3': 1.3 * ring_ins,
                        'basis': 'ASSUMED 0.05 mm radial interference over the insert engagement.'},
                       *[{'id': f'pin-{i}-in-post', 'part_a': f'pin_{i}', 'part_b': 'shell', 'min_overlap_mm3': .7 * ring_post, 'max_overlap_mm3': 1.3 * ring_post,
                          'basis': f'ASSUMED {inter:.2f} mm radial interference over {peng:.1f} mm in the post.'} for i in (1, 2)],
                       *[{'id': f'pin-{i}-in-block', 'part_a': f'pin_{i}', 'part_b': 'carrier_block', 'min_overlap_mm3': .7 * ring_block, 'max_overlap_mm3': 1.3 * ring_block,
                          'basis': f'ASSUMED {binter:.2f} mm radial interference through the block (locates the carrier, no play).'} for i in (1, 2)]],
        'clearance_checks': [
            {'id': 'rest-gap-insert-to-pin', 'part_a': 'actuator_insert', 'part_b': 'switch_pin', 'min_mm': p['rest_gap_mm'] - 1e-3},
            {'id': 'rest-button-shell', 'part_a': 'button', 'part_b': 'shell', 'min_mm': .35},
            {'id': 'leaf-a-to-shell', 'part_a': 'leaf_a', 'part_b': 'shell', 'min_mm': .4},
            {'id': 'leaf-b-to-shell', 'part_a': 'leaf_b', 'part_b': 'shell', 'min_mm': .4}],
        'motion_checks': [
            {'id': 'rest-outward-blocked-by-lug', **moving, 'obstacles': ['rest_stop'], 'translation_end_mm': [0., .3, 0.], 'expect': 'blocked', 'samples': 4, 'max_samples': 4},
            {'id': 'press-to-pin-flush-clear-of-shell', **moving, 'obstacles': ['shell'], 'translation_end_mm': [-shortening, -deep, 0.], 'samples': 3, 'max_samples': 5, 'min_mm': .15},
            {'id': 'press-leaves-the-lug', **moving, 'obstacles': ['rest_stop'], 'start_translation_mm': [0., -.01, 0.], 'translation_end_mm': [-shortening, -deep, 0.], 'samples': 3, 'max_samples': 3, 'min_mm': 0.},
            {'id': 'carrier-insertion', 'moving_part': 'carrier_block', 'carried_parts': ['leaf_a', 'leaf_b', 'button', 'actuator_insert'], 'obstacles': ['shell', 'rest_stop'],
             'start_translation_mm': [0., -6., 0.], 'translation_end_mm': [0., 5.98, 0.], 'samples': 5, 'max_samples': 5, 'min_mm': 0.},
            *[{'id': f'pin-{i}-insertion', 'moving_part': f'pin_{i}', 'obstacles': ['leaf_a', 'leaf_b', 'button'], 'start_translation_mm': [8., 0., 0.],
               'translation_end_mm': [-8., 0., 0.], 'samples': 5, 'max_samples': 9, 'min_mm': .1} for i in (1, 2)]],
        'rotation_checks': [
            # An edge press twists the face while it travels; checked from 0.3 mm in (tab off the lug) and at the deepest pose.
            *[{'id': f'edge-press-twist-{sign_name}-{depth_name}', **moving, 'obstacles': ['shell', 'rest_stop'], **tw_axis,
               'start_translation_mm': [-shortening * (dy / deep) ** 2, -dy, 0.], 'end_deg': sign * tw['twist_deg'], 'samples': 2, 'max_samples': 3,
               'min_mm': p['twist_min_gap_mm']}
              for sign_name, sign in (('positive', 1.), ('negative', -1.)) for depth_name, dy in (('early', .3), ('deep', deep))]],
        'wall_checks': [{'id': 'shell-printed-wall', 'part': 'shell', 'min_mm': p['min_printed_wall_mm'], 'samples_per_face': 10},
                        {'id': 'button-printed-wall', 'part': 'button', 'min_mm': p['min_printed_wall_mm'], 'samples_per_face': 10}],
        'flexure_checks': [{'id': 'parallel-leaves-beam', 'part': 'leaf_a', 'beam_node': 'leaf_a', 'length_axis': 'x', 'fixed_end': 'min', 'bend_axis': 'y',
                            'end_condition': 'guided', 'parallel_count': 2,
                            'material': DEFAULT_MATERIAL, 'orientation': 'horizontal', 'strength_basis': 'tensile_strength', 'deflection_mm': deep,
                            'min_force_n': p['force_band_min_n'], 'max_force_n': p['force_band_max_n'], 'force_basis': 'ASSUMED press-force band 0.3-3 N anywhere on the face (translation).',
                            'switch_profiles': list(SWITCH_PROFILES), 'beam_force_ratio': 1., 'switch_force_ratio': 1.,
                            'ratio_basis': 'Translation: leaves, switch and press point share the same displacement (no lever).',
                            'stress_allowance': p['stress_allowance'], 'allowance_basis': 'ASSUMED half of the datasheet tensile strength (yield not published); fatigue UNKNOWN.',
                            'stress_concentration': p['stress_concentration'], 'stress_concentration_basis': 'ASSUMED 1.5 at R1-filleted corners (r/t about 1.4).'}],
        'base_shape_checks': [{'id': 'outer-form-matches-base', 'base_node': 'outer', 'parts': ['shell', 'button'], 'tolerance_mm': .05, 'samples_per_face': 12, 'regions': [
            {'id': 'side-button-region', 'kind': 'allowed_change', 'reason': 'Changes around the side buttons are allowed (window and running gap).',
             'lo_mm': [wl - 1., 20., zl - 1.], 'hi_mm': [wh + 3., 40., zh + 1.]},
            {'id': 'open-bottom', 'kind': 'not_in_base', 'reason': 'The base outer form is the skin; its bottom cap is the open rim.', 'lo_mm': [-70., -40., -.1], 'hi_mm': [70., 40., .1]}]}],
        'unverified_requirements': [
            '押しやすさ: 平行移動のため面のどこを押しても同じ力（板バネ復帰力＋スイッチ作動力）。実機の押下感・クリック感は未試験。',
            f'Press force at the deepest pose about {beam_force + max(pr.operating_force.value for pr in SWITCH_PROFILES.values() if pr.operating_force.known) * .00980665:.2f} N (leaves {beam_force:.2f} N + largest registered switch force); the leaves add to the bare switch force.',
            f'Switch profiles (insert from datasheets): {summary}.',
            'Leaves: beam theory only (guided small deflection, rigid root, typical datasheet values, ASSUMED stress concentration and Poisson ratio); creep and fatigue UNKNOWN.',
            'Switch bottoming force is carried by the switch (no hard stop); its rating is not in the registered datasheets (UNKNOWN).',
            'Pin and insert retention in printed ABS and print accuracy of the gaps are not qualified; presses load the pins in shear.',
            'PCB plane is ASSUMED; the real board and shell were not measured. OP1-supplied screws are not used by this carrier.',
            'Wall checks are sampled minima of the stated parts, not a proof of minimum wall or of strength.'],
    }


# ---------------------------------------------------------------------------
# Revision 17: repairs the revision-16 round-1 findings.
# - Insert rule could leave the switch held inside its release hysteresis ->
#   inserts in 0.1 mm steps (one layer); fit the longest insert with which the
#   switch still releases after a full press, then the next shorter one. The
#   travel stack uses the operating position, the movement differential and
#   two steps, not a nominal gap.
# - Pins could not be pressed (pad in the way) -> pins run vertically through
#   two shell tabs and the block, pressed in from the open bottom; the press
#   load is shear on the pins.
# - Nothing pushed the tab onto the lug -> the lug sits 0.1 mm into the tab
#   path (declared preload): the leaves are pre-bent 0.1 mm at rest and the
#   face rests 0.1 mm below the skin.
# - Leaf tip joined over 7 of 10 mm -> full-width lower pad.
# - Insert tip overhung the pin onto the switch body -> Ø1.0 tip; the press
#   sweep includes the switch body to the pin flush pose.
# - Yaw from a press at the far end checked; stale texts and unused
#   parameters removed; PCB keep-out stated.
# ---------------------------------------------------------------------------
P17 = {k: v for k, v in PP.items() if k not in ('edge_press_offset_mm', 'post_x_mm', 'pin_post_engagement_mm', 'pin_y_mm', 'pin_z_mm', 'post_radius_mm',
                                                  'stop_lug_y_mm', 'design_insert_protrusion_mm', 'insert_step_mm', 'rest_gap_mm')}
P17.update({'tab_gap_mm': .2, 'tab_thickness_mm': 3., 'pin_tab_engagement_mm': 2.5, 'pin_xy_mm': ((-34., 14.), (-32., 18.7)),
            'lug_y_mm': 26.5, 'preload_mm': .1, 'insert_step_mm': .1, 'tip_radius_mm': .5, 'tip_length_mm': 1.2,
            'design_rest_above_op_mm': .25, 'collar_radius_mm': 1.3, 'collar_thickness_mm': .6, 'counterbore_radius_mm': 1.45,
            'counterbore_depth_mm': .8, 'pin_end_clearance_mm': .3, 'plunger_z_min_mm': 10., 'plunger_z_max_mm': 16.})
P17.update({'leaf_root_x_mm': -33., 'leaf_thickness_mm': .6, 'leaf_z_min_mm': 9.5, 'leaf_z_max_mm': 17.5,
            'leaf_a_y_mm': 11., 'leaf_b_y_mm': 19., 'pin_xy_mm': ((-36.2, 13.), (-35.8, 16.6)), 'block_x_mm': 5.,
            'upper_tab_thickness_mm': 3.5, 'pin_tab_engagement_mm': 2.2})


def stack_v17(profile, p=P17):
    """Travel stack from the click-referenced insert rule (needs OP, MD and body height on one datum)."""
    need = ('operating_position', 'movement_differential', 'body_height', 'plunger_width', 'body_length', 'body_width', 'overtravel')
    missing = [k for k in need if not getattr(profile, k).known]
    if missing:
        return {'profile': profile.id, 'verdict': 'unverified', 'missing': missing,
                'reason': 'The insert rule and the travel stack need these datasheet values; UNKNOWN gives no pass.'}
    s = p['insert_step_mm']; md = profile.movement_differential.value
    op, op_tol = profile.operating_position.value, profile.operating_position.tolerance or 0.
    top, top_tol = profile.body_height.value, profile.body_height.tolerance or 0.
    # Rule: longest insert that still releases after a full press, then one step shorter:
    # rest tip above the release point by [s, 2s); the release point is up to md above OP.
    rest_above_op = (s, md + 2 * s)
    to_flush = rest_above_op[1] + (op + op_tol) - (top - top_tol)
    return {'profile': profile.id, 'verdict': 'pass', 'rest_above_op_mm': rest_above_op, 'travel_to_operate_max_mm': rest_above_op[1],
            'travel_to_pin_flush_max_mm': to_flush,
            'scope': 'Click-referenced insert choice; the switch takes the overtravel to the pin flush pose.'}


def deep_travel_v17(p=P17):
    return max(f['travel_to_pin_flush_max_mm'] for f in (stack_v17(pr, p) for pr in SWITCH_PROFILES.values()) if f['verdict'] == 'pass')


def twist_v17(p=P17):
    E = MATERIALS[DEFAULT_MATERIAL].flexural_modulus_gpa['horizontal'] * 1000.; G = E / (2 * (1 + p['poisson_ratio']))
    L = p['leaf_free_x_mm'] - p['leaf_root_x_mm']; t = p['leaf_thickness_mm']; w = p['leaf_z_max_mm'] - p['leaf_z_min_mm']
    d = p['leaf_b_y_mm'] - p['leaf_a_y_mm']
    kz = 12 * E * (t * w ** 3 / 12) / L ** 3; beta = (1 - .63 * t / w) / 3
    k_twist = 2 * kz * (d / 2) ** 2 + 2 * G * beta * w * t ** 3 / L
    mid = (p['leaf_z_min_mm'] + p['leaf_z_max_mm']) / 2
    offset = max(abs(p['window_z_max_mm'] - mid), abs(p['window_z_min_mm'] - mid))
    k_axial = E * w * t / L; k_yaw = 2 * k_axial * (d / 2) ** 2
    yaw_lever = p['window_x_max_mm'] - p['leaf_free_x_mm']
    return {'twist_deg': math.degrees(p['edge_press_force_n'] * offset / k_twist), 'twist_offset_mm': offset,
            'yaw_deg': math.degrees(p['edge_press_force_n'] * yaw_lever / k_yaw), 'yaw_lever_mm': yaw_lever}


def _outer_y(x, z):
    """Outer skin Y at (x, z) on the +Y side, from the section ellipses (linear between sections; ASSUMED close to the spline)."""
    for (z0, a0, b0), (z1, a1, b1) in zip(SECTIONS, SECTIONS[1:]):
        if z0 <= z <= z1:
            f = (z - z0) / (z1 - z0); a = a0 + f * (a1 - a0); b = b0 + f * (b1 - b0)
            return b * math.sqrt(max(0., 1 - (x / a) ** 2))
    raise ValueError('z outside the shell sections')


def side_button_parallel_recipe_v17(request=REQUEST, p=None):
    p = dict(P17 if p is None else p)
    wl, wh, zl, zh, g = p['window_x_min_mm'], p['window_x_max_mm'], p['window_z_min_mm'], p['window_z_max_mm'], p['window_gap_mm']
    xr, xf, t, r = p['leaf_root_x_mm'], p['leaf_free_x_mm'], p['leaf_thickness_mm'], p['fillet_radius_mm']
    ya, yb = p['leaf_a_y_mm'], p['leaf_b_y_mm']; lz0, lz1 = p['leaf_z_min_mm'], p['leaf_z_max_mm']; L = xf - xr
    bx0 = xr - p['block_x_mm']; by0, by1 = ya, yb + t
    tg, tt, teng = p['tab_gap_mm'], p['tab_thickness_mm'], p['pin_tab_engagement_mm']
    profile = SWITCH_PROFILES[DESIGN_SWITCH]
    px = (p['plunger_x_min_mm'] + p['plunger_x_max_mm']) / 2; pz = (p['plunger_z_min_mm'] + p['plunger_z_max_mm']) / 2
    ins_r, hole_r, eng = p['insert_radius_mm'], p['insert_hole_radius_mm'], p['insert_engagement_mm']
    tip_y = p['plunger_tip_y_mm'] - p['tip_length_mm']
    op_y = tip_y - p['design_rest_above_op_mm']; base_y = op_y - profile.operating_position.value
    yl = p['lug_y_mm']; xg = wh + g; tab_x0 = wh - 2.; tab_x1 = xg + p['stop_reach_mm']; pre = p['preload_mm']
    r_pin, inter, binter = p['pin_radius_mm'], p['pin_interference_mm'], p['pin_block_interference_mm']
    pins = list(p['pin_xy_mm'])
    deep = deep_travel_v17(p); tw = twist_v17(p)
    own_flush = p['design_rest_above_op_mm'] + SWITCH_PROFILES[DESIGN_SWITCH].operating_position.value - SWITCH_PROFILES[DESIGN_SWITCH].body_height.value
    def short(dy): return p['parasitic_shortening_factor'] * dy ** 2 / L
    def cyl(node_id, function_id, reason, radius, origin, height, axis=(0., 0., 1.)):
        return {'id': node_id, 'op': 'cylinder', 'function_id': function_id, 'reason': reason, 'radius_mm': radius,
                'height_mm': height, 'origin_mm': list(origin), 'axis': list(axis)}
    fillets = []
    for name, x_face, sx in (('root', xr, 1.), ('tip', xf, -1.)):
        fillets += _fillet(f'{name}_fillet_a', 'F2_guide_button', x_face, ya + t, sx, 1., r, lz0, lz1)
        fillets += _fillet(f'{name}_fillet_b', 'F2_guide_button', x_face, yb, sx, -1., r, lz0, lz1)
    # Leaf B outer face meets the rising pad at the tip: outer fillet over the pad height.
    fillets += _fillet('tip_fillet_c', 'F2_guide_button', xf, yb + t, -1., 1., r, p['pad_z_min_mm'], p['pad_z_max_mm'])
    lt0, lt1 = lz0 - tg - tt, lz0 - tg; ut0, ut1 = lz1 + tg, lz1 + tg + p['upper_tab_thickness_mm']
    pin_bottom = lt0; pin_top = ut0 + teng - p['pin_end_clearance_mm']; head_h = p['pin_head_height_mm']
    # Insert from outside: through hole in the plunger, counterbore in the face for its head.
    skin_y = _outer_y(px, pz); cb_bottom = skin_y - p['counterbore_depth_mm']
    ops = [
        {'id': 'outer', 'op': 'spline_loft', 'function_id': 'F6_connect_shell', 'reason': 'Base outer skin (stand-in for a scanned shell).',
         'sections': [{'z_mm': z, 'points_mm': _ellipse(a_, b_)} for z, a_, b_ in SECTIONS]},
        {'id': 'cavity', 'op': 'spline_loft', 'function_id': 'F6_connect_shell', 'reason': 'Inner cavity, open at the bottom.', 'sections': _inset_sections(p['shell_wall_mm'])},
        {'id': 'hollow', 'op': 'difference', 'function_id': 'F6_connect_shell', 'reason': 'Shell skin = outer minus cavity.', 'operands': ['outer', 'cavity']},
        _box('window', 'F1_transmit_force', 'Button skin region (edges parallel to the press direction: the face translates).', [wl, 20., zl], [wh, 40., zh]),
        _box('window_gap', 'F6_connect_shell', 'Window with the 0.4 mm running gap on all sides.', [wl - g, 20., zl - g], [wh + g, 40., zh + g]),
        {'id': 'shell_open', 'op': 'difference', 'function_id': 'F6_connect_shell', 'reason': 'Open the window.', 'operands': ['hollow', 'window_gap']},
        _box('low_tab_box', 'F6_connect_shell', 'Lower shell tab under the carrier block.', [bx0 - 1.5, by0 - 1., lt0], [bx0 + p['block_x_mm'] - .5, 40., lt1]),
        _box('up_tab_box', 'F6_connect_shell', 'Upper shell tab over the carrier block.', [bx0 - 1.5, by0 - 1., ut0], [bx0 + p['block_x_mm'] - .5, 40., ut1]),
        {'id': 'low_tab', 'op': 'intersection', 'function_id': 'F6_connect_shell', 'reason': 'Lower tab grown from the side wall.', 'operands': ['low_tab_box', 'outer']},
        {'id': 'up_tab', 'op': 'intersection', 'function_id': 'F6_connect_shell', 'reason': 'Upper tab grown from the side wall.', 'operands': ['up_tab_box', 'outer']},
        *[cyl(f'low_hole_{i}', 'F6_connect_shell', f'Press-fit hole for pin {i} through the lower tab.', r_pin - inter, (x, y, lt0 - .01), tt + .02) for i, (x, y) in enumerate(pins, 1)],
        *[cyl(f'up_hole_{i}', 'F6_connect_shell', f'Blind press-fit hole for pin {i} in the upper tab.', r_pin - inter, (x, y, ut0 - .01), teng + .01) for i, (x, y) in enumerate(pins, 1)],
        _box('lug_box', 'F2_guide_button', 'Rest-stop lug under the skin beyond the window far edge (0.1 mm into the tab path: preload).',
             [xg + .3, yl - pre, p['stop_z_min_mm'] - .5], [tab_x1 + .5, 40., p['stop_z_max_mm'] + .5]),
        {'id': 'rest_stop', 'op': 'intersection', 'function_id': 'F2_guide_button', 'reason': 'Lug grown from the inner skin (same print as the shell).', 'operands': ['lug_box', 'cavity']},
        {'id': 'shell_raw', 'op': 'union', 'function_id': 'F6_connect_shell', 'reason': 'Shell with the two pin tabs.', 'operands': ['shell_open', 'low_tab', 'up_tab']},
        {'id': 'shell', 'op': 'difference', 'function_id': 'F6_connect_shell', 'reason': 'Tabs with the pin holes.',
         'operands': ['shell_raw', 'low_hole_1', 'low_hole_2', 'up_hole_1', 'up_hole_2']},
        _box('block_raw', 'F6_connect_shell', 'Carrier block between the shell tabs, flush with the leaves outer faces (prints flat).', [bx0, by0, lz0], [xr, by1, lz1]),
        *[cyl(f'block_hole_{i}', 'F6_connect_shell', f'Press-fit hole for pin {i} through the block.', r_pin - binter, (x, y, lz0 - .01), lz1 - lz0 + .02) for i, (x, y) in enumerate(pins, 1)],
        *fillets,
        {'id': 'block_filleted', 'op': 'union', 'function_id': 'F6_connect_shell', 'reason': 'Block with the root fillets.', 'operands': ['block_raw', 'root_fillet_a', 'root_fillet_b']},
        {'id': 'carrier_block', 'op': 'difference', 'function_id': 'F6_connect_shell', 'reason': 'Block with the pin holes.', 'operands': ['block_filleted', 'block_hole_1', 'block_hole_2']},
        _box('leaf_a', 'F2_guide_button', 'Lower leaf of the parallel guide (also returns the face).', [xr, ya, lz0], [xf, ya + t, lz1]),
        _box('leaf_b', 'F2_guide_button', 'Upper leaf of the parallel guide.', [xr, yb, lz0], [xf, yb + t, lz1]),
        {'id': 'leaf_a_part', 'op': 'union', 'function_id': 'F2_guide_button', 'reason': 'Leaf A with its tip fillet.', 'operands': ['leaf_a', 'tip_fillet_a']},
        {'id': 'leaf_b_part', 'op': 'union', 'function_id': 'F2_guide_button', 'reason': 'Leaf B with its tip fillets (inner and outer).', 'operands': ['leaf_b', 'tip_fillet_b', 'tip_fillet_c']},
        {'id': 'skin_piece', 'op': 'intersection', 'function_id': 'F1_transmit_force', 'reason': 'Button face is the removed skin piece.', 'operands': ['hollow', 'window']},
        _box('pad_low', 'F2_guide_button', 'Full-width lower pad: both leaf tips joined over their whole width (flush with both outer faces).', [xf, ya, lz0], [xf + p['pad_x_mm'], yb + t, lz1]),
        _box('pad_box', 'F2_guide_button', 'Pad rising to the face (window height only).', [xf, ya, p['pad_z_min_mm']], [xf + p['pad_x_mm'], 40., p['pad_z_max_mm']]),
        {'id': 'pad_in', 'op': 'intersection', 'function_id': 'F2_guide_button', 'reason': 'Pad inside the outer skin.', 'operands': ['pad_box', 'outer']},
        _box('spine_box', 'F1_transmit_force', 'Spine stiffening the face.', [xf, p['spine_y_min_mm'], p['spine_z_min_mm']], [wh - 1.5, 40., p['spine_z_max_mm']]),
        {'id': 'spine', 'op': 'intersection', 'function_id': 'F1_transmit_force', 'reason': 'Spine inside the outer skin.', 'operands': ['spine_box', 'outer']},
        _box('plunger_box', 'F3_actuate_switch', 'Plunger carrying the actuator insert.', [p['plunger_x_min_mm'], p['plunger_tip_y_mm'], p['plunger_z_min_mm']], [p['plunger_x_max_mm'], 40., p['plunger_z_max_mm']]),
        {'id': 'plunger', 'op': 'intersection', 'function_id': 'F3_actuate_switch', 'reason': 'Plunger inside the outer skin.', 'operands': ['plunger_box', 'outer']},
        _box('tab_riser_box', 'F2_guide_button', 'Riser carrying the rest-stop tab from the face.', [tab_x0, yl - p['stop_tab_thickness_mm'], p['stop_z_min_mm']], [wh - .5, 40., p['stop_z_max_mm']]),
        {'id': 'tab_riser', 'op': 'intersection', 'function_id': 'F2_guide_button', 'reason': 'Riser inside the outer skin.', 'operands': ['tab_riser_box', 'outer']},
        _box('stop_tab', 'F2_guide_button', 'Rest-stop tab; the lug presses it 0.1 mm in at rest (preload).', [tab_x0, yl - p['stop_tab_thickness_mm'], p['stop_z_min_mm']], [tab_x1, yl, p['stop_z_max_mm']]),
        {'id': 'button_solid', 'op': 'union', 'function_id': 'F1_transmit_force', 'reason': 'Face, pads, spine, plunger and rest-stop tab.',
         'operands': ['skin_piece', 'pad_low', 'pad_in', 'spine', 'plunger', 'tab_riser', 'stop_tab']},
        cyl('insert_hole', 'F3_actuate_switch', 'Through hole for the actuator insert (press fit), open to the face.', hole_r, (px, p['plunger_tip_y_mm'] - .01, pz), 20., (0., 1., 0.)),
        cyl('insert_counterbore', 'F3_actuate_switch', 'Counterbore in the face for the insert head (side-button region).', p['counterbore_radius_mm'], (px, cb_bottom, pz), 20., (0., 1., 0.)),
        {'id': 'button', 'op': 'difference', 'function_id': 'F3_actuate_switch', 'reason': 'Button with the insert through hole and head counterbore.', 'operands': ['button_solid', 'insert_hole', 'insert_counterbore']},
        cyl('insert_head', 'F3_actuate_switch', 'Insert head: seats in the counterbore (length datum), removable from outside.', p['collar_radius_mm'], (px, cb_bottom, pz), p['collar_thickness_mm'], (0., 1., 0.)),
        cyl('insert_shank', 'F3_actuate_switch', 'Insert shank (press fit through the plunger).', ins_r, (px, p['plunger_tip_y_mm'], pz), cb_bottom - p['plunger_tip_y_mm'], (0., 1., 0.)),
        cyl('insert_tip', 'F3_actuate_switch', 'Insert tip Ø1.0: lands on the switch pin only.', p['tip_radius_mm'], (px, tip_y, pz), p['tip_length_mm'] + .01, (0., 1., 0.)),
        {'id': 'actuator_insert', 'op': 'union', 'function_id': 'F3_actuate_switch', 'reason': 'Printed actuator insert, pushed in from the face (tip length from a 0.1 mm series).', 'operands': ['insert_head', 'insert_shank', 'insert_tip']},
        *[cyl(f'pin_{i}_shank', 'F6_connect_shell', f'Pin {i} shank (vertical).', r_pin, (x, y, pin_bottom), pin_top - pin_bottom) for i, (x, y) in enumerate(pins, 1)],
        *[cyl(f'pin_{i}_head', 'F6_connect_shell', f'Pin {i} head under the lower tab.', p['pin_head_radius_mm'], (x, y, pin_bottom - head_h), head_h) for i, (x, y) in enumerate(pins, 1)],
        *[{'id': f'pin_{i}', 'op': 'union', 'function_id': 'F6_connect_shell', 'reason': f'Separately printed ABS pin {i}, pressed in from the open bottom.', 'operands': [f'pin_{i}_shank', f'pin_{i}_head']} for i in (1, 2)],
        _box('switch_body', 'F3_actuate_switch', f'Switch body from profile {profile.id} on the ASSUMED PCB plane (OP {p["design_rest_above_op_mm"]:.2f} mm below the tip at rest).',
             [px - profile.body_length.value / 2, base_y, pz - profile.body_width.value / 2], [px + profile.body_length.value / 2, base_y + profile.body_height.value, pz + profile.body_width.value / 2]),
        _box('switch_pin', 'F3_actuate_switch', 'Switch pin under the tip at rest (pin x size UNKNOWN, 1.2 mm assumed).',
             [px - .6, base_y + profile.body_height.value, pz - profile.plunger_width.value / 2], [px + .6, tip_y - .001, pz + profile.plunger_width.value / 2]),
    ]
    moving = {'moving_part': 'button', 'carried_parts': ['actuator_insert']}
    tw_axis = {'axis_origin_mm': [0., (ya + yb + t) / 2, (lz0 + lz1) / 2], 'axis_direction': [1., 0., 0.]}
    yaw_axis = {'axis_origin_mm': [xf, (ya + yb + t) / 2, 0.], 'axis_direction': [0., 0., 1.]}
    E = MATERIALS[DEFAULT_MATERIAL].flexural_modulus_gpa['horizontal'] * 1000.
    fits = [stack_v17(pr, p) for pr in SWITCH_PROFILES.values()]
    summary = '; '.join(f"{f['profile']}: {f['verdict']}" + (f" (to pin flush {f['travel_to_pin_flush_max_mm']:.2f} mm)" if f['verdict'] == 'pass' else f" (missing {', '.join(f['missing'])})") for f in fits)
    ring_ins = math.pi * (ins_r ** 2 - hole_r ** 2) * (cb_bottom - p['plunger_tip_y_mm'])
    ring_tab = math.pi * (r_pin ** 2 - (r_pin - inter) ** 2)
    ring_block = math.pi * (r_pin ** 2 - (r_pin - binter) ** 2) * (lz1 - lz0)
    lug_overlap = (tab_x1 - (xg + .3)) * (p['stop_z_max_mm'] - p['stop_z_min_mm']) * pre
    params = {k: float(v) for k, v in p.items() if not isinstance(v, tuple)}
    k_pair = 2 * 12 * E * ((lz1 - lz0) * t ** 3 / 12) / L ** 3
    of_max = max(pr.operating_force.value for pr in SWITCH_PROFILES.values() if pr.operating_force.known) * .00980665
    click_travel = max(f['travel_to_operate_max_mm'] for f in fits if f['verdict'] == 'pass')
    return {
        'title': 'Side button test subject, revision 17 (parallel-leaf ABS carrier, vertical pins, preloaded rest stop)',
        'original_request': request,
        'design_parameters': params,
        'parameter_basis': {k: 'ASSUMED test-subject proposal; not measured from a real mouse, switch or PCB.' for k in params},
        'functions': {'F1_transmit_force': 'Transmit thumb force from the skin piece into the button.',
                      'F2_guide_button': 'Guide the face on two parallel leaves; hold it on the preloaded rest lug.',
                      'F3_actuate_switch': 'Press the switch pin with a printed insert chosen against the fitted switch.',
                      'F4_restore_button': 'Return the face with the elastic leaves (no separate spring).',
                      'F5_limit_overtravel': 'Travel ends at the switch pin bottoming (no hard stop); clearances are checked to the pin flush pose.',
                      'F6_connect_shell': 'Fix the carrier between two shell tabs with vertical press-fit pins; keep the outer skin outside the window.'},
        'protected_constraints': ['Outer skin outside the side-button region is not changed (checked against the base skin).',
                                  'Owner policy: ABS only; no screws except those supplied with the OP1.'],
        'design_basis': {'kind': 'first_principles',
                         'summary': 'Separately printed ABS carrier: the face translates on two parallel leaves, preloaded onto a shell lug, fixed between two shell tabs by vertical press-fit pins; the switch takes the overtravel.',
                         'assumptions': [ASSUMED_V15['material'], ASSUMED_V15['screws'],
                                         'ASSUMED stress concentration 1.5 at the R1-filleted leaf corners; outer leaf faces run flush into block and pad.',
                                         f'Edge press (ASSUMED 3 N at the face edge {tw["twist_offset_mm"]:.1f} mm from the leaf mid-plane) twists the guide by {tw["twist_deg"]:.2f} deg; a press at the far end yaws it by {tw["yaw_deg"]:.2f} deg (leaf axial stiffness). Poisson ratio 0.35 ASSUMED.',
                                         f'Rest preload: the lug sits {pre:.1f} mm into the tab path, so the face rests {pre:.1f} mm below the skin with the leaves pre-bent.',
                                         'Printing: carrier standing on its lowest face (mouse Z up): block, leaves and lower pad start on the bed, the leaves are thin vertical walls with bending stress in the layer plane; the face lower edge (z 10, a 1.5 mm strip) needs a small removable support; the insert bore is horizontal. Inserts and pins upright (0.1 mm layers). Shell rim-down with supports under the window lintel, roof, tabs and lug.',
                                         'Assembly: carrier in from the cavity side (+Y) between the tabs until the tab meets the lug; pins pressed up from the open bottom through the lower tab and block into the upper tab (shell supported on its top); switch/PCB fitted; inserts tried from outside through the face (head in a counterbore, pulled out with tweezers).',
                                         f'Insert rule: fit the longest insert (0.1 mm steps) with which the switch still releases after a full press and release, then use the next shorter one: the tip rests {p["insert_step_mm"]:.1f}-{2 * p["insert_step_mm"]:.1f} mm above the release point.',
                                         'Reading of 「もっと押しやすく」 used here (an interpretation for the owner to confirm): the same press force anywhere on the face (translation), with a short travel to the click.',
                                         'PCB keep-out (ASSUMED plane): the board must stay clear of the carrier block, tabs and leaves (x below -9 mm on the switch side of the plane).']},
        'verification_plan': [
            'Pair overlap and bounds; declared press fits (pins in tabs and block, insert in plunger, rest preload on the lug).',
            f'Press: face with insert clear of the shell by at least 0.15 mm to {deep:.3f} mm (pin flush for the deepest registered switch under the insert rule), including leaf shortening; the insert tip clears the switch body to that pose.',
            'Rest: the face leaves the lug after the preload when pressed; outward motion is held by the preloaded lug.',
            f'Twist and yaw: face clear of the shell and lug by at least {p["twist_min_gap_mm"]:.2f} mm at +/-{tw["twist_deg"]:.2f} deg (edge press) and +/-{tw["yaw_deg"]:.2f} deg (far-end press), 0.3 mm into the stroke and at the deepest pose.',
            'Carrier insertion between the tabs and pin insertion from the open bottom are clear.',
            'Leaves: guided-beam stiffness (two leaves), force with the largest registered switch force, root stress with stress concentration, including the preload.',
            'Outer form outside the side-button region matches the base skin; sampled printed walls of shell and button.'],
        'operations': ops,
        'outputs': [{'part_id': 'shell', 'node': 'shell', 'manufacturing_process': 'FDM ABS, rim-down'},
                    {'part_id': 'rest_stop', 'node': 'rest_stop', 'manufacturing_process': 'FDM ABS, same print as the shell'},
                    {'part_id': 'carrier_block', 'node': 'carrier_block', 'manufacturing_process': 'FDM ABS, one carrier print (block, leaves, button)'},
                    {'part_id': 'leaf_a', 'node': 'leaf_a_part', 'manufacturing_process': 'FDM ABS, same carrier print'},
                    {'part_id': 'leaf_b', 'node': 'leaf_b_part', 'manufacturing_process': 'FDM ABS, same carrier print'},
                    {'part_id': 'button', 'node': 'button', 'manufacturing_process': 'FDM ABS, same carrier print'},
                    {'part_id': 'actuator_insert', 'node': 'actuator_insert', 'manufacturing_process': 'FDM ABS insert from a 0.1 mm length series, printed upright'},
                    {'part_id': 'pin_1', 'node': 'pin_1', 'manufacturing_process': 'FDM ABS pin, printed upright'},
                    {'part_id': 'pin_2', 'node': 'pin_2', 'manufacturing_process': 'FDM ABS pin, printed upright'},
                    {'part_id': 'switch_body', 'node': 'switch_body', 'manufacturing_process': f'Placeholder for a purchased switch (profile {profile.id})'},
                    {'part_id': 'switch_pin', 'node': 'switch_pin', 'manufacturing_process': 'Placeholder for the switch pin'}],
        'press_fits': [{'id': 'insert-in-plunger', 'part_a': 'actuator_insert', 'part_b': 'button', 'min_overlap_mm3': .7 * ring_ins, 'max_overlap_mm3': 1.3 * ring_ins,
                        'basis': 'ASSUMED 0.05 mm radial interference along the plunger through hole.'},
                       {'id': 'rest-preload-on-lug', 'part_a': 'button', 'part_b': 'rest_stop', 'min_overlap_mm3': .7 * lug_overlap, 'max_overlap_mm3': 1.3 * lug_overlap,
                        'basis': f'Declared {pre:.1f} mm preload: the lug sits that far into the tab path (the leaves bend instead).'},
                       *[{'id': f'pin-{i}-in-tabs', 'part_a': f'pin_{i}', 'part_b': 'shell', 'min_overlap_mm3': .7 * ring_tab * (tt + teng), 'max_overlap_mm3': 1.3 * ring_tab * (tt + teng),
                          'basis': f'ASSUMED {inter:.2f} mm radial interference in the lower tab and the blind upper-tab hole.'} for i in (1, 2)],
                       *[{'id': f'pin-{i}-in-block', 'part_a': f'pin_{i}', 'part_b': 'carrier_block', 'min_overlap_mm3': .7 * ring_block, 'max_overlap_mm3': 1.3 * ring_block,
                          'basis': f'ASSUMED {binter:.2f} mm radial interference through the block (locates the carrier, no play).'} for i in (1, 2)]],
        'clearance_checks': [
            {'id': 'rest-button-shell', 'part_a': 'button', 'part_b': 'shell', 'min_mm': .35},
            {'id': 'leaf-a-to-shell', 'part_a': 'leaf_a', 'part_b': 'shell', 'min_mm': .15},
            {'id': 'leaf-b-to-shell', 'part_a': 'leaf_b', 'part_b': 'shell', 'min_mm': .15},
            {'id': 'block-to-tabs', 'part_a': 'carrier_block', 'part_b': 'shell', 'min_mm': 0.}],
        'motion_checks': [
            {'id': 'press-to-pin-flush-clear-of-shell', **moving, 'obstacles': ['shell'], 'translation_end_mm': [-short(deep), -deep, 0.], 'samples': 3, 'max_samples': 5, 'min_mm': .15},
            # The drawn switch's own pin-flush pose: the tip reaches the body top there and no further (the pin bottoms first).
            {'id': 'press-insert-clear-of-switch-body', **moving, 'obstacles': ['switch_body'],
             'translation_end_mm': [-short(own_flush), -own_flush, 0.], 'samples': 3, 'max_samples': 5, 'min_mm': 0.},
            {'id': 'press-leaves-the-lug', **moving, 'obstacles': ['rest_stop'], 'start_translation_mm': [0., -pre - .01, 0.], 'translation_end_mm': [-short(deep), -deep, 0.],
             'samples': 3, 'max_samples': 3, 'min_mm': 0.},
            {'id': 'carrier-insertion', 'moving_part': 'carrier_block', 'carried_parts': ['leaf_a', 'leaf_b', 'button', 'actuator_insert'], 'obstacles': ['shell'],
             'start_translation_mm': [0., -12., 0.], 'translation_end_mm': [0., 12. - pre - .02, 0.], 'samples': 7, 'max_samples': 7, 'min_mm': .15},
            *[{'id': f'pin-{i}-insertion-from-below', 'moving_part': f'pin_{i}', 'obstacles': ['shell', 'carrier_block', 'leaf_a', 'leaf_b', 'button'],
               'start_translation_mm': [0., 0., -(pin_top - pin_bottom) - 20.], 'translation_end_mm': [0., 0., 20. - .05], 'samples': 7, 'max_samples': 9, 'min_mm': .05} for i in (1, 2)]],
        'rotation_checks': [
            *[{'id': f'edge-press-twist-{sn}-{dn}', **moving, 'obstacles': ['shell', 'rest_stop'], **tw_axis,
               'start_translation_mm': [-short(dy), -dy, 0.], 'end_deg': sign * tw['twist_deg'], 'samples': 2, 'max_samples': 3, 'min_mm': p['twist_min_gap_mm']}
              for sn, sign in (('positive', 1.), ('negative', -1.)) for dn, dy in (('early', .3), ('deep', deep))],
            *[{'id': f'far-end-yaw-{sn}', **moving, 'obstacles': ['shell'], **yaw_axis,
               'start_translation_mm': [-short(.3), -.3, 0.], 'end_deg': sign * tw['yaw_deg'], 'samples': 2, 'max_samples': 3, 'min_mm': p['twist_min_gap_mm']}
              for sn, sign in (('positive', 1.), ('negative', -1.))],
            # The far end may meet the designed rest lug under a yaw (it is a stop), but must not pass into it beyond the preload.
            {'id': 'far-end-yaw-on-lug', **moving, 'obstacles': ['rest_stop'], **yaw_axis,
             'start_translation_mm': [-short(.3), -.3, 0.], 'end_deg': tw['yaw_deg'], 'samples': 2, 'max_samples': 3, 'min_mm': 0.}],
        'wall_checks': [{'id': 'shell-printed-wall', 'part': 'shell', 'min_mm': p['min_printed_wall_mm'], 'samples_per_face': 10},
                        {'id': 'button-printed-wall', 'part': 'button', 'min_mm': p['min_printed_wall_mm'], 'samples_per_face': 10}],
        'flexure_checks': [{'id': 'parallel-leaves-beam', 'part': 'leaf_a', 'beam_node': 'leaf_a', 'length_axis': 'x', 'fixed_end': 'min', 'bend_axis': 'y',
                            'end_condition': 'guided', 'parallel_count': 2,
                            'material': DEFAULT_MATERIAL, 'orientation': 'horizontal', 'strength_basis': 'tensile_strength', 'deflection_mm': deep + pre,
                            'min_force_n': p['force_band_min_n'], 'max_force_n': p['force_band_max_n'],
                            'force_basis': 'ASSUMED band 0.3-3 N for the worst case: leaves at the pin flush pose (with preload) plus the largest registered switch operating force.',
                            'switch_profiles': list(SWITCH_PROFILES), 'beam_force_ratio': 1., 'switch_force_ratio': 1.,
                            'ratio_basis': 'Translation: leaves, switch and press point share the same displacement (no lever).',
                            'stress_allowance': p['stress_allowance'], 'allowance_basis': 'ASSUMED half of the datasheet tensile strength (yield not published); fatigue UNKNOWN.',
                            'stress_concentration': p['stress_concentration'], 'stress_concentration_basis': 'ASSUMED 1.5 at R1-filleted corners joined over the full leaf width.'}],
        'base_shape_checks': [{'id': 'outer-form-matches-base', 'base_node': 'outer', 'parts': ['shell', 'button'], 'tolerance_mm': .05, 'samples_per_face': 12, 'regions': [
            {'id': 'side-button-region', 'kind': 'allowed_change', 'reason': 'Changes around the side buttons are allowed (window, running gap, insert head counterbore, face 0.1 mm below the skin at rest).',
             'lo_mm': [wl - 1., 20., zl - 1.], 'hi_mm': [wh + 3., 40., zh + 1.]},
            {'id': 'open-bottom', 'kind': 'not_in_base', 'reason': 'The base outer form is the skin; its bottom cap is the open rim.', 'lo_mm': [-70., -40., -.1], 'hi_mm': [70., 40., .1]}]}],
        'unverified_requirements': [
            '押しやすさ: 平行移動のため面のどこを押しても同じ力。この読み方はオーナー確認待ちの解釈。実機の押下感・クリック感は未試験。',
            f'Press force at the click about {k_pair * (click_travel + pre) + of_max:.2f} N (leaves {k_pair * (click_travel + pre):.2f} N + largest registered switch operating force); at the pin flush pose about {k_pair * (deep + pre) + of_max:.2f} N. The leaves add to the bare switch force.',
            f'Switch profiles (insert rule and travel stack from datasheets): {summary}.',
            'Leaves: beam theory only (guided small deflection, rigid root, typical datasheet values, ASSUMED stress concentration and Poisson ratio); creep and fatigue UNKNOWN.',
            'Switch bottoming force goes into the switch and the owner PCB (no hard stop); its rating and the PCB support are not modeled (UNKNOWN).',
            'Pin, insert and preload retention in printed ABS and print accuracy of the gaps are not qualified; presses load the pins in shear.',
            'PCB plane is ASSUMED; the real board and shell were not measured. OP1-supplied screws are not used by this carrier.',
            'Wall checks are sampled minima of the stated parts, not a proof of minimum wall or of strength.'],
    }
