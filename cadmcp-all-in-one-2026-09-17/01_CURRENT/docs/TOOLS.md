# MCPツール一覧

生成元: cadmcp_brain.api.Tools.list()。正確な引数はschemas/mcp-tools.jsonまたはbrain_schema/brain_task。

| 名前 | 用途 |
|---|---|
| brain_add_source | Append an exact new user instruction; invalidate old intent, concepts, plans and verification, preserving audit history. |
| brain_backend_call | Opt-in gated AgentCAD call. Owner allowlist required. Default dry-run. A call_id permits at most one network write attempt; never retry uncertain outcomes. |
| brain_backend_probe | Read the configured loopback AgentCAD live tool registry. Disabled unless CADMCP_AGENTCAD_URL is set by the owner. |
| brain_doctor | Report local capabilities without pretending to test a remote CAD backend or a Windows/Cursor installation. |
| brain_export | Export immutable contract.json, CAD_HANDOFF.md and design_graph.json for the existing CAD backend. Does not execute CAD. |
| brain_fs_case | Read exact original functional annotation and linked asset metadata. Labels are hypotheses, not verified engineering capabilities. |
| brain_fs_compare | Compare actual materialized face-adjacency topology (WL) and surface geometry descriptors. Not a functional equivalence or automatic assembly proof. |
| brain_fs_evidence | Return source-hashed function + geometry + topology evidence, usable in Concept.case_references. Requires original file integrity; no strength claims. |
| brain_fs_interfaces | Inspect materialized planar/cylindrical surfaces. Distinguish inner cavity from solid shaft exterior; NOT proof of through-bore, fit, force transmission or fatigue. |
| brain_fs_materialize | Reconstruct/import the registered real CAD; export STEP/STL/views and measure face-type graph, WL features and sampled geometry. Never invent geometry for missing UIDs. |
| brain_fs_portfolio | Choose structurally diverse representatives from retrieved, measured CAD UIDs. Missing geometry is reported, not fabricated. |
| brain_fs_search | Retrieve real CAD UIDs by functional keywords. Semantic is default and requires a prepared real model/index. Lexical mode must be explicitly requested. |
| brain_fs_search_tasks | Search multiple paraphrases per functional requirement without double-counting them. Inspect real surface preconditions; unknown geometry is not a pass. Explicit lexical mode is only a diagnostic/limited retrieval route. |
| brain_fs_status | Read actual function/asset/geometry coverage. An empty catalog is not an installed 128k library. |
| brain_fusion_handoff | Issue the only Fusion adapter script allowed for this built subject. Host must pass it to fusion_mcp_execute unchanged. Does not save f3d. CadQuery remains the geometry referee. |
| brain_fusion_ingest | Accept Fusion print JSON only when it echoes the issued adapter. Remeasure overlap/clearance/motion in CadQuery. A Fusion screenshot is not a pass. f3d is not saved. |
| brain_get | Read current state and revision. Reload after REVISION_CONFLICT; never overwrite a newer design. |
| brain_history | Read the transactional project event history. |
| brain_import_step | Copy/hash a workspace-relative STEP. output needs current contract digest; reference performs actual kernel measurements and invalidates concepts/plans. Trusted local STEP only. |
| brain_mouse_get_board_pack | Read one stored board pack. Presence is not printability, optical alignment, or click-feel. |
| brain_mouse_get_shell_pack | Read one stored shell pack. Registration is not printability, wall-thickness proof everywhere, or optical alignment. |
| brain_mouse_inspect_inputs | Hash workspace files and report board/shell pack status. A STEP on disk is not a ready shell. Does not invent fasteners or a passing design. |
| brain_mouse_list_board_packs | List draft and ready board packs in this workspace. Demo CAD cases are not listed here. |
| brain_mouse_list_shell_packs | List draft and ready prepared-shell packs. A mesh scan is not listed here. |
| brain_mouse_register_board_pack | Store a typed PCB mechanical pack. Ready status is refused when required fields are unverified, hashes mismatch, or the STEP is not a valid B-rep. |
| brain_mouse_register_shell_pack | Store a typed prepared-shell pack. Ready status needs a protected outer envelope, a positive wall thickness, matching STEP hash, and a valid B-rep. Scan-to-shell conversion is not performed. |
| brain_mouse_structure_gate | Report whether a ready board pack and a ready shell pack exist. Does not generate structure CAD, bosses, or click parts. |
| brain_open | Start source-grounded design. request is the user's exact original text, not an invented paraphrase. Next call brain_task. |
| brain_patterns | Retrieve original mechanism patterns using lexical English/Japanese search. Results are not validated designs or dimensional allowables. |
| brain_schema | Read a versioned Brief, Concept, Concepts or Plan JSON schema. |
| brain_select | Select a gate-eligible concept. This does not attest human approval, printability, strength or fatigue life. |
| brain_studio_build | Build a STEP-bound typed CAD recipe in a separate process; export real STEP/STL/SVG and static/sampled-motion clearance. No arbitrary Python exec, printer send or canonical project modification. |
| brain_studio_reply | Record an evidence-based response to a specific review finding. No majority vote or prose rebuttal automatically clears a blocker. |
| brain_studio_review_packet | Prepare a requirements/mechanism/assembly/manufacturing/verification reviewer packet with real evidence and exact output schema. This does NOT spawn an independent LLM itself. |
| brain_studio_review_status | Read review coverage, open disagreements, geometry failures and unverified physical requirements. Reviewer independence and human approval are never inferred. |
| brain_studio_schema | Get FunctionBrief, Matrix, Recipe, Review, Reply, BoardPack, ShellPack, FusionHandoff or FusionReport schemas. These are typed host/worker contracts, not a claim of semantic intelligence. |
| brain_studio_submit_review | Record actual host-submitted engineering findings for this revision and subject. Roles and agreement never authenticate independent reviewers or clear physical tests. |
| brain_studio_synthesize | Combine real-reference mechanism options into compatible functional covers. Reject absent required surfaces and invented face IDs. Returns review subjects, NOT finished assemblies. |
| brain_submit_concepts | Commit 2–4 distinct FBS mechanism alternatives and return mechanical/declaration gate results for each. |
| brain_submit_intent | Validate and commit the source-linked Brief. Reject source omissions, fabricated quotations, contradictory constraints and mandatory inferences. |
| brain_submit_plan | Commit a typed geometric construction plan with dependency, provenance and test-obligation validation. |
| brain_task | Get the next host-model task, relevant state and exact JSON schema. The server does not pretend to understand natural language itself. |
| brain_verify | Measure imported B-reps and evaluate listed geometry checks. Missing/stale/unsupported evidence remains unknown; physical performance is not certified. |
