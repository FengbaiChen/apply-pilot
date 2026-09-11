from pydantic import BaseModel, Field as ModelField
from app.domain.enums import FieldType, InspectionStatus

class Option(BaseModel):
    label: str
    value: str

class LocatorMetadata(BaseModel):
    # Ephemeral handles assigned to live elements, never generated employer IDs.
    token: str = ""
    option_tokens: dict[str, str] = ModelField(default_factory=dict)
    searchable: bool = False
    virtualized: bool = False
    input_type: str = ""
    read_only: bool = False
    control_kind: str = ""
    phone_country_code: str = ""
    date_component: str = ""

class Field(BaseModel):
    id: str
    name: str = ""
    label: str = ""
    question: str
    field_type: FieldType = FieldType.TEXT
    required: bool = False
    current_value: str | list[str] | bool | None = None
    attachment_hashes: dict[str, str] = ModelField(default_factory=dict)
    options: list[Option] = ModelField(default_factory=list)
    locator: LocatorMetadata = ModelField(default_factory=LocatorMetadata)
    section: str = ""
    visible: bool = True
    enabled: bool = True
    confidence: float = 1.0
    inspection_status: InspectionStatus = InspectionStatus.PASSIVE
    validation_message: str = ""
    page_url: str = ""

    @property
    def key(self) -> str:
        return f"{self.page_url}|{self.section}|{self.name or self.question}"
