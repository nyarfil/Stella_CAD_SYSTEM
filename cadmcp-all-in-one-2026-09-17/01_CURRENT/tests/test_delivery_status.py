"""Status projection tests; the subject loader is a double, not CAD proof."""
import pytest
from cadmcp_brain.studio.runtime import Studio


@pytest.mark.parametrize('verdict',['pass','fail',None])
def test_regular_build_exposes_measured_or_unrecorded_delivery_status(tmp_path,monkeypatch,verdict):
    check={'id':'_system-delivery-step-geometry-consistency','verdict':verdict}
    payload={'kind':'recipe_build','folder':str(tmp_path),
             'measurements':{'checks':[] if verdict is None else [check],
                             'geometry_checks_verdict':'pass'}}
    studio=object.__new__(Studio)
    monkeypatch.setattr(studio,'_subject',lambda *args:(tmp_path,{'payload':payload}))
    result=studio.status('fixture',0,'a'*64)
    delivery=result['delivery_step_consistency']
    assert delivery['verified'] is (verdict is not None)
    assert delivery['status']==(verdict or 'not_recorded')
    assert result['discussion_ready_for_owner'] is False
    assert result['overall_verdict']=='unknown'
