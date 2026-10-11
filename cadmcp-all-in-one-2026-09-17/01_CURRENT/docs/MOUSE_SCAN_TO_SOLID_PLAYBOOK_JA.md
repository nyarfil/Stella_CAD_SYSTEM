# マウス スキャン→ソリッド 標準チェーン（プレイブック）

生スキャン（PLY）から、上シェルと底板のSTEP、および役割で色分けしたアセンブリSTEPまでを、MCPツールだけで一回で作る手順。全ツールを既定引数で呼ぶ。各ツールへの入力は、前段レポートの出力パスだけを使う。手作業のジオメトリ処理や出力ファイルへの後付けパッチは行わない。

## 原則

- 汎用であること。機種固有の座標や定数は使わない。非対称なマウスや左手用のマウスでも同じ手順で動く。
- 対称化は強制しない。領域ごとに鏡映テストを行い、ほぼ対称と判定された所だけを平均化するか、良い側を鏡映する。サイドボタンは鏡映しない。
- ラベルはヒントとして扱い、形状は幾何から決める。スキャンの忠実なコピーではなく、製品として通用する形状を目標にする。
- 修正は必ずツール本体に入れ、テストと自動ゲートを付ける。証明は、生スキャンから新しいフォルダへ再実行して行う。
- 判定は READY / NOT_READY / REVIEW の3種類。NOT_READY の場合は、その段で止まる。REVIEW の場合は出力が書かれ、人の確認を待つ。

## 段の順序（既定引数）

| 段 | ツール | 入力 | 主な規則・ゲート |
|---|---|---|---|
| s01 | brain_mouse_scan_model | raw PLY, unit mm | 溶接、デシメート、水密化（Hausdorff 0.05 mm 目標） |
| s02 | brain_mouse_prepare_scan | s01 target | 閉メッシュの検査 |
| s03 | brain_mouse_recognize_regions | scan_id | 左右クリック、ホイール、サイドボタン（ヒント）、利き手 |
| s04 | brain_mouse_recognize_shell | scan_id | 底板、上シェル、パーティング、センサー窓 |
| s05 | brain_mouse_scan_flush | s04 canonical.stl + labels | 底板を z=0 に置く剛体変換。面の順序は変えない |
| s05c | brain_mouse_scan_cable_fill | s05 flushed + labels | 前壁のケーブル穴を平らな壁で埋める。NOT_READY ならフィルメッシュを書かず、未充填のまま後段へ進む |
| s06 | brain_mouse_scan_symmetrise | メッシュ組* | 鏡映面を求め、領域ごとに対称テストする |
| s07 | brain_mouse_shell_fit | s06 対称化メッシュ + ラベル*, symmetry report | B-スプラインのスキン。front_cut は auto |
| s08 | brain_mouse_scan_click_grooves | s05 flushed + labels, symmetry report | G1.5 窓規則、外周の正則化、ゲート群 |
| s09 | brain_mouse_shell_solid | s07 report, s08 report | SS1.2（seam_to_crest）。閉じた1ソリッド |
| s10 | brain_mouse_click_slots | s09 solid, s08 report, symmetry report | CS1.3。スリット体積、窓がギャップ線上にあること |
| s10b | brain_mouse_scan_side_buttons | s10 slotted_shell, s05 flushed + labels, s03 regions report | 約1 mm 突出したパッド、溝 0.4 x 1.5 mm、鏡映しない |
| s11 | brain_mouse_plate_side | s10b shell, outline_mode mesh, outline_path = メッシュ*, symmetry report | PS1.5。底板の外形と側面 |
| s12 | brain_mouse_face_roles | s10b shell, s11 plate, hint = メッシュ組* | 面役割、assembly_colored.step |
| s13（任意） | brain_mouse_handedness_flip | s10b shell, s11 plate, s12 face_roles.json, symmetry report | 全体を鏡映して利き手を反転。HF1.0 |

\*メッシュ組の決め方: s05c が READY なら、そのレポートの `downstream.mesh` と `downstream.labels` を使う。充填パッチが末尾に付くため、面の順序が変わっている。s05c が NOT_READY なら、s05 の flushed メッシュとラベルを使う。s08 と s10b は、常に s05 の flushed メッシュとラベルを組で使う。

## 主な既定規則

- **ホイール窓（G1.5）**
  - 辺は、ホイールウェル縁とラベルの切り欠きの外側包絡に置く。
  - ホイールの平面外形に 0.5 mm を加えた範囲が入るまで、辺を広げる。
  - 角R は次の順に決める。
    - 切り欠きが窓とほぼ同じ大きさなら、切り欠きに当てはめる。
    - それ以外は、短辺の半分 x 0.8 とする。
    - どちらの場合も 2 mm 未満にはしない。
  - ゲート WINDOW_SHAPE_IRREGULAR: 角Rが小さすぎる、またはアスペクト比が 1–4 の範囲外。
- **クリック外周**
  - 幅 2 mm 未満のラベルのスパイクではスリットを動かさない。
  - ゲート PERIMETER_OUTLINE_ROUGH: 曲率の符号反転、または滑らかさが 0.02 mm を超える。
  - 鏡映する枝は、もう一方の枝がはみ出さない側を選ぶ。これにより、鏡映したスキャンでも同じ物理的な配置になる。
- **ケーブル充填（CF1.0）**
  - ポケット周囲 4 mm の信頼できる壁に、3次多項式を当てはめる。
  - 前壁が滑らかでなければ CABLE_INFERRED_WALL_NOT_SMOOTH とする。
- **サイドボタン（SB1.0）**
  - フランクごとに 0〜2 個。
  - 信頼度が high 未満なら、スキン + 1.0 mm とし、REVIEW にする。
  - face_roles では sidebutton / sidebutton_wall（緑）として読む。
- **シーム（SS1.2）**: 壁のふくらみの側面にあるシーム点は、稜線へ移す。
- **底板（PS1.5）**: 丸い脚部は床まで実測する。外形は内側にのみ外挿する。

## 利き手の反転（HF1.0、任意の s13）

- 完成した右手用（または左手用）のマウスを、再設計せずにもう一方の手用にする。上シェル、底板、face_roles.json を、symmetry report の鏡映面（または mirror_normal + mirror_d）で全体鏡映する。鏡映面は既定値を持たず、必ず与える。
- 傾いた鏡映面でも床が傾くため、床の最小二乗平面を水平にする最小の剛体回転と z 移動で、床をちょうど z=0 に戻す。剛体なので形状も対称性も変わらない。鏡映で体積が負になったソリッドは向きを直す。
- 面の順序と役割は保つ。サイドボタンの役割は反対側のフランクに移る。point と bbox は書き出した STEP から測り直す。assembly_colored.step は役割から色を付け直す。
- ゲート（NOT_READY）: 無効なソリッド、床が z=0 から 1e-3 を超える、体積が元と 0.1 % を超えて違う、サイドボタンのフランクが入れ替わらない、面数・役割数の違い、面が元の面の像でない、STEP の読み戻しで色が失われる、殻と板の接触・非重なりが変わる。
- 出力は mouse/cad/<hf_id>/ に一度だけ書く。証明は e2e_final の結果を e2e_final_lh へ流して行い、手作業の LH_v6 と ICP 偏差で比べる。

## 証明と比較

- 実行フォルダ（例: e2e_final）に raw/ と run_chain.py、call_tool.py を置く。`python run_chain.py` を実行すると s01〜s12 が走る。
- 汎用性の確認として、鏡映した生スキャン（左手用）でも同じドライバを実行し、全段 READY になることと、配置が鏡映になっていることを確かめる。
- 基準形状との比較は、ICP偏差、底板外形のHausdorff距離、面の数と役割ごとの数、スリット体積、前壁、サイドボタンの各項目を、解析専用のスクリプトで行う。比較結果はツールの入力に戻さない。
- スキャンデータと実機の基準データはリポジトリに入れない。テストは合成データだけで行う。

## メッシュ backend の選択（numpy / pymeshlab / cgal、任意）

- 標準チェーン（s01-s13）は変えない。どの段も cgal を使わない。cgal は `brain_mesh_ops` の**ユーザー選択式**バックエンドだけ。
- 選択は案件（workspace）ごとに `.cadmcp/mesh-backend.json`。未選択なら `brain_mesh_ops` は `NEEDS_USER_CHOICE`（選択肢・できること・実行場所・license・上限・費用・利用可否）を返す。AIはユーザーに聞き、`brain_mesh_backend(action='select', operation, backend)` で保存する。自動選択・黙った fallback はしない。
- cgal = 別プロセスの cgal-mcp（CGAL Master MCP 1.0.0）を `cadmcp_brain/studio/cgal_link.py` が stdio JSON-RPC で操作（`cgal_artifact_import`→`cgal_plan`→`cgal_execute`→`cgal_job_status` poll→`cgal_artifact_export`）。登録は `CADMCP_CGAL_MCP_CONFIG` か `~/.claude.json` の `cgal-mcp`。`CADMCP_CGAL_DISABLE=1` で不在扱い、`CADMCP_CGAL_TIMEOUT_S`（既定 300 s、超過は cancel）。succeeded かつ validation passed の結果だけ使い、拒否は `REFUSED`（コード付き）で結果なし。
- 結果は新規ファイル `mouse/mesh_ops/<mo_id>/result.stl`。元ファイルは書かない（実行後に sha256 再確認）。全 backend の結果を同じ studio 厳密距離で再測定（`independent_check_numpy`）して公平に比較する。
- fill_holes は max_hole_edges 以下の**全部の穴**を埋める（選択的な穴埋めは未提供）。

### OP1 実測（2026-10-11、work/e2e_cgal/real_check.json）

| 操作 | numpy | pymeshlab | cgal |
|---|---|---|---|
| Hausdorff 対称化 vs cable-fill（71k面） | 0.355 mm、18.9 s（p95 0.093） | 0.334 mm、0.6 s | REFUSED（unmet_precondition: 400面以下） |
| simplify 71200→35600、上限 0.1 mm | なし | 0.65 s、0.212 mm → NOT_READY（gate） | REFUSED（SELF_INTERSECTION、validator） |
| 25穴の穴埋め | 0.1 s、元面保持、元スキャン比 7.6e-6 mm | なし | 20.3 s（起動 2.2 s）、元面保持、元スキャン比 1e-13 mm（元の三角形と一致） |

結論: OP1 規模では cgal の距離・簡略化は Master の上限で使えない。穴埋めは cgal が正確（validator 付き）だが numpy の約 200 倍遅い。小さいメッシュ（<=400面）では cgal の Hausdorff は numpy と 2 % 以内で一致（tests/test_mesh_backend.py）。
