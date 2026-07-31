"""Debug: counts, last runs, last errors, sample rows.

    DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler \
      python scripts/inspect_db.py

Every identifier in this script used to be wrong. It imported a `runner.apply`
that does not exist (the function is `migrate`), passed `config.DB_PATH` (removed
in the PostgreSQL migration), and queried tables `crawl_runs` / `crawl_errors`
with columns `jobs_inserted`, `jobs_updated`, `errors_count`, `error_type` and
`error_message` -- none of which the schema has. The real names are `runs` /
`run_errors` with `jobs_found`, `jobs_new`, `stage` and `message`
(crawler/storage/migrations/V001__initial.sql).
"""
from pathlib import Path

from crawler.storage.db import connect
from crawler.storage.migrations.runner import migrate

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "crawler" / "storage" / "migrations"


def main() -> None:
    conn = connect()
    migrate(conn, MIGRATIONS_DIR)

    with conn.cursor() as cur:
        print("=== Counts ===")
        for table in ("jobs", "runs", "run_errors", "sources"):
            cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
            print(f"  {table}: {cur.fetchone()['n']}")

        print("\n=== Last 5 runs ===")
        cur.execute("""
            SELECT id, source, status, jobs_found, jobs_new, started_at
            FROM runs ORDER BY id DESC LIMIT 5
        """)
        for r in cur.fetchall():
            print(f"  #{r['id']} {r['source']} {r['status']} "
                  f"found={r['jobs_found']} new={r['jobs_new']} @ {r['started_at']}")

        print("\n=== Last 5 errors ===")
        cur.execute("""
            SELECT run_id, stage, message, occurred_at
            FROM run_errors ORDER BY id DESC LIMIT 5
        """)
        for e in cur.fetchall():
            print(f"  run#{e['run_id']} [{e['stage']}] {e['message']} @ {e['occurred_at']}")

        print("\n=== 5 sample jobs ===")
        cur.execute("""
            SELECT source, source_id, title, company, location
            FROM jobs ORDER BY id DESC LIMIT 5
        """)
        for j in cur.fetchall():
            print(f"  [{j['source']}] {j['title']} @ {j['company']} ({j['location']})")

    conn.close()


if __name__ == "__main__":
    main()
