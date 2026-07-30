"""Tests for the --json-out flag and the per-CV profile cache.

--json-out is what the dashboard's CV-upload-and-scan flow shells out to: it
needs one deterministic JSON payload instead of a Telegram send or an HTML
dashboard. The profile cache test guards a real bug found while building that
flow: load_profile() used to cache under a single fixed path (data/profile.json)
regardless of which CV was passed via --cv, so the first CV ever scored would
silently "win" forever and every later --cv (including every web upload) would
be scored against a stranger's profile.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scout


@pytest.fixture
def cv_pdf(tmp_path):
    """A syntactically valid, near-empty PDF -- content doesn't matter here
    because extract_cv_text is monkeypatched per-test where needed."""
    from pypdf import PdfWriter

    path = tmp_path / "cv.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with open(path, "wb") as f:
        writer.write(f)
    return path


def test_load_profile_is_keyed_by_cv_content_not_a_shared_file(tmp_path, monkeypatch, cv_pdf):
    monkeypatch.setattr(scout, "PROFILE_PATH", tmp_path / "data" / "profile.json")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    texts = {}

    def fake_extract(path):
        return texts[Path(path)]

    monkeypatch.setattr(scout, "extract_cv_text", fake_extract)

    cv_a = tmp_path / "a.pdf"
    cv_a.write_bytes(cv_pdf.read_bytes())
    cv_b = tmp_path / "b.pdf"
    cv_b.write_bytes(cv_pdf.read_bytes() + b"\n%different")
    texts[cv_a] = "Senior .NET Backend Engineer, Kafka, Kubernetes, Azure"
    texts[cv_b] = "DevOps Engineer, Terraform, Kubernetes, CI/CD"

    profile_a = scout.load_profile(cv_a, rebuild=False)
    profile_b = scout.load_profile(cv_b, rebuild=False)

    assert "dotnet" in profile_a["skills"]
    assert "dotnet" not in profile_b["skills"]
    assert "terraform" in profile_b["skills"]


def test_load_profile_reuses_cache_for_the_same_cv_bytes(tmp_path, monkeypatch, cv_pdf):
    monkeypatch.setattr(scout, "PROFILE_PATH", tmp_path / "data" / "profile.json")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    calls = []

    def fake_extract(path):
        calls.append(path)
        return "Python Engineer, LLM, RAG"

    monkeypatch.setattr(scout, "extract_cv_text", fake_extract)

    scout.load_profile(cv_pdf, rebuild=False)
    scout.load_profile(cv_pdf, rebuild=False)

    assert len(calls) == 1  # second call hit the cache, no re-extraction


def test_json_out_writes_structured_results_offline(tmp_path, monkeypatch, cv_pdf):
    """--sources '' means no live source is queried (no network, no duckdb) --
    this exercises the full main() pipeline (profile load, scoring, dedupe,
    json-out) with zero external calls, which is exactly the code path the
    dashboard's scan API depends on when live sources happen to be unreachable."""
    monkeypatch.setattr(scout, "PROFILE_PATH", tmp_path / "data" / "profile.json")
    monkeypatch.setattr(scout, "SENT_PATH", tmp_path / "data" / "sent_jobs.json")
    monkeypatch.setattr(scout, "CV_DASHBOARD_DIR", tmp_path / "dashboards")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    out_path = tmp_path / "out.json"
    argv = [
        "scout.py", "--dry-run", "--cv", str(cv_pdf), "--sources", "",
        "--json-out", str(out_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)

    rc = scout.main()
    assert rc == 0
    assert out_path.exists()

    result = json.loads(out_path.read_text())
    assert result["jobs"] == []
    assert result["total_matches"] == 0
    assert "generated_at" in result
    assert result["cv"] == str(cv_pdf)


def test_json_out_ranks_and_caps_the_full_scored_set(tmp_path, monkeypatch, cv_pdf):
    monkeypatch.setattr(scout, "PROFILE_PATH", tmp_path / "data" / "profile.json")
    monkeypatch.setattr(scout, "SENT_PATH", tmp_path / "data" / "sent_jobs.json")
    monkeypatch.setattr(scout, "CV_DASHBOARD_DIR", tmp_path / "dashboards")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setattr(scout, "extract_cv_text", lambda path: "Backend Engineer, Kafka")

    out_path = tmp_path / "out.json"
    argv = [
        "scout.py", "--dry-run", "--cv", str(cv_pdf), "--sources", "",
        "--json-out", str(out_path), "--top", "2",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    # Inject jobs the same way fetch_jobs()/fetch_free_apis() would, by
    # monkeypatching fetch_free_apis and turning "apis" on, since jobhive/
    # karriere/stepstone all require network or duckdb this test must avoid.
    def fake_apis(days, role_titles):
        return [
            {"url": "https://x/1", "title": "Senior Backend Engineer", "company": "ACME",
             "ats_type": "arbeitnow", "location": "Wien, Austria", "is_remote": "false",
             "country_iso": "AT", "salary_min": None, "salary_max": None,
             "salary_currency": None, "salary_period": None, "salary_summary": None,
             "employment_type": None, "description": "Kafka, distributed systems",
             "posted": "2026-07-29", "apply_url": "https://x/1"},
            {"url": "https://x/2", "title": "Kafka Backend Engineer", "company": "Beta",
             "ats_type": "arbeitnow", "location": "Wien, Austria", "is_remote": "false",
             "country_iso": "AT", "salary_min": None, "salary_max": None,
             "salary_currency": None, "salary_period": None, "salary_summary": None,
             "employment_type": None, "description": "Kafka, event-driven",
             "posted": "2026-07-30", "apply_url": "https://x/2"},
        ]

    monkeypatch.setattr(scout, "fetch_free_apis", fake_apis)
    argv[argv.index("--sources") + 1] = "apis"
    monkeypatch.setattr(sys, "argv", argv)

    rc = scout.main()
    assert rc == 0
    result = json.loads(out_path.read_text())
    assert len(result["jobs"]) == 2
    titles = {j["title"] for j in result["jobs"]}
    assert titles == {"Senior Backend Engineer", "Kafka Backend Engineer"}
    assert all(j["rank"] for j in result["jobs"])


def test_missing_bucket_config_degrades_instead_of_crashing(tmp_path, monkeypatch, cv_pdf):
    """A fresh checkout (or this sandbox) has no career/Resume/JOB-SEARCH/keywords/
    directory -- data/buckets.json points outside the repo. main() must still be
    able to run the CV-upload flow without that personal directory existing."""
    monkeypatch.setattr(scout, "PROFILE_PATH", tmp_path / "data" / "profile.json")
    monkeypatch.setattr(scout, "SENT_PATH", tmp_path / "data" / "sent_jobs.json")
    monkeypatch.setattr(scout, "CV_DASHBOARD_DIR", tmp_path / "dashboards")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    missing_config = tmp_path / "does-not-exist.json"
    out_path = tmp_path / "out.json"
    argv = [
        "scout.py", "--dry-run", "--cv", str(cv_pdf), "--sources", "",
        "--json-out", str(out_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)

    import buckets as buckets_mod

    monkeypatch.setattr(buckets_mod, "DEFAULT_CONFIG", missing_config)

    rc = scout.main()
    assert rc == 0
    assert out_path.exists()
