# Core development state (handoff)

Branch `claude/project-thread-jqv4yf` (draft PR #2, base `cursor/vendor-sidecar-cad-engines`).
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
- r14 leaf print-in-place (4 blocking), r15 single-leaf carrier (blocking: carrier location, twist threshold), r16 parallel leaves (0 blocking), r17 vertical pins + preload + outside insert (0 blocking, 14 major). No subject has reached an accepted 5-role review yet.

## Open r17 review findings (verification/side-button-flow-r17-20261008/reviews-r1)
- Leaf stress margin 3 % (16.15 vs 16.7 MPa); no hard stop protects the leaves before the switch is fitted or while inserts are pressed.
- Carrier angle set by two pins about 4 mm apart: a 0.05 mm hole error tilts it about 0.26 deg and moves the far end about 0.24 mm, more than the 0.1 mm rest preload; Z located only by pin friction.
- Switch overtravel beyond the guaranteed minimum is not checked (stack ignores OT; pressing to pin flush exceeds it); bottoming rating UNKNOWN.
- Insert: no extraction feature; retention only by friction against the switch's outward force.
- PCB keep-out text wrong (moving pad crosses the assumed board plane at x -9 to -6.5).
- Checks stop at 1.52 mm, not the 1.62 mm pin-flush pose that includes the preload; yaw only at 0.3 mm.
- Supports for the carrier incomplete; pin-hole wall 0.83 mm in the block; upper-tab blind holes open downward.

## r18 plan
1. Rest lug becomes a separately printed shim (thickness series chosen at assembly) so the preload no longer depends on carrier placement.
2. Shell C-bracket with a lower lug as a hard stop at about 1.72 mm CAD travel (protects leaves; also takes insert press-in).
3. Leaves 0.5 +/- 0.05 mm, flexure judged at +tolerance; declare carrier placement tolerance (+/-0.05 mm, +/-0.26 deg) on key clearances.
4. Insert head pull slot; retention UNKNOWN with a first-article pull-out test; OT beyond the guaranteed minimum reported as UNKNOWN rating.
5. Pin wall fix, through holes in the upper tab, full support list, measured PCB keep-out, checks to deep+preload, yaw at the deep pose.
Then build, run the 5-role review, and report. If r18 does not reach acceptance, report to the coordinator before further subject iterations.

## Assumptions in force (ASSUMED / UNKNOWN)
- ASSUMED: press-force band 0.3-3 N; stress allowance half of the ABS tensile strength; stress concentration 1.5 at R1 fillets; Poisson ratio 0.35; edge press 3 N; PCB plane placed from the Zippy profile; print orientations; press-fit interferences 0.03-0.05 mm.
- UNKNOWN: fatigue and creep of printed ABS; switch bottoming rating; Huano/Kailh geometry; real PCB and shell; OP1 screw size; pin/insert retention force.

## Next steps after r18
- Report "what the system can now do" to the coordinator (session_01GnHdA119EyChgR9VrE9XVp), Japanese, short.
- Then the in-house encoder (held-out evaluation against the text search; keep the old path selectable, no fallback).
- Next 4 (port of the Req2CAD checkpoint) stays blocked: upstream weights are not published.
