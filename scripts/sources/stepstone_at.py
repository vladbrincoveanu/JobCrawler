"""StepStone.at source for the job scout.

Chosen after devjobs.at -- CAREER-BUCKETS.md's top-ranked Austrian tech board --
turned out to be unreachable: every path there, `robots.txt` included, answers
429 behind a Vercel bot challenge, so there is no polite way in. StepStone.at is
the next-ranked source and is plainly crawlable: robots.txt allows everything
except `/?*` and some legacy `.cfm` paths, and search results are server-rendered.

Two things differ from the karriere.at source:

1. LISTING-ONLY. Ad detail pages (`/stellenangebote--…-inline.html`) sit behind a
   WAF that returns 403 to any non-interactive client, so this module never
   requests them. Every field comes from the result card: title, company,
   location, home-office flag, the ~200-char teaser and a relative post date.
   Salary is therefore usually absent -- StepStone does not print it on cards --
   and the rows go through the scout as "no salary stated", which its
   --min-salary filter keeps by design.

2. REAL PAGINATION. Unlike karriere.at, `?page=N` works, 25 cards a page. Breadth
   comes from depth here, so fewer search terms are needed per location. A page
   past the end returns 0 cards, which is the stop condition.

Ad URLs are emitted exactly as StepStone writes them (`-inline.html`); the WAF
blocks verification of any rewritten form, so nothing is rewritten.

Emits the same dict shape as scout.fetch_free_apis() so rows drop straight into
the existing pipeline.
"""

from __future__ import annotations

import re
import sys
import time
from datetime import date, timedelta
from urllib.parse import quote

import requests

from .at_common import clean, in_scope, parse_salary  # noqa: F401 - in_scope re-exported

BASE = "https://www.stepstone.at"
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
}
REQUEST_DELAY = 1.0  # be a polite guest: ~1 req/s
CARDS_PER_PAGE = 25

# One result card is an <article> carrying the numeric ad id. Splitting on that
# rather than on `data-at="job-item"` matters: the latter also appears inside the
# page's emitted CSS (`[data-at="job-item"]{border-radius:4px}`), which would add
# a phantom card.
CARD_SPLIT_RE = re.compile(r'(?=<article\b[^>]*id="job-item-\d+")')
# href precedes data-at in the anchor, hence the order here.
TITLE_RE = re.compile(
    r'<a[^>]*href="([^"]+)"[^>]*data-at="job-item-title"[^>]*>(.*?)</a>', re.DOTALL)

# Card fields are marked by data-at attributes and wrapped in several layers of
# generated-class divs, so each field is read as "everything up to the next
# data-at marker", then tag-stripped. Robust to the styling churn that a
# CSS-in-JS build produces on every deploy.


def log(msg: str) -> None:
    print(f"[stepstone.at] {msg}", file=sys.stderr)


def field(chunk: str, name: str) -> str:
    """Text of the `data-at="<name>"` element in a card chunk, or ''.

    The end boundary is the START of the tag carrying the next data-at marker,
    not the marker itself -- cutting at the marker would leave that tag's opening
    fragment (`<span class="res-…" data-genesis-element="BASE"`) in the text,
    where the tag-stripper can't remove it because it never closes.
    """
    marker = f'data-at="{name}"'
    start = chunk.find(marker)
    if start < 0:
        return ""
    open_end = chunk.find(">", start + len(marker))
    if open_end < 0:
        return ""
    rest = chunk[open_end + 1:]
    article_end = rest.find("</article>")
    if article_end >= 0:
        rest = rest[:article_end]
    next_marker = rest.find('data-at="')
    if next_marker >= 0:
        tag_start = rest.rfind("<", 0, next_marker)
        rest = rest[:tag_start if tag_start >= 0 else next_marker]
    return clean(rest)


def slugify(term: str) -> str:
    """StepStone search slugs hyphenate whitespace and drop the dots karriere.at
    keeps: `.NET` is reachable as `/jobs/net`, `/jobs/.net` 404s."""
    slug = re.sub(r"[^a-z0-9+#\s-]", "", term.strip().lower())
    slug = re.sub(r"[\s-]+", "-", slug).strip("-")
    # '#' must be percent-encoded, not passed through: raw it would start a URL
    # fragment and "c#-developer" would be requested as "/jobs/c".
    return quote(slug, safe="-+")


def location_slug(location: str) -> str:
    return slugify(location)


# "vor 22 Stunden", "vor 1 Tag", "vor 3 Tagen", "vor 1 Woche", "vor 2 Wochen".
REL_RE = re.compile(
    r"vor\s+(\d+)\s+(stunde|stunden|tag|tagen|woche|wochen|monat|monaten)", re.IGNORECASE)
REL_UNIT_DAYS = {"stunde": 0, "stunden": 0, "tag": 1, "tagen": 1,
                 "woche": 7, "wochen": 7, "monat": 30, "monaten": 30}


def parse_posted(raw: str, today: date) -> str | None:
    """StepStone prints only relative ages; normalize to ISO for the scout's filters.

    Week and month ages are coarse by nature ("vor 1 Woche" is 7-13 days old); the
    conversion takes the *youngest* age in the bucket so a --days cutoff errs
    toward keeping a borderline ad rather than silently dropping a fresh one.
    """
    text = clean(raw).lower()
    if not text:
        return None
    if "heute" in text or "gerade" in text:
        return today.isoformat()
    if "gestern" in text:
        return (today - timedelta(days=1)).isoformat()
    match = REL_RE.search(text)
    if not match:
        return None
    days = int(match.group(1)) * REL_UNIT_DAYS[match.group(2).lower()]
    return (today - timedelta(days=days)).isoformat()


def parse_cards(html: str, today: date | None = None) -> list[dict]:
    """Parse a StepStone.at search results page into raw card dicts."""
    today = today or date.today()
    cards = []
    for chunk in CARD_SPLIT_RE.split(html or "")[1:]:
        title_match = TITLE_RE.search(chunk)
        if not title_match:
            continue
        url, title = title_match.group(1), clean(title_match.group(2))
        if not title or not url:
            continue
        if url.startswith("/"):
            url = BASE + url
        home_office = field(chunk, "job-item-work-from-home")
        cards.append({
            "url": url,
            "title": title,
            "company": field(chunk, "job-item-company-name"),
            "location": field(chunk, "job-item-location") or "Österreich",
            "posted": parse_posted(field(chunk, "job-item-timeago"), today),
            "home_office": home_office,
            "snippet": field(chunk, "jobcard-content"),
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


def search_url(term: str, location: str, page: int = 1) -> str:
    """`/jobs/<term>/in-<location>?page=N`. An empty location searches all of
    Austria, which is how remote/home-office ads outside Vienna are reached."""
    slug = slugify(term)
    loc = location_slug(location)
    url = f"{BASE}/jobs/{slug}/in-{loc}" if loc else f"{BASE}/jobs/{slug}"
    return f"{url}?page={page}" if page > 1 else url


def fetch(terms: list[str], locations: list[str], days: int = 14,
          max_pages: int = 3, delay: float = REQUEST_DELAY) -> list[dict]:
    """Search StepStone.at and return rows in the scout's job-dict shape.

    Rows with an unparseable posting date are KEPT, matching karriere_at: the
    scout's own recency scoring handles the missing value, and dropping them
    would silently lose fresh ads whose card omits the age.
    """
    today = date.today()
    cutoff = (today - timedelta(days=days)).isoformat()
    pairs = [(term, loc) for term in terms for loc in locations if slugify(term)]
    log(f"{len(pairs)} searches x up to {max_pages} pages "
        f"({len(terms)} terms x {len(locations)} locations)")

    seen: dict[str, dict] = {}
    requests_made = 0
    for term, location in pairs:
        for page in range(1, max_pages + 1):
            if requests_made:
                time.sleep(delay)
            requests_made += 1
            html = _get(search_url(term, location, page))
            if not html:
                break
            cards = parse_cards(html, today)
            if not cards:
                break  # past the last page of results for this search
            for card in cards:
                if card["posted"] and card["posted"] < cutoff:
                    continue
                seen.setdefault(card["url"], card)
            if len(cards) < CARDS_PER_PAGE:
                break  # short page: this was the last one

    log(f"{len(seen)} unique ads from {requests_made} search pages")

    jobs = []
    dropped = 0
    for card in seen.values():
        remote = bool(re.search(r"home[\s-]?office|remote|telearbeit",
                                card["home_office"] or "", re.I))
        if not in_scope({"location": card["location"],
                         "is_remote": str(remote).lower()}, locations):
            dropped += 1
            continue
        # StepStone rarely prints salary on a card, and detail pages are WAF-
        # blocked, so this usually yields None -- deliberately, rather than
        # inventing a figure the ad does not state.
        salary_eur, salary_raw = parse_salary(f"{card['title']} {card['snippet']}")
        jobs.append({
            "url": card["url"],
            "title": card["title"],
            "company": card["company"],
            "ats_type": "stepstone_at",
            "location": card["location"],
            "is_remote": "true" if remote else "false",
            "country_iso": "AT",
            "salary_min": salary_eur,
            "salary_max": salary_eur,
            "salary_currency": "EUR" if salary_eur else None,
            "salary_period": "year" if salary_eur else None,
            "salary_summary": salary_raw,
            "employment_type": card["home_office"] or None,
            "description": " ".join(x for x in (card["title"], card["snippet"]) if x),
            "posted": card["posted"],
            "apply_url": card["url"],
        })
    if dropped:
        log(f"{dropped} ads dropped as out of scope (onsite outside "
            f"{', '.join(l for l in locations if l.strip()) or 'anywhere'})")
    log(f"{len(jobs)} jobs returned")
    return jobs
