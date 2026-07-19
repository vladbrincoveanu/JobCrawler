#!/usr/bin/env python3
"""CV-matched job scout: query jobhive ATS dataset, score against a CV profile,
send the top matches as a Telegram message.

Default run (dry):    python scripts/scout.py --dry-run
Send to dev bot:      python scripts/scout.py
Defaults: AT (Vienna boosted) + remote EU/global, min €85k (unknown salaries kept).
Tune:                 python scripts/scout.py --min-salary 70000 --countries AT,DE --days 7 --top 8 --remote eu

Telegram credentials: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID env vars, or fallback
to immo-scouter's config.json (--telegram dev|main selects the bot there).
LLM re-ranking uses NVIDIA_API_KEY when present; otherwise keyword scoring only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import requests

JOBHIVE_BASE = "https://storage.stapply.ai/jobhive/v1"
NVIDIA_MODEL = "meta/llama-3.3-70b-instruct"  # nemotron-70b returns 404 on this account
DEFAULT_SLICES = ["eures", "personio", "recruitee", "greenhouse", "lever", "ashby",
                  "join_com", "remoteok", "weworkremotely"]
BIG_SLICES = ["workday", "successfactors", "smartrecruiters", "teamtailor", "workable"]
API_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) job-scout/1.0"}

DEFAULT_CV = Path.home() / "Documents" / "Vlad_Brincoveanu_CV_2026.pdf"
PROFILE_PATH = Path(__file__).resolve().parent.parent / "data" / "profile.json"
SENT_PATH = Path(__file__).resolve().parent.parent / "data" / "sent_jobs.json"
IMMO_CONFIG = Path.home() / "Desktop" / "Startup" / "immo-scouter" / "config.json"

# Fallback skill lexicon for profile extraction without an LLM. Weights are
# relative importance for scoring (title hits count 3x, description 1x).
SKILL_LEXICON = {
    r"\.net|dotnet": ("dotnet", 10), r"\bc#": ("csharp", 10),
    r"asp\.net": ("aspnet", 8), r"\bazure\b": ("azure", 7),
    r"\bkafka\b": ("kafka", 6), r"kubernetes|\bk8s\b": ("kubernetes", 6),
    r"\bdocker\b": ("docker", 4), r"microservice": ("microservices", 6),
    r"distributed system": ("distributed-systems", 7),
    r"\bangular\b": ("angular", 5), r"typescript": ("typescript", 4),
    r"\bpython\b": ("python", 5), r"\bsql\b|postgres|sql server": ("sql", 4),
    r"\bllm\b|large language model|\bgen(erative)? ?ai\b|\brag\b": ("ai-llm", 8),
    r"\baws\b": ("aws", 4), r"terraform": ("terraform", 3),
    r"\bci/cd\b|devops": ("devops", 4), r"tech lead|team lead": ("lead", 6),
    r"backend|back-end": ("backend", 6),
}

ROLE_TITLES = [
    ".net", "c#", "backend", "software engineer", "software developer",
    "softwareentwickler", "software-entwickler", "full stack", "fullstack",
    "tech lead", "platform engineer", "ai engineer",
]

# EURES uses NUTS region codes as locations; map the common DACH ones.
NUTS_REGIONS = {
    "AT11": "Burgenland", "AT12": "Lower Austria", "AT13": "Vienna",
    "AT21": "Carinthia", "AT22": "Styria", "AT31": "Upper Austria",
    "AT32": "Salzburg", "AT33": "Tyrol", "AT34": "Vorarlberg",
}

COUNTRY_LOCATION_PATTERNS = {
    "AT": ["austria", "österreich", "wien", "vienna", "linz", "graz", "salzburg"],
    "DE": ["germany", "deutschland", "berlin", "münchen", "munich", "hamburg", "frankfurt"],
    "CH": ["switzerland", "schweiz", "zürich", "zurich", "basel", "geneva"],
}


def log(msg: str) -> None:
    print(f"[scout] {msg}", file=sys.stderr)


def nvidia_chat(api_key: str, prompt: str, max_tokens: int) -> str:
    """One NVIDIA chat completion with a single retry on 5xx/timeouts."""
    last_exc: Exception | None = None
    for attempt in (1, 2):
        try:
            resp = requests.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": NVIDIA_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": max_tokens,
                },
                timeout=90,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt == 1:
                log(f"NVIDIA call failed ({exc}); retrying once")
    raise last_exc  # type: ignore[misc]


# --------------------------------------------------------------------------- profile

def extract_cv_text(cv_path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(cv_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def build_profile_from_lexicon(cv_text: str) -> dict:
    lower = cv_text.lower()
    skills = {}
    for pattern, (name, weight) in SKILL_LEXICON.items():
        if re.search(pattern, lower):
            skills[name] = weight
    return {"skills": skills, "role_titles": ROLE_TITLES, "source": "lexicon"}


def build_profile_with_llm(cv_text: str, api_key: str) -> dict | None:
    prompt = (
        "Extract a job-matching profile from this CV. Reply with ONLY JSON: "
        '{"skills": {"<skill>": <weight 1-10>}, "role_titles": ["<job title keyword>", ...]}. '
        "Max 20 skills, max 12 role title keywords (lowercase, substrings that would "
        "appear in matching job titles, include German variants).\n\nCV:\n" + cv_text[:12000]
    )
    try:
        text = nvidia_chat(api_key, prompt, max_tokens=800)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        profile = json.loads(match.group(0)) if match else None
        if profile and profile.get("skills"):
            profile["source"] = "llm"
            return profile
    except Exception as exc:  # noqa: BLE001 - fall back to lexicon on any failure
        log(f"LLM profile extraction failed ({exc}); using lexicon fallback")
    return None


def load_profile(cv_path: Path, rebuild: bool) -> dict:
    if PROFILE_PATH.exists() and not rebuild:
        return json.loads(PROFILE_PATH.read_text())
    log(f"building profile from {cv_path}")
    cv_text = extract_cv_text(cv_path)
    profile = None
    api_key = os.environ.get("NVIDIA_API_KEY")
    if api_key:
        profile = build_profile_with_llm(cv_text, api_key)
    if profile is None:
        profile = build_profile_from_lexicon(cv_text)
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, indent=2))
    log(f"profile saved ({profile['source']}): {len(profile['skills'])} skills")
    return profile


# --------------------------------------------------------------------------- query

def fetch_jobs(slices: list[str], countries: list[str], days: int,
               role_titles: list[str], remote: str) -> list[dict]:
    urls = [f"{JOBHIVE_BASE}/{s}/jobs.parquet" for s in slices]
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    loc_clauses = [f"country_iso = '{c}'" for c in countries]
    for c in countries:
        for pat in COUNTRY_LOCATION_PATTERNS.get(c, []):
            loc_clauses.append(f"location ILIKE '%{pat}%'")
    if remote == "eu":
        loc_clauses.append("(is_remote ILIKE '%true%' AND (location ILIKE '%europe%' OR location ILIKE '%emea%' OR location ILIKE '%eu%'))")
    elif remote == "global":
        # any remote job not explicitly restricted to the Americas/APAC
        loc_clauses.append(
            "(is_remote ILIKE '%true%' AND NOT location ILIKE '%united states%'"
            " AND NOT location ILIKE '%canada%' AND NOT location ILIKE '%latam%'"
            " AND NOT location ILIKE '%apac%' AND NOT regexp_matches(location, ', ?[A-Z]{2}, US'))"
        )
    title_clauses = " OR ".join(f"title ILIKE '%{t}%'" for t in role_titles)

    query = f"""
        SELECT url, title, company, ats_type, location, is_remote, country_iso,
               salary_min, salary_max, salary_currency, salary_period, salary_summary,
               employment_type, description, posted_at[:10] AS posted, apply_url
        FROM read_parquet({json.dumps(urls)})
        WHERE ({' OR '.join(loc_clauses)})
          AND NOT regexp_matches(location, ', ?VA\\b')      -- Vienna, Virginia
          AND NOT location ILIKE '%united states%'
          AND ({title_clauses})
          AND posted_at >= '{cutoff}'
    """
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    rows = con.execute(query).fetchall()
    cols = [d[0] for d in con.description]
    return [dict(zip(cols, r)) for r in rows]


def _api_get(url: str) -> dict | None:
    try:
        resp = requests.get(url, headers=API_UA, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001 - free APIs may flake; never block the run
        log(f"API source failed, skipping: {url.split('/')[2]} ({exc})")
        return None


def _title_matches(title: str, role_titles: list[str]) -> bool:
    lower = (title or "").lower()
    return any(rt in lower for rt in role_titles)


def fetch_free_apis(days: int, role_titles: list[str]) -> list[dict]:
    """Live free job APIs (no auth): Arbeitnow (DACH), Remotive + Jobicy (remote)."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    jobs: list[dict] = []

    def add(ats: str, title, company, location, is_remote, posted, url,
            description="", salary_summary=None, salary_min=None,
            salary_max=None, salary_currency=None):
        if not _title_matches(title, role_titles) or (posted or "") < cutoff:
            return
        jobs.append({
            "url": url, "title": title, "company": company, "ats_type": ats,
            "location": location, "is_remote": str(is_remote).lower(),
            "country_iso": None, "salary_min": salary_min, "salary_max": salary_max,
            "salary_currency": salary_currency, "salary_period": "year",
            "salary_summary": salary_summary, "employment_type": None,
            "description": description, "posted": posted, "apply_url": url,
        })

    for page in (1, 2, 3):
        data = _api_get(f"https://www.arbeitnow.com/api/job-board-api?page={page}")
        if not data:
            break
        for j in data.get("data", []):
            posted = date.fromtimestamp(j.get("created_at", 0)).isoformat()
            add("arbeitnow", j.get("title"), j.get("company_name"), j.get("location"),
                j.get("remote", False), posted, j.get("url"),
                description=re.sub(r"<[^>]+>", " ", j.get("description") or "")[:6000])

    data = _api_get("https://remotive.com/api/remote-jobs?limit=100")
    for j in (data or {}).get("jobs", []):
        add("remotive", j.get("title"), j.get("company_name"),
            j.get("candidate_required_location") or "Remote", True,
            (j.get("publication_date") or "")[:10], j.get("url"),
            description=re.sub(r"<[^>]+>", " ", j.get("description") or "")[:6000],
            salary_summary=j.get("salary") or None)

    data = _api_get("https://jobicy.com/api/v2/remote-jobs?count=50")
    for j in (data or {}).get("jobs", []):
        add("jobicy", j.get("jobTitle"), j.get("companyName"),
            j.get("jobGeo") or "Remote", True, (j.get("pubDate") or "")[:10],
            j.get("url"), description=re.sub(r"<[^>]+>", " ", j.get("jobDescription")
                                             or j.get("jobExcerpt") or "")[:6000],
            salary_min=j.get("annualSalaryMin"), salary_max=j.get("annualSalaryMax"),
            salary_currency=j.get("salaryCurrency"))

    log(f"{len(jobs)} rows from free APIs (arbeitnow/remotive/jobicy)")
    return jobs


# Region restrictions that show up in titles rather than the location field.
FOREIGN_REGION_RE = re.compile(
    r"latam|apac|\bus only\b|\bu\.s\.\b|united states|canada|india|philippines", re.IGNORECASE)

# A remote job is takeable from Austria only if its location is generic
# ("Remote", "Worldwide") or Europe-flavored; "Remote - Brazil" means hiring there.
GENERIC_REMOTE_RE = re.compile(r"^\s*(fully )?(remote|anywhere|worldwide|global)[\s!,.·-]*$",
                               re.IGNORECASE)
EU_HINT_RE = re.compile(
    r"europe|emea|\beu\b|austria|österreich|wien|vienna|german|deutschland|switzerland|schweiz"
    r"|netherlands|poland|spain|portugal|italy|france|belgium|ireland|denmark|sweden|finland"
    r"|norway|czech|slovak|hungary|romania|bulgaria|croatia|slovenia|estonia|latvia|lithuania"
    r"|greece|luxembourg|united kingdom|\buk\b", re.IGNORECASE)


def reachable_from_home(job: dict, countries: list[str]) -> bool:
    loc = job["location"] or ""
    if (job.get("country_iso") or "").upper() in countries:
        return True
    lower = loc.lower()
    for c in countries:
        if any(pat in lower for pat in COUNTRY_LOCATION_PATTERNS.get(c, [])):
            return True
    if "true" in (job.get("is_remote") or "").lower():
        return bool(GENERIC_REMOTE_RE.match(loc) or EU_HINT_RE.search(loc))
    return False


def fingerprint(job: dict) -> str:
    return hashlib.md5(
        f"{(job['company'] or '').lower()}|{(job['title'] or '').lower()}".encode()
    ).hexdigest()


def dedupe(jobs: list[dict]) -> list[dict]:
    """Collapse multi-location repostings: one entry per company+title,
    preferring an Austrian/Vienna variant, then the freshest posting."""
    def rank(job: dict) -> tuple:
        loc = (job["location"] or "").lower()
        at = any(p in loc for p in COUNTRY_LOCATION_PATTERNS["AT"]) or loc.startswith("at ")
        return (at, job["posted"] or "")

    seen: dict[str, dict] = {}
    for job in jobs:
        fp = fingerprint(job)
        prev = seen.get(fp)
        if prev is None or rank(job) > rank(prev):
            seen[fp] = job
    return list(seen.values())


def load_sent() -> dict:
    if SENT_PATH.exists():
        return json.loads(SENT_PATH.read_text())
    return {}


def save_sent(sent: dict) -> None:
    SENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SENT_PATH.write_text(json.dumps(sent, indent=2, sort_keys=True))


# --------------------------------------------------------------------------- scoring

def annual_salary_eur(job: dict) -> int | None:
    try:
        raw = job.get("salary_max") or job.get("salary_min")
        if not raw:
            return None
        value = float(re.sub(r"[^\d.]", "", str(raw)) or 0)
        if value <= 0:
            return None
        period = (job.get("salary_period") or "").lower()
        if "month" in period or (value < 15000 and "year" not in period):
            value *= 12
        elif "hour" in period:
            value *= 1720
        return int(value)
    except (ValueError, TypeError):
        return None


def score_job(job: dict, profile: dict, exclude_terms: list[str],
              extra_keywords: list[str]) -> float:
    title = (job["title"] or "").lower()
    desc = (job["description"] or "").lower()[:6000]
    if any(term in title for term in exclude_terms):
        return -1
    if FOREIGN_REGION_RE.search(f"{title} {job['location'] or ''}"):
        return -1
    score = 0.0
    for pattern, (name, weight) in SKILL_LEXICON.items():
        if name not in profile["skills"]:
            continue
        w = profile["skills"][name]
        if re.search(pattern, title):
            score += w * 3
        elif re.search(pattern, desc):
            score += w
    for kw in extra_keywords:
        if kw in title:
            score += 15
        elif kw in desc:
            score += 5
    if any(rt in title for rt in profile["role_titles"]):
        score += 10
    location = (job["location"] or "").lower()
    if "wien" in location or "vienna" in location or "at13" in location:
        score += 8  # Vienna preferred
    posted = job.get("posted") or ""
    if posted >= (date.today() - timedelta(days=3)).isoformat():
        score += 8
    elif posted >= (date.today() - timedelta(days=7)).isoformat():
        score += 4
    if annual_salary_eur(job):
        score += 5  # transparent salary is a plus
    return score


def llm_rerank(jobs: list[dict], profile: dict, api_key: str) -> None:
    """Ask the LLM for a 0-100 fit score + one-line reason for each top job.
    Mutates jobs in place; silently keeps keyword scores on failure."""
    summary = "\n".join(
        f"{i}. {j['title']} @ {j['company']} ({j['location']}) :: {(j['description'] or '')[:300]}"
        for i, j in enumerate(jobs)
    )
    prompt = (
        "Candidate skills: " + ", ".join(profile["skills"]) +
        ". Target roles: " + ", ".join(profile["role_titles"][:6]) +
        '.\nScore each job 0-100 for fit and give a short reason. Reply ONLY JSON: '
        '[{"i": <index>, "fit": <0-100>, "reason": "<max 12 words>"}]\n\nJobs:\n' + summary
    )
    try:
        text = nvidia_chat(api_key, prompt, max_tokens=1500)
        match = re.search(r"\[.*\]", text, re.DOTALL)
        for entry in json.loads(match.group(0)):
            idx = entry.get("i")
            if isinstance(idx, int) and 0 <= idx < len(jobs):
                jobs[idx]["fit"] = entry.get("fit")
                jobs[idx]["reason"] = entry.get("reason")
        jobs.sort(key=lambda j: j.get("fit") or 0, reverse=True)
        log("LLM rerank applied")
    except Exception as exc:  # noqa: BLE001
        log(f"LLM rerank skipped ({exc})")


# --------------------------------------------------------------------------- telegram

def resolve_telegram(target: str, config_path: Path) -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        return token, chat_id
    config = json.loads(config_path.read_text())
    bot = config["telegram"][f"telegram_{target}"]
    return bot["bot_token"], str(bot["chat_id"])


def esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_message(jobs: list[dict], args: argparse.Namespace) -> str:
    lines = [
        f"<b>🎯 Job Scout — top {len(jobs)} CV matches</b>",
        f"<i>{', '.join(args.countries)}"
        + (f" + remote-{args.remote}" if args.remote != "off" else "")
        + f" · last {args.days}d"
        + (f" · min €{args.min_salary:,}" if args.min_salary else "") + "</i>",
        "",
    ]
    for i, job in enumerate(jobs, 1):
        company = job["company"] or ""
        if not company or "siehe beschreibung" in company.lower():
            company = "(EURES ad — company in description)"
        salary = annual_salary_eur(job)
        location = job["location"] or "?"
        nuts = re.fullmatch(r"([A-Z]{2}) \((AT\d{3})\)", location)
        if nuts:
            location = NUTS_REGIONS.get(nuts.group(2)[:4], nuts.group(1)) + ", AT"
        parts = [f"<b>{i}. {esc(job['title'])}</b>"]
        meta = f"{esc(company)} · {esc(location)} · {job['posted'] or '?'}"
        if salary:
            meta += f" · ~€{salary:,}/yr"
        if job.get("fit") is not None:
            meta += f" · fit {job['fit']}/100"
        parts.append(meta)
        if job.get("reason"):
            parts.append(f"<i>{esc(job['reason'])}</i>")
        link = job.get("apply_url") or job.get("url")
        if link:
            parts.append(f'<a href="{esc(link)}">Apply ↗</a>')
        lines.append("\n".join(parts))
        lines.append("")
    return "\n".join(lines).strip()


def send_telegram(token: str, chat_id: str, message: str) -> None:
    # Telegram caps messages at 4096 chars; split on job boundaries.
    chunks, current = [], ""
    for block in message.split("\n\n"):
        if len(current) + len(block) + 2 > 4000:
            chunks.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}" if current else block
    chunks.append(current)
    for chunk in chunks:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=30,
        )
        if not resp.ok:
            raise RuntimeError(f"Telegram send failed: {resp.status_code} {resp.text[:200]}")
    log(f"sent {len(chunks)} Telegram message(s)")


# --------------------------------------------------------------------------- main

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--countries", default="AT",
                        help="comma-separated ISO codes: AT,DE,CH (default AT)")
    parser.add_argument("--min-salary", type=int, default=85000,
                        help="min annual EUR (default 85000); jobs with a LOWER parsed salary "
                             "are dropped (jobs without salary info are kept unless "
                             "--require-salary; 0 disables)")
    parser.add_argument("--require-salary", action="store_true",
                        help="drop jobs with no parseable salary")
    parser.add_argument("--days", type=int, default=14, help="recency window (default 14)")
    parser.add_argument("--top", type=int, default=10, help="number of jobs in the message")
    parser.add_argument("--slices", default=",".join(DEFAULT_SLICES),
                        help=f"jobhive slices; 'all' adds {','.join(BIG_SLICES)}")
    parser.add_argument("--keywords", default="", help="comma-separated boost terms")
    parser.add_argument("--exclude", default="intern,praktik,werkstudent,student",
                        help="comma-separated title terms to drop")
    parser.add_argument("--remote", choices=["off", "eu", "global"], default="global",
                        help="include remote jobs: off, eu-only, or global (default global; "
                             "global drops US/Canada/LATAM/APAC-restricted ads)")
    parser.add_argument("--cv", type=Path, default=DEFAULT_CV)
    parser.add_argument("--rebuild-profile", action="store_true",
                        help="re-extract the profile from the CV")
    parser.add_argument("--no-llm", action="store_true", help="skip LLM rerank")
    parser.add_argument("--no-apis", action="store_true",
                        help="skip live free APIs (arbeitnow, remotive, jobicy)")
    parser.add_argument("--no-dedup", action="store_true",
                        help="don't skip jobs already sent in a previous run")
    parser.add_argument("--reset-sent", action="store_true",
                        help="clear the sent-jobs history before this run")
    parser.add_argument("--telegram", choices=["dev", "main"], default="dev",
                        help="which immo-scouter bot to use (default dev)")
    parser.add_argument("--telegram-config", type=Path, default=IMMO_CONFIG)
    parser.add_argument("--dry-run", action="store_true", help="print instead of sending")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.countries = [c.strip().upper() for c in args.countries.split(",") if c.strip()]
    exclude_terms = [t.strip().lower() for t in args.exclude.split(",") if t.strip()]
    extra_keywords = [k.strip().lower() for k in args.keywords.split(",") if k.strip()]
    slices = DEFAULT_SLICES + BIG_SLICES if args.slices == "all" else \
        [s.strip() for s in args.slices.split(",") if s.strip()]

    profile = load_profile(args.cv, args.rebuild_profile)
    log(f"querying {len(slices)} slices for {args.countries}, last {args.days}d …")
    jobs = fetch_jobs(slices, args.countries, args.days,
                      profile["role_titles"], args.remote)
    log(f"{len(jobs)} raw rows from jobhive")
    if not args.no_apis:
        jobs += fetch_free_apis(args.days, profile["role_titles"])
    if args.remote != "off":
        jobs = [j for j in jobs if reachable_from_home(j, args.countries)]
        log(f"{len(jobs)} after remote-reachability filter")
    jobs = dedupe(jobs)

    if args.min_salary or args.require_salary:
        kept = []
        for job in jobs:
            salary = annual_salary_eur(job)
            if salary is None:
                if not args.require_salary:
                    kept.append(job)
            elif salary >= args.min_salary:
                kept.append(job)
        jobs = kept

    for job in jobs:
        job["score"] = score_job(job, profile, exclude_terms, extra_keywords)
    rerank_pool = max(args.top * 3, 30)
    jobs = sorted((j for j in jobs if j["score"] > 0),
                  key=lambda j: j["score"], reverse=True)[:rerank_pool]
    log(f"{len(jobs)} jobs after dedupe/filter/score")
    if not jobs:
        log("no matches — widen --days, --countries or --slices")
        return 1

    api_key = os.environ.get("NVIDIA_API_KEY")
    if api_key and not args.no_llm:
        llm_rerank(jobs, profile, api_key)

    sent = {} if args.reset_sent else load_sent()
    if not args.no_dedup:
        before = len(jobs)
        jobs = [j for j in jobs if fingerprint(j) not in sent]
        log(f"{len(jobs)} new (skipped {before - len(jobs)} already sent)")
    jobs = jobs[: args.top]

    if not jobs:
        log("no new matches since last run — nothing to send")
        return 0

    message = format_message(jobs, args)
    if args.dry_run:
        print(message)
        return 0
    token, chat_id = resolve_telegram(args.telegram, args.telegram_config)
    send_telegram(token, chat_id, message)
    today = date.today().isoformat()
    for job in jobs:
        sent[fingerprint(job)] = today
    save_sent(sent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
