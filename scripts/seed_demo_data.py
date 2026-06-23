"""Seed data/jobs.db with a handful of fake jobs and runs for dashboard demo.

Idempotent: if the jobs table already has rows, this is a no-op.

Usage:
    PYTHONPATH=. python scripts/seed_demo_data.py
    PYTHONPATH=. python scripts/seed_demo_data.py --force   # wipe jobs+runs+errors first
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from crawler import config
from crawler.models import NormalizedJob
from crawler.storage.db import connect
from crawler.storage.migrations.runner import apply as apply_migrations
from crawler.storage import repository


def _ts(offset_minutes: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=offset_minutes)).isoformat()


def seed(force: bool = False, db_path=None) -> None:
    path = db_path or config.DB_PATH
    conn = connect(path)
    try:
        apply_migrations(conn)

        existing = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        if existing > 0 and not force:
            print(f"jobs table already has {existing} rows; skipping (use --force to wipe)")
            return
        if force:
            conn.execute("DELETE FROM jobs")
            conn.execute("DELETE FROM crawl_runs")
            conn.execute("DELETE FROM crawl_errors")
            print("wiped jobs, crawl_runs, crawl_errors")

        now = datetime.now(timezone.utc)
        fetched_at = now
        fixtures = [
            NormalizedJob(
                source="ams",
                source_id="1001",
                url="https://jobs.ams.at/public/1001",
                title="Senior Software Engineer",
                company="ACME GmbH",
                location="Wien",
                description="Build distributed systems.",
                salary="€70k–€90k",
                employment_type="fulltime",
                posted_at=now - timedelta(days=2),
                content_hash="h_ams_1001",
                fetched_at=fetched_at,
                raw_html=None,
            ),
            NormalizedJob(
                source="ams",
                source_id="1002",
                url="https://jobs.ams.at/public/1002",
                title="Frontend Developer (React)",
                company="Linz AG",
                location="Wien",
                description="React + TypeScript role.",
                salary=None,
                employment_type="fulltime",
                posted_at=now - timedelta(days=5),
                content_hash="h_ams_1002",
                fetched_at=fetched_at,
                raw_html=None,
            ),
            NormalizedJob(
                source="ams",
                source_id="1003",
                url="https://jobs.ams.at/public/1003",
                title="Data Engineer",
                company="ACME GmbH",
                location="Graz",
                description="Airflow + dbt + Snowflake.",
                salary="€60k–€80k",
                employment_type="fulltime",
                posted_at=now - timedelta(days=1),
                content_hash="h_ams_1003",
                fetched_at=fetched_at,
                raw_html=None,
            ),
            NormalizedJob(
                source="ams",
                source_id="1004",
                url="https://jobs.ams.at/public/1004",
                title="DevOps Engineer",
                company="Salzburg IT",
                location="Salzburg",
                description="K8s, Terraform, AWS.",
                salary=None,
                employment_type="fulltime",
                posted_at=now - timedelta(days=7),
                content_hash="h_ams_1004",
                fetched_at=fetched_at,
                raw_html=None,
            ),
            NormalizedJob(
                source="ams",
                source_id="1005",
                url="https://jobs.ams.at/public/1005",
                title="Junior Python Developer",
                company="Wien Startup",
                location="Wien",
                description="Entry-level Python role.",
                salary="€38k–€45k",
                employment_type="fulltime",
                posted_at=now - timedelta(hours=12),
                content_hash="h_ams_1005",
                fetched_at=fetched_at,
                raw_html=None,
            ),
        ]

        for job in fixtures:
            repository.upsert_job(conn, job)
        print(f"inserted {len(fixtures)} jobs")

        # Two runs: one success, one partial
        run1 = repository.start_run(conn, "ams", "success")
        repository.finalize_run(
            conn,
            run1,
            "success",
            {"found": 5, "inserted": 5, "updated": 0, "errors": 0},
        )
        # Backdate run1
        conn.execute(
            "UPDATE crawl_runs SET started_at=?, finished_at=? WHERE id=?",
            (_ts(60), _ts(58), run1),
        )

        run2 = repository.start_run(conn, "ams", "partial")
        repository.finalize_run(
            conn,
            run2,
            "partial",
            {"found": 5, "inserted": 0, "updated": 5, "errors": 1},
        )
        conn.execute(
            "UPDATE crawl_runs SET started_at=?, finished_at=? WHERE id=?",
            (_ts(15), _ts(13), run2),
        )
        repository.log_error(
            conn,
            run2,
            "ams",
            "https://jobs.ams.at/public/9999",
            "captcha",
            "Hit captcha after 3 requests — backing off",
        )
        print("inserted 2 runs (1 success, 1 partial) + 1 error")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo data into the dev DB")
    parser.add_argument("--force", action="store_true", help="wipe existing rows first")
    parser.add_argument("--db", help="override DB path (default: data/jobs.db)")
    args = parser.parse_args()
    seed(force=args.force, db_path=args.db)


if __name__ == "__main__":
    main()
