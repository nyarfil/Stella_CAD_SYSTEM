# cadMCP Function–Structure Knowledge Base 0.2.1

## 今回の主機能

**既存の構造を機能から探し、実際のCADと接続構造を参照して設計するための追加MCPです。**
要求や検査の管理だけを増やすものではありません。固定13カードを検索する方式ではなく、Req2CADの公開注釈を全件取り込み、共通UIDでDeepCADの原CADを結び付けます。

```
日本語の要求（ホストモデルが機能に分解し、必要なら英語検索語も作る）
 → Req2CAD全件注釈の機能検索
 → 候補UID／機能説明／元データの出典
 → 対応するDeepCAD raw JSON または登録済みSTEP
 → CADソリッド復元・面種類・面接続グラフの実測
 → 複数候補の比較
 → 参考STEP・UID・ハッシュ・適用理由を既存CADエージェントへ渡す
```

## 読み違えてはいけない範囲

- 本配布物は**取り込み・検索・CAD復元・比較・引き継ぎを実装したソース**です。128,873件すべての実CADとQwen重みを組み込み済み・検証済みのDBとは呼びません。
- 原論文の学習済み点群／cross-attention形状モデルは同梱していません。本実装の形状比較は実測D2＋共分散特徴です。面接続は実B-repから抽出し、WL特徴で比較します。これは原論文全体の再現実験ではありません。
- 形状結合のアンカーを求める原論文のsketch MCS、原版対話UI、任意の機構の自動合成・強度保証は未実装です。
- CSVの件数は実際の取り込み結果を使います。「論文では128,873」とコードに記載されていても、その件数をローカル件数として返しません。
- 機能注釈は機械生成です。検索ヒットは構想の候補であって、正しい機能・強度・嵌合・寿命の証明ではありません。
- 以前の作業で言及した245件という件数を、この再構成配布物の検証件数として流用していません。今回の実行記録は`verification/test-results.json`です。

## 初期化（Windows）

このフォルダで次を実行します。

```powershell
.\setup-req2cad.cmd
```

この処理はローカルvenvへ依存を導入し、テスト、公開注釈ダウンロード、CADアーカイブとのUID結合、Qwen機能語索引の生成を順に行います。CADのソリッド復元は通常、検索で選んだ候補だけ行います。

Qwenのモデル・CUDA対応PyTorchの導入状態で利用デバイスが変わります。`--device cuda`を明示しCUDAが使えない場合はエラーです。CPUへ黙って変更しません。`auto`は利用可能性から選びます。

```powershell
.\setup-req2cad.cmd --device cuda
```

全CADを順次復元する場合：

```powershell
.\.venv\Scripts\python.exe -m cadmcp_fs --workspace .\fs-workspace build-geometry --all
```

正常復元済みのUIDは次回スキップします。失敗したUID・理由は`geometry_build.jsonl`へ記録されます。アーカイブの分割ダウンロード再開機能はありません。埋め込みは完了したバッチから再開します。

ライブラリ導入のみを先に行う場合：

```powershell
.\setup-req2cad.cmd --skip-initialize
```

`--skip-cad`や`--skip-embeddings`は機能を省いた状態です。完了状態と誤認しないでください。

## MCP接続

`cursor.mcp.generated.json`／`codex.config.generated.toml`を生成します。既存の設定を丸ごと置き換えず、追加するサーバーの項目だけマージします。このインストーラーは既存MCP設定やCADプロジェクトを書き換えません。

実装はstdio MCP 2025-06-18のtoolsサブセットです。最新全仕様・すべてのクライアントとの相互接続の保証ではありません。

### 7つのツール

| ツール | 役割 |
|---|---|
| `fs_status` | 実件数、原CAD結合数、検査済み形状数、ベクトル索引状態 |
| `fs_search` | 複数機能から参考構造を検索。標準はQwenのdense検索 |
| `fs_case` | UIDの機能注釈、出典、CAD、実測トポロジーを読む |
| `fs_materialize` | 原CADを復元し、STEPと実測記録を作る |
| `fs_compare` | 候補の面接続とD2形状の類似を比較 |
| `fs_adopt` | 実形状を確認した候補を新しい構造パターンとして登録 |
| `fs_handoff` | 実STEPと出典のハッシュをまとめ、既存CADへ引き継ぐ |

`dense`が利用できないとき、`lexical`へ自動で切り替えません。日本語の意味解釈を固定辞書だけで代用もしません。ホストモデルが要求を保持しながら機能語を作り、元データの言語に合わせた検索を行います。

## 既存Design Brainへの接続

独立した追加MCPとして使えます。既存のv0.1.0を変更するコード統合では、`cadmcp_fs.brain_adapter.attach_catalog(brain,kb)`がCatalogをラップし、`fs_adopt`で返された`req2cad_...` IDを解決します。固定13カードは補助として残します。

```python
from cadmcp_fs import KnowledgeBase
from cadmcp_fs.brain_adapter import attach_catalog
from cadmcp_fs.server import Tools as FunctionStructureTools

kb = KnowledgeBase(r'C:\cad-work\function-structure')
attach_catalog(brain, kb)  # 既存Brainオブジェクト。対応しない版では推測せずエラー。
kb_tools = FunctionStructureTools(kb)
# 既存MCPのtool一覧へkb_tools.list()を加える。
# fs_*呼出しはkb_tools.call(name, arguments)に送る。
```

このアダプターは既存ソースへの組み込み完了を意味しません。ホストごとのCAD書込み権限、Undo、プロジェクト排他、契約digestと出典の対応付けは既存cadMCP側で確認してください。Catalog構造の違う版へ自動的に無理なパッチを当てません。

## CAD復元の範囲

DeepCADのraw `entities`／`sequence`から、直線・円・円弧、外周と内周、片側／対称／両側押出し、Join／Cut／Intersect／NewBodyを処理します。未対応の曲線、ロフト、テーパ、開始位置定義等は別形状に置き換えず失敗します。NewBodyは独立ソリッドを保持し、原DeepCAD可視化コードの無条件Fuseとは区別します。

元データの単位が実際のmmだとは自動認定しません。STEPの数値をそのままマウス部品の製造寸法として採用しないでください。

## 検証と実例

```powershell
.\.venv\Scripts\python.exe scripts\verify.py
.\.venv\Scripts\python.exe scripts\demo.py
```

`examples/synthetic-only/`は本配布物用に作った試験形状で、Req2CADの実データではありません。テスト用ベクトルは索引計算の確認だけに使い、Qwen実重みの品質検証として扱いません。テストのskip／失敗／未実施は`verification/`の記録に残します。

元注釈・CAD・モデルの取得失敗は、存在しない検索結果や架空のCADで置き換えません。取得失敗の記録がある状態は、機能検索DBの初期化完了ではありません。

## 出典と再配布

- Req2CAD研究: https://doi.org/10.1145/3772318.3791949
- 著者の注釈データ: https://huggingface.co/datasets/QianzhiJing/Req2CAD
- Qwen埋め込みモデル: https://huggingface.co/Qwen/Qwen3-Embedding-4B
- DeepCAD原実装・データ案内: https://github.com/rundiwu/DeepCAD
- DeepCAD rawデータ: https://www.cs.columbia.edu/cg/deepcad/data.tar

Req2CAD注釈の表示ライセンスはCC-BY-4.0です。著者・配布元への帰属を保持し、本パッケージのフィルタと索引加工を区別します。DeepCADのCADデータ、Text2CAD画像、Qwen重みの条件を注釈の条件と同一視しません。Text2CADのアクセス制限付き画像は本ツールで迂回取得しません。原著者による本パッケージの保証・推奨はありません。
