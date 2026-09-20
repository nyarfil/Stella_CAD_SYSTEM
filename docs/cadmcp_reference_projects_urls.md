# cadMCP 参照プロジェクト・URL一覧

更新日: 2026-09-17

この文書は、cadMCP Design Studio の設計・実装で参照した主要プロジェクトと、「どの部分を参考にしたか」をまとめたものです。

特に **Req2CAD** は、以下の4つが別の場所にあるため注意してください。

1. 論文
2. 実装コード
3. Function–Structure用の機能注釈データ
4. UIDで対応する元CADデータ

---

# 1. Req2CAD

## 1.1 GitHub実装本体

**Repository**  
https://github.com/hankaiuu/Req2CAD

README:  
https://github.com/hankaiuu/Req2CAD/blob/main/README.md

主な構成:

```text
Req2CAD/
├─ Python_backend/
│  ├─ func2cad.py
│  ├─ func2cad_api.py
│  ├─ cad2topo_2d.py
│  ├─ get_geom_embed.py
│  ├─ get_geom_embed_api.py
│  ├─ sketch_comb.py
│  ├─ sketch_comb_api.py
│  └─ structure_assembly_api.py
├─ components/
│  ├─ functional-reasoning/
│  ├─ structure-generation/
│  └─ structure-assembly/
└─ app/
```

README上では、主要部分が以下に分かれています。

- Functional Structure Reasoning
- Structure Generation and Reasoning
- Structure Assembly

---

## 1.2 Function → CAD検索

最重要ファイル:  
https://github.com/hankaiuu/Req2CAD/blob/main/Python_backend/func2cad.py

主な処理:

```text
Function
  ↓
Qwen embedding
  ↓
関連 function keyword
  ↓
function → CAD ID
  ↓
候補CAD一覧
```

主な関数:

```python
query_related_func(...)
cad4single_func(...)
cad4multifunc(...)
```

複数機能の場合は、複数の要求Functionに対応できるCAD候補を集約します。

---

## 1.3 Function–Structure Knowledge Base用データ

**Hugging Face Dataset**  
https://huggingface.co/datasets/QianzhiJing/Req2CAD

ここに、CAD UIDと機能注釈の対応データがあります。

概念的には:

```text
CAD UID
├─ function_description
└─ function_keywords
```

このUIDを使って、DeepCAD側の元CADへ辿ります。

---

## 1.4 Req2CAD論文

DOI:  
https://doi.org/10.1145/3772318.3791949

論文で扱われる流れ:

```text
Requirement
↓
Function decomposition
↓
Function retrieval
↓
CAD component retrieval
↓
Geometry / topology analysis
↓
Structure generation
```

---

## 1.5 CAD Topology抽出

ファイル:  
https://github.com/hankaiuu/Req2CAD/blob/main/Python_backend/cad2topo_2d.py

STEPから主に以下を抽出します。

```text
Face
Edge
Surface Type
Curvature
Adjacency
```

さらに、グラフ比較用として以下を使用します。

```text
Weisfeiler-Lehman
Vertex Histogram
```

---

## 1.6 Geometry Embedding

ファイル:  
https://github.com/hankaiuu/Req2CAD/blob/main/Python_backend/get_geom_embed.py

Point Cloudから学習済みモデルを使って形状Embeddingを生成します。

中心処理:

```python
model.get_shape_embed(...)
```

Req2CADは最終的に、

```text
Function similarity
+
Geometry similarity
+
Topology similarity
```

を組み合わせる方向のシステムです。

---

## 1.7 Structure / Sketch Combination

実装:  
https://github.com/hankaiuu/Req2CAD/blob/main/Python_backend/sketch_comb.py

API版:  
https://github.com/hankaiuu/Req2CAD/blob/main/Python_backend/sketch_comb_api.py

---

## 1.8 Structure Assembly

実装:  
https://github.com/hankaiuu/Req2CAD/blob/main/Python_backend/structure_assembly_api.py

主な処理:

```text
STEP loading
Shape properties
Transform
Boolean fusion
Distance
Assembly
```

---

# 2. DeepCAD

## Repository

https://github.com/rundiwu/DeepCAD

README:  
https://github.com/rundiwu/DeepCAD/blob/master/README.md

Req2CADのUIDに対応する元CADを取得するために重要です。

公開データには主に:

```text
cad_json
cad_vec
```

があります。

`cad_json`には、Onshape由来のCAD構築シーケンスが保存されています。

---

## 2.1 DeepCAD元データ

公式README記載のデータ:  
https://www.cs.columbia.edu/cg/deepcad/data.tar

概念的な対応:

```text
Req2CAD
  function_keywords
        ↓
     CAD UID
        ↓
DeepCAD
  data/cad_json/
    0032/
      00329619.json
```

---

## 2.2 実際に確認した公開CAD例

### UID: 0032/00329619
https://github.com/arnavagarwal05/3d_modelling/blob/432d03406b89a924b755c1826f2eb78da650e440/data/cad_json/0032/00329619.json

### UID: 0032/00325917
https://github.com/arnavagarwal05/3d_modelling/blob/432d03406b89a924b755c1826f2eb78da650e440/data/cad_json/0032/00325917.json

### UID: 0032/00323296
https://github.com/arnavagarwal05/3d_modelling/blob/432d03406b89a924b755c1826f2eb78da650e440/data/cad_json/0032/00323296.json

### UID: 0032/00321991
https://github.com/arnavagarwal05/3d_modelling/blob/432d03406b89a924b755c1826f2eb78da650e440/data/cad_json/0032/00321991.json

---

# 3. Qwen3 Embedding

**Qwen3-Embedding-4B**  
https://huggingface.co/Qwen/Qwen3-Embedding-4B

用途:

```text
"support rotating shaft"
↓
embedding
↓
Req2CAD function keywordとのcosine similarity
↓
対応CAD UID検索
```

---

# 4. iDesignGPT

Repository:  
https://github.com/Songkai-Liu-SJTU/iDesignGPT

## Functional Structure Decomposition
https://github.com/Songkai-Liu-SJTU/iDesignGPT/tree/main/code/agent/Functional%20Structure%20Decomposition

## Morphological Analysis
https://github.com/Songkai-Liu-SJTU/iDesignGPT/tree/main/code/agent/Morphological%20analysis

## Morphological Matrix Prompt
https://github.com/Songkai-Liu-SJTU/iDesignGPT/blob/main/code/agent/Morphological%20analysis/Morphological%20Matrix.md

cadMCP内での役割:

```text
Req2CAD
= 実例構造を供給

iDesignGPT
= それらを発散・組み合わせる方法
```

---

# 5. Agentic Engineering Design

Repository:  
https://github.com/SoheylM/agentic-eng-design

重要ファイル:  
https://github.com/SoheylM/agentic-eng-design/blob/main/data_models.py

参考にした考え方:

```text
Design-State Graph
DesignNode
Embodiment
PhysicsModel
linked_reqs
verification_plan
```

---

# 6. Multi-Agent-CAD

Repository:  
https://github.com/Pan-Chera/Multi-Agent-CAD

Workflow:  
https://github.com/Pan-Chera/Multi-Agent-CAD/blob/main/multi_agent_cad/WORKFLOW.md

Schemas:  
https://github.com/Pan-Chera/Multi-Agent-CAD/blob/main/multi_agent_cad/schemas.py

参考にした主要思想:

```text
User Request
↓
CADBrief
↓
ArchitectPlan
↓
CAD Code
↓
QA
```

---

# 7. agent-spec

Repository:  
https://github.com/ZhangHanDong/agent-spec

Intent Compiler Skill:  
https://github.com/ZhangHanDong/agent-spec/blob/main/skills/agent-spec-intent-compiler/SKILL.md

参考にした部分:

```text
source excerpt
requirement
inference
unknown
open question
human confirmation
```

目的:  
**AIの推測を確定仕様として扱わないこと。**

---

# 8. AI-CAD Labs

Repository:  
https://github.com/ai-cad-labs/ai-cad

Agents:  
https://github.com/ai-cad-labs/ai-cad/tree/main/.shared/agents

Planner:  
https://github.com/ai-cad-labs/ai-cad/blob/main/.shared/agents/planner/instructions.md

主に参考にしたもの:

```text
Part decomposition
Interfaces
Assembly order
Make / Buy
Manufacturing constraints
DFMA
Repair
Regression Gate
```

---

# 9. AgentCAD

Repository:  
https://github.com/n3r/AgentCAD

Executable Specs:  
https://github.com/n3r/AgentCAD/blob/main/agentcad/toolkit/specs.py

Agent API:  
https://github.com/n3r/AgentCAD/blob/main/docs/agent-api.md

代表的な検査:

```python
check_valid()
check_mass()
check_volume()
check_bbox()
check_wall()
check_fem_static()
```

---

# 10. CADDesigner

Repository:  
https://github.com/562590763/CADDesigner-Code

主に参考にした考え方:

```text
Vague Requirement
↓
Requirement Expansion
↓
Explicit Operation Intent
↓
CAD
```

---

# 11. 今回の主要参照先まとめ

| Project | 主用途 | URL |
|---|---|---|
| Req2CAD | Function → Structure → CAD | https://github.com/hankaiuu/Req2CAD |
| Req2CAD Dataset | 機能注釈とCAD UID | https://huggingface.co/datasets/QianzhiJing/Req2CAD |
| Req2CAD Paper | アルゴリズム・全体設計 | https://doi.org/10.1145/3772318.3791949 |
| DeepCAD | 元CAD構築データ | https://github.com/rundiwu/DeepCAD |
| Qwen3-Embedding-4B | Function semantic search | https://huggingface.co/Qwen/Qwen3-Embedding-4B |
| iDesignGPT | 機能分解・Morphological Matrix | https://github.com/Songkai-Liu-SJTU/iDesignGPT |
| Agentic Engineering Design | Design-State Graph | https://github.com/SoheylM/agentic-eng-design |
| Multi-Agent-CAD | 型付きAgent間IR | https://github.com/Pan-Chera/Multi-Agent-CAD |
| agent-spec | Intent Compiler | https://github.com/ZhangHanDong/agent-spec |
| AI-CAD | Planner / DFMA / Repair | https://github.com/ai-cad-labs/ai-cad |
| AgentCAD | CAD Backend / Executable Specs | https://github.com/n3r/AgentCAD |
| CADDesigner | Requirement → CAD Intent | https://github.com/562590763/CADDesigner-Code |

---

# 12. Req2CADだけ追う場合の読む順番

1. 実装全体  
   https://github.com/hankaiuu/Req2CAD

2. Function → CAD  
   https://github.com/hankaiuu/Req2CAD/blob/main/Python_backend/func2cad.py

3. Function–Structureデータ  
   https://huggingface.co/datasets/QianzhiJing/Req2CAD

4. CAD Topology  
   https://github.com/hankaiuu/Req2CAD/blob/main/Python_backend/cad2topo_2d.py

5. Geometry Embedding  
   https://github.com/hankaiuu/Req2CAD/blob/main/Python_backend/get_geom_embed.py

6. Structure Combination  
   https://github.com/hankaiuu/Req2CAD/blob/main/Python_backend/sketch_comb.py

7. Structure Assembly  
   https://github.com/hankaiuu/Req2CAD/blob/main/Python_backend/structure_assembly_api.py

8. 元CAD  
   https://github.com/rundiwu/DeepCAD

---

# 13. Req2CADの位置関係

```text
Req2CAD Paper
https://doi.org/10.1145/3772318.3791949

        │
        ├─────────────────────────────┐
        │                             │
        ▼                             ▼

Req2CAD Code                    Req2CAD Dataset
GitHub                          Hugging Face
hankaiuu/Req2CAD                QianzhiJing/Req2CAD

        │                             │
        └──────────────┬──────────────┘
                       │
                    CAD UID
                       │
                       ▼

                   DeepCAD
             rundiwu/DeepCAD

                       │
                       ▼

              Original CAD JSON
              Sketch / Extrude
              Boolean / BRep

                       │
                       ▼

             Geometry / Topology
```
