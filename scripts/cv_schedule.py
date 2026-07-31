#!/usr/bin/env python3
"""Which CV profiles are due to scan right now.

Called once per hourly wake by .github/workflows/scout-cron.yml. Kept out of the
workflow YAML deliberately: the interesting cases here -- a delayed tick, a
retried failure, a corrupt state file -- are exactly the ones that need tests,
and bash inside YAML cannot have any.

Named cv_schedule, not schedule: the test suite puts scripts/ at the front of
sys.path, where a module called `schedule` would shadow the PyPI package of that
name for anything else importing it.
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# How long after its scheduled hour a slot may still be picked up. GitHub delays
# scheduled workflows on public repos by 5-20+ minutes routinely and drops ticks
# entirely under load; exact-hour matching loses that day's scan silently. Six
# hours is "the next few wakes can still catch it" without a missed midnight slot
# firing at lunchtime.
WINDOW_HOURS = 6

# One retry, then the slot is abandoned until its next scheduled hour. Zero
# retries means a transient network blip costs a whole day; unbounded retries
# mean a hard failure re-runs every hour for the whole window.
MAX_ATTEMPTS = 2


def due_slot(hours_utc: list[int], now: datetime) -> datetime | None:
    """The newest scheduled slot at or before `now`, or None if unscheduled."""
    hours = sorted({int(h) for h in hours_utc if 0 <= int(h) <= 23})
    if not hours:
        return None
    today = now.replace(minute=0, second=0, microsecond=0)
    for hour in reversed(hours):
        candidate = today.replace(hour=hour)
        if candidate <= now:
            return candidate
    # Before the first slot of the day: the newest slot is yesterday's last.
    return (today - timedelta(days=1)).replace(hour=hours[-1])


def is_due(profile: dict, now: datetime, run: dict | None) -> bool:
    if not profile.get("enabled", True):
        return False
    schedule = profile.get("schedule") or {}
    slot = due_slot(schedule.get("hours_utc") or [], now)
    if slot is None:
        return False
    if schedule.get("weekdays_only") and slot.weekday() >= 5:
        return False
    if now - slot > timedelta(hours=WINDOW_HOURS):
        return False
    if not run or run.get("slot") != slot.isoformat():
        return True          # never attempted this slot
    if run.get("status") == "ok":
        return False
    return int(run.get("attempts") or 0) < MAX_ATTEMPTS


def load_run(runs_dir: Path, cv_id: str) -> dict | None:
    path = runs_dir / f"{cv_id}.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        # A missing file is the normal first-run state; a truncated one is a
        # half-finished push. Both mean "no trustworthy record", and treating
        # them as "never ran" re-runs the scan, which is recoverable. Treating
        # them as "ran fine" would wedge this CV until someone noticed.
        return None


def select_due(profiles_path: Path, runs_dir: Path, now: datetime) -> list[str]:
    doc = json.loads(profiles_path.read_text())
    return [
        p["id"] for p in doc.get("profiles", [])
        if is_due(p, now, load_run(runs_dir, p["id"]))
    ]


def attempts_for(run: dict | None, slot: datetime) -> int:
    """Attempt number to record for `slot`, given the previous run record."""
    if run and run.get("slot") == slot.isoformat():
        return int(run.get("attempts") or 0) + 1
    return 1


def shell_filters(profile: dict) -> str:
    """This CV's filters as shell-quoted assignments, for `eval` in the workflow.

    Lives here rather than as an inline heredoc in the YAML for two reasons: a
    heredoc terminator inside a YAML block scalar is indentation-sensitive and
    easy to get subtly wrong, and anything living in the YAML is untestable.
    Quoting is not cosmetic -- the workflow evals the result, so an unquoted
    `sources` string would be a command injection from a config file that anyone
    can send a pull request against.
    """
    f = profile.get("filters") or {}
    alert = profile.get("alert") or {}
    return "\n".join([
        f"F_DAYS={shlex.quote(str(f.get('days', 7)))}",
        f"F_TOP={shlex.quote(str(f.get('top', 50)))}",
        f"F_SOURCES={shlex.quote(str(f.get('sources', 'apis,karriere,adzuna,jooble')))}",
        f"F_REQUIRE_SALARY={shlex.quote('1' if f.get('require_salary') else '')}",
        f"F_MIN_MATCH={shlex.quote(str(alert.get('min_match', 75)))}",
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--now", default=None,
                        help="ISO-8601 UTC instant; defaults to now (tests pass one)")
    parser.add_argument("--slot-for", default=None,
                        help="print the due slot of this CV id instead of the due list")
    parser.add_argument("--filters-for", default=None,
                        help="print this CV's filters as shell-quoted assignments")
    parser.add_argument("--all-enabled", action="store_true",
                        help="print every enabled CV id, ignoring schedules "
                             "(the workflow's manual 'force' input)")
    args = parser.parse_args()

    if args.filters_for:
        doc = json.loads(args.profiles.read_text())
        print(shell_filters(
            next(p for p in doc["profiles"] if p["id"] == args.filters_for)))
        return 0

    if args.all_enabled:
        doc = json.loads(args.profiles.read_text())
        for p in doc.get("profiles", []):
            if p.get("enabled", True):
                print(p["id"])
        return 0

    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if args.slot_for:
        doc = json.loads(args.profiles.read_text())
        profile = next(p for p in doc["profiles"] if p["id"] == args.slot_for)
        slot = due_slot((profile.get("schedule") or {}).get("hours_utc") or [], now)
        run = load_run(args.runs_dir, args.slot_for)
        print(json.dumps({"slot": slot.isoformat() if slot else None,
                          "attempts": attempts_for(run, slot) if slot else 0}))
        return 0

    for cv_id in select_due(args.profiles, args.runs_dir, now):
        print(cv_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
