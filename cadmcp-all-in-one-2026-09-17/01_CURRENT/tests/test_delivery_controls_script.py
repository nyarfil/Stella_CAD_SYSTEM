"""Actual-kernel checks for the isolated delivery-control development probe."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip('cadquery', reason='Delivery controls require the actual CAD kernel.')

from scripts import check_delivery_controls as script


def test_worker_measures_positive_and_all_negative_controls(tmp_path):
    run_root = tmp_path / 'fresh-run'
    run_root.mkdir()
    result = script.run_worker(run_root)
    result, errors = script._validate_worker_result(run_root, result)
    observed = {item['case_id']: item['actual_verdict'] for item in result['cases']}
    assert not errors and result['all_expected_verdicts_observed']
    assert observed == {
        'positive_exact': 'pass', 'same_bbox_volume_different_shape': 'fail',
        'moved_solid': 'fail', 'missing_solid': 'fail', 'extra_solid': 'fail',
        'duplicate_solid': 'fail',
    }
    for case in result['cases']:
        assert case['hand_authored_synthetic_fixture']
        assert len(case['input_step_hashes']['assembly']) == 64
        assert case['input_step_hashes']['parts']
    same = next(case for case in result['cases'] if case['case_id'] == 'same_bbox_volume_different_shape')
    assert same['same_bbox_volume_precondition']['bounds_match']
    assert same['same_bbox_volume_precondition']['volume_match']


def test_parent_rejects_existing_runroot_before_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(script, 'ROOT', tmp_path)
    run_root = tmp_path / 'verification' / 'already-there'
    run_root.mkdir(parents=True)
    monkeypatch.setattr(script.subprocess, 'run', lambda *a, **k: pytest.fail('worker must not start'))
    with pytest.raises(ValueError, match='already exists'):
        script.main(['--run-root', str(run_root)])


def test_parent_uses_bounded_worker_and_writes_scope_report(tmp_path, monkeypatch):
    monkeypatch.setattr(script, 'ROOT', tmp_path)
    verification = tmp_path / 'verification'
    verification.mkdir()
    for path in (tmp_path / 'cadmcp_brain/studio/recipe.py', tmp_path / 'cadmcp_brain/studio/measurement.py'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# evaluator double', encoding='utf-8')
    run_root = verification / 'fresh'
    def run(command, **kwargs):
        assert '--worker' in command and kwargs['timeout'] == 90 and kwargs['check'] is False
        worker = script.run_worker(run_root)
        return SimpleNamespace(stdout=json.dumps(worker), returncode=0, stderr='')
    monkeypatch.setattr(script.subprocess, 'run', run)
    assert script.main(['--run-root', str(run_root)]) == 0
    report = json.loads((run_root / 'DELIVERY_CONTROLS_REPORT.json').read_text('utf-8'))
    assert report['model_calls'] == 0 and report['physical_performance_certified'] is False
    assert report['formal_subject_linked'] is False
    assert 'same CadQuery/OCCT tool creates and measures' in report['scope']


@pytest.mark.parametrize('mutation', ['empty', 'wrong_verdict', 'changed_hash','empty_parts','malformed_id'])
def test_parent_reports_rejected_worker_evidence_without_false_success(tmp_path, monkeypatch, mutation):
    monkeypatch.setattr(script, 'ROOT', tmp_path)
    verification = tmp_path / 'verification'; verification.mkdir()
    for path in (tmp_path / 'cadmcp_brain/studio/recipe.py', tmp_path / 'cadmcp_brain/studio/measurement.py'):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text('# evaluator double', encoding='utf-8')
    run_root = verification / mutation
    def run(*args, **kwargs):
        result = {'cases': []} if mutation == 'empty' else script.run_worker(run_root)
        if mutation == 'wrong_verdict': result['cases'][0]['actual_verdict'] = 'fail'
        if mutation=='empty_parts':
            result['cases'][0]['input_step_paths']['parts']={}
            result['cases'][0]['input_step_hashes']['parts']={}
        if mutation=='malformed_id':result['cases'][0]['case_id']=[]
        if mutation == 'changed_hash':
            assembly = Path(result['cases'][0]['input_step_paths']['assembly'])
            assembly.write_bytes(assembly.read_bytes() + b'changed')
        return SimpleNamespace(stdout=json.dumps(result), returncode=1, stderr='expected negative worker outcome')
    monkeypatch.setattr(script.subprocess, 'run', run)
    assert script.main(['--run-root', str(run_root)]) == 1
    report = json.loads((run_root / 'DELIVERY_CONTROLS_REPORT.json').read_text('utf-8'))
    assert report['success'] is False and report['worker_contract_valid'] is False
    assert report['validation_errors']


@pytest.mark.parametrize('failure',['crash','timeout','invalid_json'])
def test_worker_execution_failures_leave_failed_records(tmp_path,monkeypatch,failure):
    monkeypatch.setattr(script,'ROOT',tmp_path)
    evaluator=tmp_path/'cadmcp_brain/studio'
    evaluator.mkdir(parents=True)
    for name in ('recipe.py','measurement.py'):
        (evaluator/name).write_text('# evaluator double',encoding='utf-8')
    target=tmp_path/'verification'/failure
    def run(*args,**kwargs):
        if failure=='timeout':raise subprocess.TimeoutExpired('isolated worker',90)
        return SimpleNamespace(returncode=2 if failure=='crash' else 0,
                               stdout='invalid JSON',stderr='synthetic failure')
    monkeypatch.setattr(script.subprocess,'run',run)
    assert script.main(['--run-root',str(target)])==1
    record=json.loads((target/'failure.json').read_text('utf-8'))
    assert record['success'] is False and record['model_calls']==0
    assert not (target/'DELIVERY_CONTROLS_REPORT.json').exists()
