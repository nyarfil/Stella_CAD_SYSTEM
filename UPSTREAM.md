# 上流（本家）の記録

Stella CAD System は、AgentCAD の本体を `agentcad-for-windows/` に取り込み、Windows 上で Cursor と Codex から使えるようにした作業リポです。

## 取り込み元

| 項目 | 値 |
|---|---|
| リポ | https://github.com/n3r/AgentCAD |
| 取り込んだコミット | `4b00aa5` |
| そのコミットの題名 | `PRD-018 completed: move PRD to completed/, mark roadmap DONE (PR #37)` |
| 取り込み日 | 2026-09-15 |
| 置き場所 | `agentcad-for-windows/` |

本家の `.git` は削除して、**Stella の 1 リポに吸収**しています。履歴は 1 本です。本家の更新を取り込むときは、上のコミットから先を手で差分コピーします。

## 改造の置き場

| 種類 | 置き場所 |
|---|---|
| 起動・橋・手引き（Stella 側） | リポ根の `scripts/stella/`、`stella_cad/`、`.cursor/skills/`、このファイルと `README.md` / `AGENTS.md` |
| Windows 向けの本体修正 | `agentcad-for-windows/` の中（隔離・フォントなど、Windows で動かないと分かったものだけ） |

本家の更新を取り込むときは、`agentcad-for-windows/` への Stella 側パッチを上書きしないよう、先に差分を確認します。
