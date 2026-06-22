# JobCrawler Sub-Project 1: Crawler + Storage — Design Spec

**Date:** 2026-06-22
**Status:** Draft → review
**Scope:** Sub-project 1 of 4 (see [§ Scope](#scope))

## Goal

Fetch raw job listings from AMS (Austrian Public Employment Service) and persist them to a local SQLite database. CLI-driven, no scheduler, no enrichment, no dashboard. Pipeline + storage proven on a single source before adding more.

## Scope

Sub-project 1 ships:
- AMS source adapter (httpx + JSON, no JS rendering)
- SourceAdapter Protocol contract
- Per-source parser, HTTP client (retry/backoff/rate-limit)
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
        ├─► crawler/sources/ams.py   implements SourceAdapter (httpx + JSON parse)
        │       │
        │       ├─► crawler/http.py  rotating UA, per-source rate limit, retry/backoff
        │       └─► crawler/parser.py  JSON → NormalizedJob
        │
        └─► crawler/storage/repository.py  upsert_job, log_error, finalize_run
                │
                ▼
        crawler/storage/db.py  WAL-mode SQLite connection
                │
                ▼
        data/jobs.db  (gitignored)
```

Stack: **Python 3.12+**, **httpx** (async HTTP), **pydantic v2** (validation), **sqlite3** stdlib, **pytest** + **pytest-asyncio** + **freezegun**, **respx** or httpx MockTransport for fixtures.

## Components

### Directory layout

```
jobcrawler/
  crawler/
    __init__.py
    config.py              # named constants (see § Configuration)
    exceptions.py          # CrawlerError hierarchy
    http.py                # shared client: UA pool, throttle, retry, backoff
    models.py              # pydantic: JobQuery, RawJob, NormalizedJob
    parser.py              # generic JSON parsing helpers (per-source logic lives in sources/*.py)
    pipeline.py            # orchestrator: run_source(), run()
    sources/
      __init__.py
      base.py              # SourceAdapter Protocol
      ams.py               # AMS adapter
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
    record_fixtures.py     # one-shot: capture live AMS responses to tests/fixtures/
  tests/
    unit/
      test_ams_parser.py
      test_dedup.py
      test_http_retry.py
      test_repository.py
      test_config.py
    contract/
      test_source_adapter.py
    integration/
      test_crawl_ams.py
      test_crawl_partial.py
      test_crawl_dry_run.py
    fixtures/
      ams_search_page.json
      ams_detail_page.json
      ams_empty_results.json
      ams_malformed.json
  data/                    # gitignored: jobs.db
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

### HTTP client (`crawler/http.py`)

- UA pool: rotating realistic desktop UAs per request (10 UAs, round-robin)
- Per-source token bucket: rate from `sources.rate_limit_per_min` (default 30/min)
- Retry: ≤3 attempts, exp backoff per error class (see § Error Handling)
- Timeout: connect 10s / read 30s
- Raises typed exceptions only: `RateLimited`, `Blocked`, `Timeout`, `HTTPError`, `NetworkError`

### AMS adapter (`crawler/sources/ams.py`)

- Stack: httpx async client
- `search()`: paginated API call, yields `RawJob` per result
- `fetch_detail()`: per-job detail call, returns `NormalizedJob` with `content_hash` computed
- No JS rendering, no anti-bot circumvention needed (AMS public service)

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

# Testing
COVERAGE_GATE: float = 0.90  # AMS-only small surface, high target
```

## Error Handling

### Exception hierarchy (`crawler/exceptions.py`)

```
CrawlerError
├─ FetchError
│  ├─ RateLimited      # 429, has retry_after
│  ├─ Blocked          # 403, anti-bot
│  ├─ Timeout          # connect/read
│  ├─ HTTPError        # other 4xx/5xx
│  └─ NetworkError     # DNS, conn refused
├─ ParseError
│  ├─ SchemaChanged    # selectors/JSON shape broke
│  └─ MissingField     # required field absent
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
- 1 `SchemaChanged` → open
- Open: skip source for remainder of run, log summary, other sources continue
- Reset: per-run boundary (no cross-run state — sub-project 4 scheduler owns persistence)

### Logging

- All errors → `crawl_errors` table (run_id, source, url, error_type, msg, occurred_at)
- `SchemaChanged` + `Blocked` + `StorageError` → also `print()` to stderr (operator-visible)
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

- `test_ams_parser.py`: JSON → `NormalizedJob`, edge cases (empty/malformed), raises `SchemaChanged` on missing required fields
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

- 1 search page + 1 detail page (JSON)
- Edge cases: empty results, malformed JSON, paginated response
- Recorded via `scripts/record_fixtures.py` (one-shot, not in main loop)
- httpx `MockTransport` mounts fixtures by URL pattern → zero real network in tests
- Age warning: tests print warning if fixture mtime >30 days (operator prompt to re-record)

### Infrastructure

- `pytest` + `pytest-asyncio` (async adapter tests)
- `freezegun` for `posted_at` / `fetched_at` determinism
- `respx` (or httpx `MockTransport`) for HTTP mocking
- In-memory SQLite (`:memory:`) for repo tests
- Coverage via `pytest-cov`

### Coverage targets

- Parser: ≥95% (selectors/JSON shape drift → safety net)
- Repository/dedup/retry/migrations: 100% (correctness-critical)
- Pipeline: ≥90% (state machine)
- Overall: ≥90% (CI gate via `COVERAGE_GATE = 0.90`)

### CI

- `pytest` on push
- Fail if coverage <`COVERAGE_GATE`
- No live network in CI — fixtures only
- AMS adapter fixture-only (no `@pytest.mark.live` needed; LinkedIn sub-project 1.3+ will add)

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

## Discovery Step (Pre-Spec Implementation)

Before writing the implementation plan, run a 30-min spike:

1. Verify AMS endpoint exists (likely `ejob.ams.at` or `api.ams.at`)
2. Check `robots.txt` policy
3. Sample 1 search request + 1 detail request, capture responses
4. Confirm response format (JSON vs HTML)
5. Document rate limit headers if any

If no clean API/RSS endpoint exists → escalate, possibly pivot sub-project 1 to a different source (e.g., Karriere.at if its RSS is accessible).

## Deferred / Out of Scope

See `~/.claude/projects/-Users-vladbrincoveanu-Desktop-Startup-JobCrawler/memory/jobcrawler-deferred-to-future-subprojects.md`:

- **Sub-project 1.1** (Karriere.at): HTML+JSON-LD adapter, `raw_html` storage (`job_raw` table, opt-in per source)
- **Sub-project 1.2** (Willhaben.at/jobs): adapter (verify URL exists first)
- **Sub-project 1.3+** (LinkedIn): Playwright + stealth UA, ToS review, anti-bot (residential proxy, fingerprint)
- **Sub-project 2** (Enrichment): company lookup, financial distress, employee reviews, `job_aliases` table for cross-source dedup linking, optional description fingerprint dedup
- **Sub-project 3** (Dashboard): Next.js UI, reads jobs.db via API route (WAL mode enables concurrent read)
- **Sub-project 4** (Scheduler): cron/UI-trigger, env var config override, cross-run circuit state, remote alerts, Prometheus, auto-restart, checkpoint/resume, load/stress testing

See `~/.claude/projects/-Users-vladbrincoveanu-Desktop-Startup-JobCrawler/memory/jobcrawler-never-do.md` for explicitly rejected approaches.

## Risks

| Risk | Mitigation |
|---|---|
| AMS endpoint unavailable / requires auth | 30-min discovery spike before plan; pivot source if blocked |
| AMS rate limits undocumented | Start conservative (10/min), observe 429s, tune up |
| AMS JSON shape changes silently | Fixture age warning (>30d), manual smoke checklist pre-release |
| SQLite single-writer constraint blocks future multi-process | WAL mode from day 1; sub-project 4 scheduler owns process count |
| Coverage gate too aggressive (90%) for evolving codebase | Gate per-module (parser 95%, dedup/repo 100%), not just overall |

## Open Questions

None at spec time. Discovery spike (above) may surface questions that update this spec before plan writing.
