# 導入・統合 — 0.3.1

Cursorについては **[CURSOR_GUIDE_JA.md](CURSOR_GUIDE_JA.md)** が現行手順です。

## Cursorを主に使う

```powershell
.\setup_cursor.cmd --geometry
```

既存のCursorプロジェクトへ追加する場合:

```powershell
.\setup_cursor.cmd --geometry --project "C:\work\your-cadMCP"
```

自動実行をCursorへ切り替える場合は、従来のautopilotコマンドへ
`--provider cursor` を追加します。モデル呼出しには引き続き `--execute-model` が必要です。

MCP設定のみの従来導入 `setup.cmd --geometry`、Req2CAD初期化 `setup_req2cad.cmd`、
Python API `Brain`/`Tools` は維持しています。旧コード・データを丸ごと削除せず、別フォルダで確認してください。
旧0.3.0の導入説明は `docs/archive/v0.3.0/INSTALL_INTEGRATE_JA.md` に保存しました。
