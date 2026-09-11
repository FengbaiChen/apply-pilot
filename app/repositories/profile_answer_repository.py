import os
from pathlib import Path
import tempfile

import yaml

from app.config.profile import Profile, SavedAnswer
from app.services.question_normalizer import normalized_text


class ProfileSaveError(RuntimeError):
    pass


def saved_answer_key(answer: SavedAnswer):
    return (normalized_text(answer.question), answer.field_type,
            normalized_text(answer.section), tuple(sorted(normalized_text(x) for x in answer.option_labels)),
            answer.application_url)


class ProfileAnswerRepository:
    """Persist explicit panel replies as one atomic profile update, before resuming."""

    def __init__(self, profile: Profile, path: Path | None = None):
        self.profile = profile
        self.path = path.expanduser().resolve() if path is not None else None
        self.inherited_answers = []
        self.new_file_defaults = None

    def save(self, entries: list[SavedAnswer]):
        temporary = None
        try:
            # Read the latest file so unrelated edits/unknown config keys survive.
            raw = (yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}) if self.path and self.path.exists() else (self.new_file_defaults.copy() if self.new_file_defaults is not None else self.profile.model_dump(mode="json", exclude={"work_experience"}))
            current = Profile.model_validate(raw)
            # Persist the merged single-profile shape even when an older file
            # still contains the compatibility `work_experience` key.
            raw.pop("work_experience", None)
            if not raw.get("work_experiences"):
                raw["work_experiences"] = [x.model_dump(mode="json") for x in current.work_records]
            merged = {saved_answer_key(a): a for a in current.saved_answers}
            batch = {}
            for entry in entries:
                key = saved_answer_key(entry)
                if key in batch and batch[key].value != entry.value:
                    raise ValueError("Conflicting replies to indistinguishable questions")
                batch[key] = entry
            merged.update(batch)
            saved = list(merged.values())
            raw["saved_answers"] = [a.model_dump(mode="json") for a in saved]
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                                 prefix=".profile-", suffix=".tmp", delete=False) as handle:
                    temporary = Path(handle.name)
                    yaml.safe_dump(raw, handle, allow_unicode=True, sort_keys=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            # Do not publish a cache entry if persistence failed.
            self.profile.saved_answers = self.inherited_answers + saved
        except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
            raise ProfileSaveError("Could not save answers to the profile. Check file permissions, valid YAML, and conflicting replies, then retry. The application remains paused.") from exc
        finally:
            if temporary and temporary.exists():
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
