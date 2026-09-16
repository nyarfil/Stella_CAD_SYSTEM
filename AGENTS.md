# Stella CAD — エージェント向け手順

このファイルは Cursor（Grok）と Codex（Astra / Sol）が最初に読む正本です。同じ内容の短い入口が `.cursor/skills/stella-cad/SKILL.md` にあります。

Anthropic キーは不要です。内蔵チャットは使いません。**あなたが Claude Code の代わりに、同じ MCP 工具を呼びます。**

## これは何か

Stella は AgentCAD を Windows で動かす層です。部品は build123d の Python スクリプト、判定はカーネルです。

本家が Claude Code に出していたのと **同じ 109 個の工具** を、このリポの MCP で Cursor と Codex に出します。

- Cursor: `.cursor/mcp.json` のサーバ名 `agentcad`
- Codex: `.codex/config.toml` の `mcp_servers.agentcad`（このリポを trusted にすること）

ユーザー全体の共有 `mcp.json` には登録しないでください（マウス側の設定を壊します）。

## 起動（人に頼まない）

MCP を初めて繋ぐと、隔離オンのサーバがまだ無ければ自分で起きます。すでに `kernel: ready` ならそれを使います。

手で確認するとき:

```powershell
uv run python -m stella_cad.bridge health
```

`kernel` が `ready` でなければ:

```powershell
uv run python -m stella_cad.bridge serve
```

止めるとき（自分が起動した PID だけ）:

```powershell
uv run python -m stella_cad.bridge stop
```

隔離（AppContainer）は既定オンです。オフにするのはユーザーが明示したときだけです。

既定ポートは 8630 です。そこが別の AgentCAD（隔離オフ）なら 8640 を使います。MCP も同じ判定をします。

## 工具の呼び方（Claude Code と同じ）

MCP の `agentcad` が繋がっているときは、**工具を直接呼ぶ**のが正です。`create_project`、`create_part`、`update_part_script`、`export_part`、`render_view`、`list_skills`、`load_skill` など、本家の名前のままです。

最初の部品を書く前に:

1. `part_template` — 部品の契約と、読める技能の一覧
2. 作業に合う技能があれば `load_skill`（例: `holes`、`enclosures`、`sheet-metal`）
3. それからスクリプトを書く

16 個の CAD Skill を `.cursor/skills` にコピーしないでください。本家と同じく、必要なときだけ `load_skill` します。

MCP がまだ無いとき（接続待ち・失敗）だけ、橋に落ちます:

1. `uv run python -m stella_cad.bridge list`
2. `uv run python -m stella_cad.bridge call <name> --args '{...}'`

よく使う流れ:

1. `create_project`（名前は `[a-z][a-z0-9_]{0,39}`。既存なら `open_project`）
2. `create_part` で部品を作り、以降の変更は `update_part_script`
3. 再ビルドが成功するまで、失敗 JSON を読んで直す（`ok: true` または error 無し）
4. `export_part` に `format: "step"`

文章から部品を作るのも **あなたが** `PARAMS` と `build(p)` を書くことです。ブラウザの Agent パネルや `generate_*` は Anthropic キー前提なので使いません。

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

- `PARAMS` は型付きの辞書。`default` は必須。
- `build(p)` は `Part` / `Solid` / `Compound`（または `BuildPart`）を返す。
- 単位は mm、角度は度。
- 失敗は print ではなく例外。トレースバックに行番号が付きます。
- 推測でブール演算を増やさない。カーネルが返した失敗 JSON を読んで直す。

詳細は `agentcad-for-windows/docs/part-authoring.md`。

## 失敗の読み方

MCP も橋も、AgentCAD の JSON を加工しません。典型:

```json
{
 "error": {
 "type": "script_error",
 "message": "...",
 "details": {
 "traceback": "...",
 "line": 12,
 "hint": "..."
 }
 }
}
```

`type` と `line` と `hint` を先に読む。形が分からないまま切り貼りしない。

## やってはいけないこと

- 109 工具を Cursor の **共有** `mcp.json` に登録する（このリポの `.cursor/mcp.json` は正）
- マウス（ZA13）のリポや共有 MCP を書き換える
- 隔離を黙ってオフにする
- 知らないプロセスを `stop` で殺す
- API キーやトークンをコード・ログ・コミットに出す
