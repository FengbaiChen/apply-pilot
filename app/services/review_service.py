from app.domain.enums import Severity
from app.domain.review import ReviewReport, ReviewFinding, ReviewAnswer
from app.services.answer_service import PERSONAL_KEYS
from app.services.question_normalizer import normalized_text

class ReviewService:
    def __init__(self, validation): self.validation = validation

    def audit(self, fields, answers=None, errors=(), prior_page_count=0):
        findings = self.validation.validate(fields, answers, errors)
        categories = {"name": False, "email": False, "phone": False, "school": False, "major": False,
                      "degree": False, "graduation": False, "work authorization": False, "sponsorship": False, "resume attachment": False}
        mapping = {"SCHOOL": "school", "MAJOR": "major", "DEGREE": "degree", "GRADUATION_DATE": "graduation",
                   "AUTHORIZED_TO_WORK": "work authorization", "REQUIRES_SPONSORSHIP": "sponsorship"}
        for field in fields:
            canonical = self.validation.answers.normalizer.normalize(field.question).value
            if canonical in mapping: categories[mapping[canonical]] = True
            personal = PERSONAL_KEYS.get(normalized_text(field.question), "")
            if "name" in personal: categories["name"] = True
            if personal in {"email", "phone"}: categories[personal] = True
            if field.field_type.value == "file": categories["resume attachment"] = True
        for category, observed in categories.items():
            if not observed: findings.append(ReviewFinding(severity=Severity.WARNING,
                message=f"{category.capitalize()} was not exposed by the application; verify manually."))
        if prior_page_count:
            findings.append(ReviewFinding(severity=Severity.WARNING,
                message="Some evidence was captured on earlier steps; compare it with the employer's final summary."))
        if not fields:
            findings.append(ReviewFinding(severity=Severity.ERROR, message="No application field evidence is available to audit."))
        answer_items = []
        for field in fields:
            answer = (answers or {}).get(field.key)
            if answer is None:
                continue
            answer_items.append(ReviewAnswer(field_id=field.id, question=field.question,
                value=answer.value, field_type=field.field_type.value,
                option_labels=[o.label for o in field.options],
                source=answer.source.value, reason=answer.reason,
                requires_review=answer.requires_review, model=answer.model, basis=answer.basis,
                inferred=answer.inferred))
        return ReviewReport(ready=self.validation.can_navigate(findings), findings=findings,
                            audited_fields=len(fields), answers=answer_items)
