"""Independent artifact acceptance: fixed owner/test criteria, never model-authored checks.

Uses the same OCCT kernel, but reimports only the delivered STEP, not its recipe.
This is an independent verification path, not an independent physical solver.
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..errors import BrainError
from ..req2cad.common import atomic_json, digest, file_hash, json_load, trusted_file
from ..util import safe_id, safe_path

Coordinate = Annotated[float, Field(ge=-1_000_000, le=1_000_000)]
Point = Annotated[list[Coordinate], Field(min_length=3, max_length=3)]
Point2 = Annotated[list[Coordinate], Field(min_length=2, max_length=2)]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


class Region(Strict):
    id: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,63}$')
    lower_mm: Point
    upper_mm: Point
    min_fill: float = Field(ge=0, le=1)
    max_fill: float = Field(ge=0, le=1)

    @model_validator(mode='after')
    def ordered(self):
        if any(b-a < 1e-5 for a,b in zip(self.lower_mm,self.upper_mm)):
            raise ValueError('Acceptance regions must have positive, measurable extent.')
        if self.min_fill > self.max_fill:
            raise ValueError('Region minimum fill exceeds its maximum.')
        return self


def _cross(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def _segments_intersect(a: tuple[float, float], b: tuple[float, float],
                        c: tuple[float, float], d: tuple[float, float]) -> bool:
    eps=1e-12
    ab_c=_cross(a,b,c); ab_d=_cross(a,b,d)
    cd_a=_cross(c,d,a); cd_b=_cross(c,d,b)
    if ((ab_c > eps and ab_d < -eps) or (ab_c < -eps and ab_d > eps)) and \
       ((cd_a > eps and cd_b < -eps) or (cd_a < -eps and cd_b > eps)):
        return True
    def on_segment(p, q, r):
        return abs(_cross(p,q,r)) <= eps and min(p[0],q[0])-eps <= r[0] <= max(p[0],q[0])+eps and min(p[1],q[1])-eps <= r[1] <= max(p[1],q[1])+eps
    return on_segment(a,b,c) or on_segment(a,b,d) or on_segment(c,d,a) or on_segment(c,d,b)


class ExpectedPrism(Strict):
    points_mm: list[Point2] = Field(min_length=3, max_length=64)
    z_min_mm: Coordinate
    z_max_mm: Coordinate
    max_symmetric_difference_mm3: float = Field(ge=0, le=1e12)

    @model_validator(mode='after')
    def coherent(self):
        points=[(p[0],p[1]) for p in self.points_mm]
        if self.z_max_mm <= self.z_min_mm:
            raise ValueError('Expected prism height must be positive.')
        if len(set(points)) != len(points):
            raise ValueError('Expected prism vertices must be unique.')
        signed_area=sum(points[i][0]*points[(i+1)%len(points)][1]-points[(i+1)%len(points)][0]*points[i][1] for i in range(len(points)))/2
        if abs(signed_area) <= 1e-12:
            raise ValueError('Expected prism section must have positive area.')
        for i in range(len(points)):
            a,b=points[i],points[(i+1)%len(points)]
            for j in range(i+1,len(points)):
                if j in (i-1,i,i+1) or (i==0 and j==len(points)-1):
                    continue
                if _segments_intersect(a,b,points[j],points[(j+1)%len(points)]):
                    raise ValueError('Expected prism section must not self-intersect.')
        return self


class AcceptanceSpec(Strict):
    schema_version: Literal[1] = 1
    case_id: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,63}$')
    original_request: str = Field(min_length=3, max_length=20000)
    expected_solids: int = Field(ge=1, le=128)
    lower_mm: Point
    upper_mm: Point
    coordinate_tolerance_mm: float = Field(ge=0, le=100)
    volume_mm3: float = Field(gt=0, le=1e18)
    volume_tolerance_mm3: float = Field(ge=0, le=1e12)
    regions: list[Region] = Field(default_factory=list, max_length=64)
    expected_prism: ExpectedPrism | None = None
    unverified_requirements: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def coherent(self):
        if any(b<=a for a,b in zip(self.lower_mm,self.upper_mm)):
            raise ValueError('Expected bounding envelope must have positive extent.')
        if len({r.id for r in self.regions}) != len(self.regions):
            raise ValueError('Region IDs must be unique.')
        if any(not item.strip() for item in self.unverified_requirements):
            raise ValueError('Unverified requirements cannot be blank.')
        return self


def _difference_volume(left, right) -> float:
    """Measure both sides of a boolean difference without trusting a Recipe."""
    return float(sum(part.Volume() for solid in left.Solids() for part in solid.cut(right).Solids()))


def _prism_check(shape, spec: ExpectedPrism) -> dict:
    import cadquery as cq
    points=[tuple(p) for p in spec.points_mm]
    height=spec.z_max_mm-spec.z_min_mm
    oracle=cq.Workplane('XY').polyline(points).close().extrude(height).val().translate((0,0,spec.z_min_mm))
    candidate_minus_oracle=_difference_volume(shape,oracle)
    oracle_minus_candidate=_difference_volume(oracle,shape)
    symmetric_difference=candidate_minus_oracle+oracle_minus_candidate
    return {'id':'expected_prism','kind':'extruded_section','passed':symmetric_difference<=spec.max_symmetric_difference_mm3,
            'actual_symmetric_difference_mm3':symmetric_difference,
            'candidate_minus_oracle_mm3':candidate_minus_oracle,
            'oracle_minus_candidate_mm3':oracle_minus_candidate,
            'max_symmetric_difference_mm3':spec.max_symmetric_difference_mm3,
            'vertices_mm':spec.points_mm,'z_min_mm':spec.z_min_mm,'z_max_mm':spec.z_max_mm}


def inspect_step(step: Path, spec: AcceptanceSpec, delivery_manifest: Path | None = None,
                 delivery_manifest_sha256: str | None = None) -> dict:
    """Run inside a bounded worker for untrusted CAD. Does not mutate any source."""
    import cadquery as cq
    step=trusted_file(Path(step).resolve(),128*1024*1024)
    before=file_hash(step)
    imported=cq.importers.importStep(str(step)).vals()
    shape=cq.Compound.makeCompound(imported)
    solids=shape.Solids()
    valid=bool(solids) and shape.isValid() and all(s.isValid() and s.Volume()>0 for s in solids)
    if not valid:
        raise BrainError('ACCEPTANCE_INVALID','Delivered STEP is not a valid positive-volume solid model.')
    from .measurement import nominal_bounds
    bounds=nominal_bounds(shape)
    lower=list(bounds[:3]);upper=list(bounds[3:])
    volume=float(sum(s.Volume() for s in solids))
    checks=[{'id':'solid_count','passed':len(solids)==spec.expected_solids,'actual':len(solids),'expected':spec.expected_solids},
            {'id':'positioned_envelope','passed':all(abs(a-b)<=spec.coordinate_tolerance_mm for a,b in zip(lower+upper,spec.lower_mm+spec.upper_mm)),
             'actual_lower_mm':lower,'actual_upper_mm':upper,'tolerance_mm':spec.coordinate_tolerance_mm},
            {'id':'volume','passed':abs(volume-spec.volume_mm3)<=spec.volume_tolerance_mm3,
             'actual_mm3':volume,'expected_mm3':spec.volume_mm3,'tolerance_mm3':spec.volume_tolerance_mm3}]
    for region in spec.regions:
        size=[b-a for a,b in zip(region.lower_mm,region.upper_mm)]
        box=cq.Solid.makeBox(*size,cq.Vector(*region.lower_mm))
        overlap=float(sum(s.Volume() for s in shape.intersect(box).Solids()))
        fraction=overlap/(size[0]*size[1]*size[2])
        checks.append({'id':region.id,'kind':'region_occupancy','actual_fill':fraction,
                       'min_fill':region.min_fill,'max_fill':region.max_fill,
                       'passed':region.min_fill<=fraction<=region.max_fill})
    if spec.expected_prism is not None:
        checks.append(_prism_check(shape,spec.expected_prism))
        prism_scope='verified_against_fixed_expected_prism'
    else:
        checks.append({'id':'expected_prism','kind':'extruded_section','passed':True,'verified':False,
                       'status':'not_specified','note':'Full section/solid equality was not verified because expected_prism is absent.'})
        prism_scope='not_verified_expected_prism_not_specified'
    if delivery_manifest is not None:
        manifest_path=trusted_file(Path(delivery_manifest).resolve(),1024*1024)
        if not delivery_manifest_sha256 or file_hash(manifest_path)!=delivery_manifest_sha256:
            raise BrainError('ACCEPTANCE_DELIVERY_MANIFEST_CHANGED','Delivery manifest does not match its fixed byte hash.')
        manifest=json_load(manifest_path)
        if (not isinstance(manifest,dict) or type(manifest.get('schema_version')) is not int or
                manifest.get('schema_version')!=1 or
                not isinstance(manifest.get('parts'),dict) or not manifest['parts'] or
                set(manifest)!= {'schema_version','assembly','parts'}):
            raise BrainError('ACCEPTANCE_DELIVERY_MANIFEST','Delivery manifest is not the strict internal schema.')
        assembly_entry=manifest.get('assembly')
        entries=[assembly_entry,*manifest['parts'].values()]
        if any(not isinstance(entry,dict) or set(entry)!= {'relative_path','sha256'} or
               not isinstance(entry.get('relative_path'),str) or
               not isinstance(entry.get('sha256'),str) or
               re.fullmatch(r'[0-9a-f]{64}',entry['sha256']) is None for entry in entries):
            raise BrainError('ACCEPTANCE_DELIVERY_MANIFEST','Delivery manifest entries are invalid.')
        for part_id in manifest['parts']:safe_id(part_id)
        root=manifest_path.parent
        resolved={part_id:safe_path(root,entry['relative_path']) for part_id,entry in manifest['parts'].items()}
        resolved_assembly=safe_path(root,assembly_entry['relative_path'])
        if resolved_assembly.resolve()!=step.resolve():
            raise BrainError('ACCEPTANCE_DELIVERY_MANIFEST','Delivery manifest assembly does not identify the accepted STEP.')
        for entry,path in [(assembly_entry,resolved_assembly),
                           *((manifest['parts'][part_id],path) for part_id,path in resolved.items())]:
            if file_hash(path)!=entry['sha256']:
                raise BrainError('ACCEPTANCE_DELIVERY_CHANGED','A manifest-bound delivery STEP changed before comparison.')
        from .recipe import verify_delivery_steps
        delivery=verify_delivery_steps(resolved,resolved_assembly)
        if (file_hash(manifest_path)!=delivery_manifest_sha256 or
                any(file_hash(path)!=entry['sha256'] for entry,path in
                    [(assembly_entry,resolved_assembly),
                     *((manifest['parts'][part_id],path) for part_id,path in resolved.items())])):
            raise BrainError('ACCEPTANCE_DELIVERY_CHANGED','A delivery STEP or manifest changed during comparison.')
        delivery['passed']=delivery.get('verdict')=='pass'
        checks.append(delivery)
        delivery_status={'verified':True,'status':'pass' if delivery['passed'] else 'fail',
                         'verdict':'pass' if delivery['passed'] else 'fail',
                         'manifest_file_sha256':delivery_manifest_sha256,
                         'manifest_digest':digest(manifest),'step_hashes':{
                             'assembly':assembly_entry['sha256'],
                             'parts':{part_id:entry['sha256'] for part_id,entry in manifest['parts'].items()}},
                         'check':delivery}
    else:
        delivery_status={'verified':False,'status':'not_requested',
                         'note':'Part-to-assembly STEP equivalence was not requested by this acceptance invocation.'}
    if file_hash(step)!=before:
        raise BrainError('ACCEPTANCE_CHANGED','Delivered STEP changed during acceptance measurement.')
    return {'case_id':spec.case_id,'original_request':spec.original_request,
            'acceptance_spec_digest':digest(spec.model_dump()),'step_sha256':before,
            'checks':checks,'geometry_acceptance':'pass' if all(c['passed'] for c in checks) else 'fail',
            'delivery_consistency':delivery_status,
            'geometry_acceptance_scope':prism_scope,
            'tolerance_interpretation':{
                'kind':'numerical_comparison_only',
                'not_design_or_manufacturing_tolerance':True,
                'original_recipe_checks_replaced':False,
                'scope':'Thresholds describe this additional numerical comparison, not permission to relax the original request or production dimensions. Source checks remain independently binding.'},
            'overall_verdict':'unknown','physical_performance_certified':False,
            'unverified_requirements':spec.unverified_requirements,
            'scope':'Reimported STEP against supplied fixed geometric criteria; no recipe trust, no independent kernel or physical certification.'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',required=True,type=Path)
    parser.add_argument('--spec-sha256',required=True,help='Expected exact bytes hash fixed before generation.')
    parser.add_argument('--step',required=True,type=Path)
    parser.add_argument('--delivery-manifest',type=Path)
    parser.add_argument('--delivery-manifest-sha256')
    parser.add_argument('--report',type=Path)
    parser.add_argument('--timeout',type=int,default=60)
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    try:
        if not 5<=args.timeout<=300:raise ValueError('Timeout must be between 5 and 300 seconds.')
        spec_path=trusted_file(args.spec.resolve(),1024*1024)
        if file_hash(spec_path)!=args.spec_sha256:
            raise BrainError('ACCEPTANCE_SPEC_CHANGED','Acceptance specification does not match the precommitted hash.')
        spec=AcceptanceSpec.model_validate(json_load(spec_path))
        if args.report and (args.report.exists() or args.report.resolve() in (spec_path,args.step.resolve())):
            raise ValueError('Report must be a new file, never an input or an existing report.')
        if bool(args.delivery_manifest) != bool(args.delivery_manifest_sha256):
            raise ValueError('Delivery manifest path and hash must be supplied together.')
        if args.worker:
            result=inspect_step(args.step,spec,args.delivery_manifest,args.delivery_manifest_sha256)
        else:
            command=[sys.executable,'-m',__name__ if __name__!='__main__' else 'cadmcp_brain.studio.acceptance',
                     '--worker','--spec',str(spec_path),'--spec-sha256',args.spec_sha256,'--step',str(args.step.resolve())]
            if args.delivery_manifest:
                command.extend(['--delivery-manifest',str(args.delivery_manifest.resolve()),
                                '--delivery-manifest-sha256',args.delivery_manifest_sha256])
            proc=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=args.timeout)
            if proc.returncode not in (0,1):
                raise BrainError('ACCEPTANCE_WORKER','Acceptance worker did not complete.',{'stderr':proc.stderr[-2000:]})
            result=json.loads(proc.stdout)
        if file_hash(spec_path)!=args.spec_sha256:
            raise BrainError('ACCEPTANCE_SPEC_CHANGED','Acceptance specification changed during measurement.')
        result['acceptance_spec_file_sha256']=args.spec_sha256
        if args.report:atomic_json(args.report,result)
        print(json.dumps(result,ensure_ascii=True))
        return 0 if result['geometry_acceptance']=='pass' else 1
    except Exception as exc:
        print(json.dumps({'error':type(exc).__name__,'message':str(exc)[:2000]}),file=sys.stderr)
        return 2


if __name__=='__main__':raise SystemExit(main())
