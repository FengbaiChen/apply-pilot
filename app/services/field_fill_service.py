from app.domain.enums import FieldType as T, InspectionStatus as I
from app.services.question_normalizer import normalized_text

class FieldFillService:
    def __init__(self, answers, confidence=None): self.answers, self.confidence = answers, confidence

    async def fill(self, field, answer, adapter) -> bool:
        if answer.value is None:
            return False
        if self.answers.matches(field, answer): return True
        if not field.enabled or field.locator.read_only or field.inspection_status == I.HUMAN_REQUIRED: return False
        options = None
        if field.field_type in {T.SELECT, T.AUTOCOMPLETE, T.RADIO, T.MULTISELECT}:
            if field.field_type == T.MULTISELECT and isinstance(answer.value, list):
                selected = []
                for value in answer.value:
                    matches = [x for x in field.options if normalized_text(x.label) == normalized_text(value)]
                    if len(matches) != 1: return False
                    selected.append(matches[0])
                await adapter.fill_field(field, answer.value, selected)
                return True
            labels = {normalized_text(x) for x in self.answers.acceptable_labels(field, answer)}
            options = [x for x in field.options if normalized_text(x.label) in labels]
            # Duplicate labels with different values are ambiguous; never take the first.
            if len(options) != 1: return False
        await adapter.fill_field(field, answer.value, options[0] if options else None)
        return True
