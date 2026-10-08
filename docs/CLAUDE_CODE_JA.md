# Claude Code での StellaCAD 利用

Claude Code でも Cursor / Codex と同じ規則（`AGENTS.md`）と同じ cadMCP 本体・検査ロジックを使います。別エンジンは作りません。

## 構成
| 要素 | 場所 | 役割 |
|---|---|---|
| 入口 | `CLAUDE.md`（`@AGENTS.md` を取り込み） | 共通規則 + Claude 固有の補足 |
| MCP | `.mcp.json` | cadmcp-design-brain / cgal-mcp / mouse-library（案件共有、初回は承認が必要） |
| 権限 | `.claude/settings.json` | 読取専用の brain 工具のみ事前許可。build/import/submit 等の書込系は毎回確認。`LLM_cad_Projects/` の編集も確認 |
| Skill | `.claude/skills/stella-cad-design/` | 設計順・5役レビュー・禁止事項（長文版は `.agents/skills/cadmcp-design-brain/SKILL.md`） |
| 5役 | `.claude/agents/cadmcp-{requirements,mechanism,assembly,manufacturing,verification}.md` | 読取専用の別コンテキストレビュー（Read/Grep/Glob のみ、MCP 呼出し不可） |
| コマンド | `.claude/commands/cad-{check,design,review}.md` | 接続確認 / 設計 / 5役レビュー |

## 使い方
- 新規セッションでこのフォルダを開き、`.mcp.json` の 3 サーバーを承認する。`/cad-check` で接続を確認。
- CAD設計の依頼を普通に書けば `stella-cad-design` が起動する。本体ソフトの開発にはこの手順を使わない。
- 5役レビュー: 親が `brain_studio_review_packet` を取得 → 5 subagent を並列起動（1巡目）→ 相互反証（2巡目）→ 親だけが提出。Claude Code の subagent は別コンテキストなので「独立レビュー」を正直に名乗れる。

## 外部CAD書込系（既定では未登録）
classcad / stella-fusion-community / stella_freecad_mouse_b は、案件で所有者がそのバックエンドを選んだ後にだけ追加する。設定値は `.codex/config.toml` の該当ブロックを `.mcp.json` 形式（command/args/env）へ写す。FreeCAD は `integration/freecad` の準備手順と `docs/FREECAD_INTEGRATION_JA.md` に従う。失敗時の自動切替はしない。

## 注意
- 個人の旧登録（local scope の同名サーバー）は project scope より優先される。重複は無害だが、整理するなら `claude mcp remove <name> -s local`。
- `.mcp.json` の絶対パスはこのPC前提。別PCでは venv パスを直す。
- 事前許可は読取専用に限定。これは物理性能・レビュー受入の認定ではない。

## Build123d MCP（試験導入・任意）
- 内容: サードパーティの `pzfreo/build123d-mcp`（Apache-2.0、`build123d-mcp==0.3.90`）。Claudeがbuild123dコードを書き、サーバーが実行してSTEPを出力する text-to-CAD 経路。
- 場所: `integration/build123d-mcp/`（専用venv `.venv`、gitignore済み。手順・試験は同フォルダの README.md と `smoke_test.py`）。
- 有効化: 所有者の指示により、`build123d` と `stella-fusion-steve` の2サーバーを3クライアント全てに登録済み（下記「全クライアント登録」）。
- ネイティブRecipe工具とは別runtime。失敗時に他のCADへ自動切替しない。
- 出力STEPは必ず `brain_import_step` で取り込み検査してから使う。
- Windows注意: システムフォント破損（`mstmc.ttf`）でbuild123dがimport失敗するため、`winfix/sitecustomize.py` をPYTHONPATHで読み込む（snippet設定済み）。

## 全クライアント登録（build123d / stella-fusion-steve）
- 登録先: Claude Code `.mcp.json`、Codex `.codex/config.toml`、Cursor `.cursor/mcp.json`（本リポジトリと `V:\mouse`）。`V:\mouse` 側は本リポジトリ内の絶対パスを指す（`.codex/` は mouse 側でgit無視）。
- 無効化: Codex は該当ブロックの `enabled = false`。Claude Code / Cursor は該当エントリを削除（または `claude mcp` / Cursor 設定画面でOFF）。
- stella-fusion-steve は絶対パスのPython（`C:/Users/nikis/AppData/Local/Programs/Python/Python313/python.exe`）で起動し、`PYTHONUTF8=1` を維持。Fusionが起動していないと `stella_fusion_health` は ECONNREFUSED になる（正常）。
- 書込許可文書は `STELLA_FUSION_SANDBOX` のみ。広げない。別名の文書が必要になったら所有者へ報告する。
- フォント回避: build123d は `PYTHONPATH=integration/build123d-mcp/winfix`（`sitecustomize.py`）で破損フォント `C:\Windows\Fonts\mstmc.ttf` を読み飛ばす。`mcp.snippet.json` も有効なJSON（スラッシュ区切り）に修正済み。
- 上流がフォント問題を直したら winfix は外せる。
