"""Stella local viewer server. Loopback only, read-only.

Serves static/ and lists/converts mesh files under --root.
Uses only the standard library plus numpy/trimesh (already installed).
Usage: python server.py --root <dir> [--port 8765]
"""
import argparse
import hashlib
import json
import mimetypes
import subprocess
import sys
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
MESH_EXT = {".stl", ".ply", ".obj", ".glb", ".gltf", ".step", ".stp"}
STEP_EXT = {".step", ".stp"}
ROOT = HERE
STEP_PYTHON = sys.executable
CACHE = Path(tempfile.gettempdir()) / "stella-viewer-cache"
# Interpreters that already carry OCP (OpenCascade), tried in order when --step-python is not given.
STEP_PYTHON_CANDIDATES = [
    HERE.parent / "build123d-mcp" / ".venv" / "Scripts" / "python.exe",
    HERE.parent.parent / "cadmcp-all-in-one-2026-09-17" / "01_CURRENT" / ".venv" / "Scripts" / "python.exe",
]


def safe(rel):
    p = (ROOT / rel).resolve()
    if p != ROOT and ROOT not in p.parents:
        raise PermissionError("outside root")
    return p


def step_to_glb(p):
    st = p.stat()
    key = hashlib.sha1(f"{p}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()[:20]
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"{key}.glb"
    if not out.is_file():
        tmp = out.with_suffix(".tmp")
        r = subprocess.run([STEP_PYTHON, "-I", str(HERE / "step_to_glb.py"), str(p), str(tmp)],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError("STEP conversion failed: " + (r.stderr.strip().splitlines() or ["?"])[-1])
        tmp.replace(out)
    return out.read_bytes()


def step_to_shapes(p):
    st = p.stat()
    key = hashlib.sha1(f"shapes|{p}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()[:20]
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"{key}.json"
    if not out.is_file():
        tmp = out.with_suffix(".tmp")
        r = subprocess.run([STEP_PYTHON, "-I", str(HERE / "step_to_shapes.py"), str(p), str(tmp)],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError("STEP conversion failed: " + (r.stderr.strip().splitlines() or ["?"])[-1])
        tmp.replace(out)
    return out.read_bytes()


def to_glb(p):
    if p.suffix.lower() in (".glb", ".gltf"):
        return p.read_bytes()
    if p.suffix.lower() in STEP_EXT:
        return step_to_glb(p)
    import trimesh

    m = trimesh.load(str(p), force="mesh")
    return m.export(file_type="glb")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(HERE), **k)

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        try:
            if u.path == "/api/models":
                items = []
                for p in ROOT.rglob("*"):
                    if p.suffix.lower() in MESH_EXT and p.is_file():
                        st = p.stat()
                        items.append({"path": p.relative_to(ROOT).as_posix(), "mtime": st.st_mtime, "size": st.st_size})
                items.sort(key=lambda x: -x["mtime"])
                return self._send(200, json.dumps(items[:500]).encode(), "application/json")
            if u.path == "/api/shapes":
                rel = parse_qs(u.query).get("path", [""])[0]
                p = safe(rel)
                if p.suffix.lower() not in STEP_EXT or not p.is_file():
                    return self._send(404, b"not found", "text/plain")
                return self._send(200, step_to_shapes(p), "application/json")
            if u.path == "/api/mesh":
                rel = parse_qs(u.query).get("path", [""])[0]
                p = safe(rel)
                if p.suffix.lower() not in MESH_EXT or not p.is_file():
                    return self._send(404, b"not found", "text/plain")
                return self._send(200, to_glb(p), "model/gltf-binary")
        except PermissionError:
            return self._send(403, b"forbidden", "text/plain")
        except Exception as e:
            return self._send(500, str(e).encode(), "text/plain")
        return super().do_GET()


def main():
    global ROOT, STEP_PYTHON
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--step-python", help="interpreter with OCP+trimesh used to read STEP")
    a = ap.parse_args()
    ROOT = Path(a.root).resolve()
    if a.step_python:
        STEP_PYTHON = a.step_python
    else:
        STEP_PYTHON = next((str(c) for c in STEP_PYTHON_CANDIDATES if c.is_file()), sys.executable)
    if not ROOT.is_dir():
        sys.exit("root is not a directory")
    mimetypes.add_type("text/javascript", ".js")
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"viewer: http://127.0.0.1:{a.port}/static/index.html  root={ROOT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
