import asyncio
from pathlib import Path
from unittest.mock import Mock
import pytest
from app.ats.generic import GenericATSAdapter
from app.ats.registry import AdapterRegistry
from app.ats.detector import PlatformDetector
from app.domain.enums import FieldType as T, ApplicationState as S
from app.services.field_inspection_service import FieldInspectionService
from app.services.option_collector import OptionCollector
from app.services.field_fill_service import FieldFillService
from app.services.confidence_policy import ConfidencePolicy
from app.services.navigation_service import NavigationService
from app.services.review_service import ReviewService
from app.services.application_service import ApplicationService
from app.repositories.database import Database
from app.repositories.application_repository import ApplicationRepository
from app.workers.browser_worker import UnsafeInteraction

pytestmark = pytest.mark.integration

async def test_scan_live_semantics(worker,fixture_url):
    await worker.page.goto(fixture_url+'/form.html')
    fields = await GenericATSAdapter(worker).scan_fields()
    assert len(fields) == 10
    assert next(f for f in fields if f.question == 'School').current_value == 'University of Michigan-Flint'
    sponsorship = next(f for f in fields if 'sponsorship' in f.question)
    assert sponsorship.field_type == T.RADIO and sponsorship.current_value == 'No' and sponsorship.required
    await worker.page.get_by_label('Email',exact=True).fill('changed@example.test')
    assert next(f for f in await GenericATSAdapter(worker).scan_fields() if f.question == 'Email').current_value == 'changed@example.test'

async def test_lazy_dropdown_inspection_and_exact_fill(worker,fixture_url,answers):
    await worker.page.goto(fixture_url+'/dropdown.html')
    adapter = GenericATSAdapter(worker)
    f = (await adapter.scan_fields())[0]
    assert not f.options
    f = await FieldInspectionService(OptionCollector()).inspect(f,adapter)
    assert [o.label for o in f.options] == ['University of Michigan-Flint','University of Michigan']
    assert await FieldFillService(answers,ConfidencePolicy()).fill(f,await answers.resolve(f),adapter)
    assert (await adapter.scan_fields())[0].current_value == 'University of Michigan'

async def test_autocomplete_targeted_search(worker,fixture_url,answers):
    await worker.page.goto(fixture_url+'/autocomplete.html')
    adapter=GenericATSAdapter(worker); f=(await adapter.scan_fields())[0]
    a=await answers.resolve(f)
    f=await FieldInspectionService(OptionCollector()).inspect(f,adapter,str(a.value))
    assert f.options[0].label == 'University of Michigan'
    assert await worker.page.locator('#school').input_value() == ''  # Inspection restores prior value.
    assert await FieldFillService(answers,ConfidencePolicy()).fill(f,a,adapter)
    assert await worker.page.locator('#school').input_value() == 'University of Michigan'
    assert (await worker.page.evaluate('window.queries'))[0] == 'University of Michigan - Ann Arbor'

async def test_virtualized_options_are_collected(worker,fixture_url):
    await worker.page.goto(fixture_url+'/virtualized.html')
    adapter=GenericATSAdapter(worker); f=(await adapter.scan_fields())[0]
    f=await FieldInspectionService(OptionCollector(12,3)).inspect(f,adapter)
    assert len(f.options) >= 5
    assert len({o.label for o in f.options}) == len(f.options)
    assert f.options[0].label == 'School 0'

async def test_required_and_visible_errors(worker,fixture_url,validation):
    await worker.page.goto(fixture_url+'/validation.html')
    adapter=GenericATSAdapter(worker)
    findings=validation.validate(await adapter.scan_fields(),errors=await adapter.get_validation_errors())
    assert not validation.can_navigate(findings)
    assert any(f.message == 'Email is required' for f in findings)

async def test_final_submit_never_clicked(worker,fixture_url):
    await worker.page.goto(fixture_url+'/review.html')
    adapter=GenericATSAdapter(worker)
    assert await adapter.is_review_page()
    assert not await NavigationService().advance(adapter)
    control=(await adapter.navigation_controls())[0]
    with pytest.raises(UnsafeInteraction): await worker.guarded_next(control)
    assert await worker.page.evaluate('window.submitted') is False

async def test_end_to_end_repairs_uploads_navigates_and_keeps_review_open(worker,fixture_url,answers,validation,tmp_path):
    resume=tmp_path/'resume.txt'; resume.write_text('Local fixture resume, no real applicant data.')
    answers.profile.application.resume_path=str(resume)
    db=Database(tmp_path/'sessions.sqlite')
    # Existing local fixture browser is injected; application still uses real browser mechanics.
    async def open_fixture(url): await worker.page.goto(url)
    worker.open=open_fixture
    service=ApplicationService(worker.settings,ApplicationRepository(db),answers,
        FieldInspectionService(OptionCollector()),FieldFillService(answers,ConfidencePolicy()),validation,
        NavigationService(),ReviewService(validation),AdapterRegistry(),PlatformDetector(),worker_factory=lambda settings:worker)
    try:
        session=await service.start(fixture_url+'/form.html')
        await asyncio.wait_for(service.task,30)
        result=service.get(session.application_id)
        assert result.status == S.READY_FOR_REVIEW, result.model_dump_json(indent=2)
        assert result.review.ready and result.review.audited_fields >= 10
        assert result.pages_processed == 1
        assert await worker.page.get_by_role('heading').inner_text() == 'Review application'
        assert await worker.page.evaluate('window.submitted') is False
        assert not worker.page.is_closed()
    finally:
        await service.shutdown(); db.close()

async def test_native_multiselect_uses_explicit_list(worker,fixture_url,answers):
    from app.domain.answer import Answer
    from app.domain.enums import AnswerSource
    await worker.page.goto(fixture_url+'/review.html')
    await worker.page.set_content('<label>Languages<select multiple><option value="py">Python</option><option value="js">JavaScript</option><option value="rs">Rust</option></select></label>')
    adapter=GenericATSAdapter(worker); f=(await adapter.scan_fields())[0]
    answer=Answer(value=['Python','Rust'],source=AnswerSource.HUMAN,confidence=1,requires_review=False)
    assert await FieldFillService(answers,ConfidencePolicy()).fill(f,answer,adapter)
    assert (await adapter.scan_fields())[0].current_value == ['Python','Rust']

async def test_hidden_upload_and_optional_checkbox(worker,fixture_url,answers,validation,tmp_path):
    await worker.page.goto(fixture_url+'/review.html')
    await worker.page.set_content('<label for="upload">Resume</label><input id="upload" type="file" hidden required><label><input type="checkbox">Subscribe to updates</label>')
    adapter=GenericATSAdapter(worker); fields=await adapter.scan_fields()
    assert len(fields) == 2
    attachment=tmp_path/'resume.txt'; attachment.write_text('Fixture only')
    answers.profile.application.resume_path=str(attachment)
    resume=next(f for f in fields if f.field_type == T.FILE)
    await FieldFillService(answers,ConfidencePolicy()).fill(resume,await answers.resolve(resume),adapter)
    assert validation.can_navigate(validation.validate(await adapter.scan_fields()))
