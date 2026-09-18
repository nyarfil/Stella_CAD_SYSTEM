# Function → behavior → mechanism → components
Generate 2–4 genuinely different alternatives; do not spawn extra agents merely
because a pipeline exists. A single host can execute these roles sequentially.

## Retrieval-first: retrieve real structures before synthesizing them
Call brain_fs_status. Convert the actual task into distinct verb+object functions.
Call brain_fs_search(functions=[...], mode="semantic") and retain real UID hits and
matched-keyword scores. Default library method is keyword-level embeddings, not a
list of 13 hand-authored patterns. If data/model/index are missing, state that fact;
do not fall back to patterns or a made-up CAD silently. Lexical search is explicitly
labeled diagnostic fallback, not semantic equivalence.

For promising hits, call brain_fs_materialize(uid), then brain_fs_evidence(uid).
Inspect the actual 4 SVG engineering views/STEP through available CAD/image tools;
reading the annotation alone does not inspect the object. Use brain_fs_compare or
brain_fs_portfolio to diversify actual measured candidates. Geometry descriptors
are a deterministic alternative, not the original trained point-cloud network.

Create Concept.case_references with the exact UID, returned evidence_digest,
function_query, adopted_principle and required_adaptations. Connect them using
Mechanism.reference_ids. For structures outside the small legacy catalog use
pattern_id="reference_structure", and specify motion_relation for actuators.
Do not force a real reference into an unrelated old card merely to pass a validator.
Reference-first mode forbids an ungrounded candidate from advancing. If the library
has no suitable candidate, report the coverage gap instead of inventing a hit.

Reusing a principle is not copying nominal dimensions. Match actual installation
space, input/output axes, retained parts, printing orientation and assembly.
Function labels are machine hypotheses. A real CAD shape is NOT proof of friction,
strength, allowable travel, fatigue life or appropriateness for the current mouse.

For each concept:
- Functions use a verb and object. State expected observable behavior separately.
- Use real case evidence as the structure source. brain_patterns is auxiliary
  vocabulary/checklist only, not a substitute for function–structure retrieval.
- Show how each function is realized, what physically carries its load, how moving
  parts are constrained, how parts return, what limits travel and how they assemble.
- Include printed, purchased and reference components, their material, manufacturing
  orientation and assembly/tool access. Do not silently omit the PCB or switch support.
- Interfaces must connect distinct existing components. Avoid floating parts and
  overconstraint. A connectivity graph alone does not prove assembly feasibility.
- For side buttons, inspect the ACTUAL switch actuation direction. A switch beside
  the button, actuated along the same axis, normally warrants evaluating direct
  actuation before introducing a motion-redirection mechanism. Do not invent a
  vertically facing switch. Left/right refers to the explicitly declared frame.
- Direct mechanisms must have matching input/output unit vectors. For a lever,
  explain the pivot, force ratio, output contact trajectory and resulting side loads.
- Specify return and hard stop. The internal switch spring may not overcome guide
  friction, gravity or tolerance stack-up. Printed flexure fatigue is not established
  by a plausible shape, a static FEA pass or a generic ABS material value.
- Prefer separately printable parts where critical guide/contact surfaces would
  otherwise sit on supports. Do not prescribe universal clearances or wall thickness.
- List realistic failure modes, blocking unknowns and alternatives rejected on grounds.

Compare conventional/simple versus flexure or lever solutions as applicable.
A rejected alternative may remain in the comparison. The server will forbid selecting
one with violated hard gates. Do not fabricate numerical "quality" or confidence.
Submit the Concepts envelope via brain_submit_concepts, then inspect evaluations.
