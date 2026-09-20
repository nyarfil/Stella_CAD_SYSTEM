# cadMCP Design Studio 0.3.3 正式版運用ガイド

ファイル名の`MCP_PREVIEW_JA.md`は既存参照との互換性のため維持しています。内容は現行正式版0.3.3の運用境界を示します。

ユーザーの方針変更により、高度化を一旦区切りMCP利用を優先する。0.3.3はMCPソフトウェアの正式版として扱うが、競合以上の評価・CADレビュー受入・物理性能保証とは称さない。

## 起動と責務

- Codex: このルートの `.codex/config.toml` でcadmcp-design-brainと製品Skillを有効化。既存Python環境と01_CURRENT本体、cadmcp-workspaceを使用する。グローバル信頼・認証・安全設定は変更しない。
- Cursor: 既存無効状態を保持。将来接続する場合も同一本体と検証ロジックを使用し、別エンジンにしない。
- Factory OS → factory-cad-3dp → cadMCP工具 → CadQuery。モデル・費用・委譲・最終判断はFactory側、cadMCPは状態・型付き形状生成・証拠管理を担当する。
- 本体開発はfactory-software。製品SkillのCAD手順をソフト開発へ適用しない。
- Factory標準スキル・agents・hooksは変更しない。個人能力カタログのreferences/cadmcp.mdを接続点とする。

## 受入と限界

現Codexアプリの実工具からdoctor/fs_status/projects/FunctionBrief schemaの読取呼出しに成功。証拠は本体verification/mcp-preview-app-connection.json。設定の存在やPython直呼出しとは区別する。常駐プロセスが最新wheelと同一コードかはこの診断では証明しない。

実行時のverification配下（モデル呼出しログ、画像、STEP、wheel等）はローカル証拠として保持し、GitHub公開対象からは除外する。再現時はテストと診断スクリプトを実行して新しい証拠を作る。

カタログ175,978件、CAD紐付け175,978件、機能注釈付き128,873件、機能24,757、意味索引ready。B-rep測定記録は5件で全件測定済みではない。検索品質・物理性能をreadyフラグから推定しない。

原理参考R2は実Sol14呼出しで新規形状、5役2巡、固定oracle測定まで完走。参照形状importなし、径方向隙間0.3mm・非干渉・部品対応の検査はpass。ただしレビュー受入not_accepted、物理未認定。後測定oracleを先行レビューが見たとは扱わない。

マウス曲面/肉厚/可動機構、提供CADの局所編集範囲契約、未知事項の部分解消、clean環境配布、同条件競合比較は残課題。保護部品・元要求・検査閾値を緩和して通さない。

## 利用手順

このプロジェクトをCodexで開き、工具が出ない場合は新しいタスクで再読込する。信頼確認が出た場合は所有者が判断する。doctor/fs_status/projects/schemaを実呼出しし、CAD設計時だけ製品Skillを読む。元ZA13・正本・未保存Fusionは明示許可なしで編集しない。まず新しい試験案件で使用する。

MCP呼出し自体は追加のCLIモデル実行を起動しない。自律実証スクリプトの実行は別の費用を伴うため、回数・時間を合意してから行う。

## 戻し方

Codexプロジェクト設定のcadMCPと該当Skillのenabledをfalseへ戻す。変更前設定は `.codex/config.toml.before-mcp-preview`。後から加えた無関係設定を失わないよう、ファイル全体の上書き復元は避ける。
