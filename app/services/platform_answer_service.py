from app.services.answer_service import AnswerService
from app.domain.answer import Answer
from app.domain.enums import AnswerSource, FieldType
from app.services.question_normalizer import normalized_text


class PlatformAnswerService(AnswerService):
    """Legacy import compatibility for external integrations; unused by Workday."""
    def __init__(self, *args, platform_profile=None, shared_profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.platform_profile = platform_profile
        if shared_profile is not None:
            self.profile_answers.inherited_answers = shared_profile.saved_answers
        self.bindings = {normalized_text(k): v for k, v in (platform_profile.question_aliases.items() if platform_profile else [])}

    def deterministic(self, field):
        path = self.bindings.get(normalized_text(field.question))
        if path:
            value = self.profile.model_dump()
            for part in path.removeprefix("shared.").split("."):
                value = value.get(part) if isinstance(value, dict) else None
            if value is not None:
                if isinstance(value, bool) and field.field_type != FieldType.CHECKBOX:
                    value = "Yes" if value else "No"
                return Answer(value=value, source=AnswerSource.PROFILE, confidence=1, requires_review=False,
                              reason=f"Explicit platform mapping to {path}")
        return super().deterministic(field)
