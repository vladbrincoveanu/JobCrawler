"""Field-mapping tests for scout.fetch_free_apis, the zero-auth API sources.

Each provider is stubbed with a recorded-shape payload rather than hit live: the
point is to catch "we read the wrong key" and "we invented a salary the ad never
stated", which a live test cannot assert on because its data changes hourly.

Himalayas gets the most attention here because its payload is the odd one out --
`pubDate` is a unix epoch delivered as a *string*, and `locationRestrictions` is
a list rather than a location string, so both need converting before the rest of
the pipeline (recency cutoff, reachable_from_home) can read them.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scout  # noqa: E402

ROLE_TITLES = ["backend", "software engineer"]
TODAY = date.today()


def _himalayas_job(**over):
    job = {
        "title": "Senior Backend Engineer",
        "companyName": "ACME",
        "locationRestrictions": ["Austria", "Germany"],
        "pubDate": str(int(
            __import__("datetime").datetime.combine(
                TODAY, __import__("datetime").time(12, 0)).timestamp())),
        "applicationLink": "https://himalayas.app/jobs/1",
        "description": "<p>Kafka and .NET</p>",
        "minSalary": 70000,
        "maxSalary": 90000,
        "currency": "EUR",
    }
    job.update(over)
    return job


@pytest.fixture
def only_himalayas(monkeypatch):
    """Stub every provider; the caller fills in the Himalayas payload.

    Himalayas is paged, and only the FIRST page serves the caller's payload --
    later offsets come back empty, which is both what the real API does past the
    end and the condition that stops the paging loop. Serving every offset the
    same page would multiply each fixture row by the page count.
    """
    payloads = {}

    def fake_get(url):
        for key, value in payloads.items():
            if key in url:
                if "himalayas" in url and "offset=0" not in url:
                    return {"jobs": []}
                return value
        return None

    monkeypatch.setattr(scout, "_api_get", fake_get)
    return payloads


def test_himalayas_maps_every_field(only_himalayas):
    only_himalayas["himalayas.app"] = {"jobs": [_himalayas_job()]}

    jobs = scout.fetch_free_apis(days=14, role_titles=ROLE_TITLES)

    assert len(jobs) == 1
    job = jobs[0]
    assert job["ats_type"] == "himalayas"
    assert job["title"] == "Senior Backend Engineer"
    assert job["company"] == "ACME"
    # The country list becomes a location string reachable_from_home can read.
    assert job["location"] == "Austria, Germany"
    assert job["is_remote"] == "true"
    assert job["posted"] == TODAY.isoformat()
    assert job["apply_url"] == "https://himalayas.app/jobs/1"
    assert "Kafka" in job["description"] and "<p>" not in job["description"]
    assert (job["salary_min"], job["salary_max"]) == (70000, 90000)


def test_himalayas_empty_restrictions_mean_worldwide(only_himalayas):
    only_himalayas["himalayas.app"] = {
        "jobs": [_himalayas_job(locationRestrictions=[])]
    }
    jobs = scout.fetch_free_apis(days=14, role_titles=ROLE_TITLES)
    assert jobs[0]["location"] == "Worldwide"


def test_himalayas_unparseable_date_does_not_crash_the_run(only_himalayas):
    """A bad epoch must drop the row on the recency filter, not raise."""
    only_himalayas["himalayas.app"] = {"jobs": [_himalayas_job(pubDate="not-a-date")]}
    assert scout.fetch_free_apis(days=14, role_titles=ROLE_TITLES) == []


def test_stale_rows_are_dropped_by_the_recency_cutoff(only_himalayas):
    old = __import__("datetime").datetime.combine(
        TODAY - timedelta(days=90), __import__("datetime").time(12, 0))
    only_himalayas["himalayas.app"] = {
        "jobs": [_himalayas_job(pubDate=str(int(old.timestamp())))]
    }
    assert scout.fetch_free_apis(days=14, role_titles=ROLE_TITLES) == []


def test_titles_outside_the_profile_are_dropped(only_himalayas):
    only_himalayas["himalayas.app"] = {
        "jobs": [_himalayas_job(title="Regional Sales Manager")]
    }
    assert scout.fetch_free_apis(days=14, role_titles=ROLE_TITLES) == []


def test_a_dead_provider_does_not_stop_the_others(monkeypatch):
    """_api_get returns None on failure; that must skip, not raise."""
    monkeypatch.setattr(scout, "_api_get", lambda url: None)
    assert scout.fetch_free_apis(days=14, role_titles=ROLE_TITLES) == []
