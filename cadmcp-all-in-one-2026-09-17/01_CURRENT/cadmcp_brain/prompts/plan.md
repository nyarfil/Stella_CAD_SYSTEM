# Geometric construction contract, not free-form CAD improvisation
Read the selected concept and build a dependency-ordered Plan. Preserve every fixed
interface, input shape and explicit source constraint. Keep the plan backend-neutral.

For every step state operation, affected components, purpose, requirements, prerequisites,
what must be preserved, and precise geometric instructions. Use actual component IDs,
reference frames and semantic selectors. Avoid brittle "face 17" references.

Classify each numerical design dimension as user (exact quote with units), measurement
(stored kernel evidence ID) or proposal (with rationale). A proposed value is not a
manufacturing tolerance or a verified material allowable. Do not invent exact PCB,
switch, sensor or wheel locations. Reuse measured CAD or stop that dependent step.

Attach test obligations to every mandatory requirement. For a geometric target choose
an appropriate available check and explicit tolerance. A bounding box alone cannot
prove wall thickness, hole fit, shell preservation or assembly. Unsupported checks
must use external_geometry obligations for unimplemented geometry measurements,
manual for design review, or physical_test for experiments. Never replace them
with unrelated easier measurements. external_geometry remains unknown.
Use physical_test for feel, fatigue, strength and actual print quality. Such checks
remain unknown in this release. No LLM-provided pass/fail is accepted as test evidence.

Allowed CAD-task operations: create_part, modify_part, place_part, create_joint, inspect.
The instructions can specify a real loft or sweep when supported by the actual backend.
Do not relabel a loft/sweep as an extrusion. This plan is handed to a real CAD executor;
it is not directly executable Python and no arbitrary code is executed by the brain.

Specify print orientation and assembly order. Verify insertion/access, not just the
final static pose. Submit via brain_submit_plan and export the immutable handoff.
