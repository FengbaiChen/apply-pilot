from datetime import datetime, timezone
from pydantic import BaseModel, Field
from app.domain.enums import Severity

class ReviewFinding(BaseModel):
    severity: Severity
    message: str
    field_id: str | None = None
    question: str = ""


class ReviewAnswer(BaseModel):
    field_id: str
    question: str
    value: str | list[str] | bool | None = None
    field_type: str = "text"
    option_labels: list[str] = Field(default_factory=list)
    source: str = "UNKNOWN"
    reason: str = ""
    requires_review: bool = True
    model: str | None = None
    basis: str | None = None
    inferred: bool = False

class ReviewReport(BaseModel):
    ready: bool
    findings: list[ReviewFinding] = Field(default_factory=list)
    audited_fields: int = 0
    answers: list[ReviewAnswer] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
