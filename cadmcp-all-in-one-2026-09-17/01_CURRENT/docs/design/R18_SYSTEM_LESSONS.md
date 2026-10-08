# System fixes from the r18 blocking findings — design

The side-button subject stays capped at r18 (owner decision). These are recipe-check changes in
`cadmcp_brain/studio/recipe.py` so that the two r18 blocking findings (assembly A1, mechanism B1)
are caught by the system itself instead of by reviewers. Success = the r18 recipe, re-checked with
the new checks added, reports FAIL on the stop-vs-click margin, with measured numbers.

## Fix 1 — tolerance coverage audit (blocking)
Problem: a check on a toleranced part could silently omit a declared placement tolerance
(stack_v18 omitted the carrier yaw).
- For every clearance / translation / rotation / stop-travel check whose `moving_part` or any
  `carried_parts` is in a declared `PlacementTolerance`'s parts, every such tolerance id must be in
  the check's `tolerance_ids`, or listed in a new optional field
  `tolerance_waivers: [{id, reason (min 10 chars)}]` on that check.
- Missing without waiver -> that check's verdict becomes `unverified` with
  `reason: 'declared placement tolerance not applied: <ids>'` (blocks overall pass; never pass).
- Waived ids are listed in the result as `waived_tolerances` with the reason (reported, not hidden).
- Raise `tolerance_ids` max_length from 4 to 8 (the declared list allows 8).
- Read the existing `PlacementTolerance` model first and use its actual field names for "parts".

## Fix 2 — `stop_travel_checks` (new check kind)
Problem: the stop was proven by a hand stack along a pure translation; rotation (carrier yaw,
far-end press yaw) shortens the travel at the plunger; rotation checks left the stop parts out.
Model `StopTravelCheck(Strict)`:
- `id`, `moving_part`, `carried_parts` (as translation checks), `stop_obstacles` (parts that form the
  hard stop, >=1), `other_obstacles` (optional; any contact with these before the stop -> fail).
- `load_cases`: 1..6 entries, each `{id, rotation: {axis_point, axis_direction, angle_deg} | null,
  direction: unit vector, max_travel_mm}`. Pose(s) = apply the rotation (rigid, about the given
  axis, the load-case's press-induced yaw) at s = 0 then translate by s * direction, s in
  [0, max_travel_mm]. (Rigid approximation; scope string must say elastic deformation is excluded.)
- `reference_point`: [x, y, z] on the moving part (e.g. the plunger tip) in the part's frame.
- `reference_direction`: unit vector; the reported travel is the displacement of the reference
  point projected on this direction from the rest pose (no rotation) to the first stop contact.
- `required_min_travel_mm` (> 0) + `requirement_source` (text, e.g. 'worst-case click 0.32 mm
  from switch profile + insert rule'), and `margin_mm` (>= 0).
- `resolution_mm` (default 0.005): first contact with a stop obstacle is located by sampling then
  bisection on s until the bracket is <= resolution; contact = min distance <= `contact_tol_mm`
  (default 0.002) or overlap > 0. Report the bracket [s_clear, s_contact] and the obstacle.
- `tolerance_ids`, `tolerance_waivers`: evaluated at every placement corner exactly like the existing
  rigid corner sweep (reuse its corner generation).
Verdict per (load case x corner): pass if the stop is reached within max_travel, no
`other_obstacles` contact happens before it, and reference travel at contact >=
required_min_travel_mm + margin_mm. Check verdict = worst. Report the minimum reference travel,
the governing load case and corner, and the margin left (may be negative). If no stop contact
within max_travel -> fail ('stop not reached').
Wire into recipe validation (part names exist, no overlap between stop_obstacles and
other_obstacles and carried parts, unit vectors), into the result list, and into the overall verdict
the same way the existing motion checks are. Update the JSON schema export if the repo generates one
(look for a schema regeneration script/test).

## Fix 3 — demonstration on r18 (no subject change)
New script `scripts/check_r18_system_lessons.py`: load the r18 recipe exactly as
`scripts/side_button_leaf_recipe.py` builds it (import, do not copy or edit the subject), add
(a) a stop-travel check with load cases: centre press (no rotation), carrier yaw +/- (the declared
+/-0.18 deg about the leaf-tip axis the recipe already uses for its yaw checks), far-end press yaw
(the recipe's declared 0.32 deg case); reference point = the plunger contact point at x of about 2
as used in the recipe; stop_obstacles = stop_jaw (and stop_post if that is the contacted part);
required_min_travel = the recipe's worst-case click (rest_above_op upper bound 0.32 mm) with
margin 0; tolerance_ids = all declared placement tolerances; (b) run the tolerance coverage audit on
the existing r18 checks. Write `verification/r18-system-lessons-20261008/RESULT.json` and print a
short summary. Expected (not to be forced): the stop-travel check FAILS with minimum reference
travel around 0.23-0.31 mm vs 0.32 mm required, and the audit marks some existing checks
unverified. Report what actually comes out.

## Tests
Synthetic, fast: a block on a stop post where pure translation passes but a yaw load case reduces
reference travel below the requirement -> fail with the expected number (analytic within
resolution); a missing tolerance id -> unverified; a waiver -> reported and not unverified; stop not
reached -> fail; an `other_obstacles` contact before the stop -> fail; validation errors.
