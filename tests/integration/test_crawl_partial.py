"""Integration: 1 broken job among 2 → partial status, 1 inserted, 1 error logged."""
import pytest
from datetime import datetime, timezone
from crawler import config
from crawler.storage.db import connect
from crawler.storage.migrations.runner import apply as apply_migrations
from crawler.storage.repository import start_run
from crawler.sources.ams import AmsAdapter
from crawler.pipeline import run
from crawler.models import JobQuery
from tests.fakes.browser import FakeBrowserContext


SEARCH_HTML = '''
<html><body>
<div data-testid="job-card">
  <a class="title" href="/public/jobs/123">SWE</a>
  <span class="company">ACME</span>
  <span class="location">Wien</span>
  <time datetime="2026-06-20T09:00:00Z">2026-06-20</time>
</div>
<div data-testid="job-card">
  <a class="title" href="/public/jobs/456">Broken</a>
  <span class="company">Foo</span>
  <span class="location">Graz</span>
  <time datetime="2026-06-21T09:00:00Z">2026-06-21</time>
</div>
</body></html>
'''

GOOD_DETAIL = '''
<html><body>
<article data-testid="job-detail">
  <h1>SWE</h1>
  <div class="company">ACME</div>
  <div class="location">Wien</div>
  <div class="description">d</div>
</article>
</body></html>
'''

# Broken: missing data-testid="job-detail" → SPAWaitTimeout (fake raises on missing URL or wait_selector not in HTML)
BROKEN_DETAIL = '<html><body>no detail selector</body></html>'


@pytest.mark.asyncio
async def test_partial_run(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.db")
    conn = connect(config.DB_PATH)
    apply_migrations(conn)
    run_id = start_run(conn, source="ams")

    fake = FakeBrowserContext({
        config.AMS_BASE_URL + "jobs": SEARCH_HTML,
        "https://jobs.ams.at/public/jobs/123": GOOD_DETAIL,
        "https://jobs.ams.at/public/jobs/456": BROKEN_DETAIL,
    })
    adapter = AmsAdapter(browser=fake)
    results = await run(conn, [adapter], JobQuery(), run_id=run_id)
    assert results[0].status == "partial"
    assert results[0].counters["inserted"] == 1
    assert results[0].counters["errors"] == 1
    errs = conn.execute("SELECT * FROM crawl_errors").fetchall()
    assert len(errs) == 1
