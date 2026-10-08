# Scan -> hollow shell, stage A2 (smooth B-spline route) — design

A1 (`SCAN_TO_SHELL_A1.md`) gives a valid faceted B-rep, but at mouse scale it is heavy (about 72k
faces, about 100 s at a 1 mm voxel) and not a smooth surface model. A2 is the quality route: one
pair of smooth B-spline surfaces (outer skin = scan, inner skin = distance t from the scan) on the same
rays, closed by a planar ring on the opening plane. No offset operation is used. It is selected explicitly (`route: "smooth_fit"`); A1 and A2 never fall back to
each other.

## Applicability (checked, never assumed)
- Prepared scan READY; opening is a plane. The shape above the plane must be star-shaped from a
  centre point C on the opening plane (every ray from C into the upper half-space leaves the surface
  exactly once). Typical mouse bodies satisfy this; a non-star shape stops with
  `SMOOTH_FIT_NOT_STAR_SHAPED` (report the fraction and the directions of failing rays).
- C: the centroid of the scan's cross-section at the opening plane (area centroid of the section
  polygon). Rays are cast in a scaled frame (x/a, y/b, z/c with a, b, c the half-extents of the part
  above the plane) so parameters spread evenly; geometry stays in mm.

## Parametrisation without a pole
Square (u, v) in [-1, 1]^2 -> unit disk by the elliptical grid map
(x = u*sqrt(1 - v^2/2), y = v*sqrt(1 - u^2/2)) -> upper unit hemisphere
(z = sqrt(1 - x^2 - y^2)) -> ray direction (unscaled by a, b, c). The square boundary maps to the
equator, i.e. to the section curve on the opening plane, so the patch boundary lies on the plane and
there is no pole at the top. Record that the four square corners are parametric singular points
(rim corners); they lie on the plane boundary.

## Fit
1. Grid N x N (default 121, max 201) of ray hits: exact ray/triangle intersection with the prepared
   mesh (vectorised; reuse `scan_mesh` helpers). Rows on the boundary are snapped exactly onto the
   plane.
2. `GeomAPI_PointsToBSplineSurface` approximation with degree 3-5, continuity C2, tolerance =
   `fit_tolerance_mm` (default = outer_tolerance_mm / 2), using the smoothing variant (weights for
   length/curvature/torsion criteria) when `smoothing` > 0 (default small, stated). Report pole
   counts, knots, degree. No interior knot may reach multiplicity >= degree.
3. Inner skin (replaces the offset): on the same rays from C (same directions, same (u,v)) find the point at distance t from the scan
   (phi = -t of the signed distance field, phi = -unsigned distance inside the scan). Implemented as bracketing + bisection on a fast
   nearest-sample distance, then Newton steps on A1's exact point-to-mesh distance (not trilinear phi); the exact residual is reported.
   A ray with no crossing (locally solid) -> `SMOOTH_FIT_LOCALLY_SOLID` with the directions; no fallback. The inner points are fitted
   with the same degree/knot settings as the outer surface.
4. Outer face, inner face (reversed), and one planar ring face on the opening plane bounded by the outer rim wire and the inner rim wire
   (boundary rows of both surfaces snapped onto the plane); sew -> shell -> solid. `BRepCheck_Analyzer` must pass without healing;
   if `ShapeFix_Solid` is needed it is listed in `repairs_applied` and judged on the final shape (`SMOOTH_FIT_BREP_INVALID` otherwise).
5. Export `shell_smooth.step`, `shell_smooth.stl`, report.

## Checks (same vocabulary as A1; reuse A1 functions)
- `brep_valid`, `single_closed_solid`, face count (expect about 4: outer, inner, rim ring, ...).
- `outer_deviation` both directions vs the prepared scan above the plane: PASS if max <=
  `outer_tolerance_mm`; else `SMOOTH_FIT_OUT_OF_TOLERANCE` is reported as FAIL (do not loosen or
  densify automatically; report the grid size used and the worst location).
- `wall_thickness` sampled on the inner face vs the outer B-spline face (and vs the scan) with
  the "sampled minimum" label.
- `opening_present` (planar ring face on the opening plane).
- `surface_quality`: run `studio/surface_quality.analyze_surface_quality` on the outer face with
  the `consumer_product` profile; include internal knots, curvature ranges, waviness; the rim edge
  is a crease (outer-to-plane) and is reported as such.
- `fit_report`: grid size, degree, poles, smoothing weights, max residual at the grid points.

## Tool
`brain_mouse_build_shell_brep(..., route="faceted_sdf" | "smooth_fit")`; the default stays
`faceted_sdf` for compatibility; the route is recorded in the report. Extra args for smooth_fit:
`grid`, `degree_min`, `degree_max`, `fit_tolerance_mm`, `smoothing`.

## Tests
- Mouse-like superellipsoid from `tests/scan_shapes.py`: PASS, outer deviation within tolerance,
  wall min >= t - tol, surface_quality internal_knots PASS, face count small.
- A non-star-shaped mesh (e.g. a C/U-shaped body seen from C) -> `SMOOTH_FIT_NOT_STAR_SHAPED`.
- Tolerance too tight for the grid (e.g. 0.001 mm on a noisy mesh) -> FAIL reported, not loosened.
- Determinism (two runs identical STEP-independent hash of poles).

## Implementation notes and measured findings (2026-10-08)
Module `cadmcp_brain/studio/scan_fit.py`; report `build_report_smooth.json`, files `shell_smooth.step/.stl`, `fit_surface.npz`.
- Frame: up = -opening normal, plane at local z = 0. Interior rays: exact ray/triangle hits with angular candidate culling; equator
  rays: exact 2D hits on the section polyline (boundary rows lie exactly on the plane). Star-shape is verified on the grid rays only.
- Defaults: grid 121 (max 201), degree 3..5, `fit_tolerance_mm` = outer/2, `smoothing` 0 (plain approximation). `smoothing` > 0 selects the
  OCCT smoothing variant with equal (length, curvature, torsion) weights; it is not the default.
- Residual and deviations are closest-point distances (dense 241x241 tessellation of the fitted surface; the 60 worst points
  re-measured by a bounded local minimisation on the B-spline), not parameter-space residuals.
- Extra checks beyond the spec: `inner_skin_extent` (inner skin must not extend below the plane), `fit_knots` (per direction),
  `face_structure`, `step_roundtrip`, spline-based wall thickness. The sewn two-surface solid is valid without healing in all measured cases (`repairs_applied` empty).
- Why the offset route was dropped (first implementation): the four square corners are singular for ANY single-patch parametrisation whose
  boundary is one smooth closed curve (P_u and P_v are collinear there). The outer part was fine, but `BRepOffsetAPI_MakeThickSolid`
  (Arc join) returned an invalid raw shape (IntersectingWires, healed by ShapeFix with wrong geometry) and a wall thinner than requested
  near the rim corners (down to 1.3-1.6 mm of 2.0; in other settings the inner skin ran below the opening plane or the inner face was missing).
  Join `Intersection` does not hollow at all; degree 3, tight fit tolerances and smoothing > 0 gave a null shape or a construction error.
- Two-surface route, measured (superellipsoid meshes n=40, 19.2k triangles, t = 2, degree 5x5, no repair, 3 faces, brep_valid PASS,
  surface_quality PASS with internal_knots PASS and G0/G1/G2 UNVERIFIED because the rim edges are creases):
  - mouse-like 24x14x9 (plane z=-5), grid 121, default fit tol 0.075: poles 24x33 (outer), 28x39 (inner), 51 s, outer deviation 0.161 / 0.164 mm
    (FAIL vs 0.15), wall min 1.935 (scan) / 1.895 (outer spline) FAIL vs 1.9. Grid 201: 0.124 / 0.136, wall spline min 1.877 (FAIL).
    Grid 121 with fit tol 0.03: poles 32x45, 60 s, deviation 0.113 / 0.122, wall 1.967 / 1.914: all blocking checks PASS.
  - mouse scale 120x64x38 (plane z=-8.5), fit tol 0.04: grid 121, 53x51 poles, 56 s, deviation 0.150 / 0.190 (FAIL), wall 1.957 / 1.958 PASS;
    grid 201, 128x75 poles, 147 s, deviation 0.115 / 0.165 (FAIL), wall 1.956 / 1.946 PASS. Residual error is concentrated near the rim.
  The default settings are therefore not enough for PASS at mouse scale; denser grid and tighter `fit_tolerance_mm` are the user's
  decision per run, nothing is densified or loosened automatically.
