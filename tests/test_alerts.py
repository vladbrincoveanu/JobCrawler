"""Tests for the per-CV alerting sender.

Three failure modes drive this file, all of them silent in production:

  1. Thresholding on `fit` instead of `match_pct` sends nothing on a keyless
     runner, because llm_rerank() only sets `fit` when NVIDIA_API_KEY exists.
  2. A shared sent-store suppresses an ad on CV B because CV A alerted it.
  3. A first run with no sent-state pushes 4 CVs x up to 50 matches to Telegram.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import alerts


def job(title, company, match_pct, **extra):
    return {"title": title, "company": company, "match_pct": match_pct,
            "location": "Wien", "posted": "2026-07-30",
            "apply_url": f"https://example.com/{title}", **extra}


@pytest.fixture
def results(tmp_path):
    path = tmp_path / "results.json"
    path.write_text(json.dumps({
        "generated_at": "2026-07-31T05:10:00",
        "cv": "scout/profiles/backend-streaming.json",
        "total_matches": 3,
        "jobs": [
            job("Senior .NET Engineer", "Bosch", 86),
            job("Backend Engineer", "Runtastic", 74),
            job("Java Developer", "Erste", 91),
        ],
    }))
    return path


class FakeSender:
    def __init__(self):
        self.messages = []

    def __call__(self, token, chat_id, message):
        self.messages.append(message)


def test_selects_only_matches_at_or_above_the_threshold(results):
    picked = alerts.select_alerts(json.loads(results.read_text())["jobs"], {}, 75)
    assert [j["title"] for j in picked] == ["Senior .NET Engineer", "Java Developer"]


def test_threshold_uses_match_pct_not_fit(results):
    """Regression: with no NVIDIA_API_KEY no job has `fit`, and a fit-based
    threshold would send nothing at all, silently."""
    jobs = json.loads(results.read_text())["jobs"]
    assert all("fit" not in j for j in jobs)
    assert len(alerts.select_alerts(jobs, {}, 75)) == 2


def test_already_sent_fingerprints_are_dropped(results):
    jobs = json.loads(results.read_text())["jobs"]
    sent = {alerts.job_fingerprint(jobs[0]): {"sent_date": "2026-07-30",
                                              "title": jobs[0]["title"],
                                              "company": jobs[0]["company"]}}
    picked = alerts.select_alerts(jobs, sent, 75)
    assert [j["title"] for j in picked] == ["Java Developer"]


def test_entries_older_than_90_days_are_dropped_on_write():
    sent = {
        "old": {"sent_date": "2026-01-01", "title": "Stale", "company": "X"},
        "fresh": {"sent_date": "2026-07-30", "title": "Fresh", "company": "Y"},
    }
    kept = alerts.expire_sent(sent, today="2026-07-31")
    assert set(kept) == {"fresh"}


def test_an_expired_ad_alerts_again(results):
    """A genuine repost 90+ days later is news, not a duplicate."""
    jobs = json.loads(results.read_text())["jobs"]
    fp = alerts.job_fingerprint(jobs[0])
    sent = alerts.expire_sent(
        {fp: {"sent_date": "2026-01-01", "title": "old", "company": "old"}},
        today="2026-07-31")
    assert [j["title"] for j in alerts.select_alerts(jobs, sent, 75)] == \
        ["Senior .NET Engineer", "Java Developer"]


def test_quiet_first_run_records_everything_and_sends_nothing(results, tmp_path):
    sender = FakeSender()
    sent_path = tmp_path / "sent" / "backend-streaming.json"
    sent_count = alerts.run(results, sent_path, min_match=75,
                            token="t", chat_id="c", send=sender)

    assert sender.messages == []
    assert sent_count == 0
    recorded = json.loads(sent_path.read_text())
    assert len(recorded) == 3          # every match, not just the two above 75
    assert all(v["title"] for v in recorded.values())


def test_the_second_run_sends_only_new_matches(results, tmp_path):
    sender = FakeSender()
    sent_path = tmp_path / "sent" / "backend-streaming.json"
    alerts.run(results, sent_path, 75, "t", "c", send=sender)      # quiet

    results.write_text(json.dumps({
        "generated_at": "2026-08-01T05:10:00", "cv": "x", "total_matches": 1,
        "jobs": [job("Staff Engineer", "Dynatrace", 80),
                 job("Senior .NET Engineer", "Bosch", 86)],
    }))
    sent_count = alerts.run(results, sent_path, 75, "t", "c", send=sender)

    assert sent_count == 1
    assert len(sender.messages) == 1
    assert "Staff Engineer" in sender.messages[0]
    assert "Senior .NET Engineer" not in sender.messages[0]


def test_sent_state_is_isolated_per_cv(results, tmp_path):
    """The case the whole per-CV design exists for: one ad, two CVs, two alerts."""
    sender = FakeSender()
    for cv_id in ("backend-streaming", "devops-sre"):
        path = tmp_path / "sent" / f"{cv_id}.json"
        alerts.run(results, path, 75, "t", "c", send=sender)          # quiet first
        alerts.run(results, path, 75, "t", "c", send=sender)          # nothing new

    backend = json.loads((tmp_path / "sent" / "backend-streaming.json").read_text())
    devops = json.loads((tmp_path / "sent" / "devops-sre.json").read_text())
    assert set(backend) == set(devops)
    assert sender.messages == []

    # A third CV that has never seen this ad still alerts on its own first
    # non-quiet run, even though the other two have it recorded.
    fresh = tmp_path / "sent" / "ai-agentic.json"
    fresh.parent.mkdir(parents=True, exist_ok=True)
    fresh.write_text("{}")                # exists but empty: not a first run
    assert alerts.run(results, fresh, 75, "t", "c", send=sender) == 2


def test_a_send_failure_does_not_record_the_fingerprints(results, tmp_path):
    """The workflow writes results/ before pushing; if the push fails the ads
    must still be pending, not marked as delivered."""
    def boom(token, chat_id, message):
        raise RuntimeError("Telegram send failed: 502")

    sent_path = tmp_path / "sent" / "backend-streaming.json"
    sent_path.parent.mkdir(parents=True)
    sent_path.write_text("{}")
    with pytest.raises(RuntimeError):
        alerts.run(results, sent_path, 75, "t", "c", send=boom)
    assert json.loads(sent_path.read_text()) == {}


def test_message_states_the_match_percentage_and_links_the_ad(results, tmp_path):
    sender = FakeSender()
    sent_path = tmp_path / "sent" / "backend-streaming.json"
    sent_path.parent.mkdir(parents=True)
    sent_path.write_text("{}")
    alerts.run(results, sent_path, 75, "t", "c", send=sender)

    body = sender.messages[0]
    assert "91%" in body and "Java Developer" in body
    assert "https://example.com/Java Developer" in body


def test_an_entry_with_an_unreadable_date_is_kept_not_dropped():
    """Over-suppressing one ad beats re-alerting a whole file because one entry
    was written by an older version."""
    sent = {"weird": {"title": "T", "company": "C"}}
    assert alerts.expire_sent(sent, today="2026-07-31") == sent
