# cadMCP Design Studio 0.3.1 — Cursor対応

**Cursor IDE内のMCP設計と、Cursor Agent CLIによる自動設計・5役レビューの両方を追加しました。**
Req2CADの実例検索・CAD復元・型付きレシピ・実測検査は0.3.0の実装を維持しています。

まず [CURSOR_GUIDE_JA.md](CURSOR_GUIDE_JA.md) を参照してください。

```powershell
.\setup_cursor.cmd --geometry
```

そのフォルダをCursorで開いてMCPを再読み込みし、Agentモードで `/cad-check` を実行します。
IDEモードはCodex CLI不要です。外部の自動実行は明示的に `--provider cursor --execute-model` を選択します。

| 追加部分 | 内容 |
|---|---|
| Cursor用導入 | MCP項目マージ、Rule/Skill/コマンド/5役定義を配置、ローカル変更保護・バックアップ |
| IDE内レビュー | .cursor/agents、model: inherit、readonly、初回と相互反証の手順 |
| Cursor CLI | Askモード、別コンテキスト、JSON二段階検査、根拠スナップショット、回数・時間上限 |
| Codexとの両立 | --providerで明示選択。既存のCodex経路と43個のMCPツールを維持 |

本版の試験結果は [TEST_REPORT_JA.md](TEST_REPORT_JA.md) と `verification/` にあります。
**実Cursor GUI/認証モデルによる実行と全件Req2CAD+Qwenの検索品質は未検証です。**
Cursor形式のCLI代役を実行した試験と、実モデルによる設計評価を区別しています。

システムの構造設計部分・実例CADのデモ・既存限界については
[0.3.0の説明](docs/archive/v0.3.0/README_JA.md) と
[AGENT_WORKFLOW_JA.md](AGENT_WORKFLOW_JA.md)を参照してください。
旧版文書の260件という数は旧版の記録です。本版の結果へ混ぜていません。

試作品をCAD正本へ自動反映せず、プリンタ送信をしない方針は同じです。
