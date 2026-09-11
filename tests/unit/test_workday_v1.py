import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from app.config.profile import Profile
from app.domain.answer import Answer
from app.domain.enums import AnswerSource, FieldType
from app.domain.field import Field, Option
from app.platforms.workday.answers import WorkdayAnswerService
from app.platforms.workday.steps.my_information import MyInformationStep
from app.platforms.workday.steps.voluntary_disclosures import VoluntaryDisclosuresStep
from app.services.answer_service import AnswerService


def valid_profile():
    return Profile.model_validate({
        "personal": {"first_name": "Eric", "last_name": "Chen", "email": "e@example.test"},
        "work_authorization": {"authorized_to_work_us": True, "require_future_sponsorship": False},
        "phone": {"device_type": "Home Cellular", "country_code": "+1", "number": "+1 217-305-2634"},
        "education": {"school": "University of Michigan Ann Arbor", "degree": "Bachelor of Science",
                       "major": "Computer Science", "start_month": 8, "start_year": 2025,
                       "graduation_month": 5, "graduation_year": 2027},
        "work_experiences": [{"company": f"Company {i}", "job_title": "Intern", "location": "Ann Arbor",
                               "start_month": 1,
                               "start_year": 2020, "end_month": 2, "end_year": 2021,
                               "current": False,
                               "description": "Built software."} for i in range(5)],
        "demographics": {"gender": "Male"},
        "links": {"github": "https://github.com/example", "linkedin": "https://linkedin.com/in/example"},
    })


def test_profile_requires_exactly_five_complete_work_records():
    profile = valid_profile()
    profile.validate_workday()
    profile.work_experiences.pop()
    with pytest.raises(ValueError, match="exactly five"):
        profile.validate_workday()


def test_current_record_cannot_have_an_end_date():
    profile = valid_profile()
    profile.work_experiences[0].current = True
    profile.work_experiences[0].end_year = None
    profile.work_experiences[0].end_month = None
    profile.work_experiences[0].model_fields_set.add("current")
    profile.work_experiences[0].end_year = 2026
    with pytest.raises(ValueError, match="must not have an end date"):
        profile.validate_workday()


def test_workday_fixed_and_sensitive_answers():
    profile = valid_profile()
    source = MyInformationStep()
    assert source.answer(Field(id="source", question="How Did You Hear About Us?*", field_type=FieldType.SELECT), profile).value == "LinkedIn Jobs"
    assert source.answer(Field(id="previous", question="Have you previously worked for NVIDIA as an employee or contractor?*", field_type=FieldType.RADIO), profile).value == "No"
    assert WorkdayAnswerService(profile, Mock()).deterministic(Field(id="terms", question="Applicant Privacy Policy Terms and Conditions", field_type=FieldType.CHECKBOX)).value is True
    assert VoluntaryDisclosuresStep().answer(Field(id="gender", question="What is your gender?"), profile).value == "Male"
    answers = WorkdayAnswerService(profile, Mock())
    assert answers.deterministic(Field(id="auth", question="Are you legally authorized to work in the country where this position is located?", field_type=FieldType.RADIO)).value == "Yes"
    assert answers.deterministic(Field(id="sponsor", question="Will you require employer support to obtain or maintain authorization to work in that country? (work permit)", field_type=FieldType.RADIO)).value == "No"
    assert answers.deterministic(Field(id="marketing", question="I agree to marketing communications", field_type=FieldType.CHECKBOX)).value is None


def test_required_llm_dropdown_must_match_visible_option():
    profile = valid_profile()
    llm = Mock(generate=AsyncMock(return_value="Yes"))
    service = AnswerService(profile, Mock(find_approved=Mock(return_value=None), save=Mock(return_value=1)), llm)
    field = Field(id="q", question="Would you recommend this role?", required=True,
                  field_type=FieldType.SELECT, options=[Option(label="No", value="no")])
    answer = asyncio.run(service.resolve(field))
    assert answer.value is None
    assert "exact option" in answer.reason


def test_llm_answer_is_review_required():
    profile = valid_profile()
    llm = Mock(generate=AsyncMock(return_value="I built reliable software."))
    repo = Mock(find_approved=Mock(return_value=None), save=Mock(return_value=1))
    answer = asyncio.run(AnswerService(profile, repo, llm).resolve(
        Field(id="q", question="Why this role?", field_type=FieldType.TEXTAREA, required=True)))
    assert answer.source == AnswerSource.LLM and answer.requires_review


def test_llm_wrong_python_type_pauses():
    profile = valid_profile()
    llm = Mock(generate=AsyncMock(return_value=["not", "text"]))
    repo = Mock(find_approved=Mock(return_value=None))
    answer = asyncio.run(AnswerService(profile, repo, llm).resolve(
        Field(id="q", question="Describe your project", field_type=FieldType.TEXT, required=True)))
    assert answer.value is None and "unsupported field type" in answer.reason
