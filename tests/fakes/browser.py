"""FakeBrowserContext — implements BrowserContext Protocol for tests.

Grill-me amendment 1: lives in tests/fakes/, NOT crawler/browser.py.
Keeps Playwright import chain out of test path.
"""
from typing import Any
from bs4 import BeautifulSoup
from crawler import config
from crawler.browser import _detect_anti_bot
from crawler.exceptions import SPAWaitTimeout


class FakeBrowserContext:
    """Returns HTML from a fixture map. Supports anti-bot injection + cookie stub."""

    def __init__(self, fixture_map: dict[str, str] | None = None):
        self._fixtures: dict[str, str] = fixture_map or {}
        self._cookies: list[dict[str, Any]] = []
        self._anti_bot_overrides: dict[str, dict[str, Any]] = {}

    def add_anti_bot_response(self, url: str, *, title: str = "captcha",
                              body: str = "", status: int | None = None) -> None:
        """Register a URL that should trigger anti-bot detection."""
        self._anti_bot_overrides[url] = {"title": title, "body": body, "status": status}

    def set_cookies(self, cookies: list[dict[str, Any]]) -> None:
        self._cookies = list(cookies)

    async def goto(self, url: str, wait_selector: str | None = None,
                   timeout_ms: int = config.BROWSER_TIMEOUT_MS) -> str:
        if url in self._anti_bot_overrides:
            ov = self._anti_bot_overrides[url]
            _detect_anti_bot(title=ov["title"], body=ov.get("body", ""),
                             url=url, status=ov.get("status"))
        if url not in self._fixtures:
            raise SPAWaitTimeout(f"no fixture for {url} (no selector met)")
        html = self._fixtures[url]
        # If a wait_selector is requested, only return HTML if it contains that selector
        if wait_selector and not BeautifulSoup(html, "html.parser").select(wait_selector):
            raise SPAWaitTimeout(f"selector {wait_selector!r} not in {url}")
        # Run anti-bot detection on normal responses too (captcha can be in body)
        _detect_anti_bot(title="Jobs - AMS", body=html, url=url)
        self._last_html = html
        return html

    async def extract_html(self) -> str:
        return self._last_html or ""

    async def cookies(self) -> list[dict[str, Any]]:
        return list(self._cookies)

    async def close(self) -> None:
        pass