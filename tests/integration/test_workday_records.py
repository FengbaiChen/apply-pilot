import pytest
from app.config.profile import WorkExperience
from app.platforms.workday.adapter import WorkdayATSAdapter
from app.platforms.workday.steps.my_experience import MyExperienceStep

pytestmark=pytest.mark.integration


def records():
    return [WorkExperience(company=f'Company {i}',job_title='Intern',start_month=i,start_year=2026) for i in range(1,6)]


@pytest.mark.parametrize('existing',[0,1,5])
async def test_add_only_missing_work_cards(worker,fixture_url,existing):
    await worker.page.goto(fixture_url+'/workday_records.html')
    await worker.page.evaluate('(n)=>{for(let i=0;i<n;i++)addWork();window.workAdds=0;}',existing)
    adapter=WorkdayATSAdapter(worker)
    assert await adapter.ensure_work_experience_records(records()) is None
    assert await worker.page.evaluate('window.workAdds')==5-existing
    assert await worker.page.evaluate('window.educationAdds')==0
    assert await adapter.ensure_work_experience_records(records()) is None
    assert await worker.page.evaluate('window.workAdds')==5-existing


async def test_record_sections_and_month_year_are_distinct(worker,fixture_url,profile):
    await worker.page.goto(fixture_url+'/workday_records.html')
    adapter=WorkdayATSAdapter(worker)
    profile.work_experience=records()
    assert await adapter.ensure_work_experience_records(profile.work_experience) is None
    fields=await adapter.scan_fields()
    dates=[f for f in fields if f.section=='Work Experience 2' and f.locator.date_component]
    assert len(dates)==2
    assert len({f.key for f in dates})==2
    step=MyExperienceStep()
    assert {f.question:step.answer(f,profile).value for f in dates}=={'From (month)*':'02','From (year)*':'2026'}
    titles=[f for f in fields if f.question=='Job Title*']
    assert len({f.key for f in titles})==5


async def test_conflicting_existing_record_stops_without_adding(worker,fixture_url):
    await worker.page.goto(fixture_url+'/workday_records.html')
    await worker.page.evaluate('addWork();window.workAdds=0;')
    await worker.page.get_by_label('Company*',exact=True).fill('Different company')
    message=await WorkdayATSAdapter(worker).ensure_work_experience_records(records())
    assert 'differs' in message
    assert await worker.page.evaluate('window.workAdds')==0


async def test_extra_records_never_deleted(worker,fixture_url):
    await worker.page.goto(fixture_url+'/workday_records.html')
    await worker.page.evaluate('for(let i=0;i<6;i++)addWork();window.workAdds=0;')
    message=await WorkdayATSAdapter(worker).ensure_work_experience_records(records())
    assert 'more work records' in message
    assert await worker.page.locator('#cards > div').count()==6
