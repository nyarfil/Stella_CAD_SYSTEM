# StellaCAD CGAL integration

登録済みの`cgal-mcp`はCGAL Master MCP。旧`stella_cgal_mcp.py`（v0.1 sidecar）は**非推奨で未登録**、履歴として保存のみ。
手順と実際の接続先は [CGAL統合](../../docs/CGAL_INTEGRATION_JA.md) を参照。

## CGAL Master adapter（派生ファイル橋）

- `master_derive.py` — 登録済み`cgal-mcp`（Master）で簡略化し、新規OFFと`.provenance.json`を作る（元ファイル不変、validator全pass時のみ公開）。
- `test_master_derive.py`、`verify_master_connection.py`、`fixtures/` — 試験・接続確認・fixture。
- AIエージェントは`cgal-mcp`の`cgal_get_guide`（`cgal://guide/start`）から始める。詳細・状態・TODOは [CGAL統合](../../docs/CGAL_INTEGRATION_JA.md)。
- このディレクトリがStellaCAD側の正本。CGAL repoの`integration/stellacad/`は控え。
