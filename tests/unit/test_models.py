from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from crawler.models import JobQuery, NormalizedJob, RawJob


def test_job_query_defaults():
    q = JobQuery()
    assert q.keywords == []
    assert q.location is None
    assert q.max_results == 100
    assert q.since is None


def test_raw_job_required_fields():
    raw = RawJob(
        source="ams",
        source_id="12345",
        url="https://jobs.ams.at/public/jobs/12345",
        title="Software Engineer",
        company="ACME GmbH",
        location="Wien",
        fetched_at=datetime(2026, 6, 22, tzinfo=timezone.utc),
    )
    assert raw.source == "ams"
    assert raw.posted_at is None


def test_normalized_job_requires_content_hash():
    with pytest.raises(ValidationError):
        NormalizedJob(
            source="ams",
            source_id="1",
            url="https://x.at/1",
            title="X",
            company="Y",
            location="Wien",
            description="d",
            fetched_at=datetime.now(timezone.utc),
        )


def test_normalized_job_with_hash_ok():
    n = NormalizedJob(
        source="ams",
        source_id="1",
        url="https://x.at/1",
        title="X",
        company="Y",
        location="Wien",
        description="d",
        content_hash="abc123",
        fetched_at=datetime.now(timezone.utc),
    )
    assert n.content_hash == "abc123"
    assert n.salary is None
    assert n.employment_type is None
