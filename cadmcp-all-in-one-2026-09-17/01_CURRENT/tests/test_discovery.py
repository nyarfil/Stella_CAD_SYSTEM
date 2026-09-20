import pytest
from cadmcp_brain.api import Tools
from cadmcp_brain.errors import BrainError
from cadmcp_brain.protocol import Protocol


def test_project_pagination_and_unicode_roundtrip(brain):
    tools = Tools(brain)
    request = 'センサー台座に傷を付けない。外形と基板の位置を維持する。'
    tools.brain_open('b-project', request)
    tools.brain_open('a-project', request)
    result = tools.brain_projects(limit=1)
    assert result['total'] == 2 and result['next_offset'] == 1
    assert result['projects'][0]['project_id'] == 'a-project'
    assert tools.brain_projects(limit=1, offset=1)['next_offset'] is None
    assert tools.brain_get('b-project')['project']['sources'][0]['text'] == request
    assert tools.brain_studio_attempts('b-project')['subjects'] == []
    names = {t['name']: t for t in tools.list()}
    assert names['brain_projects']['annotations']['readOnlyHint']
    assert names['brain_studio_attempts']['annotations']['readOnlyHint']


def test_studio_history_is_not_legacy_stage_or_current_pass(brain):
    tools = Tools(brain)
    tools.brain_open('test', 'Keep the original request unchanged.')
    studio = tools._studio()
    subject = 'a' * 64
    studio.register_subject('test', 0, subject, {'kind': 'concept'})
    before = tools.brain_get('test')
    listing = tools.brain_studio_attempts('test')
    assert listing['total_subjects'] == 1
    assert listing['subjects'][0]['current_revision']
    assert not listing['subjects'][0]['evidence_revalidated']
    assert tools.brain_get('test') == before
    tools.brain_add_source('test', 0, 'A new constraint.')
    assert not tools.brain_studio_attempts('test')['subjects'][0]['current_revision']


@pytest.mark.parametrize('kwargs', [{'limit': 0}, {'limit': 101}, {'offset': -1}])
def test_invalid_pagination(brain, kwargs):
    with pytest.raises(BrainError):
        Tools(brain).brain_projects(**kwargs)
