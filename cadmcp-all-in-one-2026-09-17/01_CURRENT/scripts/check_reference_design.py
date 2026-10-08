"""Bounded real-reference to original-geometry proof runner.

The four public catalog records are an explicitly selected isolation fixture,
not a search-quality benchmark or a complete catalog.  Their measured hashes
are retained as provenance while the generated recipe may use them only as
principle references; their shapes must not be imported into the new fixture.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cadmcp_brain.errors import BrainError
from cadmcp_brain.req2cad.common import atomic_json, file_hash, json_load
from cadmcp_brain.studio.autopilot import Autopilot
from cadmcp_brain.studio.provider import CodexProvider
from cadmcp_brain.studio.runtime import ROLES
from scripts.demo_real_references import init_cases


REQUEST = (
    '公開カタログの実測CADは円筒案内・取付フランジ等の構造原理だけを参考にする。開発用の'
    'ソフトウェア幾何fixtureとして、外部形状を流用しない新規の2独立solidをmmで設計する。'
    '案内部品はXY=[0,24]x[0,18], Z=[0,3]の角フランジに、中心(12,9)、外R4のスリーブ'
    'Z=[3,12]を結合し、同中心・内R2の貫通穴Z=[0,12]を設ける。軸は中心(12,9)、R1.7、'
    'Z=[-2,14]とする。案内部品体積は1296+96pi mm3、軸体積は46.24pi mm3、'
    '体積干渉なし、径方向隙間0.3 mmを満たす。公開参考の原単位をmmと断定せず、'
    'reference_usesにはprinciple_referenceを記録する。これは実案件を触らない開発fixtureであり、'
    '実マウス、PCB、材料、製造、疲労、実機組立は未検証として残す。'
)
VERIFICATION_ROOT = (ROOT / 'verification').resolve()
DEFAULT_RUN_ROOT = VERIFICATION_ROOT / 'reference-design-20260920'
PROJECT_PREFIX = 'reference-principle-fixture'
ORACLE_SPEC = {
    'schema_version': 1, 'units': 'mm', 'guide_flange_xy_mm': [0.0, 24.0, 0.0, 18.0],
    'guide_flange_z_mm': [0.0, 3.0], 'center_xy_mm': [12.0, 9.0],
    'guide_outer_radius_mm': 4.0, 'guide_sleeve_z_mm': [3.0, 12.0],
    'guide_inner_radius_mm': 2.0, 'guide_bore_z_mm': [0.0, 12.0],
    'shaft_radius_mm': 1.7, 'shaft_z_mm': [-2.0, 14.0],
    'guide_volume_mm3_expression': '1296 + 96*pi', 'shaft_volume_mm3_expression': '46.24*pi',
    'radial_clearance_mm': 0.3, 'independent_solids': 2, 'geometry_tolerance_mm': 1e-6,
}
INSPECTION_CHECK_IDS = {'delivery_one_to_one', 'oracle_one_to_one_match',
                        'zero_intersection_volume', 'radial_clearance_0_3_mm'}


def resolve_run_root(value: Path) -> Path:
    candidate = Path(value).resolve()
    if not candidate.is_relative_to(VERIFICATION_ROOT) or candidate == VERIFICATION_ROOT:
        raise ValueError('run-root must be a new child directory below verification.')
    if candidate.exists():
        raise ValueError('run-root already exists; evidence is immutable and is never overwritten.')
    return candidate


def _receipts(provider):
    if provider is None:
        return []
    rows = []
    for path in sorted(provider.root.glob('*/receipt.json')):
        row = json_load(path)
        rows.append({'path': str(path.resolve()), 'sha256': file_hash(path), **row})
    return rows


def _review_responses(provider):
    if provider is None:
        return []
    return [json_load(path) for path in sorted(provider.root.glob('*/normalized-response.json'))
            if json_load(path).get('role') in ROLES]


def _result_build(state: dict) -> dict:
    if state.get('build'):
        return state['build']
    if state.get('last_failure', {}).get('build'):
        return state['last_failure']['build']
    raise RuntimeError('Autopilot did not retain a completed build receipt.')


def _write_oracles(folder: Path) -> dict:
    """Create the fixed predeclared geometry oracle in the bounded worker only."""
    import cadquery as cq
    _assert_oracle_spec_consistency()
    flange = cq.Solid.makeBox(24, 18, 3, cq.Vector(0, 0, 0))
    sleeve = cq.Solid.makeCylinder(4, 9, cq.Vector(12, 9, 3), cq.Vector(0, 0, 1))
    bore = cq.Solid.makeCylinder(2, 12, cq.Vector(12, 9, 0), cq.Vector(0, 0, 1))
    guide = flange.fuse(sleeve).cut(bore)
    shaft = cq.Solid.makeCylinder(1.7, 16, cq.Vector(12, 9, -2), cq.Vector(0, 0, 1))
    paths = {'guide': folder / 'oracle-guide.step', 'shaft': folder / 'oracle-shaft.step'}
    cq.exporters.export(guide, str(paths['guide'])); cq.exporters.export(shaft, str(paths['shaft']))
    return paths


def inspection_worker(run_root: Path, assembly: Path, part_steps: list[Path]) -> dict:
    """Bounded OCCT oracle comparison; it is deliberately not an independent kernel."""
    import cadquery as cq
    from cadmcp_brain.studio.recipe import pair_clearance, verify_delivery_steps
    run_root = run_root.resolve(); assembly = assembly.resolve(); part_steps = [path.resolve() for path in part_steps]
    if (not run_root.is_dir() or not assembly.is_relative_to(run_root) or
            any(not path.is_relative_to(run_root) for path in part_steps)):
        raise ValueError('Inspection inputs must be existing files below the verification run-root.')
    if len(part_steps) != 2 or len(set(part_steps)) != 2:
        raise ValueError('Exactly two distinct generated part STEP paths are required.')
    work = run_root / 'independent-inspection'; work.mkdir(exist_ok=False)
    oracle = _write_oracles(work)
    # First prove generated exports and assembly are one-to-one, then establish
    # a bijection against the two predeclared oracle solids without assuming IDs.
    delivery = verify_delivery_steps({str(index): path for index, path in enumerate(part_steps)}, assembly)
    match = {}
    for label, oracle_path in oracle.items():
        match[label] = []
        for index, candidate in enumerate(part_steps):
            value = verify_delivery_steps({'oracle': oracle_path}, candidate)
            if value['verdict'] == 'pass':
                match[label].append(index)
    guide_indices, shaft_indices = match['guide'], match['shaft']
    one_to_one = len(guide_indices) == len(shaft_indices) == 1 and guide_indices[0] != shaft_indices[0]
    overlap = distance = None
    if one_to_one:
        guide = cq.importers.importStep(str(part_steps[guide_indices[0]])).val()
        shaft = cq.importers.importStep(str(part_steps[shaft_indices[0]])).val()
        distance, overlap = pair_clearance(guide, shaft)
    checks = {
        'delivery_one_to_one': delivery['verdict'] == 'pass', 'oracle_one_to_one_match': one_to_one,
        'zero_intersection_volume': overlap is not None and overlap <= 1e-7,
        'radial_clearance_0_3_mm': distance is not None and abs(distance - 0.3) <= 1e-6,
    }
    return {'oracle_spec': ORACLE_SPEC, 'oracle_spec_sha256': file_hash(run_root / 'ORACLE_SPEC.json'),
            'oracle_step_hashes': {key: file_hash(path) for key, path in oracle.items()},
            'generated_step_hashes': [file_hash(path) for path in part_steps], 'assembly_step_sha256': file_hash(assembly),
            'delivery_check': delivery, 'oracle_matches': match, 'distance_mm': distance, 'overlap_mm3': overlap,
            'checks': checks, 'verdict': 'pass' if all(checks.values()) else 'fail',
            'scope': 'Same OCCT kernel creates and measures the oracle; this is fixture-pipeline geometry evidence, not independent-kernel validation or proof of principle understanding.'}


def inspect_fixture_build(run_root: Path, build: dict) -> dict:
    """Parent only launches a 90-second worker; Boolean work is never done here."""
    run_root = run_root.resolve(); folder = Path(build['folder']).resolve()
    if not folder.is_relative_to(run_root):
        raise RuntimeError('Build folder escapes the verification run-root.')
    measurement_path = folder / 'measurements.json'
    if not measurement_path.is_file():
        raise RuntimeError('Build measurements are missing.')
    measurement = json_load(measurement_path)
    part_steps = [folder / value['exports']['model.step']['relative_path'] for _, value in sorted(measurement.get('outputs', {}).items())]
    assembly = Path(build['assembly_step']).resolve()
    if (not assembly.is_relative_to(run_root) or any(not path.resolve().is_relative_to(run_root) for path in part_steps) or
            len(part_steps) != 2 or not assembly.is_file() or any(not path.is_file() for path in part_steps)):
        raise RuntimeError('Fixture must have exactly two STEP exports below its verification run-root.')
    registered = {'assembly': measurement.get('assembly', {}).get('sha256'),
                  'parts': [value['exports']['model.step'].get('sha256') for _, value in sorted(measurement.get('outputs', {}).items())]}
    before = {'assembly': file_hash(assembly), 'parts': [file_hash(path) for path in part_steps]}
    if registered['assembly'] != before['assembly'] or registered['parts'] != before['parts']:
        raise RuntimeError('Generated STEP bytes do not match registered export hashes before inspection.')
    oracle_path = run_root / 'ORACLE_SPEC.json'
    if not oracle_path.is_file() or json_load(oracle_path) != ORACLE_SPEC:
        raise RuntimeError('Predeclared oracle specification is missing or changed before inspection.')
    oracle_hash_before_inspection = file_hash(oracle_path)
    worker_args = []
    for path in part_steps:
        worker_args.extend(['--part-step', str(path)])
    try:
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--inspection-worker',
                               '--run-root', str(run_root), '--assembly-step', str(assembly),
                               *worker_args], capture_output=True, text=True, encoding='utf-8', timeout=90, check=False)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError(f'Inspection worker did not complete: {type(exc).__name__}') from exc
    if proc.returncode not in (0, 1):
        raise RuntimeError(f'Inspection worker crashed with returncode {proc.returncode}: {proc.stderr[-1000:]}')
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError('Inspection worker emitted invalid JSON.') from exc
    checks = result.get('checks')
    if (result.get('verdict') not in ('pass', 'fail') or proc.returncode != (0 if result.get('verdict') == 'pass' else 1) or
            not isinstance(checks, dict) or set(checks) != INSPECTION_CHECK_IDS or
            any(type(value) is not bool for value in checks.values()) or result['verdict'] != ('pass' if all(checks.values()) else 'fail')):
        raise RuntimeError('Inspection worker did not return a bounded verdict.')
    if (result.get('assembly_step_sha256') != before['assembly'] or result.get('generated_step_hashes') != before['parts'] or
            result.get('oracle_spec_sha256') != oracle_hash_before_inspection or result.get('oracle_spec') != ORACLE_SPEC):
        raise RuntimeError('Inspection worker evidence is not bound to pre-inspection STEP/spec hashes.')
    after = {'assembly': file_hash(assembly), 'parts': [file_hash(path) for path in part_steps]}
    if after != before or file_hash(oracle_path) != oracle_hash_before_inspection or json_load(oracle_path) != ORACLE_SPEC:
        raise RuntimeError('Generated STEP evidence changed during inspection.')
    result.update(registered_export_hashes=registered, pre_inspection_hashes=before,
                  post_inspection_hashes=after, oracle_spec_sha256_pre_inspection=oracle_hash_before_inspection,
                  oracle_spec_sha256_post_inspection=file_hash(oracle_path), worker_returncode=proc.returncode)
    return result


def _execution_checks(provider, receipts, reviews, review_receipts):
    return {
        'model_call_budget_respected': provider.calls <= 16,
        'all_call_receipts_saved': len(receipts) == provider.calls and all(row.get('response_received') for row in receipts),
        'five_roles_two_rounds_called': len(reviews) == 10 and all(sum(row.get('role') == role for row in reviews) == 2 for role in ROLES),
        'five_roles_have_rounds_one_and_two': len(reviews) == 10 and all(
            sorted(row.get('discussion_round') for row in reviews if row.get('role') == role) == [1, 2] for role in ROLES),
        'ten_review_submissions_saved': len(review_receipts) == 10,
    }


def _reference_summary(measured: dict, source_checks: list[dict]) -> list[dict]:
    source_by_uid = {row['uid']: row for row in source_checks}
    return [{'uid': uid, 'evidence_digest': value['evidence_digest'],
             'step_sha256': value['geometry']['exports']['model.step']['sha256'],
             'source_sha256_verified': source_by_uid[uid]['sha256_verified'],
             'git_blob_verified': source_by_uid[uid]['git_blob_verified']}
            for uid, value in sorted(measured.items())]


def _snapshot_reference_steps(measured: dict) -> dict:
    """Bind all four selected materialized STEP files before and after model work."""
    result = {}
    for uid, value in measured.items():
        export = value['geometry']['exports']['model.step']; path = Path(export['absolute_path']).resolve()
        if not path.is_file() or file_hash(path) != export['sha256']:
            raise RuntimeError(f'Materialized public reference is not hash-stable: {uid}')
        result[uid] = {'path': str(path), 'sha256': export['sha256']}
    if len(result) != 4:
        raise RuntimeError('Exactly four selected public reference STEP files are required.')
    return result


def _assert_oracle_spec_consistency() -> None:
    expected = {'guide_flange_xy_mm': [0.0, 24.0, 0.0, 18.0], 'guide_flange_z_mm': [0.0, 3.0],
                'center_xy_mm': [12.0, 9.0], 'guide_outer_radius_mm': 4.0,
                'guide_sleeve_z_mm': [3.0, 12.0], 'guide_inner_radius_mm': 2.0,
                'guide_bore_z_mm': [0.0, 12.0], 'shaft_radius_mm': 1.7,
                'shaft_z_mm': [-2.0, 14.0], 'radial_clearance_mm': 0.3,
                'geometry_tolerance_mm': 1e-6, 'independent_solids': 2,
                'guide_volume_mm3_expression': '1296 + 96*pi', 'shaft_volume_mm3_expression': '46.24*pi'}
    if any(ORACLE_SPEC[key] != value for key, value in expected.items()):
        raise RuntimeError('ORACLE_SPEC no longer matches fixed worker construction dimensions.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inspection-worker', action='store_true')
    parser.add_argument('--assembly-step', type=Path)
    parser.add_argument('--part-step', type=Path, action='append', default=[])
    parser.add_argument('--execute-model', action='store_true', help='Authorize one bounded real-model run.')
    parser.add_argument('--run-root', type=Path, default=DEFAULT_RUN_ROOT)
    args = parser.parse_args(argv)
    if args.inspection_worker:
        if args.assembly_step is None:
            parser.error('--inspection-worker requires --assembly-step.')
        if (not args.run_root.resolve().is_relative_to(VERIFICATION_ROOT) or
                args.run_root.resolve() == VERIFICATION_ROOT):
            parser.error('inspection worker run-root must stay under verification.')
        result = inspection_worker(args.run_root.resolve(), args.assembly_step.resolve(), [path.resolve() for path in args.part_step])
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['verdict'] == 'pass' else 1
    if not args.execute_model:
        parser.error('This runner performs an authenticated model run; --execute-model is required.')
    try:
        run_root = resolve_run_root(args.run_root)
    except ValueError as exc:
        parser.error(str(exc))
    run_root.mkdir(parents=True)
    request_path = run_root / 'REQUEST.txt'; request_path.write_text(REQUEST, encoding='utf-8')
    oracle_path = run_root / 'ORACLE_SPEC.json'; atomic_json(oracle_path, ORACLE_SPEC)
    request_hash_before, oracle_hash_before = file_hash(request_path), file_hash(oracle_path)
    evaluator_paths = [Path(__file__).resolve(), ROOT / 'cadmcp_brain/studio/recipe.py',
                       ROOT / 'cadmcp_brain/studio/measurement.py',
                       ROOT / 'cadmcp_brain/studio/autopilot.py']
    evaluator_hashes_before = {str(path): file_hash(path) for path in evaluator_paths}
    previous_req2cad_root = os.environ.get('CADMCP_REQ2CAD_ROOT')
    provider = None
    try:
        tools, catalog, measured, source_checks = init_cases(run_root / 'public-cases')
        references_before = _snapshot_reference_steps(measured)
        project_id = PROJECT_PREFIX + '-' + uuid.uuid4().hex[:8]
        opened = tools.brain_open(project_id, REQUEST)
        provider = CodexProvider(run_root / 'calls', model='gpt-5.6-sol', max_calls=16,
                                 timeout_seconds=180, evidence_root=run_root)
        state = Autopilot(tools, provider, run_root / 'autopilot', search_mode='lexical', max_reference_builds=4,
                          design_route='reference_required', max_repairs=0, max_replans=1, review_workers=3, debate_rounds=2).run(project_id)
        build = _result_build(state); recipe_path = Path(build['recipe_path']).resolve(); recipe = json_load(recipe_path)
        independent = inspect_fixture_build(run_root, build)
        receipts, reviews = _receipts(provider), _review_responses(provider)
        review_receipts = state.get('review_receipts', [])
        status = state.get('review_status') or state.get('last_failure', {}).get('review_status') or {}
        recipe_checks = {
            'request_exact': recipe.get('original_request') == REQUEST and request_path.read_text('utf-8') == REQUEST,
            'new_geometry_only': not any(node.get('op') in ('reference', 'project_step') for node in recipe.get('operations', [])),
            'principle_reference_recorded': bool(recipe.get('reference_uses')) and
                all(use.get('use') == 'principle_reference' for use in recipe.get('reference_uses', [])),
            'physical_unknown_retained': any(any(word in item.casefold() for word in
                ('material', 'manufactur', 'fatigue', 'pcb', '材料', '製造', '疲労', '実機')) for item in recipe.get('unverified_requirements', [])),
        }
        execution = _execution_checks(provider, receipts, reviews, review_receipts)
        references_after = _snapshot_reference_steps(measured)
        evaluator_hashes_after = {str(path): file_hash(path) for path in evaluator_paths}
        integrity = {
            'request_hash_unchanged': request_hash_before == file_hash(request_path),
            'oracle_spec_hash_unchanged': oracle_hash_before == file_hash(oracle_path) and json_load(oracle_path) == ORACLE_SPEC,
            'reference_step_hashes_unchanged': references_before == references_after,
            'evaluator_hashes_unchanged': evaluator_hashes_before == evaluator_hashes_after,
        }
        owner_ready = state.get('phase') == 'prototype_ready_for_owner_review' and bool(status.get('discussion_ready_for_owner'))
        completed = (bool(independent['checks']) and all(independent['checks'].values()) and
                     all(recipe_checks.values()) and all(execution.values()) and all(integrity.values()))
        report = {
            'proof_passed': completed and owner_ready, 'execution_completed': completed,
            'acceptance_status': 'ready_for_owner_review' if owner_ready else 'not_accepted',
            'overall_verdict': 'unknown' if owner_ready else 'not_accepted', 'physical_performance_certified': False,
            'actual_model_called': provider.calls > 0, 'model': 'gpt-5.6-sol', 'model_calls': provider.calls,
            'request': REQUEST, 'request_sha256': file_hash(request_path), 'request_sha256_before_model': request_hash_before,
            'project_open_receipt': opened, 'oracle_spec_path': str(oracle_path.resolve()),
            'oracle_spec_sha256': file_hash(oracle_path), 'oracle_spec_sha256_before_model': oracle_hash_before,
            'reference_materialization': _reference_summary(measured, source_checks), 'public_cases_count': 4,
            'search_quality_benchmark': False, 'full_catalog_evaluated': False,
            'catalog_status': catalog.status(), 'search_mode': 'lexical', 'max_reference_builds': 4,
            'autopilot_state_path': str((run_root / 'autopilot/run-state.json').resolve()),
            'recipe_path': str(recipe_path), 'recipe_sha256': file_hash(recipe_path), 'recipe_checks': recipe_checks,
            'independent_step_inspection': independent, 'review_status': status, 'execution_checks': execution,
            'integrity_checks': integrity, 'reference_step_hashes_before_model': references_before,
            'reference_step_hashes_after_model': references_after,
            'evaluator_file_hashes_before_model': evaluator_hashes_before,
            'evaluator_file_hashes_after_model': evaluator_hashes_after,
            'provider_receipts': receipts, 'post_review_oracle_measurement_not_reviewed_by_existing_reviews': True,
            'scope': 'geometry_fixture_pipeline only: selected four-public-record provenance plus a new software geometry fixture. Source shapes are not reused; same-kernel oracle comparison is not independent validation or a quality proof of principle understanding. Oracle measurement occurs after the model reviews and is not represented as review evidence. Physical performance remains unknown.',
        }
        atomic_json(run_root / 'REFERENCE_DESIGN_RESULT.json', report)
        print(json.dumps({'report': str((run_root / 'REFERENCE_DESIGN_RESULT.json').resolve()),
                          'proof_passed': report['proof_passed'], 'model_calls': provider.calls}, ensure_ascii=False))
        return 0 if report['proof_passed'] else 1
    except Exception as exc:
        error = exc.as_dict() if isinstance(exc, BrainError) else {'type': type(exc).__name__, 'message': str(exc)}
        report = {'proof_passed': False, 'execution_completed': False, 'acceptance_status': 'not_accepted',
                  'overall_verdict': 'not_accepted', 'physical_performance_certified': False,
                  'actual_model_called': bool(provider and provider.calls), 'model_calls': provider.calls if provider else 0,
                  'request': REQUEST, 'error': error, 'provider_receipts': _receipts(provider),
                  'scope': 'Failure evidence only; no physical certification or formal owner acceptance.'}
        atomic_json(run_root / 'REFERENCE_DESIGN_RESULT.json', report)
        print(json.dumps({'report': str((run_root / 'REFERENCE_DESIGN_RESULT.json').resolve()), 'proof_passed': False}, ensure_ascii=False))
        return 1
    finally:
        if previous_req2cad_root is None:
            os.environ.pop('CADMCP_REQ2CAD_ROOT', None)
        else:
            os.environ['CADMCP_REQ2CAD_ROOT'] = previous_req2cad_root


if __name__ == '__main__':
    raise SystemExit(main())
