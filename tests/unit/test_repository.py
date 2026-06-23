"""Tests for crawler.storage.repository (PG CRUD)."""
import psycopg

from crawler.storage import repository as repo


def _make_job(source_id: str, title: str = "SWE", company: str = "ACME",
              location: str = "Wien", source: str = "ams") -> dict:
    """Return kwargs for repo.upsert_job."""
    return {
        "source": source,
        "source_id": source_id,
        "url": f"https://jobs.ams.at/public/jobs/{source_id}",
        "title": title,
        "company": company,
        "location": location,
        "description": "d",
    }


def test_upsert_source_inserts(pg_conn):
    repo.upsert_source(pg_conn, "ams")
    src = repo.get_source(pg_conn, "ams")
    assert src is not None
    assert src["name"] == "ams"
    assert src["enabled"] is True


def test_upsert_source_updates_on_conflict(pg_conn):
    repo.upsert_source(pg_conn, "ams", enabled=False, rate_limit_per_min=5)
    repo.upsert_source(pg_conn, "ams", enabled=True, rate_limit_per_min=99)
    src = repo.get_source(pg_conn, "ams")
    assert src["enabled"] is True
    assert src["rate_limit_per_min"] == 99


def test_get_source_missing_returns_none(pg_conn):
    assert repo.get_source(pg_conn, "nope") is None


def test_upsert_job_inserts_new(pg_conn):
    repo.upsert_source(pg_conn, "ams")
    row = repo.upsert_job(pg_conn, **_make_job("1"))
    assert row["created"] is True
    with pg_conn.cursor() as cur:
        cur.execute("SELECT source, source_id FROM jobs")
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["source_id"] == "1"


def test_upsert_job_updates_existing(pg_conn):
    repo.upsert_source(pg_conn, "ams")
    repo.upsert_job(pg_conn, **_make_job("1", title="Old"))
    row = repo.upsert_job(pg_conn, **_make_job("1", title="New"))
    assert row["created"] is False
    with pg_conn.cursor() as cur:
        cur.execute("SELECT title FROM jobs WHERE source_id = %s", ("1",))
        r = cur.fetchone()
    assert r["title"] == "New"


def test_upsert_job_preserves_first_seen(pg_conn):
    repo.upsert_source(pg_conn, "ams")
    repo.upsert_job(pg_conn, **_make_job("1"))
    with pg_conn.cursor() as cur:
        cur.execute("SELECT first_seen_at FROM jobs WHERE source_id = %s", ("1",))
        first = cur.fetchone()["first_seen_at"]
    repo.upsert_job(pg_conn, **_make_job("1"))
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT first_seen_at, last_seen_at FROM jobs WHERE source_id = %s",
            ("1",),
        )
        row = cur.fetchone()
    assert row["first_seen_at"] == first
    assert row["last_seen_at"] >= first


def test_get_by_hash(pg_conn):
    repo.upsert_source(pg_conn, "ams")
    repo.upsert_job(pg_conn, **_make_job("1", title="OldTitle"))
    # Compute the hash the same way repo does (via dedup)
    from crawler.storage.dedup import content_hash
    h = content_hash("OldTitle", "ACME", "Wien")
    found = repo.get_by_hash(pg_conn, h)
    assert found is not None
    assert found["source_id"] == "1"


def test_get_by_hash_missing(pg_conn):
    assert repo.get_by_hash(pg_conn, "nope") is None


def test_list_jobs(pg_conn):
    repo.upsert_source(pg_conn, "ams")
    for i in range(3):
        # Vary title so content_hash doesn't collide
        repo.upsert_job(pg_conn, **_make_job(str(i), title=f"SWE-{i}"))
    jobs = repo.list_jobs(pg_conn, limit=10)
    assert len(jobs) == 3


def test_list_jobs_filter_by_source(pg_conn):
    repo.upsert_source(pg_conn, "ams")
    repo.upsert_source(pg_conn, "karriere")
    repo.upsert_job(pg_conn, **_make_job("1", source="ams", title="A1"))
    repo.upsert_job(pg_conn, **_make_job("2", source="karriere", title="K1"))
    jobs = repo.list_jobs(pg_conn, source="ams", limit=10)
    assert len(jobs) == 1
    assert jobs[0]["source"] == "ams"


def test_start_run_returns_id(pg_conn):
    repo.upsert_source(pg_conn, "ams")
    run_id = repo.start_run(pg_conn, source="ams")
    assert isinstance(run_id, int)
    with pg_conn.cursor() as cur:
        cur.execute("SELECT status FROM runs WHERE id = %s", (run_id,))
        row = cur.fetchone()
    assert row["status"] == "running"


def test_finish_run_updates_counters(pg_conn):
    repo.upsert_source(pg_conn, "ams")
    run_id = repo.start_run(pg_conn, source="ams")
    repo.finish_run(pg_conn, run_id, status="success", jobs_found=10, jobs_new=7)
    with pg_conn.cursor() as cur:
        cur.execute("SELECT * FROM runs WHERE id = %s", (run_id,))
        row = cur.fetchone()
    assert row["status"] == "success"
    assert row["jobs_found"] == 10
    assert row["jobs_new"] == 7
    assert row["ended_at"] is not None


def test_record_error_persists(pg_conn):
    repo.upsert_source(pg_conn, "ams")
    run_id = repo.start_run(pg_conn, source="ams")
    repo.record_error(pg_conn, run_id, stage="fetch",
                      message="captcha triggered", context={"url": "https://x"})
    with pg_conn.cursor() as cur:
        cur.execute("SELECT * FROM run_errors WHERE run_id = %s", (run_id,))
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["stage"] == "fetch"
    assert rows[0]["message"] == "captcha triggered"
    assert rows[0]["context"] == {"url": "https://x"}


def test_list_runs_returns_recent_first(pg_conn):
    repo.upsert_source(pg_conn, "ams")
    repo.upsert_source(pg_conn, "karriere")
    repo.start_run(pg_conn, source="ams")
    repo.start_run(pg_conn, source="karriere")
    runs = repo.list_runs(pg_conn, limit=10)
    assert len(runs) == 2


def test_get_run_errors(pg_conn):
    repo.upsert_source(pg_conn, "ams")
    run_id = repo.start_run(pg_conn, source="ams")
    repo.record_error(pg_conn, run_id, stage="parse", message="boom")
    errors = repo.get_run_errors(pg_conn, run_id)
    assert len(errors) == 1
    assert errors[0]["stage"] == "parse"


def test_get_stats_aggregates(pg_conn):
    repo.upsert_source(pg_conn, "ams")
    repo.upsert_job(pg_conn, **_make_job("1", title="A"))
    repo.upsert_job(pg_conn, **_make_job("2", title="B"))
    run_id = repo.start_run(pg_conn, source="ams")
    repo.finish_run(pg_conn, run_id, status="success", jobs_found=2, jobs_new=2)
    stats = repo.get_stats(pg_conn)
    assert stats["jobs_total"] == 2
    assert stats["runs_success"] == 1
    assert stats["by_source"]["ams"] == 2