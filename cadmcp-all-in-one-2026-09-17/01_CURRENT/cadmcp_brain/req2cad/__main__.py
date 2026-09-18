"""Owner-side CLI: network and bulk indexing happen explicitly, outside MCP calls."""
from __future__ import annotations
import argparse,json,os,sys
from pathlib import Path
from .catalog import Catalog
from .common import *

def main(argv=None):
    p=argparse.ArgumentParser(description='Req2CAD full-data ingestion / semantic retrieval / real CAD + topology')
    p.add_argument('--root',type=Path,default=Path(os.environ.get('CADMCP_REQ2CAD_ROOT',str(Path.home()/'.cadmcp-brain'/'knowledge'/'req2cad'))))
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('status')
    sub.add_parser('download-annotations',help='Fetch pinned full CSV and ingest it; no fixture substitution')
    i=sub.add_parser('ingest');i.add_argument('csv',type=Path);i.add_argument('--source-url',default=SOURCES['Req2CAD']['url']);i.add_argument('--expected-sha256')
    a=sub.add_parser('attach-cad');a.add_argument('path',type=Path);a.add_argument('--kind',choices=['deepcad_json','step','deepcad_tar'],required=True)
    a.add_argument('--scale-to-mm',type=float);a.add_argument('--unit-basis');a.add_argument('--reference-only',action='store_true',help='Unknown physical scale: inspect topology/normalized geometry only; do not expose physical mm metrics');a.add_argument('--source-url',default=SOURCES['DeepCAD']['url']);a.add_argument('--license-note',default='Original CAD/data terms must be checked separately from code license.')
    d=sub.add_parser('download-deepcad');d.add_argument('--max-gb',type=int,default=20)
    m=sub.add_parser('install-model');m.add_argument('--model',default='Qwen/Qwen3-Embedding-4B');m.add_argument('--revision');m.add_argument('--device',default='cuda');m.add_argument('--batch-size',type=int,default=8);m.add_argument('--query-mode',choices=['req2cad_native','mechanical_instruction'],default='req2cad_native')
    b=sub.add_parser('build-embeddings');b.add_argument('--batch-size',type=int,default=64)
    sub.add_parser('verify-index')
    s=sub.add_parser('search');s.add_argument('functions',nargs='+');s.add_argument('--mode',choices=['semantic','lexical'],default='semantic');s.add_argument('--threshold',type=float,default=0.7);s.add_argument('--limit',type=int,default=20);s.add_argument('--require-cad',action='store_true')
    k=sub.add_parser('case');k.add_argument('uid')
    g=sub.add_parser('materialize');g.add_argument('uid');g.add_argument('--timeout',type=int,default=60)
    batch=sub.add_parser('materialize-all');batch.add_argument('--limit',type=int,default=None);batch.add_argument('--timeout',type=int,default=60)
    c=sub.add_parser('compare');c.add_argument('a');c.add_argument('b')
    args=p.parse_args(argv);catalog=Catalog(args.root)
    try:
        from .assets import download_file,attach_directory,attach_tar
        from .service import Service
        if args.command=='status':out=catalog.status()
        elif args.command=='download-annotations':
            path=download_file(REQ_URL,catalog.root/'downloads'/'Req2CAD.csv',REQ_SHA256)
            out=catalog.ingest(path,expected_sha256=REQ_SHA256)
        elif args.command=='ingest':out=catalog.ingest(args.csv,args.source_url,args.expected_sha256)
        elif args.command=='download-deepcad':
            bounded_int(args.max_gb,1,64,'max-gb')
            path=download_file(DEEP_URL,catalog.root/'downloads'/'data.tar',max_bytes=args.max_gb*1024**3)
            out={'path':path,'sha256':file_hash(Path(path)),'next':'attach-cad --kind deepcad_tar; supply explicit source units; no automatic unit guess'}
        elif args.command=='attach-cad':
            if args.reference_only:
                args.scale_to_mm=1.;args.unit_basis='Uncalibrated source coordinates; structure reference only, not physical millimeters'
            elif args.scale_to_mm is None or not args.unit_basis: raise BrainError('FS_UNITS','Supply --reference-only OR explicit --scale-to-mm and --unit-basis.')
            if args.kind=='deepcad_tar':out=attach_tar(catalog,args.path,args.scale_to_mm,args.unit_basis,args.source_url,args.license_note,args.reference_only)
            else:out=attach_directory(catalog,args.path,args.kind,args.scale_to_mm,args.unit_basis,args.source_url,args.license_note,args.reference_only)
        elif args.command=='install-model':
            from .semantic import install_model
            dest=catalog.root/'models'/'embedding'
            out=install_model(dest,args.model,args.revision)
            atomic_json(catalog.root/'encoder_config.json',{'model_path':str(dest),'device':args.device,'batch_size':args.batch_size,'query_mode':args.query_mode})
        elif args.command in ('build-embeddings','verify-index','search'):
            from .semantic import SemanticIndex,SentenceEncoder,verify_model
            if args.command=='verify-index':out=SemanticIndex(catalog).verify()
            elif args.command=='search' and args.mode=='lexical':out=catalog.lexical(args.functions,args.limit,args.require_cad)
            else:
                conf=json_load(catalog.root/'encoder_config.json');verify_model(conf['model_path'])
                encoder=SentenceEncoder(conf['model_path'],conf['device'],conf['batch_size'],query_mode=conf.get('query_mode','req2cad_native'))
                if args.command=='build-embeddings':out=SemanticIndex(catalog).build(encoder,args.batch_size)
                else:out=SemanticIndex(catalog).search(args.functions,encoder,args.threshold,args.limit,args.require_cad)
        elif args.command=='case':out=catalog.case(args.uid)
        elif args.command=='materialize':out=Service(catalog).materialize(args.uid,args.timeout)
        elif args.command=='compare':out=Service(catalog).compare(args.a,args.b)
        elif args.command=='materialize-all':
            with catalog.connect() as db:keys=[r[0] for r in db.execute('SELECT a.uid FROM assets a JOIN cases c ON c.uid=a.uid LEFT JOIN geometry g ON g.uid=a.uid WHERE c.usable=1 AND g.uid IS NULL ORDER BY a.uid')]
            if args.limit is not None:bounded_int(args.limit,1,1000000,'limit');keys=keys[:args.limit]
            counts={'requested':len(keys),'succeeded':0,'failed':0};log=catalog.root/'bulk-build.jsonl'
            for key in keys:
                try:Service(catalog).materialize(key,args.timeout);rec={'uid':key,'ok':True};counts['succeeded']+=1
                except Exception as exc:rec={'uid':key,'ok':False,'error':str(exc)};counts['failed']+=1
                with log.open('a',encoding='utf-8') as f:f.write(canonical(rec)+'\n')
                print(canonical(rec),file=sys.stderr,flush=True)
            out={**counts,'log':str(log),'status':catalog.status()}
        print(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False));return 0
    except Exception as exc:
        error=exc.as_dict() if isinstance(exc,BrainError) else {'code':type(exc).__name__,'message':str(exc)}
        print(json.dumps({'ok':False,'error':error},ensure_ascii=False),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
