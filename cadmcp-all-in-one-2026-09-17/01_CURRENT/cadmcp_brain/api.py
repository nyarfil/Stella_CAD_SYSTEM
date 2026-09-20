"""Typed tool registry shared by the stdio server and embedding integrations."""
from __future__ import annotations
import inspect
import os
import platform
import sys
from typing import Any, get_type_hints
from pydantic import ConfigDict, ValidationError, create_model
from . import __version__, geometry
from .engine import Brain
from .backend import AgentCADClient
from .models import SCHEMAS
from .errors import BrainError


from .req2cad.mixin import Req2CADToolsMixin

from .studio.mixin import StudioToolsMixin
from .studio.mouse import BoardRegistry, ShellRegistry, MouseToolsMixin, structure_gate

class Tools(MouseToolsMixin,StudioToolsMixin,Req2CADToolsMixin):
    def __init__(self,brain: Brain,backend: AgentCADClient | None=None):
        self.brain=brain
        self.backend=backend or AgentCADClient(None)
        self.registry={}
        for name in dir(self):
            if not name.startswith("brain_"): continue
            fn=getattr(self,name)
            signature=inspect.signature(fn); hints=get_type_hints(fn)
            fields={k:(hints[k],... if v.default is inspect.Parameter.empty else v.default) for k,v in signature.parameters.items()}
            model=create_model(name+"_arguments",__config__=ConfigDict(extra="forbid",strict=True,allow_inf_nan=False),**fields)
            self.registry[name]={"handler":fn,"model":model,"description":inspect.getdoc(fn) or name}

    def list(self):
        readonly={"brain_get","brain_task","brain_schema","brain_patterns","brain_history","brain_backend_probe","brain_doctor","brain_fs_status","brain_fs_search","brain_fs_case","brain_fs_evidence","brain_fs_compare","brain_fs_portfolio","brain_studio_schema","brain_fs_search_tasks","brain_fs_interfaces","brain_studio_review_status","brain_mouse_inspect_inputs","brain_mouse_get_board_pack","brain_mouse_list_board_packs","brain_mouse_get_shell_pack","brain_mouse_list_shell_packs","brain_mouse_structure_gate"}
        readonly.update({'brain_projects', 'brain_studio_attempts', 'brain_studio_capabilities', 'brain_get_project_protection'})
        return [{"name":name,"description":t["description"],"inputSchema":t["model"].model_json_schema(),"annotations":{"readOnlyHint":name in readonly,"destructiveHint":name in {"brain_backend_call", "brain_set_project_protection"},"openWorldHint":name in {"brain_backend_probe","brain_backend_call"}}} for name,t in sorted(self.registry.items())]

    def call(self,name: str,arguments: dict[str,Any]):
        if name not in self.registry: raise BrainError("UNKNOWN_TOOL","Unknown brain tool.",{"name":name})
        tool=self.registry[name]
        args=tool["model"].model_validate(arguments)
        return tool["handler"](**args.model_dump())

    def brain_open(self,project_id: str,request: str) -> dict:
        """Start source-grounded design. request is the user's exact original text, not an invented paraphrase. Next call brain_task."""
        return self.brain.open(project_id,request)

    def brain_get(self,project_id: str) -> dict:
        """Read current state and revision. Reload after REVISION_CONFLICT; never overwrite a newer design."""
        return self.brain.get(project_id)

    def brain_get_project_protection(self,project_id: str) -> dict:
        """Read durable project protection and effective legacy environment guards. No CAD/model execution or policy change."""
        return self.brain.get_project_protection(project_id)

    def brain_set_project_protection(self,project_id: str,expected_revision: int,protection: dict[str,Any],reason: str) -> dict:
        """Explicit owner-directed policy change only, never an automatic repair. Replaces project protection, records before/after and reason, advances revision. Get ProjectProtection via brain_schema. Caller identity/owner approval must be enforced by the host; a reason is not authentication. Can remove protection or grant editing, so requires approval review."""
        return self.brain.set_project_protection(project_id,expected_revision,protection,reason)

    def brain_projects(self,limit: int=50,offset: int=0) -> dict:
        """List saved project IDs/revisions. Legacy next_stage does not describe Studio builds; use brain_studio_attempts for prototype history."""
        total, projects = self.brain.store.list_projects(limit, offset)
        return {'total': total, 'projects': [self.brain.summary(p) for p in projects],
                'next_offset': offset + len(projects) if offset + len(projects) < total else None,
                'stage_scope': 'legacy Brief/Concept/Plan only; Studio is a separate workflow'}

    def brain_studio_attempts(self,project_id: str,limit: int=50,offset: int=0) -> dict:
        """List persisted Studio subjects and current/stale revisions. Recorded geometry verdicts are history, not freshly verified evidence. Use review_status to recheck hashes."""
        return self._studio().attempts(project_id, limit, offset)

    def brain_add_source(self,project_id: str,expected_revision: int,text: str) -> dict:
        """Append an exact new user instruction; invalidate old intent, concepts, plans and verification, preserving audit history."""
        return self.brain.add_source(project_id,expected_revision,text)

    def brain_task(self,project_id: str,stage: str | None=None) -> dict:
        """Get the next host-model task, relevant state and exact JSON schema. The server does not pretend to understand natural language itself."""
        return self.brain.task(project_id,stage)

    def brain_schema(self,name: str) -> dict:
        """Read a versioned Brief, Concept, Concepts or Plan JSON schema."""
        if name not in SCHEMAS: raise BrainError("UNKNOWN_SCHEMA","Choose Brief, Concept, Concepts or Plan.")
        return SCHEMAS[name].model_json_schema()

    def brain_patterns(self,query: str="",limit: int=6,function: str | None=None) -> dict:
        """Retrieve original mechanism patterns using lexical English/Japanese search. Results are not validated designs or dimensional allowables."""
        return {"retrieval":"lexical_not_embedding","results":self.brain.catalog.search(query,limit,function)}

    def brain_submit_intent(self,project_id: str,expected_revision: int,brief: dict[str,Any]) -> dict:
        """Validate and commit the source-linked Brief. Reject source omissions, fabricated quotations, contradictory constraints and mandatory inferences."""
        return self.brain.submit_intent(project_id,expected_revision,brief)

    def brain_submit_concepts(self,project_id: str,expected_revision: int,concepts: dict[str,Any]) -> dict:
        """Commit 2–4 distinct FBS mechanism alternatives and return mechanical/declaration gate results for each."""
        return self.brain.submit_concepts(project_id,expected_revision,concepts)

    def brain_select(self,project_id: str,expected_revision: int,concept_id: str) -> dict:
        """Select a gate-eligible concept. This does not attest human approval, printability, strength or fatigue life."""
        return self.brain.select(project_id,expected_revision,concept_id)

    def brain_submit_plan(self,project_id: str,expected_revision: int,plan: dict[str,Any]) -> dict:
        """Commit a typed geometric construction plan with dependency, provenance and test-obligation validation."""
        return self.brain.submit_plan(project_id,expected_revision,plan)

    def brain_export(self,project_id: str,expected_revision: int) -> dict:
        """Export immutable contract.json, CAD_HANDOFF.md and design_graph.json for the existing CAD backend. Does not execute CAD."""
        return self.brain.export(project_id,expected_revision)

    def brain_import_step(self,project_id: str,expected_revision: int,artifact_id: str,relative_path: str,contract_digest: str | None=None,purpose: str="output") -> dict:
        """Copy/hash a workspace-relative STEP. output needs current contract digest; reference performs actual kernel measurements and invalidates concepts/plans. Trusted local STEP only."""
        return self.brain.import_step(project_id,expected_revision,artifact_id,relative_path,contract_digest,purpose)

    def brain_verify(self,project_id: str,expected_revision: int) -> dict:
        """Measure imported B-reps and evaluate listed geometry checks. Missing/stale/unsupported evidence remains unknown; physical performance is not certified."""
        return self.brain.verify(project_id,expected_revision)

    def brain_history(self,project_id: str) -> dict:
        """Read the transactional project event history."""
        return {"events":self.brain.store.history(project_id)}

    def brain_backend_probe(self) -> dict:
        """Read the configured loopback AgentCAD live tool registry. Disabled unless CADMCP_AGENTCAD_URL is set by the owner."""
        return self.backend.probe()

    def brain_backend_call(self,project_id: str,expected_revision: int,contract_digest: str,call_id: str,tool: str,arguments: dict[str,Any],dry_run: bool=True) -> dict:
        """Opt-in gated AgentCAD call. Owner allowlist required. Default dry-run. A call_id permits at most one network write attempt; never retry uncertain outcomes."""
        return self.brain.backend_call(self.backend,project_id,expected_revision,contract_digest,call_id,tool,arguments,dry_run)

    def brain_doctor(self) -> dict:
        """Report local capabilities without pretending to test a remote CAD backend or a Windows/Cursor installation."""
        root=self.brain.store.root
        return {"version":__version__,"python":sys.version.split()[0],"platform":platform.platform(),"workspace":str(root),"protocol":"2025-06-18 stdio subset","geometry_extra_available":geometry.available(),"host_llm_required":True,"external_llm_api_used":False,"agentcad_configured":bool(self.backend.base_url),"backend_allowed_tools":sorted(self.backend.allowed_tools),"mouse_board_packs":BoardRegistry(root).summary(),"mouse_shell_packs":ShellRegistry(root).summary(),"mouse_structure_intake":structure_gate(root),"req2cad_is_not_implied_ready":True}
