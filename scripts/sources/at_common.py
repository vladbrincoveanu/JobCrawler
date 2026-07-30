"""Parsing helpers shared by the Austrian board sources (karriere.at, StepStone.at).

Both boards quote salaries the same way -- German number formatting, amount and
currency in either order, monthly figures that are paid 14x a year -- and both
need the same "is this ad actually reachable from Vienna" scope check. Keeping
one copy means a fix to the salary parser can't silently apply to only one board.

karriere_at re-exports these names, so `karriere_at.parse_salary` still works.
"""

from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, TypeVar

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
# <style>/<script> bodies are TEXT, so stripping tags alone leaves the CSS or JS
# behind. StepStone inlines an emotion <style> block inside some title anchors,
# which put ".res-xrpel9{box-sizing:border-box…}" in a job title on a live run.
NON_CONTENT_RE = re.compile(r"<(style|script)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)

ENTITIES = {
    "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'",
    "&apos;": "'", "&nbsp;": " ", "&auml;": "ä", "&ouml;": "ö", "&uuml;": "ü",
    "&Auml;": "Ä", "&Ouml;": "Ö", "&Uuml;": "Ü", "&szlig;": "ß", "&euro;": "€",
    "&ndash;": "–", "&mdash;": "—",
}

# Austrian boards write the amount BEFORE the currency ("3.954 € – 5.000 €
# monatlich", "ab 56.000 € jährlich"); job text sometimes uses the other order
# ("mind. EUR 65.000 brutto/Jahr"). Both are matched.
AMOUNT_RE = re.compile(r"(?:(?:EUR|€)\s*([\d][\d.,]*)|([\d][\d.,]*)\s*(?:EUR|€))",
                       re.IGNORECASE)
MONTHLY_RE = re.compile(r"monatlich|pro\s+Monat|/\s*Monat|per\s+month|/\s*month|p\.?m\.?\b",
                        re.IGNORECASE)
YEARLY_RE = re.compile(r"j(?:ä|ae)hrlich|pro\s+Jahr|/\s*Jahr|per\s+year|/\s*year|p\.?a\.?\b",
                       re.IGNORECASE)

# Austrian gross salaries are quoted per month and paid 14x a year (13th/14th
# month are statutory). Annualising a monthly figure at 12x understates real
# gross by ~17%, which silently drops good ads under --min-salary.
AT_MONTHS_PER_YEAR = 14

# Words that actually introduce a pay figure. Used to bound the search window in
# a full ad body: without this, `parse_salary` scanned 4000 characters and took
# the largest €-amount anywhere in them, so a funding sum or a revenue figure
# could win over the real salary line.
SALARY_CONTEXT_RE = re.compile(
    r"gehalt|entlohnung|verg(?:ü|ue)tung|bezahlung|verdien|brutto|lohn|salary|pay\b"
    r"|kollektivvertrag|kv-mindest|(?:ü|ue)berzahl",
    re.IGNORECASE)
# How far either side of a context word the amount may sit. An Austrian pay
# sentence ("Für diese Position gilt ein Bruttojahresgehalt ab EUR 56.000,-")
# comfortably fits; the next paragraph does not.
SALARY_WINDOW_CHARS = 140
# Above this length the text is an ad body, not a salary pill, so a context word
# is required. Short strings (pills, salary snippets) are their own window.
SALARY_PILL_MAX_CHARS = 200
# A figure at or above this is already an annual sum, whatever period word
# happens to be nearby -- no Austrian job pays €15k a *month* at the low end,
# and this is what stopped "Jahresbruttogehalt ab EUR 85.900" from being
# multiplied by 14 because the word "monatlich" appeared later in the ad.
MONTHLY_CEILING_EUR = 15_000
# Plausibility band for an annual gross. Outside it, refuse to guess rather
# than publish a €1.2M "salary".
MIN_PLAUSIBLE_ANNUAL_EUR = 10_000
MAX_PLAUSIBLE_ANNUAL_EUR = 400_000

LOCATION_ALIASES = {"wien": ("wien", "vienna"), "vienna": ("wien", "vienna")}

# Both boards used to be fetched strictly one request at a time with a 1s sleep
# between them. For the CLI digest that was merely slow; for the web CV-upload
# flow it was fatal -- a full karriere+stepstone scan took 8m16s against a
# request that has to answer in seconds, so the feature could never work.
#
# The politeness budget is now spent as a small number of *concurrent* requests
# instead of a serialising sleep. How much concurrency each board tolerates is a
# property OF THAT BOARD, not a global tuning knob, so each source passes its own
# value; both boards' robots.txt permit these paths with no Crawl-delay directive.
#
# karriere.at: measured fine at 6 (52 requests in 2.3s, no rejections).
# StepStone.at: NOT fine. It sits behind an Akamai WAF that answered 403 to
# every request -- and then IP-blocked outright -- when the same 6-wide burst
# was pointed at it. It gets 2 workers plus a 1s per-worker pace (~2 req/s,
# still twice the old serial rate) and is kept out of the default interactive
# scan, so a WAF block degrades one optional source instead of the feature.
FETCH_WORKERS = max(1, int(os.environ.get("SCOUT_FETCH_WORKERS", "6")))
STEPSTONE_WORKERS = max(1, int(os.environ.get("SCOUT_STEPSTONE_WORKERS", "2")))
STEPSTONE_PACE_SECONDS = 1.0

T = TypeVar("T")
R = TypeVar("R")


def fetch_parallel(items: Iterable[T], worker: Callable[[T], R],
                   workers: int = FETCH_WORKERS, pace: float = 0.0) -> list[R]:
    """Map `worker` over `items` with bounded concurrency, preserving order.

    Order is preserved because the callers dedupe with `setdefault`, where
    "first one wins" -- letting completion order decide which duplicate is kept
    would make a run's output depend on network timing rather than on the search
    ordering the caller chose.

    `pace` sleeps that long before each item, per worker thread, giving an
    effective ceiling of `workers / pace` requests per second for boards that
    police their rate.

    `worker` is expected to swallow its own network errors (the boards' `_get`
    returns None on failure): a single bad query must not kill the run, exactly
    as in the serial version.
    """
    items = list(items)
    if not items:
        return []
    if pace:
        inner = worker

        def worker(item):  # noqa: F811 - deliberate paced wrapper
            time.sleep(pace)
            return inner(item)

    if workers <= 1:
        return [worker(item) for item in items]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(worker, items))


def clean(raw: str) -> str:
    """Strip tags, decode the entities these boards actually emit, squash space."""
    text = NON_CONTENT_RE.sub(" ", raw or "")
    text = TAG_RE.sub(" ", text)
    for entity, char in ENTITIES.items():
        text = text.replace(entity, char)
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    return WS_RE.sub(" ", text).strip()


def german_number(raw: str) -> int | None:
    """German formatting: '.' groups thousands, ',' is the decimal separator.
    '49.784,42' -> 49784. Cents are irrelevant here, so the decimal part is cut."""
    try:
        return int(raw.replace(".", "").split(",")[0])
    except ValueError:
        return None


def _salary_windows(text: str) -> list[str]:
    """The stretches of `text` that plausibly contain a pay figure.

    A short string (a salary pill, or a snippet a caller already isolated) is
    taken whole. A long ad body is cut down to the neighbourhoods of the words
    that introduce pay -- everything else in the ad is noise that used to be
    scanned for euro amounts with no way to tell a salary from a budget.
    """
    if len(text) <= SALARY_PILL_MAX_CHARS:
        return [text]
    spans: list[tuple[int, int]] = []
    for match in SALARY_CONTEXT_RE.finditer(text):
        start = max(0, match.start() - SALARY_WINDOW_CHARS)
        end = min(len(text), match.end() + SALARY_WINDOW_CHARS)
        if spans and start <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], end))
        else:
            spans.append((start, end))
    return [text[start:end] for start, end in spans]


def _annualise(value: int, window: str) -> int:
    """Annual gross from one figure and the period words around it.

    Magnitude decides first, and deliberately so: period words are scattered all
    over an ad ("14x jährlich", "monatlich kündbar"), but no monthly Austrian
    gross reaches five figures, so a large number is annual no matter what word
    sits next to it, and a small one is monthly no matter what.
    """
    if value >= MONTHLY_CEILING_EUR:
        return value
    if YEARLY_RE.search(window) and not MONTHLY_RE.search(window):
        # Explicitly annual and below the ceiling: a part-time or trainee ad.
        return value
    return value * AT_MONTHS_PER_YEAR


def parse_salary(text: str) -> tuple[int | None, str | None]:
    """Best-effort annual gross EUR from an Austrian salary line.

    Returns (annual_eur, raw_snippet). For a range ("3.954 € – 5.000 €") the TOP
    of the range is used, matching how the scout treats salary_max elsewhere.
    The snippet is the window the figure was actually read from, so a wrong
    number can be traced back to the sentence that produced it.
    """
    text = clean(text or "")
    if not text:
        return None, None

    best: tuple[int, str] | None = None
    for window in _salary_windows(text):
        for match in AMOUNT_RE.finditer(window):
            raw = german_number(match.group(1) or match.group(2))
            if not raw or raw <= 0:
                continue
            value = _annualise(raw, window)
            # Each amount is judged on its own. Taking the window's maximum
            # instead would let one implausible figure ("Projektvolumen von EUR
            # 250.000.000") mask the real salary sitting beside it, and a range
            # ("3.954 € – 5.000 €") still resolves to its top because the larger
            # end simply wins the comparison below.
            if not MIN_PLAUSIBLE_ANNUAL_EUR <= value <= MAX_PLAUSIBLE_ANNUAL_EUR:
                continue  # implausible as an annual salary; don't guess
            if best is None or value > best[0]:
                snippet = window[max(0, match.start() - 80):match.end() + 80]
                best = (value, snippet.strip())
    if best is None:
        return None, None
    return best


def in_scope(job: dict, named_locations: list[str]) -> bool:
    """Keep a job only if it is in one of the named locations, or is remote.

    The country-wide search arm (the empty location) exists to reach remote and
    homeoffice ads that a city-filtered search hides. Without this check it also
    drags in every onsite ad in Linz, Graz and Salzburg -- the arm's side effect,
    not its purpose. With no named locations, everything is in scope.
    """
    wanted = [loc.strip().lower() for loc in named_locations if loc.strip()]
    if not wanted:
        return True
    if (job.get("is_remote") or "").lower() == "true":
        return True
    haystack = (job.get("location") or "").lower()
    for loc in wanted:
        for alias in LOCATION_ALIASES.get(loc, (loc,)):
            if alias in haystack:
                return True
    return False
