"""MCP declares policy mutation separately from ordinary CAD build operations."""
import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.errors import BrainError


def test_project_protection_tools_and_revision_guard(brain):
    tools=Tools(brain)
    tools.brain_open('policy-api','Preserve owner-designated reference components.')
    entries={x['name']:x for x in tools.list()}
    assert entries['brain_get_project_protection']['annotations']['readOnlyHint']
    update=entries['brain_set_project_protection']
    assert update['annotations']['destructiveHint'] and not update['annotations']['readOnlyHint']
    assert 'not authentication' in update['description']
    assert tools.brain_schema('ProjectProtection')['title']=='ProjectProtection'
    result=tools.call('brain_set_project_protection',{'project_id':'policy-api','expected_revision':0,
                      'protection':{'assets':[],'editable_references':[]},'reason':'Explicit empty-policy API fixture.'})
    assert result['revision']==1
    with pytest.raises(BrainError) as exc:
        tools.brain_set_project_protection('policy-api',0,{},'Stale policy must not overwrite state.')
    assert exc.value.code=='REVISION_CONFLICT'
    assert tools.brain_get_project_protection('policy-api')['revision']==1
