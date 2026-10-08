# MVP 0.1.0の確認結果

確認日: 2026-10-03。既存案件を使わず、一時workspaceと一時インストール先で確認した。

## 接続・動作

実行コマンド（StellaCADの既存Python環境）:

```powershell
python -m unittest discover -s integration/mouse-library/tests -v
```

結果: **10件成功、失敗0件**。

1. 標準入出力で初期化・5ツール列挙・12知識項目・出典ハッシュを取得。
2. 日本語「ホイールの構造」と英語「wheel encoder」で関連知識を取得。
3. 設計計画が未確認測定、未確認CAD能力、測定テンプレートと6段階の手順を保持。
4. 独立橋のFunctionBrief・Recipe設計根拠・構造案設計根拠を現行Stellaモデルで検証。
5. 15リソース、ガイドプロンプト、同梱測定レポート2件を取得。
6. 不正なID、件数、未知の要求フィールド、任意ファイルURIを拒否。
7. 2025-06-18のMCP版を交渉し、知識を取得。
8. 新規一時workspaceのStella MCPプロセスでネイティブ6ツールを列挙・呼出。橋の現行モデル検証と要求スキーマの版情報を確認。
9. パッケージを別の一時フォルダーへコピーし、Stellaソースに依存せず知識・測定資料を取得。
10. 有線条件でも電源・ケーブル保持の知識を計画へ含める。G305実例は必須機能にせず参照ガイダンスへ引き継ぐ。

初回確認で見つかった測定テンプレートのハッシュ扱いと読み取り専用注釈の不足は修正後に再確認した。出典メタデータの上書き、ネイティブ版情報、公開測定URIなどのレビュー指摘も修正した。

## 配布用wheel

```sh
python -m pip wheel --no-deps --no-build-isolation --wheel-dir artifacts .
python scripts/check_package.py --wheel artifacts/mouse_library_mcp-0.1.0-py3-none-any.whl --report artifacts/package-verification.json
```

結果: **成功**。ネットワークのパッケージ索引を使わず、一時フォルダーへwheelをインストールした。Pythonの隔離モードでインストール先だけを追加し、MCP初期化・12知識項目・2測定レポートの取得を確認した。

wheel SHA-256: `7fab089bec4bf54b1c7381b21b18e9b74c5ab8c3da765936b705821193a2ec74`。同梱PythonとデータJSONの4ファイルについて、wheel内と最終ソースのハッシュ一致も確認する。

## 確認範囲

これはWindows上のPython 3.13と現行Stellaソースでの確認。別OS・すべてのMCPホスト・既に起動中のCodex工具一覧への追加は未確認。プロジェクト設定は次のMCP起動から適用される。

本確認はソフトウェアの接続・返却契約・配布内容に関するもの。独立したマウスCADの完成、G305個体との寸法適合、クリック復帰、光学追従、印刷や耐久の成立は証明していない。
