"""Schema migration runner. Spec § Storage Schema + grill-me amendment 2.

Scans crawler/storage/migrations/V*.sql, applies unapplied versions in order.
Idempotent — safe to run on every startup.
"""
import re
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from crawler.exceptions import MigrationError

MIGRATIONS_DIR = Path(__file__).parent
VERSION_PATTERN = re.compile(r"^V(\d+)__(.+)\.sql$")


def _list_migration_files() -> list[Path]:
    """Return V*.sql files in this dir, sorted by version number."""
    files = []
    for path in MIGRATIONS_DIR.glob("V*.sql"):
        m = VERSION_PATTERN.match(path.name)
        if m:
            files.append((int(m.group(1)), path))
    return [p for _, p in sorted(files)]


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    """Return versions already in schema_version table."""
    try:
        rows = conn.execute("SELECT version FROM schema_version").fetchall()
        return {r[0] for r in rows}
    except sqlite3.OperationalError:
        # schema_version doesn't exist yet → nothing applied
        return set()


def apply(conn: sqlite3.Connection) -> None:
    """Apply pending migrations. Idempotent."""
    applied = _applied_versions(conn)
    for path in _list_migration_files():
        m = VERSION_PATTERN.match(path.name)
        if not m:
            continue
        version = int(m.group(1))
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        try:
            conn.executescript(sql)
        except sqlite3.Error as e:
            raise MigrationError(f"V{version} ({path.name}) failed: {e}") from e
        # Record the version (executescript may have created schema_version
        # via this migration, so this insert comes after the script)
        conn.execute(
            "INSERT INTO schema_version (version, applied_at, description) VALUES (?, ?, ?)",
            (version, datetime.now(timezone.utc).isoformat(), m.group(2).replace("_", " ")),
        )
