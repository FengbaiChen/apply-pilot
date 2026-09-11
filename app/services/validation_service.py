from app.domain.enums import Severity as S, AnswerSource, FieldType
from app.domain.review import ReviewFinding

def is_blank(field) -> bool:
    value = field.current_value
    return value is None or value == [] or (isinstance(value, str) and not value.strip()) or (field.field_type == FieldType.CHECKBOX and value is False)

class ValidationService:
    def __init__(self, answers, confidence=None): self.answers, self.confidence = answers, confidence

    def validate(self, fields, resolved=None, errors=()):
        resolved = resolved or {}
        findings = []
        for f in fields:
            def add(severity, message):
                findings.append(ReviewFinding(severity=severity, message=message, field_id=f.id, question=f.question))
            if f.required and is_blank(f): add(S.ERROR, "Required field is blank.")
            if f.validation_message: add(S.ERROR, f.validation_message)
            # Review pages expose read-only summaries, not editable controls.
            # They are evidence for the audit and must not become new blockers.
            if f.locator.read_only:
                continue
            if f.required and f.field_type == FieldType.UNKNOWN: add(S.ERROR, "Unsupported required control.")
            a = resolved.get(f.key) or self.answers.deterministic(f)
            if a is None or a.value is None:
                if f.required or not is_blank(f): add(S.ERROR, "Value has not been verified; human confirmation is required.")
                continue
            if not self.answers.matches(f, a): add(S.ERROR, "Current value does not match the trusted answer/profile.")
            elif not is_blank(f): add(S.INFO, f"Verified value from {a.source.value}.")
            if a.source == AnswerSource.LLM: add(S.WARNING, "LLM-generated answer: verify all claims before submission.")
            elif a.requires_review:
                add(S.WARNING, "Medium-confidence or review-required answer needs manual review.")
        findings.extend(ReviewFinding(severity=S.ERROR, message=e) for e in errors)
        return findings

    @staticmethod
    def can_navigate(findings): return not any(f.severity == S.ERROR for f in findings)
