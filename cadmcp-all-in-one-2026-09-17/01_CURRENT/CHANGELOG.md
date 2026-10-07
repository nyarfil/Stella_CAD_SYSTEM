# 0.3.3 — Official MCP release (2026-09-20)

- Publish the Codex project MCP configuration, Design Skill, Factory OS handoff, and the shared Cursor/Codex cadMCP implementation as the current official software release.
- Include typed Studio planning, principle-reference routing, bounded CAD acceptance, project protection, evidence-state handling, delivery consistency checks, review contracts, and the 505-test regression baseline (2 Windows symlink skips).
- Preserve known boundaries: a software release is not CAD review acceptance, mouse-mechanism completion, physical-performance certification, clean-install proof, or a competitive benchmark.
- Runtime model/image/STEP traces remain local evidence and are intentionally not included in the GitHub source release.

The older `Unreleased` headings below are retained as development-history sections for the same 0.3.3 release.

# Unreleased — §22 side-button flow and measurement robustness (2026-10-07)

- Add `scripts/check_side_button_flow.py` and `scripts/side_button_recipe.py`: the design-doc §22 flow through the real Studio tools (intent, function decomposition, Req2CAD search recorded as unavailable when no encoder is configured, first-principles morphology and synthesis, typed recipe, worker build, role packets, separate review submission and delivery). The switch is an explicit placeholder; physical feel stays unverified.
- Add `volume_integration_agreement` (`_system-volume-agreement-<part>`): OCCT's default volume integration is several percent off on B-spline lofts and grossly wrong on offset surfaces left by hollowing, although the B-rep is valid. Verdict volumes now use adaptive integration and must agree with an independent triangulated volume. Trace volumes use the adaptive value.
- Reject Boolean results that violate set-volume monotonicity (a cut that grows material was observed on spline shells) instead of trusting them.
- `shell` converts offset faces to B-splines after hollowing so its material invariant is measured correctly. Interference overlap volume takes the largest of the default, adaptive and triangulated estimates.
- Add `wall_checks` (`sampled_wall_thickness`): inward-normal rays from a UV grid on every face; only exits through a roughly opposing face count as wall, oblique wedge exits are reported separately. A sampled observation, not a proof of minimum wall. Frozen in correction lineage and autopilot guards. It caught a 0.7 mm hinge barrel in the first side-button draft.
- Add optional `end_max_distance_mm` to rotation checks: the end pose must actually reach a hard stop or contact, not merely stay clear.
- Rotation checks gain `expect: blocked` (the motion must collide within the sweep: proves a rest stop or hard stop exists) and `axis_play_mm` (the sweep is repeated at eight radial axis shifts: a hinge-play envelope). Translation checks gain `start_translation_mm` so multi-leg assembly paths (slide, then drop) can be checked leg by leg.
- Side-button revision 8 (`side_button_recipe_v8`, flow `--revision 8`): stop screw back low beside the spring on a 4 mm tab, square jam nuts locking the stop and rest screws, stroke set with a depth gauge before the PCB, and the placeholder housing at the assumed stem bottoming depth so the switch travel limit is backed by a hinge-play check.
- Side-button revision 7 (`side_button_recipe_v7`, flow `--revision 7`): screw-adjusted rest and hard stops (M2 grub screws, two-way, set after assembly), a grub screw closing the spring pocket, and the far window edge cut normal to the hinge radius so the running gap holds while pressing; switch and spring selection limits stated.
- Raise the motion and rotation check capacity from 8 to 16 per recipe (a count limit, not a threshold).
- Side-button revision 6 (`side_button_recipe_v6`, flow `--revision 6`): chamfered barrel rim with a full-rise hinge-play check against the inner skin, purchased dowel plug, blind dowel hole as depth stop, deeper link, per-part manufacturing processes, and stated support, finishing and rest-face calibration steps.
- Add declared `press_fits`: an intended interference between two named output parts, verified as a rigid overlap-volume band instead of the zero-overlap rule. Undeclared pairs keep the zero-overlap rule; declarations are frozen in correction lineage and autopilot guards.
- Side-button revision 5 (`side_button_recipe_v5`, flow `--revision 5`): declared press fits for the dowel and spring plug, gaps on a 0.2 mm layer grid, chamfered stop-web bed edges, a back stiffener, and the switch position window stated in the contract.
- Rotation checks gain `start_deg` and `start_translation_mm`: a sweep can begin past a rest contact (so a blocked result can only come from the intended stop) or with axial/radial play already taken up (pin tilt checks).
- Side-button revisions 3 and 4 (`side_button_recipe_v3`/`_v4`, flow `--revision 3|4`): revision 3 reached zero blocking findings in five-role review; revision 4 addresses its major findings (tilt and axial play, spring fitted last through a through pocket, one printing bed plane, press-fit dowel).
- Evidence summaries keep nested sub-verdicts (end-pose engagement, blocking) that decide a check verdict; a reviewer noted they were dropped.
- Side-button flow: revision 1 went through five-role review (two rounds, independent subagent contexts) and was rejected with 14 blocking findings (captive pin, no rest stop, hinge play, lever ratio). Revision 2 (`side_button_recipe_v2`, `--revision 2`) repairs them with a stock pin, slot rest/hard stops, a centred plunger, 0.1 mm hinge play and checks that prove each fix.
- Add `sweep` (closed polygon profile along a polyline or interpolating-spline path; the profile frame is the start tangent with world Z, or X when nearly parallel, projected as its x axis) and `section_loft` (closed polygon or periodic-spline sections on arbitrary, non-parallel planes with explicit origin, normal and x axis). Both require one valid positive-volume solid; failures raise without fallback geometry. Free-form `surface_loft` remains routed to external editors. Capability tests that used `sweep` as an unsupported example now use `surface_loft`; assertions are unchanged.
- Studio SVG drawings use polygonal hidden-line removal on a private mesh copy. Exact HLR ran for over 25 minutes on a spline shell, beyond the 300 s worker budget. SVGs are display evidence; STEP remains the exact geometry.

# Unreleased — Shell, spline surfaces and rotation clearance (2026-10-07)

- Add typed Recipe operations `shell` (inward uniform wall with optional open faces), `revolve`, `spline_loft` (parallel closed periodic-spline sections), `mirror`, and selector-bounded `fillet_edges` / `chamfer_edges`. Kernel failures raise without reducing wall/size or substituting geometry.
- `shell` rejects walls of at least half the smallest source extent before calling the kernel, and requires one valid solid with less material and unchanged outer bounds. Wall thickness is the construction offset, not a measured minimum wall.
- Protected hardware cannot be the source of any reshaping operation (transform, fillet, shell, mirror, edge finishing), in both the Recipe contract and owner protection policy.
- Add `rotation_checks` (`sampled_rotation_clearance`): rigid rotation about one fixed axis with adaptive sampling and a conditional Lipschitz lower bound using the bounding-box corner radius. Not a formal kernel-error certificate; elastic, flexure and hinge-play behavior remain unverified.
- Freeze rotation checks in correction lineage and autopilot schema-repair guards. Routing tests that used `shell` as an unsupported example now use `surface_loft`, which keeps the same assertions.

# Unreleased — Parallel polygon Loft and evidence limits (2026-09-20)

- Require registered per-part/assembly STEP equivalence in new supplemental verification subjects, within the existing worker budget. Bind the internal delivery manifest, report details and STEP hashes; reject contract downgrade and contradictory results.
- Preserve legacy supplemental evidence and display its absent delivery test as not recorded. Include the new manifest in review attachments and expose ordinary build delivery-check status.
- Add bounded synthetic positive/negative control reports with parent-side identity checks and retained crash/timeout/failure evidence. These reports are not yet linked to formal review subjects.

- Add bounded smooth/ruled Loft through parallel XY polygon sections; reject invalid sections and failed or multi-solid kernel results without fallback geometry. General splines, sweep and shell qualification remain unsupported.
- Label additional acceptance thresholds as numerical comparison only, not design or manufacturing allowances. Preserve original checks and historical reports.
- Generate published schemas from runtime registries and test all exported contracts for drift.
- Real supplemental review completed ten calls across five roles and two rounds, but remained not accepted. Preserve findings on delivery geometry equivalence, historical unknowns and negative-control evidence.
- Reimport delivered per-part and assembly STEP files for one-to-one solid equivalence, including bidirectional differences, bounded complexity and invalid-topology rejection. Include the result in the geometry verdict without rewriting historical builds.
- Add a bounded read-only delivery evidence probe with source/evaluator hashes and non-overwriting reports. The existing real-model L-plate has zero bidirectional difference; historical review acceptance remains unchanged.

# Unreleased — Supplemental evidence without CAD regeneration (2026-09-20)

- Add shared `brain_studio_verify_artifact` and AcceptanceSpec schema (50 tools). Measure exact source STEP copies in a directly bounded worker; create fresh review subjects without copying reviews.
- Preserve original checks, unknown declarations and source evidence. Additional criteria may add unknowns but cannot omit original obligations; passing added checks cannot override failed original checks.
- Bind derived subject identity to source record, manifest, criteria, measured report and attempt. Revalidate source registration and every copied hash; include original and added evidence in review packets and delivery.
- Isolated real-model-origin L-plate V2 supplemental probe passed its artifact checks; CAD regeneration, new model calls and new role reviews were not performed. Physical certification remains unknown.

# Unreleased — Artifact acceptance and project protection (2026-09-20)

- Add persistent hash-bound project protection and editable-reference policy (49 tools); read-only obstacle/cutting reference use remains permitted.
- Measure nominal B-rep bounds independently of cached render triangulation. Keep original dimensional thresholds unchanged.
- Add bounded STEP acceptance CLI with fixed-spec hash, positioned envelope, region occupancy and optional polygon-prism symmetric difference; distinguish geometric checks from physical certification.
- Original-design R2 generated STEP with 14 model calls and ten role reviews, but was not accepted. A separate unchanged-Recipe nominal rebuild passed geometry with no model calls; it has no new reviews and does not overwrite R2.
- Preserve failed trials, original evidence and development-disabled host configuration. Development probes are not held-out performance benchmarks.

# Unreleased — Original design and development isolation (2026-09-20)

- Separate principle/fit reference use from direct CAD reuse. Permit explicit original design basis with a verification plan; add bounded polygon extrusion.
- Add auto/reference-required/original planning routes, bounded concept replanning and capability reporting (47 tools). Unsupported physics remains unknown.
- Match review attachments by registered path/hash/kind, preserve raw provider responses, detect build-record modification and freeze correction-baseline conditions.
- Disable project production MCP during development; preserve a Cursor configuration backup. Allow explicit isolated stdio checks without mutating host settings.
- Bounded real-model original-design trial stopped before CAD on invalid check-to-output identifiers (5 calls). This is recorded as not accepted, not a design success.

# Unreleased — Codex host support and evidence-safe discovery

- Embed bounded text evidence and attach images through native Codex image input; record immutable attachment hashes and inspection observations without granting shell access.
- Require five-role Round 1 plus review-ID-backed Round 2 peer challenge before discussion readiness; measured failures cannot be cleared by consensus.
- Freeze original requirements, functions, protected constraints and check thresholds across repairs; add same-subject DELIVERY.json/MD with geometry, review and physical states separated.
- Add bounded isolated real-model probes for evidence viewing and a negative-control → typed repair → rebuild → five-role re-review loop.
- Project-local Codex TOML installer with conflict detection, backups and idempotence; existing Cursor configuration is retained.
- The same stdio connection check supports Cursor and Codex configurations (46 tools, including delivery manifest generation). Native app activation still requires project trust.
- Add read-only project and Studio subject discovery; distinguish legacy workflow state from stored CAD build evidence.
- Codex CLI capability probe, UTF-8, strict JSON/schema validation and bounded evidence snapshots outside the user's project; reject modified inputs.
- Review status now includes declared unverified requirements.
- Windows regression: 342 passed, 2 symlink-dependent skips. Real one-call Codex smoke test and isolated real-CAD demo recorded separately from automated test doubles.

# Unreleased — Generic Fusion assembly bridge

- cadMCP is the control plane for a customer's solid parts, not a mouse-only
  factory. Mouse Board/Shell packs stay optional for PCB-and-shell jobs.
- Typed `FusionHandoff` plus `brain_fusion_handoff` / `brain_fusion_ingest`.
  Cursor may only run the issued Fusion adapter script (sha-checked). The
  adapter imports STEP, applies millimetre poses as centimetres, refuses to
  move protected occurrences, and never saves f3d (43 tools).
- After a Fusion print JSON, CadQuery remesures overlap, clearance and motion
  on the issued part STEPs. A Fusion screenshot is not a geometry pass.
- Recipe origin is real STEP: a Req2CAD `reference` or a registered
  `project_step`. Primitive boxes alone are still refused.

# Unreleased — Req2CAD corpus helpers

- Resume DeepCAD/CSV downloads from a stable `.partial` file with HTTP Range.
  A failed transfer keeps the partial; it is not deleted. A complete destination
  with a matching SHA is reused. The four-case demo is not a substitute catalog.

# 0.3.3 — Shell pack and structure intake gate

- Add a typed prepared-shell pack. Ready status needs a protected outer
  envelope, a positive wall thickness, matching STEP hash, and a valid B-rep.
- `brain_mouse_structure_gate` opens only when a ready board pack AND a ready
  shell pack exist. A STEP file on disk is not a shell pack. The gate does not
  generate bosses, click parts, or scan-to-shell geometry (41 tools).
- Install the package editable so Cursor MCP (cwd = project root) loads this
  tree instead of a stale site-packages 0.3.1 copy.
- Force UTF-8 on bounded CLI child processes so Windows cp932 logs cannot
  masquerade as UTF-8 JSON.

# 0.3.2 — Mouse Board Pack intake

- Add a typed Board Pack for reusable PCB mechanical interfaces (sensor datum,
  mounts, switches, keepouts) with draft vs ready status.
- Refuse ready packs that still have unverified required fields, hash mismatch,
  or an invalid STEP B-rep. Do not classify cylindrical CAD features as screws.
- Add `brain_mouse_inspect_inputs`, `brain_mouse_register_board_pack`,
  `brain_mouse_get_board_pack`, `brain_mouse_list_board_packs` (37 tools).
- Inspection never starts mechanical design from a mesh or an empty catalog.
  Req2CAD corpus install remains a separate owner step.

# 0.3.1 — Cursor support


- Add CursorProvider and explicit `--provider cursor` without removing CodexProvider.
- Handle native terminal result JSON, native engineering maps, schema failures,
  duplicate keys, non-finite numbers, errors, fresh sessions and process budgets.
- Add bounded immutable evidence snapshots, ask mode, deny rules, default sandbox
  request, and an explicit owner-controlled permissions-only option.
- Add non-generative Cursor CLI capability probe.
- Add IDE Skill, five read-only foreground subagent definitions and three commands.
- Add configuration installer preserving unrelated MCP entries/custom env, with
  managed-file conflict detection, preflight, backups and update journal.
- Record actual test-double transport/CAD results separately from live Cursor tests.

# 0.3.0 — Function → real structure → adapted prototype

- Four source-hash-checked public CAD records, actual B-rep replay and reproducible demo.
- Geometric loop containment instead of trusting inconsistent is_outer metadata.
- Safe nested/compressed DeepCAD archive normalization.
- Grouped function retrieval; paraphrases do not create extra coverage votes.
- Measured inner/outer cylindrical and planar interfaces; evidence-bound face IDs.
- Typed morphological matrix and bounded compatible functional covers.
- Typed source-bound CAD adaptation; protected hardware and editing authority.
- Automatic output-pair interference, dimensions, clearances and bounded linear-motion checks.
- Native portable z-buffer PNG views + SVG/STEP, read-only local evidence report.
- Five-role review and peer-challenge orchestration; frozen-check repair.
- Optional bounded owner-authenticated Codex CLI provider; no implicit new API calls.
- 260 passing tests in the final Linux source run; live-model/full-corpus/Windows/physical tests remain outstanding.

0.2-era test totals and intermediate failed runs are not used as this release's results.
