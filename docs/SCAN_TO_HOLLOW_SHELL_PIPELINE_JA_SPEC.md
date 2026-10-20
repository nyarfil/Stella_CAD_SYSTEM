# スキャンメッシュから中空の正式アセンブリまで: 再現仕様 (LH2 左手マウス v23f)

状態: 仕様書 (読み取りと記録のみ。コードは変更していない)。作成日 2026-10-13。
対象: オーナーの左手マウス殻を、スキャン(メッシュ)から正式中空アセンブリ v23f まで作った手順を、将来 StellaCAD MCP ツール化できる精度で記録する。

## 0. 日本語サマリ (オーナー向け)

- 結論: 工程の前半 (スキャン整形から上殻・底板の分割形状まで) は既存MCPツールでほぼカバー済み。後半 (中空化、クリック床、天板の一体化、ホイール窓、底板の縁と段、部品との干渉チェック) は手作業とエージェント主導のスクリプト(FreeCADCmd / build123d / OCP)で、MCPツールは未整備。
- 最重要の設計方針 (オーナー指示): 天板(クリック床)は「後から床を足して融合し、橋渡しして、継ぎ目を直す」方式で作った。これは不自然で、失敗要因(重なり、自己交差、継ぎ目)を生んだ。今後は「中実の上殻から、滑らかな単一の内側オフセット面で囲んだ一つの空洞を一回で削り出す」方式にする (第 8 章)。旧方式は legacy / fallback と位置付ける。
- 未決のオーナー判断: ブッシュ対 壁 83 mm3、PCB 18 mm3、座面(傾斜した基礎の下面)、後部の継ぎ目 (第 6 章)。推測では決めない。
- 数値の出典と注意: 壁 1.3 mm は「0.4 の倍数」ではない (0.4 x 3 = 1.2, 0.4 x 4 = 1.6)。オーナーの「0.4 の倍数」意図との整合は未確認で、第 6 章の質問に入れた。

## 1. Owner intent, in order (inferred from finished models vs the scan)

Frame used everywhere: front = +X, thumb side = -Y (left-hand build), bottom plate underside z = 0, mm.

| # | Intent | Evidence |
|---|---|---|
| 1 | Take the right-hand scan (PLY, ~60x82x92 mm class) to a clean, watertight mesh. Replace messy zones by design intent (smooth shape), not scan fidelity. | memory scan-to-cad successes 1-10 |
| 2 | Flush the bottom plate to z = 0, symmetrise only where truly near-symmetric, fill the cable pocket, rebuild click grooves and side-button pads. | tools scan_flush / symmetrise / cable_fill / click_grooves / side_buttons |
| 3 | Hand flip: mirror the WHOLE model (shell, plate, board data) to left-hand. Sensor/board data are derived by mirroring (LH sensor y = +0.07 from RH -0.07). | handedness_flip report, PLACEMENT_NOTES |
| 4 | Fit a smooth skin, close it to a solid top shell, cut click slots and wheel window, add side buttons. Plate side: one straight ruled side under the shell. | shell_fit, shell_solid, click_slots, side_buttons, plate_side |
| 5 | Split into three roles: top shell (outer skin), bottom plate, click region (two click plates L/R, split by a centre slot). | v8 -> v17 click_split.py |
| 6 | Hollow the top shell into a "foundation" with a 1.3 mm wall (owner wants printable walls, multiples of the 0.4 mm line; see open question Q6). | v19e_shell_foundation.step |
| 7 | Click plates 1.1 mm thick follow the skin; under each plate a floor 1.3 mm thick sits 1.0 mm below the plate underside; the plate is separated from the shell by a 0.5 mm groove; the centre slot between L and R is 1.0 mm. | v17 params, v23a floors |
| 8 | Make the top shell ONE seam-free solid: floors fused to the wall, centre slot bridged (the slot exists in the plates, not in the shell floor), single smooth top/underside faces. | v23c3 -> v23e1 |
| 9 | Wheel window sized from the real wheel with >= 0.3 mm clearance, widened rearward (v23f). | v23c2 comment, v23f_fix.py |
| 10 | Bottom plate hollow, floor 1.2 mm, bearing ledge 1.45 mm and tongue 1.1 mm high 1.2 mm with 0.15 mm clearance, stepped bearing height z0(x). | joint_params.json, v20a/v20b |
| 11 | Assemble with all 27 parts (board set, wheel, bush, switches); keep parts unmoved; report interference. | v22 manifest, v23f report |

Rules from the owner that constrain every step: sensor+lens+main PCB are one board set fixed to the bottom plate; main-switch boards mount on the top shell for split-type mice; bush end face flush with the outer skin; protected parts (PCB, switches, sensor, shell outer shape) are never moved to make a check pass; work step by step with the owner, no unrequested big analyses (memory mouse-internals-rules).

## 2. Step-by-step specification

Notation: P = parameter; V = validity check / acceptance number; F = failure mode and proven remedy.

### S1 Scan intake and clean (tools exist: brain_mouse_prepare_scan, scan_model, scan_clean)
- In: PLY/STL, mm (unit not in PLY header).
- Out: watertight decimated STL, cleaned STL, region labels.
- P: decimation target 71.2k faces (0.05 mm needs ~67-71.5k; 20k gives 0.15 mm); denoise optional (this scan sigma 0.0057 mm, so no effect); groove/rim cleanup with design_intent=true, straight grooves (centre gap w 0.816 / d 0.323).
- V: watertight, manifold, winding, single component; error vs welded original max 0.039 mm (target 0.05, hard 0.10); outside-zone deviation <= 0.009 mm; self-intersection is UNVERIFIED (checker over-reports: 975 vs 30).
- F: faceted_sdf fails SHELL_MESH_NOT_MANIFOLD (checkerboard cells in surface_nets; fix = ambiguity-resolving marching cubes or dual contouring); lower front lip / parting band is a real undercut slit that normal displacement cannot rebuild (rebuild by cut-and-fill).

### S2 Flush, symmetrise, cable fill, handedness (tools exist)
- flush: area-weighted RANSAC plate plane; tilt removed (0.2 deg here); plate to z = 0; returns transform + residuals.
- symmetrise: only passing regions/cells corrected (abs 2.0 mm / rel 0.015 x bbox diagonal as tool defaults for the coarse test); mirror plane from edge-sampled geometry: y_c = -0.01 mm, spread 0.015, median mirror distance 0.10-0.13 mm (sampling limited).
- cable fill: designed front wall is plain; pocket filled from trusted surroundings.
- handedness flip: mirror normal (0.00026, 0.99999, -0.00177), d = 0.0157 (RH scan); applies to shell, plate and derived board data.
- V: mirrored solid same volume, valid; side-button y = -27.3 / -27.1, click centroids y +9.84 / -7.50 (LH).

### S3 Skin, solid, slots, side buttons (tools exist: shell_fit, shell_solid, click_slots, side_buttons, plate_side, face_roles)
- Recipe B2 (verified earlier): star-shaped parametrisation of the smooth top skin, ONE cubic B-spline patch (no internal borders), trim 1 mm above bottom plate, planar cap. N=60 recommended: deviation mean/p95/p99/max 0.0035/0.013/0.035/0.28 mm; N=80 reaches 0.0018/0.0057/0.016 (max 2.93 at a 3.5 mm deep recess, only 0.14 % of points > 0.10 mm). Volume 144,874 mm3 (-0.10 % vs scan above cut).
- Cuts into the B-spline skin by OCCT 7.9.3 booleans: per-segment step retry (1.0, 0.7, 0.5, 1.5 mm), strict checks (BRepCheck valid, 0 <= removed <= cutter x 1.05, vol > 50 %), expected vs measured removed volume; lip slit 0.8 x 2.5 mm ok at step >= 1.0 (step 0.5 empties the solid, reject).
- Result frame for LH2: top shell filled solid `top_shell_solid_reference` 127,015 mm3 (bbox x -0.15..117.68, y +-30.26, z 1.84..36.63); owner-adopted plate frame.
- Sensor/board placement (PLACEMENT_NOTES): optical axis (63.09, +0.07) marker, centred on mirror plane y = -0.01, wheel halfway rule (-2.0175 mm), bush flush shift -0.2858 mm, then board +0.1 mm X: final sensor axis X 64.822+0.1 and tyre offset about -2.2 mm from window centre (accepted by owner).

### S4 Split: top shell / bottom plate / click region (automation/click_split.py, run_v17.py; tool missing)
- In: v8 shell (groove faces present), board assembly. Out: filled skin S_filled, shell open, plate_L/R.
- Manual input (NOT automated): groove fill `wip/S_skin_filled.step` (groove outer wall, 0.5 mm floor, inner wall faces removed; cap on shared skin B-spline; end caps on nose face; slot cap; sewn at tol 0.02, 0 free edges).
- P: groove 0.5 (outer groove = plate outline + 0.6 mm cut, depth only the plate layer); plate outline = footprint + 0.1 mm; plate thickness 1.5 (v11) then 1.1 (v17); plate-to-structure gap 1.7 (v11) then 1.0 (v17); recess cut = footprint + 0.6 down to skin offset -(t + gap) = -2.1; centre slot 1.0 (R ymin 0.49, L ymax -0.51 in v3 plates); wheel window 19.12 x 8.32, corner R 3.33 at (97.325, -0.01), cut through shell and plates; side-button gap 0.3.
- Detection thresholds (hard coded): floor width < 1.2, wall |nz| < 0.2, patch area > 300 mm2; outline margin 0.1; cutting slab top +5 mm above skin; auto centre line y = -0.0088.
- V: volume bookkeeping closes within 30 mm3 (script requirement; achieved ~10); L/R symmetry within 2 %; zero interference; one valid shell solid; >= 97 % of rays inside 1.1 +-0.002 (plate) and 1.0 +-0.01 (gap). v17 reproduction: all 28 solids match, max volume difference 0.017 mm3, bbox 0.0016 mm. v3 plates: normal-ray thickness 1.5000 over 1750/1736 rays.
- F (all proven):
  - Coincident or near-coincident faces: `S & prism` returned None, `S - T` silently no-op. Remedy: one smooth periodic spline outline offset +0.1 / +0.6; slabs start +5 mm above skin; plate top comes from S itself.
  - Offset surfaces: `Offset(S,-1.5)` fails; `Geom_OffsetSurface` booleans hang; `GeomConvert_ApproxSurface` max error 290 mm. Remedy: sample the true normal offset on a 161x161 UV grid, fit a C2 B-spline (GeomAPI_PointsToBSplineSurface, tol 2e-5; error < 1e-3 inside the click area); slab = two fitted faces + four ruled faces, sewn.
  - BRepGProp volumes on B-spline solids differ by ~100 mm3 between methods. Remedy: use mesh volume (deflection 0.003).
  - Projected patch edges miss by up to 0.02. Remedy: ShapeAnalysis_FreeBounds tol 0.02 then ShapeFix_Wire.
  - Silent failure rule: every boolean wrapper rejects None/empty result.

### S5 Hollow foundation, 1.3 mm wall (v19a -> v19e, then v21; tool missing)
- In: v18b closed shell (cache/v18b_shell.brep: faces list, parting plane), z0(x) bearing profile. Out: `v19e_shell_foundation.step` (10,452.78 mm3, bbox x -0.15..117.68, y +-30.26, z 1.84..36.63).
- P: wall 1.3 mm normal to skin (inner face = outer skin offset -1.3); foundation bottom = flat cut at z0(x) (same function as the plate ledge); z0 levels: x >= 76 -> 2.0; 52 -> 2.5; 36 -> 3.1; 24 -> 4.2; 12 -> 5.5; < 12 -> 6.9, joined by linear ramps of total width 2|dz| (26.6 deg).
- V: wall thickness statistics on the seam bands (v21 wall.py: wall_stats, tol 0.005, samples 1500-4000) must show min >= 1.3 - tol everywhere except documented bands; 1 solid; valid after STEP round trip.
- F: thick-solid of the shell via BRepOffsetAPI_MakeThickSolid with selected faces works only for part of the faces (t1.py experiment); the foundation was built from face groups and glued (v21: three pieces front/middle/rear, `out/glued.step`), left L-lip faces F22/F25 self-intersecting at x 72-78.5 (defeats OCCT booleans). Remedy used: station-wise pieces that skip x 63..80 for L (v23b1_final PIECES L = (0,63),(80,155)) and `fix(0.01)` in FreeCAD.
- Status: the exact v19e construction script was not recovered in this reading (it lives in the 50bca0d9 session scratchpad: f19*.py, v18/v19 caches). Treat construction details here as partially documented.

### S6 Click floors (legacy build, v23a; see section 8 for the replacement)
- Script automation/click_floor.py (usage `L|R`, grid NG = 121). In: click plate STEP (v22_parts 26/27). Out: `v23a_click_floor_{L,R}.step`.
- Method: take the plate underside B-spline face (largest, most downward normal); sample normal offsets D1 = 1.0 and D2 = 2.3 mm (floor thickness 1.3 = D2 - D1, gap 1.0) on NG^2 grid, fit C2 B-splines (tol 2e-5), project the plate outline into the offset surfaces' UV space (rebuild edges as 2D B-splines, 3D curves via BuildCurves3d), sew top face + bottom face + ruled side faces, ShapeFix_Solid; subtract the window prism.
- Skipped edges: window notch (87.7 <= x <= 107 and |y + 0.01| > 0.52) and tab edges entering the slot (|y + 0.01| < 0.45); loop clipped to |y + 0.01| >= 0.485; bridged by 30-point lines.
- V: valid, 1 solid after window cut; mesh volume; STEP round trip count/valid/volume; projection error < 5e-3 (fix attempts) and < 2e-2 (assert).

### S7 Fuse floors into the foundation, bridge the slot (v23b1 -> v23c3; LEGACY / fallback)
- v23b1 extension strips (per floor edge station): INSET 0.3, SKIN 0.15, PEN 0.34, TH 1.3, DS 0.4 (sampling), YMIN 0.70; corners Tp = P - 0.3 e - 0.15 n, Bp = P - 1.3 n - 0.3 e + 0.15 n; strip = 4 C2 B-spline edges (GeomAPI_PointsToBSpline, common chord-length parametrisation, tol 0.003-0.01, STEP 2 stations) + ruled faces + end caps -> solid.
- Overlap trick: every added solid overlaps material by 0.2-0.34 mm (SKIN 0.15 / PEN 0.34 / bridge OV 0.3 into each floor at the slot, DEL 0.03 shrink in z so no faces coincide), never touches face to face.
- v23c2 bridges (rear x 70.02..88.4, front 106.4..117.19): z(x) taken by ray intersection with the floor top/bottom faces at y = yin -/+ 0.3, linear extrapolation from 5 end points, top -0.03, bottom +0.03.
- Fusion order and gating: wall_fixed -> ext_R -> ext_L -> bridge_rear -> bridge_front -> gap strip. Accept each fuse only if 1 solid, valid, and volume = a + b - common within 2.0-2.5 mm3; random point-in-solid test (N samples) `inside(result) == inside(a) or inside(b)` with bad <= max(2, N/500).
- Final window cut in FreeCAD: box 19.64+ (x 87.22..106.885, y -0.01 +- 4.16, fillet R 3.33 on the 4 vertical edges), `fix(0.01, 0.01, 0.01)` then `removeSplitter()`; single solid, round trip.
- F: OCCT fuse with self-intersecting L-lip faces fails; remedy = FreeCADCmd fuse + ShapeFix 0.01 + removeSplitter. Slot-flush (v23d1) and seamless refit (v23e1: single-face B-spline top/underside refit to kill the seam bands) were the last two manual repairs; their scripts are in the session scratchpad and were not recovered here.

### S8 Wheel window (v23c2 comment, v23f_fix.py)
- Parameters: original 19.12 x 8.32 r 3.33 at (97.325, -0.01), window x 87.77..106.88. v23c2 widened to x 87.22..106.885: rear edge 87.22 = wheel intrusion 87.52 minus 0.30 (the >= 0.3 mm rule; wheel_part2 clearance rule). v23f widened a further DELTA = 0.8 mm rearward (tool box x from 87.22 - 0.8 = 86.42 to 92, rear vertical edges filleted R 3.33, half width 4.16).
- V: for every part near the window (x 80..112, |y| < 12, wheel*): common volume with the shell and distance. Official result: rear clearance 0.52 / 0.54 mm (NOTES); other 27 parts unchanged (max volume/position change 0 by script check).
- F: v23e wheel_part2 intrusion at the rear edge (hence 0.8 mm widening).

### S9 Bottom plate (v20a/v20b, joint_params.json, plate_v20b/params.py)
- Hollow plate adopted: `bottom_plate_OFFICIAL_v20a.step` 7,280.96 mm3, floor 1.2 mm, bbox x -0.15..113.80, z 0..7.15.
- P: ledge = 1.45 mm measured normal to the skin from the outer skin inward (1.3 wall + 0.15 clearance; horizontal chord ~1.8 at the sides), flat bearing face at z = z0(x), outer edge flush with the skin; tongue from skin 1.45 to 2.55 (width 1.1), height above z0 = 1.2, top z0 + 1.2, clearance to foundation inner face 0.15; offset surfaces from a skin radial model (s8_offlev.py), station table at x = 5, 18, 30, 44, 60, 70 ... (ledge top z = z0(x), tongue top = z0 + 1.2).
- V: plate and foundation common volume 0 and gap = 0.15 +- tolerance at stations; bottom flat z = 0.

### S10 Assembly and interference report (v22 manifest, v23*_asm.py)
- Build: replace one solid in the labelled flat assembly; all other 27 solids unchanged (assert max volume/centre change 0); export STEP AP242 compound; import back and compare labels/volumes.
- 28 solids in OFFICIAL v23f: 27 unchanged parts from v22c + `top_shell` (volumes in v22_parts/MANIFEST.md).
- Interference report with every part: top_shell common volume (> 0.01 mm3 listed). Official open results: bush vs wall 83 mm3, main_pcb_8 vs shell 18 mm3, click_plate L/R ~0.3 mm3 (overlap).

## 3. Numbers cheat-sheet (all in mm)

| Parameter | Value | Why |
|---|---|---|
| plate thickness | 1.1 (v17 on; 1.5 earlier) | printable thin click plate, owner-adopted |
| groove (plate-shell gap) | 0.5 | visible split, plate outline +0.1, groove outline +0.6 |
| centre slot | 1.0 (+-0.5) | L/R separation; exists in plates, bridged in shell floor |
| plate-to-floor gap (click gap) | 1.0 (1.7 then 1.5 then 1.0) | pre/post-travel clearance, tuned |
| click floor thickness | 1.3 (D2 2.3 - D1 1.0) | same as wall |
| foundation wall | 1.3 | owner wall; open Q about 0.4 multiples |
| plate floor | 1.2 | bottom plate hollow floor |
| ledge | 1.45 | wall 1.3 + 0.15 clearance |
| tongue | 1.1 wide, 1.2 high | interlock, 0.15 clearance |
| side-button gap | 0.3 | pad groove clearance |
| window | 19.12 x 8.32 r 3.33; widened rear | wheel + >= 0.3 clearance; v23f -0.8 |
| overlap tricks | 0.15-0.34 mm (SKIN 0.15, PEN 0.34, OV 0.3, DEL 0.03) | booleans overlap into material, never coincident |
| dedupe/fuse tolerances | sew 1e-4 / 2e-3 / 0.02; ShapeFix 0.01; fit tol 2e-5 / 0.003 | see S4-S7 |
| mesh volume deflection | 0.003 | consistent volumes |
| fuse acceptance | 2.0-2.5 mm3 volume mismatch | v23b1/v23c2 gating |

## 4. Mapping to existing MCP tools

| Pipeline step | Existing tool | Coverage |
|---|---|---|
| S1 intake, clean | brain_mouse_prepare_scan, scan_model, scan_clean | done (self-intersection UNVERIFIED; lip undercut not fixable) |
| S2 flush / symmetrise / cable fill / hand flip | scan_flush, scan_symmetrise, scan_cable_fill, handedness_flip | done |
| click grooves / slots | scan_click_grooves (layout), click_slots (cut into solid: depth 2.0 default, walls vertical, floors follow local surface minus depth, smooth 1.5) | partial: cuts grooves, not the hollow + floor concept |
| side buttons | scan_side_buttons | done for pads and grooves; gaps 0.3 not restored in v3 plates |
| skin, solid | shell_fit, shell_solid (G0/G1 front tube + cap) | done for RH; LH by flip |
| face roles | face_roles | done (helps S5, S9 detection) |
| plate | plate_side (one ruled side) | partial; no hollow, ledge, tongue |
| S4 split / plates | none (click_split.py outside repo) | MISSING |
| S5 hollow foundation | none | MISSING |
| S6-S7 floors, fuse, bridge, seams | none (scripts) | MISSING; superseded by section 8 |
| S8 window from wheel | none | MISSING (click_slots has window params only) |
| S9 hollow plate ledge/tongue | none | MISSING |
| S10 assembly + interference | brain_fusion_*, brain_import_step | partial; no interference report with acceptance |

## 5. Proposed new tools (ordered by value / effort)

Common contract: inputs are workspace STEP/STL paths; outputs under mouse/cad/<id>/, never overwriting; each tool returns a JSON report with `evidence` (numbers below), `verdict` READY/PARTIAL/STOP, and never reports a pass without the numeric check. All OCCT work in a subprocess worker like the existing scan_*_worker pattern.

1. `brain_mouse_carve_shell` (highest value, large effort): single-pass carve-from-solid hollowing (section 8).
   In: shell_step (filled closed solid), plate_step_or_footprints, wall_mm=1.3, plate_thickness_mm=1.1, click_gap_mm=1.0, floor_mm=1.3, groove_mm=0.5, slot_mm=1.0, windows[] (wheel, side buttons; each a prism/outline with clearance), z0_profile, mirror_plane.
   Out: hollow_shell.step (one solid), cavity.step (for debugging), report.json.
   Evidence: solid count, valid, free edges, seam edge count in slot band, wall thickness stats (min/p05/mean), floor thickness stats, deviation of cavity from ideal offset (max/p95), volume bookkeeping, STEP round trip.
2. `brain_mouse_interference_report` (high value, low effort): In: assembly STEP (labelled solids) + optional keep-out list; Out: per pair common volume, min distance, location, flagged protected parts; Evidence: counts and the listed numbers (e.g. bush 83, PCB 18); never moves parts. Also a `diff` mode against a baseline assembly (max volume/position change).
3. `brain_mouse_wheel_window` (high value, low effort): In: shell STEP, wheel solid (or board STEP + names), clearance_mm=0.3, corner_radius_mm=3.33, mode `rect_from_wheel|widen_rear(delta)`; Out: shell with window, report; Evidence: per-part common and distance, rear clearance, window x range, one solid, valid.
4. `brain_mouse_split_click_region` (medium value, medium effort): groove-aware click footprint + plate carve: In: shell with grooves (or S_filled), plate_thickness, groove, slot, gap; Out: S_filled, plate_L/R, shell_open; Evidence: ray thickness stats (plate 1.5000 style), 0 interference, symmetry within 2 %, bookkeeping residual.
5. `brain_mouse_plate_joint` (medium value, medium effort): hollow bottom plate with ledge/tongue from the shell's inner offset and z0(x): In: shell STEP, plate STEP, wall, clearance 0.15, ledge 1.45, tongue 1.1 x 1.2, floor 1.2, z0 steps; Out: hollow plate, joint_params.json; Evidence: gap at stations, common = 0, bearing face contact areas.
6. `brain_mouse_wall_audit` (medium value, low effort): thickness map for a hollow solid by two-sided ray casting; In: solid STEP, outer skin STEP/faces, target wall (1.3), tolerance; Out: histogram, min locations; used also as acceptance of carve_shell.
7. `brain_mouse_groove_fill` (medium value, medium effort; removes the manual S_skin_filled input): remove groove faces and cap on the shared skin B-spline; Evidence: free edges 0, sew tol 0.02, volume added.
8. `brain_mouse_assembly_swap` (low-medium value, low effort): replace one labelled solid keeping all others bit-identical; Evidence: max change of other parts = 0.
9. `brain_mouse_seam_audit` (medium value, low effort): list edges in a given band (rear skin seam y ~ 0, slot band) and face count per band; Evidence: edge count, G1 deviation across seams.
10. `brain_solid_boolean_safe` (support, medium effort): wrapper with retry steps (1.0, 0.7, 0.5, 1.5), overlap-into-material helper (0.2-0.3 mm), expected-vs-measured volume gate, random point-in-solid test, and a FreeCADCmd fallback (fuse, ShapeFix 0.01, removeSplitter). Used by all above.

Build first (value per effort): (1) interference_report, (2) wheel_window, (3) wall_audit; then the big one carve_shell, which also needs wall_audit as its acceptance test.

## 6. Open decisions owned by the owner (not guesses)

- Q1 Bush vs wall, 83 mm3 interference: shape the wall around the bush, move the board (changes the owner's flush rule), or trim the bush? Which part is protected?
- Q2 main_pcb_8 vs shell, 18 mm3: PCB is protected; wall pocket or shell edge offset? Decide.
- Q3 Bearing face (the slanted foundation bottom against the plate ledge): keep the stepped flat z0(x) bearing, or redefine to the slanted skin-parallel face? Unresolved.
- Q4 Rear skin seam lines (y ~ 0): accept as cosmetic, refit single-face, or move the seam? Unresolved.
- Q5 click_plate L/R ~0.3 mm3 overlap with shell: accept (overlap trick) or true clearance?
- Q6 Wall 1.3 mm is not a multiple of 0.4. Intended wall: 1.2 (3 lines), 1.6, or 1.3 as is? Same for plate 1.1, floor 1.3, floor 1.2.
- Q7 L lip self-intersections not fully repaired: repair by redesign or accept?
- Q8 Side-button gaps (0.3, raised caps) and windows in the carved shell: confirm geometry and positions.
- Q9 Whether the click floor stays flat-following-the-skin or follows an ideal plate-parallel offset (smooth transitions at the edges).

## 7. Honest limits: what was manual or agent-driven, not yet deterministic

- Manual/hand input: groove fill (S_skin_filled.step), board placement decisions (sensor axis, wheel halfway, bush flush), parking of side/click boards, grouping in Fusion, wheel window position, window widening amount (0.8), wheel clearance judgement.
- Agent-driven, iterative: v19 foundation (5+ variants a, b, d, e, f), v21 three pieces, v23b1 strips (station by station, two sides, L skipped x 63..80), v23b2 sequences s1-s3 with gap handling, v23c3 FreeCAD fuse, v23d1 slot flush, v23e1 seamless refit, v23f1 widening. The v19e foundation build, v23c1 wall repair, v23d1, v23e1 scripts were not located in the files read for this document; only their outputs and the lineage are documented.
- Heuristic/hard-coded: detection thresholds, margins, station tables, loop skip rules (window notch, tab edges), L lip piece ranges, input paths.
- Unverified: scan_clean self-intersection count; official part has known self-intersections near the L lip; ray thickness 0.12-1.5 within 0.7 mm of window edges (steep wall); bookkeeping tolerances of ~10 mm3.
- Not deterministic across runs: OCCT fuse results depend on tolerances and orientation; every acceptance check above is therefore a runtime gate, not an assumption.
- Reproduction evidence: only click_split (run_v17) was reproduced against saved output (28 solids, 0.017 mm3 max).

## 8. Carve-from-solid redesign (owner direction, top-level requirement)

Owner observation: the top plate (天板) with click floors was built by force: hollow first, then floors added, fused, bridged and seams repaired. It looks unnatural and failed repeatedly. New target: carve from the solid in one go.

### 8.1 Why the add-on approach failed (evidence from this build)
- Coincident / near-coincident faces: fuse and common returned None or silent no-ops; remedy needed overlap tricks (0.15-0.34 mm) and DEL 0.03 shrinks.
- Self-intersecting foundation faces F22/F25 (L lip, x 72-78.5): OCCT fuse fails; pieces skipped x 63..80; FreeCAD ShapeFix needed.
- Seams: every added strip, bridge and floor leaves shared edges; slot band and rear skin (y ~ 0) show seam bands; v23d1/v23e1 repairs refit single faces by hand.
- Bookkeeping fragility: BRepGProp volumes jump ~100 mm3; each fuse needs a volume gate and random point tests.
- Order dependence: result depended on the fuse order (R, rear bridge, L, front bridge, gap strip) and on tolerance choice.

### 8.2 Target process
1. Start from the filled top-shell solid S (outer skin, grooves/side buttons as designed; 127,015 mm3 reference).
2. Define ONE cavity solid C whose boundary is a single smooth surface:
   - Away from the click region: skin offset -1.3 mm (normal), down to the bearing cut z0(x).
   - Under each click plate: surface = plate underside offset by -(1.0 + 1.3) = -2.3 mm (the floor top is 1.0 below the plate underside; the floor is 1.3 thick; the cavity ceiling under the plate is the plate-gap region, i.e. the cavity extends up to plate underside offset 1.0; below that the floor material remains). Equivalent statement: cavity ceiling = min over {skin - 1.3 outside the click region; plate underside - 1.0 under it}; floor thickness 1.3 is the separation between the cavity top surface and the skin recess surface below the plate.
   - Transition between the two regimes: a smooth blend (fillet radius to be set, start 2.0 mm, to be tuned against the printable limit) along the click footprint boundary rather than a step.
   - The centre slot does not exist as a groove in the floor: the floor surface is continuous across y = 0 (the slot exists only in the plates).
   - Wheel window and side-button windows: part of the same cavity definition (prisms with clearance, window 19.12 x 8.32 r 3.33 widened rearward as required by S8; side-button window gaps 0.3), cut as the same boolean step.
3. Result = S - C (and window prisms), single boolean from solid inputs. Floor and wall are one continuous material: no add, no fuse, no overlap, no seam steps.

### 8.3 Cavity construction (two options)
- A (B-rep first): cavity ceiling as ONE loft/B-spline surface fitted from sampled normal offsets (161x161 UV grid, C2, tol 2e-5; same fit machinery as click_floor.py but over the whole skin patch including click region), blended by smooth max/min in the height field (or a fillet transition), side walls = skin offset -1.3 fitted the same way; close with the bearing plane z0(x); build cavity as sewn shell -> solid, then ONE cut. The cut tool starts away from coincident faces (extend the cavity 0.5 mm below the bearing face).
- B (mesh first, then fit): compute the cavity as a signed-distance level set (offset -1.3 from skin, minus plate-gap region), extract with marching cubes with ambiguity resolution at voxel <= 0.1 mm, fit one B-spline skin (star-shaped or patch fit, tol 0.02), then cut. Use B as a fallback when A fails the validity gate.
- Acceptance numbers: cavity vs ideal offset deviation max <= 0.02 mm (B-spline fit) and p95 <= 0.01; wall >= 1.3 - 0.02 everywhere; floor 1.3 +- 0.02 under plates.

### 8.4 Tool signature (new)
`brain_mouse_carve_shell(shell_step, plate_step?, wall_mm=1.3, floor_mm=1.3, click_gap_mm=1.0, plate_thickness_mm=1.1, groove_mm=0.5, slot_mm=1.0, bearing_profile=[{x_from, z0}...], windows=[{type: wheel|side_button|other, outline, clearance_mm, depth: through}], blend_radius_mm=2.0, method=brep|mesh_fit|auto, mirror_plane?)`.
- Out: `hollow_shell.step` (one solid), `cavity.step`, `report.json`.
- Report fields: solid_count, valid, free_edges, seam_edges_in_slot_band (count), seam_edges_total, wall_thickness {min, p05, mean}, floor_thickness {min, mean}, cavity_deviation {max, p95} vs ideal offset, volume_removed (expected vs measured), step_round_trip {solids, valid, volume_delta}, windows[{id, clearance_min, interference}], verdict.

### 8.5 Acceptance checks
- Exactly 1 solid, valid after STEP round trip; 0 free edges.
- No seam edges in the slot band |y| <= 1.0 over the click x range, and none along the rear skin line (y ~ 0); count reported (target 0).
- Wall >= 1.3 - 0.02 mm outside the click region; floor 1.3 +- 0.02 under plates; plate-to-floor gap 1.0 +- 0.02 (ray method as in v17: >= 97 % of rays).
- Cavity deviation vs ideal offset max <= 0.02 mm.
- Volume bookkeeping: removed volume matches expected within 2 mm3 (mesh volume deflection 0.003).
- Window clearance >= 0.3 mm to the wheel (rear 0.52 mm reference), zero interference with protected parts (reported, never moved).
- Run time and tolerance parameters recorded; same inputs return the stored report.

### 8.6 Legacy / fallback
Steps S6 (click floor slabs), S7 (extension strips, bridges, fuse, gap strip, removeSplitter) and the v23d1 slot-flush / v23e1 seamless refit are LEGACY. Keep only as a fallback when carving fails, with the overlap / volume-gate / FreeCADCmd remedies from the failure list. The official v23f remains the approved reference for comparison: the carved result must match it within the deviation numbers above or improve its seam situation.

## 9. References (read for this spec)

- V:\mouse\LH2-mouse\work\internals\official\OFFICIAL_v23f_NOTES.md, PLACEMENT_NOTES.md, v22_parts\MANIFEST.md, automation\NOTES.md, click_split.py, click_floor.py, v23b1_*.py, v23c2_bridge.py, v23c2_unify.py, v23f_fix.py, wip\joint_params.json.
- Session scratchpad scripts: s3run.py (FreeCAD fuse chain), v21\fin.py (assembly + wall seam stats).
- Memory notes: scan-to-cad-successes, mouse-internals-rules, lh-official-assembly-v23f.
- Existing tools: cadmcp_brain/studio scan_*.py docstrings (flush, symmetrise, cable_fill, click_grooves, click_slots, side_buttons, shell_fit, shell_solid, plate_side, handedness_flip, face_roles).
