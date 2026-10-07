"""Register and verify a ClassCAD probe through Stella, in a fresh workspace."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'cadmcp-all-in-one-2026-09-17/01_CURRENT'
sys.path.insert(0, str(SOURCE))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run_directory', type=Path)
    args = parser.parse_args()
    run = args.run_directory.resolve()
    source_step = run / 'box.step'
    from cadmcp_brain.req2cad.common import file_hash
    from cadmcp_brain.studio.acceptance import AcceptanceSpec, inspect_step
    from cadmcp_brain.api import Tools
    from cadmcp_brain.engine import Brain
    before = file_hash(source_step)
    workspace = run / ('stella-' + uuid.uuid4().hex[:8])
    (workspace / 'imports').mkdir(parents=True)
    shutil.copyfile(source_step, workspace / 'imports/box.step')
    os.environ['CADMCP_REQ2CAD_ROOT'] = str(workspace / 'knowledge/req2cad')
    tools = Tools(Brain(workspace))
    request = 'ClassCAD integration probe: one rectangular solid 20 x 10 x 5 mm, volume 1000 mm3. Physical performance remains untested.'
    tools.brain_open('classcad-probe', request)
    tools.brain_import_step('classcad-probe', 0, 'ClassCADBox', 'imports/box.step', purpose='reference')
    recipe = {
        'title': 'Preserve externally generated ClassCAD box', 'original_request': request,
        'functions': {'Keep': 'Retain and measure the externally generated box.'},
        'operations': [{'id': 'box', 'op': 'project_step', 'function_id': 'Keep',
                        'reason': 'Preserve the exact registered ClassCAD solid for verification.',
                        'artifact_id': 'ClassCADBox', 'sha256': before, 'role': 'protected_hardware',
                        'unit_basis': 'ClassCAD probe explicitly requested dimensions in millimetres.'}],
        'outputs': [{'part_id': 'box', 'node': 'box'}],
        'dimension_checks': [{'id': 'size_' + axis, 'part': 'box', 'kind': 'bbox',
                              'axis': axis, 'nominal_mm': size, 'tolerance_mm': 1e-6}
                             for axis, size in zip('xyz', [20., 10., 5.])],
        'unverified_requirements': ['Strength, material, fatigue and real production are not tested.'],
    }
    built = tools.brain_studio_build('classcad-probe', 1, recipe, timeout_seconds=90)
    spec = AcceptanceSpec.model_validate({
        'case_id': 'classcad_box', 'original_request': request, 'expected_solids': 1,
        'lower_mm': [0., 0., 0.], 'upper_mm': [20., 10., 5.],
        'coordinate_tolerance_mm': 1e-6, 'volume_mm3': 1000., 'volume_tolerance_mm3': 1e-5,
        'expected_prism': {'points_mm': [[0., 0.], [20., 0.], [20., 10.], [0., 10.]],
                           'z_min_mm': 0., 'z_max_mm': 5., 'max_symmetric_difference_mm3': 1e-5},
        'unverified_requirements': ['No physical performance or autonomous-design benchmark.'],
    })
    independent = inspect_step(source_step, spec)
    handoff = tools.brain_fusion_handoff('classcad-probe', 1, built['subject_digest'])
    result = {'generator': 'ClassCAD WASM 21.2.0 / @classcad/mcp 0.2.0',
              'source_step': str(source_step), 'source_sha256': before,
              'source_unchanged': file_hash(source_step) == before,
              'workspace': str(workspace), 'geometry': built['geometry_checks_verdict'],
              'independent_acceptance': independent,
              'subject_digest': built['subject_digest'], 'assembly_step': built['assembly_step'],
              'fusion_handoff': handoff,
              'review': 'not_run', 'physical_performance': 'unknown',
              'autonomous_design_benchmark': False}
    target = workspace / 'integration-result.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    passed = (result['source_unchanged'] and result['geometry'] == 'pass'
              and independent['geometry_acceptance'] == 'pass')
    print(json.dumps({'passed': passed, 'result': str(target),
                      'geometry': result['geometry'], 'acceptance': independent['geometry_acceptance']}))
    return 0 if passed else 1

if __name__ == '__main__':
    raise SystemExit(main())
