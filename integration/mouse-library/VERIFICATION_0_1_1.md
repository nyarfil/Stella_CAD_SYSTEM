# 0.1.1：クリック板の測定知識追加

確認日: 2026-10-03。

- 主クリックの知識に、鉛直材料区間と法線肉厚の違いを追加した。
- 提供STLの84点の測定レポートを同梱し、測定リソースを3件へ増やした。
- 測定スクリプト、STL、姿勢レポートのハッシュを保持した。姿勢は取り付け候補で、単位・実物適合・曲げ支点・荷重・復帰・疲労は未確定。
- 独立した幾何監査で、鉛直区間を肉厚や機構成立へ読み替えないことを確認した。左右の近いサンプルも全体対称性の証明にはしない。

## ソフトウェア確認

`python -m unittest discover -s integration/mouse-library/tests -v`：**11件成功、失敗0件**。新しい知識と84点レポートがMCPから取得でき、法線肉厚が未検証として保持されることを含む。

wheelを再構築し、sourceのPython／JSON 4ファイルとの一致、隔離先へのオフラインインストール、MCP初期化・知識12項目・測定3件の取得を確認した。

```sh
python -m pip wheel --no-deps --no-build-isolation --wheel-dir artifacts .
python scripts/check_package.py --wheel artifacts/mouse_library_mcp-0.1.1-py3-none-any.whl --report artifacts/package-verification-0.1.1.json
```

wheel SHA-256: `79dc51c400bac81a5d34c4cf09c4e7426d03fd5cd74fba4d9fea40398a91df24`。

Windows/Python 3.13での確認。別OS・別MCPホスト・マウス実物の適合と性能は本確認の対象外。0.1.0の配布物と確認記録は履歴として保持する。
