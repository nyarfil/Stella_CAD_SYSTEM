# ClassCAD / Fusion 統合

確認日: 2026-10-03。Stella 0.3.3 本体に、外部生成と Fusion 編集の入口を追加した構成です。

## 担当

| 要素 | 担当 | 固定版 |
|---|---|---|
| ClassCAD | 独立セッションで形状・アセンブリを生成し STEP を出力 | `@classcad/mcp@0.2.0`、lockfile 固定 |
| Fusion community | Fusion のスケッチ・フィーチャー・寸法・アセンブリ操作 | faust-machines `ba8560f321656aa493cdc775bc2fa7b2e7d8f005` |
| cadMCP / CadQuery | STEP の登録、出自・要件・試作履歴、幾何検査 | Stella 0.3.3 / CadQuery 2.8.0 |
| AI-CAD | 独立した既存ツールとして保持 | `c7503b4febd3bfa3368c1df38adb187eeb375fd7`、上流最新確認済み |

上流: [ClassCAD](https://github.com/awv-informatik/classcad-ai)、[Fusion community](https://github.com/faust-machines/fusion360-mcp-server)、[AI-CAD](https://github.com/ai-cad-labs/ai-cad)。

ClassCAD の MCP パッケージは MIT です。CAD エンジンとアカウントには別の利用条件があり、MCP のライセンスだけでエンジンの利用権を判断しません。今回は既存の認証で WASM エンジンを実行できました。

## 接続

本体の `.codex/config.toml` とチャット作業フォルダの `.codex/config.toml` に `classcad` と `stella-fusion-community` を設定済みです。既存の cadMCP 設定は保持しています。新しい Codex セッションで読み込まれます。現在のチャットでの検証は、同じ入口へ直接 MCP 接続して行いました。

ユーザーの追加指定により、`stella-fusion-community` は `C:/Users/nikis/.codex/config.toml` にも共通登録しました。同じPCの別プロジェクト・別セッションでも通常のFusion操作の優先経路です。利用方針は共通の `user-extensions/PREFERENCES.md` と `references/fusion.md` に保存しています。

Fusion 内にはプロジェクト直下の `integration/fusion-community/addon` を登録し、起動しました。自動起動は無効です。Fusion 再起動後は「Scripts and Add-Ins」で Fusion360MCP を Run します。手順は [専用 README](../integration/fusion-community/README_STELLA_JA.md)。

現在の編集許可は新規文書 `STELLA_FUSION_COMMUNITY_SANDBOX` だけです。案件を開始する際は新規文書を作り、設定の `--allow-document` にその正確な文書名を追加します。同名の文書は区別できないため、固有の名前を使います。

コミュニティ版は 93 ツールの beta です。Stella の入口は 79 ツールを公開し、任意 Python 実行・全削除・パラメータ削除・設計モード変更・CAM・汎用保存を除外します。公式 MCP は API 文書の参照と接続準備に利用できます。全機能の安定性や公式版の完全な上位互換は未検証です。

この PC の実動作で、上流の STEP 出力が Body を渡して失敗する問題と、アドインの標準出力ログが公式 MCP の JSON 応答に混ざる問題を確認し、プロジェクト内で修正しました。STEP の個別出力は、対象 Body だけを含み子コンポーネントがない Component に限定します。周辺 Body まで黙って出力しません。パッチの対象は `PINNED_SOURCE.json` に記録します。

## 設計の流れ

1. 要件と固定部品を cadMCP 側で記録する。
2. ClassCAD で新規セッションを開始し、実際のメソッド文書を取得して形を生成する。
3. STEP を出力し、`brain_import_step` で登録する。寸法の単位と SHA-256 を記録する。
4. CadQuery で寸法・ソリッド・体積・要求形状を検査する。
5. Fusion 編集が必要なら新規文書へ STEP を取り込むか、高水準ツールで形を作る。編集後の STEP を新しい成果物として再検査する。
6. CAD レビューと物理要件の検証を行う。

単位は入口ごとに確認します。今回の ClassCAD メソッドは mm、コミュニティ Fusion の箱生成 API は Fusion 内部単位の cm でした。20 × 10 × 5 mm は Fusion への入力で 2 × 1 × 0.5 です。体積 cm³ は 1,000 倍して mm³ に換算します。新しいメソッドでこの単位を推測して使いません。

既存の `brain_fusion_handoff` / `brain_fusion_ingest` は発行スクリプトと整合した従来契約です。コミュニティで出力した STEP をその契約の完了として登録しません。まず通常の外部 STEP として扱います。外部 MCP と Studio の全操作を自動同期する機能はまだありません。

## 実動作で確認したこと

ClassCAD MCP は 17 ツールを公開し、WASM 21.2.0 で 20 × 10 × 5 mm の直方体を生成しました。

- ClassCAD 体積: 1,000 mm³。
- STEP 出力と画像生成: 成功。
- Stella 登録・型付きレシピでの保持・独立した形状照合: 合格。
- Fusion への新規文書インポート: 1 ソリッド、寸法 20 × 10 × 5 mm、体積 1,000 mm³。
- 元 STEP のハッシュと既存 Fusion 文書の変更状態: 保持。

証拠は `integration/classcad/verification/build-20261003/` にあります。生成物と認証依存の実行データは Git 管理外です。

コミュニティ Fusion MCP でも専用文書に 20 × 10 × 5 mm の履歴付き箱を生成できました。スケッチ 1、フィーチャー 1、履歴 2、ソリッド 1 を確認し、STEP を出力しました。CadQuery で独立して再読込し、寸法・体積・有効性・要求直方体との形状差ゼロを確認しました。証拠は `integration/fusion-community/verification/live-wrapper-sandbox.json` と `stella-community-20x10x5mm.acceptance.json` です。許可文書がない場合の変更拒否も実接続で確認しています。

試験後は元の Fusion 文書をアクティブに戻しました。新規の試験文書 2 件は未保存のまま開いています。保存・削除は行っていません。

再実行用入口:

```powershell
node integration/classcad/probe.mjs integration/classcad/verification/new-run --build
cadmcp-all-in-one-2026-09-17/01_CURRENT/.venv/Scripts/python.exe integration/classcad/verify_stella.py integration/classcad/verification/new-run
```

Fusion の実インポート検証は `integration/classcad/verify_fusion.py` の `run` を公式 MCP の script として実行したものです。このファイルはテスト専用であり、既存案件の生成ルートには使いません。

この試験は接続・形状互換性の確認です。複雑な機構、ジョイントの運動、荷重、疲労、量産性、既存 CAD に対する設計品質の優位性は合格と判定していません。

## AI-CAD の整合復旧

上流 HEAD は取り込み済みの `c7503b4` と同じでした。不足したフロントエンド 2 ファイルと `.gitkeep` を復元し、5 本の Junction を現配置へ修復しました。破損した `.venv` は `.venv-backup-20261003` として保持し、上流 lock から再作成しました。Cairo と CasADi の DLL 読込順を Windows で修正しています。

実配置の `aicad-health.ps1` は `ok: true`、CadQuery / Cairo の読込が成功しました。renderer 12 件、その他 Python 149 件、API 文書 4 件とフロントエンド本番 build は成功しています。上流試験の Windows 固有の期待値 2 件と、上流 frontend lock の監査結果 moderate 7 / high 15 は残っています。既存の生成プロジェクトと設定は保持しています。詳細は [上流管理記録](../LLM_cad_Projects/UPSTREAM.md) を参照してください。
