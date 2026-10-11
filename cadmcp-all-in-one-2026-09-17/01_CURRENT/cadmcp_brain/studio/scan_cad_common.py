"""Shared job runner for the scan-to-CAD tools (shell fit, click slots, plate side, face roles, symmetrise).

Each tool validates its arguments, hashes its inputs and settings into a job id, and runs ONE worker script as a subprocess
(heavy geometry never runs in the server process; a timeout stops it). Outputs are written once under mouse/<area>/<id>/ and never
overwritten; the same inputs return the stored report (hashes re-checked). B-rep workers run in the server python (needs OCP,
extra `geometry`); mesh workers run in the separate scan python (brain_mouse_scan_model.find_scan_python).
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable
from ..errors import BrainError
from ..req2cad.common import atomic_json, json_load
from ..util import digest, file_hash, safe_path

MAX_INPUT_BYTES = 512 * 1024 * 1024


def server_python() -> Path:
    return Path(sys.executable)


def check_file(workspace: Path, rel: str, suffixes: tuple[str, ...], code: str, what: str) -> Path:
    p = safe_path(workspace, rel)
    if p.suffix.lower() not in suffixes or p.is_symlink() or not p.is_file():
        raise BrainError(code, f'{what} must be a regular {" / ".join(suffixes)} file inside the workspace.', {'given': rel})
    if p.stat().st_size > MAX_INPUT_BYTES:
        raise BrainError(code, f'{what} is too large.', {'given': rel})
    return p


def check_range(name: str, val: Any, lo: float, hi: float, code: str) -> None:
    if isinstance(val, bool) or not isinstance(val, (int, float)) or not lo <= val <= hi:
        raise BrainError(code, f'{name} must be in [{lo}, {hi}].', {'given': val})


def _read_json_obj(path: Path, code: str) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise BrainError(code, 'The file is not readable JSON.', {'file': path.name}) from exc
    if not isinstance(obj, dict):
        raise BrainError(code, 'The file must hold a JSON object.', {'file': path.name})
    return obj


def _plane_of(obj: Any) -> dict[str, Any] | None:
    if isinstance(obj, dict) and isinstance(obj.get('normal'), list) and len(obj['normal']) == 3 and isinstance(obj.get('d'), (int, float)) \
            and not isinstance(obj.get('d'), bool) and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in obj['normal']) \
            and sum(float(x) ** 2 for x in obj['normal']) > 1e-12:
        return {'normal': [float(x) for x in obj['normal']], 'd': float(obj['d'])}
    return None


def mirror_from_report(workspace: Path, rel: str, code: str, what: str = 'symmetry_report_path', _depth: int = 0) -> dict[str, Any]:
    """Mirror plane {normal, d} from a report path: brain_mouse_scan_symmetrise report / mirror_plane.json ("plane" or top-level normal + d) or a
    report that names its symmetry source (shell_fit: settings.mirror_plane or source.symmetry_report_relative_path)."""
    path = check_file(workspace, rel, ('.json',), code, what)
    obj = _read_json_obj(path, code)
    pl = _plane_of(obj.get('plane')) or _plane_of(obj) or _plane_of((obj.get('settings') or {}).get('mirror_plane'))
    if pl is None and _depth == 0:
        src = (obj.get('source') or {}).get('symmetry_report_relative_path')
        if isinstance(src, str) and src:
            return mirror_from_report(workspace, src, code, what, 1)
    if pl is None:
        raise BrainError(code, f'{what} holds no mirror plane {{"normal": [nx, ny, nz], "d": d}} (symmetrise report, mirror_plane.json or a report '
                               'that names its symmetry report).', {'given': rel})
    return pl


def layout_from(workspace: Path, rel: str, code: str, what: str = 'layout_path') -> tuple[Path, str]:
    """slot_layout.json (click_slot_layout/1) or a brain_mouse_scan_click_grooves report -> (layout file, its workspace-relative path)."""
    path = check_file(workspace, rel, ('.json',), code, what)
    obj = _read_json_obj(path, code)
    if str(obj.get('schema', '')).startswith('scan_click_grooves_report'):
        lr = ((obj.get('outputs') or {}).get('layout') or {}).get('relative_path')
        if not isinstance(lr, str) or not lr:
            raise BrainError(code, 'The click_grooves report lists no slot layout.', {'given': rel})
        return check_file(workspace, lr, ('.json',), code, f'{what} (layout named by the click_grooves report)'), lr
    return path, rel


def job_folder(workspace: Path, area: str, job_id: str) -> Path:
    return Path(workspace) / 'mouse' / area / job_id


def run_job(*, workspace: Path, area: str, prefix: str, version: str, code: str, inputs: dict[str, Path | None], settings: dict[str, Any],
            worker: Path, python: Path, report_name: str, build_report: Callable[[dict[str, Any], Path, str, dict[str, str | None]], dict[str, Any]],
            timeout_s: int = 1800, extra_request: dict[str, Any] | None = None) -> dict[str, Any]:
    """code = error-code prefix (e.g. 'SHELL_FIT'). build_report(res, final_folder, job_id, input_hashes) -> report dict (must hold 'outputs')."""
    hashes = {k: (file_hash(p) if p else None) for k, p in inputs.items()}
    job_id = prefix + digest({'inputs': hashes, 'settings': settings, 'version': version})[:12]
    out = job_folder(workspace, area, job_id)
    if (out / report_name).is_file():
        return stored(out, report_name, code)
    if out.exists():
        raise BrainError(f'{code}_OUTPUT_EXISTS', 'The output folder exists without a report; it is never overwritten. Move it away first.',
                         {'folder': f'mouse/{area}/{job_id}'})
    tmp = out.with_name(out.name + '.tmp-' + uuid.uuid4().hex[:8])
    tmp.mkdir(parents=True)
    try:
        req = {'inputs': {k: (str(p) if p else None) for k, p in inputs.items()}, 'params': settings, 'out_dir': str(tmp / 'out'), **(extra_request or {})}
        (tmp / 'request.json').write_text(json.dumps(req), encoding='utf-8')
        try:
            proc = subprocess.run([str(python), '-I', str(worker), str(tmp / 'request.json')], capture_output=True, text=True, encoding='utf-8',
                                  errors='replace', timeout=timeout_s, cwd=str(tmp), env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        except subprocess.TimeoutExpired as exc:
            raise BrainError(f'{code}_TIMEOUT', f'The worker exceeded {timeout_s} s and was stopped.') from exc
        except OSError as exc:
            raise BrainError(f'{code}_PYTHON_MISSING', 'The worker python could not be started.', {'python': str(python), 'error': type(exc).__name__}) from exc
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith('{')]
        try:
            res = json.loads(lines[-1])
        except (IndexError, ValueError) as exc:
            raise BrainError(f'{code}_WORKER', 'The worker returned no JSON result.', {'exit_code': proc.returncode, 'stderr_tail': proc.stderr[-1500:]}) from exc
        if res.get('status') != 'OK':
            err = res.get('error') or {}
            raise BrainError(err.get('code', f'{code}_WORKER'), err.get('message', 'The worker failed.'),
                             {'python': str(python), 'details': err.get('details'), 'trace': err.get('trace')})
        final = tmp / 'out'
        report = build_report(res, final, job_id, hashes)
        report.setdefault('job_id', job_id)
        report.setdefault('worker_python', str(python))
        for name, item in report.get('outputs', {}).items():
            if isinstance(item, dict) and 'file' in item and 'sha256' not in item:
                item['sha256'] = file_hash(final / item['file'])
                item['relative_path'] = f'mouse/{area}/{job_id}/{item["file"]}'
        atomic_json(final / report_name, report)
        out.parent.mkdir(parents=True, exist_ok=True)
        final.replace(out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return report


def stored(folder: Path, report_name: str, code: str) -> dict[str, Any]:
    rep = json_load(folder / report_name)
    for item in rep.get('outputs', {}).values():
        if not isinstance(item, dict) or 'relative_path' not in item:
            continue
        p = folder / Path(item['relative_path']).name
        if not p.is_file() or file_hash(p) != item['sha256']:
            raise BrainError(f'{code}_OUTPUT_CHANGED', 'A stored output no longer matches its recorded hash; it is not overwritten.', {'file': p.name})
    return {**rep, 'cached': True}


def worker_main(run: Callable[[dict[str, Any]], dict[str, Any]], error_cls: type, argv: list[str]) -> int:
    """Worker-side entry: read request.json, run, print the result as the LAST stdout line (JSON)."""
    import time
    import traceback
    t0 = time.time()
    try:
        req = json.loads(Path(argv[1]).read_text(encoding='utf-8'))
        res = run(req)
        res.setdefault('seconds', round(time.time() - t0, 1))
        res['status'] = 'OK'
    except error_cls as exc:  # type: ignore[misc]
        res = {'status': 'ERROR', 'error': {'code': exc.code, 'message': exc.message, 'details': exc.details}}
    except Exception as exc:  # noqa: BLE001 - the worker reports every failure as JSON
        res = {'status': 'ERROR', 'error': {'code': 'WORKER_EXCEPTION', 'message': f'{type(exc).__name__}: {exc}', 'trace': traceback.format_exc()[-3000:]}}
    sys.stdout.write('\n' + json.dumps(_clean(res), allow_nan=False, default=_json_default) + '\n')
    return 0


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float):
        return o if o == o and abs(o) != float('inf') else None
    if type(o).__module__ == 'numpy':
        return _clean(_json_default(o))
    return o


def _json_default(o):
    try:
        import numpy as np
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            v = float(o)
            return v if v == v and abs(v) != float('inf') else None
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, np.bool_):
            return bool(o)
    except ImportError:
        pass
    return str(o)


class WorkerError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


__all__ = ['run_job', 'stored', 'check_file', 'check_range', 'server_python', 'worker_main', 'WorkerError', 'job_folder']
