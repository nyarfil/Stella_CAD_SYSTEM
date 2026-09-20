# Codexで使う — 2026-09-20

## 現在の状態

更新: ユーザーが高度化を一旦中断しMCP利用を優先したため、CodexのプロジェクトMCPと製品Skillを有効化。現アプリから4診断の実呼出し成功、隔離stdio50工具。Factory OSの個人能力カタログへ登録。最新手順は `docs/MCP_PREVIEW_JA.md`。以下の無効化説明は以前の開発期間の記録です。Cursorは無効のまま、グローバル・信頼設定は変更していません。

このリポジトリにCodex用MCP設定と設計Skillはありますが、ユーザー指示により開発中は両方無効です。CursorのcadMCP設定もバックアップへ退避し、自動適用ルールを無効化しています。完成前に通常接続を戻さないでください。
MCPは別製品へ分岐させず、両ホストが同じ本体・同じworkspaceを利用します。
本体は `cadmcp-all-in-one-2026-09-17/01_CURRENT`、実データは `cadmcp-workspace` です。

## 過去の接続確認（現在の有効状態ではありません）

2026-09-19にCodexアプリの現セッションから `brain_doctor`、`brain_fs_status`、
`brain_projects`、`brain_studio_schema(name="FunctionBrief")` を実MCPツールとして呼び出しました。
設定ファイルやPython直呼出しだけではなく、アプリ接続を確認済みです。

Codexは信頼済みプロジェクトでのみプロジェクト設定を読み込みます。
公式仕様: https://developers.openai.com/codex/mcp
Skill配置: https://developers.openai.com/codex/skills

別PCや設定変更後は、プロジェクトルートを開き、表示された信頼確認をユーザーが判断したうえで、上記4ツールを再確認します。こちらから信頼設定は変更しません。
ただし開発中はこの通常接続手順を行わず、明示的な別workspaceの試験だけを行います。既存セッションの工具一覧に残っても利用しません。

## 2つの利用経路

| 経路 | 利点 | コスト・制限 |
|---|---|---|
| CodexアプリからMCPを利用 | 会話中に意図・未知事項を確認して設計を進められる。通常はこちら | プロジェクトの信頼とセッションでのMCP読込が必要 |
| 明示的なCodex CLI Provider | 別コンテキストの構造化出力、回数・時間上限、呼出し記録を残せる | CLI認証と利用枠が必要。モデル実行は追加の時間・使用量を消費する |

CLI ProviderはMCPツールの背後で無断にモデルを呼びません。CLI検証スクリプトも `--execute-model` が必要です。
一時ディレクトリへ必要な証拠だけを複製し、JSON/Markdown/textは入力本文へ埋め込み、画像はnative image入力で渡します。元案件のMCPやAGENTS設定の再帰読込を避け、ephemeral・read-onlyを要求し、証拠の変更を検出すると結果を拒否します。
これはOS隔離の独立した侵入試験に合格したという意味ではありません。

## 運用上の注意

- `brain_projects` は保存案件を、`brain_studio_attempts` は登録された試作・レビュー対象を列挙します。
- Legacyの `next_stage=intent` を「CAD生成履歴なし」と解釈しないでください。
- 一覧の過去の幾何判定は現在の証拠を再検証していません。現在revisionに対し `brain_studio_review_status` を呼びます。
- 両ホストで同じ案件を同時に編集しないでください。revision競合時は再読込します。
- CAD生成・幾何合格・レビュー合格・物理試験合格は別の状態です。
- 5役レビューは実際の個別実行が必要です。役名5個を付けただけで独立レビュー済みにしません。
- 元CAD、保護形状、ユーザーの未保存Fusion文書、プリンタには自動反映しません。

## 再診断・再設置（開発者/AI向け）

PowerShellの作業場所を `E:\aiwork\Stella_CAD_SYSTEM\cadmcp-all-in-one-2026-09-17\01_CURRENT` にして実行します。
ユーザーがコードを貼り付けたりファイルを上書きしたりする必要はありません。

```powershell
.\.venv\Scripts\python.exe scripts/check_cursor_connection.py --project E:\aiwork\Stella_CAD_SYSTEM --host codex --isolated-test-workspace E:\aiwork\Stella_CAD_SYSTEM\cadmcp-all-in-one-2026-09-17\01_CURRENT\verification\mcp-isolated-20260920
.\.venv\Scripts\python.exe -m cadmcp_brain.studio --workspace E:\aiwork\Stella_CAD_SYSTEM\cadmcp-workspace provider-check --provider codex
.\.venv\Scripts\python.exe scripts/setup_codex.py --project E:\aiwork\Stella_CAD_SYSTEM --workspace E:\aiwork\Stella_CAD_SYSTEM\cadmcp-workspace --dry-run
```

setupは既存仮想環境を利用し、ユーザー全体の設定を変更しません。無関係なTOML設定を保持し、変更する既存ファイルはバックアップします。カスタマイズ済みSkillとの競合では停止します。
新規Codexサーバ設定は無効を初期値にします。開発中は再設置・通常接続の有効化を行いません。パスはこのPC専用です。

## 検証記録

### 現在の到達点（2026-09-20）

- 通常のcadMCP接続と製品Skillは開発中のため無効。隔離した通信試験は50工具で成功しているが、現在のGUI接続成功とは扱わない。
- 全回帰 `verification/windows-codex-20260920-delivery-all.xml` は449成功・2スキップ・失敗0。これは納品STEP整合性検査を含む版の結果。
- 実モデルによる新規L字STEP生成と、別コンテキストの5役×2巡レビューは実行済み。ただし最新レビューは `not_accepted`。単純試験部品の生成・幾何合格を、マウス機構や物理性能の完成へ拡大しない。
- `verification/delivery-consistency-20260920-v2.json` は既存L字の個別STEPとassembly STEPの双方向差分体積0を確認した開発証拠。旧レビューは書き換えていない。

### 以前の実行記録（現在の完成判定の代用にはしない）

- 本体 `verification/windows-codex-20260919-v2.xml`: 345成功、2スキップ、失敗0（Windows symlink作成不可）。
- 本体 `verification/codex-connection-20260919-v2.json` と `cursor-connection-20260919-v2.json`: 各設定から46ツール取得、doctor・検索状態・schema取得。
- workspace `integration-tests/codex-model-20260919/result.json`: 実Codexモデル、日本語原文保持、未実施物理試験false。
- workspace `integration-tests/codex-cad-20260919/DEMO_RESULT.json`: 4公開実例の隔離カタログ、既存レシピのCAD生成と幾何検査。全件検索品質やAIの自律設計品質の試験ではありません。
- 同フォルダー `CODEX_REVIEW_RESULT.json`: 実モデルのverification役を1回実行し保存。実行ポリシーでファイル直接確認が拒否された旨を申告し、結論はrevise。全5役や画像閲覧成功の証明ではありません。
- workspace `integration-tests/codex-evidence-20260919/EVIDENCE_PROBE_RESULT.json`: JSON原文とPNGを実モデルが直接確認。nonce、画像観察、shell不使用を記録。
- workspace `integration-tests/codex-studio-e2e-20260919/codex-review-loop/CODEX_REVIEW_LOOP_RESULT.json`: 隔離公開デモで、負例と修正後の各々を5役×2ラウンドで別実行。型付き修正、固定条件維持、再測定、引渡しまで21回上限内で記録。
- 修正後は幾何passだが、物理性能・人間承認・実機適合はunknown。レビュー実行は製品完成を意味しません。
- 粗い要求からの実モデル経路は、実CAD検索、2案、画像付き選択まで到達しましたが、Recipe DAGが不正でCAD生成前に安全停止しました。次の主課題です。

残作業と完成判定は `IMPLEMENTATION_PLAN_JA.md` を正とします。
