from urllib.parse import urlsplit
import re
from app.services.application_service import ApplicationService
from app.services.question_normalizer import normalized_text
from .steps import BY_HEADING


class WorkdayApplicationService(ApplicationService):
    """Workday entry, authentication pause, resume upload and guarded wizard flow."""

    async def prepare_page(self):
        p = self.worker.page
        for _ in range(5):
            if await self.adapter.security_challenge():
                self._pause('Finish signing in or the security check in the Workday browser, then Resume.')
                return False
            if (await p.locator('[data-automation-id="SignInWithEmailButton"]').count()
                    or await p.locator('[data-automation-id="utilityButtonSignIn"]').count()):
                self._pause('Sign in to Workday in the browser, then Resume. Credentials are not stored in profiles.')
                return False
            if not self.job_context_extracted:
                try:
                    title = await p.title()
                    body = (await p.locator('body').inner_text())[:12000]
                    body = re.sub(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b', '[redacted email]', body)
                    body = re.sub(r'(?<!\d)(?:\+?\d[\d ()-]{8,}\d)(?!\d)', '[redacted phone]', body)
                    title_parts = re.split(r'\s+[|–—-]\s+', title.strip(), maxsplit=1)
                    self.session.job_title = title_parts[0] or None
                    self.session.company = title_parts[1] if len(title_parts) == 2 else None
                    self.session.job_description = body
                    extracted = f"Job page title: {title}\nJob page URL: {p.url}\nJob page text:\n{body}"
                    if self.session.application_context:
                        extracted += "\n\nUser-provided additional context:\n" + self.session.application_context
                    self.session.application_context = extracted
                    self.job_context_extracted = True
                    self.repository.save(self.session)
                except Exception:
                    # Context extraction is useful for writing only; it must not
                    # prevent deterministic form filling when a page is unusual.
                    pass
            entry = p.locator('[data-automation-id="adventureButton"]')
            if await entry.count() == 1 and await entry.is_visible():
                href = await entry.get_attribute('href') or ''
                source, target = urlsplit(p.url), urlsplit(href)
                if target.netloc != source.netloc or not target.path.endswith('/apply'):
                    self._pause('Unrecognized Workday application entry; open the application manually, then Resume.')
                    return False
                await entry.click()
                await p.get_by_role('button', name='Apply Manually', exact=True).wait_for()
            manual = p.get_by_role('button', name='Apply Manually', exact=True)
            if await manual.count() and await manual.is_visible():
                # Deterministic profile filling avoids trusting unreviewed resume parsing.
                await manual.click()
                await p.locator('h2').first.wait_for()
                await self.worker.settle(autofill=True)
                continue
            text = await p.locator('body').inner_text()
            if 'Something went wrong' in text and 'Please refresh the page' in text:
                self._pause('Workday returned a page error. Refresh the browser, then Resume.')
                return False
            headings = [normalized_text(h) for h in await p.locator('h2:visible,h3:visible,[role=heading]:visible').all_inner_texts()]
            steps = [BY_HEADING[h] for h in headings if h in BY_HEADING]
            if len(steps) != 1:
                self._pause('Unrecognized Workday step. Check the page in the browser, then Resume; this layout needs a step strategy.')
                return False
            step = steps[0]
            self.session.current_step = step.key
            self.answers.step_key = step.key
            self._update(action=f'Workday: {step.heading}')
            blocker = await step.prepare(self)
            if blocker:
                self._pause(blocker)
                return False
            return True
        self._pause('Workday is still loading. Check the browser, then Resume.')
        return False
