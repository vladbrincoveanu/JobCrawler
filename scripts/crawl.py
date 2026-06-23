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