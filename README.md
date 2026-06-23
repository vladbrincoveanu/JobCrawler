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

## License

Proprietary. All rights reserved.
