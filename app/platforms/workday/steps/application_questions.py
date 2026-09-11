from .base import WorkdayStep


class ApplicationQuestionsStep(WorkdayStep):
    key = 'application_questions'
    heading = 'Application Questions'
    # Shared facts and explicit Workday aliases answer factual questions. Recognized
    # prose uses the existing optional LLM pipeline. Everything else pauses for a human.
