---
title: JobCrawler Sub-Project 1 — Crawler + Storage (AMS)
date: 2026-06-22
status: approved
ui_scope: false
graph_scope: false
test_scope: true
---

# JobCrawler Sub-Project 1: Crawler + Storage — Design Spec

**Date:** 2026-06-22
**Status:** Approved (AMS Playwright pivot)
**Scope:** Sub-project 1 of 4 (see [§ Scope](#scope))

## Goal

Fetch raw job listings from AMS (Austrian Public Employment Service) and persist them to a local SQLite database. CLI-driven, no scheduler, no enrichment, no dashboard. Pipeline + storage proven on a single source before adding more.

## Scope

Sub-project 1 ships:
- AMS source adapter (Playwright browser, anti-bot aware, cookie-managed)
- SourceAdapter Protocol contract
- Per-source parser, browser wrapper (Playwright, AMS), HTTP client (httpx, future sources)
- SQLite storage (jobs, sources, crawl_runs, crawl_errors, schema_version)
- Dedup via `(source, source_id)` UNIQUE + `content_hash` index
- CLI entry: `scripts/crawl.py`
- Test pyramid: unit + contract + integration (fixtures) + manual smoke
- Operator-facing error logging, circuit breaker, graceful shutdown

Out of scope (own sub-projects, see [§ Deferred](#deferred--out-of-scope)):
- Karriere.at, Willhaben.at/jobs, LinkedIn (sub-projects 1.1, 1.2, 1.3+)
- Enrichment (sub-project 2): company lookup, financial distress, employee reviews
- Dashboard (sub-project 3): Next.js UI
- Scheduler (sub-project 4): cron/UI-trigger, remote alerts, checkpoint/resume

## Architecture

```
scripts/crawl.py        CLI entry (argparse, asyncio.run)
        │
        ▼
crawler/pipeline.py     Orchestrator: per-source run_source() with timeout + try/except
        │
        ├─► crawler/sources/ams.py   implements SourceAdapter (Playwright browser)
        │       │
        │       ├─► crawler/browser.py  Playwright wrapper: cookie store, UA pool, SPA wait, anti-bot detect
        │       └─► crawler/parser.py  HTML → NormalizedJob (selector-based)
        │
        ├─► crawler/sources/<future>  future sources (Karriere.at → crawler/http.py + parser.py)
        │
        └─► crawler/storage/repository.py  upsert_job, log_error, finalize_run
                │
                ▼
        crawler/storage/db.py  WAL-mode SQLite connection
                │
                ▼
        data/jobs.db  (gitignored)
```

Stack: **Python 3.12+**, **httpx** (async HTTP — future sources: Karriere.at, Willhaben), **playwright** (async browser — AMS), **pydantic v2** (validation), **sqlite3** stdlib, **pytest** + **pytest-asyncio** + **freezegun** + **pytest-playwright** (browser fixtures), **respx** or httpx `MockTransport` for non-browser fixtures.

## Components

### Directory layout

```
jobcrawler/
  crawler/
    __init__.py
    config.py              # named constants (see § Configuration)
    exceptions.py          # CrawlerError hierarchy
    http.py                # httpx async client (UA pool, throttle, retry, backoff) — future sources
    browser.py             # Playwright wrapper: cookie store, UA pool, SPA wait, anti-bot detect — AMS
                            #   + BrowserContext Protocol, PlaywrightBrowserContext (real), FakeBrowserContext (test)
    models.py              # pydantic: JobQuery, RawJob, NormalizedJob
    parser.py              # generic HTML/JSON parsing helpers (per-source logic lives in sources/*.py)
    pipeline.py            # orchestrator: run_source(), run()
    sources/
      __init__.py
      base.py              # SourceAdapter Protocol
      ams.py               # AMS adapter (Playwright)
    storage/
      __init__.py
      db.py                # connect() with PRAGMAs
      schema.sql           # tables + indexes
      repository.py        # CRUD: upsert_job, get_by_hash, list_jobs, log_error
      dedup.py             # normalize() + content_hash()
      migrations.py        # schema_version table + apply()
  scripts/
    crawl.py               # CLI: argparse + asyncio.run
    inspect_db.py          # debug: counts, schema, sample rows
    record_fixtures.py     # one-shot: capture live AMS HTML to tests/fixtures/
  tests/
    unit/
      test_ams_parser.py           # HTML selector parsing
      test_browser_anti_bot.py     # captcha/403 detection
      test_browser_session.py      # SM2_SESSION persist + refresh
      test_dedup.py
      test_http_retry.py
      test_repository.py
      test_config.py
    contract/
      test_source_adapter.py
    integration/
      test_crawl_ams.py            # AMS pipeline vs recorded HTML fixtures via FakeBrowserContext (no Playwright in CI)
      test_crawl_partial.py
      test_crawl_dry_run.py
    fixtures/
      ams_search_page.html
      ams_detail_page.html
      ams_empty_results.html
      ams_malformed.html
      ams_captcha.html             # anti-bot signal
  data/                    # gitignored: jobs.db, session_ams.json
  docs/superpowers/specs/
  pyproject.toml
  README.md
  .env.example
```

### Module contracts

`crawler/sources/base.py`:

```python
from typing import AsyncIterator, Protocol
from crawler.models import JobQuery, RawJob, NormalizedJob

class SourceAdapter(Protocol):
    name: str
    async def search(self, query: JobQuery) -> AsyncIterator[RawJob]: ...
    async def fetch_detail(self, raw: RawJob) -> NormalizedJob: ...
```

`crawler/models.py`:

```python
from datetime import datetime
from pydantic import BaseModel, HttpUrl, Field

class JobQuery(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    location: str | None = None
    max_results: int = 100
    since: datetime | None = None  # posted_at filter

class RawJob(BaseModel):
    source: str
    source_id: str
    url: HttpUrl
    title: str
    company: str | None = None
    location: str | None = None
    posted_at: datetime | None = None
    fetched_at: datetime

class NormalizedJob(BaseModel):
    source: str
    source_id: str
    url: HttpUrl
    title: str
    company: str
    location: str
    description: str
    salary: str | None = None
    employment_type: str | None = None
    posted_at: datetime | None = None
    content_hash: str  # SHA256 hex, stable-fields canonical
    fetched_at: datetime
```

### SourceAdapter contract guarantees

- `search()` yields `RawJob` objects, never raises `CrawlerError` subclasses silently — only typed exceptions
- `fetch_detail()` raises `ParseError.SchemaChanged` if required fields missing or response shape unexpected
- Returns empty iterator on no results (does not raise)
- All async methods are cancellation-safe (`asyncio.CancelledError` propagates cleanly)
- Browser-backed adapters (AMS): one browser context per `run_source()`, closed on completion/exception/cancellation; per-source session state isolated from other sources

### Module Design Blocks

### Module: `crawler.pipeline`
- **Responsibility:** Orchestrate per-source crawl runs with timeout, error containment, and circuit breaker.
- **Interface:** `async run(adapters, query, run_id) -> list[SourceResult]`; `async run_source(adapter, query, run_id) -> SourceResult`
- **Dependencies:** adapters, repository, circuit breaker state, asyncio
- **Size target:** ~150 lines

### Module: `crawler.sources.base`
- **Responsibility:** Define `SourceAdapter` Protocol and shared adapter utilities.
- **Interface:** `class SourceAdapter(Protocol)` with `name`, `search()`, `fetch_detail()`
- **Dependencies:** `crawler.models`
- **Size target:** ~50 lines

### Module: `crawler.sources.ams`
- **Responsibility:** AMS adapter — navigate SPA via Playwright, extract job listings + details.
- **Interface:** `class AmsAdapter: implements SourceAdapter`; constructor takes injectable `BrowserContext` (DI for tests)
- **Dependencies:** `crawler.browser`, `crawler.parser`, `crawler.exceptions`
- **Size target:** ~200 lines

### Module: `crawler.browser`
- **Responsibility:** Playwright wrapper — cookie store, UA pool, SPA wait, anti-bot detection. Defines `BrowserContext` Protocol + real/test implementations.
- **Interface:** `class BrowserContext(Protocol)`; `class PlaywrightBrowserContext` (real impl, `async with`-managed); `class FakeBrowserContext` (test impl in same module, returns fixture HTML); methods: `goto(url, wait_selector)`, `extract_html()`, `cookies`
- **Dependencies:** `playwright.async_api`, `crawler.exceptions`, `crawler.config`
- **Size target:** ~300 lines (incl. FakeBrowserContext)

### Module: `crawler.http` (future sources)
- **Responsibility:** Shared httpx async client — UA pool, throttle, retry, backoff.
- **Interface:** `class HttpClient: async with`-managed; methods: `get(url)`, `head(url)`
- **Dependencies:** `httpx`, `crawler.exceptions`
- **Size target:** ~150 lines

### Module: `crawler.parser`
- **Responsibility:** Generic HTML/JSON parsing helpers + selector utilities. Per-source DOM extraction lives in `sources/*.py`.
- **Interface:** `select_text(soup, selector)`, `select_attr(soup, selector, attr)`, `extract_jsonld(html)`, `parse_iso_date(s)`
- **Dependencies:** `beautifulsoup4`, `crawler.models`, `crawler.exceptions`
- **Size target:** ~150 lines

### Module: `crawler.storage.repository`
- **Responsibility:** CRUD operations on jobs + crawl_runs + crawl_errors. Upsert with dedup.
- **Interface:** `upsert_job(job) -> Literal["inserted", "updated"]`, `log_error(run_id, source, url, type, msg)`, `finalize_run(run_id, status, counters)`, `get_by_hash(hash)`, `list_jobs(...)`
- **Dependencies:** `crawler.storage.db`, `crawler.models`
- **Size target:** ~200 lines

### Module: `crawler.storage.db`
- **Responsibility:** SQLite connection factory with WAL + busy_timeout PRAGMAs.
- **Interface:** `connect(path) -> Connection`, `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`, `PRAGMA foreign_keys=ON`, `PRAGMA busy_timeout=30000`
- **Dependencies:** `sqlite3` stdlib
- **Size target:** ~50 lines

### Module: `crawler.storage.dedup`
- **Responsibility:** Canonical normalization + content hash for cross-source dedup.
- **Interface:** `normalize(s) -> str`, `content_hash(title, company, location) -> str` (SHA256 hex)
- **Dependencies:** stdlib only
- **Size target:** ~100 lines

### Module: `crawler.storage.migrations`
- **Responsibility:** Schema versioning + apply on startup. Idempotent.
- **Interface:** `apply(conn) -> None` — checks `schema_version`, applies pending migrations from `schema.sql`
- **Dependencies:** `crawler.storage.db`
- **Size target:** ~80 lines

### Module: `crawler.config`
- **Responsibility:** Named constants for concurrency, retry, circuit breaker, browser, DB.
- **Interface:** constants only (no functions)
- **Dependencies:** stdlib only
- **Size target:** ~80 lines

### Module: `crawler.exceptions`
- **Responsibility:** Typed exception hierarchy (see § Error Handling).
- **Interface:** exception classes only
- **Dependencies:** stdlib only
- **Size target:** ~80 lines

### Module: `scripts.crawl`
- **Responsibility:** CLI entry — argparse, asyncio.run, signal handling, exit codes.
- **Interface:** `crawl.py --source=ams --limit=N --query=... --since=ISO --dry-run`
- **Dependencies:** `crawler.pipeline`, `crawler.config`, `crawler.storage`
- **Size target:** ~150 lines

## Storage Schema

`crawler/storage/schema.sql`:

```sql
CREATE TABLE schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL,
  description TEXT NOT NULL
);

CREATE TABLE sources (
  name TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL DEFAULT 1,
  rate_limit_per_min INTEGER NOT NULL DEFAULT 30,
  last_crawled_at TEXT
);

CREATE TABLE jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  source_id TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT NOT NULL,
  company TEXT,
  location TEXT,
  description TEXT,
  salary TEXT,
  employment_type TEXT,
  posted_at TEXT,
  content_hash TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  UNIQUE(source, source_id)
);
CREATE INDEX idx_jobs_hash ON jobs(content_hash);
CREATE INDEX idx_jobs_posted ON jobs(posted_at DESC);
CREATE INDEX idx_jobs_company ON jobs(company);
CREATE INDEX idx_jobs_active_posted ON jobs(is_active, posted_at DESC);

CREATE TABLE crawl_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,  -- running|success|partial|failed|dry_run
  jobs_found INTEGER DEFAULT 0,
  jobs_inserted INTEGER DEFAULT 0,
  jobs_updated INTEGER DEFAULT 0,
  errors_count INTEGER DEFAULT 0
);

CREATE TABLE crawl_errors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES crawl_runs(id),
  source TEXT NOT NULL,
  url TEXT,
  error_type TEXT NOT NULL,
  error_message TEXT,
  occurred_at TEXT NOT NULL
);
CREATE INDEX idx_errors_run ON crawl_errors(run_id);
```

**No raw storage columns** (no `raw_html`, no `raw_json`). Re-fetch on schema change. Reopen at sub-project 1.1 when HTML sources land.

### SQLite PRAGMAs

Applied in `crawler/storage/db.py:connect()`:

```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
conn.execute("PRAGMA foreign_keys=ON")
conn.execute("PRAGMA busy_timeout=30000")
```

### Dedup

Primary: UNIQUE `(source, source_id)` — INSERT OR UPDATE on conflict.

Secondary: `content_hash` index for cross-source duplicate detection. Same job posted on multiple sources → 2 rows with matching hash. Linking via `job_aliases` table deferred to sub-project 2.

`content_hash = SHA256(canonical)` where canonical = `normalize(title) | normalize(company) | normalize(location)`.

Normalization (`crawler/storage/dedup.py:normalize()`):

- Lowercase
- Collapse whitespace
- Strip punctuation except alphanumerics + spaces
- Strip company legal suffixes: `GmbH`, `AG`, `eG`, `OG`, `KG`, `mbH`
- Normalize Vienna districts: `1.` / `I.` / `erster Bezirk` → `wien-1`

Excluded from canonical (too noisy): `salary`, `posted_at`, `description`.

### Upsert

```sql
INSERT INTO jobs (source, source_id, url, title, company, location,
                  description, salary, employment_type, posted_at,
                  content_hash, first_seen_at, last_seen_at, is_active)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
ON CONFLICT(source, source_id) DO UPDATE SET
  title=excluded.title,
  description=excluded.description,
  salary=excluded.salary,
  employment_type=excluded.employment_type,
  last_seen_at=excluded.last_seen_at
RETURNING id, (xmax = 0) AS inserted;
```

`xmax = 0` → new row → `inserted`; else → `updated`. SQLite-specific, documented as such. Sub-project 4 scheduler may revisit if multi-DB portability needed.

## Data Flow

### CLI entry (`scripts/crawl.py`)

1. Parse args: `--source=ams` (default all enabled, AMS-only in sub-project 1), `--limit=N`, `--query="..."`, `--since=ISO`, `--dry-run`
2. Load config from `crawler/config.py`, init storage (run migrations)
3. Insert `crawl_runs` row (status=`running` for live, `dry_run` for `--dry-run`)
4. `await pipeline.run(adapters, query, run_id)` — fans out sources via `asyncio.gather`
5. On exit: update `crawl_runs` (`finished_at`, `status`, counters)
6. Exit code: 0 = success, 1 = partial, 2 = failed, 3 = dry_run

### Pipeline (`crawler/pipeline.py`)

```python
async def run_source(adapter, query, run_id) -> SourceResult:
    try:
        async with asyncio.timeout(SOURCE_TIMEOUT_SECONDS):  # 600s default
            async for raw in adapter.search(query):
                try:
                    detail = await adapter.fetch_detail(raw)
                    action = repository.upsert_job(detail)
                    counters[action] += 1  # inserted | updated
                except CrawlerError as e:
                    repository.log_error(run_id, adapter.name, raw.url, type(e).__name__, str(e))
                    counters["errors"] += 1
        return SourceResult(status="success", counters=counters)
    except CrawlerError as e:
        return SourceResult(status="failed", error=e)
    except Exception as e:
        return SourceResult(status="crashed", error=e)  # unexpected

async def run(adapters, query, run_id):
    results = await asyncio.gather(*[run_source(a, query, run_id) for a in adapters])
    # aggregate → final crawl_runs status
```

`asyncio.gather` (no `return_exceptions` needed — `run_source` always returns). Per-source timeout via `asyncio.timeout`. Unexpected exceptions caught and logged as `crashed`.

### HTTP client (`crawler/http.py`) — future sources only

- httpx async client. **AMS does NOT use this** (uses browser — see below).
- Future sources: Karriere.at (JSON-LD via static HTML), Willhaben.at/jobs.
- UA pool: rotating realistic desktop UAs per request (10 UAs, round-robin)
- Per-source token bucket: rate from `sources.rate_limit_per_min` (default 30/min)
- Retry: ≤3 attempts, exp backoff per error class (see § Error Handling)
- Timeout: connect 10s / read 30s
- Raises typed exceptions only: `RateLimited`, `Blocked`, `Timeout`, `HTTPError`, `NetworkError`

### Browser wrapper (`crawler/browser.py`) — AMS

- Playwright async API, Chromium headless
- **Cookie store**: persist `SM2_SESSION` (and any `ams.at` cookies) to `data/session_ams.json` (gitignored). Refresh on session start + on `CookieExpired` signal (no time-based TTL — server-driven expiry only).
- **UA pool**: 10 realistic desktop Chrome/Firefox/Edge strings, round-robin per session (not per request — minimize fingerprint churn)
- **Page waiter**: `await page.wait_for_selector(selector, timeout=BROWSER_TIMEOUT_MS)`. No `networkidle` (analytics/tracking hangs).
- **Anti-bot detector**: returns typed exception on `title=='captcha'`, `403`, body contains `access denied`, URL ends with `/verify`. No auto-solving.
- **Session lifecycle**: context opened by `pipeline.run_source()`, closed on completion/exception/cancellation via `async with`
- **Resource limit**: single browser instance shared across one `run_source()`; per-source isolation
- Raises typed exceptions: `CaptchaEncountered`, `CookieExpired`, `SPAWaitTimeout`

### AMS adapter (`crawler/sources/ams.py`)

- **Stack**: Playwright async API via `crawler/browser.py`
- `search()`: paginated `/jobs` browser navigation; waits for `[data-testid="job-card"]`; yields `RawJob` per card
- `fetch_detail()`: per-job detail page; waits for `[data-testid="job-detail"]`; returns `NormalizedJob` with `content_hash`
- **Session**: extracts `SM2_SESSION` from first navigation response, persists to `data/session_ams.json` (gitignored). Refresh on session start (always) + on `CookieExpired` signal. No TTL clock.
- **Throttle**: 10 req/min (conservative start, tune via `AMS_RATE_LIMIT_PER_MIN` config), ±2s random jitter between requests
- **Anti-bot**: on captcha/403/access-denied → retry 1× after 60s → circuit-break; stderr alert (no captcha solving — ethical + ToS)
- **SPA wait**: 15s selector timeout, 1 retry on timeout (likely transient)
- **No captcha solving**: out of scope (ethical + ToS)
- **No raw HTML storage** (per deferred section — re-fetch on schema change)
- **No image/screenshot capture**: text-only extraction from rendered DOM

## Configuration

`crawler/config.py` — named constants, no env override (sub-project 1). Sub-project 4 scheduler will add env override.

```python
# Concurrency
MAX_CONCURRENT_FETCHES_PER_SOURCE: int = 4
MAX_CONCURRENT_HTTP_GLOBAL: int = 16
SOURCE_TIMEOUT_SECONDS: int = 600

# Circuit breaker
CIRCUIT_BREAKER_THRESHOLD: int = 5            # consecutive FetchError
CIRCUIT_BREAKER_BLOCKED_THRESHOLD: int = 1    # single Blocked
CIRCUIT_BREAKER_CAPTCHA_THRESHOLD: int = 1    # single CaptchaEncountered
CIRCUIT_BREAKER_COOKIE_THRESHOLD: int = 1     # single CookieExpired (after refresh)
CIRCUIT_BREAKER_SCHEMA_THRESHOLD: int = 1     # single SchemaChanged

# Signal handling
SIGINT_GRACE_SECONDS: int = 30

# Database
DB_BUSY_TIMEOUT_SECONDS: int = 30
DB_PATH: Path = Path("data/jobs.db")

# Retry
RETRY_MAX_ATTEMPTS: int = 3
RETRY_BACKOFF_FAST: tuple[int, ...] = (1, 2, 4)   # 5xx, Timeout
RETRY_BACKOFF_SLOW: tuple[int, ...] = (1, 5, 15)  # NetworkError

# Browser (AMS)
BROWSER_TIMEOUT_MS: int = 15_000                   # SPA selector wait
BROWSER_RETRIES_ON_TIMEOUT: int = 1                # SPA wait retry
BROWSER_CAPTCHA_BACKOFF_SECONDS: int = 60          # anti-bot retry
BROWSER_UA_POOL_SIZE: int = 10                     # rotating realistic UAs
AMS_RATE_LIMIT_PER_MIN: int = 10                   # conservative start
AMS_REQUEST_JITTER_SECONDS: int = 2                # ±random jitter
AMS_CAPTCHA_TUNE_THRESHOLD: float = 0.001          # captchas per request; tune rate up if <3 runs below
AMS_CAPTCHA_TUNE_RUNS: int = 3                     # consecutive runs needed to tune rate up

# Testing
COVERAGE_GATE: float = 0.90  # AMS-only small surface, high target
```

## Error Handling

### Exception hierarchy (`crawler/exceptions.py`)

```
CrawlerError
├─ FetchError
│  ├─ RateLimited           # 429, has retry_after
│  ├─ Blocked               # 403, anti-bot
│  ├─ CaptchaEncountered    # AMS: anti-bot challenge page detected
│  ├─ CookieExpired         # AMS: SM2_SESSION invalid/expired mid-session
│  ├─ SPAWaitTimeout        # AMS: page selector never appeared
│  ├─ Timeout               # connect/read
│  ├─ HTTPError             # other 4xx/5xx
│  └─ NetworkError          # DNS, conn refused
├─ ParseError
│  ├─ SchemaChanged         # selectors/JSON shape broke
│  └─ MissingField          # required field absent
└─ StorageError
   ├─ MigrationError
   └─ ConstraintError
```

### Retry policy

| Error | Retry | Backoff | On exhaust |
|---|---|---|---|
| `RateLimited` (with `Retry-After`) | yes (≤3) | respect header | skip job, log |
| `RateLimited` (no `Retry-After`) | no | — | skip job, log |
| `Blocked` (with `Retry-After`) | yes (1) | respect header | circuit-break |
| `Blocked` (no `Retry-After`) | no | — | circuit-break |
| `CaptchaEncountered` | yes (1) | 60s | circuit-break, stderr alert |
| `CookieExpired` | yes (1) | refresh session | circuit-break |
| `SPAWaitTimeout` | yes (1) | FAST (1s) | skip job, log |
| `Timeout` | yes (≤3) | FAST (1/2/4) | skip job, log |
| `HTTPError` 5xx | yes (≤3) | FAST (1/2/4) | skip job, log |
| `HTTPError` 4xx (not 429) | no | — | skip job, log |
| `NetworkError` | yes (≤3) | SLOW (1/5/15) | skip job, log |
| `ParseError.SchemaChanged` | no | — | circuit-break, stderr alert |
| `ParseError.MissingField` | no | — | skip job, log only (no raw storage in sub-project 1) |
| `StorageError` | no | — | mark run `failed`, exit 2 |

### Circuit breaker (per source, in-memory, per run)

- 5 consecutive `FetchError` → open
- 1 `Blocked` → open
- 1 `CaptchaEncountered` → open (AMS: anti-bot detected)
- 1 `CookieExpired` (after 1 refresh attempt) → open (AMS: session unsalvageable)
- 1 `SchemaChanged` → open
- Open: skip source for remainder of run, log summary, other sources continue
- Reset: per-run boundary (no cross-run state — sub-project 4 scheduler owns persistence)

### Logging

- All errors → `crawl_errors` table (run_id, source, url, error_type, msg, occurred_at)
- `SchemaChanged` + `Blocked` + `CaptchaEncountered` + `StorageError` → also `print()` to stderr (operator-visible)
- Format: text default; `LOG_FORMAT=json` env (sub-project 4 scheduler adds) → JSON to stderr

### Signal handling

- SIGINT/SIGTERM → graceful shutdown:
  - Stop scheduling new fetches
  - Wait in-flight ≤`SIGINT_GRACE_SECONDS` (30s)
  - Update current `crawl_runs`: `status='failed'`, `finished_at=now`
  - Exit 130 / 143

### CLI live counter

```
[ams]      fetched 47 | upserted 45 (3 errors) | elapsed 12s
[ams]      BLOCKED — circuit open, skipping 178 remaining
```

On finish: summary table + exit code (0/1/2/3).

### Run lifecycle states

`crawl_runs.status`: `running` → `success` (0 errors) | `partial` (≥1 error, ≥1 job) | `failed` (all sources errored or DB unavailable) | `dry_run` (CLI flag set).

## Testing Strategy

### Pyramid

| Layer | Scope | Speed | Network |
|---|---|---|---|
| Unit | parser/dedup/retry/repository | <100ms/test | none |
| Contract | adapter Protocol compliance | <100ms/test | none |
| Integration | pipeline vs fixtures | <2s/test | none |
| Smoke | live AMS | manual | real |

### Unit tests

- `test_ams_parser.py`: HTML → `NormalizedJob` (selectors on rendered DOM), edge cases (empty/malformed), raises `SchemaChanged` on missing required fields
- `test_browser_anti_bot.py`: captcha title, 403 response, `/verify` redirect, access-denied body → typed `CaptchaEncountered`
- `test_browser_session.py`: SM2_SESSION extract → persist → load <24h old → load >24h old → refresh flow
- `test_dedup.py`: hash stability, `(source, source_id)` UNIQUE behavior, cross-source hash match, normalization edge cases (legal suffixes, Vienna districts)
- `test_http_retry.py`: 429 + `Retry-After`, 5xx exp backoff, 4xx no-retry, timeout retry, exhaustion → typed error
- `test_repository.py`: insert/update/conflict SQL, `xmax=0` semantics, `crawl_errors` logging
- `test_config.py`: constant values, no env override (sub-project 1)

### Contract tests

`test_source_adapter.py`: AMS adapter implements `SourceAdapter` Protocol, returns correct types, handles empty results, raises only typed exceptions from `crawler/exceptions.py`.

### Integration tests

- `test_crawl_ams.py`: full pipeline vs recorded AMS fixtures; assert DB row counts, `crawl_runs` lifecycle (running→success), zero `crawl_errors`
- `test_crawl_partial.py`: inject 1 bad fixture → that job logged, others succeed, `status='partial'`
- `test_crawl_dry_run.py`: `--dry-run` → no `jobs` rows written, `crawl_runs.status='dry_run'`, stdout contains JSON lines
- `test_crawl_crash.py`: source raises unexpected `Exception` → `SourceResult.status='crashed'`, run continues, error logged

### Fixtures (`tests/fixtures/`, committed)

- **AMS HTML** (recorded from rendered SPA via `page.content()`): search page, detail page, empty results, malformed (selector returns nothing), captcha page
- **Future httpx fixtures** (sub-project 1.1+): JSON-LD JobPosting payloads for Karriere.at
- Recorded via `scripts/record_fixtures.py` (one-shot, not in main loop)
- AMS integration tests use **parsed HTML fixtures directly** — no Playwright launch in CI. `AmsAdapter` accepts injected `BrowserContext` (DI); tests pass a `FakeBrowserContext` that returns fixture HTML. Real Playwright only in smoke checklist.
- Age warning: tests print warning if fixture mtime >30 days (operator prompt to re-record)

### Infrastructure

- `pytest` + `pytest-asyncio` (async adapter tests)
- `freezegun` for `posted_at` / `fetched_at` determinism
- `respx` (or httpx `MockTransport`) for HTTP mocking
- In-memory SQLite (`:memory:`) for repo tests
- Coverage via `pytest-cov`

### Coverage targets

- Parser: ≥95% (selector drift → safety net)
- Browser wrapper: ≥90% (anti-bot detection, cookie mgmt)
- Repository/dedup/retry/migrations: 100% (correctness-critical)
- Pipeline: ≥90% (state machine)
- Overall: ≥90% (CI gate via `COVERAGE_GATE = 0.90`)

### CI

- `pytest` on push
- Fail if coverage <`COVERAGE_GATE`
- No live network in CI — fixtures only
- No Playwright launch in CI — `AmsAdapter` takes injected `BrowserContext`; tests pass a `FakeBrowserContext` returning fixture HTML
- Live Playwright only in manual smoke checklist (operator runs locally, not CI)

### Smoke checklist (operator manual, pre-release)

```bash
[ ] crawl.py --source=ams --limit=5          → exit 0, 5 jobs in DB
[ ] crawl.py --source=ams --limit=5 --dry-run → exit 3, no DB writes, JSON stdout
[ ] crawl.py --source=ams --since=2026-06-01  → exit 0, posted_at filter works
[ ] inspect_db.py                             → expected counts, no SchemaChanged errors
[ ] rm data/jobs.db && crawl.py --source=ams --limit=10 → migration applies cleanly
```

## CLI Interface

```
usage: crawl.py [-h] [--source SOURCE] [--limit N] [--query TERM]
                [--since ISO_DATE] [--dry-run] [--log-format {text,json}]

optional arguments:
  --source       Source name (default: all enabled). Sub-project 1: only 'ams'.
  --limit        Max jobs to fetch per source (default: 100)
  --query        Search keywords (default: empty = all)
  --since        ISO date, filter by posted_at >= since (default: no lower bound)
  --dry-run      Fetch + parse + print to stdout, no DB writes
  --log-format   Output format: text (default) | json
```

Exit codes: 0=success, 1=partial, 2=failed, 3=dry_run.

## Discovery Findings (Pre-Spec Spike — Completed)

Pre-spec spike completed. Findings:

- AMS `/jobs` route = **Angular SPA**. Initial HTML empty; populated via XHR to internal API after JS render.
- **`SM2_SESSION` cookie** required (anti-bot honeypot, set on first visit). Domain `ams.at`. HttpOnly + Secure.
- **No public REST API / RSS / JSON-LD** for job listings.
- **No `robots.txt` ban** on `/jobs` (verified).
- **No public rate limit headers** documented.
- **Consequence**: httpx+JSON stack assumption invalid for AMS → pivot to Playwright browser.

Updated approach: see [AMS adapter](#ams-adapter-crawlersourcesamspy) and [Browser wrapper](#browser-wrapper-crawlerbrowserpy--ams) sections for Playwright + cookie mgmt + anti-bot handling.

Probes retained for future reference: `$TMPDIR/jobs_ams_index.html` (initial SPA shell), `$TMPDIR/ams_main.js` (404 — confirms SPA loads bundles dynamically).

## Deferred / Out of Scope

See `~/.claude/projects/-Users-vladbrincoveanu-Desktop-Startup-JobCrawler/memory/jobcrawler-deferred-to-future-subprojects.md`:

- **Sub-project 1.1** (Karriere.at): static HTML + JSON-LD `JobPosting` adapter via `crawler/http.py` (httpx — no browser needed); `raw_html` storage (`job_raw` table, opt-in per source)
- **Sub-project 1.2** (Willhaben.at/jobs): adapter (verify URL exists first; likely browser-backed given modern SPA patterns)
- **Sub-project 1.3+** (LinkedIn): Playwright + stealth UA, ToS review, anti-bot (residential proxy, fingerprint). **Reuses `crawler/browser.py` infra with AMS.**
- **Sub-project 2** (Enrichment): company lookup, financial distress, employee reviews, `job_aliases` table for cross-source dedup linking, optional description fingerprint dedup
- **Sub-project 3** (Dashboard): Next.js UI, reads jobs.db via API route (WAL mode enables concurrent read)
- **Sub-project 4** (Scheduler): cron/UI-trigger, env var config override, cross-run circuit state, remote alerts, Prometheus, auto-restart, checkpoint/resume, load/stress testing

See `~/.claude/projects/-Users-vladbrincoveanu-Desktop-Startup-JobCrawler/memory/jobcrawler-never-do.md` for explicitly rejected approaches.

## Risks

| Risk | Mitigation |
|---|---|
| AMS endpoint unavailable / requires auth | Discovery spike complete; Playwright + SM2_SESSION handles auth (post-pivot) |
| AMS rate limits undocumented | Start conservative (10/min), observe 429s/captchas, tune up via `AMS_RATE_LIMIT_PER_MIN` |
| AMS anti-bot escalation (CAPTCHA, IP ban) | Conservative throttle (10/min), ±2s jitter, no captcha solving, circuit-break on first signal, stderr alert |
| AMS SPA selector drift | Fixture age warning (>30d), selector-based parser unit tests at 95% coverage, `test_ams_parser.py` covers happy + edge cases |
| SM2_SESSION cookie expires mid-run | Auto-refresh on `CookieExpired` (1 retry), circuit-break on second expiry |
| Playwright browser resource exhaustion | Single browser context per `run_source()`, closed via `async with`; subprocess cleanup on SIGINT |
| AMS response shape changes silently (HTML selectors) | Fixture age warning (>30d), manual smoke checklist pre-release |
| SQLite single-writer constraint blocks future multi-process | WAL mode from day 1; sub-project 4 scheduler owns process count |
| Coverage gate too aggressive (90%) for evolving codebase | Gate per-module (parser 95%, dedup/repo 100%), not just overall |
| Headless browser detectable by AMS | Realistic UA pool + Accept-Language + viewport; if detected → escalate (consider stealth plugin or proxy) |

## Open Questions

None at spec time. Plan-writing may surface questions that update this spec before implementation.
