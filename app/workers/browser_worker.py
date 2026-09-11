import json
from pathlib import Path
from app.browser.manager import BrowserManager
from app.domain.enums import FieldType as T, NavigationKind as N
from app.domain.field import Option
from app.services.navigation_service import NavigationService

class UnsafeInteraction(RuntimeError): pass

class BrowserWorker:
    """Long-lived browser mechanics; no profile access or answer decisions."""
    def __init__(self, settings, manager=None):
        self.settings = settings
        self.manager = manager or BrowserManager(settings)
        self.page = None
        self._original_search = {}

    async def open(self, url):
        self.page = await self.manager.launch()
        await self.page.goto(url, wait_until="domcontentloaded")
        await self.settle(autofill=True)

    async def close(self): await self.manager.close()

    async def settle(self, autofill=False):
        # Bounded quiescence window observes DOM and input values, including extension autofill.
        await self.page.wait_for_load_state("domcontentloaded")
        return await self.page.evaluate("""({minimum,maximum}) => new Promise(resolve => {
            const start=performance.now(); let last=start, previous='';
            const observer=new MutationObserver(() => {last=performance.now()});
            observer.observe(document.documentElement,{childList:true,subtree:true,characterData:true});
            const tick=() => {
                const now=performance.now();
                const values=Array.from(document.querySelectorAll('input,select,textarea')).map(x=>[x.value,x.checked]).toString();
                if(values!==previous){previous=values;last=now;}
                if ((now-start>=minimum && now-last>=250) || now-start>=maximum){observer.disconnect();resolve(now-last>=250);}
                else setTimeout(tick,50);
            }; tick();
        })""", {"minimum": self.settings.autofill_wait_ms if autofill else 250,
                  "maximum": max(self.settings.settle_timeout_ms, self.settings.autofill_wait_ms + 500)})

    def locate(self, field):
        return self.page.locator(f'[data-applypilot-token="{field.locator.token}"]')

    async def _control_safe(self, locator):
        meta = await locator.evaluate("""el => ({labels:[el.getAttribute('aria-label')||'',el.innerText||'',el.value||''],
            type:el.type,tag:el.tagName})""")
        if meta['tag'] in {'BUTTON', 'A'} and (any(NavigationService.classify(label) == N.FINAL_SUBMIT for label in meta['labels']) or meta['type'] == 'submit'):
            raise UnsafeInteraction("Refusing to use a submission-like element as a field control")

    async def open_control(self, field):
        loc = self.locate(field)
        await self._control_safe(loc)
        if await loc.evaluate("el => el.tagName === 'SELECT'"): return
        if field.locator.searchable:
            search = loc if await loc.evaluate("el => el.tagName === 'INPUT'") else loc.locator('input').first
            self._original_search[field.id] = await search.input_value()
        await loc.click()

    async def popup(self, field):
        loc = self.locate(field)
        controls = await loc.get_attribute('aria-controls') or await loc.get_attribute('aria-owns') or await loc.get_attribute('list')
        if controls:
            # Exact ID lookup avoids CSS interpolation of employer-controlled IDs.
            for popup_id in controls.split():
                target = self.page.locator('[id=' + json.dumps(popup_id) + ']')
                if await target.count() and (await target.is_visible() or await target.evaluate("el=>el.tagName==='DATALIST'")):
                    return target
        boxes = self.page.locator('[role="listbox"]:visible')
        await boxes.first.wait_for(state="visible", timeout=self.settings.browser_timeout_ms)
        if await boxes.count() != 1: raise UnsafeInteraction("Multiple unassociated option lists")
        return boxes.first

    async def search_options(self, field, target):
        loc = self.locate(field)
        search = loc if await loc.evaluate("el => el.tagName === 'INPUT'") else loc.locator('input').first
        await search.fill(target)
        popup = await self.popup(field)
        await popup.locator('[role="option"],option').first.wait_for(state="attached")
        await self.settle()

    async def visible_options(self, field):
        popup = await self.popup(field)
        is_datalist = await popup.evaluate("el => el.tagName === 'DATALIST'")
        options = popup.locator('[role="option"],option')
        await options.first.wait_for(state='attached' if is_datalist else 'visible')
        found = []
        for i in range(await options.count()):
            loc = options.nth(i)
            if not is_datalist and not await loc.is_visible(): continue
            if await loc.get_attribute('aria-disabled') == 'true' or await loc.is_disabled(): continue
            label = (await loc.inner_text()).strip() or await loc.get_attribute('label') or await loc.get_attribute('value') or ''
            value = await loc.get_attribute('data-value') or await loc.get_attribute('value') or label
            if label: found.append(Option(label=label, value=value))
        return found

    async def scroll_options(self, field):
        popup = await self.popup(field)
        moved = await popup.evaluate("""el => {
            const old=el.scrollTop; el.scrollTop += Math.max(el.clientHeight-10,1);
            return el.scrollTop>old;
        }""")
        await self.settle()
        return moved

    async def close_control(self, field):
        try:
            loc = self.locate(field)
            if field.id in self._original_search:
                search = loc if await loc.evaluate("el=>el.tagName==='INPUT'") else loc.locator('input').first
                await search.fill(self._original_search.pop(field.id))
            await loc.press('Escape')
        except Exception:
            pass  # A control may disappear while its options are inspected.

    async def fill(self, field, value, option=None):
        loc = self.locate(field)
        if field.field_type == T.FILE:
            path = Path(str(value)).expanduser().resolve()
            if not path.is_file(): raise ValueError("Configured attachment file does not exist")
            if path.stat().st_size > 5 * 1024 * 1024:
                raise ValueError("Configured resume exceeds Workday's 5 MB upload limit")
            await loc.set_input_files(str(path))
        elif field.field_type == T.CHECKBOX:
            if not isinstance(value, bool): raise UnsafeInteraction("Checkbox answer must be boolean")
            await self._control_safe(loc)
            await loc.set_checked(value)
        elif field.field_type == T.RADIO:
            token = field.locator.option_tokens.get(option.value)
            if not token: raise UnsafeInteraction("Radio option is no longer available")
            radio = self.page.locator(f'[data-applypilot-token="{token}"]')
            await self._control_safe(radio)
            await radio.check()
        elif await loc.evaluate("el => el.tagName === 'SELECT'"):
            await loc.select_option(value=[o.value for o in option] if isinstance(option, list) else option.value)
        elif field.field_type in {T.AUTOCOMPLETE, T.MULTISELECT}:
            if isinstance(option, list):
                raise UnsafeInteraction('Custom multiselect requires manual selection')
            await self.open_control(field)
            try:
                if field.locator.searchable: await self.search_options(field, option.label)
                popup = await self.popup(field)
                if await popup.evaluate("el=>el.tagName==='DATALIST'"):
                    await loc.fill(option.value)
                    await loc.press('Tab')
                else:
                    if field.locator.virtualized and not field.locator.searchable:
                        await popup.evaluate('el => { el.scrollTop = 0; }')
                        await self.settle()
                    # Virtual lists may need another bounded traversal to reveal the chosen option.
                    for _ in range(self.settings.max_option_iterations):
                        candidates = popup.get_by_role('option', name=option.label, exact=True)
                        if await candidates.count() == 1 and await candidates.is_visible():
                            await self._control_safe(candidates)
                            await candidates.click(); break
                        if not await self.scroll_options(field): raise UnsafeInteraction("Selected option is no longer visible")
                    else: raise UnsafeInteraction("Option traversal limit reached")
                self._original_search.pop(field.id, None)
            finally:
                await self.close_control(field)
        elif field.field_type in {T.TEXT, T.TEXTAREA, T.DATE}:
            # fill never presses Enter, avoiding implicit form submission.
            await loc.fill(str(value))
            await loc.press('Tab')
        else: raise UnsafeInteraction("Unsupported field control")
        await self.settle()

    async def navigation_controls(self):
        return await self.page.evaluate("""() => Array.from(document.querySelectorAll('button,input[type=submit],input[type=button],a,[role=button]'))
            .filter(el=>el.getClientRects().length && !el.disabled && el.getAttribute('aria-disabled')!=='true')
            .map(el=>{window.__applyPilotSeq ??= 0; el.dataset.applypilotToken ||= 'ap-'+(++window.__applyPilotSeq);
                return {token:el.dataset.applypilotToken,label:el.getAttribute('aria-label')||el.innerText||el.value||'',
                        type:el.type||'',href:el.getAttribute('href')||''};})""")

    async def guarded_next(self, control):
        # Re-read immediately before clicking; never trust stale classification.
        loc = self.page.locator(f'[data-applypilot-token="{control["token"]}"]')
        labels = await loc.evaluate("el=>[el.getAttribute('aria-label')||'',el.innerText||'',el.value||'',el.title||'']")
        if any(NavigationService.classify(label) == N.FINAL_SUBMIT for label in labels):
            raise UnsafeInteraction("Final submission controls are never clicked")
        if not any(NavigationService.classify(label) == N.NEXT for label in labels):
            raise UnsafeInteraction("Navigation control changed or is ambiguous")
        await loc.click()
        await self.settle(autofill=True)

    async def security_challenge(self):
        if len([p for p in self.page.context.pages if not p.is_closed()]) > 1:
            return "An additional browser tab opened. Complete any login, close the extra tab, then Resume."
        if await self.page.locator('input[type="password"]:visible,input[autocomplete="one-time-code"]:visible').count():
            return "Complete account registration, login or MFA in the browser, then Resume."
        if await self.page.locator('iframe[src*="recaptcha"]:visible,iframe[src*="hcaptcha"]:visible,iframe[src*="challenges.cloudflare"]:visible').count():
            return "Complete the CAPTCHA or security challenge manually, then Resume."
        text = (await self.page.locator('body').inner_text()).lower()
        if any(phrase in text for phrase in ['verify you are human', 'checking your browser', 'enter verification code', 'access denied']):
            return "The site requires a security check. Complete it manually, then Resume."
        return None
