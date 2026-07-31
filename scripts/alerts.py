#!/usr/bin/env python3
"""Per-CV Telegram alerting for scheduled scans.

The sole sender for scheduled runs. scout.py contains a second, older alerting
path (a global data/sent_jobs.json, dedupe applied before ranking instead of
thresholding after it, its own --top cut and its own dashboard write). That path
is unreachable from the cron -- --json-out returns before it -- and stays
exactly as it is for manual CLI use. It is deliberately not extended here: two
senders with two notions of "already sent" drift into disagreeing, and the one
that loses is the one you find out about when an alert never arrives.

Thresholds on match_pct, never on fit. fit is set by llm_rerank(), which only
runs when NVIDIA_API_KEY is present, so a fit-based cutoff sends nothing at all
on a keyless runner -- and sends nothing silently.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scout import esc, fingerprint, resolve_telegram, send_telegram  # noqa: E402

# How long a sent record suppresses re-alerting. Unbounded, the file grows
# forever on a branch nothing ever prunes, and a genuine repost months later is
# silently swallowed.
SENT_TTL_DAYS = 90


def job_fingerprint(job: dict) -> str:
    """The same company|title hash scout.py uses, so a fingerprint means the
    same thing on both sides of the pipeline."""
    return fingerprint({"company": job.get("company"), "title": job.get("title")})


def expire_sent(sent: dict, today: str) -> dict:
    cutoff = date.fromisoformat(today) - timedelta(days=SENT_TTL_DAYS)
    kept = {}
    for fp, entry in sent.items():
        try:
            if date.fromisoformat(entry["sent_date"]) >= cutoff:
                kept[fp] = entry
        except (KeyError, TypeError, ValueError):
            # An entry with no readable date cannot be aged out on evidence.
            # Keep it: over-suppressing one ad beats re-alerting a whole file.
            kept[fp] = entry
    return kept


def select_alerts(jobs: list[dict], sent: dict, min_match: int) -> list[dict]:
    return [
        j for j in jobs
        if (j.get("match_pct") or 0) >= min_match
        and job_fingerprint(j) not in sent
    ]


def format_alert(cv_id: str, jobs: list[dict]) -> str:
    lines = [f"<b>🎯 {esc(cv_id)} — {len(jobs)} new match(es)</b>", ""]
    for j in jobs:
        url = j.get("apply_url") or ""
        salary = j.get("salary")
        lines.append(
            f"<b>{j.get('match_pct')}%</b> · <a href=\"{esc(str(url))}\">"
            f"{esc(j.get('title') or 'Untitled')}</a>\n"
            f"{esc(j.get('company') or '—')} · {esc(j.get('location') or '—')}"
            + (f" · {esc(str(salary))}" if salary else "")
        )
        lines.append("")
    return "\n".join(lines).strip()


def run(results_path: Path, sent_path: Path, min_match: int,
        token: str, chat_id: str, send=send_telegram,
        today: str | None = None) -> int:
    """Alert on one CV's results. Returns how many ads were pushed."""
    today = today or date.today().isoformat()
    payload = json.loads(results_path.read_text())
    jobs = payload.get("jobs") or []
    cv_id = sent_path.stem

    # A missing sent file is this CV's very first scan. Pushing then would mean
    # 4 CVs x up to 50 matches on day one. Record the backlog and push nothing;
    # the dashboard still shows the full board immediately.
    quiet = not sent_path.exists()
    sent = {} if quiet else json.loads(sent_path.read_text())
    sent = expire_sent(sent, today)

    if quiet:
        to_record, pushed = jobs, 0
    else:
        to_record = select_alerts(jobs, sent, min_match)
        pushed = len(to_record)
        if to_record:
            # Sent first, recorded second: a failed push must leave the ads
            # pending rather than marked as delivered.
            send(token, chat_id, format_alert(cv_id, to_record))

    for j in to_record:
        sent[job_fingerprint(j)] = {
            "sent_date": today,
            "title": j.get("title") or "",
            "company": j.get("company") or "",
        }
    sent_path.parent.mkdir(parents=True, exist_ok=True)
    sent_path.write_text(json.dumps(sent, indent=2, sort_keys=True))
    return pushed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--sent", type=Path, required=True,
                        help="per-CV sent-state file; its stem is the CV id")
    parser.add_argument("--min-match", type=int, default=75)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the message instead of sending it")
    parser.add_argument("--telegram", choices=["dev", "main"], default="main")
    args = parser.parse_args()

    if args.dry_run:
        def send(token, chat_id, message):
            print(message)
        token, chat_id = "", ""
    else:
        send = send_telegram
        # A deliberately nonexistent config path: resolve_telegram() falls back
        # to a personal machine's config.json when the env vars are missing, and
        # on a runner that must fail loudly naming the missing secret rather
        # than reaching for a file that will never be there.
        token, chat_id = resolve_telegram(args.telegram, Path("/nonexistent"))

    pushed = run(args.results, args.sent, args.min_match, token, chat_id, send=send)
    print(f"[alerts] {args.sent.stem}: pushed {pushed}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
