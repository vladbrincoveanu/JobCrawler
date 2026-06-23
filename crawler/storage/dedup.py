"""Content-hash based dedup for upsert.

Stable fields only (title, company, location). Aggressive normalize:
  - lowercase
  - collapse whitespace
  - strip punctuation
  - remove city suffixes from company (e.g. "ams wien" -> "ams")
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

import psycopg

_WHITESPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9\s]")


def normalize(value: str | None) -> str:
    if not value:
        return ""
    # NFKD strip accents
    nfkd = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    lower = ascii_only.lower()
    no_punct = _NON_ALNUM.sub(" ", lower)
    return _WHITESPACE.sub(" ", no_punct).strip()


def content_hash(title: str | None, company: str | None, location: str | None) -> str:
    """SHA256 over normalized stable fields."""
    parts = [normalize(title), normalize(company), normalize(location)]
    blob = "|".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def find_by_hash(conn: psycopg.Connection, hash_value: str) -> dict | None:
    """Return existing job row with this content_hash, or None."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, source, source_id, url, title, company, location, "
            "description, content_hash, first_seen_at, last_seen_at "
            "FROM jobs WHERE content_hash = %s LIMIT 1",
            (hash_value,),
        )
        return cur.fetchone()
