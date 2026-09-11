from datetime import datetime, timezone
from uuid import uuid4
from pydantic import BaseModel, Field
from app.domain.enums import ApplicationState
from app.domain.review import ReviewReport
from app.domain.human_question import HumanQuestion

class ApplicationSession(BaseModel):
    application_id: str = Field(default_factory=lambda: "app_" + uuid4().hex)
    url: str
    status: ApplicationState = ApplicationState.STARTING
    current_action: str = "Starting browser"
    human_message: str | None = None
    platform: str = "workday"
    company: str | None = None
    job_title: str | None = None
    job_description: str | None = None
    current_step: str | None = None
    pages_processed: int = 0
    review: ReviewReport | None = None
    pending_questions: list[HumanQuestion] = Field(default_factory=list)
    reference_prompt: str = ""
    application_context: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
