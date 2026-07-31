"""Tests for the hourly due-check.

The failure mode this guards is silent. GitHub routinely delays scheduled
workflows on public repos by 5-20 minutes and drops ticks entirely under load.
An `hour in hours_utc` equality test would let a 05:00 scan that fires at 06:04
vanish with no error anywhere -- no alert, no log line, nothing on the board.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import cv_schedule


def at(hour, minute=0, day=31):
    return datetime(2026, 7, day, hour, minute, tzinfo=timezone.utc)


PROFILE = {
    "id": "backend-streaming",
    "enabled": True,
    "schedule": {"hours_utc": [5], "weekdays_only": False},
}


def test_due_slot_is_the_newest_hour_at_or_before_now():
    assert cv_schedule.due_slot([5, 15], at(16)) == at(15)
    assert cv_schedule.due_slot([5, 15], at(6)) == at(5)


def test_due_slot_before_the_first_hour_of_the_day_uses_yesterdays_last_slot():
    assert cv_schedule.due_slot([5, 15], at(2)) == at(15, day=30)


def test_due_slot_of_an_empty_schedule_is_none():
    assert cv_schedule.due_slot([], at(6)) is None


def test_runs_on_its_hour():
    assert cv_schedule.is_due(PROFILE, at(5, 2), run=None) is True


def test_a_wake_at_0604_still_runs_the_0500_slot():
    """The regression test for exact-hour matching."""
    assert cv_schedule.is_due(PROFILE, at(6, 4), run=None) is True


def test_a_slot_older_than_the_window_is_abandoned():
    assert cv_schedule.is_due(PROFILE, at(11, 30), run=None) is False


def test_a_disabled_profile_never_runs():
    assert cv_schedule.is_due({**PROFILE, "enabled": False}, at(5, 2), run=None) is False


def test_a_slot_already_succeeded_does_not_run_again():
    run = {"slot": at(5).isoformat(), "status": "ok", "attempts": 1}
    assert cv_schedule.is_due(PROFILE, at(6, 4), run) is False


def test_a_failed_slot_is_retried_exactly_once():
    failed = {"slot": at(5).isoformat(), "status": "error", "attempts": 1}
    assert cv_schedule.is_due(PROFILE, at(6, 4), failed) is True
    exhausted = {"slot": at(5).isoformat(), "status": "error", "attempts": 2}
    assert cv_schedule.is_due(PROFILE, at(7, 4), exhausted) is False


def test_a_new_slot_resets_the_attempt_count():
    """Yesterday's exhausted failure must not suppress today's scan."""
    exhausted = {"slot": at(5, day=30).isoformat(), "status": "error", "attempts": 2}
    assert cv_schedule.is_due(PROFILE, at(5, 2), exhausted) is True


def test_weekdays_only_skips_the_weekend():
    weekday_profile = {**PROFILE, "schedule": {"hours_utc": [5], "weekdays_only": True}}
    saturday = datetime(2026, 8, 1, 5, 2, tzinfo=timezone.utc)
    assert cv_schedule.is_due(weekday_profile, saturday, run=None) is False
    assert cv_schedule.is_due(weekday_profile, at(5, 2), run=None) is True  # Friday


def test_select_due_reads_profiles_and_runs_from_disk(tmp_path):
    (tmp_path / "runs").mkdir()
    profiles = tmp_path / "profiles.json"
    profiles.write_text(json.dumps({"version": 1, "profiles": [
        PROFILE,
        {"id": "devops-sre", "enabled": False, "schedule": {"hours_utc": [5]}},
        {"id": "ai-agentic", "enabled": True, "schedule": {"hours_utc": [15]}},
    ]}))
    (tmp_path / "runs" / "backend-streaming.json").write_text(
        json.dumps({"slot": at(5).isoformat(), "status": "ok", "attempts": 1}))

    due = cv_schedule.select_due(profiles, tmp_path / "runs", at(6, 4))
    assert due == []   # backend already ran, devops disabled, ai-agentic not due yet

    due = cv_schedule.select_due(profiles, tmp_path / "runs", at(15, 30))
    assert due == ["ai-agentic"]


def test_shell_filters_are_quoted_so_a_hostile_value_cannot_inject():
    """The workflow `eval`s this. An unquoted sources string would be a command
    injection from a file anyone can send a pull request against."""
    out = cv_schedule.shell_filters({
        "filters": {"days": 7, "top": 50, "require_salary": True,
                    "sources": "apis; rm -rf /"},
        "alert": {"min_match": 80},
    })
    assert "F_DAYS=7" in out
    assert "F_REQUIRE_SALARY=1" in out
    assert "F_MIN_MATCH=80" in out
    assert "'apis; rm -rf /'" in out          # quoted, not bare
    assert "\nF_SOURCES=apis;" not in out


def test_shell_filters_fall_back_to_the_documented_defaults():
    out = cv_schedule.shell_filters({})
    assert "F_DAYS=7" in out and "F_TOP=50" in out and "F_MIN_MATCH=75" in out
    assert "F_REQUIRE_SALARY=''" in out


def test_select_due_tolerates_a_corrupt_run_file(tmp_path):
    """A half-written runs/<id>.json must not wedge the CV forever."""
    (tmp_path / "runs").mkdir()
    profiles = tmp_path / "profiles.json"
    profiles.write_text(json.dumps({"version": 1, "profiles": [PROFILE]}))
    (tmp_path / "runs" / "backend-streaming.json").write_text("{ truncated")

    assert cv_schedule.select_due(profiles, tmp_path / "runs", at(5, 30)) == \
        ["backend-streaming"]
