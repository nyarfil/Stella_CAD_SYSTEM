# ClassCAD 接続

`@classcad/mcp@0.2.0` を `package-lock.json` で固定しています。`npm ci --ignore-scripts` で再配置できます。この PC では Node 24.3.0 と既存の ClassCAD 認証で接続・生成・STEP 出力が成功しました。

Codex のプロジェクト MCP 設定は WASM エンジンを選び、自動ブラウザ起動を抑制しています。初めて使う別環境ではアカウント認証が必要です。認証情報や非公開セッション URL は共有しません。

## 実操作

1. `list_tools` で 17 ツールの接続を確認する。
2. `use_session` で案件専用の WASM セッションを作る。
3. `docs` / `describe_method` から実際のメソッド契約を取得する。
4. `run_script` で ClassCAD API を呼ぶ。これは ClassCAD セッションの操作であり、Fusion 上の任意 Python 実行ではありません。
5. `inspect` / `snapshot` で確認し、`save` で新しい STEP ファイルへ出力する。
6. Stella に STEP を登録し、要求寸法と形状を独立して検査する。

`clear` / `restore` は現在の ClassCAD セッションに作用します。既存案件のセッションを流用せず、必ず対象を確認します。MCP の MIT ライセンスと CAD エンジンの利用条件は別です。

## 検証ファイル

- `probe.mjs`: stdio MCP の接続と 20 × 10 × 5 mm の試験モデル生成。
- `verify_stella.py`: 新規の隔離 workspace に STEP を登録し、保持・寸法・体積・要求形状を検査。
- `verify_fusion.py`: 公式 Fusion MCP で新規文書にインポートし、内部 cm を mm に換算して測定。元文書を再アクティブ化し、保存は行わない。

結果は `verification/` に置き、Git に登録しません。全体の手順と検証範囲は [統合文書](../../docs/CLASSCAD_FUSION_INTEGRATION_JA.md) を参照してください。
