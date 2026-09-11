from pathlib import Path
import re
from playwright.async_api import expect, TimeoutError as PlaywrightTimeoutError
from app.ats.generic import GenericATSAdapter
from app.domain.field import Field, Option
from app.services.question_normalizer import normalized_text
from app.workers.browser_worker import UnsafeInteraction

SCAN = Path(__file__).with_name('scan.js').read_text()


class WorkdayATSAdapter(GenericATSAdapter):
    async def ensure_education_record(self):
        """Create exactly one education card; never duplicate or delete an existing card."""
        section = self.worker.page.get_by_role('group', name='Education', exact=True)
        if await section.count() != 1:
            return 'The Education section is missing or ambiguous; add the Ann Arbor record manually.'
        cards = section.get_by_role('group', name=re.compile(r'^Education\s+\d+$'))
        count = await cards.count()
        if count > 1:
            return 'Workday has multiple education records; this profile supports only the Ann Arbor record.'
        if count == 0:
            add = section.get_by_role('button', name=re.compile(r'^Add(?: Another)?$'))
            if await add.count() != 1:
                return 'No unambiguous Education Add button was found; add the Ann Arbor record manually.'
            await add.click()
            try:
                await expect(cards).to_have_count(1, timeout=self.worker.settings.browser_timeout_ms)
            except (AssertionError, PlaywrightTimeoutError):
                return 'Workday did not add the education record. Inspect the page before retrying.'
        return None

    async def ensure_work_experience_records(self, records):
        """Add only missing cards inside Work Experience; never delete existing cards."""
        if await self.is_review_page():
            return 'Work experience cannot be added from the final review page.'
        section = self.worker.page.get_by_role('group', name='Work Experience', exact=True)
        if await section.count() != 1:
            return 'The Work Experience section is missing or ambiguous; this layout needs manual handling.'
        cards = section.get_by_role('group', name=re.compile(r'^Work Experience\s+\d+$'))
        current = await cards.count()
        if current > len(records):
            return 'Workday has more work records than the required five profile records; review manually; none were deleted.'
        # Refuse to reorder or overwrite a different pre-existing employer/position.
        for i in range(current):
            for label, expected in [('Company', records[i].company), ('Job Title', records[i].job_title)]:
                control = cards.nth(i).get_by_label(re.compile(r'^' + label + r'\s*\*?$'))
                if await control.count() != 1:
                    return 'An existing work card has an unsupported layout; check its company and job title.'
                value = await control.input_value()
                if value.strip() and normalized_text(value) != normalized_text(expected):
                    return f'Work Experience {i + 1} differs from the shared profile order. Review it manually before continuing.'
            for date_kind, prefix in (('startDate', 'start'), ('endDate', 'end')):
                for component in ('Month', 'Year'):
                    date = cards.nth(i).locator(f'[data-automation-id="formField-{date_kind}"] [data-automation-id="dateSection{component}-input"]')
                    if await date.count() == 1:
                        value = (await date.input_value()).strip()
                        expected = getattr(records[i], prefix + '_' + component.lower())
                        if value and expected is not None and (not value.isdecimal() or int(value) != expected):
                            return f'Work Experience {i + 1} has a different {prefix} date; verify the record order before continuing.'
                        if value and expected is None:
                            return f'Work Experience {i + 1} contains an unexpected {prefix} date; review it manually before continuing.'
            current_box = cards.nth(i).get_by_label(re.compile(r'^I currently work here\s*\*?$'))
            if await current_box.count() == 1 and records[i].current is False and await current_box.is_checked():
                return f'Work Experience {i + 1} is marked current but the profile record is closed; review it manually before continuing.'
        for before in range(current, len(records)):
            add = section.get_by_role('button', name=re.compile(r'^Add(?: Another)?$'))
            if await add.count() != 1:
                return 'No unambiguous Add button inside Work Experience. Add the missing records manually.'
            await add.click()
            try:
                await expect(cards).to_have_count(before + 1, timeout=self.worker.settings.browser_timeout_ms)
            except (AssertionError, PlaywrightTimeoutError):
                return 'Workday did not add exactly one work record. Inspect the page before retrying.'
        return None

    async def scan_fields(self):
        fields = {f.id: f for f in await super().scan_fields()}
        for meta in await self.worker.page.evaluate(SCAN):
            if meta.get('field'):
                fields[meta['id']] = Field.model_validate(meta['field'])
            if meta['id'] in fields:
                f = fields[meta['id']]
                f.question = meta['question']
                f.required = meta['required']
                f.section = meta['section']
                f.name = meta['name']
                f.locator.date_component = meta.get('date_component', '')
                f.locator.phone_country_code = meta['phone_country_code']
                # Same URL is used by every wizard step. Keep evidence separated.
                f.page_url = self.worker.page.url.split('#')[0] + '#' + meta['stage']
        # Workday's Skills widget is intentionally out of scope for v1. It is
        # not a required application fact and must never be populated from a
        # guessed or parsed resume value.
        return [f for f in fields.values()
                if normalized_text(f.section) != 'skills'
                and normalized_text(f.question) not in {'skills', 'type to add skills'}]

    async def open_control(self, field):
        if not field.locator.control_kind: return await super().open_control(field)
        await self.worker.locate(field).click()

    async def search_options(self, field, target):
        if field.locator.control_kind != 'workday-prompt': return await super().search_options(field, target)
        await self.worker.locate(field).fill(target)
        # Confirmed Workday source-search interaction only; not ordinary form inputs.
        if normalized_text(field.question) == 'how did you hear about us':
            if await self.worker.locate(field).get_attribute('enterkeyhint') != 'search':
                raise UnsafeInteraction('Source input no longer identifies itself as a search control')
            await self.worker.locate(field).press('Enter')
        await self.worker.settle()

    async def _selected_labels(self, field):
        return await self.worker.locate(field).evaluate('''e=>Array.from(e.closest('[data-automation-id^="formField-"]')?.querySelectorAll('[data-automation-id="selectedItem"] [data-automation-id="promptOption"]')||[]).map(x=>x.innerText.trim())''')

    def _options(self):
        return self.worker.page.locator('[role="option"]:visible').filter(
            visible=True).locator('xpath=self::*[not(ancestor-or-self::*[@data-automation-id="selectedItemList"])]')

    async def visible_options(self, field):
        if not field.locator.control_kind: return await super().visible_options(field)
        if normalized_text(field.question) == 'how did you hear about us':
            selected = await self._selected_labels(field)
            if selected: return [Option(label=x, value=x) for x in selected]
        candidates = self._options()
        await candidates.first.wait_for(state='visible', timeout=self.worker.settings.browser_timeout_ms)
        records = await candidates.evaluate_all('''es => es.filter(e=>e.getAttribute('aria-disabled')!=='true').map(e=>{
            window.__applyPilotSeq ??= 0; e.dataset.applypilotToken ||= 'ap-'+(++window.__applyPilotSeq);
            return {label:(e.innerText||'').trim(),value:e.dataset.applypilotToken};
        })''')
        return [Option(**r) for r in records if r['label'] and normalized_text(r['label']) != 'select one']

    async def close_control(self, field):
        if not field.locator.control_kind: return await super().close_control(field)
        loc = self.worker.locate(field)
        if field.locator.control_kind == 'workday-prompt': await loc.fill('')
        await loc.press('Escape')
        await loc.press('Tab')

    async def fill_field(self, field, value, option=None):
        if not field.locator.control_kind: return await super().fill_field(field, value, option)
        if not option or isinstance(option, list): raise UnsafeInteraction('Workday requires one explicit option')
        if field.locator.control_kind == 'workday-prompt':
            if await self._selected_labels(field) == [option.label]: return
        await self.open_control(field)
        try:
            if field.locator.searchable: await self.search_options(field, option.label)
            await self.visible_options(field)
            matches = self._options().filter(has_text=option.label)
            exact = [matches.nth(i) for i in range(await matches.count())
                     if normalized_text(await matches.nth(i).inner_text()) == normalized_text(option.label)]
            if len(exact) != 1: raise UnsafeInteraction('Workday option is missing or ambiguous')
            await self.worker._control_safe(exact[0])
            await exact[0].click()
            await self.worker.settle()
        finally:
            await self.close_control(field)

    async def is_review_page(self):
        # Wizard progress text always includes Review; only the active heading counts.
        headings = await self.worker.page.locator('h2:visible,h3:visible,[role=heading]:visible').all_inner_texts()
        return any(normalized_text(h) in {'review', 'review your application', 'review and submit'} for h in headings)

    async def get_validation_errors(self):
        errors = await super().get_validation_errors()
        errors += await self.worker.page.locator('[data-automation-id="errorMessage"]:visible').all_inner_texts()
        return list(dict.fromkeys(x.strip() for x in errors if x.strip()))

    async def next_page(self, control):
        if await self.is_review_page(): raise UnsafeInteraction('Workday review is the final stopping point')
        await super().next_page(control)
