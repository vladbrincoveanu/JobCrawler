"""AMS adapter — Playwright-based. Real browser via PlaywrightBrowserContext;
tests use FakeBrowserContext (DI). Spec § AMS adapter."""
import asyncio
import random
from datetime import datetime, timezone
from typing import AsyncIterator
from bs4 import BeautifulSoup
from crawler import config
from crawler.browser import BrowserContext
from crawler.models import JobQuery, RawJob, NormalizedJob
from crawler.parser import select_text, parse_iso_date
from crawler.storage.dedup import content_hash
from crawler.exceptions import SchemaChanged

# Selectors — exported so tests can reference the exact strings (grill-me 10)
AMS_JOB_CARD_SELECTOR = '[data-testid="job-card"]'
AMS_DETAIL_SELECTOR = '[data-testid="job-detail"]'
AMS_TITLE_SELECTOR = "h1"
AMS_COMPANY_SELECTOR = ".company"
AMS_LOCATION_SELECTOR = ".location"
AMS_DESCRIPTION_SELECTOR = ".description"
AMS_SALARY_SELECTOR = ".salary"
AMS_EMPLOYMENT_TYPE_SELECTOR = ".employment-type"
AMS_POSTED_SELECTOR = "time"


class AmsAdapter:
    """AMS source adapter. Takes injectable BrowserContext for testability."""

    name = "ams"

    def __init__(self, browser: BrowserContext):
        self._browser = browser

    async def search(self, query: JobQuery) -> AsyncIterator[RawJob]:
        url = config.AMS_BASE_URL + "jobs"
        await self._browser.goto(url, wait_selector=AMS_JOB_CARD_SELECTOR)
        html = await self._browser.extract_html()
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(AMS_JOB_CARD_SELECTOR)
        for i, card in enumerate(cards):
            if i >= query.max_results:
                break
            try:
                raw = _parse_search_card(card, fetched_at=_now())
                yield raw
            except Exception:
                # Skip malformed cards — they'll be caught in pipeline
                continue
            # Throttle between cards
            await asyncio.sleep(_jitter_seconds())

    async def fetch_detail(self, raw: RawJob) -> NormalizedJob:
        html = await self._browser.goto(str(raw.url), wait_selector=AMS_DETAIL_SELECTOR)
        soup = BeautifulSoup(html, "html.parser")
        return _parse_detail_page(soup, raw, html=html, fetched_at=raw.fetched_at)


# --- Parsing helpers (unit-tested in test_ams_parser.py) ---

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _jitter_seconds() -> float:
    return random.uniform(0, config.AMS_REQUEST_JITTER_SECONDS)


def _parse_search_card(card, *, fetched_at: datetime) -> RawJob:
    """Extract RawJob from a search result card. Required: title + href."""
    title_el = card.select_one("a.title") or card.select_one("a")
    if title_el is None:
        raise SchemaChanged("no anchor in job card")
    title = title_el.get_text(strip=True)
    href = title_el.get("href", "")
    source_id = href.rstrip("/").split("/")[-1]
    if not source_id:
        raise SchemaChanged(f"cannot extract source_id from href {href!r}")
    company = card.select_one(".company")
    location = card.select_one(".location")
    posted = card.select_one("time")
    return RawJob(
        source="ams",
        source_id=source_id,
        url=f"{config.AMS_BASE_URL.rstrip('/')}{href}" if href.startswith("/") else href,
        title=title,
        company=company.get_text(strip=True) if company else None,
        location=location.get_text(strip=True) if location else None,
        posted_at=parse_iso_date(posted.get("datetime") if posted and posted.has_attr("datetime") else None),
        fetched_at=fetched_at,
    )


def _parse_detail_page(soup: BeautifulSoup, raw: RawJob, *, html: str,
                       fetched_at: datetime) -> NormalizedJob:
    """Extract NormalizedJob from a detail page. Required: title + company + location + description."""
    try:
        title = select_text(soup, AMS_TITLE_SELECTOR, required=True)
        company = select_text(soup, AMS_COMPANY_SELECTOR, required=True)
        location = select_text(soup, AMS_LOCATION_SELECTOR, required=True)
        description = select_text(soup, AMS_DESCRIPTION_SELECTOR, required=True)
    except Exception as e:
        raise SchemaChanged(f"required field missing on detail page: {e}") from e
    salary = select_text(soup, AMS_SALARY_SELECTOR)
    employment_type = select_text(soup, AMS_EMPLOYMENT_TYPE_SELECTOR)
    posted = soup.select_one(AMS_POSTED_SELECTOR)
    posted_at = parse_iso_date(posted.get("datetime") if posted and posted.has_attr("datetime") else None)
    return NormalizedJob(
        source=raw.source,
        source_id=raw.source_id,
        url=raw.url,
        title=title,
        company=company,
        location=location,
        description=description,
        salary=salary,
        employment_type=employment_type,
        posted_at=posted_at,
        content_hash=content_hash(title, company, location),
        fetched_at=fetched_at,
        raw_html=html,  # grill-me amendment 4
    )