> HISTORICAL v0.2.0 — この文書の試験件数・実装状態は0.3.0の検証結果ではありません。

# 導入・統合 — v0.2.0 Req2CAD

## 1. 新規フォルダと動作試験

ZIPを新しい場所へ展開します。Python 3.11以上。確認環境はLinux / Python 3.13です。PowerShellで:

```powershell
.\setup.cmd --geometry
```

この処理は `.venv` を作り、通常依存とCADカーネル・テスト依存を導入し、ローカル試験と設定生成を行います。ネットワーク・依存取得・Windowsそのものは作成環境で再現していません。インストールが失敗した場合は途中で停止します。

## 2. 全件注釈・CAD原本・実埋め込みの導入

```powershell
.\setup_req2cad.cmd --download-deepcad --reference-only
```

実行する処理:

1. `geometry,semantic` の追加依存を導入。
2. Req2CAD.csvを全件取得し、確認済みSHA-256と一致するか検査して取り込み。
3. DeepCADの元 `data.tar` を取得。展開せず、元JSONのUIDとアーカイブ内位置を登録。
4. Qwen3-Embedding-4Bの具体的リビジョンを取得して記録。safetensorsを利用し、remote Pythonは許可しない。
5. ユニークな機能語ごとに埋め込みを計算。再開可能なチェックポイントとハッシュ付き索引を作成。
6. モデル、索引、UID対応の実状態を表示し、設定を生成。

`--reference-only` は元形状の単位を推測しないための設定です。CADカーネル用の表示座標と実物寸法を区別します。正規化形状やトポロジーの比較には使えますが、その座標をマウスの寸法へそのままコピーしません。

CUDAが有効なPyTorchなら自動的にCUDAを選びます。そうでなければCPUです。CPUで動いたことをGPUで動いたと表示しません。明示指定は `--device cuda` / `--device cpu`。モデルの実ロードと推論はこの配布作成環境では未検証です。独立したLLM APIキーは不要です。

データが既にある場合:

```powershell
.\setup_req2cad.cmd --csv "D:\CADdata\Req2CAD.csv" --cad-path "D:\CADdata\data.tar" --reference-only
```

`cad_json` フォルダの場合は `--cad-kind deepcad_json`、対応UIDのSTEPフォルダは `--cad-kind step` を加えます。物理単位の根拠がある場合のみ `--reference-only` の代わりに `--scale-to-mm` と `--unit-basis` を指定します。

途中失敗後は、同じコマンドで再開します。同一CSVの再取り込みでは登録済みCADを消しません。違うCSVへの更新は新しい世代となり、形状参照・埋め込みの再確認が必要です。クラッシュで `.write.lock` が残った場合、実プロセスが停止していることを確認してから削除してください。動作中に強制削除しません。

## 3. 設定

通常root:
`<展開先>/workspace/knowledge/req2cad`

生成ファイル:
`integration/generated/cursor.mcp.json`
`integration/generated/codex.config.toml`

Req2CAD導入スクリプトは生成ファイルのみ変更します。既存クライアント設定への自動マージはしません。他のサーバーを残して `cadmcp-design-brain` の項目だけ更新してください。

生成される追加環境変数:

```text
CADMCP_REQ2CAD_ROOT=<実際の絶対パス>
CADMCP_REQUIRE_CAD_REFERENCES=1
```

`CADMCP_REQUIRE_CAD_REFERENCES=1` は、このBrain内部で、構造案に測定済みCAD参照があり、それが機構へ接続されていることを必須にします。参照が1件あることは、すべての機能や強度が証明されたことではありません。無関係な参照を加えて形式的に通す行為は禁止です。

環境変数を設定しない互換運用、または導入時の `--allow-ungrounded-drafts` は探索的な未根拠案を許可します。通常の参照重視運用では使いません。

## 4. 利用確認

```powershell
.\req2cad.cmd status
.\req2cad.cmd search "support rotating shaft" "reduce friction" --require-cad
```

確認すべき項目は `cases`、`function_labeled_cases`、`cad_assets_linked`、`semantic_ready`、`breps_measured` です。注釈件数とCAD実体件数とB-rep変換済み件数を混同しません。`full_original_sha_match=true` は元CSVの同一性のみで、全CADの再構成成功を示しません。

モデル側は `brain_fs_status` → `brain_fs_search` → `brain_fs_materialize` → `brain_fs_evidence` を使います。検索は既定で意味検索です。エンコーダーや索引がない場合はエラーとなり、字句検索へ黙って切り替わりません。

## 5. 全件事前変換と試験片

すべてを事前変換する必要はありません。必要な候補だけ実体化する方が、未使用CADに対する処理を避けられます。全件に対して実行する場合:

```powershell
.\req2cad.cmd materialize-all --timeout 60
```

未測定・失敗したUIDを順次処理し、`bulk-build.jsonl` に実際の成功・失敗を記録します。未対応形状を単純形状へ置換しません。`--limit` で処理対象件数を制限できます。時間指定は1件あたりの処理上限です。

外部データなしで、作者作成の試験片だけを再実行する場合:

```powershell
.\.venv\Scripts\python.exe scripts\demo_req2cad.py
```

これは意味検索モデルや元Req2CADを使わない、明示的な字句検索＋幾何処理の試験です。本番KBとは違う `workspace/_test_req2cad` に書きます。配布済みの実行結果 `examples/req2cad_fixture/` の古い絶対パスをMCP設定へコピーしないでください。

## 6. 既存cadMCPへの接続

Pythonでは `cadmcp_brain.api.Tools` の `list()` と `call(name, arguments)` が既存と共通の入口です。新しい7個のツールも同じレジストリに入っています。別MCPとして追加しても、他のCAD MCPへの直接呼び出しまで禁止することはできません。強制経路を作るには、既存CADの書込入口で現行の契約ハッシュ、対象部品、操作、排他を検査します。

実際のユーザーリポジトリはこの作業では変更していません。既存のAgentCAD/FusionのAPIを推測して書き換えることもしません。元のAgentCADブリッジは引き続き任意・既定無効です。

## 7. 更新・持ち運び

元v0.1 workspaceを保存して、新workspaceで開始してください。Req2CADのSQLiteも世代管理があり、別CSVや単位扱いへの更新は古い根拠を無効にします。モデル設定とCAD登録には絶対パスがあるため、PCや配置を変えたら新しいパスで登録し直します。
