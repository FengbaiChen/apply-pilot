from pydantic import BaseModel
from app.domain.enums import ApplicationState

class ApplicationResponse(BaseModel):
    application_id: str
    status: ApplicationState
    platform: str = "workday"
    current_step: str | None = None
