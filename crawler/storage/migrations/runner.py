"""PG migration runner.

Tracks applied versions in `schema_migrations`. Applies pending
V*.sql files in order. Idempotent — re-running is a no-op once
all migrations are applied.
"""
from __future__ import annotations

import re
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

VERSION_PATTERN = re.compile(r"^V(\d+)__(.+)\.sql$")


def _applied_versions(conn: psycopg.Connection) -> set[int]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT version FROM schema_migrations")
        return {row["version"] for row in cur.fetchall()}


def _ensure_migrations_table(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version     INTEGER PRIMARY KEY,
              applied_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
              description TEXT NOT NULL
            )
        """)
    conn.commit()


def _discover(migrations_dir: Path) -> list[tuple[int, str, Path]]:
    """Return [(version, description, path)] sorted by version."""
    out: list[tuple[int, str, Path]] = []
    for entry in sorted(migrations_dir.iterdir()):
        m = VERSION_PATTERN.match(entry.name)
        if m:
            out.append((int(m.group(1)), m.group(2), entry))
    return out


def migrate(conn: psycopg.Connection, migrations_dir: Path) -> list[int]:
    """Apply pending migrations. Returns list of applied versions."""
    _ensure_migrations_table(conn)
    applied = _applied_versions(conn)
    new: list[int] = []
    for version, description, path in _discover(migrations_dir):
        if version in applied:
            continue
        sql = path.read_text()
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                "INSERT INTO schema_migrations (version, description) VALUES (%s, %s)",
                (version, description),
            )
        conn.commit()
        new.append(version)
    return new