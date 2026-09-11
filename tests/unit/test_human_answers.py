from unittest.mock import Mock
import pytest
from app.domain.answer import Answer
from app.domain.enums import AnswerSource, FieldType as T
from app.domain.field import Option
from app.domain.human_question import HumanResponse
from app.services.human_question_service import HumanQuestionService, InvalidHumanAnswer
from app.services.confidence_policy import ConfidencePolicy
from app.services.application_service import SessionConflict

# Reuse the fully isolated session fixture; this module still launches no browser.
from test_application_service import service

@pytest.fixture
def questions(answers): return HumanQuestionService(answers, ConfidencePolicy())

def test_collect_unknown_and_protect_known_facts(questions, field):
    unknown=field('Years using Python','')
    school=field('School','Wrong University')
    file=field('Resume',[],field_type=T.FILE)
    pending,snapshots=questions.collect([unknown,school,file],{})
    assert len(pending) == 1 and pending[0].question == 'Years using Python'
    assert snapshots[pending[0].question_id].key == unknown.key

@pytest.mark.parametrize('type,value',[(T.TEXT,'3'),(T.TEXTAREA,'My answer'),(T.CHECKBOX,True)])
def test_explicit_answers_are_human(questions,field,type,value):
    answer=questions.validate(field('Question',field_type=type),value)
    assert answer.value == value and answer.source == AnswerSource.HUMAN and answer.confidence == 1

@pytest.mark.parametrize('type,value',[(T.TEXT,''),(T.TEXT,' '),(T.TEXT,True),(T.CHECKBOX,'false'),(T.CHECKBOX,False),(T.MULTISELECT,[])])
def test_invalid_values_rejected(questions,field,type,value):
    with pytest.raises(InvalidHumanAnswer): questions.validate(field('Question',field_type=type),value)

def test_multiple_choices_validate_unique_labels(questions,field):
    f=field('Languages',field_type=T.MULTISELECT,options=[Option(label='Python',value='py'),Option(label='Go',value='go')])
    assert questions.validate(f,['Python','Go']).value == ['Python','Go']
    with pytest.raises(InvalidHumanAnswer): questions.validate(f,['Python','Python'])
    with pytest.raises(InvalidHumanAnswer): questions.validate(f,['Rust'])

async def test_unknown_question_reply_auto_resumes(service,field):
    app,worker,adapter=service
    f=field('Years using Python','')
    adapter.scan_fields.return_value=[f]
    async def fill_field(fld,value,option=None): f.current_value=value
    adapter.fill_field.side_effect=fill_field
    session=await app.start('https://example.test/apply'); await app.task
    paused=app.get(session.application_id)
    assert paused.status == 'WAITING_FOR_HUMAN'
    assert paused.pending_questions[0].question == 'Years using Python'
    response=HumanResponse(question_id=paused.pending_questions[0].question_id,value='3')
    await app.submit_answers(session.application_id,[response]); await app.task
    assert app.get(session.application_id).status == 'READY_FOR_REVIEW'
    assert f.current_value == '3'
    assert not app.get(session.application_id).pending_questions
    worker.close.assert_not_awaited()
    await app.shutdown()

async def test_stale_browser_values_rejected(service,field):
    app,_,adapter=service
    f=field('Years using Python',''); adapter.scan_fields.return_value=[f]
    session=await app.start('https://example.test/apply'); await app.task
    q=app.session.pending_questions[0]
    f.current_value='Changed manually'
    with pytest.raises(SessionConflict):
        await app.submit_answers(session.application_id,[HumanResponse(question_id=q.question_id,value='3')])
    assert app.session.status == 'WAITING_FOR_HUMAN'
    await app.shutdown()

async def test_answer_batch_is_atomic(service,field):
    app,_,adapter=service
    fields=[field('Years using Python',''),field('Languages','',field_type=T.SELECT,options=[Option(label='Python',value='py')])]
    adapter.scan_fields.return_value=fields
    session=await app.start('https://example.test/apply'); await app.task
    pending=app.session.pending_questions
    with pytest.raises(InvalidHumanAnswer):
        await app.submit_answers(session.application_id,[HumanResponse(question_id=pending[0].question_id,value='3'),HumanResponse(question_id=pending[1].question_id,value='Rust')])
    assert app.resolved[fields[0].key].value is None
    await app.shutdown()

async def test_duplicate_or_partial_question_ids_rejected(service,field):
    app,_,adapter=service
    adapter.scan_fields.return_value=[field('Question one',''),field('Question two','')]
    session=await app.start('https://example.test/apply'); await app.task
    q=app.session.pending_questions[0]
    answer=HumanResponse(question_id=q.question_id,value='Answer')
    with pytest.raises(InvalidHumanAnswer): await app.submit_answers(session.application_id,[answer])
    with pytest.raises(InvalidHumanAnswer): await app.submit_answers(session.application_id,[answer,answer])
    await app.shutdown()

async def test_unknown_school_can_use_explicit_human_selection(service,field):
    app,_,adapter=service
    app.answers.profile.education.school=None
    app.answers.profile.education.school_aliases=[]
    f=field('School','',field_type=T.SELECT,options=[Option(label='Human supplied university',value='uni')])
    adapter.scan_fields.return_value=[f]
    async def fill_field(fld,value,option=None): f.current_value=option.label
    adapter.fill_field.side_effect=fill_field
    session=await app.start('https://example.test/apply'); await app.task
    q=app.session.pending_questions[0]
    await app.submit_answers(session.application_id,[HumanResponse(question_id=q.question_id,value='Human supplied university')]); await app.task
    assert app.session.status == 'READY_FOR_REVIEW'
    await app.shutdown()

async def test_unconfigured_llm_exposes_free_form_question(service,field):
    app,_,adapter=service
    adapter.scan_fields.return_value=[field('Why this company?','',field_type=T.TEXTAREA)]
    session=await app.start('https://example.test/apply'); await app.task
    assert 'No usable LLM draft' in app.session.pending_questions[0].reason
    assert not app.capabilities()['llm_configured']
    await app.shutdown()
