from app.domain.answer import Answer
from app.domain.enums import CanonicalQuestion, AnswerSource, FieldType
from app.services.question_normalizer import QuestionNormalizer, normalized_text
import re
import inspect
from .base import WorkdayStep


class MyExperienceStep(WorkdayStep):
    key = 'my_experience'
    heading = 'My Experience'

    async def prepare(self, service):
        # Repeated employer/education cards need their own identities. Never fill every
        # card with the same top-level school or guess a record from its screen position.
        p = service.worker.page
        records = service.answers.profile.work_records
        ensure_work = getattr(service.adapter, 'ensure_work_experience_records', None)
        result = ensure_work(records) if ensure_work else None
        blocker = await result if inspect.isawaitable(result) else result if isinstance(result, str) else None
        if blocker:
            return blocker
        ensure_education = getattr(service.adapter, 'ensure_education_record', None)
        result = ensure_education() if ensure_education else None
        blocker = await result if inspect.isawaitable(result) else result if isinstance(result, str) else None
        if blocker:
            return blocker
        fields = await service.adapter.scan_fields()
        normalizer = QuestionNormalizer()
        schools = [f for f in fields if normalizer.normalize(f.question) == CanonicalQuestion.SCHOOL]
        if len(schools) > 1:
            return 'Only one Ann Arbor education record is supported; remove extra education cards manually.'
        uploads = p.locator('input[type="file"]')
        if await uploads.count() and not service.answers.profile.application.resume_path:
            return 'Add a resume path to the shared profile, then restart, or upload it in Workday and confirm it.'
        return None

    def answer(self, field, profile):
        if 'work experience' in field.section.casefold():
            match = re.fullmatch(r'work experience\s+(\d+)', normalized_text(field.section))
            records = profile.work_records
            if not match or not 1 <= int(match[1]) <= len(records):
                return Answer(reason='This Workday work record has no corresponding shared-profile entry.')
            record = records[int(match[1]) - 1]
            question = re.sub(r'\s+\((month|year)\)$', '', normalized_text(field.question))
            key = {'job title': 'job_title', 'company': 'company', 'location': 'location',
                   'role description': 'description', 'i currently work here': 'current'}.get(question)
            value = getattr(record, key) if key else None
            if question in {'from', 'to', 'to (actual or expected)'}:
                prefix = 'start' if question == 'from' else 'end'
                component = field.locator.date_component
                if component in {'month', 'year'}:
                    value = getattr(record, prefix + '_' + component)
                    if value is not None:
                        value = f'{value:02d}' if component == 'month' else str(value)
            if value is None:
                return Answer(reason='This fact is missing for the selected work record; please supply it explicitly.')
            if isinstance(value, bool) and field.field_type != FieldType.CHECKBOX:
                value = 'Yes' if value else 'No'
            return Answer(value=value, source=AnswerSource.PROFILE, confidence=1,
                          requires_review=False, reason=f'Shared work_experience record {match[1]}')
        question = normalized_text(field.question)
        if question == 'url' and normalized_text(field.section).startswith('websites'):
            value = profile.links.github
            if value:
                return Answer(value=value, source=AnswerSource.PROFILE, confidence=1,
                              requires_review=False, reason='Configured GitHub website')
        if ('linkedin profile' in question or 'linkedin' in normalized_text(field.section)
                or ('social network' in normalized_text(field.section) and question == 'url')):
            value = profile.links.linkedin or profile.personal.linkedin
            if value:
                return Answer(value=value, source=AnswerSource.PROFILE, confidence=1,
                              requires_review=False, reason='Configured LinkedIn profile')
        return None
