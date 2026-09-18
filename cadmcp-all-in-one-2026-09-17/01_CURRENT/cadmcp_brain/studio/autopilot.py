"""Bounded rough-request → real references → concepts → CAD → review loop.

Actual generation is delegated to an explicit Provider. No synthetic provider is
installed as a production fallback. Checkpoint files are audit artifacts; a
failed run never resumes a non-idempotent external call automatically.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import copy
from pathlib import Path
from .runtime import ROLES,Review
from .synthesis import FunctionBrief,Matrix
from .recipe import Recipe,Reference
from ..errors import BrainError
from ..req2cad.common import atomic_json,digest

class Autopilot:
    def __init__(self,tools,provider,root,*,search_mode='semantic',max_reference_builds=8,max_repairs=1,review_workers=1,debate_rounds=2):
        if search_mode not in ('semantic','lexical'):raise BrainError('AUTOPILOT_MODE','Explicit semantic or lexical mode required.')
        if not 1<=max_reference_builds<=32 or not 0<=max_repairs<=3 or not 1<=review_workers<=3 or not 1<=debate_rounds<=3:raise BrainError('AUTOPILOT_BUDGET','Invalid bounded resource settings.')
        self.tools=tools;self.provider=provider;self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.mode=search_mode;self.max_refs=max_reference_builds;self.max_repairs=max_repairs;self.review_workers=review_workers;self.debate_rounds=debate_rounds
        self.state={'phase':'created','search_mode':self.mode,'finished':False,'model_provider':type(provider).__name__}
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
            brief=self.generate(FunctionBrief,
              'Preserve original_request exactly. Decompose the mechanical request into functions and physical behavior. For each, give English search paraphrases; do not add missing numeric requirements. Protect supplied hardware and shell constraints. A source excerpt must be an exact substring. Mark unknowns instead of inventing facts.',
              {'original_request':request,'project_measurements':project['measurements'],'registered_step_artifacts':project['artifacts']},'requirements')
            if brief['original_request']!=request:raise BrainError('AUTOPILOT_REQUEST','Model changed original user text.')
            self.save('retrieve',brief=brief)
            retrieval=self.tools.brain_fs_search_tasks(brief,mode=self.mode,limit_per_function=6)
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
            if not actual:raise BrainError('AUTOPILOT_NO_REFERENCE','No real reference could be materialized. Missing geometry was not invented.',{'failures':errors})
            self.save('mechanism_options',reference_uids=[e['uid'] for e in actual],reference_errors=errors)
            # Do not swamp the context with sampled point clouds or model code.
            references=[{'uid':e['uid'],'evidence_digest':e['evidence_digest'],'function_keywords':e['function_keywords'],
                         'annotation_provenance':e['function_provenance'],'interfaces':e['geometry'].get('interfaces'),
                         'topology':e['geometry']['topology'],'bbox':e['geometry'].get('bbox_mm',e['geometry'].get('bbox_model_units')),
                         'dimensional_status':e['geometry']['dimensional_status'],'exports':e['geometry']['exports']} for e in actual]
            matrix=self.generate(Matrix,
              'Return a morphological matrix using the exact supplied brief, and at least two structurally different options where evidence allows. Reference ONLY supplied UID/digest/face identifiers. Distinguish force paths, return/stop mechanisms and assembly methods. Inspect the provided PNG view files using your available image tool as well as the measured interfaces. Report inability to view instead of claiming visual inspection. Cavity surface absence cannot be called a bearing hole. Do not force poor reference matches; retain risks. Do not invent physical validation.',
              {'brief':brief,'references':references,'registered_hardware':project['artifacts'],'measurements':project['measurements']},'mechanism')
            if matrix['brief']!=brief:raise BrainError('AUTOPILOT_BRIEF','Matrix changed the frozen function brief.')
            combos=self.tools.brain_studio_synthesize(project_id,revision,matrix)
            if not combos['candidates']:raise BrainError('AUTOPILOT_NO_CONCEPT','No feasible declared functional cover survived measured preconditions.',combos)
            # Selection is an explicit bounded engineering decision, not just a
            # part-count score. The selector can decline all candidates.
            selection_schema={'type':'object','additionalProperties':False,'properties':{
                'candidate_index':{'type':'integer','minimum':-1,'maximum':len(combos['candidates'])-1},
                'reason':{'type':'string'},'remaining_risks':{'type':'array','items':{'type':'string'}}},
                'required':['candidate_index','reason','remaining_risks']}
            selection=self.provider.generate('Choose the strongest mechanically justified candidate for the stated request, not the most verbose one. Return -1 if none is supportable. Explain decisive interfaces/risks; do not claim physical proof.',selection_schema,{'brief':brief,'combinations':combos},role='mechanical_selector')
            import jsonschema
            jsonschema.validate(selection,selection_schema)
            if selection['candidate_index']==-1:raise BrainError('AUTOPILOT_DECLINED','No candidate was accepted; evidence and options remain available.',selection)
            chosen=combos['candidates'][selection['candidate_index']]
            self.save('cad_recipe',matrix=matrix,combinations=combos,selection=selection)
            recipe=self.generate(Recipe,
               'Produce an executable typed reference-adaptation recipe in mm for the selected concept. Use only schema-supported geometry operations, actual UID/digest references and registered STEP artifacts. No arbitrary code. Keep original_request exact and all supplied function IDs. Keep protected hardware fixed. Bind each proposed dimension to a clearly marked proposal; do not pretend source model units are calibrated mm. Add explicit static and motion checks. Include physical/manufacturing/assembly unknowns. When unsupported geometry is essential, do not substitute a box.',
               {'request':request,'brief':brief,'selected_concept':chosen,'references':references,'project_artifacts':project['artifacts'],'project_measurements':project['measurements']},'geometric_architect')
            allowed=set(chosen['source_digests'])
            if not {n['uid'] for n in recipe['operations'] if n['op']=='reference'}<=allowed:raise BrainError('AUTOPILOT_REFERENCE','Recipe used a nonselected structure reference.')
            if not {f['id'] for f in brief['functions']}<=set(recipe['functions']):raise BrainError('AUTOPILOT_FUNCTION','Recipe dropped a required function.')
            frozen={key:recipe[key] for key in ('original_request','functions','dimension_checks','clearance_checks','motion_checks','unverified_requirements')}
            for attempt in range(self.max_repairs+1):
                self.save('build',attempt=attempt,recipe=recipe)
                try:build=self.tools.brain_studio_build(project_id,revision,recipe,timeout_seconds=180)
                except BrainError as exc:
                    failure={'build_error':exc.as_dict()};build=None
                else:
                    self.save('review',build=build)
                    review_receipts=[];prior_reports=[]
                    for review_round in range(self.debate_rounds):
                        def review_role(role):
                            packet=self.tools.brain_studio_review_packet(project_id,revision,build['subject_digest'],role)
                            packet['discussion_round']=review_round+1
                            if prior_reports:
                                packet['peer_findings']=copy.deepcopy(prior_reports)
                                packet['instructions']+=' Challenge or corroborate specific peer findings against the immutable CAD/measurements. Find missed counterexamples. Do not appeal to votes or authority; do not claim any unperformed test. A rebuttal alone never clears an earlier blocker.'
                            review=self.generate(Review,packet['instructions'],packet,role)
                            if review['role']!=role or review['discussion_round']!=review_round+1:raise BrainError('AUTOPILOT_ROLE','Reviewer returned another role.')
                            return review
                        with ThreadPoolExecutor(max_workers=self.review_workers) as pool:
                            review_reports=list(pool.map(review_role,ROLES))
                        review_receipts.extend(self.tools.brain_studio_submit_review(project_id,revision,build['subject_digest'],r) for r in review_reports)
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
                if not {n['uid'] for n in recipe['operations'] if n['op']=='reference'}<=allowed:raise BrainError('AUTOPILOT_REFERENCE','Repair introduced a nonselected reference.')
        except Exception as exc:
            self.save('stopped_with_evidence',finished=True,error=exc.as_dict() if isinstance(exc,BrainError) else {'type':type(exc).__name__,'message':str(exc)},overall_verdict='not_accepted')
            raise
