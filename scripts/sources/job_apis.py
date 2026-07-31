"""Key-gated job aggregator APIs: Adzuna and Jooble.

Both are free-tier but require a personal key, so both are OFF unless their env
vars are set, and a missing key is a skip with one log line -- never an error.
That is the whole reason they live behind the same `--sources` switch as the
zero-auth APIs instead of being added to `scout.fetch_free_apis()`: a scan must
still work on a fresh checkout with no credentials at all.

    Adzuna   ADZUNA_APP_ID + ADZUNA_APP_KEY   https://developer.adzuna.com
    Jooble   JOOBLE_API_KEY                   https://jooble.org/api/about

Both emit the same dict shape as `scout.fetch_free_apis()`, so rows drop
straight into the existing dedupe/score/rank pipeline with no other changes.

HONESTY NOTE: unlike karriere.at, StepStone and the zero-auth APIs, these two
mappings have NOT been exercised against a live response -- no key was available
in the environment they were written in. The field mappings follow each
provider's documented schema and are unit-tested against recorded-shape
payloads, but the first real run may still turn up a renamed field. That is the
known risk of shipping them; the alternative was leaving the two aggregators the
brief specifically asked for unimplemented.

Other candidates considered and deliberately skipped:
  RemoteOK      already covered by the `remoteok` jobhive slice, and its API
                terms require a follow backlink from the consuming site.
  TheMuse       zero-auth and live, but overwhelmingly US postings; almost
                everything it returns dies in `reachable_from_home()`.
  Arbeitsagentur (BA) Jobsuche
                zero-auth and live, but it is the *German* federal agency: a
                "Wien" search returns Kaiserslautern. Austrian coverage is nil,
                and its list endpoint carries no description to score against.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date, timedelta

import requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) job-scout/1.0"}
TIMEOUT = 25

ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs"
JOOBLE_BASE = "https://jooble.org/api"

# Adzuna is per-country; these are the ones this scout's --countries can mean.
ADZUNA_COUNTRIES = {"AT": "at", "DE": "de", "CH": "ch"}


def log(msg: str) -> None:
    print(f"[job-apis] {msg}", file=sys.stderr)


def _strip_html(text: str | None) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _row(*, ats: str, title, company, location, is_remote, posted, url,
         description="", salary_min=None, salary_max=None,
         salary_summary=None) -> dict:
    """The scout's job-dict shape. Kept in one place so both providers agree."""
    return {
        "url": url, "title": title, "company": company, "ats_type": ats,
        "location": location, "is_remote": str(bool(is_remote)).lower(),
        "country_iso": None,
        "salary_min": salary_min, "salary_max": salary_max,
        "salary_currency": "EUR" if (salary_min or salary_max) else None,
        "salary_period": "year" if (salary_min or salary_max) else None,
        "salary_summary": salary_summary, "employment_type": None,
        "description": description[:6000], "posted": posted, "apply_url": url,
    }


# --------------------------------------------------------------------- adzuna

def fetch_adzuna(terms: list[str], countries: list[str], days: int,
                 max_pages: int = 2, results_per_page: int = 50) -> list[dict]:
    """Adzuna search, one request per (country, term, page).

    Adzuna returns `salary_min`/`salary_max` as annual floats already in the
    country's currency, which is why they are passed through without the
    monthly/14x reasoning the Austrian board scrapers need.
    """
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        log("adzuna skipped (set ADZUNA_APP_ID + ADZUNA_APP_KEY to enable)")
        return []

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    jobs: list[dict] = []
    for country in countries:
        code = ADZUNA_COUNTRIES.get(country.upper())
        if not code:
            continue
        for term in terms:
            for page in range(1, max_pages + 1):
                data = _get_json(
                    f"{ADZUNA_BASE}/{code}/search/{page}",
                    params={
                        "app_id": app_id, "app_key": app_key,
                        "results_per_page": results_per_page,
                        "what": term, "max_days_old": days,
                        "content-type": "application/json",
                    })
                results = (data or {}).get("results") or []
                for j in results:
                    posted = (j.get("created") or "")[:10]
                    if posted and posted < cutoff:
                        continue
                    jobs.append(_row(
                        ats="adzuna",
                        title=j.get("title"),
                        company=(j.get("company") or {}).get("display_name"),
                        location=(j.get("location") or {}).get("display_name"),
                        is_remote=False,
                        posted=posted or None,
                        url=j.get("redirect_url"),
                        description=_strip_html(j.get("description")),
                        salary_min=_as_int(j.get("salary_min")),
                        salary_max=_as_int(j.get("salary_max")),
                    ))
                if len(results) < results_per_page:
                    break  # last page for this term
    log(f"{len(jobs)} rows from adzuna ({', '.join(countries)})")
    return jobs


# --------------------------------------------------------------------- jooble

def fetch_jooble(terms: list[str], locations: list[str], days: int,
                 max_pages: int = 2) -> list[dict]:
    """Jooble search. POST-only API: the key is part of the path, not a header."""
    api_key = os.environ.get("JOOBLE_API_KEY")
    if not api_key:
        log("jooble skipped (set JOOBLE_API_KEY to enable)")
        return []

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    jobs: list[dict] = []
    for term in terms:
        for location in locations or [""]:
            for page in range(1, max_pages + 1):
                data = _post_json(f"{JOOBLE_BASE}/{api_key}",
                                  {"keywords": term, "location": location,
                                   "page": page})
                results = (data or {}).get("jobs") or []
                for j in results:
                    posted = (j.get("updated") or "")[:10]
                    if posted and posted < cutoff:
                        continue
                    jobs.append(_row(
                        ats="jooble",
                        title=j.get("title"),
                        company=j.get("company"),
                        location=j.get("location"),
                        # Jooble has no remote flag; the type string is the only hint.
                        is_remote="remote" in (j.get("type") or "").lower(),
                        posted=posted or None,
                        url=j.get("link"),
                        description=_strip_html(j.get("snippet")),
                        # Jooble's salary is free text ("€ 50.000 - 70.000/Jahr"),
                        # not a number, so it goes through as a summary and the
                        # scout's own parser decides what it means.
                        salary_summary=(j.get("salary") or None),
                    ))
                if not results:
                    break
    log(f"{len(jobs)} rows from jooble")
    return jobs


# ---------------------------------------------------------------------- http

def _as_int(value) -> int | None:
    try:
        return int(float(value)) if value else None
    except (TypeError, ValueError):
        return None


def _get_json(url: str, params: dict) -> dict | None:
    try:
        resp = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001 - one bad query must not kill the run
        log(f"GET failed, skipping ({exc}): {url}")
        return None


def _post_json(url: str, payload: dict) -> dict | None:
    try:
        resp = requests.post(url, json=payload, headers=UA, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        log(f"POST failed, skipping ({exc}): {url.rsplit('/', 1)[0]}/<key>")
        return None
