"""karriere.at source for the job scout.

karriere.at is the largest Austrian job portal and its robots.txt is fully open
(`User-agent: * / Disallow:`). Search results are server-rendered, so plain
`requests` + regex is enough -- no headless browser.

Pagination: there is none in the server-rendered HTML. Every one of `?page=`,
`?seite=`, `?p=`, `?pageIndex=`, `?currentPage=`, `?start=` and `?offset=`
returns a byte-identical result set, and the path forms `/jobs/<q>/seite-2` and
`/jobs/<q>/2` are 404. Deeper pages come from an internal API reachable only
through minified JS bundles.

So breadth comes from query diversity, not depth: many narrow searches of ~16
high-relevance rows each, unioned and deduped. `/jobs/<slug>` and
`/jobs/<slug>/<location>` are the canonical search URLs.

Emits the same dict shape as scout.fetch_free_apis() so rows drop straight into
the existing pipeline.
"""

from __future__ import annotations

import re
import sys
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote

import requests

from .at_common import (  # noqa: F401 - re-exported as this module's public API
    AMOUNT_RE, AT_MONTHS_PER_YEAR, ENTITIES, LOCATION_ALIASES, MONTHLY_RE,
    TAG_RE, WS_RE, YEARLY_RE, clean, german_number, in_scope, parse_salary,
)

BASE = "https://www.karriere.at"
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
}
REQUEST_DELAY = 1.0  # be a polite guest: ~1 req/s

# One result card. The list markup is BEM (`m-jobsListItem__*`) and minified onto
# few lines, so cards are split on the title link rather than on newlines.
CARD_SPLIT_RE = re.compile(r'(?=<a[^>]*m-jobsListItem__titleLink)')
TITLE_RE = re.compile(
    r'<a[^>]*m-jobsListItem__titleLink[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
COMPANY_RE = re.compile(r'm-jobsListItem__companyName[^>]*>(.*?)<', re.DOTALL)
# The location span carries a data-location attribute AFTER the class, and wraps
# a nested "lastComma" span -- so capture only up to the next tag.
LOCATION_RE = re.compile(r'class="m-jobsListItem__location"[^>]*>([^<]*)')
DATE_RE = re.compile(r'm-jobsListItem__date[^>]*>(.*?)<', re.DOTALL)
PILL_RE = re.compile(r'class="m-jobsListItem__pill">(.*?)<', re.DOTALL)

DETAIL_DESC_RE = re.compile(
    r'<div[^>]*class="[^"]*m-jobContent__jobDetail[^"]*"[^>]*>(.*?)</div>\s*</div>', re.DOTALL)

# "vor 3 Tagen", "gestern", "heute", or a literal date.
REL_DAYS_RE = re.compile(r"vor\s+(\d+)\s+Tag", re.IGNORECASE)
ABS_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")

def log(msg: str) -> None:
    print(f"[karriere.at] {msg}", file=sys.stderr)


def slugify(term: str) -> str:
    """karriere.at search slugs keep dots (`.net`) but hyphenate whitespace."""
    slug = term.strip().lower().replace(" ", "-")
    return quote(slug, safe=".-+#")


def parse_posted(raw: str, today: date) -> str | None:
    """karriere.at prints relative dates; normalize to ISO for the scout's filters."""
    text = clean(raw).lower()
    if not text:
        return None
    if "heute" in text:
        return today.isoformat()
    if "gestern" in text:
        return (today - timedelta(days=1)).isoformat()
    rel = REL_DAYS_RE.search(text)
    if rel:
        return (today - timedelta(days=int(rel.group(1)))).isoformat()
    abs_match = ABS_DATE_RE.search(text)
    if abs_match:
        day, month, year = (int(g) for g in abs_match.groups())
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None
    return None


def parse_cards(html: str, today: date | None = None) -> list[dict]:
    """Parse a karriere.at search results page into raw card dicts."""
    today = today or date.today()
    cards = []
    for chunk in CARD_SPLIT_RE.split(html or "")[1:]:
        title_match = TITLE_RE.search(chunk)
        if not title_match:
            continue
        url = title_match.group(1)
        title = clean(title_match.group(2))
        if not title or not url:
            continue
        if url.startswith("/"):
            url = BASE + url
        company_match = COMPANY_RE.search(chunk)
        locations = [clean(loc) for loc in LOCATION_RE.findall(chunk)]
        locations = [loc.strip(" ,") for loc in locations if loc.strip(" ,")]
        date_match = DATE_RE.search(chunk)
        pills = [clean(p) for p in PILL_RE.findall(chunk)]
        cards.append({
            "url": url,
            "title": title,
            "company": clean(company_match.group(1)) if company_match else "",
            "location": ", ".join(dict.fromkeys(locations)) or "Österreich",
            "posted": parse_posted(date_match.group(1) if date_match else "", today),
            "pills": pills,
        })
    return cards


def _get(url: str) -> str | None:
    """Single GET; a failure is logged and skipped, never fatal to the run."""
    try:
        resp = requests.get(url, headers=UA, timeout=25)
        resp.raise_for_status()
        return resp.text
    except Exception as exc:  # noqa: BLE001 - one bad query must not kill the scout
        log(f"request failed, skipping ({exc}): {url}")
        return None


def search_urls(terms: list[str], locations: list[str]) -> list[str]:
    """Cross search terms with locations. An empty location means Austria-wide,
    which is how remote/homeoffice ads are reached (scout's reachable_from_home
    then decides whether a remote ad is actually takeable from Vienna)."""
    urls = []
    for term in terms:
        slug = slugify(term)
        if not slug:
            continue
        for loc in locations:
            loc_slug = slugify(loc)
            urls.append(f"{BASE}/jobs/{slug}/{loc_slug}" if loc_slug
                        else f"{BASE}/jobs/{slug}")
    return list(dict.fromkeys(urls))


def fetch_detail(url: str) -> tuple[str, int | None, str | None]:
    """Job detail page -> (description, annual_eur, salary_snippet)."""
    html = _get(url)
    if not html:
        return "", None, None
    match = DETAIL_DESC_RE.search(html)
    body = clean(match.group(1)) if match else clean(html)
    salary_eur, salary_raw = parse_salary(body[:4000])
    return body[:6000], salary_eur, salary_raw


def fetch(terms: list[str], locations: list[str], days: int = 14,
          detail: bool = True, max_detail: int = 60,
          delay: float = REQUEST_DELAY) -> list[dict]:
    """Search karriere.at and return rows in the scout's job-dict shape.

    Rows with an unparseable posting date are KEPT: karriere.at omits the date
    on some ad formats, and dropping them would silently lose fresh jobs. The
    scout's own recency scoring handles the missing value.
    """
    today = date.today()
    cutoff = (today - timedelta(days=days)).isoformat()
    urls = search_urls(terms, locations)
    log(f"{len(urls)} searches ({len(terms)} terms x {len(locations)} locations)")

    seen: dict[str, dict] = {}
    for i, url in enumerate(urls):
        if i:
            time.sleep(delay)
        html = _get(url)
        if not html:
            continue
        for card in parse_cards(html, today):
            if card["posted"] and card["posted"] < cutoff:
                continue
            seen.setdefault(card["url"], card)

    log(f"{len(seen)} unique ads from search pages")

    # Scope-filter BEFORE fetching detail pages, so the request budget is spent
    # only on ads that can actually be recommended.
    candidates = []
    for card in seen.values():
        pill_text = " ".join(card["pills"])
        remote = bool(re.search(r"home\s?office|remote|teleworking", pill_text, re.I))
        card["pill_text"] = pill_text
        card["remote"] = remote
        if in_scope({"location": card["location"], "is_remote": str(remote).lower()},
                    locations):
            candidates.append(card)
    dropped = len(seen) - len(candidates)
    if dropped:
        log(f"{dropped} ads dropped as out of scope (onsite outside "
            f"{', '.join(l for l in locations if l.strip()) or 'anywhere'})")

    jobs = []
    for i, card in enumerate(candidates):
        description, salary_eur, salary_raw = "", None, None
        pill_text = card["pill_text"]
        remote = card["remote"]
        if detail and i < max_detail:
            time.sleep(delay)
            description, salary_eur, salary_raw = fetch_detail(card["url"])
        if salary_eur is None:
            salary_eur, salary_raw = parse_salary(pill_text)
        jobs.append({
            "url": card["url"],
            "title": card["title"],
            "company": card["company"],
            "ats_type": "karriere_at",
            "location": card["location"],
            "is_remote": "true" if remote else "false",
            "country_iso": "AT",
            "salary_min": salary_eur,
            "salary_max": salary_eur,
            "salary_currency": "EUR" if salary_eur else None,
            "salary_period": "year" if salary_eur else None,
            "salary_summary": salary_raw,
            "employment_type": pill_text or None,
            "description": description or f"{card['title']} {pill_text}",
            "posted": card["posted"],
            "apply_url": card["url"],
        })
    if detail and len(candidates) > max_detail:
        log(f"detail pages fetched for {max_detail} of {len(candidates)} ads "
            f"(--karriere-max-detail); the rest have title/pill text only")
    log(f"{len(jobs)} jobs returned")
    return jobs
