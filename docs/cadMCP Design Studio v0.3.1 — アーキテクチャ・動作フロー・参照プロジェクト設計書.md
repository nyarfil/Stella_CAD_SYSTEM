# cadMCP Design Studio v0.3.1
## アーキテクチャ・動作フロー・参照プロジェクト設計書

## 1. このツールが何をするものか

cadMCP Design Studioの目的は、

**「人間の雑な要求を、そのままCAD操作命令へ変換すること」ではない。**

目的は、

```text
雑な要求
 ↓
設計意図を理解
 ↓
必要な機能を分解
 ↓
過去の実CADから構造を調査
 ↓
複数の機構案を構成
 ↓
力・拘束・組立・製造面を検討
 ↓
CADとして実体化
 ↓
実形状を測定
 ↓
レビュー・修正
 ↓
人間へ成果物と根拠を提示
```

という、**機械設計そのもののプロセスをAIに実行させること**である。

最大の特徴は、

> LLMだけの知識から構造を「想像」させるのではなく、Req2CAD等の実CAD構造知識を検索して設計させる

ことである。

---

# 2. 全体構造

```text
┌─────────────────────────────────────────────────────┐
│                     HUMAN                           │
│ 「このサイドボタン押しやすくして」                 │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│ ① Cursor / Host Agent Layer                        │
│                                                     │
│ .cursor/mcp.json                                    │
│ .cursor/rules/                                      │
│ .cursor/skills/                                     │
│ .cursor/commands/                                   │
│ .cursor/agents/                                     │
│                                                     │
│ 人間との会話・全体オーケストレーション              │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│ ② Design Brain / Intent Layer                      │
│                                                     │
│ Raw request                                         │
│ → DesignIntent                                      │
│ → Requirements                                      │
│ → Constraints                                       │
│ → Unknowns                                          │
│ → Protected Intent                                  │
│                                                     │
│ models.py / engine.py / gates.py                    │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│ ③ Functional Reasoning Layer                       │
│                                                     │
│ Requirement                                         │
│      ↓                                              │
│ Function                                            │
│      ↓                                              │
│ Behavior                                            │
│                                                     │
│ 例：                                                │
│ 「押しやすい」                                      │
│ → finger forceをswitchへ伝達                       │
│ → 横方向移動                                       │
│ → switch plungerを押す                             │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│ ④ Function–Structure Knowledge Base                │
│                  ★中核★                             │
│                                                     │
│ Req2CAD                                             │
│                                                     │
│ function                                            │
│       ↕ semantic search                             │
│ CAD UID                                             │
│       ↓                                             │
│ DeepCAD raw CAD                                     │
│       ↓                                             │
│ Geometry / Topology                                 │
│                                                     │
│ cadmcp_brain/req2cad/                               │
│ ├ catalog.py                                        │
│ ├ semantic.py                                       │
│ ├ assets.py                                         │
│ ├ geometry.py                                       │
│ ├ worker.py                                         │
│ ├ service.py                                        │
│ └ mixin.py                                          │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│ ⑤ Concept Synthesis Layer                          │
│                                                     │
│ 実例A                                               │
│ 実例B                                               │
│ 実例C                                               │
│      ↓                                              │
│ Morphological Matrix                               │
│      ↓                                              │
│ Candidate Concept A/B/C/D                          │
│                                                     │
│ iDesignGPT系の構想設計方法                         │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│ ⑥ Engineering Structure Layer                     │
│                                                     │
│ Requirement                                        │
│ Function                                           │
│ Mechanism                                          │
│ Part                                               │
│ Interface                                          │
│ Load path                                          │
│ Constraint                                         │
│ Verification                                       │
│                                                     │
│ Design-State Graph的構造                           │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│ ⑦ CAD Planning Layer                              │
│                                                     │
│ Design Contract                                    │
│ ↓                                                   │
│ CAD Recipe / Plan                                  │
│ ↓                                                   │
│ Part / Feature / Operation                         │
│                                                     │
│ 「何を作るか」と「どうCAD操作するか」を分離         │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│ ⑧ Deterministic CAD Executor                      │
│                                                     │
│ CadQuery / OCCT / AgentCAD                         │
│                                                     │
│ reference                                           │
│ box                                                 │
│ cylinder                                            │
│ transform                                           │
│ boolean                                             │
│ fillet                                              │
│ etc.                                                │
│                                                     │
│ → STEP                                              │
│ → STL                                               │
│ → Assembly                                          │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│ ⑨ Geometry Verification                           │
│                                                     │
│ BRep validity                                       │
│ bounding box                                        │
│ clearance                                           │
│ interference                                        │
│ body count                                          │
│ topology                                            │
│ motion sampling                                     │
│ reference consistency                               │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│ ⑩ Engineering Review Team                         │
│                                                     │
│ Requirements reviewer                              │
│ Mechanism reviewer                                 │
│ Assembly reviewer                                  │
│ Manufacturing reviewer                             │
│ Verification reviewer                              │
│                                                     │
│ ↓ critique                                          │
│ ↓ cross critique                                    │
│ ↓ repair                                            │
│ ↓ re-verification                                   │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
                     HUMAN
```

---

# 3. Cursor層

## 場所

```text
.cursor/
├─ mcp.json
├─ rules/
│   └─ cadmcp-design-brain.mdc
├─ skills/
│   └─ cadmcp-cursor/
│       └─ SKILL.md
├─ agents/
│   ├─ cadmcp-requirements.md
│   ├─ cadmcp-mechanism.md
│   ├─ cadmcp-assembly.md
│   ├─ cadmcp-manufacturing.md
│   └─ cadmcp-verification.md
└─ commands/
    ├─ cad-check.md
    ├─ cad-design.md
    └─ cad-review.md
```

最新版はこれらをCursorプロジェクトへ追加する。既存の他MCPや環境変数は残す方針になっている。

## 役割

Cursor自体は、

**「設計脳を実行するホスト」**

である。

CursorにCAD知識を全部詰め込むのではない。

CursorのAgentは、

```text
次にどの機能を呼ぶか
何を調査するか
どの構造候補を比較するか
どこを修正するか
```

を判断する。

実CAD検索・計測・CAD生成などはMCP側へ任せる。

### 設計意図

LLMへ巨大なプロンプトとCADデータ全部を投げると、

- Contextが肥大化する
- 根拠を取り違える
- 前の推測を事実として扱う
- CAD操作まで文章で曖昧になる

という問題が起こる。

そのため、

**Cursor = reasoning / orchestration**

**MCP = engineering state + tools**

と分離している。

---

# 4. Design Brain

## 主な場所

```text
cadmcp_brain/
├─ models.py
├─ engine.py
├─ gates.py
├─ api.py
├─ protocol.py
└─ studio...
```

Req2CAD実装資料では、`models.py / engine.py / gates.py`が設計案・作業契約と参照根拠を接続する場所として定義されている。

## 役割

ここはCADを作る場所ではない。

**設計上の事実を管理する場所**である。

例えば、

```text
Original Request:
サイドボタンを押しやすくしたい

Requirement:
少ない指力でswitchを作動させる

Constraint:
PCB位置変更禁止

Preference:
部品数少なめ

Unknown:
必要stroke不明

Protected Intent:
既存外形を大きく変えない

Inferred:
lever機構が適する可能性
```

を別々に保存する。

---

# 5. agent-specから持ってきた部分

## 元

```text
ZhangHanDong/agent-spec
skills/agent-spec-intent-compiler/SKILL.md
```

agent-specでは、自然言語から要求を作る際、

- source excerpt
- confidence
- open questions
- source trace
- human-confirmed requirement

を明確に分離する。

特に、

> 推測した要求を勝手に確定事項へ変更しない

というルールを強く持つ。

## cadMCPでの場所

```text
models.py
engine.py
gates.py
Intent / Requirement / Unknown / SourceRef
```

## 採用した意図

LLMの最大の弱点の一つは、

```text
「たぶんこうだろう」
↓
次のターン
↓
「これは確定仕様です」
```

になりやすいこと。

そこで、

```text
USER FACT
MODEL INFERENCE
DESIGN DECISION
UNKNOWN
```

を分離している。

---

# 6. Functional Reasoning

設計指示を直接形状にしない。

まず、

```text
Requirement
↓
Function
↓
Behavior
```

へ変換する。

例：

```text
「サイドボタンを押しやすくしたい」

↓

FUNCTION
Transmit finger force

Guide button

Actuate switch

Return button

Limit overtravel
```

このFunctionが、Req2CAD検索のQueryになる。

---

# 7. Req2CAD — Function–Structure Knowledge Base

これは現在のシステムで最も重要な層である。

## 本家の場所

```text
hankaiuu/Req2CAD

Python_backend/
├─ func2cad.py
├─ func2cad_api.py
├─ cad2topo_2d.py
├─ get_geom_embed.py
├─ get_geom_embed_api.py
├─ sketch_comb.py
├─ sketch_comb_api.py
└─ structure_assembly_api.py
```

本家READMEでも、

```text
Functional Structure Reasoning
Structure Generation and Reasoning
Structure Assembly
```

の3系統が主要構造として明記されている。

---

# 8. Req2CAD `func2cad.py`

## 本家

```text
Req2CAD/Python_backend/func2cad.py
```

## やっていること

Functionの文章をEmbeddingし、

```text
Function
↓
Qwen embedding
↓
function vocabulary similarity
↓
function → CAD ID
```

へ変換する。

本家コードでは、

```text
query_related_func()
cad4single_func()
cad4multifunc()
```

があり、複数機能の場合は、それぞれの機能に対応するCADを集め、**何個の要求機能にヒットしたか**で候補をまとめている。

## cadMCP側

```text
cadmcp_brain/req2cad/
├─ catalog.py
└─ semantic.py
```

### catalog.py

```text
CAD UID
Function Description
Function Keywords
Source
Hash
```

などの関係を管理。

### semantic.py

FunctionをEmbeddingしてCAD候補を探す。

## 採用した意図

LLMへ、

> 軸を支持する構造考えて

と聞くだけでは、

LLM自身の知識の中から

```text
boss
hole
bearing
clip
```

を想像する。

Req2CADを使う場合、

```text
support rotating shaft
↓
実際にその機能が注釈されたCAD
↓
実形状
```

を見る。

つまり、

**Language → Languageではなく**

**Language → Real CAD**

へ繋ぐ。

ここがこのプロジェクトの中心思想である。

---

# 9. DeepCAD

## 元

```text
rundiwu/DeepCAD
```

DeepCADはCADを、

```text
Sketch
Extrude
Boolean
...
```

という構築シーケンスとして保持するデータセット／モデルである。

公開データには、

```text
cad_json
cad_vec
```

があり、`cad_json`には元のCAD構築シーケンスが保存されている。STEP出力用のコードも公開されている。

## cadMCP側

```text
req2cad/assets.py
req2cad/geometry.py
req2cad/worker.py
```

### assets.py

UIDから、

```text
DeepCAD JSON
STEP
source hash
```

を特定。

### geometry.py

JSONをBRepへ復元。

### worker.py

CAD処理を別プロセスで実行し、

```text
STEP
STL
geometry measurements
topology
```

を生成。

## 意図

Req2CADのFunction labelだけでは、

「そのCADがどんな構造か」

は分からない。

そのため、

```text
Req2CAD annotation
↓ UID
DeepCAD CAD
↓
実形状
```

へ戻す。

---

# 10. Req2CADのTopology

## 本家

```text
Python_backend/cad2topo_2d.py
```

ここではSTEPから、

```text
Face
Edge
Surface type
Curvature
Adjacency
```

を抽出し、グラフ化する。

さらに、

```text
Weisfeiler-Lehman kernel
VertexHistogram
```

を使うコードが存在する。

## cadMCP側

```text
req2cad/geometry.py
```

で、

```text
face type
shared-edge adjacency
WL topology feature
```

を抽出する。

## 意図

単純な画像類似度では、

```text
穴がある
軸を囲っている
面がどこに繋がる
```

という「構造」が分かりにくい。

そのため、

**CADの面と接続関係そのもの**

を見る。

---

# 11. Req2CAD Geometry Embedding

## 本家

```text
Python_backend/get_geom_embed.py
```

本家はPoint Cloudから学習済みモデルを使ってShape Embeddingを生成する。

`get_shape_embed()`を使用して形状特徴を生成している。

## 現在のcadMCP

ここは**完全移植していない**。

現在は、

```text
surface sampling
D2 distance histogram
radius histogram
covariance eigenvalues
WL topology
```

などの非学習特徴を使用する。

つまり、

```text
Req2CAD original learned geometry encoder
≠
current cadMCP geometry matcher
```

である。

## 理由

元モデルには、

```text
checkpoint
CUDA
PyTorch
torch_cluster
cuML
```

などへの依存がある。

まず、

**実CADを確実に読み取る経路**

を優先した。

将来的には、本家Geometry Encoderを追加して

```text
semantic function similarity
+
learned geometry similarity
+
topology similarity
```

の3系統検索にする価値がある。

---

# 12. Req2CAD Structure Assembly

## 本家

```text
Python_backend/structure_assembly_api.py
```

ここには、

```text
STEP loading
shape property extraction
boolean fusion
transform
distance
assembly
```

などのOpenCascade処理が存在する。

## 現在のcadMCP

本家をそのままBackendにはしていない。

代わりに、

```text
CAD Recipe
↓
typed operation
↓
deterministic CAD executor
```

にしている。

理由は、本家のAPIをそのまま自由に呼ばせるより、

```text
何を変更するか
何を保存するか
どのConstraintを満たすか
```

を先に固定した方が、自動修正時に壊れにくいからである。

---

# 13. iDesignGPT

## 元

```text
Songkai-Liu-SJTU/iDesignGPT

code/agent/
├─ Functional Structure Decomposition/
├─ Morphological analysis/
├─ Triz/
├─ Brainstorming/
├─ Biomimetic design/
└─ Scamper/
```

特に採用価値が高いのは、

```text
Functional Structure Decomposition
Morphological Matrix
```

である。

Morphological Matrixでは、

**各Functionに最低2つ以上の実現方法を用意し、組み合わせを作る**

という方法を取る。

## cadMCP側

Concept Synthesis段階。

例えば、

```text
FUNCTION: return button

Option A:
printed flexure

Option B:
switch spring itself

Option C:
separate compliant arm
```

という候補を作る。

さらに、

```text
Actuation A
+
Guide B
+
Return A
+
Stop C
```

のように組み合わせる。

## 意図

LLMは最初に思い付いた案に固執しやすい。

そこで、

```text
一案を考える
```

ではなく、

```text
機能ごとに構造候補を出す
↓
組み合わせる
```

へ変える。

Req2CADとは非常に相性がよい。

つまり、

```text
iDesignGPT
=
どう探索するか

Req2CAD
=
何を参考にするか
```

である。

---

# 14. Agentic Engineering Design

## 元

```text
SoheylM/agentic-eng-design
data_models.py
```

ここではDesign-State Graphを使い、

```text
DesignNode
Embodiment
PhysicsModel
linked_reqs
verification_plan
```

を保持する。

## cadMCPでの思想

設計を単なるSTEPファイルとして扱わない。

例えば、

```text
REQ-012
↓
FUNC-08
↓
MECH-03
↓
PART-side-button
↓
FEATURE-flexure-root
↓
VERIFY-fatigue
```

という関係を持つ。

## 意図

「この形状はなぜ存在するのか？」

を後から追跡できるようにするため。

AIが修正するときにも、

```text
このboss削除していい？
```

ではなく、

```text
このbossはPCB XY位置決めを実現する
```

と理解できる。

---

# 15. Multi-Agent-CAD

## 元

```text
Pan-Chera/Multi-Agent-CAD

multi_agent_cad/
├─ WORKFLOW.md
└─ schemas.py
```

MACの重要思想は、

**Agent間で全文会話を渡さず、型付き状態だけを渡す**

ことである。

本家では、

```text
User request
↓
CADBrief
↓
ArchitectPlan
↓
Python CAD code
↓
QA
```

という構造になっている。

## cadMCP

この思想を、

```text
DesignIntent
FunctionBrief
Concept
DesignContract
CADRecipe
VerificationReport
```

という中間表現に使っている。

## 意図

LLM同士が、

```text
Agent A:
私はこう思います...

Agent B:
Aの文章を読んで...
```

と延々会話するより、

```text
Function:
Actuate switch

Direction:
+X

Constraint:
PCB fixed
```

と渡した方が、

- 誤解が減る
- tokenが減る
- 検証可能
- JSON Schemaで止められる

ため。

---

# 16. AI-CAD

## 元

```text
ai-cad-labs/ai-cad

.shared/agents/
├─ planner/
├─ cad_designer/
├─ dfma_inspector/
├─ validator/
├─ repair/
├─ reviewer/
└─ assembly_resolver/
```

Plannerは、

```text
part decomposition
interfaces
make/buy
constraints
assembly order
```

を定義する。

## cadMCPへ持ってきた思想

特に、

```text
Part
Interface
Assembly
Manufacturing
Verification
```

をCAD生成前に考えること。

そして、

**修正しても前より悪化したら採用しない**

というRegression Gateの考え方。

## 意図

AI CADで非常によくある、

```text
干渉を直した
↓
でも肉厚が不足した

肉厚を直した
↓
でも組み立てられなくなった
```

を防止する。

---

# 17. AgentCAD

## 元

```text
n3r/AgentCAD
```

AgentCADはCAD正本候補。

特に、

```text
agentcad/toolkit/specs.py
```

には、

```text
check_valid
check_mass
check_bbox
check_wall
check_fem_static
...
```

といった**Executable Spec**が存在する。

またAgent APIは、CAD機能をMCP／HTTPから呼べる単一Tool Registryとして提供する。

## cadMCPでの位置

最終CAD Backend候補。

```text
Design Studio
↓
validated plan
↓
AgentCAD
↓
production CAD
```

という関係。

## 意図

Design Brain自身が第2のCAD正本にならないようにする。

つまり、

```text
Design Brain
= why / what

AgentCAD
= actual CAD
```

という分業。

---

# 18. CAD生成部

CAD生成は、

**LLMが自由にPythonを書くことを基本方式にしていない。**

まず、

```text
CADRecipe
```

を作る。

例：

```text
part: side_button

operations:

reference:
  PCB

create:
  actuator_body

create:
  flexure

boolean:
  join

fillet:
  root

verify:
  switch_clearance
```

これを決定的なExecutorが実行する。

## 意図

LLMによる直接コード生成では、

```text
API hallucination
座標取り違え
boolean順序ミス
存在しないFeature参照
```

などが起こる。

そのため、

```text
LLM
↓
typed recipe
↓
schema validation
↓
CAD executor
```

にしている。

---

# 19. Geometry Verification

CADを作った後は、

**LLMに「大丈夫そう？」と聞かない。**

実形状を測る。

現在確認している系統は、

```text
BRep validity
solid count
bounding box
distance
clearance
interference volume
motion sampling
topology
reference hash
```

等である。

未実装の検査は、

```text
UNKNOWN
```

にする。

別の簡単な検査で代用してPASSにはしない。

---

# 20. 5役Reviewer

Cursor版では、

```text
.cursor/agents/

requirements
mechanism
assembly
manufacturing
verification
```

を用意している。

### Requirements Reviewer

見るもの：

```text
ユーザー原文
Requirement
Constraint
Unknown
勝手な推測
```

### Mechanism Reviewer

見るもの：

```text
force path
reaction force
degrees of freedom
return mechanism
overtravel
failure mode
```

### Assembly Reviewer

見るもの：

```text
part interfaces
insertion direction
tool access
assembly order
serviceability
```

### Manufacturing Reviewer

見るもの：

```text
FDM suitability
overhang
support removal
wall
print orientation
stress vs layer direction
```

### Verification Reviewer

見るもの：

```text
本当に測定したか
検査漏れ
invalid assumptions
stale evidence
```

---

# 21. Debateフロー

単純な多数決ではない。

```text
Round 1

Requirements
Mechanism
Assembly
Manufacturing
Verification

       ↓

各自の指摘を収集

       ↓

Round 2

Mechanism ← Manufacturingの反論
Assembly ← Mechanismの反論
Verification ← 全員の主張

       ↓

修正案

       ↓

再CAD生成

       ↓

再計測
```

となる。

## 意図

同じモデルに、

```text
自分の案をレビューして
```

と言うだけでは自己肯定しやすい。

役割とContextを分け、

**異なる失敗モードを探させる。**

ただし、

独立Contextだから独立した知能になるわけではない。

最新版でも実Cursorモデルによる5役実行は未検証であり、コード側の実行経路を代役プロセスで検証した段階である。

---

# 22. 実際の完全動作フロー

最終的に目指している1回の設計はこうなる。

```text
USER

「このマウスのサイドボタン、
もっと押しやすく。
外形はできるだけ変えないで。」

─────────────────────────────

STEP 1
Intent Compiler

Explicit:
押しやすくする

Preference:
外形変更最小

Unknown:
target force
travel
allowed internal volume

─────────────────────────────

STEP 2
Reference CAD Inspection

PCB.step
shell.step
switch.step

↓

実際のswitch位置
switch direction
available space
shell wall
PCB envelope

を測る

─────────────────────────────

STEP 3
Function Decomposition

F1 transmit finger force
F2 guide button
F3 actuate switch
F4 restore button
F5 limit overtravel
F6 connect to shell

─────────────────────────────

STEP 4
Req2CAD Search

各Functionについて、

semantic search

↓

実CAD候補

↓

materialize

↓

STEP / topology

─────────────────────────────

STEP 5
Structure Portfolio

例：

Actuation
A direct
B lever
C flexure

Guidance
A rails
B integral flexure
C pivot

Return
A switch spring
B flexure
C separate spring

─────────────────────────────

STEP 6
Concept Synthesis

Concept A
direct + rail + switch-return

Concept B
lever + pivot + switch-return

Concept C
flexure + integral guide + elastic return

─────────────────────────────

STEP 7
Engineering Evaluation

space
load path
part count
assembly
printability
reference suitability

─────────────────────────────

STEP 8
CAD Recipe

選択案をCAD操作へ落とす

─────────────────────────────

STEP 9
CAD Build

prototype STEP生成

─────────────────────────────

STEP 10
Deterministic Verification

clearance
interference
stroke
body validity
assembly

─────────────────────────────

STEP 11
5-role review

Requirement
Mechanism
Assembly
Manufacturing
Verification

─────────────────────────────

STEP 12
Cross Review

反論

─────────────────────────────

STEP 13
Repair

ただし

Requirement
Protected components
Verification targets

は固定

─────────────────────────────

STEP 14
Rebuild

─────────────────────────────

STEP 15
Reverify

─────────────────────────────

STEP 16
Human Handoff

STEP
STL
BOM
design rationale
references
verification report
unknowns

─────────────────────────────

HUMAN

確認
↓
必要ならproduction CADへ反映
```

---

# 23. なぜ「全部を1つのAgent」にしなかったのか

このシステムは意図的に、

```text
Super CAD AI
```

という一個の巨大プロンプトにはしていない。

理由は、

```text
自然言語理解
機構設計
過去構造検索
CAD操作
製造知識
検証
```

は性質が違うから。

特に、

**ReasoningとVerificationを同じ主体だけに任せない**

ことが重要。

```text
Reasoner
「これでOK」

Verifier
「0.2mm干渉しています」
```

なら、Verifierを優先する。

---

# 24. このツールの思想を一言で表すと

従来のAI CAD：

```text
Prompt
↓
LLM
↓
CAD
```

このツール：

```text
Prompt
↓
Intent
↓
Function
↓
Real-world structural knowledge
↓
Concept synthesis
↓
Engineering model
↓
CAD contract
↓
Deterministic geometry
↓
Measurement
↓
Critical review
↓
Revision
```

である。

つまり、

**Text-to-CADではなく**

**Intent-to-Engineering-to-CAD**

を目指している。

---

# 25. 各Projectの役割を一枚でまとめる

| Project | cadMCPで借りたもの | 配置される層 | 採用意図 |
|---|---|---|---|
| **agent-spec** | Intent Compiler、Source Trace、Unknown | Intent Layer | 人間の要求とAI推測を混同しない |
| **Req2CAD** | Function→実CAD検索 | Knowledge Layer | LLMの構造妄想を実例で補う |
| **DeepCAD** | CAD構築シーケンス | Reference Geometry | UIDから実CADへ戻る |
| **iDesignGPT** | Functional decomposition、Morphological Matrix | Concept Layer | 一案固定を避け、複数原理を組み合わせる |
| **Agentic Engineering Design** | Design-State Graph | Engineering State | Requirement→Mechanism→Verificationを追跡 |
| **Multi-Agent-CAD** | CADBrief / ArchitectPlan型の中間表現 | Planning Layer | Agent間を構造化データで接続 |
| **AI-CAD** | Planner、Interface、DFMA、Regression思想 | Engineering/Review | 部品・組立・製造をCAD前に検討 |
| **AgentCAD** | CAD正本、Executable Specs、Tool Registry | CAD Backend | CAD実行を設計Reasoningから分離 |
| **Cursor** | Host Agent、MCP、Subagents、Skills | UI / Orchestration | 人間との入口とAgent実行環境 |

---

# 26. 現在まだ完全に取り込んでいないもの

ここは重要。

### Req2CAD original Geometry Encoder

未完全移植。

現在は非学習特徴で代替。

### Req2CAD自動Structure Fusion

本家の全アルゴリズムをそのまま使ってはいない。

### iDesignGPT

FastGPTのシステム全体ではなく、

設計方法を利用。

### AI-CAD

フルOrchestratorを動かしているわけではない。

設計思想・Planner・検査方法を利用。

### AgentCAD

現時点では正本Backend候補／Adapter。

ユーザー環境の実AgentCADとの最終統合は未検証。

### Cursor native review team

定義・実行経路はある。

実Cursor GUI上で5サブエージェントが設計品質を改善したところまではまだ実証していない。

---

# 27. 今後の最重要ポイント

現在の構造で、もっとも強化効果が大きいのは引き続き、

```text
FUNCTION
↓
STRUCTURE KNOWLEDGE
↓
REAL CAD
```

である。

つまりReq2CAD。

今後は、

```text
Req2CAD function semantic search

+

Req2CAD learned geometry encoder

+

BRep topology search

+

Mouse-specific proven structure library

+

Successful/failed design history
```

を統合すると、

単なる一般CAD検索ではなく、

**「過去に実際に使えた構造を知っている機械設計AI」**

へ近づく。

最終形としては、

```text
General Engineering Knowledge
        +
Req2CAD
        +
Mouse-specific Knowledge
        +
User's previous successful designs
        +
CAD measurements
        +
Manufacturing feedback
```

をDesign Brainが利用し、

Cursorはその設計探索を制御する、という構造が理想である。