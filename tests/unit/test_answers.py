import pytest
from app.domain.answer import Answer
from app.domain.enums import CanonicalQuestion as Q, AnswerSource as S, FieldType as T, ConfidenceAction as C
from app.services.question_normalizer import QuestionNormalizer
from app.services.education_service import EducationService
from app.services.confidence_policy import ConfidencePolicy
from app.services.answer_service import AnswerService

@pytest.mark.parametrize('question',[
    'Will you now or in the future require sponsorship?', 'Will you require employment sponsorship?',
    'Do you anticipate needing visa sponsorship?'])
def test_sponsorship_normalization(question):
    assert QuestionNormalizer().normalize(question) == Q.REQUIRES_SPONSORSHIP

@pytest.mark.parametrize('question',['Are you authorized to work in the US?', 'Are you legally eligible for employment in the United States?', 'Do you have the legal right to work in the USA?'])
def test_authorization_normalization(question):
    assert QuestionNormalizer().normalize(question) == Q.AUTHORIZED_TO_WORK

@pytest.mark.parametrize('question',['Why this company?', 'Describe your experience with Python.', 'I do not require sponsorship'])
def test_unknown_normalization(question):
    assert QuestionNormalizer().normalize(question) == Q.UNKNOWN

@pytest.mark.parametrize('school',['University of Michigan - Ann Arbor','University of Michigan','University of Michigan-Ann Arbor'])
def test_explicit_school_aliases(profile, school):
    assert EducationService(profile).matches(Q.SCHOOL, school)

@pytest.mark.parametrize('school',['University of Michigan-Dearborn','University of Michigan-Flint','Michigan State University'])
def test_unsafe_nearby_schools(profile, school):
    assert not EducationService(profile).matches(Q.SCHOOL, school)
    profile.education.school_aliases.append(school)
    assert EducationService(profile).matches(Q.SCHOOL, school)
    profile.education.unsafe_school_matches.append(school)
    assert not EducationService(profile).matches(Q.SCHOOL, school)

@pytest.mark.parametrize('major',['Computer Engineering','Data Science','Information Science','Computer Science, General'])
def test_no_fuzzy_major(profile, major):
    assert not EducationService(profile).matches(Q.MAJOR, major)

def test_major_alias_requires_configuration(profile):
    service = EducationService(profile)
    assert service.matches(Q.MAJOR,'Computer Science')
    assert not service.matches(Q.MAJOR,'Computer Science, General')
    profile.education.major_aliases.append('Computer Science, General')
    assert service.matches(Q.MAJOR,'Computer Science, General')

def test_degree_and_graduation(profile):
    service = EducationService(profile)
    assert service.matches(Q.DEGREE,'Bachelor of Science')
    assert not service.matches(Q.DEGREE,'Master of Science')
    assert service.matches(Q.GRADUATION_DATE,'2027-05','Graduation date')
    assert not service.matches(Q.GRADUATION_DATE,'2027-06','Graduation date')
    assert service.matches(Q.GRADUATION_DATE,'May','Graduation month')
    assert service.expected(Q.GRADUATION_DATE,'Graduation year') == '2027'

@pytest.mark.parametrize('value,expected',[(.95,C.AUTO_FILL),(.9,C.AUTO_FILL),(.82,C.FILL_AND_REVIEW),(.70,C.FILL_AND_REVIEW),(.69,C.REQUIRE_HUMAN)])
def test_confidence_thresholds(value, expected): assert ConfidencePolicy().classify(value) == expected

def test_configurable_confidence():
    assert ConfidencePolicy(.95,.8).classify(.9) == C.FILL_AND_REVIEW
    with pytest.raises(ValueError): ConfidencePolicy(.6,.8)

async def test_deterministic_before_bank_and_llm(profile, bank, llm, field):
    answer = await AnswerService(profile,bank,llm).resolve(field('Will you require employment sponsorship?'))
    assert answer.value == 'Yes' and answer.source == S.RULE
    bank.find_approved.assert_not_called(); llm.generate.assert_not_awaited()

async def test_profile_before_llm(profile, bank, llm, field):
    answer = await AnswerService(profile,bank,llm).resolve(field('Email'))
    assert answer.value == 'test@example.test' and answer.confidence == 1
    llm.generate.assert_not_awaited()

@pytest.mark.parametrize('label', ['School or University*', 'School / University', 'College or University*'])
async def test_combined_school_label_uses_profile(profile, bank, llm, field, label):
    service = AnswerService(profile, bank, llm)
    answer = await service.resolve(field(label))
    assert answer.value == profile.education.school and answer.source == S.PROFILE
    assert not service.matches(field(label, 'University of Michigan-Flint'), answer)
    bank.find_approved.assert_not_called()
    llm.generate.assert_not_awaited()

async def test_bank_before_llm(profile, bank, llm, field):
    bank.find_approved.return_value = Answer(value='Approved answer',source=S.ANSWER_BANK,confidence=1,requires_review=False)
    answer = await AnswerService(profile,bank,llm).resolve(field('Why this company?'))
    assert answer.value == 'Approved answer'
    llm.generate.assert_not_awaited()

async def test_unapproved_not_reused_and_llm_draft_saved(profile, bank, llm, field):
    bank.find_approved.return_value = None
    answer = await AnswerService(profile,bank,llm).resolve(field('Why this company?',field_type=T.TEXTAREA))
    bank.find_approved.assert_called_once()
    assert answer.source == S.LLM and answer.requires_review and answer.bank_id == 42
    bank.save.assert_called_once()
    assert not bank.save.call_args.kwargs.get('approved',False)

async def test_missing_factual_value_never_calls_llm(profile, bank, llm, field):
    profile.work_authorization.require_future_sponsorship = None
    answer = await AnswerService(profile,bank,llm).resolve(field('Will you require sponsorship?'))
    assert answer.value is None
    bank.find_approved.assert_not_called(); llm.generate.assert_not_awaited()

@pytest.mark.parametrize('q',['Are you authorized to work in Canada?', 'Are you authorized to work?', 'What is your ethnicity?', 'How many years of Python experience?'])
async def test_never_infer_facts(profile, bank, llm, field, q):
    assert (await AnswerService(profile,bank,llm).resolve(field(q))).value is None
    llm.generate.assert_not_awaited()

async def test_provider_failure_escalates(profile, bank, llm, field):
    llm.generate.side_effect = RuntimeError('secret provider response')
    answer = await AnswerService(profile,bank,llm).resolve(field('Why this role?'))
    assert answer.value is None and 'secret' not in answer.reason

async def test_no_key_deterministic_works(answers,field):
    assert (await answers.resolve(field('Major'))).value == 'Computer Science'

async def test_boolean_false_is_trusted(profile,bank,field):
    a = await AnswerService(profile,bank).resolve(field('Are you willing to relocate?'))
    assert a.value == 'No'

def test_attachment_same_name_is_not_sufficient(answers,field,tmp_path):
    import hashlib
    resume=tmp_path/'resume.txt'; resume.write_text('Correct resume')
    answers.profile.application.resume_path=str(resume)
    f=field('Resume',['resume.txt'],field_type=T.FILE)
    answer=answers.deterministic(f)
    assert not answers.matches(f,answer)
    f.attachment_hashes={'resume.txt':hashlib.sha256(b'Wrong resume').hexdigest()}
    assert not answers.matches(f,answer)
    f.attachment_hashes={'resume.txt':hashlib.sha256(resume.read_bytes()).hexdigest()}
    assert answers.matches(f,answer)
