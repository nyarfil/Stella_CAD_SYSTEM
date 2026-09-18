"""Deterministic gates for provenance, coverage, graph integrity and declarations.

These gates cannot prove that a paraphrase faithfully captures human intent.
Keep that semantic review in the host; never call an LLM confidence a probability.
"""
from __future__ import annotations
import math
import re
from .models import Brief, Concept, Plan, Project
from .patterns import Catalog
from .errors import BrainError
from .util import check_unique


def require(condition, code, message, **details):
    if not condition:
        raise BrainError(code, message, details)


def refs_valid(refs, sources):
    lookup = {s.id: s.text for s in sources}
    for ref in refs:
        require(ref.source_id in lookup, "BAD_SOURCE", "Referenced source is missing.", source_id=ref.source_id)
        require(ref.quote in lookup[ref.source_id], "BAD_QUOTE", "Source quotes must be exact, not paraphrased.", source_id=ref.source_id, quote=ref.quote)


def unknowns_valid(unknowns, sources):
    check_unique(unknowns, "unknowns")
    for u in unknowns:
        refs_valid(u.source_refs, sources)
        if u.resolution is not None:
            require(bool(u.resolution.strip()) and bool(u.source_refs), "UNSOURCED_RESOLUTION", "Resolving an unknown requires a nonempty answer and its source.", unknown_id=u.id)


def pending(unknowns, stage):
    order = {"intent": 0, "concepts": 1, "plan": 2, "release": 3}
    return [u.model_dump() for u in unknowns if u.resolution is None and order[u.blocks] <= order[stage]]


def validate_brief(brief: Brief, p: Project):
    check_unique(brief.requirements, "requirements")
    reqs = {r.id: r for r in brief.requirements}
    allrefs = []
    for r in brief.requirements:
        refs_valid(r.source_refs, p.sources)
        allrefs.extend(r.source_refs)
        require(not (r.origin == "inferred" and r.priority != "preference"), "INFERENCE_AS_REQUIREMENT", "An inferred need cannot silently become a mandatory requirement. Preserve it as a preference or unresolved question.", requirement_id=r.id)
    for d in brief.dispositions:
        refs_valid([d], p.sources)
        allrefs.append(d)
    # Lossless coverage: every alphanumeric source character is either linked or explicitly disposed.
    # This detects dropped spans, not semantic fidelity of the interpretation.
    for src in p.sources:
        covered = [False] * len(src.text)
        for ref in allrefs:
            if ref.source_id != src.id: continue
            start = 0
            while (at := src.text.find(ref.quote, start)) >= 0:
                covered[at:at+len(ref.quote)] = [True]*len(ref.quote)
                start = at+len(ref.quote)
        gaps = [i for i, ch in enumerate(src.text) if ch.isalnum() and not covered[i]]
        require(not gaps, "SOURCE_COVERAGE", "Some source text has no requirement or explicit disposition.", source_id=src.id, uncovered_example=src.text[gaps[0]:gaps[0]+100] if gaps else "")
    unit_by_property = {}
    for constraint in brief.constraints:
        prev=unit_by_property.setdefault(constraint.property,constraint.unit)
        require(prev==constraint.unit,"UNIT_CONFLICT","A property uses inconsistent units; normalize its contract first.",property=constraint.property)
    bounds = {}
    equalities = {}
    for c in brief.constraints:
        require(c.requirement_id in reqs, "ORPHAN_CONSTRAINT", "Constraint references an unknown requirement.")
        require(reqs[c.requirement_id].origin == "explicit", "INFERENCE_AS_CONSTRAINT", "Only explicit requirements can create binding constraints.")
        require(reqs[c.requirement_id].priority != "preference", "PREFERENCE_AS_CONSTRAINT", "A preference must not silently become a binding constraint.")
        key = (c.property, c.unit)
        if c.op == "eq":
            if key in equalities:
                require((type(equalities[key]) is type(c.value) or (type(equalities[key]) in (int,float) and type(c.value) in (int,float))) and equalities[key] == c.value, "CONTRADICTORY_CONSTRAINTS", "Two equalities contradict one another.", property=c.property)
            equalities[key] = c.value
        if c.op in ("le", "ge"):
            lo, hi = bounds.get(key, (-math.inf, math.inf))
            bounds[key] = (max(lo, c.value) if c.op == "ge" else lo, min(hi, c.value) if c.op == "le" else hi)
    for key, (lo, hi) in bounds.items():
        require(lo <= hi, "CONTRADICTORY_CONSTRAINTS", "A lower limit exceeds its upper limit.", property=key[0])
        eq = equalities.get(key)
        if isinstance(eq, (int, float)) and not isinstance(eq, bool):
            require(lo <= eq <= hi, "CONTRADICTORY_CONSTRAINTS", "Equality violates an interval constraint.", property=key[0])
    for c in brief.constraints:
        if c.op == "ne" and (c.property,c.unit) in equalities:
            require(equalities[c.property,c.unit] != c.value, "CONTRADICTORY_CONSTRAINTS", "Equality contradicts an exclusion.")
    unknowns_valid(brief.unknowns, p.sources)
    require(not pending(brief.unknowns, "intent"), "BLOCKING_UNKNOWNS", "Resolve intent-level uncertainty before committing the brief.", unknowns=pending(brief.unknowns,"intent"))


def concept_integrity(c: Concept, brief: Brief, catalog: Catalog, sources):
    for label, items in (("functions",c.functions),("components",c.components),("mechanisms",c.mechanisms),("interfaces",c.interfaces)):
        check_unique(items,label)
    global_ids = [x.id for group in (brief.requirements,c.functions,c.components,c.mechanisms,c.interfaces,c.case_references) for x in group]
    require(len(global_ids)==len(set(global_ids)),"DUPLICATE_ID","IDs must also be unique across graph node kinds.")
    reqids = {r.id for r in brief.requirements}
    funcs = {f.id for f in c.functions}
    comps = {x.id for x in c.components}
    for f in c.functions:
        require(set(f.requirement_ids) <= reqids, "UNKNOWN_REQUIREMENT", "Function refers to an unknown requirement.", function_id=f.id)
    for x in c.components:
        require(set(x.function_ids) <= funcs, "UNKNOWN_FUNCTION", "Component refers to an unknown function.", component_id=x.id)
    for m in c.mechanisms:
        catalog.get(m.pattern_id)
        refids={r.id for r in c.case_references}
        require(set(m.reference_ids)<=refids,"UNKNOWN_CASE_REFERENCE","Mechanism refers to an unknown CAD evidence reference.")
        if m.pattern_id=="reference_structure":
            require(bool(m.reference_ids),"CAD_REFERENCE_REQUIRED","A reference-derived structure needs actual materialized CAD evidence.")
        require(set(m.function_ids) <= funcs, "UNKNOWN_FUNCTION", "Mechanism refers to an unknown function.")
        require(set(m.component_ids) <= comps, "UNKNOWN_COMPONENT", "Mechanism refers to an unknown component.")
    for i in c.interfaces:
        require(i.component_a in comps and i.component_b in comps and i.component_a != i.component_b, "BAD_INTERFACE", "An interface must connect two existing, distinct components.", interface_id=i.id)
    unknowns_valid(c.unknowns,sources)


def evaluate_concept(c: Concept, brief: Brief, catalog: Catalog):
    errors, warnings = [], []
    def err(code,msg): errors.append({"code":code,"message":msg})
    coverage = {x for f in c.functions for x in f.requirement_ids}
    for r in brief.requirements:
        if r.id not in coverage:
            (errors if r.priority != "preference" else warnings).append({"code":"REQUIREMENT_COVERAGE","message":f"{r.id}: no function realizes this requirement"})
    realized = {f for m in c.mechanisms for f in m.function_ids}
    for f in c.functions:
        if f.id not in realized: err("UNREALIZED_FUNCTION",f"{f.id}: no mechanism assigned")
    for x in c.components:
        if not any(x.id in m.component_ids for m in c.mechanisms):
            err("ORPHAN_COMPONENT",f"{x.id}: component has no assigned mechanism")
    if len(c.components)>1:
        graph = {x.id:set() for x in c.components}
        for i in c.interfaces:
            graph[i.component_a].add(i.component_b); graph[i.component_b].add(i.component_a)
        seen, todo=set(),[c.components[0].id]
        while todo:
            n=todo.pop()
            if n in seen: continue
            seen.add(n); todo.extend(graph[n]-seen)
        if len(seen)!=len(graph): err("DISCONNECTED_ASSEMBLY","Declared interfaces leave components disconnected")
    for m in c.mechanisms:
        pat = catalog.get(m.pattern_id)
        assigned=[f for f in c.functions if f.id in m.function_ids]
        for f in assigned:
            if "*" not in pat["functions"] and f.function_key not in pat["functions"]: err("PATTERN_FUNCTION_MISMATCH",f"{m.id}: pattern does not declare support for {f.function_key}")
        if any(f.function_key=="actuate_switch" for f in assigned) and not pat["is_switch_actuator"] and m.pattern_id!="reference_structure":
            err("ACTUATOR_PATTERN_REQUIRED",f"{m.id}: a switch-actuation function needs an explicit actuator pattern")
        if m.pattern_id=="reference_structure":
            warnings.append({"code":"REFERENCE_ADAPTATION_UNVERIFIED","message":"Case labels and B-rep topology do not prove mechanical function or printable dimensions."})
        if pat["is_switch_actuator"] or (m.pattern_id=="reference_structure" and any(f.function_key=="actuate_switch" for f in assigned)):
            if m.pattern_id=="reference_structure" and m.motion_relation is None: err("MOTION_RELATION_REQUIRED",f"{m.id}: declare direct/lever/other motion transmission")
            if m.input_direction is None or m.output_direction is None: err("UNKNOWN_ACTUATION_DIRECTION",f"{m.id}: both input and switch-actuation directions must be known")
            elif pat["axis_rule"]=="same_direction" or m.motion_relation=="direct":
                dot=sum(a*b for a,b in zip(m.input_direction,m.output_direction))
                if dot < 1-1e-6: err("AXIS_MISMATCH",f"{m.id}: direct actuation cannot silently rotate or reverse the force direction")
            if m.return_method in ("none","not_applicable"): err("MISSING_RETURN",f"{m.id}: no return mechanism")
            if not m.hard_stop: err("MISSING_STOP",f"{m.id}: switch overtravel protection is unspecified")
            elif not any(i.kind=="stop" and i.component_a in m.component_ids and i.component_b in m.component_ids for i in c.interfaces):
                err("STOP_INTERFACE_MISSING",f"{m.id}: hard_stop=true without a declared physical stop interface")
            if m.pattern_id=="side_direct_guided" and not any(i.kind=="guide" and i.component_a in m.component_ids and i.component_b in m.component_ids for i in c.interfaces):
                err("GUIDE_INTERFACE_MISSING",f"{m.id}: a guided direct actuator needs a guide interface")
            if m.return_method=="switch_internal": warnings.append({"code":"RETURN_FORCE_UNPROVEN","message":"Check actual switch return force against friction, gravity and tolerances; internal return is not automatically sufficient."})
            if m.return_method=="printed_flexure": warnings.append({"code":"FATIGUE_UNPROVEN","message":"Printed flexure life, strain and creep need material/orientation-specific evidence."})
    properties = dict(c.properties)
    # These properties are computed from the design, not trusted from a model.
    properties["printed_parts_count"] = sum(x.role=="printed" for x in c.components)
    properties["uses_metal_spring"] = any(x.return_method=="metal_spring" for x in c.mechanisms)
    for key in ("printed_parts_count","uses_metal_spring"):
        if key in c.properties and (type(c.properties[key]) is not type(properties[key]) or c.properties[key]!=properties[key]):
            err("PROPERTY_SPOOF",f"{key} contradicts the declared components/mechanisms")
    satisfied = 0
    for con in brief.constraints:
        if con.property not in properties:
            err("UNKNOWN_CONSTRAINT_PROPERTY",f"{con.requirement_id}: property {con.property} is not declared")
            continue
        actual=properties[con.property]
        if con.op in ("le","ge"):
            ok=isinstance(actual,(int,float)) and not isinstance(actual,bool) and (actual<=con.value if con.op=="le" else actual>=con.value)
        else:
            same_type = type(actual) is type(con.value) or (type(actual) in (int,float) and type(con.value) in (int,float))
            equal = same_type and actual==con.value
            ok=equal if con.op=="eq" else not equal
        if not ok: err("CONSTRAINT_VIOLATION",f"{con.requirement_id}: {con.property} {con.op} {con.value!r} is not satisfied by {actual!r}")
        else: satisfied+=1
    for u in pending(brief.unknowns+c.unknowns,"concepts"):
        err("BLOCKING_UNKNOWNS",u["question"])
    return {"concept_id":c.id,"eligible_for_planning":not errors,"errors":errors,"warnings":warnings,"declared_properties":properties,"constraint_pass_count":satisfied,"quality_score":None,"note":"No invented engineering quality score. Eligibility checks declarations; it does not certify the mechanism."}


def topological_order(steps):
    check_unique(steps,"steps")
    deps={s.id:set(s.depends_on) for s in steps}
    require(all(d<=deps.keys() for d in deps.values()),"UNKNOWN_DEPENDENCY","A plan dependency does not exist.")
    order=[]
    while deps:
        ready=sorted(k for k,v in deps.items() if not v)
        require(bool(ready),"DEPENDENCY_CYCLE","The construction plan contains a dependency cycle.")
        order.extend(ready)
        for k in ready: del deps[k]
        for v in deps.values(): v.difference_update(ready)
    return order


def validate_plan(plan: Plan,p: Project,catalog: Catalog):
    require(p.brief is not None and p.selection is not None,"WRONG_STAGE","Select a valid concept first.")
    c=next(x for x in p.concepts if x.id==p.selection)
    require(plan.concept_id==c.id,"WRONG_CONCEPT","Plan must refer to the selected concept.")
    report=evaluate_concept(c,p.brief,catalog)
    require(report["eligible_for_planning"],"CONCEPT_INVALID","Selected concept no longer passes.",report=report)
    global_ids=[x.id for group in (p.brief.requirements,c.functions,c.components,c.mechanisms,c.interfaces,c.case_references,plan.steps,plan.checks,plan.dimensions) for x in group]
    require(len(global_ids)==len(set(global_ids)),"DUPLICATE_ID","Plan IDs collide with each other or with the design graph.")
    reqs={r.id:r for r in p.brief.requirements}
    comps={x.id for x in c.components}
    topological_order(plan.steps)
    check_unique(plan.checks,"checks"); check_unique(plan.dimensions,"dimensions")
    used=set()
    for s in plan.steps:
        require(set(s.requirement_ids)<=reqs.keys(),"UNKNOWN_REQUIREMENT","Plan step references an unknown requirement.")
        require(set(s.component_ids)<=comps,"UNKNOWN_COMPONENT","Plan step references an unknown component.")
        used.update(s.component_ids)
    require(comps<=used,"UNPLANNED_COMPONENT","Some components have no plan step.",missing=sorted(comps-used))
    checkmap={r:[] for r in reqs}
    for ch in plan.checks:
        require(set(ch.requirement_ids)<=reqs.keys(),"UNKNOWN_REQUIREMENT","A check references an unknown requirement.")
        for r in ch.requirement_ids: checkmap[r].append(ch)
    for r in reqs.values():
        if r.priority=="preference": continue
        require(bool(checkmap[r.id]),"UNCHECKED_REQUIREMENT","Each mandatory requirement needs a verification obligation.",requirement_id=r.id)
        if r.verification=="physical":
            require(any(ch.kind=="physical_test" for ch in checkmap[r.id]),"PHYSICAL_TEST_REQUIRED","A geometric pass cannot substitute for a physical requirement.",requirement_id=r.id)
        if r.verification=="geometry":
            require(any(ch.kind not in ("manual","physical_test") for ch in checkmap[r.id]),"GEOMETRY_TEST_REQUIRED","A geometry requirement needs at least one measured geometry check.",requirement_id=r.id)
    for d in plan.dimensions:
        refs_valid(d.source_refs,p.sources)
        if d.provenance=="user":
            require(bool(d.source_refs),"UNSOURCED_DIMENSION","User dimensions must quote a source.",dimension_id=d.id)
            vals=[]
            for ref in d.source_refs:
                for value,unit in re.findall(r"(?<![0-9A-Za-z_.+\-])([0-9]+(?:\.[0-9]+)?)\s*(mm|cm|m|ミリ|センチ)(?![A-Za-z])",ref.quote,re.I):
                    vals.append(float(value)*{"mm":1,"ミリ":1,"cm":10,"センチ":10,"m":1000}[unit.lower()])
            require(any(abs(v-d.value_mm)<1e-9 for v in vals),"INVENTED_DIMENSION","Claimed user dimension was not found with units in its source quote; mark a design choice as proposal.",dimension_id=d.id)
        elif d.provenance=="measurement":
            m=getattr(p,"measurements",{}).get(d.evidence_id)
            require(m is not None and m.get("value_mm")==d.value_mm,"UNVERIFIED_MEASUREMENT","Measurement dimensions require a stored, kernel-produced evidence ID.",dimension_id=d.id)
    unknowns_valid(plan.unknowns,p.sources)
    blocked=pending(p.brief.unknowns+c.unknowns+plan.unknowns,"plan")
    require(not blocked,"BLOCKING_UNKNOWNS","The plan depends on unresolved information.",unknowns=blocked)
