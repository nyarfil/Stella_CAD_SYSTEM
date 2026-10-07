# FreeCAD正式統合と案件別CAD選択

2026-10-04。StellaCADはFreeCAD / ClassCAD / Fusion / CadQueryをユーザー選択式で扱います。Stellaの要求・参考検索・証拠管理と、実際に形状を編集するCADを分けます。未選択時は設計開始前に一度確認し、自動選択・自動フォールバックをしません。

同日追加: 自動選択を依頼された案件では、[能力別CAD選択](CAD_BACKEND_ROUTING_JA.md)の自動モードも利用できます。明示選択は引き続き優先し、実行失敗による自動フォールバックは行いません。自動方針を保存しただけでは既存の明示選択は解除されません。

## このPCでの構成

- Stella本体: `E:/aiwork/Stella_CAD_SYSTEM`
- OP1-LHD案件: `V:/mouse/OP1-LHD`
- FreeCAD実行環境: `E:/aiwork/FreeCAD_OP1_LHD`
- FreeCAD: 1.1.4、専用profile、上流 `neka-nat/freecad-mcp` 0.1.25、commit `d6bbe4b38be3a622b5981d9d2afa7037ee080534`
- 追加Workbench: Curves / MeshRemodel / Fasteners。各取得commitはFreeCAD実行環境の `runtime/sources.lock.json` に記録。
- 接続: `stella_freecad_mouse_b`。名前は添付パックとの互換用で、実案件はOP1-LHDです。

案件設定は `<案件>/.stella/cad-backend.json`。ZA13の共有 `.cursor/cad-session.json` は上書きしません。CAD選択コマンドは案件状態と案件内MCPの有効・無効設定を保存し、CADの起動やモデル編集をしません。選択後は新しい案件チャットでMCP設定を再読込してください。既存チャットに読込済みの工具はその場で消えません。

## 選ぶ・確認する・準備する

OP1-LHDでは `V:/mouse/OP1-LHD/Select-CAD.cmd` をダブルクリックすると選択メニューが出ます。FreeCADを選ぶと専用環境を準備します。モデルの編集は開始しません。

Stellaのルートで、ユーザーが選んだCADだけを記録します。

```powershell
python integration/freecad/select_backend.py select --project V:/mouse/OP1-LHD --backend freecad --kit E:/aiwork/FreeCAD_OP1_LHD
python integration/freecad/select_backend.py status --project V:/mouse/OP1-LHD
python integration/freecad/select_backend.py prepare --project V:/mouse/OP1-LHD
```

ClassCADを選ぶ場合:

```powershell
python integration/freecad/select_backend.py select --project V:/mouse/OP1-LHD --backend classcad
```

Fusion / CadQueryは `--backend fusion` / `--backend cadquery`。FreeCAD以外の選択に `--kit` は付けません。FreeCADの `prepare` は専用profileの起動を担当します。他CADの接続・編集は既存の工具と手順を使い、このコマンドから自動で別CADを起動しません。

選択前のFreeCAD候補確認は次の読取コマンドでできます。

```powershell
python integration/freecad/select_backend.py status --project V:/mouse/OP1-LHD --kit E:/aiwork/FreeCAD_OP1_LHD
```

CodexでOP1-LHDを設計するときは `V:/mouse/OP1-LHD` をプロジェクトとして開きます。この案件の `.codex/config.toml` はStella・ClassCAD・FreeCAD・mouse-libraryを定義し、初期状態ではCAD編集用MCPを無効化しています。選択すると対応する外部CADのMCPだけを有効にします。プリンタ操作MCPは案件内で無効です。OP1でFusionを選ぶときは、まず案件の専用許可文書とMCP設定を準備します。ZA13の許可を転用しません。

FreeCAD専用の `E:/aiwork/FreeCAD_OP1_LHD` を開く場合はFreeCADが唯一のCAD編集経路です。実行環境の初回起動は `Start-FreeCAD.cmd`、実機試験は `Test-FreeCAD.cmd`。接続設定の配置と、現在のチャットへのMCP工具読込は別です。新しいプロジェクトチャットで有効工具を確認してください。

## OP1-LHDの入力と引き渡し

作り直しの元は `V:/mouse/OP1-LHD/OP1-RHD_original.step`。専用環境の `project/inputs/OP1-RHD_original.step` に同一ハッシュのコピーを配置しました。旧左利き版08は比較専用です。未知の肉厚・公差・基板基準はnullのまま保持しています。

FreeCAD文書は `MouseB_OP1_LHD_*` と明示指定し、原入力や他案件を保存し直しません。FCStdを編集正本として保存し、部品別STEP/STL・検証JSON・画像を出力します。STEPはStellaの既存 `brain_import_step` に外部CAD由来として登録します。STEPでFreeCADの履歴を保持できるとは扱いません。

## 検証済みの範囲

専用FreeCAD GUIとstdio MCPで、寸法変更後の再計算、STEP再読込、STL出力、既知の距離・干渉検査、画像取得が合格。3つの追加Workbenchは登録・activationを確認しました。OP1-LHDの完成形状、実曲面の肉厚品質、クリック機構、FEM、印刷実物は今回の環境試験に含みません。

接続受入のため案件設定のコマンドを直接起動したStella（57工具）、mouse-library（6工具）、FreeCAD（17工具）は初期化と読取診断に成功しています。証拠はFreeCAD実行環境の `project/reports/stella-host-connection.json` と `runtime/last-live-test.json`。

## MCP比較と採用理由

[neka-nat版](https://github.com/neka-nat/freecad-mcp)はPython実行・文書検査・画像取得を提供します。[Robust版](https://github.com/spkane/freecad-addon-robust-mcp-server)は150以上の専用工具、[TESSA版](https://github.com/tessalabs-space/freecad-mcp)は図面・パラメータ掃引・解析準備等の工具を掲げています。工具数は曲面品質や実行速度の証明ではありません。今回の正式経路にはこのPCで実機試験を通したneka-nat固定版を採用しました。他版への変更は別profileで同じ受入試験とOP1に必要な操作を比較してから行います。

mouse親階層には現行Stellaの証拠管理と知識図書館を追加し、既存CAD設定は保持しています。グローバルFreeCAD/Fusion/Codex設定、Factory OS、既存ZA13文書は変更しません。ClassCAD・FreeCADを同じ形状へ同時に書き込ませません。
