# 上流プロジェクト調査・採否・移植対応表

調査日: **2026-09-16**。対象は確認できた公開ファイルと仕様です。
各プロジェクト全体の性能順位や、任意の機械設計の成功率を測定したものではありません。
ファイルの説明・名称の存在と、その機能の実行成功も区別しています。

## 採用した4系統

| 参照元 | 実際に確認したファイル | 採用した考え方 | このパッケージでの実装先 |
|---|---|---|---|
| agent-spec [S1] | `skills/agent-spec-intent-compiler/SKILL.md` | 原文に戻れる要求、推測と採用済み要求の分離、未確定事項、決定的なゲート | `models.py`のBrief/SourceRef/Unknown、`gates.py`のvalidate_brief、`prompts/intent.md` |
| Agentic Engineering Design [S2] | `data_models.py` | 要求と機能・実体・検証のつながりを設計状態として保持 | `models.py`のConcept/Function/Mechanism/Interface、`engine.py`のgraphとSQLite状態 |
| Multi-Agent-CAD [S3] | `multi_agent_cad/WORKFLOW.md`、`multi_agent_cad/schemas.py` | 要求と作業計画を型付き中間表現で分離し、モデル間の引継ぎを明示 | `models.py`のBrief/Plan、`gates.py`のvalidate_plan、`engine.py`のexport |
| AgentCAD [S4] | `docs/agent-api.md`、`agentcad/core/tools.py` | 実在のtool registryを唯一のAPI契約とし、本文のエラー・部分成功を読む | `backend.py`のprobe/prepare/execute_prepared、`engine.py`のbackend_call |

上記コードをそのまま切り貼りしたのではありません。共通の小さなIRとAPIに**新規実装**しました。
多人数のエージェント構成そのものや依存一式を取り込むより、ホストモデルが順に役割を担い、
ゲート・状態・出典をコードで固定する設計を今回の統合方針としました。これは本実装の設計判断です。

## 元ファイルを読んで採用しなかった部分

**MACのoperation normalization。** 確認したWORKFLOWには`sweep`／`loft`を`extrude`へ正規化する記述があります。
今回の目的では、形状が違う操作を成功させるより未対応として止める方を選びました。
また、必要なfilletが失敗したときに半径を黙って小さくして「成功」にする処理は入れていません。
PlanはCADタスク契約であり、そこにあるloft指示を自動的に押出しへ変換するコードはありません。[S3]

**スキーマに名前があることと測定実装があることの混同。** MACのschemasには複数の検証種類がありますが、
WORKFLOWの実運用記述では限定した最終形状属性のQAが説明されています。このパッケージは、
名前だけ列挙された検査を実装済み扱いせず、実測できる種類とexternal_geometryを区別しました。[S3]

**AgentCADのHTTP 200を成功とみなす処理。** 公開APIはエラー本文を返す場合があるため、
HTTPステータスだけではなく`error`／`ok:false`を確認します。タイムアウト後の自動再送も行いません。[S4]

**LLMの自己評価を合格証にする処理。** モデルが「十分強い」「合格した」と言っただけでは
実測・実試験の証跡にしません。候補のquality_scoreは未計算を示すnullであり、
0.97等の根拠のない意図理解確率は使っていません。

## 前回候補に挙げたが、この配布物には組み込んでいないもの

Req2CADの論文内容・Function–Structureの方向性は着想候補ですが、その研究用知識ベース、
CADコンポーネント群、学習済みモデル、実動コードをこの配布物へ取り込んだわけではありません。
前の説明にあったコンポーネント件数や性能を、本実装のデータ量・能力として転記していません。
13個の初期カードは今回作成した設計上の出発点です。

iDesignGPT、CADDesigner、AI-CADの全パイプラインや特定の性能改善も、本リリースの依存・移植済み機能ではありません。
この作業は、それらを含む全論文・全リポジトリの再現実験を完了したものではありません。
実際に移植先を対応付けられる4系統と、動かして確認できる小さな基盤を優先しました。

## 検索・構造知識について

`data/patterns.json`の検索は英単語・日本語の部分語による**字句検索**です。
埋め込みモデル、ベクトルDB、ウェブRAG、研究用データセットを使っていません。
各カードは適用条件、リスク、方向ルール、検証注意を含みますが、汎用的に実証済みの
板厚・強度・寿命・クリアランスを与える資料ではありません。

`source_ids`の`design_method`／`manufacturing_principles`は、原著論文の個別機構実証を示すIDではなく、
**今回の著者による設計方法／製造上の検討項目という分類**です。
これを特定メーカーのデータや実験結果の引用として扱わないでください。
`knowledge_sources.json`で分類と外部参照を分離しています。

## 参照ファイルの記録

GitHubから返されたSHAは**Git blob SHA**で、リポジトリ全体のcommit SHAではありません。
全体を固定バージョンで検証したという意味ではありません。リンク先mainは変更され得るため、
移植時には記録したblob SHAと実ファイルの差を確認してください。

| ID | ファイル | 確認時に取得したblob SHA |
|---|---|---|
| S1 | agent-spec intent compiler Skill | `621f18eb08affcd8665bb36c7edaacf28ed368fc` |
| S3 | Multi-Agent-CAD schemas.py | `d8bef8705a630e2c5e6036b3906d7e4b4161dccc` |
| S4a | AgentCAD docs/agent-api.md | `d1cf9876276c67d4c520490c03aabcb6cefbd56b` |
| S4b | AgentCAD agentcad/core/tools.py | `51d84a4021ae9c5743e1d69455abe58c899826bd` |

S2とMAC WORKFLOWは本文を確認しましたが、この表には未記録のSHAを推測して記載していません。
各参照は実装レビュー用リンクであり、ソースコード・画像・モデルの再配布ではありません。

## 一次資料

- **S1** https://github.com/ZhangHanDong/agent-spec/blob/main/skills/agent-spec-intent-compiler/SKILL.md
- **S2** https://github.com/SoheylM/agentic-eng-design/blob/main/data_models.py
- **S3a** https://github.com/Pan-Chera/Multi-Agent-CAD/blob/main/multi_agent_cad/WORKFLOW.md
- **S3b** https://github.com/Pan-Chera/Multi-Agent-CAD/blob/main/multi_agent_cad/schemas.py
- **S4a** https://github.com/n3r/AgentCAD/blob/main/docs/agent-api.md
- **S4b** https://github.com/n3r/AgentCAD/blob/main/agentcad/core/tools.py
- **S5** MCP初期化・版交渉: https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- **S5b** MCPツール: https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- **S6** Cursor MCP設定: https://cursor.com/docs/mcp
- **S6b** Cursor Rules: https://cursor.com/docs/rules
- **S7** Codex MCP設定: https://developers.openai.com/codex/mcp/ （確認時はChatGPT Learnの公式文書へ転送）

MCPはS5/S5bの標準入出力サブセットを今回実装しました。最新の全仕様への対応を意味しません。
Cursor/Codex設定形式を文書で確認したことと、それらのGUI/CLIで本パッケージを実際に起動したことは別です。
