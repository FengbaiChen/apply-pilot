from enum import StrEnum

class ApplicationState(StrEnum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    STOPPED = "STOPPED"
    FAILED = "FAILED"

class FieldType(StrEnum):
    TEXT = "text"
    TEXTAREA = "textarea"
    RADIO = "radio"
    CHECKBOX = "checkbox"
    SELECT = "select"
    AUTOCOMPLETE = "autocomplete"
    DATE = "date"
    FILE = "file"
    MULTISELECT = "multiselect"
    UNKNOWN = "unknown"

class AnswerSource(StrEnum):
    PROFILE = "PROFILE"
    PROFILE_CACHE = "PROFILE_CACHE"
    RULE = "RULE"
    ANSWER_BANK = "ANSWER_BANK"
    LLM = "LLM"
    HUMAN = "HUMAN"
    UNKNOWN = "UNKNOWN"

class CanonicalQuestion(StrEnum):
    AUTHORIZED_TO_WORK = "AUTHORIZED_TO_WORK"
    REQUIRES_SPONSORSHIP = "REQUIRES_SPONSORSHIP"
    WILLING_TO_RELOCATE = "WILLING_TO_RELOCATE"
    SCHOOL = "SCHOOL"
    MAJOR = "MAJOR"
    DEGREE = "DEGREE"
    GRADUATION_DATE = "GRADUATION_DATE"
    UNKNOWN = "UNKNOWN"

class ConfidenceAction(StrEnum):
    AUTO_FILL = "AUTO_FILL"
    FILL_AND_REVIEW = "FILL_AND_REVIEW"
    REQUIRE_HUMAN = "REQUIRE_HUMAN"

class InspectionStatus(StrEnum):
    PASSIVE = "PASSIVE"
    INSPECTED = "INSPECTED"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"

class Severity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"

class NavigationKind(StrEnum):
    NEXT = "NEXT"
    FINAL_SUBMIT = "FINAL_SUBMIT"
    UNKNOWN = "UNKNOWN"
