# Stella Viewer (最小版)

Fusionを使わずにモデルを確認するための、ローカル専用の3Dビューアです。読み取り専用で、127.0.0.1 だけで動きます。

```
python integration/stella-viewer/server.py --root <モデルのフォルダ>
```

ブラウザで http://127.0.0.1:8765/static/cad.html (STEP用) または /static/index.html (STL等のメッシュ用) を開きます。

- 対応形式: STEP / STP / STL / PLY / OBJ / GLB。STEPは既存のOCP（build123d環境またはcadMCP環境）で変換し、結果を一時フォルダにキャッシュします。変換用の環境は自動検出、`--step-python` で指定もできます
- 機能: 回転・拡大、軸ごとの断面（スライダー）、ワイヤ表示、外形寸法の表示、ファイル更新の自動再読み込み（3秒間隔）
- 外部コード: three.js r186 (MIT)、詳細は NOTICE.md
- 未実装: 断面の蓋、寸法測定

## STEP表示ページ (cad.html)
- three-cad-viewer 5.1.3 (MIT) を使用。STEPのアセンブリ構造・名前・色を保ったまま表示します。
- 面・辺の選択、距離測定（最小距離・座標・角度）、プロパティ表示、3軸の断面（蓋付き）、ツリーでの表示切替、Materialタブ。
- 変換は `step_to_shapes.py`（OCP）。結果は一時フォルダにキャッシュされます。9 MBのSTEPで約2秒。
- 距離測定は「mesh based」（三角形に基づく概算）です。厳密な寸法は `BRepExtrema` による数値検査で確認すること。
- 測定ツールは既定で非表示です。コンソールから `__viewer.showMeasureTools(true)` で出します（画面ボタン化は未実装）。

## MCP (段階2) — `mcp_server.py`
build123d-mcp の venv で動く stdio MCP。`.mcp.json` の `stella-viewer` に登録。
- `viewer_snapshot(path, view, clip, width, height)` — ヘッドレスEdgeでビューアを撮影しPNGを返す（STEPは断面の蓋つき）。
- `step_info(path)` — bbox・ソリッドごとの体積/面積/重心。
- `step_distance(path, solid_a, solid_b)` — 厳密な最小距離（接触時は重なり体積）。
- `step_thickness(path, solid)` — 光線法の肉厚統計。
実測: ZA13_Z30_assembly.step (186 MB) は step_info 約136秒、thickness 約70秒、snapshot（初回変換込み）約90秒+。変換結果はキャッシュされる。
