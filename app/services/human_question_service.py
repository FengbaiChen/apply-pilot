from app.domain.answer import Answer
from app.domain.enums import AnswerSource, FieldType as T
from app.domain.field import Field
from app.domain.human_question import HumanQuestion
from app.services.question_normalizer import normalized_text
from app.services.validation_service import is_blank


class InvalidHumanAnswer(ValueError):
    pass


class HumanQuestionService:
    """Turn unresolved facts into explicit questions; never infer an answer."""

    def __init__(self, answers, confidence):
        self.answers = answers
        self.confidence = confidence

    def collect(self, fields, resolved):
        pending = []
        snapshots = {}
        for field in fields:
            if (not field.enabled or field.locator.read_only
                    or field.field_type in {T.FILE, T.UNKNOWN}
                    or (not field.required and is_blank(field))):
                continue
            known = self.answers.deterministic(field)
            if known is not None and known.value is not None:
                continue  # A known profile mismatch must be corrected, not overwritten.
            answer = resolved.get(field.key) or known
            if (answer is not None and answer.value is not None
                    and self.answers.matches(field, answer)):
                continue
            # A trusted answer that failed to fill needs browser intervention.
            if (answer is not None and answer.value is not None
                    ):
                continue
            question = HumanQuestion(question=field.question, field_type=field.field_type,
                required=field.required, current_value=field.current_value, options=field.options,
                reason=answer.reason if answer else "Please supply this answer.")
            pending.append(question)
            snapshots[question.question_id] = field.model_copy(deep=True)
        return pending, snapshots

    @staticmethod
    def validate(field: Field, value) -> Answer:
        if field.field_type == T.CHECKBOX:
            if not isinstance(value, bool):
                raise InvalidHumanAnswer("Choose Yes or No for each checkbox question.")
            if field.required and not value:
                raise InvalidHumanAnswer("This required checkbox cannot remain unchecked; handle it in the browser if you disagree.")
        elif field.field_type == T.MULTISELECT:
            if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
                raise InvalidHumanAnswer("Choose at least one option for each multiple-choice question.")
            value = [v.strip() for v in value]
            if len(set(value)) != len(value):
                raise InvalidHumanAnswer("Duplicate selections are not allowed.")
        else:
            if not isinstance(value, str) or not value.strip() or len(value) > 10000:
                raise InvalidHumanAnswer("Provide a non-empty text answer of at most 10,000 characters.")
            value = value.strip()
        if field.options and field.field_type in {T.SELECT, T.RADIO, T.MULTISELECT, T.AUTOCOMPLETE}:
            for item in value if isinstance(value, list) else [value]:
                matches = [o for o in field.options if normalized_text(o.label) == normalized_text(str(item))]
                if len(matches) != 1:
                    raise InvalidHumanAnswer("Choose an unambiguous option shown for this question.")
        return Answer(value=value, source=AnswerSource.HUMAN, confidence=1,
                      requires_review=False, reason="Explicit answer supplied through the local control panel")
