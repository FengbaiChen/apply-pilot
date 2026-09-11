from pathlib import Path
from pydantic import BaseModel, Field, model_validator
import yaml
from app.domain.enums import FieldType


class SavedAnswer(BaseModel):
    question: str
    field_type: FieldType
    value: str | list[str] | bool
    section: str = ""
    option_labels: list[str] = Field(default_factory=list)
    application_url: str = ""

class Personal(BaseModel):
    full_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    preferred_name: str | None = None
    email: str | None = None
    phone: str | None = None
    phone_country_code: str | None = None
    address_line1: str | None = None
    postal_code: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    linkedin: str | None = None


class Phone(BaseModel):
    # These are deliberately unset by default: Workday must use the values
    # explicitly configured by the applicant rather than guessing from digits.
    device_type: str | None = None
    country_code: str | None = None
    number: str | None = None

class WorkAuthorization(BaseModel):
    authorized_to_work_us: bool | None = None
    require_future_sponsorship: bool | None = None

class Preferences(BaseModel):
    willing_to_relocate: bool | None = None


class Demographics(BaseModel):
    gender: str | None = None
    ethnicity: str | None = None
    hispanic_or_latino: str | None = None
    veteran_status: str | None = None
    disability: str | None = None


class Links(BaseModel):
    github: str | None = None
    linkedin: str | None = None

class Education(BaseModel):
    school: str | None = None
    school_aliases: list[str] = Field(default_factory=list)
    unsafe_school_matches: list[str] = Field(default_factory=list)
    degree: str | None = None
    major: str | None = None
    major_aliases: list[str] = Field(default_factory=list)
    graduation_month: int | None = Field(default=None, ge=1, le=12)
    graduation_year: int | None = Field(default=None, ge=1900, le=2200)
    start_month: int | None = Field(default=None, ge=1, le=12)
    start_year: int | None = Field(default=None, ge=1900, le=2200)
    gpa: str | float | None = None

class ApplicationProfile(BaseModel):
    resume_path: str | None = None

class WorkExperience(BaseModel):
    # Nullable in the example template so startup validation can report all
    # missing records in one clear Workday-specific error.
    company: str | None = None
    job_title: str | None = None
    location: str | None = None
    start_year: int | None = Field(default=None, ge=1900, le=2200)
    start_month: int | None = Field(default=None, ge=1, le=12)
    end_year: int | None = Field(default=None, ge=1900, le=2200)
    end_month: int | None = Field(default=None, ge=1, le=12)
    current: bool = False
    description: str | None = None

class Profile(BaseModel):
    personal: Personal = Field(default_factory=Personal)
    work_authorization: WorkAuthorization = Field(default_factory=WorkAuthorization)
    preferences: Preferences = Field(default_factory=Preferences)
    education: Education = Field(default_factory=Education)
    application: ApplicationProfile = Field(default_factory=ApplicationProfile)
    phone: Phone = Field(default_factory=Phone)
    demographics: Demographics = Field(default_factory=Demographics)
    links: Links = Field(default_factory=Links)
    experience_facts: list[str] = Field(default_factory=list)
    saved_answers: list[SavedAnswer] = Field(default_factory=list)
    facts: dict[str, str | bool | list[str]] = Field(default_factory=dict)
    work_experience: list[WorkExperience] = Field(default_factory=list)
    work_experiences: list[WorkExperience] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_shape(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if not data.get("work_experiences") and data.get("work_experience"):
            data["work_experiences"] = data["work_experience"]
        data.pop("work_experience", None)
        # Older profiles stored the phone and LinkedIn URL under personal.
        personal = dict(data.get("personal") or {})
        phone = dict(data.get("phone") or {})
        if personal.get("phone") and not phone.get("number"):
            phone["number"] = personal["phone"]
        if personal.get("phone_country_code") and not phone.get("country_code"):
            phone["country_code"] = personal["phone_country_code"]
        if phone:
            data["phone"] = phone
        links = dict(data.get("links") or {})
        if personal.get("linkedin") and not links.get("linkedin"):
            links["linkedin"] = personal["linkedin"]
        if links:
            data["links"] = links
        return data

    @classmethod
    def load(cls, path: Path) -> "Profile":
        if not path.exists():
            return cls()
        profile = cls.model_validate(yaml.safe_load(path.read_text()) or {})
        if profile.application.resume_path:
            resume = Path(profile.application.resume_path).expanduser()
            profile.application.resume_path = str(resume.resolve())
        return profile

    def prose_facts(self) -> dict:
        # Intentionally omit contact details, authorization, resume path and secrets.
        return {"education": self.education.model_dump(exclude_none=True),
                "work_experiences": [x.model_dump(exclude_none=True) for x in self.work_records],
                "experience_facts": self.experience_facts,
                "links": self.links.model_dump(exclude_none=True)}

    @property
    def work_records(self) -> list[WorkExperience]:
        return self.work_experiences or self.work_experience

    def validate_workday(self) -> None:
        records = self.work_records
        if len(records) != 5:
            raise ValueError("Workday requires exactly five work_experiences in profile.yaml")
        for index, record in enumerate(records, 1):
            required = {"job_title": record.job_title, "company": record.company,
                        "location": record.location,
                        "start_year": record.start_year, "start_month": record.start_month,
                        "description": record.description}
            if any(value in (None, "") for value in required.values()):
                raise ValueError(f"work_experiences[{index}] is missing a required value")
            if "current" not in record.model_fields_set:
                raise ValueError(f"work_experiences[{index}] must explicitly set current: true or false")
            if not record.current and (record.end_year is None or record.end_month is None):
                raise ValueError(f"work_experiences[{index}] needs end_year/end_month or current: true")
            if record.current and (record.end_year is not None or record.end_month is not None):
                raise ValueError(f"work_experiences[{index}] with current: true must not have an end date")
            if (not record.current and (record.start_year, record.start_month)
                    > (record.end_year, record.end_month)):
                raise ValueError(f"work_experiences[{index}] starts after its end date")
        if (not self.education.school or "ann arbor" not in self.education.school.casefold()
                or not self.education.degree or not self.education.major):
            raise ValueError("education must contain the Ann Arbor school, degree and major")
        if any(value is None for value in (self.education.start_month, self.education.start_year,
                                           self.education.graduation_month, self.education.graduation_year)):
            raise ValueError("education must contain start and expected/actual graduation month and year")
        if (self.education.start_year, self.education.start_month) > (self.education.graduation_year,
                                                                       self.education.graduation_month):
            raise ValueError("education starts after its expected/actual graduation date")
