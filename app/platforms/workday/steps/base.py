from app.domain.answer import Answer


class WorkdayStep:
    key = ''
    heading = ''

    async def prepare(self, service) -> str | None:
        """Return a human-facing blocker, or None to run shared inspect/fill/verify."""
        return None

    def answer(self, field, profile) -> Answer | None:
        """Only explicit step-specific facts belong here; None delegates to shared rules."""
        return None
