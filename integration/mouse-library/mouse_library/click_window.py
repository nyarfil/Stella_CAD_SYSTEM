"""Conservative click compression conditions, never a physical fit certificate."""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import math
from typing import Any

UNITS = {name: 'mm' for name in ('gap', 'rest_closure', 'pre_stop_closure',
    'post_stop_closure', 'on_compression', 'off_compression', 'allowable_compression',
    'on_margin', 'release_margin', 'safety_margin')}
UNITS['design_load'] = 'N'
KINDS = ['measured', 'manufacturer_specification', 'cad_computed', 'proposed']
SOURCE_SCHEMA = {'type':'object','additionalProperties':False,
    'required':['kind','evidence_ref','hardware_scope'], 'properties': {
        'kind':{'enum':KINDS}, 'evidence_ref':{'type':'string','minLength':1,'maxLength':1000},
        'hardware_scope':{'type':'string','minLength':1,'maxLength':300}}}

ALLOWABLE_DEFINITION = 'maximum_permitted_compression_not_minimum_overtravel'

def interval_schema(unit: str, name: str) -> dict:
    schema = {'type':'object','additionalProperties':False,'required':['min','max','unit','source'],
        'properties':{'min':{'type':'number','minimum':-10000,'maximum':10000},
                      'max':{'type':'number','minimum':-10000,'maximum':10000},
                      'unit':{'const':unit},'source':SOURCE_SCHEMA}}
    if name=='allowable_compression':
        schema['required'].append('definition')
        schema['properties']['definition']={'const':ALLOWABLE_DEFINITION}
    if name not in ('gap','rest_closure','pre_stop_closure','post_stop_closure'):
        for key in ('min','max'):
            schema['properties'][key]['minimum']=0
    if name in ('on_compression','design_load'):
        for key in ('min','max'):
            schema['properties'][key]['exclusiveMinimum']=0
    return schema

INPUT_SCHEMA = {'type':'object','additionalProperties':False,
    'required':['hardware_id','coordinate_basis','quantities','state_context'], 'properties':{
        'hardware_id':{'type':'string','minLength':1,'maxLength':200},
        'coordinate_basis':{'type':'string','minLength':1,'maxLength':2000,
            'description':'Define a common u=0 datum and plunger axis; gap is signed clearance at u=0. Do not double-count gap tolerances in closure. Not finger motion.'},
        'state_context':{'type':'object','additionalProperties':False,
            'properties':{name:{'type':'string','minLength':1,'maxLength':1000} for name in ('rest_closure','pre_stop_closure','post_stop_closure')},
            'description':'Rest after depression/release history; immediately before stop contact; after stop at design_load, with relative support deflection included.'},
        'quantities':{'type':'object','additionalProperties':False,
            'properties':{name:interval_schema(unit,name) for name,unit in UNITS.items()}}}}

def _object(value: Any, allowed: set[str], label: str) -> dict:
    if not isinstance(value,dict) or set(value)-allowed:
        raise ValueError(f'{label}: expected object with known keys')
    return value

def _text(value: Any, limit: int, label: str) -> str:
    if not isinstance(value,str) or not 1<=len(value)<=limit or not value.strip():
        raise ValueError(f'{label}: expected nonempty bounded string')
    return value

def _number(value: Any, label: str) -> Decimal:
    if type(value) not in (int,float) or abs(value)>10000 or not math.isfinite(value):
        raise ValueError(f'{label}: expected finite number in [-10000,10000]')
    return Decimal(str(value))

def evaluate(arguments: dict[str,Any]) -> dict[str,Any]:
    """Evaluate supplied independent bounds with Decimal arithmetic."""
    args=_object(arguments,{'hardware_id','coordinate_basis','quantities','state_context'},'arguments')
    hardware=_text(args.get('hardware_id'),200,'hardware_id')
    basis=_text(args.get('coordinate_basis'),2000,'coordinate_basis')
    quantities=_object(args.get('quantities'),set(UNITS),'quantities')
    contexts=_object(args.get('state_context'),{'rest_closure','pre_stop_closure','post_stop_closure'},'state_context')
    for name,value in contexts.items():
        _text(value,1000,'state_context.'+name)
    bounds={}
    for name,item in quantities.items():
        item=_object(item,{'min','max','unit','source'}|({'definition'} if name=='allowable_compression' else set()),name)
        if name=='allowable_compression' and item.get('definition')!=ALLOWABLE_DEFINITION:
            raise ValueError('allowable_compression: must identify permitted maximum; OT minimum is not accepted')
        low,high=_number(item.get('min'),name+'.min'),_number(item.get('max'),name+'.max')
        if low>high or item.get('unit')!=UNITS[name]:
            raise ValueError(f'{name}: reversed bounds or incorrect unit')
        if name not in ('gap','rest_closure','pre_stop_closure','post_stop_closure') and low<0:
            raise ValueError(f'{name}: must be nonnegative')
        if name in ('on_compression','design_load') and low<=0:
            raise ValueError(f'{name}: positive lower bound required')
        source=_object(item.get('source'),{'kind','evidence_ref','hardware_scope'},name+'.source')
        if source.get('kind') not in KINDS:
            raise ValueError(f'{name}.source.kind: unknown kind')
        _text(source.get('evidence_ref'),1000,name+'.source.evidence_ref')
        _text(source.get('hardware_scope'),300,name+'.source.hardware_scope')
        bounds[name]=(low,high)
    encoded=json.dumps(args,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    result={'hardware_id':hardware,'coordinate_basis':basis,
        'input_sha256':hashlib.sha256(encoded).hexdigest(), 'inputs':args,
        'evidence_verification':'Caller-declared sources retained, not independently validated or matched to hardware.',
        'assumption_inputs':[name for name,item in quantities.items() if item['source']['kind']=='proposed'],
        'model':'delta=max(0,closure-gap); independent interval extrema; Decimal arithmetic on JSON numeric values',
        'physical_design_complete':False,'fit_claim':'none',
        'not_verified':['full-path return force and friction','contact/lateral motion and kinematics',
            'support deflection at design load','actual threshold bounds and source applicability',
            'assembly, print variability, optical datum, fatigue and hardware operation',
            'opposite button crosstalk, stop/PCB strength, plunger lateral load, adjustment range and retention'],
        'coordinate_contract':'g is the signed reference clearance at common u=0; u_rest is closure after release history. Use one axis/sign/datum; do not double-count the same gap error in u.',
        'motion_order':'Rest/pre-stop/post-stop must be consistent per physical tolerance realization; independent interval endpoint ordering alone does not verify it.'}
    missing=[name for name in UNITS if name not in bounds]+['state_context.'+name for name in ('rest_closure','pre_stop_closure','post_stop_closure') if name not in contexts]
    lo=lambda name: bounds[name][0]
    hi=lambda name: bounds[name][1]
    zero=Decimal(0)
    dependencies={'on_before_stop':['gap','pre_stop_closure','on_compression','on_margin'],
        'off_after_return':['gap','rest_closure','off_compression','release_margin'],
        'compression_after_stop':['gap','post_stop_closure','allowable_compression','safety_margin','design_load']}
    closures={'on_before_stop':'pre_stop_closure','off_after_return':'rest_closure','compression_after_stop':'post_stop_closure'}
    conditions=[]
    for name,needed in dependencies.items():
        absent=[key for key in needed if key not in bounds]
        closure=closures[name]
        if closure not in contexts:
            absent.append('state_context.'+closure)
        if absent:
            conditions.append({'id':name,'status':'not_evaluated','holds_for_supplied_bounds':None,'missing_inputs':absent})
            continue
        if name=='on_before_stop':
            slack=max(zero,lo(closure)-hi('gap'))-hi('on_compression')-hi('on_margin')
        elif name=='off_after_return':
            slack=lo('off_compression')-hi('release_margin')-max(zero,hi(closure)-lo('gap'))
        else:
            slack=lo('allowable_compression')-hi('safety_margin')-max(zero,hi(closure)-lo('gap'))
        conditions.append({'id':name,'status':'holds' if slack>=zero else 'not_satisfied',
            'holds_for_supplied_bounds':slack>=zero,'slack_mm':float(slack),'slack_decimal_mm':str(slack)})
    model_checks=[]
    threshold_state='not_evaluated'
    if all(name in bounds for name in ('off_compression','on_compression','allowable_compression')):
        if hi('off_compression')<lo('on_compression') and hi('on_compression')<=lo('allowable_compression'):
            threshold_state='guaranteed'
        elif lo('off_compression')>=hi('on_compression') or lo('on_compression')>hi('allowable_compression'):
            threshold_state='contradicted'
        else:
            threshold_state='overlap_not_guaranteed'
        model_checks.append({'id':'threshold_order','status':threshold_state})
    if all(name in bounds for name in ('on_compression','on_margin','allowable_compression','safety_margin')):
        required_budget=hi('on_compression')+hi('on_margin')
        safe_budget=lo('allowable_compression')-hi('safety_margin')
        model_checks.append({'id':'monotonic_compression_budget','status':'holds' if required_budget<=safe_budget else 'not_satisfied',
            'required_on_mm':float(required_budget),'safe_available_mm':float(safe_budget),
            'assumption':'Compression does not decrease from actuation to maximum depression; independent extrema are conservative.'})
    if all(name in bounds for name in ('pre_stop_closure','post_stop_closure')):
        model_checks.append({'id':'pre_post_motion_order','status':'contradicted' if hi('post_stop_closure')<lo('pre_stop_closure') else 'not_independently_verified',
            'meaning':'Only rejects fully reversed envelopes under nondecreasing closure assumption; overlap does not prove physical motion order.'})
    model_failed=any(c['status'] in ('contradicted','not_satisfied') for c in model_checks)
    failed=any(c['holds_for_supplied_bounds'] is False for c in conditions) or model_failed
    result.update(status='interval_conditions_not_satisfied' if failed else ('not_evaluated_missing_inputs' if missing else 'interval_conditions_hold'),
        missing_inputs=missing,conditions=conditions,gap_window=None,model_checks=model_checks,threshold_order_status=threshold_state)
    if 'design_load' in quantities:
        result['post_stop_load_context']={'design_load_interval_N':[float(lo('design_load')),float(hi('design_load'))],
            'scope':'Post-stop closure must envelop relative deflection at design_load.max; relationship is caller-declared, not independently verified.'}
    if missing:
        return result
    rest=max(zero,hi('rest_closure')-lo('gap'))
    on=max(zero,lo('pre_stop_closure')-hi('gap'))
    post=max(zero,hi('post_stop_closure')-lo('gap'))
    required=hi('on_compression')+hi('on_margin')
    off_limit=lo('off_compression')-hi('release_margin')
    safe_limit=lo('allowable_compression')-hi('safety_margin')
    lower=max(hi('rest_closure')-off_limit,hi('post_stop_closure')-safe_limit)
    upper=lo('pre_stop_closure')-required
    feasible=off_limit>=zero and safe_limit>=zero and lower<=upper
    threshold_order=threshold_state=='guaranteed'
    result['threshold_order_guaranteed_by_independent_bounds']=threshold_order
    if not threshold_order and not failed:
        result['status']='not_evaluated_threshold_order'
    result.update(
        compression_extrema_mm={'rest_max':float(rest),'on_min':float(on),'post_stop_max':float(post)},
        gap_window={'feasible_for_supplied_bounds':feasible and threshold_order and not model_failed,'algebraic_window_nonempty':feasible,'lower_mm':float(lower),'upper_mm':float(upper),
            'lower_decimal_mm':str(lower),'upper_decimal_mm':str(upper),
            'reason':'Bounds admit a gap interval; supplied gap may still lie outside it' if feasible and threshold_order and not model_failed else 'A model check fails, budgets are negative, window is empty, or threshold order not guaranteed',
            'meaning':'Every actual gap must remain within this window, including tolerances. A nominal center alone is insufficient.'},
        comparison='Exact Decimal inequalities; equality allowed. Required engineering margins must be supplied explicitly.',
        limitations=['Not satisfying a conservative condition does not prove all physical tolerance combinations fail.',
            'Closure values must already include actual kinematics and relative deflection; this tool does not compute them.',
            'OFF after reaching rest does not prove the mechanism returns to rest.',
            'Input/source digest identifies the calculation; it is not CAD or physical acceptance evidence.'])
    return result
