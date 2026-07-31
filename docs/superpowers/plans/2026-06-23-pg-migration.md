# JobCrawler Sub-Project 1.5 — PostgreSQL Backend Swap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SQLite with PostgreSQL 16 across crawler (Python) + dashboard (Node/Next.js), drop SQLite entirely, keep all existing functionality green.

**Architecture:** Local PostgreSQL via docker-compose. Python uses `psycopg[binary]` + `psycopg_pool.ConnectionPool`. Node/Next.js dashboard uses `pg` + `pg.Pool`. Migration runner keeps the current shape (`V*.sql` files + `schema_migrations` table). Tests use ephemeral PG schema per test (UUID-suffixed) for isolation.

**Tech Stack:** PostgreSQL 16 + pgvector (Docker image `pgvector/pgvector:pg16`), psycopg[binary] ≥3.2, psycopg-pool ≥3.2, pg ≥8.13 (Node), @types/pg ≥8, Next.js 15 (RSC async), pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-06-23-pg-migration-design.md`
**Spec scope flags:** `test_scope: true` (coverage measurement task required), `ui_scope: false`, `graph_scope: false`.

**Pre-flight grill-me note:** User pushed back on over-grilling micro-decisions during brainstorm. Plan uses sensible defaults throughout — psycopg+pg, raw SQL (no ORM), docker-compose, ephemeral PG schema per test. Revise only if a default blocks a step.

**Port override (global, applied 2026-06-23 during Task 1):** Host port 5432 is occupied on this dev machine by `knowledgeforge-postgres` (another project). All JobCrawler PG references use **port 5433** instead. Host port 3010 is occupied by `knowledgeforge-ui`. All JobCrawler dashboard references use **port 3011** instead. This is a port-only deviation; architecture is unchanged. Implemented via `docker-compose.yml` mapping `5433:5432` (host 5433 → container 5432, where PG actually listens) and `npx next start --port 3011`.

---

## Task 1: docker-compose.yml + .env.example — PG service

**Files:**
- Create: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `.gitignore` (add `.pgdata/`, `postgres-data/`)

- [ ] **Step 1: Create `docker-compose.yml`**

```yaml
# docker-compose.yml — local PG for dev + tests
services:
  postgres:
    image: pgvector/pgvector:pg16   # pgvector preinstalled
    container_name: jobcrawler-pg
    environment:
      POSTGRES_USER: jobcrawler
      POSTGRES_PASSWORD: dev
      POSTGRES_DB: jobcrawler
    ports:
      - "5433:5432"   # host 5433 → container 5432 (host 5432 occupied by knowledgeforge-postgres)
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U jobcrawler -d jobcrawler"]
      interval: 2s
      timeout: 5s
      retries: 20

volumes:
  pgdata:
```

- [ ] **Step 2: Update `.env.example`**

Replace `.env.example` contents:

```bash
# JobCrawler — copy to .env, never commit
# Postgres connection (local docker-compose defaults)
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler

# Sub-project 1 (AMS crawler)
AMS_BASE_URL=https://jobs.ams.at/public/
AMS_COOKIE_DOMAIN=.ams.at

# Logging
LOG_FORMAT=text
```

- [ ] **Step 3: Add PG data dirs to `.gitignore`**

Append to `.gitignore`:
```
# Postgres local data
.pgdata/
postgres-data/
```

- [ ] **Step 4: Start PG + verify**

Run:
```bash
docker compose up -d postgres
docker compose ps
```

Expected: `postgres` shows `Up (healthy)` after ~10s.

- [ ] **Step 5: Smoke test connection**

Run:
```bash
docker compose exec postgres psql -U jobcrawler -d jobcrawler -c "SELECT version();"
```

Expected output contains `PostgreSQL 16.x`.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml .env.example .gitignore
git commit -m "chore(infra): docker-compose for local PostgreSQL 16 (pgvector)"
```

---

## Task 2: PG schema migration V001

**Files:**
- Rewrite: `crawler/storage/migrations/V001__initial.sql`

- [ ] **Step 1: Rewrite `V001__initial.sql` in PG dialect**

```sql
-- V001: initial schema (PG dialect)
-- Spec: 2026-06-23-pg-migration-design.md

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE schema_migrations (
  version     INTEGER PRIMARY KEY,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  description TEXT NOT NULL
);

CREATE TABLE sources (
  name               TEXT PRIMARY KEY,
  enabled            BOOLEAN NOT NULL DEFAULT TRUE,
  rate_limit_per_min INTEGER NOT NULL DEFAULT 30,
  last_crawled_at    TIMESTAMPTZ
);

CREATE TYPE run_status AS ENUM ('pending', 'running', 'success', 'partial', 'failed');

CREATE TABLE runs (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source     TEXT NOT NULL REFERENCES sources(name),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at   TIMESTAMPTZ,
  status     run_status NOT NULL DEFAULT 'pending',
  jobs_found INTEGER NOT NULL DEFAULT 0,
  jobs_new   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE jobs (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source        TEXT NOT NULL REFERENCES sources(name),
  source_id     TEXT NOT NULL,
  url           TEXT NOT NULL,
  title         TEXT NOT NULL,
  company       TEXT,
  location      TEXT,
  description   TEXT,
  embedding     vector(384),
  content_hash  TEXT NOT NULL UNIQUE,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  raw_payload   JSONB,
  UNIQUE (source, source_id)
);

CREATE TABLE run_errors (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id      BIGINT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  stage       TEXT NOT NULL,
  message     TEXT NOT NULL,
  context     JSONB
);

CREATE INDEX idx_jobs_source      ON jobs (source);
CREATE INDEX idx_jobs_last_seen   ON jobs (last_seen_at DESC);
CREATE INDEX idx_runs_source_time ON runs (source, started_at DESC);
CREATE INDEX idx_run_errors_run   ON run_errors (run_id);
```

- [ ] **Step 2: Apply migration to dev DB**

Run:
```bash
docker compose exec -T postgres psql -U jobcrawler -d jobcrawler < crawler/storage/migrations/V001__initial.sql
```

Expected: `CREATE EXTENSION`, `CREATE TABLE`, `CREATE TYPE`, `CREATE INDEX` for each statement. No errors.

- [ ] **Step 3: Verify schema in DB**

Run:
```bash
docker compose exec postgres psql -U jobcrawler -d jobcrawler -c "\dt"
docker compose exec postgres psql -U jobcrawler -d jobcrawler -c "\dT+"
```

Expected: tables `schema_migrations`, `sources`, `runs`, `jobs`, `run_errors`. Type `run_status` listed.

- [ ] **Step 4: Commit (migrations + verification)**

Note: Migration application is to dev DB; only the SQL file is committed.

```bash
git add crawler/storage/migrations/V001__initial.sql
git commit -m "feat(storage): V001 schema in PostgreSQL dialect (pgvector + JSONB + ENUM)"
```

---

## Task 3: crawler/storage/db.py — psycopg pool

**Files:**
- Rewrite: `crawler/storage/db.py`

- [ ] **Step 1: Rewrite `db.py`**

```python
"""PostgreSQL connection factory + connection pool.

Two entry points:
  - connect(): single connection, used by migration runner
  - get_pool(): psycopg_pool.ConnectionPool, used by app code

WAL/busy_timeout SQLite PRAGMAs gone — PG has MVCC + per-statement
timeouts. PRAGMAs here are PG session settings applied on connect.
"""
from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg_pool import ConnectionPool

from crawler import config

# Module-level pool, lazy-initialized.
_pool: ConnectionPool | None = None


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL not set. Copy .env.example to .env or set env var."
        )
    return url


def connect(url: str | None = None) -> psycopg.Connection:
    """Open a single PG connection (used by migration runner + tests)."""
    conn = psycopg.connect(
        url or _database_url(),
        autocommit=False,
        row_factory=psycopg.rows.dict_row,
    )
    # Session-level settings
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '30s'")
        cur.execute("SET application_name = 'jobcrawler'")
    conn.commit()
    return conn


def get_pool() -> ConnectionPool:
    """Lazy-init pool. Used by repository + app code."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=_database_url(),
            min_size=2,
            max_size=10,
            kwargs={"autocommit": False, "row_factory": psycopg.rows.dict_row},
            open=True,
        )
    return _pool


def close_pool() -> None:
    """For tests + atexit. Idempotent."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
```

- [ ] **Step 2: Add `DATABASE_URL` to config**

Add to `crawler/config.py` (or create if missing):

```python
"""JobCrawler config constants."""
import os

# Postgres connection (read from env)
DATABASE_URL: str = os.environ.get(
    "DATABASE_URL", "postgresql://jobcrawler:dev@localhost:5433/jobcrawler"
)

# AMS crawler
AMS_BASE_URL: str = os.environ.get("AMS_BASE_URL", "https://jobs.ams.at/public/")
AMS_COOKIE_DOMAIN: str = os.environ.get("AMS_COOKIE_DOMAIN", ".ams.at")

# Statement timeout (ms)
PG_STATEMENT_TIMEOUT_MS: int = int(os.environ.get("PG_STATEMENT_TIMEOUT_MS", "30000"))
```

- [ ] **Step 3: Verify import + connection**

Run:
```bash
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler python -c "
from crawler.storage.db import connect
conn = connect()
with conn.cursor() as cur:
    cur.execute('SELECT 1 AS x')
    print(cur.fetchone())
conn.close()
"
```

Expected: `{'x': 1}` printed.

- [ ] **Step 4: Commit**

```bash
git add crawler/storage/db.py crawler/config.py
git commit -m "feat(storage): db.py — psycopg pool + config.DATABASE_URL"
```

---

## Task 4: crawler/storage/migrations/runner.py — PG runner

**Files:**
- Rewrite: `crawler/storage/migrations/runner.py`

- [ ] **Step 1: Rewrite `runner.py`**

```python
"""PG migration runner.

Tracks applied versions in `schema_migrations`. Applies pending
V*.sql files in order. Idempotent — re-running is a no-op once
all migrations are applied.
"""
from __future__ import annotations

import re
from pathlib import Path

import psycopg

VERSION_PATTERN = re.compile(r"^V(\d+)__(.+)\.sql$")


def _applied_versions(conn: psycopg.Connection) -> set[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations")
        return {row["version"] for row in cur.fetchall()}


def _ensure_migrations_table(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version     INTEGER PRIMARY KEY,
              applied_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
              description TEXT NOT NULL
            )
        """)
    conn.commit()


def _discover(migrations_dir: Path) -> list[tuple[int, str, Path]]:
    """Return [(version, description, path)] sorted by version."""
    out: list[tuple[int, str, Path]] = []
    for entry in sorted(migrations_dir.iterdir()):
        m = VERSION_PATTERN.match(entry.name)
        if m:
            out.append((int(m.group(1)), m.group(2), entry))
    return out


def migrate(conn: psycopg.Connection, migrations_dir: Path) -> list[int]:
    """Apply pending migrations. Returns list of applied versions."""
    _ensure_migrations_table(conn)
    applied = _applied_versions(conn)
    new: list[int] = []
    for version, description, path in _discover(migrations_dir):
        if version in applied:
            continue
        sql = path.read_text()
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                "INSERT INTO schema_migrations (version, description) VALUES (%s, %s)",
                (version, description),
            )
        conn.commit()
        new.append(version)
    return new
```

- [ ] **Step 2: Verify migration runner against fresh DB**

Drop + recreate `jobcrawler` DB, then test:

Run:
```bash
docker compose exec postgres dropdb -U jobcrawler jobcrawler --if-exists
docker compose exec postgres createdb -U jobcrawler jobcrawler
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler python -c "
from pathlib import Path
from crawler.storage.db import connect
from crawler.storage.migrations.runner import migrate
conn = connect()
applied = migrate(conn, Path('crawler/storage/migrations'))
print('applied:', applied)
conn.close()
"
docker compose exec postgres psql -U jobcrawler -d jobcrawler -c "SELECT * FROM schema_migrations"
```

Expected: `applied: [1]` printed. `schema_migrations` row shows `1 | ... | initial schema`.

- [ ] **Step 3: Verify idempotency (re-run = no-op)**

Run:
```bash
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler python -c "
from pathlib import Path
from crawler.storage.db import connect
from crawler.storage.migrations.runner import migrate
conn = connect()
applied = migrate(conn, Path('crawler/storage/migrations'))
print('applied:', applied)
conn.close()
"
```

Expected: `applied: []` (already-applied migrations skipped).

- [ ] **Step 4: Commit**

```bash
git add crawler/storage/migrations/runner.py
git commit -m "feat(storage): migration runner — PG schema_migrations + idempotent apply"
```

---

## Task 5: crawler/storage/dedup.py — PG-compatible hash

**Files:**
- Rewrite: `crawler/storage/dedup.py`

The current SQLite dedup normalizes title/company/location, computes SHA256 of the normalized string, and checks uniqueness. PG version: same hash logic, but the DB lookup uses PG instead of sqlite3.

- [ ] **Step 1: Rewrite `dedup.py`**

```python
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
```

- [ ] **Step 2: Smoke test against PG**

Run:
```bash
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler python -c "
from crawler.storage.db import connect
from crawler.storage.dedup import content_hash, find_by_hash
h = content_hash('Senior Developer', 'AMS', 'Wien')
print('hash:', h)
conn = connect()
print('found:', find_by_hash(conn, h))
conn.close()
"
```

Expected: hash printed (64-char hex), `found: None` (empty DB).

- [ ] **Step 3: Commit**

```bash
git add crawler/storage/dedup.py
git commit -m "feat(storage): dedup.py — PG-compatible content_hash + find_by_hash"
```

---

## Task 6: crawler/storage/repository.py — PG CRUD

**Files:**
- Rewrite: `crawler/storage/repository.py`

- [ ] **Step 1: Rewrite `repository.py`**

```python
"""Typed CRUD over jobs, runs, sources, errors (PostgreSQL).

All functions take a `psycopg.Connection`. Callers manage
transactions via `with conn.transaction():` blocks.
"""
from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from crawler.storage.dedup import content_hash


# ---------- sources ----------

def upsert_source(conn: psycopg.Connection, name: str, *, enabled: bool = True,
                  rate_limit_per_min: int = 30) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO sources (name, enabled, rate_limit_per_min)
            VALUES (%s, %s, %s)
            ON CONFLICT (name) DO UPDATE
              SET enabled = EXCLUDED.enabled,
                  rate_limit_per_min = EXCLUDED.rate_limit_per_min
        """, (name, enabled, rate_limit_per_min))


def get_source(conn: psycopg.Connection, name: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM sources WHERE name = %s", (name,))
        return cur.fetchone()


# ---------- runs ----------

def start_run(conn: psycopg.Connection, source: str) -> int:
    """Begin a run, return its id."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO runs (source, status) VALUES (%s, 'running') RETURNING id",
            (source,),
        )
        return cur.fetchone()["id"]


def finish_run(conn: psycopg.Connection, run_id: int, *,
               status: str, jobs_found: int, jobs_new: int) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE runs SET status = %s, ended_at = now(),
                            jobs_found = %s, jobs_new = %s
            WHERE id = %s
        """, (status, jobs_found, jobs_new, run_id))


def record_error(conn: psycopg.Connection, run_id: int, *,
                 stage: str, message: str, context: dict[str, Any] | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO run_errors (run_id, stage, message, context)
            VALUES (%s, %s, %s, %s)
        """, (run_id, stage, message, Jsonb(context) if context else None))


def list_runs(conn: psycopg.Connection, source: str | None = None,
              limit: int = 50) -> list[dict]:
    sql = "SELECT * FROM runs"
    args: tuple = ()
    if source:
        sql += " WHERE source = %s"
        args = (source,)
    sql += " ORDER BY started_at DESC LIMIT %s"
    args = args + (limit,)
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return list(cur.fetchall())


def get_run_errors(conn: psycopg.Connection, run_id: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM run_errors WHERE run_id = %s ORDER BY occurred_at DESC",
            (run_id,),
        )
        return list(cur.fetchall())


# ---------- jobs ----------

def upsert_job(conn: psycopg.Connection, *,
               source: str, source_id: str, url: str, title: str,
               company: str | None, location: str | None,
               description: str | None, raw_payload: dict | None = None) -> dict:
    """Insert or update a job. Returns row dict with `created: bool`."""
    h = content_hash(title, company, location)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO jobs (source, source_id, url, title, company, location,
                              description, content_hash, raw_payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, source_id) DO UPDATE
              SET url = EXCLUDED.url,
                  title = EXCLUDED.title,
                  company = EXCLUDED.company,
                  location = EXCLUDED.location,
                  description = EXCLUDED.description,
                  content_hash = EXCLUDED.content_hash,
                  last_seen_at = now(),
                  raw_payload = EXCLUDED.raw_payload
            RETURNING id, (xmax = 0) AS created, *
        """, (source, source_id, url, title, company, location, description, h,
              Jsonb(raw_payload) if raw_payload else None))
        row = cur.fetchone()
        return dict(row)


def get_by_hash(conn: psycopg.Connection, h: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM jobs WHERE content_hash = %s", (h,))
        return cur.fetchone()


def list_jobs(conn: psycopg.Connection, *,
              source: str | None = None, limit: int = 100,
              offset: int = 0) -> list[dict]:
    sql = "SELECT * FROM jobs"
    args: list = []
    if source:
        sql += " WHERE source = %s"
        args.append(source)
    sql += " ORDER BY last_seen_at DESC LIMIT %s OFFSET %s"
    args.extend([limit, offset])
    with conn.cursor() as cur:
        cur.execute(sql, tuple(args))
        return list(cur.fetchall())


def get_job(conn: psycopg.Connection, job_id: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
        return cur.fetchone()


# ---------- stats ----------

def get_stats(conn: psycopg.Connection) -> dict:
    """Stats for dashboard overview page."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM jobs")
        jobs_total = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM runs WHERE status = 'success'")
        runs_success = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM runs WHERE status = 'failed'")
        runs_failed = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM run_errors")
        errors_total = cur.fetchone()["n"]
        cur.execute("SELECT source, COUNT(*) AS n FROM jobs GROUP BY source")
        by_source = {row["source"]: row["n"] for row in cur.fetchall()}
        cur.execute("""
            SELECT date_trunc('day', last_seen_at)::date AS day, COUNT(*) AS n
            FROM jobs GROUP BY day ORDER BY day DESC LIMIT 7
        """)
        recent = list(cur.fetchall())
    return {
        "jobs_total": jobs_total,
        "runs_success": runs_success,
        "runs_failed": runs_failed,
        "errors_total": errors_total,
        "by_source": by_source,
        "recent_days": recent,
    }
```

- [ ] **Step 2: Smoke test full upsert cycle**

Run:
```bash
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler python -c "
from crawler.storage.db import connect
from crawler.storage.repository import (
    upsert_source, start_run, finish_run, upsert_job, list_jobs, get_stats
)
from crawler.storage.migrations.runner import migrate
from pathlib import Path

conn = connect()
migrate(conn, Path('crawler/storage/migrations'))

upsert_source(conn, 'ams')
rid = start_run(conn, 'ams')
row1 = upsert_job(conn, source='ams', source_id='J1', url='https://example.com/j1',
                  title='Senior Dev', company='AMS', location='Wien',
                  description='PG rocks')
print('first insert created:', row1['created'])
row2 = upsert_job(conn, source='ams', source_id='J1', url='https://example.com/j1',
                  title='Senior Dev', company='AMS', location='Wien',
                  description='PG still rocks')
print('second insert created:', row2['created'])
finish_run(conn, rid, status='success', jobs_found=1, jobs_new=1)
print('jobs:', list_jobs(conn))
print('stats:', get_stats(conn))
conn.close()
"
```

Expected output (abbreviated):
```
first insert created: True
second insert created: False
jobs: [{'id': 1, ...}]
stats: {'jobs_total': 1, ...}
```

- [ ] **Step 3: Commit**

```bash
git add crawler/storage/repository.py
git commit -m "feat(storage): repository.py — PG CRUD (jobs, runs, sources, errors, stats)"
```

---

## Task 7: tests/conftest.py — ephemeral PG schema fixture

**Files:**
- Create: `tests/conftest.py`
- Modify: `pyproject.toml` (no changes yet — handled in Task 9)

- [ ] **Step 1: Create `tests/conftest.py`**

```python
"""Pytest fixtures for ephemeral PG schema per test.

Session-scoped: ensure PG is up, run migrations into template schema.
Function-scoped: per-test schema with UUID suffix for isolation.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from crawler.storage.migrations.runner import migrate


PG_BASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://jobcrawler:dev@localhost:5433/jobcrawler"
)


@pytest.fixture(scope="session")
def pg_base_url() -> str:
    """Verify PG is reachable. Skip entire suite if not."""
    try:
        with psycopg.connect(PG_BASE_URL, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    except Exception as e:
        pytest.skip(f"PostgreSQL not reachable at {PG_BASE_URL}: {e}")
    return PG_BASE_URL


@pytest.fixture(scope="session")
def pg_migrated_template(pg_base_url: str) -> str:
    """Create a template DB with migrations applied. Tests clone this per-test."""
    template_name = f"jobcrawler_template_{uuid.uuid4().hex[:8]}"
    admin_url = pg_base_url.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        with admin.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{template_name}"')
    template_url = pg_base_url.rsplit("/", 1)[0] + f"/{template_name}"
    with psycopg.connect(template_url) as conn:
        migrate(conn, Path("crawler/storage/migrations"))
        conn.commit()
    yield template_url
    # Teardown
    with psycopg.connect(admin_url, autocommit=True) as admin:
        with admin.cursor() as cur:
            cur.execute(
                f'REVOKE CONNECT ON DATABASE "{template_name}" FROM PUBLIC'
            )
            cur.execute(
                f"""SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                    WHERE datname = '{template_name}'"""
            )
            cur.execute(f'DROP DATABASE "{template_name}"')


@pytest.fixture
def pg_schema(pg_migrated_template: str) -> str:
    """Yield a fresh schema name (per-test isolation)."""
    schema = f"test_{uuid.uuid4().hex[:12]}"
    # Connect to the template DB and create schema
    with psycopg.connect(pg_migrated_template, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}"')
    yield schema
    # Teardown: drop schema
    with psycopg.connect(pg_migrated_template, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.fixture
def pg_url(pg_migrated_template: str, pg_schema: str) -> str:
    """DATABASE_URL pointing at template DB with search_path set."""
    # Append search_path option to URL
    sep = "&" if "?" in pg_migrated_template else "?"
    return f"{pg_migrated_template}{sep}options=-c search_path%3D{pg_schema}"


@pytest.fixture
def pg_conn(pg_url: str):
    """Yield a PG connection with search_path set to test schema."""
    conn = psycopg.connect(pg_url, autocommit=False)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def pg_pool(pg_url: str):
    """Yield a connection pool for tests that exercise pool semantics."""
    pool = ConnectionPool(conninfo=pg_url, min_size=1, max_size=2, open=True)
    try:
        yield pool
    finally:
        pool.close()
```

- [ ] **Step 2: Verify fixtures work in isolation**

Create `tests/unit/test_pg_fixtures.py`:

```python
"""Smoke test: PG fixtures create + teardown schema cleanly."""


def test_pg_conn_sees_migrated_tables(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = current_schema()
            ORDER BY table_name
        """)
        tables = [r["table_name"] for r in cur.fetchall()]
    assert "jobs" in tables
    assert "runs" in tables
    assert "sources" in tables


def test_two_tests_get_isolated_schemas(pg_conn):
    # First test inserts a job
    with pg_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO jobs (source, source_id, url, title, content_hash) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("ams", "X1", "http://x", "Job A", "h1"),
        )
    pg_conn.commit()
    with pg_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM jobs")
        n = cur.fetchone()["n"]
    assert n == 1
```

Run:
```bash
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler pytest tests/unit/test_pg_fixtures.py -v
```

Expected: 2 tests pass.

- [ ] **Step 3: Verify schema isolation (run twice, no leakage)**

Run the same command twice in a row. Both runs pass with `2 passed`. No `Job A` leakage between runs (proves schema teardown works).

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py tests/unit/test_pg_fixtures.py
git commit -m "test(storage): ephemeral PG schema fixtures (session template + per-test schema)"
```

---

## Task 8: Migrate existing tests from sqlite :memory: to PG schema

**Files:**
- Modify: All test files that import sqlite3 or use sqlite fixtures
- Likely: `tests/unit/test_repository.py`, `tests/unit/test_db.py`, `tests/unit/test_dedup.py`, `tests/unit/test_migrations.py`, `tests/integration/test_crawl_*.py`

- [ ] **Step 1: Inventory existing test fixtures**

Run:
```bash
grep -rln "sqlite3\|:memory:\|jobs.db" tests/
```

Expected: list of test files using sqlite.

- [ ] **Step 2: Replace sqlite fixtures with PG fixtures**

For each test file, replace:
- `sqlite3.connect(":memory:")` → use `pg_conn` fixture
- `import sqlite3` → use `psycopg` via `pg_conn`
- String placeholders `?` → `%s`
- `row_factory = sqlite3.Row` → already handled by `connect()` via `dict_row`

Example migration for `tests/unit/test_repository.py`:

```python
# BEFORE (SQLite)
import sqlite3
import pytest
from crawler.storage.repository import upsert_job


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript("""
        CREATE TABLE sources (...);
        CREATE TABLE jobs (...);
    """)
    return c


def test_upsert_job_creates(conn):
    upsert_source(conn, "ams")
    row = upsert_job(conn, source="ams", ...)
    assert row["created"] is True


# AFTER (PG)
import pytest
from crawler.storage.repository import upsert_job, upsert_source


def test_upsert_job_creates(pg_conn):
    upsert_source(pg_conn, "ams")
    row = upsert_job(pg_conn, source="ams", ...)
    assert row["created"] is True
```

- [ ] **Step 3: Run migrated tests, fix until green**

Run:
```bash
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler pytest tests/ -x -q
```

Iterate on each failure: fix syntax (`?` → `%s`), type issues (`0/1` for boolean → `True/False`), datetime handling.

- [ ] **Step 4: Commit incrementally**

After each file's tests pass:
```bash
git add tests/unit/test_<file>.py
git commit -m "test: migrate <file> from sqlite :memory: to PG schema fixture"
```

---

## Task 9: pyproject.toml — drop sqlite deps, add psycopg

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update dependencies**

In `pyproject.toml` `[project]` section, replace `dependencies`:

```toml
dependencies = [
    "httpx>=0.27",
    "playwright>=1.45",
    "pydantic>=2.7",
    "beautifulsoup4>=4.12",
    "psycopg[binary]>=3.2",
    "psycopg-pool>=3.2",
]
```

- [ ] **Step 2: Reinstall + verify import**

Run:
```bash
pip install -e ".[dev]"
python -c "import psycopg, psycopg_pool; print('ok')"
```

Expected: `ok` printed.

- [ ] **Step 3: Run full test suite**

Run:
```bash
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler pytest tests/ -q
```

Expected: All tests green (84+ tests).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore(deps): drop sqlite3 stdlib, add psycopg[binary] + psycopg-pool"
```

---

## Task 10: scripts/seed_demo_data.py — PG inserts

**Files:**
- Rewrite: `scripts/seed_demo_data.py`

- [ ] **Step 1: Rewrite `seed_demo_data.py`**

```python
"""Seed demo data into PG (5 jobs + 2 runs + 1 error).

Usage:
    python scripts/seed_demo_data.py [--database-url URL]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crawler.storage.repository import (  # noqa: E402
    finish_run, record_error, start_run, upsert_job, upsert_source,
)


JOBS = [
    {
        "source": "ams", "source_id": "DEMO-1",
        "url": "https://jobs.ams.at/public/DEMO-1",
        "title": "Senior Backend Engineer (Python)",
        "company": "DemoCo",
        "location": "Wien",
        "description": "Build crawlers + storage layers with PostgreSQL.",
    },
    {
        "source": "ams", "source_id": "DEMO-2",
        "url": "https://jobs.ams.at/public/DEMO-2",
        "title": "Frontend Developer (React/Next.js)",
        "company": "DemoCo",
        "location": "Wien",
        "description": "Dashboard UI work.",
    },
    {
        "source": "ams", "source_id": "DEMO-3",
        "url": "https://jobs.ams.at/public/DEMO-3",
        "title": "Data Engineer",
        "company": "DataCorp",
        "location": "Graz",
        "description": "ETL pipelines, PostgreSQL tuning.",
    },
    {
        "source": "ams", "source_id": "DEMO-4",
        "url": "https://jobs.ams.at/public/DEMO-4",
        "title": "DevOps Engineer",
        "company": "CloudOps",
        "location": "Linz",
        "description": "K8s, Terraform, PG operators.",
    },
    {
        "source": "ams", "source_id": "DEMO-5",
        "url": "https://jobs.ams.at/public/DEMO-5",
        "title": "ML Engineer",
        "company": "AIStartup",
        "location": "Wien",
        "description": "pgvector + LLM integration.",
    },
]


def seed(database_url: str) -> None:
    with psycopg.connect(database_url) as conn:
        upsert_source(conn, "ams")
        for j in JOBS:
            upsert_job(conn, **j)
        run1 = start_run(conn, "ams")
        finish_run(conn, run1, status="success", jobs_found=5, jobs_new=5)
        run2 = start_run(conn, "ams")
        record_error(
            conn, run2, stage="parse",
            message="Failed to parse one listing",
            context={"url": "https://jobs.ams.at/public/DEMO-X"},
        )
        finish_run(conn, run2, status="partial", jobs_found=5, jobs_new=0)
        conn.commit()
    print(f"Seeded {len(JOBS)} jobs + 2 runs + 1 error into {database_url}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args()
    if not args.database_url:
        print("ERROR: --database-url or DATABASE_URL required", file=sys.stderr)
        return 2
    seed(args.database_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Test seed script**

Drop + recreate dev DB, then run seed:

```bash
docker compose exec postgres dropdb -U jobcrawler jobcrawler --if-exists
docker compose exec postgres createdb -U jobcrawler jobcrawler
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler \
  python -m crawler.storage.migrations.runner 2>/dev/null  # noop, use migrate()
```

Use the runner:
```bash
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler python -c "
from pathlib import Path
from crawler.storage.db import connect
from crawler.storage.migrations.runner import migrate
migrate(connect(), Path('crawler/storage/migrations'))
"
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler \
  python scripts/seed_demo_data.py
```

Expected: `Seeded 5 jobs + 2 runs + 1 error into postgresql://...`

Verify:
```bash
docker compose exec postgres psql -U jobcrawler -d jobcrawler -c "SELECT COUNT(*) FROM jobs"
docker compose exec postgres psql -U jobcrawler -d jobcrawler -c "SELECT COUNT(*) FROM runs"
docker compose exec postgres psql -U jobcrawler -d jobcrawler -c "SELECT COUNT(*) FROM run_errors"
```

Expected: `5`, `2`, `1`.

- [ ] **Step 3: Commit**

```bash
git add scripts/seed_demo_data.py
git commit -m "feat(seed): seed_demo_data.py — PG inserts (5 jobs + 2 runs + 1 error)"
```

---

## Task 11: dashboard/lib/db.ts — pg.Pool

**Files:**
- Rewrite: `dashboard/lib/db.ts`

**Pre-req:** `cd dashboard && npm install pg @types/pg` (full removal of `better-sqlite3` happens in Task 14; for this task we just need `pg` importable so the tsc check passes).

- [ ] **Step 1: Rewrite `db.ts`**

```typescript
import { Pool } from "pg";

/**
 * PostgreSQL connection pool for the dashboard.
 *
 * Path resolution:
 *   1. DATABASE_URL env var
 *   2. Default: postgresql://jobcrawler:dev@localhost:5433/jobcrawler
 *
 * Async (vs previous sync better-sqlite3). RSC supports async natively.
 */
let _pool: Pool | null = null;

function resolveDatabaseUrl(): string {
  return (
    process.env.DATABASE_URL ??
    "postgresql://jobcrawler:dev@localhost:5433/jobcrawler"
  );
}

export function getPool(): Pool {
  if (_pool) return _pool;
  _pool = new Pool({
    connectionString: resolveDatabaseUrl(),
    min: 2,
    max: 10,
    idleTimeoutMillis: 30_000,
    connectionTimeoutMillis: 5_000,
  });
  return _pool;
}

/** For tests: reset cached pool so a different connection can be used. */
export async function resetPool(): Promise<void> {
  if (_pool) {
    await _pool.end();
    _pool = null;
  }
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run:
```bash
cd dashboard && npx tsc --noEmit
```

Expected: clean (no errors).

- [ ] **Step 3: Commit**

```bash
git add dashboard/lib/db.ts
git commit -m "feat(dashboard): db.ts — pg.Pool singleton (replaces better-sqlite3)"
```

---

## Task 12: dashboard/lib/queries.ts — async PG queries

**Files:**
- Rewrite: `dashboard/lib/queries.ts`

- [ ] **Step 1: Rewrite `queries.ts`**

```typescript
import { getPool } from "./db";

export interface Job {
  id: number;
  source: string;
  source_id: string;
  url: string;
  title: string;
  company: string | null;
  location: string | null;
  description: string | null;
  first_seen_at: string;
  last_seen_at: string;
}

export interface Run {
  id: number;
  source: string;
  started_at: string;
  ended_at: string | null;
  status: "pending" | "running" | "success" | "partial" | "failed";
  jobs_found: number;
  jobs_new: number;
}

export interface RunError {
  id: number;
  run_id: number;
  occurred_at: string;
  stage: string;
  message: string;
}

export interface Stats {
  jobs_total: number;
  runs_success: number;
  runs_failed: number;
  errors_total: number;
  by_source: Record<string, number>;
}

export async function getStats(): Promise<Stats> {
  const pool = getPool();
  const [jobs, runsS, runsF, errors, bySource] = await Promise.all([
    pool.query<{ n: string }>("SELECT COUNT(*)::int AS n FROM jobs"),
    pool.query<{ n: string }>(
      "SELECT COUNT(*)::int AS n FROM runs WHERE status = 'success'"
    ),
    pool.query<{ n: string }>(
      "SELECT COUNT(*)::int AS n FROM runs WHERE status = 'failed'"
    ),
    pool.query<{ n: string }>("SELECT COUNT(*)::int AS n FROM run_errors"),
    pool.query<{ source: string; n: string }>(
      "SELECT source, COUNT(*)::int AS n FROM jobs GROUP BY source"
    ),
  ]);
  return {
    jobs_total: jobs.rows[0].n,
    runs_success: runsS.rows[0].n,
    runs_failed: runsF.rows[0].n,
    errors_total: errors.rows[0].n,
    by_source: Object.fromEntries(
      bySource.rows.map((r) => [r.source, r.n])
    ),
  };
}

export async function listJobs(filter?: {
  source?: string;
  limit?: number;
}): Promise<Job[]> {
  const pool = getPool();
  const limit = filter?.limit ?? 100;
  if (filter?.source) {
    const { rows } = await pool.query<Job>(
      "SELECT * FROM jobs WHERE source = $1 ORDER BY last_seen_at DESC LIMIT $2",
      [filter.source, limit]
    );
    return rows;
  }
  const { rows } = await pool.query<Job>(
    "SELECT * FROM jobs ORDER BY last_seen_at DESC LIMIT $1",
    [limit]
  );
  return rows;
}

export async function getJob(id: number): Promise<Job | null> {
  const pool = getPool();
  const { rows } = await pool.query<Job>("SELECT * FROM jobs WHERE id = $1", [
    id,
  ]);
  return rows[0] ?? null;
}

export async function listRuns(limit = 50): Promise<Run[]> {
  const pool = getPool();
  const { rows } = await pool.query<Run>(
    "SELECT * FROM runs ORDER BY started_at DESC LIMIT $1",
    [limit]
  );
  return rows;
}

export async function getRunErrors(runId: number): Promise<RunError[]> {
  const pool = getPool();
  const { rows } = await pool.query<RunError>(
    "SELECT * FROM run_errors WHERE run_id = $1 ORDER BY occurred_at DESC",
    [runId]
  );
  return rows;
}
```

- [ ] **Step 2: Type-check**

Run:
```bash
cd dashboard && npx tsc --noEmit
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add dashboard/lib/queries.ts
git commit -m "feat(dashboard): queries.ts — async pg queries (stats, jobs, runs, errors)"
```

---

## Task 13: dashboard pages — async refactor

**Files:**
- Modify: `dashboard/app/page.tsx`
- Modify: `dashboard/app/jobs/page.tsx`
- Modify: `dashboard/app/runs/page.tsx`
- Modify: `dashboard/components/JobTable.tsx` (if it calls queries directly)

Every function that calls a query becomes `async`. Every caller `await`s it. RSC supports this natively.

- [ ] **Step 1: Inspect current pages**

Read each page file. Identify every `getStats()`, `listJobs()`, `listRuns()`, `getRunErrors()` call site.

- [ ] **Step 2: Add `async` + `await`**

Pattern:
```tsx
// BEFORE
export default function Page() {
  const stats = getStats();
  return <StatsView stats={stats} />;
}

// AFTER
export default async function Page() {
  const stats = await getStats();
  return <StatsView stats={stats} />;
}
```

- [ ] **Step 3: Build to catch type errors**

Run:
```bash
cd dashboard && npx next build 2>&1 | tail -30
```

Expected: 0 errors. If errors, fix and re-run.

- [ ] **Step 4: Commit**

```bash
git add dashboard/app/ dashboard/components/
git commit -m "refactor(dashboard): async RSC pages — await pg query calls"
```

---

## Task 14: dashboard/package.json — drop better-sqlite3, add pg

**Files:**
- Modify: `dashboard/package.json`

- [ ] **Step 1: Update deps**

Replace:
```json
"dependencies": {
  "better-sqlite3": "^11.x",
  "next": "...",
  "react": "...",
  ...
}
```
With:
```json
"dependencies": {
  "next": "...",
  "pg": "^8.13.0",
  "react": "...",
  ...
},
"devDependencies": {
  "@types/pg": "^8.11.0",
  ...
}
```

(Exact versions: run `npm view pg version` and `npm view @types/pg version` to get latest stable.)

- [ ] **Step 2: Reinstall**

Run:
```bash
cd dashboard && rm -rf node_modules package-lock.json
npm install
```

Expected: installs cleanly, no peer-dep errors.

- [ ] **Step 3: Build to verify**

Run:
```bash
cd dashboard && npx next build 2>&1 | tail -10
```

Expected: clean build.

- [ ] **Step 4: Commit**

```bash
git add dashboard/package.json dashboard/package-lock.json
git commit -m "chore(dashboard-deps): drop better-sqlite3, add pg + @types/pg"
```

---

## Task 15: playwright global-setup.ts — PG seed

**Files:**
- Modify: `dashboard/tests/global-setup.ts`

- [ ] **Step 1: Rewrite global-setup**

```typescript
import { execSync } from "node:child_process";
import { Client } from "pg";

const DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://jobcrawler:dev@localhost:5433/jobcrawler_test";

export default async function globalSetup() {
  // Drop + recreate test DB for isolation
  const adminUrl = DATABASE_URL.replace(/\/[^/]+$/, "/postgres");
  const admin = new Client({ connectionString: adminUrl });
  await admin.connect();
  await admin.query(
    `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '"jobcrawler_test"'`
  );
  await admin.query(`DROP DATABASE IF EXISTS "jobcrawler_test"`);
  await admin.query(`CREATE DATABASE "jobcrawler_test"`);
  await admin.end();

  // Run migrations
  execSync(
    `DATABASE_URL=${DATABASE_URL} python -c "from pathlib import Path; from crawler.storage.db import connect; from crawler.storage.migrations.runner import migrate; migrate(connect(), Path('crawler/storage/migrations'))"`,
    { stdio: "inherit" }
  );

  // Seed demo data
  execSync(
    `DATABASE_URL=${DATABASE_URL} python scripts/seed_demo_data.py`,
    { stdio: "inherit" }
  );
}
```

- [ ] **Step 2: Verify Playwright runs**

Run:
```bash
cd dashboard && npx playwright test --reporter=dot
```

Expected: 14/14 pass.

- [ ] **Step 3: Commit**

```bash
git add dashboard/tests/global-setup.ts
git commit -m "test(dashboard): playwright global-setup — PG test DB + migrations + seed"
```

---

## Task 16: Delete SQLite files + final cleanup

**Files:**
- Delete: `data/jobs.db`, `data/jobs.db-shm`, `data/jobs.db-wal`
- Modify: `.gitignore` (already updated)

- [ ] **Step 1: Delete SQLite files**

Run:
```bash
rm -f data/jobs.db data/jobs.db-shm data/jobs.db-wal
ls data/
```

Expected: only `.gitkeep` remains.

- [ ] **Step 2: Search for any remaining sqlite references**

Run:
```bash
grep -rn "sqlite3\|better-sqlite3\|jobs.db" --include="*.py" --include="*.ts" --include="*.tsx" --include="*.toml" --include="*.json" . 2>&1 | grep -v node_modules | grep -v .venv
```

Expected: no matches (or only intentional ones in comments/migration history).

- [ ] **Step 3: Commit any cleanup**

If cleanup needed:
```bash
git add -u
git commit -m "chore: remove SQLite files (migration to PG complete)"
```

---

## Task 17: README — PG quickstart

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace SQLite quickstart with PG quickstart**

Find the "quickstart" section. Replace SQLite instructions with:

```markdown
## Quickstart

1. Install deps:
   ```bash
   pip install -e ".[dev]"
   cd dashboard && npm install
   ```

2. Start PostgreSQL:
   ```bash
   docker compose up -d postgres
   ```

3. Apply migrations:
   ```bash
   python -c "from pathlib import Path; from crawler.storage.db import connect; from crawler.storage.migrations.runner import migrate; migrate(connect(), Path('crawler/storage/migrations'))"
   ```

4. Seed demo data:
   ```bash
   python scripts/seed_demo_data.py
   ```

5. Start dashboard:
   ```bash
   cd dashboard && npx next start --port 3011
   # Open http://127.0.0.1:3011
   ```

## Tests

```bash
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler pytest tests/ -q
cd dashboard && npx playwright test
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): PostgreSQL quickstart (docker-compose + migrations + seed)"
```

---

## Task 18: Coverage measurement (test_scope: true)

**Files:**
- Modify: (none, run existing tools)

- [ ] **Step 1: Run pytest with coverage**

Run:
```bash
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler \
  pytest tests/ --cov=crawler --cov-report=term-missing -q
```

Expected: coverage report. Baseline was 90% (per `pyproject.toml` `fail_under = 90`).

- [ ] **Step 2: Compare to baseline**

If coverage dropped, find the gap:
```bash
pytest tests/ --cov=crawler --cov-report=term-missing --cov-report=html
# Open htmlcov/index.html
```

Add tests for uncovered lines. Likely candidates: `close_pool()`, `get_source()` (untested), error paths.

- [ ] **Step 3: Commit any new tests**

```bash
git add tests/
git commit -m "test(coverage): fill PG migration gaps — coverage stays >=90%"
```

---

## Task 19: End-to-end verification

**Files:**
- (none, run all checks)

- [ ] **Step 1: PG up + fresh migrate + seed**

```bash
docker compose up -d postgres
docker compose exec postgres dropdb -U jobcrawler jobcrawler --if-exists
docker compose exec postgres createdb -U jobcrawler jobcrawler
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler \
  python -c "from pathlib import Path; from crawler.storage.db import connect; from crawler.storage.migrations.runner import migrate; migrate(connect(), Path('crawler/storage/migrations'))"
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler \
  python scripts/seed_demo_data.py
```

- [ ] **Step 2: Full pytest**

```bash
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler \
  pytest tests/ -q
```

Expected: 84+ tests pass.

- [ ] **Step 3: Dashboard build**

```bash
cd dashboard && npx next build 2>&1 | tail -10
```

Expected: clean (0 errors).

- [ ] **Step 4: Dashboard start + smoke routes**

```bash
cd dashboard && npx next start --port 3011 &
SERVER_PID=$!
sleep 4
for path in / /jobs /runs; do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3011$path)
  echo "$path → HTTP $code"
done
kill $SERVER_PID
```

Expected: all 3 routes return HTTP 200.

- [ ] **Step 5: Playwright suite**

```bash
cd dashboard && npx playwright test --reporter=line
```

Expected: 14/14 pass.

- [ ] **Step 6: Verify all changes committed + branch ready for PR**

```bash
git status
git log --oneline main..HEAD
```

Expected: clean working tree, branch `relentless/pg-migration` ahead of main.

- [ ] **Step 7: Final commit (no-op or "chore: e2e verified")**

```bash
git commit --allow-empty -m "chore(pg-migration): end-to-end verified — pytest + playwright + dashboard routes"
```

---

## Summary

19 tasks, ~80% TDD where tests are meaningful (db, runner, dedup, repository, queries, fixtures). Pure-infra tasks (docker-compose, pyproject, package.json) skip TDD. Coverage task included per spec `test_scope: true`.

**Open risks (from spec):**
1. Dashboard async refactor — every query call site changes signature. RSC handles natively.
2. Test speed — ephemeral PG schema is slower than `:memory:` SQLite. Acceptable.
3. pgvector extension — depends on `pgvector/pgvector:pg16` Docker image (pinned).

**Out of scope:**
- pgvector data population (sub-project 2)
- FTS, LISTEN/NOTIFY, partitioning
- Production hosting (Neon/Supabase)
- ORM adoption
