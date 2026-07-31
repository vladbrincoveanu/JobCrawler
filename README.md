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

### The two filters

Both pages carry the same two, and no others: **posted within N days**, and
**only jobs that state a salary**. On `/scout` they are scan parameters (`days`
narrows what the boards are asked for; `require_salary` becomes
`--require-salary`). On `/matches` they filter an already-fetched feed.

An ad with **no posting date at all** survives the date filter deliberately.
Several boards omit it, and treating undated as old would make them vanish the
moment the filter was touched — looking like "no new jobs" rather than "this
board doesn't date its ads".

### `/matches` — the scheduled scan

`/matches` shows the last scan produced by the `scout-cron` GitHub Actions
workflow, so the dashboard has jobs in it without anyone uploading anything.
It reads, in priority order:

1. `SCOUT_FEED_URL` — raw URL of `latest.json` on the `scout-data` branch, for
   a deployed dashboard with no checkout to read from;
2. `data/scout/latest.json` in the repo (also settable via `SCOUT_FEED_PATH`).

No feed yet is a normal empty state with setup instructions. A feed that exists
but will not parse is reported as an error — a broken cron must not hide behind
a friendly "nothing yet".

### Scheduled scans (GitHub Actions)

`.github/workflows/scout-cron.yml` runs daily at 05:30 UTC and on demand
(Actions → scout-cron → Run workflow, with `days`/`top`/`sources`/
`require_salary` inputs). It publishes `latest.json` plus a timestamped copy
to the **`scout-data`** branch, and uploads the same file as an artifact.

The CV never lives in this repository — it is passed as a secret and exists
only on the runner:

```bash
base64 -w0 /path/to/cv.pdf | gh secret set CV_PDF_BASE64   # -i instead of -w0 on macOS
```

Optional secrets: `NVIDIA_API_KEY` (LLM profile extraction, rerank, and
employer pros/cons), `ADZUNA_APP_ID` + `ADZUNA_APP_KEY`, `JOOBLE_KEY`. With no
LLM key the run still works — keyword scoring, no review panels.

### Employer pros/cons

`scripts/company_reviews.py`, enabled with `scout.py --company-reviews`, adds a
short pros/cons panel per company, cached in `data/company_reviews/`.

**It is not scraped from Glassdoor, kununu, or any review site.** All of them
forbid scraping and sit behind bot walls, which is the same verdict this
project already reached for devjobs.at and metajob.at. It asks a language model
what is generally reported about working there. That is a useful list of things
to go verify and is not sourced fact: the prompt makes "I don't recognise this
company" an easy answer, unknown and hedged-empty answers produce no panel at
all, and every record carries its `source` so the dashboard can print the
caveat next to the pros and cons. It does.

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
failing, so the DB-free scout specs still run. Note the consequence: a spec that
only runs under Postgres can drift unnoticed for a long time. Several had —
they asserted against a fixture `seed_demo_data.py` does not produce — and were
corrected the first time the suite was actually run with a database up.

`/matches` is tested against `dashboard/tests/fixtures/scout-feed.json`, wired
in by `playwright.config.ts` via `SCOUT_FEED_PATH`, so the suite never reads (or
overwrites) a real scan sitting in `data/scout/`.

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
| 4 | Scheduler (cron, alerts) | shipped — `.github/workflows/scout-cron.yml` runs daily and publishes to the `scout-data` branch; Telegram digest also works (`scripts/scout.py` without `--dry-run`) |
| 5 | Employer pros/cons | shipped as `--company-reviews` (model-generated, cached, explicitly not scraped from review sites) |

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
