"""Function-grounded retrieval and a bounded morphological combination search.

Natural-language interpretation remains the host model's job. Alternatives are
not silently treated as separate hard requirements. Source interfaces provide
only geometric preconditions, never a mechanism's complete functional proof.
"""
from __future__ import annotations
from typing import Annotated, Literal, Union
from pydantic import Field, model_validator
from .recipe import Strict, Name, Statement
from .interfaces import screen_interfaces
from ..errors import BrainError
from ..req2cad.common import digest

Feature = Literal['has_cylindrical_cavity_surface','has_cylindrical_outer_surface','has_planar_surface']

class FunctionTask(Strict):
    id: Name
    source_excerpt: str = Field(min_length=1,max_length=2000)
    function: str = Field(min_length=2,max_length=300)
    behavior: str = Field(min_length=5,max_length=2000)
    queries: list[str] = Field(min_length=1,max_length=8)
    required_features: list[Feature] = Field(default_factory=list,max_length=3)
    @model_validator(mode='after')
    def query_unique(self):
        words=[' '.join(q.casefold().split()) for q in self.queries]
        if any(not q or len(q)>400 for q in words) or len(words)!=len(set(words)):
            raise ValueError('Provide distinct, nonempty search paraphrases of THIS function.')
        if len(set(self.required_features))!=len(self.required_features):raise ValueError('Duplicate feature predicate.')
        return self

class FunctionBrief(Strict):
    original_request: str = Field(min_length=3,max_length=20000)
    functions: list[FunctionTask] = Field(min_length=1,max_length=12)
    protected_constraints: list[str] = Field(default_factory=list,max_length=50)
    unresolved: list[str] = Field(default_factory=list,max_length=50)
    @model_validator(mode='after')
    def sources(self):
        if len({f.id for f in self.functions}) != len(self.functions):raise ValueError('Duplicate function ids.')
        if any(f.source_excerpt not in self.original_request for f in self.functions):
            raise ValueError('Function source excerpt must occur in original request. A quote proves traceability, not interpretation.')
        return self

class CaseRef(Strict):
    uid: str = Field(pattern=r'^\d{4}/\d{8}$')
    evidence_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    used_face_ids: list[str] = Field(min_length=1,max_length=128)
    adopted_principle: str = Field(min_length=10,max_length=2000)
    adaptations: list[str] = Field(min_length=1,max_length=50)

class FirstPrinciplesBasis(Strict):
    kind: Literal['first_principles']
    principles: list[Statement] = Field(min_length=1,max_length=50)
    assumptions: list[Statement] = Field(min_length=1,max_length=50)
    verification_plan: list[Statement] = Field(min_length=1,max_length=50)
    unknowns: list[Statement] = Field(min_length=1,max_length=50)
    @model_validator(mode='after')
    def meaningful(self):
        if any(len(x.strip())<8 for rows in (self.principles,self.assumptions,self.verification_plan,self.unknowns) for x in rows):
            raise ValueError('Design-basis statements must be meaningful.')
        return self

class ProvidedCadBasis(Strict):
    kind: Literal['provided_cad']
    artifact_id: Name
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    application: str = Field(min_length=12,max_length=2000)
    verification_plan: list[Statement] = Field(min_length=1,max_length=50)
    unknowns: list[Statement] = Field(min_length=1,max_length=50)
    @model_validator(mode='after')
    def meaningful(self):
        if any(len(x.strip())<8 for rows in (self.verification_plan,self.unknowns) for x in rows):
            raise ValueError('Verification and unknown statements must be meaningful.')
        return self

OptionDesignBasis = Annotated[Union[FirstPrinciplesBasis,ProvidedCadBasis],Field(discriminator='kind')]

class Option(Strict):
    id: Name
    name: str = Field(min_length=2,max_length=200)
    covers: list[Name] = Field(min_length=1,max_length=12)
    mechanism_principle: str = Field(min_length=10,max_length=2000)
    references: list[CaseRef] = Field(default_factory=list,max_length=8)
    design_basis: OptionDesignBasis | None = None
    proposed_parts: list[Name] = Field(min_length=1,max_length=16)
    force_path: str = Field(min_length=8,max_length=2000)
    assembly_method: str = Field(min_length=8,max_length=2000)
    risks: list[str] = Field(min_length=1,max_length=50)
    @model_validator(mode='after')
    def unique(self):
        if len(self.covers)!=len(set(self.covers)) or len(self.proposed_parts)!=len(set(self.proposed_parts)):raise ValueError('Duplicate coverage or part name.')
        if len({r.uid for r in self.references})!=len(self.references):raise ValueError('Duplicate reference UID.')
        if not self.references and self.design_basis is None:
            raise ValueError('An option without Req2CAD references needs a first-principles or provided-CAD basis.')
        return self

class Incompatible(Strict):
    option_a: Name
    option_b: Name
    reason: str = Field(min_length=8,max_length=2000)

class Matrix(Strict):
    brief: FunctionBrief
    options: list[Option] = Field(min_length=2,max_length=64)
    incompatibilities: list[Incompatible] = Field(default_factory=list,max_length=256)
    max_search_states: int = Field(default=5000,ge=10,le=100000)
    max_candidates: int = Field(default=6,ge=1,le=12)
    @model_validator(mode='after')
    def ids(self):
        fids={f.id for f in self.brief.functions};oids={o.id for o in self.options}
        if len(oids)!=len(self.options):raise ValueError('Duplicate option ids.')
        if any(set(o.covers)-fids for o in self.options):raise ValueError('Unknown covered function.')
        if any(c.option_a not in oids or c.option_b not in oids or c.option_a==c.option_b for c in self.incompatibilities):raise ValueError('Invalid incompatible pair.')
        return self


def retrieve_tasks(brief, search_one, service, *, mode='semantic',limit_per_function=12,threshold=.7,grouped_response=None):
    """search_one is an actual lexical/dense retriever, never an LLM hit generator."""
    b=FunctionBrief.model_validate(brief);out=[]
    if not 1<=limit_per_function<=30:raise BrainError('STUDIO_LIMIT','limit_per_function must be 1–30.')
    for task in b.functions:
        found={}
        responses = [(query,search_one([query],limit=limit_per_function,threshold=threshold,require_cad=True,mode=mode)) for query in task.queries] if grouped_response is None else [(task.function,grouped_response['groups'][task.id])]
        for query,response in responses:
            for row in response['results']:
                item=found.setdefault(row['uid'],{'uid':row['uid'],'matched_queries':[],'matched_keywords':[],
                                                  'citation':row['citation'],'scores':[],'annotation_origin':row['annotation_origin']})
                item['matched_queries'].extend(m.get('matched_query_variant',query) for m in row['matched'])
                item['matched_keywords'].extend(m['matched_keyword'] for m in row['matched'])
                item['scores'].extend(m['score'] for m in row['matched'])
        ranked=[]
        for item in found.values():
            evidence=service.evidence(item['uid'])
            item['matched_keywords']=list(dict.fromkeys(item['matched_keywords']))
            item['feature_screen']=screen_interfaces(evidence['geometry'],task.required_features)
            item['geometry_ready']=bool(evidence['geometry'])
            item['evidence_digest']=evidence['evidence_digest'] if evidence['geometry'] else None
            item['retrieval_score']=max(item.pop('scores'),default=0.)
            item['interpretation']='Retrieval evidence only. Paraphrases count as ONE requested function.'
            ranked.append(item)
        ranked.sort(key=lambda x:({'pass':0,'unknown':1,'fail':2}[x['feature_screen']['verdict']],-x['retrieval_score'],x['uid']))
        out.append({'function_id':task.id,'function':task.function,'behavior':task.behavior,
                    'required_features':task.required_features,'candidates':ranked[:limit_per_function],
                    'no_match':not bool(ranked),'note':'No result does not prove no suitable structure exists.'})
    return {'brief_digest':digest(b.model_dump()),'mode':mode,'functions':out,
            'original_request':b.original_request,'protected_constraints':b.protected_constraints,
            'search_quality_measured':False,'next':'Materialize representative UIDs, inspect views/ports, then propose morphology options.'}


def synthesize(matrix, service):
    """Enumerate compatible covers. CAD geometry/assembly MUST be checked later."""
    m=Matrix.model_validate(matrix);function_map={f.id:f for f in m.brief.functions}
    accepted={};rejected=[];evidence={}
    for option in m.options:
        refs=[]
        for ref in option.references:
            e=service.evidence(ref.uid)
            if not e['geometry'] or e['evidence_digest']!=ref.evidence_digest:
                raise BrainError('STUDIO_STALE_REFERENCE','Materialize/currently inspect every referenced CAD.',{'uid':ref.uid,'option':option.id})
            actual={'F'+str(n['id']) for n in e['geometry']['topology']['nodes']}
            if set(ref.used_face_ids)-actual:raise BrainError('STUDIO_FACE','A cited face does not exist in the hashed B-rep.',{'uid':ref.uid})
            evidence[ref.uid]=e
            scoped=dict(e)
            geometry=dict(e['geometry'])
            interfaces=dict(geometry.get('interfaces',{}))
            if interfaces:
                ports=[p for p in interfaces.get('ports',[]) if p['face_id'] in ref.used_face_ids]
                interfaces['ports']=ports
                interfaces['capabilities']={
                    'has_cylindrical_cavity_surface':any(p['port_kind']=='inner_cylinder' for p in ports),
                    'has_cylindrical_outer_surface':any(p['port_kind']=='outer_cylinder' for p in ports),
                    'has_planar_surface':any(p['port_kind']=='planar_surface' for p in ports)}
                geometry['interfaces']=interfaces
            scoped['geometry']=geometry;refs.append(scoped)
        failures=[];unknown=[]
        for fid in option.covers:
            # Required surfaces may be spread across the component references.
            for feature in function_map[fid].required_features:
                if not refs:
                    unknown.append({'function':fid,'feature':feature,
                                    'reason':'No Req2CAD face evidence; verify against generated or provided CAD.'})
                    continue
                values=[screen_interfaces(e['geometry'],[feature])['verdict'] for e in refs]
                if 'pass' in values:continue
                (unknown if 'unknown' in values else failures).append({'function':fid,'feature':feature})
        if failures:rejected.append({'option':option.id,'reason':'Measured required surface missing from all references','checks':failures})
        else:accepted[option.id]={'option':option,'unknown_feature_checks':unknown}
    by_function={fid:sorted(oid for oid,v in accepted.items() if fid in v['option'].covers) for fid in function_map}
    insufficient={fid:len(oids) for fid,oids in by_function.items() if len(oids)<2}
    conflicts={frozenset([c.option_a,c.option_b]) for c in m.incompatibilities}
    visited=set();solutions=set();expanded=0;truncated=False
    def recurse(selected):
        nonlocal expanded,truncated
        selected=frozenset(selected)
        if selected in visited:return
        if expanded>=m.max_search_states:truncated=True;return
        visited.add(selected);expanded+=1
        covered=set().union(*(set(accepted[s]['option'].covers) for s in selected)) if selected else set()
        if set(function_map)<=covered:
            solutions.add(selected);return
        missing=set(function_map)-covered
        fid=min(missing,key=lambda f:(len(by_function[f]),f))
        for oid in by_function[fid]:
            if any(frozenset([oid,other]) in conflicts for other in selected):continue
            recurse(selected|{oid})
    recurse(set())
    def key(sol):
        opts=[accepted[s] for s in sol]
        return (sum(len(v['unknown_feature_checks']) for v in opts),
                len(set().union(*(set(v['option'].proposed_parts) for v in opts))),len(sol),tuple(sorted(sol)))
    candidates=[]
    for sol in sorted(solutions,key=key)[:m.max_candidates]:
        opts=[accepted[s]['option'] for s in sorted(sol)]
        coverage={fid:[o.id for o in opts if fid in o.covers] for fid in function_map}
        basis_unknowns=[u for o in opts if o.design_basis for u in o.design_basis.unknowns]
        candidate={'options':[o.model_dump() for o in opts], 'function_coverage':coverage,
                   'part_names':sorted(set().union(*(set(o.proposed_parts) for o in opts))),
                   'protected_constraints':m.brief.protected_constraints,
                   'unresolved':list(dict.fromkeys([*m.brief.unresolved,*basis_unknowns])),
                   'status':'concept_candidate_not_assembly_validated',
                   'source_digests':{r.uid:r.evidence_digest for o in opts for r in o.references}}
        candidate['candidate_digest']=digest(candidate);candidates.append(candidate)
    return {'matrix_digest':digest(m.model_dump()),'candidates':candidates,'rejected_options':rejected,
            'insufficient_diversity':insufficient,'expanded_states':expanded,'search_truncated':truncated,
            'complete_covers_found':len(solutions),'ordering':'Unknown feature count, proposed part-name count, option count, deterministic ID tie break. Not a strength/quality ranking.',
            'requires_review':['function sufficiency','force and reaction path','pairwise interfaces','assembly insertion','manufacturing and physical validation'],
            'grounded_reference_count':len(evidence)}
