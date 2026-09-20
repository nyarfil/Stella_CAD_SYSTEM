# Stella CAD System — cadMCP Design Studio

ユーザーの意図を汲んで、実例CADを見ながら機械部品を設計する作業リポです。

本体は **cadMCP Design Studio 0.3.3（正式版）** です。考えるのは Cursor / Codex のモデル、探す・測る・検査するのは共通の cadMCP、形を計算するのは CadQuery です。

## リリース状態

現在の正式版タグは `v0.3.3` です。これはMCPソフトウェアと運用基盤の正式リリースを意味します。CADレビューの受入、マウス機構、物理性能、強度、耐久性、競合比較まで完了したという意味ではありません。未検証事項は合格に変換せず、設計成果物・幾何検査・レビュー・物理試験を別々に扱います。

CodexのプロジェクトMCPとFactory OSの下位能力登録を含みます。CursorとCodexは同じMCP本体・検証ロジックを使いますが、Cursorのホスト設定は現在の安全境界により無効のままです。利用手順と限界は `docs/MCP_PREVIEW_JA.md`（旧ファイル名を互換維持）を参照してください。

Codexの導入状況と初回操作は `CODEX_GUIDE_JA.md`、受入状況と残作業は `IMPLEMENTATION_PLAN_JA.md` を参照してください。

旧エンジン（AgentCAD / AI-CAD / text-to-cad / ForgeCAD）は `LLM_cad_Projects/` に隔離してあります。混ぜません。

## いま使えること

- MCP サーバー名: `cadmcp-design-brain`
- Cursor設計 Skill: `.cursor/skills/cadmcp-cursor/SKILL.md`
- Codex設計 Skill: `.agents/skills/cadmcp-design-brain/SKILL.md`
- Cursorコマンド: `/cad-check` `/cad-design` `/cad-review`（Codexへ同名コマンドは移植していません）
- CAD カーネル: CadQuery 2.8.0（導入済み）
- データ置き場: `cadmcp-workspace/`（Git に入れない）

2026-09-19のこのPCでの診断ではReq2CAD 175,978件、CAD対応175,978件、Qwen意味索引は `semantic_ready: true` でした。これは配置確認であり検索品質の合格判定ではありません。他環境では必ず再診断し、デモ4件を全件データの代わりに扱わないでください。

## エージェントが最初にやること

1. 使用ホストに対応する上記Skillを読む
2. `brain_doctor`、`brain_fs_status`、`brain_studio_schema(name="FunctionBrief")` を実際に呼ぶ
3. MCP接続・CADカーネル・Req2CAD件数・意味索引を別々に報告する
4. 未導入を完了扱いしない

設計の順番は、必要機能 → 実例CAD検索 → 実形状と面の確認 → 複数案 → 型付きレシピ → 実カーネル検査 → 5役レビュー → 固定条件での修正です。

CAD正本、シェル、基板、認証情報は無断で変えない。プリンタ送信もしない。

## フォルダ

```
Stella_CAD_SYSTEM/
  .cursor/                 この Cursor 用 MCP / Skill / 5役
  .codex/                  プロジェクト限定Codex MCP設定
  .agents/skills/          Codex用設計Skill
  cadmcp-all-in-one-2026-09-17/   設計図と 0.3.3 本体
  cadmcp-workspace/        実行時データ（未追跡）
  LLM_cad_Projects/        旧エンジン置き場（隔離）
```

詳細は `cadmcp-all-in-one-2026-09-17/START_HERE_JA.md`、`01_CURRENT/CURSOR_GUIDE_JA.md`、`CODEX_GUIDE_JA.md` です。
