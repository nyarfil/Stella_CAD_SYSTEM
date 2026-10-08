"""Re-check the frozen r18 side-button recipe with the system lessons of its review.

Imports the r18 recipe unchanged, adds (a) a stop-travel check (load cases: centre press, carrier yaw +/-, far-end press yaw +/-)
and (b) lets the tolerance coverage audit mark existing checks that omit the declared carrier placement tolerance.
Writes verification/r18-system-lessons-20261008/RESULT.json. Rigid-body model; elastic deformation is excluded.
"""
from __future__ import annotations
import json
import math
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))

from cadmcp_brain.studio.recipe import Recipe,execute_recipe
from cadmcp_brain.studio.switch_profiles import PROFILES as SWITCH_PROFILES
from side_button_leaf_recipe import P18,carrier_tolerance_v18,side_button_parallel_recipe_v18,stack_v18,twist_v18

OUT=ROOT/'verification'/'r18-system-lessons-20261008'


def build_stop_check(recipe,check_id,margin_mm,margin_note,p=P18):
    checks={c['id']:c for c in recipe['rotation_checks']+recipe['motion_checks']}
    press=checks['press-to-stop-clear-of-shell']  # the recipe's own rest pose and press path to the stop (+ tolerance)
    yaw=checks['far-end-yaw-positive-stop']      # the recipe's own yaw axis and far-end press yaw
    rest=list(press['start_translation_mm']);end=list(press['translation_end_mm'])
    norm=math.sqrt(sum(x*x for x in end));direction=[x/norm for x in end]
    axis={'axis_point':list(yaw['axis_origin_mm']),'axis_direction':list(yaw['axis_direction'])}
    px=(p['plunger_x_min_mm']+p['plunger_x_max_mm'])/2;pz=(p['plunger_z_min_mm']+p['plunger_z_max_mm'])/2
    tip_y=p['plunger_tip_y_mm']-p['tip_length_mm']
    fits=[stack_v18(pr,p) for pr in SWITCH_PROFILES.values()]
    click_hi=max(f['rest_above_op_mm'][1] for f in fits if f['verdict']!='unverified')
    carrier_deg=carrier_tolerance_v18(p)['rotation_deg'];far_deg=twist_v18(p)['yaw_deg']
    max_travel=norm+.3
    def case(cid,angle):
        return {'id':cid,'direction':direction,'max_travel_mm':max_travel,
                'rotation':None if angle is None else {**axis,'angle_deg':angle}}
    return {'id':check_id,'moving_part':'button','carried_parts':['actuator_insert'],
            'stop_obstacles':['stop_jaw','stop_post'],'start_translation_mm':rest,
            'reference_point':[px,tip_y,pz],'reference_direction':[0.,-1.,0.],
            'required_min_travel_mm':click_hi,'margin_mm':margin_mm,
            'requirement_source':f'worst-case click {click_hi:.2f} mm after rest from the switch profiles (insert rule rest_above_op upper bound); '+margin_note,
            'load_cases':[case('centre-press',None),case('carrier-yaw-positive',carrier_deg),case('carrier-yaw-negative',-carrier_deg),
                          case('far-end-yaw-positive',far_deg),case('far-end-yaw-negative',-far_deg)],
            'tolerance_ids':[t['id'] for t in recipe['placement_tolerances']]}


def main():
    recipe=side_button_parallel_recipe_v18()
    dT=P18['stop_travel_tolerance_mm']
    # The +/-dT print error of the lip and jaw faces is a declared recipe parameter but not a placement tolerance, so the geometry
    # is nominal in it; the primary check carries it as the margin, the second shows the number without it.
    recipe['stop_travel_checks']=[build_stop_check(recipe,'stop-reference-travel',dT,f'margin {dT:.2f} mm = declared stop travel print tolerance (not modelled in the geometry)'),
                                  build_stop_check(recipe,'stop-reference-travel-no-print-margin',0.,'no margin (geometry only, nominal stop faces)')]
    Recipe.model_validate(recipe)
    with tempfile.TemporaryDirectory() as tmp:
        result=execute_recipe(recipe,{},Path(tmp)/'r18')
    checks={c['id']:c for c in result['checks']}
    stop=checks['stop-reference-travel'];stop0=checks['stop-reference-travel-no-print-margin']
    unverified=[{'id':c['id'],'reason':c['reason'],'computed_verdict':c['computed_verdict']} for c in result['checks'] if c['verdict']=='unverified']
    keys=('verdict','required_min_travel_mm','margin_mm','requirement_source','min_reference_travel_mm','governing_load_case',
          'governing_placement','governing_stop_obstacle','margin_left_mm','cases_evaluated')
    summary={'stop_travel':{k:stop[k] for k in keys},'stop_travel_no_print_margin':{k:stop0[k] for k in keys},
             'tolerance_coverage_audit':{'unverified_checks':unverified,'count':len(unverified)},
             'other_failed_checks':[c['id'] for c in result['checks'] if c['verdict']=='fail' and not c['id'].startswith('stop-reference-travel')],
             'geometry_checks_verdict':result['geometry_checks_verdict']}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'RESULT.json').write_text(json.dumps({'summary':summary,'stop_travel_check':stop,'stop_travel_check_no_print_margin':stop0,'checks':result['checks'],
                                               'scope':'The r18 subject is unchanged. Rigid-body approximation; elastic deformation excluded.'},indent=1,default=str),encoding='utf-8')
    print(json.dumps(summary,indent=1,default=str))


if __name__=='__main__':
    main()
