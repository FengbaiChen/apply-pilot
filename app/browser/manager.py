from playwright.async_api import async_playwright

class BrowserManager:
    def __init__(self, settings):
        self.settings = settings
        self.playwright = None
        self.context = None

    async def launch(self):
        self.settings.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        self.playwright = await async_playwright().start()
        self.context = await self.playwright.chromium.launch_persistent_context(
            str(self.settings.browser_profile_dir.resolve()), headless=self.settings.browser_headless,
            channel="chromium", accept_downloads=False)
        self.context.set_default_timeout(self.settings.browser_timeout_ms)
        return self.context.pages[0] if self.context.pages else await self.context.new_page()

    async def close(self):
        if self.context: await self.context.close()
        if self.playwright: await self.playwright.stop()
        self.context = self.playwright = None
