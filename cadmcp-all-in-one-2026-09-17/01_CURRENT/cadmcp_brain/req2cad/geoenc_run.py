"""In-house geometry encoder, part 2: data pipeline, training, evaluation, embedding, search.

See docs/design/GEOMETRY_ENCODER.md. Read-only on catalog.sqlite / semantic/ / archive-cache/ / downloads/.
Outputs go only to <root>/models/geometry_encoder/<version>/ and benchmarks/results/.
"""
from __future__ import annotations
import hashlib, json, math, os, tarfile, time
from pathlib import Path
import numpy as np
from .common import BrainError, atomic_json, file_hash, json_load, canonical
from .catalog import Catalog
from . import geoenc_core as gc

DEFAULT_VERSION = 'v1'
SPLIT_MEMBER = 'data/train_val_test_split.json'
THRESHOLD = 0.7
PKG_ROOT = Path(__file__).resolve().parents[2]


def version_dir(root, version=DEFAULT_VERSION):
    return Path(root) / 'models' / 'geometry_encoder' / version


def code_version():
    h = hashlib.sha256()
    for n in ('geoenc_core.py', 'geoenc_run.py'):
        h.update((Path(__file__).parent / n).read_bytes())
    return h.hexdigest()[:16]


# ----------------------------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------------------------
def load_split(root):
    """Official DeepCAD split read straight from the downloaded data.tar (read-only). Returns (uid->split, sha256)."""
    path = Path(root) / 'downloads' / 'data.tar'
    if not path.is_file():
        raise BrainError('FS_GEOENC_SPLIT', 'downloads/data.tar (official DeepCAD split source) is missing.')
    with tarfile.open(path, 'r:*') as t:
        raw = t.extractfile(SPLIT_MEMBER).read()
    sp = json.loads(raw)
    m = {}
    for name, key in (('train', 'train'), ('validation', 'val'), ('test', 'test')):
        for u in sp[name]:
            m[u] = key
    return m, hashlib.sha256(raw).hexdigest()


def _tok_worker(args):
    path, items = args
    out = []
    with open(path, 'rb') as f:
        for uid, off, size in items:
            f.seek(off)
            try:
                c, p, ft, info = gc.tokenize_json(json.loads(f.read(size)))
                cc, pp = gc.pack(c, p)
                out.append((uid, cc, pp, ft, info['truncated'], None))
            except gc.GeoSkip as e:
                out.append((uid, None, None, None, False, e.reason))
            except Exception:
                out.append((uid, None, None, None, False, 'unparseable'))
    return out


def tokenize_catalog(root, workers=24, log=print):
    """Tokenise every case with a registered DeepCAD asset (read-only). Returns dict of arrays + stats."""
    cat = Catalog(root)
    with cat.connect() as db:
        rows = db.execute('SELECT uid,path,member FROM assets WHERE kind=? ORDER BY uid', ('deepcad_tar',)).fetchall()
    path = rows[0]['path']
    items = []
    for r in rows:
        if r['path'] != path:
            raise BrainError('FS_GEOENC', 'Assets span several archives; unsupported.')
        loc = json.loads(r['member'])
        items.append((r['uid'], loc['offset_data'], loc['size']))
    items.sort(key=lambda x: x[1])
    chunks = [(path, items[i:i + 512]) for i in range(0, len(items), 512)]
    import multiprocessing as mp
    uids, C, P, F, trunc = [], [], [], [], 0
    skipped = {}
    t0 = time.time()
    with mp.get_context('spawn').Pool(workers) as pool:
        for k, res in enumerate(pool.imap(_tok_worker, chunks)):
            for uid, cc, pp, ft, tr, reason in res:
                if reason:
                    skipped[reason] = skipped.get(reason, 0) + 1
                    continue
                uids.append(uid); C.append(cc); P.append(pp); F.append(ft); trunc += tr
            if k % 50 == 0:
                log('tokenised chunks %d/%d (%.0fs)' % (k + 1, len(chunks), time.time() - t0))
    order = np.argsort(np.array(uids))
    return {'uids': np.array(uids)[order], 'cmds': np.stack(C)[order], 'params': np.stack(P)[order],
            'feats': np.stack(F)[order], 'stats': {'cases_with_asset': len(items), 'tokenised': len(uids),
                                                   'skipped': skipped, 'skipped_total': sum(skipped.values()),
                                                   'truncated_to_64': trunc}}


def load_or_build_tokens(root, vdir, log=print):
    f = vdir / 'tokens.npz'
    if f.is_file():
        z = np.load(f, allow_pickle=False)
        return {'uids': z['uids'], 'cmds': z['cmds'], 'params': z['params'], 'feats': z['feats'],
                'stats': json.loads(str(z['stats']))}
    vdir.mkdir(parents=True, exist_ok=True)
    d = tokenize_catalog(root, log=log)
    tmp = vdir / 'tokens.tmp.npz'
    np.savez(tmp, uids=d['uids'], cmds=d['cmds'], params=d['params'], feats=d['feats'], stats=json.dumps(d['stats']))
    os.replace(tmp, f)
    return d


class Labels:
    """Case -> function rows of the Qwen keyword matrix, and case targets."""
    def __init__(self, root):
        root = Path(root); cat = Catalog(root)
        sem = root / 'semantic'
        words = json_load(sem / 'keywords.json')
        self.fid2row = {int(w[0]): i for i, w in enumerate(words)}
        self.V = np.load(sem / 'vectors.npy', mmap_mode='r', allow_pickle=False)
        self.keywords = [w[1] for w in words]
        self.case_rows = {}
        with cat.connect() as db:
            for uid, fid in db.execute('SELECT c.uid,cf.function_id FROM case_functions cf JOIN cases c ON c.uid=cf.uid WHERE c.usable=1 ORDER BY c.uid,cf.function_id'):
                self.case_rows.setdefault(uid, []).append(self.fid2row[fid])
        self.dataset_sha256 = json_load(sem / 'manifest.json')['dataset_sha256']

    def targets(self, uids):
        T = np.zeros((len(uids), self.V.shape[1]), dtype=np.float32)
        V = np.asarray(self.V)
        for i, u in enumerate(uids):
            T[i] = V[self.case_rows[u]].mean(0)
        T /= np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-12)
        return T


# ----------------------------------------------------------------------------------------------
# Evaluation set
# ----------------------------------------------------------------------------------------------
def build_eval(uids, case_rows, V, n_queries=2000, seed=0, threshold=THRESHOLD):
    """Queries = fixed-seed sample of functions linked to the pool cases; gains = max cosine over the
    case's keywords that clear the threshold (0 if none). Returns query rows, query vectors, gains (Q, N)."""
    V = np.asarray(V)
    funcs = sorted({r for u in uids for r in case_rows[u]})
    rng = np.random.default_rng(seed)
    pick = np.array(sorted(rng.choice(funcs, size=min(n_queries, len(funcs)), replace=False)))
    pos = {r: i for i, r in enumerate(funcs)}
    edge_f, indptr = [], [0]
    for u in uids:
        edge_f += [pos[r] for r in case_rows[u]]; indptr.append(len(edge_f))
    q = V[pick]
    sims = q @ V[np.array(funcs)].T
    sims = np.where(sims >= threshold - 1e-6, sims, 0.0)
    per_edge = sims[:, np.array(edge_f)]
    gains = np.maximum.reduceat(per_edge, np.array(indptr[:-1]), axis=1).astype(np.float32)
    return pick, q, gains


def evaluate_scores(scores, gains, seed=0):
    m = gc.rank_metrics(scores, gains)
    return {k: gc.bootstrap_ci(v, seed=seed) for k, v in m.items()}, m


def jaccard_neighbours(emb, func_sets, k=10, seed=0, metric='cosine'):
    """Per-case mean Jaccard overlap of function sets with its top-k neighbours (self excluded)."""
    import torch
    x = torch.as_tensor(np.asarray(emb, dtype=np.float32))
    if metric == 'cosine':
        x = torch.nn.functional.normalize(x, dim=-1)
        sim = x @ x.T
    else:
        sim = -torch.cdist(x, x)
    sim.fill_diagonal_(-1e9)
    nn_idx = sim.topk(k, dim=1).indices.numpy()
    return _mean_jaccard(nn_idx, func_sets)


def _mean_jaccard(nn_idx, func_sets):
    out = np.zeros(len(nn_idx))
    for i, row in enumerate(nn_idx):
        a = func_sets[i]
        out[i] = np.mean([len(a & func_sets[j]) / len(a | func_sets[j]) for j in row])
    return out


def random_neighbours(n, k=10, seed=0):
    rng = np.random.default_rng(seed)
    idx = np.empty((n, k), dtype=int)
    for i in range(n):
        c = rng.choice(n - 1, size=k, replace=False)
        idx[i] = c + (c >= i)
    return idx


# ----------------------------------------------------------------------------------------------
# Training
# ----------------------------------------------------------------------------------------------
def _device():
    import torch
    return 'cuda' if torch.cuda.is_available() else 'cpu'


def embed_tokens(model, cmds, params, device, batch=2048):
    import torch
    model.eval(); out = []
    with torch.no_grad():
        for i in range(0, len(cmds), batch):
            c = torch.as_tensor(cmds[i:i + batch]).to(device); p = torch.as_tensor(params[i:i + batch]).to(device)
            with torch.autocast(device, dtype=torch.bfloat16, enabled=device == 'cuda'):
                out.append(model(c, p).float().cpu())
    return torch.cat(out).numpy()


def train(cmds, params, targets, val_cmds, val_params, val_eval, *, hp, vdir, log=print, device=None):
    """Generic training loop (also used by the CPU unit test). val_eval(emb_val)->float (higher is better).
    Returns dict(best_epoch, history, seconds, state_dict of best)."""
    import torch
    device = device or _device()
    torch.manual_seed(hp['seed']); np.random.seed(hp['seed'])
    model = gc.build_model(hp['d_model'], hp['heads'], hp['layers'], targets.shape[1], hp['ff'], hp['dropout']).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=hp['lr'], weight_decay=hp['weight_decay'])
    N = len(cmds); bs = hp['batch_size']
    steps_per_epoch = N // bs
    total = steps_per_epoch * hp['max_epochs']
    warm = min(hp['warmup_steps'], total // 4)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / warm) * (0.5 * (1 + math.cos(math.pi * min(1.0, s / total))) * 0.97 + 0.03))
    C = torch.as_tensor(cmds).to(device); P = torch.as_tensor(params).to(device)
    T = torch.as_tensor(targets).to(device=device, dtype=torch.float16)
    t0 = time.time(); best = (-1.0, -1, None); hist = []; bad = 0
    for epoch in range(1, hp['max_epochs'] + 1):
        model.train()
        g = torch.Generator(device='cpu'); g.manual_seed(hp['seed'] * 1000 + epoch)
        perm = torch.randperm(N, generator=g).to(device)
        tl = 0.0
        for s in range(steps_per_epoch):
            ix = perm[s * bs:(s + 1) * bs]
            with torch.autocast(device, dtype=torch.bfloat16, enabled=device == 'cuda'):
                z = model(C[ix], P[ix])
            loss, nce, reg = gc.contrastive_loss(z.float(), T[ix].float(), model.logit_scale, hp['reg_weight'])
            opt.zero_grad(set_to_none=True); loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step(); tl += float(loss)
            with torch.no_grad():
                model.logit_scale.clamp_(0, math.log(100))
        rec = {'epoch': epoch, 'train_loss': tl / steps_per_epoch, 'seconds': time.time() - t0, 'lr': sched.get_last_lr()[0]}
        if val_eval is not None and epoch % hp['eval_every'] == 0:
            rec['val_metric'] = float(val_eval(embed_tokens(model, val_cmds, val_params, device)))
            if rec['val_metric'] > best[0]:
                best = (rec['val_metric'], epoch, {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}); bad = 0
            else:
                bad += 1
        hist.append(rec); log(json.dumps(rec))
        if vdir is not None:
            with open(Path(vdir) / 'train_log.jsonl', 'a') as f:
                f.write(json.dumps(rec) + '\n')
        if time.time() - t0 > hp['time_cap_seconds']:
            log('time cap reached'); rec['stop'] = 'time_cap'; break
        if bad >= hp['patience']:
            log('early stop'); rec['stop'] = 'patience'; break
    if best[2] is None:
        best = (float('nan'), len(hist), {k: v.detach().cpu().clone() for k, v in model.state_dict().items()})
    return {'best_metric': best[0], 'best_epoch': best[1], 'history': hist, 'seconds': time.time() - t0,
            'state': best[2], 'stop': hist[-1].get('stop', 'max_epochs')}


DEFAULT_HP = dict(seed=0, d_model=256, heads=8, layers=4, ff=1024, dropout=0.1, lr=5e-4, weight_decay=0.05,
                  batch_size=512, max_epochs=100, warmup_steps=300, reg_weight=0.1, eval_every=1, patience=15,
                  time_cap_seconds=3600, val_queries=500)


def run_training(root, version=DEFAULT_VERSION, hp_overrides=None, log=print):
    import torch
    root = Path(root); vdir = version_dir(root, version); vdir.mkdir(parents=True, exist_ok=True)
    hp = {**DEFAULT_HP, **(hp_overrides or {})}
    tok = load_or_build_tokens(root, vdir, log)
    labels = Labels(root); split, split_sha = load_split(root)
    uids = tok['uids']; idx = {u: i for i, u in enumerate(uids)}
    sel = {s: [u for u in uids if split.get(u) == s and u in labels.case_rows] for s in ('train', 'val', 'test')}
    data_stats = {'tokenisation': tok['stats'], 'labeled_per_split': {k: len(v) for k, v in sel.items()},
                  'unsplit_or_unlabeled_cases': int(len(uids) - sum(len(v) for v in sel.values()))}
    log(json.dumps(data_stats))
    ti = np.array([idx[u] for u in sel['train']]); vi = np.array([idx[u] for u in sel['val']])
    targets = labels.targets(sel['train'])
    pick, q, gains = build_eval(sel['val'], labels.case_rows, labels.V, hp['val_queries'], seed=hp['seed'] + 1)

    def val_eval(emb):
        return gc.rank_metrics(q @ emb.T, gains)['ndcg@10'].mean()
    res = train(tok['cmds'][ti], tok['params'][ti], targets, tok['cmds'][vi], tok['params'][vi], val_eval,
                hp=hp, vdir=vdir, log=log)
    ckpt = vdir / 'model.pt'
    torch.save({'state': res['state'], 'hp': hp, 'model_cfg': {k: hp[k] for k in ('d_model', 'heads', 'layers', 'ff', 'dropout')},
                'out_dim': int(targets.shape[1])}, ckpt)
    manifest = {
        'version': version, 'created_unix': int(time.time()), 'code_version': code_version(), 'seed': hp['seed'],
        'hyper_parameters': hp, 'split_sha256': split_sha, 'catalog_dataset_sha256': labels.dataset_sha256,
        'semantic_vectors_sha256': json_load(root / 'semantic' / 'manifest.json')['vectors_sha256'],
        'tokens_sha256': file_hash(vdir / 'tokens.npz'), 'checkpoint': 'model.pt', 'checkpoint_sha256': file_hash(ckpt),
        'data': data_stats, 'training': {'best_epoch': res['best_epoch'], 'best_val_ndcg@10': res['best_metric'],
                                         'epochs_run': len(res['history']), 'seconds': res['seconds'], 'stop': res['stop'],
                                         'device': _device(), 'torch': torch.__version__},
        'experimental': True, 'evaluation': None}
    atomic_json(vdir / 'manifest.json', manifest)
    return manifest


def load_model(vdir, device=None):
    import torch
    device = device or _device()
    ck = torch.load(Path(vdir) / 'model.pt', map_location='cpu', weights_only=False)
    c = ck['model_cfg']
    m = gc.build_model(c['d_model'], c['heads'], c['layers'], ck['out_dim'], c['ff'], c['dropout'])
    m.load_state_dict(ck['state']); return m.to(device).eval()


# ----------------------------------------------------------------------------------------------
# Held-out evaluation
# ----------------------------------------------------------------------------------------------
def run_evaluation(root, version=DEFAULT_VERSION, n_queries=2000, seed=0, results_dir=None, log=print):
    import torch
    root = Path(root); vdir = version_dir(root, version); manifest = json_load(vdir / 'manifest.json')
    if file_hash(vdir / 'model.pt') != manifest['checkpoint_sha256']:
        raise BrainError('FS_GEOENC_STALE', 'Checkpoint differs from its manifest.')
    tok = load_or_build_tokens(root, vdir); labels = Labels(root); split, _ = load_split(root)
    uids = tok['uids']; idx = {u: i for i, u in enumerate(uids)}
    test = [u for u in uids if split.get(u) == 'test' and u in labels.case_rows]      # sorted by uid
    train = [u for u in uids if split.get(u) == 'train' and u in labels.case_rows]
    ti = np.array([idx[u] for u in test]); tri = np.array([idx[u] for u in train])
    pick, q, gains = build_eval(test, labels.case_rows, labels.V, n_queries, seed=seed)
    device = _device()
    model = load_model(vdir, device)
    emb = embed_tokens(model, tok['cmds'][ti], tok['params'][ti], device)
    enc_scores = q @ emb.T
    # handcrafted_knn: standardised cheap JSON-derived features (documented subset; OCC B-rep descriptors need
    # a CAD replay per case and exist for only a handful of cases), k=10 nearest TRAIN cases, mean of their targets.
    F = tok['feats']; mu = F[tri].mean(0); sd = F[tri].std(0) + 1e-6
    Fz = torch.as_tensor((F - mu) / sd, dtype=torch.float32, device=device)
    d = torch.cdist(Fz[torch.as_tensor(ti, device=device)], Fz[torch.as_tensor(tri, device=device)])
    nn_idx = d.topk(10, largest=False, dim=1).indices.cpu().numpy()
    Ttrain = labels.targets(train)
    knn_t = Ttrain[nn_idx].mean(1); knn_t /= np.maximum(np.linalg.norm(knn_t, axis=1, keepdims=True), 1e-12)
    knn_scores = q @ knn_t.T
    # text_search_reference: ranks by max cosine over test annotations, uid ascending on ties (pool is uid-sorted).
    text_scores = gains
    ci = {}
    systems = {}
    for name, sc in (('encoder', enc_scores), ('handcrafted_knn', knn_scores), ('text_search_reference', text_scores)):
        r, _ = evaluate_scores(sc, gains, seed)
        systems[name] = {k: {'mean': v[0], 'ci95': [v[1], v[2]]} for k, v in r.items()}
    rnd = gc.random_expected_metrics(gains)
    systems['random'] = {k: {'mean': float(np.mean(v)), 'ci95': list(gc.bootstrap_ci(v, seed=seed)[1:])} for k, v in rnd.items()}
    # shape-to-shape
    fsets = [set(labels.case_rows[u]) for u in test]
    jm_enc = jaccard_neighbours(emb, fsets, 10)
    jm_hc = jaccard_neighbours(Fz[torch.as_tensor(ti, device=device)].cpu().numpy(), fsets, 10, metric='euclid')
    jm_rnd = _mean_jaccard(random_neighbours(len(test), 10, seed), fsets)
    s2s = {n: {'mean': float(v.mean()), 'ci95': list(gc.bootstrap_ci(v, seed=seed)[1:])}
           for n, v in (('encoder', jm_enc), ('handcrafted', jm_hc), ('random', jm_rnd))}
    e, h = systems['encoder'], systems['handcrafted_knn']
    beats = lambda m: e[m]['ci95'][0] > h[m]['ci95'][1]
    accepted = bool(beats('ndcg@10') and beats('recall@50'))
    result = {
        'version': version, 'seed': seed, 'n_queries': int(len(pick)), 'pool_size': len(test),
        'relevance_rule': 'test cases linked to any keyword with Qwen cosine >= 0.7 to the query keyword; gain = max cosine',
        'metric_definitions': 'recall@k = relevant in top k / all relevant; MRR = 1/rank of first relevant; nDCG@10 linear graded gain',
        'systems': systems, 'shape_to_shape_jaccard_top10': s2s,
        'handcrafted_features': {'names': gc.FEATURE_NAMES, 'k': 10, 'kind': 'cheap JSON-derived subset (no B-rep replay)'},
        'acceptance': {'rule': 'encoder beats handcrafted_knn on nDCG@10 and Recall@50 with non-overlapping 95% CIs',
                       'ndcg@10_ci_disjoint': bool(beats('ndcg@10')), 'recall@50_ci_disjoint': bool(beats('recall@50')),
                       'accepted': accepted},
        'checkpoint_sha256': manifest['checkpoint_sha256'], 'code_version': code_version(),
        'training': manifest['training'], 'data': manifest['data']}
    results_dir = Path(results_dir or PKG_ROOT / 'benchmarks' / 'results'); results_dir.mkdir(parents=True, exist_ok=True)
    out = results_dir / ('geometry_encoder_%s.json' % version)
    atomic_json(out, result)
    manifest['evaluation'] = {'file': str(out), 'sha256': file_hash(out), 'accepted': accepted}
    manifest['experimental'] = not accepted
    atomic_json(vdir / 'manifest.json', manifest)
    (results_dir / ('geometry_encoder_%s.md' % version)).write_text(markdown_summary(result), encoding='utf-8')
    return result


def markdown_summary(r):
    L = ['# Geometry encoder %s evaluation' % r['version'], '',
         'Pool: %d held-out test cases with annotations; %d queries; seed %d. Relevance: %s.' % (r['pool_size'], r['n_queries'], r['seed'], r['relevance_rule']), '',
         '| system | Recall@10 | Recall@50 | MRR | nDCG@10 |', '|---|---|---|---|---|']
    for n, s in r['systems'].items():
        L.append('| %s | ' % n + ' | '.join('%.4f [%.4f, %.4f]' % (s[m]['mean'], *s[m]['ci95']) for m in ('recall@10', 'recall@50', 'mrr', 'ndcg@10')) + ' |')
    L += ['', 'Shape-to-shape mean Jaccard (top-10 neighbours): ' + '; '.join('%s %.4f [%.4f, %.4f]' % (n, s['mean'], *s['ci95']) for n, s in r['shape_to_shape_jaccard_top10'].items()), '',
          'Acceptance (%s): **%s**' % (r['acceptance']['rule'], 'ACCEPTED' if r['acceptance']['accepted'] else 'NOT accepted (experimental)'), '',
          'text_search_reference uses the test annotations and relevance is defined by the same rule, so it is an upper bound, not a competitor.']
    return '\n'.join(L) + '\n'


# ----------------------------------------------------------------------------------------------
# Embedding of all cases + search mode
# ----------------------------------------------------------------------------------------------
def encode_all(root, version=DEFAULT_VERSION, log=print):
    root = Path(root); vdir = version_dir(root, version)
    if not (vdir / 'model.pt').is_file():
        raise BrainError('FS_GEOMETRY_ENCODER_NOT_READY', 'Train the geometry encoder first (python -m cadmcp_brain.req2cad train-geometry).')
    manifest = json_load(vdir / 'manifest.json')
    if file_hash(vdir / 'model.pt') != manifest['checkpoint_sha256']:
        raise BrainError('FS_GEOMETRY_ENCODER_STALE', 'Checkpoint differs from its manifest.')
    tok = load_or_build_tokens(root, vdir, log); device = _device()
    emb = embed_tokens(load_model(vdir, device), tok['cmds'], tok['params'], device).astype(np.float16)
    np.save(vdir / 'embeddings.tmp.npy', emb); os.replace(vdir / 'embeddings.tmp.npy', vdir / 'embeddings.npy')
    atomic_json(vdir / 'uids.json', [str(u) for u in tok['uids']])
    manifest['embeddings'] = {'file': 'embeddings.npy', 'sha256': file_hash(vdir / 'embeddings.npy'), 'uids_sha256': file_hash(vdir / 'uids.json'),
                              'rows': int(len(emb)), 'dim': int(emb.shape[1]), 'dtype': 'float16',
                              'catalog_dataset_sha256': Catalog(root).status()['meta']['dataset_sha256'],
                              'checkpoint_sha256': manifest['checkpoint_sha256']}
    atomic_json(vdir / 'manifest.json', manifest)
    return manifest['embeddings']


_CACHE = {}


def check_ready(catalog, version=None):
    """Cheap readiness check (manifest-level). Raises explicit codes; never selects another mode."""
    root = catalog.root; base = root / 'models' / 'geometry_encoder'
    if version is None:
        cands = sorted(p.name for p in base.iterdir() if (p / 'manifest.json').is_file()) if base.is_dir() else []
        if not cands:
            raise BrainError('FS_GEOMETRY_ENCODER_NOT_READY', 'No geometry encoder installed under models/geometry_encoder. No other mode was used.')
        version = cands[-1]
    vdir = version_dir(root, version)
    if not (vdir / 'manifest.json').is_file():
        raise BrainError('FS_GEOMETRY_ENCODER_NOT_READY', 'Geometry encoder version not found.', {'version': version})
    m = json_load(vdir / 'manifest.json'); e = m.get('embeddings')
    if not e or not (vdir / 'embeddings.npy').is_file():
        raise BrainError('FS_GEOMETRY_ENCODER_NOT_READY', 'Geometry embeddings are not built; run encode-geometry. No other mode was used.')
    st = catalog.status()
    if e['catalog_dataset_sha256'] != st['meta']['dataset_sha256'] or e['checkpoint_sha256'] != m['checkpoint_sha256']:
        raise BrainError('FS_GEOMETRY_ENCODER_STALE', 'Geometry embeddings do not match the catalog/checkpoint; re-run encode-geometry.')
    return vdir, version, m, e


def geometry_search(catalog, qvecs, functions, version=None, limit=20, require_cad=False):
    """Cosine of the query vectors (already Qwen-encoded, normalised) against precomputed geometry embeddings.
    Never falls back to another mode: missing or stale encoder -> explicit error."""
    vdir, version, m, e = check_ready(catalog, version)
    f = vdir / 'embeddings.npy'; sig = (str(f), f.stat().st_size, f.stat().st_mtime_ns)
    if _CACHE.get('sig') != sig:
        if file_hash(f) != e['sha256'] or file_hash(vdir / 'uids.json') != e['uids_sha256']:
            raise BrainError('FS_GEOMETRY_ENCODER_STALE', 'Embedding files changed after they were recorded.')
        _CACHE.update(sig=sig, emb=np.load(f, mmap_mode='r', allow_pickle=False), uids=json_load(vdir / 'uids.json'))
    emb, uids = _CACHE['emb'], _CACHE['uids']
    q = np.asarray(qvecs, dtype=np.float32)
    if q.shape[1] != emb.shape[1]:
        raise BrainError('FS_EMBEDDING', 'Query dimension differs from geometry embedding dimension.')
    sims = np.asarray(emb, dtype=np.float32) @ q.T
    score = sims.mean(1)
    order = np.argsort(-score, kind='stable')
    results = []
    ev = m.get('evaluation') or {}
    for i in order:
        if len(results) >= limit:
            break
        c = catalog.case(uids[int(i)], include_geometry=False)
        if require_cad and not c['asset']:
            continue
        results.append({'uid': uids[int(i)], 'geometry_cosine_mean': float(score[i]),
                        'per_function_cosine': [float(x) for x in sims[i]], 'cad_available': c['asset'] is not None,
                        'function_keywords': c['function_keywords'], 'description': c['description'],
                        'citation': c['citation'], 'annotation_origin': c['annotation_origin'], 'engineering_validation': 'unknown'})
    return {'method': 'geometry_encoder', 'mode': 'geometry_encoder', 'encoder_version': version,
            'experimental': bool(m.get('experimental', True)), 'evaluation_file': ev.get('file'),
            'note': 'Ranks by predicted function from CAD construction only; case annotations are NOT used. '
                    + ('' if not m.get('experimental', True) else 'EXPERIMENTAL: not shown to beat the hand-crafted baseline on held-out data. '),
            'queries': functions, 'results': results,
            'ranking': 'mean cosine between function query and geometry embedding; not an engineering fitness score'}
