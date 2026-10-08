# Stella 用 STEVE ブリッジ (steve-bridge)

StellaからAutodesk Fusionを操作するための経路です。Fusion側は10-X-eng/STEVE (MIT, commit `17e684e`, v0.8.1) のアドインをそのまま取り込み、**RMFG関連だけ**を削除しています。Stella側はguard付きのstdio MCPサーバーです。詳細は [docs/DESIGN.md](docs/DESIGN.md)、来歴は [NOTICE.md](NOTICE.md)。

状態: 偽の `adsk` に対するテスト72件は合格。**実際のFusionでは未検証**です。Fusionへの導入、Codex/Cursor/Claude Codeの設定ファイルへの書き込みは行っていません。

## 重要な注意

- STEVE本体のチャットパネル(ChatGPT/Grok/Claude/OpenRouter/Ollama)は、Stellaの文書許可リスト、read-only、コード検査、監査ログの**対象外**です。これらが効くのはStellaのMCP(`stella_fusion_*`)経由の呼び出しだけです。
- 完全版STEVEの外部通信先 (OpenAI via Codex、xAI、OpenRouter、Anthropic、Ollama、help.autodesk.com、GitHub更新確認) は DESIGN.md 第7章の表にあります。更新確認・Codex `web_search: live`・既定プロバイダー・デバッグログの上流既定値は**変更していません**。判断は DESIGN.md 第9章です。
- コード検査は多層防御であり、サンドボックスではありません。トークンを読めるプロセスは、Stella側guardを迂回してseamへ直接コードを送れます (DESIGN.md 第4章)。

## 構成

```
addin/STEVE/            上流STEVE (RMFG削除) + steve/stella_seam.py (唯一の機能追加) + STEVE.py に4行のtry/exceptフック (safe_start)
server/                 Stella側MCPサーバー (標準ライブラリのみ)
tests/                  pytest (偽adsk使用)
docs/DESIGN.md          設計・信頼境界・未検証事項・設定案・移行計画・ライブ試験手順
docs/patches/*.diff     上流との完全な差分
```

MCPツール: `stella_fusion_health` / `_inspect` / `_query` / `_execute` / `_viewport` / `_api_help` (最後の1つは追加。オフラインのAPIヘルプ)。

## 有効化の手順 (まだ実行していません)

1. 使い捨てのFusion文書 `STELLA_FUSION_SANDBOX` を用意します。
2. `%LOCALAPPDATA%\STEVE\stella-seam\config.json` を作り `{"enabled": true}` と書きます (既定は無効)。
3. Fusion: `Shift+S` → Add-Ins → 緑の `+` → フォルダ `E:\aiwork\Stella_CAD_SYSTEM\integration\steve-bridge\addin\STEVE` → Run。「Run on Startup」は判断が済むまでオフ。他のFusion MCPアドインは止めます。
4. `endpoint.json` と `token` が同じフォルダにできたことを確認します。
5. MCPクライアントに下記の設定を貼ります (貼る作業はまだ行っていません)。
6. DESIGN.md 第11章のチェックリストを、使い捨て文書で上から順に確認します。

STEVEのチャット(Codexランタイム)を使う場合だけ、別途ランタイムが必要です。上流 `10-X-eng/STEVE` の `17e684e` で `python scripts/fetch_runtime.py` を実行するか、検証済みランタイムを `%LOCALAPPDATA%\STEVE\runtimes\` に置きます。Stellaのツールだけなら不要で、今回CodexやClaudeのバイナリはダウンロードしていません。

## MCP設定 (貼り付け用・未適用)

サーバーは標準的なstdio MCP (JSON-RPC 2.0) で、3つのホストで同じコマンドが動きます。Python 3.9以上だけが必要です (`python` がPATHで別物なら絶対パスを使う)。引数: `--allow-document 名前` (複数可、完全一致)、`--read-only`、`--allow-read-any`、`--port`、`--token-file`、`--audit-log`、`--scratch-dir`。

**Codex** `.codex/config.toml`

```toml
[mcp_servers.stella-fusion-steve]
command = "python"
args = [
  "E:/aiwork/Stella_CAD_SYSTEM/integration/steve-bridge/server/stella_steve_bridge_mcp.py",
  "--allow-document", "STELLA_FUSION_SANDBOX",
  # "--read-only",
]
startup_timeout_sec = 20
tool_timeout_sec = 130
```

TOMLでバックスラッシュを使うなら `'C:\Users\...'` の単一引用符リテラルにします。スラッシュ区切りなら二重引用符で問題ありません。

**Claude Code** `.mcp.json` またはコマンド

```json
{ "mcpServers": { "stella-fusion-steve": {
  "command": "python",
  "args": ["E:/aiwork/Stella_CAD_SYSTEM/integration/steve-bridge/server/stella_steve_bridge_mcp.py",
           "--allow-document", "STELLA_FUSION_SANDBOX"] } } }
```

```powershell
claude mcp add stella-fusion-steve --scope project -- python E:/aiwork/Stella_CAD_SYSTEM/integration/steve-bridge/server/stella_steve_bridge_mcp.py --allow-document STELLA_FUSION_SANDBOX
```

`--` より後ろはすべてサーバー側の引数です。文書名に空白があるときはシェルで1引数になるよう引用します。プロジェクト共有の `.mcp.json` は初回に承認が求められます。

**Cursor** `.cursor/mcp.json`

```json
{ "mcpServers": { "stella-fusion-steve": {
  "command": "python",
  "args": ["E:/aiwork/Stella_CAD_SYSTEM/integration/steve-bridge/server/stella_steve_bridge_mcp.py",
           "--allow-document", "STELLA_FUSION_SANDBOX"] } } }
```

JSONでバックスラッシュは二重にします (スラッシュ推奨)。空白や日本語を含む文書名は、環境変数 `STELLA_FUSION_ALLOWED_DOCUMENTS` に `["文書名"]` のJSON配列で渡す方が安全です。

## 次にやること

- 実機検証 (DESIGN.md 第8・11章)。
- 既定経路への移行は DESIGN.md 第13章のチェックリストに従います (既存ファイルは未変更)。公式 `fusion` MCPには文書の開閉・保存があり、このブリッジにはありません。これを先に決めてください。
- Claude Code用のスキル/エントリはまだありません (Codex/Cursorにはあります)。
