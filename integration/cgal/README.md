# StellaCAD CGAL sidecar

`stella_cgal_mcp.py` は独立CGAL-MCPに検証付きSTL/OFFファイル入口を追加する。
インストール済みの `E:/aiwork/cgal-mcp/.venv/Scripts/python.exe` で起動する。
手順と実際の接続先は [CGAL統合](../../docs/CGAL_INTEGRATION_JA.md) を参照。
ネイティブCADの変更・Undoは実行しない。

## CGAL Master adapter（派生ファイル橋）

- `master_derive.py` — 登録済み`cgal-master`で簡略化し、新規OFFと`.provenance.json`を作る（元ファイル不変、validator全pass時のみ公開）。
- `test_master_derive.py`、`verify_master_connection.py`、`fixtures/` — 試験・接続確認・fixture。
- AIエージェントは`cgal-master`の`cgal_get_guide`（`cgal://guide/start`）から始める。詳細・状態・TODOは [CGAL統合](../../docs/CGAL_INTEGRATION_JA.md)。
- このディレクトリがStellaCAD側の正本。CGAL repoの`integration/stellacad/`は控え。
