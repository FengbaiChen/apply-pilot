import os
from pathlib import Path
import yaml
from pydantic import BaseModel, Field

class Settings(BaseModel):
    browser_profile_dir: Path = Path("data/browser-profile")
    browser_headless: bool = False
    browser_timeout_ms: int = Field(default=10000, ge=100)
    autofill_wait_ms: int = Field(default=2500, ge=0, le=30000)
    settle_timeout_ms: int = Field(default=8000, ge=100)
    database_path: Path = Path("data/applypilot.sqlite3")
    max_pages: int = Field(default=25, ge=1, le=100)
    max_option_iterations: int = Field(default=20, ge=1, le=100)
    option_stale_limit: int = Field(default=3, ge=1)
    llm_enabled: bool = False
    llm_prompt_path: Path | None = None

    @classmethod
    def load(cls):
        path = Path(os.getenv("APPLY_PILOT_SETTINGS", "config/settings.yaml"))
        return cls.model_validate(yaml.safe_load(path.read_text()) or {}) if path.exists() else cls()
