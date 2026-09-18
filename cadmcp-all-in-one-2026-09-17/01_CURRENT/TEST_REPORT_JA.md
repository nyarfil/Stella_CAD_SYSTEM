# 検証記録 — cadMCP Design Studio 0.3.1 Cursor対応

記録日: **2026-09-17 JST**。この版の最終ソースで再実行した結果です。

## 1. 結果

**304件合格 / 0件失敗 / 0件エラー / 0件skip。** 実測実行時間 201.215 秒。

| 試験 | 結果 | 根拠 |
|---|---:|---|
| 既存機能を含む最終全試験 | 304件合格 | `verification/all-tests.xml`、`all-tests.log` |
| Cursor追加部分の単独試験 | 44件合格 | `verification/cursor-tests.xml`、`cursor-tests.log` |
| 配布wheelと最終package内容の一致 | 51ファイル一致 | `verification/test-results.json` |
| 別配置wheel + 生成Cursor設定からのMCP通信 | 33ツール、doctor/schema成功 | `verification/wheel-mcp-smoke.json` |

**44件は304件に含まれます。合算して348件とはしません。** 旧版の260件という記録を流用したものではなく、既存260件も本版で再実行しました。旧版の説明は`docs/archive/v0.3.0/`に保存しています。

## 2. Cursor追加試験の内容

Cursor公式形式を模した、明示的なスクリプト代役を別プロセスで起動しました。実モデル・実Cursor CLIの代わりであることを出力の版名にも記録しています。

- JSON外側の成功判定と、回答内のネイティブJSON Schema検査。辞書・map、1個のコードフェンス、重複キー、NaN、型違い、余計な項目、空回答、エラー応答を確認。
- 起動フラグ、Ask/deny/sandbox指定、call上限、別session、3並列呼出し、入力改変の拒否、元要求の保持、根拠スナップショットとサイズ制限を確認。
- `agent`/`cursor-agent`とエディターランチャーの区別。Windows用exe/ps1選択は**模擬ファイル・引数検査**であり、Windows自体を実行した結果ではありません。
- 設定マージで無関係なMCP項目と既存envを保持し、ローカル修正のあるRule等は停止、変更前をバックアップ。冪等性、dry-run、不正JSON、5役のreadonly定義を確認。
- 完全なAutopilot経路を**14回のスクリプト応答・2巡のレビュー**で実行し、実CADカーネルによるモデル構築へ接続。自由文からのモデル設計成功率ではありません。

全件索引や意味検索の元からある試験も、制御ベクトルによる計算検査と実モデル精度を区別しています。幾何は実CadQueryを使用していますが、図をCursorモデルが理解できたことは検査していません。

## 3. 配布wheelと設定済みプロセスの確認

`dist/cadmcp_design_brain-0.3.1-py3-none-any.whl`を別venvへ`pip install --no-deps`で導入しました。最初の試行では基底環境にpydantic/jsonschemaがなく失敗したため、検証済み環境のsite-packagesを明示的な`.pth`で共有して再試験しました。**ネットワークから全依存を新規取得するクリーンインストール試験ではありません。** この検証用`.pth`やvenvは配布物に含みません。

package本体は別venvのwheel導入先から読み込み、ソースディレクトリには依存しません。空白・日本語を含む別プロジェクトに`scripts/setup_cursor.py --no-install --python ...`で設定とアセットを配置し、その`.cursor/mcp.json`を読み取って実stdioサーバーを起動しました。

初期化、33個のtools/list、brain_doctor、brain_fs_status、FunctionBrief schemaを確認しています。新規workspaceのReq2CAD件数は0、semantic_ready=falseと実際に返り、未導入状態を準備完了と扱っていません。

この試験は**Cursor設定形式で起動したMCPの実通信**です。Cursor GUIやCursor Agentアプリ自体が接続した結果ではありません。

Wheel SHA-256:
`680daf614339143501e17a0d9c6f97d5ea39a486fdb2fe802ecc9e23ec2fb29f`

## 4. 再実行

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest -q tests\test_cursor.py
.\.venv\Scripts\python.exe scripts\check_cursor_connection.py --project .
```

最後のコマンドは実際のMCPサーバーを起動し、設定されたworkspaceを開きます。新規workspaceは作成されますが、CADモデルを生成・変更したり外部モデルを呼んだりしません。

## 5. 未実施

**実Cursor GUI、認証済みCursor Agent CLIでのモデル呼出し、ネイティブサブエージェント5役の実行、Windows実行、OS sandboxの強制を検証していません。** Cursorインストーラー取得の試行はDNS解決で失敗しました。公式ドキュメントによる契約確認と、代役プロセスによるコード検査までです。

Req2CAD全件+Qwen実重みの検索品質、任意の雑な指示から実物マウスを完成させる能力、既存AgentCAD/Fusionと所有者の実CAD、実印刷・組立・強度・疲労も今回の合格範囲には含みません。モデルの独立コンテキストは誤りの独立性を保証しません。

CLIは既定でsandboxを**要求**し、シェル/書込み/MCP/WebFetchのdenyを設定しますが、CLI実装やグローバル設定を含む隔離を認定したものではありません。権限のみの明示的な代替モードは実行記録に区別されます。

## 6. 環境

```json
{
  "python": "3.13.5",
  "platform": "Linux-6.18.44-x86_64-with-glibc2.41",
  "packages": {
    "pydantic": "2.13.4",
    "jsonschema": "4.26.0",
    "cadquery": "2.8.0",
    "pytest": "9.0.2",
    "numpy": "2.3.5",
    "Pillow": "12.3.0",
    "setuptools": "82.0.1"
  }
}
```

記録の`/mnt/data/...`は作成時のパスです。利用者のMCP設定へ転記せず、setup_cursorで実環境のパスを生成してください。
