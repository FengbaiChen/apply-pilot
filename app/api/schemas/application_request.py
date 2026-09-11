from pydantic import BaseModel, Field, HttpUrl, field_validator
from app.domain.human_question import HumanResponse
from typing import Literal

class ApplicationRequest(BaseModel):
    url: HttpUrl
    reference_prompt: str = Field(default="", max_length=8000)
    application_context: str = Field(default="", max_length=16000)
    platform: Literal["workday"]

    @field_validator("url")
    @classmethod
    def no_credentials(cls, value):
        if value.username or value.password: raise ValueError("URL must not contain credentials")
        return value

class ResumeRequest(BaseModel):
    confirm_current_values: bool = False


class HumanAnswersRequest(BaseModel):
    answers: list[HumanResponse] = Field(min_length=1, max_length=100)


class ReviewEdit(BaseModel):
    field_id: str
    value: str | list[str] | bool


class ReviewApprovalRequest(BaseModel):
    answers: list[ReviewEdit] = Field(default_factory=list, max_length=200)
