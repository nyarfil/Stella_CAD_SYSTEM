"""Bounded, read-only delivery comparison for an existing isolated supplement trial."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from cadmcp_brain.req2cad.common import atomic_json,file_hash,json_load


def snapshot(folder):
    return {p.relative_to(folder).as_posix():file_hash(p)
            for p in sorted(folder.rglob('*')) if p.is_file()}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-result',required=True,type=Path)
    parser.add_argument('--report',type=Path)
    parser.add_argument('--worker',action='store_true')
    args=parser.parse_args(argv)
    source=args.source_result.resolve()
    verification=(ROOT/'verification').resolve()
    if not source.is_relative_to(verification):
        raise ValueError('Only isolated verification results may be inspected.')
    source_hash=file_hash(source)
    folder=Path(json_load(source)['result']['folder']).resolve()
    if not folder.is_relative_to(verification) or not folder.is_dir():
        raise ValueError('Source folder must be an existing isolated verification folder.')
    if args.worker:
        from cadmcp_brain.studio.recipe import verify_delivery_steps
        measurement=json_load(folder/'measurements.json')
        parts={part:folder/part/'model.step' for part in measurement['outputs']}
        if any(not path.resolve().is_relative_to(folder) for path in parts.values()):
            raise ValueError('Part export escapes source folder.')
        print(json.dumps(verify_delivery_steps(parts,folder/'assembly.step')))
        return 0
    if args.report is None:
        raise ValueError('A new report path is required.')
    target=args.report.resolve()
    if (target.exists() or not target.is_relative_to(verification)
            or target.is_relative_to(folder)):
        raise ValueError('Report must be new and outside the source evidence folder.')
    before=snapshot(folder)
    evaluator_paths=[Path(__file__).resolve(),
                     ROOT/'cadmcp_brain/studio/recipe.py',
                     ROOT/'cadmcp_brain/studio/measurement.py']
    evaluator_hashes={str(p):file_hash(p) for p in evaluator_paths}
    proc=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker',
                         '--source-result',str(source)],capture_output=True,
                        text=True,encoding='utf-8',timeout=90,check=True)
    check=json.loads(proc.stdout)
    if snapshot(folder)!=before or file_hash(source)!=source_hash:
        raise RuntimeError('Source evidence changed during inspection.')
    if {str(p):file_hash(p) for p in evaluator_paths}!=evaluator_hashes:
        raise RuntimeError('Evaluator changed during inspection.')
    result={'source_result_sha256':source_hash,'source_folder':str(folder),
            'source_manifest':before,'source_unchanged':True,'check':check,
            'evaluator_file_hashes':evaluator_hashes,
            'model_calls':0,'cad_regenerated':False,'historical_review_modified':False,
            'scope':'Development remeasurement only; not a registered review acceptance or physical certification.'}
    atomic_json(target,result)
    print(json.dumps({'report':str(target),'verdict':check['verdict'],'source_unchanged':True}))
    return 0 if check['verdict']=='pass' else 1


if __name__=='__main__':raise SystemExit(main())
