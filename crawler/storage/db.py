"""PostgreSQL connection factory + connection pool.

Two entry points:
  - connect(): single connection, used by migration runner
  - get_pool(): psycopg_pool.ConnectionPool, used by app code

WAL/busy_timeout SQLite PRAGMAs gone — PG has MVCC + per-statement
timeouts. PRAGMAs here are PG session settings applied on connect.
"""
from __future__ import annotations

import os

import psycopg
from psycopg_pool import ConnectionPool

# Module-level pool, lazy-initialized.
_pool: ConnectionPool | None = None


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL not set. Copy .env.example to .env or set env var."
        )
    return url


def connect(url: str | None = None) -> psycopg.Connection:
    """Open a single PG connection (used by migration runner + tests)."""
    conn = psycopg.connect(
        url or _database_url(),
        autocommit=False,
        row_factory=psycopg.rows.dict_row,
    )
    # Session-level settings
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '30s'")
        cur.execute("SET application_name = 'jobcrawler'")
    conn.commit()
    return conn


def get_pool() -> ConnectionPool:
    """Lazy-init pool. Used by repository + app code."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=_database_url(),
            min_size=2,
            max_size=10,
            kwargs={"autocommit": False, "row_factory": psycopg.rows.dict_row},
            open=True,
        )
    return _pool


def close_pool() -> None:
    """For tests + atexit. Idempotent."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
