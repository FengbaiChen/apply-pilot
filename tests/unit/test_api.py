from unittest.mock import Mock, AsyncMock
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.domain.application import ApplicationSession
from app.domain.enums import ApplicationState as S
from app.services.application_service import SessionConflict

@pytest.fixture
def client_service():
    session = ApplicationSession(url='https://employer.test/apply')
    service = Mock(start=AsyncMock(return_value=session), get=Mock(return_value=session),
                   resume=AsyncMock(return_value=session),stop=AsyncMock(return_value=session),shutdown=AsyncMock())
    with TestClient(create_app(service)) as client: yield client,service

def test_create_returns_prompt_202(client_service):
    client,service = client_service
    response = client.post('/applications',json={'url':'https://employer.test/apply'})
    assert response.status_code == 202 and response.json()['status'] == 'STARTING'
    service.start.assert_awaited_once_with('https://employer.test/apply',reference_prompt='',application_context='',platform='generic')

@pytest.mark.parametrize('url',['file:///etc/passwd','javascript:alert(1)','ftp://host/file','https://user:password@example.test'])
def test_invalid_urls(client_service,url):
    client,service = client_service
    assert client.post('/applications',json={'url':url}).status_code == 422
    service.start.assert_not_awaited()

def test_api_status_resume_stop_and_review(client_service):
    client,service = client_service
    assert client.get('/applications/one').status_code == 200
    assert client.get('/applications/one/review').status_code == 409
    assert client.post('/applications/one/resume',json={'confirm_current_values':True}).status_code == 200
    service.resume.assert_awaited_once_with('one',True)
    assert client.post('/applications/one/stop').status_code == 200

def test_not_found_conflict_and_cross_site(client_service):
    client,service = client_service
    service.get.side_effect = KeyError('missing')
    assert client.get('/applications/missing').status_code == 404
    service.start.side_effect = SessionConflict('Already active')
    assert client.post('/applications',json={'url':'https://employer.test'}).status_code == 409
    assert client.post('/applications',json={'url':'https://employer.test'},headers={'Origin':'https://evil.test'}).status_code == 403

def test_local_ui_assets(client_service):
    client,_ = client_service
    assert 'Start Application' in client.get('/').text
    assert client.get('/static/app.js').status_code == 200
    assert 'frame-ancestors' in client.get('/').headers['content-security-policy']


def test_prompt_and_context_forwarded(client_service):
    client,service=client_service
    response=client.post('/applications',json={'url':'https://employer.test/apply','reference_prompt':'Be concise','application_context':'Testing tools'})
    assert response.status_code == 202
    service.start.assert_awaited_once_with('https://employer.test/apply',reference_prompt='Be concise',application_context='Testing tools',platform='generic')

def test_human_answers_endpoint(client_service):
    client,service=client_service
    service.submit_answers=AsyncMock(return_value=ApplicationSession(url='https://employer.test',status=S.RUNNING))
    response=client.post('/applications/one/answers',json={'answers':[{'question_id':'q_one','value':'My answer'}]})
    assert response.status_code == 202
    assert service.submit_answers.call_args.args[1][0].value == 'My answer'
    assert client.post('/applications/one/answers',json={'answers':[]}).status_code == 422

def test_invalid_human_answer_reports_422(client_service):
    from app.services.human_question_service import InvalidHumanAnswer
    client,service=client_service
    service.submit_answers=AsyncMock(side_effect=InvalidHumanAnswer('Choose a shown option'))
    assert client.post('/applications/one/answers',json={'answers':[{'question_id':'q_one','value':'x'}]}).status_code == 422

def test_profile_save_failure_reports_retryable_503(client_service):
    from app.repositories.profile_answer_repository import ProfileSaveError
    client, service = client_service
    service.submit_answers = AsyncMock(side_effect=ProfileSaveError('Could not save answers.'))
    response = client.post('/applications/one/answers', json={'answers': [{'question_id': 'q_one', 'value': 'x'}]})
    assert response.status_code == 503
    assert response.json()['detail'] == 'Could not save answers.'
