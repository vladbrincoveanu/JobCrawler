"""One-shot: capture live AMS HTML to tests/fixtures/ for offline test replay.

WARNING: only run manually. Not in CI. AMS ToS permitting scraping for
personal use only — re-record fixtures sparingly.

Grill-me amendment 8: strip job descriptions, keep only structural HTML.
"""
import asyncio
import sys
from pathlib import Path

from crawler import config
from crawler.browser import PlaywrightBrowserContext, SessionCookieStore
from crawler.sources.ams import (
    AMS_DETAIL_SELECTOR,
    AMS_JOB_CARD_SELECTOR,
)

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"
# The PostgreSQL migration removed config.DB_PATH, which this used to derive the
# session file from; every run since then died with AttributeError before it
# opened a browser. The cookie jar was always data/session_ams.json in practice.
SESSION_FILE = Path(__file__).parent.parent / "data" / "session_ams.json"


def strip_descriptions(html: str) -> str:
    """Replace .description contents with placeholder. Keeps structural layout."""
    import re
    return re.sub(
        r'(<div class="description">).*?(</div>)',
        r'\1[stripped by record_fixtures.py]\2',
        html,
        flags=re.DOTALL,
    )


async def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    cookie_store = SessionCookieStore(SESSION_FILE)

    async with PlaywrightBrowserContext(cookie_store) as browser:
        # Search page
        html = await browser.goto(config.AMS_BASE_URL + "jobs", wait_selector=AMS_JOB_CARD_SELECTOR)
        (FIXTURES_DIR / "ams_search_page.html").write_text(strip_descriptions(html), encoding="utf-8")
        print(f"saved ams_search_page.html ({len(html)} bytes)")

        # First job detail (operator edits URL to specific job ID after first run)
        if len(sys.argv) > 1:
            url = sys.argv[1]
            html = await browser.goto(url, wait_selector=AMS_DETAIL_SELECTOR)
            (FIXTURES_DIR / "ams_detail_page.html").write_text(strip_descriptions(html), encoding="utf-8")
            print(f"saved ams_detail_page.html from {url} ({len(html)} bytes)")
        else:
            print("skip detail — pass URL as argv[1]")


if __name__ == "__main__":
    asyncio.run(main())
