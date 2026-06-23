from datetime import datetime, timezone
import pytest
from crawler.storage.db import connect
from crawler.storage.migrations.runner import apply as apply_migrations
from crawler.storage.repository import (
    start_run, finalize_run, log_error, upsert_job, get_by_hash, list_jobs,
)
from crawler.models import NormalizedJob


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "r.db")
    apply_migrations(c)
    return c


def _job(source_id: str, title: str = "SWE", company: str = "ACME",
         location: str = "Wien", hash_val: str = "h1") -> NormalizedJob:
    return NormalizedJob(
        source="ams", source_id=source_id,
        url=f"https://jobs.ams.at/public/jobs/{source_id}",
        title=title, company=company, location=location,
        description="d", content_hash=hash_val,
        fetched_at=datetime.now(timezone.utc),
    )


def test_upsert_inserts_new(conn):
    action = upsert_job(conn, _job("1"))
    assert action == "inserted"
    rows = conn.execute("SELECT id, source, source_id FROM jobs").fetchall()
    assert len(rows) == 1
    assert rows[0]["source_id"] == "1"


def test_upsert_updates_existing(conn):
    upsert_job(conn, _job("1", title="Old"))
    action = upsert_job(conn, _job("1", title="New"))
    assert action == "updated"
    rows = conn.execute("SELECT title FROM jobs WHERE source_id='1'").fetchall()
    assert rows[0]["title"] == "New"


def test_upsert_updates_last_seen(conn):
    upsert_job(conn, _job("1"))
    first_seen = conn.execute("SELECT first_seen_at FROM jobs WHERE source_id='1'").fetchone()["first_seen_at"]
    upsert_job(conn, _job("1"))
    row = conn.execute("SELECT first_seen_at, last_seen_at FROM jobs WHERE source_id='1'").fetchone()
    assert row["first_seen_at"] == first_seen
    assert row["last_seen_at"] >= first_seen


def test_upsert_writes_raw_html(conn):
    j = _job("1")
    j.raw_html = "<html>test</html>"
    upsert_job(conn, j)
    row = conn.execute("SELECT raw_html FROM jobs WHERE source_id='1'").fetchone()
    assert row["raw_html"] == "<html>test</html>"


def test_get_by_hash(conn):
    upsert_job(conn, _job("1", hash_val="deadbeef"))
    found = get_by_hash(conn, "deadbeef")
    assert found is not None
    assert found["source_id"] == "1"


def test_get_by_hash_missing(conn):
    assert get_by_hash(conn, "nope") is None


def test_list_jobs(conn):
    for i in range(3):
        upsert_job(conn, _job(str(i)))
    jobs = list_jobs(conn, limit=10)
    assert len(jobs) == 3


def test_start_run_returns_id(conn):
    run_id = start_run(conn, source="ams")
    assert isinstance(run_id, int)
    row = conn.execute("SELECT status FROM crawl_runs WHERE id=?", (run_id,)).fetchone()
    assert row["status"] == "running"


def test_finalize_run_updates_counters(conn):
    run_id = start_run(conn, source="ams")
    finalize_run(conn, run_id, status="success", counters={"inserted": 5, "updated": 2, "errors": 0})
    row = conn.execute("SELECT * FROM crawl_runs WHERE id=?", (run_id,)).fetchone()
    assert row["status"] == "success"
    assert row["jobs_inserted"] == 5
    assert row["jobs_updated"] == 2
    assert row["errors_count"] == 0
    assert row["finished_at"] is not None


def test_log_error_persists(conn):
    run_id = start_run(conn, source="ams")
    log_error(conn, run_id, "ams", "https://x.at/1", "CaptchaEncountered", "captcha")
    rows = conn.execute("SELECT * FROM crawl_errors WHERE run_id=?", (run_id,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["error_type"] == "CaptchaEncountered"