# Sources, attribution and separate data terms

Original implementation in this distribution: MIT, see LICENSE. No upstream model
weights or full research datasets are redistributed in this ZIP.

Req2CAD: Qianzhi Jing, Hankai Lu, Shuojin Huang, Peter Childs, Liuqing Chen.
“Req2CAD: bridging functional requirements and parametric CAD models to support
conceptual 3D design”, CHI 2026. https://doi.org/10.1145/3772318.3791949
Annotation dataset card: CC-BY-4.0, https://huggingface.co/datasets/QianzhiJing/Req2CAD
Preserve author/source attribution with any downloaded/reused annotations.

DeepCAD: https://github.com/rundiwu/DeepCAD — repository code MIT. Check the data
source terms separately; the repository code license is not automatically a license
to every original Onshape design. Native replay here is independently implemented
against the public JSON semantics, not a vendored import of the upstream cadlib.

Qwen3-Embedding-4B: https://huggingface.co/Qwen/Qwen3-Embedding-4B — model card
Apache-2.0. Owner-side download records the exact revision and file hashes.

Text2CAD rendered images are not downloaded by this package. That source has
separate access/license conditions; Req2CAD's annotation license does not replace
those conditions. Views here are generated from the actual registered CAD.

Other inspirations retained from v0.1: agent-spec, Agentic Engineering Design,
Multi-Agent-CAD, n3r/AgentCAD. See archived audit for the inspected files.

Author-created 9000/900000xx test fixtures are MIT examples made for this package,
not actual Req2CAD geometry. Do not relabel them as dataset or manufacturer assets.


## Four public-mirror examples added in 0.3.0

`examples/public-cases/provenance.json` lists the exact source repository commit,
UID, Git blob SHA and SHA-256 for four selected JSON models. They are not authored
fixtures, not the complete corpus, and not matched to the official data archive.
Their data rights remain separate from this code's MIT license. The included
annotation descriptions are marked paraphrases; published function keywords and
attribution are preserved. Derived demo geometry and renders are explicitly
reference-based trial outputs, not manufacturer-certified parts. No Text2CAD
access-restricted images or font files are included.

iDesignGPT morphological-analysis prompts and the public hankaiuu/Req2CAD backend
were inspected as method references; see docs/UPSTREAM_AUDIT_JA.md. Original
upstream runtimes, model weights and complete data have not been vendored.
