# Freeform / class-A surface quality checks — design

Purpose: measure, not eyeball, whether a B-rep's freeform surfaces are smooth the way a
professional surface model is (mouse shells: many blended freeform faces). Outputs numbers per
face and per shared edge, a verdict against a declared profile, and optional zebra / curvature
images for human review. Images never replace the numeric verdict.

Statuses: PASS / FAIL / UNVERIFIED per check; profile thresholds are labelled ASSUMED unless cited.
Dependencies: OCP (present), numpy, vtk (present, offscreen) for images. No new packages.

## Module
`cadmcp_brain/studio/surface_quality.py` with
`analyze_surface_quality(shape_or_step_path, profile="consumer_product", faces=None, samples=...)
-> dict` and `render_zebra(shape, out_png, ...)`, `render_curvature(shape, out_png, ...)`.
CLI: `scripts/surface_quality.py <step> [--profile] [--json out] [--zebra out.png] [--curvature out.png]`.

## Per face (non-planar faces; planes are listed but skipped for curvature)
- Surface type; for B-spline/Bezier: U/V degree, pole counts, knot vectors, rational flag.
- Internal knots with multiplicity >= degree (C0 crease inside the face) and == degree - 1 (only
  C1, so curvature jumps inside the face). Reported with knot value and direction.
- `GeomAbs_Shape` continuity of the underlying surface.
- Curvature sampling on a UV grid restricted to the trimmed face (classify each UV sample with
  `BRepTopAdaptor_FClass2d`; drop outside points; skip singular normals and report their count):
  principal curvatures k1 >= k2, mean H, Gaussian K; minimum convex radius and minimum concave
  radius; area fraction with K < 0 (saddle).
- Waviness along iso-lines (fixed number of U- and V-iso lines inside the face): normal curvature
  in the iso direction; count sign changes of its derivative (curvature extrema) per line after
  ignoring changes smaller than `waviness_noise` (relative to the line's curvature range).
  Report max and mean per face. A smooth designed patch typically has <= 2 extrema per line.

## Per shared edge (edges with two distinct adjacent faces; seams and degenerated edges skipped and
counted)
Sample N points by arc length along the edge (exclude 2% at each end). At each point use each
face's pcurve to get (u, v) on that face, evaluate with `BRepLProp_SLProps`/`GeomLProp_SLProps`,
orient normals by face orientation (TopAbs_REVERSED flips).
- G0 gap: distance between the two surface points (mm).
- G1 angle: angle between the oriented normals (deg).
- Edge class: `crease` if median G1 angle > `crease_angle_deg` (an intended sharp edge, not assessed
  for smoothness), else `smooth` (intended tangent) and assessed.
- G2: cross-edge direction c_i = normalize(n_i x t) chosen to point INTO face i (check with a small
  step in UV); normal curvature k_i along c_i from the second fundamental form. Reported:
  absolute jump |k_a - k_b'| where k_b' is face b's curvature along -c_b (the continuation
  direction) and relative jump = abs / max(|k_a|, |k_b'|, k_floor). k_floor (default 1e-3 1/mm,
  i.e. 1000 mm radius) prevents nearly-flat edges from producing huge relative numbers.
- Reflection-line (zebra) proxy per smooth edge: for three fixed light directions (X, Y, Z),
  stripe phase s = arccos(clamp(n . d)) on each side; report max phase offset (G1-type stripe
  break) and max difference of the cross-edge phase derivative (G2-type stripe kink).

## Profiles (ASSUMED values, no cited standard; reported with the result)
| profile | G0 mm | G1 deg | G2 relative | crease deg | internal knots |
|---|---|---|---|---|---|
| `class_a` | 0.005 | 0.05 | 0.05 | 10 | none with mult >= degree-1 |
| `consumer_product` (default) | 0.01 | 0.1 | 0.10 | 10 | none with mult >= degree |
| `mechanical` | 0.02 | 0.5 | not assessed | 10 | not assessed |
Checks: `g0_smooth_edges`, `g1_smooth_edges`, `g2_smooth_edges` (UNVERIFIED for `mechanical`),
`internal_knots`, `waviness` (info only: reported, never PASS/FAIL until a threshold is cited or
the owner sets one). Overall `surface_quality_status` PASS only if every assessed check passes.
Results list the worst 20 edges/faces with ids, location (mid point xyz) and numbers.
Faceted (all-planar) models: return `NOT_APPLICABLE` with the reason, never PASS.

## Images (review aids)
- Zebra: tessellate (`BRepMesh_IncrementalMesh`, fine deflection), exact per-vertex normals from
  the surfaces, stripe = sin(freq * arccos(reflect(view, n) . axis)) > 0, render offscreen with vtk
  to PNG from a fixed set of views (top, left, right, front-iso).
- Curvature: per-vertex mean curvature colour map (clipped at a stated radius range).

## Tests
- CadQuery box with filleted edges: plane-cylinder edges G1 PASS, G2 FAIL (curvature jump 0 -> 1/r).
- Sphere / single smooth B-spline patch: PASS, no smooth edges assessed (count reported).
- Two B-spline patches joined C2 (same knot structure, continuous control net) -> G2 PASS;
  same pair with the shared row rotated by ~1 deg -> G1 FAIL with ~1 deg reported.
- B-spline surface with an interior knot of multiplicity = degree -> `internal_knots` FAIL.
- Faceted solid -> NOT_APPLICABLE.
- Slow, skipped when absent: `V:/mouse/OP1-PCB/stock-shell/OP1_Shell_NEW.step` (3541 planes, 213
  B-spline, 33 cylinders, 7 tori): runs to completion and produces numbers + images (no verdict
  assertion).
