"""HTTP Range resume for owner-side Req2CAD/DeepCAD downloads."""
import hashlib, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest
from cadmcp_brain.errors import BrainError
from cadmcp_brain.req2cad.assets import download_file


def _serve(handler):
    httpd=ThreadingHTTPServer(('127.0.0.1',0),handler)
    thread=threading.Thread(target=httpd.serve_forever,daemon=True)
    thread.start()
    return httpd

def test_complete_sha_skips_network(tmp_path,monkeypatch):
    dest=tmp_path/'Req2CAD.csv';dest.write_bytes(b'abc')
    sha=hashlib.sha256(b'abc').hexdigest()
    import urllib.request
    monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**k: (_ for _ in ()).throw(AssertionError('network')))
    assert download_file('http://example.invalid/x',dest,sha)==str(dest)

def test_existing_complete_file_without_sha_is_reused(tmp_path,monkeypatch):
    dest=tmp_path/'data.tar';dest.write_bytes(b'already-complete')
    import urllib.request
    monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**k: (_ for _ in ()).throw(AssertionError('network')))
    assert download_file('http://example.invalid/data.tar',dest)==str(dest)

def test_range_resume_keeps_partial(tmp_path):
    body=bytes(range(256))*256  # 64 KiB
    sha=hashlib.sha256(body).hexdigest()
    state={'n':0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a): pass
        def do_GET(self):
            state['n']+=1
            if state['n']==1:
                self.send_response(200)
                self.send_header('Content-Length',str(len(body)))
                self.end_headers()
                self.wfile.write(body[:8000])
                return
            assert self.headers.get('Range')=='bytes=8000-'
            chunk=body[8000:]
            self.send_response(206)
            self.send_header('Content-Range',f'bytes 8000-{len(body)-1}/{len(body)}')
            self.send_header('Content-Length',str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)

    httpd=_serve(Handler)
    try:
        url=f'http://127.0.0.1:{httpd.server_address[1]}/data.tar'
        dest=tmp_path/'data.tar'
        partial=dest.with_name('data.tar.partial')
        with pytest.raises(BrainError,match='interrupted'):
            download_file(url,dest,sha,max_bytes=10*1024**3)
        assert not dest.exists()
        assert partial.is_file() and partial.stat().st_size==8000
        out=download_file(url,dest,sha,max_bytes=10*1024**3)
        assert Path(out).read_bytes()==body
        assert file_hash_matches(out,sha)
        assert not partial.exists()
        assert state['n']==2
    finally:
        httpd.shutdown();httpd.server_close()

def file_hash_matches(path,sha):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha

def test_ignored_range_restarts_from_zero(tmp_path):
    body=b'full-body-bytes-for-restart'
    sha=hashlib.sha256(body).hexdigest()
    dest=tmp_path/'data.tar'
    dest.with_name('data.tar.partial').write_bytes(body[:7])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a): pass
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd=_serve(Handler)
    try:
        url=f'http://127.0.0.1:{httpd.server_address[1]}/data.tar'
        out=download_file(url,dest,sha)
        assert Path(out).read_bytes()==body
    finally:
        httpd.shutdown();httpd.server_close()
