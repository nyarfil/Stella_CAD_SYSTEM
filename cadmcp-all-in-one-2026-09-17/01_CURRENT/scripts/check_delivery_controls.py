"""Generate and measure isolated STEP delivery negative controls.

This development-only probe deliberately creates hand-authored synthetic
geometry.  It neither reads a production CAD subject nor registers a Studio
review subject.  It is useful for showing that the delivery comparison rejects
specific mismatches, but it is not a physical certification.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cadmcp_brain.req2cad.common import atomic_json, file_hash


FIXED_CASES = {
    'positive_exact': 'pass',
    'same_bbox_volume_different_shape': 'fail',
    'moved_solid': 'fail',
    'missing_solid': 'fail',
    'extra_solid': 'fail',
    'duplicate_solid': 'fail',
}


def _export(path, shape):
    import cadquery as cq
    cq.exporters.export(shape, str(path))
    return path


def _box(x=0.0):
    import cadquery as cq
    return cq.Workplane('XY').box(4, 4, 4).val().translate((x, 0, 0))


def _case_shapes():
    """Return only synthetic cases, with an explicit expected verdict."""
    import cadquery as cq
    left, right = _box(-4), _box(4)
    base = cq.Workplane('XY').box(6, 6, 6).val()
    # Fully internal cavities keep the exact external bounds and removed volume
    # equal, while their locations make the B-reps non-equivalent.
    expected = base.cut(cq.Workplane('XY').box(1, 1, 1).val().translate((1, 1, 1)))
    different = base.cut(cq.Workplane('XY').box(1, 1, 1).val().translate((-1, -1, -1)))
    bounds = lambda shape: [shape.BoundingBox().xmin, shape.BoundingBox().ymin, shape.BoundingBox().zmin,
                            shape.BoundingBox().xmax, shape.BoundingBox().ymax, shape.BoundingBox().zmax]
    same_bbox_volume = {
        'expected_bounds_mm': bounds(expected), 'assembly_bounds_mm': bounds(different),
        'expected_volume_mm3': float(expected.Volume()), 'assembly_volume_mm3': float(different.Volume()),
    }
    same_bbox_volume['bounds_match'] = same_bbox_volume['expected_bounds_mm'] == same_bbox_volume['assembly_bounds_mm']
    same_bbox_volume['volume_match'] = same_bbox_volume['expected_volume_mm3'] == same_bbox_volume['assembly_volume_mm3']
    if not (same_bbox_volume['bounds_match'] and same_bbox_volume['volume_match']):
        raise RuntimeError('Synthetic same-bounds/same-volume negative control is invalid.')
    return [
        ('positive_exact', {'left': left, 'right': right}, cq.Compound.makeCompound([left, right]), None),
        ('same_bbox_volume_different_shape', {'part': expected}, different, same_bbox_volume),
        ('moved_solid', {'left': left, 'right': right}, cq.Compound.makeCompound([left.translate((1, 0, 0)), right]), None),
        ('missing_solid', {'left': left, 'right': right}, left, None),
        ('extra_solid', {'left': left, 'right': right}, cq.Compound.makeCompound([left, right, _box(12)]), None),
        ('duplicate_solid', {'left': left, 'right': right}, cq.Compound.makeCompound([left, right, right]), None),
    ]


def run_worker(run_root: Path) -> dict:
    """Write new hand fixtures below run_root and measure each with real CadQuery."""
    from cadmcp_brain.studio.recipe import verify_delivery_steps

    if not run_root.is_dir() or any(run_root.iterdir()):
        raise ValueError('Worker requires an empty parent-created run-root.')
    cases = []
    for case_id, parts, assembly, precondition in _case_shapes():
        folder = run_root / case_id
        folder.mkdir()
        part_paths = {part_id: _export(folder / f'{part_id}.step', shape) for part_id, shape in parts.items()}
        assembly_path = _export(folder / 'assembly.step', assembly)
        check = verify_delivery_steps(part_paths, assembly_path)
        cases.append({
            'case_id': case_id,
            'hand_authored_synthetic_fixture': True,
            'expected_verdict': FIXED_CASES[case_id],
            'actual_verdict': check['verdict'],
            'check': check,
            'input_step_paths': {
                'parts': {part_id: str(path.resolve()) for part_id, path in part_paths.items()},
                'assembly': str(assembly_path.resolve()),
            },
            'input_step_hashes': {
                'parts': {part_id: file_hash(path) for part_id, path in part_paths.items()},
                'assembly': file_hash(assembly_path),
            },
        })
        if precondition is not None:
            cases[-1]['same_bbox_volume_precondition'] = precondition
    return {'cases': cases}


def _validate_worker_result(run_root: Path, result: object) -> tuple[dict, list[str]]:
    """Recompute success from fixed controls and bytes still on disk."""
    errors = []
    cases = result.get('cases') if isinstance(result, dict) else None
    if not isinstance(cases, list):
        return {'cases': [], 'all_expected_verdicts_observed': False}, ['worker result has no cases list']
    ids = [item.get('case_id') for item in cases if isinstance(item, dict)]
    if any(not isinstance(case_id,str) for case_id in ids):
        return {'cases':cases,'all_expected_verdicts_observed':False}, ['worker case IDs must be strings']
    if len(cases) != len(FIXED_CASES) or len(ids) != len(set(ids)) or set(ids) != set(FIXED_CASES):
        errors.append('worker cases must contain each fixed case ID exactly once')
    normalized = []
    for item in cases:
        if not isinstance(item, dict):
            errors.append('worker case is not an object')
            continue
        case_id = item.get('case_id')
        expected = FIXED_CASES.get(case_id)
        actual = item.get('actual_verdict')
        check = item.get('check')
        if item.get('expected_verdict') != expected:
            errors.append(f'{case_id}: expected verdict is not fixed')
        if actual not in ('pass', 'fail') or not isinstance(check, dict) or check.get('verdict') != actual:
            errors.append(f'{case_id}: actual verdict and check verdict disagree')
        paths, hashes = item.get('input_step_paths'), item.get('input_step_hashes')
        if not isinstance(paths, dict) or not isinstance(hashes, dict) or not isinstance(paths.get('parts'), dict) or not isinstance(hashes.get('parts'), dict):
            errors.append(f'{case_id}: missing input STEP identities')
        else:
            required_parts={'part'} if case_id=='same_bbox_volume_different_shape' else {'left','right'}
            if set(paths['parts'])!=required_parts:
                errors.append(f'{case_id}: part identities do not match the fixed fixture')
            pairs = [('assembly', paths.get('assembly'), hashes.get('assembly'))]
            pairs.extend((f'part:{part_id}', path, hashes['parts'].get(part_id)) for part_id, path in paths['parts'].items())
            if set(paths['parts']) != set(hashes['parts']):
                errors.append(f'{case_id}: part STEP path/hash keys disagree')
            for label, raw_path, expected_hash in pairs:
                try:
                    path = Path(raw_path).resolve()
                    expected_name='assembly.step' if label=='assembly' else label.removeprefix('part:')+'.step'
                    expected_path=(run_root/str(case_id)/expected_name).resolve()
                    if (path!=expected_path or not path.is_relative_to(run_root)
                            or file_hash(path) != expected_hash):
                        errors.append(f'{case_id}: {label} STEP hash does not match worker report')
                except (OSError, TypeError, ValueError):
                    errors.append(f'{case_id}: {label} STEP identity is unreadable')
        if case_id == 'same_bbox_volume_different_shape':
            prerequisite = item.get('same_bbox_volume_precondition')
            if not isinstance(prerequisite, dict) or prerequisite.get('bounds_match') is not True or prerequisite.get('volume_match') is not True:
                errors.append('same_bbox_volume_different_shape: measured equal-bounds/equal-volume prerequisite missing')
        normalized.append(item)
    observed = not errors and all(item.get('actual_verdict') == FIXED_CASES.get(item.get('case_id')) for item in normalized)
    return {'cases': normalized, 'all_expected_verdicts_observed': observed}, errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', required=True, type=Path)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args(argv)
    verification = (ROOT / 'verification').resolve()
    run_root = args.run_root.resolve()
    if not run_root.is_relative_to(verification):
        raise ValueError('run-root must be a new directory below verification.')
    if args.worker:
        result = run_worker(run_root)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if run_root.exists():
        raise ValueError('run-root already exists; reports are never overwritten.')
    run_root.mkdir(parents=True)
    evaluator_paths = [Path(__file__).resolve(), ROOT / 'cadmcp_brain/studio/recipe.py',
                       ROOT / 'cadmcp_brain/studio/measurement.py']
    evaluator_hashes = {str(path): file_hash(path) for path in evaluator_paths}
    try:
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker',
                           '--run-root', str(run_root)], capture_output=True, text=True,
                          encoding='utf-8', timeout=90, check=False)
    except (subprocess.TimeoutExpired, OSError) as exc:
        atomic_json(run_root / 'failure.json', {'success': False, 'failure_kind': type(exc).__name__,
                                                'message': str(exc), 'model_calls': 0})
        return 1
    if proc.returncode not in (0, 1):
        atomic_json(run_root / 'failure.json', {'success': False, 'failure_kind': 'worker_crash',
                                                'returncode': proc.returncode, 'stdout': proc.stdout[-4000:],
                                                'stderr': proc.stderr[-4000:], 'model_calls': 0})
        return 1
    try:
        worker_result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        atomic_json(run_root / 'failure.json', {'success': False, 'failure_kind': 'invalid_worker_json',
                                                'returncode': proc.returncode, 'message': str(exc), 'model_calls': 0})
        return 1
    result, validation_errors = _validate_worker_result(run_root, worker_result)
    evaluator_unchanged = {str(path): file_hash(path) for path in evaluator_paths} == evaluator_hashes
    if not evaluator_unchanged:
        validation_errors.append('Evaluator changed during delivery-control measurement.')
    success = proc.returncode == 0 and result['all_expected_verdicts_observed'] and evaluator_unchanged
    report = {
        'schema_version': 1,
        'run_root': str(run_root),
        'hand_authored_synthetic_fixtures': True,
        'cases': result['cases'],
        'all_expected_verdicts_observed': result['all_expected_verdicts_observed'],
        'worker_returncode': proc.returncode,
        'worker_contract_valid': not validation_errors,
        'validation_errors': validation_errors,
        'success': success,
        'evaluator_file_hashes': evaluator_hashes,
        'model_calls': 0,
        'physical_performance_certified': False,
        'formal_subject_linked': False,
        'scope': ('Development self-test only: the same CadQuery/OCCT tool creates and measures synthetic STEP files; '
                  'this is not independent-kernel validation, a registered Studio subject, or physical certification.'),
    }
    atomic_json(run_root / 'DELIVERY_CONTROLS_REPORT.json', report)
    print(json.dumps({'report': str(run_root / 'DELIVERY_CONTROLS_REPORT.json'),
                      'all_expected_verdicts_observed': report['all_expected_verdicts_observed'],
                      'success': success}))
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
