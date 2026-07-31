"""What the cron is contractually forbidden to publish.

Every scout-data commit to date carries model-GENERATED employer cons about
named real companies ("management churn", "low pay") inside latest.json, on a
public branch, with company_reviews.py's own "may invent something plausible for
a small company" caveat living only in the dashboard UI.

Dropping --company-reviews from the cron removes the source. Stripping the key
on write means a hand-run local scan piped through the same helper cannot leak
it either.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import publish


def test_company_review_is_stripped_even_when_present(tmp_path):
    src = tmp_path / "raw.json"
    src.write_text(json.dumps({
        "generated_at": "2026-07-31T05:10:00", "cv": "x", "total_matches": 1,
        "jobs": [{"title": "T", "company": "Bosch", "match_pct": 80,
                  "company_review": {"company": "Bosch", "pros": ["p"],
                                     "cons": ["management churn"],
                                     "summary": "s", "source": "model",
                                     "generated_at": "2026-07-31"}}],
    }))
    dst = tmp_path / "results" / "backend-streaming.json"
    assert publish.strip_and_write(src, dst) == 1

    out = json.loads(dst.read_text())
    assert "company_review" not in out["jobs"][0]
    assert out["jobs"][0]["title"] == "T"


def test_a_clean_payload_survives_unchanged(tmp_path):
    src = tmp_path / "raw.json"
    payload = {"generated_at": "2026-07-31T05:10:00", "cv": "x",
               "total_matches": 1,
               "jobs": [{"title": "T", "company": "Bosch", "match_pct": 80}]}
    src.write_text(json.dumps(payload))
    dst = tmp_path / "results" / "backend-streaming.json"
    publish.strip_and_write(src, dst)
    assert json.loads(dst.read_text()) == payload


def test_stripping_survives_a_null_review_and_an_empty_job_list(tmp_path):
    src = tmp_path / "raw.json"
    src.write_text(json.dumps({
        "generated_at": "x", "cv": "x", "total_matches": 0,
        "jobs": [{"title": "T", "company_review": None}],
    }))
    dst = tmp_path / "results" / "a.json"
    publish.strip_and_write(src, dst)
    assert "company_review" not in json.loads(dst.read_text())["jobs"][0]


def test_run_record_carries_slot_status_attempts_and_count(tmp_path):
    path = tmp_path / "runs" / "backend-streaming.json"
    publish.write_run(path, slot="2026-07-31T05:00:00+00:00", status="ok",
                      attempts=1, matches=42,
                      finished_at="2026-07-31T06:04:11+00:00")
    assert json.loads(path.read_text()) == {
        "slot": "2026-07-31T05:00:00+00:00", "status": "ok", "attempts": 1,
        "matches": 42, "finished_at": "2026-07-31T06:04:11+00:00",
    }


def test_a_run_record_round_trips_through_the_due_check(tmp_path):
    """The record publish.py writes must be the shape cv_schedule.py reads.
    These two are the only writer and the only reader; if they disagree the
    symptom is a scan that silently repeats or silently never runs."""
    import cv_schedule
    from datetime import datetime, timezone

    runs = tmp_path / "runs"
    slot = datetime(2026, 7, 31, 5, tzinfo=timezone.utc)
    publish.write_run(runs / "backend-streaming.json", slot=slot.isoformat(),
                      status="ok", attempts=1, matches=42,
                      finished_at="2026-07-31T06:04:11+00:00")

    profile = {"id": "backend-streaming", "enabled": True,
               "schedule": {"hours_utc": [5], "weekdays_only": False}}
    run = cv_schedule.load_run(runs, "backend-streaming")
    assert run is not None
    assert cv_schedule.is_due(profile, datetime(2026, 7, 31, 6, 4,
                                                tzinfo=timezone.utc), run) is False
