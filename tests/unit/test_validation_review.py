import pytest
from app.domain.answer import Answer
from app.domain.enums import Severity as S, AnswerSource as A, FieldType as T
from app.services.review_service import ReviewService

@pytest.mark.parametrize('value',[None,'','   ',[]])
def test_blank_required_blocks(validation,field,value):
    findings = validation.validate([field(value=value)])
    assert not validation.can_navigate(findings)
    assert any(f.message == 'Required field is blank.' for f in findings)

@pytest.mark.parametrize('question,value',[('School','University of Michigan-Flint'),('Major','Data Science'),('Degree','Master of Science'),('Graduation date','2026-05')])
def test_education_mismatch_blocks(validation,field,question,value):
    assert not validation.can_navigate(validation.validate([field(question,value)]))

def test_unknown_prefilled_is_untrusted(validation,field):
    assert not validation.can_navigate(validation.validate([field('Current salary','90000')]))

def test_low_confidence_blocks(validation,field):
    f = field('Years of experience','3')
    a = Answer(value='3',confidence=.69,source=A.UNKNOWN)
    assert not validation.can_navigate(validation.validate([f],{f.key:a}))

def test_warnings_alone_allow_navigation(validation,field):
    f = field('Why this company?','A draft')
    a = Answer(value='A draft',confidence=.82,source=A.LLM,requires_review=True)
    findings = validation.validate([f],{f.key:a})
    assert any(x.severity == S.WARNING for x in findings)
    assert validation.can_navigate(findings)

def test_empty_optional_unknown_does_not_block(validation,field):
    assert validation.can_navigate(validation.validate([field('Optional question','',required=False)]))
    assert validation.can_navigate(validation.validate([field('Subscribe',False,required=False,field_type=T.CHECKBOX)]))

@pytest.mark.parametrize('question,value',[('School','Michigan State University'),('Email','')])
def test_review_wrong_school_and_blank_required_not_ready(validation,field,question,value):
    assert not ReviewService(validation).audit([field(question,value)]).ready

@pytest.mark.parametrize('source',[A.LLM,A.ANSWER_BANK])
def test_review_exposes_generated_and_medium_answers(validation,field,source):
    f = field('Why this company?','Draft')
    report = ReviewService(validation).audit([f],{f.key:Answer(value='Draft',confidence=.82,source=source,requires_review=True)})
    assert report.ready
    assert any(x.severity == S.WARNING and x.field_id == f.id for x in report.findings)

def test_valid_application_ready(validation,field):
    fields = [field('Full name','Test Applicant'),field('Email','test@example.test'),field('Phone','555-010-1234'),
        field('School','University of Michigan'),field('Major','Computer Science'),field('Degree','Bachelor of Science'),
        field('Graduation date','2027-05'),field('Are you authorized to work in the US?','Yes'),field('Will you require sponsorship?','Yes')]
    report = ReviewService(validation).audit(fields)
    assert report.ready and report.audited_fields == 9
    assert not any(x.severity == S.ERROR for x in report.findings)
    assert any('attachment' in x.message for x in report.findings)

def test_empty_audit_not_ready(validation): assert not ReviewService(validation).audit([]).ready

def test_visible_validation_error_blocks(validation,field):
    assert not validation.can_navigate(validation.validate([field('Email','test@example.test')],errors=['Invalid email from server']))
