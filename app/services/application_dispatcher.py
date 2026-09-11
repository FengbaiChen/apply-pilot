import asyncio
from app.services.application_service import SessionConflict


class ApplicationDispatcher:
    """One public API and one browser lease across all platform services."""

    def __init__(self, repository, factory, capabilities):
        self.repository, self.factory = repository, factory
        self._capabilities = capabilities
        self.active = None
        self.lock = asyncio.Lock()

    async def start(self, url, reference_prompt="", application_context="", platform="workday"):
        async with self.lock:
            if self.active and self.active.worker is not None:
                raise SessionConflict("Stop and close the current browser before starting another application.")
            if platform != "workday":
                raise SessionConflict("Only Workday applications are supported.")
            self.active = self.factory(platform)
            return await self.active.start(url, reference_prompt, application_context, platform=platform)

    def get(self, application_id):
        result = self.repository.get(application_id)
        if result is None: raise KeyError(application_id)
        return result

    def _owner(self, application_id):
        self.get(application_id)
        if not self.active or not self.active.session or self.active.session.application_id != application_id:
            raise SessionConflict("This application has no attached browser. Start a new application.")
        return self.active

    async def submit_answers(self, application_id, responses):
        return await self._owner(application_id).submit_answers(application_id, responses)

    async def resume(self, application_id, confirm_current_values=False):
        return await self._owner(application_id).resume(application_id, confirm_current_values)

    async def stop(self, application_id):
        return await self._owner(application_id).stop(application_id)

    async def approve_review(self, application_id, edits):
        return await self._owner(application_id).approve_review(application_id, edits)

    async def shutdown(self):
        if self.active: await self.active.shutdown()

    def capabilities(self):
        return {**self._capabilities, "platforms": ["workday"]}
