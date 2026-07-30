# JobCrawler

Upload a CV, scan live job boards, get the open roles that match it best right now.

Two independent halves, and it is worth knowing which one you are using:

| | **Scout** (`scripts/scout.py` + `/scout`) | **Crawler** (`crawler/` + PostgreSQL) |
|---|---|---|
| What it does | CV in, ranked live matches out | archives listings into a database |
| Needs Postgres | no | yes |
| Sources | karriere.at, StepStone.at, Arbeitnow, Remotive, Jobicy, jobhive, Adzuna\*, Jooble\* | AMS |
| State | working end-to-end | see the AMS caveat below |

\* needs a free API key; skipped with a log line when the key is absent.

## Quickstart — CV scan (no database needed)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,scout]"          # 'scout' pulls requests/duckdb/pypdf

# CLI
python scripts/scout.py --dry-run --no-llm --sources apis,karriere \
  --cv /path/to/your_cv.pdf --days 30 --top 10

# Browser: upload a PDF at http://127.0.0.1:3011/scout
cd dashboard && npm install && npx next build
npx next start --port 3011
```

The `/scout` page posts the PDF to `/api/scout`, which shells out to
`scripts/scout.py --json-out` and renders the ranked result.

### How matching works (and what it is not)

The CV is parsed with `pypdf`, then turned into a skill profile — via an LLM if
`NVIDIA_API_KEY` is set, otherwise via the keyword lexicon in `scout.py`. Jobs
are scored on weighted title/description keyword hits, Vienna preference,
posting recency and salary transparency, then ranked 0–100 *within the result
set* so the number means "how does this compare to the rest of what's open".

**This is keyword matching, not embeddings.** The `embedding vector(384)` column
in `jobs` is still unused. Semantic matching would handle CV vocabulary that
does not literally appear in an ad ("event-driven" vs "message queues"), which
keyword scoring misses — but it needs an embedding model, a backfill over every
crawled job, and the scout does not read from Postgres at all today. Keyword
scoring was the honest first pass; the column stays reserved.

## Quickstart — crawler + dashboard (needs Postgres)

```bash
docker compose up -d postgres          # host port 5433 -> container 5432
playwright install chromium

DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler \
  python -c "from pathlib import Path; from crawler.storage.db import connect; from crawler.storage.migrations.runner import migrate; migrate(connect(), Path('crawler/storage/migrations'))"

DATABASE_URL=... python scripts/seed_demo_data.py
DATABASE_URL=... python scripts/crawl_ams.py --query Software --limit 24
DATABASE_URL=... python scripts/inspect_db.py
```

### The AMS caveat

`crawler/sources/ams.py` parses the **old** AMS markup at
`jobs.ams.at/public/jobs`. AMS has since moved to `/public/emps/`, an Angular SPA
behind a consent wall, so those selectors match nothing on the live site and
`scripts/crawl.py --source=ams` finds zero jobs. Its unit tests pass because they
feed it hand-written HTML in that old shape.

`scripts/crawl_ams.py` is the AMS crawler that actually works — it drives the SPA
with Playwright and is what has produced real rows in this database.
`scripts/crawl.py` is kept as the pipeline/adapter/storage wiring a future source
would plug into.

## Tests

```bash
# Python — 90% gate applies to crawler/ and needs Postgres up, since the
# repository/migration/pipeline tests skip (not fail) without it.
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler \
  pytest --cov=crawler --cov-fail-under=90

# Dashboard
cd dashboard && npx playwright test

# Include the live scan (real network, real job boards)
cd dashboard && SCOUT_LIVE=1 npx playwright test

# Run beside another dashboard instance
cd dashboard && DASHBOARD_PORT=3021 NEXT_DIST_DIR=.next-test npx playwright test
```

Without Postgres the dashboard specs skip with a stated reason instead of
failing, so the DB-free scout specs still run.

## Status

| # | Name | Status |
|---|------|--------|
| 1 | Crawler + Storage | pipeline + storage shipped; **AMS adapter targets retired markup** — use `scripts/crawl_ams.py` |
| 1.5 | PostgreSQL backend | shipped |
| 1.1 | karriere.at | shipped, in the scout (not as a `SourceAdapter`) |
| 1.2 | StepStone.at | shipped, in the scout; Akamai WAF 403s a share of requests, so it is off by default in the web scan |
| 1.3+ | LinkedIn | **not planned.** Scraping it means defeating deliberate anti-bot measures and breaching their ToS. Not worth the account ban. |
| 2 | Enrichment / CV matching | shipped as keyword + optional-LLM scoring in the scout; pgvector embeddings **not** done |
| 3 | Dashboard (Next.js) | shipped |
| 4 | Scheduler (cron, alerts) | Telegram digest works (`scripts/scout.py` without `--dry-run`); no cron wiring |

Also evaluated and rejected as sources: **devjobs.at** (Vercel bot challenge, 429
on every path), **RemoteOK** (already covered by the `remoteok` jobhive slice,
and its API terms require a backlink), **TheMuse** (live and free, but almost
entirely US postings), **Arbeitsagentur Jobsuche** (live and free, but it is the
German federal agency — a "Wien" search returns Kaiserslautern).

## Port overrides (dev box)

- **PG port 5433** (not 5432): host 5432 occupied by `knowledgeforge-postgres`
- **Dashboard port 3011** (not 3010): host 3010 occupied by `knowledgeforge-ui`

Override the dashboard port with `DASHBOARD_PORT`; for PG, adjust
`docker-compose.yml` and `DATABASE_URL`.

## License

MIT — see `LICENSE`.
