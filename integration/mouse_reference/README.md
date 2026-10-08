# マウス参照メッシュの測定

提供されたSTLを変更せず、機構理解に使う寸法と接続情報をJSONへ記録する。
完成CAD生成、STL修復、単位変換、組立姿勢の推定は行わない。

使用する依存ライブラリーはNumPy。ユーザー環境ではcadgen 0.6.5のPythonを利用する。

```powershell
& 'C:\Users\nikis\.codex\user-runtimes\cadgen-0.6.5\Scripts\python.exe' `
  'E:\aiwork\Stella_CAD_SYSTEM\integration\mouse_reference\inspect_stl.py' `
  'E:\WINDOWS\Y\Download\zs-f1-3d-printed-finalmouse-ultralight-2-x-starlight-small-mouse-g305-model_files' `
  'E:\aiwork\Stella_CAD_SYSTEM\docs\examples\zs_f1_g305_mesh_measurements.json'
```

接続成分は1e-5座標単位で頂点座標を丸めて接続した結果。文字や重なる形状も独立成分になる場合があるため、成分数は機能部品数ではない。境界辺・非多様体辺がゼロでも自己交差・組立干渉・変形・強度は検証されない。

機能との対応・作者ガイドの出典・未確定事項は `docs/REFERENCE_ZS_F1_G305_MOUSE_JA.md`、StellaCAD入力の参照例は `docs/examples/zs_f1_g305_function_brief.example.json` に記録する。これらは参照資料であり、MCPに搭載済みのG305実形状や検証済みの製品CADではない。

追加の参照測定:

- `measure_planar_interfaces.py SOURCE OUTPUT_JSON`: 軸方向の平面にある円境界を抽出する。穴と外周は自動分類しない。
- `align_primary_clicks.py SOURCE REPORT_JSON PREVIEW_STL`: ZS-F1の左右取付穴中心を使った姿勢候補を復元する。専用の特徴選択を含むため他モデルへの汎用適用は禁止。原本外へのプレビュー出力のみ。
- `inspect_board_reference.py STEP OUTPUT_JSON`: STEPの形状別外接寸法と円弧/全円の境界を区別して記録する。cadgenとOCPを使う。
- `align_board_reference.py BOARD_JSON BOTTOM_JSON BOARD_STL REPORT_JSON PREVIEW_STL`: 2つの全円穴と2つの開放溝の中心を底部の4ねじ軸へ剛体で照合する。単位とボス上面支持の仮定、非ゼロ残差を保持する。BOARD_STLは対象STEPからcadgenで出力した一時メッシュを指定する。
- `measure_click_chords.py TRIGGER_STL POSE_JSON OUTPUT_JSON`: 候補姿勢で84点の鉛直材料区間を測る。原本のパス・ハッシュを姿勢レポートへ照合し、法線肉厚・曲げ支点・力・復帰とは区別する。
- `plot_click_chords.py REPORT_JSON OUTPUT_PNG`: 区間をサンプル棒として表示する。Pillowを使用し、連続断面や肉厚分布として補間しない。
- `measure_click_normal_chords.py TRIGGER_STL POSE_JSON OUTPUT_JSON`: 同じ84点で最上面の三角形法線から内側へ交差線を投射する。表裏が局所的に平行な候補と非平行の交差を区別するが、最小肉厚・固体の妥当性・機能部の同定は証明しない。

出力例は `docs/examples/zs_f1_g305_planar_boundaries.json` と `zs_f1_g305_click_mounting_pose.json`。基準中心の数値一致は、隙間・干渉・弾性・実物適合の検証とは区別する。

## 任意ハードウェアの初期検査

`inspect_hardware_intake.py SOURCE_STEP OUTPUT_JSON` はStella側CadQuery環境で実行する。原本を変更せず、SHA、STEPヘッダ、単位宣言、実際の読み込み単位、各ソリッドの妥当性・体積・外接寸法を記録する。列挙番号から部品名を推定しない。基板全体が複数ソリッドでも板だけが別ソリッドの場合がある。出力は未承認入力の記録で、ready Board Packや動作保証にはしない。

例: `V:/mouse/op18kv2pcb_251212.step` → `docs/examples/op18_alternate_hardware_intake.json`。21ソリッドの形状妥当性を確認済み。物理版・部品機能・光学基準・配置は未確定。スキャン由来とは認定していない。
