# 上流との対応 — 0.3.0

確認日: 2026-09-16。各プロジェクト全体の性能比較・再現成功率ではありません。

## Req2CAD

公開注釈の入口は `https://huggingface.co/datasets/QianzhiJing/Req2CAD`。CSVのUID/function_keywords/function_descriptionを取り込みます。ラベルは機械生成の機能仮説であり設計仕様ではありません。原CSVの登録hashは`req2cad/common.py`、同梱4件の別標本は`examples/public-cases/provenance.json`を参照します。128,873という論文のフィルタ後件数と、公開CSV行数・ローカル成功件数は区別します。

今回新しくコードを確認した公開リポジトリ：
`https://github.com/hankaiuu/Req2CAD/tree/39824684655771e6082d6a3669c21c515cae1152`

| 元ファイル | 確認内容 | 本実装 |
|---|---|---|
| `Python_backend/func2cad.py` | last-token pooling、raw query、max_length128、cosine機能語検索、機能↔CAD対応、多機能ヒット数 | `req2cad/semantic.py`のnative query経路と機能別集約。実埋め込みでの同等精度は未測定 |
| `Python_backend/cad2topo_2d.py` | ファイル名に2dとあるがSTEPの面・edgeからグラフを構築しWL比較 | 実B-rep面隣接・面種類・WL特徴。元の全属性と厳密に同一なカーネルではない |
| `Python_backend/get_geom_embed.py` | `models_ae`と学習checkpoint、点群特徴、cross-attention系処理 | 学習済みcheckpointは未取得。本版はD2/共分散等の非学習代替。再現したとはしない |
| `README.md` | Next.js、機能推論・構造生成・組立、Onshape/API設定 | 元UIや全アプリは依存にしない。既存CADホストを保持 |

この公開リポジトリの作者と論文著者の身元同一性までは確認していません。コードの公開状態と、原論文の完全再現可能性は別です。

論文：`https://doi.org/10.1145/3772318.3791949`

## DeepCADと取得したCAD

原実装案内：`https://github.com/rundiwu/DeepCAD`。原JSONをスケッチと押出しの列として読む方式を参考に、OCP/CadQueryで実装しました。旧pythonoccコード一式をそのまま動かすものではありません。NewBodyを無条件にFuseする可視化処理とは区別し、独立材質領域を保持します。

実取得した4件は`arnavagarwal05/3d_modelling`のcommit`432d03406b89a924b755c1826f2eb78da650e440`からの公開ミラーです。UID、Git blob SHA、SHA-256を記録・実照合しました。元アーカイブとの同一性、元画像との対応は未検証です。元CADのライセンスをコードMIT/注釈CC-BYと混同しません。

## iDesignGPT

`https://github.com/Songkai-Liu-SJTU/iDesignGPT/blob/a6e55bf7007f566234285271edcfd2ad3b99c7b9/code/agent/Morphological%20analysis/Morphological%20Matrix.md`

機能ごとの複数実現方法→組み合わせ→実現可能性・冗長性の評価を参考に、型付きMatrixと制約付き機能カバー列挙を新規実装しました。FastGPT環境・全プロンプト・TRIZ・論文の能力向上を丸ごと移植したとはしません。

## AI-CAD / AgentCAD / 要求管理

AI-CADのPlannerで示された部品分解、インターフェース、組立順の検討を、構造案とassembly reviewに反映しています。`.shared/agents/planner/instructions.md`の定量製造ルールを、QIDI/ABSへそのままコピーしていません。AI-CAD本体は依存にしていません。

AgentCADは既存正本として保持。`n3r/AgentCAD`の公開API契約に合わせたレジストリ取得/許可操作/エラー本文判定のブリッジは既存実装を継承しました。実AgentCAD本体との接続は未検証。agent-spec、Agentic Engineering Design、Multi-Agent-CADの型・出典・状態の着想は旧基盤として継承しています。詳細な過去確認は`archive`で歴史情報として保存しています。

## 所有者側モデル呼び出し

公式CLI資料：`https://developers.openai.com/codex/noninteractive/`

`exec`、read-only sandbox、output schema、output-last-message、既存認証を用いるアダプターを実装。実CLI実行は未検証。CLI版が必要フラグを持たなければ失敗し、無制限実行/任意シェルへのフォールバックをしません。5役を別コンテキストで起動する設計と、実際に独立した5モデルをこの環境で実行したことは別です。
