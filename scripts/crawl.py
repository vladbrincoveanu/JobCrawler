"""Generic crawl CLI: `crawler.pipeline` + a `SourceAdapter`, into PostgreSQL.

Exit codes: 0=success, 1=partial, 2=failed, 3=dry-run.

WHICH SCRIPT TO USE FOR AMS
---------------------------
`crawler.sources.ams.AmsAdapter` parses the *old* AMS markup at
`jobs.ams.at/public/jobs` -- a server-rendered card list. AMS has since moved to
`/public/emps/`, an Angular SPA behind a consent wall, so those selectors match
nothing on the live site and this script reports 0 jobs found for `--source ams`.
It is kept because it is the only wiring of the pipeline + adapter + storage
contract, and that contract is what a second source would plug into.

For a real AMS crawl use `scripts/crawl_ams.py`, which drives the SPA with
Playwright and is the path that has actually produced rows in this database:

    python scripts/crawl_ams.py --query Software --limit 24

This file previously did not run at all: it referenced `config.DB_PATH` (removed
in the PostgreSQL migration) and called `start_run`, `finish_run` and
`record_error` with their pre-migration signatures, so it raised AttributeError
before it ever opened a connection.
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from crawler.browser import PlaywrightBrowserContext, SessionCookieStore
from crawler.exceptions import CrawlerError
from crawler.models import JobQuery
from crawler.pipeline import run
from crawler.sources.ams import AmsAdapter
from crawler.storage.db import connect
from crawler.storage.migrations.runner import migrate
from crawler.storage.repository import finish_run, record_error, start_run, upsert_source

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "crawler" / "storage" / "migrations"
SESSION_DIR = Path(__file__).resolve().parent.parent / "data"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="crawl")
    p.add_argument("--source", default="ams", help="Source name (only 'ams' is wired)")
    p.add_argument("--limit", type=int, default=200, help="Max jobs per source (default 200)")
    p.add_argument("--query", default="", help="Search keywords")
    p.add_argument("--since", default=None, help="ISO date — filter by posted_at >=")
    p.add_argument("--dry-run", action="store_true",
                   help="Fetch + parse + JSON stdout, no job writes")
    p.add_argument("--log-format", default="text", choices=["text", "json"])
    return p


async def _run_cli(args: argparse.Namespace) -> int:
    """Returns exit code: 0=success, 1=partial, 2=failed, 3=dry_run."""
    if args.source != "ams":
        print(f"only 'ams' is wired, got {args.source!r}", file=sys.stderr)
        return 2

    query = JobQuery(
        keywords=args.query.split() if args.query else [],
        max_results=args.limit,
        since=datetime.fromisoformat(args.since) if args.since else None,
    )

    conn = connect()
    migrate(conn, MIGRATIONS_DIR)
    # runs.source is a foreign key to sources.name, so the source row has to
    # exist before a run can reference it.
    upsert_source(conn, args.source)
    run_id = start_run(conn, args.source)
    conn.commit()

    cookie_store = SessionCookieStore(SESSION_DIR / f"session_{args.source}.json")

    try:
        async with PlaywrightBrowserContext(cookie_store) as browser:
            adapter = AmsAdapter(browser=browser)
            results = await run(conn, [adapter], query, run_id=run_id,
                                dry_run=args.dry_run)
            cookie_store.save(await browser.cookies())
    except CrawlerError as e:
        conn.rollback()
        record_error(conn, run_id, stage=args.source, message=f"{type(e).__name__}: {e}")
        # 'failed' is a run_status enum member; 'dry_run' is not, which is why a
        # dry run finishes as 'success' below and signals itself via exit 3.
        finish_run(conn, run_id, status="failed", jobs_found=0, jobs_new=0)
        conn.commit()
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
        finish_run(conn, run_id, status="success",
                   jobs_found=counters["found"], jobs_new=0)
        conn.commit()
        print(json.dumps({
            "dry_run": True, "counters": counters,
            "results": [
                {"source": r.adapter_name, "status": r.status, "counters": r.counters}
                for r in results
            ],
        }))
        conn.close()
        return 3

    status = "partial" if any_error else "success"
    finish_run(conn, run_id, status=status,
               jobs_found=counters["found"], jobs_new=counters["inserted"])
    conn.commit()
    conn.close()
    if args.log_format == "json":
        print(json.dumps({"status": status, "counters": counters}))
    else:
        print(f"[{args.source}] status={status} counters={counters}")
    return 1 if any_error else 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(asyncio.run(_run_cli(args)))


if __name__ == "__main__":
    main()
