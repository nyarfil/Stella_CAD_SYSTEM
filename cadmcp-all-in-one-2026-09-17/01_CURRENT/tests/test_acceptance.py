"""Fixed requirements detect wrong delivered geometry without reading any Recipe."""
import copy
import json
import subprocess
import sys

import pytest
from pydantic import ValidationError

cq=pytest.importorskip('cadquery',reason='Actual STEP acceptance requires the optional CAD kernel.')

from cadmcp_brain.studio.acceptance import AcceptanceSpec, inspect_step
from cadmcp_brain.req2cad.common import file_hash


def spec_data():
    return {'case_id':'original_L_plate','original_request':'L plate: 20 x 14 x 2 mm with a 10 x 8 mm upper-right notch.',
            'expected_solids':1,'lower_mm':[0.,0.,0.],'upper_mm':[20.,14.,2.],
            'coordinate_tolerance_mm':1e-5,'volume_mm3':400.,'volume_tolerance_mm3':1e-5,
            'expected_prism':{'points_mm':[[0.,0.],[20.,0.],[20.,6.],[10.,6.],[10.,14.],[0.,14.]],
                              'z_min_mm':0.,'z_max_mm':2.,'max_symmetric_difference_mm3':1e-5},
            'regions':[{'id':'notch','lower_mm':[11.,7.,.1],'upper_mm':[19.,13.,1.9],'min_fill':0.,'max_fill':1e-8},
                       {'id':'left_arm','lower_mm':[1.,7.,.1],'upper_mm':[9.,13.,1.9],'min_fill':.99999999,'max_fill':1.}],
            'unverified_requirements':['Material strength, fatigue and actual production remain untested.']}


def delivered(tmp_path, *, wrong=False, displacement=0., vertex_shift=False, bump=False):
    points=([(0,0),(20,0),(20,14),(10,14),(10,6),(0,6)] if wrong else
            [(0,0),(20,0),(20,6),(10,6),(10,14),(0,14)])
    if vertex_shift:
        points=[(0,0),(20,0),(20,6),(10,6.01),(10,14),(0,14)]
    shape=cq.Workplane('XY').polyline(points).close().extrude(2).val().translate((displacement,0,0))
    if bump:
        shape=shape.fuse(cq.Solid.makeBox(.01,.01,2,cq.Vector(10.,7.,0.)))
    target=tmp_path/'delivery.step'
    cq.exporters.export(shape,str(target))
    return target


def test_correct_geometry_is_not_physical_certification(tmp_path):
    path=delivered(tmp_path);before=file_hash(path)
    report=inspect_step(path,AcceptanceSpec.model_validate(spec_data()))
    assert report['geometry_acceptance']=='pass'
    assert report['overall_verdict']=='unknown' and not report['physical_performance_certified']
    assert report['tolerance_interpretation']['kind']=='numerical_comparison_only'
    assert report['tolerance_interpretation']['not_design_or_manufacturing_tolerance']
    assert not report['tolerance_interpretation']['original_recipe_checks_replaced']
    assert file_hash(path)==before==report['step_sha256']


def test_optional_prism_omission_is_explicitly_unverified(tmp_path):
    data=spec_data();data.pop('expected_prism')
    report=inspect_step(delivered(tmp_path),AcceptanceSpec.model_validate(data))
    prism=next(c for c in report['checks'] if c['id']=='expected_prism')
    assert report['geometry_acceptance_scope']=='not_verified_expected_prism_not_specified'
    assert prism['verified'] is False and prism['status']=='not_specified'


def test_same_volume_and_bbox_but_wrong_shape_fails(tmp_path):
    report=inspect_step(delivered(tmp_path,wrong=True),AcceptanceSpec.model_validate(spec_data()))
    checks={c['id']:c for c in report['checks']}
    assert checks['positioned_envelope']['passed'] and checks['volume']['passed']
    assert not checks['notch']['passed'] and not checks['left_arm']['passed']
    assert not checks['expected_prism']['passed']
    assert report['geometry_acceptance']=='fail'


def test_small_protrusion_over_section_tolerance_fails(tmp_path):
    report=inspect_step(delivered(tmp_path,bump=True),AcceptanceSpec.model_validate(spec_data()))
    checks={c['id']:c for c in report['checks']}
    assert not checks['expected_prism']['passed']
    assert checks['expected_prism']['actual_symmetric_difference_mm3']>1e-5
    assert report['geometry_acceptance']=='fail'


def test_shifted_section_vertex_fails_even_when_other_checks_are_close(tmp_path):
    report=inspect_step(delivered(tmp_path,vertex_shift=True),AcceptanceSpec.model_validate(spec_data()))
    checks={c['id']:c for c in report['checks']}
    assert not checks['expected_prism']['passed']
    assert report['geometry_acceptance']=='fail'


def test_correct_size_at_wrong_position_fails(tmp_path):
    report=inspect_step(delivered(tmp_path,displacement=3.),AcceptanceSpec.model_validate(spec_data()))
    assert not next(c for c in report['checks'] if c['id']=='positioned_envelope')['passed']


@pytest.mark.parametrize('mutation',['nan','reversed','duplicate','blank','prism_nan','prism_too_many','prism_duplicate','prism_self_intersect'])
def test_invalid_acceptance_criteria_are_not_silently_ignored(mutation):
    data=spec_data()
    if mutation=='nan':data['volume_mm3']=float('nan')
    if mutation=='reversed':data['regions'][0]['upper_mm'][0]=0.
    if mutation=='duplicate':data['regions'].append(copy.deepcopy(data['regions'][0]))
    if mutation=='blank':data['unverified_requirements']=[' ']
    if mutation=='prism_nan':data['expected_prism']['z_max_mm']=float('nan')
    if mutation=='prism_too_many':data['expected_prism']['points_mm']=[[float(i),0.] for i in range(65)]
    if mutation=='prism_duplicate':data['expected_prism']['points_mm'][2]=data['expected_prism']['points_mm'][1]
    if mutation=='prism_self_intersect':data['expected_prism']['points_mm']=[[0.,0.],[20.,14.],[20.,0.],[0.,14.]]
    with pytest.raises(ValidationError):AcceptanceSpec.model_validate(data)


def test_cli_precommitted_spec_hash_and_new_report(tmp_path):
    step=delivered(tmp_path);spec=tmp_path/'acceptance.json';report=tmp_path/'report.json'
    spec.write_text(json.dumps(spec_data()),encoding='utf-8')
    command=[sys.executable,'-m','cadmcp_brain.studio.acceptance','--spec',str(spec),
             '--spec-sha256',file_hash(spec),'--step',str(step),'--report',str(report)]
    result=subprocess.run(command,capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stderr
    assert json.loads(report.read_text())['geometry_acceptance']=='pass'
    before=file_hash(report)
    retry=subprocess.run(command,capture_output=True,text=True,timeout=60)
    assert retry.returncode==2 and file_hash(report)==before
    data=spec_data();data['volume_mm3']=560.
    spec.write_text(json.dumps(data),encoding='utf-8')
    changed=subprocess.run(command[:-2],capture_output=True,text=True,timeout=60)
    assert changed.returncode==2 and 'precommitted hash' in changed.stderr
