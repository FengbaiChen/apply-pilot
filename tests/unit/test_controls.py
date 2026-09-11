from unittest.mock import AsyncMock, Mock
import pytest
from app.domain.field import Option, LocatorMetadata
from app.domain.answer import Answer
from app.domain.enums import FieldType as T, InspectionStatus as I, NavigationKind as N
from app.services.navigation_service import NavigationService
from app.services.option_collector import OptionCollector
from app.services.field_inspection_service import FieldInspectionService
from app.services.field_fill_service import FieldFillService
from app.services.confidence_policy import ConfidencePolicy
from app.ats.detector import PlatformDetector
from app.ats.registry import AdapterRegistry
from app.ats.generic import GenericATSAdapter
from app.workers.browser_worker import BrowserWorker, UnsafeInteraction
from app.config.settings import Settings

@pytest.mark.parametrize('label',['Next','Continue','Save and Continue','Review'])
def test_safe_navigation(label): assert NavigationService.classify(label) == N.NEXT

@pytest.mark.parametrize('label',['Submit','Submit Application','Send Application','Complete Application','Finish and Submit','Continue and Submit Application','Continue & submit','Next and Submit'])
def test_final_submit_wins(label): assert NavigationService.classify(label) == N.FINAL_SUBMIT

@pytest.mark.parametrize('label',['Start','Go','Confirm details','Next application','Learn more'])
def test_unknown_or_risky_navigation_is_not_next(label): assert NavigationService.classify(label) != N.NEXT

async def test_review_stops_navigation():
    adapter = Mock(navigation_controls=AsyncMock(return_value=[{'label':'Next'}]),is_review_page=AsyncMock(return_value=True),next_page=AsyncMock())
    assert not await NavigationService().advance(adapter)
    adapter.next_page.assert_not_awaited()

async def test_multiple_next_buttons_pause():
    adapter = Mock(navigation_controls=AsyncMock(return_value=[{'label':'Next'},{'label':'Continue'}]),is_review_page=AsyncMock(return_value=False),next_page=AsyncMock())
    assert not await NavigationService().advance(adapter)

async def test_browser_rechecks_stale_submit_label():
    worker = BrowserWorker(Settings())
    locator = Mock(evaluate=AsyncMock(return_value=['Continue','Continue and Submit Application','','']),click=AsyncMock())
    worker.page = Mock(locator=Mock(return_value=locator))
    with pytest.raises(UnsafeInteraction): await worker.guarded_next({'token':'x','label':'Continue'})
    locator.click.assert_not_awaited()

async def test_collector_dedup_stable_order_and_empty():
    a,b,c = [Option(label=x,value=x) for x in 'ABC']
    read = AsyncMock(side_effect=[[a,b],[],[b,c],[a,c],[c]])
    scroll = AsyncMock(return_value=True)
    result = await OptionCollector(10,2).collect(read,scroll)
    assert result == [a,b,c] and read.await_count == 5

async def test_collector_stale_limit():
    read = AsyncMock(return_value=[Option(label='A',value='a')])
    result = await OptionCollector(20,3).collect(read,AsyncMock(return_value=True))
    assert len(result) == 1 and read.await_count == 4

async def test_collector_iteration_limit():
    read = AsyncMock(side_effect=[[Option(label=str(x),value=str(x))] for x in range(10)])
    result = await OptionCollector(4,3).collect(read,AsyncMock(return_value=True))
    assert len(result) == 4 and read.await_count == 4

@pytest.fixture
def adapter():
    return Mock(open_control=AsyncMock(),search_options=AsyncMock(),visible_options=AsyncMock(return_value=[Option(label='School',value='s')]),
                close_control=AsyncMock(),scroll_options=AsyncMock(return_value=False),fill_field=AsyncMock())

async def test_dropdown_requests_visible_options(field,adapter):
    f = field('Country',field_type=T.SELECT)
    await FieldInspectionService(OptionCollector()).inspect(f,adapter)
    adapter.open_control.assert_awaited_once(); adapter.visible_options.assert_awaited_once(); adapter.close_control.assert_awaited_once()
    assert f.inspection_status == I.INSPECTED

async def test_targeted_search_preferred_over_scrolling(field,adapter):
    f = field('School',field_type=T.AUTOCOMPLETE,locator=LocatorMetadata(searchable=True,virtualized=True))
    await FieldInspectionService(OptionCollector()).inspect(f,adapter,'University of Michigan')
    adapter.search_options.assert_awaited_once_with(f,'University of Michigan')
    adapter.scroll_options.assert_not_awaited()

async def test_virtual_control_collects_iteratively(field,adapter):
    adapter.scroll_options.side_effect = [True,False]
    f = field('School',field_type=T.AUTOCOMPLETE,locator=LocatorMetadata(virtualized=True))
    await FieldInspectionService(OptionCollector()).inspect(f,adapter)
    assert adapter.visible_options.await_count == 2 and len(f.options) == 1

async def test_unsupported_control_is_human_required(field,adapter):
    f = field('Something',field_type=T.UNKNOWN)
    assert (await FieldInspectionService(OptionCollector()).inspect(f,adapter)).inspection_status == I.HUMAN_REQUIRED
    adapter.open_control.assert_not_awaited()

async def test_inspection_failure_restores_control(field,adapter):
    adapter.visible_options.side_effect = RuntimeError('popup disappeared')
    f = field('School',field_type=T.AUTOCOMPLETE)
    assert (await FieldInspectionService(OptionCollector()).inspect(f,adapter)).inspection_status == I.HUMAN_REQUIRED
    adapter.close_control.assert_awaited_once()

async def test_ambiguous_education_options_are_not_filled(answers,field,adapter):
    f = field('School',field_type=T.SELECT,options=[Option(label='University of Michigan',value='a'),Option(label='University of Michigan',value='b')])
    answer = await answers.resolve(f)
    assert not await FieldFillService(answers,ConfidencePolicy()).fill(f,answer,adapter)
    adapter.fill_field.assert_not_awaited()

async def test_low_confidence_not_filled(answers,field,adapter):
    assert not await FieldFillService(answers,ConfidencePolicy()).fill(field(),Answer(value='x',confidence=.5),adapter)
    adapter.fill_field.assert_not_awaited()

class ExampleAdapter(GenericATSAdapter): pass

def test_registry_known_and_unknown():
    registry = AdapterRegistry(); registry.register('example',ExampleAdapter)
    assert isinstance(registry.create('example',None),ExampleAdapter)
    assert type(registry.create('new-ats',None)) is GenericATSAdapter

async def test_detector_host_dom_and_fallback():
    detector = PlatformDetector(); detector.register('example',hosts=('ats.example',),selectors=('[data-ats]',))
    page = Mock(url='https://jobs.ats.example/apply',locator=Mock(return_value=Mock(count=AsyncMock(return_value=0))))
    assert await detector.detect(page) == 'example'
    page.url = 'https://ats.example.evil.test/apply'
    assert await detector.detect(page) == 'generic'
    page.locator.return_value.count.return_value = 1
    assert await detector.detect(page) == 'example'

async def test_field_control_conflicting_submit_label_is_rejected():
    worker=BrowserWorker(Settings())
    loc=Mock(evaluate=AsyncMock(return_value={'labels':['School','Submit Application',''],'type':'button','tag':'BUTTON'}))
    with pytest.raises(UnsafeInteraction): await worker._control_safe(loc)

async def test_field_control_implicit_submit_button_is_rejected():
    worker=BrowserWorker(Settings())
    loc=Mock(evaluate=AsyncMock(return_value={'labels':['School','',''],'type':'submit','tag':'BUTTON'}))
    with pytest.raises(UnsafeInteraction): await worker._control_safe(loc)
