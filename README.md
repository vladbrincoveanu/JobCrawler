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

### `/matches` — the scheduled scan, per CV

`/matches?cv=<id>` shows the last scan the `scout-cron` workflow produced for
one CV, with a switcher across all configured CVs that carries each one's
last-run state. The failure worth seeing is a single CV that stopped running
while the others kept going; without that per-tab state it renders as a quiet
week.

The feed is read, in priority order:

1. `SCOUT_FEED_BASE_URL` — raw base URL of the `scout-data` branch, e.g.
   `https://raw.githubusercontent.com/<owner>/<repo>/scout-data`. Files under it
   are `results/<cv-id>.json` and `runs/<cv-id>.json`. **This is what the
   deployment uses.**
2. `SCOUT_FEED_URL` — the legacy single feed, kept for one release.
3. `SCOUT_FEED_DIR` (default `data/scout/`) — a local checkout of that branch.

No feed yet — a 404 or a missing file — is a normal empty state. A feed that
exists but will not parse is reported as an error: a broken cron must not hide
behind a friendly "nothing yet".

### `/profiles` — the control panel

Which CVs are scanned, when, with what filters, and above what match percentage
they trigger a Telegram alert. Saving commits `scout/profiles.json` on the
default branch — the same file the workflow reads, so the page and the cron
cannot drift. "Scan now" dispatches the workflow rather than scanning here.

Reading is public (`scout/` is a committed, public directory anyway). Writing
needs a session; see **Deployment** below.

> The route is `/profiles`, not `/cvs`, because the Vercel CLI's upload filter
> silently drops directories named like version-control metadata — `.git`,
> `.svn`, `CVS`. `app/cvs/` built locally and 404'd in production with nothing
> in the build log to say why.

### Scheduled scans (GitHub Actions)

`.github/workflows/scout-cron.yml` wakes hourly and asks `scripts/cv_schedule.py`
which CVs are due, per each profile's own `hours_utc`. It also runs on demand
(Actions → scout-cron → Run workflow, with `cv_id` and `force` inputs — which is
exactly what the dashboard's "Scan now" sends).

It publishes `results/`, `runs/` and `sent/` to the **`scout-data`** branch.

No CV PDF is involved: the runner reads `scout/profiles/<id>.json`, roughly
600 bytes of `{skills, role_titles, source}`. Nothing else may be written there
— `dashboard/lib/cvProfiles.ts` rejects (does not strip) any other key, any
email-, phone- or credential-shaped value, and PII-shaped map *keys* as well as
values. `scout/` is world-readable and a public branch's history stays readable
after the field stops being written.

Required secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Optional:
`NVIDIA_API_KEY` (LLM profile extraction and rerank), `ADZUNA_APP_ID` +
`ADZUNA_APP_KEY`, `JOOBLE_KEY`. With no LLM key the run still works — keyword
scoring only.

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

## Deployment (Vercel)

The dashboard is deployed at **https://jobcrawler-scout.vercel.app** and is the
intended way to use it. Vercel has a read-only filesystem and no Python, so the
deployed app does not scan and does not write files: it commits configuration to
this repository and dispatches the workflow that owns scanning.

Project root is `dashboard/`. Deploy with:

```bash
cd dashboard && vercel deploy --prod
```

Environment variables (Vercel project settings, all three environments):

| Variable | Purpose | Without it |
|---|---|---|
| `SCOUT_FEED_BASE_URL` | Raw base URL of the `scout-data` branch | Every board is empty |
| `GITHUB_REPO` | `owner/name` of this repository | Config falls back to a local file that does not exist on Vercel |
| `GITHUB_BRANCH` | Default `main` | — |
| `GITHUB_TOKEN` | Fine-grained PAT, **Contents: read/write** and **Actions: read/write**, scoped to this repo only | The CV list is empty and saves and "Scan now" both refuse |
| `DASHBOARD_PASSWORD` | The one password for the one user | Reads work; every write is refused with 503 |

`DATABASE_URL` is deliberately **not** set: the crawler pages (`/`, `/jobs`,
`/runs`) query PostgreSQL, and `pg` hangs rather than erroring on an unreachable
host, so the whole site would read as down. With it unset those routes drop out
of the nav and `/` redirects to `/matches`.

Nothing here stores a credential. `/profiles` reports which are present *by
name* and prints `gh secret set KEY` for the missing ones — that command prompts
on your own terminal, so the value never enters a request body, a response, or
shell history.

Writes are confined to `scout/`: the same token can reach `.github/workflows`,
and a config editor that can rewrite its own CI is a different thing entirely.


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

# Just the pure-Node lib specs (cvProfiles, credentials, feed, github, auth).
# PW_NO_SERVER skips booting Next for them: it costs a two-minute build they
# never use, and where listen(2) is denied it fails as "0 tests ran".
cd dashboard && PW_NO_SERVER=1 npx playwright test tests/{cv-profiles,credentials,feed,github,auth}.spec.ts

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

`/matches` and `/profiles` are tested against `dashboard/tests/fixtures/`, wired
in by `playwright.config.ts`: `config/` supplies one CV profile and
`feed/results/test-cv.json` its scan. The suite therefore never reads (or
overwrites) the real `scout/profiles.json` or a real scan in `data/scout/`. That
one fixture file is reached both as the per-CV feed and, via `SCOUT_FEED_PATH`,
as the legacy single feed — two copies would drift, and the point of the
migration is that both render the same scan.

`DASHBOARD_PASSWORD` is deliberately unset for the test server, so the suite
asserts the fail-closed case: an unauthenticated deployment renders the config
read-only and answers 503 to a POST aimed straight at the API.

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
