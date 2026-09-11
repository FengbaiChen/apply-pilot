from unittest.mock import patch

import pytest
import yaml

from app.config.profile import Profile
from app.domain.enums import AnswerSource as S, FieldType as T
from app.domain.field import Option
from app.domain.human_question import HumanResponse
from app.repositories.profile_answer_repository import ProfileSaveError
from app.services.answer_service import AnswerService
from app.services.human_question_service import HumanQuestionService, InvalidHumanAnswer
from test_application_service import service


def remember(answers, field, value, company="https://one.test/apply"):
    answers.remember([(field, HumanQuestionService.validate(field, value))], company=company)


async def test_saved_reply_survives_reload_and_precedes_bank_llm(profile, bank, llm, field, tmp_path):
    path = tmp_path / 'custom-profile.yaml'
    path.write_text(yaml.safe_dump({**profile.model_dump(mode='json'), 'custom_metadata': {'keep': True}}))
    answers = AnswerService(profile, bank, llm, profile_path=path)
    remember(answers, field('Years using Python?'), '3')
    raw = yaml.safe_load(path.read_text())
    assert raw['custom_metadata'] == {'keep': True}
    assert raw['personal']['email'] == profile.personal.email
    restarted = AnswerService(Profile.load(path), bank, llm, profile_path=path)
    answer = await restarted.resolve(field('  YEARS using Python *'), company='https://two.test/apply')
    assert answer.value == '3' and answer.source == S.PROFILE_CACHE
    bank.find_approved.assert_not_called()
    llm.generate.assert_not_awaited()
    assert 'saved_answers' not in restarted.profile.prose_facts()
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('kind,value,options', [
    (T.TEXT, '中文回答', []), (T.CHECKBOX, False, []),
    (T.SELECT, 'Hybrid', [Option(label='Hybrid', value='h')]),
    (T.MULTISELECT, ['Go', 'Python'], [Option(label='Go', value='g'), Option(label='Python', value='p')]),
])
async def test_cache_preserves_typed_values(profile, bank, field, tmp_path, kind, value, options):
    path = tmp_path / 'profile.yaml'
    answers = AnswerService(profile, bank, profile_path=path)
    f = field('Preference', required=False, field_type=kind, options=options)
    remember(answers, f, value)
    answer = await AnswerService(Profile.load(path), bank).resolve(f)
    assert answer.value == value and type(answer.value) is type(value)


async def test_missing_profile_fact_can_use_explicit_cache_but_known_fact_wins(answers, field):
    answers.profile.preferences.willing_to_relocate = None
    f = field('Are you willing to relocate?')
    remember(answers, f, 'Yes')
    assert (await answers.resolve(f)).value == 'Yes'
    answers.profile.preferences.willing_to_relocate = False
    answer = await answers.resolve(f)
    assert answer.value == 'No' and answer.source == S.RULE


async def test_cached_school_uses_explicit_selected_label(answers, field):
    answers.profile.education.school = None
    answers.profile.education.school_aliases = []
    f = field('School', 'Explicit University', field_type=T.SELECT,
              options=[Option(label='Explicit University', value='u')])
    remember(answers, f, 'Explicit University')
    answer = await answers.resolve(f)
    assert answers.matches(f, answer)
    assert answers.acceptable_labels(f, answer) == ['Explicit University']


@pytest.mark.parametrize('question,kind', [('Why this company?', T.TEXT),
    ('Additional comments', T.TEXTAREA), ('I agree to the terms', T.CHECKBOX)])
async def test_contextual_answers_do_not_cross_application_urls(answers, field, question, kind):
    f = field(question, field_type=kind)
    value = True if kind == T.CHECKBOX else 'Explicit reply'
    remember(answers, f, value)
    assert (await answers.resolve(f, company='https://one.test/apply')).value == value
    assert (await answers.resolve(f, company='https://two.test/apply')).value is None


async def test_question_section_type_and_choices_must_match(answers, field):
    options = [Option(label='Hybrid', value='h'), Option(label='Remote', value='r')]
    original = field('Preferred work arrangement', field_type=T.SELECT, options=options)
    remember(answers, original, 'Hybrid')
    # Employers may use different opaque option values and ordering.
    equivalent = original.model_copy(update={'options': [Option(label='Remote', value='2'), Option(label='Hybrid', value='1')]})
    assert (await answers.resolve(equivalent)).value == 'Hybrid'
    for changed in [original.model_copy(update={'question': 'Previous work arrangement'}),
                    original.model_copy(update={'section': 'Previous job'}),
                    original.model_copy(update={'field_type': T.RADIO}),
                    original.model_copy(update={'options': [Option(label='Onsite', value='o')]})]:
        assert (await answers.resolve(changed)).value is None


async def test_failed_save_keeps_original_file_cache_and_paused_session(service, field, tmp_path):
    app, _, adapter = service
    path = tmp_path / 'profile.yaml'
    original = yaml.safe_dump(app.answers.profile.model_dump(mode='json'))
    path.write_text(original)
    app.answers.profile_answers.path = path
    adapter.scan_fields.return_value = [field('Years using Python')]
    session = await app.start('https://one.test/apply'); await app.task
    question = app.session.pending_questions[0]
    with patch('app.repositories.profile_answer_repository.os.replace', side_effect=OSError('private error')):
        with pytest.raises(ProfileSaveError, match='remains paused'):
            await app.submit_answers(session.application_id, [HumanResponse(question_id=question.question_id, value='3')])
    assert path.read_text() == original
    assert app.answers.profile.saved_answers == []
    assert app.session.status == 'WAITING_FOR_HUMAN'
    assert app.session.pending_questions[0].question_id == question.question_id
    assert not list(tmp_path.glob('.profile-*.tmp'))
    adapter.fill_field.assert_not_awaited()
    await app.shutdown()


async def test_invalid_batch_saves_nothing(service, field, tmp_path):
    app, _, adapter = service
    path = tmp_path / 'profile.yaml'
    app.answers.profile_answers.path = path
    adapter.scan_fields.return_value = [field('Question one'), field('Question two')]
    session = await app.start('https://one.test/apply'); await app.task
    first, second = app.session.pending_questions
    with pytest.raises(InvalidHumanAnswer):
        await app.submit_answers(session.application_id, [HumanResponse(question_id=first.question_id, value='Good'),
            HumanResponse(question_id=second.question_id, value='')])
    assert not path.exists()
    assert app.answers.profile.saved_answers == []
    await app.shutdown()


async def test_next_application_reuses_reply_even_when_optional(service, field, tmp_path):
    app, _, adapter = service
    app.answers.profile_answers.path = tmp_path / 'profile.yaml'
    f = field('Years using Python')
    adapter.scan_fields.return_value = [f]
    async def fill(fld, value, option=None): f.current_value = value
    adapter.fill_field.side_effect = fill
    session = await app.start('https://one.test/apply'); await app.task
    q = app.session.pending_questions[0]
    await app.submit_answers(session.application_id, [HumanResponse(question_id=q.question_id, value='3')])
    await app.task
    assert app.session.status == 'READY_FOR_REVIEW'
    await app.stop(session.application_id)
    f.current_value = ''; f.required = False
    await app.start('https://two.test/apply'); await app.task
    assert app.session.status == 'READY_FOR_REVIEW'
    assert f.current_value == '3'
    assert app.resolved[f.key].source == S.PROFILE_CACHE
    await app.shutdown()


def test_upsert_preserves_external_edits(answers, field, tmp_path):
    path = tmp_path / 'profile.yaml'
    answers.profile_answers.path = path
    remember(answers, field('Years using Python'), '3')
    raw = yaml.safe_load(path.read_text())
    raw['personal']['city'] = 'Updated externally'
    path.write_text(yaml.safe_dump(raw))
    remember(answers, field('Years using Python'), '4')
    raw = yaml.safe_load(path.read_text())
    assert raw['personal']['city'] == 'Updated externally'
    assert len(raw['saved_answers']) == 1
    assert raw['saved_answers'][0]['value'] == '4'
