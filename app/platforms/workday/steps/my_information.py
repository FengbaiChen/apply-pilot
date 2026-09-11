import re
from app.domain.answer import Answer
from app.domain.enums import AnswerSource
from app.services.question_normalizer import normalized_text
from .base import WorkdayStep


class MyInformationStep(WorkdayStep):
    key = 'my_information'
    heading = 'My Information'

    def answer(self, field, profile):
        question = normalized_text(field.question)
        if question == 'how did you hear about us':
            return Answer(value='LinkedIn Jobs', source=AnswerSource.RULE, confidence=1,
                          requires_review=False, reason='Workday source policy: LinkedIn Jobs')
        if question == 'i have a preferred name':
            return Answer(value=bool(profile.personal.preferred_name), source=AnswerSource.RULE,
                          confidence=1, requires_review=False, reason='Preferred name is explicit in profile')
        if re.fullmatch(r'have you previously worked for .+ as an employee or contractor', question):
            return Answer(value='No', source=AnswerSource.RULE, confidence=1, requires_review=False,
                          reason='User policy: answer no to previous-employer questions')
        if normalized_text(field.question) not in {'phone number', 'phone', 'mobile phone'}:
            return None
        phone = profile.phone.number or profile.personal.phone or ''
        code = re.sub(r'\D', '', profile.phone.country_code or profile.personal.phone_country_code or '')
        selected = field.locator.phone_country_code
        digits = re.sub(r'\D', '', phone)
        if not code or (selected and selected != code):
            return Answer(reason='Confirm the phone country code before filling the national phone number.')
        if phone.startswith('+'):
            if not digits.startswith(code): return Answer(reason='Phone country code conflicts with the shared phone number.')
            digits = digits[len(code):]
        if not digits: return Answer(reason='Phone number is missing.')
        return Answer(value=digits, source=AnswerSource.RULE, confidence=1, requires_review=False,
                      reason='Workday uses a separate country code; this is the national number only.')
