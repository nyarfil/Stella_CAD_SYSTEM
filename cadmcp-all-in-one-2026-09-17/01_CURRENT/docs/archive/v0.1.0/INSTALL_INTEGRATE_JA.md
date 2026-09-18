# 導入・既存cadMCPへの統合

対象: v0.1.0。手元のcadMCPソースを変更したものではなく、これから接続するための実装と手順です。

## 1. インストール

ZIPをたとえば`C:\cadmcp-design-brain`へ展開します。フォルダ名に空白・日本語を含む設定生成とファイル処理はLinuxで試験しています。Windows自体の動作確認は未実施です。

PowerShellで展開先を開きます。

```powershell
.\setup.cmd --geometry
```

Python launcherがない場合は`python`を使います。複数Pythonがある場合は使用する版を指定して、直接次を実行できます。

```powershell
py -3.13 scripts\bootstrap.py --geometry
```

`--geometry`なしでは軽量構成になります。形状測定の試験はskipとなり、カーネルが必要な実測はunknownです。skipを「全機能確認済み」と解釈しないでください。

インストーラーは既存のAgentCAD/Fusion、環境変数、ユーザーのグローバルMCP設定を書き換えません。依存は`.venv`へインストールします。直接依存のバージョンは固定されていますが、全推移依存をOS横断でhash-lockした環境ではありません。

## 2. Cursorへ追加

生成される`integration/generated/cursor.mcp.json`は、絶対パスと`type: stdio`を含みます。既存プロジェクトの`.cursor/mcp.json`では、**ファイル全体を置換せず**、`mcpServers.cadmcp-design-brain`だけを追加します。Cursorの設定形式は公式文書[S6]を確認しています。

明示した既存プロジェクトへ設定をマージする場合は次を使います。パスは実在する自分のプロジェクトに置き換えます。

```powershell
.\setup.cmd --geometry --cursor-project "C:\work\your-cadMCP"
```

このオプションを指定した場合のみ対象の`.cursor/mcp.json`を書きます。他のMCP項目・トップレベル設定を残し、元ファイルのバックアップを同じディレクトリへ作ります。コメント付きJSON等を解釈できない場合は、上書きせず停止します。Skill/Rule/AGENTSの自動上書きはしません。

同梱`.cursor/rules/cadmcp-design-brain.mdc`を対象プロジェクトの同名相対位置へ追加してください。同名が存在したら差分を確認してマージします。モデルには`.agents/skills/cadmcp-design-brain/SKILL.md`も読ませてください。配置先の機能差がある場合でも、ファイルを明示的に読む方法で利用できます。

CursorでMCPを再読込みし、`brain_doctor`と`brain_schema`が呼べるか確認します。ツール名にホスト側の接頭辞が付く場合は、表示される名前をそのまま使います。起動できないときはMCPログと、次の単独診断を照合します。

```powershell
.\.venv\Scripts\python.exe -m cadmcp_brain --workspace .\workspace doctor
```

`serve`をターミナルで直接起動して文字が出ないのは、JSON-RPCの入力を待つ仕様です。通常はCursorが子プロセスとして起動します。

## 3. Codexへ追加

`integration/generated/codex.config.toml`のセクションを、既存の`config.toml`に重複しないよう追加します。生成ファイルで全体を置換しないでください。起動・ツールのタイムアウトは20秒／120秒の設定値です。これは作業完了の所要時間予測ではなく接続の上限設定です。

公式文書[S7]では`[mcp_servers.<name>]`、`command`、`args`、`env`形式が定義されています。ユーザー用設定とプロジェクト用設定のどちらを使うかは、既存の運用に合わせます。このパッケージはそれらを自動変更しません。

同梱Skillは、配置による自動検出に依存せず、次の指示で明示的に読み込ませることもできます。

## 4. Cursor / Codexへ最初に渡す指示

```text
このフォルダのREADME_JA.md、INSTALL_INTEGRATE_JA.md、
.agents/skills/cadmcp-design-brain/SKILL.mdを読んでください。

まずbrain_doctorとbrain_schemaを実際に呼び、接続を確認してください。
既存のcadMCP・AgentCAD・Fusionの設定やソースをいきなり置き換えないでください。
自然言語の解釈と構造提案はあなたが担当し、出典・制約・依存関係・検証状態は
このMCPに記録してください。サンプル寸法を実物の寸法として使わないでください。

私の新しい設計依頼では、原文→Brief→2〜4構造案→選択→Plan→既存CAD→STEP測定
の順で進めてください。試験がunknownなら合格と言わないでください。
寸法等がCADから測定できる場合は、同じ質問を私に繰り返さず、利用可能な実データから測ってください。
```

日常の設計依頼例:

```text
このサイドボタンを、押しやすく壊れにくい構造へ変更してください。
外形とPCBは動かさず、実際のスイッチ押下方向を先に調べてください。
CADを変更する前に、Design Brainに要求・構造案・計画を登録してください。
```

これは追加指示の例です。ユーザーからその制約が与えられていない案件で、外形やPCBを勝手に固定条件として追加しないでください。

## 5. 既存cadMCPへコードとして組み込む

Python製なら`cadmcp_brain.engine.Brain`と`cadmcp_brain.api.Tools`が入口です。既存サーバーがMCP SDKを使っている場合は、`Tools.list()`のスキーマと`Tools.call(name,arguments)`を既存のtoolルーティングへ追加できます。`protocol.py`はスタンドアロン時の通信部分なので、無理に移植する必要はありません。

```python
from cadmcp_brain.engine import Brain
from cadmcp_brain.api import Tools

brain = Brain(r"C:\work\cadmcp-workspace")
tools = Tools(brain)
# tools.list(): name / description / inputSchema / annotations
# tools.call(actual_tool_name, validated_arguments): result dict
# BrainErrorとPydantic ValidationErrorを既存MCPのtool errorへ変換する。
```

既存サーバーがTypeScript等の場合はまず独立MCPとして並べるか、実装済みのstdioクライアントで接続します。このリリースはユーザー専用のTypeScriptアダプターを実装したものではありません。

**書込みを強制的に制御する場合**は、既存cadMCPの変更入口で、現在の`revision`と契約digestを確認し、対象プロジェクト／対象部品／Planステップ／許可する操作を対応付けてから実行します。既存CAD側の排他・取引・Undo管理も必要です。本体の独立MCPや汎用ブリッジだけでは、外部バックエンドの一連の操作を原子的に保証できません。

統合を担当するモデルには`integration/INTEGRATE_EXISTING_PROMPT_JA.md`を渡してください。既存の登録関数・API・プロジェクトIDを実際のソースから調べるよう指示してあります。

## 6. 任意: AgentCADの直接ブリッジ

初期状態は無効です。通常はCursor/Codexが既存CAD MCPを呼ぶ方式で使います。直接ブリッジは、所有者が`CADMCP_AGENTCAD_URL`をローカルAgentCADのoriginに、`CADMCP_AGENTCAD_ALLOWED_TOOLS`を許可した**実在するツール名のJSON配列**に設定した場合だけ呼べます。外部URL、redirect、自動再試行は拒否します。

`brain_backend_probe`で`GET /api/tools`の実際のレジストリを取得します。必須フィールド・引数型が変わっていたら、推測せず停止します。アダプターは`POST /api/tools/{name}`へ引数オブジェクトを渡し、HTTP 200でも本文の`error`／`ok:false`を確認します。[S4]

最初は`brain_backend_call(...,dry_run=true)`です。これはスキーマ確認であり、CAD書込みをしません。書込みを許可する場合は`dry_run=false`と一意な`call_id`、現在の契約digest／revisionが必要です。呼出しIDは全workspaceで一意にしてください。

同じcall_idは1回しか送信を試みません。タイムアウトやクラッシュは`outcome_unknown`となり、同じIDを再度呼んでも送信しません。ただし**別IDを作れば外部操作が重複し得ます**。バックエンドの実状態・履歴を確認せず別IDで再送しないでください。exactly-once保証ではありません。

このアダプターは「正しいスキーマの許可済みツール」を呼ぶものです。「CAD引数が設計意図を意味的に正しく実現する」「別プロジェクトの破壊を自動検知する」という保証ではありません。特に任意スクリプトを受け付けるツールの許可は、実質的なコード実行権限を与えます。既存CAD側の権限／サンドボックスが別途必要です。

ブリッジ試験はAgentCAD公開仕様を模したローカルHTTPテストサーバーで実施しました。ユーザーが使っているAgentCAD本体との接続成功は未確認です。

## 7. 測定と実物設計への移行

`workspace/incoming/`へ信頼できるSTEPを置き、workspaceからの相対パスで取り込みます。`purpose=reference`は実カーネルでbbox寸法を測り、寸法の根拠IDを返します。参照を変更したら構造・Planは無効になります。測定根拠はファイルハッシュと結び付きます。

生成品は`purpose=output`で現在の契約digestに紐付けます。A-frame等のサンプルIDは、実案件ではPlanに定めた部品ID／artifact IDへ置き換えます。各部品を同一アセンブリ座標系で出力してください。

本体が自動計測しない形状条件（壁厚、穴の寸法・位置、変形全域の干渉等）は`external_geometry`へ登録します。これらはunknownとして残り、単なるbbox検査で代用しません。外部計測器・試験票を正式に受け付ける拡張では、将来の追加コードで実行器、出典、原本hash、対象契約、結果の型を検証する必要があります。現リリースはこの外部合格証跡の取込APIを持ちません。

## 8. 戻す・復旧する

Cursor設定だけを戻す場合は、その時に生成されたバックアップとの差分を確認し、追加した`cadmcp-design-brain`項目だけを外します。後から追加された他のMCP項目があれば、古いバックアップの丸ごと復元で消さないようにしてください。

`workspace`は設計状態です。バックアップはMCPを停止してからディレクトリ全体をコピーしてください。動いているSQLiteの本体ファイルだけをコピーする運用はしません。本体を更新する際も旧workspaceを残し、版違いのスキーマを無理に読み替えないでください。v0.1.0は汎用DBマイグレーション機構を持ちません。

資料IDのURLは`docs/UPSTREAM_AUDIT_JA.md`に記載しています。
