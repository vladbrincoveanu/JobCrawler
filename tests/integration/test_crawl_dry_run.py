"""Integration: --dry-run mode does not write to jobs table."""
import pytest
from crawler import config
from crawler.sources.ams import AmsAdapter
from crawler.storage.db import connect
from crawler.storage.migrations.runner import apply as apply_migrations
from crawler.storage.repository import start_run
from crawler.pipeline import run
from crawler.models import JobQuery
from tests.fakes.browser import FakeBrowserContext


@pytest.mark.asyncio
async def test_dry_run_does_not_write_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.db")
    conn = connect(config.DB_PATH)
    apply_migrations(conn)
    run_id = start_run(conn, source="ams", status="dry_run")

    fake = FakeBrowserContext({
        config.AMS_BASE_URL + "jobs": '''
<html><body>
<div data-testid="job-card">
  <a class="title" href="/public/jobs/1">X</a>
  <span class="company">A</span><span class="location">Wien</span>
  <time datetime="2026-06-22T00:00:00Z"></time>
</div>
</body></html>''',
        "https://jobs.ams.at/public/jobs/1": '''
<html><body>
<article data-testid="job-detail">
  <h1>X</h1><div class="company">A</div><div class="location">Wien</div><div class="description">d</div>
</article>
</body></html>''',
    })
    adapter = AmsAdapter(browser=fake)
    results = await run(conn, [adapter], JobQuery(), run_id=run_id, dry_run=True)
    # Pipeline counts but does not write
    assert results[0].counters["inserted"] == 1
    rows = conn.execute("SELECT * FROM jobs").fetchall()
    assert len(rows) == 0
    # Crawl run lifecycle
    row = conn.execute("SELECT status FROM crawl_runs WHERE id=?", (run_id,)).fetchone()
    assert row["status"] == "dry_run"
