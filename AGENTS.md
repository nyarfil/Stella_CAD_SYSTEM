# Stella CAD — エージェント向け手順

このファイルは Cursor（Grok）と Codex（Astra / Sol）が最初に読む正本です。同じ内容の短い入口が `.cursor/skills/stella-cad/SKILL.md` にあります。

Anthropic キーは不要です。内蔵チャットは使いません。**あなたが Claude Code の代わりに、同じ MCP 工具を呼びます。**

## これは何か

Stella の目的は、ユーザーの意図を汲んで自動で 3D モデリングすることです。AgentCAD の Windows 対応は下ごしらえです。

いまはこのリポにエンジンを並べます。

- **AgentCAD**（`agentcad-for-windows/`）: 部品は build123d、判定はカーネル。本家が Claude Code に出していたのと **同じ 109 個の工具** を MCP 名 **`Stella_Agentcad`** で出します。
- **AI-CAD**（`ai-cad-labs/`）: CadQuery、多視点レンダ、DFM/DFA。サーバは無く、`uv --directory ai-cad-labs run python -m tools.<name>`。venv は 3.13 で、AgentCAD の 3.12 と混ぜません。セットアップは `scripts/stella/setup-aicad.ps1`。入口 Skill は `.cursor/skills/stella-aicad/SKILL.md`。本家の `ai-cad-labs/AGENTS.md` を読んでから工具を呼びます。
- **text-to-cad**（`text-to-cad/`）: cadgen（build123d）。自然言語・図面・画像からモデルし、STEP を検査する。サーバ無し。セットアップは `scripts/stella/setup-text-to-cad.ps1`。入口は `.cursor/skills/stella-text-to-cad/SKILL.md`。cookbook は `text-to-cad/skills/`（`.cursor/skills` にコピーしない）。venv は 3.13 で、他と混ぜません。
- **ForgeCAD**（`forgecad/`）: `.forge.js` と npm の `forgecad@0.13.0`。サーバ無し。セットアップは `scripts/stella/setup-forgecad.ps1`。入口は `.cursor/skills/stella-forgecad/SKILL.md`。グローバル PATH の `forgecad` は使わない。独自ライセンスなので、商用やエージェント埋め込みは本家の条件を確認する。

- Cursor: このリポの `.cursor/mcp.json`、およびマウス（`V:\mouse`）の `.cursor/mcp.json`。サーバ名は **`Stella_Agentcad`**
- Codex: このリポとマウスの `.codex/config.toml` の `mcp_servers.Stella_Agentcad`

本家 n3r/AgentCAD の MCP（`agentcad` / `n3r-agentcad`）は登録しないでください。マウスの OpenSCAD MCP は残します。

Cursor 3.20 はプロジェクト MCP を Customize に出さず、`disconnected` のまま落とすことがあります。そのときは共有 `mcp.json` に **`Stella_Agentcad` だけ** 足してよい（本家の名前では足さない）。OpenSCAD 作業中は Customize で Stella をオフにしてよい。

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

`/api/health` が数秒で落ちても、待ち受けプロセスのコマンドラインにこのリポと `agentcad serve` があれば Stella です。未知プロセスではありません。カーネルが重い処理中なので、第二サーバは立てません。`.stella/server.pid` は venv ランチャではなく、ポートを聞いている PID です。MCP の表示名 `Stella_Agentcad` は判定に使いません。

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

- 本家 n3r/AgentCAD を MCP 名 `agentcad` / `n3r-agentcad` で出す
- 共有 `mcp.json` に本家の名前で 109 工具を出す（見える必要があるときだけ `Stella_Agentcad`）
- マウスの `.cursor/mcp.json` から OpenSCAD を消す、または本家名で AgentCAD を足す
- 隔離を黙ってオフにする
- 知らないプロセスを `stop` で殺す
- API キーやトークンをコード・ログ・コミットに出す
- AgentCAD の 3.12 venv と AI-CAD / text-to-cad の 3.13 venv を混ぜる
- AI-CAD の正本として `V:\mouse\vendor\ai-cad` を使う
- text-to-cad の正本として `V:\mouse\.venv-text-to-cad` を使う
- ForgeCAD の正本としてグローバル PATH の `forgecad` を使う
