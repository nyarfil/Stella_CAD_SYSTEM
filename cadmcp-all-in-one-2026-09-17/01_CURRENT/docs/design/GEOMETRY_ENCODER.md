# In-house geometry encoder (queue item 5) — design

## Goal and honest framing
Learn an embedding of a CAD model's construction (DeepCAD sketch-and-extrude JSON) into the
same 2560-d space as the Qwen3-Embedding-4B function-keyword vectors the current semantic search
uses. Uses: (1) find CAD by function text when the case has NO annotation (the user's own models,
new parts, scans converted later), (2) shape-to-shape similarity, (3) a second opinion on the
VLM/LLM-inferred annotations. It does not replace the text search; it is a separate, explicitly
selected mode with no fallback either way. It is enabled for users only if the held-out evaluation
beats the baselines below; otherwise it ships as experimental with the numbers.

## Data (already on this machine; nothing to download)
Knowledge root (`CADMCP_REQ2CAD_ROOT`, here `E:/aiwork/Stella_CAD_SYSTEM/cadmcp-workspace/knowledge/req2cad`):
- `catalog.sqlite`: 175,978 cases, 24,757 functions, 539,799 case-function links, assets
  (kind `deepcad_tar`). Read the schema in `cadmcp_brain/req2cad/catalog.py`.
- `semantic/keywords.json` ([id, keyword] x 24,757) + `semantic/vectors.npy` (24,757 x 2560, float32,
  normalised Qwen vectors) + `manifest.json`.
- `archive-cache/<sha>.tar` (normalised DeepCAD archive, 215k JSON members) - read members via
  the existing asset code path (`cadmcp_brain/req2cad/assets.py`) or tarfile with the member index;
  `data/train_val_test_split.json` inside it is the official DeepCAD split - use it.
Read-only: never write into the catalog, semantic index or archives. New outputs go to
`<root>/models/geometry_encoder/<version>/` (checkpoint, manifest with data hashes, split hash,
seed, hyper-parameters, code version, metrics).

## Model
- Tokenise each DeepCAD JSON into a sequence (max 64 commands): command type (line, arc,
  circle, loop/profile end, extrude, EOS) + up to 16 parameters quantised to 256 levels after
  normalising the model into a unit box (the DeepCAD convention; implement it, do not depend on
  DeepCAD code). Unparseable JSON -> skipped and counted.
- Encoder: small transformer (about 4 layers, d=256, 8 heads, learned positional + command +
  parameter embeddings), mean-pooled, projection to 2560, L2-normalised.
- Target per case: the normalised mean of its function-keyword vectors (from `vectors.npy`).
- Loss: symmetric InfoNCE (CLIP-style) between geometry embeddings and case targets in the batch
  (learned temperature) + small cosine-regression term to the target. Fixed seeds; deterministic
  data order per epoch; mixed precision on CUDA (RTX 4080 SUPER present).
- Training budget: stop at a wall-clock cap (default 60 min) or at best validation metric;
  checkpoint = best on the validation split.

## Evaluation (held-out = DeepCAD test split cases that have Req2CAD annotations)
Queries: for a fixed-seed sample of up to 2,000 test functions (keywords linked to test cases),
the query vector is that keyword's Qwen vector. Relevant set = test cases linked to any keyword
whose Qwen cosine with the query >= 0.7 (the same rule the current search uses), graded by the
max cosine. Pool = all test cases.
Systems compared on the identical pool and queries:
1. `encoder`: rank test cases by cosine(query, geometry embedding) - annotations of test cases
   NOT used (unlabeled setting).
2. `handcrafted_knn`: the existing hand-built shape features (`req2cad/geometry.py` WL-graph and
   point-sample features, or a documented cheap subset if those need STEP; state which) -> for each
   test case, average the target vectors of its k=10 nearest TRAIN cases -> rank by cosine. Also
   unlabeled.
3. `random`: expected metric values for a random ranking.
4. `text_search_reference`: the current semantic search scoring restricted to the pool, which DOES
   use the test annotations - an upper reference, not a competitor in the unlabeled setting.
Metrics: Recall@10, Recall@50, MRR, nDCG@10, with 95% bootstrap CIs (fixed seed). Also
shape-to-shape: for each test case, mean Jaccard overlap of function sets between it and its top-10
encoder neighbours vs handcrafted neighbours vs random.
Output: `benchmarks/results/geometry_encoder_<version>.json` + a short markdown summary.
Acceptance for user-facing enablement: encoder beats handcrafted_knn on nDCG@10 and Recall@50 with
non-overlapping CIs. Otherwise the mode is marked `experimental: true` in its manifest and the
search response says so.

## Integration
- `brain_fs_search(mode="geometry_encoder", ...)`: query text -> Qwen query vector (existing code
  path) -> cosine against precomputed geometry embeddings of all cases (built once by
  `python -m cadmcp_brain.req2cad encode-geometry`, stored under the encoder version dir with the
  case uid order and hashes). Missing/stale encoder -> explicit error code, never a silent switch to
  another mode. Responses state the mode, encoder version, experimental flag and evaluation file.
- Existing modes unchanged and still default.

## Tests (fast; fixture-based, CPU)
Tokeniser on the repo's public DeepCAD JSON fixtures (`examples/public-cases/cad_json`) with known
command counts; model forward shape/normalisation; a 2-epoch CPU training on a tiny synthetic set
improves the loss; evaluation metrics on a hand-made ranking with known values; search mode with a
missing encoder raises the error code; manifest records hashes.
