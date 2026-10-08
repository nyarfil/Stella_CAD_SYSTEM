"""Capability discovery and actionable failure classification; never a fallback executor."""
from __future__ import annotations
from .recipe import Recipe, DELIVERY_MAX_SOLIDS


def capabilities(required_operations=(), required_checks=()):
    definitions = Recipe.model_json_schema()['$defs'].values()
    operations = sorted({item['properties']['op']['const'] for item in definitions
                         if 'const' in item.get('properties', {}).get('op', {})}
                        | {value for item in definitions
                           for value in item.get('properties', {}).get('op', {}).get('enum', [])})
    checks = ['solid_validity', 'solid_count', 'bbox', 'inner_cylinder_diameter',
              'outer_cylinder_diameter', 'rigid_pair_interference', 'static_clearance',
              'sampled_translation_clearance', 'delivery_step_equivalence']
    missing_ops = sorted(set(required_operations) - set(operations))
    missing_checks = sorted(set(required_checks) - set(checks))
    return {'operations': operations, 'checks': checks,
            'unsupported_operations': missing_ops, 'unsupported_checks': missing_checks,
            'requested_capabilities_supported': not (missing_ops or missing_checks),
            'verification_limits': {'delivery_step_equivalence_max_solids': DELIVERY_MAX_SOLIDS},
            'reference_policy': 'principle_reference, fit_reference, direct_reuse or explicit original design; shape reuse is not mandatory',
            'limitations': ['No rotational or elastic-motion verification.',
                            'Rigid pair overlap is not a press-fit deformation model.',
                            'Loft supports only bounded parallel XY polygon sections; sweep paths, arbitrary section planes, splines and shelling are unsupported.',
                            'No physical strength, fatigue or manufacturing certification.'],
            'next': ('Plan with supported operations and verify the result.' if not (missing_ops or missing_checks)
                     else 'Identify an equivalent design preserving the requirements, or implement and test the missing capability. Do not silently substitute geometry or waive checks.'),
            'design_feasibility_certified': False}


def recovery_for(error):
    code = getattr(error, 'code', type(error).__name__)
    if any(word in code for word in ('STALE', 'CHANGED', 'PROTECTED', 'WEAKENED', 'REVISION')):
        kind, action = 'integrity_or_contract', 'Reload the exact evidence/contract; preserve all owner constraints. Do not retry with weaker checks.'
    elif code.startswith('FS_'):
        kind, action = 'reference_data', 'Record unavailable evidence; repair the catalog or explicitly plan from provided CAD/first principles. Do not claim successful retrieval.'
    elif code in ('AUTOPILOT_NO_CONCEPT', 'AUTOPILOT_DECLINED'):
        kind, action = 'concept', 'Replan mechanisms within the remaining call budget, preserving the original requirements.'
    elif code == 'ValidationError':
        kind, action = 'recipe_contract', 'Inspect the validation location and capability report; correct the operation graph without changing acceptance conditions.'
    elif code == 'STUDIO_DELIVERY_COMPLEXITY':
        kind, action = 'verification_capacity', 'The delivery comparator capacity was exceeded, not a proved geometry defect. Preserve every part and check; extend and test verification capacity before retrying. Do not remove parts to pass.'
    elif code in ('STUDIO_BUILD', 'STUDIO_TIMEOUT'):
        kind, action = 'geometry_execution', 'Inspect the worker evidence and revise the relevant operation; retain the failed attempt.'
    elif code in ('AGENT_BUDGET', 'AGENT_TIMEOUT'):
        kind, action = 'execution_budget', 'Keep checkpoints and stop external calls. A later run needs an explicit budget.'
    else:
        kind, action = 'diagnosis_required', 'Inspect the recorded error before retrying; no automatic alternate engine.'
    return {'category': kind, 'code': code, 'next_action': action,
            'automatic_retry': False, 'requirements_relaxed': False}
