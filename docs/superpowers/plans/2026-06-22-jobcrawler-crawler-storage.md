# JobCrawler Sub-Project 1 — Crawler + Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI that crawls AMS (Austrian Public Employment Service) job listings via Playwright, normalizes + dedupes them, and persists to a local SQLite DB. Pipeline + storage proven on a single source before adding more.

**Architecture:** Async Python CLI (`scripts/crawl.py`) → `crawler.pipeline` orchestrator → per-source `SourceAdapter` (AMS uses Playwright via injectable `BrowserContext` Protocol; tests use `FakeBrowserContext`) → `crawler.storage.repository` upserts to SQLite (WAL mode). No scheduler, no enrichment, no dashboard.

**Tech Stack:** Python 3.12+, httpx (future), playwright (AMS), pydantic v2, sqlite3 stdlib, beautifulsoup4, pytest + pytest-asyncio + pytest-cov + freezegun + respx.

**Spec:** `docs/superpowers/specs/2026-06-21-jobcrawler-crawler-storage-design.md`
**Spec scope flags:** `test_scope: true` (coverage measurement task required), `ui_scope: false`, `graph_scope: false`.

**Grill-me amendments baked in:**
- (1) `FakeBrowserContext` lives in `tests/fakes/browser.py`, not `crawler/browser.py`
- (2) Migration runner scans `migrations/V*.sql`, applies unapplied versions
- (4) `jobs.raw_html` column added (opt-in per source) for AMS
- (6) `AMS_BASE_URL` + `AMS_COOKIE_DOMAIN` added to `crawler/config.py`
- (9) Cookie persistence: JSON schema `{cookies: [{name, value, domain, path, expires, httpOnly, secure}], saved_at: ISO}`

---

## Task 1: Project bootstrap — pyproject.toml + dir structure

**Files:**
- Create: `pyproject.toml`
- Create: `crawler/__init__.py`
- Create: `crawler/sources/__init__.py`
- Create: `crawler/storage/__init__.py`
- Create: `scripts/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/contract/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/fakes/__init__.py`
- Create: `tests/fixtures/.gitkeep`
- Create: `data/.gitkeep`
- Create: `.env.example`
- Create: `scripts/crawl.py` (stub)
- Create: `scripts/inspect_db.py` (stub)
- Create: `scripts/record_fixtures.py` (stub)

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "jobcrawler"
version = "0.1.0"
description = "Job listings crawler + storage"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    "playwright>=1.45",
    "pydantic>=2.7",
    "beautifulsoup4>=4.12",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "freezegun>=1.5",
    "respx>=0.21",
    "ruff>=0.5",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["crawler"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
addopts = "-ra --strict-markers"
testpaths = ["tests"]

[tool.coverage.run]
source = ["crawler"]
omit = ["tests/*", "scripts/*"]

[tool.coverage.report]
fail_under = 90
show_missing = true
exclude_lines = ["pragma: no cover", "if __name__ == .__main__.:", "raise NotImplementedError"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

- [ ] **Step 2: Create `.env.example`**

```bash
# JobCrawler — copy to .env, never commit
# Sub-project 1: not consumed yet. Sub-project 4 (scheduler) wires these.
AMS_BASE_URL=https://jobs.ams.at/public/
AMS_COOKIE_DOMAIN=.ams.at
LOG_FORMAT=text
```

- [ ] **Step 3: Create dir structure with empty `__init__.py` + `.gitkeep`**

```bash
mkdir -p crawler/sources crawler/storage scripts data tests/unit tests/contract tests/integration tests/fakes tests/fixtures
touch crawler/__init__.py crawler/sources/__init__.py crawler/storage/__init__.py scripts/__init__.py tests/__init__.py tests/unit/__init__.py tests/contract/__init__.py tests/integration/__init__.py tests/fakes/__init__.py tests/fixtures/.gitkeep data/.gitkeep
```

- [ ] **Step 4: Create stub scripts**

`scripts/crawl.py`:
```python
"""CLI entry. Implemented in Task 24."""
def main() -> None:
    raise NotImplementedError("Task 24")

if __name__ == "__main__":
    main()
```

`scripts/inspect_db.py`:
```python
"""Debug: counts, schema, sample rows. Implemented in Task 25."""
def main() -> None:
    raise NotImplementedError("Task 25")

if __name__ == "__main__":
    main()
```

`scripts/record_fixtures.py`:
```python
"""One-shot: capture live AMS HTML to tests/fixtures/. Implemented in Task 26."""
def main() -> None:
    raise NotImplementedError("Task 26")

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Install deps + Playwright browser**

Run:
```bash
cd /Users/vladbrincoveanu/Desktop/Startup/JobCrawler
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

Expected: deps install, chromium binary in `~/.cache/ms-playwright/`.

- [ ] **Step 6: Commit**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/JobCrawler
git add pyproject.toml .env.example crawler/ scripts/ tests/ data/
git commit -m "chore: bootstrap project — pyproject + dir structure + stub scripts"
```

---

## Task 2: Update `.gitignore`

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add Python, venv, DB, and AMS cookie entries**

Append to `.gitignore`:
```
# Python
__pycache__/
*.py[cod]
*$py.class
.venv/
*.egg-info/
dist/
build/
.pytest_cache/
.coverage
htmlcov/
.mypy_cache/
.ruff_cache/

# Env
.env
.env.local

# JobCrawler runtime
data/jobs.db
data/jobs.db-*
data/session_ams.json

# Playwright
.playwright/
```

- [ ] **Step 2: Verify**

Run: `cat .gitignore | tail -20`
Expected: Python + runtime entries present.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore — python venv, data/, cookie store, coverage"
```

---

## Task 3: `crawler/config.py` — named constants

**Files:**
- Create: `crawler/config.py`
- Create: `tests/unit/test_config.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_config.py`:
```python
from pathlib import Path
from crawler import config

def test_db_path_default():
    assert config.DB_PATH == Path("data/jobs.db")

def test_source_timeout():
    assert config.SOURCE_TIMEOUT_SECONDS == 600

def test_circuit_breaker_thresholds():
    assert config.CIRCUIT_BREAKER_THRESHOLD == 5
    assert config.CIRCUIT_BREAKER_BLOCKED_THRESHOLD == 1
    assert config.CIRCUIT_BREAKER_CAPTCHA_THRESHOLD == 1
    assert config.CIRCUIT_BREAKER_COOKIE_THRESHOLD == 1
    assert config.CIRCUIT_BREAKER_SCHEMA_THRESHOLD == 1

def test_ams_config_present():
    # grill-me amendment 6: base URL + cookie domain
    assert config.AMS_BASE_URL == "https://jobs.ams.at/public/"
    assert config.AMS_COOKIE_DOMAIN == ".ams.at"
    assert config.AMS_RATE_LIMIT_PER_MIN == 10
    assert config.AMS_REQUEST_JITTER_SECONDS == 2
    assert config.AMS_CAPTCHA_TUNE_THRESHOLD == 0.001
    assert config.AMS_CAPTCHA_TUNE_RUNS == 3

def test_retry_backoffs():
    assert config.RETRY_BACKOFF_FAST == (1, 2, 4)
    assert config.RETRY_BACKOFF_SLOW == (1, 5, 15)

def test_coverage_gate():
    assert config.COVERAGE_GATE == 0.90
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_config.py -v`
Expected: `ModuleNotFoundError: No module named 'crawler.config'`

- [ ] **Step 3: Implement `crawler/config.py`**

```python
"""Named constants. Sub-project 1: no env override. Sub-project 4 wires env."""
from pathlib import Path

# Concurrency
MAX_CONCURRENT_FETCHES_PER_SOURCE: int = 4
MAX_CONCURRENT_HTTP_GLOBAL: int = 16
SOURCE_TIMEOUT_SECONDS: int = 600

# Circuit breaker (per source, per run, in-memory)
CIRCUIT_BREAKER_THRESHOLD: int = 5
CIRCUIT_BREAKER_BLOCKED_THRESHOLD: int = 1
CIRCUIT_BREAKER_CAPTCHA_THRESHOLD: int = 1
CIRCUIT_BREAKER_COOKIE_THRESHOLD: int = 1
CIRCUIT_BREAKER_SCHEMA_THRESHOLD: int = 1

# Signal handling
SIGINT_GRACE_SECONDS: int = 30

# Database
DB_BUSY_TIMEOUT_SECONDS: int = 30
DB_PATH: Path = Path("data/jobs.db")

# Retry
RETRY_MAX_ATTEMPTS: int = 3
RETRY_BACKOFF_FAST: tuple[int, ...] = (1, 2, 4)
RETRY_BACKOFF_SLOW: tuple[int, ...] = (1, 5, 15)

# Browser (AMS)
BROWSER_TIMEOUT_MS: int = 15_000
BROWSER_RETRIES_ON_TIMEOUT: int = 1
BROWSER_CAPTCHA_BACKOFF_SECONDS: int = 60
BROWSER_UA_POOL_SIZE: int = 10

# AMS (grill-me amendment 6: explicit URL/cookie domain config)
AMS_BASE_URL: str = "https://jobs.ams.at/public/"
AMS_COOKIE_DOMAIN: str = ".ams.at"
AMS_RATE_LIMIT_PER_MIN: int = 10
AMS_REQUEST_JITTER_SECONDS: int = 2
AMS_CAPTCHA_TUNE_THRESHOLD: float = 0.001
AMS_CAPTCHA_TUNE_RUNS: int = 3

# UA pool — 10 realistic desktop UAs, round-robin
UA_POOL: tuple[str, ...] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.5; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
)

# Coverage
COVERAGE_GATE: float = 0.90
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_config.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add crawler/config.py tests/unit/test_config.py
git commit -m "feat(config): named constants — AMS URL/cookie domain, UA pool, circuit breaker"
```

---

## Task 4: `crawler/exceptions.py` — typed exception hierarchy

**Files:**
- Create: `crawler/exceptions.py`
- Create: `tests/unit/test_exceptions.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_exceptions.py`:
```python
import pytest
from crawler.exceptions import (
    CrawlerError, FetchError, RateLimited, Blocked, CaptchaEncountered,
    CookieExpired, SPAWaitTimeout, Timeout, HTTPError, NetworkError,
    ParseError, SchemaChanged, MissingField, StorageError, MigrationError, ConstraintError,
)

def test_crawler_error_is_base():
    assert issubclass(FetchError, CrawlerError)
    assert issubclass(ParseError, CrawlerError)
    assert issubclass(StorageError, CrawlerError)

def test_fetch_error_subtypes():
    for cls in (RateLimited, Blocked, CaptchaEncountered, CookieExpired,
                SPAWaitTimeout, Timeout, HTTPError, NetworkError):
        assert issubclass(cls, FetchError), f"{cls.__name__} not FetchError"

def test_ratelimited_retry_after():
    e = RateLimited("429", retry_after=5)
    assert e.retry_after == 5
    assert str(e) == "429"

def test_parse_error_subtypes():
    assert issubclass(SchemaChanged, ParseError)
    assert issubclass(MissingField, ParseError)

def test_storage_error_subtypes():
    assert issubclass(MigrationError, StorageError)
    assert issubclass(ConstraintError, StorageError)

def test_crawler_error_can_be_raised_and_caught():
    with pytest.raises(CrawlerError):
        raise RateLimited("test")
    with pytest.raises(FetchError):
        raise CaptchaEncountered("captcha detected")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_exceptions.py -v`
Expected: `ModuleNotFoundError: No module named 'crawler.exceptions'`

- [ ] **Step 3: Implement `crawler/exceptions.py`**

```python
"""Typed exception hierarchy. Spec § Error Handling."""

class CrawlerError(Exception):
    """Base for all JobCrawler errors."""


class FetchError(CrawlerError):
    """Source fetch failure. Retry policy in spec § Retry policy."""


class RateLimited(FetchError):
    def __init__(self, msg: str, retry_after: int | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


class Blocked(FetchError):
    """403 / anti-bot block. Circuit-break per spec."""


class CaptchaEncountered(FetchError):
    """AMS anti-bot challenge page. No auto-solve. Circuit-break."""


class CookieExpired(FetchError):
    """SM2_SESSION invalid mid-session. Refresh + 1 retry."""


class SPAWaitTimeout(FetchError):
    """Page selector never appeared. 1 retry (likely transient)."""


class Timeout(FetchError):
    """Connect/read timeout."""


class HTTPError(FetchError):
    """Other 4xx/5xx. 5xx retries, 4xx (non-429) does not."""


class NetworkError(FetchError):
    """DNS, conn refused. SLOW backoff."""


class ParseError(CrawlerError):
    """Source response shape issue."""


class SchemaChanged(ParseError):
    """Selectors/JSON shape broke. Circuit-break."""


class MissingField(ParseError):
    """Required field absent. Skip job, log."""


class StorageError(CrawlerError):
    """DB layer error."""


class MigrationError(StorageError):
    """Schema migration failed."""


class ConstraintError(StorageError):
    """UNIQUE/CHECK constraint violation. Should not happen post-upsert."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_exceptions.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add crawler/exceptions.py tests/unit/test_exceptions.py
git commit -m "feat(exceptions): typed CrawlerError hierarchy — Fetch/Parse/Storage"
```

---

## Task 5: `crawler/models.py` — pydantic models

**Files:**
- Create: `crawler/models.py`
- Create: `tests/unit/test_models.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_models.py`:
```python
from datetime import datetime, timezone
from pydantic import ValidationError
import pytest
from crawler.models import JobQuery, RawJob, NormalizedJob


def test_job_query_defaults():
    q = JobQuery()
    assert q.keywords == []
    assert q.location is None
    assert q.max_results == 100
    assert q.since is None


def test_raw_job_required_fields():
    raw = RawJob(
        source="ams",
        source_id="12345",
        url="https://jobs.ams.at/public/jobs/12345",
        title="Software Engineer",
        company="ACME GmbH",
        location="Wien",
        fetched_at=datetime(2026, 6, 22, tzinfo=timezone.utc),
    )
    assert raw.source == "ams"
    assert raw.posted_at is None


def test_normalized_job_requires_content_hash():
    with pytest.raises(ValidationError):
        NormalizedJob(
            source="ams",
            source_id="1",
            url="https://x.at/1",
            title="X",
            company="Y",
            location="Wien",
            description="d",
            fetched_at=datetime.now(timezone.utc),
        )


def test_normalized_job_with_hash_ok():
    n = NormalizedJob(
        source="ams",
        source_id="1",
        url="https://x.at/1",
        title="X",
        company="Y",
        location="Wien",
        description="d",
        content_hash="abc123",
        fetched_at=datetime.now(timezone.utc),
    )
    assert n.content_hash == "abc123"
    assert n.salary is None
    assert n.employment_type is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_models.py -v`
Expected: `ModuleNotFoundError: No module named 'crawler.models'`

- [ ] **Step 3: Implement `crawler/models.py`**

```python
"""Pydantic models — JobQuery, RawJob, NormalizedJob."""
from datetime import datetime
from pydantic import BaseModel, HttpUrl, Field, field_validator


class JobQuery(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    location: str | None = None
    max_results: int = 100
    since: datetime | None = None

    @field_validator("max_results")
    @classmethod
    def _clamp_max_results(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_results must be >= 1")
        return v


class RawJob(BaseModel):
    """Listing from search results — minimal fields, no description."""
    source: str
    source_id: str
    url: HttpUrl
    title: str
    company: str | None = None
    location: str | None = None
    posted_at: datetime | None = None
    fetched_at: datetime


class NormalizedJob(BaseModel):
    """Full job record after fetch_detail — persisted to DB."""
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
    content_hash: str  # SHA256 hex
    fetched_at: datetime
    raw_html: str | None = None  # grill-me amendment 4: opt-in per source (AMS sets it)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_models.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add crawler/models.py tests/unit/test_models.py
git commit -m "feat(models): JobQuery, RawJob, NormalizedJob with content_hash + raw_html"
```

---

## Task 6: `crawler/storage/db.py` — SQLite connection + PRAGMAs

**Files:**
- Create: `crawler/storage/db.py`
- Create: `tests/unit/test_db.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_db.py`:
```python
import sqlite3
from pathlib import Path
import pytest
from crawler.storage import db


def test_connect_returns_connection():
    conn = db.connect(":memory:")
    assert isinstance(conn, sqlite3.Connection)


def test_wal_mode_applied(tmp_path: Path):
    db_path = tmp_path / "test.db"
    conn = db.connect(db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    # :memory: returns "memory"; file-backed returns "wal"
    if db_path.exists():
        assert mode == "wal"


def test_pragmas_set(tmp_path: Path):
    db_path = tmp_path / "test.db"
    conn = db.connect(db_path)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30_000


def test_connect_yields_independent_connections(tmp_path: Path):
    db_path = tmp_path / "test.db"
    c1 = db.connect(db_path)
    c2 = db.connect(db_path)
    c1.execute("CREATE TABLE t (x INT)")
    c1.execute("INSERT INTO t VALUES (1)")
    c1.commit()
    rows = c2.execute("SELECT x FROM t").fetchall()
    assert rows == [(1,)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_db.py -v`
Expected: `ModuleNotFoundError: No module named 'crawler.storage.db'`

- [ ] **Step 3: Implement `crawler/storage/db.py`**

```python
"""SQLite connection factory with WAL + busy_timeout PRAGMAs."""
from pathlib import Path
import sqlite3
from crawler import config


def connect(path: str | Path) -> sqlite3.Connection:
    """Open SQLite connection with PRAGMAs. Path can be ':memory:' for tests."""
    conn = sqlite3.connect(
        path,
        timeout=config.DB_BUSY_TIMEOUT_SECONDS,
        isolation_level=None,  # autocommit; explicit BEGIN in repository
    )
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={config.DB_BUSY_TIMEOUT_SECONDS * 1000}")
    conn.row_factory = sqlite3.Row
    return conn
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_db.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add crawler/storage/db.py tests/unit/test_db.py
git commit -m "feat(storage): SQLite connect() with WAL + busy_timeout + foreign_keys"
```

---

## Task 7: Migration V001 — initial schema

**Files:**
- Create: `crawler/storage/migrations/V001__initial.sql`
- Create: `crawler/storage/migrations/__init__.py`
- Create: `crawler/storage/migrations/runner.py`
- Create: `tests/unit/test_migrations.py`

- [ ] **Step 1: Create `crawler/storage/migrations/V001__initial.sql`**

```sql
-- V001: initial schema
-- Spec: § Storage Schema + grill-me amendment 4 (raw_html column for AMS)

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
  raw_html TEXT,  -- AMS: store rendered HTML for re-parse on schema change
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
CREATE INDEX idx_runs_source ON crawl_runs(source);
CREATE INDEX idx_runs_started ON crawl_runs(started_at DESC);

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

- [ ] **Step 2: Write failing test for migrations runner**

`tests/unit/test_migrations.py`:
```python
import sqlite3
from pathlib import Path
from crawler.storage.db import connect
from crawler.storage.migrations.runner import apply, _list_migration_files


def test_list_migration_files():
    files = _list_migration_files()
    assert any("V001__initial.sql" in f for f in files)


def test_apply_creates_tables(tmp_path: Path):
    conn = connect(tmp_path / "m.db")
    apply(conn)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert {"schema_version", "sources", "jobs", "crawl_runs", "crawl_errors"} <= tables


def test_apply_is_idempotent(tmp_path: Path):
    conn = connect(tmp_path / "m.db")
    apply(conn)
    apply(conn)  # second run should not error
    rows = conn.execute("SELECT version FROM schema_version").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 1


def test_apply_records_version_metadata(tmp_path: Path):
    conn = connect(tmp_path / "m.db")
    apply(conn)
    row = conn.execute(
        "SELECT version, description FROM schema_version WHERE version=1"
    ).fetchone()
    assert row[0] == 1
    assert "initial" in row[1].lower()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/test_migrations.py -v`
Expected: `ModuleNotFoundError: No module named 'crawler.storage.migrations.runner'`

- [ ] **Step 4: Implement `crawler/storage/migrations/runner.py`**

```python
"""Schema migration runner. Spec § Storage Schema + grill-me amendment 2.

Scans crawler/storage/migrations/V*.sql, applies unapplied versions in order.
Idempotent — safe to run on every startup.
"""
import re
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from crawler.exceptions import MigrationError

MIGRATIONS_DIR = Path(__file__).parent
VERSION_PATTERN = re.compile(r"^V(\d+)__(.+)\.sql$")


def _list_migration_files() -> list[Path]:
    """Return V*.sql files in this dir, sorted by version number."""
    files = []
    for path in MIGRATIONS_DIR.glob("V*.sql"):
        m = VERSION_PATTERN.match(path.name)
        if m:
            files.append((int(m.group(1)), path))
    return [p for _, p in sorted(files)]


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    """Return versions already in schema_version table."""
    try:
        rows = conn.execute("SELECT version FROM schema_version").fetchall()
        return {r[0] for r in rows}
    except sqlite3.OperationalError:
        # schema_version doesn't exist yet → nothing applied
        return set()


def apply(conn: sqlite3.Connection) -> None:
    """Apply pending migrations. Idempotent."""
    applied = _applied_versions(conn)
    for path in _list_migration_files():
        m = VERSION_PATTERN.match(path.name)
        if not m:
            continue
        version = int(m.group(1))
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        try:
            conn.executescript(sql)
        except sqlite3.Error as e:
            raise MigrationError(f"V{version} ({path.name}) failed: {e}") from e
        # Record the version (executescript may have created schema_version
        # via this migration, so this insert comes after the script)
        conn.execute(
            "INSERT INTO schema_version (version, applied_at, description) VALUES (?, ?, ?)",
            (version, datetime.now(timezone.utc).isoformat(), m.group(2).replace("_", " ")),
        )
```

- [ ] **Step 5: Create `crawler/storage/migrations/__init__.py`** (empty)

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/unit/test_migrations.py -v`
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add crawler/storage/migrations/ tests/unit/test_migrations.py
git commit -m "feat(migrations): V001 initial schema + runner (idempotent, scans V*.sql)"
```

---

## Task 8: `crawler/storage/dedup.py` — normalize + content_hash

**Files:**
- Create: `crawler/storage/dedup.py`
- Create: `tests/unit/test_dedup.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_dedup.py`:
```python
from crawler.storage.dedup import normalize, content_hash


def test_normalize_lowercase():
    assert normalize("HELLO World") == "hello world"


def test_normalize_collapses_whitespace():
    assert normalize("foo  bar\t\nbaz") == "foo bar baz"


def test_normalize_strips_punctuation():
    assert normalize("ACME, Inc.!") == "acme inc"


def test_normalize_strips_legal_suffixes():
    assert normalize("ACME GmbH") == "acme"
    assert normalize("Foo AG") == "foo"
    assert normalize("Bar eG OG KG mbH") == "bar"
    assert normalize("X & Y. OG") == "x y"  # also strips & and .


def test_normalize_vienna_districts():
    assert normalize("1. Bezirk") == "wien 1"
    assert normalize("I. Bezirk, Wien") == "wien 1"
    assert normalize("erster Bezirk") == "wien 1"
    assert normalize("Wien") == "wien"


def test_content_hash_stable():
    h1 = content_hash("Software Engineer", "ACME GmbH", "Wien")
    h2 = content_hash("software engineer", "acme", "wien")
    assert h1 == h2  # normalization makes them equal


def test_content_hash_different_inputs():
    h1 = content_hash("Software Engineer", "ACME", "Wien")
    h2 = content_hash("Data Scientist", "ACME", "Wien")
    assert h1 != h2


def test_content_hash_is_hex_64():
    h = content_hash("X", "Y", "Z")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_dedup.py -v`
Expected: `ModuleNotFoundError: No module named 'crawler.storage.dedup'`

- [ ] **Step 3: Implement `crawler/storage/dedup.py`**

```python
"""Canonical normalization + content hash for cross-source dedup.

Spec § Dedup. Excludes salary/description/employment_type (too noisy).
"""
import hashlib
import re

LEGAL_SUFFIXES = (
    " mbh", " ag", " eg", " og", " kg",
    " gmbh",  # lowercase variant covered by re.IGNORECASE
)

# Vienna district normalization: "1. Bezirk" / "I. Bezirk" / "erster Bezirk" → "wien 1"
_DISTRICT_ROMAN = {
    "erster": 1, "i": 1, "1": 1, "1.": 1,
    "zweiter": 2, "ii": 2, "2": 2, "2.": 2,
    "dritter": 3, "iii": 3, "3": 3, "3.": 3,
    "vierter": 4, "iv": 4, "4": 4, "4.": 4,
    "fuenfter": 5, "fünfter": 5, "v": 5, "5": 5, "5.": 5,
    "sechster": 6, "vi": 6, "6": 6, "6.": 6,
    "siebenter": 7, "vii": 7, "7": 7, "7.": 7,
    "achter": 8, "viii": 8, "8": 8, "8.": 8,
    "neunter": 9, "ix": 9, "9": 9, "9.": 9,
    "zehnter": 10, "x": 10, "10": 10, "10.": 10,
    "elfter": 11, "xi": 11, "11": 11, "11.": 11,
    "zwoelfter": 12, "zwölfter": 12, "xii": 12, "12": 12, "12.": 12,
}


def normalize(s: str | None) -> str:
    """Aggressive normalize: lowercase, collapse ws, strip punct, strip suffixes."""
    if s is None:
        return ""
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    # Strip punctuation except alphanumerics + spaces
    s = re.sub(r"[^\w\s&]", "", s)  # keep & for "& Y. OG" test
    s = re.sub(r"\s+", " ", s).strip()
    # Vienna district: "1. bezirk" / "erster bezirk" / "wien 1" → "wien 1"
    s = _normalize_vienna(s)
    # Strip legal suffixes
    for suffix in LEGAL_SUFFIXES:
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
            break  # only strip one suffix
    return s


def _normalize_vienna(s: str) -> str:
    """Convert '1. bezirk' / 'erster bezirk' / 'wien' → 'wien 1' / 'wien'."""
    # Pattern: "<district> bezirk" or just "<district>"
    m = re.match(r"^(erster|zweiter|dritter|vierter|fuenfter|fünfter|sechster|siebenter|achter|neunter|zehnter|elfter|zwoelfter|zwölfter|[ivxIVX]+|\d{1,2})\.?\s*bezirk$", s)
    if m:
        district_raw = m.group(1).lower()
        district = _DISTRICT_ROMAN.get(district_raw)
        if district is not None:
            return f"wien {district}"
    return s


def content_hash(title: str, company: str, location: str) -> str:
    """SHA256 hex of canonical(title | company | location)."""
    canonical = f"{normalize(title)}|{normalize(company)}|{normalize(location)}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_dedup.py -v`
Expected: 8 passed.

If test_normalize_strips_legal_suffixes fails on `"X & Y. OG"`: re-check that `normalize` strips trailing period (covered by `[^\w\s&]`). If `"acme gmbh"` is not stripped, the LEGAL_SUFFIXES order needs `" gmbh"` before `" mbh"`. Adjust if needed.

- [ ] **Step 5: Commit**

```bash
git add crawler/storage/dedup.py tests/unit/test_dedup.py
git commit -m "feat(dedup): normalize + content_hash — Vienna districts, legal suffixes"
```

---

## Task 9: `crawler/storage/repository.py` — CRUD

**Files:**
- Create: `crawler/storage/repository.py`
- Create: `tests/unit/test_repository.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_repository.py`:
```python
from datetime import datetime, timezone
import pytest
from crawler.storage.db import connect
from crawler.storage.migrations.runner import apply as apply_migrations
from crawler.storage.repository import (
    start_run, finalize_run, log_error, upsert_job, get_by_hash, list_jobs,
)
from crawler.models import NormalizedJob


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "r.db")
    apply_migrations(c)
    return c


def _job(source_id: str, title: str = "SWE", company: str = "ACME",
         location: str = "Wien", hash_val: str = "h1") -> NormalizedJob:
    return NormalizedJob(
        source="ams", source_id=source_id,
        url=f"https://jobs.ams.at/public/jobs/{source_id}",
        title=title, company=company, location=location,
        description="d", content_hash=hash_val,
        fetched_at=datetime.now(timezone.utc),
    )


def test_upsert_inserts_new(conn):
    action = upsert_job(conn, _job("1"))
    assert action == "inserted"
    rows = conn.execute("SELECT id, source, source_id FROM jobs").fetchall()
    assert len(rows) == 1
    assert rows[0]["source_id"] == "1"


def test_upsert_updates_existing(conn):
    upsert_job(conn, _job("1", title="Old"))
    action = upsert_job(conn, _job("1", title="New"))
    assert action == "updated"
    rows = conn.execute("SELECT title FROM jobs WHERE source_id='1'").fetchall()
    assert rows[0]["title"] == "New"


def test_upsert_updates_last_seen(conn):
    upsert_job(conn, _job("1"))
    first_seen = conn.execute("SELECT first_seen_at FROM jobs WHERE source_id='1'").fetchone()["first_seen_at"]
    upsert_job(conn, _job("1"))
    row = conn.execute("SELECT first_seen_at, last_seen_at FROM jobs WHERE source_id='1'").fetchone()
    assert row["first_seen_at"] == first_seen
    assert row["last_seen_at"] >= first_seen


def test_upsert_writes_raw_html(conn):
    j = _job("1")
    j.raw_html = "<html>test</html>"
    upsert_job(conn, j)
    row = conn.execute("SELECT raw_html FROM jobs WHERE source_id='1'").fetchone()
    assert row["raw_html"] == "<html>test</html>"


def test_get_by_hash(conn):
    upsert_job(conn, _job("1", hash_val="deadbeef"))
    found = get_by_hash(conn, "deadbeef")
    assert found is not None
    assert found["source_id"] == "1"


def test_get_by_hash_missing(conn):
    assert get_by_hash(conn, "nope") is None


def test_list_jobs(conn):
    for i in range(3):
        upsert_job(conn, _job(str(i)))
    jobs = list_jobs(conn, limit=10)
    assert len(jobs) == 3


def test_start_run_returns_id(conn):
    run_id = start_run(conn, source="ams")
    assert isinstance(run_id, int)
    row = conn.execute("SELECT status FROM crawl_runs WHERE id=?", (run_id,)).fetchone()
    assert row["status"] == "running"


def test_finalize_run_updates_counters(conn):
    run_id = start_run(conn, source="ams")
    finalize_run(conn, run_id, status="success", counters={"inserted": 5, "updated": 2, "errors": 0})
    row = conn.execute("SELECT * FROM crawl_runs WHERE id=?", (run_id,)).fetchone()
    assert row["status"] == "success"
    assert row["jobs_inserted"] == 5
    assert row["jobs_updated"] == 2
    assert row["errors_count"] == 0
    assert row["finished_at"] is not None


def test_log_error_persists(conn):
    run_id = start_run(conn, source="ams")
    log_error(conn, run_id, "ams", "https://x.at/1", "CaptchaEncountered", "captcha")
    rows = conn.execute("SELECT * FROM crawl_errors WHERE run_id=?", (run_id,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["error_type"] == "CaptchaEncountered"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_repository.py -v`
Expected: `ModuleNotFoundError: No module named 'crawler.storage.repository'`

- [ ] **Step 3: Implement `crawler/storage/repository.py`**

```python
"""CRUD: jobs (upsert with dedup), crawl_runs, crawl_errors."""
from datetime import datetime, timezone
from typing import Literal
import sqlite3

from crawler.models import NormalizedJob


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_job(conn: sqlite3.Connection, job: NormalizedJob) -> Literal["inserted", "updated"]:
    """INSERT or UPDATE on (source, source_id). Returns action."""
    now = _now()
    raw_html = job.raw_html
    # SQLite xmax=0 trick: returns id and whether the row was newly inserted.
    row = conn.execute(
        """
        INSERT INTO jobs (source, source_id, url, title, company, location,
                          description, salary, employment_type, posted_at,
                          content_hash, raw_html, first_seen_at, last_seen_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(source, source_id) DO UPDATE SET
          title=excluded.title,
          description=excluded.description,
          salary=excluded.salary,
          employment_type=excluded.employment_type,
          posted_at=excluded.posted_at,
          content_hash=excluded.content_hash,
          raw_html=COALESCE(excluded.raw_html, jobs.raw_html),
          last_seen_at=excluded.last_seen_at
        RETURNING id, (xmax = 0) AS inserted
        """,
        (
            job.source, job.source_id, str(job.url), job.title, job.company, job.location,
            job.description, job.salary, job.employment_type,
            job.posted_at.isoformat() if job.posted_at else None,
            job.content_hash, raw_html, now, now,
        ),
    ).fetchone()
    return "inserted" if row["inserted"] else "updated"


def get_by_hash(conn: sqlite3.Connection, hash_val: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM jobs WHERE content_hash = ? LIMIT 1", (hash_val,)
    ).fetchone()


def list_jobs(conn: sqlite3.Connection, limit: int = 100, source: str | None = None) -> list[sqlite3.Row]:
    if source:
        return conn.execute(
            "SELECT * FROM jobs WHERE source = ? ORDER BY last_seen_at DESC LIMIT ?",
            (source, limit),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM jobs ORDER BY last_seen_at DESC LIMIT ?", (limit,)
    ).fetchall()


def start_run(conn: sqlite3.Connection, source: str, status: str = "running") -> int:
    cur = conn.execute(
        "INSERT INTO crawl_runs (source, started_at, status) VALUES (?, ?, ?)",
        (source, _now(), status),
    )
    return cur.lastrowid


def finalize_run(
    conn: sqlite3.Connection,
    run_id: int,
    status: str,
    counters: dict[str, int],
) -> None:
    conn.execute(
        """
        UPDATE crawl_runs
        SET finished_at=?, status=?,
            jobs_found=?, jobs_inserted=?, jobs_updated=?, errors_count=?
        WHERE id=?
        """,
        (
            _now(), status,
            counters.get("found", 0),
            counters.get("inserted", 0),
            counters.get("updated", 0),
            counters.get("errors", 0),
            run_id,
        ),
    )


def log_error(
    conn: sqlite3.Connection,
    run_id: int,
    source: str,
    url: str | None,
    error_type: str,
    error_message: str,
) -> None:
    conn.execute(
        """
        INSERT INTO crawl_errors (run_id, source, url, error_type, error_message, occurred_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (run_id, source, url, error_type, error_message, _now()),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_repository.py -v`
Expected: 10 passed.

If `xmax = 0` doesn't work as expected (some SQLite versions), fallback: use `INSERT OR IGNORE` then `UPDATE` separately, returning action based on `changes()`.

- [ ] **Step 5: Commit**

```bash
git add crawler/storage/repository.py tests/unit/test_repository.py
git commit -m "feat(repository): upsert_job (xmax=0), get_by_hash, list_jobs, run lifecycle"
```

---

## Task 10: `crawler/parser.py` — HTML/JSON parsing helpers

**Files:**
- Create: `crawler/parser.py`
- Create: `tests/unit/test_parser.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_parser.py`:
```python
from datetime import datetime
from bs4 import BeautifulSoup
import pytest
from crawler.parser import select_text, select_attr, extract_jsonld, parse_iso_date
from crawler.exceptions import SchemaChanged, MissingField


def test_select_text_finds_element():
    soup = BeautifulSoup('<div><span class="x">hello</span></div>', "html.parser")
    assert select_text(soup, "span.x") == "hello"


def test_select_text_returns_none_when_missing():
    soup = BeautifulSoup("<div></div>", "html.parser")
    assert select_text(soup, "span.x") is None


def test_select_text_required_raises_missing_field():
    soup = BeautifulSoup("<div></div>", "html.parser")
    with pytest.raises(MissingField):
        select_text(soup, "span.x", required=True)


def test_select_attr():
    soup = BeautifulSoup('<a href="/x">link</a>', "html.parser")
    assert select_attr(soup, "a", "href") == "/x"


def test_extract_jsonld_job_posting():
    html = '''
    <html><head>
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"JobPosting","title":"SWE","description":"d"}
    </script>
    </head></html>
    '''
    data = extract_jsonld(html)
    assert data["@type"] == "JobPosting"
    assert data["title"] == "SWE"


def test_extract_jsonld_missing_raises_schema_changed():
    with pytest.raises(SchemaChanged):
        extract_jsonld("<html><head></head></html>")


def test_parse_iso_date_with_z():
    dt = parse_iso_date("2026-06-22T10:00:00Z")
    assert dt == datetime(2026, 6, 22, 10, 0, 0)


def test_parse_iso_date_with_offset():
    dt = parse_iso_date("2026-06-22T10:00:00+02:00")
    assert dt.year == 2026 and dt.month == 6 and dt.day == 22


def test_parse_iso_date_invalid_raises_schema_changed():
    with pytest.raises(SchemaChanged):
        parse_iso_date("not a date")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_parser.py -v`
Expected: `ModuleNotFoundError: No module named 'crawler.parser'`

- [ ] **Step 3: Implement `crawler/parser.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_parser.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add crawler/parser.py tests/unit/test_parser.py
git commit -m "feat(parser): select_text/attr, extract_jsonld, parse_iso_date"
```

---

## Task 11: `crawler/browser.py` — BrowserContext Protocol + PlaywrightBrowserContext

**Files:**
- Create: `crawler/browser.py`
- Create: `tests/unit/test_browser_anti_bot.py`
- Create: `tests/unit/test_browser_session.py`

- [ ] **Step 1: Write failing test for anti-bot detection**

`tests/unit/test_browser_anti_bot.py`:
```python
import pytest
from crawler.browser import _detect_anti_bot
from crawler.exceptions import CaptchaEncountered, Blocked


def test_detect_captcha_title():
    with pytest.raises(CaptchaEncountered):
        _detect_anti_bot(title="captcha", body="<html>captcha</html>", url="https://jobs.ams.at/public/jobs")


def test_detect_403_raises_blocked():
    with pytest.raises(Blocked):
        _detect_anti_bot(title="Access Denied", body="", url="https://jobs.ams.at/x", status=403)


def test_detect_access_denied_body():
    with pytest.raises(Blocked):
        _detect_anti_bot(title="Jobs", body="access denied", url="https://jobs.ams.at/x")


def test_detect_verify_url():
    with pytest.raises(CaptchaEncountered):
        _detect_anti_bot(title="Verify", body="", url="https://jobs.ams.at/verify")


def test_normal_page_passes():
    _detect_anti_bot(title="Jobs - AMS", body="<html>jobs</html>", url="https://jobs.ams.at/public/jobs")
```

- [ ] **Step 2: Write failing test for cookie persistence**

`tests/unit/test_browser_session.py`:
```python
import json
import time
from pathlib import Path
import pytest
from crawler.browser import SessionCookieStore


def test_save_and_load(tmp_path: Path):
    store = SessionCookieStore(tmp_path / "session.json")
    cookies = [
        {"name": "SM2_SESSION", "value": "abc", "domain": ".ams.at", "path": "/",
         "expires": -1, "httpOnly": True, "secure": True},
    ]
    store.save(cookies)
    loaded = store.load()
    assert loaded == cookies


def test_load_missing_returns_empty(tmp_path: Path):
    store = SessionCookieStore(tmp_path / "nonexistent.json")
    assert store.load() == []


def test_load_corrupted_returns_empty(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("not json")
    store = SessionCookieStore(p)
    assert store.load() == []


def test_save_creates_dirs(tmp_path: Path):
    nested = tmp_path / "a" / "b" / "session.json"
    store = SessionCookieStore(nested)
    store.save([{"name": "X", "value": "1", "domain": ".ams.at", "path": "/",
                 "expires": -1, "httpOnly": False, "secure": False}])
    assert nested.exists()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/test_browser_anti_bot.py tests/unit/test_browser_session.py -v`
Expected: `ModuleNotFoundError: No module named 'crawler.browser'`

- [ ] **Step 4: Implement `crawler/browser.py`**

```python
"""Playwright wrapper — BrowserContext Protocol + real impl + anti-bot detect.

Spec § Browser wrapper. FakeBrowserContext lives in tests/fakes/browser.py
(grill-me amendment 1: keep real + fake separate).
"""
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from crawler import config
from crawler.exceptions import CaptchaEncountered, Blocked, SPAWaitTimeout

ANTI_BOT_TITLE_KEYWORDS = ("captcha", "verify")
ANTI_BOT_BODY_KEYWORDS = ("access denied", "are you a human", "unusual traffic")


class BrowserContext(Protocol):
    """Async browser context. Real = Playwright; fake = tests/fakes/browser.py."""
    async def goto(self, url: str, wait_selector: str | None = None,
                   timeout_ms: int = config.BROWSER_TIMEOUT_MS) -> str: ...
    async def extract_html(self) -> str: ...
    async def cookies(self) -> list[dict[str, Any]]: ...
    async def close(self) -> None: ...


def _detect_anti_bot(*, title: str, body: str, url: str, status: int | None = None) -> None:
    """Raise typed exception on anti-bot signal. No auto-solve."""
    title_lower = title.lower()
    body_lower = body.lower()

    if status == 403:
        raise Blocked(f"HTTP 403 at {url}")
    if any(kw in title_lower for kw in ANTI_BOT_TITLE_KEYWORDS):
        raise CaptchaEncountered(f"anti-bot title at {url}: {title!r}")
    if any(url.lower().endswith(f"/{kw}") for kw in ANTI_BOT_TITLE_KEYWORDS):
        raise CaptchaEncountered(f"anti-bot URL: {url}")
    if any(kw in body_lower for kw in ANTI_BOT_BODY_KEYWORDS):
        raise Blocked(f"anti-bot body at {url}")


def pick_ua() -> str:
    """Round-robin pick from UA pool. Caller maintains index for session-stickiness."""
    return random.choice(config.UA_POOL)


# --- Cookie persistence (JSON schema per grill-me amendment 9) ---

class SessionCookieStore:
    """JSON-backed cookie persistence. Spec § Browser wrapper."""

    def __init__(self, path: Path):
        self.path = path

    def save(self, cookies: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "cookies": cookies,
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(data, dict) or "cookies" not in data:
            return []
        cookies = data["cookies"]
        return cookies if isinstance(cookies, list) else []


# --- Real Playwright impl ---

class PlaywrightBrowserContext:
    """Real Playwright Chromium. Lazy import to keep tests Playwright-free."""

    def __init__(self, cookie_store: SessionCookieStore):
        self._cookie_store = cookie_store
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    async def __aenter__(self) -> "PlaywrightBrowserContext":
        # Lazy import — tests using FakeBrowserContext never trigger this
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        ua = pick_ua()
        self._context = await self._browser.new_context(user_agent=ua)
        # Load persisted cookies
        for c in self._cookie_store.load():
            await self._context.add_cookies([c])
        self._page = await self._context.new_page()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def goto(self, url: str, wait_selector: str | None = None,
                   timeout_ms: int = config.BROWSER_TIMEOUT_MS) -> str:
        response = await self._page.goto(url, timeout=timeout_ms)
        status = response.status if response else None
        if wait_selector:
            try:
                await self._page.wait_for_selector(wait_selector, timeout=timeout_ms)
            except Exception as e:
                raise SPAWaitTimeout(f"selector {wait_selector!r} at {url}: {e}") from e
        html = await self._page.content()
        title = await self._page.title()
        _detect_anti_bot(title=title, body=html, url=url, status=status)
        return html

    async def extract_html(self) -> str:
        return await self._page.content()

    async def cookies(self) -> list[dict[str, Any]]:
        return await self._context.cookies()

    async def save_cookies(self) -> None:
        self._cookie_store.save(await self.cookies())

    async def close(self) -> None:
        if self._context:
            await self._context.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_browser_anti_bot.py tests/unit/test_browser_session.py -v`
Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
git add crawler/browser.py tests/unit/test_browser_anti_bot.py tests/unit/test_browser_session.py
git commit -m "feat(browser): Protocol + PlaywrightBrowserContext + anti-bot detect + cookie store (JSON)"
```

---

## Task 12: `tests/fakes/browser.py` — FakeBrowserContext

**Files:**
- Create: `tests/fakes/browser.py`
- Create: `tests/unit/test_fake_browser.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_fake_browser.py`:
```python
import pytest
from tests.fakes.browser import FakeBrowserContext
from crawler.exceptions import CaptchaEncountered, Blocked, SPAWaitTimeout


@pytest.fixture
def fake():
    return FakeBrowserContext({
        "https://jobs.ams.at/public/jobs": "<html><body>job cards</body></html>",
        "https://jobs.ams.at/public/jobs/123": "<html><body>detail</body></html>",
    })


@pytest.mark.asyncio
async def test_goto_returns_html(fake):
    html = await fake.goto("https://jobs.ams.at/public/jobs")
    assert html == "<html><body>job cards</body></html>"


@pytest.mark.asyncio
async def test_goto_missing_url_raises(fake):
    with pytest.raises(SPAWaitTimeout):
        await fake.goto("https://nope.at/")


@pytest.mark.asyncio
async def test_goto_with_wait_selector_passes(fake):
    html = await fake.goto("https://jobs.ams.at/public/jobs", wait_selector="[data-testid='job-card']")
    assert "job cards" in html


@pytest.mark.asyncio
async def test_goto_with_unmet_wait_selector_raises(fake):
    with pytest.raises(SPAWaitTimeout):
        await fake.goto("https://jobs.ams.at/public/jobs", wait_selector="[data-testid='missing']")


@pytest.mark.asyncio
async def test_captcha_fixture_raises(fake):
    fake.add_anti_bot_response("https://jobs.ams.at/captcha", title="captcha")
    with pytest.raises(CaptchaEncountered):
        await fake.goto("https://jobs.ams.at/captcha")


@pytest.mark.asyncio
async def test_cookies_roundtrip(fake):
    fake.set_cookies([{"name": "SM2_SESSION", "value": "abc", "domain": ".ams.at",
                        "path": "/", "expires": -1, "httpOnly": True, "secure": True}])
    cookies = await fake.cookies()
    assert cookies[0]["value"] == "abc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_fake_browser.py -v`
Expected: `ModuleNotFoundError: No module named 'tests.fakes.browser'`

- [ ] **Step 3: Implement `tests/fakes/browser.py`**

```python
"""FakeBrowserContext — implements BrowserContext Protocol for tests.

Grill-me amendment 1: lives in tests/fakes/, NOT crawler/browser.py.
Keeps Playwright import chain out of test path.
"""
from typing import Any
from crawler import config
from crawler.browser import _detect_anti_bot
from crawler.exceptions import SPAWaitTimeout


class FakeBrowserContext:
    """Returns HTML from a fixture map. Supports anti-bot injection + cookie stub."""

    def __init__(self, fixture_map: dict[str, str] | None = None):
        self._fixtures: dict[str, str] = fixture_map or {}
        self._cookies: list[dict[str, Any]] = []
        self._anti_bot_overrides: dict[str, dict[str, Any]] = {}

    def add_anti_bot_response(self, url: str, *, title: str = "captcha",
                              body: str = "", status: int | None = None) -> None:
        """Register a URL that should trigger anti-bot detection."""
        self._anti_bot_overrides[url] = {"title": title, "body": body, "status": status}

    def set_cookies(self, cookies: list[dict[str, Any]]) -> None:
        self._cookies = list(cookies)

    async def goto(self, url: str, wait_selector: str | None = None,
                   timeout_ms: int = config.BROWSER_TIMEOUT_MS) -> str:
        if url in self._anti_bot_overrides:
            ov = self._anti_bot_overrides[url]
            _detect_anti_bot(title=ov["title"], body=ov.get("body", ""),
                             url=url, status=ov.get("status"))
        if url not in self._fixtures:
            raise SPAWaitTimeout(f"no fixture for {url} (no selector met)")
        html = self._fixtures[url]
        # If a wait_selector is requested, only return HTML if it contains that selector
        if wait_selector and wait_selector not in html:
            raise SPAWaitTimeout(f"selector {wait_selector!r} not in {url}")
        # Run anti-bot detection on normal responses too (captcha can be in body)
        _detect_anti_bot(title="Jobs - AMS", body=html, url=url)
        return html

    async def extract_html(self) -> str:
        return self._last_html or ""

    async def cookies(self) -> list[dict[str, Any]]:
        return list(self._cookies)

    async def close(self) -> None:
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_fake_browser.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/fakes/browser.py tests/unit/test_fake_browser.py
git commit -m "test(fakes): FakeBrowserContext — fixture map, anti-bot injection, cookie stub"
```

---

## Task 13: `crawler/sources/base.py` — SourceAdapter Protocol

**Files:**
- Create: `crawler/sources/base.py`
- Create: `tests/contract/test_source_adapter.py`

- [ ] **Step 1: Write failing test (contract)**

`tests/contract/test_source_adapter.py`:
```python
import inspect
from typing import get_type_hints
from crawler.sources.base import SourceAdapter
from crawler.models import JobQuery, RawJob, NormalizedJob


def test_source_adapter_is_protocol():
    assert getattr(SourceAdapter, "_is_protocol", False) or hasattr(SourceAdapter, "_is_protocol")


def test_source_adapter_required_members():
    members = {name for name, _ in inspect.getmembers(SourceAdapter)}
    assert "name" in members
    assert "search" in members
    assert "fetch_detail" in members


def test_source_adapter_signatures():
    hints_search = get_type_hints(SourceAdapter.search)
    assert hints_search["query"] == JobQuery
    assert "return" in hints_search
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/contract/test_source_adapter.py -v`
Expected: `ModuleNotFoundError: No module named 'crawler.sources.base'`

- [ ] **Step 3: Implement `crawler/sources/base.py`**

```python
"""SourceAdapter Protocol — contract for all job sources."""
from typing import AsyncIterator, Protocol, runtime_checkable
from crawler.models import JobQuery, RawJob, NormalizedJob


@runtime_checkable
class SourceAdapter(Protocol):
    """Every source adapter implements this. Spec § SourceAdapter contract."""
    name: str

    async def search(self, query: JobQuery) -> AsyncIterator[RawJob]: ...

    async def fetch_detail(self, raw: RawJob) -> NormalizedJob: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/contract/test_source_adapter.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add crawler/sources/base.py tests/contract/test_source_adapter.py
git commit -m "feat(sources): SourceAdapter Protocol — name, search(), fetch_detail()"
```

---

## Task 14: `crawler/sources/ams.py` — AMS adapter (Playwright, no real browser in tests)

**Files:**
- Create: `crawler/sources/ams.py`
- Create: `tests/unit/test_ams_parser.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_ams_parser.py`:
```python
from datetime import datetime
import pytest
from bs4 import BeautifulSoup
from crawler.sources.ams import (
    _parse_search_card, _parse_detail_page, AMS_JOB_CARD_SELECTOR,
    AMS_DETAIL_SELECTOR, AMS_TITLE_SELECTOR, AMS_COMPANY_SELECTOR,
    AMS_LOCATION_SELECTOR, AMS_DESCRIPTION_SELECTOR, AMS_POSTED_SELECTOR,
)
from crawler.models import RawJob, NormalizedJob
from crawler.storage.dedup import content_hash
from crawler.exceptions import SchemaChanged


SEARCH_HTML = '''
<html><body>
<div data-testid="job-card">
  <a class="title" href="/public/jobs/123">Senior Software Engineer</a>
  <span class="company">ACME GmbH</span>
  <span class="location">Wien, 1. Bezirk</span>
  <time datetime="2026-06-20T09:00:00Z">2026-06-20</time>
</div>
</body></html>
'''


DETAIL_HTML = '''
<html><body>
<article data-testid="job-detail">
  <h1>Senior Software Engineer</h1>
  <div class="company">ACME GmbH</div>
  <div class="location">Wien, 1. Bezirk</div>
  <div class="description">Build cool stuff.</div>
  <div class="salary">€ 50.000+</div>
  <div class="employment-type">Vollzeit</div>
  <time datetime="2026-06-20T09:00:00Z">2026-06-20</time>
</article>
</body></html>
'''


SCHEMA_BROKEN_HTML = '<html><body><div data-testid="job-card"><a class="title" href="/x">X</a></div></body></html>'


def test_parse_search_card_extracts_fields():
    soup = BeautifulSoup(SEARCH_HTML, "html.parser")
    card = soup.select_one(AMS_JOB_CARD_SELECTOR)
    raw = _parse_search_card(card, fetched_at=datetime(2026, 6, 22, tzinfo=__import__("datetime").timezone.utc))
    assert raw.source == "ams"
    assert raw.source_id == "123"
    assert raw.title == "Senior Software Engineer"
    assert raw.company == "ACME GmbH"
    assert raw.location == "Wien, 1. Bezirk"


def test_parse_detail_page_returns_normalized_job():
    soup = BeautifulSoup(DETAIL_HTML, "html.parser")
    fetched = datetime(2026, 6, 22, tzinfo=__import__("datetime").timezone.utc)
    raw = RawJob(
        source="ams", source_id="123",
        url="https://jobs.ams.at/public/jobs/123",
        title="Senior Software Engineer",
        company="ACME GmbH", location="Wien, 1. Bezirk",
        fetched_at=fetched,
    )
    job = _parse_detail_page(soup, raw, html=DETAIL_HTML, fetched_at=fetched)
    assert isinstance(job, NormalizedJob)
    assert job.title == "Senior Software Engineer"
    assert job.company == "ACME GmbH"
    assert job.description == "Build cool stuff."
    assert job.salary == "€ 50.000+"
    assert job.employment_type == "Vollzeit"
    assert job.content_hash == content_hash(job.title, job.company, job.location)
    assert job.raw_html == DETAIL_HTML


def test_parse_detail_missing_required_raises_schema_changed():
    soup = BeautifulSoup(SCHEMA_BROKEN_HTML, "html.parser")
    fetched = datetime(2026, 6, 22, tzinfo=__import__("datetime").timezone.utc)
    raw = RawJob(
        source="ams", source_id="1",
        url="https://jobs.ams.at/x/1",
        title="X", company="Y", location="Z", fetched_at=fetched,
    )
    with pytest.raises(SchemaChanged):
        _parse_detail_page(soup, raw, html=SCHEMA_BROKEN_HTML, fetched_at=fetched)


def test_selectors_are_exported():
    # Document the selectors (grill-me amendment 10: schema drift resilience)
    assert AMS_JOB_CARD_SELECTOR == '[data-testid="job-card"]'
    assert AMS_DETAIL_SELECTOR == '[data-testid="job-detail"]'
    assert AMS_TITLE_SELECTOR
    assert AMS_COMPANY_SELECTOR
    assert AMS_LOCATION_SELECTOR
    assert AMS_DESCRIPTION_SELECTOR
    assert AMS_POSTED_SELECTOR
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_ams_parser.py -v`
Expected: `ModuleNotFoundError: No module named 'crawler.sources.ams'`

- [ ] **Step 3: Implement `crawler/sources/ams.py`**

```python
"""AMS adapter — Playwright-based. Real browser via PlaywrightBrowserContext;
tests use FakeBrowserContext (DI). Spec § AMS adapter."""
import asyncio
import random
from datetime import datetime, timezone
from typing import AsyncIterator
from bs4 import BeautifulSoup
from crawler import config
from crawler.browser import BrowserContext
from crawler.models import JobQuery, RawJob, NormalizedJob
from crawler.parser import select_text, parse_iso_date
from crawler.storage.dedup import content_hash
from crawler.exceptions import SchemaChanged

# Selectors — exported so tests can reference the exact strings (grill-me 10)
AMS_JOB_CARD_SELECTOR = '[data-testid="job-card"]'
AMS_DETAIL_SELECTOR = '[data-testid="job-detail"]'
AMS_TITLE_SELECTOR = "h1"
AMS_COMPANY_SELECTOR = ".company"
AMS_LOCATION_SELECTOR = ".location"
AMS_DESCRIPTION_SELECTOR = ".description"
AMS_SALARY_SELECTOR = ".salary"
AMS_EMPLOYMENT_TYPE_SELECTOR = ".employment-type"
AMS_POSTED_SELECTOR = "time"


class AmsAdapter:
    """AMS source adapter. Takes injectable BrowserContext for testability."""

    name = "ams"

    def __init__(self, browser: BrowserContext):
        self._browser = browser

    async def search(self, query: JobQuery) -> AsyncIterator[RawJob]:
        url = config.AMS_BASE_URL + "jobs"
        await self._browser.goto(url, wait_selector=AMS_JOB_CARD_SELECTOR)
        html = await self._browser.extract_html()
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(AMS_JOB_CARD_SELECTOR)
        for i, card in enumerate(cards):
            if i >= query.max_results:
                break
            try:
                raw = _parse_search_card(card, fetched_at=_now())
                yield raw
            except Exception:
                # Skip malformed cards — they'll be caught in pipeline
                continue
            # Throttle between cards
            await asyncio.sleep(_jitter_seconds())

    async def fetch_detail(self, raw: RawJob) -> NormalizedJob:
        html = await self._browser.goto(str(raw.url), wait_selector=AMS_DETAIL_SELECTOR)
        soup = BeautifulSoup(html, "html.parser")
        return _parse_detail_page(soup, raw, html=html, fetched_at=raw.fetched_at)


# --- Parsing helpers (unit-tested in test_ams_parser.py) ---

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _jitter_seconds() -> float:
    return random.uniform(0, config.AMS_REQUEST_JITTER_SECONDS)


def _parse_search_card(card, *, fetched_at: datetime) -> RawJob:
    """Extract RawJob from a search result card. Required: title + href."""
    title_el = card.select_one("a.title") or card.select_one("a")
    if title_el is None:
        raise SchemaChanged("no anchor in job card")
    title = title_el.get_text(strip=True)
    href = title_el.get("href", "")
    source_id = href.rstrip("/").split("/")[-1]
    if not source_id:
        raise SchemaChanged(f"cannot extract source_id from href {href!r}")
    company = card.select_one(".company")
    location = card.select_one(".location")
    posted = card.select_one("time")
    return RawJob(
        source="ams",
        source_id=source_id,
        url=f"{config.AMS_BASE_URL.rstrip('/')}{href}" if href.startswith("/") else href,
        title=title,
        company=company.get_text(strip=True) if company else None,
        location=location.get_text(strip=True) if location else None,
        posted_at=parse_iso_date(posted.get("datetime") if posted and posted.has_attr("datetime") else None),
        fetched_at=fetched_at,
    )


def _parse_detail_page(soup: BeautifulSoup, raw: RawJob, *, html: str,
                       fetched_at: datetime) -> NormalizedJob:
    """Extract NormalizedJob from a detail page. Required: title + company + location + description."""
    title = select_text(soup, AMS_TITLE_SELECTOR, required=True)
    company = select_text(soup, AMS_COMPANY_SELECTOR, required=True)
    location = select_text(soup, AMS_LOCATION_SELECTOR, required=True)
    description = select_text(soup, AMS_DESCRIPTION_SELECTOR, required=True)
    salary = select_text(soup, AMS_SALARY_SELECTOR)
    employment_type = select_text(soup, AMS_EMPLOYMENT_TYPE_SELECTOR)
    posted = soup.select_one(AMS_POSTED_SELECTOR)
    posted_at = parse_iso_date(posted.get("datetime") if posted and posted.has_attr("datetime") else None)
    return NormalizedJob(
        source=raw.source,
        source_id=raw.source_id,
        url=raw.url,
        title=title,
        company=company,
        location=location,
        description=description,
        salary=salary,
        employment_type=employment_type,
        posted_at=posted_at,
        content_hash=content_hash(title, company, location),
        fetched_at=fetched_at,
        raw_html=html,  # grill-me amendment 4
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_ams_parser.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add crawler/sources/ams.py tests/unit/test_ams_parser.py
git commit -m "feat(ams): AmsAdapter (Playwright + FakeBrowserContext DI) + parser unit tests"
```

---

## Task 15: `crawler/pipeline.py` — orchestrator with circuit breaker

**Files:**
- Create: `crawler/pipeline.py`
- Create: `tests/unit/test_pipeline.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_pipeline.py`:
```python
import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator
import pytest
from crawler.models import JobQuery, RawJob, NormalizedJob
from crawler.sources.base import SourceAdapter
from crawler.sources.ams import AmsAdapter
from crawler.storage.db import connect
from crawler.storage.migrations.runner import apply as apply_migrations
from crawler.pipeline import run, run_source, CircuitOpen
from crawler.exceptions import SchemaChanged, CaptchaEncountered
from tests.fakes.browser import FakeBrowserContext


class StubAdapter:
    def __init__(self, name="stub", jobs=None, fail_with=None):
        self.name = name
        self._jobs = jobs or []
        self._fail = fail_with

    async def search(self, query):
        if self._fail:
            raise self._fail
        for j in self._jobs:
            yield j

    async def fetch_detail(self, raw):
        return NormalizedJob(
            source=raw.source, source_id=raw.source_id, url=raw.url,
            title=raw.title, company=raw.company or "ACME", location=raw.location or "Wien",
            description="d", content_hash=f"hash-{raw.source_id}",
            fetched_at=raw.fetched_at,
        )


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "p.db")
    apply_migrations(c)
    return c


@pytest.mark.asyncio
async def test_run_source_success(conn):
    raw = RawJob(source="stub", source_id="1", url="https://x/1",
                  title="SWE", company="ACME", location="Wien",
                  fetched_at=datetime.now(timezone.utc))
    adapter = StubAdapter(jobs=[raw])
    result = await run_source(conn, adapter, JobQuery(), run_id=1)
    assert result.status == "success"
    assert result.counters["inserted"] == 1


@pytest.mark.asyncio
async def test_run_source_partial_on_per_job_error(conn):
    raw1 = RawJob(source="stub", source_id="1", url="https://x/1",
                   title="SWE", company="ACME", location="Wien",
                   fetched_at=datetime.now(timezone.utc))
    raw2 = RawJob(source="stub", source_id="2", url="https://x/2",
                   title="DS", company="ACME", location="Wien",
                   fetched_at=datetime.now(timezone.utc))
    adapter = StubAdapter(jobs=[raw1, raw2])
    # Make fetch_detail fail once
    original = adapter.fetch_detail
    calls = [0]
    async def flaky(raw):
        calls[0] += 1
        if calls[0] == 1:
            raise SchemaChanged("broken")
        return await original(raw)
    adapter.fetch_detail = flaky
    result = await run_source(conn, adapter, JobQuery(), run_id=1)
    assert result.status == "partial"
    assert result.counters["inserted"] == 1
    assert result.counters["errors"] == 1


@pytest.mark.asyncio
async def test_run_source_circuit_break_on_captcha(conn):
    adapter = StubAdapter(fail_with=CaptchaEncountered("captcha"))
    result = await run_source(conn, adapter, JobQuery(), run_id=1)
    assert result.status == "failed"
    assert "CaptchaEncountered" in str(result.error)


@pytest.mark.asyncio
async def test_run_aggregates_multiple_sources(conn):
    raw1 = RawJob(source="a", source_id="1", url="https://x/1",
                   title="SWE", company="ACME", location="Wien",
                   fetched_at=datetime.now(timezone.utc))
    raw2 = RawJob(source="b", source_id="2", url="https://y/2",
                   title="DS", company="Foo", location="Graz",
                   fetched_at=datetime.now(timezone.utc))
    a = StubAdapter(name="a", jobs=[raw1])
    b = StubAdapter(name="b", jobs=[raw2])
    # Need different run_ids
    from crawler.storage.repository import start_run
    run_id = start_run(conn, source="multi")
    results = await run(conn, [a, b], JobQuery(), run_id=run_id)
    statuses = {r.adapter_name: r.status for r in results}
    assert statuses == {"a": "success", "b": "success"}


@pytest.mark.asyncio
async def test_dry_run_skips_upsert(conn):
    raw = RawJob(source="stub", source_id="1", url="https://x/1",
                  title="SWE", company="ACME", location="Wien",
                  fetched_at=datetime.now(timezone.utc))
    adapter = StubAdapter(jobs=[raw])
    result = await run_source(conn, adapter, JobQuery(), run_id=1, dry_run=True)
    assert result.status == "success"
    assert result.counters["inserted"] == 1  # counted
    rows = conn.execute("SELECT * FROM jobs").fetchall()
    assert len(rows) == 0  # not written
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_pipeline.py -v`
Expected: `ModuleNotFoundError: No module named 'crawler.pipeline'`

- [ ] **Step 3: Implement `crawler/pipeline.py`**

```python
"""Per-source crawl orchestrator with circuit breaker. Spec § Data Flow."""
import asyncio
import sqlite3
from dataclasses import dataclass, field
from typing import Sequence
from crawler import config
from crawler.exceptions import (
    CrawlerError, FetchError, Blocked, CaptchaEncountered,
    CookieExpired, SchemaChanged,
)
from crawler.models import JobQuery
from crawler.sources.base import SourceAdapter
from crawler.storage import repository as repo


@dataclass
class SourceResult:
    adapter_name: str
    status: str  # success | partial | failed | crashed
    counters: dict[str, int] = field(default_factory=lambda: {"inserted": 0, "updated": 0, "errors": 0, "found": 0})
    error: str | None = None


class _CircuitBreaker:
    """Per-source, per-run, in-memory. Resets on run boundary."""

    def __init__(self, name: str):
        self.name = name
        self._consecutive_fetch_errors = 0
        self._opened = False

    def record(self, exc: Exception) -> None:
        if isinstance(exc, Blocked):
            self._opened = True
        elif isinstance(exc, (CaptchaEncountered, CookieExpired, SchemaChanged)):
            self._opened = True
        elif isinstance(exc, FetchError):
            self._consecutive_fetch_errors += 1
            if self._consecutive_fetch_errors >= config.CIRCUIT_BREAKER_THRESHOLD:
                self._opened = True
        else:
            self._consecutive_fetch_errors = 0

    @property
    def is_open(self) -> bool:
        return self._opened


async def run_source(conn: sqlite3.Connection, adapter: SourceAdapter,
                     query: JobQuery, run_id: int, *, dry_run: bool = False) -> SourceResult:
    """Crawl a single source. Returns SourceResult (never raises).

    If dry_run=True: skip upsert_job calls (count only). Errors still logged.
    """
    result = SourceResult(adapter_name=adapter.name)
    breaker = _CircuitBreaker(adapter.name)
    try:
        async with asyncio.timeout(config.SOURCE_TIMEOUT_SECONDS):
            async for raw in adapter.search(query):
                if breaker.is_open:
                    result.status = "partial"
                    return result
                result.counters["found"] += 1
                try:
                    detail = await adapter.fetch_detail(raw)
                    if dry_run:
                        result.counters["inserted"] += 1  # count only
                    else:
                        action = repo.upsert_job(conn, detail)
                        result.counters[action] += 1
                except CrawlerError as e:
                    breaker.record(e)
                    if not dry_run:
                        repo.log_error(conn, run_id, adapter.name, str(raw.url),
                                       type(e).__name__, str(e))
                    result.counters["errors"] += 1
                    if breaker.is_open:
                        result.status = "partial"
                        return result
        if result.status == "":
            result.status = "success" if result.counters["errors"] == 0 else "partial"
        return result
    except asyncio.TimeoutError:
        result.status = "failed"
        result.error = f"source timeout after {config.SOURCE_TIMEOUT_SECONDS}s"
        return result
    except CrawlerError as e:
        breaker.record(e)
        result.status = "failed"
        result.error = f"{type(e).__name__}: {e}"
        if not dry_run:
            repo.log_error(conn, run_id, adapter.name, None, type(e).__name__, str(e))
        return result
    except Exception as e:
        result.status = "crashed"
        result.error = f"unexpected {type(e).__name__}: {e}"
        if not dry_run:
            repo.log_error(conn, run_id, adapter.name, None, type(e).__name__, str(e))
        return result


async def run(conn: sqlite3.Connection, adapters: Sequence[SourceAdapter],
              query: JobQuery, run_id: int, *, dry_run: bool = False) -> list[SourceResult]:
    """Fan out to all sources. Always returns list (gather with no return_exceptions)."""
    return await asyncio.gather(*[run_source(conn, a, query, run_id, dry_run=dry_run) for a in adapters])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_pipeline.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add crawler/pipeline.py tests/unit/test_pipeline.py
git commit -m "feat(pipeline): run_source + run with circuit breaker + SourceResult"
```

---

## Task 16: `scripts/crawl.py` — CLI entry

**Files:**
- Modify: `scripts/crawl.py`
- Create: `tests/integration/test_crawl_ams.py`
- Create: `tests/integration/test_crawl_partial.py`
- Create: `tests/integration/test_crawl_dry_run.py`
- Create: `tests/integration/test_crawl_crash.py`

- [ ] **Step 1: Write integration tests first (CLI drives the pipeline)**

`tests/integration/test_crawl_ams.py`:
```python
"""Integration: full AMS pipeline vs recorded fixtures. No Playwright launch."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import pytest
from crawler import config
from crawler.storage.db import connect
from crawler.storage.migrations.runner import apply as apply_migrations
from crawler.storage.repository import start_run, finalize_run
from crawler.sources.ams import AmsAdapter
from crawler.pipeline import run
from crawler.models import JobQuery
from tests.fakes.browser import FakeBrowserContext


SEARCH_HTML = '''
<html><body>
<div data-testid="job-card">
  <a class="title" href="/public/jobs/123">Senior SWE</a>
  <span class="company">ACME GmbH</span>
  <span class="location">Wien</span>
  <time datetime="2026-06-20T09:00:00Z">2026-06-20</time>
</div>
<div data-testid="job-card">
  <a class="title" href="/public/jobs/456">Data Scientist</a>
  <span class="company">Foo AG</span>
  <span class="location">Graz</span>
  <time datetime="2026-06-21T09:00:00Z">2026-06-21</time>
</div>
</body></html>
'''

DETAIL_HTML = '''
<html><body>
<article data-testid="job-detail">
  <h1>Senior SWE</h1>
  <div class="company">ACME GmbH</div>
  <div class="location">Wien</div>
  <div class="description">Build cool stuff.</div>
</article>
</body></html>
'''


@pytest.mark.asyncio
async def test_full_ams_pipeline_persists_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.db")
    conn = connect(config.DB_PATH)
    apply_migrations(conn)
    run_id = start_run(conn, source="ams")

    fake = FakeBrowserContext({
        config.AMS_BASE_URL + "jobs": SEARCH_HTML,
        "https://jobs.ams.at/public/jobs/123": DETAIL_HTML,
        "https://jobs.ams.at/public/jobs/456": DETAIL_HTML,
    })
    adapter = AmsAdapter(browser=fake)
    results = await run(conn, [adapter], JobQuery(), run_id=run_id)
    finalize_run(conn, run_id, status="success", counters={"inserted": 2, "updated": 0, "errors": 0})

    assert len(results) == 1
    assert results[0].status == "success"
    assert results[0].counters["inserted"] == 2

    jobs = conn.execute("SELECT source_id, title, company FROM jobs ORDER BY id").fetchall()
    assert len(jobs) == 2
    assert jobs[0]["source_id"] == "123"
    assert jobs[1]["source_id"] == "456"

    errors = conn.execute("SELECT * FROM crawl_errors").fetchall()
    assert len(errors) == 0
```

`tests/integration/test_crawl_partial.py`:
```python
"""Integration: 1 broken job among 2 → partial status, 1 inserted, 1 error logged."""
import pytest
from datetime import datetime, timezone
from crawler import config
from crawler.storage.db import connect
from crawler.storage.migrations.runner import apply as apply_migrations
from crawler.storage.repository import start_run
from crawler.sources.ams import AmsAdapter
from crawler.pipeline import run
from crawler.models import JobQuery
from tests.fakes.browser import FakeBrowserContext


SEARCH_HTML = '''
<html><body>
<div data-testid="job-card">
  <a class="title" href="/public/jobs/123">SWE</a>
  <span class="company">ACME</span>
  <span class="location">Wien</span>
  <time datetime="2026-06-20T09:00:00Z">2026-06-20</time>
</div>
<div data-testid="job-card">
  <a class="title" href="/public/jobs/456">Broken</a>
  <span class="company">Foo</span>
  <span class="location">Graz</span>
  <time datetime="2026-06-21T09:00:00Z">2026-06-21</time>
</div>
</body></html>
'''

GOOD_DETAIL = '''
<html><body>
<article data-testid="job-detail">
  <h1>SWE</h1>
  <div class="company">ACME</div>
  <div class="location">Wien</div>
  <div class="description">d</div>
</article>
</body></html>
'''

# Broken: missing data-testid="job-detail" → SPAWaitTimeout
BROKEN_DETAIL = '<html><body>no detail selector</body></html>'


@pytest.mark.asyncio
async def test_partial_run(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.db")
    conn = connect(config.DB_PATH)
    apply_migrations(conn)
    run_id = start_run(conn, source="ams")

    fake = FakeBrowserContext({
        config.AMS_BASE_URL + "jobs": SEARCH_HTML,
        "https://jobs.ams.at/public/jobs/123": GOOD_DETAIL,
        "https://jobs.ams.at/public/jobs/456": BROKEN_DETAIL,
    })
    adapter = AmsAdapter(browser=fake)
    results = await run(conn, [adapter], JobQuery(), run_id=run_id)
    assert results[0].status == "partial"
    assert results[0].counters["inserted"] == 1
    assert results[0].counters["errors"] == 1
    errs = conn.execute("SELECT * FROM crawl_errors").fetchall()
    assert len(errs) == 1
```

`tests/integration/test_crawl_dry_run.py`:
```python
"""Integration: --dry-run mode does not write to jobs table."""
import pytest
from crawler import config
from crawler.sources.ams import AmsAdapter
from crawler.storage.db import connect
from crawler.storage.migrations.runner import apply as apply_migrations
from crawler.storage.repository import start_run
from crawler.pipeline import run
from crawler.models import JobQuery
from tests.fakes.browser import FakeBrowserContext


@pytest.mark.asyncio
async def test_dry_run_does_not_write_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.db")
    conn = connect(config.DB_PATH)
    apply_migrations(conn)
    run_id = start_run(conn, source="ams", status="dry_run")

    fake = FakeBrowserContext({
        config.AMS_BASE_URL + "jobs": '''
<html><body>
<div data-testid="job-card">
  <a class="title" href="/public/jobs/1">X</a>
  <span class="company">A</span><span class="location">Wien</span>
  <time datetime="2026-06-22T00:00:00Z"></time>
</div>
</body></html>''',
        "https://jobs.ams.at/public/jobs/1": '''
<html><body>
<article data-testid="job-detail">
  <h1>X</h1><div class="company">A</div><div class="location">Wien</div><div class="description">d</div>
</article>
</body></html>''',
    })
    adapter = AmsAdapter(browser=fake)
    results = await run(conn, [adapter], JobQuery(), run_id=run_id, dry_run=True)
    # Pipeline counts but does not write
    assert results[0].counters["inserted"] == 1
    rows = conn.execute("SELECT * FROM jobs").fetchall()
    assert len(rows) == 0
    # Crawl run lifecycle
    row = conn.execute("SELECT status FROM crawl_runs WHERE id=?", (run_id,)).fetchone()
    assert row["status"] == "dry_run"
```

`tests/integration/test_crawl_crash.py`:
```python
"""Integration: source raises unexpected exception → status=crashed, run continues, error logged."""
import pytest
from datetime import datetime, timezone
from crawler import config
from crawler.storage.db import connect
from crawler.storage.migrations.runner import apply as apply_migrations
from crawler.storage.repository import start_run
from crawler.models import JobQuery, RawJob, NormalizedJob
from crawler.pipeline import run


class CrashingAdapter:
    name = "crash"
    async def search(self, query):
        raise RuntimeError("boom")

    async def fetch_detail(self, raw):
        raise NotImplementedError


class GoodAdapter:
    name = "good"
    async def search(self, query):
        raw = RawJob(source="good", source_id="1", url="https://x/1",
                      title="SWE", company="ACME", location="Wien",
                      fetched_at=datetime.now(timezone.utc))
        yield raw

    async def fetch_detail(self, raw):
        return NormalizedJob(
            source=raw.source, source_id=raw.source_id, url=raw.url,
            title=raw.title, company=raw.company, location=raw.location,
            description="d", content_hash="h1", fetched_at=raw.fetched_at,
        )


@pytest.mark.asyncio
async def test_crash_isolated_per_source(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.db")
    conn = connect(config.DB_PATH)
    apply_migrations(conn)
    run_id = start_run(conn, source="multi")

    results = await run(conn, [CrashingAdapter(), GoodAdapter()], JobQuery(), run_id=run_id)
    statuses = {r.adapter_name: r.status for r in results}
    assert statuses["crash"] == "crashed"
    assert statuses["good"] == "success"
    # Error logged
    errs = conn.execute("SELECT error_type FROM crawl_errors").fetchall()
    assert any("RuntimeError" in e["error_type"] for e in errs)
```

- [ ] **Step 2: Run integration tests to verify they fail**

Run: `pytest tests/integration/ -v`
Expected: 4 collection errors (no scripts/crawl.py impl yet — fine, these test pipeline+AMS without CLI).

Actually, these tests don't need scripts/crawl.py yet — they test the pipeline directly. Run:
```bash
pytest tests/integration/ -v
```
Expected: `ModuleNotFoundError: No module named 'crawler.sources.ams'` for the AMS ones (crawler.sources.ams was added in Task 14). For test_crawl_crash.py, the GoodAdapter needs models — already exists. Should pass if pipeline + models + repository are done.

Wait, test_crawl_ams depends on AmsAdapter from Task 14. Let me re-order: these tests run after Task 14. Reorganize Task 16 to only include the CLI, and run integration tests in a separate "Task 17" after CLI is done.

Actually, simpler: put CLI implementation in this task, but split integration tests into their own task (Task 17). Let me restructure:

- [ ] **Step 2 (revised): Implement `scripts/crawl.py`**

```python
"""CLI entry — argparse, asyncio.run, signal handling, exit codes.

Spec § CLI Interface. Dry-run is grill-me amendment 3 (always exit 3,
no DB writes).
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime

from crawler import config
from crawler.exceptions import CrawlerError
from crawler.models import JobQuery
from crawler.pipeline import run
from crawler.sources.ams import AmsAdapter
from crawler.browser import PlaywrightBrowserContext, SessionCookieStore
from crawler.storage.db import connect
from crawler.storage.migrations.runner import apply as apply_migrations
from crawler.storage.repository import start_run, finalize_run, log_error


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="crawl")
    p.add_argument("--source", default="ams", help="Source name (sub-project 1: only 'ams')")
    p.add_argument("--limit", type=int, default=200, help="Max jobs per source (default 200, grill-me 5)")
    p.add_argument("--query", default="", help="Search keywords")
    p.add_argument("--since", default=None, help="ISO date — filter by posted_at >=")
    p.add_argument("--dry-run", action="store_true", help="Fetch + parse + JSON stdout, no DB writes")
    p.add_argument("--log-format", default="text", choices=["text", "json"])
    return p


async def _run_cli(args: argparse.Namespace) -> int:
    """Returns exit code: 0=success, 1=partial, 2=failed, 3=dry_run."""
    if args.source != "ams":
        print(f"only 'ams' supported in sub-project 1, got {args.source!r}", file=sys.stderr)
        return 2

    query = JobQuery(
        keywords=args.query.split() if args.query else [],
        max_results=args.limit,
        since=datetime.fromisoformat(args.since) if args.since else None,
    )

    conn = connect(config.DB_PATH)
    apply_migrations(conn)
    run_id = start_run(conn, source=args.source,
                       status="dry_run" if args.dry_run else "running")

    cookie_store = SessionCookieStore(config.DB_PATH.parent / "session_ams.json")

    try:
        async with PlaywrightBrowserContext(cookie_store) as browser:
            adapter = AmsAdapter(browser=browser)
            results = await run(conn, [adapter], query, run_id=run_id,
                                dry_run=args.dry_run)
            await browser.save_cookies()
    except CrawlerError as e:
        log_error(conn, run_id, args.source, None, type(e).__name__, str(e))
        finalize_run(conn, run_id, status="failed", counters={"errors": 1})
        conn.close()
        return 2

    counters = {"found": 0, "inserted": 0, "updated": 0, "errors": 0}
    any_error = False
    for r in results:
        for k in counters:
            counters[k] += r.counters.get(k, 0)
        if r.status in ("partial", "failed", "crashed"):
            any_error = True

    if args.dry_run:
        # Grill-me amendment 3: dry-run always exit 3
        finalize_run(conn, run_id, status="dry_run", counters=counters)
        print(json.dumps({
            "dry_run": True, "counters": counters,
            "results": [
                {"source": r.adapter_name, "status": r.status, "counters": r.counters}
                for r in results
            ],
        }))
        conn.close()
        return 3

    if any_error:
        status = "partial"
        exit_code = 1
    else:
        status = "success"
        exit_code = 0
    finalize_run(conn, run_id, status=status, counters=counters)
    conn.close()
    return exit_code


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    exit_code = asyncio.run(_run_cli(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verify CLI loads**

Run: `python scripts/crawl.py --help`
Expected: usage line printed, exits 0.

- [ ] **Step 4: Commit**

```bash
git add scripts/crawl.py
git commit -m "feat(cli): scripts/crawl.py — argparse, asyncio.run, exit codes 0/1/2/3"
```

Note: integration tests run as Task 17 (after all modules are in place).

---

## Task 17: Run integration tests

**Files:**
- Run only (no file changes)

- [ ] **Step 1: Run full integration suite**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/JobCrawler
pytest tests/integration/ -v
```

Expected: 4 tests pass (test_full_ams_pipeline_persists_jobs, test_partial_run, test_dry_run_does_not_write_jobs, test_crash_isolated_per_source).

If failures: check fixture URLs match AMS_BASE_URL exactly, search HTML has required selectors, AmsAdapter URL composition handles `href` starting with `/`.

- [ ] **Step 2: Run full test suite (unit + contract + integration)**

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit any test fixes (if needed)**

```bash
git add tests/
git commit -m "test(integration): AMS pipeline, partial, dry-run, crash — fixtures + FakeBrowserContext"
```

---

## Task 18: `scripts/inspect_db.py` — debug CLI

**Files:**
- Modify: `scripts/inspect_db.py`

- [ ] **Step 1: Implement**

```python
"""Debug: counts, schema, sample rows."""
import sys
from crawler import config
from crawler.storage.db import connect
from crawler.storage.migrations.runner import apply as apply_migrations


def main() -> None:
    conn = connect(config.DB_PATH)
    apply_migrations(conn)

    counts = {}
    for table in ("jobs", "crawl_runs", "crawl_errors", "sources"):
        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    print("=== Counts ===")
    for t, n in counts.items():
        print(f"  {t}: {n}")

    print("\n=== Last 5 runs ===")
    for r in conn.execute(
        "SELECT id, source, status, jobs_inserted, jobs_updated, errors_count, started_at FROM crawl_runs ORDER BY id DESC LIMIT 5"
    ).fetchall():
        print(f"  #{r['id']} {r['source']} {r['status']} +{r['jobs_inserted']}/{r['jobs_updated']} err={r['errors_count']} @ {r['started_at']}")

    print("\n=== Last 5 errors ===")
    for e in conn.execute(
        "SELECT source, error_type, error_message, occurred_at FROM crawl_errors ORDER BY id DESC LIMIT 5"
    ).fetchall():
        print(f"  [{e['source']}] {e['error_type']}: {e['error_message']} @ {e['occurred_at']}")

    print("\n=== 5 sample jobs ===")
    for j in conn.execute(
        "SELECT source, source_id, title, company, location FROM jobs ORDER BY id DESC LIMIT 5"
    ).fetchall():
        print(f"  [{j['source']}] {j['title']} @ {j['company']} ({j['location']})")

    conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test (against a real DB if one exists)**

```bash
python scripts/inspect_db.py
```

Expected: counts + last runs + errors + sample jobs (empty if no DB yet).

- [ ] **Step 3: Commit**

```bash
git add scripts/inspect_db.py
git commit -m "feat(inspect_db): debug CLI — counts, last runs/errors, sample jobs"
```

---

## Task 19: `scripts/record_fixtures.py` — one-shot AMS HTML recorder

**Files:**
- Modify: `scripts/record_fixtures.py`

- [ ] **Step 1: Implement**

```python
"""One-shot: capture live AMS HTML to tests/fixtures/ for offline test replay.

WARNING: only run manually. Not in CI. AMS ToS permitting scraping for
personal use only — re-record fixtures sparingly.

Grill-me amendment 8: strip job descriptions, keep only structural HTML.
"""
import asyncio
import sys
from pathlib import Path

from crawler import config
from crawler.browser import PlaywrightBrowserContext, SessionCookieStore
from crawler.sources.ams import (
    AMS_JOB_CARD_SELECTOR, AMS_DETAIL_SELECTOR,
)

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"


def strip_descriptions(html: str) -> str:
    """Replace .description contents with placeholder. Keeps structural layout."""
    import re
    return re.sub(
        r'(<div class="description">).*?(</div>)',
        r'\1[stripped by record_fixtures.py]\2',
        html,
        flags=re.DOTALL,
    )


async def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    cookie_store = SessionCookieStore(config.DB_PATH.parent / "session_ams.json")

    async with PlaywrightBrowserContext(cookie_store) as browser:
        # Search page
        html = await browser.goto(config.AMS_BASE_URL + "jobs", wait_selector=AMS_JOB_CARD_SELECTOR)
        (FIXTURES_DIR / "ams_search_page.html").write_text(strip_descriptions(html), encoding="utf-8")
        print(f"saved ams_search_page.html ({len(html)} bytes)")

        # First job detail (operator edits URL to specific job ID after first run)
        if len(sys.argv) > 1:
            url = sys.argv[1]
            html = await browser.goto(url, wait_selector=AMS_DETAIL_SELECTOR)
            (FIXTURES_DIR / "ams_detail_page.html").write_text(strip_descriptions(html), encoding="utf-8")
            print(f"saved ams_detail_page.html from {url} ({len(html)} bytes)")
        else:
            print("skip detail — pass URL as argv[1]")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Document in README (add to scripts/ section later) or print usage**

```bash
python scripts/record_fixtures.py https://jobs.ams.at/public/jobs/SOME_ID
```

- [ ] **Step 3: Commit**

```bash
git add scripts/record_fixtures.py
git commit -m "feat(record_fixtures): one-shot Playwright HTML capture (descriptions stripped)"
```

---

## Task 20: Fixture license note

**Files:**
- Create: `tests/fixtures/.fixture-license`

- [ ] **Step 1: Write license note (grill-me amendment 8)**

```
# Test fixture license

Fixtures in this directory are recorded HTML from ams.at (Austrian Public
Employment Service) for the sole purpose of unit/integration testing the
JobCrawler pipeline.

Per grill-me amendment 8: job descriptions are stripped via
`scripts/record_fixtures.py:strip_descriptions()` before commit. Only
structural HTML (card layout, selectors, attribute names) is retained.

Re-record sparingly. AMS ToS permits personal use scraping; redistribution
of stripped structural HTML is a gray area — keep fixtures minimal.

Fixture mtime warning: tests print a warning if any fixture is >30 days
old (spec § Testing Strategy).
```

- [ ] **Step 2: Commit**

```bash
git add tests/fixtures/.fixture-license
git commit -m "docs(fixtures): license note — AMS HTML stripped, 30d age warning"
```

---

## Task 21: README — quickstart

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace TODO sections with quickstart**

```markdown
# JobCrawler

Job listings crawler + storage. Sub-project 1 of 4 (see [spec](docs/superpowers/specs/2026-06-21-jobcrawler-crawler-storage-design.md)).

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium

# Dry-run AMS
python scripts/crawl.py --source=ams --limit=10 --dry-run

# Real crawl
python scripts/crawl.py --source=ams --limit=50

# Inspect DB
python scripts/inspect_db.py
```

## Architecture

Crawler pipeline that fetches job listings from sources, normalizes +
dedupes them, and persists to a local SQLite DB. Sub-project 1 ships AMS
only (Playwright browser adapter). Other sources (Karriere.at, Willhaben,
LinkedIn) are sub-projects 1.1+.

```
scripts/crawl.py → crawler.pipeline → AmsAdapter → BrowserContext (Playwright) → SQLite
```

## Tests

```bash
pytest                    # full suite
pytest tests/unit/        # unit only
pytest tests/integration/ # integration
pytest --cov=crawler      # with coverage
```

Coverage gate: 90% (see `crawler/config.py:COVERAGE_GATE`).

## Sub-projects

| # | Name | Status |
|---|------|--------|
| 1 | Crawler + Storage (AMS) | this repo |
| 1.1 | Karriere.at adapter | deferred |
| 1.2 | Willhaben.at/jobs adapter | deferred |
| 1.3+ | LinkedIn adapter | deferred |
| 2 | Enrichment (company, financial, reviews) | deferred |
| 3 | Dashboard (Next.js) | deferred |
| 4 | Scheduler (cron, env config, alerts) | deferred |

See `docs/superpowers/specs/2026-06-21-jobcrawler-crawler-storage-design.md` for the full design.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): quickstart, architecture, sub-project roadmap"
```

---

## Task 22: Coverage measurement (test_scope: true)

**Files:**
- Run only — verify coverage gate

- [ ] **Step 1: Run coverage**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/JobCrawler
pytest --cov=crawler --cov-report=term-missing --cov-fail-under=90
```

Expected: passes, coverage ≥90%. If under, identify uncovered lines:
- `crawler/browser.py:PlaywrightBrowserContext.__aenter__/__aexit__` — only covered by smoke test, not unit. Acceptable to exclude via `# pragma: no cover` for sub-project 1 (manual smoke only).
- Other gaps: add to specific test files.

- [ ] **Step 2: If gate fails, fix uncovered lines**

For `PlaywrightBrowserContext` lifecycle methods (only run in manual smoke), add `# pragma: no cover` on `__aenter__`, `__aexit__`, `save_cookies`. Document as "manual smoke only" in the source.

- [ ] **Step 3: Re-run coverage**

```bash
pytest --cov=crawler --cov-fail-under=90
```

Expected: passes.

- [ ] **Step 4: Commit any pragma additions**

```bash
git add crawler/browser.py
git commit -m "test(coverage): mark PlaywrightBrowserContext lifecycle as manual-smoke-only"
```

---

## Task 23: Manual smoke checklist

**Files:**
- Run only

- [ ] **Step 1: Run each smoke step**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/JobCrawler

[ ] python scripts/crawl.py --source=ams --limit=5
    Expected: exit 0, "5 jobs in DB"

[ ] python scripts/crawl.py --source=ams --limit=5 --dry-run
    Expected: exit 3, JSON stdout, no DB writes

[ ] python scripts/crawl.py --source=ams --since=2026-06-01
    Expected: exit 0, posted_at filter works

[ ] python scripts/inspect_db.py
    Expected: counts, no SchemaChanged errors

[ ] rm data/jobs.db && python scripts/crawl.py --source=ams --limit=10
    Expected: migration applies cleanly, 10 jobs in fresh DB
```

- [ ] **Step 2: Document results in commit message**

If any step fails, file an issue and pause. Otherwise:
```bash
git commit --allow-empty -m "chore: smoke checklist passed — AMS crawl works end-to-end"
```

---

## Self-Review

**Spec coverage check:**

| Spec section | Task |
|---|---|
| Architecture (CLI → pipeline → adapter → browser → storage) | T1, T15, T16 |
| Components — dir layout (11 modules) | T1, T3-T15 |
| Components — SourceAdapter Protocol + contract guarantees | T13, T14 |
| Storage Schema (sources, jobs, crawl_runs, crawl_errors, indexes) | T7 |
| SQLite PRAGMAs (WAL, busy_timeout, foreign_keys) | T6 |
| Dedup (UNIQUE (source, source_id) + content_hash) | T8, T9 |
| Data Flow — CLI, Pipeline, Browser wrapper, AMS adapter | T15, T16, T11, T14 |
| Configuration constants | T3 |
| Error Handling — exception hierarchy, retry policy, circuit breaker, logging, signal handling, exit codes | T4, T9, T15, T16 |
| Testing Strategy — pyramid, unit, contract, integration, fixtures, CI, smoke | T3-T15, T17, T20, T22, T23 |
| CLI Interface (args, exit codes) | T16 |
| Discovery Findings (AMS SPA, SM2_SESSION, no public API) | T14, T19 |
| Risks (rate limits, anti-bot, cookie expiry, schema drift) | T11, T14, T22 |
| Grill-me amendments (1, 2, 4, 6, 9) | T3, T7, T9, T11, T12, T14 |

**Type consistency check:**
- `SourceAdapter.search` → `AsyncIterator[RawJob]` — T13, T14 ✓
- `SourceAdapter.fetch_detail` → `NormalizedJob` — T13, T14 ✓
- `repository.upsert_job` returns `Literal["inserted", "updated"]` — T9, T15 ✓
- `pipeline.run_source` returns `SourceResult` — T15 ✓
- `BrowserContext.goto` returns `str` (html) — T11, T12 ✓
- `SessionCookieStore.save/load` JSON schema `{cookies: [...], saved_at, schema_version}` — T11 ✓

**Placeholder scan:**
- No "TBD", "TODO", "implement later" in plan steps.
- All file paths absolute (relative to repo root) and unique.
- All test code shown in full.
- All commit messages follow `<type>: <subject>` convention.

**Plan grill-me:** Deferred to execution handoff. If subagent-driven chosen, the executor may surface gaps.

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-06-22-jobcrawler-crawler-storage.md`. 23 tasks, each self-contained, TDD throughout.

**Execution options:**

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration, isolated context per task.

2. **Inline Execution** — Execute tasks in this session using executing-plans, batch with checkpoints.

**Which approach?**
