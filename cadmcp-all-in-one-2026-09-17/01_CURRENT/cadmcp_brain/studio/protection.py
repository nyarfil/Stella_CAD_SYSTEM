"""Persistent owner authority for imported CAD that Studio must not alter."""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..errors import BrainError
from ..models import Project, ProjectProtection
from ..req2cad.common import file_hash
from ..util import safe_path
from .recipe import Boolean, ProjectStep, Transform


def _environment_ids(name):
    try:
        value=json.loads(os.environ.get(name,'[]'))
    except json.JSONDecodeError as exc:
        raise BrainError('STUDIO_OWNER_POLICY','Owner reference IDs must be JSON arrays of strings.') from exc
    if not isinstance(value,list) or not all(isinstance(item,str) for item in value):
        raise BrainError('STUDIO_OWNER_POLICY','Owner reference IDs must be JSON arrays of strings.')
    return set(value)


def validate_policy(project: Project, root: Path, policy: ProjectProtection):
    """Accept only current, registered reference assets as durable protection."""
    for item in policy.assets:
        artifact=project.artifacts.get(item.artifact_id)
        if not artifact or artifact.contract_digest!='reference':
            raise BrainError('STUDIO_PROTECTED','Protected CAD must name one registered project reference.',{'artifact_id':item.artifact_id})
        if artifact.sha256!=item.sha256:
            raise BrainError('STUDIO_PROTECTED','Protected CAD hash is not the current registered reference hash.',{'artifact_id':item.artifact_id})
        path=safe_path(root,artifact.filename)
        if file_hash(path)!=item.sha256:
            raise BrainError('STUDIO_STALE_HARDWARE','Protected project reference bytes changed.',{'artifact_id':item.artifact_id})
    for item in policy.editable_references:
        artifact=project.artifacts.get(item.artifact_id)
        if not artifact or artifact.contract_digest!='reference':
            raise BrainError('STUDIO_OWNER_POLICY','Editable CAD must name one registered project reference.',{'artifact_id':item.artifact_id})
        if artifact.sha256!=item.sha256:
            raise BrainError('STUDIO_OWNER_POLICY','Editable CAD hash is not the current registered reference hash.',{'artifact_id':item.artifact_id})
        path=safe_path(root,artifact.filename)
        if file_hash(path)!=item.sha256:
            raise BrainError('STUDIO_STALE_HARDWARE','Editable project reference bytes changed.',{'artifact_id':item.artifact_id})


def effective_policy(project: Project, root: Path, policy: ProjectProtection | None=None):
    """Merge durable policy with legacy environment guards without weakening either."""
    policy=policy or project.protection
    validate_policy(project,root,policy)
    persisted={item.artifact_id:item for item in policy.assets}
    environment_protected=_environment_ids('CADMCP_PROTECTED_ARTIFACT_IDS')
    persisted_editable={item.artifact_id:item for item in policy.editable_references}
    editable=set(persisted_editable)|_environment_ids('CADMCP_EDITABLE_REFERENCE_IDS')
    protected=set(persisted)|environment_protected
    if protected&editable:
        raise BrainError('STUDIO_OWNER_POLICY','An artifact cannot be protected and editable.',{'artifact_ids':sorted(protected&editable)})
    return persisted,protected,persisted_editable,editable


def validate_recipe(project: Project, root: Path, recipe):
    """Require protected geometry unchanged, placed as imported and exported by name."""
    persisted,protected,persisted_editable,editable=effective_policy(project,root)
    steps={}
    for node in recipe.operations:
        if isinstance(node,ProjectStep): steps.setdefault(node.artifact_id,[]).append(node)
    outputs={item.part_id:item for item in recipe.outputs}
    for artifact_id in protected:
        candidates=steps.get(artifact_id,[])
        if len(candidates)!=1 or candidates[0].role!='protected_hardware':
            raise BrainError('STUDIO_PROTECTED','Owner-protected hardware must remain a fixed project-step in this build.',{'artifact_id':artifact_id})
        node=candidates[0]
        if artifact_id in persisted:
            item=persisted[artifact_id]
            if node.sha256!=item.sha256:
                raise BrainError('STUDIO_PROTECTED','Recipe hash differs from the owner-protected asset.',{'artifact_id':artifact_id})
            output=outputs.get(item.required_output_id)
            if not output or output.node!=node.id:
                raise BrainError('STUDIO_PROTECTED','A protected asset must remain an exact, named required output.',{'artifact_id':artifact_id,'required_output_id':item.required_output_id})
        elif not any(output.node==node.id for output in recipe.outputs):
            # Exact legacy behavior: environment-only policy required the
            # protected node to survive as an output, without inventing an ID.
            raise BrainError('STUDIO_PROTECTED','Owner-protected hardware must remain present in the output assembly.',{'artifact_id':artifact_id})
        for operation in recipe.operations:
            if isinstance(operation,Transform) and operation.source==node.id:
                raise BrainError('STUDIO_PROTECTED','Protected CAD cannot be transformed from its registered placement.',{'artifact_id':artifact_id})
            if isinstance(operation,Boolean) and node.id in operation.operands and (operation.op=='union' or operation.operands[0]==node.id):
                raise BrainError('STUDIO_PROTECTED','Protected CAD cannot be a boolean target or fused geometry.',{'artifact_id':artifact_id})
    for node in recipe.operations:
        if isinstance(node,ProjectStep) and node.role=='design_reference' and node.artifact_id not in editable:
            raise BrainError('STUDIO_PROTECTED','The owner must explicitly permit editing this project reference.',{'artifact_id':node.artifact_id})
        if isinstance(node,ProjectStep) and node.role=='design_reference' and node.artifact_id in persisted_editable and node.sha256!=persisted_editable[node.artifact_id].sha256:
            raise BrainError('STUDIO_PROTECTED','Recipe hash differs from the owner-approved editable reference.',{'artifact_id':node.artifact_id})
    return {'persistent_assets':[item.model_dump(mode='json') for item in persisted.values()],
            'environment_protected_ids':sorted(_environment_ids('CADMCP_PROTECTED_ARTIFACT_IDS')),
            'editable_reference_ids':sorted(editable),'placement_rule':'as_registered'}
