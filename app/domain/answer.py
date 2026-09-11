from pydantic import BaseModel, Field
from app.domain.enums import AnswerSource

class Answer(BaseModel):
    value: str | list[str] | bool | None = None
    source: AnswerSource = AnswerSource.UNKNOWN
    confidence: float = Field(default=0.0, ge=0, le=1)
    requires_review: bool = True
    reason: str = "No trusted answer is available."
    bank_id: int | None = None
    model: str | None = None
    basis: str | None = None
    # True means the answer was generated without a directly configured fact.
    # It is intentionally separate from `requires_review` for audit consumers.
    inferred: bool = False
