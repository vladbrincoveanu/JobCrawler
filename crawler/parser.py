"""Generic HTML/JSON parsing helpers. Per-source logic lives in sources/*.py."""
import json
import re
from datetime import datetime
from typing import Any
from bs4 import BeautifulSoup
from crawler.exceptions import SchemaChanged, MissingField


def select_text(soup: BeautifulSoup, selector: str, *, required: bool = False) -> str | None:
    el = soup.select_one(selector)
    if el is None:
        if required:
            raise MissingField(f"selector {selector!r} not found")
        return None
    return el.get_text(strip=True)


def select_attr(soup: BeautifulSoup, selector: str, attr: str) -> str | None:
    el = soup.select_one(selector)
    return el.get(attr) if el else None


def extract_jsonld(html: str) -> dict[str, Any]:
    """Extract first JSON-LD block. Raise SchemaChanged on absence."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
        except json.JSONDecodeError as e:
            raise SchemaChanged(f"JSON-LD parse error: {e}") from e
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    raise SchemaChanged("no JobPosting JSON-LD found")


def parse_iso_date(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    # Normalize "Z" → "+00:00" for fromisoformat
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError as e:
        raise SchemaChanged(f"invalid ISO date {s!r}: {e}") from e