"""Fast CPU tests for the in-house geometry encoder (docs/design/GEOMETRY_ENCODER.md). No GPU, no real catalog."""
import copy, csv, json, math
from pathlib import Path
import numpy as np
import pytest
import torch
from cadmcp_brain.errors import BrainError
from cadmcp_brain.req2cad import geoenc_core as gc
from cadmcp_brain.req2cad import geoenc_run as G
from cadmcp_brain.req2cad.catalog import Catalog
from cadmcp_brain.req2cad.common import atomic_json, file_hash

FIX = Path(__file__).resolve().parents[1] / 'examples' / 'public-cases' / 'cad_json'
# Expected command streams, verified against the fixture JSON (circle/line counts, loops, extrudes).
EXPECTED = {'00321991': [gc.CIRCLE, gc.LOOP_END, gc.EXTRUDE, gc.EOS],
            '00325799': [gc.LINE] * 4 + [gc.LOOP_END, gc.EXTRUDE, gc.EOS],
            '00325917': [gc.CIRCLE, gc.LOOP_END, gc.EXTRUDE, gc.EOS],
            '00329619': [gc.CIRCLE, gc.LOOP_END] * 6 + [gc.EXTRUDE] + [gc.CIRCLE, gc.LOOP_END] * 2 + [gc.EXTRUDE]
                        + [gc.CIRCLE, gc.LOOP_END] * 2 + [gc.EXTRUDE, gc.EOS]}


def load(name):
    return json.loads(next(FIX.glob('*/' + name + '.json')).read_text())


@pytest.mark.parametrize('name', sorted(EXPECTED))
def test_tokenizer_known_command_counts(name):
    d = load(name)
    cmds, params, feats, info = gc.tokenize_json(d)
    assert cmds == EXPECTED[name]
    n_ext = sum(e['type'] == 'ExtrudeFeature' for e in d['entities'].values())
    assert cmds.count(gc.EXTRUDE) == n_ext and cmds[-1] == gc.EOS
    assert len(cmds) == len(params) <= gc.MAX_LEN and not info['truncated']
    assert feats.shape == (gc.NUM_FEATURES,) and np.isfinite(feats).all()
    for c, p in zip(cmds, params):
        assert len(p) == gc.PARAM_COUNT[c] and all(0 <= v < gc.LEVELS for v in p)


def test_tokenizer_is_scale_invariant():
    d = load('00325799'); a = gc.tokenize_json(d)
    e = copy.deepcopy(d)
    def scale(v, s):
        for k in v:
            v[k] *= s
    for ent in e['entities'].values():
        if ent['type'] == 'Sketch':
            for p in ent['profiles'].values():
                for l in p['loops']:
                    for c in l['profile_curves']:
                        for key in ('start_point', 'end_point', 'center_point'):
                            if key in c:
                                scale(c[key], 10)
        else:
            ent['extent_one']['distance']['value'] *= 10
    for k in ('min_point', 'max_point'):
        scale(e['properties']['bounding_box'][k], 10)
    b = gc.tokenize_json(e)
    assert a[0] == b[0] and a[1] == b[1]


def test_overlong_models_are_truncated_and_flagged():
    d = load('00329619')
    ent = next(k for k, v in d['entities'].items() if v['type'] == 'ExtrudeFeature')
    for i in range(40):
        d['sequence'].append({'index': 100 + i, 'type': 'ExtrudeFeature', 'entity': ent})
    cmds, params, feats, info = gc.tokenize_json(d)
    assert len(cmds) == gc.MAX_LEN and cmds[-1] == gc.EOS and info['truncated']


@pytest.mark.parametrize('mut,reason', [(lambda d: d.pop('sequence'), 'schema'), (lambda d: d['properties'].pop('bounding_box'), 'no_bbox'),
                                        (lambda d: d['sequence'].clear(), 'no_extrude')])
def test_unparseable_is_skipped_with_reason(mut, reason):
    d = load('00325799'); mut(d)
    with pytest.raises(gc.GeoSkip) as e:
        gc.tokenize_json(d)
    assert e.value.reason == reason
    with pytest.raises(gc.GeoSkip):
        gc.tokenize_json({'entities': 5, 'sequence': []})


def batch(names):
    cs, ps = zip(*[gc.pack(*gc.tokenize_json(load(n))[:2]) for n in names])
    return torch.as_tensor(np.stack(cs)), torch.as_tensor(np.stack(ps))


def test_model_forward_shape_and_normalisation():
    m = gc.build_model(32, 4, 2, 48, 64, 0.0).eval()
    c, p = batch(sorted(EXPECTED))
    z = m(c, p)
    assert z.shape == (4, 48) and torch.isfinite(z).all()
    assert torch.allclose(z.norm(dim=-1), torch.ones(4), atol=1e-5)


def test_default_model_matches_spec():
    m = gc.build_model()
    assert m.proj.out_features == 2560 and m.cfg['layers'] == 4 and m.cfg['d_model'] == 256 and m.cfg['heads'] == 8


def test_two_epoch_cpu_training_lowers_loss(tmp_path):
    rng = np.random.default_rng(0)
    n = 256
    cls = rng.integers(0, 4, n)
    cmds = np.zeros((n, gc.MAX_LEN), np.uint8); params = np.zeros((n, gc.MAX_LEN, gc.NPARAM), np.uint8)
    for i, k in enumerate(cls):                       # class k determines the command pattern
        cmds[i, :4] = [1 + k % 3, gc.LOOP_END, gc.EXTRUDE, gc.EOS]
        params[i, 0, :3] = [k * 60, k * 30, 10]; params[i, 2, :3] = [k * 50, 7, 7]
    centers = rng.normal(size=(4, 16)); centers /= np.linalg.norm(centers, axis=1, keepdims=True)
    targets = centers[cls].astype(np.float32)
    hp = dict(G.DEFAULT_HP, d_model=32, heads=4, layers=1, ff=64, dropout=0.0, batch_size=64, max_epochs=2, lr=3e-3,
              warmup_steps=2, eval_every=1, patience=5, time_cap_seconds=60)
    res = G.train(cmds, params, targets, cmds[:16], params[:16], lambda e: float(e.std()), hp=hp, vdir=tmp_path,
                  log=lambda m: None, device='cpu')
    h = res['history']
    assert len(h) == 2 and h[1]['train_loss'] < h[0]['train_loss']
    assert res['best_epoch'] in (1, 2) and 'proj.weight' in res['state']


def test_metrics_on_handmade_ranking():
    scores = np.array([[.9, .8, .1, .2]]); gains = np.array([[0, 1.0, 0, .5]])   # order 0,1,3,2 -> gains 0,1,.5,0
    m = gc.rank_metrics(scores, gains, ks=(1, 2, 3))
    assert m['recall@1'][0] == 0 and m['recall@2'][0] == 0.5 and m['recall@3'][0] == 1
    assert m['mrr'][0] == 0.5
    dcg = 1 / math.log2(3) + .5 / math.log2(4); idcg = 1 / math.log2(2) + .5 / math.log2(3)
    assert m['ndcg@10'][0] == pytest.approx(dcg / idcg)
    perfect = gc.rank_metrics(gains, gains)
    assert perfect['ndcg@10'][0] == pytest.approx(1) and perfect['mrr'][0] == 1


def test_random_expectation_matches_simulation():
    rng = np.random.default_rng(1)
    gains = np.zeros((2, 60)); gains[0, :3] = [1, .8, .7]; gains[1, :10] = .75
    exp = gc.random_expected_metrics(gains, ks=(10, 50))
    sims = [gc.rank_metrics(rng.random((2, 60)), gains) for _ in range(4000)]
    for key in ('recall@10', 'recall@50', 'mrr', 'ndcg@10'):
        assert np.mean([s[key] for s in sims], axis=0) == pytest.approx(exp[key], abs=0.01)


def test_bootstrap_ci_is_seeded_and_brackets_mean():
    v = np.random.default_rng(0).random(200)
    a = gc.bootstrap_ci(v, seed=3)
    assert a == gc.bootstrap_ci(v, seed=3) and a[1] <= a[0] <= a[2]


def test_build_eval_relevance_rule():
    V = np.eye(4, dtype=np.float32); V[1] = [.8, .6, 0, 0]
    rows = {'a': [0], 'b': [1], 'c': [2]}
    pick, q, gains = G.build_eval(['a', 'b', 'c'], rows, V, n_queries=10, seed=0)
    qi = list(pick).index(0)
    assert gains[qi].tolist() == pytest.approx([1.0, .8, 0.0])


def write_csv(path, rows):
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['uid', 'function_keywords', 'function_description']); w.writeheader(); w.writerows(rows)


def toy(tmp_path):
    write_csv(tmp_path / 'd.csv', [
        {'uid': '9000/90000001', 'function_keywords': "['support rotating shaft']", 'function_description': 'SYNTHETIC'},
        {'uid': '9000/90000002', 'function_keywords': "['reduce friction']", 'function_description': 'SYNTHETIC'}])
    c = Catalog(tmp_path / 'kb'); c.ingest(tmp_path / 'd.csv', source_url='fixture://authored-unit-test')
    vdir = G.version_dir(c.root, 'vt'); vdir.mkdir(parents=True)
    cmds, params = zip(*[gc.pack(*gc.tokenize_json(load(n))[:2]) for n in ('00325799', '00321991')])
    np.savez(vdir / 'tokens.npz', uids=np.array(['9000/90000001', '9000/90000002']), cmds=np.stack(cmds), params=np.stack(params),
             feats=np.zeros((2, gc.NUM_FEATURES), np.float32), stats=json.dumps({}))
    m = gc.build_model(16, 2, 1, 3, 32, 0.0)
    cfg = dict(d_model=16, heads=2, layers=1, ff=32, dropout=0.0)
    torch.save({'state': m.state_dict(), 'hp': {}, 'model_cfg': cfg, 'out_dim': 3}, vdir / 'model.pt')
    atomic_json(vdir / 'manifest.json', {'version': 'vt', 'checkpoint': 'model.pt', 'checkpoint_sha256': file_hash(vdir / 'model.pt'),
                                         'experimental': True, 'evaluation': None})
    return c, vdir


def test_encode_records_hashes_search_labels_mode_and_detects_tamper(tmp_path):
    c, vdir = toy(tmp_path)
    e = G.encode_all(c.root, 'vt')
    man = json.loads((vdir / 'manifest.json').read_text())
    assert man['embeddings'] == e and e['rows'] == 2 and e['dim'] == 3
    assert e['sha256'] == file_hash(vdir / 'embeddings.npy') and e['uids_sha256'] == file_hash(vdir / 'uids.json')
    assert e['catalog_dataset_sha256'] == c.status()['meta']['dataset_sha256']
    assert e['checkpoint_sha256'] == man['checkpoint_sha256']
    r = G.geometry_search(c, np.array([[1., 0., 0.]], np.float32), ['x'], None, 5)
    assert r['mode'] == 'geometry_encoder' and r['encoder_version'] == 'vt' and r['experimental'] is True
    assert {x['uid'] for x in r['results']} == {'9000/90000001', '9000/90000002'}
    import gc as pygc
    G._CACHE.clear(); del r; pygc.collect()          # release the memory map (Windows cannot overwrite a mapped file)
    emb = np.load(vdir / 'embeddings.npy'); np.save(vdir / 'embeddings.npy', emb[::-1].copy())
    with pytest.raises(BrainError) as ex:
        G.geometry_search(c, np.array([[1., 0., 0.]], np.float32), ['x'], None, 5)
    assert ex.value.code == 'FS_GEOMETRY_ENCODER_STALE'


def test_search_without_encoder_raises_not_ready(tmp_path):
    write_csv(tmp_path / 'd.csv', [{'uid': '9000/90000001', 'function_keywords': "['a']", 'function_description': 'S'}])
    c = Catalog(tmp_path / 'kb'); c.ingest(tmp_path / 'd.csv', source_url='fixture://authored-unit-test')
    for fn in (lambda: G.geometry_search(c, np.zeros((1, 3), np.float32), ['a']), lambda: G.check_ready(c)):
        with pytest.raises(BrainError) as ex:
            fn()
        assert ex.value.code == 'FS_GEOMETRY_ENCODER_NOT_READY'
    G.version_dir(c.root, 'vx').mkdir(parents=True)
    atomic_json(G.version_dir(c.root, 'vx') / 'manifest.json', {'checkpoint_sha256': 'x'})
    with pytest.raises(BrainError) as ex:
        G.check_ready(c)
    assert ex.value.code == 'FS_GEOMETRY_ENCODER_NOT_READY'


def test_brain_fs_search_geometry_mode_missing_encoder_is_explicit(tmp_path, monkeypatch):
    from cadmcp_brain.req2cad.mixin import Req2CADToolsMixin
    c, vdir = toy(tmp_path)           # checkpoint exists but embeddings are not built
    monkeypatch.setenv('CADMCP_REQ2CAD_ROOT', str(c.root))
    class T(Req2CADToolsMixin):
        from types import SimpleNamespace
        brain = SimpleNamespace(store=SimpleNamespace(root=Path('.')))
    with pytest.raises(BrainError) as ex:
        T().brain_fs_search(['support rotating shaft'], mode='geometry_encoder')
    assert ex.value.code == 'FS_GEOMETRY_ENCODER_NOT_READY'
    with pytest.raises(BrainError):
        T().brain_fs_search(['x'], mode='nonsense')
