# Stella Viewer (最小版)

Fusionを使わずにモデルを確認するための、ローカル専用の3Dビューアです。読み取り専用で、127.0.0.1 だけで動きます。

```
python integration/stella-viewer/server.py --root <モデルのフォルダ>
```

ブラウザで http://127.0.0.1:8765/static/index.html を開きます。

- 対応形式: STEP / STP / STL / PLY / OBJ / GLB。STEPは既存のOCP（build123d環境またはcadMCP環境）で変換し、結果を一時フォルダにキャッシュします。変換用の環境は自動検出、`--step-python` で指定もできます
- 機能: 回転・拡大、軸ごとの断面（スライダー）、ワイヤ表示、外形寸法の表示、ファイル更新の自動再読み込み（3秒間隔）
- 外部コード: three.js r186 (MIT)、詳細は NOTICE.md
- 未実装: 断面の蓋、寸法測定
