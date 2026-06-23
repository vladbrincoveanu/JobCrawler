"""Debug: counts, schema, sample rows."""
import sys
from crawler import config
from crawler.storage.db import connect
from crawler.storage.migrations.runner import apply as apply_migrations


def main() -> None:
    conn = connect(config.DB_PATH)
    apply_migrations(conn)

    counts = {}
    for table in ("jobs", "crawl_runs", "crawl_errors", "sources"):
        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    print("=== Counts ===")
    for t, n in counts.items():
        print(f"  {t}: {n}")

    print("\n=== Last 5 runs ===")
    for r in conn.execute(
        "SELECT id, source, status, jobs_inserted, jobs_updated, errors_count, started_at FROM crawl_runs ORDER BY id DESC LIMIT 5"
    ).fetchall():
        print(f"  #{r['id']} {r['source']} {r['status']} +{r['jobs_inserted']}/{r['jobs_updated']} err={r['errors_count']} @ {r['started_at']}")

    print("\n=== Last 5 errors ===")
    for e in conn.execute(
        "SELECT source, error_type, error_message, occurred_at FROM crawl_errors ORDER BY id DESC LIMIT 5"
    ).fetchall():
        print(f"  [{e['source']}] {e['error_type']}: {e['error_message']} @ {e['occurred_at']}")

    print("\n=== 5 sample jobs ===")
    for j in conn.execute(
        "SELECT source, source_id, title, company, location FROM jobs ORDER BY id DESC LIMIT 5"
    ).fetchall():
        print(f"  [{j['source']}] {j['title']} @ {j['company']} ({j['location']})")

    conn.close()


if __name__ == "__main__":
    main()