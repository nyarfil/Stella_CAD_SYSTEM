"""brain_mouse_assembly_swap: replace labelled solids of an assembly STEP by solids of other STEP files, keep every other solid unchanged.

The input STEP files are only READ. The new AP242 assembly (labels, placements, colours) is written once under mouse/cad/<as_id>/ and read back;
the report gates the label set and the change (volume, centre of mass, bounding box, face count) of every untouched part. Geometry runs in the
worker subprocess mouse_assembly_swap_worker.py (OCP, extra `geometry`).
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .scan_cad_common import check_file, check_range, run_job, server_python
from .. import __version__
from ..errors import BrainError

SWAP_VERSION = 'AS1.0'
STEP_SUFFIXES = ('.step', '.stp')
MAX_REPLACEMENTS = 64
HERE = Path(__file__).parent
SWAP_REPORT = 'assembly_swap_report.json'


def assembly_swap(workspace: Path, assembly_step_path: str, replacements: list[dict[str, Any]], tol_volume_mm3: float = 1e-6,
                  tol_position_mm: float = 1e-6, schema: str = 'AP242') -> dict[str, Any]:
    workspace, code = Path(workspace), 'ASSEMBLY_SWAP'
    check_range('tol_volume_mm3', tol_volume_mm3, 0.0, 10.0, f'{code}_SETTINGS')
    check_range('tol_position_mm', tol_position_mm, 0.0, 1.0, f'{code}_SETTINGS')
    if schema not in ('AP242', 'AP214', 'AP203'):
        raise BrainError(f'{code}_SETTINGS', 'schema must be AP242, AP214 or AP203.', {'given': schema})
    if not isinstance(replacements, list) or not 1 <= len(replacements) <= MAX_REPLACEMENTS:
        raise BrainError(f'{code}_SETTINGS', f'replacements must list 1-{MAX_REPLACEMENTS} {{"label", "step_path", "source_part"?}}.',
                         {'given': type(replacements).__name__})
    inputs: dict[str, Path | None] = {'assembly': check_file(workspace, assembly_step_path, STEP_SUFFIXES, f'{code}_FILE', 'assembly_step_path')}
    norm = []
    for i, r in enumerate(replacements):
        if not isinstance(r, dict) or set(r) - {'label', 'step_path', 'source_part'}:
            raise BrainError(f'{code}_SETTINGS', 'Each replacement is {"label", "step_path", "source_part"?}.', {'index': i, 'given': r})
        for k in ('label', 'step_path'):
            if not isinstance(r.get(k), str) or not r[k].strip() or len(r[k]) > 400:
                raise BrainError(f'{code}_SETTINGS', f'replacements[{i}].{k} must be a non-empty string.', {'given': r.get(k)})
        sp = r.get('source_part')
        if sp is not None and (not isinstance(sp, str) or not sp.strip()):
            raise BrainError(f'{code}_SETTINGS', f'replacements[{i}].source_part must be a part name.', {'given': sp})
        inputs[f'rep_{i}'] = check_file(workspace, r['step_path'], STEP_SUFFIXES, f'{code}_FILE', f'replacements[{i}].step_path')
        norm.append({'label': r['label'], 'source_part': sp})
    settings = {'replacements': norm, 'tol_volume_mm3': float(tol_volume_mm3), 'tol_position_mm': float(tol_position_mm), 'schema': schema}

    def build_report(res, final, job_id, hashes):
        ch = res['checks']
        status = 'FAIL' if 'FAIL' in ch.values() else 'WARN' if 'WARN' in ch.values() else 'PASS'
        return {'schema': 'mouse_assembly_swap_report/1', 'status': status, 'assembly_swap_id': job_id, 'version': SWAP_VERSION, 'server_version': __version__,
                'inputs': {'assembly_step_path': assembly_step_path,
                           'replacements': [{'label': r['label'], 'step_path': replacements[i]['step_path']} for i, r in enumerate(norm)]},
                'input_hashes': hashes, 'settings': settings, 'labels': res['labels'], 'schema_header': res['schema_header'], 'checks': ch,
                'untouched_max_change': res['untouched_max_change'], 'replaced': res['replaced'], 'rows': res['rows'], 'colours': res['colours'],
                'outputs': {k: {'file': v} for k, v in res['files'].items()}, 'seconds': res.get('seconds'),
                'limits': ['Untouched solids are written with the same B-rep and placement, but as components of a flat assembly: nested sub-assemblies, '
                           'layers, PMI and product properties of the base file are not carried over (names and colours are).',
                           "A replacement keeps its own frame; it is not moved to the old part's placement.",
                           'Changes are measured after a STEP write + read round trip with the stated tolerances; STEP text precision can leave ~1e-9 residues.']}

    return run_job(workspace=workspace, area='cad', prefix='as_', version=SWAP_VERSION, code=code, inputs=inputs, settings=settings,
                   worker=HERE / 'mouse_assembly_swap_worker.py', python=server_python(), report_name=SWAP_REPORT, build_report=build_report, timeout_s=1800)
