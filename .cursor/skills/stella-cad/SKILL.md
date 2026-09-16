---
name: stella-cad
description: Drive Stella CAD (AgentCAD on Windows) from Cursor or Codex. Use when creating or editing 3D parts, rebuilding, exporting STEP, loading CAD skills, or talking to the AgentCAD kernel. Prefer the AgentCAD MCP tools (same 109 tools Claude Code used).
---

# Stella CAD

この Skill はルートの `AGENTS.md` と同じ手順です。Anthropic キーは不要。内蔵チャットは使わない。**あなたが Claude Code の代わりに MCP 工具を呼ぶ。**

## 入口

Cursor は `.cursor/mcp.json`、Codex は `.codex/config.toml` でサーバ名 `agentcad` を出す。共有 `mcp.json` には足さない。

MCP が繋がっているときは工具を直接呼ぶ。まだ無いときだけ橋:

```powershell
uv run python -m stella_cad.bridge health
uv run python -m stella_cad.bridge serve
uv run python -m stella_cad.bridge list
uv run python -m stella_cad.bridge call <name> --args '{...}'
```

止める（`.stella/server.pid` に書いたプロセスだけ）:

```powershell
uv run python -m stella_cad.bridge stop
```

隔離（AppContainer）は既定オン。オフにするのはユーザーが明示したときだけ（`--no-sandbox`）。

既定ポートは 8630。そこが別の AgentCAD（隔離オフ）なら 8640。

## 工具（Claude Code と同じ）

1. 最初の部品の前に `part_template`
2. 作業に合う技能は `load_skill`（本体の Skill を `.cursor/skills` にコピーしない）
3. `create_project` → `create_part` / `update_part_script` → 失敗 JSON を読んで直す → `export_part` `format: "step"`

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
