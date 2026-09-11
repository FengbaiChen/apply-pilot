import asyncio
import socket
from threading import Thread
import pytest
import uvicorn
from app.main import create_app
from app.config.settings import Settings
from app.ats.registry import AdapterRegistry
from app.ats.detector import PlatformDetector
from app.repositories.database import Database
from app.repositories.application_repository import ApplicationRepository
from app.services.application_service import ApplicationService
from app.services.field_inspection_service import FieldInspectionService
from app.services.field_fill_service import FieldFillService
from app.services.confidence_policy import ConfidencePolicy
from app.services.option_collector import OptionCollector
from app.services.navigation_service import NavigationService
from app.services.review_service import ReviewService

pytestmark=pytest.mark.integration

async def test_control_panel_drives_real_background_browser(worker,fixture_url,answers,validation,tmp_path):
    resume=tmp_path/'resume.txt'; resume.write_text('Fixture resume')
    answers.profile.application.resume_path=str(resume)
    settings=Settings(browser_profile_dir=tmp_path/'application-browser',browser_headless=True,autofill_wait_ms=0)
    db=Database(tmp_path/'ui.sqlite')
    service=ApplicationService(settings,ApplicationRepository(db),answers,
        FieldInspectionService(OptionCollector()),FieldFillService(answers,ConfidencePolicy()),validation,
        NavigationService(),ReviewService(validation),AdapterRegistry(),PlatformDetector())
    sock=socket.socket(); sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(create_app(service),log_level='error'))
    thread=Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True); thread.start()
    try:
        # Socket readiness is probed with bounded connection attempts, without fixed sleeps.
        async with asyncio.timeout(10):
            while not server.started:
                await asyncio.to_thread(thread.join,.02)
        await worker.page.goto(f'http://127.0.0.1:{port}')
        await worker.page.get_by_label('Job application URL').fill(fixture_url+'/form.html')
        await worker.page.get_by_role('button',name='Start Application').click()
        await worker.page.locator('#status').filter(has_text='READY FOR REVIEW').wait_for(timeout=20000)
        assert await worker.page.locator('#review').is_visible()
        assert 'Ready for your review' in await worker.page.locator('#audit-summary').inner_text()
        assert service.worker is not None
        # Browser loop belongs to server thread; validate submission state on that loop.
        browser_loop=service.task.get_loop()
        submitted=asyncio.run_coroutine_threadsafe(service.worker.page.evaluate('window.submitted'),browser_loop)
        assert await asyncio.wrap_future(submitted) is False
        await worker.page.get_by_role('button',name='Stop & close browser').click()
        await worker.page.locator('#status').filter(has_text='STOPPED').wait_for(timeout=5000)
        assert service.worker is None
        await worker.page.screenshot(path=str(tmp_path/'control-panel.png'),full_page=True)
    finally:
        server.should_exit=True
        await asyncio.to_thread(thread.join,10)
        sock.close(); db.close()
    assert not thread.is_alive()

async def test_ui_human_answers_and_llm_reference_prompt(worker,fixture_url,answers,validation,tmp_path):
    from unittest.mock import AsyncMock, Mock
    from app.config.profile import Profile
    draft='I built a Python test runner and would bring that experience to your testing tools team.'
    answers.llm=Mock(generate=AsyncMock(return_value=draft))
    profile_path = tmp_path / 'profile.yaml'
    answers.profile_answers.path = profile_path
    settings=Settings(browser_profile_dir=tmp_path/'application-browser',browser_headless=True,autofill_wait_ms=0)
    db=Database(tmp_path/'ui.sqlite')
    service=ApplicationService(settings,ApplicationRepository(db),answers,
        FieldInspectionService(OptionCollector()),FieldFillService(answers,ConfidencePolicy()),validation,
        NavigationService(),ReviewService(validation),AdapterRegistry(),PlatformDetector())
    sock=socket.socket(); sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(create_app(service),log_level='error'))
    thread=Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True); thread.start()
    try:
        async with asyncio.timeout(10):
            while not server.started: await asyncio.to_thread(thread.join,.02)
        await worker.page.goto(f'http://127.0.0.1:{port}')
        await worker.page.get_by_label('Job application URL').fill(fixture_url+'/questions.html')
        await worker.page.get_by_text('Writing guidance for this application (optional)',exact=True).click()
        await worker.page.get_by_label('LLM reference prompt',exact=True).fill('Use one concise paragraph.')
        await worker.page.get_by_label('Company and role context',exact=True).fill('The team builds testing tools.')
        await worker.page.get_by_role('button',name='Start Application').click()
        await worker.page.locator('#question-form').wait_for(state='visible',timeout=15000)
        assert await worker.page.locator('#questions .question').count() == 2
        years=worker.page.get_by_label('How many years have you used Python?',exact=True)
        await years.fill('3')
        # Force a real status poll while a reply is being edited; the draft must survive.
        await worker.page.evaluate('poll()')
        assert await years.input_value() == '3'
        await worker.page.get_by_label('Preferred work arrangement',exact=True).select_option(label='Hybrid')
        await worker.page.get_by_role('button',name='Save answers & continue').click()
        await worker.page.locator('#status').filter(has_text='READY FOR REVIEW').wait_for(timeout=15000)
        assert not await worker.page.locator('#question-form').is_visible()
        assert await worker.page.locator('#findings .warning').filter(has_text='LLM-generated').count() == 1
        loop=service.task.get_loop()
        result=asyncio.run_coroutine_threadsafe(service.worker.page.evaluate("({years:document.querySelector('[name=years]').value,why:document.querySelector('[name=why]').value,arrangement:document.querySelector('[name=arrangement]').value,submitted:window.submitted})"),loop)
        values=await asyncio.wrap_future(result)
        assert values == {'years':'3','why':draft,'arrangement':'hybrid','submitted':False}
        answers.llm.generate.assert_awaited_once()
        assert answers.llm.generate.call_args.kwargs['reference_prompt'] == 'Use one concise paragraph.'
        assert answers.llm.generate.call_args.kwargs['application_context'] == 'The team builds testing tools.'
        await worker.page.get_by_role('button',name='Stop & close browser').click()
        await worker.page.locator('#status').filter(has_text='STOPPED').wait_for(timeout=5000)
        saved = Profile.load(profile_path).saved_answers
        assert {a.question: a.value for a in saved} == {
            'How many years have you used Python?': '3', 'Preferred work arrangement': 'Hybrid'}
        # A second real application fills both general answers without asking again.
        await worker.page.get_by_role('button',name='Start Application').click()
        await worker.page.locator('#status').filter(has_text='READY FOR REVIEW').wait_for(timeout=15000)
        assert not await worker.page.locator('#question-form').is_visible()
        assert await worker.page.locator('#findings').get_by_text('Verified value from PROFILE_CACHE.', exact=False).count() == 2
        loop = service.task.get_loop()
        result = asyncio.run_coroutine_threadsafe(service.worker.page.evaluate("({years:document.querySelector('[name=years]').value,arrangement:document.querySelector('[name=arrangement]').value,submitted:window.submitted})"), loop)
        assert await asyncio.wrap_future(result) == {'years': '3', 'arrangement': 'hybrid', 'submitted': False}
        assert answers.llm.generate.await_count == 2  # Unapproved generated prose was not cached.
        await worker.page.get_by_role('button',name='Stop & close browser').click()
        await worker.page.locator('#status').filter(has_text='STOPPED').wait_for(timeout=5000)
    finally:
        server.should_exit=True
        await asyncio.to_thread(thread.join,10)
        sock.close(); db.close()
    assert not thread.is_alive()
