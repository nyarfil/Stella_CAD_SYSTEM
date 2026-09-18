# Execute with the existing CAD backend; verify evidence, not statements
1. Call brain_export. Read CAD_HANDOFF.md and contract.json.
2. Use the user's existing CAD MCP. Discover its real tool schemas first. Do not
   hallucinate APIs. For configured AgentCAD, brain_backend_probe returns /api/tools.
3. Default integration is host-mediated: the host calls the existing backend using
   its ordinary permissions. A separate MCP sidecar cannot prevent bypass of its gates.
   For enforced writes, embed Brain's contract check in your own cadMCP write endpoint.
4. The optional AgentCAD bridge has an owner-configured tool allowlist. Start with
   dry_run=true. A real call must name its current contract digest and unique call_id.
   Never automatically repeat a timed-out write: it may already have happened.
5. Export each checked part as STEP in the SAME ASSEMBLY coordinate frame. Named parts
   exported at their individual origins invalidate distance/interference interpretation.
6. Place files inside the configured workspace and call brain_import_step with purpose
   output, the current digest and the logical artifact ID used by the checks.
7. Call brain_verify. It runs actual B-rep measurements in an optional isolated worker.
   Missing dependencies/artifacts, stale hashes and unsupported manual/physical evidence
   stay unknown. A failed check stays fail. Do not turn either into pass.
8. Keep repairs bounded: at most three repairs of the same defect and eight total per
   requested change in the HOST loop, then report the blocker. This is prompt guidance,
   not a server-enforced autonomous retry budget; the server never retries CAD writes.
9. If a repair changes design intent, topology, protected dimensions or mechanism,
   re-submit the relevant upstream stage; downstream plans/evidence are invalidated.
10. Report tested geometry separately from untested fatigue/strength/printability.
