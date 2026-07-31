"""Company pros/cons to show next to a match.

Where this does NOT come from: Glassdoor, kununu, Indeed reviews, or any other
review site. All of them forbid scraping in their terms and put their review
pages behind bot walls, so there is no polite automated way in -- the same
verdict this project already reached for devjobs.at and metajob.at.

What it does instead: asks a language model what is generally said about
working at the company, from its training data. That is genuinely useful as a
"what should I look into before applying" prompt and genuinely NOT a source of
fact -- it can be out of date, and for a small company the model may know
nothing and invent something plausible. Two guards against the second failure:
the prompt makes "I don't know this company" an explicit, easy answer, and
every stored record carries `source` so the UI can caveat it. The dashboard
prints that caveat verbatim next to the pros and cons.

Results are cached on disk per company, because the answer changes on the
scale of months and a scan may see the same employer in twenty ads.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "company_reviews"
# Employer reputation is not a fast-moving quantity, and a re-ask costs an LLM
# call per company. Refresh quarterly.
CACHE_TTL_SECONDS = 90 * 24 * 3600
MAX_ITEMS = 5

PROMPT = (
    "What is it like to work at the company below, according to what employees "
    "generally report (Glassdoor/kununu-style pros and cons)?\n\n"
    "Company: {company}\n\n"
    'Reply with ONLY JSON: {{"known": true|false, "pros": ["..."], '
    '"cons": ["..."], "summary": "one sentence"}}\n'
    "Rules:\n"
    '- If you do not actually recognise this specific company, reply exactly '
    '{{"known": false, "pros": [], "cons": [], "summary": ""}}. Do not guess, '
    "and do not describe a different company with a similar name.\n"
    f"- At most {MAX_ITEMS} pros and {MAX_ITEMS} cons, each a short phrase.\n"
    "- Report what employees say, including the negatives. A list with no cons "
    "is not credible.\n"
)


def _slug(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", company.strip().lower()).strip("-")[:80]


def _resolve_dir(cache_dir: Path | None) -> Path:
    """Resolved per call, never as a default argument value: a default binds
    CACHE_DIR at import time, which made a test that monkeypatched the module
    attribute write to the real data/company_reviews/ instead of its tmp_path.
    """
    return cache_dir if cache_dir is not None else CACHE_DIR


def cache_path(company: str, cache_dir: Path | None = None) -> Path:
    return _resolve_dir(cache_dir) / f"{_slug(company)}.json"


def load_cached(company: str, cache_dir: Path | None = None,
                now: float | None = None) -> dict | None:
    """Cached record for `company`, or None when absent or past its TTL."""
    path = cache_path(company, cache_dir)
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    age = (now if now is not None else time.time()) - record.get("cached_at", 0)
    if age > CACHE_TTL_SECONDS:
        return None
    return record


def _parse(text: str, company: str, model: str, now: float) -> dict | None:
    """Turn a model reply into a record, or None if it disclaimed knowledge."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not data.get("known"):
        return None
    pros = [str(p).strip() for p in (data.get("pros") or []) if str(p).strip()]
    cons = [str(c).strip() for c in (data.get("cons") or []) if str(c).strip()]
    # "known: true" with nothing to say is the model hedging; treat it as a
    # miss rather than rendering an empty pros/cons panel that implies the
    # company was researched and found unremarkable.
    if not pros and not cons:
        return None
    return {
        "company": company,
        "pros": pros[:MAX_ITEMS],
        "cons": cons[:MAX_ITEMS],
        "summary": str(data.get("summary") or "").strip(),
        "source": f"llm:{model}",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
        "cached_at": now,
    }


def fetch_review(company: str, chat, model: str, *, cache_dir: Path | None = None,
                 now: float | None = None, log=lambda _m: None) -> dict | None:
    """Cached-or-fetched review record for one company.

    `chat` is a callable taking the prompt and returning the model's text --
    injected rather than imported so this module has no opinion about which
    provider is in play, and so tests never touch the network.
    """
    company = (company or "").strip()
    if not company:
        return None
    now = now if now is not None else time.time()
    cache_dir = _resolve_dir(cache_dir)

    cached = load_cached(company, cache_dir, now)
    if cached is not None:
        return cached if cached.get("pros") or cached.get("cons") else None

    try:
        text = chat(PROMPT.format(company=company))
    except Exception as exc:  # noqa: BLE001 - enrichment must never fail a scan
        log(f"company review lookup failed for {company!r} ({exc})")
        return None

    record = _parse(text, company, model, now)
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Negative results are cached too, as an empty record: without this, every
    # scan re-asks the model about the same unknown small company forever.
    to_store = record or {
        "company": company, "pros": [], "cons": [], "summary": "",
        "source": f"llm:{model}", "generated_at": "", "cached_at": now,
    }
    try:
        cache_path(company, cache_dir).write_text(json.dumps(to_store, indent=2))
    except OSError as exc:
        log(f"could not cache review for {company!r} ({exc})")
    return record


def annotate(jobs: list[dict], chat, model: str, *, limit: int = 20,
             cache_dir: Path | None = None, log=lambda _m: None) -> int:
    """Attach `company_review` to `jobs`, newest-uncached companies first.

    `limit` caps how many DISTINCT companies are looked up in one run, not how
    many jobs are annotated: every job at an already-resolved company gets the
    record for free. Returns the number of jobs annotated.
    """
    reviews: dict[str, dict | None] = {}
    annotated = 0
    for job in jobs:
        company = (job.get("company") or "").strip()
        if not company:
            continue
        key = _slug(company)
        if key not in reviews:
            if len(reviews) >= limit:
                continue
            reviews[key] = fetch_review(company, chat, model,
                                        cache_dir=cache_dir, log=log)
        if reviews[key]:
            job["company_review"] = reviews[key]
            annotated += 1
    log(f"company reviews: {annotated} jobs annotated from "
        f"{sum(1 for r in reviews.values() if r)}/{len(reviews)} companies")
    return annotated
