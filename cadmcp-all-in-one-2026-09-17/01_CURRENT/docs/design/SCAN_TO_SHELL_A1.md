# Scan -> hollow shell, stage A1 (faceted route) — design

Source plan: `../02_DOCUMENTS/planning/mouse_mcp_architecture_2026-09-16.md` sections 3, 4, 7, 8, 10 (stage A).
Status vocabulary: every check reports PASS / FAIL / UNVERIFIED; execution success is a separate field.

## Scope
A1 turns a closed scan mesh of a mouse outer shape into a valid, open-bottom hollow B-rep solid of
requested wall thickness, with measured deviation and thickness. It is the "faceted B-rep" tier of
plan section 3. The smooth B-spline route (A2) is a later, separate route and is NOT a fallback of A1.
No silent approximations: when a step cannot meet its declared tolerance, the run stops with a code.

Dependencies: numpy, scipy, OCP (all already in the project venv). No new packages.

## Module layout
- `cadmcp_brain/studio/scan_mesh.py` — pure numpy/scipy: read, weld, inspect, allowed repairs, exact
  point-to-mesh distance, inside test, signed distance field, surface-nets extraction.
- `cadmcp_brain/studio/scan_shell.py` — orchestration + OCP B-rep build + checks + exports + report.
- Tools in `MouseToolsMixin` (`studio/mouse.py`): `brain_mouse_prepare_scan`, `brain_mouse_build_shell_brep`.
  Follow the existing worker/subprocess pattern used for CadQuery/OCP measurements if one exists.
- Outputs go under `<workspace>/mouse/scans/<scan_id>/` (never next to or over the source file).

## 1. prepare_scan
Input: `relative_path` (STL binary/ASCII; OBJ optional), `unit` ("mm" | "cm" | "m" | "in", REQUIRED,
no guessing), optional `transform` (16 floats, same convention as `board_to_world_transform`),
`repairs` (allow-list, all default off): `weld_tolerance_mm`, `remove_degenerate`,
`drop_components_below_fraction` (by area), `orient_outward`, `fill_holes_max_perimeter_mm`.
Report (JSON, stored as `prepare_report.json` with source sha256, settings, code version):
- triangle/vertex counts before and after weld, bbox in mm, surface area, signed volume.
- Unit sanity: a mouse-sized bbox is 30-200 mm on the long axis; outside that -> warning
  `UNIT_SUSPECT` (never rescale automatically).
- Edges: boundary edges, boundary loops (holes) with perimeters, non-manifold edges.
- Connected components (area per component), degenerate triangles, orientation consistency
  (every interior edge used once in each direction), outward orientation (signed volume > 0).
- Self-intersection: `UNVERIFIED` unless a check is implemented; do not report as PASS.
- Every repair actually applied: what, how many elements, max vertex displacement, filled area.
  Hole filling (fan or ear-clip on the loop) only for loops under the declared perimeter limit;
  the filled area is reported as "surface not measured by the scan".
Verdict `prepared_status`: READY (closed, 2-manifold, consistently oriented, one component after
allowed repairs) else NOT_READY with the blocking reasons. Output: `prepared.npz` (vertices,
faces in mm, after transform) + report.

## 2. build_shell_brep (route "faceted_sdf")
Input: `scan_id`, `thickness_mm` (> 0), `opening`: `{type: "plane", point: [x,y,z], normal: [..]}`
(material kept on the side opposite the normal; the cavity is open through that plane — for a mouse
the bottom plane with normal -Z), `voxel_mm` (default 0.5), `outer_tolerance_mm` (default 0.15),
`thickness_tolerance_mm` (default 0.1), `max_faces` (default 60000), `max_voxels` (default 40e6).
Refuse with a code when the grid exceeds `max_voxels` (`SCAN_GRID_TOO_LARGE`) or prepared status is
not READY (`SCAN_NOT_READY`).

Steps:
1. Grid: axis-aligned, padding >= thickness + 3 voxels; record origin, spacing, shape.
2. Inside mask: ray parity along +Z per (x, y) column, vectorized by binning triangles into
   columns; robust to rays hitting vertices/edges (jitter the column x/y by a fixed tiny epsilon,
   deterministic). Cross-check parity along X for a random fixed-seed subset; mismatch rate > 0.1%
   -> `SCAN_INSIDE_TEST_UNSTABLE`.
3. Signed distance phi (outside +, inside -): coarse from `scipy.ndimage.distance_transform_edt`
   on both masks, then EXACT point-to-triangle distance for every grid node within 2 voxels of
   the iso values used (phi ~ 0 and phi ~ -t); candidate triangles via `cKDTree` on triangle
   centroids with radius = query distance + max triangle circumradius. Sign from the mask.
4. Shell field psi = max(phi, -(phi + t), plane_sd) where plane_sd is the signed distance to the
   opening plane, positive on the removed side. Material is psi <= 0.
5. Extract the psi = 0 surface with surface nets (one vertex per sign-changing cell, placed at the
   mean of linear-interpolated edge crossings; quads split into triangles along the shorter
   diagonal; consistent outward orientation). Vertices whose active term of psi is plane_sd are
   projected exactly onto the plane (keeps the opening rim flat). Must be closed and 2-manifold;
   otherwise `SHELL_MESH_NOT_MANIFOLD` (report non-manifold counts, do not patch silently).
6. Face budget: triangle count > `max_faces` -> stop `BREP_FACE_BUDGET_EXCEEDED` (report count and the
   voxel size that would fit, never coarsen automatically).
7. B-rep: one planar face per triangle (shared vertices/edges built once, not sewn by tolerance
   where avoidable; `BRepBuilderAPI_Sewing` with tolerance <= voxel/100 acceptable), shell ->
   solid, `ShapeFix_Solid` orientation only, then `ShapeUpgrade_UnifySameDomain` to merge
   coplanar faces (the opening plane becomes one ring face). `BRepCheck_Analyzer` must pass and
   the shape must be one closed solid, else `BREP_FIT_FAILED` with the diagnostic mesh written.
8. Export `shell.step`, `shell.stl`, `shell_mesh.npz`, `build_report.json`.

## 3. Checks (each PASS / FAIL / UNVERIFIED with numbers)
- `brep_valid`, `single_closed_solid`, face count, build time, peak voxel count.
- `volume_consistency`: |V_brep - V_mesh| / V_mesh <= 1e-6.
- `outer_deviation`: sample >= 20k points (fixed seed, area-weighted) on the output faces whose
  active term was phi (outer skin); exact distance to the prepared scan mesh; report max, p99,
  mean; PASS if max <= outer_tolerance_mm. Also the reverse direction (scan points above the opening
  plane -> output outer skin) so missing regions are caught.
- `wall_thickness`: sample points on the inner skin; exact distance to the scan mesh; report min,
  p1, mean; PASS if min >= t - thickness_tolerance_mm. Label as "sampled minimum, not a global
  minimum" (plan section 8).
- `locally_solid_regions`: grid cells inside the scan whose depth (-phi) never reaches t along
  their medial region, i.e. connected inside components of {phi < 0} that contain no node with
  phi <= -t; report count and volume. Not a FAIL by itself; reported as a fact (plan 4.2).
- `opening_present`: the solid has a planar face on the opening plane with at least one inner wire,
  and the cavity volume (V_scan_above_plane - V_solid) > 0.
- `self_intersection`: carried over from prepare (UNVERIFIED unless checked).
- `edit_suitability`: always reported as "faceted B-rep: boolean/export ok if checks pass; not a
  smooth surface model" — surface-quality metrics do not apply to this route.
`design_status` is PASS only if every blocking check is PASS; UNVERIFIED blocks PASS.

## 4. Reproducibility
Same inputs + settings + code version -> identical `shell_mesh.npz` hash (deterministic seeds,
no threading nondeterminism in the mesh path). Report includes all settings and hashes.

## 5. Tests (fast, synthetic; no network)
- Analytic shapes: sphere, box, mouse-like superellipsoid cut flat at the bottom; tessellated
  meshes written as STL in tmp. Expected thickness and deviation within tolerance; known volumes.
- Defect meshes: hole (boundary loop) -> NOT_READY; non-manifold edge; flipped triangles
  (fixed only when `orient_outward` allowed); two components; wrong unit (metres) -> UNIT_SUSPECT;
  thin fin thinner than 2t -> locally_solid_regions > 0; face budget exceeded -> code.
- Determinism test (two runs, same hash).
- Optional slow test (marked) on `V:/mouse/OP1-PCB/stock-shell/Lightweight Mod.stl` if present:
  prepare only (it is an already-hollow shell, so expect the inspection to report it, not a pass).
