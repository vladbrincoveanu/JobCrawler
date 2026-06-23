"""Pytest fixtures for ephemeral PG schema per test.

Session-scoped: ensure PG is up, run migrations into template schema.
Function-scoped: per-test schema with UUID suffix for isolation.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from crawler.storage.migrations.runner import migrate


PG_BASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://jobcrawler:dev@localhost:5433/jobcrawler"
)


@pytest.fixture(scope="session")
def pg_base_url() -> str:
    """Verify PG is reachable. Skip entire suite if not."""
    try:
        with psycopg.connect(PG_BASE_URL, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    except Exception as e:
        pytest.skip(f"PostgreSQL not reachable at {PG_BASE_URL}: {e}")
    return PG_BASE_URL


@pytest.fixture(scope="session")
def pg_migrated_template(pg_base_url: str) -> str:
    """Create a template DB with migrations applied. Tests clone this per-test."""
    template_name = f"jobcrawler_template_{uuid.uuid4().hex[:8]}"
    admin_url = pg_base_url.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        with admin.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{template_name}"')
    template_url = pg_base_url.rsplit("/", 1)[0] + f"/{template_name}"
    with psycopg.connect(template_url) as conn:
        migrate(conn, Path("crawler/storage/migrations"))
        conn.commit()
    yield template_url
    # Teardown
    with psycopg.connect(admin_url, autocommit=True) as admin:
        with admin.cursor() as cur:
            cur.execute(
                f'REVOKE CONNECT ON DATABASE "{template_name}" FROM PUBLIC'
            )
            cur.execute(
                f"""SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                    WHERE datname = '{template_name}'"""
            )
            cur.execute(f'DROP DATABASE "{template_name}"')


@pytest.fixture
def pg_schema(pg_migrated_template: str) -> str:
    """Yield a fresh schema (per-test isolation). Tables from public are
    cloned into the test schema so FK relationships resolve within the
    same schema, then dropped on teardown."""
    schema = f"test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(pg_migrated_template, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}"')
            # Clone tables from public → test schema (preserves structure + FKs)
            cur.execute(f"""
                DO $$
                DECLARE r record;
                BEGIN
                  FOR r IN
                    SELECT tablename FROM pg_tables WHERE schemaname='public'
                  LOOP
                    EXECUTE format(
                      'CREATE TABLE %I.%I (LIKE public.%I INCLUDING ALL)',
                      '{schema}', r.tablename, r.tablename
                    );
                  END LOOP;
                END $$;
            """)
    yield schema
    with psycopg.connect(pg_migrated_template, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.fixture
def pg_url(pg_migrated_template: str, pg_schema: str) -> str:
    """DATABASE_URL pointing at template DB with search_path set to test schema."""
    sep = "&" if "?" in pg_migrated_template else "?"
    return f"{pg_migrated_template}{sep}options=-c%20search_path%3D{pg_schema}"


@pytest.fixture
def pg_conn(pg_url: str):
    """Yield a PG connection with search_path set to test schema, dict rows."""
    conn = psycopg.connect(
        pg_url, autocommit=False, row_factory=psycopg.rows.dict_row
    )
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def pg_pool(pg_url: str):
    """Yield a connection pool for tests that exercise pool semantics."""
    pool = ConnectionPool(
        conninfo=pg_url, min_size=1, max_size=2,
        kwargs={"row_factory": psycopg.rows.dict_row},
        open=True,
    )
    try:
        yield pool
    finally:
        pool.close()