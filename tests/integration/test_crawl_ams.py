"""Integration: full AMS pipeline vs recorded fixtures. No Playwright launch."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import pytest
from crawler import config
from crawler.storage.db import connect
from crawler.storage.migrations.runner import apply as apply_migrations
from crawler.storage.repository import start_run, finalize_run
from crawler.sources.ams import AmsAdapter
from crawler.pipeline import run
from crawler.models import JobQuery
from tests.fakes.browser import FakeBrowserContext


SEARCH_HTML = '''
<html><body>
<div data-testid="job-card">
  <a class="title" href="/public/jobs/123">Senior SWE</a>
  <span class="company">ACME GmbH</span>
  <span class="location">Wien</span>
  <time datetime="2026-06-20T09:00:00Z">2026-06-20</time>
</div>
<div data-testid="job-card">
  <a class="title" href="/public/jobs/456">Data Scientist</a>
  <span class="company">Foo AG</span>
  <span class="location">Graz</span>
  <time datetime="2026-06-21T09:00:00Z">2026-06-21</time>
</div>
</body></html>
'''

DETAIL_HTML = '''
<html><body>
<article data-testid="job-detail">
  <h1>Senior SWE</h1>
  <div class="company">ACME GmbH</div>
  <div class="location">Wien</div>
  <div class="description">Build cool stuff.</div>
</article>
</body></html>
'''


@pytest.mark.asyncio
async def test_full_ams_pipeline_persists_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.db")
    conn = connect(config.DB_PATH)
    apply_migrations(conn)
    run_id = start_run(conn, source="ams")

    fake = FakeBrowserContext({
        config.AMS_BASE_URL + "jobs": SEARCH_HTML,
        "https://jobs.ams.at/public/jobs/123": DETAIL_HTML,
        "https://jobs.ams.at/public/jobs/456": DETAIL_HTML,
    })
    adapter = AmsAdapter(browser=fake)
    results = await run(conn, [adapter], JobQuery(), run_id=run_id)
    finalize_run(conn, run_id, status="success", counters={"inserted": 2, "updated": 0, "errors": 0})

    assert len(results) == 1
    assert results[0].status == "success"
    assert results[0].counters["inserted"] == 2

    jobs = conn.execute("SELECT source_id, title, company FROM jobs ORDER BY id").fetchall()
    assert len(jobs) == 2
    assert jobs[0]["source_id"] == "123"
    assert jobs[1]["source_id"] == "456"

    errors = conn.execute("SELECT * FROM crawl_errors").fetchall()
    assert len(errors) == 0
