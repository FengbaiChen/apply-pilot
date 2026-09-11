from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import pytest
import pytest_asyncio
from app.config.settings import Settings
from app.workers.browser_worker import BrowserWorker

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args): pass

@pytest.fixture(scope='session')
def fixture_url():
    root = Path(__file__).parent / 'fixtures'
    server = ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(root)))
    thread = Thread(target=server.serve_forever,daemon=True); thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown(); server.server_close(); thread.join()

@pytest_asyncio.fixture
async def worker(tmp_path):
    settings = Settings(browser_profile_dir=tmp_path/'browser',browser_headless=True,autofill_wait_ms=0,browser_timeout_ms=1500)
    worker = BrowserWorker(settings)
    worker.page = await worker.manager.launch()
    # No external employer or provider traffic is allowed in browser fixtures.
    await worker.page.context.route('**/*',lambda route: route.continue_() if route.request.url.startswith('http://127.0.0.1:') else route.abort())
    try: yield worker
    finally: await worker.close()
