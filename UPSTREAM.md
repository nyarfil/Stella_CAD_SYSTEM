# 上流（本家）の記録

Stella CAD System は、複数の AI-CAD 系プロジェクトの良い部分を一本にするための作業リポです。AgentCAD の Windows 起動は下ごしらえです。

## 取り込み元

### AgentCAD

| 項目 | 値 |
|---|---|
| リポ | https://github.com/n3r/AgentCAD |
| 取り込んだコミット | `4b00aa5` |
| そのコミットの題名 | `PRD-018 completed: move PRD to completed/, mark roadmap DONE (PR #37)` |
| 取り込み日 | 2026-09-15 |
| 置き場所 | `agentcad-for-windows/` |

### AI-CAD（ai-cad-labs）

| 項目 | 値 |
|---|---|
| リポ | https://github.com/ai-cad-labs/ai-cad |
| 取り込んだコミット | `c7503b4` |
| そのコミットの題名 | `OSS Public readiness` |
| 取り込み日 | 2026-09-16 |
| 置き場所 | `ai-cad-labs/` |
| Python | 3.13（AgentCAD の 3.12 と別 venv） |

### text-to-cad（cadgen）

| 項目 | 値 |
|---|---|
| リポ | https://github.com/earthtojake/text-to-cad |
| 取り込んだコミット | `3e4dfde` |
| そのコミットの題名 | `Add source-only Tendon Hand project (#384)` |
| 取り込み日 | 2026-09-16 |
| 置き場所 | `text-to-cad/` |
| 実行系 | `cadgen[snapshot]==0.5.1`（`skills/cad/requirements.txt` のピン） |
| Python | 3.13（他と別 venv） |

### ForgeCAD

| 項目 | 値 |
|---|---|
| 配布 | npm `forgecad@0.13.0`（公開ソースの吸収ではない。本家は非公開開発リポ） |
| 課題トラッカ | https://github.com/KoStard/forgecad-public-kit |
| 取り込み日 | 2026-09-16 |
| 置き場所 | `forgecad/`（`package.json` でピン。実体は `node_modules/forgecad`） |
| 実行系 | Node 20+、`dist-cli/forgecad.js` |
| ライセンス | ForgeCAD Software License（個人非商用は無料。商用・エージェント埋め込みは Pro/Enterprise） |

本家の `.git` は削除して、**Stella の 1 リポに吸収**しています。履歴は 1 本です。本家の更新を取り込むときは、上のコミットから先を手で差分コピーします。

## 改造の置き場

| 種類 | 置き場所 |
|---|---|
| 起動・橋・手引き（Stella 側） | リポ根の `scripts/stella/`、`stella_cad/`、`.cursor/skills/`、このファイルと `README.md` / `AGENTS.md` |
| Windows 向けの本体修正 | `agentcad-for-windows/` の中（隔離・フォントなど、Windows で動かないと分かったものだけ） |
| AI-CAD のジャンクション修復 | `scripts/stella/link-aicad.ps1`（`tools` と harness 設定は `.shared/` への Junction。Git では消えるので setup が直す） |

本家の更新を取り込むときは、`agentcad-for-windows/` や `ai-cad-labs/` や `text-to-cad/` や `forgecad/` への Stella 側パッチを上書きしないよう、先に差分を確認します。
