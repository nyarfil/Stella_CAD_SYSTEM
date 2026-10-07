from unittest.mock import patch
import importlib
import importlib.util
import json
import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from cadmcp_brain.api import Tools
from cadmcp_brain.studio.backend_routing import route_backend


def probe(backend='freecad', operations=None, **overrides):
    return dict(backend=backend, installed=True, ready=True,
                operations=operations or ['shell', 'surface_loft'],
                evidence='isolated adapter test, fixture hash and operation receipt',
                cost='free', **overrides)


_real_import = importlib.import_module


def _kernel_loads(name, *args, **kwargs):
    # Simulate a loadable kernel for routing-logic tests only; other imports stay real.
    return object() if name == 'cadquery' else _real_import(name, *args, **kwargs)


@pytest.fixture(autouse=True)
def native_available():
    with patch('cadmcp_brain.studio.backend_routing.geometry.available', return_value=True), \
         patch('cadmcp_brain.studio.backend_routing.importlib.import_module', side_effect=_kernel_loads):
        yield


def test_simple_native_and_limited_loft():
    result = route_backend({'mode': 'auto', 'required_operations': ['box', 'loft']})
    assert result['selected_backend'] == 'cadquery'
    assert result['executed'] is False
    assert result['automatic_failure_fallback'] is False


def test_native_shell_and_spline_loft_route_to_cadquery_without_external_adapter():
    result = route_backend({'mode': 'auto', 'required_operations': ['spline_loft', 'shell', 'fillet_edges'],
                            'required_checks': ['sampled_rotation_clearance']})
    assert result['selected_backend'] == 'cadquery'
    assert result['status'] == 'ready'


def test_advanced_surface_uses_observed_freecad():
    result = route_backend({'mode': 'auto', 'required_operations': ['shell', 'surface_loft'],
                            'probes': [probe()]})
    assert result['selected_backend'] == 'freecad'
    assert result['dispatch']['executor'] == 'host'
    assert 'brain_verify' in result['verification']['external_route']


def test_explicit_cadquery_does_not_switch_on_missing_operation():
    result = route_backend({'required_operations': ['surface_loft'], 'selected_backend': 'cadquery',
                            'probes': [probe()]})
    assert result['status'] == 'selected_backend_unavailable'
    assert result['selected_backend'] is None


@pytest.mark.parametrize('overrides', [{'ready': False}, {'installed': False},
                                     {'cost': 'subscription'}, {'cost': 'unknown'}])
def test_unavailable_or_unfunded_adapter_blocked(overrides):
    observation = probe()
    observation.update(overrides)
    result = route_backend({'mode': 'auto', 'required_operations': ['surface_loft'],
                            'probes': [observation]})
    assert result['status'] == 'no_capable_backend'


def test_unsupported_check_blocks_otherwise_valid_geometry():
    result = route_backend({'mode': 'auto', 'required_operations': ['surface_loft'],
                            'required_checks': ['fatigue'], 'probes': [probe()]})
    assert result['status'] == 'verification_extension_required'
    assert result['selected_backend'] is None


def test_build123d_can_dispatch_only_observed_operations():
    result = route_backend({'mode': 'auto', 'required_operations': ['sweep'],
                            'probes': [probe('build123d', ['sweep'])]})
    assert result['selected_backend'] == 'build123d'
    assert 'cadgen CLI' in result['dispatch']['workflow']


def test_host_cannot_extend_native_recipe_by_claim():
    result = route_backend({'mode': 'auto', 'required_operations': ['surface_loft'],
                            'probes': [probe('cadquery')]})
    assert result['status'] == 'no_capable_backend'


def test_unknown_or_duplicate_probes_rejected():
    with pytest.raises(ValidationError):
        route_backend({'mode': 'auto', 'required_operations': ['box'], 'probes': [dict(probe(), backend='invented')]})
    with pytest.raises(ValueError, match='Duplicate'):
        route_backend({'mode': 'auto', 'required_operations': ['box'], 'probes': [probe(), probe()]})


def test_external_route_cannot_claim_native_only_verification():
    result = route_backend({'mode': 'auto', 'required_operations': ['surface_loft'],
                            'required_checks': ['sampled_translation_clearance'], 'probes': [probe()]})
    assert result['status'] == 'no_capable_backend'
    freecad = next(c for c in result['candidates'] if c['backend'] == 'freecad')
    assert freecad['missing_checks'] == ['sampled_translation_clearance']


def test_missing_or_broken_common_verifier_blocks_external_generation():
    with patch('cadmcp_brain.studio.backend_routing.geometry.available', return_value=False):
        assert route_backend({'mode': 'auto', 'required_operations': ['surface_loft'],
                              'probes': [probe()]})['status'] == 'verification_engine_unavailable'
    with patch('cadmcp_brain.studio.backend_routing.importlib.import_module', side_effect=ImportError('kernel')):
        assert route_backend({'mode': 'auto', 'required_operations': ['box']})['status'] == 'verification_engine_unavailable'


def test_mcp_route_readonly_and_schema(brain):
    tools = Tools(brain)
    tool = next(t for t in tools.list() if t['name'] == 'brain_cad_route')
    assert tool['annotations']['readOnlyHint'] is True
    assert tools.call('brain_studio_schema', {'name': 'BackendRequest'})['properties']['probes']
    assert tools.call('brain_cad_route', {'request': {'mode': 'auto', 'required_operations': ['box']}})['status'] == 'ready'


@pytest.mark.skipif(importlib.util.find_spec('cadquery') is None,
                    reason='Actual CAD kernel not installed; real stdio routing dispatch not claimed executed.')
def test_real_stdio_dispatch_in_isolated_workspace(tmp_path):
    workspace = tmp_path / 'isolated 日本語'
    messages = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-06-18', 'capabilities': {},
            'clientInfo': {'name': 'route-acceptance', 'version': '1'}}},
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {
            'name': 'brain_cad_route', 'arguments': {'request': {
                'mode': 'auto', 'required_operations': ['box'], 'required_checks': ['bbox']}}}},
        {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {
            'name': 'brain_cad_route', 'arguments': {'request': {
                'mode': 'auto', 'required_operations': ['surface_loft']}}}},
    ]
    proc = subprocess.run([sys.executable, '-m', 'cadmcp_brain', '--workspace', str(workspace), 'serve'],
                          input=''.join(json.dumps(m) + '\n' for m in messages),
                          capture_output=True, text=True, encoding='utf-8', timeout=30,
                          env=dict(os.environ, PYTHONUTF8='1'))
    assert proc.returncode == 0, proc.stderr
    replies = [json.loads(line) for line in proc.stdout.splitlines()]
    assert len(replies) == 3
    assert replies[1]['result']['isError'] is False
    result = json.loads(replies[1]['result']['content'][0]['text'])['result']
    assert result['selected_backend'] == 'cadquery' and result['executed'] is False
    blocked = json.loads(replies[2]['result']['content'][0]['text'])['result']
    assert blocked['status'] == 'no_capable_backend'
    assert not list(workspace.rglob('*.step'))
