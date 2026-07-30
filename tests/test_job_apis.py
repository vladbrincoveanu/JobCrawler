"""Adzuna + Jooble source mapping.

These two providers are key-gated, so the important behaviours to pin down are
(a) a missing key is a skip and not a crash, and (b) the response -> job-dict
mapping matches each provider's documented schema. The payloads below are
hand-built to that schema rather than recorded, because no API key was available
when this was written -- see the honesty note in scripts/sources/job_apis.py.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from sources import job_apis  # noqa: E402

TODAY = date.today().isoformat()
OLD = (date.today() - timedelta(days=400)).isoformat()


@pytest.fixture(autouse=True)
def _no_keys(monkeypatch):
    """Every test starts with no credentials; the ones that need a key set it."""
    for var in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "JOOBLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)


# --- key gating ---

def test_adzuna_without_a_key_is_a_skip_not_a_crash(monkeypatch):
    called = []
    monkeypatch.setattr(job_apis, "_get_json", lambda *a, **k: called.append(1))
    assert job_apis.fetch_adzuna(["backend"], ["AT"], 30) == []
    assert not called, "must not issue a request with no credentials"


def test_adzuna_needs_both_halves_of_the_credential(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id-only")
    monkeypatch.setattr(job_apis, "_get_json", lambda *a, **k: pytest.fail("requested"))
    assert job_apis.fetch_adzuna(["backend"], ["AT"], 30) == []


def test_jooble_without_a_key_is_a_skip_not_a_crash(monkeypatch):
    monkeypatch.setattr(job_apis, "_post_json", lambda *a, **k: pytest.fail("requested"))
    assert job_apis.fetch_jooble(["backend"], ["Wien"], 30) == []


# --- adzuna mapping ---

ADZUNA_PAGE = {
    "results": [{
        "title": "Senior .NET Engineer",
        "company": {"display_name": "ACME GmbH"},
        "location": {"display_name": "Wien, Wien"},
        "created": f"{TODAY}T09:00:00Z",
        "redirect_url": "https://www.adzuna.at/land/ad/123",
        "description": "<p>Work with <b>C#</b> and Azure.</p>",
        "salary_min": 60000.0,
        "salary_max": 80000.0,
    }],
}


def test_adzuna_maps_a_result_into_the_scout_job_shape(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    monkeypatch.setattr(job_apis, "_get_json", lambda *a, **k: ADZUNA_PAGE)

    jobs = job_apis.fetch_adzuna(["backend"], ["AT"], 30, max_pages=1)

    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Senior .NET Engineer"
    assert job["company"] == "ACME GmbH"
    assert job["location"] == "Wien, Wien"
    assert job["ats_type"] == "adzuna"
    assert job["posted"] == TODAY
    assert job["apply_url"] == job["url"] == "https://www.adzuna.at/land/ad/123"
    # HTML is stripped: the scorer matches plain words, and tag soup in a
    # description shows up verbatim in the dashboard.
    assert "<b>" not in job["description"] and "C#" in job["description"]
    # Adzuna salaries are already annual, so they pass through untouched --
    # applying the Austrian 14x monthly rule here would inflate them.
    assert (job["salary_min"], job["salary_max"]) == (60000, 80000)
    assert job["salary_period"] == "year"


def test_adzuna_only_queries_countries_it_serves(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    seen: list[str] = []

    def fake_get(url, params):
        seen.append(url)
        return {"results": []}

    monkeypatch.setattr(job_apis, "_get_json", fake_get)
    job_apis.fetch_adzuna(["backend"], ["AT", "XX"], 30, max_pages=1)
    assert all("/at/" in url for url in seen)
    assert seen, "the supported country must still be queried"


def test_adzuna_drops_results_older_than_the_window(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    stale = {"results": [dict(ADZUNA_PAGE["results"][0], created=f"{OLD}T09:00:00Z")]}
    monkeypatch.setattr(job_apis, "_get_json", lambda *a, **k: stale)
    assert job_apis.fetch_adzuna(["backend"], ["AT"], 30, max_pages=1) == []


def test_adzuna_stops_paging_on_a_short_page(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    pages = []
    monkeypatch.setattr(job_apis, "_get_json",
                        lambda url, params: pages.append(url) or ADZUNA_PAGE)
    job_apis.fetch_adzuna(["backend"], ["AT"], 30, max_pages=5, results_per_page=50)
    # One result came back for a 50-per-page request, so page 2 is pointless.
    assert len(pages) == 1


def test_adzuna_survives_a_failed_request(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    monkeypatch.setattr(job_apis, "_get_json", lambda *a, **k: None)
    assert job_apis.fetch_adzuna(["backend"], ["AT"], 30, max_pages=1) == []


# --- jooble mapping ---

JOOBLE_PAGE = {
    "jobs": [{
        "title": "Backend Developer (m/w/d)",
        "company": "Beta AG",
        "location": "Wien",
        "snippet": "<b>Java</b> and Kafka",
        "salary": "€ 50.000 - 70.000/Jahr",
        "link": "https://at.jooble.org/jdp/456",
        "updated": f"{TODAY}T08:00:00.000",
        "type": "Vollzeit, Remote",
    }],
}


def test_jooble_maps_a_result_into_the_scout_job_shape(monkeypatch):
    monkeypatch.setenv("JOOBLE_API_KEY", "key")
    monkeypatch.setattr(job_apis, "_post_json", lambda *a, **k: JOOBLE_PAGE)

    jobs = job_apis.fetch_jooble(["backend"], ["Wien"], 30, max_pages=1)

    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Backend Developer (m/w/d)"
    assert job["company"] == "Beta AG"
    assert job["ats_type"] == "jooble"
    assert job["posted"] == TODAY
    assert job["apply_url"] == "https://at.jooble.org/jdp/456"
    assert "<b>" not in job["description"]
    # Jooble's salary is free text, so it must NOT land in the numeric fields --
    # the scout's own parser reads salary_summary instead.
    assert job["salary_min"] is None and job["salary_max"] is None
    assert job["salary_summary"] == "€ 50.000 - 70.000/Jahr"


def test_jooble_reads_remote_from_the_type_string(monkeypatch):
    monkeypatch.setenv("JOOBLE_API_KEY", "key")
    monkeypatch.setattr(job_apis, "_post_json", lambda *a, **k: JOOBLE_PAGE)
    assert job_apis.fetch_jooble(["backend"], ["Wien"], 30, max_pages=1)[0]["is_remote"] == "true"

    onsite = {"jobs": [dict(JOOBLE_PAGE["jobs"][0], type="Vollzeit")]}
    monkeypatch.setattr(job_apis, "_post_json", lambda *a, **k: onsite)
    assert job_apis.fetch_jooble(["backend"], ["Wien"], 30, max_pages=1)[0]["is_remote"] == "false"


def test_jooble_keeps_the_key_out_of_the_failure_log(monkeypatch, capsys):
    """The key is path-positional in Jooble's API, so a naive error log would
    print it. Anything written to stderr here ends up in the dashboard's 502
    detail field, which is shown in the browser."""
    monkeypatch.setenv("JOOBLE_API_KEY", "super-secret-key")
    import requests

    def boom(*a, **k):
        raise requests.RequestException("nope")

    monkeypatch.setattr(job_apis.requests, "post", boom)
    job_apis.fetch_jooble(["backend"], ["Wien"], 30, max_pages=1)
    assert "super-secret-key" not in capsys.readouterr().err


def test_jooble_stops_paging_when_a_page_is_empty(monkeypatch):
    monkeypatch.setenv("JOOBLE_API_KEY", "key")
    calls = []
    monkeypatch.setattr(job_apis, "_post_json",
                        lambda url, payload: calls.append(payload["page"]) or {"jobs": []})
    job_apis.fetch_jooble(["backend"], ["Wien"], 30, max_pages=5)
    assert calls == [1]
