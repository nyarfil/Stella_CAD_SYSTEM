# Stella CAD — エージェント向け手順

## MCP暫定利用と本体開発の分離（ユーザーのMCP優先への変更）

このリポジトリの実装・診断・試験では、下記のCAD利用フローを開発手順として適用しない。
ユーザー指定により高度化をいったん区切り、CodexのcadMCPと製品Skillを暫定利用向けに有効化する。製品完成・物理性能認定ではない。
MCPのdoctor等を開発開始条件にしない。接続試験は明示した隔離workspaceへの一時起動のみ。
本体の通常開発では製品CADワークフローを実行しない。接続受入時の読取診断は許可。ユーザー設定・本番案件を保持する。
実例CADは設計参考であり、形状流用を強制しない。原理参考・適合・直接流用を区別する。
Sol/Terra/Lunaへの限定委任を使い、主担当が統合・最終監査する。
Factory OSが分類・予算・モデル・委譲を管理し、cadMCPは下位のCAD実行・証拠管理能力として使う。下記は実際のCAD設計用であり、本体開発の統括手順ではない。利用入口は docs/MCP_PREVIEW_JA.md。

このファイルは Cursor / Codex 共通の入口です。Cursor は `.cursor/skills/cadmcp-cursor/SKILL.md`、Codex は `.agents/skills/cadmcp-design-brain/SKILL.md` を参照します。

## これは何か

ユーザーの意図を汲み、機能から実例CADを探し、面を測り、型付きレシピで試作し、検査するシステムです。

- **Cursor / Codex のモデル**: 考える（要求整理、構造案、5役レビュー）
- **cadMCP (`cadmcp-design-brain`)**: 作業順・証拠・状態・検査を管理する
- **CadQuery**: 実形状を計算する

旧エンジンは `LLM_cad_Projects/` です。本家 n3r/AgentCAD の MCP 名は使いません。cadMCP が繋がっているときは、まず cadMCP の Skill と工具に従います。

## 最初に必ず呼ぶ

1. `brain_doctor`
2. `brain_fs_status`
3. `brain_studio_schema(name="FunctionBrief")`

MCP接続、CADカーネル、Req2CAD注釈件数、CAD対応数、意味検索索引を個別に報告する。全件データが未導入なら完了扱いせず、デモ4件や字句検索で黙って代替しない。

継続案件では `brain_projects` と `brain_studio_attempts` で保存状態を確認します。
`brain_get.summary.next_stage` は旧Brief/Concept/Plan経路の段階です。Studio試作履歴の有無を意味しません。
履歴の recorded_geometry_verdict は保存時の値で、採用前に `brain_studio_review_status` で証拠を再検証します。
Codexの設定は `.codex/config.toml`。新規セッションでこのプロジェクトを開いて利用します。
実行可能なサブエージェントがある場合、CADの5役レビューは別コンテキストで行い、親だけが結果を登録します。
同時実行上限に合わせて分割し、全員の初回レビュー完了後に相互反証します。

## 設計の順番

必要機能 → 実例CAD検索 → 実形状と面の確認 → 複数の構造案 → 構築レシピ → 実カーネル検査 → 要求・機構・組立・製造・検証のレビュー → 相互反証 → 固定条件での修正。

独立サブエージェントが使えない場合は明示する。同一Agentの順番レビューを5モデル実行と称しない。

## やってはいけないこと

- 測れる寸法を聞き直さず、測れない値を確定すること
- 中実の軸を穴のある案内として採用すること
- 保護部品（PCB・スイッチ・センサー・シェル外形）を勝手に動かすこと
- 検査を消す、閾値を下げる、部品を抜いて合格すること
- 未検証を合格と報告すること
- APIキーをコードやログに出すこと
- `LLM_cad_Projects/` の正本を無断で書き換えること
