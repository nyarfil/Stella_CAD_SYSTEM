# cadMCP 一式 — ここから開始

まとめ日：2026-09-17（日本時間）  
利用する本体：**cadMCP Design Studio 0.3.1 / Cursor対応版**

## このZIPの役割

この会話で作成し、今回実体を取得できた配布物を、一つのフォルダに整理した保存・導入用パッケージです。
新しいエンジン版への更新ではなく、**最新版の本体は元ZIPから変更せず展開**しています。
旧版を順番にインストールしたり、旧版のPythonファイルを最新版へ上書きしたりする必要はありません。

**通常使うのは `01_CURRENT` だけです。** このフォルダをCursorで開いてください。
`04_ARCHIVE`は履歴保管用です。旧版と新版のSkill・Rulesを同時に有効化しないでください。

## 収録フォルダ

| フォルダ／ファイル | 内容 |
|---|---|
| `01_CURRENT/` | Cursor対応0.3.1のソース、MCP、Req2CAD連携、CAD生成・検査、役割別レビュー、Cursor/Codex接続、導入スクリプト、wheel、テスト・既存検証ログ |
| `02_DOCUMENTS/` | 読む順番、Cursorへ渡す開始指示、当初の要件・アーキテクチャ資料 |
| `03_CAD_EVIDENCE/` | 実例CADのSTEP/STL、PNG/SVG、レシピ、測定記録、HTMLと、個別配布したSTEP/PNG |
| `04_ARCHIVE/` | 取得できた元ZIP5個と、過去版・個別配布の説明資料 |
| `BUNDLE_MANIFEST.json` | 収録ファイルごとのサイズとSHA-256 |
| `SOURCE_INVENTORY.json` | 今回集約した元ファイルと収録先の対応 |
| `SHA256SUMS.txt` | 展開内容のハッシュ一覧 |
| `verify_bundle.py` | Python標準ライブラリだけで行う、読み取り専用の収録内容照合 |
| `PACKAGING_REPORT_JA.md` | 今回の梱包確認と、含まれないもの |

## Cursorで最初に使う

ZIPをすべて展開した後、展開先のトップフォルダでPowerShellを開きます。
ZIPのプレビュー内から直接起動しないでください。既存プロジェクトへ丸ごと上書きしないでください。

```powershell
cd .\01_CURRENT
.\setup_cursor.cmd --geometry
```

その後、**`01_CURRENT`フォルダそのものをCursorで開き**、MCPを有効化・再読み込みします。
Agentチャットで `/cad-check` を実行します。項目が出なければ、
[`02_DOCUMENTS/CURSOR_START_PROMPT_JA.md`](02_DOCUMENTS/CURSOR_START_PROMPT_JA.md)の開始指示を貼り付けてください。
詳細は [`01_CURRENT/CURSOR_GUIDE_JA.md`](01_CURRENT/CURSOR_GUIDE_JA.md) を参照してください。

既存のCursorプロジェクトと既存の知識ベースを使う場合は、`01_CURRENT`で次を実行します。
以下のパスは利用者の実在するフォルダへ置き換えてください。

```powershell
.\setup_cursor.cmd --geometry `
  --project "C:\work\your-cadMCP" `
  --workspace "C:\work\cad-data\workspace"
```

同名のRule等に変更があれば差分を確認します。`--replace-managed`を考えなしに追加しないでください。
既存CADのソース、基板、シェル、認証情報をこのZIPで置き換えないでください。

## Req2CAD全件・埋め込みモデルの準備

**Req2CAD全件CSV、DeepCAD全件原本、Qwenの実重みは、このZIPに同梱されていません。**
ダウンロード・UID対応付け・索引構築のコードと手順を同梱しています。
Pythonの依存ライブラリ、Cursorアプリ、Cursor/Codex CLI、認証情報も含めていません。
したがって「完全オフラインで全件がすぐ使えるパッケージ」ではありません。

`01_CURRENT`で実行します。

```powershell
.\setup_req2cad.cmd --download-deepcad --reference-only
```

既存workspaceを使っている場合は、ここでも同じ`--workspace`を指定してください。
セットアップ終了後は、生成された `integration/generated/cursor.mcp.json` の
**`mcpServers.cadmcp-design-brain`項目を、利用するプロジェクトの`.cursor/mcp.json`へ反映**します。
これは生成ファイルを作る処理であり、先に設定したCursor側の項目へ必ず自動反映されるという意味ではありません。
既存の他サーバーと独自envを残し、`CADMCP_REQ2CAD_ROOT`が本番データ保存先を指すことを確認してください。
全体の上書きはしないでください。MCP再読み込み後、`brain_fs_status`で件数と索引状態を確認します。

構造参照用の元寸法は、実マウス部品にそのまま流用しません。
デモの4件・制御用ベクトルを全件の知識ベースやQwen実推論の代わりにしないでください。

## まずCAD成果物を見る

環境をインストールせず資料を見る場合は、
[`03_CAD_EVIDENCE/real-reference-output/EVIDENCE_REVIEW.html`](03_CAD_EVIDENCE/real-reference-output/EVIDENCE_REVIEW.html)
をブラウザーで開きます。STEP等は同じフォルダと各部品フォルダにあります。

デモを再実行する場合は、`01_CURRENT`で以下を実行します。CAD依存の導入が必要です。

```powershell
.\.venv\Scripts\python.exe scripts\demo_real_references.py --workspace .\demo-workspace
```

デモ用workspaceと本番workspaceを混ぜないでください。

## 検証記録の読み方

`01_CURRENT/TEST_REPORT_JA.md`と`01_CURRENT/verification/`は、元の0.3.1作成時の検証記録です。
今回の梱包でアプリの全テスト、実Cursor/Windowsでの接続、全件検索、実印刷を新たに実施したわけではありません。
`PACKAGING_REPORT_JA.md`の梱包確認と混同しないでください。

全件Req2CAD＋Qwenの検索品質、実モデルの自由文設計・5役討論、実マウス完成までの受入試験は未完了です。
このZIP化で機能追加や未検証項目の解消をしたという意味ではありません。

## 取得できなかった過去版

会話で案内されていた`cadmcp-function-structure-v0.2.1.zip`は、今回ZIP実体を確認できませんでした。
その版は取得できたREADMEと設計手順だけを `04_ARCHIVE/documents/v0.2.1-documents-only/` に収録しました。
存在しない旧版ZIPを再作成したり、別版をその名前で代用したりしていません。
最新版0.3.1本体は元ZIPからすべて展開して収録しています。

## 展開内容の照合（任意）

展開先のトップフォルダで実行します。アプリの依存は必要ありません。

```powershell
python .\verify_bundle.py
```

一覧にあるファイルの存在・サイズ・SHA-256を照合するだけで、インストール、モデル呼び出し、
既存CADの編集は行いません。導入後に増える`.venv`やworkspaceは一覧の照合対象外です。
意図的にソースを編集した場合は、そのファイルが不一致になります。
