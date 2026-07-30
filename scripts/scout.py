#!/usr/bin/env python3
"""CV-matched job scout: pull jobs from the jobhive ATS dataset, free remote-job
APIs, karriere.at and StepStone.at, score them against a CV profile, and send the
top matches as a Telegram message.

Default run (dry):    python scripts/scout.py --dry-run
Send to dev bot:      python scripts/scout.py
Defaults: AT (Vienna boosted) + remote EU/global, min €85k (unknown salaries kept),
top 5, never resends a job already delivered. Dashboard: data/dashboard.html
(regenerated on every send — open it directly in a browser, no server needed).
Tune:                 python scripts/scout.py --min-salary 70000 --countries AT,DE --days 7 --top 8 --remote eu

Sources (--sources, default all four):
  jobhive    international ATS parquet slices (needs duckdb)
  apis       arbeitnow / remotive / jobicy
  karriere   karriere.at, Austria's largest board — Wien + Austria-wide remote
  stepstone  StepStone.at — same coverage area, listing-only (detail pages are
             WAF-blocked, so these rows carry a teaser instead of a full ad text
             and almost never a salary)

CV buckets: every job is tagged with WHICH of the four CV variants to send,
scored against the keyword files in career/Resume/JOB-SEARCH/keywords/ (the same
files kwcount.py audits the CVs against). See data/buckets.json.
  Only bucket C, karriere.at only:
      python scripts/scout.py --dry-run --sources karriere --buckets C

Note: Austrian ads commonly quote €45–70k gross. The default --min-salary 85000
therefore drops most karriere.at rows that state a salary (ads with no salary are
still kept). Lower it to see the Austrian mid-market.

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
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import buckets as buckets_mod  # noqa: E402
from sources import karriere_at, stepstone_at  # noqa: E402

JOBHIVE_BASE = "https://storage.stapply.ai/jobhive/v1"
NVIDIA_MODEL = "meta/llama-3.3-70b-instruct"  # nemotron-70b returns 404 on this account
DEFAULT_SLICES = ["eures", "personio", "recruitee", "greenhouse", "lever", "ashby",
                  "join_com", "remoteok", "weworkremotely", "smartrecruiters",
                  "teamtailor", "workable", "jobsch", "bundesagentur"]
BIG_SLICES = ["workday", "successfactors"]  # huge (684k/290k rows) — opt in via --slices all
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
    # Imported here, not at module scope: duckdb is only needed for the jobhive
    # parquet slices, so `--sources karriere` runs without it installed.
    import duckdb

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
    r"|netherlands|poland|spain|portugal|italy|france|belgium|denmark|sweden|finland"
    r"|norway|czech|slovak|hungary|romania|bulgaria|croatia|slovenia|estonia|latvia|lithuania"
    r"|greece|luxembourg", re.IGNORECASE)
# UK/Ireland deliberately excluded from the generic EU hint: "remote, UK" or
# "remote, Ireland" almost always means UK/IE work authorization required,
# not free movement — the false positive that let "Zilch UK" through.
UK_ONLY_RE = re.compile(r"\bu\.?k\.?\b|united kingdom|\bireland\b", re.IGNORECASE)


def reachable_from_home(job: dict, countries: list[str]) -> bool:
    loc = job["location"] or ""
    if (job.get("country_iso") or "").upper() in countries:
        return True
    lower = loc.lower()
    for c in countries:
        if any(pat in lower for pat in COUNTRY_LOCATION_PATTERNS.get(c, [])):
            return True
    if "true" in (job.get("is_remote") or "").lower():
        if UK_ONLY_RE.search(loc) and not EU_HINT_RE.search(loc.replace("uk", "")):
            return False
        return bool(GENERIC_REMOTE_RE.match(loc) or EU_HINT_RE.search(loc))
    return False


GENDER_MARKER_RE = re.compile(r"\(?\b[mwfdx](?:\s*/\s*[mwfdx]){1,3}\)?", re.IGNORECASE)


def normalize_title(title: str) -> str:
    t = GENDER_MARKER_RE.sub(" ", (title or "").lower())
    t = re.sub(r"[^a-z0-9äöüß]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def fingerprint(job: dict) -> str:
    company = re.sub(r"\s+", " ", (job["company"] or "").strip().lower())
    return hashlib.md5(f"{company}|{normalize_title(job['title'])}".encode()).hexdigest()


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

DASHBOARD_PATH = Path(__file__).resolve().parent.parent / "data" / "dashboard.html"


def generate_dashboard(sent: dict) -> None:
    """Simplest possible dashboard: one static HTML file, no server.
    Open data/dashboard.html directly in a browser."""
    def esc(text) -> str:
        return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    def row(rec) -> str:
        if not isinstance(rec, dict):  # legacy entries from before the dashboard existed
            return f"<tr><td>{esc(rec)}</td><td colspan=9>(sent before dashboard tracking started)</td></tr>"
        link = f'<a href="{esc(rec["apply_url"])}" target="_blank">apply</a>' if rec.get("apply_url") else ""
        salary = f"€{rec['salary']:,}" if isinstance(rec.get("salary"), int) else esc(rec.get("salary"))
        bucket = esc(rec.get("bucket"))
        if bucket and rec.get("bucket_fit") != "":
            bucket = f"{bucket} <span class=dim>{esc(rec.get('bucket_fit'))}%</span>"
        return (f"<tr><td>{esc(rec.get('sent_date'))}</td><td>{esc(rec.get('title'))}</td>"
                f"<td>{esc(rec.get('company'))}</td><td>{esc(rec.get('location'))}</td>"
                f"<td>{salary}</td><td>{bucket}</td><td>{esc(rec.get('source'))}</td>"
                f"<td>{esc(rec.get('fit'))}</td>"
                f"<td>{esc(rec.get('posted'))}</td><td>{link}</td></tr>")

    ordered = sorted(sent.items(),
                     key=lambda kv: kv[1].get("sent_date", "") if isinstance(kv[1], dict) else str(kv[1]),
                     reverse=True)
    rows_html = "\n".join(row(rec) for _, rec in ordered)
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Job Scout — sent history</title>
<style>
body{{font-family:-apple-system,Segoe UI,sans-serif;background:#0b0d10;color:#e6e6e6;padding:24px}}
h1{{font-size:18px;margin:0 0 4px}} .meta{{color:#888;margin-bottom:16px;font-size:13px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{padding:6px 10px;border-bottom:1px solid #222;text-align:left;vertical-align:top}}
th{{color:#9ab;position:sticky;top:0;background:#0b0d10}}
tr:hover{{background:#151a20}} a{{color:#7dc4ff;text-decoration:none}}
.dim{{color:#888}}
</style></head><body>
<h1>Job Scout — sent history</h1>
<div class="meta">{len(sent)} jobs ever sent · generated {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
<table><thead><tr><th>Sent</th><th>Title</th><th>Company</th><th>Location</th>
<th>Salary</th><th>CV</th><th>Source</th><th>Fit</th><th>Posted</th><th></th></tr></thead>
<tbody>{rows_html}</tbody></table>
</body></html>"""
    DASHBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_PATH.write_text(html)
    log(f"dashboard: file://{DASHBOARD_PATH}")


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
        if job.get("bucket"):
            parts.append(f"📄 send <b>{esc(job['bucket'])}</b> — "
                         f"{esc(job['bucket_label'])} ({job['bucket_fit']}%)")
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
    parser.add_argument("--top", type=int, default=5, help="number of jobs in the message (default 5)")
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
    parser.add_argument("--sources", default="jobhive,apis,karriere,stepstone",
                        help="comma-separated: jobhive, apis, karriere, stepstone "
                             "(default all)")
    parser.add_argument("--buckets", default="",
                        help="restrict CV variants, e.g. A,C (default: all in "
                             "data/buckets.json)")
    parser.add_argument("--karriere-locations", default="wien,",
                        help="karriere.at location slugs; an empty entry means "
                             "Austria-wide, which is how remote ads are reached "
                             "(default 'wien,' = Wien + Austria-wide)")
    parser.add_argument("--karriere-max-detail", type=int, default=60,
                        help="max karriere.at detail pages to fetch for "
                             "descriptions/salary (default 60)")
    parser.add_argument("--stepstone-locations", default="wien,",
                        help="StepStone.at location slugs; an empty entry means "
                             "Austria-wide, which is how remote ads are reached "
                             "(default 'wien,' = Wien + Austria-wide)")
    parser.add_argument("--stepstone-pages", type=int, default=3,
                        help="max StepStone.at result pages per search term "
                             "(25 ads a page; default 3)")
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

    sources = {s.strip().lower() for s in args.sources.split(",") if s.strip()}
    bucket_filter = [b.strip().upper() for b in args.buckets.split(",") if b.strip()]
    cv_buckets = buckets_mod.load_buckets(only=bucket_filter or None)

    profile = load_profile(args.cv, args.rebuild_profile)
    jobs: list[dict] = []

    if "jobhive" in sources:
        log(f"querying {len(slices)} slices for {args.countries}, last {args.days}d …")
        jobs += fetch_jobs(slices, args.countries, args.days,
                           profile["role_titles"], args.remote)
        log(f"{len(jobs)} raw rows from jobhive")
    if "apis" in sources and not args.no_apis:
        jobs += fetch_free_apis(args.days, profile["role_titles"])
    if "karriere" in sources:
        # Locations are split without dropping empties: a trailing comma in
        # "wien," is the deliberate Austria-wide arm, not a typo.
        locations = [loc.strip() for loc in args.karriere_locations.split(",")]
        jobs += karriere_at.fetch(
            buckets_mod.all_search_terms(cv_buckets), locations,
            days=args.days, max_detail=args.karriere_max_detail)
    if "stepstone" in sources:
        # Same trailing-comma convention as --karriere-locations: the empty entry
        # is the deliberate Austria-wide arm, not a typo.
        locations = [loc.strip() for loc in args.stepstone_locations.split(",")]
        jobs += stepstone_at.fetch(
            buckets_mod.all_search_terms(cv_buckets), locations,
            days=args.days, max_pages=args.stepstone_pages)
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

    buckets_mod.annotate(jobs, cv_buckets)
    for job in jobs:
        job["score"] = score_job(job, profile, exclude_terms, extra_keywords)
    jobs = sorted((j for j in jobs if j["score"] > 0), key=lambda j: j["score"], reverse=True)
    log(f"{len(jobs)} jobs after dedupe/filter/score")

    sent = {} if args.reset_sent else load_sent()
    if not args.no_dedup:
        before = len(jobs)
        jobs = [j for j in jobs if fingerprint(j) not in sent]
        log(f"{len(jobs)} new (skipped {before - len(jobs)} already sent)")

    rerank_pool = max(args.top * 4, 20)
    jobs = jobs[:rerank_pool]
    if not jobs:
        log("no new matches since last run — nothing to send")
        return 0

    api_key = os.environ.get("NVIDIA_API_KEY")
    if api_key and not args.no_llm:
        llm_rerank(jobs, profile, api_key)
    jobs = jobs[: args.top]

    message = format_message(jobs, args)
    if args.dry_run:
        print(message)
        return 0
    token, chat_id = resolve_telegram(args.telegram, args.telegram_config)
    send_telegram(token, chat_id, message)
    today = date.today().isoformat()
    for job in jobs:
        sent[fingerprint(job)] = {
            "sent_date": today, "title": job["title"],
            "company": ("(EURES — see ad)" if (job["company"] or "").lower().startswith("siehe")
                       else job["company"]),
            "location": job.get("location") or "", "posted": job.get("posted") or "",
            "salary": annual_salary_eur(job) or job.get("salary_summary") or "",
            "fit": job.get("fit", ""), "apply_url": job.get("apply_url") or job.get("url") or "",
            "source": job.get("ats_type") or "",
            "bucket": job.get("bucket") or "", "bucket_fit": job.get("bucket_fit", ""),
        }
    save_sent(sent)
    generate_dashboard(sent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
