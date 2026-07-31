# Multi-CV Scout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the single-CV scout into N CV profiles, each with its own schedule, filters, alert threshold and per-CV sent-state, driven from one dashboard and an hourly GitHub Actions cron.

**Architecture:** CV PDFs stay local and are never committed; only a ~600-byte derived profile (`{skills, role_titles, source}`) reaches the public repo, gated by a key whitelist in code. An hourly workflow reads `scout/profiles.json`, asks a pure Python due-checker which CVs to run, scans each with `scout.py --profile`, publishes per-CV results to the `scout-data` orphan branch, and alerts via `scripts/alerts.py` — the sole sender, keyed on `match_pct`.

**Tech Stack:** Python 3.12 (`scripts/*.py`, pytest), Next.js 15 App Router + React 18 + Tailwind (`dashboard/`), Playwright, GitHub Actions.

**Source spec:** `docs/superpowers/specs/2026-07-31-multi-cv-scout-design.md` (status: approved).

---

## Deviations from the spec (decided while planning, with reasons)

These are deliberate. Anyone executing this plan should know why the code will not
match the spec's letter in these seven places.

| # | Spec says | Plan does | Why |
|---|---|---|---|
| D1 | Due-check lives in the workflow (`Modules` lists only `scout-cron.yml`) | Due-check is `scripts/cv_schedule.py`, a pure function + thin CLI; the YAML only calls it | The spec's Testing section demands five pytest cases for due-check. Logic in bash inside YAML cannot be unit-tested, and the 06:04-runs-the-05:00-slot case is exactly the kind that only a test catches. Module named `cv_schedule` not `schedule` because tests do `sys.path.insert(0, "scripts")` and a bare `schedule.py` would shadow the PyPI package of that name for anything else on the path. |
| D2 | `--profile-only <pdf>` "extracts a profile, writes it, and exits" — destination unstated | Writes to the existing `data/profiles/<digest>.json` cache and prints that path on stdout; `lib/cvProfiles.ts` reads it, sanitises it, and writes `scout/profiles/<id>.json` | Keeps exactly one PII gate, in TypeScript, on the only code path that writes the public directory. A second writer in Python would be a second thing to audit. Honours "only these two new flags". |
| D3 | Container reads the feed via `SCOUT_FEED_URL` | Adds `SCOUT_FEED_BASE_URL` (branch raw base; `feed.ts` appends `results/<id>.json`); `SCOUT_FEED_URL` kept, unchanged, for the single-feed case and the existing tests | Per-CV feeds need per-CV URLs. One base URL beats N env vars. |
| D4 | `lib/cvProfiles.ts` resolves the repo root from `SCOUT_REPO_ROOT` | Resolves `SCOUT_CONFIG_ROOT ?? SCOUT_REPO_ROOT ?? cwd/..` | Playwright must redirect config *writes* into a fixture tree, but `app/api/scout/route.ts` uses `SCOUT_REPO_ROOT` to locate `scripts/scout.py`. Sharing one var means pointing the config tests at a fixture also breaks the live-scan spec. |
| D5 | PII gate "strips to exactly `{skills, role_titles, source}` **and** hard-fails on any other key" | Hard-fails only. Nothing is silently stripped | The two halves contradict each other. Failing loud is project rule 12; a silent strip is how an unnoticed field arrives. |
| D6 | "The nav collapses to a single entry" (route unstated) | The single entry is `/scout`, relabelled **Dashboard**. `/`, `/jobs`, `/runs`, `/matches` keep working by URL, unlinked | `/scout` already owns upload + scan; the board is a component that moves into it. |
| D7 | "Coverage gate stays at ≥90% (`--cov=crawler`)" | Gate unchanged and re-run, but the plan states plainly that it measures **nothing added here** | `pyproject.toml` sets `source = ["crawler"]`, `omit = ["scripts/*"]`. Every Python file in this plan lives in `scripts/`. Claiming "coverage held at 90%" as evidence the new code is tested would be false. The new pytest tests are the evidence; the gate is a no-regression check on the crawler. |

## Two collisions to be aware of before touching anything

1. **`scout/` means two different things on two different branches.** On `main` it is committed config (`scout/profiles.json`, `scout/profiles/<id>.json`). On the `scout-data` orphan branch it is published output (`scout/latest.json`, today). Because the publish step does `git checkout -B scout-data` *in the same working tree*, `main`'s `scout/profiles.json` sits there as an untracked file during the publish. Task 12 therefore publishes to `results/`, `sent/`, `runs/` at the branch root (as the spec's state table already says) and `git add`s only explicit paths — never `git add .`, never `git add scout/`.
2. **`scout/latest.json` on the data branch is the current feed** and `docker-compose.yml` + `/matches` may be pointed at it. Task 12 keeps writing it (a copy of the first enabled CV's results) for one release so nothing that reads it breaks mid-migration, and marks it deprecated in the workflow comment.

---

## File structure

**Create**
| Path | Responsibility |
|---|---|
| `scout/profiles.json` | Committed config: the profile list. Public. |
| `scout/README.md` | The "everything in here is world-readable" header. |
| `scripts/cv_schedule.py` | Pure due-check + CLI. ~110 lines. |
| `scripts/alerts.py` | Threshold, per-CV sent-state, Telegram push. Sole sender. ~150 lines. |
| `dashboard/lib/cvProfiles.ts` | Read/validate/write `scout/`. PII gate. ~180 lines. |
| `dashboard/lib/credentials.ts` | Write `.env.local` only. ~100 lines. |
| `dashboard/app/api/cv/route.ts` | CRUD one CV. ~170 lines. |
| `dashboard/app/api/scout/stream/route.ts` | Scan one CV, stream stderr as SSE. ~150 lines. |
| `dashboard/components/CvSwitcher.tsx` | Pick / create a CV. ~120 lines. |
| `dashboard/components/CvSettings.tsx` | Schedule, filters, threshold. ~200 lines. |
| `tests/test_cv_schedule.py`, `tests/test_alerts.py`, `tests/test_scout_profile_flag.py` | pytest. |
| `dashboard/tests/cv-dashboard.spec.ts` | Playwright. |
| `dashboard/tests/fixtures/config-root/` | Hermetic write target for config tests. |

**Modify**
| Path | Change |
|---|---|
| `scripts/scout.py` | `--profile`, `--profile-only`; `--company-reviews` unchanged. |
| `dashboard/lib/feed.ts` | Per-CV load: `SCOUT_FEED_BASE_URL`, `loadFeed(cvId?)`. |
| `dashboard/app/scout/page.tsx` | Becomes the one dashboard. |
| `dashboard/components/Nav.tsx` | One link. |
| `.github/workflows/scout-cron.yml` | Hourly, due-check, N CVs, per-CV publish + alert, no `--company-reviews`. |
| `docker-compose.yml` | `SCOUT_FEED_BASE_URL`, read-only config notice. |
| `.claude/rules/ui-testing.md` | Real routes. |
| `dashboard/playwright.config.ts` | `SCOUT_CONFIG_ROOT` for the web server. |
| `README.md` | Multi-CV setup + `gh secret set`. |

---

## Phase 0 — unblock the gates

### Task 0: Fix the UI-testing rule so the final gate checks real routes

Risk 6 in the spec: the rule gates on `/dashboard` and `/dashboard/map`, which
this app has never served. Every "final gate" run so far verified nothing. The UI
work in Phase 3 is gated by this file, so it is fixed first.

**Files:**
- Modify: `.claude/rules/ui-testing.md:19`

- [ ] **Step 1: Replace the route list**

In the "Final gate" section, replace the line:

```
- Full suite once: `npx playwright test --reporter=line` — 0 failures, 0 console errors on `/`, `/dashboard`, `/dashboard/map`.
```

with:

```
- Full suite once: `npx playwright test --reporter=line` — 0 failures, 0 console errors on `/`, `/jobs`, `/runs`, `/scout`, `/matches`.
```

- [ ] **Step 2: Verify the named routes exist**

Run: `ls dashboard/app/page.tsx dashboard/app/jobs/page.tsx dashboard/app/runs/page.tsx dashboard/app/scout/page.tsx dashboard/app/matches/page.tsx`
Expected: all five listed, no "No such file".

- [ ] **Step 3: Commit**

```bash
git add .claude/rules/ui-testing.md
git commit -m "fix(rules): gate UI testing on routes this app actually serves"
```

---

## Phase 1 — Python core

### Task 1: `scout.py --profile` (use a committed profile, skip the PDF)

**Files:**
- Modify: `scripts/scout.py` (arg parser ~line 795, `main()` ~line 921)
- Test: `tests/test_scout_profile_flag.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scout_profile_flag.py`:

```python
"""Tests for --profile and --profile-only.

--profile is what every *scheduled* run uses: the runner has no PDF (the CV is
never committed and is too big for a 48KB Actions secret), only the ~600-byte
derived profile. --profile-only is the dashboard's "register a new CV" path:
extract and exit, so adding a CV costs a second instead of a full scan.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scout


@pytest.fixture
def profile_file(tmp_path):
    path = tmp_path / "backend.json"
    path.write_text(json.dumps({
        "skills": {"dotnet": 10, "kafka": 6},
        "role_titles": ["backend engineer", "software engineer"],
        "source": "llm",
    }))
    return path


def test_load_profile_file_returns_the_file_verbatim(profile_file):
    assert scout.load_profile_file(profile_file) == {
        "skills": {"dotnet": 10, "kafka": 6},
        "role_titles": ["backend engineer", "software engineer"],
        "source": "llm",
    }


def test_load_profile_file_rejects_a_profile_with_no_skills(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"skills": {}, "role_titles": ["x"], "source": "llm"}))
    with pytest.raises(ValueError, match="no skills"):
        scout.load_profile_file(path)


def test_load_profile_file_rejects_a_profile_with_no_role_titles(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"skills": {"dotnet": 10}, "role_titles": [], "source": "llm"}))
    with pytest.raises(ValueError, match="no role_titles"):
        scout.load_profile_file(path)


def test_profile_flag_never_reads_the_pdf(monkeypatch, tmp_path, profile_file):
    """The runner has no PDF at all. Reading one would crash the scheduled run."""
    def explode(_path):
        raise AssertionError("extract_cv_text must not be called with --profile")

    monkeypatch.setattr(scout, "extract_cv_text", explode)
    monkeypatch.setattr(scout, "fetch_free_apis", lambda *a, **k: [
        {"title": "Senior .NET Engineer", "company": "Bosch", "location": "Wien",
         "posted": "2026-07-30", "url": "https://example.com/1",
         "description": "dotnet kafka", "ats_type": "test"},
    ])
    out = tmp_path / "result.json"
    monkeypatch.setattr(sys, "argv", [
        "scout.py", "--profile", str(profile_file), "--sources", "apis",
        "--no-llm", "--json-out", str(out), "--top", "5",
    ])

    assert scout.main() == 0
    result = json.loads(out.read_text())
    assert result["cv"] == str(profile_file)
    assert result["profile_source"] == "llm"
    assert result["jobs"][0]["match_pct"] > 0


def test_profile_flag_scores_identically_to_the_pdf_path(monkeypatch, tmp_path, profile_file):
    """Same profile in, same score out -- the flag changes where the profile
    comes from, nothing else."""
    job = {"title": "Senior .NET Engineer", "company": "Bosch", "location": "Wien",
           "posted": "2026-07-30", "url": "https://example.com/1",
           "description": "dotnet kafka", "ats_type": "test"}
    profile = json.loads(profile_file.read_text())

    monkeypatch.setattr(scout, "fetch_free_apis", lambda *a, **k: [dict(job)])
    out_a = tmp_path / "a.json"
    monkeypatch.setattr(sys, "argv", [
        "scout.py", "--profile", str(profile_file), "--sources", "apis",
        "--no-llm", "--json-out", str(out_a),
    ])
    assert scout.main() == 0

    monkeypatch.setattr(scout, "load_profile", lambda *a, **k: profile)
    monkeypatch.setattr(scout, "fetch_free_apis", lambda *a, **k: [dict(job)])
    out_b = tmp_path / "b.json"
    monkeypatch.setattr(sys, "argv", [
        "scout.py", "--cv", str(tmp_path / "fake.pdf"), "--sources", "apis",
        "--no-llm", "--json-out", str(out_b),
    ])
    assert scout.main() == 0

    a, b = json.loads(out_a.read_text()), json.loads(out_b.read_text())
    assert [j["score"] for j in a["jobs"]] == [j["score"] for j in b["jobs"]]
    assert [j["match_pct"] for j in a["jobs"]] == [j["match_pct"] for j in b["jobs"]]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_scout_profile_flag.py -v`
Expected: FAIL — `AttributeError: module 'scout' has no attribute 'load_profile_file'`

- [ ] **Step 3: Add `load_profile_file` to `scripts/scout.py`**

Insert directly after `load_profile()` (which ends at line 207):

```python
def load_profile_file(path: Path) -> dict:
    """Load a pre-extracted profile, no PDF involved.

    Scheduled runs have no CV: the PDF is never committed (public repo) and is
    too large for an Actions secret (48KB cap, ~76KB base64). They read the
    committed profile instead, which also saves the parse and the LLM
    extraction call on every wake.

    Validated rather than trusted: an empty profile scores every job 0 and the
    run would publish an empty board with no error anywhere.
    """
    profile = json.loads(path.read_text())
    if not profile.get("skills"):
        raise ValueError(f"{path} has no skills; nothing to match against")
    if not profile.get("role_titles"):
        raise ValueError(f"{path} has no role_titles; no board can be searched")
    profile.setdefault("source", "file")
    return profile
```

- [ ] **Step 4: Add the two flags to `parse_args()`**

In `parse_args()`, immediately after the `--rebuild-profile` argument (line ~821):

```python
    parser.add_argument("--profile", type=Path, default=None,
                        help="use this already-extracted profile JSON instead of "
                             "reading --cv; skips PDF parsing and LLM extraction "
                             "entirely (this is what scheduled runs use -- the CV "
                             "never leaves the local machine)")
    parser.add_argument("--profile-only", type=Path, default=None,
                        help="extract a profile from this PDF, write it to the "
                             "data/profiles/ cache, print the path, and exit "
                             "without scanning")
```

- [ ] **Step 5: Wire both into `main()`**

Replace line 921 (`    profile = load_profile(args.cv, args.rebuild_profile)`) with:

```python
    if args.profile_only:
        # Register-a-new-CV path: extract and stop. The dashboard then reads the
        # printed path, strips it to the published whitelist, and commits it.
        path = _profile_cache_path(args.profile_only)
        load_profile(args.profile_only, args.rebuild_profile)
        print(path)
        return 0

    if args.profile:
        profile = load_profile_file(args.profile)
    else:
        profile = load_profile(args.cv, args.rebuild_profile)
```

Then, so the result payload names what was actually used, change the `"cv":`
line inside the `--json-out` result dict (line ~995) from:

```python
            "cv": str(args.cv),
```

to:

```python
            # What this run was actually matched against: the profile file for a
            # scheduled run, the PDF for a local one. Naming --cv unconditionally
            # printed a home-directory path that never existed on the runner.
            "cv": str(args.profile or args.cv),
```

**Note on ordering:** `--profile-only` must return *before* `load_buckets` and any
source fetching, but the bucket load at line 913 is harmless and already
degrades. Put the `--profile-only` block where line 921 was, as shown, so the
existing degraded-buckets behaviour is untouched.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_scout_profile_flag.py -v`
Expected: 5 passed

- [ ] **Step 7: Run the existing scout tests for regressions**

Run: `.venv/bin/python -m pytest tests/test_scout_json_out.py tests/test_match_evidence.py tests/test_cv_dashboards.py -q`
Expected: all pass, same count as before this task.

- [ ] **Step 8: Verify `--profile-only` end to end**

Run:
```bash
.venv/bin/python scripts/scout.py --profile-only data/cv/*.pdf 2>/dev/null | tail -1
```
Expected: a path like `data/profiles/<16-hex>.json` on stdout, and that file exists.
If `data/cv/` is empty, generate one first: `.venv/bin/python scripts/make_test_cv.py /tmp/cv.pdf` and use that path.

- [ ] **Step 9: Commit**

```bash
git add scripts/scout.py tests/test_scout_profile_flag.py
git commit -m "feat(scout): --profile and --profile-only, so scheduled runs need no PDF"
```

---

### Task 2: `scripts/cv_schedule.py` — the due-check

**Files:**
- Create: `scripts/cv_schedule.py`
- Test: `tests/test_cv_schedule.py`

State shape this task defines, referenced by Tasks 3 and 12:

```jsonc
// runs/<id>.json on the scout-data branch
{
  "slot": "2026-07-31T05:00:00+00:00",  // the scheduled hour this attempt was for
  "status": "ok",                        // "ok" | "error"
  "attempts": 1,                         // attempts made for THIS slot
  "finished_at": "2026-07-31T06:04:11+00:00",
  "matches": 42                          // published match count; 0 on error
}
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cv_schedule.py`:

```python
"""Tests for the hourly due-check.

The failure mode this guards is silent: GitHub routinely delays scheduled
workflows on public repos by 5-20 minutes and drops ticks under load. An
`hour in hours_utc` equality test would let a 05:00 scan that fires at 06:04
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
    saturday = datetime(2026, 8, 1, 5, 2, tzinfo=timezone.utc)   # 2026-08-01 is a Saturday
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cv_schedule.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cv_schedule'`

- [ ] **Step 3: Write `scripts/cv_schedule.py`**

```python
#!/usr/bin/env python3
"""Which CV profiles are due to scan right now.

Called once per hourly wake by .github/workflows/scout-cron.yml. Kept out of
the workflow YAML deliberately: the interesting cases here (a delayed tick, a
retried failure, a corrupt state file) are exactly the ones that need tests,
and bash inside YAML cannot have any.

Named cv_schedule, not schedule: tests put scripts/ at the front of sys.path,
where a module called `schedule` would shadow the PyPI package of that name.
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# How long after its scheduled hour a slot may still be picked up. GitHub
# delays scheduled workflows on public repos by 5-20+ minutes routinely and
# drops ticks entirely under load; exact-hour matching loses that day's scan
# silently. Six hours is "the next few wakes can still catch it" without a
# missed midnight slot firing at lunchtime.
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
        # them as "never ran" re-runs the scan -- which is recoverable. Treating
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
    easy to get subtly wrong, and anything in the YAML is untestable.
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
        print(shell_filters(next(p for p in doc["profiles"] if p["id"] == args.filters_for)))
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cv_schedule.py -v`
Expected: 15 passed

- [ ] **Step 5: Verify the CLI**

Run:
```bash
mkdir -p /tmp/duetest/runs
cat > /tmp/duetest/profiles.json <<'JSON'
{"version": 1, "profiles": [{"id": "backend-streaming", "enabled": true,
  "schedule": {"hours_utc": [5], "weekdays_only": false}}]}
JSON
.venv/bin/python scripts/cv_schedule.py --profiles /tmp/duetest/profiles.json \
  --runs-dir /tmp/duetest/runs --now 2026-07-31T06:04:00+00:00
```
Expected: `backend-streaming`

Run the same command with `--now 2026-07-31T12:00:00+00:00`.
Expected: no output (slot is 7h old, past the window).

- [ ] **Step 6: Commit**

```bash
git add scripts/cv_schedule.py tests/test_cv_schedule.py
git commit -m "feat(scout): hourly due-check with a 6h window and one retry"
```

---

### Task 3: `scripts/alerts.py` — the only sender

**Files:**
- Create: `scripts/alerts.py`
- Test: `tests/test_alerts.py`

`scout.py`'s own Telegram path (lines 1046-1078) is **not touched**. It is
unreachable from the cron (`--json-out` returns at line 1044) and stays as-is for
manual CLI use. `alerts.py` imports only `fingerprint`, `resolve_telegram` and
`send_telegram` from it — never `load_sent`/`save_sent`, which own the global
`data/sent_jobs.json` this module must not share.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_alerts.py`:

```python
"""Tests for the per-CV alerting sender.

Three failure modes drive this file, all silent in production:
  1. Thresholding on `fit` instead of `match_pct` sends nothing on a keyless
     runner, because llm_rerank() only sets `fit` when NVIDIA_API_KEY exists.
  2. A shared sent-store suppresses an ad on CV B because CV A alerted it.
  3. A first run with no sent-state pushes 4 CVs x 50 matches to Telegram.
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
    threshold would send nothing, silently."""
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
    # non-quiet run.
    fresh = tmp_path / "sent" / "ai-agentic.json"
    fresh.parent.mkdir(parents=True, exist_ok=True)
    fresh.write_text("{}")                # exists but empty: not a first run
    assert alerts.run(results, fresh, 75, "t", "c", send=sender) == 2


def test_a_send_failure_does_not_record_the_fingerprints(results, tmp_path):
    """Results are written before the push (the workflow's job); if the push
    fails, the ads must still be pending, not marked sent."""
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
    assert "https://example.com/Java Developer".replace(" ", "%20") in body or \
        "https://example.com/Java Developer" in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_alerts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'alerts'`

- [ ] **Step 3: Write `scripts/alerts.py`**

```python
#!/usr/bin/env python3
"""Per-CV Telegram alerting for scheduled scans.

The sole sender for scheduled runs. scout.py contains a second, older alerting
path (a global data/sent_jobs.json, dedupe applied before ranking instead of
thresholding after it, its own --top cut). That path is unreachable from the
cron -- --json-out returns before it -- and stays exactly as it is for manual
CLI use. It is not extended here: two senders with two notions of "already
sent" drift into disagreeing, and the one that loses is the one you find out
about when an alert never arrives.

Thresholds on match_pct, never on fit. fit is set by llm_rerank(), which only
runs when NVIDIA_API_KEY is present, so a fit-based cutoff sends nothing at all
on a keyless runner -- and sends nothing silently.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scout import esc, fingerprint, resolve_telegram, send_telegram  # noqa: E402

# How long a sent record suppresses re-alerting. Unbounded, the file grows
# forever on a branch nothing prunes and a genuine repost months later is
# silently swallowed.
SENT_TTL_DAYS = 90


def job_fingerprint(job: dict) -> str:
    """Same company|title hash scout.py uses, so a fingerprint means the same
    thing on both sides of the pipeline."""
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

    # A missing sent file is a CV's very first scan. Pushing then would mean
    # 4 CVs x up to 50 matches on day one. Record the backlog, push nothing;
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
            # pending, not marked as delivered.
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
        token, chat_id = resolve_telegram(args.telegram, Path("/nonexistent"))

    pushed = run(args.results, args.sent, args.min_match, token, chat_id, send=send)
    print(f"[alerts] {args.sent.stem}: pushed {pushed}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Note:** `resolve_telegram` falls back to reading `IMMO_CONFIG` when the env
vars are absent. `main()` passes a nonexistent path so a missing
`TELEGRAM_BOT_TOKEN` on the runner fails loudly with a `FileNotFoundError`
naming `/nonexistent` rather than silently reading a personal machine's config.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_alerts.py -v`
Expected: 11 passed

- [ ] **Step 5: Verify the CLI in dry-run**

Run:
```bash
mkdir -p /tmp/alerttest
cat > /tmp/alerttest/results.json <<'JSON'
{"generated_at": "2026-07-31T05:10:00", "cv": "x", "total_matches": 1,
 "jobs": [{"title": "Senior .NET Engineer", "company": "Bosch",
           "location": "Wien", "match_pct": 86,
           "apply_url": "https://example.com/1"}]}
JSON
echo '{}' > /tmp/alerttest/backend-streaming.json
.venv/bin/python scripts/alerts.py --results /tmp/alerttest/results.json \
  --sent /tmp/alerttest/backend-streaming.json --min-match 75 --dry-run
```
Expected: the formatted message on stdout containing `86%` and `Bosch`, and
`[alerts] backend-streaming: pushed 1` on stderr.

- [ ] **Step 6: Commit**

```bash
git add scripts/alerts.py tests/test_alerts.py
git commit -m "feat(scout): per-CV Telegram alerts thresholded on match_pct"
```

---

### Task 4: Seed `scout/profiles.json` from the four cached profiles

**Files:**
- Create: `scout/profiles.json`, `scout/profiles/*.json`, `scout/README.md`

- [ ] **Step 1: Inspect the four cached profiles**

Run: `for f in data/profiles/*.json; do echo "== $f"; cat "$f" | head -5; done`
Expected: four files, each `{"skills": {...}, "role_titles": [...], "source": ...}`.
Confirm by eye that none carries a name, email, phone, employer or date. If any
does, stop and report it — that is a finding, not a step to work around.

- [ ] **Step 2: Write `scout/README.md`**

```markdown
# scout/ — published configuration

**Everything in this directory is committed to a PUBLIC repository and is
world-readable, forever, including in history.**

- `profiles.json` — the CV list: id, label, schedule, filters, alert threshold.
- `profiles/<id>.json` — a derived matching profile: `{skills, role_titles, source}`
  and nothing else. No name, no email, no phone, no employer, no dates.

CV PDFs are never committed. They live in `data/cv/`, which is gitignored.

Adding a field here publishes it. `dashboard/lib/cvProfiles.ts` enforces the
whitelist in code — a profile write carrying any other key, or an email-, phone-
or token-shaped value, fails rather than being written. Widening that whitelist
is a decision to publish, not a refactor.
```

- [ ] **Step 3: Write `scout/profiles.json`**

Use the four real CVs. `hours_utc` is staggered so four sequential scans do not
all land on the same wake:

```json
{
  "version": 1,
  "profiles": [
    {
      "id": "ai-agentic",
      "label": "AI / Agentic",
      "enabled": true,
      "schedule": { "hours_utc": [5], "weekdays_only": false },
      "filters": { "days": 7, "top": 50, "require_salary": false,
                   "sources": "apis,karriere,adzuna,jooble" },
      "alert": { "min_match": 75 }
    },
    {
      "id": "backend-streaming",
      "label": "Backend / Streaming",
      "enabled": true,
      "schedule": { "hours_utc": [5], "weekdays_only": false },
      "filters": { "days": 7, "top": 50, "require_salary": false,
                   "sources": "apis,karriere,adzuna,jooble" },
      "alert": { "min_match": 75 }
    },
    {
      "id": "devops-sre",
      "label": "DevOps / SRE",
      "enabled": true,
      "schedule": { "hours_utc": [5], "weekdays_only": false },
      "filters": { "days": 7, "top": 50, "require_salary": false,
                   "sources": "apis,karriere,adzuna,jooble" },
      "alert": { "min_match": 75 }
    },
    {
      "id": "fullstack",
      "label": "FullStack",
      "enabled": true,
      "schedule": { "hours_utc": [5], "weekdays_only": false },
      "filters": { "days": 7, "top": 50, "require_salary": false,
                   "sources": "apis,karriere,adzuna,jooble" },
      "alert": { "min_match": 75 }
    }
  ]
}
```

- [ ] **Step 4: Copy the cached profiles in, whitelisted**

Run:
```bash
mkdir -p scout/profiles
.venv/bin/python - <<'PY'
import json, pathlib
# Map each cached digest file to its CV id BY HAND after reading its skills --
# the digest is a content hash and carries no label. Print them first, then fill
# this mapping in and re-run.
for f in sorted(pathlib.Path("data/profiles").glob("*.json")):
    d = json.loads(f.read_text())
    print(f.name, sorted(d["skills"], key=lambda s: -d["skills"][s])[:8])
PY
```

Read the output, decide which digest is which CV, then:

```bash
.venv/bin/python - <<'PY'
import json, pathlib
MAPPING = {
    # "<digest>.json": "<cv-id>",   <-- fill in from the printed skills
}
assert MAPPING, "fill in MAPPING from the printed skill lists first"
for digest, cv_id in MAPPING.items():
    d = json.loads(pathlib.Path("data/profiles", digest).read_text())
    out = {"skills": d["skills"], "role_titles": d["role_titles"],
           "source": d.get("source", "lexicon")}
    extra = set(d) - {"skills", "role_titles", "source"}
    assert not extra, f"{digest} carries unpublishable keys: {extra}"
    pathlib.Path("scout/profiles", f"{cv_id}.json").write_text(
        json.dumps(out, indent=2) + "\n")
    print("wrote", cv_id)
PY
```

- [ ] **Step 5: Verify nothing personal is about to be committed**

Run:
```bash
grep -rEi '[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}|\+?[0-9][0-9 ()-]{8,}' scout/ && \
  echo "FOUND PII — STOP" || echo "clean"
```
Expected: `clean`

Run: `.venv/bin/python -c "
import json,glob
for f in glob.glob('scout/profiles/*.json'):
    assert set(json.load(open(f))) == {'skills','role_titles','source'}, f
print('whitelist ok')"`
Expected: `whitelist ok`

- [ ] **Step 6: Confirm `scout/` is not gitignored**

Run: `git check-ignore -v scout/profiles.json; echo "exit=$?"`
Expected: `exit=1` (not ignored). `.gitignore:87` ignores `data/profiles/`, which
is a different path — confirm the new one is not swept up.

- [ ] **Step 7: Commit**

```bash
git add scout/
git commit -m "feat(scout): committed CV profile config (no PII, public by design)"
```

---

## Phase 2 — the cron

### Task 5: Rewrite `scout-cron.yml` for hourly multi-CV runs

**Files:**
- Modify: `.github/workflows/scout-cron.yml` (full rewrite)
- Test: `tests/test_cron_publish.py`

- [ ] **Step 1: Write the failing test for the publish contract**

The YAML itself cannot be unit-tested, but the two things it must guarantee can:
that no `company_review` reaches the branch, and that the published payload
parses. Create `tests/test_cron_publish.py`:

```python
"""What the cron is contractually forbidden to publish.

Every scout-data commit to date carries model-GENERATED employer cons about
named real companies inside latest.json, on a public branch. Dropping
--company-reviews removes the source; stripping on write means a hand-run local
scan piped through the same helper cannot leak it either.
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
    publish.strip_and_write(src, dst)

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


def test_run_record_carries_slot_status_attempts_and_count(tmp_path):
    path = tmp_path / "runs" / "backend-streaming.json"
    publish.write_run(path, slot="2026-07-31T05:00:00+00:00", status="ok",
                      attempts=1, matches=42,
                      finished_at="2026-07-31T06:04:11+00:00")
    assert json.loads(path.read_text()) == {
        "slot": "2026-07-31T05:00:00+00:00", "status": "ok", "attempts": 1,
        "matches": 42, "finished_at": "2026-07-31T06:04:11+00:00",
    }
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cron_publish.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'publish'`

- [ ] **Step 3: Write `scripts/publish.py`**

```python
#!/usr/bin/env python3
"""Prepare one CV's scan for the public scout-data branch.

Two jobs, both about what is allowed to become world-readable:

  * company_review is stripped unconditionally. It is model-GENERATED text
    about named real employers -- "management churn", "low pay" -- carrying a
    "may invent something plausible for a small company" caveat that lives only
    in the dashboard UI. The cron no longer passes --company-reviews, so the
    field should not be there at all; stripping on write means a hand-run local
    scan piped through here cannot leak it either.
  * the run record is written by one function, so the due-check and the
    dashboard status strip read a shape that has exactly one author.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Published verbatim. Anything not in a job dict here would simply pass through;
# the point of this constant is the explicit removal list below it.
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cron_publish.py -v`
Expected: 3 passed

- [ ] **Step 5: Rewrite `.github/workflows/scout-cron.yml`**

Replace the whole file:

```yaml
name: scout-cron

# Hourly multi-CV job scan.
#
# Every wake asks scripts/cv_schedule.py which CV profiles are due, scans each
# one sequentially against its committed profile, publishes per-CV results to
# the scout-data orphan branch, and alerts on Telegram via scripts/alerts.py.
#
# No CV PDF is involved. The runner reads scout/profiles/<id>.json -- ~600
# bytes of {skills, role_titles, source} -- which is why there is no
# CV_PDF_BASE64 secret any more (CVs are ~76KB base64, over the 48KB cap).
#
# No --company-reviews either. Enrichment is one sequential LLM call per unseen
# company against a data/company_reviews/ cache that is gitignored, so a runner
# is always cold: a measured 4m18s-to-10min per scan, paid again every wake,
# with no way for the result to reach the local dashboard once it is stripped
# from the published feed. Reviews run locally, where the cache lives.
#
# Required secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
# Optional: NVIDIA_API_KEY (LLM rerank), ADZUNA_APP_ID + ADZUNA_APP_KEY, JOOBLE_KEY.

on:
  schedule:
    # Hourly. Which CVs actually run is decided by cv_schedule.py against each
    # profile's hours_utc, not by this cron line.
    - cron: "7 * * * *"
  workflow_dispatch:
    inputs:
      cv_id:
        description: "Scan only this CV id, ignoring its schedule (blank = whatever is due)"
        default: ""
      force:
        description: "Ignore the due-check and scan every enabled CV"
        type: boolean
        default: false

concurrency:
  group: scout-cron
  cancel-in-progress: false

permissions:
  contents: write

jobs:
  scan:
    runs-on: ubuntu-latest
    # Four sequential scans at roughly a minute each, plus checkout and publish.
    # A runaway guard, not a target.
    timeout-minutes: 45
    env:
      FEED_BRANCH: scout-data
      STATE_DIR: ${{ github.workspace }}/.feed
      NVIDIA_API_KEY: ${{ secrets.NVIDIA_API_KEY }}
      ADZUNA_APP_ID: ${{ secrets.ADZUNA_APP_ID }}
      ADZUNA_APP_KEY: ${{ secrets.ADZUNA_APP_KEY }}
      JOOBLE_KEY: ${{ secrets.JOOBLE_KEY }}
      TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
      TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install scout dependencies
        # Only the scout extra: the crawler half needs Playwright and Postgres,
        # neither of which this job touches. pypdf is not needed either -- no
        # PDF is read on a scheduled run -- but it is one small wheel and
        # dropping it would make a --cv fallback fail obscurely.
        run: pip install requests duckdb pypdf

      - name: Fetch the current feed state
        # The branch holds results/, sent/ and runs/. Read into $STATE_DIR so
        # the working tree stays on the default branch while scanning.
        run: |
          set -euo pipefail
          mkdir -p "$STATE_DIR"
          if git ls-remote --exit-code --heads origin "$FEED_BRANCH" >/dev/null 2>&1; then
            git fetch --depth=1 origin "$FEED_BRANCH"
            # FETCH_HEAD, not origin/$FEED_BRANCH: actions/checkout configures a
            # narrow fetch refspec for the branch it checked out, so fetching a
            # second branch never creates its remote-tracking ref. This was
            # verified broken -- the orphan-create path works and every run
            # after the first died with "not a commit".
            git archive FETCH_HEAD | tar -x -C "$STATE_DIR"
            echo "feed state restored: $(find "$STATE_DIR" -name '*.json' | wc -l) files"
          else
            echo "::notice::$FEED_BRANCH does not exist yet; first run"
          fi
          mkdir -p "$STATE_DIR/results" "$STATE_DIR/sent" "$STATE_DIR/runs"

      - name: Decide which CVs are due
        id: due
        run: |
          set -euo pipefail
          if [ "${{ inputs.force }}" = "true" ]; then
            DUE=$(python scripts/cv_schedule.py \
              --profiles scout/profiles.json --runs-dir "$STATE_DIR/runs" --all-enabled)
          elif [ -n "${{ inputs.cv_id }}" ]; then
            DUE="${{ inputs.cv_id }}"
          else
            DUE=$(python scripts/cv_schedule.py \
              --profiles scout/profiles.json --runs-dir "$STATE_DIR/runs")
          fi
          echo "due<<EOF" >> "$GITHUB_OUTPUT"
          echo "$DUE" >> "$GITHUB_OUTPUT"
          echo "EOF" >> "$GITHUB_OUTPUT"
          echo "due: ${DUE:-（none）}"

      - name: Scan, publish and alert each due CV
        if: steps.due.outputs.due != ''
        run: |
          set -euo pipefail
          NOW=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
          echo "## scout-cron $NOW" >> "$GITHUB_STEP_SUMMARY"
          echo "" >> "$GITHUB_STEP_SUMMARY"
          echo "| CV | Status | Published | Alerted |" >> "$GITHUB_STEP_SUMMARY"
          echo "|---|---|---|---|" >> "$GITHUB_STEP_SUMMARY"

          while read -r CV_ID; do
            [ -n "$CV_ID" ] || continue
            SLOT_JSON=$(python scripts/cv_schedule.py \
              --profiles scout/profiles.json --runs-dir "$STATE_DIR/runs" \
              --slot-for "$CV_ID")
            SLOT=$(echo "$SLOT_JSON" | python -c 'import json,sys; print(json.load(sys.stdin)["slot"])')
            ATTEMPTS=$(echo "$SLOT_JSON" | python -c 'import json,sys; print(json.load(sys.stdin)["attempts"])')

            # Filters come out of Python already shell-quoted. No inline heredoc:
            # a heredoc terminator inside a YAML block scalar is indentation-
            # sensitive in a way that is very easy to get subtly wrong, and this
            # way the parsing is covered by test_cv_schedule.py.
            eval "$(python scripts/cv_schedule.py \
              --profiles scout/profiles.json --runs-dir "$STATE_DIR/runs" \
              --filters-for "$CV_ID")"

            ARGS=(--dry-run
                  --profile "scout/profiles/$CV_ID.json"
                  --sources "$F_SOURCES"
                  --days "$F_DAYS"
                  --top "$F_TOP"
                  --json-out "$RUNNER_TEMP/$CV_ID.raw.json")
            # if/then, not `[ ... ] && ARGS+=(...)`: under `set -e` a bare test
            # that fails IS the last command of the line, and the whole job
            # exits. That would silently skip every remaining CV.
            if [ -n "$F_REQUIRE_SALARY" ]; then
              ARGS+=(--require-salary)
            fi
            # No --company-reviews, ever: see the header comment.
            if [ -z "${NVIDIA_API_KEY:-}" ]; then
              ARGS+=(--no-llm)
            fi

            STATUS=ok
            python scripts/scout.py "${ARGS[@]}" || STATUS=error
            FINISHED=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)

            if [ "$STATUS" = "ok" ]; then
              COUNT=$(python scripts/publish.py results \
                --src "$RUNNER_TEMP/$CV_ID.raw.json" \
                --dst "$STATE_DIR/results/$CV_ID.json")
              # Results are written before any push is attempted: a Telegram
              # outage must not cost the scan.
              ALERTED=0
              if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
                python scripts/alerts.py \
                  --results "$STATE_DIR/results/$CV_ID.json" \
                  --sent "$STATE_DIR/sent/$CV_ID.json" \
                  --min-match "$F_MIN_MATCH" || {
                    echo "::warning::alerting failed for $CV_ID; results kept"
                    STATUS=error
                  }
                ALERTED=1
              else
                echo "::warning::TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID unset — no alerts sent"
              fi
            else
              COUNT=0
              ALERTED=0
              echo "::error::scan failed for $CV_ID"
            fi

            python scripts/publish.py run \
              --path "$STATE_DIR/runs/$CV_ID.json" \
              --slot "$SLOT" --status "$STATUS" --attempts "$ATTEMPTS" \
              --matches "$COUNT" --finished-at "$FINISHED"

            echo "| $CV_ID | $STATUS | $COUNT | $ALERTED |" >> "$GITHUB_STEP_SUMMARY"
          done <<< "${{ steps.due.outputs.due }}"

      - name: Publish the state to the ${{ env.FEED_BRANCH }} branch
        if: steps.due.outputs.due != ''
        run: |
          set -euo pipefail
          STAMP=$(date -u +%Y-%m-%dT%H-%M-%SZ)
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

          if git ls-remote --exit-code --heads origin "$FEED_BRANCH" >/dev/null 2>&1; then
            git fetch --depth=1 origin "$FEED_BRANCH"
            git checkout -B "$FEED_BRANCH" FETCH_HEAD
          else
            git checkout --orphan "$FEED_BRANCH"
            git rm -rf --cached . >/dev/null 2>&1 || true
          fi

          # Explicit paths only, never `git add .`: the working tree still holds
          # the default branch's files, including scout/profiles.json, which
          # must not be duplicated onto the data branch.
          mkdir -p results sent runs
          cp -r "$STATE_DIR"/results/. results/ 2>/dev/null || true
          cp -r "$STATE_DIR"/sent/. sent/ 2>/dev/null || true
          cp -r "$STATE_DIR"/runs/. runs/ 2>/dev/null || true
          git add results sent runs

          # Deprecated single-CV feed, kept one release so anything still
          # pointed at scout/latest.json (docker-compose, an old bookmark) does
          # not break mid-migration. Remove once SCOUT_FEED_BASE_URL is
          # everywhere.
          FIRST=$(ls results/*.json 2>/dev/null | head -1 || true)
          if [ -n "$FIRST" ]; then
            mkdir -p scout
            cp "$FIRST" scout/latest.json
            git add scout/latest.json
          fi

          git commit -m "chore(scout): scan $STAMP" || {
            echo "::notice::feed unchanged; nothing committed"; exit 0;
          }
          git push origin "$FEED_BRANCH"

          RAW="https://raw.githubusercontent.com/${GITHUB_REPOSITORY}/${FEED_BRANCH}"
          echo "" >> "$GITHUB_STEP_SUMMARY"
          echo "Feed base: $RAW" >> "$GITHUB_STEP_SUMMARY"

      - name: Heartbeat
        # GitHub disables scheduled workflows on public repos after 60 days with
        # no commits, silently -- alerts would simply stop. A run record with a
        # recent timestamp is what makes that visible on the dashboard, so it is
        # written even on a wake where nothing was due.
        if: steps.due.outputs.due == ''
        run: echo "::notice::no CV due this hour"
```

- [ ] **Step 6: Validate the YAML parses**

Run: `.venv/bin/python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/scout-cron.yml')); print('yaml ok')"`
Expected: `yaml ok` (install with `.venv/bin/pip install pyyaml` if missing)

- [ ] **Step 7: Dry-run the whole loop locally with git plumbing**

This is the step that caught the `origin/$FEED_BRANCH` bug last time. Run it
against a throwaway branch, twice, and check history accumulates:

```bash
export FEED_BRANCH=scout-data-verify2 STATE_DIR=/tmp/feedstate
rm -rf "$STATE_DIR" && mkdir -p "$STATE_DIR"/{results,sent,runs}
.venv/bin/python scripts/cv_schedule.py --profiles scout/profiles.json \
  --runs-dir "$STATE_DIR/runs" --now "$(date -u +%Y-%m-%dT%H:00:00+00:00)"
```
Expected: at least one CV id printed (the profiles are all scheduled at 05:00, so
pass `--now 2026-07-31T05:30:00+00:00` if the current hour is outside the window).

- [ ] **Step 8: Run the full pytest suite**

Run: `.venv/bin/python -m pytest -q --cov=crawler --cov-fail-under=90`
Expected: all pass, coverage ≥90%. **Note:** coverage measures `crawler` only —
`pyproject.toml` omits `scripts/*`, so this number says nothing about the code in
Tasks 1-5. The tests in those tasks are the evidence for them.

- [ ] **Step 9: Commit**

```bash
git add .github/workflows/scout-cron.yml scripts/publish.py tests/test_cron_publish.py
git commit -m "feat(scout): hourly multi-CV cron; no PDF, no company reviews on the runner"
```

---

## Phase 3 — the dashboard

### Task 6: `lib/cvProfiles.ts` — read, validate, write, and the PII gate

**Files:**
- Create: `dashboard/lib/cvProfiles.ts`
- Test: `dashboard/tests/cv-profiles.spec.ts`

- [ ] **Step 1: Write the failing tests**

Create `dashboard/tests/cv-profiles.spec.ts`. These run in Playwright's Node
context — no browser — because the module is server-side fs code:

```ts
import { test, expect } from "@playwright/test";
import { mkdtemp, readFile, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import {
  readProfiles,
  writeProfiles,
  sanitizeProfileDoc,
  validateProfile,
  type CvProfile,
} from "@/lib/cvProfiles";

async function configRoot() {
  const root = await mkdtemp(path.join(tmpdir(), "cvcfg-"));
  await mkdir(path.join(root, "scout", "profiles"), { recursive: true });
  await writeFile(
    path.join(root, "scout", "profiles.json"),
    JSON.stringify({ version: 1, profiles: [] }),
  );
  return root;
}

const VALID: CvProfile = {
  id: "backend-streaming",
  label: "Backend / Streaming",
  enabled: true,
  schedule: { hours_utc: [5], weekdays_only: false },
  filters: { days: 7, top: 50, require_salary: false, sources: "apis,karriere" },
  alert: { min_match: 75 },
};

test("a valid profile round-trips", async () => {
  const root = await configRoot();
  await writeProfiles(root, [VALID]);
  expect(await readProfiles(root)).toEqual([VALID]);
});

test("rejects an id that is not a slug", () => {
  expect(() => validateProfile({ ...VALID, id: "Backend Streaming" })).toThrow(/id/);
  expect(() => validateProfile({ ...VALID, id: "a".repeat(41) })).toThrow(/id/);
  expect(() => validateProfile({ ...VALID, id: "../../etc/passwd" })).toThrow(/id/);
});

test("rejects duplicate ids", async () => {
  const root = await configRoot();
  await expect(writeProfiles(root, [VALID, { ...VALID, label: "Other" }]))
    .rejects.toThrow(/duplicate/i);
});

test("rejects an empty schedule", () => {
  expect(() =>
    validateProfile({ ...VALID, schedule: { hours_utc: [], weekdays_only: false } }),
  ).toThrow(/hours_utc/);
});

test("rejects more than four scheduled hours", () => {
  expect(() =>
    validateProfile({
      ...VALID,
      schedule: { hours_utc: [0, 4, 8, 12, 16], weekdays_only: false },
    }),
  ).toThrow(/at most 4/);
});

test("rejects an hour outside 0-23", () => {
  expect(() =>
    validateProfile({ ...VALID, schedule: { hours_utc: [24], weekdays_only: false } }),
  ).toThrow(/hours_utc/);
});

test("rejects a min_match outside 0-100", () => {
  expect(() => validateProfile({ ...VALID, alert: { min_match: 101 } })).toThrow(/min_match/);
  expect(() => validateProfile({ ...VALID, alert: { min_match: -1 } })).toThrow(/min_match/);
});

// --- the PII gate -----------------------------------------------------------

test("a profile document with an unknown key is rejected, not stripped", () => {
  expect(() =>
    sanitizeProfileDoc({
      skills: { dotnet: 10 },
      role_titles: ["backend engineer"],
      source: "llm",
      raw_cv_text: "Vlad Brincoveanu, Vienna",
    }),
  ).toThrow(/raw_cv_text/);
});

test("an email-shaped value anywhere in the document is rejected", () => {
  expect(() =>
    sanitizeProfileDoc({
      skills: { dotnet: 10 },
      role_titles: ["gg.vladbrincoveanu@gmail.com"],
      source: "llm",
    }),
  ).toThrow(/email/i);
});

test("a phone-shaped value is rejected", () => {
  expect(() =>
    sanitizeProfileDoc({
      skills: { dotnet: 10 },
      role_titles: ["+43 660 1234567"],
      source: "llm",
    }),
  ).toThrow(/phone/i);
});

test("a token-shaped value is rejected", () => {
  expect(() =>
    sanitizeProfileDoc({
      skills: { dotnet: 10 },
      role_titles: ["backend"],
      source: "ghp_0123456789abcdefghijklmnopqrstuvwxyzA",
    }),
  ).toThrow(/token|credential/i);
  expect(() =>
    sanitizeProfileDoc({
      skills: { dotnet: 10 },
      role_titles: ["backend"],
      source: "nvapi-0123456789abcdefghijklmnopqrstuvwxyz0123456789",
    }),
  ).toThrow(/token|credential/i);
});

test("a clean profile document passes and is written verbatim", async () => {
  const root = await configRoot();
  const clean = { skills: { dotnet: 10 }, role_titles: ["backend engineer"], source: "llm" };
  expect(sanitizeProfileDoc(clean)).toEqual(clean);

  const { writeProfileDoc } = await import("@/lib/cvProfiles");
  await writeProfileDoc(root, "backend-streaming", clean);
  const written = JSON.parse(
    await readFile(path.join(root, "scout", "profiles", "backend-streaming.json"), "utf-8"),
  );
  expect(written).toEqual(clean);
});

test("writeProfiles reports the paths it changed", async () => {
  const root = await configRoot();
  const changed = await writeProfiles(root, [VALID]);
  expect(changed).toEqual([path.join(root, "scout", "profiles.json")]);
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd dashboard && npx playwright test tests/cv-profiles.spec.ts --reporter=dot`
Expected: FAIL — cannot resolve `@/lib/cvProfiles`.

- [ ] **Step 3: Write `dashboard/lib/cvProfiles.ts`**

```ts
import { readFile, writeFile, mkdir, access } from "node:fs/promises";
import { constants } from "node:fs";
import path from "node:path";

/**
 * The committed CV configuration: scout/profiles.json and
 * scout/profiles/<id>.json.
 *
 * THE REPOSITORY IS PUBLIC. Everything this module writes is world-readable
 * forever, including in history. That is why the profile writer refuses
 * anything outside a three-key whitelist instead of trusting its caller: the
 * failure mode is not a crash, it is a name and an email address on the
 * internet that no later commit can take back.
 *
 * Credentials go through lib/credentials.ts, which can only target .env.local.
 * These two modules deliberately share nothing, so no edit here can route a
 * token into the committed tree.
 *
 * Root resolution is SCOUT_CONFIG_ROOT, not SCOUT_REPO_ROOT: the scan route
 * uses the latter to locate scripts/scout.py, and the tests need to redirect
 * config writes into a fixture without also breaking the live-scan spec.
 */

export const CONFIG_ROOT =
  process.env.SCOUT_CONFIG_ROOT ??
  process.env.SCOUT_REPO_ROOT ??
  path.resolve(process.cwd(), "..");

const ID_RE = /^[a-z0-9-]{1,40}$/;
const EMAIL_RE = /[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}/i;
const PHONE_RE = /(\+\d[\d\s()-]{7,})|(\b\d{3,}[\s-]\d{3,}[\s-]\d{3,}\b)/;
/** ghp_/github_pat_, nvapi-, sk-, and long opaque hex/base64 runs. */
const TOKEN_RE =
  /(ghp_[A-Za-z0-9]{20,})|(github_pat_[A-Za-z0-9_]{20,})|(nvapi-[A-Za-z0-9_-]{20,})|(sk-[A-Za-z0-9]{20,})|(\b[A-Fa-f0-9]{32,}\b)/;

/** Exactly what may be published. Widening this is a decision to publish. */
const PROFILE_KEYS = ["skills", "role_titles", "source"] as const;

export interface CvSchedule {
  hours_utc: number[];
  weekdays_only: boolean;
}

export interface CvFilters {
  days: number;
  top: number;
  require_salary: boolean;
  sources: string;
}

export interface CvProfile {
  id: string;
  label: string;
  enabled: boolean;
  schedule: CvSchedule;
  filters: CvFilters;
  alert: { min_match: number };
}

export interface ProfileDoc {
  skills: Record<string, number>;
  role_titles: string[];
  source: string;
}

export function profilesPath(root = CONFIG_ROOT): string {
  return path.join(root, "scout", "profiles.json");
}

export function profileDocPath(id: string, root = CONFIG_ROOT): string {
  if (!ID_RE.test(id)) throw new Error(`Invalid CV id: ${id}`);
  return path.join(root, "scout", "profiles", `${id}.json`);
}

export function validateProfile(profile: CvProfile): CvProfile {
  if (!ID_RE.test(profile.id)) {
    throw new Error(
      `Invalid CV id "${profile.id}": lowercase letters, digits and hyphens, 1-40 chars.`,
    );
  }
  if (!profile.label?.trim()) throw new Error("A CV needs a label.");

  const hours = profile.schedule?.hours_utc ?? [];
  if (hours.length === 0) {
    throw new Error(`"${profile.id}": hours_utc is empty — it would never run.`);
  }
  // Job ads do not turn over hourly. The cap makes a runaway config
  // ([0..23] x 4 CVs = 96 scans a day) unreachable rather than merely unlikely.
  if (hours.length > 4) {
    throw new Error(`"${profile.id}": at most 4 scheduled hours per CV.`);
  }
  if (hours.some((h) => !Number.isInteger(h) || h < 0 || h > 23)) {
    throw new Error(`"${profile.id}": hours_utc must be whole hours 0-23 (UTC).`);
  }
  const min = profile.alert?.min_match;
  if (!Number.isFinite(min) || min < 0 || min > 100) {
    throw new Error(`"${profile.id}": min_match must be 0-100.`);
  }
  return profile;
}

/**
 * The PII gate. Hard-fails; it does not strip.
 *
 * A silent strip is how an unnoticed field arrives: the write succeeds, nobody
 * reads the diff, and the next time someone adds a key it is not obvious the
 * old one was ever dropped. Failing means the caller has to decide.
 */
export function sanitizeProfileDoc(doc: unknown): ProfileDoc {
  if (!doc || typeof doc !== "object") throw new Error("Profile is not an object.");
  const record = doc as Record<string, unknown>;

  const extra = Object.keys(record).filter(
    (k) => !(PROFILE_KEYS as readonly string[]).includes(k),
  );
  if (extra.length) {
    throw new Error(
      `Profile carries unpublishable key(s): ${extra.join(", ")}. ` +
        `scout/ is world-readable; only ${PROFILE_KEYS.join(", ")} may be written.`,
    );
  }
  if (!record.skills || typeof record.skills !== "object") {
    throw new Error("Profile has no skills.");
  }
  if (!Array.isArray(record.role_titles) || record.role_titles.length === 0) {
    throw new Error("Profile has no role_titles.");
  }
  if (typeof record.source !== "string") throw new Error("Profile has no source.");

  for (const value of scalars(record)) {
    if (EMAIL_RE.test(value)) throw new Error(`Profile contains an email address: "${value}"`);
    if (PHONE_RE.test(value)) throw new Error(`Profile contains a phone number: "${value}"`);
    if (TOKEN_RE.test(value)) {
      throw new Error("Profile contains a credential-shaped value; refusing to publish it.");
    }
  }

  return {
    skills: record.skills as Record<string, number>,
    role_titles: record.role_titles as string[],
    source: record.source,
  };
}

/** Every string in the document, keys included — a token in a key is still a token. */
function* scalars(value: unknown): Generator<string> {
  if (typeof value === "string") yield value;
  else if (Array.isArray(value)) for (const v of value) yield* scalars(v);
  else if (value && typeof value === "object") {
    for (const [k, v] of Object.entries(value)) {
      yield k;
      yield* scalars(v);
    }
  }
}

export async function readProfiles(root = CONFIG_ROOT): Promise<CvProfile[]> {
  try {
    const raw = await readFile(profilesPath(root), "utf-8");
    return (JSON.parse(raw).profiles ?? []) as CvProfile[];
  } catch (err) {
    if ((err as NodeJS.ErrnoException)?.code === "ENOENT") return [];
    throw err;
  }
}

export async function writeProfiles(
  profiles: CvProfile[],
): Promise<string[]>;
export async function writeProfiles(
  root: string,
  profiles: CvProfile[],
): Promise<string[]>;
export async function writeProfiles(
  a: string | CvProfile[],
  b?: CvProfile[],
): Promise<string[]> {
  const root = typeof a === "string" ? a : CONFIG_ROOT;
  const profiles = (typeof a === "string" ? b : a) as CvProfile[];

  const seen = new Set<string>();
  for (const profile of profiles) {
    validateProfile(profile);
    if (seen.has(profile.id)) throw new Error(`Duplicate CV id: ${profile.id}`);
    seen.add(profile.id);
  }
  const target = profilesPath(root);
  await mkdir(path.dirname(target), { recursive: true });
  await writeFile(target, JSON.stringify({ version: 1, profiles }, null, 2) + "\n");
  return [target];
}

export async function writeProfileDoc(
  root: string,
  id: string,
  doc: unknown,
): Promise<string> {
  const clean = sanitizeProfileDoc(doc);
  const target = profileDocPath(id, root);
  await mkdir(path.dirname(target), { recursive: true });
  await writeFile(target, JSON.stringify(clean, null, 2) + "\n");
  return target;
}

/**
 * Whether config can be edited at all.
 *
 * The Docker container mounts only ./dashboard, so it reaches neither scout/
 * nor data/company_reviews/. That is a real limitation of the file-sync model,
 * not a bug: the UI renders read-only and says so, rather than offering a Save
 * button that throws ENOENT.
 */
export async function configWritable(root = CONFIG_ROOT): Promise<boolean> {
  try {
    await access(path.join(root, "scout"), constants.W_OK);
    return true;
  } catch {
    return false;
  }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd dashboard && npx playwright test tests/cv-profiles.spec.ts --reporter=dot`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add dashboard/lib/cvProfiles.ts dashboard/tests/cv-profiles.spec.ts
git commit -m "feat(dashboard): CV profile config with a code-enforced publish whitelist"
```

---

### Task 7: `lib/credentials.ts` — `.env.local` and nothing else

**Files:**
- Create: `dashboard/lib/credentials.ts`
- Test: `dashboard/tests/credentials.spec.ts`

- [ ] **Step 1: Write the failing tests**

Create `dashboard/tests/credentials.spec.ts`:

```ts
import { test, expect } from "@playwright/test";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import {
  ALLOWED_KEYS,
  ghSecretCommands,
  writeCredentials,
} from "@/lib/credentials";

async function root() {
  return mkdtemp(path.join(tmpdir(), "creds-"));
}

test("writes only to .env.local", async () => {
  const dir = await root();
  const written = await writeCredentials(dir, { TELEGRAM_BOT_TOKEN: "123:abc" });
  expect(written).toBe(path.join(dir, ".env.local"));
  expect(await readFile(written, "utf-8")).toContain("TELEGRAM_BOT_TOKEN=123:abc");
});

test("refuses a key that is not an alert credential", async () => {
  const dir = await root();
  await expect(
    writeCredentials(dir, { SOME_OTHER_KEY: "x" } as never),
  ).rejects.toThrow(/SOME_OTHER_KEY/);
});

test("merges into an existing .env.local without dropping other keys", async () => {
  const dir = await root();
  await writeFile(path.join(dir, ".env.local"), "DATABASE_URL=postgres://x\nTELEGRAM_CHAT_ID=old\n");
  await writeCredentials(dir, { TELEGRAM_CHAT_ID: "new" });

  const body = await readFile(path.join(dir, ".env.local"), "utf-8");
  expect(body).toContain("DATABASE_URL=postgres://x");
  expect(body).toContain("TELEGRAM_CHAT_ID=new");
  expect(body).not.toContain("TELEGRAM_CHAT_ID=old");
});

test("returns the gh commands to mirror the secrets, without the values", () => {
  const cmds = ghSecretCommands({ TELEGRAM_BOT_TOKEN: "123:abc", TELEGRAM_CHAT_ID: "42" });
  expect(cmds).toEqual([
    "gh secret set TELEGRAM_BOT_TOKEN",
    "gh secret set TELEGRAM_CHAT_ID",
  ]);
  expect(cmds.join(" ")).not.toContain("123:abc");
});

test("the allowed key list is exactly the documented one", () => {
  expect([...ALLOWED_KEYS].sort()).toEqual([
    "ADZUNA_APP_ID",
    "ADZUNA_APP_KEY",
    "JOOBLE_KEY",
    "NVIDIA_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
  ]);
});

test("a value containing a newline is rejected", async () => {
  const dir = await root();
  await expect(
    writeCredentials(dir, { TELEGRAM_CHAT_ID: "42\nDATABASE_URL=evil" }),
  ).rejects.toThrow(/newline/i);
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd dashboard && npx playwright test tests/credentials.spec.ts --reporter=dot`
Expected: FAIL — cannot resolve `@/lib/credentials`.

- [ ] **Step 3: Write `dashboard/lib/credentials.ts`**

```ts
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

/**
 * Alert credentials, written to .env.local and nowhere else.
 *
 * This module shares nothing with lib/cvProfiles.ts on purpose. That one writes
 * scout/, which is committed to a public repository; a credential in a
 * committed file is a published credential, and the cheapest way to guarantee
 * no future edit routes a token there is for the two writers to have no common
 * path-building code at all.
 *
 * .env.local is covered by .gitignore:45 (`.env*.local`).
 *
 * GitHub Actions cannot read .env.local, so scheduled runs need the same values
 * as repo secrets. The dashboard never stores a GitHub token and never writes
 * secrets itself: it prints the `gh secret set` commands for the user to paste.
 */

export const ALLOWED_KEYS = new Set([
  "TELEGRAM_BOT_TOKEN",
  "TELEGRAM_CHAT_ID",
  "NVIDIA_API_KEY",
  "ADZUNA_APP_ID",
  "ADZUNA_APP_KEY",
  "JOOBLE_KEY",
]);

export type CredentialKey =
  | "TELEGRAM_BOT_TOKEN"
  | "TELEGRAM_CHAT_ID"
  | "NVIDIA_API_KEY"
  | "ADZUNA_APP_ID"
  | "ADZUNA_APP_KEY"
  | "JOOBLE_KEY";

const ENV_FILE = ".env.local";

/** Never takes a path from the caller: the filename is a constant here. */
export async function writeCredentials(
  root: string,
  values: Partial<Record<CredentialKey, string>>,
): Promise<string> {
  for (const [key, value] of Object.entries(values)) {
    if (!ALLOWED_KEYS.has(key)) {
      throw new Error(
        `Refusing to write "${key}": only alert credentials go in ${ENV_FILE}.`,
      );
    }
    if (/[\r\n]/.test(value ?? "")) {
      throw new Error(`Value for ${key} contains a newline; that would inject another key.`);
    }
  }

  const target = path.join(root, ENV_FILE);
  let existing = "";
  try {
    existing = await readFile(target, "utf-8");
  } catch (err) {
    if ((err as NodeJS.ErrnoException)?.code !== "ENOENT") throw err;
  }

  // Merge, don't overwrite: .env.local also holds DATABASE_URL and whatever
  // else local development needs. Replacing the file would break the dashboard
  // the moment someone saved a Telegram token.
  const lines = existing.split("\n").filter((l) => l.length > 0);
  const kept = lines.filter((line) => {
    const key = line.split("=")[0]?.trim();
    return !(key in values);
  });
  for (const [key, value] of Object.entries(values)) {
    kept.push(`${key}=${value}`);
  }
  await writeFile(target, kept.join("\n") + "\n", { mode: 0o600 });
  return target;
}

/** The commands to mirror these to GitHub. Values are never included: they
 *  would end up in the HTTP response, the browser devtools and shell history. */
export function ghSecretCommands(
  values: Partial<Record<CredentialKey, string>>,
): string[] {
  return Object.keys(values)
    .filter((k) => ALLOWED_KEYS.has(k))
    .sort()
    .map((k) => `gh secret set ${k}`);
}

/** Which credentials the server currently has, by name only. */
export function configuredKeys(): CredentialKey[] {
  return [...ALLOWED_KEYS].filter((k) => !!process.env[k]) as CredentialKey[];
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd dashboard && npx playwright test tests/credentials.spec.ts --reporter=dot`
Expected: 6 passed

- [ ] **Step 5: Verify `.env.local` is really gitignored**

Run: `git check-ignore -v .env.local; echo "exit=$?"`
Expected: `exit=0` and the matching rule printed (`.gitignore:45:.env*.local`).

- [ ] **Step 6: Commit**

```bash
git add dashboard/lib/credentials.ts dashboard/tests/credentials.spec.ts
git commit -m "feat(dashboard): alert credentials write to .env.local only"
```

---

### Task 8: Extend `lib/feed.ts` for per-CV feeds

**Files:**
- Modify: `dashboard/lib/feed.ts`
- Test: `dashboard/tests/feed.spec.ts` (extend)

- [ ] **Step 1: Add the failing tests**

Append to `dashboard/tests/feed.spec.ts`:

```ts
test("loads a per-CV feed from the state directory", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "feed-"));
  await mkdir(path.join(dir, "results"), { recursive: true });
  await writeFile(
    path.join(dir, "results", "backend-streaming.json"),
    JSON.stringify({ generated_at: "2026-07-31T05:10:00", cv: "x",
                     total_matches: 1, jobs: [{ title: "T" }] }),
  );
  process.env.SCOUT_FEED_DIR = dir;
  try {
    const { result, error } = await loadFeed("backend-streaming");
    expect(error).toBeNull();
    expect(result?.jobs).toHaveLength(1);
  } finally {
    delete process.env.SCOUT_FEED_DIR;
  }
});

test("a missing per-CV feed is an empty state, not an error", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "feed-"));
  process.env.SCOUT_FEED_DIR = dir;
  try {
    const { result, error } = await loadFeed("never-scanned");
    expect(result).toBeNull();
    expect(error).toBeNull();
  } finally {
    delete process.env.SCOUT_FEED_DIR;
  }
});

test("SCOUT_FEED_BASE_URL builds the per-CV URL", async () => {
  process.env.SCOUT_FEED_BASE_URL = "https://raw.example/repo/scout-data";
  try {
    expect(feedUrlFor("backend-streaming")).toBe(
      "https://raw.example/repo/scout-data/results/backend-streaming.json",
    );
  } finally {
    delete process.env.SCOUT_FEED_BASE_URL;
  }
});

test("a CV id with a path separator is refused", () => {
  expect(() => feedUrlFor("../../secrets")).toThrow(/Invalid CV id/);
});
```

Add to that file's imports:

```ts
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { loadFeed, feedUrlFor } from "@/lib/feed";
```

- [ ] **Step 2: Run to verify failure**

Run: `cd dashboard && npx playwright test tests/feed.spec.ts --reporter=dot`
Expected: FAIL — `feedUrlFor` is not exported.

- [ ] **Step 3: Extend `dashboard/lib/feed.ts`**

Add above `loadFeed`, keeping everything already in the file:

```ts
const CV_ID_RE = /^[a-z0-9-]{1,40}$/;

/** Where the per-CV feeds live locally: a checkout of the scout-data branch,
 *  or the state directory the workflow writes. */
function feedDir(): string {
  return process.env.SCOUT_FEED_DIR ?? path.join(REPO_ROOT, "data", "scout");
}

export function feedUrlFor(cvId: string): string | null {
  // Validate before the base-URL check, not after: otherwise "../../secrets"
  // is silently accepted whenever SCOUT_FEED_BASE_URL happens to be unset, and
  // the path traversal only surfaces in the deployment that has it set.
  if (!CV_ID_RE.test(cvId)) throw new Error(`Invalid CV id: ${cvId}`);
  const base = process.env.SCOUT_FEED_BASE_URL;
  if (!base) return null;
  return `${base.replace(/\/$/, "")}/results/${cvId}.json`;
}

export function feedPathFor(cvId: string): string {
  if (!CV_ID_RE.test(cvId)) throw new Error(`Invalid CV id: ${cvId}`);
  return path.join(feedDir(), "results", `${cvId}.json`);
}
```

Then change the `loadFeed` signature and its two lookups:

```ts
/**
 * Load one CV's feed, or the legacy single feed when no id is given.
 *
 * Order: SCOUT_FEED_BASE_URL (per-CV over HTTP, what the container uses) →
 * SCOUT_FEED_URL (the legacy single feed) → the local file. A missing feed is
 * a normal state; an unparseable one is not, and must never read as "no scan
 * yet" — that would hide a broken cron behind an innocuous empty page.
 */
export async function loadFeed(cvId?: string): Promise<FeedLoad> {
  const url = (cvId ? feedUrlFor(cvId) : null) ?? process.env.SCOUT_FEED_URL;
  if (url) {
    // ...unchanged fetch block...
  }

  const file = cvId ? feedPathFor(cvId) : feedPath();
  // ...unchanged read block...
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd dashboard && npx playwright test tests/feed.spec.ts --reporter=dot`
Expected: all pass, including the four pre-existing feed tests.

- [ ] **Step 5: Commit**

```bash
git add dashboard/lib/feed.ts dashboard/tests/feed.spec.ts
git commit -m "feat(dashboard): per-CV feed loading over file and HTTP"
```

---

### Task 9: `app/api/cv/route.ts` — register, update and list CVs

**Files:**
- Create: `dashboard/app/api/cv/route.ts`
- Test: covered by Task 11's Playwright flow (an API-only test would duplicate
  Task 6's validation tests without exercising anything new).

- [ ] **Step 1: Write `dashboard/app/api/cv/route.ts`**

```ts
import { NextRequest, NextResponse } from "next/server";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import {
  CONFIG_ROOT,
  configWritable,
  readProfiles,
  writeProfileDoc,
  writeProfiles,
  type CvProfile,
} from "@/lib/cvProfiles";

/**
 * One CV: register it from a PDF, or save its settings.
 *
 * Registering runs `scout.py --profile-only`, which extracts the matching
 * profile and exits without scanning — a second, not the four minutes a full
 * scan takes. The PDF is written to data/cv/<id>.pdf, which is gitignored and
 * never leaves this machine; only the derived profile reaches scout/.
 */

export const dynamic = "force-dynamic";
export const maxDuration = 120;

const REPO_ROOT = process.env.SCOUT_REPO_ROOT ?? path.resolve(process.cwd(), "..");
const SCOUT_SCRIPT = path.join(REPO_ROOT, "scripts", "scout.py");
const MAX_UPLOAD_BYTES = 15 * 1024 * 1024;
const ID_RE = /^[a-z0-9-]{1,40}$/;

function resolvePython(): string {
  if (process.env.SCOUT_PYTHON_BIN) return process.env.SCOUT_PYTHON_BIN;
  const venv = path.join(REPO_ROOT, ".venv", "bin", "python");
  return existsSync(venv) ? venv : "python3";
}

export async function GET() {
  return NextResponse.json({
    profiles: await readProfiles(),
    writable: await configWritable(),
  });
}

/** Register a CV: multipart with `id`, `label` and a `cv` PDF. */
export async function POST(request: NextRequest) {
  if (!(await configWritable())) {
    return NextResponse.json({ error: READ_ONLY }, { status: 409 });
  }

  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return NextResponse.json(
      { error: "Expected multipart/form-data with a 'cv' file." },
      { status: 400 },
    );
  }

  const id = String(form.get("id") ?? "").trim();
  const label = String(form.get("label") ?? "").trim();
  if (!ID_RE.test(id)) {
    return NextResponse.json(
      { error: "id must be 1-40 chars of a-z, 0-9 and hyphens." },
      { status: 400 },
    );
  }
  if (!label) return NextResponse.json({ error: "label is required." }, { status: 400 });

  const file = form.get("cv");
  if (!file || typeof file === "string") {
    return NextResponse.json({ error: "Missing 'cv' file upload (PDF)." }, { status: 400 });
  }
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    return NextResponse.json({ error: "Only PDF CVs are supported." }, { status: 400 });
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return NextResponse.json({ error: "CV file too large (max 15MB)." }, { status: 400 });
  }

  // The PDF stays here. data/cv/ is gitignored; the repository is public.
  const cvDir = path.join(REPO_ROOT, "data", "cv");
  await mkdir(cvDir, { recursive: true });
  const cvPath = path.join(cvDir, `${id}.pdf`);
  await writeFile(cvPath, Buffer.from(await file.arrayBuffer()));

  const { code, stdout, stderr } = await runScout([
    SCOUT_SCRIPT, "--profile-only", cvPath,
  ]);
  if (code !== 0) {
    return NextResponse.json(
      { error: "Profile extraction failed.", detail: stderr.slice(-4000) },
      { status: 502 },
    );
  }

  const extractedPath = stdout.trim().split("\n").pop() ?? "";
  let doc: unknown;
  try {
    doc = JSON.parse(await readFile(extractedPath, "utf-8"));
  } catch (err) {
    return NextResponse.json(
      { error: `Could not read the extracted profile at ${extractedPath}.`,
        detail: err instanceof Error ? err.message : String(err) },
      { status: 502 },
    );
  }

  let profileDocPath: string;
  try {
    // The PII gate. A profile that carries anything but {skills, role_titles,
    // source} fails here rather than being committed to a public repository.
    profileDocPath = await writeProfileDoc(CONFIG_ROOT, id, doc);
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Profile rejected." },
      { status: 422 },
    );
  }

  const profiles = await readProfiles();
  if (profiles.some((p) => p.id === id)) {
    return NextResponse.json({ error: `CV "${id}" already exists.` }, { status: 409 });
  }
  const profile: CvProfile = {
    id,
    label,
    enabled: true,
    schedule: { hours_utc: [5], weekdays_only: false },
    filters: { days: 7, top: 50, require_salary: false,
               sources: "apis,karriere,adzuna,jooble" },
    alert: { min_match: 75 },
  };
  const changed = await writeProfiles(CONFIG_ROOT, [...profiles, profile]);

  return NextResponse.json({ profile, changed: [...changed, profileDocPath] });
}

/** Save one CV's settings: JSON body of a full CvProfile. */
export async function PUT(request: NextRequest) {
  if (!(await configWritable())) {
    return NextResponse.json({ error: READ_ONLY }, { status: 409 });
  }
  let incoming: CvProfile;
  try {
    incoming = (await request.json()) as CvProfile;
  } catch {
    return NextResponse.json({ error: "Expected a JSON profile." }, { status: 400 });
  }

  const profiles = await readProfiles();
  const index = profiles.findIndex((p) => p.id === incoming.id);
  if (index === -1) {
    return NextResponse.json({ error: `Unknown CV "${incoming.id}".` }, { status: 404 });
  }
  profiles[index] = incoming;

  try {
    const changed = await writeProfiles(CONFIG_ROOT, profiles);
    return NextResponse.json({ profile: incoming, changed });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Invalid profile." },
      { status: 422 },
    );
  }
}

/**
 * Remove a CV from the config.
 *
 * Its results/, sent/ and runs/ files on scout-data are deliberately left
 * alone. They are a few KB, and orphan state is preferable to destroying alert
 * history because someone typo'd an id. Reusing a deleted id resumes its old
 * sent-history — documented, not accidental. The local PDF is left alone too:
 * deleting a user's own file is not this endpoint's call.
 */
export async function DELETE(request: NextRequest) {
  if (!(await configWritable())) {
    return NextResponse.json({ error: READ_ONLY }, { status: 409 });
  }
  const id = request.nextUrl.searchParams.get("id") ?? "";
  const profiles = await readProfiles();
  if (!profiles.some((p) => p.id === id)) {
    return NextResponse.json({ error: `Unknown CV "${id}".` }, { status: 404 });
  }
  const changed = await writeProfiles(
    CONFIG_ROOT,
    profiles.filter((p) => p.id !== id),
  );
  return NextResponse.json({
    removed: id,
    changed,
    note:
      `Alert history and results for "${id}" are kept on the scout-data branch. ` +
      `Re-adding this id resumes them.`,
  });
}

const READ_ONLY =
  "Config is read-only here: this dashboard cannot reach the repository's scout/ " +
  "directory. Run it locally with `npm run dev` from the repo checkout to edit CVs.";

function runScout(
  args: string[],
): Promise<{ code: number; stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn(resolvePython(), args, { cwd: REPO_ROOT, env: process.env });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (c: Buffer) => (stdout += c.toString()));
    child.stderr.on("data", (c: Buffer) => (stderr += c.toString()));
    child.on("error", reject);
    child.on("close", (code) => resolve({ code: code ?? 1, stdout, stderr }));
  });
}
```

- [ ] **Step 2: Verify it type-checks**

Run: `cd dashboard && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Verify the read-only branch by hand**

Run:
```bash
cd dashboard && SCOUT_CONFIG_ROOT=/nonexistent-root npx next dev -p 3099 &
sleep 6
curl -s localhost:3099/api/cv | head -c 200
curl -s -X PUT localhost:3099/api/cv -H 'content-type: application/json' \
  -d '{"id":"x"}' | head -c 200
pkill -f "next dev"
```
Expected: the GET returns `{"profiles":[],"writable":false}`; the PUT returns the
read-only message with status 409.

- [ ] **Step 4: Commit**

```bash
git add dashboard/app/api/cv/route.ts
git commit -m "feat(dashboard): CV registration and settings API"
```

---

### Task 10: `app/api/scout/stream/route.ts` — scan with live progress

**Files:**
- Create: `dashboard/app/api/scout/stream/route.ts`

A scan is 30s–4m18s. The existing route buffers stderr and returns nothing until
it finishes, which reads as "hung". `scout.py` already writes progress to stderr
(`log()`, line 112) while `--json-out` writes results to a *file*, so the two
never collide and stderr can simply be forwarded.

- [ ] **Step 1: Write the route**

```ts
import { NextRequest } from "next/server";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { readProfiles } from "@/lib/cvProfiles";

/**
 * Scan one registered CV, streaming progress.
 *
 * scout.py writes progress to stderr and results to the --json-out file, so
 * forwarding stderr line by line costs nothing and turns a four-minute blank
 * spinner into "karriere.at: 41 ads … Remotive: 12 … scoring".
 *
 * Uses --profile (the committed profile), not --cv: the same input the
 * scheduled run uses, so "Scan now" and the cron cannot disagree about what
 * this CV is.
 */

export const dynamic = "force-dynamic";
export const maxDuration = 300;

const REPO_ROOT = process.env.SCOUT_REPO_ROOT ?? path.resolve(process.cwd(), "..");
const SCOUT_SCRIPT = path.join(REPO_ROOT, "scripts", "scout.py");
const ID_RE = /^[a-z0-9-]{1,40}$/;

function resolvePython(): string {
  if (process.env.SCOUT_PYTHON_BIN) return process.env.SCOUT_PYTHON_BIN;
  const venv = path.join(REPO_ROOT, ".venv", "bin", "python");
  return existsSync(venv) ? venv : "python3";
}

export async function GET(request: NextRequest) {
  const cvId = request.nextUrl.searchParams.get("cv") ?? "";
  if (!ID_RE.test(cvId)) {
    return new Response("Invalid CV id", { status: 400 });
  }
  const profile = (await readProfiles()).find((p) => p.id === cvId);
  if (!profile) return new Response(`Unknown CV "${cvId}"`, { status: 404 });

  const configRoot =
    process.env.SCOUT_CONFIG_ROOT ?? process.env.SCOUT_REPO_ROOT ?? REPO_ROOT;
  const workDir = await mkdtemp(path.join(tmpdir(), "scout-stream-"));
  const jsonPath = path.join(workDir, "result.json");

  const args = [
    SCOUT_SCRIPT,
    "--dry-run",
    "--profile", path.join(configRoot, "scout", "profiles", `${cvId}.json`),
    "--sources", profile.filters.sources,
    "--days", String(profile.filters.days),
    "--top", String(profile.filters.top),
    "--json-out", jsonPath,
  ];
  if (profile.filters.require_salary) args.push("--require-salary");
  if (!process.env.NVIDIA_API_KEY) args.push("--no-llm");
  // Reviews are enriched here and only here: the cache lives on this machine
  // and the runner's is always cold. See the spec's "Company reviews are local".
  else args.push("--company-reviews");

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      const send = (event: string, data: unknown) =>
        controller.enqueue(
          encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`),
        );

      const child = spawn(resolvePython(), args, { cwd: REPO_ROOT, env: process.env });
      let buffer = "";
      let tail = "";

      child.stderr.on("data", (chunk: Buffer) => {
        buffer += chunk.toString();
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          tail = `${tail}\n${line}`.slice(-4000);
          send("progress", { line: line.replace(/^\[scout] /, "") });
        }
      });

      child.on("error", (err) => {
        send("failed", { error: err.message });
        controller.close();
      });

      child.on("close", async (code) => {
        try {
          if (code !== 0) {
            send("failed", { error: "Scan failed.", detail: tail });
          } else {
            send("result", JSON.parse(await readFile(jsonPath, "utf-8")));
          }
        } catch (err) {
          send("failed", {
            error: err instanceof Error ? err.message : "Could not read the result.",
          });
        } finally {
          await rm(workDir, { recursive: true, force: true });
          controller.close();
        }
      });

      // A closed tab must not leave a four-minute scan running.
      request.signal.addEventListener("abort", () => {
        child.kill("SIGTERM");
      });
    },
  });

  return new Response(stream, {
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
    },
  });
}
```

- [ ] **Step 2: Type-check**

Run: `cd dashboard && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Verify the stream by hand against a real CV**

Run (requires Task 4's `scout/profiles/` to exist):
```bash
cd dashboard && npx next dev -p 3099 &
sleep 6
curl -N --max-time 90 "localhost:3099/api/scout/stream?cv=backend-streaming" | head -20
pkill -f "next dev"
```
Expected: a series of `event: progress` frames naming real sources
(`querying …`, `karriere.at …`), then `event: result`.

- [ ] **Step 4: Commit**

```bash
git add dashboard/app/api/scout/stream/route.ts
git commit -m "feat(dashboard): stream scan progress as SSE instead of a blank spinner"
```

---

### Task 11: The one dashboard — switcher, settings, board, status strip

**Files:**
- Create: `dashboard/components/CvSwitcher.tsx`, `dashboard/components/CvSettings.tsx`
- Modify: `dashboard/app/scout/page.tsx`, `dashboard/components/Nav.tsx`
- Test: `dashboard/tests/cv-dashboard.spec.ts`

- [ ] **Step 1: Write `dashboard/components/CvSwitcher.tsx`**

```tsx
"use client";

import type { CvProfile } from "@/lib/cvProfiles";

/**
 * The CV picker. Four tabs and a "New CV" button, because the product's whole
 * shape is "which of my CVs am I looking at right now".
 */
export function CvSwitcher({
  profiles,
  activeId,
  onSelect,
  onCreate,
  disabled,
}: {
  profiles: CvProfile[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  disabled?: boolean;
}) {
  return (
    <div
      data-testid="cv-switcher"
      className="flex flex-wrap items-center gap-2 border-b border-gray-200 pb-3"
    >
      {profiles.map((profile) => (
        <button
          key={profile.id}
          type="button"
          data-testid={`cv-tab-${profile.id}`}
          data-active={profile.id === activeId ? "true" : "false"}
          onClick={() => onSelect(profile.id)}
          className={
            profile.id === activeId
              ? "rounded-full bg-gray-900 px-4 py-1.5 text-sm font-medium text-white"
              : "rounded-full border border-gray-300 px-4 py-1.5 text-sm text-gray-700 hover:border-gray-400"
          }
        >
          {profile.label}
          {!profile.enabled && (
            <span
              data-testid={`cv-tab-${profile.id}-paused`}
              className="ml-2 text-xs opacity-70"
            >
              paused
            </span>
          )}
        </button>
      ))}

      <button
        type="button"
        data-testid="cv-new"
        onClick={onCreate}
        disabled={disabled}
        className="rounded-full border border-dashed border-gray-400 px-4 py-1.5 text-sm text-gray-600 hover:border-gray-600 disabled:cursor-not-allowed disabled:opacity-50"
      >
        + New CV
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Write `dashboard/components/CvSettings.tsx`**

```tsx
"use client";

import { useState } from "react";
import type { CvProfile } from "@/lib/cvProfiles";

const HOURS = Array.from({ length: 24 }, (_, h) => h);

/**
 * Schedule, filters and alert threshold for one CV.
 *
 * hours_utc is UTC and says so on screen: [5] is 07:00 in Vienna in summer and
 * 06:00 in winter. A one-hour seasonal drift on a pre-working-day scan is not
 * worth a timezone field and its DST edge cases, but it is worth a label.
 *
 * The threshold is compared against match_pct — the deterministic skill overlap
 * — never against `fit`, which only exists when NVIDIA_API_KEY is set.
 */
export function CvSettings({
  profile,
  readOnly,
  onSave,
}: {
  profile: CvProfile;
  readOnly: boolean;
  onSave: (profile: CvProfile) => Promise<void>;
}) {
  const [draft, setDraft] = useState<CvProfile>(profile);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function toggleHour(hour: number) {
    const hours = draft.schedule.hours_utc.includes(hour)
      ? draft.schedule.hours_utc.filter((h) => h !== hour)
      : [...draft.schedule.hours_utc, hour].sort((a, b) => a - b);
    setDraft({ ...draft, schedule: { ...draft.schedule, hours_utc: hours } });
    setSaved(false);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await onSave(draft);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  const tooManyHours = draft.schedule.hours_utc.length > 4;
  const noHours = draft.schedule.hours_utc.length === 0;

  return (
    <section data-testid="cv-settings" className="space-y-6 rounded-lg border border-gray-200 p-5">
      <div>
        <h2 className="text-sm font-semibold text-gray-900">Schedule (UTC)</h2>
        <p className="mt-1 text-xs text-gray-500">
          Up to 4 hours a day. Times are UTC — 05 UTC is 07:00 in Vienna in summer.
        </p>
        <div data-testid="cv-hours" className="mt-3 flex flex-wrap gap-1">
          {HOURS.map((hour) => (
            <button
              key={hour}
              type="button"
              disabled={readOnly}
              data-testid={`cv-hour-${hour}`}
              data-selected={draft.schedule.hours_utc.includes(hour) ? "true" : "false"}
              onClick={() => toggleHour(hour)}
              className={
                draft.schedule.hours_utc.includes(hour)
                  ? "w-10 rounded bg-gray-900 py-1 text-xs text-white"
                  : "w-10 rounded border border-gray-300 py-1 text-xs text-gray-600 disabled:opacity-50"
              }
            >
              {String(hour).padStart(2, "0")}
            </button>
          ))}
        </div>
        {noHours && (
          <p data-testid="cv-hours-error" className="mt-2 text-xs text-red-600">
            Pick at least one hour, or this CV never runs.
          </p>
        )}
        {tooManyHours && (
          <p data-testid="cv-hours-error" className="mt-2 text-xs text-red-600">
            At most 4 hours per CV.
          </p>
        )}
        <label className="mt-3 flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            data-testid="cv-weekdays-only"
            disabled={readOnly}
            checked={draft.schedule.weekdays_only}
            onChange={(e) => {
              setDraft({
                ...draft,
                schedule: { ...draft.schedule, weekdays_only: e.target.checked },
              });
              setSaved(false);
            }}
          />
          Weekdays only
        </label>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <label className="text-sm text-gray-700">
          Posted within (days)
          <input
            type="number"
            min={1}
            max={90}
            data-testid="cv-days"
            disabled={readOnly}
            value={draft.filters.days}
            onChange={(e) => {
              setDraft({
                ...draft,
                filters: { ...draft.filters, days: Number(e.target.value) },
              });
              setSaved(false);
            }}
            className="mt-1 w-full rounded border border-gray-300 px-2 py-1"
          />
        </label>
        <label className="text-sm text-gray-700">
          Publish top N
          <input
            type="number"
            min={1}
            max={100}
            data-testid="cv-top"
            disabled={readOnly}
            value={draft.filters.top}
            onChange={(e) => {
              setDraft({
                ...draft,
                filters: { ...draft.filters, top: Number(e.target.value) },
              });
              setSaved(false);
            }}
            className="mt-1 w-full rounded border border-gray-300 px-2 py-1"
          />
        </label>
        <label className="text-sm text-gray-700">
          Alert at match ≥ (%)
          <input
            type="number"
            min={0}
            max={100}
            data-testid="cv-min-match"
            disabled={readOnly}
            value={draft.alert.min_match}
            onChange={(e) => {
              setDraft({ ...draft, alert: { min_match: Number(e.target.value) } });
              setSaved(false);
            }}
            className="mt-1 w-full rounded border border-gray-300 px-2 py-1"
          />
          <span className="mt-1 block text-xs text-gray-500">
            Compared against match %, the skill overlap — not the LLM fit score.
          </span>
        </label>
        <label className="flex items-end gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            data-testid="cv-require-salary"
            disabled={readOnly}
            checked={draft.filters.require_salary}
            onChange={(e) => {
              setDraft({
                ...draft,
                filters: { ...draft.filters, require_salary: e.target.checked },
              });
              setSaved(false);
            }}
          />
          Only ads that state a salary
        </label>
      </div>

      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input
          type="checkbox"
          data-testid="cv-enabled"
          disabled={readOnly}
          checked={draft.enabled}
          onChange={(e) => {
            setDraft({ ...draft, enabled: e.target.checked });
            setSaved(false);
          }}
        />
        Scan this CV on its schedule
      </label>

      <div className="flex items-center gap-3">
        <button
          type="button"
          data-testid="cv-save"
          disabled={readOnly || saving || noHours || tooManyHours}
          onClick={save}
          className="rounded bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        {saved && (
          <span data-testid="cv-saved" className="text-sm text-green-700">
            Saved to scout/profiles.json — commit and push to apply it to the schedule.
          </span>
        )}
        {error && (
          <span data-testid="cv-save-error" className="text-sm text-red-600">
            {error}
          </span>
        )}
      </div>
    </section>
  );
}
```

- [ ] **Step 3: Rewrite `dashboard/app/scout/page.tsx` as the one dashboard**

This replaces the file wholesale — the code below is complete, including the
upload form, so nothing needs to be salvaged from the old version. Read the old
file only to check whether it used any `data-testid` that `scout.spec.ts` still
asserts on; if it did, keep that id on the corresponding new element rather than
editing the spec.

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import type { ScoutResult } from "@/app/api/scout/route";
import type { CvProfile } from "@/lib/cvProfiles";
import { CvSettings } from "@/components/CvSettings";
import { CvSwitcher } from "@/components/CvSwitcher";
import { MatchesView } from "@/components/MatchesView";

/**
 * The dashboard. One page: pick a CV, configure its scanner, scan it now, read
 * its board.
 *
 * Config is written into the working tree, never pushed: the repository is
 * public and nothing should reach it unattended. Saving tells you which files
 * changed; you commit them.
 */
export default function ScoutDashboard() {
  const [profiles, setProfiles] = useState<CvProfile[]>([]);
  const [writable, setWritable] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [result, setResult] = useState<ScoutResult | null>(null);
  const [progress, setProgress] = useState<string[]>([]);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    const res = await fetch("/api/cv");
    const data = await res.json();
    setProfiles(data.profiles);
    setWritable(data.writable);
    setActiveId((current) => current ?? data.profiles[0]?.id ?? null);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const active = profiles.find((p) => p.id === activeId) ?? null;

  // The board follows the switcher: selecting a CV replaces the rows, not just
  // a heading.
  useEffect(() => {
    if (!activeId) return;
    setResult(null);
    void fetch(`/api/feed?cv=${activeId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => setResult(data?.result ?? null))
      .catch(() => setResult(null));
  }, [activeId]);

  function scanNow() {
    if (!activeId) return;
    setScanning(true);
    setProgress([]);
    setError(null);
    const source = new EventSource(`/api/scout/stream?cv=${activeId}`);
    source.addEventListener("progress", (e) => {
      setProgress((lines) => [...lines, JSON.parse((e as MessageEvent).data).line]);
    });
    source.addEventListener("result", (e) => {
      setResult(JSON.parse((e as MessageEvent).data) as ScoutResult);
      setScanning(false);
      source.close();
    });
    source.addEventListener("failed", (e) => {
      setError(JSON.parse((e as MessageEvent).data).error);
      setScanning(false);
      source.close();
    });
  }

  async function saveProfile(profile: CvProfile) {
    const res = await fetch("/api/cv", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(profile),
    });
    if (!res.ok) throw new Error((await res.json()).error ?? "Save failed.");
    await load();
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-gray-900">Scout</h1>
        <p className="mt-1 text-sm text-gray-600">
          One board per CV. Each scans on its own schedule and alerts on its own
          threshold.
        </p>
      </header>

      {!writable && (
        <div
          data-testid="config-readonly"
          className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800"
        >
          Config is read-only here — this dashboard cannot reach the repository&apos;s{" "}
          <code>scout/</code> directory. The board still works; to change schedules
          or add a CV, run the dashboard locally with <code>npm run dev</code> from
          the checkout.
        </div>
      )}

      <CvSwitcher
        profiles={profiles}
        activeId={activeId}
        onSelect={setActiveId}
        onCreate={() => setCreating(true)}
        disabled={!writable}
      />

      {creating && (
        <NewCvForm
          onDone={async () => {
            setCreating(false);
            await load();
          }}
          onCancel={() => setCreating(false)}
        />
      )}

      {active && (
        <>
          <div className="flex items-center gap-3">
            <button
              type="button"
              data-testid="scan-now"
              disabled={scanning}
              onClick={scanNow}
              className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {scanning ? "Scanning…" : "Scan now"}
            </button>
            {scanning && (
              <span data-testid="scan-progress" className="text-sm text-gray-600">
                {progress[progress.length - 1] ?? "starting…"}
              </span>
            )}
            {error && (
              <span data-testid="scan-error" className="text-sm text-red-600">
                {error}
              </span>
            )}

            <button
              type="button"
              data-testid="cv-remove"
              disabled={!writable}
              onClick={async () => {
                // Config-only. Alert history and published results stay on
                // scout-data, so a typo'd removal costs nothing permanent.
                if (!confirm(`Remove "${active.label}" from the scan schedule?`)) return;
                await fetch(`/api/cv?id=${active.id}`, { method: "DELETE" });
                setActiveId(null);
                await load();
              }}
              className="ml-auto text-sm text-gray-500 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Remove CV
            </button>
          </div>

          <CvSettings profile={active} readOnly={!writable} onSave={saveProfile} />

          {result ? (
            <MatchesView result={result} origin={null} />
          ) : (
            <p data-testid="cv-board-empty" className="text-sm text-gray-500">
              No scan for {active.label} yet. Press “Scan now”, or wait for its
              scheduled run.
            </p>
          )}
        </>
      )}
    </div>
  );
}

function NewCvForm({
  onDone,
  onCancel,
}: {
  onDone: () => void | Promise<void>;
  onCancel: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <form
      data-testid="cv-new-form"
      className="space-y-3 rounded-lg border border-gray-200 p-5"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        const res = await fetch("/api/cv", {
          method: "POST",
          body: new FormData(e.currentTarget),
        });
        setBusy(false);
        if (!res.ok) {
          setError((await res.json()).error ?? "Could not add the CV.");
          return;
        }
        await onDone();
      }}
    >
      <p className="text-xs text-gray-500">
        The PDF stays on this machine (<code>data/cv/</code>, gitignored). Only the
        derived skill profile — no name, email or employer — is written to{" "}
        <code>scout/</code>, which is public.
      </p>
      <input
        name="id"
        data-testid="cv-new-id"
        required
        pattern="[a-z0-9-]{1,40}"
        placeholder="id (e.g. backend-streaming)"
        className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
      />
      <input
        name="label"
        data-testid="cv-new-label"
        required
        placeholder="Label (e.g. Backend / Streaming)"
        className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
      />
      <input
        name="cv"
        data-testid="cv-new-file"
        type="file"
        accept="application/pdf"
        required
        className="w-full text-sm"
      />
      <div className="flex items-center gap-3">
        <button
          type="submit"
          data-testid="cv-new-submit"
          disabled={busy}
          className="rounded bg-gray-900 px-4 py-2 text-sm text-white disabled:opacity-50"
        >
          {busy ? "Extracting…" : "Add CV"}
        </button>
        <button type="button" onClick={onCancel} className="text-sm text-gray-600">
          Cancel
        </button>
        {error && (
          <span data-testid="cv-new-error" className="text-sm text-red-600">
            {error}
          </span>
        )}
      </div>
    </form>
  );
}
```

- [ ] **Step 4: Add the feed API the page reads**

Create `dashboard/app/api/feed/route.ts`:

```ts
import { NextRequest, NextResponse } from "next/server";
import { loadFeed } from "@/lib/feed";

/** One CV's published board, for the client-side switcher. */
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const cv = request.nextUrl.searchParams.get("cv") ?? undefined;
  try {
    return NextResponse.json(await loadFeed(cv));
  } catch (err) {
    return NextResponse.json(
      { result: null, origin: null, error: err instanceof Error ? err.message : "Bad CV id." },
      { status: 400 },
    );
  }
}
```

- [ ] **Step 5: Collapse the nav to one entry**

In `dashboard/components/Nav.tsx`, replace the whole `<div className="flex gap-4 text-sm">` block with:

```tsx
            <div className="flex gap-4 text-sm">
              {/* One entry. /, /jobs, /runs and /matches still work by URL and
                  keep the AMS crawler pages reachable for debugging — deleting
                  them would orphan the Postgres schema the tests depend on —
                  but they are no longer part of the product's navigation. */}
              <Link
                href="/scout"
                className="text-gray-700 hover:text-gray-900"
                data-testid="nav-link-scout"
              >
                Dashboard
              </Link>
            </div>
```

- [ ] **Step 6: Point Playwright's server at a fixture config root**

In `dashboard/playwright.config.ts`, inside `webServer.env`, add:

```ts
      // Config writes go into a fixture tree, never the real scout/. Separate
      // from SCOUT_REPO_ROOT, which must stay pointed at the checkout so the
      // scan route can still find scripts/scout.py.
      SCOUT_CONFIG_ROOT: require("node:path").resolve(__dirname, "tests/fixtures/config-root"),
      SCOUT_FEED_DIR: require("node:path").resolve(__dirname, "tests/fixtures/config-root"),
```

In `dashboard/tests/global-setup.ts`, before returning, seed that tree:

```ts
  // A known-good config for the dashboard specs: two CVs, one with a board.
  const configRoot = path.resolve(__dirname, "fixtures/config-root");
  await fs.rm(configRoot, { recursive: true, force: true });
  await fs.mkdir(path.join(configRoot, "scout", "profiles"), { recursive: true });
  await fs.mkdir(path.join(configRoot, "results"), { recursive: true });
  await fs.writeFile(
    path.join(configRoot, "scout", "profiles.json"),
    JSON.stringify(
      {
        version: 1,
        profiles: [
          {
            id: "backend-streaming",
            label: "Backend / Streaming",
            enabled: true,
            schedule: { hours_utc: [5], weekdays_only: false },
            filters: { days: 7, top: 50, require_salary: false, sources: "apis" },
            alert: { min_match: 75 },
          },
          {
            id: "devops-sre",
            label: "DevOps / SRE",
            enabled: true,
            schedule: { hours_utc: [15], weekdays_only: false },
            filters: { days: 7, top: 50, require_salary: false, sources: "apis" },
            alert: { min_match: 80 },
          },
        ],
      },
      null,
      2,
    ),
  );
  for (const [id, title] of [
    ["backend-streaming", "Senior .NET Engineer"],
    ["devops-sre", "Platform Engineer"],
  ]) {
    await fs.writeFile(
      path.join(configRoot, "results", `${id}.json`),
      JSON.stringify({
        generated_at: "2026-07-31T05:10:00",
        cv: `scout/profiles/${id}.json`,
        profile_source: "lexicon",
        total_matches: 1,
        jobs: [
          {
            title,
            company: "Bosch",
            location: "Wien",
            posted: "2026-07-30",
            salary: 75000,
            source: "test",
            apply_url: "https://example.com/1",
            score: 40,
            rank: 1,
            rank_score: 100,
            match_pct: 86,
            matched_skills: ["dotnet"],
            profile_skills: ["dotnet"],
            fit: null,
            reason: null,
            bucket: null,
          },
        ],
      }),
    );
  }
```

Also generate the fixture PDF the new-CV test uploads (the repo already has a
generator, so the fixture is never a committed binary that drifts):

```ts
  // A syntactically valid PDF with real CV-ish text, so scout.py --profile-only
  // extracts a non-empty lexicon profile. Generated, not committed: a binary
  // fixture in git is a thing nobody can review in a diff.
  const fixturePdf = path.resolve(__dirname, "fixtures/test-cv.pdf");
  await new Promise<void>((resolve, reject) => {
    const child = spawn(
      process.env.SCOUT_PYTHON_BIN ??
        path.resolve(__dirname, "../../.venv/bin/python"),
      [path.resolve(__dirname, "../../scripts/make_test_cv.py"), fixturePdf],
      { stdio: "inherit" },
    );
    child.on("error", reject);
    child.on("close", (code) =>
      code === 0 ? resolve() : reject(new Error(`make_test_cv.py exited ${code}`)),
    );
  });
```

(add `import fs from "node:fs/promises";`, `import path from "node:path";` and
`import { spawn } from "node:child_process";` if the file does not already have
them).

**Verify the generator's CLI first:** run
`.venv/bin/python scripts/make_test_cv.py /tmp/x.pdf && ls -l /tmp/x.pdf`.
If it takes no path argument, read `scripts/make_test_cv.py` and adjust the
invocation — do not guess.

Add `dashboard/tests/fixtures/test-cv.pdf` to `.gitignore` so the generated
fixture is not committed:

```bash
echo "dashboard/tests/fixtures/test-cv.pdf" >> .gitignore
```

- [ ] **Step 7: Write `dashboard/tests/cv-dashboard.spec.ts`**

```ts
import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";

const CONFIG_ROOT = path.resolve(__dirname, "fixtures/config-root");

test.describe("the CV dashboard", () => {
  test("nav has exactly one entry", async ({ page }) => {
    await page.goto("/scout");
    const links = page.getByTestId("nav").locator("a[data-testid^='nav-link-']");
    await expect(links).toHaveCount(1);
    await expect(page.getByTestId("nav-link-scout")).toHaveText("Dashboard");
  });

  test("the switcher lists every configured CV", async ({ page }) => {
    await page.goto("/scout");
    await expect(page.getByTestId("cv-tab-backend-streaming")).toBeVisible();
    await expect(page.getByTestId("cv-tab-devops-sre")).toBeVisible();
  });

  test("switching CV replaces the board's rows, not just a label", async ({ page }) => {
    await page.goto("/scout");
    await expect(page.getByText("Senior .NET Engineer")).toBeVisible();
    await expect(page.getByText("Platform Engineer")).toHaveCount(0);

    await page.getByTestId("cv-tab-devops-sre").click();
    await expect(page.getByText("Platform Engineer")).toBeVisible();
    await expect(page.getByText("Senior .NET Engineer")).toHaveCount(0);
  });

  test("saving a schedule persists across reload and lands in profiles.json", async ({ page }) => {
    await page.goto("/scout");
    await page.getByTestId("cv-tab-backend-streaming").click();

    await expect(page.getByTestId("cv-hour-5")).toHaveAttribute("data-selected", "true");
    await page.getByTestId("cv-hour-15").click();
    await page.getByTestId("cv-save").click();
    await expect(page.getByTestId("cv-saved")).toBeVisible();

    const written = JSON.parse(
      await fs.readFile(path.join(CONFIG_ROOT, "scout", "profiles.json"), "utf-8"),
    );
    const profile = written.profiles.find((p: { id: string }) => p.id === "backend-streaming");
    expect(profile.schedule.hours_utc).toEqual([5, 15]);

    await page.reload();
    await expect(page.getByTestId("cv-hour-15")).toHaveAttribute("data-selected", "true");
  });

  test("a fifth scheduled hour is refused before it can be saved", async ({ page }) => {
    await page.goto("/scout");
    for (const hour of [0, 8, 12, 20]) {
      await page.getByTestId(`cv-hour-${hour}`).click();
    }
    await expect(page.getByTestId("cv-hours-error")).toContainText("At most 4");
    await expect(page.getByTestId("cv-save")).toBeDisabled();
  });

  test("clearing the schedule is refused", async ({ page }) => {
    await page.goto("/scout");
    await page.getByTestId("cv-hour-5").click();      // deselect the only hour
    await expect(page.getByTestId("cv-hours-error")).toContainText("at least one hour");
    await expect(page.getByTestId("cv-save")).toBeDisabled();
  });

  test("the new-CV form states that the PDF stays local", async ({ page }) => {
    await page.goto("/scout");
    await page.getByTestId("cv-new").click();
    await expect(page.getByTestId("cv-new-form")).toContainText("stays on this machine");
    await expect(page.getByTestId("cv-new-form")).toContainText("public");
  });

  test("the new-CV flow adds a switcher entry and writes the expected files", async ({ page }) => {
    // A real upload through a real scout.py --profile-only. No network: profile
    // extraction with no NVIDIA_API_KEY is the keyword lexicon, ~1s.
    const pdf = path.resolve(__dirname, "fixtures/test-cv.pdf");
    await page.goto("/scout");
    await page.getByTestId("cv-new").click();
    await page.getByTestId("cv-new-id").fill("plan-test-cv");
    await page.getByTestId("cv-new-label").fill("Plan Test CV");
    await page.getByTestId("cv-new-file").setInputFiles(pdf);
    await page.getByTestId("cv-new-submit").click();

    await expect(page.getByTestId("cv-tab-plan-test-cv")).toBeVisible({ timeout: 30_000 });

    const doc = JSON.parse(
      await fs.readFile(
        path.join(CONFIG_ROOT, "scout", "profiles", "plan-test-cv.json"),
        "utf-8",
      ),
    );
    // The publish whitelist, asserted on the file that actually reaches the
    // public repo — not on the function that wrote it.
    expect(Object.keys(doc).sort()).toEqual(["role_titles", "skills", "source"]);

    const config = JSON.parse(
      await fs.readFile(path.join(CONFIG_ROOT, "scout", "profiles.json"), "utf-8"),
    );
    expect(config.profiles.map((p: { id: string }) => p.id)).toContain("plan-test-cv");
  });

  test("removing a CV drops it from config and says history is kept", async ({ page }) => {
    const before = JSON.parse(
      await fs.readFile(path.join(CONFIG_ROOT, "scout", "profiles.json"), "utf-8"),
    );
    test.skip(
      !before.profiles.some((p: { id: string }) => p.id === "plan-test-cv"),
      "depends on the new-CV test having run",
    );

    await page.goto("/scout");
    page.on("dialog", (d) => d.accept());
    await page.getByTestId("cv-tab-plan-test-cv").click();
    await page.getByTestId("cv-remove").click();

    await expect(page.getByTestId("cv-tab-plan-test-cv")).toHaveCount(0);
    const after = JSON.parse(
      await fs.readFile(path.join(CONFIG_ROOT, "scout", "profiles.json"), "utf-8"),
    );
    expect(after.profiles.map((p: { id: string }) => p.id)).not.toContain("plan-test-cv");
    // The profile document itself is left on disk deliberately: config removal
    // is not a destructive delete.
    await expect(
      fs.access(path.join(CONFIG_ROOT, "scout", "profiles", "plan-test-cv.json")),
    ).resolves.toBeUndefined();
  });

  test("read-only mode shows the notice and disables save", async ({ page }) => {
    // Simulate the container: no reachable scout/ directory.
    await page.route("**/api/cv", async (route) => {
      if (route.request().method() !== "GET") return route.continue();
      await route.fulfill({
        json: { profiles: JSON.parse(
          await fs.readFile(path.join(CONFIG_ROOT, "scout", "profiles.json"), "utf-8"),
        ).profiles, writable: false },
      });
    });
    await page.goto("/scout");
    await expect(page.getByTestId("config-readonly")).toBeVisible();
    await expect(page.getByTestId("cv-save")).toBeDisabled();
    await expect(page.getByTestId("cv-new")).toBeDisabled();
  });

  test("no console errors on the dashboard", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });
    await page.goto("/scout");
    await page.getByTestId("cv-tab-devops-sre").click();
    await expect(page.getByText("Platform Engineer")).toBeVisible();
    expect(errors).toEqual([]);
  });
});
```

**Ordering note:** the "saving a schedule persists" test mutates the fixture
`profiles.json`, and the "a fifth scheduled hour" test asserts against the
starting `[5]`. Playwright runs files in parallel but tests within a file
serially, and these two are in the same file — but the fifth-hour test would then
see `[5, 15]`. Fix it by making that test independent: it clicks 4 more hours, so
it exceeds 4 from either starting point. If it proves flaky, re-seed the fixture
in a `test.beforeEach` that re-runs the global-setup seeding block.

- [ ] **Step 8: Run the dashboard spec**

Run:
```bash
cd dashboard && DASHBOARD_PORT=3021 NEXT_DIST_DIR=.next-test \
  npx playwright test tests/cv-dashboard.spec.ts --reporter=dot
```
Expected: 11 passed, 0 skipped. The remove test skips only if the add test that
precedes it in the same file did not run — a skip here means the add test broke.

- [ ] **Step 9: Update the four existing assertions the nav change breaks**

Exactly four call sites reference links that no longer exist:
`dashboard/tests/dashboard.spec.ts:168,170,172` and
`dashboard/tests/matches.spec.ts:99`.

In `dashboard/tests/dashboard.spec.ts`, replace the body of the test at line 166
(`"nav links go to overview, jobs, runs"`) with:

```ts
  // The nav is one entry now (the CV dashboard). These pages are deliberately
  // still served -- deleting them would orphan the AMS crawler and the Postgres
  // schema the rest of this suite depends on -- they are just unlinked, so they
  // are reached by URL.
  test("the crawler pages are still served, unlinked", async ({ page }) => {
    await page.goto("/jobs");
    await expect(page.getByTestId("job-table")).toBeVisible();
    await page.goto("/runs");
    await expect(page.getByTestId("run-table")).toBeVisible();
    await page.goto("/");
    await expect(page.getByTestId("nav-brand")).toBeVisible();
  });
```

If those two `data-testid`s differ, take the real ones from `JobTable.tsx` and
`RunTable.tsx` — do not invent them.

In `dashboard/tests/matches.spec.ts:99`, replace
`await page.getByTestId("nav-link-matches").click();` with
`await page.goto("/matches");`.

Then confirm nothing else refers to a removed link:

Run: `cd dashboard && grep -rn "nav-link-\(jobs\|runs\|overview\|matches\)" tests/ ; echo "exit=$?"`
Expected: `exit=1` (no matches).

- [ ] **Step 10: Commit**

```bash
git add dashboard/components/CvSwitcher.tsx dashboard/components/CvSettings.tsx \
  dashboard/app/scout/page.tsx dashboard/app/api/feed/route.ts \
  dashboard/components/Nav.tsx dashboard/playwright.config.ts \
  dashboard/tests/global-setup.ts dashboard/tests/cv-dashboard.spec.ts \
  dashboard/tests/dashboard.spec.ts dashboard/tests/matches.spec.ts .gitignore
git commit -m "feat(dashboard): one dashboard, N CVs, per-CV board and settings"
```

---

### Task 12: Fix the container's silently-empty board

**Files:**
- Modify: `docker-compose.yml:36`

The container mounts only `./dashboard`, so `REPO_ROOT` resolves to `/`, the read
of `/data/scout/latest.json` ENOENTs, and `feed.ts` treats ENOENT as the innocuous
"nobody has run the cron yet" state. The board shows nothing, with no error,
whatever the feed actually contains.

- [ ] **Step 1: Read the current service block**

Run: `grep -n -A 20 "dashboard:" docker-compose.yml`

- [ ] **Step 2: Add the feed base URL and a config-root that cannot be written**

In the dashboard service's `environment:` block:

```yaml
      # The container mounts only ./dashboard, so it can reach neither scout/
      # nor data/. Without this it read /data/scout/latest.json, got ENOENT, and
      # rendered the innocuous "no scan yet" empty state -- silently, whatever
      # the feed actually contained. Read the published feed over HTTP instead.
      SCOUT_FEED_BASE_URL: https://raw.githubusercontent.com/vladbrincoveanu/JobCrawler/scout-data
      # Config editing needs the repo checkout; in here it renders read-only
      # with an explanation. This is a limitation of the file-sync model, not a
      # bug: nothing is pushed to a public repo unattended.
      SCOUT_CONFIG_ROOT: /nonexistent
```

- [ ] **Step 3: Verify the container serves a populated board**

Run:
```bash
docker compose up -d dashboard
sleep 15
curl -s localhost:3000/api/feed?cv=backend-streaming | head -c 300
docker compose logs dashboard | grep -iE "error|fail" | head
docker compose down
```
Expected: JSON with a `result` object (or a *stated* `error` if the branch has no
results yet) — never `{"result":null,"error":null}`, which is the silent state
this task exists to remove.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "fix(docker): container read the wrong feed path and showed an empty board silently"
```

---

### Task 13: Document the setup

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the scout-cron section**

Find the section documenting `CV_PDF_BASE64` and replace it with:

```markdown
### Scheduled scans (multi-CV)

The cron wakes hourly and scans whichever CVs are due, per `scout/profiles.json`.

**Add a CV:** run the dashboard locally (`cd dashboard && npm run dev`), open
`/scout`, press "+ New CV" and upload the PDF. The PDF is written to `data/cv/`
(gitignored, never committed — this repository is public). Only the derived
profile — `{skills, role_titles, source}`, no name, email, phone or employer —
is written to `scout/profiles/<id>.json`. Commit and push `scout/` to apply it.

**No `CV_PDF_BASE64` secret any more.** Actions secrets cap at 48 KB and these
CVs are ~76 KB base64; gzip does not help (PDFs are already compressed). The
runner reads the committed profile instead, which also saves a PDF parse and an
LLM extraction call on every wake.

**Secrets to set** (the dashboard prints these commands when you enter the
values; it never writes them itself):

```bash
gh secret set TELEGRAM_BOT_TOKEN
gh secret set TELEGRAM_CHAT_ID
gh secret set NVIDIA_API_KEY     # optional: LLM rerank
gh secret set ADZUNA_APP_ID      # optional
gh secret set ADZUNA_APP_KEY     # optional
gh secret set JOOBLE_KEY         # optional
```

Locally the same values live in `.env.local` (gitignored). Nothing scheduled
runs and no alert sends until the repo secrets are set.

**Company reviews are local only.** Enrichment is one LLM call per unseen
company against a cache in `data/company_reviews/`, which is gitignored — a
runner is always cold, so the cron never passes `--company-reviews` and
`scripts/publish.py` strips `company_review` from anything published. Press
"Scan now" locally to fill the panels.

**Scheduling.** `hours_utc` is an explicit list of UTC hours, at most 4 per CV.
`[5]` is 07:00 in Vienna in summer, 06:00 in winter — a one-hour seasonal drift
on a pre-working-day scan, accepted rather than carrying a timezone field. A
slot is picked up by any wake within 6 hours of it, because GitHub delays
scheduled workflows on public repos routinely; a failed scan is retried once.

**Alerting** thresholds on `match_pct` (deterministic skill overlap), never on
`fit` (only set when `NVIDIA_API_KEY` is present — a `fit`-based cutoff would
send nothing at all on a keyless runner, silently). A CV's first scan records
every match and pushes nothing, so day one is not 200 Telegram messages.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: multi-CV setup, secrets, and why there is no CV secret any more"
```

---

## Phase 4 — verification gates

### Task 14: Coverage measurement

**Spec flag:** `test_scope: true`.

- [ ] **Step 1: Record the pre-change number**

Run: `git stash && .venv/bin/python -m pytest -q --cov=crawler --cov-fail-under=90 2>&1 | tail -5; git stash pop`
Expected: a `TOTAL` percentage — write it down.

(Skip the stash if the working tree is clean at this point, which it should be —
every task above ends in a commit. Use `git checkout main -- .` in a scratch
worktree instead if stashing is awkward.)

- [ ] **Step 2: Run the full suite on the new code**

Run: `.venv/bin/python -m pytest -q --cov=crawler --cov-fail-under=90`
Expected: 0 failures; `TOTAL` ≥ the number from Step 1.

- [ ] **Step 3: State plainly what this measures**

`pyproject.toml` sets `source = ["crawler"]` and `omit = ["scripts/*"]`. Every
Python file added by this plan lives in `scripts/`, so this number is unchanged
by design and is **not** evidence that `alerts.py`, `cv_schedule.py`,
`publish.py` or the `scout.py` flags are tested. Their evidence is
`tests/test_alerts.py` (11), `tests/test_cv_schedule.py` (15),
`tests/test_cron_publish.py` (3) and `tests/test_scout_profile_flag.py` (5).

Record both in the completion report: the coverage number, and the count of new
tests with what they cover. Reporting only the first would be the
"tests pass" claim rule 12 forbids.

- [ ] **Step 4: Confirm the new tests actually run and can fail**

Run: `.venv/bin/python -m pytest tests/test_alerts.py tests/test_cv_schedule.py tests/test_cron_publish.py tests/test_scout_profile_flag.py -q`
Expected: 34 passed, 0 skipped. **A skip here is a failure** — these tests need
no Postgres, so a skip means a collection error is being swallowed.

Then break one deliberately: change `WINDOW_HOURS = 6` to `1` in
`scripts/cv_schedule.py` and re-run.
Expected: `test_a_wake_at_0604_still_runs_the_0500_slot` FAILS. Revert.
A test that cannot fail when the logic changes is not a test (rule 9).

---

### Task 15: Visual verification

**Spec flag:** `ui_scope: true`. Reference: `~/.claude/skills/frontend-design/SKILL.md` §Visual verification loop.

- [ ] **Step 1: Start the dev server once**

Run: `cd dashboard && npm run dev &` then wait for `localhost:3000`.

- [ ] **Step 2: Screenshot `/scout` at three viewports**

Run:
```bash
cd dashboard && npx playwright screenshot --viewport-size=375,812 \
  http://localhost:3000/scout .frontend-design/baselines/scout-375.png
npx playwright screenshot --viewport-size=768,1024 \
  http://localhost:3000/scout .frontend-design/baselines/scout-768.png
npx playwright screenshot --viewport-size=1280,900 \
  http://localhost:3000/scout .frontend-design/baselines/scout-1280.png
```
Expected: three PNGs written.

- [ ] **Step 3: Check each for layout breakage**

Open each and confirm: the CV tabs wrap rather than overflow at 375px; the 24
hour buttons form a readable grid at every width; the match table scrolls
horizontally rather than clipping; nothing overlaps the nav.

Fix any breakage in `CvSwitcher.tsx` / `CvSettings.tsx` and re-shoot.

- [ ] **Step 4: Commit the baselines**

```bash
git add dashboard/.frontend-design/baselines/
git commit -m "test(dashboard): visual baselines for the CV dashboard"
```

---

### Task 16: Final gate

- [ ] **Step 1: Full Playwright suite**

Run:
```bash
cd dashboard && DASHBOARD_PORT=3021 NEXT_DIST_DIR=.next-test \
  npx playwright test --reporter=line
```
Expected: 0 failures. Per `.claude/rules/ui-testing.md` (as fixed in Task 0),
0 console errors on `/`, `/jobs`, `/runs`, `/scout`, `/matches`.

- [ ] **Step 2: Live scan smoke test**

Run:
```bash
cd dashboard && SCOUT_LIVE=1 DASHBOARD_PORT=3021 NEXT_DIST_DIR=.next-test \
  npx playwright test tests/scout-live.spec.ts --reporter=line
```
Expected: passes, including a real browser CV upload.

- [ ] **Step 3: Full pytest**

Run: `.venv/bin/python -m pytest -q --cov=crawler --cov-fail-under=90`
Expected: 0 failures, coverage ≥90%.

- [ ] **Step 4: Lint**

Run: `.venv/bin/python -m ruff check scripts/ tests/ && cd dashboard && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 5: Prove no secret is staged**

Run:
```bash
git diff --cached --name-only | xargs -r grep -lEi \
  'ghp_|github_pat_|nvapi-|TELEGRAM_BOT_TOKEN=|[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}' \
  && echo "SECRET OR PII STAGED — STOP" || echo "clean"
git status --short scout/ data/
```
Expected: `clean`, and `data/cv/`, `data/profiles/`, `data/scout/` all absent
from `git status` (gitignored).

- [ ] **Step 6: Stop the dev server**

Run: `pkill -f "next dev"`

- [ ] **Step 7: One real cron run**

Push the branch, set the two Telegram secrets, then trigger the workflow with
`force: true` and one CV:

```bash
gh workflow run scout-cron -f cv_id=backend-streaming
gh run watch
```
Expected: the run succeeds; `scout-data` gains
`results/backend-streaming.json`, `sent/backend-streaming.json` and
`runs/backend-streaming.json`; the first run is quiet (no Telegram message) and
`sent/` records every match.

Then verify the strip actually held:

```bash
gh api "repos/:owner/:repo/contents/results/backend-streaming.json?ref=scout-data" \
  --jq '.content' | base64 -d | grep -c company_review || echo "0 — clean"
```
Expected: `0 — clean`.

- [ ] **Step 8: Second run, to exercise the update path**

Run: `gh workflow run scout-cron -f cv_id=backend-streaming && gh run watch`
Expected: succeeds (this is the path that was broken before `f2f8733`), history
accumulates, and this time any match ≥75% that was not in `sent/` alerts.

---

## Known-unknowns carried into execution

Flagged, not solved, so nobody mistakes them for verified:

1. **The runner environment is still unexercised.** The publish path was verified
   with local git plumbing and an orphan-branch push, not on an Actions runner.
   Task 16 Step 7-8 is the first real run.
2. **Company reviews have never hit a live LLM** (no `NVIDIA_API_KEY` in this
   environment) — only fake-reply unit tests.
3. **Generated employer cons are already on `scout-data`** in every commit to
   date. Stripping future writes does not unpublish history. Whether to
   force-push the branch clean is a separate decision (spec Risk 5), deliberately
   out of scope here.
4. **Adzuna and Jooble remain keyless**, so those sources are logged skips.
5. **`crawler/sources/ams.py` parses a retired DOM** — pre-existing, untouched.
6. **`scout.annual_salary_eur()` annualises monthly pay 12× while `at_common`
   uses 14×** — pre-existing inconsistency, untouched, and it affects the
   `require_salary` filter's cutoff.
