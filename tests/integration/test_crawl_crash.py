"""Integration: source raises unexpected exception → status=crashed, run continues, error logged."""
from datetime import datetime, timezone

import pytest

from crawler.models import JobQuery, RawJob, NormalizedJob
from crawler.storage import repository as repo
from crawler.pipeline import run


class CrashingAdapter:
    name = "crash"

    async def search(self, query):
        raise RuntimeError("boom")
        yield  # makes this an async generator (unreachable, but required for type)

    async def fetch_detail(self, raw):
        raise NotImplementedError


class GoodAdapter:
    name = "good"

    async def search(self, query):
        raw = RawJob(
            source="good", source_id="1", url="https://x/1",
            title="SWE", company="ACME", location="Wien",
            fetched_at=datetime.now(timezone.utc),
        )
        yield raw

    async def fetch_detail(self, raw):
        return NormalizedJob(
            source=raw.source, source_id=raw.source_id, url=str(raw.url),
            title=raw.title, company=raw.company, location=raw.location,
            description="d", content_hash="h1", fetched_at=raw.fetched_at,
        )


@pytest.mark.asyncio
async def test_crash_isolated_per_source(pg_conn):
    repo.upsert_source(pg_conn, "good")
    run_id = repo.start_run(pg_conn, source="multi")

    results = await run(pg_conn, [CrashingAdapter(), GoodAdapter()],
                        JobQuery(), run_id=run_id)
    statuses = {r.adapter_name: r.status for r in results}
    assert statuses["crash"] == "crashed"
    assert statuses["good"] == "success"
    # Error logged: message contains the RuntimeError class name
    with pg_conn.cursor() as cur:
        cur.execute("SELECT message FROM run_errors")
        msgs = [r["message"] for r in cur.fetchall()]
    assert any("RuntimeError" in m for m in msgs)