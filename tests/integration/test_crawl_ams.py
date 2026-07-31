"""Integration: full AMS pipeline vs recorded fixtures. No Playwright launch."""
import pytest

from crawler import config
from crawler.models import JobQuery
from crawler.pipeline import run
from crawler.sources.ams import AmsAdapter
from crawler.storage import repository as repo
from tests.fakes.browser import FakeBrowserContext

SEARCH_HTML = '''
<html><body>
<div data-testid="job-card">
  <a class="title" href="/public/jobs/123">Senior SWE</a>
  <span class="company">ACME</span>
  <span class="location">Wien</span>
  <time datetime="2026-06-20T09:00:00Z">2026-06-20</time>
</div>
<div data-testid="job-card">
  <a class="title" href="/public/jobs/456">Data Scientist</a>
  <span class="company">Foo</span>
  <span class="location">Graz</span>
  <time datetime="2026-06-21T09:00:00Z">2026-06-21</time>
</div>
</body></html>
'''

DETAIL_HTML_123 = '''
<html><body>
<article data-testid="job-detail">
  <h1>Senior SWE</h1>
  <div class="company">ACME</div>
  <div class="location">Wien</div>
  <div class="description">Build cool stuff.</div>
</article>
</body></html>
'''

DETAIL_HTML_456 = '''
<html><body>
<article data-testid="job-detail">
  <h1>Data Scientist</h1>
  <div class="company">Foo</div>
  <div class="location">Graz</div>
  <div class="description">Analyze data.</div>
</article>
</body></html>
'''


@pytest.mark.asyncio
async def test_full_ams_pipeline_persists_jobs(pg_conn):
    repo.upsert_source(pg_conn, "ams")
    run_id = repo.start_run(pg_conn, source="ams")

    fake = FakeBrowserContext({
        config.AMS_BASE_URL + "jobs": SEARCH_HTML,
        "https://jobs.ams.at/public/jobs/123": DETAIL_HTML_123,
        "https://jobs.ams.at/public/jobs/456": DETAIL_HTML_456,
    })
    adapter = AmsAdapter(browser=fake)
    results = await run(pg_conn, [adapter], JobQuery(), run_id=run_id)
    repo.finish_run(pg_conn, run_id, status="success",
                    jobs_found=2, jobs_new=2)

    assert len(results) == 1
    assert results[0].status == "success"
    assert results[0].counters["inserted"] == 2

    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT source_id, title, company FROM jobs ORDER BY id"
        )
        jobs = cur.fetchall()
    assert len(jobs) == 2
    assert jobs[0]["source_id"] == "123"
    assert jobs[1]["source_id"] == "456"

    with pg_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM run_errors")
        n = cur.fetchone()["n"]
    assert n == 0