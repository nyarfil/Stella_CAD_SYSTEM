"""Compare source hole patterns without moving, scaling or approving hardware."""
from __future__ import annotations
import hashlib
import argparse
import itertools
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    directory = ROOT / 'docs/examples'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boundaries', type=Path, default=directory / 'zs_f1_g305_planar_boundaries.json')
    parser.add_argument('--bottom-key', default='Solid/bottom-solid.stl')
    parser.add_argument('--output', type=Path, default=directory / 'zs_f1_g305_primary_click_mount_pattern.json')
    args = parser.parse_args()
    boundaries_path = args.boundaries
    boundaries = json.loads(boundaries_path.read_text(encoding='utf-8'))
    raw_bottom = Path(boundaries['source_root']) / args.bottom_key
    assert digest(raw_bottom) == boundaries['source_sha256'][args.bottom_key]
    rims = [r for r in boundaries['files'][args.bottom_key]
            if r['axis'] == 'Z' and abs(r['radius']-.6)<.001 and abs(r['center'][2]-5.159756)<.001]
    assert len(rims) == 4
    results = []
    for side in ('left', 'right'):
        board_path = directory / f'g305_{side}_switch_board_reference.json'
        board = json.loads(board_path.read_text(encoding='utf-8'))
        source_file = Path(board['source'])
        assert digest(source_file) == board['source_sha256']
        shape = next(s for s in board['shapes'] if s['ref'] == '#o1.2.s1')
        holes = [e for e in shape['circular_edges'] if e['full_circle'] and abs(e['radius']-1)<.001 and abs(e['center'][2]-.6)<.001]
        assert len(holes) == 4
        target = sorted([r for r in rims if (r['center'][0]<0)==(side=='left')], key=lambda r:r['center'][1])
        assert len(target) == 2
        target_distance = math.dist(target[0]['center'], target[1]['center'])
        candidates = []
        for a,b in itertools.combinations(holes,2):
            distance = math.dist(a['center'],b['center'])
            error = abs(distance-target_distance)
            candidates.append({'source_centers_mm':[a['center'],b['center']],
                               'source_distance_mm':distance, 'target_distance_stl_units':target_distance,
                               'distance_mismatch_under_unit_scale':error,
                               'minimum_equal_weight_two_point_rms_under_unit_scale':error/2})
        candidates.sort(key=lambda r:r['distance_mismatch_under_unit_scale'])
        results.append({'side':side,'source_sha256':board['source_sha256'],
                        'side_convention': 'Comparison only: bottom X<0 called left, X>0 called right; physical handedness unverified.',
                        'best_pair_count': sum(abs(c['distance_mismatch_under_unit_scale']-candidates[0]['distance_mismatch_under_unit_scale'])<1e-8 for c in candidates),
                        'residual_units': 'comparison coordinate units under 1 STEP mm = 1 STL coordinate unit assumption',
                        'residual_scope': 'Theoretical lower bound for free equal-weight two-point rigid alignment only; not an installed assembly residual.',
                        'source_report_sha256':digest(board_path),'source_board_ref':shape['ref'],
                        'target_rims':target,'pair_candidates':candidates})
    report = {'status':'reference_pattern_mismatch_not_fit_verified',
              'unit_assumption':'For comparison only: one STEP mm equals one STL coordinate unit; physical STL scale remains unverified.',
              'bottom_file':args.bottom_key,'bottom_sha256':digest(raw_bottom),'boundary_report_sha256':digest(boundaries_path),
              'script_sha256':digest(Path(__file__)),
              'method':'Enumerate all six pairs of four PCB full-circle rims; compare with each same-side pair of bottom radius-0.6 rims. Pair distance is rigid-motion invariant; best equal-weight residual per point is half the distance difference.',
              'sides':results,
              'not_verified':['Which two PCB holes are used by the ZS-F1 author.', 'Circular rims as functional bores and support lands.',
                              'Physical STL scale, screw dimensions and radial clearance.', 'PCB orientation, switch contact alignment, Z seating and all-body clearance.',
                              'Reference hardware revision and actual user hardware.'],
              'prohibited_inference':'Do not scale the PCB, deform holes or approve a ready hardware pack to erase mismatch.'}
    output = args.output
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({side['side']: {'best_pair_count':side['best_pair_count'], 'best_value':side['pair_candidates'][0]} for side in results}))

if __name__ == '__main__':
    main()
