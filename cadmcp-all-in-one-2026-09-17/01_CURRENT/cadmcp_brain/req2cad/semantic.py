"""Keyword-level dense cosine retrieval, not text search disguised as embeddings."""
from __future__ import annotations
import contextlib, hashlib, os, shutil, uuid
from pathlib import Path
import numpy as np
from .common import *
from .catalog import Catalog

DEFAULT_MODEL='Qwen/Qwen3-Embedding-4B'
QUERY_INSTRUCTION='Given a mechanical function, retrieve synonymous function labels of CAD components.'

class SentenceEncoder:
    """Owner installs weights explicitly in CLI. Server only opens local snapshots.

    Revision + model file content hashes identify an encoder. No remote Python is run.
    """
    def __init__(self,model_path,device='cpu',batch_size=8,max_length=128,query_mode='req2cad_native'):
        from sentence_transformers import SentenceTransformer
        import torch
        from importlib.metadata import version
        dtype = (torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float16) if str(device).startswith('cuda') else torch.float32
        if query_mode not in ('req2cad_native','mechanical_instruction'):raise BrainError('FS_MODEL_MODE','Unsupported query encoding mode.')
        self.query_mode=query_mode
        self.model_path=Path(model_path).resolve()
        lock=json_load(self.model_path/'cadmcp_model_lock.json')
        self.identity=lock['identity']
        self.model=SentenceTransformer(str(self.model_path),device=device,local_files_only=True,trust_remote_code=False,model_kwargs={'torch_dtype':dtype})
        self.model.max_seq_length=max_length
        self.batch_size=batch_size
        self.identity={**self.identity,'max_length':max_length,'query_mode':query_mode,'query_instruction':QUERY_INSTRUCTION if query_mode=='mechanical_instruction' else '','normalize':True,'dtype':str(dtype),'sentence_transformers_version':version('sentence-transformers'),'transformers_version':version('transformers')}
    def encode(self,texts,query=False):
        values=['Instruct: '+QUERY_INSTRUCTION+'\nQuery:'+t for t in texts] if query and self.query_mode=='mechanical_instruction' else texts
        return self.model.encode(values,batch_size=self.batch_size,convert_to_numpy=True,normalize_embeddings=True,show_progress_bar=False,prompt='')


def install_model(destination,model_id=DEFAULT_MODEL,revision=None):
    """Network is allowed ONLY in this explicitly invoked owner-side command."""
    from huggingface_hub import HfApi,snapshot_download
    destination=Path(destination).resolve()
    commit=HfApi().model_info(model_id,revision=revision).sha
    snapshot_download(repo_id=model_id,revision=commit,local_dir=str(destination),
        ignore_patterns=['*.bin','*.pt','*.pth','*.onnx','*.gguf'])
    records={}
    for p in sorted(destination.rglob('*')):
        if p.is_file() and '.cache' not in p.parts and p.name!='cadmcp_model_lock.json':
            records[p.relative_to(destination).as_posix()]=file_hash(p)
    if not any(n.endswith('.safetensors') for n in records): raise BrainError('FS_MODEL','No safetensors weights downloaded.')
    identity={'model_id':model_id,'revision':commit,'file_manifest_sha256':digest(records)}
    atomic_json(destination/'cadmcp_model_lock.json',{'identity':identity,'files':records})
    return identity


def verify_model(path):
    path=Path(path);m=json_load(path/'cadmcp_model_lock.json')
    for relative,expected in m['files'].items():
        from ..util import safe_path
        p=safe_path(path,relative)
        if file_hash(p)!=expected: raise BrainError('FS_MODEL_CHANGED','Model file differs from installed lock.',{'file':relative})
    return m['identity']


def normalized(value,rows):
    array=np.asarray(value,dtype=np.float32)
    if array.ndim!=2 or array.shape[0]!=rows or not 1<=array.shape[1]<=8192 or not np.isfinite(array).all():
        raise BrainError('FS_EMBEDDING','Encoder returned invalid shape/non-finite data.')
    norms=np.linalg.norm(array,axis=1,keepdims=True)
    if np.any(norms<1e-12): raise BrainError('FS_EMBEDDING','Zero embeddings are invalid.')
    return array/norms

class SemanticIndex:
    def __init__(self,catalog: Catalog):
        self.catalog=catalog;self.root=catalog.root/'semantic'
    def build(self,encoder,batch_size=64):
        bounded_int(batch_size,1,512,'batch_size')
        words=self.catalog.keywords()
        if not words: raise BrainError('FS_EMPTY','No functional labels to embed.')
        state=self.catalog.status();dataset=state['meta']['dataset_sha256'];word_digest=digest(words)
        identity=encoder.identity
        # A build resumes only when source, ordering and encoder identity match exactly.
        checkpoint=self.catalog.root/'semantic.build'
        with write_lock(self.catalog.root):
            expected={'dataset_sha256':dataset,'keyword_digest':word_digest,'encoder':identity,'rows':len(words)}
            meta_path=checkpoint/'checkpoint.json'
            if meta_path.exists():
                cp=json_load(meta_path)
                if any(cp.get(k)!=v for k,v in expected.items()):
                    raise BrainError('FS_INDEX_BUILD_MISMATCH','Stale build checkpoint: move/delete semantic.build only after confirming no build is running.')
            else:
                checkpoint.mkdir(exist_ok=True)
                first=normalized(encoder.encode([w[1] for w in words[:batch_size]],query=False),min(batch_size,len(words)))
                dim=first.shape[1]
                matrix=np.lib.format.open_memmap(checkpoint/'vectors.npy',mode='w+',dtype='float32',shape=(len(words),dim))
                matrix[:len(first)]=first;matrix.flush();del matrix
                cp={**expected,'dimensions':dim,'completed':len(first)};atomic_json(meta_path,cp)
            matrix=np.lib.format.open_memmap(checkpoint/'vectors.npy',mode='r+')
            if matrix.shape!=(len(words),cp['dimensions']): raise BrainError('FS_INDEX_BUILD_MISMATCH','Checkpoint shape mismatch.')
            try:
                for i in range(cp['completed'],len(words),batch_size):
                    batch=words[i:i+batch_size]
                    encoded=normalized(encoder.encode([w[1] for w in batch],query=False),len(batch))
                    if encoded.shape[1]!=matrix.shape[1]: raise BrainError('FS_EMBEDDING','Encoder dimension changed.')
                    matrix[i:i+len(batch)]=encoded;matrix.flush()
                    cp['completed']=i+len(batch);atomic_json(meta_path,cp)
                if self.catalog.status()['meta']['dataset_sha256']!=dataset: raise BrainError('FS_CHANGED','Dataset changed during indexing.')
            finally: del matrix
            atomic_json(checkpoint/'keywords.json',words)
            manifest={**expected,'dimensions':cp['dimensions'],'dtype':'float32','complete':True,
              'vectors_sha256':file_hash(checkpoint/'vectors.npy'),'keywords_sha256':file_hash(checkpoint/'keywords.json'),
              'method':'keyword embeddings + cosine + matched-function-count aggregation',
              'paper_threshold':0.7,'threshold_note':'Original paper threshold; this prompt/environment has not been calibrated against original results.'}
            atomic_json(checkpoint/'manifest.json',manifest)
            # Keep installed index available on errors. Same-volume rename; readers reopen per request.
            backup=self.catalog.root/('semantic.old.'+uuid.uuid4().hex)
            if self.root.exists(): os.replace(self.root,backup)
            try: os.replace(checkpoint,self.root)
            except BaseException:
                if backup.exists(): os.replace(backup,self.root)
                raise
            if backup.exists(): shutil.rmtree(backup)
            return manifest

    def search(self,functions,encoder,threshold=0.7,limit=20,require_asset=False):
        self.catalog._queries(functions);bounded_int(limit,1,50,'limit')
        threshold=finite(threshold)
        if not -1<=threshold<=1: raise BrainError('FS_ARGUMENT','Cosine threshold must be in [-1,1].')
        if not (self.root/'manifest.json').exists(): raise BrainError('FS_SEMANTIC_NOT_READY','Build real embeddings first. No silent lexical fallback.')
        m=json_load(self.root/'manifest.json')
        if m['dataset_sha256']!=self.catalog.status()['meta']['dataset_sha256'] or m['encoder']!=encoder.identity:
            raise BrainError('FS_INDEX_STALE','Dataset or encoder identity differs from this index.')
        if file_hash(self.root/'keywords.json')!=m['keywords_sha256']: raise BrainError('FS_INDEX_CHANGED','Keyword table changed.')
        words=json_load(self.root/'keywords.json')
        # Verify even unit-normalized tampering; integrity is not just a shape/norm test.
        if file_hash(self.root/'vectors.npy')!=m['vectors_sha256']: raise BrainError('FS_INDEX_CHANGED','Embedding file checksum changed.')
        matrix=np.load(self.root/'vectors.npy',mmap_mode='r',allow_pickle=False)
        if matrix.shape!=(len(words),m['dimensions']) or matrix.dtype!=np.float32: raise BrainError('FS_INDEX_CHANGED','Vector matrix shape/type mismatch.')
        q=normalized(encoder.encode(functions,query=True),len(functions))
        if q.shape[1]!=m['dimensions']: raise BrainError('FS_EMBEDDING','Query embedding dimension mismatch.')
        hits=[[] for _ in functions]
        for i in range(0,len(words),4096):
            block=np.asarray(matrix[i:i+4096])
            if not np.isfinite(block).all() or not np.allclose(np.linalg.norm(block,axis=1),1,atol=1e-3):
                raise BrainError('FS_INDEX_CHANGED','Stored embeddings must remain finite and unit-normalized.')
            similarities=block@q.T
            for j in range(len(functions)):
                for k in np.flatnonzero(similarities[:,j]>threshold):
                    fid,word=words[i+int(k)];hits[j].append((fid,float(similarities[k,j]),word))
        result=self.catalog.aggregate(functions,hits,limit,require_asset,threshold=threshold)
        result['encoder']=m['encoder'];result['keyword_matches_per_query']=[len(h) for h in hits]
        result['index_manifest_sha256']=file_hash(self.root/'manifest.json')
        return result

    def verify(self):
        m=json_load(self.root/'manifest.json')
        for key,name in [('vectors_sha256','vectors.npy'),('keywords_sha256','keywords.json')]:
            if file_hash(self.root/name)!=m[key]: raise BrainError('FS_INDEX_CHANGED',f'{name} checksum mismatch')
        return {'checksums_verified':True,'manifest':m}

    def search_groups(self, groups, encoder, threshold=.7, limit=12, require_asset=True):
        """One index/model pass for multiple OR-paraphrases of distinct functions.

        ``groups`` is [{id, queries:[...]}]. A keyword's score for a function is
        max(cosine(query_variant, keyword)); variants never add coverage votes.
        This avoids rereading a large vector index once for every paraphrase.
        """
        bounded_int(limit,1,50,'limit');threshold=finite(threshold)
        if not -1<=threshold<=1:raise BrainError('FS_ARGUMENT','Invalid cosine threshold.')
        if not isinstance(groups,list) or not 1<=len(groups)<=12:raise BrainError('FS_QUERY','Provide 1–12 function groups.')
        if len({g['id'] for g in groups})!=len(groups):raise BrainError('FS_QUERY','Duplicate function group IDs.')
        texts=[];indices=[]
        for group in groups:
            self.catalog._queries(group['queries'])
            if len(group['queries'])>8:raise BrainError('FS_QUERY','At most 8 variants per function.')
            idx=[]
            for q in group['queries']:
                if q not in texts:texts.append(q)
                idx.append(texts.index(q))
            indices.append(idx)
        if not (self.root/'manifest.json').is_file():raise BrainError('FS_SEMANTIC_NOT_READY','Real index missing. No lexical substitute was used.')
        m=json_load(self.root/'manifest.json')
        if m['dataset_sha256']!=self.catalog.status()['meta']['dataset_sha256'] or m['encoder']!=encoder.identity:
            raise BrainError('FS_INDEX_STALE','Dataset or encoder identity mismatch.')
        for name,key in [('keywords.json','keywords_sha256'),('vectors.npy','vectors_sha256')]:
            if file_hash(self.root/name)!=m[key]:raise BrainError('FS_INDEX_CHANGED','Index checksum mismatch.')
        words=json_load(self.root/'keywords.json');matrix=np.load(self.root/'vectors.npy',mmap_mode='r',allow_pickle=False)
        if matrix.shape!=(len(words),m['dimensions']) or matrix.dtype!=np.float32:raise BrainError('FS_INDEX_CHANGED','Index shape/type changed.')
        query=normalized(encoder.encode(texts,query=True),len(texts))
        if query.shape[1]!=m['dimensions']:raise BrainError('FS_EMBEDDING','Query dimensions differ from index.')
        hits=[[] for _ in groups];best_variant=[{} for _ in groups]
        for offset in range(0,len(words),4096):
            block=np.asarray(matrix[offset:offset+4096])
            if not np.isfinite(block).all() or not np.allclose(np.linalg.norm(block,axis=1),1,atol=1e-3):raise BrainError('FS_INDEX_CHANGED','Corrupt vector block.')
            sim=block@query.T
            for gi,qi in enumerate(indices):
                local=sim[:,qi];winner=np.argmax(local,axis=1);score=local[np.arange(len(local)),winner]
                for k in np.flatnonzero(score>threshold):
                    fid,word=words[offset+int(k)];hits[gi].append((fid,float(score[k]),word))
                    best_variant[gi][word]=texts[qi[int(winner[k])]]
        result={}
        for gi,group in enumerate(groups):
            row=self.catalog.aggregate([group['id']],[hits[gi]],limit,require_asset,
                                       method='semantic_OR_paraphrases_max_cosine',threshold=threshold)
            for case in row['results']:
                for match in case['matched']:match['matched_query_variant']=best_variant[gi][match['matched_keyword']]
            row['query_variants']=group['queries'];result[group['id']]=row
        return {'groups':result,'encoder':m['encoder'],'encoded_query_count':len(texts),
                'index_scans':1,'method':'OR within each function; independent coverage across functions'}
