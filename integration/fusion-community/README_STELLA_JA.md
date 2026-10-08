# Stella 用 Fusion Community MCP

このフォルダは `faust-machines/fusion360-mcp-server` の固定ソースと、Stella用の制限付きMCP入口です。固定したコミットとライセンスは [PINNED_SOURCE.json](PINNED_SOURCE.json) に記録します。上流のGitディレクトリは持たないため、更新は新しいコミットを明示して再取得します。

`stella_fusion_mcp.py` は上流の `execute_code`、`delete_all`、`delete_parameter`、`set_design_type`、CAM操作、汎用 `export` を公開しません。`inspection` は読取・寸法・干渉・画像確認だけ、`modeling` はそれに名前付きのSketch、Feature、Parameter、Assembly、明示的なSTEP/STL出力を加えます。FusionのネイティブF3D保存はユーザーがFusion上で行います。STEPはFusion APIがComponentだけを受けるため、対象ボディだけを含むComponentから出力します。モデル操作は既定で拒否され、起動時の `--allow-document` または `STELLA_FUSION_ALLOWED_DOCUMENTS` のJSON配列で明示した現在文書名だけを許可します。

## 初回準備

1. このフォルダで一度だけ、固定lockfileから環境を作ります。

   ```powershell
   uv sync --frozen --no-dev
   ```

2. 既存のFusion360MCPアドインがある場合は、同時実行を避けるためFusionの「Scripts and Add-Ins」で停止します。アドインの起動と `inspection` プロファイルの読取確認は、現在開いている文書を変更しません。モデル操作は専用の新規テスト文書から開始します。

3. Fusionで `Shift+S` → **Add-Ins** → 「My Add-Ins」横の緑の `+` を選び、次のファイルを登録します。

   ```text
   E:\aiwork\Stella_CAD_SYSTEM\integration\fusion-community\addon\Fusion360MCP.py
   ```

   Fusionは任意場所にある自己完結したアドインを登録できるため、`%APPDATA%` へコピーする必要はありません。この段階では環境変数 `FUSION_MCP_HOST` を設定しません。既定の `localhost:9876` のままにします。LAN公開は認証がないため、Stellaでは使いません。

4. 一覧の **Fusion360MCP** を選び **Run** を実行します。Run on Startupを有効にする必要はありません。

5. MCPクライアントは次を起動します。Codex設定の変更はプロジェクト統合担当だけが行います。

   ```powershell
   E:\aiwork\Stella_CAD_SYSTEM\integration\fusion-community\.venv\Scripts\python.exe `
     E:\aiwork\Stella_CAD_SYSTEM\integration\fusion-community\stella_fusion_mcp.py `
     --profile modeling `
     --allow-document STELLA_FUSION_COMMUNITY_SANDBOX
   ```

## 検証

Fusionを開かずにMCPのtool listと禁止ツールの非公開を確認できます。

```powershell
E:\aiwork\Stella_CAD_SYSTEM\integration\fusion-community\.venv\Scripts\python.exe `
  E:\aiwork\Stella_CAD_SYSTEM\integration\fusion-community\probe_stella_wrapper.py --profile modeling
```

この確認は上流のmock transportを使います。Fusion API、アドイン、現在開いているCAD文書は検証しません。Fusionの実機接続後は、新規の専用空白文書で `ping`、`get_scene_info`、`render_view` を順に確認してからモデル操作を有効にします。保存前の新規文書でも検証できます。

実機では最初に、どの文書でもモデル操作が拒否されることを確認します。

```powershell
E:\aiwork\Stella_CAD_SYSTEM\integration\fusion-community\.venv\Scripts\python.exe `
  E:\aiwork\Stella_CAD_SYSTEM\integration\fusion-community\probe_live_wrapper.py guard
```

新規の専用空白文書 `STELLA_FUSION_COMMUNITY_SANDBOX` が現在アクティブなときだけ、次で履歴付き20 × 10 × 5 mmボックスを作り、質量特性と外接寸法を読み、STEPを `verification` に出力します。

```powershell
E:\aiwork\Stella_CAD_SYSTEM\integration\fusion-community\.venv\Scripts\python.exe `
  E:\aiwork\Stella_CAD_SYSTEM\integration\fusion-community\probe_live_wrapper.py sandbox `
  --document STELLA_FUSION_COMMUNITY_SANDBOX
```

## 実機検証記録（2026-10-03）

上記の新規・未保存の専用文書で実行した結果は [`verification/live-wrapper-sandbox.json`](verification/live-wrapper-sandbox.json) にあります。`create_box_parametric` が作成した履歴は Sketch 1件、Feature 1件、Timeline 2件でした。Fusion APIの内部単位はcmなので、実測 `size: [2.0, 1.0, 0.5]` と `volume: 1.0` はそれぞれ 20 × 10 × 5 mm と 1000 mm³です。スクリプトはこの値を数値としてassertし、同じ実行で [`stella-community-20x10x5mm.step`](verification/stella-community-20x10x5mm.step) を出力しました。

上流の `export_step` は `BRepBody` をSTEP APIに渡しており、現在のFusionでは失敗しました。Autodesk APIが受けるのは `Component` だけなので、ローカル修正では対象ボディだけのComponentだけを渡し、複数ボディまたは子Occurrenceを含む場合は出力を拒否します。これにより別部品を混ぜて出力しません。
