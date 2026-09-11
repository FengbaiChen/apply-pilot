from collections.abc import Awaitable, Callable
from app.domain.field import Option

class OptionCollector:
    def __init__(self, max_iterations: int = 20, stale_limit: int = 3):
        if max_iterations < 1 or stale_limit < 1: raise ValueError("Limits must be positive")
        self.max_iterations, self.stale_limit = max_iterations, stale_limit

    async def collect(self, read: Callable[[], Awaitable[list[Option]]], scroll: Callable[[], Awaitable[bool]]) -> list[Option]:
        seen: dict[tuple[str, str], Option] = {}
        stale = 0
        for _ in range(self.max_iterations):
            before = len(seen)
            for option in await read(): seen.setdefault((option.label, option.value), option)
            stale = stale + 1 if len(seen) == before else 0
            if stale >= self.stale_limit or not await scroll(): break
        return list(seen.values())
