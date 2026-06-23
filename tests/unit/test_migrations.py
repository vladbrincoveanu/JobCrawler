import sqlite3
from pathlib import Path
from crawler.storage.db import connect
from crawler.storage.migrations.runner import apply, _list_migration_files


def test_list_migration_files():
    files = _list_migration_files()
    assert any("V001__initial.sql" in str(f) for f in files)


def test_apply_creates_tables(tmp_path: Path):
    conn = connect(tmp_path / "m.db")
    apply(conn)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert {"schema_version", "sources", "jobs", "crawl_runs", "crawl_errors"} <= tables


def test_apply_is_idempotent(tmp_path: Path):
    conn = connect(tmp_path / "m.db")
    apply(conn)
    apply(conn)  # second run should not error
    rows = conn.execute("SELECT version FROM schema_version").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 1


def test_apply_records_version_metadata(tmp_path: Path):
    conn = connect(tmp_path / "m.db")
    apply(conn)
    row = conn.execute(
        "SELECT version, description FROM schema_version WHERE version=1"
    ).fetchone()
    assert row[0] == 1
    assert "initial" in row[1].lower()
