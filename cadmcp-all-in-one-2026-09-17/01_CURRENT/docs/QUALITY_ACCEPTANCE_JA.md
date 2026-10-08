# CADMCP Design Studio 品質受入基準（第三者再現用）

**基準日:** 2026-09-20  
**対象:** `cadmcp-all-in-one-2026-09-17/01_CURRENT`  
**目的:** 自動テストの成功と、CAD設計システムとしての完成を混同せず、第三者が同じ入力・環境・証拠から独立して受入判定できるようにする。

## 最新の追加実証（2026-09-20）

以下の旧時点の記述より新しい結果: `windows-codex-20260920-supplement-all.xml` は415成功・2スキップ。Loft追加後の関連試験 `windows-codex-20260920-loft-acceptance.xml` は50成功であり、全体再試験の代わりではない。公開schemaの同期後18試験成功、生成失敗時の保全等を加えたschema対象3試験成功。重複する件数は合算しない。

`supplement-review-20260920/SUPPLEMENT_REVIEW_RESULT.json` は実Sol10呼出し、5役×2巡、画像2件・JSON6件の提供/閲覧記録、相互批評を保存した。これは旧「新レビュー0件」の時点からの進展であるが、5役ともrevise、受入はnot_acceptedのまま。個別STEPとassemblyの整合性、歴史的unknownと現在の測定状態の区別、比較許容差の意味、負例検査根拠の添付が指摘された。将来reportの許容差説明のみ追加済みで、過去の判定を変更していない。

Loftは平行XY多角形断面に限定される。一般自由曲面・Sweep・肉厚・マウス機構・物理性能・他製品との優劣を実証したものではない。

納品整合性の開発実測 `verification/delivery-consistency-20260920-v2.json` は、同じ実モデルL字の個別STEPとassembly STEPを再importし、双方向差分体積0、1対1 solid対応、元証拠不変を確認した。検査コードhash付き、90秒worker上限、追加モデル呼出し0。正式レビューsubjectの更新や再受入ではなく、この証拠だけで過去のreviseを解除しない。

納品整合性版の全回帰 `windows-codex-20260920-delivery-all.xml` は449成功・2スキップ・失敗0。次段の追加測定契約改訂前の結果である。

否定対照 `verification/delivery-controls-20260920-r3/DELIVERY_CONTROLS_REPORT.json` は手書き実CADの正例1・負例5を測定し全期待判定に一致した。固定case/部品集合、実STEP hash、検査コードhashを保持する。同じCadQuery/OCCTで作成・測定した検査器の自己試験であり、別カーネル・未知案件成功率・物理性能の証明ではない。正式subjectへの連携はまだなく、過去のレビューがこの新証拠を閲覧済みとは扱わない。

追加測定の正式統合版は関連103試験成功。その後の通常build status表示補正は関連11試験成功（重複あり、合算しない）。`original-design-20260920-r2-remeasure/SUPPLEMENT_RESULT_V3.json` は正式report内の納品整合性まで含む10確認成功、元CAD bytes/元証拠不変、モデル0、CAD再生成なし、新レビュー0、owner_ready=false。必須添付は画像2/JSON7の9件となり、新しいdelivery manifestも登録hash付きで含む。現行版全回帰と新5役レビューはまだ実行していない。

- 追加測定APIを組み込む前の全回帰は405成功・2スキップ・失敗0（`windows-codex-20260920-goal1-final.xml`）。後から追加した機能までこの件数で合格扱いしない。
- `original-design-20260920-r2-remeasure/SUPPLEMENT_RESULT_V2.json` は、実モデルが設計したSTEPの同一bytesを追加測定し、新しい正式レビューsubjectを登録した証拠。元subject・元STEPは不変、CAD再生成なし、追加モデル呼出し0、新レビュー0件、owner-ready=false。
- 元build-record/measurementsと追加spec/reportがhash固定の必須添付になった。Q-09の「証拠を正式に渡す経路」は進展したが、未知の自動解消・指摘の完了判定・新5役再レビューは未完了。
- `SUPPLEMENT_RESULT.json`（V2なし）は監査補強前の試行で、最終受入証拠としては使わない。
- `codex-isolated-20260920-supplement.json` は通常disabledのまま50工具の隔離stdio通信を確認。GUIや実モデルの新接続試験ではない。

## 1. 結論と判定規則

現時点では、ソフトウェア回帰と隔離されたMCP stdio接続には証拠がある。一方、実モデルによる新規CAD完成、提供CADの保護付き再利用、原理参考の形状非流用、マウス曲面・可動、物理性能、配布のクリーン再現性、コスト比較は完成を示す証拠がない。したがって本資料だけで製品完成とは判定しない。

受入は機能単位に行う。次のいずれか一つでも欠ける機能は `PASS` ではない。

1. 固定した要求と入力のハッシュがある。
2. 実行環境・依存関係・コマンドが第三者に再現できる。
3. 期待結果を満たす実行証拠（ログ、構造化結果、生成物、SHA-256）がある。
4. 失敗時に安全に停止・記録・復帰でき、条件や検査を弱めていない。
5. CADの場合、形状・寸法・干渉・クリアランス・組立/動作・製造性の該当証拠がある。
6. 実機・物理性能・社会的評価を主張する場合は、コード試験とは別の実測・人手評価がある。

### 判定語

| 判定 | 意味 |
|---|---|
| `あり` | この版の対象と条件に対する、直接的で再読可能な証拠が存在する。 |
| `部分` | 一部の層（例: fixture、stdio、回帰）はあるが、実運用または別の必須層がない。 |
| `不足` | 要求に必要な証拠がなく、現状は受入不可。 |
| `未実行` | 実行記録がない。失敗とは別だが、合格とも扱わない。 |
| `不合格` | 実行した結果が受入条件を満たさなかった。 |

達成率・点数は定義済みの重み、母数、反復回数がない限り算出しない。本表の状態を足し上げて「何%完成」とは呼ばない。

## 2. 要求と必要証拠の一覧

| ID / 要求 | 受入に必要な証拠 | 現在の証拠 | 残る境界・判定 |
|---|---|---|---|
| Q-01 通信・設定分離 | production configを変更せず、通常disabled、明示した隔離workspaceだけで接続するログ。入力configと出力configの差分。 | **部分**。`verification/codex-isolated-20260920.json` はWindows隔離stdio、47 tools、`configured_enabled=false`、`host_config_modified=false`を記録。 | GUI/Agent CLIの実接続ではない。通常開発からのMCP不使用を別環境で再確認する。 |
| Q-02 コーパス・意味検索 | データセットSHA、件数、索引マニフェスト、検索の再現結果と品質校正。 | **部分**。`codex-connection-20260919-v2.json` 等に175,978行、semantic ready、データSHAがある。 | `annotation_origin` は推論由来で、検索品質・論文結果との一致は未校正。 |
| Q-03 原理参考（inspiration） | 原参考のUID/evidence digest、参照面、STEP export SHA、`reference_use`、最終形状が参考の直接再利用でないこと、照合ログ。 | **不足**。スキーマ・fixture検査はあるが、実参考を使ったエンドツーエンド成果物の独立記録がない。 | hash不一致、面の取り違え、直接流用を合格にしない。 |
| Q-04 提供CAD（provided CAD） | 登録済みファイルの実在とSHA、登録UID、ProjectStep/Referenceの役割、保護部品と配置の差分、出力への追跡。 | **不足**。ready packの存在検査と契約テストはあるが、実提供CADを保護して生成・検査した証拠がない。 | 「STEPがディスクにある」だけでは登録済みCADとはみなさない。 |
| Q-05 新規自由形状 | catalog/referenceなしの入力、`original` route、typed Recipe、CadQuery生成物、STEP/画像/幾何検査、レビュー記録。 | **部分**。`verification/original-design-20260920-r2/ORIGINAL_DESIGN_RESULT.json` は実モデル14 calls、STEP生成、5役×2巡を完走したが `acceptance_status=not_accepted`。後続 `original-design-20260920-r2-remeasure/INDEPENDENT_ACCEPTANCE.json` は固定6頂点の対称差分0、bbox/体積/欠き取りをpassした。 | R2のレビュー判定はnot acceptedのまま。remeasureは測定器修正後の再測定であり、製品完成・物理認証・新規レビュー完走の証拠ではない。旧5-call初回は別の安全停止記録として保持する。 |
| Q-06 マウス曲面・可動 | 実ボード/シェルpackのUID・寸法、曲面の形状/厚み、保護部品の固定、干渉ゼロ、操作/回転/組立経路、実機または指定代替試験。 | **不足 / 未実行**。隔離doctorではready pack 0、`generated_cad=false`、不足はready board/shell。旧接続記録のpackは入力準備であって構造CAD完成ではない。 | PCB・スイッチ・センサー・シェル外形を動かしただけの成功を受入しない。 |
| Q-07 失敗・復帰 | 失敗入力、エラーコード、保存された状態、再試行の入力/出力SHA、検査の保持、worker前拒否、復帰後の同一要求。 | **部分**。R2はnot acceptedの元証拠を保持し、remeasure JSONは同じrequest、Recipe SHA、zero-tolerance dimension contractを不変として確認。新しいsubjectは旧レビューをコピーせず、実モデル呼出しなしで測定器修正後のgeometry passを記録した。 | これは再測定と証拠保全であり、providerが失敗から同じ要求を再生成して受入まで復帰した証拠ではない。 |
| Q-08 条件・保護 | protected IDs、baseline checks、条件数値/種類/閾値の比較、無関係設定の不変SHA、違反時のbuild前拒否。 | **部分**。baseline・development isolation・自動拒否のテストはある。 | すべての実運用経路と実成果物に保護が適用された証拠は不足。 |
| Q-09 未知の解消 | 未知を `unknown` として保存し、解消入力・根拠・再検査・解消者を追跡。未解消を合格にしない。 | **部分**。状態/レビュー契約で未知を表現する試験はある。 | 実ユーザー要求から未知を解消した実行記録、人手確認、CAD再検査が未実行。 |
| Q-10 配布・環境再現 | clean machine/venvへのinstall、lockまたは全依存記録、wheel SHA、console/MCP起動、同じ結果、二回以上の再実行。 | **部分**。旧`test-results.json`はwheel SHAと304 tests、stdio smokeを記録。 | 旧環境は依存site-packagesを`.pth`で共有し、実GUI/Windows/clean installではない。現行0.3.3成果物の独立clean installは未実行。 |
| Q-11 コスト・時間 | 事前に固定したモデル、回数、タイムアウト、計算資源、所要時間、失敗/再試行費用、成果物単位の測定。 | **不足**。旧初回は5 calls、R2は14 model callsでreceipt時間が保存されている。 | 受入閾値、成功案件との比較、同条件の反復がないため、費用対効果は判定不可。call数を完成度の割合へ換算しない。 |
| Q-12 同条件競合比較 | 同一要求・入力・モデル/温度・予算・ハードウェア・評価者・反復数で、比較対象と指標を固定した結果。 | **未実行**。外部比較調査は本資料の対象外で、比較対象URLも推測しない。 | 外部ベンチマークを採用する場合も、公開説明だけで優劣を断定せず、同条件の実測を別ケースとして残す。 |
| Q-13 レビュー・証拠 | 要求、機構、組立、製造、検証の5役による独立レビューと反証、source/evidence digestとの紐付け。 | **部分**。R2は要求・機構・組立・製造・検証の5役×2巡（10 review submissions）を保存し、相互反証は記録されている。 | R2のgeometry reviewはfail、overallはunknown、acceptanceはnot accepted、independence_verified=false。remeasure後の新subjectはreview status `not_run`、reports=0であり、修正後の独立レビューではない。 |
| Q-14 物理・社会 | 実機試験、造形/加工、組立、耐久、操作性、利用者評価、事故/安全評価をコード証拠と分離して記録。 | **不足 / 未実行**。旧資料も物理性能を未認定としている。 | コード試験、CAD幾何証明、ユーザーの社会的評価は互いの代替にならない。 |

## 3. シナリオ別の独立受入手順

### 3.1 原理参考と提供CAD

同じ参照を「参考にした」ことと、形状を直接再利用したことを分ける。第三者は次を一組として保存する。

- 参照UID、登録時と実行時の evidence digest、CAD exportのSHA-256、使用面ID。
- `principle_reference` / `fit_reference` / `direct_reuse` の別、要求されたfunction_id、選択されたsource digest。
- 提供CADの場合は元ファイル、登録記録、保護部品ID・配置・許可された変更範囲。
- 生成Recipe、検査の全数値・閾値・種類・ID、build前の許可集合検査ログ。
- 最終STEPと再計算したSHA-256、元参照との差分説明。

current evidenceにUID/digestだけがあっても、実ファイル、面、生成物の三者がつながらなければ `Q-03/Q-04` は不足のままとする。

### 3.2 新規自由形状

参照なしfixtureではなく、実providerを含む一つの固定要求を使う。入力に「カタログ形状を流用しない」を含め、検索候補、選択集合、Recipe、CadQuery出力、STEP、幾何検査、要求・機構・組立・製造・検証の5役レビューを一つの証跡鎖にする。R2は実モデル14 callsでSTEPと5役×2巡まで到達したが、`not_accepted`を維持する。remeasureは同Recipe/requestとzero tolerancesを保ったまま独立STEP測定をpassした別subjectで、レビューは未実行である。失敗時は `not_accepted` として残し、成功を推測で補完しない。旧5-call初回記録も負の対照として保持する。

### 3.3 マウス曲面・可動

ready board/shell packの実在、寸法・面・配置を最初に読み戻す。続いて、曲面シェル、PCB/スイッチ/センサーの保護、内部クリアランス、操作ストローク、回転・組立経路を別々に検査する。`distance=0`だけでは接触と干渉を区別できないため、交差体積、取付面、動作範囲、組立経路を記録する。物理保持、ばね寿命、手触りは別の実機試験が必要である。

### 3.4 失敗・復帰と条件保護

1. 故意に不正な参照、誤ったcheck target、未登録CADを入力する。
2. build前に型付きエラー（例: `AUTOPILOT_REFERENCE`、`AUTOPILOT_WEAKENED_CHECK`）で停止することを確認する。
3. raw recipe、訂正応答、拒否理由を保存する。
4. 訂正後も、元から存在したcheckの数値・種類・ID・閾値・対象が保持されることを比較する。出力nodeから同一output.part_idへの一意変換以外の変更は許可しない。
5. 同じ要求を再実行し、production workspace、host config、保護部品、無関係設定が変わらないことをSHA/差分で確認する。

R2の再測定を記録する場合は、元のR2 JSON、request SHA、Recipe SHA、dimension checkの種類・ID・nominal・`tolerance_mm=0.0`を先に保存し、測定器の設定変更後に新subjectを作る。新subjectのgeometry passは、旧R2の `not_accepted` を上書きせず、旧evidenceが不変であること、新レビューが未実行なら `not_run` であることを同じ報告書に残す。

### 3.5 配布再現性と比較

第三者はリポジトリのrevision、Python、OS、依存バージョン、wheel SHA、入力SHAを記録し、隔離環境を二度作る。通常開発のMCPはdisabledのまま、テスト時のみ明示した隔離workspaceで起動する。比較試験を行う場合は、結果を「成功/失敗」だけでなく、検査合格、参照忠実度、停止安全性、時間、呼出回数、再実行一致率に分解する。比較対象の調査・選定は別の責任者が一次情報付きで行う。

## 4. 第三者再現プロトコル

以下は受入を主張するための記録順であり、未実行の項目を自動的に合格にしない。

1. `git revision`、作業ツリー差分、対象文書のSHA-256を保存する。既存のdirty変更は破棄しない。
2. production workspaceとhost configをバックアップではなく読み取り比較し、MCPを通常disabledに固定する。
3. cleanな隔離workspace/venvを作り、依存の取得元とバージョン、wheel SHAを保存する。
4. offline回帰を実行し、JUnit XML、stdout/stderr、終了コードを保存する。回帰成功はQ-05/Q-06/Q-14の代用にしない。
5. 接続確認は、明示した `--isolated-test-workspace PATH` のみで実行し、production workspaceと一致するPATHを拒否する。host configの前後差分が空であることを確認する。
6. シナリオごとに要求JSON、参照/CADファイルのSHA、provider receipt、Recipe、検査結果、生成STEP/画像のSHAを同じケースディレクトリに保存する。
7. 成功・停止・復帰をそれぞれ別ケースとして再実行する。モデル呼出しを行わないケースでは `model_called=false` を記録する。
8. 人手・実機・社会評価を行わなかった場合は、該当欄に `未実行` と記録する。

## 5. 受入記録テンプレート

```text
case_id:
requirement_id:
decision: PASS | PARTIAL | INSUFFICIENT | NOT_RUN | REJECTED
repository_revision:
dirty_tree_policy:
os_python_dependencies:
input_manifest_sha256:
reference_or_cad_sha256:
command:
expected:
actual:
artifact_paths_and_sha256:
provider_model_and_call_count:
reviewer_and_date:
physical_or_social_evaluation: NOT_RUN | evidence path
notes_and_unresolved_unknowns:
```

`PASS` はこのテンプレートの必須欄が埋まり、要求固有の証拠が直接確認できる場合だけに使う。テスト名、ログ件数、モデルが応答した事実だけではCAD完成を意味しない。

## 6. 現時点の主な見落とし候補

1. R2では実モデル14 callsでSTEP生成まで到達したが、受入はnot accepted。remeasureのgeometry passは証拠を補正した別subjectで、レビュー0件であり完成受入ではない。
2. 原理参考・提供CADについて、UID/hashの契約テストと実CAD生成物をつなぐ独立証拠が不足している。
3. マウス曲面・可動・保護部品の実形状/干渉/組立/物理試験が未実行である。
4. 旧配布検証は共有site-packagesを`.pth`で参照しており、現行版のclean install再現性を証明しない。
5. コスト・時間の受入閾値、同条件競合比較、利用者/社会評価は未定義または未実行である。

この5点をscope外へ移しても、製品完成の証拠にはならない。未実行は未実行、不足は不足として残し、該当シナリオの独立証拠が揃うまで受入判定を保留する。

## 7. 参照した現行証拠と歴史資料

- 現行隔離接続: `verification/codex-isolated-20260920.json`
- 現行Windows回帰: `verification/windows-codex-20260920-integrated.xml`（読み取り集計: 379 cases、failures 0、errors 0、skipped 2）
- 現行モデル実行の負の対照: `verification/original-design-20260920/ORIGINAL_DESIGN_RESULT.json`
- R2実モデル実行（14 calls、5役×2巡、not accepted）: `verification/original-design-20260920-r2/ORIGINAL_DESIGN_RESULT.json`
- R2再測定（request/Recipe/zero tolerances不変、独立geometry pass、new subject review 0）: `verification/original-design-20260920-r2-remeasure/INDEPENDENT_ACCEPTANCE.json`、`NOMINAL_REBUILD_RESULT.json`
- 旧回帰・配布記録（0.3.1、歴史資料）: `verification/test-results.json`、`TEST_REPORT_JA.md`
- 旧接続/Req2CAD状態: `verification/codex-connection-20260919-v2.json`、`verification/cursor-connection-20260919-v2.json`
- 受入の前提と境界: `README.md`、`IMPLEMENTATION_PLAN_JA.md`、`CHANGELOG.md`

旧計画資料は、手書き公開デモについて「実モデル21 calls、5役×2巡、破損形状failから修正後pass」と記載している。ただし、そこが参照する `integration-tests/codex-studio-e2e-20260919/codex-review-loop/CODEX_REVIEW_LOOP_RESULT.json` はこの作業ツリーで確認できなかったため、本版では独立再現済みの証拠として数えない。旧計画の記述と現行R2（14 calls、not accepted）を混同しない。

同条件比較を設計する際の候補情報として、親担当が確認した一次リポジトリを挙げる（いずれも自己公表内容であり、ここから優劣を推定しない）。[cadgenbench](https://github.com/huggingface/cadgenbench) は生成/編集とSTEP、validity・shape similarity・interface match・topology等の評価軸を説明している。[AgentCAD](https://github.com/n3r/AgentCAD) は同一kernel検証、structured error、parametric parts/package integrityを説明している。[Multi-Agent-CAD](https://github.com/Pan-Chera/Multi-Agent-CAD) はtyped multi-agentと予算枠・baseline比較を説明している。採用する場合は、同一入力・資源・評価者・反復数での実測結果をこの文書のQ-12記録として追加する。

上記ファイルの「記録がある」こと自体を、記録が主張する実運用・物理性能・社会的評価の独立証拠とは扱わない。資料の版が異なる場合は、実行日時・version・環境を優先して再確認する。
