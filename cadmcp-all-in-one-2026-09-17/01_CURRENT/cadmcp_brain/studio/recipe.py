"""Typed CAD recipes: compose original geometry or adapt measured references.

This module is the bounded geometry workbench, not another canonical
CAD project. Its recipe, STEP and provenance are handed to the existing backend.
"""
from __future__ import annotations
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..errors import BrainError

Vec = Annotated[list[float], Field(min_length=3, max_length=3)]
Vec2 = Annotated[list[float], Field(min_length=2, max_length=2)]
Name = Annotated[str, Field(pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,63}$')]
Positive = Annotated[float, Field(gt=0, le=1_000_000)]
Statement = Annotated[str, Field(min_length=8,max_length=2000)]
DELIVERY_VOLUME_TOLERANCE_MM3=1e-7
DELIVERY_BOUNDS_TOLERANCE_MM=1e-6
DELIVERY_MAX_SOLIDS=128

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

class PolygonExtrusion(Node):
    """A bounded, closed XY polygon extruded along +Z; not a loft/sweep substitute."""
    op: Literal['polygon_extrusion']
    points_mm: list[Vec2] = Field(min_length=3, max_length=64)
    height_mm: Positive
    origin_mm: Vec = Field(default_factory=lambda:[0.,0.,0.])
    @model_validator(mode='after')
    def simple_profile(self):
        points=[tuple(p) for p in self.points_mm]
        if any(abs(v)>1_000_000 for p in points for v in p):
            raise ValueError('Polygon coordinates must stay within the bounded CAD workspace.')
        if len(set(points))!=len(points):raise ValueError('Polygon vertices must be distinct.')
        area=sum(points[i][0]*points[(i+1)%len(points)][1]-points[(i+1)%len(points)][0]*points[i][1] for i in range(len(points)))/2
        if abs(area)<=1e-9:raise ValueError('Polygon profile must enclose nonzero area.')
        def orient(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        def on_segment(a,b,p):
            return (abs(orient(a,b,p))<=1e-9 and
                    min(a[0],b[0])-1e-9<=p[0]<=max(a[0],b[0])+1e-9 and
                    min(a[1],b[1])-1e-9<=p[1]<=max(a[1],b[1])+1e-9)
        def intersects(a,b,c,d):
            o=(orient(a,b,c),orient(a,b,d),orient(c,d,a),orient(c,d,b))
            return (((o[0]>1e-9) != (o[1]>1e-9) and (o[2]>1e-9) != (o[3]>1e-9)) or
                    on_segment(a,b,c) or on_segment(a,b,d) or on_segment(c,d,a) or on_segment(c,d,b))
        count=len(points)
        for i in range(count):
            a,b=points[i],points[(i+1)%count]
            for j in range(i+1,count):
                if j in (i,(i+1)%count) or (j+1)%count in (i,(i+1)%count):continue
                if intersects(a,b,points[j],points[(j+1)%count]):
                    raise ValueError('Polygon profile must not self-intersect.')
        return self

class LoftSection(Strict):
    """One closed XY polygon at a fixed Z elevation for a bounded solid loft."""
    z_mm: float = Field(ge=-1_000_000, le=1_000_000)
    points_mm: list[Vec2] = Field(min_length=3, max_length=64)
    @model_validator(mode='after')
    def simple_profile(self):
        # Keep the same bounded-simple-polygon contract as extrusion instead
        # of introducing a second, subtly different profile validator.
        PolygonExtrusion(id='section',function_id='section',
                         reason='Validate this bounded loft section profile.',
                         op='polygon_extrusion',points_mm=self.points_mm,
                         height_mm=1.,origin_mm=[0.,0.,0.])
        return self

class Loft(Node):
    """Solid loft through parallel XY polygon sections; not a sweep."""
    op: Literal['loft']
    sections: list[LoftSection] = Field(min_length=2, max_length=16)
    mode: Literal['smooth','ruled']
    @model_validator(mode='after')
    def coherent_sections(self):
        z_values=[section.z_mm for section in self.sections]
        if any(later<=earlier for earlier,later in zip(z_values,z_values[1:])):
            raise ValueError('Loft section elevations must be strictly ascending; duplicate planes are not allowed.')
        vertex_count=len(self.sections[0].points_mm)
        if any(len(section.points_mm)!=vertex_count for section in self.sections[1:]):
            raise ValueError('Loft sections must have the same polygon vertex count.')
        signed_areas=[]
        for section in self.sections:
            points=section.points_mm
            signed_areas.append(sum(points[i][0]*points[(i+1)%len(points)][1]-points[(i+1)%len(points)][0]*points[i][1]
                                    for i in range(len(points)))/2)
        if any(area*signed_areas[0] <= 0 for area in signed_areas[1:]):
            raise ValueError('Loft sections must retain one polygon winding direction.')
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

Operation = Annotated[Union[Reference,ProjectStep,Box,Cylinder,PolygonExtrusion,Loft,Transform,Boolean,Fillet],Field(discriminator='op')]

class ReferenceUse(Strict):
    """Auditable Req2CAD use, independent of whether its shape is imported."""
    function_id: Name
    use: Literal['principle_reference','fit_reference','direct_reuse']
    uid: str = Field(pattern=r'^\d{4}/\d{8}$')
    evidence_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    cad_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    application: str = Field(min_length=12,max_length=2000)
    used_face_ids: list[str] = Field(default_factory=list,max_length=128)
    @model_validator(mode='after')
    def fit_faces(self):
        if self.use=='fit_reference' and not self.used_face_ids:
            raise ValueError('Fit references must identify the measured faces used for fit.')
        if len(self.used_face_ids)!=len(set(self.used_face_ids)):raise ValueError('Duplicate referenced face id.')
        return self

class DesignBasis(Strict):
    kind: Literal['first_principles','provided_cad','reference_informed','mixed']
    summary: str = Field(min_length=12,max_length=2000)
    assumptions: list[Statement] = Field(min_length=1,max_length=50)
    @model_validator(mode='after')
    def meaningful(self):
        if len(self.summary.strip())<12 or any(len(x.strip())<8 for x in self.assumptions):
            raise ValueError('Design basis and assumptions must be meaningful statements.')
        return self

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
    protected_constraints: list[str] = Field(default_factory=list,max_length=50)
    reference_uses: list[ReferenceUse] = Field(default_factory=list,max_length=64)
    design_basis: DesignBasis | None = None
    verification_plan: list[Statement] = Field(default_factory=list,max_length=100)
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
        if not references:
            if self.design_basis is None or not self.verification_plan:
                raise ValueError('A new shape without imported CAD requires an explicit design basis and verification plan.')
            if any(len(x.strip())<8 for x in self.verification_plan):
                raise ValueError('Verification-plan entries must name a meaningful check.')
        reference_nodes={(n.uid,n.evidence_digest) for n in self.operations if isinstance(n,Reference)}
        seen_uses=set()
        for use in self.reference_uses:
            key=(use.function_id,use.use,use.uid)
            if key in seen_uses:raise ValueError('Duplicate reference-use provenance.')
            seen_uses.add(key)
            if use.function_id not in self.functions:raise ValueError('Reference use must link to a defined function.')
            if use.use=='direct_reuse' and (use.uid,use.evidence_digest) not in reference_nodes:
                raise ValueError('Direct reuse must name a matching imported reference operation.')
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


def verify_delivery_steps(part_steps, assembly_step):
    """Re-import delivered STEP files and prove a one-to-one solid match.

    The tolerance is solely a fixed numerical STEP/B-rep comparison allowance;
    it is not a design or manufacturing tolerance and is never auto-relaxed.
    """
    import cadquery as cq
    import math
    from OCP.TopoDS import TopoDS_Iterator
    from pathlib import Path
    from .measurement import nominal_bounds

    def solids(path):
        values=cq.importers.importStep(str(Path(path))).vals()
        result=[]
        def collect(value):
            kind=value.ShapeType()
            if kind=='Solid':
                result.append(value);return
            if kind not in ('Compound','CompSolid'):
                raise BrainError('STUDIO_INVALID_DELIVERY_STEP','Delivered STEP contains standalone non-solid topology.',
                                 {'path':str(path),'shape_type':kind})
            iterator=TopoDS_Iterator(value.wrapped)
            while iterator.More():
                collect(cq.Shape.cast(iterator.Value()))
                iterator.Next()
        for value in values:collect(value)
        if not result or any(not solid.isValid() or not math.isfinite(float(solid.Volume())) or solid.Volume()<=0
                             for solid in result):
            raise BrainError('STUDIO_INVALID_DELIVERY_STEP','Delivered STEP contains no valid positive-volume solids.',
                             {'path':str(path)})
        return result

    expected=[]
    for part_id,path in part_steps.items():
        expected.extend((part_id,index,solid) for index,solid in enumerate(solids(path)))
    delivered=solids(assembly_step)
    if len(expected)>DELIVERY_MAX_SOLIDS or len(delivered)>DELIVERY_MAX_SOLIDS:
        raise BrainError('STUDIO_DELIVERY_COMPLEXITY','Delivery equivalence exceeds the bounded solid comparison limit.',
                         {'part_solids':len(expected),'assembly_solids':len(delivered),'max_solids':DELIVERY_MAX_SOLIDS})
    comparisons=[];compatible={index:[] for index in range(len(expected))}
    for expected_index,(part_id,solid_index,left) in enumerate(expected):
        for assembly_index,right in enumerate(delivered):
            left_bounds=nominal_bounds(left);right_bounds=nominal_bounds(right)
            volume_delta=abs(float(left.Volume())-float(right.Volume()))
            if (volume_delta>DELIVERY_VOLUME_TOLERANCE_MM3 or
                    any(abs(a-b)>DELIVERY_BOUNDS_TOLERANCE_MM for a,b in zip(left_bounds,right_bounds))):
                comparisons.append({'part_id':part_id,'part_solid_index':solid_index,
                                    'assembly_solid_index':assembly_index,'prefilter':'different_bounds_or_volume',
                                    'absolute_volume_delta_mm3':volume_delta})
                continue
            left_difference=left.cut(right);right_difference=right.cut(left)
            if (left_difference.wrapped.IsNull() or right_difference.wrapped.IsNull() or
                    not left_difference.isValid() or not right_difference.isValid()):
                raise BrainError('STUDIO_DELIVERY_BOOLEAN','Delivery STEP comparison produced an invalid Boolean result.',
                                 {'part_id':part_id,'part_solid_index':solid_index,
                                  'assembly_solid_index':assembly_index})
            left_only=float(sum(s.Volume() for s in left_difference.Solids()))
            right_only=float(sum(s.Volume() for s in right_difference.Solids()))
            if not all(math.isfinite(value) and value>=0 for value in (left_only,right_only)):
                raise BrainError('STUDIO_DELIVERY_BOOLEAN','Delivery STEP comparison produced a non-finite difference.',
                                 {'part_id':part_id,'part_solid_index':solid_index,
                                  'assembly_solid_index':assembly_index})
            candidate={'part_id':part_id,'part_solid_index':solid_index,
                       'assembly_solid_index':assembly_index,
                       'part_minus_assembly_mm3':left_only,
                       'assembly_minus_part_mm3':right_only}
            comparisons.append(candidate)
            if left_only<=DELIVERY_VOLUME_TOLERANCE_MM3 and right_only<=DELIVERY_VOLUME_TOLERANCE_MM3:
                compatible[expected_index].append(assembly_index)

    matched_assembly={}
    def assign(expected_index,seen):
        for assembly_index in compatible[expected_index]:
            if assembly_index in seen:continue
            seen.add(assembly_index)
            if assembly_index not in matched_assembly or assign(matched_assembly[assembly_index],seen):
                matched_assembly[assembly_index]=expected_index
                return True
        return False
    matched_expected={index for index in range(len(expected)) if assign(index,set())}
    unmatched_parts=[{'part_id':part_id,'solid_index':solid_index}
                     for index,(part_id,solid_index,_) in enumerate(expected) if index not in matched_expected]
    unmatched_assembly=[index for index in range(len(delivered)) if index not in matched_assembly]
    passed=(len(expected)==len(delivered) and not unmatched_parts and not unmatched_assembly)
    return {'id':'_system-delivery-step-geometry-consistency','kind':'reimported_step_one_to_one_solid_equivalence',
            'verdict':'pass' if passed else 'fail','part_solid_count':len(expected),
            'assembly_solid_count':len(delivered),'unmatched_part_solids':unmatched_parts,
            'unmatched_assembly_solids':unmatched_assembly,'comparisons':comparisons,
            'comparison_tolerance_mm3':DELIVERY_VOLUME_TOLERANCE_MM3,
            'prefilter_tolerance_mm':DELIVERY_BOUNDS_TOLERANCE_MM,'max_solids':DELIVERY_MAX_SOLIDS,
            'tolerance_interpretation':'Fixed numerical STEP/B-rep comparison allowance only; not a design or manufacturing tolerance; never auto-relaxed.',
            'scope':'Every re-imported part solid must match exactly one re-imported assembly solid in both difference directions.'}


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
            from .measurement import nominal_bounds
            bounds=nominal_bounds(body);values=[bounds[axis_index+3]-bounds[axis_index]]
        else:
            from .interfaces import extract_interfaces
            kind='inner_cylinder' if d.kind=='inner_cylinder_diameter' else 'outer_cylinder'
            values=[2*p['radius_mm'] for p in extract_interfaces(body)['ports'] if p['port_kind']==kind and abs(p['axis_direction'][axis_index])>1-1e-6]
        passes=[v for v in values if abs(v-d.nominal_mm)<=d.tolerance_mm+1e-8]
        checks.append({'id':d.id,'kind':d.kind,'axis':d.axis,'part':d.part,'actual_candidates_mm':values,
                       'measurement_basis':'nominal B-rep bounds; cached triangulation and shape-tolerance enlargement disabled' if d.kind=='bbox' else 'analytic cylinder surface',
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
        elif isinstance(node,PolygonExtrusion):
            body=(cq.Workplane('XY').polyline([tuple(p) for p in node.points_mm]).close()
                  .extrude(node.height_mm).val().translate(tuple(node.origin_mm)))
        elif isinstance(node,Loft):
            try:
                wires=[cq.Wire.makePolygon([(x,y,section.z_mm) for x,y in section.points_mm],close=True)
                       for section in node.sections]
                body=cq.Solid.makeLoft(wires,ruled=node.mode=='ruled')
                if not body.isValid() or len(body.Solids())!=1 or body.Solids()[0].Volume()<=0:
                    raise ValueError('Loft must produce exactly one valid positive-volume solid.')
            except Exception as exc:
                raise BrainError('STUDIO_INVALID_SOLID','Loft kernel construction failed; no fallback geometry was used.',
                                 {'node':node.id,'op':node.op}) from exc
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
    delivery_check=verify_delivery_steps(
        {part_id:out_dir/part_id/'model.step' for part_id in outputs},out_dir/'assembly.step')
    checks.append(delivery_check)
    geometry_verdict='pass' if all(check['verdict']=='pass' for check in checks) else 'fail'
    result={'recipe_schema':1,'outputs':outputs,'trace':trace,'references':reference_sources,
            'reference_uses':[r.model_dump() for r in recipe.reference_uses],
            'design_basis':recipe.design_basis.model_dump() if recipe.design_basis else None,
            'verification_plan':recipe.verification_plan,'checks':checks,
            'geometry_checks_verdict':geometry_verdict,
            'overall_verdict':'unknown','unverified_requirements':recipe.unverified_requirements,
            'assembly':{'relative_path':'assembly.step','sha256':file_hash(out_dir/'assembly.step')},
            'unit_notice':'Target recipe assigns mm explicitly; imported reference scale is a design choice, not proof of original physical units.',
            'notes':['No global wall thickness or FEA certification.', 'Motion checks use adaptive samples and a conditional Lipschitz distance bound; not formal kernel-error certification.', 'No printer commands or canonical CAD writes were sent.']}
    atomic_json(out_dir/'recipe.json',recipe.model_dump())
    atomic_json(out_dir/'measurements.json',result)
    return result
