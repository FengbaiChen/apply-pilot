from app.services.answer_service import AnswerService
from .steps import STEPS
from app.services.question_normalizer import normalized_text
from app.domain.answer import Answer
from app.domain.enums import AnswerSource, CanonicalQuestion, FieldType


class WorkdayAnswerService(AnswerService):
    step_key = 'my_information'

    def __init__(self, *args, platform_profile=None, shared_profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.platform_profile = platform_profile
        self.bindings = {normalized_text(k): v for k, v in (platform_profile.question_aliases.items() if platform_profile else [])}

    def deterministic(self, field):
        q = normalized_text(field.question)
        terms_phrase = ('terms of service' in q or 'applicant privacy policy' in q
                        or ('terms and conditions' in q
                            and any(x in q for x in ('accept', 'agree', 'acknowledge', 'consent'))))
        unsafe_consent = any(x in q for x in ('marketing', 'background', 'arbitration'))
        if field.field_type == FieldType.CHECKBOX and terms_phrase and not unsafe_consent:
            return Answer(value=True, source=AnswerSource.RULE, confidence=1,
                          requires_review=True, reason='Explicit Workday terms/privacy consent policy')
        if (field.field_type == FieldType.CHECKBOX and (not terms_phrase or unsafe_consent)
                and any(x in q for x in ('marketing', 'background', 'arbitration', 'consent',
                                         'authorize', 'agree', 'acknowledge', 'release'))):
            return Answer(reason='This consent checkbox is not a narrowly recognized Workday Terms/Privacy agreement; confirm it manually.')
        if 'authorized to work in the country where this position is located' in q:
            value = self.profile.work_authorization.authorized_to_work_us
            if value is not None:
                return Answer(value='Yes' if value else 'No', source=AnswerSource.RULE,
                              confidence=1, requires_review=False,
                              reason='Workday position country is the configured US authorization jurisdiction')
        path = self.bindings.get(q)
        if path:
            value = self.profile.model_dump()
            for part in path.removeprefix('shared.').split('.'):
                value = value.get(part) if isinstance(value, dict) else None
            if value is not None:
                return Answer(value=('Yes' if value is True else 'No' if value is False else value),
                              source=AnswerSource.PROFILE, confidence=1, requires_review=False,
                              reason=f'Explicit Workday mapping to {path}')
        step = STEPS.get(self.step_key)
        answer = step.answer(field, self.profile) if step else None
        return answer if answer is not None else super().deterministic(field)

    def acceptable_labels(self, field, answer):
        labels = super().acceptable_labels(field, answer)
        if normalized_text(field.question) in {'country phone code', 'phone country code'}:
            code = str(answer.value)
            labels.extend([o.label for o in field.options if code in o.label or f'+{code.lstrip("+")}' in o.label])
        return list(dict.fromkeys(labels))

    async def resolve(self, field, *args, **kwargs):
        """Never reuse stale history for authorization or voluntary disclosures."""
        canonical = self.normalizer.normalize(field.question)
        q = normalized_text(field.question)
        protected_disclosure = self.step_key == 'voluntary_disclosures' and any(
            marker in q for marker in ('gender', 'race', 'ethnic', 'hispanic', 'veteran', 'disability'))
        protected_fact = canonical in {CanonicalQuestion.AUTHORIZED_TO_WORK,
                                      CanonicalQuestion.REQUIRES_SPONSORSHIP}
        if protected_disclosure or protected_fact:
            direct = self.deterministic(field)
            if direct is not None and direct.value is None:
                return direct
        return await super().resolve(field, *args, **kwargs)
