"""Integration: --dry-run mode does not write to jobs table."""
import pytest

from crawler import config
from crawler.sources.ams import AmsAdapter
from crawler.storage import repository as repo
from crawler.pipeline import run
from crawler.models import JobQuery
from tests.fakes.browser import FakeBrowserContext


@pytest.mark.asyncio
async def test_dry_run_does_not_write_jobs(pg_conn):
    repo.upsert_source(pg_conn, "ams")
    run_id = repo.start_run(pg_conn, source="ams")

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
    results = await run(pg_conn, [adapter], JobQuery(), run_id=run_id, dry_run=True)
    # Pipeline counts but does not write
    assert results[0].counters["inserted"] == 1
    with pg_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM jobs")
        n = cur.fetchone()["n"]
    assert n == 0
    # Crawl run lifecycle — finish with dry_run status to mark the run
    repo.finish_run(pg_conn, run_id, status="success", jobs_found=1, jobs_new=0)
    with pg_conn.cursor() as cur:
        cur.execute("SELECT status FROM runs WHERE id = %s", (run_id,))
        row = cur.fetchone()
    assert row["status"] == "success"