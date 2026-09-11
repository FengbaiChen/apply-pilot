from unittest.mock import Mock, AsyncMock
import pytest
from app.config.profile import Profile
from app.domain.field import Field
from app.services.answer_service import AnswerService
from app.services.confidence_policy import ConfidencePolicy
from app.services.validation_service import ValidationService

@pytest.fixture
def profile():
    return Profile.model_validate({
        'personal': {'full_name':'Test Applicant','first_name':'Test','last_name':'Applicant','email':'test@example.test','phone':'5550101234'},
        'work_authorization': {'authorized_to_work_us':True,'require_future_sponsorship':True},
        'preferences': {'willing_to_relocate':False},
        'education': {'school':'University of Michigan - Ann Arbor','school_aliases':['University of Michigan','University of Michigan-Ann Arbor'],
                      'unsafe_school_matches':[], 'major':'Computer Science','major_aliases':[], 'degree':'Bachelor of Science',
                      'graduation_month':5,'graduation_year':2027},
        'experience_facts':['Built a Python test runner for a course project.']})

@pytest.fixture
def bank():
    repo = Mock()
    repo.find_approved.return_value = None
    repo.save.return_value = 42
    return repo

@pytest.fixture
def llm(): return Mock(generate=AsyncMock(return_value='I built a Python test runner for a course project.'))

@pytest.fixture
def answers(profile, bank): return AnswerService(profile, bank)

@pytest.fixture
def validation(answers): return ValidationService(answers, ConfidencePolicy())

@pytest.fixture
def field():
    def make(question='Email', value='', required=True, **kwargs):
        return Field(id=question, question=question, current_value=value, required=required, **kwargs)
    return make
