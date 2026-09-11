from app.domain.answer import Answer
from app.domain.enums import AnswerSource
from app.services.question_normalizer import normalized_text
from .base import WorkdayStep


class VoluntaryDisclosuresStep(WorkdayStep):
    key = 'voluntary_disclosures'
    heading = 'Voluntary Disclosures'

    def answer(self, field, profile):
        q = normalized_text(field.question)
        mapping = {
            'gender': profile.demographics.gender,
            'race': profile.demographics.ethnicity,
            'ethnic': profile.demographics.ethnicity,
            'hispanic': profile.demographics.hispanic_or_latino,
            'veteran': profile.demographics.veteran_status,
            'disability': profile.demographics.disability,
        }
        for marker, value in mapping.items():
            if marker in q:
                if value is None:
                    return Answer(reason='This voluntary disclosure is not configured in profile.yaml.')
                return Answer(value=value, source=AnswerSource.PROFILE, confidence=1,
                              requires_review=False, reason='Explicit voluntary disclosure in profile')
        return None
