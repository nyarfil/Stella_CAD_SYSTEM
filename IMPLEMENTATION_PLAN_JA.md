# Codex対応・cadMCP完成へ向けた受入計画

## 最新の注意事項（2026-09-20）

### 方針変更：高度化を中断しMCP正式版0.3.3へ

ユーザー指定により現在版0.3.3をMCPソフトウェアの正式版として引渡す。未達要件は保持し、高度化は再開指示後。正式版はCADレビュー受入・マウス機構・物理性能の完了宣言ではない。
R2は終了: 実Sol14呼出し、execution_completed=true、参照形状importなし、固定oracle4検査pass、要求/参考STEP/検査コードhash不変、5役2巡。レビュー受入not_accepted、物理未認定。追加モデル試行なし。
verification/package-20260920-mcp-handoffにwheel作成。既存venv/現ソースで隔離stdio50工具成功（codex-isolated-20260920-mcp-handoff.json）。clean install試験ではない。
現Codexアプリ実工具でdoctor/fs_status/projects/FunctionBrief schema成功（mcp-preview-app-connection.json）。本番は読取診断のみ。カタログ175978・注釈付き128873・機能24757・意味索引ready・BRep測定記録5。全件測定や検索品質の証明ではない。
CodexプロジェクトMCP/Skillを正式版として有効化。Cursor・無関係設定を保持。Factory標準は変更せず個人能力CATALOG/references/cadmcp.mdへ接続。docs/MCP_PREVIEW_JA.mdが現行入口（旧ファイル名を互換維持）。
引渡し対象回帰: development isolation / codex setup / protocol の27試験成功（3.25秒）。設定の構造比較で変更は該当MCP/Skillのenabled二箇所のみ、Cursor空設定保持を確認。wheel SHA256: 84c3de02d560d46549a782038ebc78084064491072677c4fc98309e94296c1b8。現在アプリの既存サーバとwheelのコード同一性・別PCのclean installは未検証。

原理参考R2: runnerの前後hash対象へautopilot.pyを追加し、対象13試験成功（10.45秒）。verification/reference-design-20260920-r2の実Sol試験は終了済みで、結果は上記のとおり。旧R1失敗記録も保持し、追加モデル試行は行わない。

以下の古い日付の「現セッション」「完了」「実行中」はその記録時点を指す。
以下の次段落以降は開発履歴であり、現行の正式版0.3.3の状態を上書きしない。
（履歴）通常MCPと製品Skillは開発中無効。直近の全体449成功は追加測定v2・証拠状態表示の統合前であり、現行全体の合格とは扱わない。
その後の全体回帰 `windows-codex-20260920-evidence-reference-all.xml` は488成功・2スキップ・失敗0、391.80秒。追加測定v2・証拠状態表示・原理参考実CAD試験までを含む。スキップはWindows symlink制約。この実行開始後に新規追加した `check_reference_design.py` / `test_reference_design_script.py` は含まない。
口頭の「実現見込み80％前後」「完成度半分程度」は主観的な見立てで、測定された成功率や受入判定ではない。完成判定は下記の証拠と未達項目で行う。

### 証拠状態表示の監修

継続確認: 実worker関連107試験成功（202.34秒）。最新監修後のfocused試験は、fixtureのfeatures欠落を補正後34試験成功（68.89秒）。途中の試験不備1件と再試験を区別する。いずれも実モデル呼出し0、通常MCP無効。全体回帰ではない。

### 原理参考の実CAD経路

次の実モデル試験を事前固定: 角フランジXY[0,24]×[0,18], Z[0,3] mm、中心(12,9)外半径4のスリーブZ[3,12]、内半径2の貫通穴Z[0,12]。軸は同中心、半径1.7、Z[-2,14]。2独立solid、径方向隙間0.3 mm、非干渉、体積は案内部品1296+96π mm3、軸46.24π mm3。参考は原理のみ、shape importなし。部品名・CAD操作は固定せず、事前oracleと納品STEPの幾何・配置一致で検査する。
この試験は限定的な剛体案内のソフトウェアfixtureで、実マウス・弾性・耐久・製造性能の代替ではない。公開4例の明示的lexical検索、Sol最大16呼出し/各180秒、repair0/replan1、独立5役2巡、CAD検査worker90秒を上限とする新runnerを実装中。現時点では新モデル呼出し0。参考・要求・受入条件の固定と失敗記録を監修してから一度だけ実行する。
新runner初版の親監修で空checks、矛盾verdict、誤STEP hashの受理、runroot外assemblyのworker起動を負例として再現（`windows-codex-20260920-reference-runner-audit.xml`: 4成功/4失敗）。実モデル実行は未解禁。初版の正例4成功を安全性・試験経路完成とは扱わず、固定入力hashの前後検証、worker返答の親再検証、入力パス境界を補強中。既存製品MCPコードへの変更ではない。
補強版の親再検証は13成功（10.29秒、`windows-codex-20260920-reference-runner-final.xml`）。空/矛盾/誤hash/誤returncode/誤spec/外部pathを拒否し、任意部品名・順序の実worker正例、実形状の軸位置ずれ・穴欠落の拒否まで確認。初回失敗XMLは保持。固定REQUEST/ORACLE/参考4STEP/evaluatorの前後hash、90秒workerを実装し、モデル呼出し前に編集を凍結した。
`verification/reference-design-20260920-r1` で実Solを一度開始した（process handle 87614）。最大16呼出し・各180秒、再計画1回、repair0。開始時点で結果未確定。次回は同じhandle/保存状態を確認し、観測待ちだけを理由に再起動しない。通常MCP/Skillは無効。本試験のoracle後測定を先行レビューが閲覧したとは扱わない。
R1は終了（exit1、2呼出し、`REFERENCE_DESIGN_RESULT.json`）。要求整理・参考取得後、Matrix.incompatibilitiesがoptionsに存在しない案名（Separate_bushing_or_bearing_insert等）を参照してValidationErrorとなった。新規設計CAD・5役レビュー・独立oracle測定は未到達。参考画像16枚添付のreceiptはあるが、添付だけで閲覧や設計品質の証明とはしない。既存runの書換え・再実行なし。
回復経路を補強: Autopilotの既存max_replans枠をMatrixの型/参照ID整合エラーにも共有し、無効Matrixとvalidation errorを保存して同じfrozen brief/参考情報で明示的再計画する。エラー箇所を黙って削除せず、上限0/1/2では各1/2/3回を超えずCAD前停止する。候補ゼロの再計画と別の追加枠を設けない。
対象回帰 `windows-codex-20260920-matrix-recovery-final.xml`: 25成功、27.42秒。初回は試験の機構案作成/機構レビューrole混同により1失敗・11成功、用途をschemaで区別して修正した（初回XML保持）。この25件はモデルdoubleを含み、実モデルの回復成功はまだ未実証。新しい実モデル試行は未開始。488全回帰はこのAutopilot変更前の版である。

`tests/test_reference_design.py` に、隔離した公開4件カタログから実CADをmaterializeし、正式Studio buildで原理参考だけを登録する試験を追加。元STEP hash保持、参照digest登録、形状importなし、指定L輪郭との双方向差分、参考CADとは異なる実形状、古い参照hash拒否を確認した。14試験成功（15.98秒、`windows-codex-20260920-reference-informed.xml`）。手書きレシピによる実kernel/worker試験であり、実モデルの原理理解、検索品質、物理性能の実証ではない。
利用者向けHTMLにも原理参考・寸法/接続面適合・直接流用の区分と応用方法、参照hashを表示する補正を追加し、最終再試験中。記録された利用意図を表示するもので、それ自体を性能証拠とはしない。
上記最終再試験は14成功（16.44秒、`windows-codex-20260920-reference-informed-final.xml`）。コード編集を凍結し、Solへ現行全体回帰を委任した。結果は未確認で、以前の449成功を現行版の成功として扱わない。

`studio/evidence_state.py` を追加し、歴史的な未検証宣言と現在の測定結果を別々にstatus・レビューpacket・納品JSONへ表示する。宣言の原文、元subject、元build-record hash、出現順によるIDを保持する。
親監修で判定不足をmeasured扱いする問題、bool/text判定矛盾、配列の元データ共有、packet圧縮後に表示がstatusと異なる問題を補正。対象12試験成功（0.36秒）。追加測定の実worker統合は結果待ち。
現行表示の関連23試験は成功（45.90秒、`windows-codex-20260920-evidence-state-final.xml`）。その後、人間向け納品Markdownも歴史的宣言と現在の観測を分け、対象12試験成功（0.24秒）。V3実モデル由来build-recordの読取表示で宣言6件と観測11件の分離を確認（記録への直接投影であり、新しいCAD検査・レビュー実行ではない）。schema --check差分0。
これは未知事項の自動解消ではない。指摘と追加証拠の対応、複合宣言の部分解消、否定対照の正式登録、新subjectの5役再受入、未知の実案件・マウス機構への適応、物理性能、比較評価は引き続き未完了。

2026-09-19。CursorとCodexから共通のcadMCPを利用する。既存データ、CAD、Cursor設定を保持する。
達成率ではなく次の受入条件と実行証拠で管理する。

| 段階 | 受入条件 | 状態 |
|---|---|---|
| Codex導入 | プロジェクト設定、既存Skill配置、冪等導入、バックアップ、無関係設定保持 | 実装・自動試験済み。Codexアプリの現セッションでも実MCPを確認 |
| 通信 | 生成されたCodex設定からstdio初期化、tools/list、doctor、検索状態、schema取得 | Cursor/Codex両設定から成功。Codexアプリからdoctor・fs_status・projects・FunctionBrief schemaを実呼出し済み |
| 回帰 | Windowsで現行全テスト実行、失敗の原因判定と必要な修正 | 全体345成功、2スキップ、失敗0。Windows symlink不可の2件のみスキップ |
| CLI | Codex実行能力診断、厳密JSON、schema検証、呼出し上限、UTF-8 | JSON本文埋込みとnative image添付を実装し、実モデルがJSON 1件・画像1件を直接確認。shell不使用 |
| 状態把握 | 案件一覧とStudio試作一覧。旧Brief状態とStudio履歴を混同しない | 実装・回帰試験済み |
| 統合実証 | 隔離workspaceでCAD生成、失敗検出、レビュー、修正条件維持 | 手書き公開デモを故意に破損し、5役×2ラウンドが不合格を検出。実モデルの型付き修正、再生成、同一閾値で幾何合格、再レビュー、引渡し保存まで実証 |
| 運用資料 | 実行証拠、既知制限、未達要件を掲載 | CODEX_GUIDE_JA.md、ARCHITECTURE.md、CHANGELOGに記録 |

## 完成条件の境界

ソフトウェアの通信・状態管理・幾何検査は自動試験で検証する。実モデルによる設計品質は
実際のモデル実行と成果物で確認する。製造、操作感、疲労などの物理性能は別の実機試験を要する。
検索時のオンデマンドB-rep生成を全件事前生成率だけで評価しない。
ゲートのgenerated_cad=falseは過去の生成履歴がゼロという意味ではない。
既存案件の文字コードはUTF-8とUnicodeコードポイントで再確認し、推測によるデータ修復はしない。

## 設計方針

共通Python MCP + ホスト別導入。利点は検査・状態・CAD正本が一本であること。
コストはCursor/Codex両方の接続テストが必要なこと。既存ソースの全面再編は行わず、
導入と診断をscripts、設計状態をengine/store/studioの既存責務へ追加する。
Codexプロジェクト設定は当該プロジェクトで利用し、グローバル設定や認証情報を書き換えない。

## 次の完成判定ゲート

| 優先 | 作業 | 合格条件 / 意思決定 |
|---|---|---|
| 完了 | Codexアプリで実MCP接続 | 現セッションからdoctor・fs_status・projects・schemaを実呼出し済み |
| 完了 | 証拠の直接閲覧 | 安全制御を変更せず、JSON本文を埋込み、画像をCodexのnative image入力で添付。nonce・画像観察・shell不使用を記録 |
| 完了 | 5役・相互批評・固定条件修正の実モデル実証 | 各役を別Codex実行、2ラウンド目は保存済み1ラウンド目IDを全件反証。21呼出し上限内で修正と再測定まで完了 |
| 一部完了 | 引渡しの網羅性 | DELIVERY.json/MDにSTEP、部品、根拠、参照、検証、不明点、未作成BOM、物理性能unknownを分離保存 |
| 未達 P1 | 粗い要求から複数案・CADまでの品質評価 | 実モデルで検索・実CAD化・2案・画像付き選択まで到達。型付きRecipeのDAG不整合を1回訂正しても解消せず、安全停止。CAD生成は未達 |
| P2 | 意味検索・形状・トポロジの評価 | 意味索引readyとは別に検索品質を評価。学習形状Encoder・本家自動Fusionは現状の完成条件へ無断追加しない |
| P2 | 実案件への反映・製造フィードバック | 対象CADと固定寸法、反映先の承認後。強度・疲労・操作感は実機試験 |

v0.3.1設計書の「未完全移植」と「今後の理想像」を、全部が既に実装された必須仕様と扱わない。
AgentCAD・学習形状Encoder・外部Orchestratorを一括導入する案は研究範囲と依存を増やす。
現行CadQuery基盤を安定化して実証する案は再現性と保守性に有利だが、それら研究機能は未搭載のままとなる。
まず後者を進め、品質測定で効果が必要と判断できた拡張を別段階にする。

## 証拠と限界

- 改修前: 325成功、2スキップ。最終全体実行: `verification/windows-codex-20260919-v2.xml`（345成功、2スキップ、失敗0）。
- Codex/Cursor設定からの実stdio試験: 本体verificationの各`connection-20260919-v2.json`（各46ツール）。
- 実モデル2呼出し: workspace/integration-testsのcodex-model-20260919、codex-cad-20260919/codex-review-calls。
- CODEX_REVIEW_RESULT.jsonはintegration_passed=trueでも設計合格を意味しない。1役だけ、conclusion=revise、discussion_ready_for_owner=false。
- 試験用CAD: 公開4実例の限定カタログ、手書きの既存レシピ。干渉0、隙間約0.15 mm、幾何合格、overall unknown。全175,978件の検索品質を実証していない。
- 元ZA13案件、CAD正本、Cursor設定、グローバルCodex設定は変更していない。Git commit/push、製品リリースも未実施。
- 証拠閲覧: `integration-tests/codex-evidence-20260919/EVIDENCE_PROBE_RESULT.json`。実モデル1回、JSON/PNGを直接入力、nonce一致、画像内の穴2個と中央軸を確認、shell不使用。
- 5役ループ: `integration-tests/codex-studio-e2e-20260919/codex-review-loop/CODEX_REVIEW_LOOP_RESULT.json`。手書きレシピを負例の起点とし、実モデル21回。破損形状fail、型付き修正半径1.65 mm、修正後pass、各subjectで5役×2ラウンド、相互反証済み。
- 修正後も物理性能、人間承認、実マウス適合はunknown。レビュー実行と製品完成を混同しない。
- 粗い要求の自動設計は、検索・2案・選択まで成功したがRecipe DAGを確定できずCAD未生成。現在の最重要未達である。

## 次の設計判断

| 案 | メリット | デメリット |
|---|---|---|
| 固定Recipe骨格と型付き差分だけを使う | 定型案件の再現性と監査性が高い | 未知の構造を既存テンプレートへ押し込める。唯一の設計経路には採用しない |
| 実モデルにRecipe全体を再生成させる | 新しい構造案への自由度が高い | 今回のような参照順序・型不整合が起きやすく、訂正呼出しと失敗率が増える |
| 操作を組み合わせるRecipeと事前能力診断、部分修正、証拠付き再計画を併用（改訂推奨） | 未知の構造を表現しながら、実行可能性と変更条件を検査できる | 能力情報、失敗分類、再計画と変更履歴の実装・試験が必要 |

固定骨格を唯一の経路にする前回方針は撤回する。定型案件では再利用し、新規構造では操作の組合せを許す。
大規模な別エンジン切替や旧 `LLM_cad_Projects` の有効化は行わない。

## 2026-09-20 柔軟性監査と改訂設計（監査時点。実装状況は末尾）

現状は既知の参照適合・剛体設計に強く、汎用の未知機構へ自動適応する実証はない。

| 確認した制約 | 必要な変更 |
|---|---|
| AutopilotはReq2CADを実体化できないと停止する。Matrixの参照はReq2CAD UID限定。一方、直接Recipeは登録済みproject_stepを受け付ける | 既存CADからの設計と実例検索を経路として区別する。検索結果ゼロは設計不可能とせず、照会修正・提供CAD利用・設計仮説の検証を予算内で選択。カタログ障害と不一致も分ける |
| 操作は参照、箱、円柱、変換、Boolean、全エッジfilletに限定。loft/sweep等はない | 開始前に作成・検査能力を照会。未知操作は具体的な不足能力として返し、必要な操作と検査を対で拡張。未対応を別形状で代用しない |
| 全出力ペアの重複を無条件でfail、動作は直線並進のみ | 剛体の隙間、接触、意図した圧入・弾性嵌合を別の設計関係として扱う。圧入に剛体検査のpassを付けず、対応する材料・公差・変形の証拠がなければ未検証を維持 |
| 検索・構想・選択で失敗すると停止し、再計画はない。修正は主にRecipe全体の再生成 | 失敗をデータ不足、能力不足、構文不整合、幾何失敗、要求衝突、権限不足に分類。該当段階へ戻る回数・時間を制限し、進展がない同一反復は停止 |
| unverified_requirementsも文字列ごと凍結し、同一subjectの過去reviseは残り続ける | 要求ID・検査目標を固定し、証拠に基づく未知事項の解消と指摘の訂正を追記で管理。実測failは新形状・再測定が必要。範囲外の提案や誤った指摘は根拠付きで区別 |

固定するものはユーザー原要求、保護資産、承認済み条件、試験対象、変更権限。
探索案、操作列、検索語、未承認の設計仮説まで固定しない。AI提案の数値は出所を明示し、
条件変更は新しい契約版として理由と影響を記録する。失敗後の閾値緩和を同じ試験の合格として扱わない。

合成可能な操作拡張を優先し、自由なPython実行を自動フォールバックにしない。
外部実行器を必要とする場合も、明示した能力と成果物契約で接続し、同じ保護・検査条件で再測定する。
この改訂は設計方針の更新であり、現行MCPがこれらの経路を実装済みという意味ではない。

受入試験は、(1) Req2CAD不一致だが提供STEPが有効、(2) 未対応loft、(3) 回転機構、
(4) 意図した圧入、(5) レビューによる範囲外要求の追加、(6) 試作後に証拠で解消した未知事項、
(7) 保護部品を含む修正と脱落防止を含める。未対応を適切に説明できたことと設計完遂は別に集計する。
既知テンプレートにない保留案件で成功率・必要介入・時間・モデル呼出し数を測る。

## 2026-09-20 開発分離と柔軟性改善の実装記録

ユーザーの最新指示により、製品MCPを開発の指揮系統から分離した。Codexの対象サーバと製品Skillを無効化し、Cursorの対象MCP設定はバックアップ後に除外した。他のユーザー設定、信頼設定、旧エンジン、正本CADは変更していない。既存セッションにロード済みの工具を即時アンロードできたとは主張しない。

Solは参照非依存の新規設計、Terraは証拠・修正契約、Lunaは開発分離と参照制約を担当。親が統合、回帰と実モデル失敗の確認を担当した。

| 実装した内容 | 検証・限界 |
|---|---|
| 実例の用途を原理参考・適合参考・直接流用に分離。根拠と検証計画があれば実例なしの新規設計を許可 | 原理参考を出力形状へ混ぜる必要はない。参考digest/STEP hash/面ID、提供CADの登録と実hashを検査 |
| auto / reference_required / original の経路、限定回数の構想再計画、能力照会ツール | 47工具。polygon_extrusion追加。loft/sweep、回転・弾性・物理性能検証は未対応のまま |
| 証拠閲覧と相互反証のゲート強化 | 未読/部分閲覧ではowner-ready不可。build-record改変検出。一時添付パスはhash照合後に登録パスへ戻す |
| baseline指定の修正契約 | 要求・保護条件・出力部品ID・検査を固定。baseline未指定の独立buildに修正保証は付けない |
| 開発中は接続無効、明示した別workspaceのみstdio試験 | verification/codex-isolated-20260920.json: protocol_ok=true、47工具、host_config_modified=false。現在のGUI接続成功を示す試験ではない |

### 実モデル新規設計試験：不合格を保存

`verification/original-design-20260920/ORIGINAL_DESIGN_RESULT.json`。Sol、最大16呼出し・各180秒、再実行なしの1run。実際は5呼出しで停止。固定したL字輪郭・厚さ2mm・体積400mm3を要求し、検索や既存レシピを使わず3案を生成した。しかし出力part_idと寸法検査partの不一致が1回訂正後も残り、CAD生成前に安全停止した。STEP・画像・5役レビューはこの試験では未生成。以前の手書き起点の修正試験とは別の証拠である。

対処は初回の型訂正と生成済み設計の修正を区別すること。誤記された参照名は同一対象への訂正を許すが、検査種別・寸法・閾値を弱めない。実モデル再成功は未実証であり、プロンプト修正だけで解決済みとはしない。

### 残る完成条件（優先順）

1. 新規設計を実モデルで生成→独立測定→5役閲覧・相互反証まで通す。単純部品の通過後もマウス曲面・機構の品質保証にはしない。
2. 案件単位で保護資産を永続固定する入口。現在の明示保護ID・baselineだけでは未指定の保護対象脱落を一般に保証できない。
3. 未知事項が実証で解消した場合と、誤指摘の訂正の追記・状態遷移。現在は訂正を保存できても過去のreviseを自動解消しない。
4. 提供CADのみの実モデル案件、能力不足、回転・圧入、マウス形状で評価。対応できないことを正しく説明する試験と、設計完成の試験を分ける。

通常MCPは未完成の間、無効のまま維持する。自動インストーラを動かしてCursorの接続を戻さない。

### 統合後の最終検証

- `verification/windows-codex-20260920-integrated.xml`: **377成功、2スキップ、失敗0**（269.19秒）。スキップはWindowsのsymlink作成制約。実モデル呼出しを含まない回帰試験で、テストダブルのレビューと実CadQuery検査を区別する。
- 前段の失敗記録は保存。従来Matrixのdesign_basis=null互換性不具合を修正し、旧参照経路も再試験した。
- 初回schema訂正時の検査値・件数・閾値の改変をプログラム側で拒否。部品参照の一意な訂正だけを許し、曖昧なnode/partの対応は停止する。テストダブルによる正例・緩和負例・曖昧負例を追加した。
- 製品Skill検査はUTF-8指定で成功。git diff --check成功。通常MCP/製品Skill無効、Cursorバックアップ保持を再確認。
- 実モデルの新規設計試験は引き続きnot_accepted。ソフトウェア試験成功を設計完遂・物理性能の証明へ転用しない。コミット・push・公開・正本CAD反映なし。

## 継続目標：第三者が再現・比較できる高品質な設計システム

ユーザーは意図したシステム全体の100%達成と、同分野の公開製品と同等以上の評価を目標に指定した。従来の70〜80%という実現性見積りを完成条件にはしない。古いアーキテクチャの全移植も目的にはしない。
社会的評価や競合優位は実装者の自己評価では証明できない。同じ要求・入力・予算での比較、第三者再現、人手評価を残課題として保持し、公開・外部提出は別途承認なしに行わない。

受入項目は本体 `docs/QUALITY_ACCEPTANCE_JA.md` に整理。通信・要求理解・原理参考・提供CAD・新規形状・マウス曲面/機構・失敗復帰・保護・未知解消・配布・時間/コスト・同条件比較・物理/社会評価を別々に判定する。

### 今回の実装・証拠（2026-09-20 継続）

- 新規設計R2: `verification/original-design-20260920-r2/ORIGINAL_DESIGN_RESULT.json`。実Sol 14呼出し、STEP生成、5役×2ラウンドの証拠付きレビューが完走。旧5呼出しの失敗runは保持。モデルの実設計であり、手書きRecipeへ差し替えていない。
- 独立STEP測定: 有効な単一ソリッド、外接20×14×2mm、配置0..20/0..14/0..2、体積約400mm3、欠き取り交差体積0。親もassembly.pngを直接確認した。
- R2の正式Studio判定はnot_acceptedのまま。描画後のtessellationを含むBoundingBoxが各軸約2e-7mm膨張し、モデルの許容差0に対してfailとなった。レビューは欠き取り・全輪郭の正式証拠不足も指摘している。
- 同一ソリッドで描画前20.0、描画後20.000000200000002の測定変化を再現。`studio/measurement.py` で表示用三角形を使わず基礎B-repから公称境界を測定。許容差や要求は変更していない。正寸法の描画前後一致と実寸法違反の負例を追加した。
- `studio/acceptance.py` はモデルRecipeを読まず、固定specのhashと成果物STEPから配置込みbbox・体積・部品数・必要/禁止領域を別プロセスで検査する。同bbox/同体積の別輪郭を負例で拒否。これは同じOCCTを使う別検証経路であり、別カーネルや物理性能の証明ではない。
- 案件単位のProjectProtectionを追加。保護CADのhash・登録配置・必須出力を永続化し、明示的な変更APIは理由・revision・before/after履歴を要求する。編集許可もhash固定。保護対象の脱落・移動・変更を拒否し、読取専用の切削参照は許可する。
- MCP工具は49に増加。設定の通常無効化は維持。保護変更APIの理由欄は所有者認証ではなく、実際の承認はホスト側の責任である。

### 次の実証で省略してはいけないこと

1. 修正後の測定器で同一Recipeを再生成・再測定し、旧不合格subjectを保持する。旧レビューを新subjectへ転記しない。
2. 独立検査を正式な証拠経路につなぎ、未実施→測定済みへの未知事項の更新と、レビューの誤指摘訂正を追記で管理する。
3. 単純L字の成功を自由曲面やマウス機構の完成へ拡大解釈せず、提供CAD・原理参考・曲面・機構・製造を固定案件群で検証する。
4. 未見の評価案件、配布のclean環境、同条件比較、第三者レビューを完了する。モデル呼出しの予算・経過時間・失敗試行をすべて数える。

### 統合確認の追記（2026-09-20）

- 上記1の同一Recipe再測定を実行済み。`verification/original-design-20260920-r2-remeasure/NOMINAL_REBUILD_RESULT.json` に要求・Recipe hash・ゼロ許容差チェック不変、旧R2全238ファイル不変、新subjectの幾何合格を記録。追加モデル呼出し0、新subjectのレビュー0件。旧レビューの転記や旧不合格の書換えはしていない。
- 同フォルダの `INDEPENDENT_ACCEPTANCE.json` は納品STEPを再importし、指定6頂点の押出形状との双方向差分体積0を確認。外接寸法・体積が同じ別形状を見逃さないための検査。基準specはR2実行後に追加した開発用検査であり、事前登録した未見ベンチマークとは称さない。元のゼロ許容差チェックとは別検査で、置換しない。
- `verification/codex-isolated-20260920-goal1.json` は49工具の隔離stdio試験成功。通常設定disabled、GUI/model試験ではない。試験workspaceのカタログ件数0は意図した分離であり、本番検索品質の証拠ではない。
- 正式な証拠登録と未知事項解消、新subjectのレビュー受入は引き続き未完了。
- 全回帰初回 `verification/windows-codex-20260920-goal1.xml`: 404成功、1失敗、2スキップ。追加保護試験のmodule fixtureがデモカタログの環境変数を復元せず、後続の空カタログ試験が4件を検出した。製品条件を変えず、該当fixtureと同種review fixtureに環境復元を追加。初回失敗記録を保持し、対象試験と全体再試験を別XMLへ実行中。再試験結果確認前に全体合格としない。
- 最初の環境復元修正は、元キーが存在しない場合にMonkeyPatchの復元対象へ記録されず、対象順序試験で再度失敗（`windows-codex-20260920-env-isolation.xml`）。明示setenvで元の不存在も記録する修正へ変更。先行する全回帰再試験は旧修正を読込済みのため中止し、合格実績に含めない。対象R2の結果を確認後に全回帰を再実行する。
- 対象R2 `windows-codex-20260920-env-isolation-r2.xml` は7成功、失敗0（42.91秒）。最終修正で全回帰 `windows-codex-20260920-goal1-final.xml` を開始。完了結果は未確認。
- 上記全回帰は完了: **405成功、2スキップ、失敗0、340.14秒**。スキップはWindowsのsymlink権限制約。これは追加検証版APIを組み込む前の版に対する結果であり、その後の変更まで合格したとは扱わない。

### 次の実装判断: 未知事項の解消経路

監査で、未検証文字列の削除を禁止する既存の固定契約は必要だが、新測定による解決状態の追記経路が不足していることを確認した。文字列を消す方式は採用しない。

| 案 | 利点 | 欠点・判断 |
|---|---|---|
| 後続buildのみ解決証拠として許可 | 既存baselineとsubjectの検証を再利用できる | 形状不変の追加測定にも再buildを強制する。柔軟性不足のため単独採用しない |
| 同一subjectへの追記専用証拠bundleと証拠revision | 形状不変の追加測定、誤指摘の訂正に対応できる | 証拠追加後の古いレビューを新証拠の確認済みとしない失効管理が必要。こちらを優先検討 |

元要求・元未検証宣言・古い指摘は不変、新証拠のhash/対象STEP/検査仕様を結合し、解決候補と検証済み解決を区別する。記録しただけでblockerや物理未検証を解除しない。実装・負例試験は次段であり、この監査だけで解決済みとはしない。

### 追加測定をレビューへ渡す経路（実装中の統合記録）

比較後、同一subjectを可変化せず、CADを再生成しない新しい検証版subjectを作る方式を採用した。旧証拠を保持して新しい5役レビューを要求できる利点がある一方、証拠コピーの容量と再レビュー費用が増える。

- `studio/supplement.py` と `brain_studio_verify_artifact` を追加。許可されたAcceptanceSpecに基づき、サーバworkerが元STEPと同hashのコピーを再測定する。任意reportやモデルの自己申告は受け取らない。工具50、通常MCP無効を維持。
- 元検査・未検証宣言・Recipe・要求を保持。追加検査だけ合格しても元の失敗は合格にならない。旧レビューを新subjectへ転記しない。
- 元build-record/measurements、追加spec/reportを必須添付にし、新reviewで実閲覧を要求する。引渡しJSONにも追加測定とCAD非再生成を別表示。
- 最初の対象試験38成功後、監査で追加reportの未検証省略と再読取時の元manifest照合を補強。`SUPPLEMENT_RESULT.json` は補強前の開発試行として保持し、最終結果の代用にしない。補強後は別V2記録・対象試験を実行する。
- これは未知事項の自動解決ledger完成ではない。新subjectの実モデル再レビュー、指摘と測定の対応付け、累積した複数追加検査の系譜は残る。単一追加検査の後も元subjectから別の検証版は作成できるが、派生subjectへの再追加は現時点で拒否する。
- 補強後の `windows-codex-20260920-supplement-r2.xml` は38成功。さらにtimeout時の未登録・コピー容量上限の負例を追加し、`windows-codex-20260920-supplement-final.xml` は15成功（既存review契約込み、58.95秒）。両者は重複する試験を含むため合算しない。
- `SUPPLEMENT_RESULT_V2.json` は8項目すべて成功。元フォルダ不変、STEP同一bytes、新subject、新レビュー0、owner-ready=false、幾何pass、CAD再生成なし、追加reportの必須添付を確認。モデル呼出し0。`codex-isolated-20260920-supplement.json` で工具50の隔離通信も成功。
- 新機能込みの全回帰 `windows-codex-20260920-supplement-all.xml` を開始。現時点では実行中で完了結果未確認。次回はこの実行を確認し、重複起動しない。
- 上記全回帰は完了: **415成功、2スキップ、失敗0、355.11秒**。Loft追加前の版として記録。スキップはWindowsのsymlink権限制約であり、物理試験等の代替合格ではない。

### 実モデル再レビューと曲面表現の次段

- `scripts/check_supplement_review.py` を監修し、`verification/supplement-review-20260920` で一度だけ実Solレビューを開始。10呼出し上限・各180秒・同時3、5役の第1巡完了後に第2巡。CAD生成・repair・追加再試行は行わない。実行完了とレビュー受入、添付実閲覧を別判定する。結果は実行中で未確定。
- 曲面表現監査: 現RecipeにはLoft/Sweepがなく、マウス外皮の断面変化を十分表現できない。既存CadQueryで平行XY断面の型付きLoftを追加する方針。断面の数・大きさ・向きとBRepを検査し、失敗時に別形状へ置換しない。一定断面のLoftは合法として、不必要な禁止を加えない。
- これは任意自由曲面・Sweep・肉厚保証・弾性変形の完成ではない。まずLoftの実カーネル試験を行い、その後に固定した曲面案件・保護部品との干渉・製造性へ進める。従来の全体完成条件は維持する。
- 実Sol再レビュー完了: `supplement-review-20260920/SUPPLEMENT_REVIEW_RESULT.json`。10呼出し、全10receipt、5役×2巡、相互批評・全8添付閲覧完了、元buildフォルダ不変。幾何passだが5役ともrevise、最終not_accepted。追加モデル再試行なし。
- 指摘から次の4件を保持: 個別model.stepとassembly.stepの幾何同一性、元unknown宣言と現在の測定済み状態の区別、数値比較許容差の明示、負例試験の根拠をレビューへ渡す経路。否定対照の単体試験はあるが、レビュー添付に含まれていなかった。未検証事項を削除して通す修正は行わない。
- 数値比較許容差の意味は今後のacceptance出力で明示する実装を追加。閾値は変更していない。旧report・旧reviseは書き換えない。他3件の正式経路と新モデル再受入は未完了。
- Loft実装済み: 2..16平行XY多角形断面、smooth/ruled、同一XY輪郭許可、無効断面拒否。親監修でwire作成失敗・空kernel結果・複数solidも型付きエラーへ統一した。`windows-codex-20260920-loft-acceptance.xml` は50成功（Loft、planning、測定、acceptance、supplement、review runnerの関連試験、40.73秒）。
- 公開Recipe等のschemaファイルが実行時契約に追従していないことを発見。runtime共通registryから全schemaを生成するスクリプトと全件一致試験を追加。schema同期・後続全回帰の結果は別記する。
- schema同期の実行は正常終了し、公開schema/protocol/supplement surfaceの18試験成功を確認。追加で破損JSONのcheckモード非変更・生成による復旧・置換失敗時の元ファイル保全を試験し、schema対象3試験成功、`generate_schemas.py --check` の差分0。生成は既存atomic_jsonを使用する。CHANGELOG追記の先行失敗では元内容が残っていることを確認し、再適用成功。失敗原因は未特定でありディスク障害とは断定しない。
- 次段の個別STEP/assembly整合性はSolへ限定委任。納品実ファイルを再importし、solid単位の双方向差分と1対1対応で欠落・余分・移動・異形を検出する方針。実装・検証結果の確認前に完了扱いしない。
- Terraの読取監査: 元unknown本文は保存したまま、対象subject/STEP/spec/report/検査種別に結びついた部分解消状態を別表示する必要がある。任意check IDの引用だけで未知を閉じる案は採用しない。特に「入力画像が未提供」は「生成画像を閲覧した」ことで解消しない。複合したunknownは一部だけ測定済みになり得る。固定検査スコープによる導出と人手の適用外判断を区別し、未知の文言や案件種別の固定リストで一般案件を塞がない設計を次段で詰める。現時点では監査案であり実装済みではない。
- 納品検査の開発実測: `verification/delivery-consistency-20260920-v2.json`。元の実モデルL字の個別STEPとassembly STEPを90秒制限workerで再importし、1 solid対1 solid、双方向差分体積とも0、元フォルダ全hash不変を確認。検査コード3ファイルのhashも固定。モデル呼出し0、CAD再生成なし、歴史的レビュー変更なし。これは正式subjectへの新証拠登録・再レビューではなく、開発用の読取実測である。V2なしの先行結果は検査コードhashを含まないためV2を優先する。
- schema・通常無効設定・protocolの対象試験 `windows-codex-20260920-schema-isolation.xml` は22成功。納品検査は関連回帰実行中で、全体回帰はその終了を待つ。
- 納品検査の関連回帰は完了: delivery consistency / studio / project protection / review contract の74試験成功、250.14秒。Sol実装を親監修し編集を凍結後、全体回帰 `windows-codex-20260920-delivery-all.xml` を開始。現在のprocess handleは35804で、完了前に合格件数を確定しない。schema --check差分0、git diff --check成功。
- 上記全回帰は完了: **449成功、2スキップ、失敗0、410.46秒**。スキップ2件はWindowsのsymlink作成制約。新規生成の納品整合性検査までを含む版の結果であり、次段の追加測定への統合はまだ含まない。

### 既存CADへの追加測定と否定対照の正式化

- Solに、既存の登録済み個別STEP/assembly manifestを追加測定workerへ渡し、同じ時間上限内で納品整合性も再検査する拡張を委任。新しい追加検証subjectだけに結果を登録し、元checks/unknowns/旧レビューは保持。旧reportの読取互換と新reportの必須検査を区別する。
- 親は新しいdelivery manifestをレビュー必須添付へ追加し、公開surface/schema対象6試験成功。実証スクリプトでは今後、正式report内のdelivery verdict/checkも要求する。
- Terraは実カーネルの正例と5種類の負例（同bbox同体積の異形、移動、欠落、余分、重複）の自己試験スクリプトを実装。初回は期待どおり判定したが、親監修で「期待不一致時に報告が保存されない」「空caseの成功申告を親が拒否しない」問題を発見。補強とR2実測を実施中。初回の全期待一致だけでは補強版の証明にしない。
- これらは未知事項の解消ledger・再レビュー受入・マウス形状設計の完成ではない。反復する実モデル実行を節約するため、今回はモデル呼出しを行わず、正式証拠経路と負例検査を先に検証する。
- 親監修で能力照会へ納品STEP整合性と実際の128-solid上限を追加。上限超過を形状不良と誤分類せずverification_capacityとして説明し、部品削除による合格を禁止する復帰案を返す。対象capability/添付surface計5試験成功。能力の存在と任意規模の案件を完遂できることは区別する。
- 否定対照の補強完了: `verification/delivery-controls-20260920-r3/DELIVERY_CONTROLS_REPORT.json`。正例pass・5負例fail、固定6case/部品集合/実STEPパス・hashを親側再検証。空case、空parts、異常ID、自己申告と判定の矛盾、差替えの試験を含む8試験成功。初回/R2結果も保持。physical=false、formal_subject_linked=falseであり、まだ正式レビューへ登録された証拠ではない。
- さらにクラッシュ/timeout/不正JSONでfailure.jsonが残る3負例を追加。controls/capability/published schemaの合計16試験成功（`windows-codex-20260920-delivery-controls.xml`、8.99秒）。既存R3実証の検査コードは不変。追加測定の統合試験はSolのhandle15741で継続中、結果未確定。
- 旧V2追加検証版の実読取 `verification/legacy-delivery-status-20260920.json`: 元フォルダhash不変、既存10レビュー保持、owner_ready=false、delivery_step_consistencyはverified=false/not_recorded_legacy。現在の実装で旧証拠が読めることと、新しい検査を実施済みとは扱わないことを確認した。モデル呼出し0。
- 正式統合の最終対象回帰（acceptance/supplement/surface/review_contract/delivery_consistency/studio）は103成功・失敗0、245.61秒。その後、親監修で通常buildのstatusにも記録済みのdelivery検査またはnot_recordedを表示する補正を追加。status/capability/surface/schemaの11試験成功。103と11は重複するため合算しない。現行版の全体再試験はまだ行っていない。
- 正式V3実証 `original-design-20260920-r2-remeasure/SUPPLEMENT_RESULT_V3.json`: 全10確認成功。新subject `c5aee0c425c67cd7aaa37634c9bfd7d77d1e5380d07fa4222f7c23de32a4c731` に元CADの同一bytesを追加測定し、正式report/check/STEP hash/manifestを登録。元証拠不変、モデル0、CAD再生成なし、レビュー0、owner_ready=false。新manifestもレビューpacketの必須添付に含まれることを確認。旧V2の10レビューは転記しない。
- 残件: 否定対照reportの正式subject連携、旧レビュー指摘と新証拠の対応付け、複合unknownの部分解消、累積追加測定の系譜、新5役による再受入。単純L字の証拠補強を、原理参考による設計成功・提供CAD編集・マウス曲面/機構・物理性能・比較ベンチマークの代わりにしない。
