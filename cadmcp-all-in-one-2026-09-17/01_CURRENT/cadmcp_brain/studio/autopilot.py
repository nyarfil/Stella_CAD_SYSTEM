"""Bounded rough-request → real references → concepts → CAD → review loop.

Actual generation is delegated to an explicit Provider. No synthetic provider is
installed as a production fallback. Checkpoint files are audit artifacts; a
failed run never resumes a non-idempotent external call automatically.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import copy
from pathlib import Path
from pydantic import ValidationError
from .runtime import ROLES,Review
from .synthesis import FunctionBrief,Matrix
from .recipe import Recipe,Reference,Dimension,Clearance,Motion
from ..errors import BrainError
from ..req2cad.common import atomic_json,digest
from .planning import capabilities,recovery_for

_CHECK_MODELS={'dimension_checks':Dimension,'clearance_checks':Clearance,'motion_checks':Motion}
_CHECK_PART_FIELDS={'dimension_checks':('part',),'clearance_checks':('part_a','part_b'),
                    'motion_checks':('moving_part','obstacles')}


def _output_part_map(recipe):
    outputs=recipe.get('outputs')
    if not isinstance(outputs,list):
        raise BrainError('AUTOPILOT_WEAKENED_CHECK','Schema correction cannot resolve check targets without outputs.')
    node_to_part={};part_to_node={}
    for output in outputs:
        if not isinstance(output,dict) or not isinstance(output.get('node'),str) or not isinstance(output.get('part_id'),str):
            raise BrainError('AUTOPILOT_WEAKENED_CHECK','Schema correction cannot resolve an invalid output target.')
        node,part=output['node'],output['part_id']
        if (node in node_to_part and node_to_part[node]!=part) or (part in part_to_node and part_to_node[part]!=node):
            raise BrainError('AUTOPILOT_WEAKENED_CHECK','Schema correction found an ambiguous output target.')
        node_to_part[node]=part;part_to_node[part]=node
    return node_to_part


def _resolve_check_part(value,node_to_part):
    if not isinstance(value,str):
        raise BrainError('AUTOPILOT_WEAKENED_CHECK','Schema correction changed a check target to a non-string.')
    if value in node_to_part and value in node_to_part.values() and node_to_part[value]!=value:
        raise BrainError('AUTOPILOT_WEAKENED_CHECK','Schema correction target is ambiguous between node and part identities.')
    if value in node_to_part:return node_to_part[value]
    if value in node_to_part.values():return value
    raise BrainError('AUTOPILOT_WEAKENED_CHECK','Schema correction introduced an unknown check target.')


def _canonical_checks(recipe):
    node_to_part=_output_part_map(recipe);result={}
    for name,model in _CHECK_MODELS.items():
        rows=recipe.get(name,[])
        if not isinstance(rows,list):
            raise BrainError('AUTOPILOT_WEAKENED_CHECK','Schema correction changed a check collection.')
        canonical=[]
        for row in rows:
            if not isinstance(row,dict):
                raise BrainError('AUTOPILOT_WEAKENED_CHECK','Schema correction changed a check entry.')
            row=copy.deepcopy(row)
            for field in _CHECK_PART_FIELDS[name]:
                if field not in row:continue
                if field=='obstacles':row[field]=[_resolve_check_part(value,node_to_part) for value in row[field]]
                else:row[field]=_resolve_check_part(row[field],node_to_part)
            try:canonical.append(model.model_validate(row).model_dump())
            except ValidationError as exc:
                raise BrainError('AUTOPILOT_WEAKENED_CHECK','Schema correction changed a check contract.',{'validation_error':str(exc)[:1000]}) from exc
        ids=[row['id'] for row in canonical]
        if len(ids)!=len(set(ids)):
            raise BrainError('AUTOPILOT_WEAKENED_CHECK','Schema correction changed check identity.')
        result[name]={row['id']:row for row in canonical}
    return result


def _guard_schema_check_correction(initial_raw,corrected):
    # An omitted/empty initial collection has no frozen check contract; the
    # correction may add appropriate checks instead of freezing their absence.
    if not any(initial_raw.get(name) for name in _CHECK_MODELS):return
    if _output_part_map(initial_raw)!=_output_part_map(corrected):
        raise BrainError('AUTOPILOT_WEAKENED_CHECK','Schema correction changed output identity while repairing a check target.')
    initial=_canonical_checks(initial_raw);updated=_canonical_checks(corrected)
    if initial!=updated:
        raise BrainError('AUTOPILOT_WEAKENED_CHECK','Schema correction changed a pre-existing inspection check.')

class Autopilot:
    def __init__(self,tools,provider,root,*,search_mode='semantic',max_reference_builds=8,max_repairs=1,review_workers=1,debate_rounds=2,design_route='auto',max_replans=1):
        if search_mode not in ('semantic','lexical'):raise BrainError('AUTOPILOT_MODE','Explicit semantic or lexical mode required.')
        if not 1<=max_reference_builds<=32 or not 0<=max_repairs<=3 or not 1<=review_workers<=3 or not 1<=debate_rounds<=3:raise BrainError('AUTOPILOT_BUDGET','Invalid bounded resource settings.')
        if design_route not in ('auto','reference_required','original') or not 0<=max_replans<=2:raise BrainError('AUTOPILOT_ROUTE','Invalid explicit route/replanning budget.')
        self.tools=tools;self.provider=provider;self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.mode=search_mode;self.max_refs=max_reference_builds;self.max_repairs=max_repairs;self.review_workers=review_workers;self.debate_rounds=debate_rounds
        self.design_route=design_route;self.max_replans=max_replans
        self.state={'phase':'created','search_mode':self.mode,'design_route':design_route,'finished':False,'model_provider':type(provider).__name__}
    def save(self,phase,**updates):
        self.state.update(phase=phase,**updates);atomic_json(self.root/'run-state.json',self.state)
    def generate(self,model,task,context,role):
        result=self.provider.generate(task,model.model_json_schema(),context,role=role)
        return model.model_validate(result).model_dump()
    def run(self,project_id):
        project=self.tools.brain_get(project_id)['project'];revision=project['revision']
        request='\n\n'.join(s['text'] for s in project['sources'])
        self.save('interpret',project_id=project_id,revision=revision)
        try:
            lexical_keywords=[]
            if self.mode=='lexical' and self.design_route!='original':
                available=[text for _,text in self.tools._fs().catalog.keywords()]
                if len(available)<=512:lexical_keywords=available
            query_guidance=(' For explicit lexical mode, include concise 2-4 word engineering keyword phrases. When lexical_keyword_vocabulary is supplied, include relevant exact phrases from it; those labels are retrieval hints, not validated capabilities.' if self.mode=='lexical' else '')
            brief=self.generate(FunctionBrief,
              'Preserve original_request exactly. Decompose the mechanical request into functions and physical behavior. For each, give English search paraphrases; do not add missing numeric requirements. Protect supplied hardware and shell constraints. A source excerpt must be an exact substring. Mark unknowns instead of inventing facts.'+query_guidance,
              {'original_request':request,'project_measurements':project['measurements'],'registered_step_artifacts':project['artifacts'],
               'lexical_keyword_vocabulary':lexical_keywords},'requirements')
            if brief['original_request']!=request:raise BrainError('AUTOPILOT_REQUEST','Model changed original user text.')
            self.save('retrieve',brief=brief)
            retrieval={'functions':[],'status':'not_requested','mode':self.mode}
            if self.design_route!='original':
                try:
                    retrieval=self.tools.brain_fs_search_tasks(brief,mode=self.mode,limit_per_function=6)
                    retrieval['status']='searched'
                except BrainError as exc:
                    if self.design_route=='reference_required' or exc.code not in ('FS_ENCODER_NOT_CONFIGURED','FS_SEMANTIC_NOT_READY','FS_EMPTY'):
                        raise
                    retrieval={'functions':[],'status':'unavailable','error':exc.as_dict(),'mode':self.mode}
            self.save('materialize',retrieval=retrieval)
            # Round-robin candidates across functions avoids spending the whole
            # geometry budget on the first function.
            groups=retrieval['functions'];uids=[]
            for rank in range(6):
                for group in groups:
                    candidates=group['candidates']
                    if rank<len(candidates) and candidates[rank]['uid'] not in uids:uids.append(candidates[rank]['uid'])
            actual=[];errors=[]
            for uid in uids[:self.max_refs]:
                try:actual.append(self.tools.brain_fs_materialize(uid))
                except BrainError as exc:errors.append({'uid':uid,'error':exc.as_dict()})
            if not actual and self.design_route=='reference_required':raise BrainError('AUTOPILOT_NO_REFERENCE','No real reference could be materialized. Missing geometry was not invented.',{'failures':errors})
            self.save('mechanism_options',reference_uids=[e['uid'] for e in actual],reference_errors=errors,
                      reference_basis='measured_references_available' if actual else 'no_measured_catalog_reference',capabilities=capabilities())
            # Do not swamp the context with sampled point clouds or model code.
            references=[{'uid':e['uid'],'evidence_digest':e['evidence_digest'],'function_keywords':e['function_keywords'],
                         'annotation_provenance':e['function_provenance'],'interfaces':e['geometry'].get('interfaces'),
                         'topology':e['geometry']['topology'],'bbox':e['geometry'].get('bbox_mm',e['geometry'].get('bbox_model_units')),
                         'dimensional_status':e['geometry']['dimensional_status'],'exports':e['geometry']['exports']} for e in actual]
            matrix_schema=copy.deepcopy(Matrix.model_json_schema())
            del matrix_schema['properties']['brief'];matrix_schema['required'].remove('brief')
            matrix_context={'frozen_brief':brief,'references':references,'registered_hardware':project['artifacts'],
                            'measurements':project['measurements'],'retrieval':retrieval,'capabilities':capabilities()}
            matrix_task='Return only morphological options and incompatibilities for the frozen brief; server attaches it. Propose distinct mechanisms. Every incompatibility must name two distinct IDs actually defined in options; rejected ideas not offered as options belong in risks, not dangling incompatibility pairs. Use references as inspiration, not mandatory source shapes. Use only supplied UID/digest/face IDs. If no appropriate reference exists, use explicit first_principles or provided_cad design_basis with verification_plan and unknowns. Never invent retrieved CAD. Inspect supplied images. Respect measured surface facts but design new geometry when needed. Preserve requirements and protected conditions; distinguish owner requirements from optional proposals.'
            for replan in range(self.max_replans+1):
                matrix_body=self.provider.generate(matrix_task,matrix_schema,matrix_context,role='mechanism')
                try:
                    matrix=Matrix.model_validate({**matrix_body,'brief':brief}).model_dump()
                except ValidationError as exc:
                    self.save('replan',replan=replan,rejected_matrix=matrix_body,
                              matrix_validation_error=str(exc)[:4000])
                    if replan==self.max_replans:raise
                    matrix_context['previous_invalid_matrix']=copy.deepcopy(matrix_body)
                    matrix_context['validation_error']=str(exc)[:4000]
                    matrix_context['correction_instruction']='Re-plan the invalid matrix within the same frozen brief and supplied evidence. Correct schema/ID relationships explicitly; do not weaken requirements or pretend rejected alternatives are defined options.'
                    continue
                combos=self.tools.brain_studio_synthesize(project_id,revision,matrix)
                if combos['candidates']:break
                self.save('replan',replan=replan,rejected_concepts=combos)
                matrix_context['previous_rejected_matrix']=matrix
                matrix_context['rejection_evidence']=combos
            if not combos['candidates']:raise BrainError('AUTOPILOT_NO_CONCEPT','Concept replanning budget exhausted; evidence retained.',combos)
            # Selection is an explicit bounded engineering decision, not just a
            # part-count score. The selector can decline all candidates.
            selection_schema={'type':'object','additionalProperties':False,'properties':{
                'candidate_index':{'type':'integer','minimum':-1,'maximum':len(combos['candidates'])-1},
                'reason':{'type':'string'},'remaining_risks':{'type':'array','items':{'type':'string'}}},
                'required':['candidate_index','reason','remaining_risks']}
            selection=self.provider.generate('Choose the strongest mechanically justified candidate for the stated request, not the most verbose one. Inspect the supplied reference images and measured interfaces. Return -1 if none is supportable even as a bounded geometry prototype. Explain decisive interfaces/risks; do not claim physical proof.',selection_schema,
                                             {'brief':brief,'combinations':combos,'references':references,'retrieval':retrieval},role='mechanical_selector')
            import jsonschema
            jsonschema.validate(selection,selection_schema)
            if selection['candidate_index']==-1:raise BrainError('AUTOPILOT_DECLINED','No candidate was accepted; evidence and options remain available.',selection)
            chosen=combos['candidates'][selection['candidate_index']]
            self.save('cad_recipe',matrix=matrix,combinations=combos,selection=selection)
            recipe_context={'request':request,'brief':brief,'selected_concept':chosen,'references':references,'capabilities':capabilities(),
                            'project_artifacts':project['artifacts'],'project_measurements':project['measurements']}
            recipe_task='Produce an executable typed recipe in mm for the selected concept. Design geometry for the user request. References may be principle_reference only: record reference_uses without inserting their shape into operations. If no shape is reused, supply explicit design_basis, verification_plan and unknowns. Use only supported operations. No arbitrary code. Keep original_request exact, all supplied function IDs, and protected_constraints exactly. Keep protected hardware fixed. design_parameters and parameter_basis MUST have the same keys. Give every proposed dimension its basis. Do not pretend source units are mm. Include checks appropriate to the required function; every dimension, clearance, and motion check must name an outputs[].part_id exactly, never an operation/node id when those differ. A static part needs no invented motion requirement. Include physical/manufacturing/assembly unknowns. If an unsupported operation is essential, do not disguise a box as that operation.'
            raw_recipe=self.provider.generate(recipe_task,Recipe.model_json_schema(),recipe_context,role='geometric_architect')
            initial_raw_recipe=copy.deepcopy(raw_recipe);corrected_from_schema=False
            try:recipe=Recipe.model_validate(raw_recipe).model_dump()
            except ValidationError as exc:
                corrected_from_schema=True
                raw_recipe=self.provider.generate(
                    'Correct the previous Recipe exactly once so it satisfies the same schema and validation error. Inspection targets are outputs[].part_id, not operation/node IDs. If an initial unverified Recipe names an operation/node ID in a dimension, clearance, or motion check, resolve that reference to the same intended outputs[].part_id only. Preserve the frozen request, functions, protected_constraints, check values, check kinds, thresholds, references and unverified requirements; do not change numbers, requirements, or add/remove checks. Existing inspection checks from a successful build baseline are frozen and must never be loosened. In particular design_parameters and parameter_basis must have identical key sets.',
                    Recipe.model_json_schema(),{'previous_recipe':raw_recipe,'validation_error':str(exc)[:2000],'frozen_context':recipe_context},
                    role='geometric_architect_correction')
                recipe=Recipe.model_validate(raw_recipe).model_dump()
            if corrected_from_schema:_guard_schema_check_correction(initial_raw_recipe,recipe)
            allowed=set(chosen['source_digests'])
            if recipe['protected_constraints']!=brief['protected_constraints']:raise BrainError('AUTOPILOT_PROTECTED','Recipe changed or dropped protected constraints.')
            if not ({n['uid'] for n in recipe['operations'] if n['op']=='reference'} | {u['uid'] for u in recipe['reference_uses']})<=allowed:raise BrainError('AUTOPILOT_REFERENCE','Recipe used a nonselected structure reference.')
            if not {f['id'] for f in brief['functions']}<=set(recipe['functions']):raise BrainError('AUTOPILOT_FUNCTION','Recipe dropped a required function.')
            frozen={key:recipe[key] for key in ('original_request','functions','protected_constraints','dimension_checks','clearance_checks','motion_checks','unverified_requirements')}
            baseline=None
            for attempt in range(self.max_repairs+1):
                self.save('build',attempt=attempt,recipe=recipe)
                try:build=self.tools.brain_studio_build(project_id,revision,recipe,timeout_seconds=180,baseline_subject_digest=baseline)
                except BrainError as exc:
                    failure={'build_error':exc.as_dict()};build=None
                else:
                    baseline=build['subject_digest']
                    self.save('review',build=build)
                    review_receipts=[];prior_reports=[]
                    for review_round in range(self.debate_rounds):
                        challenged_review_ids=[item['review_id'] for item in review_receipts if item.get('discussion_round')==1]
                        def review_role(role):
                            packet=self.tools.brain_studio_review_packet(project_id,revision,build['subject_digest'],role)
                            packet['discussion_round']=review_round+1
                            if prior_reports:
                                packet['peer_findings']=copy.deepcopy(prior_reports)
                                packet['required_challenged_review_ids']=challenged_review_ids
                                packet['instructions']+=' Challenge or corroborate specific peer findings against the immutable CAD/measurements. Return every required_challenged_review_id in challenged_review_ids. Find missed counterexamples. Do not appeal to votes or authority; do not claim any unperformed test. A rebuttal alone never clears an earlier blocker.'
                            review=self.generate(Review,packet['instructions'],packet,role)
                            if review['role']!=role or review['discussion_round']!=review_round+1:raise BrainError('AUTOPILOT_ROLE','Reviewer returned another role.')
                            if review_round and set(review['challenged_review_ids'])!=set(challenged_review_ids):raise BrainError('AUTOPILOT_DEBATE','Peer review did not cite the complete saved first-round review set.')
                            return review
                        with ThreadPoolExecutor(max_workers=self.review_workers) as pool:
                            review_reports=list(pool.map(review_role,ROLES))
                        submitted=[self.tools.brain_studio_submit_review(project_id,revision,build['subject_digest'],r) for r in review_reports]
                        for item in submitted:item['discussion_round']=review_round+1
                        review_receipts.extend(submitted)
                        prior_reports.extend(review_reports)
                        self.save('review',discussion_round=review_round+1,review_receipts=review_receipts)
                    status=self.tools.brain_studio_review_status(project_id,revision,build['subject_digest'])
                    if build['geometry_checks_verdict']=='pass' and status['discussion_ready_for_owner']:
                        self.save('prototype_ready_for_owner_review',finished=True,build=build,review_status=status,review_receipts=review_receipts,
                                  overall_verdict='unknown',physical_performance_certified=False)
                        return self.state
                    failure={'build':build,'review_status':status}
                if attempt==self.max_repairs:
                    self.save('needs_revision',finished=True,last_failure=failure,overall_verdict='not_accepted')
                    return self.state
                recipe=self.generate(Recipe,
                    'Revise the geometry in response to measured failures and blocking review findings. Do NOT change frozen acceptance checks, source request, required functions or physical unknowns. Do not loosen tolerances to pass. Cite the structural change in operation reasons.',
                    {'previous_recipe':recipe,'failure':failure,'frozen_contract':frozen,'references':references},'repair')
                if any(recipe[key]!=value for key,value in frozen.items()):raise BrainError('AUTOPILOT_WEAKENED_CHECK','Repair attempted to change a frozen acceptance condition.')
                if not ({n['uid'] for n in recipe['operations'] if n['op']=='reference'} | {u['uid'] for u in recipe['reference_uses']})<=allowed:raise BrainError('AUTOPILOT_REFERENCE','Repair introduced a nonselected reference.')
        except Exception as exc:
            self.save('stopped_with_evidence',finished=True,error=exc.as_dict() if isinstance(exc,BrainError) else {'type':type(exc).__name__,'message':str(exc)},recovery=recovery_for(exc),overall_verdict='not_accepted')
            raise
