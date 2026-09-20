from cadmcp_brain.errors import BrainError
from cadmcp_brain.studio.planning import capabilities,recovery_for
from cadmcp_brain.studio.recipe import DELIVERY_MAX_SOLIDS


def test_delivery_comparison_is_discoverable_with_its_actual_capacity():
    result=capabilities(required_checks=['delivery_step_equivalence'])
    assert result['requested_capabilities_supported']
    assert result['verification_limits']['delivery_step_equivalence_max_solids']==DELIVERY_MAX_SOLIDS
    assert result['design_feasibility_certified'] is False


def test_capacity_is_not_misreported_as_a_bad_design():
    result=recovery_for(BrainError('STUDIO_DELIVERY_COMPLEXITY','limit'))
    assert result['category']=='verification_capacity'
    assert 'Do not remove parts' in result['next_action']
