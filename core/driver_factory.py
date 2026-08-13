"""
Owns the Playwright browser/context/page lifecycle for a run.

One browser instance per run, one fresh context+page per test case, so
test cases don't leak cookies/localStorage/state into each other while
still avoiding the cost of relaunching the browser every time.
"""
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, Playwright

from core.config_loader import RunConfig
from core.logger import get_logger

logger = get_logger("driver_factory")

_BROWSER_LAUNCHERS = {
    "chromium": lambda pw: pw.chromium,
    "firefox": lambda pw: pw.firefox,
    "webkit": lambda pw: pw.webkit,
}


class DriverFactory:
    def __init__(self, config: RunConfig):
        self.config = config
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    def start_browser(self) -> None:
        self._playwright = sync_playwright().start()
        browser_type = _BROWSER_LAUNCHERS.get(self.config.browser.lower())
        if browser_type is None:
            raise ValueError(f"Unsupported browser '{self.config.browser}'. Use chromium, firefox, or webkit.")
        self._browser = browser_type(self._playwright).launch(
            headless=self.config.headless,
            slow_mo=self.config.slow_mo_ms,
        )
        logger.info(f"Launched {self.config.browser} (headless={self.config.headless})")

    def new_page(self, storage_state_path: str | None = None) -> tuple[BrowserContext, Page]:
        """storage_state_path, when given, seeds the new context with a
        previously saved session (cookies/localStorage) - see
        core/session_manager.py. Must be passed at context creation;
        Playwright has no supported way to inject storage_state into a
        context after new_context() has already run."""
        if self._browser is None:
            raise RuntimeError("Browser not started - call start_browser() first")
        context = self._browser.new_context(
            viewport={"width": self.config.viewport_width, "height": self.config.viewport_height},
            base_url=self.config.base_url or None,
            storage_state=storage_state_path,
        )
        context.set_default_timeout(self.config.default_timeout_ms)
        page = context.new_page()
        return context, page

    def close_context(self, context: BrowserContext) -> None:
        try:
            context.close()
        except Exception as e:
            logger.warning(f"Error closing context: {e}")

    def stop_browser(self) -> None:
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        logger.info("Browser stopped, Playwright driver released")

    def __enter__(self):
        self.start_browser()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_browser()
