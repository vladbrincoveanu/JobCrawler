"""Smoke test: PG fixtures create + teardown schema cleanly."""


def test_pg_conn_sees_migrated_tables(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = current_schema()
            ORDER BY table_name
        """)
        tables = [r["table_name"] for r in cur.fetchall()]
    assert "jobs" in tables
    assert "runs" in tables
    assert "sources" in tables


def test_two_tests_get_isolated_schemas(pg_conn):
    # First test inserts a job
    with pg_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO jobs (source, source_id, url, title, content_hash) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("ams", "X1", "http://x", "Job A", "h1"),
        )
    pg_conn.commit()
    with pg_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM jobs")
        n = cur.fetchone()["n"]
    assert n == 1