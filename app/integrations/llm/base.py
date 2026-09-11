from typing import Protocol

class LLMClient(Protocol):
    async def generate(self, question: str, facts: dict, reference_prompt: str = "",
                       application_context: str = "") -> str: ...
