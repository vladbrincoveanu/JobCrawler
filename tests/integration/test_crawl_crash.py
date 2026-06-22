"""Integration: source raises unexpected exception → status=crashed, run continues, error logged."""
import pytest
from datetime import datetime, timezone
from crawler import config
from crawler.storage.db import connect
from crawler.storage.migrations.runner import apply as apply_migrations
from crawler.storage.repository import start_run
from crawler.models import JobQuery, RawJob, NormalizedJob
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
        raw = RawJob(source="good", source_id="1", url="https://x/1",
                      title="SWE", company="ACME", location="Wien",
                      fetched_at=datetime.now(timezone.utc))
        yield raw

    async def fetch_detail(self, raw):
        return NormalizedJob(
            source=raw.source, source_id=raw.source_id, url=raw.url,
            title=raw.title, company=raw.company, location=raw.location,
            description="d", content_hash="h1", fetched_at=raw.fetched_at,
        )


@pytest.mark.asyncio
async def test_crash_isolated_per_source(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.db")
    conn = connect(config.DB_PATH)
    apply_migrations(conn)
    run_id = start_run(conn, source="multi")

    results = await run(conn, [CrashingAdapter(), GoodAdapter()], JobQuery(), run_id=run_id)
    statuses = {r.adapter_name: r.status for r in results}
    assert statuses["crash"] == "crashed"
    assert statuses["good"] == "success"
    # Error logged
    errs = conn.execute("SELECT error_type FROM crawl_errors").fetchall()
    assert any("RuntimeError" in e["error_type"] for e in errs)
