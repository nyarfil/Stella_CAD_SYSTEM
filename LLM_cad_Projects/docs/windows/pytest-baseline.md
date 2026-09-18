# Windows pytest 基準線（2026-09-15）

コマンド:

```
uv run pytest -q -m "not slow and not exhaustive" --tb=line -n auto --maxprocesses=4
```

結果: **6329 passed, 90 failed, 63 skipped, 14 errors** in 727 s。macOS 正本は `make test` 5087 green と記録されているが、マーカー除外と xdist で件数は一致しない。

フォント: `uv sync` 直後の `import build123d` は壊れた Windows フォントで落ちた。`scripts/stella/windows_font_patch.py` を当ててからこの基準線を取っている。

`tests/test_sandbox_windows.py` は `slow` のためこの基準線に含まれない。隔離は次のプローブと `win-sandbox-check.ps1` で見る。

## 90 件の失敗（ファイル別）と理由

第一弾では **隔離と箱→STEP 以外は直さない**。残件はここに理由を書いて置く。

| 件数 | ファイル | 理由（Windows 固有） |
|---:|---|---|
| 17 | `test_geometry_ci_action.py` | GitHub Action の bash 本文を構文検査。Windows ではシェルが違う |
| 7 | `test_skills_library.py` | シンボリックリンク（権限・Developer Mode）と `fcntl` 的な同時書き込み |
| 6 | `test_sandbox_plan.py` | POSIX の `0700`（511 vs 448）と hosted 姿勢。隔離本体のテストではない |
| 6 | `test_sync_cli.py` | `chmod 0600` と case-fold（Windows は大文字小文字を区別しない） |
| 5 | `test_examples_golden.py` | ゴールデン STEP のバイト一致。改行や OCCT 版差の可能性 |
| 4 | `test_packages_format.py` | パッケージ内シンボリックリンク |
| 4 | `test_sync_server.py` | `.git` / `.history` の case-fold。NTFS では別物にならない |
| 3 | `test_sync_merge_rce.py` | 同上（同期・hosted。第一弾の対象外） |
| 2 | `test_packages_publish.py` | CLI 経路。上の format/cache に依存 |
| 2 | `test_frontend_shell.py` | パレット登録の受け入れ。ツール数ピンの差の可能性 |
| 2 | `test_deploy_config.py` | docker compose / hosted 配置 |
| 2 | `test_tenancy.py` | POSIX 権限とロックファイル |
| 2 | `test_prd026_acceptance.py` | フロント受け入れ（`check_interference` パレット） |
| 2 | `test_bench_publish.py` | シンボリックリンク |
| 2 | `test_appmode.py` | `0600` / `0700` |
| 2 | `test_packages_cache.py` | シンボリックリンク |
| 2 | `test_authstore.py` | POSIX 権限と flock |
| 1 ずつ | `test_cli_admin`, `test_skills_lint/routes/tools`, `test_features`, `test_sketch_diagnostics`, `test_audit`, `test_protocol_ids`, `test_meter`, `test_bench_*`, `test_hosted_hardening`, `test_packages_cli/index`, `test_search`, `test_bom_export`, `test_comments`, `test_prd008`, `test_prd010` | 権限ビット、シンボリックリンク、hosted、`ru_maxrss` の OS 差、ゴールデンバイト |

14 errors は巨大パラメータ ID を含む setup 失敗が主（ログが肥大化するため生ログはコミットしない）。

## 第一弾で触るもの

- フォントパッチ（セットアップ必須。再現済み）
- AppContainer 隔離（プローブ + `test_sandbox_windows.py`）
- 起動スクリプトと HTTP 橋
