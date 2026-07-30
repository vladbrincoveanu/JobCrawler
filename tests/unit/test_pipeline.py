"""Tests for crawler.pipeline (PG-backed run_source / run)."""
from datetime import datetime, timezone

import pytest

from crawler.exceptions import CaptchaEncountered, SchemaChanged
from crawler.models import JobQuery, NormalizedJob, RawJob
from crawler.pipeline import run, run_source
from crawler.storage import repository as repo


class StubAdapter:
    """Minimal async source adapter for pipeline tests."""

    def __init__(self, name="stub", jobs=None, fail_with=None):
        self.name = name
        self._jobs = jobs or []
        self._fail = fail_with

    async def search(self, query):
        if self._fail:
            raise self._fail
        for j in self._jobs:
            yield j

    async def fetch_detail(self, raw):
        return NormalizedJob(
            source=raw.source, source_id=raw.source_id, url=str(raw.url),
            title=raw.title, company=raw.company or "ACME", location=raw.location or "Wien",
            description="d", content_hash=f"hash-{raw.source_id}",
            fetched_at=raw.fetched_at,
        )


def _raw(source_id: str, title: str = "SWE", source: str = "stub",
         location: str = "Wien", company: str = "ACME") -> RawJob:
    return RawJob(
        source=source, source_id=source_id,
        url=f"https://x/{source_id}", title=title,
        company=company, location=location,
        fetched_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_run_source_success(pg_conn):
    repo.upsert_source(pg_conn, "stub")
    raw = _raw("1", title="A")
    adapter = StubAdapter(jobs=[raw])
    run_id = repo.start_run(pg_conn, source="stub")
    result = await run_source(pg_conn, adapter, JobQuery(), run_id=run_id)
    assert result.status == "success"
    assert result.counters["inserted"] == 1


@pytest.mark.asyncio
async def test_run_source_partial_on_per_job_error(pg_conn):
    repo.upsert_source(pg_conn, "stub")
    raw1 = _raw("1", title="A")
    raw2 = _raw("2", title="B")
    adapter = StubAdapter(jobs=[raw1, raw2])
    run_id = repo.start_run(pg_conn, source="stub")

    original = adapter.fetch_detail
    calls = [0]

    async def flaky(raw):
        calls[0] += 1
        if calls[0] == 1:
            raise SchemaChanged("broken")
        return await original(raw)

    adapter.fetch_detail = flaky
    result = await run_source(pg_conn, adapter, JobQuery(), run_id=run_id)
    assert result.status == "partial"
    assert result.counters["inserted"] == 1
    assert result.counters["errors"] == 1


@pytest.mark.asyncio
async def test_run_source_circuit_break_on_captcha(pg_conn):
    repo.upsert_source(pg_conn, "stub")
    adapter = StubAdapter(fail_with=CaptchaEncountered("captcha"))
    run_id = repo.start_run(pg_conn, source="stub")
    result = await run_source(pg_conn, adapter, JobQuery(), run_id=run_id)
    assert result.status == "failed"
    assert "CaptchaEncountered" in str(result.error)


@pytest.mark.asyncio
async def test_run_aggregates_multiple_sources(pg_conn):
    repo.upsert_source(pg_conn, "a")
    repo.upsert_source(pg_conn, "b")
    raw1 = _raw("1", title="A", source="a")
    raw2 = _raw("2", title="B", source="b")
    a = StubAdapter(name="a", jobs=[raw1])
    b = StubAdapter(name="b", jobs=[raw2])
    run_id = repo.start_run(pg_conn, source="multi")
    results = await run(pg_conn, [a, b], JobQuery(), run_id=run_id)
    statuses = {r.adapter_name: r.status for r in results}
    assert statuses == {"a": "success", "b": "success"}


@pytest.mark.asyncio
async def test_dry_run_skips_upsert(pg_conn):
    repo.upsert_source(pg_conn, "stub")
    raw = _raw("1", title="A")
    adapter = StubAdapter(jobs=[raw])
    run_id = repo.start_run(pg_conn, source="stub")
    result = await run_source(pg_conn, adapter, JobQuery(), run_id=run_id, dry_run=True)
    assert result.status == "success"
    assert result.counters["inserted"] == 1  # counted
    with pg_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM jobs")
        n = cur.fetchone()["n"]
    assert n == 0  # not written