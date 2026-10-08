# Core development state (handoff)

Branch `claude/project-thread-jqv4yf` (draft PR #2, base `cursor/vendor-sidecar-cad-engines`); follow-up work on `claude/project-thread-b07n52` (stacked on it).
Never merge or mark ready without the owner. Package root: `cadmcp-all-in-one-2026-09-17/01_CURRENT`.
Python env used: `/tmp/claude-0/venv` (CadQuery 2.8). Full suite: `python -m pytest -q -p no:cacheprovider` (614 passed at b3687c6, about 14 min).

## Owner decisions so far (binding)
- The goal is the Stella CAD SYSTEM; the side button is only a pipeline test subject. Do not ask the owner product questions; use ASSUMED/UNKNOWN labels.
- ABS only. No screws except those supplied with the OP1.
- Leaf-spring (compliant) buttons preferred; hinge kept as an alternative, no automatic fallback.
- Self-tapping M2 pilot holes are acceptable (screw cuts its own thread). Hinge-pin reaming not confirmed.
- Outer-shape changes are allowed only around the side buttons when a base shape exists (enforced by `base_shape_checks`).
- Support several switch types (Zippy DF3, Huano, board-vendor options, OP1's Kailh GM 2.0).
- Side buttons: separately printed insert pins preferred over snap hooks; main clicks are screw-fastened.
- In-house geometry encoder (train on the ~176k Req2CAD records) is LAST in the queue.

## System capabilities added (all tested)
- `switch_profiles.py`: cited datasheet values (Zippy DF, OMRON D2F manufacturer sheets); Huano and Kailh GM 2.0 values UNKNOWN -> reported unverified, never passed.
- `materials.py`: Polymaker PolyLite ABS (TDS V5.6, default), Prusament PETG/PLA; Z bending and ABS yield are N/A -> UNKNOWN, never substituted.
- Recipe checks: `base_shape_checks` (blocking), `flexure_checks` (free/guided ends, parallel leaves, force band incl. switch forces, stress with stated concentration, Saint-Venant twist, `thickness_tolerance_mm` worst case), rotation and translation checks with `carried_parts`, translation `expect: blocked`, `placement_tolerances` + `tolerance_ids` on clearance/motion/rotation checks (rigid corner sweep).
- `mechanism_templates.py`: `cantilever_main_click` (OP1 screw, size UNKNOWN, M2 placeholder), `flexure_side_carrier` (insert pins default, snap hooks alternative with a strain check).
- Uncommitted before this file: placement tolerances and flexure thickness tolerance (committed together with this file).

## Test subject history (scripts/side_button_recipe.py, scripts/side_button_leaf_recipe.py; flow scripts/check_side_button_flow.py --revision N)
- r1-r13 hinge (r13 multi-switch, click-referenced screws; uses purchased screws -> conflicts with the owner policy, kept as an alternative).
- r14 leaf print-in-place (4 blocking), r15 single-leaf carrier (blocking: carrier location, twist threshold), r16 parallel leaves (0 blocking), r17 vertical pins + preload + outside insert (0 blocking, 14 major).
- r18 (commit 1fd2825; evidence verification/side-button-flow-r18-20261008): rest lip preloaded on the inner skin, printed stop jaw keyed into a shell post 0.5 +/- 0.1 mm after rest, carrier located by two pins 15.7 mm apart (block + tongue) on an upper-tab Z datum, leaves 0.6 +/- 0.05 mm, ASSUMED PCB slab, placement-tolerance corners on key clearances, overtravel beyond the guaranteed minimum reported as UNKNOWN. All 157 geometry checks pass.
- r18 5-role review round 1 (Opus subagents, not independent): NOT ACCEPTED. assembly revise (1 blocking, 4 major), mechanism revise (1 blocking, 4 major), manufacturing no blocker (4 major), requirements no blocker (2 major), verification no blocker (1 major, 10 minor). Studio status: overall_verdict unknown, peer challenge (round 2) not run. The verification review cited recipe.json, which is not a packet attachment; that one inspection entry was removed before submission (noted inside the file).
- Owner decision: the test subject is CAPPED AT r18. Do not iterate further on it.

## Open r18 findings (verification/side-button-flow-r18-20261008/reviews-r1*, for the system lessons)
- Blocking (assembly A1, mechanism B1): stack_v18 "clicks before the stop" ignores the declared carrier yaw (+/-0.18 deg) and far-end-press yaw; probe gives 0.31 mm rest-to-stop at the corner vs a 0.32 mm worst click. Lesson for the system: tolerance stacks must take every declared placement tolerance, and the stop must be checked under the rotation checks (obstacles omitted the jaw/post).
- Single far-end stop lets a near-end press pivot about the stop (leaf buckling / extra travel); stop tab, post floor (0.5 mm walls) and jaw key have no declared load or strength check; stop_post and stop_jaw not wall-checked; 0.03 mm key fit is in the layer direction.
- At the stop + tolerance the insert reaches the switch body (switch takes force at nominal values, not only in a corner); insert-vs-body check only ran to the nominal stop.
- Insert retention still friction-only under a standing pin force; pin press fits exceed ABS strength (no sizing route, press force unbounded); Z datum held by friction and is a support-interface face; back-stop lip on the wrong side of the preload.
- Face recess at rest (0.3 mm) not stated or checked; counterbore placed from an ellipse approximation (1.8 mm deep, not 1.0); blocked-motion checks can pass on a touching-face kernel artifact; sweeps sampled too coarsely to bracket the stop; carrier-insertion threshold lowered to 0.01 mm over the whole path (should be split by leg); minimum-force check cannot fail as posed.

## Assumptions in force (ASSUMED / UNKNOWN)
- ASSUMED: press-force band 0.3-3 N; stress allowance half of the ABS tensile strength; stress concentration 1.5 at R1 fillets; Poisson ratio 0.35; edge press 3 N; PCB plane placed from the Zippy profile; print orientations; press-fit interferences 0.03-0.05 mm.
- UNKNOWN: fatigue and creep of printed ABS; switch bottoming rating; Huano/Kailh geometry; real PCB and shell; OP1 screw size; pin/insert retention force.

## Test-suite state
- Full suite: 616 passed at 12a2e01 (807 s). After r18 (1fd2825) only the new/affected tests were run: 3 passed (r18 build-and-checks, r18 contract, flow brief). Full suite not rerun after r18.

## Model delegation rule (owner, 2026-10-08)
- Subagents: "sonnet" for routine work (running/triaging tests, bulk edits with a clear spec, schema regeneration, docs, datasheet lookups, and the 5-role reviewers: a different model family also eases the independence caveat); "haiku" for trivial lookups. Opus only for architecture, geometry/mechanism design and judging review findings.
- So far in this thread all subagents (including the r18 reviewers) ran on Opus; the rule applies from now on.

## Next-steps queue (owner: side-button subject capped at r18; work moves to the owner machine)
1. Rerun the full suite on the owner machine.
2. System fixes suggested by the r18 findings (no new subject revision): tolerance stacks that take all declared placement tolerances; placement corners on rotation checks; blocked-motion checks robust to touching faces; sweep sampling that brackets a declared stop; load/strength checks for stops and press fits; checks against the real skin surface instead of an ellipse approximation.
3. Mouse plan stage A (02_DOCUMENTS/planning/mouse_mcp_architecture_2026-09-16.md): scan -> hollow solid pipeline.
4. Freeform / class-A surface quality checks (curvature continuity, zebra-style metrics).
5. In-house encoder last (held-out evaluation against the text search; old path selectable, no fallback). Next 4 (Req2CAD checkpoint port) stays blocked: upstream weights not published.
6. Report "what the system can now do" to the coordinator when work resumes.

## Session 2026-10-08 (owner machine, branch claude/project-thread-b07n52)
- Python env on the owner machine: `01_CURRENT/.venv` (CadQuery 2.8, OCP 7.9, torch CUDA, RTX 4080 SUPER).
- Full suite on Windows first failed 49 tests: Git autocrlf rewrote the hash-pinned public fixtures. Fixed with `examples/public-cases/.gitattributes` (`* -text`).
- Queue 2 (r18 lessons, system only, subject untouched): design `docs/design/R18_SYSTEM_LESSONS.md`. Tolerance coverage audit (checks on toleranced parts missing a declared tolerance become unverified unless waived) and `stop_travel_checks` (rotation load cases, bisection to first stop contact, placement corners). On r18: min plunger travel at stop 0.366 mm vs 0.32 required, margin -0.054 mm with the declared 0.10 mm stop print tolerance -> FAIL; 25 existing r18 checks now unverified. Did not reproduce the reviewers' 0.23-0.31 mm (stop faces kept nominal in geometry). `verification/r18-system-lessons-20261008/RESULT.json`.
- Queue 3 (scan -> hollow shell): A1 faceted SDF route (`docs/design/SCAN_TO_SHELL_A1.md`, `studio/scan_mesh.py`, `scan_shell.py`, tools `brain_mouse_prepare_scan`, `brain_mouse_build_shell_brep`). Mouse-like 120x64x38, t=2, voxel 1.0: 72k faces, 98 s, outer deviation 0.049 mm, wall min 1.996, PASS; default voxel 0.5 exceeds the face budget (reported, not coarsened). A2 smooth route (`route="smooth_fit"`, `studio/scan_fit.py`): MakeThickSolid dropped (breaks at rim corners); inner skin fitted separately from the SDF phi=-t. Small case PASS at grid 121 / fit tol 0.03; mouse scale FAILS outer deviation near the rim (0.165 vs 0.15 at grid 201). Open: rim-region fit (e.g. rim-aware parametrisation or a separate rim band patch).
- Queue 4 (surface quality): `docs/design/SURFACE_QUALITY_CHECKS.md`, `studio/surface_quality.py`, `scripts/surface_quality.py`. OP1_Shell_NEW.step: FAIL (worst G1 21.3 deg, G2 rel 1.98, 135 internal-knot findings); zebra/curvature images via vtk offscreen. Profile thresholds ASSUMED. Not yet wired as an MCP tool.
- Queue 5 (geometry encoder): data was already present at `E:/aiwork/Stella_CAD_SYSTEM/cadmcp-workspace/knowledge/req2cad` (176k cases, DeepCAD tar, Qwen vectors). `docs/design/GEOMETRY_ENCODER.md`, `req2cad/geoenc_core.py`, `geoenc_run.py`, `brain_fs_search(mode="geometry_encoder")`. Held-out: encoder nDCG@10 0.245 vs handcrafted kNN 0.257 vs random 0.092 -> NOT accepted; shipped `experimental`. `benchmarks/results/geometry_encoder_v1.*`.
- Next: A2 rim fit; wire surface quality as a tool and run it on A2 output; encoder v2 ideas (B-rep/point features, larger model) only with a new evaluation.
