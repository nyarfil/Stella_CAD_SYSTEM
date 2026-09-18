# 導入と統合 — 0.3.0

## 0. 前提と保存先

Python3.11以上。実行確認はLinux/Python3.13.5、Windows用cmdは同梱していますがWindows実機での導入は未試験です。既存0.1/0.2とは別フォルダへ展開し、旧workspaceをバックアップしてください。旧の生成途中の構造参照・意味索引を無検査で再利用しません。幾何キャッシュ識別子と埋め込み方式が変わったため、キャッシュ再構成・索引再作成が必要になることがあります。

## 1. 本体と実カーネル

```powershell
.\setup.cmd --geometry
```

ローカル`.venv`へ導入、テスト、doctor、設定生成を順に行います。geometryなしは形状試験がskipとなる軽量構成です。失敗やskipを全機能確認済みと読まないでください。PyTorch/CUDA等の全OS別依存をhash-lockした環境ではありません。

## 2. 同梱実例で再実行

```powershell
.\.venv\Scripts\python.exe scripts\demo_real_references.py --workspace .\demo-workspace
```

4件の選定公開CAD、明示的な字句検索、作者記述の設計レシピを用いた幾何試験です。出力の`DEMO_RESULT.json`からHTML・STEPの実保存先を確認できます。ユーザーのマウス完成品やLLM性能ベンチマークではありません。

## 3. 正規データの全件初期化

```powershell
.\setup_req2cad.cmd --download-deepcad --reference-only
```

公開注釈→CAD原本→モデル→索引→整合性検査の順です。処理が止まったら実際のエラーを確認してください。原本を別の環境で取得した場合：

```powershell
.\setup_req2cad.cmd --csv C:\datasets\Req2CAD.csv --cad-path C:\datasets\data.tar --cad-kind deepcad_tar --reference-only
```

CSVは記録済み原本hashと照合します。配布元が更新した場合、保護を消して継続するのではなく、新版の差分・出典・hashを確認して取り込み設定を更新してください。Hugging Faceの利用条件やアクセス制限を迂回しません。全CAD原本の権利をReq2CAD注釈のCC-BY-4.0と同一視しません。

状態確認：

```powershell
.\.venv\Scripts\python.exe -m cadmcp_brain.req2cad --root .\workspace\knowledge\req2cad status
```

注釈件数、CAD対応数、実復元件数、意味索引は別です。元の128,873や公開CSVの件数を固定値でローカル状態として返しません。既定の意味検索は`req2cad_native`（raw query・max_length128・暗黙prefixなし）です。命令付き方式へ変える際は索引も作り直します。意味索引が未導入ならsemantic呼び出しは失敗します。lexicalは明示した診断・限定検索としてのみ利用できます。

## 4. MCPとして利用

`integration/generated/cursor.mcp.json`と`codex.config.toml`が生成されます。既存設定全体を置き換えず、`cadmcp-design-brain`の項目だけマージしてください。`.agents/skills/cadmcp-design-brain/SKILL.md`と`.cursor/rules/cadmcp-design-brain.mdc`を対象プロジェクトで読めるようにします。既存同名ファイルは差分を確認します。

最初にホストへ渡す指示：

```text
README_JA.md、AGENT_WORKFLOW_JA.md、同梱Skillを読んでください。
brain_doctor、brain_fs_status、brain_studio_schemaを実際に呼び、接続と機能を確認してください。
構造設計では、原文→FunctionBrief→実例検索→実CADとPNGの確認→機能別の複数案→Matrix→Recipe→実検査を使ってください。
既存CAD正本は保持し、基板やシェルの実ファイルから必要寸法と方向を調べてください。
未導入データや欠けた原CADを、架空のUID・寸法・デモで代替しないでください。
5役レビューは初回と相互反証を分け、実行した記録だけを登録してください。
```

既存の単一MCPへ統合するPython入口は従来どおり `Brain` と `Tools` です。`Tools.list()`のスキーマ、`Tools.call(name,arguments)`を既存ツール登録へ結び付けます。ユーザーの既存コードへ自動パッチしたものではありません。別MCPからの直接書込みを止めるには、正本CADの書込み入口で所有者の権限・取引・Undoを実装する必要があります。

## 5. 所有者側の自動実行・討論

認証済みCodex CLIが端末で動くことを、所有者自身の通常の設定で確認します。本アダプターはread-only sandbox、明示出力schema、出力ファイル、設定分離を使用します。既存認証を利用し、APIキーや認証ファイルを抽出・複製しません。利用枠・費用は選択モデルと契約によります。

```powershell
.\.venv\Scripts\python.exe -m cadmcp_brain.studio --workspace .\workspace autopilot --project mouse-design --request-file .\request.txt --execute-model --debate-rounds 2 --max-calls 32
```

`request.txt`はUTF-8の原文です。既存プロジェクトを継続する場合は同じ`--project`を指定し、`--request-file`は省きます。修正原文は既存の`brain_add_source`で世代を更新します。自動実行中に原文・出典が変われば止めて再計画します。

`--execute-model`なしでは呼び出しません。`--codex`は実際の実行ファイル、`--model`は所有者が利用可能なモデル名です。`--review-workers 1`が既定、2か3を明示すればレビューを並行実行できます。別コンテキストでも同じモデルに共通の誤りがあり得ます。

既定上限：2巡討論、最大1回修正、最大32calls、1call600秒、実体化候補最大8件。これは作業の所要時間予測ではなく停止・費用管理の上限です。許可された範囲だけを明示変更できます。終了後に未知の外部呼出しを自動再送しません。チェックポイントは記録用で、任意の中断から全て自動再開する機能ではありません。

### 既存PCB等の保護

先に`brain_import_step`で実STEPを`purpose=reference`として登録し、artifact IDを取得してください。実際の取り込みschemaは`tools/list`を確認します。

```powershell
.\.venv\Scripts\python.exe -m cadmcp_brain.studio --workspace .\workspace autopilot --project mouse-design --execute-model --protect-artifact PCB --editable-reference shell
```

PCBとshellは実在の登録済みIDへ置き換えます。保護対象は位置・形状を変えず出力アセンブリに存在しなければなりません。編集するシェルは所有者が許可します。MCPホスト方式では起動環境の`CADMCP_PROTECTED_ARTIFACT_IDS`／`CADMCP_EDITABLE_REFERENCE_IDS`へJSON文字列配列で設定します。

## 6. 出力と復旧

`workspace/studio/<project>/<attempt>/`にrecipe、STEP、STL、4方向PNG/SVG、measurements、HTML、review packetが保存されます。`agent-runs`には所有者起動時の役割・入力hash・実行記録が保存されます。実モデル未実行なのにログを生成する機能はありません。

既存CADへの反映は所有者レビュー後、既存backendの正式操作で行います。現版のtyped recipeは万能CAD操作集合ではなく、未対応操作は旧の汎用backend契約へ計画を渡すか未対応として扱います。成功のために別形状へ自動置換しません。

バックアップはMCP停止後にworkspace全体をコピーします。生きたSQLiteの一部だけを複製しません。設定を戻す際は今回追加した項目だけを外し、後で追加した他の項目を消さないでください。
