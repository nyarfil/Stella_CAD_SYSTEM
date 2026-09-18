# Cursor対応 — cadMCP Design Studio 0.3.1

この版は0.3.0への追加更新です。Req2CADの検索・CAD復元・機能別構造案・CADレシピ・検証器は維持し、Cursorの接続と実行経路を追加しています。

## 1. まず使う方法：Cursor IDEのAgent + MCP

**Codex CLIは不要です。** CursorのAgentモードで、選択したモデルが構造を考え、MCPが実例検索・CAD生成・検査を実行します。本体から別の生成APIを呼びません。Req2CAD意味検索用のローカル埋め込みモデルは別の役割です。

ZIPは旧版と別フォルダへ展開してください。そのフォルダでPowerShellを開きます。

```powershell
.\setup_cursor.cmd --geometry
```

このフォルダをCursorで開いてMCPを再読込みし、Agentチャットで `/cad-check` を実行してください。スラッシュ項目が出ない版では、次を貼り付ければ同じ手順を指示できます。

```text
.cursor/skills/cadmcp-cursor/SKILL.mdを読んでください。
brain_doctor、brain_fs_status、brain_studio_schema(name="FunctionBrief")を実際に呼んでください。
MCPの接続成功、CADカーネル、Req2CADの注釈件数・CAD対応数・意味検索索引を別々に報告してください。
未導入のデータをデモや単語検索で代替しないでください。
```

接続後は `/cad-design` に続けて要求を入力するか、通常のAgentチャットで設計を依頼します。既存の作成結果のレビューは `/cad-review` です。

```text
サイドボタンを、隣にある横向きのスイッチへ直接力が伝わる構造にしてください。
実際のPCB・スイッチ・シェルを先に調べ、指定した保護部品は変更しないでください。
Req2CADの実例CADから参考構造を検索し、実形状を見てから複数案を比較してください。
型付きレシピで試作モデルを作り、5役の初回レビューと相互反証を行ってください。
未検証事項は残し、CAD正本へ自動反映しないでください。
```

これは依頼例です。数値寸法・利き手・外形の変更許可などは、実案件の原文や実ファイルで確定します。

## 2. 既存のCursorプロジェクトへ追加

パッケージを展開したフォルダで、`--project`へ**実在する**既存プロジェクトを指定します。

```powershell
.\setup_cursor.cmd --geometry --project "C:\work\your-cadMCP"
```

既存のデータ保存先を使う場合は、明示的に指定します。

```powershell
.\setup_cursor.cmd --geometry --project "C:\work\your-cadMCP" --workspace "C:\work\cad-data\workspace"
```

すでに本版を環境へインストールしてある場合は、再インストールせず設定だけ追加できます。

```powershell
.\setup_cursor.cmd --no-install --project "C:\work\your-cadMCP"
```

任意のインストール済みPythonを使う場合は `--no-install --python "...\python.exe"` を指定します。`--dry-run`は設定差分の確認だけで、インストール・書込み・モデル実行を行いません。存在するPythonを指定してください。

### 追加・更新するファイル

- `.cursor/mcp.json` の `mcpServers.cadmcp-design-brain` 項目
- `.cursor/rules/cadmcp-design-brain.mdc`
- `.cursor/skills/cadmcp-cursor/SKILL.md` と参照手順
- `.cursor/agents/cadmcp-{requirements,mechanism,assembly,manufacturing,verification}.md`
- `.cursor/commands/cad-check.md`、`cad-design.md`、`cad-review.md`
- 管理対象とバックアップを記録する `.cursor/cadmcp-install*.json`

他のFusion/AgentCAD/MCP項目とトップレベル設定を保持します。既存の本MCPの追加env（保護するPCBのID等）も保持します。Cursorのグローバル設定・認証・選択モデルは変更しません。

同名のRule/Skill等にローカル変更があるときは、設定全体を自動上書きせず停止します。差分を確認し、本版で置き換える場合に限り `--replace-managed` を付けてください。変更前ファイルは同じ場所に `.backup-...` として残します。管理外のソースコードや他のMCPは対象外です。

JSONC、重複キー、不正JSON、リンク先への書込みは拒否します。複数ファイル更新中のOS停止まで原子的に保証するものではありません。`cadmcp-install-journal.json`とバックアップで更新範囲を確認できます。

### 設定したMCPの単独診断

Cursor画面で接続できないときは、パッケージのフォルダで次を実行します。

```powershell
.\.venv\Scripts\python.exe scripts\check_cursor_connection.py --project "C:\work\your-cadMCP"
```

対象プロジェクトの設定でstdioサーバーを起動し、33個のツールとdoctor/schemaを確認します。外部モデルは呼びません。新規workspaceは作成されるため、意図した保存先か確認してください。成功してもCursor GUIの接続確認とは別です。

## 3. Cursor内の5役レビュー

5種類の定義を `.cursor/agents/` へ配置します。`model: inherit` により親Agentのモデルを継承し、`readonly: true`、`is_background: false`を指定しています。[C3]

役割は要求、機構、組立、製造、検証です。親AgentはMCPから実際のreview packetを取得して渡し、初回結果が揃った後で具体的な相互指摘を2巡目へ渡します。MCPへの記録は親だけが行います。データのない架空のレビューや「賛成多数だから合格」は認めません。

**サブエージェント定義を置いたことと、実行されたことは別です。** インストール先のCursorがサブエージェント実行ツールを提供しない場合は、その旨を報告します。同一Agentによる順番のレビューを、独立した5コンテキストの実行と呼びません。別CLIの起動を無断で代替しません。

## 4. 端末からの自動設計・討論もCursorへ切替可能

これはIDEモードとは別の経路です。所有者の認証済みCursor Agent CLIを利用します。公式には `agent`、旧名/別名として `cursor-agent` が使われます。エディターを開く `cursor` コマンドではありません。[C1][C2]

通常の端末で確認します。

```powershell
agent --version
agent login
agent --list-models
```

CLIが未導入の場合は公式のWindows/Linux/macOS導入手順を参照してください。本パッケージはCursor自体のインストーラーを勝手に実行したり、認証ファイルをコピーしたりしません。[C2]

機能フラグの事前確認（モデル呼出しなし）：

```powershell
.\.venv\Scripts\python.exe -m cadmcp_brain.studio --workspace .\workspace provider-check
```

実行（`request.txt`はUTF-8の原文）：

```powershell
.\.venv\Scripts\python.exe -m cadmcp_brain.studio `
  --workspace .\workspace autopilot `
  --provider cursor `
  --project mouse-design `
  --request-file .\request.txt `
  --execute-model `
  --debate-rounds 2 `
  --review-workers 3 `
  --max-calls 32
```

`--cursor-agent "C:\...\agent.exe"`で実行ファイル、`--model`で実際の一覧にあるモデルIDを指定できます。`--model`を省くとCLI側の選択設定に従います。IDEとCLIが常に同じモデルになるとは限りません。既定のプロバイダーは互換性維持のためCodexのままなので、**Cursorを使う場合は `--provider cursor` を必ず指定**してください。他プロバイダーへ自動で切り替えません。

既存プロジェクトを続ける場合は `--request-file` を省きます。基板等の保護は従来どおり、実際の登録済みIDを `--protect-artifact` へ渡します。モデル呼出し数・並行数は利用枠を消費し得ます。定額内・無料・無制限とは保証しません。

### Cursor CLI用の制約

本アダプターは `--print --mode ask --output-format json` を使い、JSONの設計案/レビューだけを受け取ります。[C1][C4] CAD生成そのものはPython側の型付き実行器が担当します。

CLIのJSONは回答テキストを含む外側の封筒です。回答が自動でCADのJSON Schemaに一致するわけではないので、外側の成功判定→内側のJSON解析→ローカルのスキーマ検査を別々に行います。重複キー、NaN、余計なプロパティ、エラー応答、セッション再利用などを拒否します。失敗時は記録して停止し、検査条件を緩めたり別モデルへ再送したりしません。

呼出しごとに新しい一時作業フォルダを作り、明示された根拠ファイルのスナップショットを渡します。シェル・ファイル書込み・MCPツール・WebFetchをdenyするプロジェクト権限を設置し、既定で `--sandbox enabled` を要求します。[C5] 根拠の入力ファイルが変更された場合は出力を採用しません。

**Ask/deny/sandboxフラグは、OS隔離が完全に成立したことの証明ではありません。** Cursorのグローバル設定・認証は通常どおり使われ、CLI実装や環境に依存します。`--trust`は作成した一時フォルダだけを対象にし、元CADプロジェクトをCLIのcwdにしません。`--force`、`--yolo`、`--approve-mcps`は付けません。

sandboxを提供しない環境では既定実行を停止します。所有者がこの制約を理解し、Askとdenyルールのみで実行すると明示する場合に限り `--cursor-permissions-only` を付けられます。この選択は実行記録に残し、OS隔離を保証するモードとは呼びません。CLI版が必要なフラグを持たなければ、IDE+MCP経路を使ってください。

Windowsの `.cmd` ラッパーは `cmd.exe` に通さず、隣接するネイティブexe、またはPowerShellの `-File` で公式ps1を呼びます。PowerShell実行ポリシーを自動回避しません。対応する起動ファイルがなければ明示エラーにします。WSL経路ではPythonとAgentを同じWSL環境に導入してください。

## 5. データ・既存機能

Req2CAD全件初期化は引き続き以下です。

```powershell
.\setup_req2cad.cmd --download-deepcad --reference-only
```

**Cursor対応だけでデータベースが初期化されるわけではありません。** 注釈、CAD原本、埋め込み索引の導入状態は別です。本版でも全件データ・Qwen実重み・自由文設計の全体精度を検証済みとはしていません。既存0.3.0の同梱デモと本番workspaceは分けてください。

## 6. 今回の検証範囲

`TEST_REPORT_JA.md`と`verification/`を参照してください。今回のCursor CLI試験は、公式形式に合わせた明示的なスクリプト代役です。実プロセスで通信境界・異常系・14回の役割呼出しを通してCAD生成へ接続しますが、本物のCursorモデルを呼んだものではありません。

この作成環境からCursorインストーラーへアクセスした試行はDNS解決に失敗しました。Windows/Cursor GUI、実Agent CLIの認証後実行、ネイティブサブエージェントの実起動、実際のsandbox強制は未検証です。設定の構文試験やスクリプト代役の成功で、これらを合格に置き換えません。

## 公式参照（確認日：2026-09-17 JST）

- [C1] Cursor CLI parameters: https://cursor.com/docs/cli/reference/parameters
- [C2] Installation: https://cursor.com/docs/cli/installation
- [C3] Native subagents: https://cursor.com/docs/subagents
- [C4] Terminal JSON output: https://cursor.com/docs/cli/reference/output-format
- [C5] Permissions: https://cursor.com/docs/cli/reference/permissions
- [C6] Skills: https://cursor.com/docs/skills
- [C7] Configuration/auth location: https://cursor.com/docs/cli/reference/configuration
- [C8] MCP: https://cursor.com/docs/cli/mcp

ソースコードの参照URLであり、原著者が本パッケージを認定したものではありません。
