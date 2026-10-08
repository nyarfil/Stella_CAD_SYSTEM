"""No-model contract tests for the reference-principle proof runner."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from scripts import check_reference_design as script
from cadmcp_brain.errors import BrainError
from cadmcp_brain.req2cad.common import atomic_json,file_hash

pytest.importorskip('cadquery', reason='Oracle fixture inspection requires the actual CAD kernel.')


def test_run_root_is_new_child_of_verification(tmp_path, monkeypatch):
    monkeypatch.setattr(script, 'VERIFICATION_ROOT', tmp_path / 'verification')
    script.VERIFICATION_ROOT.mkdir()
    candidate = script.VERIFICATION_ROOT / 'fresh'
    assert script.resolve_run_root(candidate) == candidate.resolve()
    candidate.mkdir()
    with pytest.raises(ValueError, match='already exists'):
        script.resolve_run_root(candidate)
    with pytest.raises(ValueError, match='below verification'):
        script.resolve_run_root(tmp_path / 'outside')


def test_model_execution_requires_explicit_flag():
    with pytest.raises(SystemExit) as exc:
        script.main(['--run-root', str(script.VERIFICATION_ROOT / 'unused-reference-design-test')])
    assert exc.value.code == 2


def test_failure_restores_req2cad_environment_and_keeps_compact_report(tmp_path, monkeypatch):
    verification = tmp_path / 'verification'; verification.mkdir()
    monkeypatch.setattr(script, 'VERIFICATION_ROOT', verification)
    run_root = verification / 'failure'
    prior = os.environ.get('CADMCP_REQ2CAD_ROOT')
    monkeypatch.setenv('CADMCP_REQ2CAD_ROOT', 'before-test')
    def broken_init(workspace):
        os.environ['CADMCP_REQ2CAD_ROOT'] = 'changed-by-fixture'
        raise RuntimeError('controlled no-model setup failure')
    monkeypatch.setattr(script, 'init_cases', broken_init)
    assert script.main(['--execute-model', '--run-root', str(run_root)]) == 1
    report = json.loads((run_root / 'REFERENCE_DESIGN_RESULT.json').read_text('utf-8'))
    assert report['actual_model_called'] is False and report['physical_performance_certified'] is False
    assert report['error']['type'] == 'RuntimeError'
    assert os.environ['CADMCP_REQ2CAD_ROOT'] == 'before-test'
    if prior is None:
        os.environ.pop('CADMCP_REQ2CAD_ROOT', None)
    else:
        os.environ['CADMCP_REQ2CAD_ROOT'] = prior


def test_hand_authored_oracle_fixture_passes_without_a_model(tmp_path):
    import cadquery as cq
    run_root = tmp_path / 'run'; run_root.mkdir()
    atomic_json(run_root/'ORACLE_SPEC.json',script.ORACLE_SPEC)
    source = run_root / 'source'; source.mkdir()
    oracle = script._write_oracles(source)
    guide = cq.importers.importStep(str(oracle['guide'])).val()
    shaft = cq.importers.importStep(str(oracle['shaft'])).val()
    assembly = source / 'assembly.step'; cq.exporters.export(cq.Compound.makeCompound([guide, shaft]), str(assembly))
    result = script.inspection_worker(run_root, assembly, [oracle['guide'], oracle['shaft']])
    assert result['verdict'] == 'pass', result
    assert result['checks']['oracle_one_to_one_match']
    assert result['checks']['radial_clearance_0_3_mm']
    assert result['scope'].startswith('Same OCCT kernel')


def _registered_double(tmp_path,monkeypatch):
    monkeypatch.setattr(script,'VERIFICATION_ROOT',tmp_path.resolve())
    root=tmp_path/'run';folder=root/'build';folder.mkdir(parents=True)
    atomic_json(root/'ORACLE_SPEC.json',script.ORACLE_SPEC)
    files=[]
    for name in ('first.step','second.step','assembly.step'):
        path=folder/name;path.write_bytes(b'explicit test double, not CAD: '+name.encode())
        files.append(path)
    atomic_json(folder/'measurements.json',{'assembly':{'sha256':file_hash(files[2])},'outputs':{
        str(i):{'exports':{'model.step':{'relative_path':path.name,'sha256':file_hash(path)}}}
        for i,path in enumerate(files[:2])}})
    return root,{'folder':str(folder),'assembly_step':str(files[2])},files


@pytest.mark.parametrize('corruption',['empty_checks','contradictory_verdict','wrong_hash','wrong_returncode','wrong_spec'])
def test_parent_rejects_invalid_worker_claims(tmp_path,monkeypatch,corruption):
    root,build,files=_registered_double(tmp_path,monkeypatch)
    result={'checks':dict.fromkeys(('delivery_one_to_one','oracle_one_to_one_match',
                                    'zero_intersection_volume','radial_clearance_0_3_mm'),True),
            'verdict':'pass','oracle_spec':script.ORACLE_SPEC,
            'oracle_spec_sha256':file_hash(root/'ORACLE_SPEC.json'),
            'generated_step_hashes':[file_hash(p) for p in files[:2]],
            'assembly_step_sha256':file_hash(files[2])}
    if corruption=='empty_checks':result['checks']={}
    elif corruption=='contradictory_verdict':result['verdict']='fail'
    elif corruption=='wrong_hash':result['assembly_step_sha256']='0'*64
    elif corruption=='wrong_spec':result['oracle_spec']={}
    monkeypatch.setattr(script.subprocess,'run',lambda *args,**kwargs:
                        SimpleNamespace(returncode=1 if corruption=='wrong_returncode' else 0,stdout=json.dumps(result),stderr=''))
    with pytest.raises((RuntimeError,ValueError,BrainError)):
        script.inspect_fixture_build(root,build)


@pytest.mark.parametrize('variant',['correct','moved_shaft','missing_bore'])
def test_parent_runs_bounded_real_inspection_with_arbitrary_part_names(variant):
    import tempfile
    from pathlib import Path
    import cadquery as cq
    with tempfile.TemporaryDirectory(prefix='reference-worker-test-',dir=script.VERIFICATION_ROOT) as folder_name:
        root=Path(folder_name);folder=root/'build';folder.mkdir()
        atomic_json(root/'ORACLE_SPEC.json',script.ORACLE_SPEC)
        oracle=script._write_oracles(folder)
        shapes=[cq.importers.importStep(str(path)).val() for path in oracle.values()]
        if variant=='moved_shaft':
            shapes[1]=shapes[1].translate((0.4,0,0))
        elif variant=='missing_bore':
            shapes[0]=shapes[0].fuse(cq.Solid.makeCylinder(2,12,cq.Vector(12,9,0)))
        for path,shape in zip(oracle.values(),shapes):
            cq.exporters.export(shape,str(path))
        assembly=folder/'assembly.step'
        cq.exporters.export(cq.Compound.makeCompound(shapes),str(assembly))
        atomic_json(folder/'measurements.json',{
            'assembly':{'sha256':file_hash(assembly)},
            'outputs':{f'free_name_{i}':{'exports':{'model.step':{
                'relative_path':path.name,'sha256':file_hash(path)}}}
                for i,path in enumerate(reversed(list(oracle.values())))}})
        result=script.inspect_fixture_build(root,{'folder':str(folder),'assembly_step':str(assembly)})
        assert result['verdict']==('pass' if variant=='correct' else 'fail')
        assert result['worker_returncode']==(0 if variant=='correct' else 1)
        assert result['checks']['delivery_one_to_one'] is True
        assert result['checks']['oracle_one_to_one_match'] is (variant=='correct')
        assert result['pre_inspection_hashes']==result['post_inspection_hashes']


def test_external_assembly_is_rejected_before_launch(tmp_path,monkeypatch):
    root,build,_=_registered_double(tmp_path,monkeypatch)
    external=tmp_path/'outside.step';external.write_bytes(b'protected external fixture')
    build['assembly_step']=str(external)
    def forbidden(*args,**kwargs):
        raise AssertionError('Worker must not start for out-of-scope inputs')
    monkeypatch.setattr(script.subprocess,'run',forbidden)
    with pytest.raises((RuntimeError,ValueError,BrainError)):
        script.inspect_fixture_build(root,build)
