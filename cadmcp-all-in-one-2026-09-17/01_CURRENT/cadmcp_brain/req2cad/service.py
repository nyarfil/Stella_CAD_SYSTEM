from __future__ import annotations
import json, os, shutil, subprocess, sys, uuid
from pathlib import Path
from .catalog import Catalog
from .common import *
from .assets import read_asset

class Service:
    def __init__(self,catalog: Catalog):self.catalog=catalog
    def materialize(self,key,timeout_seconds=60):
        uid(key);bounded_int(timeout_seconds,5,180,'timeout_seconds')
        with write_lock(self.catalog.root):
            case=self.catalog.case(key);asset=case['asset']
            if not asset: raise BrainError('FS_CAD_MISSING','No exact-UID CAD source has been registered.',{'uid':key})
            content=read_asset(asset)
            identity=digest({'uid':key,'sha256':asset['sha256'],'scale':asset['scale_to_mm'],'reference_only':bool(asset['reference_only']),'engine':'native-replay-v4'})
            target=self.catalog.root/'geometry'/identity
            existing=target/'result.json'
            if existing.exists():
                value=json_load(existing)
                if value.get('ok'):
                    # Cached geometry must still match all exported files.
                    for name,meta in value['result']['exports'].items():
                        if file_hash(target/name)!=meta['sha256']: raise BrainError('FS_CACHE_CHANGED','Cached CAD export changed; remove the affected geometry cache and re-run.')
                    self._record(key,asset,value['result'],target);return self.evidence(key)
            tmp=self.catalog.root/'geometry'/('build-'+uuid.uuid4().hex);tmp.mkdir(parents=True)
            ext='.step' if asset['kind']=='step' else '.json';source=tmp/('source'+ext);source.write_bytes(content)
            config={'source':str(source),'kind':asset['kind'],'sha256':asset['sha256'],'out':str(tmp),'scale_to_mm':asset['scale_to_mm'],'reference_only':bool(asset['reference_only'])}
            atomic_json(tmp/'config.json',config)
            try:
                proc=subprocess.run([sys.executable,'-m','cadmcp_brain.req2cad.worker',str(tmp/'config.json')],
                    capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout_seconds)
                (tmp/'worker.stderr.log').write_text(proc.stderr,encoding='utf-8')
                if proc.returncode!=0 or not (tmp/'result.json').exists():
                    info=json_load(tmp/'result.json') if (tmp/'result.json').exists() else {'exit':proc.returncode}
                    raise BrainError('FS_CAD_FAILED','CAD replay/inspection failed; not replaced with a primitive.',{'diagnostic':info,'log':str(tmp/'worker.stderr.log')})
                value=json_load(tmp/'result.json')
                if not value['ok']: raise BrainError('FS_CAD_FAILED','Worker rejected CAD.',value)
                if read_asset(asset)!=content: raise BrainError('FS_ASSET_CHANGED','Source changed during build.')
                if target.exists(): shutil.rmtree(target)
                os.replace(tmp,target)
                self._record(key,asset,value['result'],target)
            except subprocess.TimeoutExpired as exc:
                raise BrainError('FS_CAD_TIMEOUT','Geometry worker exceeded the time budget; no successful geometry recorded.') from exc
        return self.evidence(key)

    def _record(self,key,asset,record,target):
        record={**record,'cache_relative':target.relative_to(self.catalog.root).as_posix(),'unit_basis':asset['unit_basis']}
        with self.catalog.connect() as db:
            db.execute('INSERT OR REPLACE INTO geometry VALUES(?,?,?)',(key,asset['sha256'],canonical(record)));db.commit()

    def evidence(self,key):
        c=self.catalog.case(key)
        if c['asset']: read_asset(c['asset']) # do not publish stale measured geometry
        g=c['geometry']
        if g:
            from ..util import safe_path
            folder=safe_path(self.catalog.root,g['cache_relative'])
            for name,meta in g['exports'].items():
                p=safe_path(folder,name)
                if file_hash(p)!=meta['sha256']: raise BrainError('FS_CACHE_CHANGED','Geometry cache changed.')
                meta['absolute_path']=str(p)
        return {'evidence_digest':digest({'citation':c['citation'],'cad_sha256':c['asset']['sha256'] if c['asset'] else None,'scale':c['asset']['scale_to_mm'] if c['asset'] else None,'reference_only':bool(c['asset']['reference_only']) if c['asset'] else None,'geometry':{k:v for k,v in g.items() if k!='cache_relative'} if g else None}),'uid':key,'function_keywords':c['function_keywords'],'function_description':c['description'],
            'function_provenance':c['annotation_origin'],'citation':c['citation'],
            'geometry':g,'cad_source':c['asset'],
            'must_verify_when_adapting':['actual switch/shaft direction','interface dimensions','assembly path','clearance over motion','material/process','load path','fatigue/creep'],
            'not_proven':['function correctness','printability','strength','mouse applicability']}

    def compare(self,uid_a,uid_b):
        from .geometry import compare_records
        a=self.evidence(uid_a);b=self.evidence(uid_b)
        if not a['geometry'] or not b['geometry']:raise BrainError('FS_GEOMETRY_MISSING','Materialize both cases before comparing real topology.')
        return {'a':uid_a,'b':uid_b,**compare_records(a['geometry'],b['geometry'])}

    def portfolio(self,keys,mode='topology',limit=6):
        """Deterministic farthest-first diversity over measured candidates only."""
        if not isinstance(keys,list) or not 1<=len(keys)<=50:raise BrainError('FS_ARGUMENT','Provide 1–50 retrieved UIDs.')
        bounded_int(limit,1,12,'limit')
        if mode not in ('topology','geometry'):raise BrainError('FS_ARGUMENT','Choose topology or geometry.')
        from .geometry import compare_records
        keys=list(dict.fromkeys(uid(k) for k in keys));records={};missing=[]
        for key in keys:
            e=self.evidence(key)
            if e['geometry']:records[key]=e['geometry']
            else:missing.append(key)
        if not records:return {'selected':[],'unmeasured':missing,'mode':mode}
        selected=[next(k for k in keys if k in records)];remaining=set(records)-set(selected)
        def distance(a,b):
            r=compare_records(records[a],records[b]);return 1-r['topology']['normalized_similarity'] if mode=='topology' else r['geometry']['euclidean_distance']
        while remaining and len(selected)<limit:
            pick=sorted(remaining,key=lambda k:(-min(distance(k,s) for s in selected),k))[0]
            selected.append(pick);remaining.remove(pick)
        return {'selected':selected,'unmeasured':missing,'mode':mode,'algorithm':'farthest-first from first retrieved case; not paper t-SNE/k-means visualization'}
