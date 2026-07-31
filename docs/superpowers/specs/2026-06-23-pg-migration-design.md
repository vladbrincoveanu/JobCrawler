---
title: PostgreSQL backend swap (sub-project 1.5)
date: 2026-06-23
status: approved
ui_scope: false
graph_scope: false
test_scope: true
---

# PostgreSQL backend swap

## Goal

Replace SQLite (current backend) with PostgreSQL everywhere — crawler writes, dashboard reads, tests, dev infra. Drop SQLite entirely. Keep API contracts identical (same tables, same columns, same queries return same shapes) so dashboard pages don't change.

## Driver / motivation

User wants hands-on experience with PostgreSQL and its features (specifically pgvector for the upcoming sub-project 2 / Enrichment work). This spec establishes PG as the storage backend; pgvector data population lands with sub-project 2.

## Scope

**In scope:**

- Replace SQLite with PostgreSQL 16 (docker-compose for local)
- Rewrite schema in PG dialect (idiomatic types: TIMESTAMPTZ, BOOLEAN, JSONB, GENERATED ALWAYS AS IDENTITY)
- Reserve pgvector `vector(384)` column on jobs (no data yet — sub-project 2 populates it)
- Swap Python `sqlite3` → `psycopg[binary]` + `psycopg_pool`
- Swap Node `better-sqlite3` → `pg`
- Update all tests (sqlite `:memory:` → ephemeral PG schema)
- Delete `data/jobs.db*`
- Add `docker-compose.yml`, `.env.example` updates, README infra section
- Nuke existing data (5 seed rows; no production data)

**Out of scope (deferred):**

- pgvector data population → sub-project 2
- Full-text search (tsvector + GIN)
- LISTEN/NOTIFY realtime dashboard
- Partitioning, replication, observability
- Production hosting (Neon / Supabase / RDS) — local docker-compose only
- ORM (SQLAlchemy, Prisma, Drizzle) — raw SQL + parameterized queries
- Async Python refactor of crawler — stays sync

## Stack

| Layer | Choice | Why |
|---|---|---|
| PostgreSQL version | 16 | Latest stable, pgvector compatible |
| Local infra | docker-compose, `postgres:16` image | Reproducible, CI-friendly |
| Python driver | `psycopg[binary]` | Sync, drop-in for sqlite3, mature |
| Python pooling | `psycopg_pool.ConnectionPool` | Official psycopg pool |
| Node driver | `pg` | Mature, sync-or-async, Next.js RSC compatible |
| Migration runner | Custom (current pattern) | Keeps runner.py shape; alembic overkill for one schema |
| Test infra | docker-compose PG, ephemeral schema per test | No testcontainers dep, ~2s per session startup |

## Schema (PG dialect)

`crawler/storage/migrations/V001__initial.sql` rewritten:

```sql
-- V001: initial schema (PG dialect)
-- Spec: 2026-06-23-pg-migration-design.md

CREATE TABLE schema_migrations (
  version    INTEGER PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  description TEXT NOT NULL
);

CREATE TABLE sources (
  name              TEXT PRIMARY KEY,
  enabled           BOOLEAN NOT NULL DEFAULT TRUE,
  rate_limit_per_min INTEGER NOT NULL DEFAULT 30,
  last_crawled_at   TIMESTAMPTZ
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
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source       TEXT NOT NULL REFERENCES sources(name),
  source_id    TEXT NOT NULL,
  url          TEXT NOT NULL,
  title        TEXT NOT NULL,
  company      TEXT,
  location     TEXT,
  description  TEXT,
  embedding    vector(384),                    -- pgvector; populated sub-project 2
  content_hash TEXT NOT NULL UNIQUE,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  raw_payload  JSONB,                          -- replaces raw_html (sub-project 1 spec §4)
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

CREATE INDEX idx_jobs_source       ON jobs (source);
CREATE INDEX idx_jobs_last_seen    ON jobs (last_seen_at DESC);
CREATE INDEX idx_runs_source_time  ON runs (source, started_at DESC);
CREATE INDEX idx_run_errors_run_id ON run_errors (run_id);

-- pgvector ivfflat index reserved; created only when data lands (sub-project 2)
-- CREATE INDEX idx_jobs_embedding ON jobs USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

Key type changes vs SQLite:
- `INTEGER PRIMARY KEY AUTOINCREMENT` → `BIGINT GENERATED ALWAYS AS IDENTITY`
- `0/1` enabled flags → `BOOLEAN`
- ISO TEXT timestamps → `TIMESTAMPTZ`
- Status as `TEXT` + convention → `run_status` ENUM
- Raw HTML column → `JSONB` (raw_payload)
- `vector(384)` column reserved

## Module design blocks

### Module: `crawler/storage/db.py`
- **Responsibility:** Open + pool-manage PG connections with sane timeouts.
- **Interface:** `connect() -> Connection` (single conn, for migrations), `get_pool() -> ConnectionPool` (for app).
- **Dependencies:** `psycopg_pool`, `crawler.config` (DATABASE_URL).
- **Size target:** ≤80 lines.

### Module: `crawler/storage/repository.py`
- **Responsibility:** Typed CRUD over jobs, runs, sources, errors.
- **Interface:** `upsert_job`, `get_by_hash`, `list_jobs`, `record_run`, `record_error`, etc.
- **Dependencies:** `crawler.storage.db`, PG types.
- **Size target:** ≤300 lines. Split if grows.

### Module: `crawler/storage/migrations/runner.py`
- **Responsibility:** Apply pending migrations in order, track in `schema_migrations`.
- **Interface:** `migrate(conn, migrations_dir) -> None`.
- **Dependencies:** PG, filesystem.
- **Size target:** ≤120 lines.

### Module: `crawler/storage/dedup.py`
- **Responsibility:** Compute + check content hash for upsert dedup.
- **Interface:** `content_hash(job) -> str`, `is_duplicate(conn, hash) -> bool`.
- **Dependencies:** None (pure + tiny DB call).
- **Size target:** ≤80 lines.

### Module: `dashboard/lib/db.ts`
- **Responsibility:** Singleton `pg.Pool` for dashboard queries.
- **Interface:** `getPool() -> Pool`, `resetPool()` (tests).
- **Dependencies:** `pg`, `process.env.DATABASE_URL`.
- **Size target:** ≤60 lines.

### Module: `dashboard/lib/queries.ts`
- **Responsibility:** Typed query functions returning dashboard shapes.
- **Interface:** `getStats()`, `listJobs(filter)`, `getJob(id)`, `listRuns()`, `getRunErrors(runId)`. All async.
- **Dependencies:** `dashboard/lib/db`, `@/types`.
- **Size target:** ≤200 lines.

### Module: `docker-compose.yml` (new)
- **Responsibility:** Local PG 16 service for dev + tests.
- **Interface:** `docker compose up -d postgres`.
- **Dependencies:** Docker.
- **Size target:** ≤30 lines.

### Module: `scripts/seed_demo_data.py`
- **Responsibility:** Populate demo data into PG (5 jobs + 2 runs + 1 error).
- **Interface:** `python scripts/seed_demo_data.py [--db-url URL]`.
- **Dependencies:** psycopg, fixture data.
- **Size target:** ≤180 lines.

## Data flow

### Crawler writes (Python, sync)

```
crawler run → crawler/storage/pipeline.py
  → repository.upsert_job(conn, job)         # INSERT ... ON CONFLICT (source, source_id) DO UPDATE
  → repository.record_run(conn, run_result)  # status ENUM
  → repository.record_error(conn, error)     # if any
psycopg_pool.ConnectionPool:
  with pool.connection() as conn:
      with conn.transaction():
          ... write ops ...
```

### Dashboard reads (Node, async RSC)

```
Next.js RSC page → dashboard/lib/queries.ts (async)
  → pg.Pool: const { rows } = await pool.query(sql, [...params])
  → return typed shape
Dashboard page renders rows (already-typed, no hydration boundary)
```

### Test infra

```
tests/conftest.py (or pytest plugin):
  - Session-scoped fixture: ensure docker-compose PG up, wait for ready
  - Function-scoped fixture: CREATE SCHEMA test_<uuid>; SET search_path TO test_<uuid>;
                              yield; DROP SCHEMA test_<uuid> CASCADE;
  - Run migrations into test schema once per session
Playwright global-setup.ts:
  - Same docker-compose PG; same schema-per-test pattern via --db-url override
```

## Error handling

| Failure | Behavior |
|---|---|
| PG unreachable at startup | Fail fast, clear error message ("DATABASE_URL set? docker-compose up?") |
| PG connection lost mid-query | psycopg pool reconnects automatically; query fails with `OperationalError`, surfaced to caller |
| Migration already applied | `schema_migrations` row exists → skip (idempotent) |
| Migration partially applied | `schema_migrations` row absent + table exists → manual fix required; runner exits non-zero |
| pgvector extension missing | Migration fails clearly: "CREATE EXTENSION vector; — install postgresql-16-pgvector or use pgvector/pgvector:pg16 image" |
| Test schema creation race | `CREATE SCHEMA IF NOT EXISTS` per test with UUID suffix → no race |

## Test strategy

**Unit tests (existing):** same coverage, swap `sqlite :memory:` for ephemeral PG schema per test. No logic changes expected.

**Integration tests (existing):** same crawler → storage round-trip via PG.

**New infra test:** `tests/integration/test_pg_pool.py` — connection acquisition, transaction rollback, pool exhaustion.

**Test speed:** estimated 2-5x slower than SQLite `:memory:` (~10s → ~30-50s for full suite). Acceptable.

**CI:** GitHub Actions step: `docker compose up -d postgres` before pytest + playwright.

## Risks (open)

1. **Dashboard async refactor** — every query call site changes signature (sync → async/await). ~6 call sites in `dashboard/app/`. Mitigated by RSC's native async support.
2. **Test suite speed** — ephemeral PG schema per test is slower than `:memory:`. Acceptable tradeoff for clean isolation.
3. **pgvector extension** — depends on `postgres:16-pgvector` Docker image (or manual `CREATE EXTENSION vector`). Add explicit image pinning.
4. **psycopg sync semantics in async context** — psycopg is sync. Crawler stays sync (good). Dashboard becomes async. No mixing.
5. **No transaction wrapping in dashboard reads** — dashboard reads are single queries, no need for transactions. Pool checkout handles it.
6. **Connection pool sizing** — defaults (min=2, max=10 for app, min=1 max=2 for tests) are guesses. Will tune after first run.

## Migration path (from SQLite)

1. Add `docker-compose.yml` + `.env.example`
2. Write `crawler/storage/migrations/V001__initial.sql` (PG dialect, idempotent)
3. Rewrite `db.py`, `repository.py`, `runner.py`, `dedup.py`
4. Update `pyproject.toml` deps
5. Rewrite `dashboard/lib/db.ts`, `dashboard/lib/queries.ts`
6. Update `dashboard/package.json` deps
7. Add `async/await` to all dashboard page components
8. Rewrite `scripts/seed_demo_data.py`
9. Update all test files (sqlite → PG schema)
10. Update `tests/conftest.py` + Playwright `global-setup.ts`
11. Update `tests/fakes/browser.py` if it touches DB (no — only browser)
12. Delete `data/jobs.db*`
13. Run full suite: pytest + playwright
14. Commit

## Verification

- `docker compose up -d postgres` succeeds
- `python -c "import psycopg; psycopg.connect(os.environ['DATABASE_URL'])"` succeeds
- `pytest tests/` — all green
- `cd dashboard && npx playwright test` — 14/14 green
- `cd dashboard && npx next build` — clean
- `cd dashboard && npx next start --port 3010` — serves all 4 routes with HTTP 200
- Manual: open dashboard, see seeded jobs

## Out of scope for this spec

- Sub-project 2 (Enrichment) — separate spec, will use `embedding vector(384)` column
- Sub-project 4 (Scheduler) — separate spec
- Production deploy / cloud PG — separate spec
