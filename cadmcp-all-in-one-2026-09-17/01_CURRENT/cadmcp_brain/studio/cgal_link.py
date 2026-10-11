"""Thin client that OPERATES the separate cgal-mcp (CGAL Master MCP) service over stdio JSON-RPC.

GPL isolation: nothing from CGAL or the cgal-mcp package is imported into this process. The server is started as its own
process exactly as registered (command/args/env), spoken to with MCP newline-delimited JSON-RPC, and stopped afterwards.

Server entry, in order: env CADMCP_CGAL_MCP_CONFIG (a JSON file holding either {"command", "args", "env"} or
{"mcpServers": {"cgal-mcp": {...}}}), else ~/.claude.json mcpServers.cgal-mcp. CADMCP_CGAL_DISABLE=1 reports the service absent.
CGAL_MASTER_* variables already set in this process override the registered env. CADMCP_CGAL_TIMEOUT_S bounds one job (default 300).
Only a job with state=succeeded AND validation_status=passed is used; everything else is a refusal with the server's code.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

SERVER_NAME = 'cgal-mcp'
PROTOCOL = '2025-06-18'
ENV_CONFIG, ENV_DISABLE, ENV_TIMEOUT = 'CADMCP_CGAL_MCP_CONFIG', 'CADMCP_CGAL_DISABLE', 'CADMCP_CGAL_TIMEOUT_S'


class CgalUnavailable(RuntimeError):
    """The service is not registered, not startable or did not answer."""


class CgalRefused(RuntimeError):
    """The service answered but refused or did not validate the result (code = server error code)."""

    def __init__(self, code: str, message: str, detail: Any = None):
        super().__init__(f'{code}: {message}')
        self.code, self.detail = code, detail


def server_entry() -> tuple[dict[str, Any] | None, str]:
    """(entry, source) or (None, reason)."""
    if os.environ.get(ENV_DISABLE, '').strip() == '1':
        return None, f'{ENV_DISABLE}=1'
    cfg = os.environ.get(ENV_CONFIG)
    paths = [Path(cfg)] if cfg else [Path.home() / '.claude.json']
    for p in paths:
        try:
            data = json.loads(p.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        entry = data if 'command' in data else (data.get('mcpServers') or {}).get(SERVER_NAME)
        if isinstance(entry, dict) and entry.get('command'):
            return entry, str(p)
    return None, f'no {SERVER_NAME} entry in ' + ', '.join(map(str, paths))


def status() -> dict[str, Any]:
    """Cheap presence check (no process start): is the service registered and is its command on disk."""
    entry, src = server_entry()
    if entry is None:
        return {'available': False, 'reason': src}
    cmd = Path(entry['command'])
    env = {**entry.get('env', {}), **{k: v for k, v in os.environ.items() if k.startswith('CGAL_MASTER_')}}
    worker = env.get('CGAL_MASTER_WORKER')
    missing = [str(p) for p in ([cmd] + ([Path(worker)] if worker else [])) if p.is_absolute() and not p.is_file()]
    return {'available': not missing, 'config': src, 'command': str(cmd), 'worker': worker,
            **({'reason': 'missing file(s): ' + ', '.join(missing)} if missing else {})}


class CgalClient:
    """One cgal-mcp server process for the life of a `with` block."""

    def __init__(self, timeout_s: float | None = None):
        entry, src = server_entry()
        if entry is None:
            raise CgalUnavailable(src)
        self.entry, self.config = entry, src
        self.timeout_s = float(timeout_s or os.environ.get(ENV_TIMEOUT) or 300)
        self.proc: subprocess.Popen | None = None
        self._id = 0
        self._q: queue.Queue = queue.Queue()
        self.server_info: dict[str, Any] = {}

    # ------------------------------------------------------------ transport
    def __enter__(self) -> 'CgalClient':
        env = {**os.environ, **{k: str(v) for k, v in self.entry.get('env', {}).items()},
               **{k: v for k, v in os.environ.items() if k.startswith('CGAL_MASTER_')}, 'PYTHONIOENCODING': 'utf-8'}
        try:
            self.proc = subprocess.Popen([self.entry['command'], *self.entry.get('args', [])], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, env=env, cwd=self.entry.get('cwd'), text=True, encoding='utf-8', bufsize=1)
        except OSError as exc:
            raise CgalUnavailable(f'cannot start {self.entry["command"]}: {exc}') from exc
        threading.Thread(target=self._reader, daemon=True).start()
        init = self._request('initialize', {'protocolVersion': PROTOCOL, 'capabilities': {},
                                            'clientInfo': {'name': 'cadmcp-design-brain', 'version': '1'}}, 60)
        self.server_info = init.get('serverInfo', {})
        self._send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        return self

    def __exit__(self, *exc) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.wait(5)
            except Exception:  # noqa: BLE001 - make sure the child is gone
                self.proc.kill()

    def _reader(self) -> None:
        for line in self.proc.stdout:
            line = line.strip()
            if line.startswith('{'):
                try:
                    self._q.put(json.loads(line))
                except ValueError:
                    pass
        self._q.put(None)

    def _send(self, msg: dict) -> None:
        try:
            self.proc.stdin.write(json.dumps(msg) + '\n')
            self.proc.stdin.flush()
        except OSError as exc:
            raise CgalUnavailable(f'cgal-mcp pipe closed: {exc}') from exc

    def _request(self, method: str, params: dict, timeout_s: float) -> dict:
        self._id += 1
        rid = self._id
        self._send({'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params})
        end = time.monotonic() + timeout_s
        while True:
            try:
                msg = self._q.get(timeout=max(0.05, end - time.monotonic()))
            except queue.Empty:
                raise CgalUnavailable(f'{method}: no answer within {timeout_s:.0f} s') from None
            if msg is None:
                raise CgalUnavailable(f'{method}: cgal-mcp exited')
            if msg.get('id') != rid:
                continue  # notifications / logs
            if 'error' in msg:
                raise CgalRefused('JSONRPC_ERROR', str(msg['error'].get('message')), msg['error'])
            return msg.get('result', {})

    def call(self, tool: str, arguments: dict[str, Any], timeout_s: float = 120) -> dict[str, Any]:
        res = self._request('tools/call', {'name': tool, 'arguments': arguments}, timeout_s)
        text = ''.join(b.get('text', '') for b in res.get('content', []) if isinstance(b, dict))
        if res.get('isError'):
            try:
                err = json.loads(text[text.index('{'):])
            except ValueError:
                err = {}
            raise CgalRefused(str(err.get('code', 'TOOL_ERROR')), str(err.get('message', text))[:2000], err or text[:2000])
        if isinstance(res.get('structuredContent'), dict):
            sc = res['structuredContent']
            return sc['result'] if set(sc) == {'result'} and isinstance(sc['result'], dict) else sc
        return json.loads(text)

    # ------------------------------------------------------------ jobs
    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        """Plan, execute, poll; return the accepted job or raise CgalRefused (cancelled on timeout)."""
        plan = self.call('cgal_plan', {'request': request})
        job = self.call('cgal_execute', {'plan_id': plan['plan_id']})
        end = time.monotonic() + self.timeout_s
        while True:
            job = self.call('cgal_job_status', {'job_id': job['job_id']})
            if job.get('state') not in ('queued', 'running'):
                break
            if time.monotonic() > end:
                try:
                    self.call('cgal_job_cancel', {'job_id': job['job_id']})
                finally:
                    raise CgalRefused('TIMEOUT', f'job exceeded {self.timeout_s:.0f} s and was cancelled')
            time.sleep(0.2)
        if job.get('state') != 'succeeded' or job.get('validation_status') != 'passed':
            err = job.get('error') or {}
            raise CgalRefused(str(err.get('code', job.get('state'))), str(err.get('message', 'job not accepted'))[:2000],
                              {'state': job.get('state'), 'validation_status': job.get('validation_status')})
        job['plan'] = {k: plan.get(k) for k in ('plan_id', 'registry_revision')}
        return job

    def import_mesh(self, V: np.ndarray, F: np.ndarray, unit: str, path: Path) -> dict[str, Any]:
        write_off(path, V, F)
        return self.call('cgal_artifact_import', {'path': str(path), 'unit': unit, 'artifact_type': 'TriangleSurfaceMesh'})

    def artifact_json(self, artifact_id: str, path: Path) -> Any:
        """Export a report artifact to a NEW file and read it."""
        self.call('cgal_artifact_export', {'artifact_id': artifact_id, 'path': str(path)})
        return json.loads(path.read_text(encoding='utf-8'))


def provenance(client: CgalClient, job: dict[str, Any]) -> dict[str, Any]:
    builds = [v.get('build', {}) for v in job.get('validation', []) if isinstance(v, dict)]
    ver = next((b.get('actual_cgal_version') for b in builds if b.get('actual_cgal_version')), None)
    return {'cgal_used': True, 'cgal_version': ver, 'server': client.server_info, 'config': client.config,
            'registry_revision': job['plan'].get('registry_revision'), 'plan_id': job['plan'].get('plan_id'), 'job_id': job.get('job_id'),
            'validation_status': job.get('validation_status'),
            'validators': [{'operation': v.get('operation'), 'passed': (v.get('report') or {}).get('passed'),
                            'checks': (v.get('report') or {}).get('checks')} for v in job.get('validation', []) if isinstance(v, dict)]}


def validator_report(job: dict[str, Any], operation: str) -> dict[str, Any]:
    return next(((v.get('report') or {}) for v in job.get('validation', []) if v.get('operation') == operation), {})


def weld_exact(V: np.ndarray, F: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Merge only bit-identical vertices (STL soups); no repair, no tolerance."""
    U, inv = np.unique(np.ascontiguousarray(V, dtype=np.float64), axis=0, return_inverse=True)
    return U, inv.reshape(-1)[F]


def write_off(path: Path, V: np.ndarray, F: np.ndarray) -> None:
    lines = ['OFF', f'{len(V)} {len(F)} 0'] + [f'{x!r} {y!r} {z!r}' for x, y, z in V.tolist()] + [f'3 {a} {b} {c}' for a, b, c in F.tolist()]
    path.write_text('\n'.join(lines) + '\n', encoding='ascii')


def read_off(path: Path) -> tuple[np.ndarray, np.ndarray]:
    tok = [ln.split('#')[0].strip() for ln in path.read_text(encoding='ascii').splitlines()]
    tok = [t for t in tok if t]
    head = tok[0][3:].split() if tok[0].startswith('OFF') and len(tok[0]) > 3 else None
    i = 1
    nv, nf = map(int, (head or tok[i].split())[:2])
    i += 0 if head else 1
    V = np.array([list(map(float, tok[i + k].split()[:3])) for k in range(nv)])
    rows = [list(map(int, tok[i + nv + k].split())) for k in range(nf)]
    if any(r[0] != 3 for r in rows):
        raise CgalRefused('NOT_TRIANGULATED', 'cgal-mcp returned non-triangle faces')
    return V, np.array([r[1:4] for r in rows], dtype=np.int64)
