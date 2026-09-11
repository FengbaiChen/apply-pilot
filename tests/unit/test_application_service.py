import asyncio
from unittest.mock import Mock, AsyncMock
import pytest
from app.config.settings import Settings
from app.domain.enums import ApplicationState as S, AnswerSource
from app.services.application_service import ApplicationService, SessionConflict
from app.services.field_fill_service import FieldFillService
from app.services.field_inspection_service import FieldInspectionService
from app.services.option_collector import OptionCollector
from app.services.confidence_policy import ConfidencePolicy
from app.services.navigation_service import NavigationService
from app.services.review_service import ReviewService

@pytest.fixture
def service(answers,validation,field):
    sessions={}
    repository=Mock()
    repository.save.side_effect=lambda session:sessions.update({session.application_id:session.model_copy(deep=True)})
    repository.get.side_effect=lambda key:sessions.get(key)
    worker=Mock(open=AsyncMock(),close=AsyncMock(),page=Mock(url='https://example.test/apply'))
    adapter=Mock(scan_fields=AsyncMock(return_value=[field('Email','test@example.test')]),
                 get_validation_errors=AsyncMock(return_value=[]),is_review_page=AsyncMock(return_value=True),
                 security_challenge=AsyncMock(return_value=None),fill_field=AsyncMock(),next_page=AsyncMock())
    registry=Mock(create=Mock(return_value=adapter))
    detector=Mock(detect=AsyncMock(return_value='generic'))
    result=ApplicationService(Settings(),repository,answers,FieldInspectionService(OptionCollector()),
        FieldFillService(answers,ConfidencePolicy()),validation,NavigationService(),ReviewService(validation),
        registry,detector,worker_factory=lambda settings:worker)
    return result,worker,adapter

async def test_start_background_and_review_remains_open(service):
    app,worker,adapter=service
    session=await app.start('https://example.test/apply')
    assert session.status == S.STARTING
    await app.task
    assert app.get(session.application_id).status == S.READY_FOR_REVIEW
    worker.close.assert_not_awaited(); adapter.next_page.assert_not_awaited()
    await app.shutdown()
    worker.close.assert_awaited_once()

async def test_one_active_including_review(service):
    app,worker,_=service
    await app.start('https://example.test/apply'); await app.task
    with pytest.raises(SessionConflict): await app.start('https://another.test')
    await app.shutdown()

async def test_security_pause_then_resume(service):
    app,worker,adapter=service
    adapter.security_challenge.return_value='Complete MFA in the browser'
    session=await app.start('https://example.test/apply'); await app.task
    assert app.get(session.application_id).status == S.WAITING_FOR_HUMAN
    adapter.scan_fields.assert_not_awaited(); worker.close.assert_not_awaited()
    adapter.security_challenge.return_value=None
    await app.resume(session.application_id); await app.task
    assert app.get(session.application_id).status == S.READY_FOR_REVIEW
    assert worker.open.await_count == 1
    await app.shutdown()

async def test_prefilled_unknown_requires_explicit_confirmation(service,field):
    app,worker,adapter=service
    f=field('Favorite programming language','Python')
    adapter.scan_fields.return_value=[f]
    session=await app.start('https://example.test/apply'); await app.task
    assert app.get(session.application_id).status == S.WAITING_FOR_HUMAN
    await app.resume(session.application_id); await app.task
    assert app.get(session.application_id).status == S.WAITING_FOR_HUMAN
    await app.resume(session.application_id,True); await app.task
    assert app.get(session.application_id).status == S.READY_FOR_REVIEW
    assert app.resolved[f.key].source == AnswerSource.HUMAN
    await app.shutdown()

async def test_confirmation_cannot_override_profile_mismatch(service,field):
    app,_,adapter=service
    f=field('School','Michigan State University',enabled=False)
    adapter.scan_fields.return_value=[f]
    session=await app.start('https://example.test/apply'); await app.task
    await app.resume(session.application_id,True); await app.task
    assert app.get(session.application_id).status == S.WAITING_FOR_HUMAN
    assert app.resolved[f.key].source != AnswerSource.HUMAN
    await app.shutdown()

async def test_failed_browser_start_is_persisted_and_can_stop(service):
    app,worker,_=service
    worker.open.side_effect=RuntimeError('sensitive-token')
    session=await app.start('https://example.test/apply'); await app.task
    result=app.get(session.application_id)
    assert result.status == S.FAILED and 'sensitive-token' not in result.model_dump_json()
    await app.stop(session.application_id)
    assert app.get(session.application_id).status == S.STOPPED

async def test_stop_cancels_task_and_releases_worker(service):
    app,worker,_=service
    waiting=asyncio.Event()
    worker.open.side_effect=lambda url:None
    async def blocked_open(url): await waiting.wait()
    worker.open.side_effect=blocked_open
    session=await app.start('https://example.test/apply')
    assert not app.task.done()
    await app.stop(session.application_id)
    assert app.worker is None and app.task.cancelled()
    assert app.get(session.application_id).status == S.STOPPED

async def test_resume_wrong_state_rejected(service):
    app,_,_=service
    session=await app.start('https://example.test/apply'); await app.task
    with pytest.raises(SessionConflict): await app.resume(session.application_id)
    with pytest.raises(KeyError): await app.resume('missing')
    await app.shutdown()

async def test_security_challenge_appearing_after_fill_pauses(service):
    app,worker,adapter=service
    adapter.security_challenge.side_effect=[None,'Complete the CAPTCHA manually']
    session=await app.start('https://example.test/apply'); await app.task
    assert app.get(session.application_id).status == S.WAITING_FOR_HUMAN
    adapter.is_review_page.assert_not_awaited(); adapter.next_page.assert_not_awaited()
    await app.shutdown()
