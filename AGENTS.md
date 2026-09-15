# Stella CAD — エージェント向け手順

このファイルは Cursor（Grok）と Codex（Astra / Sol）が最初に読む正本です。同じ内容の短い入口が `.cursor/skills/stella-cad/SKILL.md` にあります。

Anthropic キーは不要です。内蔵チャットは使いません。あなた（エージェント）が工具を呼びます。

## これは何か

Stella は AgentCAD を Windows で動かす層です。部品は build123d の Python スクリプト、判定はカーネル、入口は HTTP（`127.0.0.1:8630`）です。109 個の工具を IDE の MCP に全部出さないでください。橋の 5 コマンドだけ使います。

## 起動（人に頼まない）

作業リポの根（このファイルがある場所）で:

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

## 工具の呼び方

1. 名前を知る: `uv run python -m stella_cad.bridge list`
2. 必要な名前だけ呼ぶ: `uv run python -m stella_cad.bridge call <name> --args '{...}'`
3. 技能（書き方のコツ）は `list_skills` / `load_skill`。16 個の Skill を `.cursor/skills` にコピーしない。

`list` は名前と短い説明だけ返します。引数の形が要るときはその工具を呼ぶ直前に `list` の該当行を見るか、`load_skill` を使います。

よく使う流れ:

1. `create_project`（または既存を `open_project`）
2. `update_part` で `PARAMS` + `build(p)` のスクリプトを書く
3. 再ビルドが `ok: true` になるまで直す
4. `export_part` で STEP を出す

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

橋は AgentCAD の JSON を加工しません。典型:

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

- 109 工具を Cursor の共有 `mcp.json` に登録する
- マウス（ZA13）のリポや共有 MCP を書き換える
- 隔離を黙ってオフにする
- 知らないプロセスを `stop` で殺す
- API キーやトークンをコード・ログ・コミットに出す
