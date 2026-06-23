"""Typed CRUD over jobs, runs, sources, errors (PostgreSQL).

All functions take a `psycopg.Connection`. Callers manage
transactions via `with conn.transaction():` blocks.
"""
from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from crawler.storage.dedup import content_hash


# ---------- sources ----------

def upsert_source(conn: psycopg.Connection, name: str, *, enabled: bool = True,
                  rate_limit_per_min: int = 30) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO sources (name, enabled, rate_limit_per_min)
            VALUES (%s, %s, %s)
            ON CONFLICT (name) DO UPDATE
              SET enabled = EXCLUDED.enabled,
                  rate_limit_per_min = EXCLUDED.rate_limit_per_min
        """, (name, enabled, rate_limit_per_min))


def get_source(conn: psycopg.Connection, name: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM sources WHERE name = %s", (name,))
        return cur.fetchone()


# ---------- runs ----------

def start_run(conn: psycopg.Connection, source: str) -> int:
    """Begin a run, return its id."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO runs (source, status) VALUES (%s, 'running') RETURNING id",
            (source,),
        )
        return cur.fetchone()["id"]


def finish_run(conn: psycopg.Connection, run_id: int, *,
               status: str, jobs_found: int, jobs_new: int) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE runs SET status = %s, ended_at = now(),
                            jobs_found = %s, jobs_new = %s
            WHERE id = %s
        """, (status, jobs_found, jobs_new, run_id))


def record_error(conn: psycopg.Connection, run_id: int, *,
                 stage: str, message: str, context: dict[str, Any] | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO run_errors (run_id, stage, message, context)
            VALUES (%s, %s, %s, %s)
        """, (run_id, stage, message, Jsonb(context) if context else None))


def list_runs(conn: psycopg.Connection, source: str | None = None,
              limit: int = 50) -> list[dict]:
    sql = "SELECT * FROM runs"
    args: tuple = ()
    if source:
        sql += " WHERE source = %s"
        args = (source,)
    sql += " ORDER BY started_at DESC LIMIT %s"
    args = args + (limit,)
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return list(cur.fetchall())


def get_run_errors(conn: psycopg.Connection, run_id: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM run_errors WHERE run_id = %s ORDER BY occurred_at DESC",
            (run_id,),
        )
        return list(cur.fetchall())


# ---------- jobs ----------

def upsert_job(conn: psycopg.Connection, *,
               source: str, source_id: str, url: str, title: str,
               company: str | None, location: str | None,
               description: str | None, raw_payload: dict | None = None) -> dict:
    """Insert or update a job. Returns row dict with `created: bool`."""
    h = content_hash(title, company, location)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO jobs (source, source_id, url, title, company, location,
                              description, content_hash, raw_payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, source_id) DO UPDATE
              SET url = EXCLUDED.url,
                  title = EXCLUDED.title,
                  company = EXCLUDED.company,
                  location = EXCLUDED.location,
                  description = EXCLUDED.description,
                  content_hash = EXCLUDED.content_hash,
                  last_seen_at = now(),
                  raw_payload = EXCLUDED.raw_payload
            RETURNING id, (xmax = 0) AS created, *
        """, (source, source_id, url, title, company, location, description, h,
              Jsonb(raw_payload) if raw_payload else None))
        row = cur.fetchone()
        return dict(row)


def get_by_hash(conn: psycopg.Connection, h: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM jobs WHERE content_hash = %s", (h,))
        return cur.fetchone()


def list_jobs(conn: psycopg.Connection, *,
              source: str | None = None, limit: int = 100,
              offset: int = 0) -> list[dict]:
    sql = "SELECT * FROM jobs"
    args: list = []
    if source:
        sql += " WHERE source = %s"
        args.append(source)
    sql += " ORDER BY last_seen_at DESC LIMIT %s OFFSET %s"
    args.extend([limit, offset])
    with conn.cursor() as cur:
        cur.execute(sql, tuple(args))
        return list(cur.fetchall())


def get_job(conn: psycopg.Connection, job_id: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
        return cur.fetchone()


# ---------- stats ----------

def get_stats(conn: psycopg.Connection) -> dict:
    """Stats for dashboard overview page."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM jobs")
        jobs_total = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM runs WHERE status = 'success'")
        runs_success = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM runs WHERE status = 'failed'")
        runs_failed = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM run_errors")
        errors_total = cur.fetchone()["n"]
        cur.execute("SELECT source, COUNT(*) AS n FROM jobs GROUP BY source")
        by_source = {row["source"]: row["n"] for row in cur.fetchall()}
        cur.execute("""
            SELECT date_trunc('day', last_seen_at)::date AS day, COUNT(*) AS n
            FROM jobs GROUP BY day ORDER BY day DESC LIMIT 7
        """)
        recent = list(cur.fetchall())
    return {
        "jobs_total": jobs_total,
        "runs_success": runs_success,
        "runs_failed": runs_failed,
        "errors_total": errors_total,
        "by_source": by_source,
        "recent_days": recent,
    }
