from urllib.parse import urlsplit


class PlatformDetector:
    @staticmethod
    def detect_url(url):
        host = (urlsplit(url).hostname or '').lower()
        return 'workday' if host == 'myworkdayjobs.com' or host.endswith('.myworkdayjobs.com') else 'generic'

    async def detect(self, page):
        return self.detect_url(page.url)
