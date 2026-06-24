# JobCrawler

Job listings crawler + storage + dashboard. Sub-projects 1 (crawler), 1.5 (PG backend), and 3 (dashboard) shipped.

## Quickstart

```bash
# Python deps
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium

# Start PostgreSQL
docker compose up -d postgres

# Apply migrations (PG container listens on host port 5433, container 5432)
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler \
  python -c "from pathlib import Path; from crawler.storage.db import connect; from crawler.storage.migrations.runner import migrate; migrate(connect(), Path('crawler/storage/migrations'))"

# Seed demo data
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler \
  python scripts/seed_demo_data.py

# Dry-run AMS
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler \
  python scripts/crawl.py --source=ams --limit=10 --dry-run

# Real crawl
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler \
  python scripts/crawl.py --source=ams --limit=50

# Inspect DB
python scripts/inspect_db.py

# Dashboard (port 3011 because 3010 is occupied by knowledgeforge-ui)
cd dashboard && npm install && npx next build
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler \
  npx next start --port 3011
# Open http://127.0.0.1:3011
```

## Architecture

Crawler pipeline fetches job listings from sources, normalizes + dedupes them, persists to PostgreSQL. Sub-project 1 ships AMS only (Playwright). Other sources (Karriere.at, Willhaben, LinkedIn) are sub-projects 1.1+.

```
scripts/crawl.py → crawler.pipeline → AmsAdapter → BrowserContext (Playwright) → PostgreSQL
```

Storage uses PostgreSQL 16 with pgvector (`embedding vector(384)` reserved for sub-project 2 enrichment). Docker-compose for local dev. `pgvector/pgvector:pg16` image. Tests use ephemeral PG schemas (UUID-suffixed) for isolation.

## Tests

```bash
# Python
DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler pytest

# Dashboard
cd dashboard && npx playwright test
```

Coverage gate: 90% (see `crawler/config.py:COVERAGE_GATE`).

## Sub-projects

| # | Name | Status |
|---|------|--------|
| 1 | Crawler + Storage (AMS) | shipped |
| 1.5 | PostgreSQL backend swap | shipped (this session) |
| 1.1 | Karriere.at adapter | deferred |
| 1.2 | Willhaben.at/jobs adapter | deferred |
| 1.3+ | LinkedIn adapter | deferred |
| 2 | Enrichment (LLM, embeddings, scoring) | deferred |
| 3 | Dashboard (Next.js) | shipped |
| 4 | Scheduler (cron, env config, alerts) | deferred |

## Port overrides (dev box)

- **PG port 5433** (instead of default 5432): host 5432 occupied by `knowledgeforge-postgres`
- **Dashboard port 3011** (instead of default 3010): host 3010 occupied by `knowledgeforge-ui`

If your dev box has both ports free, you can switch back to defaults — adjust `docker-compose.yml` port mapping and `DATABASE_URL`.

## License

MIT — see `LICENSE`.
