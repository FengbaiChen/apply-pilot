import re
from app.domain.enums import NavigationKind as N
from app.services.question_normalizer import normalized_text

class NavigationService:
    @staticmethod
    def classify(label: str) -> N:
        text = normalized_text(label)
        if re.search(r"\b(submit|send|complete|finish|apply|accept|confirm|pay)\b", text):
            return N.FINAL_SUBMIT
        if re.fullmatch(r"(next|next step|continue|save (and|&) continue|review|review application)(\s*[→›»])?", text):
            return N.NEXT
        return N.UNKNOWN

    async def advance(self, adapter) -> bool:
        controls = await adapter.navigation_controls()
        if await adapter.is_review_page(): return False
        safe = [c for c in controls if self.classify(c["label"]) == N.NEXT]
        if len(safe) != 1: return False
        await adapter.next_page(safe[0])
        return True
