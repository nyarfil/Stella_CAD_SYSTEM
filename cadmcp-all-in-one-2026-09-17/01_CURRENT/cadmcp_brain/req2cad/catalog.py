"""Atomic CSV ingestion, normalized function edges, transparent source lineage."""
from __future__ import annotations
import ast, csv, json, os, re, sqlite3, uuid
from collections import defaultdict
from pathlib import Path
from .common import *

DDL='''
PRAGMA foreign_keys=ON;
CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE cases(uid TEXT PRIMARY KEY, description TEXT NOT NULL, raw_keywords TEXT NOT NULL,
 usable INTEGER NOT NULL, row_number INTEGER NOT NULL, annotation_origin TEXT NOT NULL);
CREATE TABLE functions(id INTEGER PRIMARY KEY, text TEXT UNIQUE NOT NULL);
CREATE TABLE case_functions(uid TEXT NOT NULL REFERENCES cases(uid),function_id INTEGER NOT NULL REFERENCES functions(id),
 PRIMARY KEY(uid,function_id));
CREATE INDEX cf_function ON case_functions(function_id,uid);
CREATE VIRTUAL TABLE function_fts USING fts5(text,content=functions,content_rowid=id,tokenize='unicode61');
CREATE TABLE assets(uid TEXT PRIMARY KEY REFERENCES cases(uid),kind TEXT NOT NULL,path TEXT NOT NULL,
 member TEXT,sha256 TEXT NOT NULL,size INTEGER NOT NULL,mtime_ns INTEGER NOT NULL,scale_to_mm REAL NOT NULL,
 unit_basis TEXT NOT NULL,source_url TEXT NOT NULL,license_note TEXT NOT NULL,reference_only INTEGER NOT NULL DEFAULT 0);
CREATE TABLE geometry(uid TEXT PRIMARY KEY REFERENCES cases(uid),source_sha256 TEXT NOT NULL,record TEXT NOT NULL);
CREATE TABLE rejected(row_number INTEGER NOT NULL,uid TEXT,reason TEXT NOT NULL);
'''

def parse_keywords(raw: str) -> list[str]:
    if len(raw)>24000: raise ValueError('keyword payload too large')
    try: value=json.loads(raw)
    except json.JSONDecodeError:
        # literal_eval, never eval; bounded length/depth below.
        value=ast.literal_eval(raw)
    if not isinstance(value,list): raise ValueError('keywords must be a list')
    result=[]
    def walk(items,depth=0):
        if depth>4 or len(items)>512: raise ValueError('keyword nesting/cardinality exceeds limit')
        for item in items:
            if isinstance(item,list): walk(item,depth+1)
            elif isinstance(item,str):
                word=' '.join(item.split()).casefold()
                if len(word)>400: raise ValueError('keyword too long')
                if word and word not in result: result.append(word)
            else: raise ValueError('non-string keyword')
    walk(value)
    return result

class ClosingConnection(sqlite3.Connection):
    def __exit__(self,*args):
        try:return super().__exit__(*args)
        finally:self.close()

class Catalog:
    def __init__(self,root):
        self.root=Path(root).expanduser().resolve()
        self.path=self.root/'catalog.sqlite'

    def connect(self):
        if not self.path.is_file(): raise BrainError('FS_NOT_READY','No full catalog installed. Run the Req2CAD CLI ingest/bootstrap; demo cards are not a substitute.')
        db=sqlite3.connect(self.path,timeout=10,factory=ClosingConnection)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def status(self):
        if not self.path.is_file(): return {'ready':False,'cases':0,'semantic_ready':False,'cad_assets_linked':0,'breps_measured':0,'sources':SOURCES}
        with self.connect() as db:
            meta={r['key']:json.loads(r['value']) for r in db.execute('SELECT * FROM meta')}
            cnt=lambda t:db.execute('SELECT count(*) FROM '+t).fetchone()[0]
            out={'ready':True,'cases':cnt('cases'),'function_labeled_cases':db.execute('SELECT count(*) FROM cases WHERE usable=1').fetchone()[0],
                 'distinct_functions':cnt('functions'),'function_case_edges':cnt('case_functions'),
                 'cad_assets_linked':cnt('assets'),'breps_measured':cnt('geometry'),
                 'labeled_breps_measured':db.execute('SELECT count(*) FROM geometry g JOIN cases c ON c.uid=g.uid WHERE c.usable=1').fetchone()[0],
                 'meta':meta,'sources':SOURCES}
        manifest=self.root/'semantic'/'manifest.json'
        out['semantic_ready']=False
        if manifest.exists():
            m=json_load(manifest);out['semantic_manifest']=m
            out['semantic_ready']=m.get('dataset_sha256')==meta.get('dataset_sha256') and m.get('complete') is True
        out['all_cad_joined']=out['cad_assets_linked']==out['cases'] and out['cases']>0
        out['all_breps_measured']=out['labeled_breps_measured']==out['function_labeled_cases'] and out['labeled_breps_measured']>0
        out['coverage_note']='Geometry counts are recorded builds; file integrity is rechecked when evidence is requested.'
        return out

    def ingest(self,csv_path,source_url=SOURCES['Req2CAD']['url'],expected_sha256=None):
        path=trusted_file(Path(csv_path).resolve(),1024**3)
        src_hash=file_hash(path)
        if expected_sha256 and src_hash!=expected_sha256:
            raise BrainError('FS_HASH','Source file does not match expected SHA-256.')
        if self.path.exists():
            previous=self.status()
            if previous['meta'].get('dataset_sha256')==src_hash and previous['meta'].get('source_url')==source_url and previous['meta'].get('schema_version')==2:
                return {**previous,'import_skipped_same_source':True}
        stats={'input_rows':0,'imported_rows':0,'empty_function_rows':0,'duplicate_identical_rows':0,'rejected_rows':0}
        with write_lock(self.root):
            tmp=self.root/('catalog.'+uuid.uuid4().hex+'.sqlite')
            db=sqlite3.connect(tmp)
            try:
                db.executescript(DDL)
                with path.open(encoding='utf-8-sig',newline='') as f:
                    csv.field_size_limit(1024**2)
                    reader=csv.DictReader(f)
                    if reader.fieldnames is None or not {'uid','function_keywords','function_description'}<=set(reader.fieldnames):
                        raise BrainError('FS_SCHEMA','Expected uid, function_keywords, function_description columns.')
                    function_ids={}
                    for rowno,row in enumerate(reader,2):
                        stats['input_rows']+=1
                        try:
                            key=uid(row['uid'].strip()); raw=row['function_keywords']; desc=row['function_description']
                            if not isinstance(desc,str) or len(desc)>100000: raise ValueError('invalid description')
                            words=parse_keywords(raw)
                        except (ValueError,SyntaxError,RecursionError,BrainError,TypeError,AttributeError) as exc:
                            db.execute('INSERT INTO rejected VALUES(?,?,?)',(rowno,str(row.get('uid',''))[:100],str(exc)[:200]));stats['rejected_rows']+=1;continue
                        old=db.execute('SELECT description,raw_keywords FROM cases WHERE uid=?',(key,)).fetchone()
                        if old:
                            if old==(desc,raw): stats['duplicate_identical_rows']+=1;continue
                            raise BrainError('FS_DUPLICATE','Conflicting annotations for one UID; no new catalog was committed.',{'uid':key})
                        usable=bool(words)
                        db.execute('INSERT INTO cases VALUES(?,?,?,?,?,?)',(key,desc,raw,int(usable),rowno,'Req2CAD VLM/LLM annotation; unverified function' if source_url==SOURCES['Req2CAD']['url'] else 'Imported annotation from '+source_url+'; unverified function'))
                        stats['imported_rows']+=1;stats['empty_function_rows']+=not usable
                        for word in words:
                            if word not in function_ids:
                                cur=db.execute('INSERT INTO functions(text) VALUES(?)',(word,));function_ids[word]=cur.lastrowid
                            db.execute('INSERT INTO case_functions VALUES(?,?)',(key,function_ids[word]))
                if not stats['imported_rows']: raise BrainError('FS_EMPTY','No valid rows; the previous catalog was kept.')
                if file_hash(path)!=src_hash: raise BrainError('FS_CHANGED','CSV changed while importing.')
                db.execute("INSERT INTO function_fts(function_fts) VALUES('rebuild')")
                meta={'schema_version':2,'dataset_sha256':src_hash,'source_url':source_url,'license':('CC-BY-4.0' if source_url==SOURCES['Req2CAD']['url'] else 'custom source: not declared by importer'),
                      'stats':stats,'filter':'nonempty parsed keywords only; not claimed identical to authors\' full filtering','full_original_sha_match':src_hash==REQ_SHA256}
                db.executemany('INSERT INTO meta VALUES(?,?)',[(k,canonical(v)) for k,v in meta.items()]);db.commit()
                ok=db.execute('PRAGMA integrity_check').fetchone()[0]
                if ok!='ok': raise BrainError('FS_SQLITE',ok)
                db.close();os.replace(tmp,self.path)
                # Geometry/embedding generations are identified by the source hash, never silently reused.
            finally:
                db.close();tmp.unlink(missing_ok=True)
        return self.status()

    def case(self,key: str,include_geometry=True):
        key=uid(key)
        with self.connect() as db:
            r=db.execute('SELECT * FROM cases WHERE uid=?',(key,)).fetchone()
            if r is None: raise BrainError('FS_CASE','UID not found.',{'uid':key})
            result=dict(r)
            result['function_keywords']=[r[0] for r in db.execute('SELECT f.text FROM functions f JOIN case_functions c ON c.function_id=f.id WHERE c.uid=? ORDER BY f.id',(key,))]
            a=db.execute('SELECT * FROM assets WHERE uid=?',(key,)).fetchone();result['asset']=dict(a) if a else None
            g=db.execute('SELECT record FROM geometry WHERE uid=?',(key,)).fetchone()
            result['geometry']=json.loads(g[0]) if g and include_geometry else None
            result['citation']={'dataset':json.loads(db.execute("SELECT value FROM meta WHERE key='source_url'").fetchone()[0]),'uid':key,'row_number':r['row_number'],'dataset_sha256':json.loads(db.execute("SELECT value FROM meta WHERE key='dataset_sha256'").fetchone()[0])}
            result['engineering_validation']='unknown'
            return result

    def keywords(self):
        with self.connect() as db: return [(r[0],r[1]) for r in db.execute('SELECT id,text FROM functions ORDER BY id')]

    def lexical(self,functions: list[str],limit=20,require_asset=False):
        """Explicit fallback/debug only, never advertised as semantic retrieval."""
        bounded_int(limit,1,50,'limit');self._queries(functions)
        groups=[]
        with self.connect() as db:
            for query in functions:
                words=re.findall(r'[^\W_]+',query.casefold(),flags=re.UNICODE)
                if not words: groups.append([]);continue
                expression=' AND '.join('"'+w+'"' for w in words)
                rows=db.execute('SELECT f.id,f.text,bm25(function_fts) rank FROM function_fts JOIN functions f ON f.id=function_fts.rowid WHERE function_fts MATCH ? ORDER BY rank LIMIT 1000',(expression,)).fetchall()
                groups.append([(r[0],1.0,r[1]) for r in rows])
        return self.aggregate(functions,groups,limit,require_asset,method='lexical_exact_tokens_no_semantic_scores')

    @staticmethod
    def _queries(queries):
        if not isinstance(queries,list) or not 1<=len(queries)<=12 or any(not isinstance(q,str) or not q.strip() or len(q)>1000 for q in queries):
            raise BrainError('FS_QUERY','Provide 1–12 nonempty functional queries, up to 1000 characters each.')
        if len(set(' '.join(q.split()).casefold() for q in queries))!=len(queries):
            raise BrainError('FS_QUERY','Duplicate functional queries do not count as separate requirements.')

    def aggregate(self,queries,groups,limit=20,require_asset=False,method='semantic',threshold=None):
        scores=defaultdict(dict)
        with self.connect() as db:
            for qi,hits in enumerate(groups):
                # Sort first: ties use the stable function ID, not query insertion order.
                for fid,score,word in sorted(hits,key=lambda x:(-x[1],x[0])):
                    for row in db.execute('SELECT uid FROM case_functions WHERE function_id=?',(int(fid),)):
                        key=row[0]
                        if qi not in scores[key] or score>scores[key][qi]['score']:
                            scores[key][qi]={'query':queries[qi],'matched_keyword':word,'score':float(score)}
            asset_uids={r[0] for r in db.execute('SELECT uid FROM assets')} if require_asset else None
            ordered=sorted((u for u in scores if asset_uids is None or u in asset_uids),key=lambda u:(-len(scores[u]),-sum(h['score'] for h in scores[u].values())/len(queries),u))
        results=[]
        for key in ordered[:limit]:
            c=self.case(key,include_geometry=False)
            results.append({'uid':key,'matched_function_count':len(scores[key]),'requested_function_count':len(queries),
              'matched':list(scores[key].values()),'function_keywords':c['function_keywords'],
              'description':c['description'],'cad_available':c['asset'] is not None,'citation':c['citation'],
              'annotation_origin':c['annotation_origin'],'engineering_validation':'unknown'})
        return {'method':method,'threshold':threshold,'candidate_count':len(ordered),'results':results,
                'ranking':'matched function count desc, mean similarity (missing=0) desc, uid asc; not an engineering fitness score'}
