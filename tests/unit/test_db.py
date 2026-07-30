"""Tests for crawler.storage.db (PG connection factory + pool)."""
import psycopg
import psycopg_pool

from crawler.storage.db import close_pool, connect, get_pool


def test_connect_returns_psycopg_connection(pg_url):
    conn = connect(pg_url)
    try:
        assert isinstance(conn, psycopg.Connection)
        # dict_row factory is applied → fetchone returns dict
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS x")
            row = cur.fetchone()
        assert row == {"x": 1}
    finally:
        conn.close()


def test_connect_applies_statement_timeout(pg_url):
    conn = connect(pg_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW statement_timeout")
            row = cur.fetchone()
        # 30s set by db.connect()
        assert row["statement_timeout"] == "30s"
    finally:
        conn.close()


def test_connect_sets_application_name(pg_url):
    conn = connect(pg_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW application_name")
            row = cur.fetchone()
        assert row["application_name"] == "jobcrawler"
    finally:
        conn.close()


def test_get_pool_returns_connection_pool(pg_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    close_pool()  # reset any prior state
    try:
        pool = get_pool()
        assert isinstance(pool, psycopg_pool.ConnectionPool)
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 42 AS n")
                row = cur.fetchone()
            assert row["n"] == 42
    finally:
        close_pool()


def test_get_pool_is_singleton(monkeypatch, pg_url):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    close_pool()
    try:
        a = get_pool()
        b = get_pool()
        assert a is b
    finally:
        close_pool()


def test_close_pool_resets_singleton(monkeypatch, pg_url):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    close_pool()
    p1 = get_pool()
    close_pool()
    p2 = get_pool()
    assert p1 is not p2
    close_pool()