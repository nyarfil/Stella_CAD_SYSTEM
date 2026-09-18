import pytest
from cadmcp_brain.engine import Brain
from cadmcp_brain.demo import fixture

@pytest.fixture
def data(): return fixture()

@pytest.fixture
def brain(tmp_path): return Brain(tmp_path/'work space_日本語')

@pytest.fixture
def intent(brain,data):
    brain.open('test',data['request']);brain.submit_intent('test',0,data['brief'])
    return brain

@pytest.fixture
def selected(intent,data):
    intent.submit_concepts('test',1,data['concepts']);intent.select('test',2,'C-direct')
    return intent

@pytest.fixture
def ready(selected,data):
    selected.submit_plan('test',3,data['plan'])
    return selected
