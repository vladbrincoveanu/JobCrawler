"""Seed PG with demo data for dashboard demo.

Idempotent: if jobs table already has rows for ams source, this is a no-op
unless --force is passed.

Usage:
    DATABASE_URL=postgresql://... python scripts/seed_demo_data.py
    DATABASE_URL=... python scripts/seed_demo_data.py --force
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.rows import dict_row

from crawler.storage import repository as repo


def _ts(offset_minutes: int = 0) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=offset_minutes)


JOBS = [
    dict(source="ams", source_id="DEMO-1",
         url="https://jobs.ams.at/public/DEMO-1",
         title="Senior Backend Engineer (Python)",
         company="DemoCo", location="Wien",
         description="Build crawlers + storage layers with PostgreSQL."),
    dict(source="ams", source_id="DEMO-2",
         url="https://jobs.ams.at/public/DEMO-2",
         title="Frontend Developer (React/Next.js)",
         company="DemoCo", location="Wien",
         description="Dashboard UI work."),
    dict(source="ams", source_id="DEMO-3",
         url="https://jobs.ams.at/public/DEMO-3",
         title="Data Engineer",
         company="DataCorp", location="Graz",
         description="ETL pipelines, PostgreSQL tuning."),
    dict(source="ams", source_id="DEMO-4",
         url="https://jobs.ams.at/public/DEMO-4",
         title="DevOps Engineer",
         company="CloudOps", location="Linz",
         description="K8s, Terraform, PG operators."),
    dict(source="ams", source_id="DEMO-5",
         url="https://jobs.ams.at/public/DEMO-5",
         title="ML Engineer",
         company="AIStartup", location="Wien",
         description="pgvector + LLM integration."),
]


def seed(database_url: str, force: bool = False) -> None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        repo.upsert_source(conn, "ams")
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM jobs WHERE source = 'ams'")
            n = cur.fetchone()["n"]
        if n > 0 and not force:
            print(f"Already seeded ({n} jobs for ams); skipping. Use --force to wipe.")
            return
        if force:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM run_errors")
                cur.execute("DELETE FROM runs")
                cur.execute("DELETE FROM jobs WHERE source = 'ams'")
        for j in JOBS:
            repo.upsert_job(conn, **j)
        run1 = repo.start_run(conn, "ams")
        repo.finish_run(conn, run1, status="success",
                         jobs_found=len(JOBS), jobs_new=len(JOBS))
        run2 = repo.start_run(conn, "ams")
        repo.record_error(
            conn, run2, stage="parse",
            message="Failed to parse one listing",
            context={"url": "https://jobs.ams.at/public/DEMO-X"},
        )
        repo.finish_run(conn, run2, status="partial",
                         jobs_found=len(JOBS), jobs_new=0)
        conn.commit()
    print(f"Seeded {len(JOBS)} jobs + 2 runs + 1 error.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not args.database_url:
        print("ERROR: --database-url or DATABASE_URL required", file=sys.stderr)
        return 2
    seed(args.database_url, force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
