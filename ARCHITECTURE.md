# Stella CAD System architecture

Cursor / Codex host → common cadmcp-design-brain → CadQuery/OpenCascade.
Source: cadmcp-all-in-one-2026-09-17/01_CURRENT. Runtime data: cadmcp-workspace.
Legacy engines remain under LLM_cad_Projects; no duplicate active CAD source is introduced.

| Capability | Responsibility | Main paths relative to 01_CURRENT |
|---|---|---|
| Host installation | Local configuration and managed skill installation | scripts/setup_cursor.py, scripts/setup_codex.py |
| Connection diagnostics | Real stdio handshake using selected host configuration | scripts/check_cursor_connection.py --host cursor/codex |
| Intent/state | Original request, provenance, revisions and legacy contracts | cadmcp_brain/models.py, engine.py, store.py |
| Discovery | Project pagination and current/historical Studio subjects | api.py, store.py, studio/runtime.py |
| Reference search | Function index, semantic search, exact CAD IDs and reconstruction | cadmcp_brain/req2cad/ |
| CAD execution | Typed recipes and deterministic geometry checks | cadmcp_brain/studio/recipe.py, worker.py |
| Review | Evidence packets, role findings, two-round peer challenge gate | cadmcp_brain/studio/runtime.py, packets.py |
| External model execution | Explicit bounded CLI calls and schema validation | cadmcp_brain/studio/provider.py, cursor_provider.py |
| Delivery | Same-subject geometry/review/physical state separation and manifests | cadmcp_brain/studio/runtime.py, mixin.py |
| Live integration probes | Opt-in evidence attachment and bounded five-role repair loop | scripts/check_codex_evidence.py, check_codex_review_loop.py, demo_real_references.py |
| Fusion handoff | Issued adapter, protected placements, remeasurement | cadmcp_brain/studio/fusion.py |

API registers public tools; transport owns JSON-RPC only. New host entry points reuse
the same domain models, verification and workspace. Skill/model selection is host-owned.
Legacy next_stage and Studio build history are separate and exposed separately.

Protected assets: user's PCB, switch, sensor and shell geometry/placement; original
requests and imported STEP hashes; prior workspace history; unrelated host configuration.
No regeneration or refactoring of these assets is part of Codex integration.

## Evidence and review trust boundary

Text evidence is copied to a bounded snapshot and embedded into the model request. Images are
passed with Codex's native image input. Each review stores the supplied attachment hash, kind,
view status and observation. This avoids granting a reviewer a general shell while still proving
which evidence it received. The provider uses ephemeral, read-only execution and never bypasses
project policy.

Round 1 requires all five roles in separate executions. Round 2 must cite every saved Round 1
review id before peer challenge is complete. Geometry pass, review coverage, human approval and
physical performance remain distinct states; consensus cannot erase a measured failure.

The original request/FunctionBrief is server-owned after validation. Repair preserves the frozen
request, functions, protected constraints and check thresholds. DELIVERY.json/MD records the
same subject and explicitly marks unavailable BOM and physical evidence rather than inventing it.

The current weak point is whole-Recipe generation: real-model search, reference materialization,
two concepts and image-backed selection succeeded, but a Recipe DAG remained invalid after one
bounded correction. The 2026-09-20 flexibility review withdraws fixed Recipe skeletons as the
only future route. Templates remain useful for known designs; novel designs require composable
typed operations, capability checks and bounded replanning. This is a proposed change, not a
claim that the current executor supports new operations or alternative planning routes.

## Flexibility boundary proposed at audit (implementation update below)

Keep owner requirements, protected artifacts and approved acceptance conditions invariant.
Allow search queries, design hypotheses and operation graphs to evolve with explicit evidence.
Unknown requirements keep their identity while their evidence status can change; reviewer
suggestions do not automatically become owner requirements. Evidence-backed correction of a
review must preserve its history and cannot clear a measured failure without remeasurement.

The current Autopilot requires Req2CAD and cannot synthesize solely from project STEP, despite
the direct Recipe executor accepting project_step. Current operations lack loft/sweep and
motion checks cover translation only. Automatic pairwise overlap checks model rigid clearance,
not press-fit deformation. Capability-aware planning must distinguish these limitations from
physical impossibility, return a specific next action and retain pass/fail/unknown boundaries.
No arbitrary-code fallback or legacy-engine activation is implied by this proposed design.

Acceptance and outstanding work: IMPLEMENTATION_PLAN_JA.md. Existing Japanese 0.3.1
test reports are historical evidence, not current-release certification.

## 2026-09-20 implementation update

This section supersedes the audit-time statements above where noted. Development does not
run under the product CAD workflow. Project Codex MCP/skill are disabled, Cursor's single
product MCP entry is backed up and removed. Only explicitly isolated test workspaces are used.
Neither global trust policy nor legacy engines are changed.

| Component | Responsibility and current change |
|---|---|
| studio/planning.py | Schema-derived operation capabilities and bounded recovery classification; exposed by brain_studio_capabilities |
| studio/synthesis.py | Reference-informed, first-principles or registered provided-CAD concept basis; no mandatory catalog reuse |
| studio/recipe.py | Typed reference-use provenance separate from output geometry; explicit design basis/verification plan for original geometry; polygon extrusion |
| studio/autopilot.py | auto/reference_required/original routes, bounded concept replanning, fixed server-owned brief, baseline-linked repair |
| studio/runtime.py + packets.py | Registered evidence identity, complete per-role attachment inspections, all-round-one peer challenge, build-record integrity, immutable repair conditions |
| studio/provider.py + cursor_provider.py | Hash-checked mapping of temporary evidence attachment paths back to registered source paths; retain raw and normalized responses |
| scripts/setup_codex.py + check_cursor_connection.py | Disabled-by-default new Codex server setup; explicit isolated stdio testing without changing host config |

Cursor and Codex continue to share Recipe, runtime, transport and kernel verification.
The development changes do not replace the CAD engine or split the repository architecture.
No arbitrary-code fallback was introduced. Raw reference solids are optional design inputs,
not mandatory ancestors of generated output geometry.

Limits: automatic replanning is not a universal recovery engine; loft/sweep and rotational or
elastic verification remain unavailable. Explicit baseline preserves known protected inputs,
but persistent project-wide protection selection remains outstanding. Review correction records
do not silently supersede measured failures or earlier revise decisions. The bounded real-model
original-design run stopped on mismatched part identifiers before STEP generation; unit/integration
passes must not be described as end-to-end original-design success.

Initial schema correction now compares normalized inspection contracts before invoking build.
Only unambiguous node-to-output-part identifier correction is allowed for existing checks;
changing values, thresholds or check coverage is rejected. This is separate from immutable
successful-build baseline lineage. Final integrated regression: 377 passed, 2 Windows symlink
skips, no failures; verification/windows-codex-20260920-integrated.xml. The live-model trial
remains not accepted and is not overridden by these automated results.

## Continuing development: independent acceptance and persistent protection

| Component | Role |
|---|---|
| studio/acceptance.py, benchmarks/ | Fixed geometric acceptance specification; reimport delivered STEP without trusting generator Recipe; bounded subprocess CLI with specification hash and new report only |
| studio/measurement.py | Nominal B-rep bounds with cached display triangulation disabled, preventing rendering from changing a dimensional verdict |
| models.ProjectProtection, studio/protection.py | Persistent per-project protected artifact hash, registered placement and required output; hash-bound editable references; legacy environment guard union |
| engine + api | Explicit revision-checked policy update/read tools; before/after history; approval delegated to host, never inferred from a reason string |
| docs/QUALITY_ACCEPTANCE_JA.md | Requirement-by-requirement evidence criteria, including held-out designs, distribution reproducibility and fair external comparison |

Protected source geometry may still be used as a read-only cutting/obstacle reference for
new geometry. Protection does not mean banning all reference use. Mutable targets, union
fusion, relocation or disappearance of the protected output remain prohibited.
Reimport invalidates hash-bound editing permission. The policy cannot authenticate an owner;
MCP host approval is required for changes that weaken protection or grant editing.

Original-design R2 generated real STEP and completed ten separate review contexts (14 total
model calls). Its original subject remains not accepted. A reproducible cached-tessellation
bounding-box inflation was found and repaired without changing thresholds; missing full-profile
verification and review/unknown state transitions are separate concerns, not cleared by this fix.

The separate nominal rebuild now passes with exactly the same Recipe hash, original request
and zero-tolerance checks. Old R2 evidence remains unchanged; the new subject has no reviews.
The acceptance evaluator additionally supports an optional fixed extruded polygon oracle:
both candidate-minus-oracle and oracle-minus-candidate volumes are checked. Absence of this
criterion explicitly leaves full-profile equality unverified. It is a same-kernel artifact
check, not physical certification, and is not yet registered as formal Studio review evidence.
The L-plate specification was authored after R2 as a development probe, not a held-out benchmark.

Pre-supplement integration regression: 405 passed, 2 Windows symlink skips, no failures
(`verification/windows-codex-20260920-goal1-final.xml`). Test catalog environment variables
are restored by module fixtures, including when the original environment key was absent.

## Supplemental artifact verification (same CAD, fresh review subject)

`studio/supplement.py` adds bounded server-side STEP acceptance to an existing build.
`brain_studio_verify_artifact` and `brain_studio_schema("AcceptanceSpec")` expose the shared
Cursor/Codex surface (50 tools). The worker reimports an exact hash-checked STEP copy;
it does not execute the Recipe or accept caller-supplied pass/fail reports.

The derived `recipe_build` retains the original context and Recipe digest, audit copies
of the original build record and measurements, plus supplemental spec/report. Its identity
binds the source subject, source record and manifest, spec, report and attempt nonce.
`cad_regenerated=false` distinguishes this from a CAD generation trial. Original checks and
unverified declarations remain unchanged; additional declarations may extend, never omit,
the source obligations. Combined geometry is pass only when both original and added checks pass.

Runtime revalidation checks the registered source, all source-copy hashes and report consistency.
Review packets require the original audit copies and added spec/report as evidence attachments.
No old reviews are copied; prior blockers are supplied as context for new review. Delivery exposes
the supplemental results separately. This is not automatic resolution of unknowns or physical
certification. Currently one supplement per source is supported: further independent verification
runs may start from the original subject, but cumulative multi-supplement lineage is not yet implemented.

Supplement integration regression completed: 415 passed, 2 Windows symlink skips, no failures
(`verification/windows-codex-20260920-supplement-all.xml`, 355.11 seconds). This result predates
the planned Loft operation and does not validate that subsequent addition.

## Parallel-section Loft and schema publication

`studio/recipe.py` now includes `LoftSection` and `Loft`: 2–16 ascending XY polygon
sections, 3–64 points with consistent vertex count/winding, and explicit smooth/ruled
mode. Identical XY profiles at different elevations are allowed. Construction, wire
errors, invalid/empty results and multiple solids fail as `STUDIO_INVALID_SOLID` without
substitution. This adds a shape-building capability, not spline surfaces, Sweep, shell
thickness verification, mouse fit or physical qualification. It introduces no editable
source reference and leaves existing protected-hardware rules in force.

`studio.mixin.studio_schemas()` is shared by runtime schema discovery and
`scripts/generate_schemas.py`. `--check` and `tests/test_published_schemas.py` cover every
published planning/review schema, preventing stale offline contracts after feature changes.

Acceptance reports label their tolerances as numerical-comparison thresholds, not design
or manufacturing allowances. No original Recipe check is replaced or relaxed. Older stored
reports remain unchanged historical evidence.

Schema generation uses the existing atomic JSON writer, so replacement failure preserves
the previous contract file. Check mode reports malformed JSON as drift without rewriting;
explicit generation repairs it from runtime definitions. Failure-injection tests cover
replacement denial and corrupted-input recovery. This changes only generated contracts,
not saved CAD evidence or user settings.

## Delivery STEP equivalence

`studio/recipe.py::verify_delivery_steps` reimports the positioned per-part STEP files
and the assembly STEP inside the existing bounded build worker. A one-to-one solid
matching uses nominal bounds/volume prefilters and bidirectional Boolean differences.
Counts and matching reject omitted, additional, moved or duplicated solids; equal
bounding boxes and total volumes alone are insufficient. Fixed numerical allowances
are not user design tolerances. The comparator is bounded to 128 solids and rejects
invalid or non-solid deliveries rather than silently qualifying them.

The system check is included in `measurements.json` and controls the geometry verdict,
so ordinary review packets and delivery reports inherit it. `_system-` check IDs cannot
collide with user check IDs, which must begin with a letter. Existing historical builds
are not rewritten or automatically upgraded.

`scripts/check_delivery_evidence.py` provides a 90-second read-only development probe
for existing isolated supplement results. It records input manifests and evaluator
hashes in a new report outside the source folder, without regenerating CAD, changing
review acceptance or claiming physical performance. This standalone report is not a
replacement for a registered and reviewed evidence subject.

The delivery-equivalence integration passed the complete Windows regression: 449 passed,
2 symlink-permission skips, zero failures in 410.46 seconds
(`verification/windows-codex-20260920-delivery-all.xml`). This is software/kernel evidence,
not mouse mechanism qualification, physical performance or external comparative quality.

Capability discovery advertises `delivery_step_equivalence` and its actual 128-solid
comparison ceiling. A capacity error is classified as `verification_capacity`, not as
an invalid design, and recovery explicitly forbids removing parts to obtain a pass.

## Delivery-comparator development controls

`scripts/check_delivery_controls.py` generates synthetic STEP controls in a new isolated
verification directory: one positive and five negative cases (same envelope/volume but
different solid, moved, missing, extra, duplicate). A 90-second worker performs the actual
CAD comparisons. The parent verifies the complete fixed case set, part identities, exact
STEP paths/hashes and verdict consistency, then recomputes success rather than trusting a
worker success flag. Failed runs are retained as reports/failure records; previous runs
are never overwritten. This is same-kernel, hand-authored development evidence, not an
independent solver or model-generated design benchmark. Formal subject linkage remains
separate work; a standalone self-test does not change a review verdict.

## Supplemental delivery verification contract v2

`studio/supplement.py` derives a hash-bound internal `delivery-manifest.json` only from
the source build's registered output STEP exports and file manifest. The existing
acceptance worker checks these individual STEP files and the assembly in the same
time budget. Its report contains the exact manifest/STEP identities and one delivery
check; both the creator and runtime revalidation compare the check, verdict and source
mapping. Overall geometry requires the original checks AND all additional checks.

New supplemental subjects require this contract and bind the evaluator set; removing
the new flag cannot silently downgrade a subject to the legacy contract. Legacy reports
remain readable but expose `not_recorded_legacy`, never an inferred delivery pass.
Ordinary build status also exposes its recorded system check, or `not_recorded` when absent.
Review packets for contract v2 include the delivery manifest alongside source and added
reports. Original statements, CAD bytes, subjects and historical reviews remain unchanged.

## Historical declarations and current evidence

`studio/evidence_state.py` derives a read-only view from a revalidated subject for
status, compact review packets and delivery JSON/Markdown. Original unknown declarations retain
their exact text and stable identities bound to source subject, source build-record hash
and ordinal; sibling supplemental subjects therefore retain the same declaration IDs.
Source measurements and supplemental observations carry separate registered file hashes.
No natural-language declaration is automatically resolved by a geometry pass.

Missing/unknown results and explicitly unverified checks remain unverified; conflicting
boolean and textual verdicts are marked inconsistent. Large sample arrays are not copied
into the view. Packet projection occurs before sample compaction so all consumers see
the same evidence state. This is a display/provenance boundary, not a completed resolution
ledger or a change to acceptance thresholds, historical reports or physical certification.

## Reference-informed build evidence

The public-catalog integration in `tests/test_reference_design.py` verifies the formal
Studio build path with a real materialized reference used only as a principle source.
It binds the current evidence/STEP hashes, imports no reference geometry, compares the
output against the specified new profile and rejects stale provenance. This uses a
hand-authored recipe and a selected four-case catalog; it does not demonstrate model
reasoning or corpus-wide retrieval quality. `studio/report.py` exposes reference-use
classification and application text in the human report without claiming that a stated
principle establishes physical effectiveness.

The integrated regression through this boundary passed 488 tests with two Windows
symlink-permission skips, zero failures (391.80 seconds;
`verification/windows-codex-20260920-evidence-reference-all.xml`). The subsequently
added development runner `scripts/check_reference_design.py` is excluded from that
collection and remains under adversarial validation before any model execution.
Its intended scope is a predeclared two-solid guide/shaft fixture, not mouse or physical
qualification. Initial parent negative controls exposed missing worker-response and
path-boundary checks; these must be resolved independently of the product regression.

The runner's hardened parent now checks fixed nonempty boolean check sets, verdict/exit
code consistency, registered STEP identities, run-root confinement, and the fixed oracle
specification. Request, reference STEP and evaluator hashes are compared before/after
model execution. Thirteen no-model tests include actual bounded-worker acceptance with
arbitrary part names/order, plus shifted-shaft and missing-bore rejection. The one-shot
real-model run is separate evidence and is not accepted until its result is inspected.

## Bounded matrix validation recovery

The first reference-informed model run stopped after two calls because incompatibility
pairs referenced option IDs not present in the model's own candidate list; no designed
CAD was built. `studio/autopilot.py` now returns such Matrix validation errors and the
original invalid matrix to the model within the existing shared `max_replans` budget.
The server-attached brief and reference context remain fixed. It never deletes conflicts
silently, creates synthetic options, or allocates another retry budget. Exhaustion retains
failure evidence and stops before CAD. No-model recovery and bounded-stop tests passed;
successful recovery by a real model remains to be demonstrated.

Reference runner R2 also fingerprints `studio/autopilot.py` before and after the
model run, binding the recovery implementation to the evidence. Runner tests:
13 passed (windows-codex-20260920-reference-runner-pre-r2.xml). R2 is in flight;
no completion or model recovery claim is made until its terminal report is inspected.

## Owner-requested MCP preview handoff

R2 terminal evidence: 14 actual Sol calls; geometry oracle and integrity checks pass,
five-role/two-round execution complete; owner acceptance remains not_accepted.
Further capability development is paused at the owner's request, not declared complete.
The project Codex MCP and product Skill are enabled for preview use. Cursor and global
trust/security settings are unchanged. Actual app read-only diagnostic evidence is
verification/mcp-preview-app-connection.json; source-based isolated stdio exposes 50 tools.
Local wheel packaging is not a clean-install or physical-performance certification.
Factory OS owns orchestration; cadMCP remains a subordinate CAD/evidence capability.
Integration uses user-extensions/CATALOG.md and references/cadmcp.md, not Factory standard
skills/agents/hooks. See docs/MCP_PREVIEW_JA.md for current boundaries and rollback.
