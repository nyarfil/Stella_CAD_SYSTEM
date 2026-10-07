"""Design-doc §22 side-button flow, end to end through the real Studio tools.

STEP 1-7  intent, reference inspection, function decomposition, Req2CAD search
          (recorded honestly when the catalog is not installed), morphology
          portfolio and concept synthesis;
STEP 8-10 typed recipe, real worker build, deterministic verification;
STEP 11+  role packets.  Reviews are produced OUTSIDE this script by separate
          reviewers and submitted with --submit-reviews; this script never
          writes a review itself, and never marks a design accepted.

    python scripts/check_side_button_flow.py --run-root verification/side-button-YYYYMMDD
    python scripts/check_side_button_flow.py --run-root ... --submit-reviews DIR
    python scripts/check_side_button_flow.py --run-root ... --delivery
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))

from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError
from cadmcp_brain.req2cad.common import atomic_json,file_hash,json_load
from cadmcp_brain.studio.runtime import ROLES
from side_button_recipe import (REQUEST,P,P2,P3,P4,P5,angles_v2,angles_v3,angles_v4,angles_v5,press_angle_deg,
                                side_button_recipe,side_button_recipe_v2,side_button_recipe_v3,side_button_recipe_v4,
                                side_button_recipe_v5,stop_angle_deg)

PROJECT_ID='side-button-flow'
VERIFICATION_ROOT=(ROOT/'verification').resolve()


def _basis(principles,assumptions,plan,unknowns):
    return {'kind':'first_principles','principles':principles,'assumptions':assumptions,
            'verification_plan':plan,'unknowns':unknowns}


def function_brief():
    def task(fid,excerpt,function,behavior,queries):
        return {'id':fid,'source_excerpt':excerpt,'function':function,'behavior':behavior,'queries':queries}
    return {'original_request':REQUEST,
            'functions':[
                task('F1_transmit_force','もっと押しやすく','transmit thumb force',
                     'Thumb force on the side skin reaches the button body without the skin flexing away.',
                     ['side button thumb pad','push button cap']),
                task('F2_guide_button','サイドボタン','guide button motion',
                     'The button moves on one controlled path without rattling against the shell.',
                     ['hinged button pivot','button guide rail']),
                task('F3_actuate_switch','仮のスイッチ外形','actuate switch',
                     'The plunger pushes the switch stem through its operating travel.',
                     ['switch plunger','actuator stem push']),
                task('F4_restore_button','仮のスイッチ外形','restore button',
                     'The button returns to rest after release.',['return spring button','snap dome return']),
                task('F5_limit_overtravel','もっと押しやすく','limit overtravel',
                     'Motion stops before the switch housing is loaded.',['hard stop','travel limiter']),
                task('F6_connect_shell','外形はできるだけ変えないで','connect to shell without changing outer form',
                     'The button and hinge are carried by the shell while the outer skin stays unchanged.',
                     ['flush shell button','shell mounted hinge'])],
            'protected_constraints':['Outer shell skin is not reshaped; the button face is the removed skin piece.'],
            'unresolved':['Target press force, travel and click feel are not specified by the owner.',
                          'Real switch, PCB and shell CAD were not provided; placeholders are used.']}


def morphology_matrix():
    common_unknowns=['Press force and click feel need a physical test with the real switch.']
    def option(oid,name,covers,principle,parts,force,assembly,risks,assumptions):
        return {'id':oid,'name':name,'covers':covers,'mechanism_principle':principle,'proposed_parts':parts,
                'force_path':force,'assembly_method':assembly,'risks':risks,
                'design_basis':_basis([principle],assumptions,
                                      ['Build the CAD and run clearance, rotation and wall checks.'],common_unknowns)}
    return {'brief':function_brief(),'options':[
        option('A_direct','Direct plunger',['F1_transmit_force','F3_actuate_switch'],
               'Skin piece translates and presses the switch directly beneath the thumb.',['button'],
               'Thumb to skin piece to switch stem in one line.','Drop-in button from inside the shell.',
               ['Translation needs guide rails; rattle if the guide is short.'],['A sliding guide can be printed with play.']),
        option('B_lever','Lever plunger',['F1_transmit_force','F3_actuate_switch'],
               'Skin piece is a lever arm; the plunger near the free end presses the switch.',['button'],
               'Thumb to lever to plunger to switch stem; reaction through the hinge pin.',
               'Button barrel slides over the pin from below before the PCB is fitted.',
               ['Force varies along the button length.'],['Pin hinge play is small relative to the stroke.']),
        option('C_flexure','Flexure button',['F1_transmit_force','F3_actuate_switch','F4_restore_button'],
               'Skin piece is joined to the shell by a thin flexure that also springs back.',['shell'],
               'Thumb to skin piece; flexure bends and stores return energy.','Printed as one with the shell.',
               ['Flexure stiffness and fatigue are unknown; not verifiable by rigid checks.'],
               ['PLA/PETG flexure survives the press count.']),
        option('G_pivot','Pin pivot',['F2_guide_button','F6_connect_shell'],
               'A fixed pin in shell tabs carries the button barrel.',['shell','button'],
               'Reaction from barrel to pin to tabs to shell wall.','Pin is part of the shell; barrel slides on.',
               ['Pin can break if undersized.'],['Printed pin is strong enough for thumb loads.']),
        option('G_rails','Guide rails',['F2_guide_button','F6_connect_shell'],
               'Rails inside the shell guide a translating button.',['shell','button'],
               'Reaction through rail contact faces.','Button inserted along the rails.',
               ['Rails need tight print tolerance.'],['Rails are printable without supports.']),
        option('R_switch','Switch spring return',['F4_restore_button'],
               'The switch stem spring returns the button.',['switch'],
               'Stem spring pushes the plunger back.','No extra part.',
               ['Return force depends on the unknown switch.'],['The switch spring alone returns the button.']),
        option('R_spring','Separate spring',['F4_restore_button'],
               'A separate spring returns the button.',['spring'],
               'Spring between shell and button.','Spring inserted during assembly.',
               ['Extra purchased part.'],['A suitable spring is available.']),
        option('S_hardstop','Hard stop',['F5_limit_overtravel'],
               'A shell stop meets a button tongue before the switch housing is reached.',['shell','button'],
               'Overtravel force goes into the shell stop, not the switch.','Stop is printed with the shell.',
               ['Stop wear.'],['The stop face is reached before the housing.']),
    ],'incompatibilities':[
        {'option_a':'C_flexure','option_b':'R_spring','reason':'A flexure already returns the button.'},
        {'option_a':'C_flexure','option_b':'G_pivot','reason':'A flexure button has no separate pivot.'},
        {'option_a':'A_direct','option_b':'G_pivot','reason':'A translating button is not carried by a pivot.'},
        {'option_a':'B_lever','option_b':'G_rails','reason':'A lever needs a pivot, not rails.'}]}


CHOSEN={1:{'B_lever','G_pivot','R_switch','S_hardstop'},2:{'B_lever','G_pivot','R_spring','S_hardstop'},
        3:{'B_lever','G_pivot','R_spring','S_hardstop'},4:{'B_lever','G_pivot','R_spring','S_hardstop'},
        5:{'B_lever','G_pivot','R_spring','S_hardstop'}}
REASONS={
    1:'Lever on a pin pivot keeps the outer skin unchanged and is fully covered by rigid rotation, '
      'clearance and wall checks; the switch spring avoids an extra part. Flexure options cannot be '
      'verified by the current kernel checks and would leave the return function UNKNOWN.',
    2:'Revision 2 after the five-role review of revision 1: the switch stem cannot hold the rest pose, so a '
      'separate preload spring (placeholder) returns the button against a modeled rest stop. The lever stays '
      'because its rest stop, hard stop, hinge play and assembly path are all checkable; the translating '
      'direct-plunger alternative was not built and remains an owner option, as does the meaning of '
      '"easier to press".',
    3:'Revision 3 after the five-role review of revision 2: same concept; the stop web, far stop datum, '
      'modeled spring envelope and reamed hinge address the new blockers. The part list is shell, button, '
      'dowel and spring plus the switch; the translating alternative remains an owner option.',
    4:'Revision 4 after the five-role review of revision 3 (no blocking findings): same concept; tilt and axial '
      'play are checked, the spring and plug are fitted last through a through pocket, and the button has one '
      'bed plane. Parts: shell, button, dowel, spring, plug, plus the switch. Force-factor hypothesis 17/(x+15) '
      'is recorded as a designer hypothesis, not a target.',
    5:'Revision 5 after the five-role review of revision 4 (no blocking findings): same concept; declared press '
      'fits replace clearance-modeled "press fits", gaps lie on a 0.2 mm layer grid, the stop web bed edges are '
      'chamfered, a back stiffener carries a firm press to the hinge-side stop, and the switch window is stated.'}


def engineering_evaluation(candidates,revision=1):
    """Host rationale for STEP 7; recorded as a judgement, not a measurement."""
    rows=[]
    for c in candidates:
        ids={o['id'] for o in c['options']}
        rows.append({'options':sorted(ids),'candidate_digest':c['candidate_digest'],
                     'verifiable_with_current_checks':'C_flexure' not in ids,
                     'concept_part_names':c['part_names'],
                     'concept_part_count_note':'Concept-level part names only; the built part list is recorded in step 9_10.',
                     'note':('Flexure return/stiffness would remain UNKNOWN (no elastic check).' if 'C_flexure' in ids
                             else 'Rigid motion, clearance and wall checks apply.')})
    chosen=next((r for r in rows if CHOSEN[revision]<=set(r['options'])),None)
    return {'rows':rows,'chosen':chosen,'revision':revision,'reason':REASONS[revision],
            'kind':'host_engineering_judgement_not_measurement'}


def resolve_run_root(value,must_exist):
    candidate=Path(value).resolve()
    try:candidate.relative_to(VERIFICATION_ROOT)
    except ValueError as exc:raise ValueError('Run root must stay under this checkout verification directory.') from exc
    if candidate==VERIFICATION_ROOT:raise ValueError('Run root must be a child of the verification directory.')
    if must_exist and not (candidate/'FLOW_RESULT.json').is_file():raise ValueError('Run root has no FLOW_RESULT.json.')
    if not must_exist and candidate.exists():raise ValueError('Run root must be a new path; existing evidence is immutable.')
    return candidate


def open_tools(run_root):
    os.environ['CADMCP_REQ2CAD_ROOT']=str((run_root/'isolated-req2cad').resolve())
    return Tools(Brain(run_root/'workspace'))


def run_flow(run_root,design_revision=1):
    run_root.mkdir(parents=True)
    tools=open_tools(run_root)
    steps={}
    opened=tools.brain_open(PROJECT_ID,REQUEST)
    revision=tools.brain_get(PROJECT_ID)['project']['revision']
    steps['1_intent']={'explicit':['もっと押しやすく'],'preference':['外形はできるだけ変えないで'],
                       'unknown':['target force','travel','allowed internal volume','real switch'],
                       'project_open':opened}
    steps['2_reference_inspection']={'status':'not_available',
        'reason':'No PCB/shell/switch STEP was provided; the recipe uses an explicit stand-in shell and placeholder switch.'}
    brief=function_brief()
    steps['3_function_decomposition']=brief['functions']
    try:steps['4_req2cad_search']={'status':'ran','result':tools.brain_fs_search_tasks(brief,'semantic')}
    except BrainError as exc:
        steps['4_req2cad_search']={'status':'not_available','error':exc.as_dict(),
                                   'consequence':'Options are first-principles; no catalog evidence is claimed.'}
    synthesis=tools.brain_studio_synthesize(PROJECT_ID,revision,morphology_matrix())
    steps['5_6_portfolio_and_synthesis']=synthesis
    steps['7_engineering_evaluation']=engineering_evaluation(synthesis['candidates'],design_revision)
    if design_revision==1:
        recipe=side_button_recipe()
        steps['8_recipe']={'revision':1,'press_angle_deg':press_angle_deg(),'stop_angle_deg':stop_angle_deg(),'parameters':P}
    elif design_revision==2:
        recipe=side_button_recipe_v2()
        steps['8_recipe']={'revision':2,'angles_deg':angles_v2(),'parameters':P2,
                           'lineage':'Separate prototype, not a lineage-verified correction: hinge geometry changes the '
                                     'check angles, and revision 2 adds checks that revision 1 did not carry.'}
    elif design_revision==5:
        recipe=side_button_recipe_v5()
        steps['8_recipe']={'revision':5,'angles_deg':angles_v5(),'parameters':P5,
                           'lineage':'Separate prototype, not a lineage-verified correction: press fits and stiffener '
                                     'change the part contract and checks.'}
    elif design_revision==4:
        recipe=side_button_recipe_v4()
        steps['8_recipe']={'revision':4,'angles_deg':angles_v4(),'parameters':P4,
                           'lineage':'Separate prototype, not a lineage-verified correction: hinge play, tilt and '
                                     'assembly checks change the check set.'}
    else:
        recipe=side_button_recipe_v3()
        steps['8_recipe']={'revision':3,'angles_deg':angles_v3(),'parameters':P3,
                           'lineage':'Separate prototype, not a lineage-verified correction: stop geometry and '
                                     'hinge play change the check angles and checks.'}
    build=tools.brain_studio_build(PROJECT_ID,revision,recipe,timeout_seconds=300)
    steps['9_10_build_and_verification']={k:build[k] for k in ('subject_digest','folder','assembly_step','recipe_path',
                                                                'geometry_checks_verdict','report_html')}
    steps['9_10_build_and_verification']['failed_checks']=[c['id'] for c in build['checks'] if c['verdict']!='pass']
    steps['9_10_build_and_verification']['built_parts']=[o['part_id'] for o in recipe['outputs']]
    packets={}
    for role in ROLES:
        tools.brain_studio_review_packet(PROJECT_ID,revision,build['subject_digest'],role)
        packets[role]=str(Path(tools._studio().root/PROJECT_ID/'reviews'/build['subject_digest']/(role+'-packet.json')).resolve())
    steps['11_review_packets']=packets
    result={'project_id':PROJECT_ID,'revision':revision,'subject_digest':build['subject_digest'],
            'request':REQUEST,'steps':steps,'reviews':'not_submitted','acceptance_status':'not_accepted',
            'overall_verdict':'unknown','physical_performance_certified':False}
    atomic_json(run_root/'FLOW_RESULT.json',result)
    return result


def submit_reviews(run_root,review_dir):
    """Submit reviewer-written JSON files: round-1 files first, then round 2 challenging every round-1 id."""
    flow=json_load(run_root/'FLOW_RESULT.json');tools=open_tools(run_root)
    project,revision,subject=flow['project_id'],flow['revision'],flow['subject_digest']
    receipts=[]
    # Round two challenges every saved round-one review, including earlier submissions.
    saved=tools._studio().root/PROJECT_ID/'reviews'/subject
    round_one_ids=[path.stem.removeprefix('review-') for path in sorted(saved.glob('review-*.json'))
                   if json_load(path)['report']['discussion_round']==1]
    files=sorted(Path(review_dir).glob('*.json'))
    for round_number in (1,2):
        for path in files:
            review=json_load(path)
            if review.get('discussion_round',1)!=round_number:continue
            if round_number==2:review['challenged_review_ids']=list(round_one_ids)
            receipt=tools.brain_studio_submit_review(project,revision,subject,review)
            if round_number==1:round_one_ids.append(receipt['review_id'])
            receipts.append({'file':str(path.resolve()),'sha256':file_hash(path),'round':round_number,
                             'role':review.get('role'),**receipt})
    status=tools.brain_studio_review_status(project,revision,subject)
    report={'receipts':receipts,'status':status}
    atomic_json(run_root/('REVIEW_SUBMISSION-'+Path(review_dir).name+'.json'),report)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--run-root',type=Path,required=True,help='Directory under this checkout verification folder.')
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--submit-reviews',type=Path,help='Directory of reviewer-written Review JSON files.')
    group.add_argument('--delivery',action='store_true',help='Write the hash-bound human handoff for the built subject.')
    parser.add_argument('--revision',type=int,choices=(1,2,3,4,5),default=5,help='Design revision to build (new runs only).')
    args=parser.parse_args(argv)
    try:run_root=resolve_run_root(args.run_root,must_exist=bool(args.submit_reviews or args.delivery))
    except ValueError as exc:parser.error(str(exc))
    try:
        if args.submit_reviews:result=submit_reviews(run_root,args.submit_reviews)
        elif args.delivery:
            flow=json_load(run_root/'FLOW_RESULT.json')
            result=open_tools(run_root).brain_studio_delivery(flow['project_id'],flow['revision'],flow['subject_digest'])
        else:result=run_flow(run_root,args.revision)
    except BrainError as exc:
        print(json.dumps({'error':exc.as_dict()},ensure_ascii=False,indent=2));return 1
    print(json.dumps(result,ensure_ascii=False,indent=2,default=str)[:20000])
    return 0


if __name__=='__main__':raise SystemExit(main())
