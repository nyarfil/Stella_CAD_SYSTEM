"""Capability-based, host-directed dispatch; CAD writes stay in existing adapters."""
from __future__ import annotations

import hashlib
import importlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .planning import capabilities
from .. import geometry
from ..errors import BrainError


Backend = Literal['cadquery', 'build123d', 'freecad', 'classcad', 'fusion']
BACKENDS = ('cadquery', 'build123d', 'freecad', 'classcad', 'fusion')
ADVANCED = frozenset({'surface_loft', 'sweep', 'shell', 'spline_surface',
                      'editable_history', 'mesh_reconstruction'})
EXTERNAL_CHECK_MAP = {
    'solid_validity': ['brep_valid'], 'solid_count': ['solid_count'],
    'bbox': ['bbox_x_mm', 'bbox_y_mm', 'bbox_z_mm'],
    'rigid_pair_interference': ['intersection_mm3'], 'static_clearance': ['distance_mm'],
}
WORKFLOWS = {
    'cadquery': 'brain_studio_build: validated typed Recipe',
    'build123d': 'cadgen CLI: project-owned parametric source in its separate runtime',
    'freecad': 'project FreeCAD MCP: named document, Python API, retain FCStd',
    'classcad': 'project ClassCAD MCP: isolated session, export STEP',
    'fusion': 'stella-fusion-community: project document allowlist, export STEP',
}


class BackendProbe(BaseModel):
    """Host observations of the actual adapter, never a product feature catalogue."""
    model_config = ConfigDict(extra='forbid', strict=True)
    backend: Backend
    installed: bool
    ready: bool
    operations: list[str] = Field(default_factory=list, max_length=128)
    evidence: str = Field(min_length=1, max_length=2048)
    cost: Literal['free', 'owned_perpetual', 'subscription', 'unknown'] = 'unknown'


class BackendRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    required_operations: list[str] = Field(min_length=1, max_length=128)
    required_checks: list[str] = Field(default_factory=list, max_length=128)
    mode: Literal['explicit', 'auto'] = 'explicit'
    selected_backend: Backend | None = None
    allowed_backends: list[Backend] = Field(default_factory=lambda: ['cadquery', 'freecad', 'build123d'])
    probes: list[BackendProbe] = Field(default_factory=list, max_length=5)


def route_backend(request: dict) -> dict:
    """Return one executor and a common verification handoff, without writes or fallback."""
    parsed = BackendRequest.model_validate(request)
    native = capabilities(parsed.required_operations, parsed.required_checks)
    by_backend = {probe.backend: probe for probe in parsed.probes}
    if len(by_backend) != len(parsed.probes):
        raise ValueError('Duplicate backend probes are ambiguous')
    if any(not op.strip() for op in parsed.required_operations):
        raise ValueError('Required operations must not be blank')
    # Only this process can establish native Recipe support. A host cannot extend
    # the native interpreter by claiming that the CadQuery library has an API.
    available = geometry.available()
    ready = False
    if available:
        try:
            importlib.import_module('cadquery')
            ready = True
        except Exception:
            # Presence of a package is not proof that its compiled kernel loads.
            pass
    by_backend['cadquery'] = BackendProbe(
        backend='cadquery', installed=available, ready=ready,
        operations=native['operations'], cost='free',
        evidence='Current Recipe schema, package detection and successful CadQuery import when ready; no CAD build performed',
    )
    advanced = bool(set(parsed.required_operations) & ADVANCED)
    order = (['freecad', 'build123d', 'cadquery', 'classcad', 'fusion'] if advanced
             else ['cadquery', 'build123d', 'freecad', 'classcad', 'fusion'])
    candidates = []
    for backend in order:
        probe = by_backend.get(backend)
        missing = sorted(set(parsed.required_operations) - set(probe.operations if probe else []))
        missing_checks = (native['unsupported_checks'] if backend == 'cadquery' else
                          sorted(set(parsed.required_checks) - set(EXTERNAL_CHECK_MAP)))
        reasons = []
        if backend not in parsed.allowed_backends:
            reasons.append('outside_project_allowlist')
        if probe is None:
            reasons.append('adapter_not_probed')
        else:
            if probe.cost not in ('free', 'owned_perpetual'):
                reasons.append('cost_not_allowed_or_unknown')
            if not probe.installed:
                reasons.append('runtime_not_installed')
            if not probe.ready:
                reasons.append('adapter_not_ready')
        if missing:
            reasons.append('required_operations_unavailable')
        if missing_checks:
            reasons.append('verification_route_unsupported')
        candidates.append({'backend': backend, 'eligible': not reasons,
                           'missing_operations': missing, 'missing_checks': missing_checks, 'reasons': reasons,
                           'probe': probe.model_dump() if probe else None})
    selected = None
    if not ready:
        status = 'verification_engine_unavailable'
    elif native['unsupported_checks']:
        status = 'verification_extension_required'
    elif parsed.mode == 'explicit':
        if parsed.selected_backend is None:
            status = 'selection_required'
        else:
            candidate = next(c for c in candidates if c['backend'] == parsed.selected_backend)
            selected = candidate['backend'] if candidate['eligible'] else None
            status = 'ready' if selected else 'selected_backend_unavailable'
    else:
        selected = next((c['backend'] for c in candidates if c['eligible']), None)
        status = 'ready' if selected else 'no_capable_backend'
    result = {
        'schema_version': 1, 'status': status, 'mode': parsed.mode,
        'selected_backend': selected, 'requested_backend': parsed.selected_backend,
        'requirements': {'operations': parsed.required_operations, 'checks': parsed.required_checks},
        'selection_reason': ('preserve_explicit_project_selection' if parsed.mode == 'explicit'
                             else 'prefer_surface_editing_environment' if advanced
                             else 'prefer_native_typed_recipe'),
        'candidates': candidates,
        'dispatch': ({'backend': selected, 'workflow': WORKFLOWS[selected],
                      'executor': 'host', 'single_writer': True,
                      'recheck_adapter_before_write': True} if selected else None),
        'verification': {
            'kernel': 'CadQuery / OpenCascade',
            'native_route': 'brain_studio_build and STEP equivalence checks',
            'external_route': ['brain_export', 'brain_import_step(purpose=output, contract_digest)', 'brain_verify'],
            'required_checks': parsed.required_checks,
            'unsupported_checks': native['unsupported_checks'],
            'external_check_mapping': EXTERNAL_CHECK_MAP,
            'preserve': ['original_request', 'protected_geometry_and_placements', 'check_thresholds',
                         'native_editable_document', 'input_and_output_hashes'],
        },
        'automatic_failure_fallback': False, 'executed': False,
        'probe_trust': 'External probes are host-supplied observations; this tool does not contact other MCPs.',
        'design_feasibility_certified': False,
    }
    result['decision_sha256'] = hashlib.sha256(json.dumps(
        result, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()
    return result


class BackendRoutingToolsMixin:
    def brain_cad_route(self, request: dict) -> dict:
        """Choose one CAD adapter by required operations, observed readiness, project selection and free/owned cost policy. Read-only host dispatch plan; external probes are host observations. No CAD execution, settings writes or failure fallback."""
        try:
            return route_backend(request)
        except ValueError as exc:
            raise BrainError('CAD_ROUTING_ARGUMENT', str(exc)[:2000]) from exc
