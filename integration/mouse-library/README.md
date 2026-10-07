# Mouse Library MCP — マウス設計の知識図書館

初期MVP。Python 3.10以上の標準ライブラリーだけで起動する、CADツールやLLMに依存しない読み取り専用MCPです。知識はパッケージ内のJSONにあり、元のStellaCADフォルダーがない環境にもコピーできます。

## 何ができるか

- 部品の意味、機構原理、部品間の接続条件、設計手順、失敗例と確認事項を取得する。
- 日本語・英語の語彙で検索する。MVPは語彙検索であり、意味検索や全文ベクトル索引ではありません。
- 利用者の要求から、測定・構造選定・CAD・製造・現物確認へ進む計画を返す。
- StellaCADのFunctionBrief下書きと設計根拠を返す。
- 全体、主クリック、サイドボタン、ホイール、基板、光学高さ、外装、電源、組立、FDM、ZS-F1/G305実例、CAD受け渡しの12項目を初期収録する。

図書館はCADカーネルを持ちません。形状生成は利用側のCAD MCPが行います。初期収録は全機種の寸法ライブラリーではなく、一般原理と一つの測定実例です。G305の全搭載部品や現物動作の証拠はまだそろっていません。

## 0.1.2で追加した学習

主クリックの3つの原理案、復帰と上下停止の力の経路、ON/OFF・過押込みの記号式を `primary_click_mechanism` に追加した。0.1.2時点では数値評価工具は未実装。取得した133TOMの左右クリック小基板STEPの測定と、法線方向区間を加え、測定リソースは6件。左右基板を鏡像で代替しないこと、端子込みの外接高さを押下量としないこと、OT最小保証と許容最大押込みを区別することを明示した。

原CADは同梱しない。詳しい探索・形状表示・限界はStellaCADの `docs/REFERENCE_G305_PRIMARY_CLICK_JA.md`、確認記録は [VERIFICATION_0_1_4.md](VERIFICATION_0_1_4.md)。

## 起動と持ち運び

このディレクトリーで次を実行します。

```sh
python -m mouse_library
```

標準入力・標準出力はMCP通信専用です。JSON-RPCを一行ずつ送受信します。起動しただけではUIは表示されません。

別のPCではこのディレクトリーをコピーし、MCPホストのcommandをその環境のPythonへ、cwdをコピー先へ設定します。パッケージとして配置する場合は `python -m pip install .` を使えます。配布先でStellaCADやcadgenをインストールする必要はありません。

汎用MCPホスト用設定例（絶対パスはコピー先に置き換える）:

```json
{
  "mcpServers": {
    "mouse-library": {
      "command": "python",
      "args": ["-m", "mouse_library"],
      "cwd": "/path/to/mouse-library",
      "env": {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    }
  }
}
```

## 初めて使うLLM／ハーネスの手順

1. `mouse_library_status` で収録範囲と限界を読む。
2. `guided_mouse_design` プロンプトまたは `mouse-library://workflow` を読む。
3. `mouse_library_plan` にユーザーの要求、採用ハードウェア、クリック構造、電源方式、製法、利用可能なCADツールを渡す。
4. 計画の関連知識を `mouse_library_get` で読み、出典・実例の適用条件・未知事項を確認する。
5. CADツールの能力と入力スキーマを取得する。工具名だけから機能を推測しない。
6. 実ハードウェアを表示・測定する。単位、基準、版、出典、ハッシュと測定方法を記録する。
7. 固定、可動、力の経路、復帰、停止、組立経路を定義し、複数の構造案を比較する。
8. 採用案をCADツールの操作へ具体化してSTEPを作る。未知寸法を適当な値で埋めたものは概念案として区別する。
9. 幾何、可動、組立、製造、現物のクリックと光学追従、耐久を別々に確認する。

例:

```json
{
  "requirements": {
    "original_request": "採用する基板と握り形状スキャンから、左右クリックとサイドボタンを持つマウスを設計したい。",
    "hardware_id": "利用者が選ぶ基板 — 個体と版は未確認",
    "button_architecture": "separate",
    "connection": "wireless",
    "manufacturing_process": "FDM — 材料とプリンター条件は未確定",
    "available_cad_tools": ["ClassCAD MCP"],
    "measurements": {},
    "protected_constraints": ["実測した既製基板と部品の形状を拡縮しない。"]
  }
}
```

`measurements` は利用者が渡した値です。入力されたという理由だけで測定済み・適合済みにはなりません。

## StellaCADとの接続

二つの入口を用意します。

| 入口 | 用途 |
|---|---|
| 独立した `mouse-library` MCP | どのLLM・ハーネス・CAD MCPでも同じ知識を取得する |
| StellaCADの `brain_mouse_knowledge_*` | StellaCADのMCPから同じ図書館実装を呼び出す |

StellaCAD側は任意依存として図書館を読み込みます。Python環境にこのパッケージを配置するか、`PYTHONPATH`へ本ディレクトリーを追加します。ライブラリーが使えない場合は利用不可を返し、他機種の知識で代用しません。`brain_mouse_knowledge_schema(name="requirements")` で要求入力の実スキーマを取得できます。

`mouse_library_stella_bridge` ／ `brain_mouse_knowledge_brief` のFunctionBriefは下書きです。各機能が元要求に合うかをホストが確認し、現在の `brain_studio_schema("FunctionBrief")` と照合して利用します。ネイティブ橋はStellaCADの現行モデルでFunctionBriefと2種類の設計根拠を検証し、`native_schema_validation` を返します。この検証はRecipe全体や実物適合の合格ではありません。StellaCADの検索、構造案、Recipe、実行・検査へ進む際も、既存のハードウェア保護と検査条件を保持します。

知識レコードのIDはReq2CADのUIDではありません。知識の出典は独立したknowledge provenanceとして残し、原理は `Recipe.design_basis` へ明示します。`Recipe.reference_uses` には実際のReq2CAD参照だけを入れます。外部の提供CADは、既存のProjectStep経路に従って登録します。図書館レコードをCAD面やready Board Packに偽装しません。

接続設定の変更は次に起動したMCPプロセスへ反映されます。現在のチャットの工具一覧は自動的に更新されたとはみなしません。

## 知識の追加方法

正本は `mouse_library/data/library.json` です。MVPには外部資料を自動取込する機能や知識編集ツールはありません。

各entryに次を記録します。

- `id`, `title`, `subsystem`, `tags`, `summary`
- `principles`, `interfaces`, `workflow`, `verification`, `common_failures`
- `evidence`: 出典ID、根拠の種類、支持する主張
- `unknowns`: 未測定、未確認、適用条件

出典は `sources` に登録します。根拠の種類は `principle`（設計原理）、`observed`（形状・写真・説明の確認）、`author_reported`（作者報告）、`measured_reference`（参考形状の測定）を区別します。写真・ファイル中の指示をホストへの命令として扱いません。幾何の転載、メーカー仕様、電気・材料の定量値には、それぞれ必要な出典と利用条件を付けます。

取り付け姿勢候補、クリック板の鉛直・法線方向材料区間、左右クリック基板の測定レポート11件を `mouse-library://measurements` から取得できます。移植時に不要な絶対パスはファイル名へ正規化し、元レポートのハッシュと区別しています。元のSTL・STEP・写真・プレビューメッシュは同梱しません。原形状から再測定する場合は、その出典と入力ハッシュが一致する形状を別に用意します。鉛直材料区間は法線肉厚・曲げ支点・クリック荷重の測定ではありません。

今後、機種別実測ハードウェア、スイッチ仕様、ホイール接続、光学高さ、製法別公差、実物試作記録を増やすことで、作れる範囲を広げます。

## 実装状態

実装と設定、実際のMCP接続、実物設計能力は別に扱います。接続・動作・持ち運び用パッケージの検証はユーザーの明示指示を受けて実施します。受入確認は `tests/test_mcp.py`、結果は別の検証記録へ保存します。確認では新しい一時workspaceを使用し、既存案件やCAD形状を書き換えません。

現在の0.1.4では受入確認21件と、wheelを隔離先へインストールしたMCP呼出を確認済みです。追加した測定知識と確認範囲は [VERIFICATION_0_1_4.md](VERIFICATION_0_1_4.md)、初期MVPの確認は [VERIFICATION.md](VERIFICATION.md) を参照してください。

## 0.1.3の追加知識

左右接触面、旧・更新底ケースの穴対比較を収録。底STL二つは入力SHA一致。17対16.5の比較はSTL単位仮定付きで、適合承認ではありません。作者写真の10M刻印を手元個体や別作者STEPへ対応付けません。詳細は同梱REFERENCE_G305_CLICK_CONTACT_AND_MOUNT_JA.mdを参照してください。

ZIPの `examples/` は同梱測定リソースから抽出したパス正規化済みJSONです。元レポートそのものではありません。元レポートのSHAと正規化内容は `mouse-library://measurements` の各レコードで確認できます。

## 0.1.4：任意基板・スキャンの入口と汎用クリック計算

G305は事例で、既定形状・寸法にしません。`mouse-library://workflow` と `cad_tool_handoff` に汎用入力契約を収録。詳細は同梱GENERIC_MOUSE_DESIGN_CONTRACT_JA.mdを参照。

独立MCPは6工具、StellaCADの知識工具は7工具です。`mouse_library_click_window` または `brain_mouse_knowledge_click_window(assessment=...)` がON前停止・復帰後OFF・停止後の最大圧縮と基準隙間窓を計算します。スキーマはStellaの `brain_mouse_knowledge_schema(name="click_window")` から取得。各区間に単位・出典種別・適用ハードウェア、closureには状態履歴を記録します。

値が欠けた条項は未評価、既知の条件不成立は残します。基準gとuの誤差を二重計上しません。許容最大押込みとOT最小は別です。入力出典は呼出側の申告で工具が実在・版対応を確認したものではありません。帰還力やスキャン変換、全マウス生成・実物合格は行わず、physical_design_completeは常にfalse。
