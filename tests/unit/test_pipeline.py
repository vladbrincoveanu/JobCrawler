import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator
import pytest
from crawler.models import JobQuery, RawJob, NormalizedJob
from crawler.sources.base import SourceAdapter
from crawler.sources.ams import AmsAdapter
from crawler.storage.db import connect
from crawler.storage.migrations.runner import apply as apply_migrations
from crawler.pipeline import run, run_source, CircuitOpen
from crawler.exceptions import SchemaChanged, CaptchaEncountered
from tests.fakes.browser import FakeBrowserContext


class StubAdapter:
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
            source=raw.source, source_id=raw.source_id, url=raw.url,
            title=raw.title, company=raw.company or "ACME", location=raw.location or "Wien",
            description="d", content_hash=f"hash-{raw.source_id}",
            fetched_at=raw.fetched_at,
        )


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "p.db")
    apply_migrations(c)
    return c


@pytest.mark.asyncio
async def test_run_source_success(conn):
    raw = RawJob(source="stub", source_id="1", url="https://x/1",
                  title="SWE", company="ACME", location="Wien",
                  fetched_at=datetime.now(timezone.utc))
    adapter = StubAdapter(jobs=[raw])
    result = await run_source(conn, adapter, JobQuery(), run_id=1)
    assert result.status == "success"
    assert result.counters["inserted"] == 1


@pytest.mark.asyncio
async def test_run_source_partial_on_per_job_error(conn):
    raw1 = RawJob(source="stub", source_id="1", url="https://x/1",
                   title="SWE", company="ACME", location="Wien",
                   fetched_at=datetime.now(timezone.utc))
    raw2 = RawJob(source="stub", source_id="2", url="https://x/2",
                   title="DS", company="ACME", location="Wien",
                   fetched_at=datetime.now(timezone.utc))
    adapter = StubAdapter(jobs=[raw1, raw2])
    # Make fetch_detail fail once
    original = adapter.fetch_detail
    calls = [0]
    async def flaky(raw):
        calls[0] += 1
        if calls[0] == 1:
            raise SchemaChanged("broken")
        return await original(raw)
    adapter.fetch_detail = flaky
    result = await run_source(conn, adapter, JobQuery(), run_id=1)
    assert result.status == "partial"
    assert result.counters["inserted"] == 1
    assert result.counters["errors"] == 1


@pytest.mark.asyncio
async def test_run_source_circuit_break_on_captcha(conn):
    adapter = StubAdapter(fail_with=CaptchaEncountered("captcha"))
    result = await run_source(conn, adapter, JobQuery(), run_id=1)
    assert result.status == "failed"
    assert "CaptchaEncountered" in str(result.error)


@pytest.mark.asyncio
async def test_run_aggregates_multiple_sources(conn):
    raw1 = RawJob(source="a", source_id="1", url="https://x/1",
                   title="SWE", company="ACME", location="Wien",
                   fetched_at=datetime.now(timezone.utc))
    raw2 = RawJob(source="b", source_id="2", url="https://y/2",
                   title="DS", company="Foo", location="Graz",
                   fetched_at=datetime.now(timezone.utc))
    a = StubAdapter(name="a", jobs=[raw1])
    b = StubAdapter(name="b", jobs=[raw2])
    # Need different run_ids
    from crawler.storage.repository import start_run
    run_id = start_run(conn, source="multi")
    results = await run(conn, [a, b], JobQuery(), run_id=run_id)
    statuses = {r.adapter_name: r.status for r in results}
    assert statuses == {"a": "success", "b": "success"}


@pytest.mark.asyncio
async def test_dry_run_skips_upsert(conn):
    raw = RawJob(source="stub", source_id="1", url="https://x/1",
                  title="SWE", company="ACME", location="Wien",
                  fetched_at=datetime.now(timezone.utc))
    adapter = StubAdapter(jobs=[raw])
    result = await run_source(conn, adapter, JobQuery(), run_id=1, dry_run=True)
    assert result.status == "success"
    assert result.counters["inserted"] == 1  # counted
    rows = conn.execute("SELECT * FROM jobs").fetchall()
    assert len(rows) == 0  # not written