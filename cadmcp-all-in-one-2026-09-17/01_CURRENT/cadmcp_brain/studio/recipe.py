"""Typed, non-executable CAD recipes: adapt real references without eval/exec.

This module is the bounded reference-adaptation workbench, not another canonical
CAD project. Its recipe, STEP and provenance are handed to the existing backend.
"""
from __future__ import annotations
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..errors import BrainError

Vec = Annotated[list[float], Field(min_length=3, max_length=3)]
Name = Annotated[str, Field(pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,63}$')]
Positive = Annotated[float, Field(gt=0, le=1_000_000)]

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)

class Node(Strict):
    id: Name
    function_id: Name
    reason: str = Field(min_length=8, max_length=2000)

class Reference(Node):
    op: Literal['reference']
    uid: str = Field(pattern=r'^\d{4}/\d{8}$')
    evidence_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    # Uniform scaling is an EXPLICIT design adaptation, not a unit inference.
    uniform_scale: Positive
    adaptation_basis: str = Field(min_length=12, max_length=2000)

class ProjectStep(Node):
    op: Literal['project_step']
    artifact_id: Name
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    role: Literal['protected_hardware','design_reference']
    unit_basis: str = Field(min_length=10,max_length=2000)

class Box(Node):
    op: Literal['box']
    size_mm: Vec
    center_mm: Vec
    @model_validator(mode='after')
    def positive(self):
        if any(x <= 0 or x > 1_000_000 for x in self.size_mm): raise ValueError('Positive bounded box dimensions required.')
        return self

class Cylinder(Node):
    op: Literal['cylinder']
    radius_mm: Positive
    height_mm: Positive
    origin_mm: Vec
    axis: Vec
    @model_validator(mode='after')
    def unit_axis(self):
        if abs(sum(x*x for x in self.axis)-1) > 1e-6: raise ValueError('Cylinder axis must be a unit direction.')
        return self

class Transform(Node):
    op: Literal['transform']
    source: Name
    translation_mm: Vec
    rotation_axis: Vec = Field(default_factory=lambda:[0.,0.,1.])
    rotation_deg: float = Field(default=0., ge=-360, le=360)
    rotation_origin_mm: Vec = Field(default_factory=lambda:[0.,0.,0.])
    @model_validator(mode='after')
    def unit_axis(self):
        if abs(sum(x*x for x in self.rotation_axis)-1) > 1e-6: raise ValueError('Rotation axis must be a unit direction.')
        return self

class Boolean(Node):
    op: Literal['union','difference','intersection']
    operands: list[Name] = Field(min_length=2, max_length=32)

class Fillet(Node):
    op: Literal['fillet_all']
    source: Name
    radius_mm: Positive
    # Explicit operation, no reduction of failed radius.

Operation = Annotated[Union[Reference,ProjectStep,Box,Cylinder,Transform,Boolean,Fillet],Field(discriminator='op')]

class Output(Strict):
    part_id: Name
    node: Name
    expected_solids: int = Field(default=1, ge=1, le=64)
    manufacturing_process: str = Field(default='FDM prototype; parameters not qualified', max_length=300)

class Clearance(Strict):
    id: Name
    part_a: Name
    part_b: Name
    min_mm: float = Field(ge=0, le=1_000_000)
    max_overlap_mm3: float = Field(default=1e-7, ge=0, le=1e-3)

class Dimension(Strict):
    id: Name
    part: Name
    kind: Literal['bbox','inner_cylinder_diameter','outer_cylinder_diameter']
    axis: Literal['x','y','z']
    nominal_mm: Positive
    tolerance_mm: float = Field(ge=0,le=1000)

class Motion(Strict):
    id: Name
    moving_part: Name
    obstacles: list[Name] = Field(min_length=1, max_length=32)
    translation_end_mm: Vec
    samples: int = Field(default=11, ge=2, le=101)
    max_samples: int = Field(default=101,ge=2,le=201)
    assumed_distance_error_mm: float = Field(default=1e-6,gt=0,le=.1)
    min_mm: float = Field(default=0., ge=0)
    max_overlap_mm3: float = Field(default=1e-7, ge=0, le=1e-3)

class Recipe(Strict):
    schema_version: Literal[1] = 1
    title: str = Field(min_length=3, max_length=200)
    original_request: str = Field(min_length=3, max_length=20000)
    units: Literal['mm'] = 'mm'
    design_parameters: dict[str, float] = Field(default_factory=dict)
    parameter_basis: dict[str, str] = Field(default_factory=dict)
    functions: dict[Name, str] = Field(min_length=1)
    operations: list[Operation] = Field(min_length=1, max_length=128)
    outputs: list[Output] = Field(min_length=1, max_length=16)
    dimension_checks: list[Dimension] = Field(default_factory=list,max_length=64)
    clearance_checks: list[Clearance] = Field(default_factory=list, max_length=64)
    motion_checks: list[Motion] = Field(default_factory=list, max_length=8)
    unverified_requirements: list[str] = Field(min_length=1, max_length=100)
    @model_validator(mode='after')
    def connected(self):
        defined = set(); references = 0; dependencies = {}; protected=set()
        if set(self.design_parameters) != set(self.parameter_basis):
            raise ValueError('Every proposed/measured parameter needs a basis; no extra basis keys.')
        if any(len(b.strip()) < 8 for b in self.parameter_basis.values()):
            raise ValueError('Parameter provenance must distinguish proposal from measurement.')
        for node in self.operations:
            if node.id in defined: raise ValueError('Duplicate node id.')
            if node.function_id not in self.functions: raise ValueError('Node must link to a defined function.')
            deps = ([node.source] if isinstance(node,(Transform,Fillet)) else
                    node.operands if isinstance(node,Boolean) else [])
            if any(x not in defined for x in deps): raise ValueError('DAG operands must name earlier nodes; no cycles or guessed IDs.')
            if len(deps) != len(set(deps)): raise ValueError('Duplicate operands are not meaningful.')
            if isinstance(node,ProjectStep) and node.role=='protected_hardware':protected.add(node.id)
            if isinstance(node,(Transform,Fillet)) and node.source in protected:
                raise ValueError('Protected hardware cannot be transformed or reshaped.')
            if isinstance(node,Boolean) and (node.operands[0] in protected or (node.op=='union' and set(node.operands)&protected)):
                raise ValueError('Protected hardware can only serve as a read-only obstacle/cutting tool, not the mutable target or fused part.')
            dependencies[node.id] = set(deps); defined.add(node.id)
            references += isinstance(node,(Reference,ProjectStep))
        if not references: raise ValueError('This workbench requires real STEP geometry: a Req2CAD reference or a registered project STEP. Primitive boxes are not a substitute catalog.')
        parts = {p.part_id for p in self.outputs}
        if len(parts)!=len(self.outputs): raise ValueError('Duplicate output part id.')
        used=set()
        def walk(n):
            if n in used:return
            used.add(n)
            for d in dependencies[n]:walk(d)
        for out in self.outputs:
            if out.node not in defined: raise ValueError('Output node does not exist.')
            walk(out.node)
        if not any(isinstance(n,(Reference,ProjectStep)) and n.id in used for n in self.operations):
            raise ValueError('A detached token reference is not reference-driven design.')
        if used!=defined: raise ValueError('Unused recipe operations obscure intent; remove them.')
        ids=[]
        for d in self.dimension_checks:
            if d.part not in parts:raise ValueError('Dimension check must reference an output part.')
            ids.append(d.id)
        for chk in self.clearance_checks:
            if chk.part_a not in parts or chk.part_b not in parts or chk.part_a==chk.part_b: raise ValueError('Invalid clearance part pair.')
            ids.append(chk.id)
        for chk in self.motion_checks:
            if chk.max_samples<chk.samples:raise ValueError('Maximum samples cannot be smaller than the initial samples.')
            if any(p.part_id==chk.moving_part and p.node in protected for p in self.outputs):raise ValueError('Protected hardware pose must stay fixed.')
            if chk.moving_part not in parts or any(x not in parts or x==chk.moving_part for x in chk.obstacles):raise ValueError('Invalid motion obstacles.')
            if len(chk.obstacles)!=len(set(chk.obstacles)):raise ValueError('Duplicate obstacle.')
            ids.append(chk.id)
        if len(ids)!=len(set(ids)):raise ValueError('Duplicate check IDs.')
        return self


def pair_clearance(a,b):
    """Kernel distance and overlap volume for two solids. Empty intersection is zero overlap."""
    common=a.intersect(b); overlap=float(sum(s.Volume() for s in common.Solids()))
    return float(a.distance(b)),overlap


def apply_rigid_mm(body,translation_mm,rotation_axis,rotation_deg,rotation_origin_mm):
    import numpy as np
    origin=np.asarray(rotation_origin_mm)
    return body.rotate(tuple(origin),tuple(origin+np.asarray(rotation_axis)),rotation_deg).translate(tuple(translation_mm))


def evaluate_geometry(recipe,part_shapes):
    """Overlap, dimension, clearance and sampled-motion checks. Does not export files."""
    import numpy as np
    recipe=Recipe.model_validate(recipe) if not isinstance(recipe,Recipe) else recipe
    checks=[]
    for output in recipe.outputs:
        body=part_shapes[output.part_id]
        checks.append({'id':'solid-count-'+output.part_id,'verdict':'pass' if len(body.Solids())==output.expected_solids else 'fail','actual':len(body.Solids()),'expected':output.expected_solids,'kind':'BRep validity and expected solid count'})
    # Every exported part pair is checked even when the model omits a
    # named clearance check. Intended contacts may touch, but solid overlap
    # is not silently accepted as a valid assembly.
    part_names=list(part_shapes)
    for i,a in enumerate(part_names):
        for b in part_names[i+1:]:
            distance,overlap=pair_clearance(part_shapes[a],part_shapes[b])
            checks.append({'id':'overlap-'+a+'-'+b,'kind':'automatic_output_pair_interference',
                           'distance_mm':distance,'overlap_mm3':overlap,'max_overlap_mm3':1e-7,
                           'verdict':'pass' if overlap<=1e-7 else 'fail'})
    for d in recipe.dimension_checks:
        body=part_shapes[d.part];axis_index={'x':0,'y':1,'z':2}[d.axis]
        if d.kind=='bbox':
            bbox=body.BoundingBox();values=[[bbox.xlen,bbox.ylen,bbox.zlen][axis_index]]
        else:
            from .interfaces import extract_interfaces
            kind='inner_cylinder' if d.kind=='inner_cylinder_diameter' else 'outer_cylinder'
            values=[2*p['radius_mm'] for p in extract_interfaces(body)['ports'] if p['port_kind']==kind and abs(p['axis_direction'][axis_index])>1-1e-6]
        passes=[v for v in values if abs(v-d.nominal_mm)<=d.tolerance_mm+1e-8]
        checks.append({'id':d.id,'kind':d.kind,'axis':d.axis,'part':d.part,'actual_candidates_mm':values,
                       'nominal_mm':d.nominal_mm,'tolerance_mm':d.tolerance_mm,'verdict':'pass' if passes else 'fail',
                       'scope':'Analytic surface presence/dimension only; a cylindrical surface does not prove a through-bore.'})
    for c in recipe.clearance_checks:
        distance,overlap=pair_clearance(part_shapes[c.part_a],part_shapes[c.part_b])
        checks.append({'id':c.id,'kind':'static_clearance','distance_mm':distance,'overlap_mm3':overlap,
                       'required_mm':c.min_mm,'max_overlap_mm3':c.max_overlap_mm3,
                       'verdict':'pass' if distance+1e-8>=c.min_mm and overlap<=c.max_overlap_mm3 else 'fail'})
    for motion in recipe.motion_checks:
        # For fixed orientation, distance(A+t*v, B) is ||v||-Lipschitz in t.
        # A uniform grid bounds unsampled distance by min(grid distances) -
        # half the sample spacing in mm. This is conditional on the explicitly
        # stated kernel distance-error allowance, NOT a formal OCCT proof.
        count=motion.samples;cache={};lower_bound=None;certificate=False
        travel=float(np.linalg.norm(motion.translation_end_mm))
        while True:
            samples=[]
            for t in np.linspace(0.,1.,count):
                moving=part_shapes[motion.moving_part].translate(tuple(np.asarray(motion.translation_end_mm)*t))
                for obstacle in motion.obstacles:
                    key=(float(t),obstacle)
                    if key not in cache:cache[key]=pair_clearance(moving,part_shapes[obstacle])
                    distance,overlap=cache[key]
                    samples.append({'t':float(t),'obstacle':obstacle,'distance_mm':distance,'overlap_mm3':overlap,
                                    'verdict':'pass' if distance+1e-8>=motion.min_mm and overlap<=motion.max_overlap_mm3 else 'fail'})
            min_observed=min(s['distance_mm'] for s in samples)
            lower_bound=min_observed-travel/(2*(count-1))-motion.assumed_distance_error_mm
            failed=any(s['verdict']=='fail' for s in samples)
            certificate=not failed and lower_bound>=motion.min_mm and lower_bound>0
            if failed or certificate or count>=motion.max_samples:break
            count=min(2*(count-1)+1,motion.max_samples)
        checks.append({'id':motion.id,'kind':'sampled_translation_clearance','samples':samples,
                       'verdict':'pass' if all(x['verdict']=='pass' for x in samples) else 'fail',
                       'continuous_swept_motion':'distance_bound_satisfied_under_stated_assumptions' if certificate else 'not_proven',
                       'continuous_distance_lower_bound_mm':lower_bound,
                       'assumed_distance_error_mm':motion.assumed_distance_error_mm,
                       'initial_samples':motion.samples,'final_samples':count,
                       'certificate_scope':'Fixed-orientation linear translation against fixed obstacles. The numerical distance-error allowance is an assumption, not a certified OCCT error bound. Rotations, deformation, wear and tolerance variation are excluded.'})
    return {'checks':checks,'geometry_checks_verdict':'pass' if all(x['verdict']=='pass' for x in checks) else 'fail'}


def execute_recipe(recipe, sources, out_dir):
    """Called only inside a time-bounded worker process. Never runs model code."""
    import cadquery as cq
    import numpy as np
    from pathlib import Path
    from ..req2cad.common import file_hash, atomic_json
    from ..req2cad.geometry import shape_features
    recipe = Recipe.model_validate(recipe)
    out_dir=Path(out_dir);out_dir.mkdir(parents=True,exist_ok=True)
    shapes={}; trace=[]; reference_sources=[]
    for node in recipe.operations:
        if isinstance(node,Reference):
            source=sources[node.uid]
            if source['evidence_digest'] != node.evidence_digest or file_hash(Path(source['step'])) != source['sha256']:
                raise BrainError('STUDIO_STALE_REFERENCE','Source reference changed before adaptation.')
            vals=cq.importers.importStep(source['step']).vals()
            body=vals[0] if len(vals)==1 else cq.Compound.makeCompound(vals)
            if node.uniform_scale!=1:body=body.scale(node.uniform_scale)
            reference_sources.append({k:source[k] for k in ('uid','evidence_digest','sha256','reference_only')})
        elif isinstance(node,ProjectStep):
            source=sources['project:'+node.artifact_id]
            if file_hash(Path(source['step']))!=node.sha256:raise BrainError('STUDIO_STALE_HARDWARE','Project STEP changed.')
            vals=cq.importers.importStep(source['step']).vals()
            body=vals[0] if len(vals)==1 else cq.Compound.makeCompound(vals)
        elif isinstance(node,Box):
            body=cq.Workplane('XY').box(*node.size_mm).val().translate(tuple(node.center_mm))
        elif isinstance(node,Cylinder):
            body=cq.Solid.makeCylinder(node.radius_mm,node.height_mm,cq.Vector(*node.origin_mm),cq.Vector(*node.axis))
        elif isinstance(node,Transform):
            origin=np.asarray(node.rotation_origin_mm)
            body=shapes[node.source].rotate(tuple(origin),tuple(origin+np.asarray(node.rotation_axis)),node.rotation_deg).translate(tuple(node.translation_mm))
        elif isinstance(node,Fillet):
            src=shapes[node.source]
            if len(src.Solids())!=1:raise BrainError('STUDIO_FILLET','Fillet requires one solid.')
            body=src.Solids()[0].fillet(node.radius_mm,src.Edges())
        else:
            body=shapes[node.operands[0]]
            for operand in node.operands[1:]:
                body={'union':body.fuse,'difference':body.cut,'intersection':body.intersect}[node.op](shapes[operand])
        if not body.isValid() or not body.Solids() or any(s.Volume()<=0 for s in body.Solids()):
            raise BrainError('STUDIO_INVALID_SOLID','Operation produced an empty/invalid solid.',{'node':node.id,'op':node.op})
        shapes[node.id]=body
        trace.append({'node':node.id,'op':node.op,'function_id':node.function_id,'reason':node.reason,
                      'volume_mm3':float(sum(s.Volume() for s in body.Solids())), 'solids':len(body.Solids())})
    outputs={}
    for output in recipe.outputs:
        body=shapes[output.node];folder=out_dir/output.part_id;folder.mkdir()
        features=shape_features(body,point_count=512);features.pop('surface_points_mm')
        cq.exporters.export(body,str(folder/'model.step'))
        cq.exporters.export(body,str(folder/'model.stl'),tolerance=.01)
        for label,d in [('iso',(1,1,1)),('top',(0,0,1)),('front',(0,-1,0)),('right',(1,0,0))]:
            (folder/(label+'.svg')).write_text(cq.exporters.getSVG(body,opts={'width':700,'height':460,'projectionDir':d,'showAxes':False}),encoding='utf-8')
            from .render import render_shapes
            render_shapes([body],folder/(label+'.png'),d,label=output.part_id+' / '+label.upper())
        files={p.name:{'relative_path':p.relative_to(out_dir).as_posix(),'sha256':file_hash(p)} for p in folder.iterdir() if p.is_file()}
        outputs[output.part_id]={'features':features,'exports':files,'manufacturing_process':output.manufacturing_process}
    part_shapes={o.part_id:shapes[o.node] for o in recipe.outputs}
    measured=evaluate_geometry(recipe,part_shapes)
    checks=measured['checks']
    from .render import render_shapes
    render_shapes(list(part_shapes.values()),out_dir/'assembly.png',(1,1,1),width=900,height=650,label='Prototype assembly / not a certified product')
    assembly=cq.Compound.makeCompound(list(part_shapes.values()))
    cq.exporters.export(assembly,str(out_dir/'assembly.step'))
    (out_dir/'assembly.svg').write_text(cq.exporters.getSVG(assembly,opts={'width':900,'height':650,'projectionDir':(1,1,1),'showAxes':False}),encoding='utf-8')
    result={'recipe_schema':1,'outputs':outputs,'trace':trace,'references':reference_sources,'checks':checks,
            'geometry_checks_verdict':measured['geometry_checks_verdict'],
            'overall_verdict':'unknown','unverified_requirements':recipe.unverified_requirements,
            'assembly':{'relative_path':'assembly.step','sha256':file_hash(out_dir/'assembly.step')},
            'unit_notice':'Target recipe assigns mm explicitly; imported reference scale is a design choice, not proof of original physical units.',
            'notes':['No global wall thickness or FEA certification.', 'Motion checks use adaptive samples and a conditional Lipschitz distance bound; not formal kernel-error certification.', 'No printer commands or canonical CAD writes were sent.']}
    atomic_json(out_dir/'recipe.json',recipe.model_dump())
    atomic_json(out_dir/'measurements.json',result)
    return result
