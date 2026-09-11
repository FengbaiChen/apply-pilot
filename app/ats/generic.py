import re
from app.ats.base import BaseATSAdapter
from app.browser.scanner import PageScanner
from app.services.navigation_service import NavigationService
from app.domain.enums import NavigationKind

class GenericATSAdapter(BaseATSAdapter):
    async def scan_fields(self): return await PageScanner().scan(self.worker.page)

    async def get_validation_errors(self):
        return [x.strip() for x in await self.worker.page.locator(
            '[role="alert"]:visible,[aria-live="assertive"]:visible,.field-error:visible,.validation-error:visible').all_inner_texts() if x.strip()]

    async def navigation_controls(self): return await self.worker.navigation_controls()

    async def find_submit_controls(self):
        return [c for c in await self.navigation_controls() if NavigationService.classify(c['label']) == NavigationKind.FINAL_SUBMIT]

    async def is_review_page(self):
        headings = await self.worker.page.locator('h1:visible,h2:visible,[role="heading"]:visible').all_inner_texts()
        explicit = any(re.fullmatch(r'(review( your)?( application)?|application review|review and submit)', h.strip(), re.I) for h in headings)
        controls = await self.navigation_controls()
        finals = [c for c in controls if NavigationService.classify(c['label']) == NavigationKind.FINAL_SUBMIT]
        # A submit button may coexist with earlier wizard controls; do not advance in that case.
        return explicit or bool(finals)

    async def next_page(self, control): await self.worker.guarded_next(control)
    async def fill_field(self, field, value, option=None): await self.worker.fill(field, value, option)
