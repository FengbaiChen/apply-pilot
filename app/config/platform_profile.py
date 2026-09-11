from pathlib import Path
import yaml
from pydantic import BaseModel, Field
from app.config.profile import SavedAnswer, Profile


class PlatformProfile(BaseModel):
    question_aliases: dict[str, str] = Field(default_factory=dict)
    value_aliases: dict[str, list[str]] = Field(default_factory=dict)
    facts: dict[str, str | bool | list[str]] = Field(default_factory=dict)
    saved_answers: list[SavedAnswer] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path):
        return cls.model_validate(yaml.safe_load(path.read_text()) or {}) if path.exists() else cls()


def load_profiles(shared_path: Path, platform_path: Path):
    shared = Profile.load(shared_path)
    platform = PlatformProfile.load(platform_path)
    effective = shared.model_copy(deep=True)
    effective.facts.update(platform.facts)
    effective.saved_answers += platform.saved_answers
    return shared, platform, effective
