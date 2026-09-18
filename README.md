# Stella CAD System

ユーザーの意図を汲んで、実例CADを見ながら機械部品を設計する作業リポです。

いまこの Cursor で使う本体は **cadMCP Design Studio 0.3.3** です。考えるのは Cursor のモデル、探す・測る・検査するのは cadMCP、形を計算するのは CadQuery です。

旧エンジン（AgentCAD / AI-CAD / text-to-cad / ForgeCAD）は `LLM_cad_Projects/` に隔離してあります。混ぜません。

## いま使えること

- MCP サーバー名: `cadmcp-design-brain`
- 設計 Skill: `.cursor/skills/cadmcp-cursor/SKILL.md`
- コマンド: `/cad-check` `/cad-design` `/cad-review`
- CAD カーネル: CadQuery 2.8.0（導入済み）
- データ置き場: `cadmcp-workspace/`（Git に入れない）

Req2CAD 全件データと Qwen 埋め込みはまだ入れていません。件数 0 / `semantic_ready: false` は未導入であり、デモ4件で代用してはいけません。

## エージェントが最初にやること

1. `.cursor/skills/cadmcp-cursor/SKILL.md` を読む
2. `brain_doctor`、`brain_fs_status`、`brain_studio_schema(name="FunctionBrief")` を実際に呼ぶ
3. MCP接続・CADカーネル・Req2CAD件数・意味索引を別々に報告する
4. 未導入を完了扱いしない

設計の順番は、必要機能 → 実例CAD検索 → 実形状と面の確認 → 複数案 → 型付きレシピ → 実カーネル検査 → 5役レビュー → 固定条件での修正です。

CAD正本、シェル、基板、認証情報は無断で変えない。プリンタ送信もしない。

## フォルダ

```
Stella_CAD_SYSTEM/
  .cursor/                 この Cursor 用 MCP / Skill / 5役
  cadmcp-all-in-one-2026-09-17/   設計図と 0.3.3 本体
  cadmcp-workspace/        実行時データ（未追跡）
  LLM_cad_Projects/        旧エンジン置き場（隔離）
```

詳細は `cadmcp-all-in-one-2026-09-17/START_HERE_JA.md` と `01_CURRENT/CURSOR_GUIDE_JA.md` です。
