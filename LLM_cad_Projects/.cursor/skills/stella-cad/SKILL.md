---
name: stella-cad
description: Drive Stella CAD (AgentCAD on Windows) from Cursor or Codex. Use when creating or editing 3D parts, rebuilding, exporting STEP, loading CAD skills, or talking to the AgentCAD kernel. Call stella_guide first, then only stella_run on the tools it returns.
---

# Stella CAD

この Skill はルートの `AGENTS.md` と同じ手順です。Anthropic キーは不要。内蔵チャットは使わない。**あなたが Claude Code の代わりに MCP 工具を呼ぶ。**

## 入口

Cursor / Codex のサーバ名は **`Stella_Agentcad`**。本家の `agentcad` / `n3r-agentcad` は使わない。このリポ、マウス（`V:\mouse`）、必要なら共有 `~\.cursor\mcp.json` のいずれも同じ名前だけ。

MCP が繋がっているときは案内役から。まだ無いときだけ橋:

```powershell
uv run python -m stella_cad.bridge health
uv run python -m stella_cad.bridge serve
uv run python -m stella_cad.bridge list
uv run python -m stella_cad.bridge call <name> --args '{...}'
```

止める（Stella の待ち受け PID だけ）:

```powershell
uv run python -m stella_cad.bridge stop
```

ヘルスがタイムアウトしても、コマンドラインがこのリポの `agentcad serve` なら busy な Stella です。第二サーバは立てない。MCP 名は関係ない。

隔離（AppContainer）は既定オン。オフにするのはユーザーが明示したときだけ（`--no-sandbox`）。

既定ポートは 8630。そこが別の AgentCAD（隔離オフ）なら 8640。

## 工具（Cursor / Codex）

MCP に出ているのは **`stella_guide` と `stella_run` だけ**です。109 個は毎回読みません。

1. やりたいことを `stella_guide` に渡す（日本語でよい）
2. 返ってきた `tools` だけを `stella_run` で呼ぶ
3. 部品を書くときは、案内どおり `part_template` → `create_part` / `update_part_script` → 失敗 JSON を直す → `export_part` `format: "step"`
4. 技能は `load_skill`（本体の Skill を `.cursor/skills` にコピーしない）

全部の工具を一覧したいときだけ環境変数 `STELLA_MCP_SURFACE=all`。

文章から部品を作るのは、あなたが `PARAMS` + `build(p)` を書くこと。`generate_*` は使わない。

## 部品の契約

```python
from build123d import *

PARAMS = {
    "size": {"type": "number", "default": 10.0, "min": 1.0, "max": 100.0, "unit": "mm",
             "description": "Cube edge"},
}

def build(p):
    return Box(p.size, p.size, p.size)
```

単位は mm、角度は度。推測でブール演算を増やさない。詳細は `agentcad-for-windows/docs/part-authoring.md`。

## 失敗 JSON

MCP も橋も加工しない。`error.type` / `details.line` / `details.hint` / `details.traceback` を読んで直す。
