"""Parametric mechanism templates that emit typed Recipes for compliant mouse buttons.

Templates are generic and built from documented assumptions: every dimension
is ASSUMED unless the caller passes a measured value, and every switch value
comes from the cited switch-profile library. A template never claims a pass
for a switch whose needed datasheet values are UNKNOWN.

* cantilever_main_click: a button plate on a long tongue (leaf spring) whose
  mounting pad is screw-fastened to a shell boss; the tongue bends, no pin.
* flexure_side_carrier: one printed carrier holding two side-button caps on a
  ladder frame of thin bars; it is fixed to shell posts by separately printed
  insert pins (default) or by snap hooks (alternative). Each cap's bars bend.

Rigid checks rotate each moving body about its flexure's pseudo-rigid-body
pivot (Howell, Compliant Mechanisms, 2001; gamma 0.85) with a pivot-play
envelope; flexures are checked by beam theory (recipe flexure_checks).
"""
from __future__ import annotations
import math
from typing import Literal

from .recipe import PRBM_GAMMA
from .switch_profiles import PROFILES as SWITCH_PROFILES
from .materials import DEFAULT_MATERIAL, MATERIALS

MAIN_CLICK_DEFAULTS = {
    'tongue_length_mm': 30., 'tongue_width_mm': 6., 'tongue_thickness_mm': 1.2,
    'cap_length_mm': 40., 'cap_width_mm': 22., 'cap_thickness_mm': 1.6,
    'pad_length_mm': 8., 'pad_thickness_mm': 2.4, 'boss_height_mm': 6., 'boss_radius_mm': 3.,
    'screw_clearance_radius_mm': 1.1, 'screw_tap_radius_mm': .8, 'screw_radius_mm': 1., 'screw_length_mm': 6.,
    'screw_head_radius_mm': 1.9, 'screw_head_height_mm': 1.2,
    'switch_from_cap_front_mm': 12., 'nub_radius_mm': 1., 'rest_gap_mm': .05,
    'pivot_play_mm': .05, 'deep_margin_deg': .03,
    'force_band_min_n': .3, 'force_band_max_n': 3., 'stress_allowance': .5,
}
ASSUMED_TEXT = {
    'dims': 'ASSUMED template dimensions (test subject); no product measurement.',
    'force_band': 'ASSUMED press-force band 0.3-3 N at the press point; no product target is set.',
    'stress_allowance': 'ASSUMED half of the datasheet tensile strength for a static check (ABS yield not published); fatigue strength is UNKNOWN.',
    'policy': 'Owner policy: ABS only; no screws except those supplied with the OP1.',
    'pivot_play': 'ASSUMED 0.05 mm pivot shift envelope for the pseudo-rigid-body approximation at small angles.',
}


def _box(node_id, function_id, reason, lo, hi):
    return {'id': node_id, 'op': 'box', 'function_id': function_id, 'reason': reason,
            'size_mm': [hi[i] - lo[i] for i in range(3)], 'center_mm': [(hi[i] + lo[i]) / 2 for i in range(3)]}


def _cyl(node_id, function_id, reason, radius, origin, height, axis=(0., 0., 1.)):
    return {'id': node_id, 'op': 'cylinder', 'function_id': function_id, 'reason': reason,
            'radius_mm': radius, 'height_mm': height, 'origin_mm': list(origin), 'axis': list(axis)}


def _complete_for_fixed_gap(profile):
    """A fixed (non-adjustable) gap needs FP, OP, body height and PT/OT from the datasheet."""
    need = ('free_position', 'operating_position', 'pretravel', 'overtravel', 'body_height', 'body_length',
            'body_width', 'plunger_width')
    return sorted(k for k in need if not getattr(profile, k).known)


def main_click_switch_fit(profile, p=None):
    """1-D stack for a fixed nub gap above the pin's free position (no adjuster)."""
    p = dict(MAIN_CLICK_DEFAULTS if p is None else p)
    missing = _complete_for_fixed_gap(profile)
    if missing:
        return {'profile': profile.id, 'verdict': 'unverified', 'missing': missing,
                'reason': 'A fixed gap needs the free position and travel limits; UNKNOWN values give no pass.'}
    fp = profile.free_position.value
    op, op_tol = profile.operating_position.value, profile.operating_position.tolerance or 0.
    top, top_tol = profile.body_height.value, profile.body_height.tolerance or 0.
    # FP is a maximum: the real pin top may be lower by up to PT max relative to OP; the nub must reach OP_min.
    to_operate = p['rest_gap_mm'] + fp - (op - op_tol)
    deepest = p['rest_gap_mm'] + fp - (top - top_tol)
    return {'profile': profile.id, 'verdict': 'pass', 'travel_to_operate_max_mm': to_operate,
            'travel_to_pin_flush_max_mm': deepest,
            'scope': 'Nub travel from rest to the lowest operating position and to the pin flush with the body (bounds bottoming); '
                     'the switch takes the overtravel.'}


def cantilever_main_click(switch_id: str = 'zippy_df_pin', p: dict | None = None, request: str | None = None) -> dict:
    """Main-click template: cap on a cantilever tongue, pad screw-fastened to a shell boss."""
    p = dict(MAIN_CLICK_DEFAULTS if p is None else p)
    profile = SWITCH_PROFILES[switch_id]
    fit = main_click_switch_fit(profile, p)
    if fit['verdict'] == 'unverified':
        raise ValueError(f'Switch profile {switch_id} lacks datasheet values for a fixed gap: {fit["missing"]}')
    lt, wt, tt = p['tongue_length_mm'], p['tongue_width_mm'], p['tongue_thickness_mm']
    lc, wc, tc = p['cap_length_mm'], p['cap_width_mm'], p['cap_thickness_mm']
    lp, tp = p['pad_length_mm'], p['pad_thickness_mm']
    # X runs forward from the pad's rear edge; Z up; pressing moves the cap toward -Z.
    x_root = lp; x_free = lp + lt; x_front = x_free + lc
    z_top = 0.; z_t0 = z_top - tt
    x_sw = x_front - p['switch_from_cap_front_mm']
    pivot = (x_root + (1 - PRBM_GAMMA) * lt, z_top - tt / 2)
    lever_sw = x_sw - pivot[0]; lever_press = (x_free + x_front) / 2 - pivot[0]
    deep_deg = -math.degrees(fit['travel_to_pin_flush_max_mm'] / lever_sw) - p['deep_margin_deg']
    nub_len = 1.
    fp = profile.free_position.value
    pin_top = z_top - tc - nub_len - p['rest_gap_mm']; base_z = pin_top - fp
    boss_top = z_top - tp
    sh, sl, sr = p['screw_head_height_mm'], p['screw_length_mm'], p['screw_radius_mm']
    ops = [
        _box('pad', 'F2_mount', 'Mounting pad of the button, screwed to the shell boss.', [0., -wt / 2 - 2., z_top - tp], [lp, wt / 2 + 2., z_top]),
        _box('tongue', 'F2_guide', 'Cantilever tongue (leaf spring): guide and return element.', [x_root, -wt / 2, z_t0], [x_free, wt / 2, z_top]),
        _box('cap', 'F1_press', 'Button cap pressed by the finger.', [x_free, -wc / 2, z_top - tc], [x_front, wc / 2, z_top]),
        _cyl('nub', 'F3_actuate', 'Actuator nub over the switch pin.', p['nub_radius_mm'], (x_sw, 0., z_top - tc - nub_len), nub_len + .01),
        {'id': 'button', 'op': 'union', 'function_id': 'F1_press', 'reason': 'Moving body: tongue, cap and nub (printed continuous with the pad).',
         'operands': ['tongue', 'cap', 'nub']},
        _cyl('pad_hole', 'F2_mount', 'Screw clearance hole in the pad.', p['screw_clearance_radius_mm'], (lp / 2, 0., z_top - tp - 1.), tp + 2.),
        {'id': 'mount_pad', 'op': 'difference', 'function_id': 'F2_mount', 'reason': 'Clamped pad (printed continuous with the tongue root).',
         'operands': ['pad', 'pad_hole']},
        _cyl('boss_body', 'F2_mount', 'Shell screw boss under the pad.', p['boss_radius_mm'], (lp / 2, 0., boss_top - p['boss_height_mm']), p['boss_height_mm']),
        _box('shell_plate', 'F2_mount', 'Stand-in shell floor carrying the boss.', [-4., -wc / 2 - 4., boss_top - p['boss_height_mm'] - 2.], [lp + 4., wc / 2 + 4., boss_top - p['boss_height_mm']]),
        {'id': 'shell_raw', 'op': 'union', 'function_id': 'F2_mount', 'reason': 'Boss on the stand-in shell floor.', 'operands': ['boss_body', 'shell_plate']},
        _cyl('boss_tap', 'F2_mount', 'Self-tapping pilot hole in the boss.', p['screw_tap_radius_mm'], (lp / 2, 0., boss_top - p['boss_height_mm'] + 1.), p['boss_height_mm']),
        {'id': 'shell', 'op': 'difference', 'function_id': 'F2_mount', 'reason': 'Boss with its pilot hole.', 'operands': ['shell_raw', 'boss_tap']},
        _cyl('screw_shank', 'F2_mount', 'M2 screw shank through the pad into the boss.', sr, (lp / 2, 0., z_top - sl), sl),
        _cyl('screw_head', 'F2_mount', 'M2 screw head clamping the pad.', p['screw_head_radius_mm'], (lp / 2, 0., z_top), sh),
        {'id': 'screw', 'op': 'union', 'function_id': 'F2_mount', 'reason': 'OP1-supplied screw (size UNKNOWN; M2 pan head ASSUMED).', 'operands': ['screw_shank', 'screw_head']},
        _box('switch_body', 'F3_actuate', f'Switch body from profile {profile.id}.',
             [x_sw - profile.body_length.value / 2, -profile.body_width.value / 2, base_z],
             [x_sw + profile.body_length.value / 2, profile.body_width.value / 2, base_z + profile.body_height.value]),
        _box('switch_pin', 'F3_actuate', 'Switch pin at its free position (FP max; pin x size UNKNOWN, 1.2 mm assumed).',
             [x_sw - .6, -profile.plunger_width.value / 2, base_z + profile.body_height.value], [x_sw + .6, profile.plunger_width.value / 2, pin_top]),
    ]
    axis = {'axis_origin_mm': [pivot[0], 0., pivot[1]], 'axis_direction': [0., 1., 0.]}
    # Positive rotation about +Y lowers +X points: press is positive here.
    press_deg = -deep_deg
    tip_defl = math.sin(math.radians(press_deg)) * PRBM_GAMMA * lt
    engaged = (boss_top) - (z_top - sl) - 0.  # shank length inside the boss below its top face
    engaged = min(engaged, p['boss_height_mm'] - 1.)
    ring = math.pi * (sr ** 2 - p['screw_tap_radius_mm'] ** 2)
    return {
        'title': f'Template: cantilever-tongue main click ({profile.id})',
        'original_request': request or 'Template test subject: main click on a screw-fastened cantilever tongue.',
        'design_parameters': {k: float(v) for k, v in p.items()},
        'parameter_basis': {k: ASSUMED_TEXT['dims'] for k in p},
        'functions': {'F1_press': 'Take the finger press on the cap.', 'F2_guide': 'Guide and return the cap by tongue bending.',
                      'F2_mount': 'Fix the tongue pad to the shell with a screw.', 'F3_actuate': 'Press the switch pin.'},
        'protected_constraints': ['Switch body is a placeholder from a cited profile; its pose is not changed.'],
        'design_basis': {'kind': 'first_principles', 'summary': 'Cap on a cantilever tongue screwed to a shell boss; the switch takes the overtravel.',
                         'assumptions': [ASSUMED_TEXT['dims'], ASSUMED_TEXT['force_band'], ASSUMED_TEXT['stress_allowance'], ASSUMED_TEXT['pivot_play'],
                                         ASSUMED_TEXT['policy'], 'ABS printed flat so tongue bending runs in the layer plane (ASSUMED orientation).',
                                         'Screw-fastened mount (common for main clicks) with an OP1-supplied screw; its size is UNKNOWN, an M2 x 6 pan head is the ASSUMED placeholder; it self-taps into the printed boss.']},
        'verification_plan': ['Pair overlap and bounds; declared screw thread fit.', f'Button clear of the shell from rest to {press_deg:.3f} deg (nub at the switch body top: pin flush, bounds bottoming), with pivot play.',
                              'Tongue: beam-theory stiffness, press force (tongue plus switch operating force) in band, static stress in allowance.'],
        'operations': ops,
        'outputs': [{'part_id': 'shell', 'node': 'shell'}, {'part_id': 'button', 'node': 'button', 'manufacturing_process': 'FDM, printed as one with the mount pad'},
                    {'part_id': 'mount_pad', 'node': 'mount_pad', 'manufacturing_process': 'FDM, same print as the button (clamped end of the tongue)'},
                    {'part_id': 'screw', 'node': 'screw', 'manufacturing_process': 'OP1-supplied screw (size UNKNOWN; M2 x 6 pan head ASSUMED placeholder), self-tapping into the boss'},
                    {'part_id': 'switch_body', 'node': 'switch_body', 'manufacturing_process': 'Placeholder for a purchased switch'},
                    {'part_id': 'switch_pin', 'node': 'switch_pin', 'manufacturing_process': 'Placeholder for the switch pin'}],
        'press_fits': [{'id': 'screw-thread', 'part_a': 'screw', 'part_b': 'shell', 'min_overlap_mm3': .7 * ring * engaged,
                        'max_overlap_mm3': 1.3 * ring * engaged, 'basis': 'M2 thread engaged in the printed boss, modeled as an interference annulus.'}],
        'clearance_checks': [{'id': 'rest-nub-pin-gap', 'part_a': 'button', 'part_b': 'switch_pin', 'min_mm': p['rest_gap_mm'] - 1e-3}],
        'rotation_checks': [
            {'id': 'press-to-pin-flush', 'moving_part': 'button', 'obstacles': ['shell'], **axis,
             'start_deg': 0., 'end_deg': press_deg, 'samples': 3, 'max_samples': 9, 'min_mm': 0., 'axis_play_mm': p['pivot_play_mm']}],
        'flexure_checks': [
            {'id': 'tongue-beam', 'part': 'button', 'beam_node': 'tongue', 'length_axis': 'x', 'fixed_end': 'min', 'bend_axis': 'z',
             'material': DEFAULT_MATERIAL, 'orientation': 'horizontal', 'strength_basis': 'tensile_strength', 'deflection_mm': tip_defl,
             'min_force_n': p['force_band_min_n'], 'max_force_n': p['force_band_max_n'], 'force_basis': ASSUMED_TEXT['force_band'],
             'switch_profiles': [switch_id], 'beam_force_ratio': PRBM_GAMMA * lt / lever_press, 'switch_force_ratio': lever_sw / lever_press,
             'ratio_basis': f'Moment balance about the pivot: tongue tip force at {PRBM_GAMMA * lt:.2f} mm, switch at {lever_sw:.2f} mm, press point (cap centre) at {lever_press:.2f} mm.',
             'stress_allowance': p['stress_allowance'], 'allowance_basis': ASSUMED_TEXT['stress_allowance']}],
        'unverified_requirements': ['Template test subject: dimensions ASSUMED; click feel and press force untested.',
                                    f'Switch {profile.id}: nub travel to operate up to {fit["travel_to_operate_max_mm"]:.2f} mm, to pin flush {fit["travel_to_pin_flush_max_mm"]:.2f} mm (datasheet limits).',
                                    'Tongue fatigue and creep UNKNOWN; screw holding torque in the printed boss not qualified.'],
    }


SIDE_CARRIER_DEFAULTS = {
    'frame_height_mm': 12., 'rail_width_mm': 1.5, 'frame_thickness_mm': 1.6, 'block_width_mm': 5., 'block_thickness_mm': 3.,
    'mount_span_mm': 60., 'bar_length_mm': 12., 'bar_width_mm': 4., 'bar_thickness_mm': 1.,
    'cap_length_mm': 14., 'cap_height_mm': 7., 'cap_thickness_mm': 1.6, 'nub_radius_mm': 1., 'nub_length_mm': 1., 'rest_gap_mm': .05,
    'pin_radius_mm': 1., 'pin_head_radius_mm': 1.8, 'pin_head_height_mm': 1., 'pin_clearance_mm': .1, 'pin_interference_mm': .05,
    'post_radius_mm': 2., 'post_engagement_mm': 4.,
    'hook_arm_length_mm': 8., 'hook_arm_thickness_mm': 1., 'hook_arm_width_mm': 3., 'hook_undercut_mm': .3, 'hook_lip_height_mm': 1.,
    'ledge_thickness_mm': 1.5,
    'pivot_play_mm': .05, 'deep_margin_deg': .03,
    'force_band_min_n': .3, 'force_band_max_n': 3., 'stress_allowance': .5,
    'insertion_force_max_n': 20., 'snap_strain_allowance': .5,
}


def flexure_side_carrier(switch_id: str = 'zippy_df_pin', retention: Literal['insert_pins', 'snap_hooks'] = 'insert_pins',
                         p: dict | None = None, request: str | None = None) -> dict:
    """Side-button carrier: two caps on cantilever bars of one ladder frame, fixed by insert pins or snap hooks."""
    p = dict(SIDE_CARRIER_DEFAULTS if p is None else p)
    profile = SWITCH_PROFILES[switch_id]
    fit = main_click_switch_fit(profile, {**MAIN_CLICK_DEFAULTS, 'rest_gap_mm': p['rest_gap_mm']})
    if fit['verdict'] == 'unverified':
        raise ValueError(f'Switch profile {switch_id} lacks datasheet values for a fixed gap: {fit["missing"]}')
    H, rw, tf = p['frame_height_mm'], p['rail_width_mm'], p['frame_thickness_mm']
    bw, tb, span = p['block_width_mm'], p['block_thickness_mm'], p['mount_span_mm']
    lb, wb, tbar = p['bar_length_mm'], p['bar_width_mm'], p['bar_thickness_mm']
    lc, hc, tc = p['cap_length_mm'], p['cap_height_mm'], p['cap_thickness_mm']
    xr, xf = 0., span  # mount block centres; X along the carrier, Y outward (press toward -Y), Z vertical
    fp = profile.free_position.value
    pin_top = -p['nub_length_mm'] - p['rest_gap_mm']; base_y = pin_top - fp
    shell_top = base_y
    ops = [
        _box('rear_block', 'F2_mount', 'Rear mounting block of the carrier.', [xr - bw / 2, 0., -H / 2], [xr + bw / 2, tb, H / 2]),
        _box('front_block', 'F2_mount', 'Front mounting block of the carrier.', [xf - bw / 2, 0., -H / 2], [xf + bw / 2, tb, H / 2]),
        _box('top_rail', 'F2_mount', 'Top rail of the ladder frame.', [xr + bw / 2, 0., H / 2 - rw], [xf - bw / 2, tf, H / 2]),
        _box('bottom_rail', 'F2_mount', 'Bottom rail of the ladder frame.', [xr + bw / 2, 0., -H / 2], [xf - bw / 2, tf, -H / 2 + rw]),
        _box('shell_plate', 'F2_mount', 'Stand-in shell side wall behind the carrier (PCB plane for the switches).',
             [xr - 8., shell_top - 2., -H / 2 - 4.], [xf + 8., shell_top, H / 2 + 4.]),
    ]
    frame_ops = ['rear_block', 'front_block']
    ops.append({'id': 'carrier_rails', 'op': 'union', 'function_id': 'F2_mount', 'reason': 'Ladder rails joining the blocks (same print).',
                'operands': ['top_rail', 'bottom_rail']})
    caps = []
    for i, (root, sign) in enumerate(((xr + bw / 2, 1.), (xf - bw / 2, -1.)), start=1):
        free = root + sign * lb
        x0, x1 = sorted((root, free)); cx0, cx1 = sorted((free, free + sign * lc)); xc = (cx0 + cx1) / 2
        pivot_x = root + sign * (1 - PRBM_GAMMA) * lb
        ops += [_box(f'bar_{i}', 'F2_guide', f'Cantilever bar of cap {i} (flexure: guide and return).', [x0, 0., -wb / 2], [x1, tbar, wb / 2]),
                _box(f'cap_{i}_plate', 'F1_press', f'Side-button cap {i}.', [cx0, 0., -hc / 2], [cx1, tc, hc / 2]),
                _cyl(f'nub_{i}', 'F3_actuate', f'Nub of cap {i} over its switch pin.', p['nub_radius_mm'], (xc, -p['nub_length_mm'], 0.), p['nub_length_mm'] + .01, (0., 1., 0.)),
                {'id': f'cap_{i}', 'op': 'union', 'function_id': 'F1_press', 'reason': f'Moving body {i}: bar, cap and nub (printed continuous with the frame).',
                 'operands': [f'bar_{i}', f'cap_{i}_plate', f'nub_{i}']},
                _box(f'switch_{i}_body', 'F3_actuate', f'Switch {i} body from profile {profile.id}.',
                     [xc - profile.body_length.value / 2, base_y, -profile.body_width.value / 2],
                     [xc + profile.body_length.value / 2, base_y + profile.body_height.value, profile.body_width.value / 2]),
                _box(f'switch_{i}_pin', 'F3_actuate', f'Switch {i} pin at its free position (pin x size UNKNOWN, 1.2 mm assumed).',
                     [xc - .6, base_y + profile.body_height.value, -profile.plunger_width.value / 2], [xc + .6, pin_top, profile.plunger_width.value / 2])]
        lever = abs(xc - pivot_x)
        caps.append({'i': i, 'pivot_x': pivot_x, 'sign': sign, 'lever': lever, 'root': root})
    outputs = [{'part_id': 'shell', 'node': 'shell'},
               {'part_id': 'carrier_frame', 'node': 'carrier_frame', 'expected_solids': 2,
                'manufacturing_process': 'FDM, one print with rails and both caps (the two mounting blocks)'},
               {'part_id': 'carrier_rails', 'node': 'carrier_rails', 'expected_solids': 2, 'manufacturing_process': 'FDM, same print as the carrier blocks'},
               *[{'part_id': f'cap_{c["i"]}', 'node': f'cap_{c["i"]}', 'manufacturing_process': 'FDM, same print as the carrier frame'} for c in caps],
               *[{'part_id': f'switch_{c["i"]}_{k}', 'node': f'switch_{c["i"]}_{k}', 'manufacturing_process': 'Placeholder for a purchased switch'}
                 for c in caps for k in ('body', 'pin')]]
    press_fits, clearance, motion, flexures = [], [], [], []
    if retention == 'insert_pins':
        r_pin, c, inter = p['pin_radius_mm'], p['pin_clearance_mm'], p['pin_interference_mm']
        eng = p['post_engagement_mm']
        for name, x in (('rear', xr), ('front', xf)):
            ops += [_cyl(f'{name}_post', 'F2_mount', f'{name.title()} shell post under the carrier block.', p['post_radius_mm'], (x, shell_top, 0.), -shell_top, (0., 1., 0.)),
                    _cyl(f'{name}_post_hole', 'F2_mount', f'{name.title()} post hole: press fit for the insert pin.', r_pin - inter, (x, -eng, 0.), eng + .01, (0., 1., 0.)),
                    _cyl(f'{name}_block_hole', 'F2_mount', f'{name.title()} block hole: clearance for the insert pin.', r_pin + c, (x, -.01, 0.), tb + .02, (0., 1., 0.)),
                    _cyl(f'{name}_pin_shank', 'F2_mount', f'{name.title()} printed insert pin shank.', r_pin, (x, -eng, 0.), eng + tb, (0., 1., 0.)),
                    _cyl(f'{name}_pin_head', 'F2_mount', f'{name.title()} insert pin head clamping the block.', p['pin_head_radius_mm'], (x, tb, 0.), p['pin_head_height_mm'], (0., 1., 0.)),
                    {'id': f'{name}_pin', 'op': 'union', 'function_id': 'F2_mount', 'reason': f'{name.title()} separately printed insert pin (default retention).',
                     'operands': [f'{name}_pin_shank', f'{name}_pin_head']}]
            outputs.append({'part_id': f'{name}_pin', 'node': f'{name}_pin', 'manufacturing_process': 'FDM ABS, separately printed insert pin'})
            ring = math.pi * (r_pin ** 2 - (r_pin - inter) ** 2) * eng
            press_fits.append({'id': f'{name}-pin-in-post', 'part_a': f'{name}_pin', 'part_b': 'shell', 'min_overlap_mm3': .7 * ring, 'max_overlap_mm3': 1.3 * ring,
                               'basis': f'ASSUMED {inter:.2f} mm radial interference over {eng:.1f} mm engagement in the printed post.'})
            # Shank runs in the block hole with radial clearance; the head seats on the block, so the sweep stops
            # one clearance short of seating and must keep that clearance all the way.
            motion.append({'id': f'{name}-pin-insertion', 'moving_part': f'{name}_pin', 'obstacles': ['carrier_frame', 'carrier_rails'] + [f'cap_{k["i"]}' for k in caps],
                           'start_translation_mm': [0., eng + tb + 6., 0.], 'translation_end_mm': [0., -(eng + tb + 6.) + c, 0.], 'samples': 9, 'max_samples': 33, 'min_mm': c - 1e-3})
        shell_ops = ['shell_plate', 'rear_post', 'front_post']
        ops += [{'id': 'shell_raw', 'op': 'union', 'function_id': 'F2_mount', 'reason': 'Shell wall with the two posts.', 'operands': shell_ops},
                {'id': 'shell', 'op': 'difference', 'function_id': 'F2_mount', 'reason': 'Posts with their pin holes.', 'operands': ['shell_raw', 'rear_post_hole', 'front_post_hole']},
                {'id': 'frame_raw', 'op': 'union', 'function_id': 'F2_mount', 'reason': 'Ladder frame: blocks and rails.', 'operands': frame_ops},
                {'id': 'carrier_frame', 'op': 'difference', 'function_id': 'F2_mount', 'reason': 'Frame with the pin clearance holes.', 'operands': ['frame_raw', 'rear_block_hole', 'front_block_hole']}]
    else:
        la, ta, wa, u, lip = p['hook_arm_length_mm'], p['hook_arm_thickness_mm'], p['hook_arm_width_mm'], p['hook_undercut_mm'], p['hook_lip_height_mm']
        ledge_t = p['ledge_thickness_mm']
        hook_ops = []
        for name, x, out in (('rear', xr, -1.), ('front', xf, 1.)):
            ax0 = x + out * bw / 2 - (ta if out > 0 else 0.)  # arm on the block's outer face
            ops += [_box(f'{name}_hook_arm', 'F2_mount', f'{name.title()} snap hook arm (cantilever).', [ax0, -la, -wa / 2], [ax0 + ta, 0., wa / 2]),
                    _box(f'{name}_hook_lip', 'F2_mount', f'{name.title()} snap hook lip ({u:.1f} mm undercut).',
                         [min(ax0, ax0 + out * u) if out < 0 else ax0, -la, -wa / 2], [ax0 + ta if out < 0 else ax0 + ta + u, -la + lip, wa / 2]),
                    _box(f'{name}_ledge', 'F2_mount', f'{name.title()} shell ledge the lip catches under.',
                         [ax0 - 6. if out < 0 else ax0 + ta, -la + lip, -wa / 2 - 2.], [ax0 if out < 0 else ax0 + ta + 6., -la + lip + ledge_t, wa / 2 + 2.]),
                    _box(f'{name}_ledge_post', 'F2_mount', f'{name.title()} post carrying the ledge from the shell wall.',
                         [ax0 - 6. if out < 0 else ax0 + ta + u + .3, shell_top, -wa / 2 - 2.], [ax0 - 4. if out < 0 else ax0 + ta + 6., -la + lip + ledge_t, wa / 2 + 2.])]
            # Lip moves the arm outward by the undercut while it passes the ledge edge.
            flexures.append({'id': f'{name}-hook-arm', 'part': 'carrier_frame', 'beam_node': f'{name}_hook_arm', 'length_axis': 'y', 'fixed_end': 'max',
                             'bend_axis': 'x', 'material': DEFAULT_MATERIAL, 'orientation': 'horizontal', 'strength_basis': 'tensile_strength',
                             'deflection_mm': u, 'min_force_n': 0., 'max_force_n': p['insertion_force_max_n'],
                             'force_basis': 'ASSUMED insertion force limit per hook for hand assembly.', 'switch_profiles': [],
                             'stress_allowance': p['snap_strain_allowance'], 'allowance_basis': 'ASSUMED half of yield for a few assembly cycles; fatigue UNKNOWN.'})
            hook_ops += [f'{name}_hook_arm', f'{name}_hook_lip']
            # Retention: the lip must sit under the ledge with no rigid overlap.
            clearance.append({'id': f'{name}-lip-under-ledge', 'part_a': 'carrier_frame', 'part_b': 'shell', 'min_mm': 0.})
        ops += [{'id': 'shell', 'op': 'union', 'function_id': 'F2_mount', 'reason': 'Shell wall with ledges for the snap hooks.',
                 'operands': ['shell_plate', 'rear_ledge', 'rear_ledge_post', 'front_ledge', 'front_ledge_post']},
                {'id': 'carrier_frame', 'op': 'union', 'function_id': 'F2_mount', 'reason': 'Ladder frame with snap hooks (alternative retention).',
                 'operands': frame_ops + hook_ops}]
        clearance = clearance[:1]
    rotation = []
    for c_ in caps:
        i = c_['i']; pivot = [c_['pivot_x'], tbar / 2, 0.]
        deep = math.degrees(fit['travel_to_pin_flush_max_mm'] / c_['lever']) + p['deep_margin_deg']
        end = -deep if c_['sign'] > 0 else deep
        others = [f'cap_{k["i"]}' for k in caps if k['i'] != i]
        # The bar root is continuous with its mounting block (not a rigid joint), so the block is not an obstacle here.
        rotation.append({'id': f'cap-{i}-press-to-pin-flush', 'moving_part': f'cap_{i}', 'obstacles': ['shell', 'carrier_rails'] + others,
                         'axis_origin_mm': pivot, 'axis_direction': [0., 0., 1.], 'start_deg': 0., 'end_deg': end,
                         'samples': 3, 'max_samples': 9, 'min_mm': 0., 'axis_play_mm': p['pivot_play_mm']})
        tip = math.sin(math.radians(deep)) * PRBM_GAMMA * lb
        flexures.append({'id': f'bar-{i}-beam', 'part': f'cap_{i}', 'beam_node': f'bar_{i}', 'length_axis': 'x', 'fixed_end': 'min' if c_['sign'] > 0 else 'max',
                         'bend_axis': 'y', 'material': DEFAULT_MATERIAL, 'orientation': 'horizontal', 'strength_basis': 'tensile_strength', 'deflection_mm': tip,
                         'min_force_n': p['force_band_min_n'], 'max_force_n': p['force_band_max_n'], 'force_basis': ASSUMED_TEXT['force_band'],
                         'switch_profiles': [switch_id], 'beam_force_ratio': PRBM_GAMMA * lb / c_['lever'], 'switch_force_ratio': 1.,
                         'ratio_basis': f'Moment balance about the bar pivot: bar tip force at {PRBM_GAMMA * lb:.2f} mm, switch and press point at {c_["lever"]:.2f} mm.',
                         'stress_allowance': p['stress_allowance'], 'allowance_basis': ASSUMED_TEXT['stress_allowance']})
    retention_text = ('Separately printed insert pins: clearance in the carrier block, ASSUMED interference in the shell post (default for 3D printing).'
                      if retention == 'insert_pins' else 'Snap hooks on the carrier blocks catching under shell ledges (alternative retention).')
    return {
        'title': f'Template: flexure side-button carrier ({retention}, {profile.id})',
        'original_request': request or 'Template test subject: one-piece flexure carrier for two side buttons.',
        'design_parameters': {k: float(v) for k, v in p.items()},
        'parameter_basis': {k: ASSUMED_TEXT['dims'] for k in p},
        'functions': {'F1_press': 'Take the thumb press on each cap.', 'F2_guide': 'Guide and return each cap by bar bending.',
                      'F2_mount': 'Fix the carrier to the shell.', 'F3_actuate': 'Press each switch pin.'},
        'protected_constraints': ['Switch bodies are placeholders from a cited profile; their poses are not changed.'],
        'design_basis': {'kind': 'first_principles', 'summary': 'Two side-button caps on cantilever bars of one printed ladder frame; switches take the overtravel.',
                         'assumptions': [ASSUMED_TEXT['dims'], ASSUMED_TEXT['force_band'], ASSUMED_TEXT['stress_allowance'], ASSUMED_TEXT['pivot_play'],
                                         retention_text, ASSUMED_TEXT['policy'], 'ABS; bars and hooks printed so bending runs in the layer plane (ASSUMED orientation).']},
        'verification_plan': ['Pair overlap and bounds; declared fits.', 'Each cap clear of shell, frame and the other cap to the pin-flush pose, with pivot play.',
                              'Bars (and snap hook arms when used): beam-theory stiffness, force band and static stress.'],
        'operations': ops, 'outputs': outputs, 'press_fits': press_fits, 'clearance_checks': clearance, 'motion_checks': motion,
        'rotation_checks': rotation, 'flexure_checks': flexures,
        'unverified_requirements': ['Template test subject: dimensions ASSUMED; click feel and press force untested.',
                                    'Bar and hook fatigue and creep UNKNOWN; pin retention force in the printed post not qualified.',
                                    f'Switch {profile.id}: nub travel to operate up to {fit["travel_to_operate_max_mm"]:.2f} mm (datasheet limits).'],
    }
