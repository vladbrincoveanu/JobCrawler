#!/usr/bin/env python3
"""Prepare one CV's scan for the public scout-data branch.

Two jobs, both about what is allowed to become world-readable:

  * company_review is stripped unconditionally. It is model-GENERATED text about
    named real employers -- "management churn", "low pay" -- carrying a "may
    invent something plausible for a small company" caveat that lives only in
    the dashboard UI. The cron no longer passes --company-reviews, so the field
    should not be there at all; stripping on write means a hand-run local scan
    piped through here cannot leak it either.

  * the run record is written by exactly one function, so the due-check
    (cv_schedule.load_run) and the dashboard status strip read a shape that has
    one author. A disagreement between writer and reader here does not crash --
    it silently repeats or silently skips a scan.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Removed from every job before publishing. Adding to this list is cheap;
# noticing a leak after the fact is not, because a public branch's history stays
# readable even after the field stops being written.
FORBIDDEN_JOB_KEYS = ("company_review",)


def strip_and_write(src: Path, dst: Path) -> int:
    payload = json.loads(src.read_text())
    for job in payload.get("jobs", []):
        for key in FORBIDDEN_JOB_KEYS:
            job.pop(key, None)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(payload, indent=2))
    return len(payload.get("jobs", []))


def write_run(path: Path, slot: str, status: str, attempts: int,
              matches: int, finished_at: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "slot": slot, "status": status, "attempts": attempts,
        "matches": matches, "finished_at": finished_at,
    }, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    results = sub.add_parser("results")
    results.add_argument("--src", type=Path, required=True)
    results.add_argument("--dst", type=Path, required=True)

    run = sub.add_parser("run")
    run.add_argument("--path", type=Path, required=True)
    run.add_argument("--slot", required=True)
    run.add_argument("--status", choices=["ok", "error"], required=True)
    run.add_argument("--attempts", type=int, required=True)
    run.add_argument("--matches", type=int, default=0)
    run.add_argument("--finished-at", required=True)

    args = parser.parse_args()
    if args.cmd == "results":
        print(strip_and_write(args.src, args.dst))
    else:
        write_run(args.path, args.slot, args.status, args.attempts,
                  args.matches, args.finished_at)
    return 0


if __name__ == "__main__":
    sys.exit(main())
