from uuid import uuid4
from pydantic import BaseModel, Field
from app.domain.enums import FieldType
from app.domain.field import Option


class HumanQuestion(BaseModel):
    question_id: str = Field(default_factory=lambda: "q_" + uuid4().hex)
    question: str
    field_type: FieldType
    required: bool
    current_value: str | list[str] | bool | None = None
    options: list[Option] = Field(default_factory=list)
    reason: str


class HumanResponse(BaseModel):
    question_id: str
    value: str | list[str] | bool
