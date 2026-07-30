"""Tests for crawler.storage.migrations.runner (PG version)."""
from pathlib import Path

from crawler.storage.migrations import runner


def test_discover_finds_v001_initial(pg_migrated_template):
    # pg_migrated_template ensures migrate() ran against the migrations dir.
    # We can re-discover against the same dir to verify the helper.
    files = runner._discover(Path("crawler/storage/migrations"))
    versions = [(v, d) for v, d, _ in files]
    assert (1, "initial") in versions


def test_migrate_creates_tables(pg_conn):
    # pg_conn fixture already has tables cloned into the test schema.
    with pg_conn.cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = current_schema()
            ORDER BY table_name
        """)
        tables = {r["table_name"] for r in cur.fetchall()}
    expected = {"schema_migrations", "sources", "runs", "jobs", "run_errors"}
    assert expected <= tables


def test_migrate_records_version_metadata(pg_migrated_template):
    """The runner records applied versions into schema_migrations on the
    connection it migrated (the template DB)."""
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(pg_migrated_template, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT version, description FROM schema_migrations WHERE version=1"
            )
            row = cur.fetchone()
    assert row["version"] == 1
    assert "initial" in row["description"].lower()


def test_migrate_is_idempotent(pg_migrated_template):
    """Calling migrate() twice should be a no-op the second time."""
    import psycopg
    with psycopg.connect(pg_migrated_template) as conn:
        # First call already happened in fixture setup; second is the idempotent check.
        new = runner.migrate(conn, Path("crawler/storage/migrations"))
        conn.commit()
    assert new == []  # nothing new to apply


def test_migrate_returns_new_versions_on_first_run(pg_base_url):
    """Calling migrate() against a fresh template returns the applied version.

    Takes `pg_base_url` rather than hardcoding the connection string: that
    fixture is what skips when PostgreSQL is unreachable, so without it this was
    the one test in the suite that *failed* instead of skipping on a machine with
    no database running -- and it ignored DATABASE_URL besides.
    """
    import uuid

    import psycopg
    admin = pg_base_url.rsplit("/", 1)[0] + "/postgres"
    template = f"jobcrawler_tmpl_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(admin, autocommit=True) as c:
        with c.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{template}"')
    try:
        tmpl_url = pg_base_url.rsplit("/", 1)[0] + f"/{template}"
        with psycopg.connect(tmpl_url) as conn:
            applied = runner.migrate(conn, Path("crawler/storage/migrations"))
            conn.commit()
        assert applied == [1]
    finally:
        with psycopg.connect(admin, autocommit=True) as c:
            with c.cursor() as cur:
                cur.execute(
                    f"""SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                        WHERE datname = '{template}'"""
                )
                cur.execute(f'DROP DATABASE "{template}"')