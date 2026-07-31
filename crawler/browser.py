"""Playwright wrapper — BrowserContext Protocol + real impl + anti-bot detect.

Spec § Browser wrapper. FakeBrowserContext lives in tests/fakes/browser.py
(grill-me amendment 1: keep real + fake separate).
"""
import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from crawler import config
from crawler.exceptions import Blocked, CaptchaEncountered, SPAWaitTimeout

ANTI_BOT_TITLE_KEYWORDS = ("captcha", "verify")
ANTI_BOT_BODY_KEYWORDS = ("access denied", "are you a human", "unusual traffic")


class BrowserContext(Protocol):
    """Async browser context. Real = Playwright; fake = tests/fakes/browser.py."""
    async def goto(self, url: str, wait_selector: str | None = None,
                   timeout_ms: int = config.BROWSER_TIMEOUT_MS) -> str: ...
    async def extract_html(self) -> str: ...
    async def cookies(self) -> list[dict[str, Any]]: ...
    async def close(self) -> None: ...


def _detect_anti_bot(*, title: str, body: str, url: str, status: int | None = None) -> None:
    """Raise typed exception on anti-bot signal. No auto-solve."""
    title_lower = title.lower()
    body_lower = body.lower()

    if status == 403:
        raise Blocked(f"HTTP 403 at {url}")
    if any(kw in title_lower for kw in ANTI_BOT_TITLE_KEYWORDS):
        raise CaptchaEncountered(f"anti-bot title at {url}: {title!r}")
    if any(url.lower().endswith(f"/{kw}") for kw in ANTI_BOT_TITLE_KEYWORDS):
        raise CaptchaEncountered(f"anti-bot URL: {url}")
    if any(kw in body_lower for kw in ANTI_BOT_BODY_KEYWORDS):
        raise Blocked(f"anti-bot body at {url}")


def pick_ua() -> str:
    """Round-robin pick from UA pool. Caller maintains index for session-stickiness."""
    return random.choice(config.UA_POOL)


# --- Cookie persistence (JSON schema per grill-me amendment 9) ---

class SessionCookieStore:
    """JSON-backed cookie persistence. Spec § Browser wrapper."""

    def __init__(self, path: Path):
        self.path = path

    def save(self, cookies: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "saved_at": datetime.now(UTC).isoformat(),
            "cookies": cookies,
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(data, dict) or "cookies" not in data:
            return []
        cookies = data["cookies"]
        return cookies if isinstance(cookies, list) else []


# --- Real Playwright impl ---

class PlaywrightBrowserContext:
    """Real Playwright Chromium. Lazy import to keep tests Playwright-free."""

    def __init__(self, cookie_store: SessionCookieStore):
        self._cookie_store = cookie_store
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    async def __aenter__(self) -> "PlaywrightBrowserContext":  # pragma: no cover
        # Lazy import — tests using FakeBrowserContext never trigger this
        # Manual smoke only (T23).
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        ua = pick_ua()
        self._context = await self._browser.new_context(user_agent=ua)
        # Load persisted cookies
        for c in self._cookie_store.load():
            await self._context.add_cookies([c])
        self._page = await self._context.new_page()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover
        # Manual smoke only (T23).
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def goto(self, url: str, wait_selector: str | None = None,
                   timeout_ms: int = config.BROWSER_TIMEOUT_MS) -> str:
        response = await self._page.goto(url, timeout=timeout_ms)
        status = response.status if response else None
        if wait_selector:
            try:
                await self._page.wait_for_selector(wait_selector, timeout=timeout_ms)
            except Exception as e:
                raise SPAWaitTimeout(f"selector {wait_selector!r} at {url}: {e}") from e
        html = await self._page.content()
        title = await self._page.title()
        _detect_anti_bot(title=title, body=html, url=url, status=status)
        return html

    async def extract_html(self) -> str:
        return await self._page.content()

    async def cookies(self) -> list[dict[str, Any]]:
        return await self._context.cookies()

    async def save_cookies(self) -> None:  # pragma: no cover
        # Manual smoke only (T23).
        self._cookie_store.save(await self.cookies())

    async def close(self) -> None:
        if self._context:
            await self._context.close()