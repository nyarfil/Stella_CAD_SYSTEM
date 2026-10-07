"""Project-local automatic CAD dispatch using the native Stella routing contract.

Planning is read-only. ``auto`` saves an allowed-backend policy; ``plan --activate``
uses the existing selector to activate one writer. CAD work runs through host tools.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'cadmcp-all-in-one-2026-09-17' / '01_CURRENT'))
from cadmcp_brain.studio.backend_routing import BACKENDS, BackendRequest, route_backend
from pydantic import ValidationError
import select_backend as selector

POLICY_PATH = Path('.stella/cad-routing.json')


def policy_path(project: Path) -> Path:
    selector._state_path(project)  # existing project path boundary
    return project / POLICY_PATH


def set_auto(project: Path, allowed: list[str]) -> dict:
    if not allowed or len(set(allowed)) != len(allowed) or any(b not in BACKENDS for b in allowed):
        raise selector.SelectionError('Use a nonempty unique list of known CAD backends')
    policy = {'schema_version': 1, 'project_root': str(project), 'mode': 'auto',
              'allowed_backends': allowed}
    with selector._exclusive_selection_lock(project):
        selector._write_json_atomic(policy_path(project), policy)
    return {'policy': policy, 'activated': False,
            'next_action': 'Plan operations with current adapter probes; explicit selection still takes priority.'}


def read_policy(project: Path) -> dict | None:
    path = policy_path(project)
    if not path.exists():
        return None
    policy = selector._read_json(path)
    if (policy.get('schema_version') != 1 or policy.get('mode') != 'auto'
            or policy.get('project_root') != str(project)):
        raise selector.SelectionError('Invalid or foreign CAD routing policy')
    BackendRequest.model_validate({'required_operations': ['box'], 'mode': 'auto',
                                   'allowed_backends': policy.get('allowed_backends')})
    return policy


def plan(project: Path, operations: list[str], checks: list[str], probes: list[dict],
         kit: Path | None = None, activate: bool = False) -> dict:
    selection = selector.read_selection(project)
    policy = read_policy(project)
    explicit = selection is not None and selection['selection_mode'] == 'explicit'
    if selection and selection['backend'] == 'freecad':
        kit = selector._canonical_directory(selection['backend_config']['kit'], 'FreeCAD kit')
    observations = [dict(p) for p in probes]
    # A supplied FreeCAD capability test must also match the selected kit's
    # process/profile identity before activation. Installation alone is insufficient.
    for probe in observations:
        if probe.get('backend') == 'freecad':
            if kit is None:
                probe['ready'] = False
            else:
                inspected = selector.inspect_freecad_kit(kit)
                probe['installed'] = probe.get('installed') is True and inspected['installed']
                probe['ready'] = probe.get('ready') is True and inspected['ready']
    request = {'required_operations': operations, 'required_checks': checks,
               'mode': 'explicit' if explicit or policy is None else 'auto',
               'selected_backend': selection['backend'] if explicit else None,
               'allowed_backends': [selection['backend']] if explicit else (
                   policy['allowed_backends'] if policy else ['cadquery', 'freecad', 'build123d']),
               'probes': observations}
    decision = route_backend(request)
    result = {'decision': decision, 'activated': False, 'executed': False}
    if activate:
        if decision['status'] != 'ready':
            raise selector.SelectionError('CAD dispatch blocked: ' + decision['status'])
        if explicit:
            result['instruction'] = 'Use the existing explicit project selection and its host workflow.'
        else:
            backend = decision['selected_backend']
            # Recheck the policy under the same selector lock as the config write.
            result['activation'] = selector.select_backend(
                project, backend, kit if backend == 'freecad' else None,
                routing_decision=decision, expected_selection=selection,
                expected_routing_policy=policy, routing_request=request)
            result['activated'] = True
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    auto = commands.add_parser('auto', help='enable project-local capability selection')
    auto.add_argument('--project', required=True)
    auto.add_argument('--allow', nargs='+', choices=BACKENDS, default=['cadquery', 'freecad', 'build123d'])
    route = commands.add_parser('plan', help='plan a single writer; optionally activate its MCP config')
    route.add_argument('--project', required=True)
    route.add_argument('--operations', nargs='+', required=True)
    route.add_argument('--checks', nargs='*', default=[])
    route.add_argument('--probes', help='JSON list of current host-observed BackendProbe records')
    route.add_argument('--kit', help='project FreeCAD kit for identity checks')
    route.add_argument('--activate', action='store_true')
    args = parser.parse_args(argv)
    try:
        project = selector._canonical_directory(args.project, 'project')
        if args.command == 'auto':
            result = set_auto(project, args.allow)
        else:
            probes = json.loads(Path(args.probes).read_text('utf-8-sig')) if args.probes else []
            if not isinstance(probes, list) or any(not isinstance(p, dict) for p in probes):
                raise selector.SelectionError('Probes must be a JSON list of objects')
            kit = selector._canonical_directory(args.kit, 'FreeCAD kit') if args.kit else None
            result = plan(project, args.operations, args.checks, probes, kit, args.activate)
    except (selector.SelectionError, ValidationError, ValueError, OSError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({'ok': True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
