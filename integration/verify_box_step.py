"""Independent box STEP acceptance, run with Stella's CadQuery environment."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cadquery as cq


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('step', type=Path)
    args = parser.parse_args()
    path = args.step.resolve()
    source = path.read_bytes()
    shape = cq.importers.importStep(str(path)).val()
    bounds = shape.BoundingBox()
    actual_bounds = [bounds.xmin, bounds.ymin, bounds.zmin,
                     bounds.xmax, bounds.ymax, bounds.zmax]
    expected_bounds = [0., 0., 0., 20., 10., 5.]
    oracle = cq.Workplane('XY').box(20, 10, 5, centered=(False, False, False)).val()
    difference = shape.cut(oracle).Volume() + oracle.cut(shape).Volume()
    checks = {
        'valid': shape.isValid(),
        'one_solid': len(shape.Solids()) == 1,
        'bounds': all(abs(a-b) <= 1e-6 for a, b in zip(actual_bounds, expected_bounds)),
        'volume': abs(shape.Volume()-1000.) <= 1e-5,
        'shape_equivalence': difference <= 1e-5,
        'source_unchanged': source == path.read_bytes(),
    }
    report = {'step': str(path), 'sha256': hashlib.sha256(source).hexdigest(),
              'bounds_mm': actual_bounds, 'volume_mm3': shape.Volume(),
              'symmetric_difference_mm3': difference, 'checks': checks,
              'passed': all(checks.values()), 'physical_performance': 'unknown'}
    path.with_suffix('.acceptance.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
