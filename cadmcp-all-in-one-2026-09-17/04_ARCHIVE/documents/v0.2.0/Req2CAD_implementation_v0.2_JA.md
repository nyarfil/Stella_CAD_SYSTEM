# Function–Structure Knowledge Base 実装内容と再現範囲

作成日: 2026-09-16 / v0.2.0

## 1. 中核の修正

ユーザーが欲しかったのは、要求の記録箱だけでなく「この機能をどういう実例構造で実現するか」を検索できる知識源です。本版はこの経路を主役にしました。旧13カードは補助です。

```text
Function query
 ↕ keyword embedding / cosine similarity
Function label ←→ case_functions ←→ original uid
                                  ├─ original functional annotation
                                  ├─ source JSON / STEP (exact UID)
                                  ├─ source content hash / terms / unit status
                                  ├─ actual B-rep / STEP / STL / SVG views
                                  ├─ face labels + shared-edge adjacency + WL
                                  └─ sampled surface descriptor (non-learned)
```

**1機能に複数構造、1構造に複数機能**を扱います。CAD本体を持たない注釈も、注釈だけとして区別します。欠けた形状をLLMで作って、実例CADと称する機能はありません。

## 2. 原資料で確認したこと

原論文4.1.1には、機能不明な候補を除外後の件数として128,873が記載されています。[S1]
公開CSVは175,978行と表示され、機能注釈、機能語、DeepCAD/Text2CAD共通UIDを含みます。[S2]
この実装のフィルタは「安全に解析できた、空でない機能語」によるものです。原著者のフィルタと完全一致するとはせず、実際の取込件数・空ラベル件数・拒否行・重複を報告します。

原論文は、機能語と要求機能をQwen3-Embedding-4Bで埋め込み、cosineで対応付けます。B-repの面種別と面隣接をグラフにし、WL subtree kernelでトポロジーを比較します。[S1] モデルの公式実装にはSentence Transformersでの利用方法があります。[S4]

公開プレビューから、例えば以下の注釈とUIDの対応を確認できます。[S2]

| 元UID | 機能注釈の例（要約） |
|---|---|
| 0032/00329619 | 回転を支える、部品を案内する、接続する |
| 0032/00321991 | 回転軸を案内する、部品を保持・組み立てる |
| 0032/00325917 | 滑り嵌合、摩擦低減、案内、間隔保持 |
| 0032/00323296 | 力の増幅、運動の変換、支点 |

これは公開注釈の確認であり、今回それらのCAD原本をダウンロードして形状を検証したという意味ではありません。注釈はVLM/LLMの機能仮説です。元論文も単純・重複的な構造という制限を述べています。[S1][S2]

## 3. 実装対応表

| 領域 | 本版の実装 | 本環境での確認 |
|---|---|---|
| 全CSV取得 | 原URLからstream取得、確認済みSHA検査、失敗時原本不更新 | 実ネットワーク取得失敗。フルCSV未取込 |
| 注釈DB | SQLite、UID主キー、機能の多対多、重複・不正・欠損の分類、原文と原本hash | 合成データで正常/異常試験 |
| 機能語埋め込み | Qwen3-Embedding-4Bローカル読込、keyword単位、batch/resume、実モデルリビジョンとファイルhash | 重み・依存未取得。実モデル推論未検証 |
| cosine検索・集約 | 複数機能ごとの最高一致、対応機能数→平均類似度→UIDで決定的順位 | 制御用ベクトルで数値処理を確認 |
| CAD対応 | UID完全一致、DeepCAD JSON / uncompressed TAR / STEP、元ファイルhash | 作者作成データで登録・TAR読込確認 |
| B-rep再構成 | Line/Arc/Circle、片側/両側/対称押出、join/cut/intersect | 実カーネルで試験片確認 |
| トポロジー | 実B-rep面種別、共有edgeの同一性、WL特徴/kernel/distance | 面種別・隣接・順序不変性を確認 |
| 幾何特徴 | 面積重み付き表面sampling、D2/半径histogram、共分散固有値 | 実カーネル/NumPyで確認。**非学習型** |
| 表示・出力 | STEP/STL、iso/top/front/rightのSVG | 実ファイル出力確認 |
| 候補の多様性 | 実測済み候補からfarthest-firstで選択 | 実試験片で確認 |
| 設計への採用 | case_references、機構へのreference_ids、根拠digest、採用原理・適合変更、契約引継ぎ | 偽根拠・古い根拠・未実体化参照の拒否確認 |

### 原版との相違を省略しない

本版は**原論文の点群cross-attention学習済みエンコーダーを実装・再現していません**。別の決定的な幾何特徴です。同じ性能や局所意味特徴が得られるとは主張しません。

原版のt-SNEクラスタUI、2DのMaximum Common Subgraphによる融合点探索、点群の局所対応による融合アンカー、元Next.jsアプリ、段階的CAD生成器全体も含みません。2Dの曲線接続グラフは出力しますが、MCSによる自動融合はしません。

機能検索では原論文の0.7を初期値にしていますが、本実装のquery instruction・ライブラリ版・dtype・フィルタは原実験との同一性が未確認です。閾値を校正済みと呼びません。原版の単一機能に対する無作為50件選択ではなく、再現可能な順位付けを使います。[S1]

## 4. MCPツールと使う順番

| Tool | 役割 |
|---|---|
| brain_fs_status | 本物の取込数、CAD対応数、埋め込み準備、測定数 |
| brain_fs_search | 複数の機能から元UIDを検索。既定semantic |
| brain_fs_case | 元注釈・機能語・CAD登録情報を読む |
| brain_fs_materialize | 該当UIDの実CADを再構成・出力・測定 |
| brain_fs_evidence | 出典、実CAD、トポロジーをハッシュ付き根拠として読む |
| brain_fs_compare | 実測済み2部品の形状/トポロジーを比較 |
| brain_fs_portfolio | 検索候補から異なる構造を持つ代表を選ぶ |

通常はホストが機能を分解してsemantic検索します。日本語で入力できますが、Qwen本体を使った日本語検索精度はこの環境では未測定です。必要ならホストが原意を残して短い英語機能に正規化します。字句検索で日本語と英語が一致しなかったことを、知識がない証拠にしてはいけません。

検索後に必ず実CADと図を確認します。たとえば「回転軸を支える」という注釈があっても、実際には案内穴なのか、片持ちの支持なのか、ハウジング全体なのかを、形状から確認します。採用するのは原理と構造上の関係であり、元部品の寸法や推定用途の丸コピーではありません。

構造案に登録する情報:

```text
CaseReference.id
CaseReference.uid              ← 検索結果の実在UID
CaseReference.evidence_digest  ← brain_fs_evidenceの実戻り値
CaseReference.function_query
CaseReference.adopted_principle
CaseReference.required_adaptations
Mechanism.reference_ids        ← どの機構が何を参考にしたか
```

実際に取得した値を入れます。提示用サンプルのdigestやUIDを使って通してはいけません。旧カードにない構造は `pattern_id=reference_structure` で扱い、方向・復帰・止め・接続等は別途宣言/検査します。UIDが違うだけで設計原理が違うとは限らないため、ホストによる案の比較も必要です。

## 5. 完了の意味

`semantic_ready` は同じ注釈に対する索引が存在することです。Qwenの意味理解精度の証明ではありません。`all_cad_joined` は全UIDへ原本が結び付いたことです。全形状の読込成功ではありません。`all_breps_measured` は機能ラベル付き部品の記録済み変換数の充足であり、形状・原本hashは利用時に再検査します。

**「正しいUID→実CAD」「形状として成立」「機能が成立」「対象マウスに適合」「印刷できる」「耐久性がある」は別の確認です。** 本版は前二者と比較に注力し、後者を自動合格にはしません。

## 6. ファイル対応

- `cadmcp_brain/req2cad/catalog.py`: 原注釈・機能多対多・実UID検索。
- `semantic.py`: モデル導入、機能語embeddings、cosine検索、hash/resume。
- `assets.py`: 実UIDのCAD原本登録・安全なTAR参照・取得。
- `geometry.py`: DeepCAD再構成、実B-repトポロジー、WLと幾何特徴。
- `worker.py`: 別プロセスの実形状処理、出力、単位状態。
- `service.py`: キャッシュ・実参照証跡・比較・多様性。
- `mixin.py`: 既存MCPレジストリへ7ツール追加。
- `models.py` / `engine.py` / `gates.py`: 設計案・作業契約への参照根拠接続。
- `scripts/setup_req2cad.py`: 所有者が明示する全データ導入経路。
- `scripts/demo_req2cad.py`: 原データと区別した作者試験片の再実行。

## 一次資料

[S1] Req2CAD論文 https://doi.org/10.1145/3772318.3791949

[S2] Req2CAD元データ・データカード https://huggingface.co/datasets/QianzhiJing/Req2CAD

[S3] DeepCAD元コード・データ案内 https://github.com/rundiwu/DeepCAD

[S4] Qwen3-Embedding-4B公式 https://huggingface.co/Qwen/Qwen3-Embedding-4B

原CSVの確認済みSHA-256:
`b645fd38a75039a505cf24318cc17510b26ebc4e70068f44def06fdf1a0a55f6`

データカード/公開プレビューと論文の確認はできましたが、作成環境のフルファイル取得は失敗しました。失敗を原データ非公開やユーザー環境でも取得不可能という意味に読み替えません。
