from pathlib import Path
from app.domain.field import Field

SCAN_SCRIPT = Path(__file__).with_name("scan.js").read_text()

class PageScanner:
    async def scan(self, page) -> list[Field]:
        return [Field.model_validate(item) for item in await page.evaluate(SCAN_SCRIPT)]
