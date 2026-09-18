#!/usr/bin/env python3
"""Read-only SHA-256 verification of this distribution; no CAD/model execution."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        manifest = json.loads((root / 'BUNDLE_MANIFEST.json').read_text(encoding='utf-8'))
        records = manifest['files']
        if manifest.get('format') != 1 or not isinstance(records, list):
            raise ValueError('Unsupported manifest format')
        failures = []
        seen = set()
        for item in records:
            rel = item['path']
            path = PurePosixPath(rel)
            if (not rel or path.is_absolute() or '..' in path.parts or
                    '\\' in rel or ':' in rel or rel in seen):
                raise ValueError('Unsafe or duplicate manifest path: ' + rel)
            seen.add(rel)
            target = root.joinpath(*path.parts)
            if not target.resolve().is_relative_to(root):
                raise ValueError('Path escapes bundle: ' + rel)
            if any(p.is_symlink() for p in [target, *target.parents] if p != root and root in p.parents):
                failures.append({'path': rel, 'reason': 'symlink'})
                continue
            if not target.is_file():
                failures.append({'path': rel, 'reason': 'missing'})
                continue
            sha = hashlib.sha256()
            with target.open('rb') as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b''):
                    sha.update(block)
            if target.stat().st_size != item['bytes'] or sha.hexdigest() != item['sha256']:
                failures.append({'path': rel, 'reason': 'size_or_sha256_mismatch'})
        result = {'checked': len(records), 'passed': len(records) - len(failures),
                  'failures': failures, 'application_tests_run': False,
                  'note': 'Only files listed in the manifest are checked; runtime-created files are ignored.'}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if failures else 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('Bundle verification error: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
