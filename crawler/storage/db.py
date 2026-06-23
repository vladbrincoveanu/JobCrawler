"""SQLite connection factory with WAL + busy_timeout PRAGMAs."""
from pathlib import Path
import sqlite3
from crawler import config


def connect(path: str | Path) -> sqlite3.Connection:
    """Open SQLite connection with PRAGMAs. Path can be ':memory:' for tests."""
    conn = sqlite3.connect(
        path,
        timeout=config.DB_BUSY_TIMEOUT_SECONDS,
        isolation_level=None,  # autocommit; explicit BEGIN in repository
    )
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={config.DB_BUSY_TIMEOUT_SECONDS * 1000}")
    conn.row_factory = sqlite3.Row
    return conn