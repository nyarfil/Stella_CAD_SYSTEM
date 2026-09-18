"""MCP surface for real-reference search, synthesis, adaptation and review."""
from __future__ import annotations
from typing import Any
from .runtime import Studio,Review,Reply
from .recipe import Recipe
from .mouse import BoardPack, ShellPack
from .fusion import FusionHandoff, FusionReport
from .synthesis import FunctionBrief,Matrix,retrieve_tasks
from .interfaces import screen_interfaces
from ..errors import BrainError

class StudioToolsMixin:
    def _studio(self):return Studio(self.brain,self._fs())

    def brain_studio_schema(self,name: str) -> dict:
        """Get FunctionBrief, Matrix, Recipe, Review, Reply, BoardPack, ShellPack, FusionHandoff or FusionReport schemas. These are typed host/worker contracts, not a claim of semantic intelligence."""
        schemas={'FunctionBrief':FunctionBrief,'Matrix':Matrix,'Recipe':Recipe,'Review':Review,'Reply':Reply,'BoardPack':BoardPack,'ShellPack':ShellPack,'FusionHandoff':FusionHandoff,'FusionReport':FusionReport}
        if name not in schemas:raise BrainError('STUDIO_SCHEMA','Choose FunctionBrief, Matrix, Recipe, Review, Reply, BoardPack, ShellPack, FusionHandoff or FusionReport.')
        return schemas[name].model_json_schema()

    def brain_fs_search_tasks(self,brief: dict[str,Any],mode: str='semantic',limit_per_function: int=12,threshold: float=.7) -> dict:
        """Search multiple paraphrases per functional requirement without double-counting them. Inspect real surface preconditions; unknown geometry is not a pass. Explicit lexical mode is only a diagnostic/limited retrieval route."""
        parsed=FunctionBrief.model_validate(brief);grouped=None
        if mode=='semantic':
            from ..req2cad.mixin import catalog_for
            from ..req2cad.semantic import SemanticIndex
            c=catalog_for(self.brain)
            grouped=SemanticIndex(c).search_groups([{'id':f.id,'queries':f.queries} for f in parsed.functions],
                                                   self._fs_get_encoder(c),threshold,limit_per_function,True)
        elif mode!='lexical':raise BrainError('FS_ARGUMENT','Use semantic or explicit lexical mode.')
        return retrieve_tasks(parsed.model_dump(),self.brain_fs_search,self._fs(),mode=mode,limit_per_function=limit_per_function,threshold=threshold,grouped_response=grouped)

    def brain_fs_interfaces(self,uid: str,required_features: list[str]) -> dict:
        """Inspect materialized planar/cylindrical surfaces. Distinguish inner cavity from solid shaft exterior; NOT proof of through-bore, fit, force transmission or fatigue."""
        e=self._fs().evidence(uid)
        return {'uid':uid,'evidence_digest':e['evidence_digest'],
                'interfaces':e['geometry'].get('interfaces') if e['geometry'] else None,
                'screen':screen_interfaces(e['geometry'],required_features)}

    def brain_studio_synthesize(self,project_id: str,expected_revision: int,matrix: dict[str,Any]) -> dict:
        """Combine real-reference mechanism options into compatible functional covers. Reject absent required surfaces and invented face IDs. Returns review subjects, NOT finished assemblies."""
        return self._studio().register_matrix(project_id,expected_revision,matrix)

    def brain_studio_build(self,project_id: str,expected_revision: int,recipe: dict[str,Any],timeout_seconds: int=120) -> dict:
        """Build a STEP-bound typed CAD recipe in a separate process; export real STEP/STL/SVG and static/sampled-motion clearance. No arbitrary Python exec, printer send or canonical project modification."""
        return self._studio().build(project_id,expected_revision,recipe,timeout_seconds)

    def brain_studio_review_packet(self,project_id: str,expected_revision: int,subject_digest: str,role: str) -> dict:
        """Prepare a requirements/mechanism/assembly/manufacturing/verification reviewer packet with real evidence and exact output schema. This does NOT spawn an independent LLM itself."""
        return self._studio().packet(project_id,expected_revision,subject_digest,role)

    def brain_studio_submit_review(self,project_id: str,expected_revision: int,subject_digest: str,review: dict[str,Any]) -> dict:
        """Record actual host-submitted engineering findings for this revision and subject. Roles and agreement never authenticate independent reviewers or clear physical tests."""
        return self._studio().submit(project_id,expected_revision,subject_digest,review)

    def brain_studio_reply(self,project_id: str,expected_revision: int,subject_digest: str,reply: dict[str,Any]) -> dict:
        """Record an evidence-based response to a specific review finding. No majority vote or prose rebuttal automatically clears a blocker."""
        return self._studio().reply(project_id,expected_revision,subject_digest,reply)

    def brain_studio_review_status(self,project_id: str,expected_revision: int,subject_digest: str) -> dict:
        """Read review coverage, open disagreements, geometry failures and unverified physical requirements. Reviewer independence and human approval are never inferred."""
        return self._studio().status(project_id,expected_revision,subject_digest)

    def brain_fusion_handoff(self,project_id: str,expected_revision: int,subject_digest: str) -> dict:
        """Issue the only Fusion adapter script allowed for this built subject. Host must pass it to fusion_mcp_execute unchanged. Does not save f3d. CadQuery remains the geometry referee."""
        from .fusion import issue_handoff
        return issue_handoff(self._studio(),project_id,expected_revision,subject_digest)

    def brain_fusion_ingest(self,project_id: str,expected_revision: int,subject_digest: str,adapter_sha256: str,fusion_report: dict[str,Any],export_step_relative: str | None=None) -> dict:
        """Accept Fusion print JSON only when it echoes the issued adapter. Remeasure overlap/clearance/motion in CadQuery. A Fusion screenshot is not a pass. f3d is not saved."""
        from .fusion import ingest_report
        return ingest_report(self._studio(),project_id,expected_revision,subject_digest,adapter_sha256,fusion_report,export_step_relative)
