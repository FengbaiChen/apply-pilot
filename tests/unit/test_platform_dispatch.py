from pathlib import Path
from unittest.mock import Mock, AsyncMock
import pytest
import yaml
from app.ats.detector import PlatformDetector
from app.config.profile import Profile
from app.config.platform_profile import PlatformProfile, load_profiles
from app.platforms.workday.answers import WorkdayAnswerService
from app.services.application_dispatcher import ApplicationDispatcher
from app.services.application_service import SessionConflict
from app.services.human_question_service import HumanQuestionService
from app.domain.enums import FieldType
from test_api import client_service

@pytest.mark.parametrize('url,expected', [
    ('https://nvidia.wd5.myworkdayjobs.com/en-US/jobs', 'workday'),
    ('https://myworkdayjobs.com/jobs', 'workday'),
    ('https://myworkdayjobs.com.evil.test/jobs', 'generic'),
    ('https://example.test/?url=myworkdayjobs.com', 'generic')])
def test_platform_host_boundary(url, expected):
    assert PlatformDetector.detect_url(url) == expected

def test_existing_endpoint_routes_workday(client_service):
    client, service = client_service
    response = client.post('/applications', json={'url':'https://nvidia.wd5.myworkdayjobs.com/job/example'})
    assert response.status_code == 202
    assert service.start.call_args.kwargs['platform'] == 'workday'
    assert client.post('/applications',json={'url':'https://example.test','platform':'unsupported'}).status_code == 422

async def test_dispatcher_enforces_single_browser_across_platforms():
    worker = Mock(worker=None, start=AsyncMock(return_value='started'), shutdown=AsyncMock())
    factory = Mock(return_value=worker)
    dispatcher = ApplicationDispatcher(Mock(), factory, {})
    assert await dispatcher.start('https://example.test', platform='workday') == 'started'
    factory.assert_called_once_with('workday')
    worker.worker = object()
    with pytest.raises(SessionConflict): await dispatcher.start('https://other.test', platform='generic')
    await dispatcher.shutdown()

@pytest.fixture
def wd_answers(profile, bank, tmp_path):
    profile.personal.phone='+1 217-305-2634'
    profile.personal.phone_country_code='+1'
    config=PlatformProfile(question_aliases={'Telephone device':'facts.phone_type','Phone Device Type':'facts.phone_type'})
    return WorkdayAnswerService(profile, bank, platform_profile=config, shared_profile=profile.model_copy(deep=True), profile_path=tmp_path/'workday.yaml')

async def test_workday_sends_national_phone_only_and_preserves_shared(wd_answers,field):
    f=field('Phone Number*'); f.locator.phone_country_code='1'
    result=await wd_answers.resolve(f)
    assert result.value=='2173052634'
    assert wd_answers.profile.personal.phone=='+1 217-305-2634'
    assert wd_answers.matches(field('Phone Number*','(217) 305-2634'),result)
    f.locator.phone_country_code='86'
    assert (await wd_answers.resolve(f)).value is None

async def test_explicit_phrasings_share_fact(wd_answers,field):
    wd_answers.profile.facts['phone_type']='Home Cellular'
    assert (await wd_answers.resolve(field('Telephone device'))).value=='Home Cellular'
    assert (await wd_answers.resolve(field('Phone Device Type*'))).value=='Home Cellular'
    assert (await wd_answers.resolve(field('Do you own a telephone?'))).value is None

def test_platform_answer_does_not_copy_or_change_shared_profile(wd_answers,field,tmp_path):
    f=field('Workday-only question')
    wd_answers.remember([(f,HumanQuestionService.validate(f,'My explicit answer'))])
    raw=yaml.safe_load((tmp_path/'workday.yaml').read_text())
    assert 'personal' not in raw
    assert raw['question_aliases']['Telephone device']=='facts.phone_type'
    assert len(raw['saved_answers'])==1
    shared=tmp_path/'shared.yaml'; shared.write_text('{}')
    _,_,generic=load_profiles(shared,tmp_path/'generic.yaml')
    assert generic.saved_answers==[]
