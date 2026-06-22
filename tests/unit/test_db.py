import sqlite3
from pathlib import Path
import pytest
from crawler.storage import db


def test_connect_returns_connection():
    conn = db.connect(":memory:")
    assert isinstance(conn, sqlite3.Connection)


def test_wal_mode_applied(tmp_path: Path):
    db_path = tmp_path / "test.db"
    conn = db.connect(db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    # :memory: returns "memory"; file-backed returns "wal"
    if db_path.exists():
        assert mode == "wal"


def test_pragmas_set(tmp_path: Path):
    db_path = tmp_path / "test.db"
    conn = db.connect(db_path)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30_000


def test_connect_yields_independent_connections(tmp_path: Path):
    db_path = tmp_path / "test.db"
    c1 = db.connect(db_path)
    c2 = db.connect(db_path)
    c1.execute("CREATE TABLE t (x INT)")
    c1.execute("INSERT INTO t VALUES (1)")
    c1.commit()
    rows = c2.execute("SELECT x FROM t").fetchall()
    assert [tuple(r) for r in rows] == [(1,)]