from datetime import datetime
import pytest
from bs4 import BeautifulSoup
from crawler.sources.ams import (
    _parse_search_card, _parse_detail_page, AMS_JOB_CARD_SELECTOR,
    AMS_DETAIL_SELECTOR, AMS_TITLE_SELECTOR, AMS_COMPANY_SELECTOR,
    AMS_LOCATION_SELECTOR, AMS_DESCRIPTION_SELECTOR, AMS_POSTED_SELECTOR,
)
from crawler.models import RawJob, NormalizedJob
from crawler.storage.dedup import content_hash
from crawler.exceptions import SchemaChanged


SEARCH_HTML = '''
<html><body>
<div data-testid="job-card">
  <a class="title" href="/public/jobs/123">Senior Software Engineer</a>
  <span class="company">ACME GmbH</span>
  <span class="location">Wien, 1. Bezirk</span>
  <time datetime="2026-06-20T09:00:00Z">2026-06-20</time>
</div>
</body></html>
'''


DETAIL_HTML = '''
<html><body>
<article data-testid="job-detail">
  <h1>Senior Software Engineer</h1>
  <div class="company">ACME GmbH</div>
  <div class="location">Wien, 1. Bezirk</div>
  <div class="description">Build cool stuff.</div>
  <div class="salary">€ 50.000+</div>
  <div class="employment-type">Vollzeit</div>
  <time datetime="2026-06-20T09:00:00Z">2026-06-20</time>
</article>
</body></html>
'''


SCHEMA_BROKEN_HTML = '<html><body><div data-testid="job-card"><a class="title" href="/x">X</a></div></body></html>'


def test_parse_search_card_extracts_fields():
    soup = BeautifulSoup(SEARCH_HTML, "html.parser")
    card = soup.select_one(AMS_JOB_CARD_SELECTOR)
    raw = _parse_search_card(card, fetched_at=datetime(2026, 6, 22, tzinfo=__import__("datetime").timezone.utc))
    assert raw.source == "ams"
    assert raw.source_id == "123"
    assert raw.title == "Senior Software Engineer"
    assert raw.company == "ACME GmbH"
    assert raw.location == "Wien, 1. Bezirk"


def test_parse_detail_page_returns_normalized_job():
    soup = BeautifulSoup(DETAIL_HTML, "html.parser")
    fetched = datetime(2026, 6, 22, tzinfo=__import__("datetime").timezone.utc)
    raw = RawJob(
        source="ams", source_id="123",
        url="https://jobs.ams.at/public/jobs/123",
        title="Senior Software Engineer",
        company="ACME GmbH", location="Wien, 1. Bezirk",
        fetched_at=fetched,
    )
    job = _parse_detail_page(soup, raw, html=DETAIL_HTML, fetched_at=fetched)
    assert isinstance(job, NormalizedJob)
    assert job.title == "Senior Software Engineer"
    assert job.company == "ACME GmbH"
    assert job.description == "Build cool stuff."
    assert job.salary == "€ 50.000+"
    assert job.employment_type == "Vollzeit"
    assert job.content_hash == content_hash(job.title, job.company, job.location)
    assert job.raw_html == DETAIL_HTML


def test_parse_detail_missing_required_raises_schema_changed():
    soup = BeautifulSoup(SCHEMA_BROKEN_HTML, "html.parser")
    fetched = datetime(2026, 6, 22, tzinfo=__import__("datetime").timezone.utc)
    raw = RawJob(
        source="ams", source_id="1",
        url="https://jobs.ams.at/x/1",
        title="X", company="Y", location="Z", fetched_at=fetched,
    )
    with pytest.raises(SchemaChanged):
        _parse_detail_page(soup, raw, html=SCHEMA_BROKEN_HTML, fetched_at=fetched)


def test_selectors_are_exported():
    # Document the selectors (grill-me amendment 10: schema drift resilience)
    assert AMS_JOB_CARD_SELECTOR == '[data-testid="job-card"]'
    assert AMS_DETAIL_SELECTOR == '[data-testid="job-detail"]'
    assert AMS_TITLE_SELECTOR
    assert AMS_COMPANY_SELECTOR
    assert AMS_LOCATION_SELECTOR
    assert AMS_DESCRIPTION_SELECTOR
    assert AMS_POSTED_SELECTOR