from abc import ABC, abstractmethod

class BaseATSAdapter(ABC):
    """DOM mechanics only. Answers, matching, confidence and audit belong to services."""
    def __init__(self, worker): self.worker = worker
    @abstractmethod
    async def scan_fields(self): ...
    @abstractmethod
    async def get_validation_errors(self): ...
    @abstractmethod
    async def navigation_controls(self): ...
    @abstractmethod
    async def is_review_page(self): ...
    @abstractmethod
    async def next_page(self, control): ...
    @abstractmethod
    async def fill_field(self, field, value, option=None): ...

    async def open_control(self, field): await self.worker.open_control(field)
    async def search_options(self, field, target): await self.worker.search_options(field, target)
    async def visible_options(self, field): return await self.worker.visible_options(field)
    async def scroll_options(self, field): return await self.worker.scroll_options(field)
    async def close_control(self, field): await self.worker.close_control(field)
    async def security_challenge(self): return await self.worker.security_challenge()
