# Stella CAD System — cadMCP Design Studio

ユーザーの意図を汲んで、実例CADを見ながら機械部品を設計する作業リポです。

本体は **cadMCP Design Studio 0.3.3（正式版）** です。考えるのは Cursor / Codex のモデル、探す・測る・検査するのは共通の cadMCP です。2026-10-03から、形状生成に ClassCAD、Fusion 内の編集にコミュニティ Fusion MCP を追加しました。CadQuery は既存レシピと独立した幾何検査で使います。設定と実動作の検証範囲は [ClassCAD / Fusion 統合](docs/CLASSCAD_FUSION_INTEGRATION_JA.md) を参照してください。

## リリース状態

現在の正式版タグは `v0.3.3` です。これはMCPソフトウェアと運用基盤の正式リリースを意味します。CADレビューの受入、マウス機構、物理性能、強度、耐久性、競合比較まで完了したという意味ではありません。未検証事項は合格に変換せず、設計成果物・幾何検査・レビュー・物理試験を別々に扱います。

CodexのプロジェクトMCPとFactory OSの下位能力登録を含みます。CursorとCodexは同じMCP本体・検証ロジックを使いますが、Cursorのホスト設定は現在の安全境界により無効のままです。利用手順と限界は `docs/MCP_PREVIEW_JA.md`（旧ファイル名を互換維持）を参照してください。

Codexの導入状況と初回操作は `CODEX_GUIDE_JA.md`、受入状況と残作業は `IMPLEMENTATION_PLAN_JA.md` を参照してください。

旧エンジン（AgentCAD / AI-CAD / text-to-cad / ForgeCAD）は `LLM_cad_Projects/` に配置しています。AI-CAD は最新上流を確認し、不足ファイルと起動用リンクを復旧しました。新しい主経路への自動接続はしていません。

## いま使えること

- MCP サーバー名: `cadmcp-design-brain`
- Cursor設計 Skill: `.cursor/skills/cadmcp-cursor/SKILL.md`
- Codex設計 Skill: `.agents/skills/cadmcp-design-brain/SKILL.md`
- Cursorコマンド: `/cad-check` `/cad-design` `/cad-review`（Codexへ同名コマンドは移植していません）
- CAD カーネル: CadQuery 2.8.0（導入済み）
- 外部形状生成: ClassCAD MCP 0.2.0（WASM、プロジェクト設定済み）
- Fusion 操作: `stella-fusion-community`（許可文書名を限定した高水準ツール）
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
  integration/            ClassCAD / Fusion community の固定依存と接続検証
  cadmcp-all-in-one-2026-09-17/   設計図と 0.3.3 本体
  cadmcp-workspace/        実行時データ（未追跡）
  LLM_cad_Projects/        旧エンジン置き場（隔離）
```

詳細は `cadmcp-all-in-one-2026-09-17/START_HERE_JA.md`、`01_CURRENT/CURSOR_GUIDE_JA.md`、`CODEX_GUIDE_JA.md` です。

## FreeCAD正式統合

FreeCAD / ClassCAD / Fusion / CadQueryはユーザーが案件ごとに選びます。選択・起動・OP1-LHDの専用環境は [FreeCAD統合手順](docs/FREECAD_INTEGRATION_JA.md) を参照してください。

必要操作・観測済み工具能力・無料／所有済み買切り条件からCADを選ぶ `brain_cad_route` と案件限定の自動選択CLIを追加しました。明示選択を優先し、自動モードでは一つの生成経路をホストへ渡します。Build123dは既存cadgen CLI経路です。[能力別CAD選択](docs/CAD_BACKEND_ROUTING_JA.md) を参照してください。
