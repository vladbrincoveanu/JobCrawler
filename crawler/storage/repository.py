"""CRUD: jobs (upsert with dedup), crawl_runs, crawl_errors."""
from datetime import datetime, timezone
from typing import Literal
import sqlite3

from crawler.models import NormalizedJob


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_job(conn: sqlite3.Connection, job: NormalizedJob) -> Literal["inserted", "updated"]:
    """INSERT or UPDATE on (source, source_id). Returns action.

    Uses INSERT OR IGNORE + UPDATE fallback because SQLite lacks the
    PostgreSQL `xmax = 0` RETURNING trick.
    """
    now = _now()
    raw_html = job.raw_html
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO jobs (source, source_id, url, title, company, location,
                                    description, salary, employment_type, posted_at,
                                    content_hash, raw_html, first_seen_at, last_seen_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            job.source, job.source_id, str(job.url), job.title, job.company, job.location,
            job.description, job.salary, job.employment_type,
            job.posted_at.isoformat() if job.posted_at else None,
            job.content_hash, raw_html, now, now,
        ),
    )
    if cur.rowcount == 1:
        return "inserted"
    conn.execute(
        """
        UPDATE jobs SET
          title=?,
          description=?,
          salary=?,
          employment_type=?,
          posted_at=?,
          content_hash=?,
          raw_html=COALESCE(?, raw_html),
          last_seen_at=?
        WHERE source=? AND source_id=?
        """,
        (
            job.title, job.description, job.salary, job.employment_type,
            job.posted_at.isoformat() if job.posted_at else None,
            job.content_hash, raw_html, now,
            job.source, job.source_id,
        ),
    )
    return "updated"


def get_by_hash(conn: sqlite3.Connection, hash_val: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM jobs WHERE content_hash = ? LIMIT 1", (hash_val,)
    ).fetchone()


def list_jobs(conn: sqlite3.Connection, limit: int = 100, source: str | None = None) -> list[sqlite3.Row]:
    if source:
        return conn.execute(
            "SELECT * FROM jobs WHERE source = ? ORDER BY last_seen_at DESC LIMIT ?",
            (source, limit),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM jobs ORDER BY last_seen_at DESC LIMIT ?", (limit,)
    ).fetchall()


def start_run(conn: sqlite3.Connection, source: str, status: str = "running") -> int:
    cur = conn.execute(
        "INSERT INTO crawl_runs (source, started_at, status) VALUES (?, ?, ?)",
        (source, _now(), status),
    )
    return cur.lastrowid


def finalize_run(
    conn: sqlite3.Connection,
    run_id: int,
    status: str,
    counters: dict[str, int],
) -> None:
    conn.execute(
        """
        UPDATE crawl_runs
        SET finished_at=?, status=?,
            jobs_found=?, jobs_inserted=?, jobs_updated=?, errors_count=?
        WHERE id=?
        """,
        (
            _now(), status,
            counters.get("found", 0),
            counters.get("inserted", 0),
            counters.get("updated", 0),
            counters.get("errors", 0),
            run_id,
        ),
    )


def log_error(
    conn: sqlite3.Connection,
    run_id: int,
    source: str,
    url: str | None,
    error_type: str,
    error_message: str,
) -> None:
    conn.execute(
        """
        INSERT INTO crawl_errors (run_id, source, url, error_type, error_message, occurred_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (run_id, source, url, error_type, error_message, _now()),
    )