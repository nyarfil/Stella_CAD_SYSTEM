"""In-house geometry encoder, part 1: DeepCAD JSON tokeniser, hand-crafted features, model, loss, metrics.

Design: docs/design/GEOMETRY_ENCODER.md. Independent of DeepCAD code. torch is imported lazily so
that tokenising / metrics work without it.

Token layout (max 64 commands, 16 parameter columns, parameters quantised to 256 levels):
  LINE(1)   sx sy ex ey                          (sketch coordinates)
  ARC(2)    sx sy ex ey cx cy sweep ccw          (sketch coordinates)
  CIRCLE(3) cx cy r
  LOOP_END(4) -
  EXTRUDE(5) zx zy zz xx xy xz ox oy oz s e1 e2 operation extent_type   (plane, origin, sketch size)
  EOS(6)
Sketch coordinates are normalised per profile (centre removed, divided by the profile size s); the
profile centre is folded into the extrude origin; the model is normalised to its unit box
((p - bbox_centre) / max bbox side), so absolute scale is not visible to the model.
"""
from __future__ import annotations
import math
import numpy as np

MAX_LEN = 64
NPARAM = 16
LEVELS = 256
PAD, LINE, ARC, CIRCLE, LOOP_END, EXTRUDE, EOS = range(7)
NUM_CMDS = 7
PARAM_COUNT = [0, 4, 8, 3, 0, 14, 0]
OPERATIONS = ['NewBodyFeatureOperation', 'JoinFeatureOperation', 'CutFeatureOperation', 'IntersectFeatureOperation']
EXTENTS = ['OneSideFeatureExtentType', 'SymmetricFeatureExtentType', 'TwoSidesFeatureExtentType']
D2_BINS = 16
FEATURE_NAMES = (['log_lines', 'log_arcs', 'log_circles', 'log_loops', 'log_profiles', 'log_extrudes', 'log_sketches']
                 + ['op_' + o[:-len('FeatureOperation')] for o in OPERATIONS]
                 + ['extent_' + e[:-len('FeatureExtentType')] for e in EXTENTS]
                 + ['dim_1', 'dim_2', 'dim_3', 'axis_aligned_frac', 'distinct_planes',
                    'ext_mean', 'ext_max', 'ext_min', 'prof_size_mean', 'prof_size_max',
                    'circle_frac', 'arc_frac', 'circle_r_mean', 'loops_per_profile_mean', 'loops_per_profile_max',
                    'fill_ratio']
                 + ['d2_%d' % i for i in range(D2_BINS)])
NUM_FEATURES = len(FEATURE_NAMES)


class GeoSkip(Exception):
    """A model that cannot be tokenised; the reason is counted, never hidden."""
    def __init__(self, reason):
        super().__init__(reason); self.reason = reason


def quant(v, lo, hi):
    if not math.isfinite(v):
        raise GeoSkip('non_finite')
    return int(min(LEVELS - 1, max(0, round((v - lo) / (hi - lo) * (LEVELS - 1)))))


def _vec(d):
    return np.array([d['x'], d['y'], d['z']], dtype=float)


def _arc_points(s, e, c, ccw, n=8):
    a0 = math.atan2(s[1] - c[1], s[0] - c[0]); a1 = math.atan2(e[1] - c[1], e[0] - c[0])
    sweep = ((a1 - a0) if ccw else (a0 - a1)) % (2 * math.pi)
    if sweep < 1e-9:
        sweep = 2 * math.pi
    r = math.hypot(s[0] - c[0], s[1] - c[1]); sign = 1 if ccw else -1
    pts = [(c[0] + r * math.cos(a0 + sign * sweep * i / n), c[1] + r * math.sin(a0 + sign * sweep * i / n)) for i in range(n + 1)]
    return sweep, pts


def tokenize_json(data):
    """Return (cmds[int], params[list of 16 ints], feats float32[NUM_FEATURES], info). Raises GeoSkip."""
    try:
        return _tokenize(data)
    except GeoSkip:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError, ZeroDivisionError, OverflowError):
        raise GeoSkip('malformed')


def _tokenize(data):
    if not isinstance(data, dict) or not isinstance(data.get('entities'), dict) or not isinstance(data.get('sequence'), list):
        raise GeoSkip('schema')
    ents = data['entities']
    try:
        bb = data['properties']['bounding_box']
        lo, hi = _vec(bb['min_point']), _vec(bb['max_point'])
    except (KeyError, TypeError):
        raise GeoSkip('no_bbox')
    dims = hi - lo
    gscale = float(dims.max())
    if not math.isfinite(gscale) or gscale <= 1e-9:
        raise GeoSkip('bad_bbox')
    gc = (hi + lo) / 2
    cmds, params = [], []
    n_line = n_arc = n_circle = n_loops = n_profiles = 0
    sketches = set(); op_cnt = [0] * 4; ext_cnt = [0] * 3
    axis_aligned = 0; planes = set(); ext_d = []; prof_s = []; circ_r = []; loops_pp = []
    world_pts = []; fill = 0.0
    n_ext = 0
    for item in data['sequence']:
        if item.get('type') != 'ExtrudeFeature':
            continue
        e = ents[item['entity']]
        op = OPERATIONS.index(e['operation']); et = EXTENTS.index(e['extent_type'])
        d1 = float(e['extent_one']['distance']['value']) / gscale
        d2 = float(e['extent_two']['distance']['value']) / gscale if et == 2 else 0.0
        refs = e['profiles']
        if not refs:
            raise GeoSkip('no_profile')
        first = None
        for ref in refs:
            sk = ents[ref['sketch']]; tr = sk['transform']
            ox, xa, ya, za = _vec(tr['origin']), _vec(tr['x_axis']), _vec(tr['y_axis']), _vec(tr['z_axis'])
            loops = sk['profiles'][ref['profile']]['loops']
            curves = []; pts = []
            for loop in loops:
                lc = []
                for c in loop['profile_curves']:
                    t = c['type']
                    if t == 'Line3D':
                        s, en = _vec(c['start_point'])[:2], _vec(c['end_point'])[:2]
                        lc.append(('L', s, en)); pts += [s, en]
                    elif t == 'Circle3D':
                        ce = _vec(c['center_point'])[:2]; r = float(c['radius'])
                        lc.append(('C', ce, r)); pts += [ce + [r, 0], ce - [r, 0], ce + [0, r], ce - [0, r]]
                    elif t == 'Arc3D':
                        s, en, ce = _vec(c['start_point'])[:2], _vec(c['end_point'])[:2], _vec(c['center_point'])[:2]
                        ccw = _vec(c['normal'])[2] >= 0
                        sweep, ap = _arc_points(s, en, ce, ccw)
                        lc.append(('A', s, en, ce, sweep, ccw)); pts += [np.array(p) for p in ap]
                    else:
                        raise GeoSkip('curve_' + str(t))
                curves.append(lc)
            pts = np.array(pts); plo, phi = pts.min(0), pts.max(0)
            s = float((phi - plo).max())
            if not math.isfinite(s) or s <= 1e-9:
                raise GeoSkip('degenerate_profile')
            cc = (plo + phi) / 2
            n_profiles += 1; sketches.add(ref['sketch']); prof_s.append(s / gscale); loops_pp.append(len(loops))
            for lc in curves:
                n_loops += 1
                for c in lc:
                    if c[0] == 'L':
                        cmds.append(LINE); n_line += 1
                        params.append([quant((c[1][0] - cc[0]) / s, -.6, .6), quant((c[1][1] - cc[1]) / s, -.6, .6),
                                       quant((c[2][0] - cc[0]) / s, -.6, .6), quant((c[2][1] - cc[1]) / s, -.6, .6)])
                    elif c[0] == 'C':
                        cmds.append(CIRCLE); n_circle += 1; circ_r.append(c[2] / s)
                        params.append([quant((c[1][0] - cc[0]) / s, -.6, .6), quant((c[1][1] - cc[1]) / s, -.6, .6), quant(c[2] / s, 0, 1)])
                    else:
                        cmds.append(ARC); n_arc += 1
                        params.append([quant((c[1][0] - cc[0]) / s, -.6, .6), quant((c[1][1] - cc[1]) / s, -.6, .6),
                                       quant((c[2][0] - cc[0]) / s, -.6, .6), quant((c[2][1] - cc[1]) / s, -.6, .6),
                                       quant((c[3][0] - cc[0]) / s, -.6, .6), quant((c[3][1] - cc[1]) / s, -.6, .6),
                                       quant(c[4], 0, 2 * math.pi), 255 if c[5] else 0])
                cmds.append(LOOP_END); params.append([])
            R = np.stack([xa, ya], axis=1)  # world = origin + R @ local
            wp = ox + pts @ R.T
            idx = np.linspace(0, len(wp) - 1, min(len(wp), 24)).astype(int)
            world_pts.append((wp[idx] - gc) / gscale)
            if first is None:
                wo = ox + R @ cc
                first = (xa, za, (wo - gc) / gscale, s / gscale)
            fill += (s * s) / (gscale * gscale)
        xa, za, wo, sn = first
        cmds.append(EXTRUDE)
        params.append([quant(v, -1, 1) for v in (*za, *xa)] + [quant(v, -1, 1) for v in wo]
                      + [quant(sn, 0, 1), quant(d1, -1, 1), quant(d2, -1, 1), op, et])
        n_ext += 1; op_cnt[op] += 1; ext_cnt[et] += 1
        axis_aligned += int(np.max(np.abs(za)) > 0.999)
        planes.add(tuple(np.round(za, 2)))
        ext_d.append(abs(d1) + abs(d2) if et != 1 else 2 * abs(d1))
    if n_ext == 0:
        raise GeoSkip('no_extrude')
    cmds.append(EOS); params.append([])
    truncated = len(cmds) > MAX_LEN
    if truncated:
        cmds = cmds[:MAX_LEN - 1] + [EOS]; params = params[:MAX_LEN - 1] + [[]]
    total_curves = max(1, n_line + n_arc + n_circle)
    P = np.concatenate(world_pts) if world_pts else np.zeros((2, 3))
    if len(P) > 96:
        P = P[np.linspace(0, len(P) - 1, 96).astype(int)]
    dd = np.sqrt(((P[:, None] - P[None]) ** 2).sum(-1))[np.triu_indices(len(P), 1)]
    h = np.histogram(dd, bins=D2_BINS, range=(0, math.sqrt(3)))[0].astype(float) if len(dd) else np.zeros(D2_BINS)
    h = h / max(1.0, h.sum())
    ds = np.sort(dims / gscale)[::-1]
    f = ([math.log1p(n_line), math.log1p(n_arc), math.log1p(n_circle), math.log1p(n_loops), math.log1p(n_profiles),
          math.log1p(n_ext), math.log1p(len(sketches))]
         + [c / n_ext for c in op_cnt] + [c / n_ext for c in ext_cnt]
         + list(ds) + [axis_aligned / n_ext, math.log1p(len(planes)),
                       float(np.mean(ext_d)), float(np.max(ext_d)), float(np.min(ext_d)),
                       float(np.mean(prof_s)), float(np.max(prof_s)),
                       n_circle / total_curves, n_arc / total_curves, float(np.mean(circ_r)) if circ_r else 0.0,
                       float(np.mean(loops_pp)), float(np.max(loops_pp)), min(fill, 20.0)]
         + list(h))
    assert len(f) == NUM_FEATURES, len(f)
    return cmds, params, np.array(f, dtype=np.float32), {'truncated': truncated}


def pack(cmds, params):
    """-> uint8 arrays (MAX_LEN,) and (MAX_LEN, NPARAM)."""
    c = np.zeros(MAX_LEN, dtype=np.uint8); p = np.zeros((MAX_LEN, NPARAM), dtype=np.uint8)
    c[:len(cmds)] = cmds
    for i, row in enumerate(params):
        p[i, :len(row)] = row
    return c, p


# ----------------------------------------------------------------------------------------------
# Model
# ----------------------------------------------------------------------------------------------
def build_model(d_model=256, heads=8, layers=4, out_dim=2560, ff=1024, dropout=0.1):
    import torch
    import torch.nn as nn

    class GeometryEncoder(nn.Module):
        def __init__(self):
            super().__init__()
            self.cfg = dict(d_model=d_model, heads=heads, layers=layers, out_dim=out_dim, ff=ff, dropout=dropout)
            self.cmd_emb = nn.Embedding(NUM_CMDS, d_model)
            self.param_emb = nn.Embedding(NPARAM * (LEVELS + 1), d_model)
            self.pos_emb = nn.Embedding(MAX_LEN, d_model)
            layer = nn.TransformerEncoderLayer(d_model, heads, ff, dropout, activation='gelu', batch_first=True, norm_first=True)
            self.enc = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
            self.norm = nn.LayerNorm(d_model)
            self.proj = nn.Linear(d_model, out_dim)
            self.logit_scale = nn.Parameter(torch.tensor(math.log(1 / 0.07)))
            self.register_buffer('pcount', torch.tensor(PARAM_COUNT, dtype=torch.long), persistent=False)
            self.register_buffer('col', torch.arange(NPARAM, dtype=torch.long) * (LEVELS + 1), persistent=False)
            self.register_buffer('colidx', torch.arange(NPARAM, dtype=torch.long), persistent=False)

        def forward(self, cmds, params):
            cmds = cmds.long(); B, L = cmds.shape
            valid = self.colidx[None, None, :] < self.pcount[cmds][..., None]
            idx = self.col[None, None, :] + torch.where(valid, params.long() + 1, torch.zeros_like(params, dtype=torch.long))
            x = self.cmd_emb(cmds) + self.param_emb(idx).sum(2) + self.pos_emb(torch.arange(L, device=cmds.device))[None]
            pad = cmds == PAD
            h = self.norm(self.enc(x, src_key_padding_mask=pad))
            m = (~pad).unsqueeze(-1).to(h.dtype)
            pooled = (h * m).sum(1) / m.sum(1).clamp(min=1)
            z = self.proj(pooled).float()
            return torch.nn.functional.normalize(z, dim=-1)
    return GeometryEncoder()


def contrastive_loss(z, t, logit_scale, reg_weight=0.1):
    """Symmetric InfoNCE between geometry embeddings z and case targets t (both L2-normalised) + cosine regression."""
    import torch
    import torch.nn.functional as F
    s = logit_scale.exp().clamp(max=100.0)
    logits = s * z @ t.T
    lab = torch.arange(len(z), device=z.device)
    nce = (F.cross_entropy(logits, lab) + F.cross_entropy(logits.T, lab)) / 2
    reg = (1 - (z * t).sum(-1)).mean()
    return nce + reg_weight * reg, nce.detach(), reg.detach()


# ----------------------------------------------------------------------------------------------
# Metrics (numpy/torch-free apart from sorting via numpy)
# ----------------------------------------------------------------------------------------------
def rank_metrics(scores, gains, ks=(10, 50)):
    """scores, gains: (Q, N). Stable descending order (ties keep pool order). Gain>0 = relevant.

    Recall@k = relevant in top k / all relevant; MRR = 1/rank of the first relevant; nDCG@10 uses the
    graded gains (linear gain, log2 discount). Returns dict of per-query arrays.
    """
    scores = np.asarray(scores, dtype=np.float64); gains = np.asarray(gains, dtype=np.float64)
    order = np.argsort(-scores, axis=1, kind='stable')
    g = np.take_along_axis(gains, order, axis=1)
    rel = g > 0
    nrel = rel.sum(1)
    out = {}
    for k in ks:
        out['recall@%d' % k] = rel[:, :k].sum(1) / np.maximum(nrel, 1)
    first = np.where(rel.any(1), rel.argmax(1) + 1, 0)
    out['mrr'] = np.where(first > 0, 1.0 / np.maximum(first, 1), 0.0)
    disc = 1.0 / np.log2(np.arange(2, 12))
    dcg = (g[:, :10] * disc[None, :g[:, :10].shape[1]]).sum(1)
    ideal = -np.sort(-gains, axis=1)[:, :10]
    idcg = (ideal * disc[None, :ideal.shape[1]]).sum(1)
    out['ndcg@10'] = np.where(idcg > 0, dcg / np.maximum(idcg, 1e-12), 0.0)
    return out


def random_expected_metrics(gains, ks=(10, 50)):
    """Exact expectation of the same metrics for a uniformly random permutation of the pool."""
    gains = np.asarray(gains, dtype=np.float64); Q, N = gains.shape
    rel = gains > 0; nrel = rel.sum(1)
    out = {}
    for k in ks:
        out['recall@%d' % k] = np.full(Q, min(k, N) / N)
    mrr = np.zeros(Q)
    for q in range(Q):
        r = int(nrel[q])
        if r == 0:
            continue
        # P(first relevant at i) = C(N-i, r-1)/C(N, r); iterate with ratios for stability.
        p = r / N; tot = 0.0
        for i in range(1, N - r + 2):
            tot += p / i
            if i >= N - r + 1:
                break
            p *= (N - r - i + 1) / (N - i)
            if p < 1e-14:
                break
        mrr[q] = tot
    out['mrr'] = mrr
    disc = (1.0 / np.log2(np.arange(2, 12))).sum() if N >= 10 else (1.0 / np.log2(np.arange(2, N + 2))).sum()
    ideal = -np.sort(-gains, axis=1)[:, :10]
    idcg = (ideal * (1.0 / np.log2(np.arange(2, 12)))[None, :ideal.shape[1]]).sum(1)
    out['ndcg@10'] = np.where(idcg > 0, gains.mean(1) * disc / np.maximum(idcg, 1e-12), 0.0)
    return out


def bootstrap_ci(values, n_boot=2000, seed=0):
    values = np.asarray(values, dtype=np.float64)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(values), size=(n_boot, len(values)))
    means = values[idx].mean(1)
    return float(values.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))
