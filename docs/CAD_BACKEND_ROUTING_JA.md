# 操作能力に基づくCADバックエンド選択

StellaCADに `brain_cad_route` と案件用CLIを追加しました。必要な操作、現在使える工具、費用条件から一つの実行経路を選びます。MCP内部から別MCPを呼ぶ構成ではなく、Codex等のホストが返された手順を実行します。

## 選択条件

- 既存の明示選択を優先。選択CADが必要操作に対応しなければ理由を返し、別CADには切り替えません。
- 自動モードは案件内の `.stella/cad-routing.json` に許可CADを保存します。既存案件への一括適用はしません。
- 単純部品ではネイティブの型付きCadQuery Recipeを優先します。
- `surface_loft` / `sweep` / `shell` / `spline_surface` / `editable_history` 等ではFreeCAD、Build123dの順に候補を評価します。これは設計環境の選好であり、形状品質のベンチマーク順位ではありません。
- 対応操作が全て観測され、installed / readyがtrue、費用がfreeまたはowned_perpetualの候補のみ選べます。未観測、サブスク、費用不明は対象外。
- ClassCAD・Fusionも候補ですが、初期許可一覧には含めません。利用条件と工具能力を確認して明示的に追加します。
- ネイティブ `loft` は平行XY多角形断面に限定。CadQueryライブラリ全体の能力をRecipeの対応能力に加算しません。
- 未対応検査（弾性、疲労等）は選択を止めます。別エンジンに変えても検査成立とはみなしません。
- 外部STEPの共通検査は有効性・ソリッド数・外接寸法・静的距離・干渉体積に限定します。Recipe専用の円筒径・移動サンプル・生成前後同等性を外部経路で保証するとは扱いません。返された `external_check_mapping` で固定Planの検査に対応付けます。共通検査カーネルが読込不能なら生成経路の選択も止めます。

## 操作

Stellaルートから、本体のPython環境で呼びます。以下の `<案件>` は対象案件ディレクトリへ置き換えます。

```powershell
& .\cadmcp-all-in-one-2026-09-17\01_CURRENT\.venv\Scripts\python.exe integration/freecad/route_backend.py auto --project "<案件>" --allow cadquery freecad build123d
& .\cadmcp-all-in-one-2026-09-17\01_CURRENT\.venv\Scripts\python.exe integration/freecad/route_backend.py plan --project "<案件>" --operations box cylinder difference --checks bbox static_clearance
```

`plan` は読取専用。`--activate` を付けると一つの選択と案件内MCP有効フラグを保存します。CAD起動・形状生成は続いて既存ホスト工具で実行します。設定変更後は案件チャットで工具を再読込してください。既存チャットの工具は直ちに切り替わりません。

曲面案件は `--operations surface_loft shell --probes <診断JSON> --kit <案件FreeCAD環境>` のように指定します。FreeCADの実行環境は案件ごとのものを使います。OP1用kitを他案件へそのまま適用しません。

診断JSONはBackendProbeの配列です。例の値をそのまま実機診断として使用しないでください。

```json
[
  {
    "backend": "freecad",
    "installed": true,
    "ready": true,
    "operations": ["surface_loft", "shell"],
    "cost": "free",
    "evidence": "対象環境で実行した操作テストの記録パス、入力ハッシュ、成功した工具名"
  }
]
```

外部診断はホストから渡す観測記録です。`brain_cad_route`自身は他MCPへの接続・操作試験を行いません。CLIはFreeCADについて追加でkit、PID、profile、RPCの一致を確認します。接続成功だけでshell操作の成功を申告しないでください。

明示的に選び直す際は従来の `select_backend.py select` を使います。自動選択した状態にはdecision全体とSHA256を保存し、保存直前に案件選択・自動方針の変更がないか再確認します。

## CAD生成と検査

`dispatch.workflow` に従いホストが一つの生成・編集経路を実行します。

| 選択 | 実行経路 | 編集正本 |
|---|---|---|
| CadQuery | `brain_studio_build` 型付きRecipe | Recipe・Studio成果物 |
| Build123d | 既存cadgen CLI、専用runtime | パラメトリックPythonソース |
| FreeCAD | 既存の案件限定MCP / Python API | FCStd |
| ClassCAD | 既存MCPの独立セッション | セッションと生成情報 |
| Fusion | community MCPの案件許可文書 | 許可文書・明示保存成果物 |

Build123dをネイティブRecipe workerとして追加したわけではありません。既存cadgen経路を選択先に登録しました。該当工具がホストにない場合はreadyにしません。

外部STEPは、現在の要求・検査条件を `brain_export` で固定し、workspace内に配置、`brain_import_step(purpose="output", contract_digest=...)` で登録して `brain_verify` に渡します。座標、単位、保護部品、閾値を維持します。STEPは元CADの編集履歴を保持しないため、FCStdやPythonソースも残します。外部操作の成功と共通検査の合格は別に記録します。

これはバックエンドの選択・ホスト実行への引渡し機能です。任意スキャンから完成マウスを作る機能や、実曲面・肉厚・クリックの品質認定を追加したものではありません。

## 実装時の検証（2026-10-04）

本体のルーティング、隔離stdio呼出し、MCP通信、公開schema一致、状態保護、Fusion引渡し、マウス入力、既存planningを含む対象試験は91件成功・Windows symlink制約で1件skip。案件選択・自動方針・設定保護・改変decision・方針競合・FreeCAD停止を含むCLI試験は25件成功・同制約で1件skip。合計116件成功、2件skip。schema --checkは差分0。

ソース上のMCP工具は58件です。稼働中のMCPプロセスへ追加工具が既に読み込まれたとは扱いません。新しい案件チャットで `brain_cad_route` の存在を確認してください。全試験一括回帰や各外部CADでの実マウス曲面生成は、この検証には含みません。
