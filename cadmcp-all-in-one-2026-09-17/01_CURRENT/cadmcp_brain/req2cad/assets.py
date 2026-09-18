"""Explicit owner-side asset registration. Uncompressed TAR is indexed, not extracted.

CAD locations are joined by exact uid, never by fuzzy matching or file order.
"""
from __future__ import annotations
import hashlib, json, os, re, shutil, tarfile, uuid
from pathlib import Path,PurePosixPath
from .common import *

MAX_JSON=16*1024**2
MAX_STEP=256*1024**2

def file_uid(name):
    p=PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name: return None
    if len(p.parts)<2: return None
    candidate=p.parts[-2]+'/'+p.stem
    return candidate if re.fullmatch(r'\d{4}/\d{8}',candidate) else None


def attach_directory(catalog,root,kind,scale_to_mm,unit_basis,source_url,license_note,reference_only=False):
    """Owner CLI only. No arbitrary path registration is exposed to the LLM."""
    root=Path(root).expanduser().resolve();scale_to_mm=finite(scale_to_mm,positive=True)
    if kind not in ('deepcad_json','step') or not root.is_dir() or not unit_basis.strip(): raise BrainError('FS_ASSET','Specify directory, kind, explicit scale and unit evidence.')
    suffixes={'.json'} if kind=='deepcad_json' else {'.step','.stp'}
    linked=0;unmatched=0;seen=set()
    with write_lock(catalog.root),catalog.connect() as db:
        for p in sorted(root.rglob('*')):
            if not p.is_file() or p.suffix.lower() not in suffixes: continue
            if any(a.is_symlink() for a in [p,*p.parents] if a!=root.parent):
                raise BrainError('FS_ASSET','Symbolic links in source assets are not accepted.')
            key=file_uid(p.relative_to(root).as_posix())
            if key is None: continue
            if key in seen: raise BrainError('FS_ASSET_DUPLICATE','Multiple files map to one UID; no registry changes committed.',{'uid':key})
            seen.add(key)
            if not db.execute('SELECT 1 FROM cases WHERE uid=?',(key,)).fetchone(): unmatched+=1;continue
            trusted_file(p,MAX_JSON if kind=='deepcad_json' else MAX_STEP)
            st=p.stat();sha=file_hash(p)
            if (p.stat().st_size,p.stat().st_mtime_ns)!=(st.st_size,st.st_mtime_ns): raise BrainError('FS_CHANGED','Source changed while registering.')
            old=db.execute('SELECT * FROM assets WHERE uid=?',(key,)).fetchone()
            if old and (old['sha256']!=sha or old['scale_to_mm']!=scale_to_mm or bool(old['reference_only'])!=reference_only): db.execute('DELETE FROM geometry WHERE uid=?',(key,))
            db.execute('INSERT OR REPLACE INTO assets VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
              (key,kind,str(p),None,sha,st.st_size,st.st_mtime_ns,scale_to_mm,unit_basis,source_url,license_note,int(reference_only)));linked+=1
        db.commit()
    return {'linked':linked,'unmatched_files':unmatched,'kind':kind,'unit_basis':unit_basis}


def _attach_flat_tar(catalog,path,scale_to_mm,unit_basis,source_url,license_note,reference_only=False):
    """Read the official uncompressed data.tar; retain original JSONs in-place."""
    path=trusted_file(Path(path).resolve(),64*1024**3);scale_to_mm=finite(scale_to_mm,positive=True)
    if not unit_basis.strip(): raise BrainError('FS_UNITS','Explicit units evidence is required.')
    st=path.stat();archive_hash=file_hash(path);linked=0;unmatched=0;duplicates=set()
    with write_lock(catalog.root),catalog.connect() as db,tarfile.open(path,'r:') as tar:
        for member in tar:
            if not member.name.endswith('.json') or 'cad_json' not in PurePosixPath(member.name).parts: continue
            key=file_uid(member.name)
            if not key: raise BrainError('FS_ARCHIVE','Unsafe or malformed CAD member name.')
            if key in duplicates: raise BrainError('FS_ARCHIVE','Duplicate UID in archive.',{'uid':key})
            duplicates.add(key)
            if not member.isfile() or member.issym() or member.islnk() or member.size>MAX_JSON: raise BrainError('FS_ARCHIVE','Non-regular or oversized CAD member.')
            if not db.execute('SELECT 1 FROM cases WHERE uid=?',(key,)).fetchone(): unmatched+=1;continue
            f=tar.extractfile(member)
            if f is None: raise BrainError('FS_ARCHIVE','Could not read member.')
            data=f.read(MAX_JSON+1);sha=hashlib.sha256(data).hexdigest()
            old=db.execute('SELECT * FROM assets WHERE uid=?',(key,)).fetchone()
            if old and (old['sha256']!=sha or old['scale_to_mm']!=scale_to_mm or bool(old['reference_only'])!=reference_only): db.execute('DELETE FROM geometry WHERE uid=?',(key,))
            # Store exact seek position and archive file identity. No extractall/path traversal.
            locator=canonical({'name':member.name,'offset_data':member.offset_data,'size':member.size,'archive_sha256':archive_hash})
            db.execute('INSERT OR REPLACE INTO assets VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
               (key,'deepcad_tar',str(path),locator,sha,st.st_size,st.st_mtime_ns,scale_to_mm,unit_basis,source_url,license_note,int(reference_only)));linked+=1
        if path.stat().st_size!=st.st_size or path.stat().st_mtime_ns!=st.st_mtime_ns: raise BrainError('FS_CHANGED','Archive changed during registration.')
        db.commit()
    return {'linked':linked,'unmatched_files':unmatched,'archive_sha256':archive_hash,'units_basis':unit_basis}



def _safe_member_name(name):
    # Names inside an archive are POSIX paths irrespective of the host OS.
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name or '\x00' in name:
        raise BrainError('FS_ARCHIVE', 'Unsafe member path; nothing is extracted.', {'name': name[:160]})
    return p


def prepare_cad_archive(path, cache_root, *, max_expanded_bytes=32*1024**3,
                        max_members=1_000_000, max_depth=3):
    """Normalize flat/nested TAR and compressed TAR by content, not file extension.

    Some data distributions wrap cad_json.tar.gz inside data.tar(.gz). Indexing
    compressed offsets as raw seek positions silently reads the wrong bytes.
    We stream regular CAD JSON members into a deterministic uncompressed TAR;
    all source bytes remain untouched. No pickle/H5 execution or extractall.
    Cache identity includes the exact source SHA and a normalization version.
    """
    import io, tempfile
    from contextlib import closing
    path = trusted_file(Path(path).resolve(), 64*1024**3)
    if not isinstance(max_expanded_bytes, int) or max_expanded_bytes <= 0:
        raise BrainError('FS_ARCHIVE', 'A positive extraction budget is required.')
    before = path.stat(); source_sha = file_hash(path)
    cache_root = Path(cache_root); cache_root.mkdir(parents=True, exist_ok=True)
    key = digest({'sha256': source_sha, 'normalizer': 1})
    target = cache_root / (key + '.tar'); receipt_path = cache_root / (key + '.json')
    if target.exists() and receipt_path.exists():
        receipt = json_load(receipt_path)
        if receipt.get('source_sha256') == source_sha and file_hash(target) == receipt.get('normalized_sha256'):
            return target, receipt
        raise BrainError('FS_ARCHIVE_CACHE', 'Archive cache was changed; remove the affected cache explicitly.')
    tmp = cache_root / ('.'+uuid.uuid4().hex+'.tar')
    budget = {'expanded_bytes': 0, 'members': 0, 'json_members': 0, 'nested_archives': 0}
    seen = set()
    def charge(n):
        budget['expanded_bytes'] += n
        if budget['expanded_bytes'] > max_expanded_bytes:
            raise BrainError('FS_ARCHIVE_LIMIT', 'Archive expansion budget exceeded.')
    def visit(handle, depth, dest):
        if depth > max_depth:
            raise BrainError('FS_ARCHIVE_LIMIT', 'Nested archive depth limit exceeded.')
        try:
            archive = tarfile.open(fileobj=handle, mode='r|*')
        except tarfile.TarError as exc:
            raise BrainError('FS_ARCHIVE_FORMAT', 'Not a supported TAR/compressed TAR stream.') from exc
        with archive:
            for member in archive:
                budget['members'] += 1
                if budget['members'] > max_members:
                    raise BrainError('FS_ARCHIVE_LIMIT', 'Too many archive entries.')
                part = _safe_member_name(member.name)
                if member.isdir(): continue
                if not member.isfile() or member.issym() or member.islnk():
                    raise BrainError('FS_ARCHIVE', 'Links/devices/nonregular members are not accepted.')
                name = part.name.lower()
                is_json = name.endswith('.json') and file_uid(member.name) is not None
                is_nested = name.endswith(('.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tar.xz'))
                # Ignore vector/point-cloud payloads: only cad_json nested archives
                # and neutral data wrappers are potentially relevant.
                if is_nested and not ('cad_json' in name or name in ('data.tar','data.tar.gz','data.tgz')):
                    continue
                if not is_json and not is_nested:
                    # A JSON below cad_json with an invalid uid is a data error.
                    if name.endswith('.json') and 'cad_json' in part.parts:
                        raise BrainError('FS_ARCHIVE', 'Malformed CAD UID in archive.')
                    continue
                if member.size < 0 or member.size > (MAX_JSON if is_json else max_expanded_bytes):
                    raise BrainError('FS_ARCHIVE_LIMIT', 'Oversized member.')
                stream = archive.extractfile(member)
                if stream is None: raise BrainError('FS_ARCHIVE', 'Unreadable member.')
                if is_json:
                    key_uid = file_uid(member.name)
                    if key_uid in seen:
                        raise BrainError('FS_ARCHIVE', 'Duplicate UID in archive.', {'uid': key_uid})
                    seen.add(key_uid)
                    raw = stream.read(MAX_JSON + 1); charge(len(raw))
                    if len(raw) != member.size or len(raw) > MAX_JSON:
                        raise BrainError('FS_ARCHIVE', 'Truncated or oversized CAD member.')
                    info = tarfile.TarInfo('cad_json/' + key_uid + '.json')
                    info.size = len(raw); info.mtime = 0; info.mode = 0o644
                    dest.addfile(info, io.BytesIO(raw)); budget['json_members'] += 1
                else:
                    budget['nested_archives'] += 1
                    # Spooled file supports recursive compression parsers without
                    # loading a multi-GB nested archive into RAM.
                    with tempfile.TemporaryFile(dir=cache_root) as nested:
                        remaining = member.size
                        while remaining:
                            block = stream.read(min(1024**2, remaining))
                            if not block: raise BrainError('FS_ARCHIVE', 'Truncated nested archive.')
                            charge(len(block)); nested.write(block); remaining -= len(block)
                        nested.seek(0); visit(nested, depth + 1, dest)
    try:
        with path.open('rb') as src, tarfile.open(tmp, 'w', format=tarfile.PAX_FORMAT) as dest:
            visit(src, 0, dest)
        if not budget['json_members']:
            raise BrainError('FS_ARCHIVE_EMPTY', 'No raw CAD JSON records found; no asset registry was changed.')
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or file_hash(path) != source_sha:
            raise BrainError('FS_CHANGED', 'Source archive changed during normalization.')
        normalized_sha = file_hash(tmp)
        receipt = {'normalizer_version': 1, 'source_path': str(path), 'source_sha256': source_sha,
                   'source_bytes': before.st_size, 'normalized_sha256': normalized_sha, **budget}
        os.replace(tmp, target); atomic_json(receipt_path, receipt)
        return target, receipt
    except tarfile.TarError as exc:
        raise BrainError('FS_ARCHIVE_FORMAT', 'Corrupt or unsupported archive.') from exc
    finally:
        tmp.unlink(missing_ok=True)


def attach_tar(catalog,path,scale_to_mm,unit_basis,source_url,license_note,reference_only=False):
    """Accept nested/compressed distribution; index only normalized raw offsets."""
    # Normalization cache has a distinct lock from the catalog's write transaction.
    cache_root = catalog.root / 'archive-cache'
    cache_root.mkdir(parents=True, exist_ok=True)
    with write_lock(cache_root):
        flat, receipt = prepare_cad_archive(path, cache_root)
    result = _attach_flat_tar(catalog, flat, scale_to_mm, unit_basis, source_url,
                              license_note, reference_only)
    return {**result, 'source_archive_sha256': receipt['source_sha256'],
            'normalization': receipt, 'normalized_path': str(flat)}

def read_asset(asset):
    path=Path(asset['path']);st=path.stat()
    if path.is_symlink() or not path.is_file() or st.st_size!=asset['size'] or st.st_mtime_ns!=asset['mtime_ns']:
        raise BrainError('FS_ASSET_CHANGED','Re-register changed/missing source asset.')
    if asset['kind']=='deepcad_tar':
        loc=json.loads(asset['member']);size=loc['size']
        if size>MAX_JSON or loc['offset_data']<0: raise BrainError('FS_ARCHIVE','Invalid member bounds.')
        with path.open('rb') as f: f.seek(loc['offset_data']);data=f.read(size)
    else:
        trusted_file(path,MAX_STEP if asset['kind']=='step' else MAX_JSON);data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=asset['sha256']: raise BrainError('FS_ASSET_CHANGED','CAD content checksum mismatch.')
    return data


def _http_status(response):
    return int(getattr(response,'status',None) or response.getcode())

def _http_header(response,name):
    headers=getattr(response,'headers',None)
    if headers is None: return None
    return headers.get(name) or headers.get(name.lower())

def _declared_size(response,status,start):
    if status==206:
        cr=(_http_header(response,'Content-Range') or '').strip()
        m=re.fullmatch(r'bytes\s+(\d+)-(\d+)/(\d+|\*)',cr)
        if not m: return None
        if int(m.group(1))!=start:
            raise BrainError('FS_DOWNLOAD','Resume offset mismatch.',{'expected':start,'got':int(m.group(1))})
        return None if m.group(3)=='*' else int(m.group(3))
    if status==200:
        cl=_http_header(response,'Content-Length')
        return int(cl) if cl else None
    return None

def download_file(url,destination,expected_sha256=None,max_bytes=2*1024**3):
    """CLI-only download. Resumes from a stable .partial via HTTP Range.

    A complete destination with a matching SHA is reused. Failed transfers keep
    the partial; they are not deleted. No user-supplied URL is accepted by MCP
    tools. TLS verification is not disabled.
    """
    import urllib.error, urllib.request
    from http.client import IncompleteRead
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.is_file():
        if not expected_sha256 or file_hash(destination)==expected_sha256: return str(destination)
        destination.unlink()
    partial=destination.with_name(destination.name+'.partial')
    start=partial.stat().st_size if partial.is_file() else 0
    if start>max_bytes: raise BrainError('FS_DOWNLOAD','Partial download exceeded configured size limit.')
    headers={'User-Agent':'cadmcp-req2cad/0.3.3'}
    if start: headers['Range']=f'bytes={start}-'
    n=start;h=hashlib.sha256();expected_total=None
    if start:
        with partial.open('rb') as existing:
            while True:
                block=existing.read(1024**2)
                if not block: break
                h.update(block)
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=120) as r:
            status=_http_status(r)
            if start and status==200:
                start=0;n=0;h=hashlib.sha256();partial.unlink(missing_ok=True)
            elif start and status!=206:
                raise BrainError('FS_DOWNLOAD','Resume was refused by the server.',{'status':status})
            expected_total=_declared_size(r,status,start)
            if expected_total is not None and expected_total>max_bytes:
                raise BrainError('FS_DOWNLOAD','Download exceeded configured size limit.')
            with partial.open('ab' if start else 'wb') as f:
                while True:
                    try: block=r.read(1024**2)
                    except IncompleteRead as exc:
                        extra=exc.partial or b''
                        if extra:
                            n+=len(extra)
                            if n>max_bytes: raise BrainError('FS_DOWNLOAD','Download exceeded configured size limit.')
                            f.write(extra);h.update(extra)
                        raise BrainError('FS_DOWNLOAD','Download interrupted; retry to resume.',{'received':n,'partial':str(partial)}) from exc
                    if not block: break
                    n+=len(block)
                    if n>max_bytes: raise BrainError('FS_DOWNLOAD','Download exceeded configured size limit.')
                    f.write(block);h.update(block)
    except BrainError:
        raise
    except (urllib.error.URLError,TimeoutError,OSError) as exc:
        raise BrainError('FS_DOWNLOAD','Download interrupted; retry to resume.',{'received':n,'partial':str(partial)}) from exc
    if n==0:
        partial.unlink(missing_ok=True);raise BrainError('FS_DOWNLOAD','Empty download.')
    if expected_total is not None and n!=expected_total:
        raise BrainError('FS_DOWNLOAD','Download interrupted; retry to resume.',{'received':n,'expected':expected_total,'partial':str(partial)})
    if expected_sha256 and h.hexdigest()!=expected_sha256:
        partial.unlink(missing_ok=True)
        raise BrainError('FS_HASH','Downloaded data differs from pinned source; no file installed.')
    os.replace(partial,destination)
    return str(destination)
