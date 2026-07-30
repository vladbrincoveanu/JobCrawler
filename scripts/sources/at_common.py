"""Parsing helpers shared by the Austrian board sources (karriere.at, StepStone.at).

Both boards quote salaries the same way -- German number formatting, amount and
currency in either order, monthly figures that are paid 14x a year -- and both
need the same "is this ad actually reachable from Vienna" scope check. Keeping
one copy means a fix to the salary parser can't silently apply to only one board.

karriere_at re-exports these names, so `karriere_at.parse_salary` still works.
"""

from __future__ import annotations

import re

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")

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

LOCATION_ALIASES = {"wien": ("wien", "vienna"), "vienna": ("wien", "vienna")}


def clean(raw: str) -> str:
    """Strip tags, decode the entities these boards actually emit, squash space."""
    text = TAG_RE.sub(" ", raw or "")
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


def parse_salary(text: str) -> tuple[int | None, str | None]:
    """Best-effort annual gross EUR from an Austrian salary line.

    Returns (annual_eur, raw_snippet). For a range ("3.954 € – 5.000 €") the TOP
    of the range is used, matching how the scout treats salary_max elsewhere.
    """
    text = clean(text or "")
    if not text:
        return None, None
    amounts = [v for v in (german_number(m.group(1) or m.group(2))
                           for m in AMOUNT_RE.finditer(text)) if v]
    amounts = [v for v in amounts if v > 0]
    if not amounts:
        return None, None
    value = max(amounts)

    if MONTHLY_RE.search(text):
        value *= AT_MONTHS_PER_YEAR
    elif YEARLY_RE.search(text):
        pass
    elif value < 15000:
        # No period stated. A figure this small can only be a monthly gross.
        value *= AT_MONTHS_PER_YEAR
    if value < 10000:
        return None, None  # implausible as an annual salary; don't guess
    return value, text[:120]


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
