from unittest.mock import Mock, AsyncMock
import pytest
from app.platforms.workday.steps import STEPS
from app.platforms.workday.steps.my_information import MyInformationStep
from app.platforms.workday.steps.voluntary_disclosures import VoluntaryDisclosuresStep
from app.platforms.workday.service import WorkdayApplicationService
from app.platforms.workday.adapter import WorkdayATSAdapter
from app.domain.field import LocatorMetadata
from app.domain.enums import FieldType
from app.workers.browser_worker import UnsafeInteraction


def test_five_steps_have_independent_modules():
    assert list(STEPS)==['my_information','my_experience','application_questions','voluntary_disclosures','review']
    assert len({type(s).__module__ for s in STEPS.values()})==5


def test_prior_employer_policy_is_explicit_and_narrow(profile,field):
    step=MyInformationStep()
    f=field('Have you previously worked for NVIDIA as an employee or contractor?*')
    assert step.answer(f,profile) is None
    profile.facts['previously_worked_for_this_employer']=False
    assert step.answer(f,profile).value=='No'
    assert step.answer(field('Describe your previous work experience'),profile) is None
    assert step.answer(field('Have you ever worked anywhere?'),profile) is None


def test_disclosures_are_never_inferred(profile,field):
    assert VoluntaryDisclosuresStep().answer(field('Gender*'),profile).value is None


@pytest.mark.parametrize('heading,expected', [('My Information','my_information'),('My Experience','my_experience'),
    ('Application Questions','application_questions'),('Voluntary Disclosures','voluntary_disclosures'),('Review','review')])
async def test_current_step_dispatch(heading,expected,profile):
    page=Mock()
    loc=Mock(count=AsyncMock(return_value=0),all_inner_texts=AsyncMock(return_value=[heading]),inner_text=AsyncMock(return_value=heading))
    page.locator.return_value=loc;page.get_by_role.return_value=loc
    service=Mock(worker=Mock(page=page),adapter=Mock(security_challenge=AsyncMock(return_value=None),scan_fields=AsyncMock(return_value=[])),session=Mock(),answers=Mock(profile=profile))
    service._pause=Mock();service._update=Mock()
    assert await WorkdayApplicationService.prepare_page(service)
    assert service.session.current_step==expected
    assert service.answers.step_key==expected
    service._pause.assert_not_called()


async def test_unrecognized_step_pauses_instead_of_falling_through():
    page=Mock()
    loc=Mock(count=AsyncMock(return_value=0),all_inner_texts=AsyncMock(return_value=['Unrecognized stage']),inner_text=AsyncMock(return_value='Unknown page'))
    page.locator.return_value=loc;page.get_by_role.return_value=loc
    service=Mock(worker=Mock(page=page),adapter=Mock(security_challenge=AsyncMock(return_value=None)))
    assert not await WorkdayApplicationService.prepare_page(service)
    assert 'Unrecognized Workday step' in service._pause.call_args.args[0]


async def test_enter_only_for_confirmed_source_search(field):
    loc=Mock(fill=AsyncMock(),press=AsyncMock(),get_attribute=AsyncMock(return_value='search'))
    worker=Mock(locate=Mock(return_value=loc),settle=AsyncMock())
    adapter=WorkdayATSAdapter(worker)
    f=field('How Did You Hear About Us?*',field_type=FieldType.AUTOCOMPLETE,locator=LocatorMetadata(control_kind='workday-prompt'))
    await adapter.search_options(f,'Linkedin')
    loc.press.assert_awaited_once_with('Enter')
    loc.press.reset_mock()
    f.question='School or University*'
    await adapter.search_options(f,'University of Michigan')
    loc.press.assert_not_awaited()
    f.question='How Did You Hear About Us?*'
    loc.get_attribute.return_value=None
    with pytest.raises(UnsafeInteraction): await adapter.search_options(f,'Linkedin')


async def test_review_never_advances():
    adapter=WorkdayATSAdapter(Mock())
    adapter.is_review_page=AsyncMock(return_value=True)
    with pytest.raises(UnsafeInteraction): await adapter.next_page({'label':'Save and Continue','token':'x'})
