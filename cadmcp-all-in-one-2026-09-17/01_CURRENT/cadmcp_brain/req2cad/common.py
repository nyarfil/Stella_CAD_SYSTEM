from __future__ import annotations
import contextlib, hashlib, json, math, os, re, time, uuid
from pathlib import Path
from ..errors import BrainError
from ..util import canonical, file_hash

REQ_URL = 'https://huggingface.co/datasets/QianzhiJing/Req2CAD/resolve/main/Req2CAD.csv'
REQ_SHA256 = 'b645fd38a75039a505cf24318cc17510b26ebc4e70068f44def06fdf1a0a55f6'
DEEP_URL = 'https://www.cs.columbia.edu/cg/deepcad/data.tar'
SOURCES = {
 'Req2CAD': {'url':'https://huggingface.co/datasets/QianzhiJing/Req2CAD','license':'CC-BY-4.0','author':'Qianzhi Jing et al.','annotation_origin':'VLM/LLM inferred, not engineering validation'},
 'paper': {'url':'https://doi.org/10.1145/3772318.3791949','filtered_components_reported':128873,'raw_rows_reported':175978},
 'DeepCAD': {'url':'https://github.com/rundiwu/DeepCAD','license_note':'Repository code MIT; verify original CAD/data terms separately.'},
}

def uid(value: str) -> str:
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}/\d{8}',value):
        raise BrainError('FS_UID','Expected the exact DeepCAD UID: 0000/00000000.')
    return value

def bounded_int(n: int, lo: int, hi: int, label: str) -> int:
    if isinstance(n,bool) or not isinstance(n,int) or not lo <= n <= hi:
        raise BrainError('FS_ARGUMENT',f'{label} must be an integer in [{lo}, {hi}].')
    return n

def finite(v, label='number', positive=False):
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or (positive and v<=0):
        raise BrainError('FS_NUMBER',f'Invalid {label}.')
    return float(v)

def json_load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'),parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))

def atomic_json(path: Path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(canonical(data),encoding='utf-8')
        os.replace(tmp,path)
    finally: tmp.unlink(missing_ok=True)

def digest(data):
    return hashlib.sha256(canonical(data).encode()).hexdigest()

@contextlib.contextmanager
def write_lock(root: Path):
    """Cross-process lock. Crash locks are NOT silently stolen."""
    root.mkdir(parents=True,exist_ok=True)
    p=root/'.write.lock'
    try: fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError as exc: raise BrainError('FS_BUSY','Catalog is being modified. If the owner crashed, verify it is stopped before deleting .write.lock.') from exc
    try:
        with os.fdopen(fd,'w') as f: f.write(canonical({'pid':os.getpid(),'started':time.time()}))
        yield
    finally: p.unlink(missing_ok=True)

def trusted_file(path: Path, max_bytes: int):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
        raise BrainError('FS_FILE','Expected a regular file within the size limit.',{'path':str(path)})
    return path
