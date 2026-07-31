---
title: Multi-CV Scout — one dashboard, N CV profiles, scheduled alerts
date: 2026-07-31
status: approved
ui_scope: true
graph_scope: false
test_scope: true
---

# Multi-CV Scout

## Problem

Today the product assumes exactly one CV. `/scout` takes a PDF upload and scans
once, statelessly. The scheduled scan (`.github/workflows/scout-cron.yml`) reads
a single `CV_PDF_BASE64` secret on a single hardcoded cron, and publishes one
`latest.json` that `/matches` renders. There is no way to keep several CVs, no
way to say when each should run, and the nav spreads five tabs across two
unrelated subsystems.

The user has four real CVs (AI/Agentic, Backend/Streaming, DevOps/SRE,
FullStack) and wants one dashboard: pick a CV, configure its scanner, get
alerted, switch to another, create more.

## Decisions taken

| Decision | Choice | Why |
| --- | --- | --- |
| Where scheduled scans run | GitHub Actions, one workflow looping N CVs | Free (public repo = unlimited minutes), reuses the existing pipeline, no host to own |
| Old `/jobs`, `/runs` tabs | Fold run status into the new dashboard; routes stay, unlinked | Deleting them orphans the AMS crawler + Postgres schema the tests still depend on |
| Alerting | Telegram, per CV | `send_telegram()` and chunking already exist |
| Config → GitHub | UI writes files, user commits | Nothing is pushed unattended to a **public** repo |
| Scan-now feedback | Stream per-source progress | A scan takes 30s–4m18s; a blank spinner already read as "hung" |

## Critical constraint: the repository is public

`github.com/vladbrincoveanu/JobCrawler` is PUBLIC. Anything committed is
world-readable forever. Two consequences drive the whole data model:

- **CV PDFs are never committed.** They stay on the local machine under
  `data/cv/` (already gitignored).
- **Only the derived profile is committed.** A profile is ~600 bytes of
  `{skills, role_titles, source}` — weighted keywords and job titles. It carries
  no name, email, phone, employer, or dates. Verified against all four cached
  profiles in `data/profiles/`.

This also sidesteps a hard blocker: GitHub Actions secrets cap at 48 KB, and
these CVs are ~76 KB base64. Gzip does not help (74 KB — PDFs are already
compressed), so one-secret-per-CV is not viable regardless.

**Rule:** `scout/` is a public directory. Any field added to it is published.
The file carries a header comment saying so.

## Architecture

```
Local (your Mac)                    Committed (public)          GitHub Actions
─────────────────                   ──────────────────          ──────────────
data/cv/<id>.pdf      ──extract──▶  scout/profiles/<id>.json ──▶ hourly cron
  (gitignored)                      scout/profiles.json          loops due CVs
                                      (schedule + filters)         │
dashboard (npm run dev)                                            │
  reads results ◀──────────────  scout-data branch  ◀──────────────┘
                                   results/<id>.json
                                   sent/<id>.json
                                   runs/<id>.json          ──▶ Telegram
```

The runner never sees a PDF. It reads a committed profile and scans. This makes
each scheduled run cheaper too: no PDF parse, no LLM profile-extraction call.

### Data model

`scout/profiles.json` — committed, the single source of truth:

```jsonc
{
  "version": 1,
  "profiles": [
    {
      "id": "backend-streaming",          // slug, unique, [a-z0-9-]{1,40}
      "label": "Backend / Streaming",
      "enabled": true,
      "schedule": { "hours_utc": [5], "weekdays_only": false },
      "filters": {
        "days": 7,
        "top": 50,
        "require_salary": false,
        "sources": "apis,karriere,adzuna,jooble"
      },
      "alert": { "min_fit": 75 }
    }
  ]
}
```

`schedule` is **one** form only: `hours_utc` is an explicit list of UTC hours at
which this CV runs. Daily-at-05:00 is `[5]`; twice a day is `[5, 15]`; hourly is
`[0..23]`. There is no `every: "24h"` field — expressing the same schedule two
ways is how the two drift apart.

### Profile precedence

Two profile stores now exist. The rule is explicit:

- `scout/profiles/<id>.json` — committed, authoritative for **scheduled** runs.
- `data/profiles/<digest>.json` — existing local content-hash cache,
  authoritative for **ad-hoc local uploads** where no CV id exists yet.

Two new `scout.py` flags, and only these two:

- `--profile <path>` — use this profile as-is; skip PDF reading and extraction
  entirely. Used by scheduled runs.
- `--profile-only <pdf>` — extract a profile from the PDF, write it, and exit
  without scanning. Used when the dashboard registers a new CV, so adding a CV
  takes a second rather than a full scan.

`--profile` always wins when passed. Without either flag, behaviour is exactly
as today.

### State on the `scout-data` orphan branch

| Path | Contents | Read by |
| --- | --- | --- |
| `results/<id>.json` | Latest ranked matches for that CV | Dashboard match board |
| `sent/<id>.json` | Alert dedupe: fingerprints already pushed | Alert step |
| `runs/<id>.json` | Last-run timestamp + status + counts | Due-check, status strip |

Per-CV `sent/` is required, not cosmetic: today's `data/sent_jobs.json` is a
single global map. Shared, an ad alerted for the DevOps CV would be silently
suppressed for the Backend CV, which is precisely the case the user cares about.

## Behaviour

### Due-check

The hourly cron wakes every hour, reads `profiles.json`, and runs a CV when
`enabled` and the current UTC hour is in `schedule.hours_utc` and
`runs/<id>.json` shows no successful run in this hour. Scans run sequentially;
four CVs at the observed worst case (~4m18s) is ~17 minutes, well inside the
6-hour job limit. `concurrency.group` stays, `cancel-in-progress: false`.

### Quiet first run

When a CV has no `sent/<id>.json`, the first scan **records every match as sent
and pushes nothing**. Without this, day one is four CVs × up to 50 matches ≈ 200
Telegram messages. The dashboard still shows the full board immediately; only
the push is suppressed, and only once per CV.

### Alerting

For each scanned CV: take matches with `fit >= alert.min_fit`, drop any
fingerprint already in `sent/<id>.json`, push the rest to Telegram as chunked
messages (chunking already exists), then append the fingerprints. Failure to
send must not lose the results — write `results/` before attempting the push.

### Deleting a CV

Removing an entry from `profiles.json` leaves its `results/`, `sent/`, `runs/`
files on `scout-data` untouched. They are small, and orphan state is preferable
to destroying alert history on a typo'd id. Reusing a deleted id resumes its old
sent-history — documented, not accidental.

## UI

One dashboard. The nav collapses to a single entry. `/`, `/jobs`, `/runs`
continue to work by URL and keep the crawler pages alive for debugging, but are
no longer linked.

Layout: a CV switcher across the top (your four, plus "New CV"); below it, for
the selected CV — upload/replace PDF, schedule + filters + alert threshold,
**Scan now**, and the match board. Crawler run status (last run, errors, job
counts) folds into a compact strip rather than owning two tabs.

Saving writes `scout/profiles.json` and `scout/profiles/<id>.json` into the
working tree and shows the resulting diff. The user commits and pushes.

**Constraint:** config writing requires the dashboard to run locally
(`npm run dev`) with the repo root as its parent. The Docker container mounts
only `./dashboard`, so it cannot reach `scout/` — in the container the config
editor renders read-only with an explanatory notice. This is a real limitation
of the chosen sync model, not a bug to fix later.

### Scan-now streaming

`scout.py` already writes progress via `log()` to **stderr** (line 112) while
`--json-out` writes results to a **file** — the two never collide. The API route
streams stderr lines to the browser as server-sent events, so the user sees
`karriere.at: 41 ads … Remotive: 12 … scoring` instead of a blank four-minute
spinner.

## Modules

### Module: `lib/cvProfiles.ts`
- **Responsibility:** Read, validate and write `scout/profiles.json`.
- **Interface:** In — profile objects. Out — typed profile list; write returns the changed paths. Throws on duplicate/invalid id, empty `hours_utc`, `min_fit` outside 0–100.
- **Dependencies:** `node:fs`, repo-root resolution (`SCOUT_REPO_ROOT`).
- **Size target:** ~150 lines.

### Module: `app/api/cv/route.ts`
- **Responsibility:** CRUD one CV — accept a PDF, extract its profile only (no scan), persist PDF locally and profile to `scout/`.
- **Interface:** In — multipart PDF + metadata. Out — saved profile JSON + diff paths.
- **Dependencies:** `lib/cvProfiles`, `scout.py --profile-only`.
- **Size target:** ~150 lines.

### Module: `app/api/scout/stream/route.ts`
- **Responsibility:** Run a scan for one CV and stream progress as SSE.
- **Interface:** In — CV id + filter overrides. Out — SSE progress events, then a final result event.
- **Dependencies:** `scout.py` (stderr), existing `/api/scout` spawn logic.
- **Size target:** ~150 lines.

### Module: `components/CvSwitcher.tsx`
- **Responsibility:** Select the active CV; create a new one.
- **Interface:** In — profile list, active id. Out — `onSelect`, `onCreate`.
- **Dependencies:** none beyond React.
- **Size target:** ~120 lines.

### Module: `components/CvSettings.tsx`
- **Responsibility:** Edit schedule, filters and alert threshold for the active CV.
- **Interface:** In — one profile. Out — `onSave(profile)`.
- **Dependencies:** `lib/cvProfiles` types.
- **Size target:** ~180 lines.

### Module: `lib/feed.ts` (exists — extend)
- **Responsibility:** Load a CV's results feed; currently single `latest.json`.
- **Interface:** In — CV id. Out — parsed feed or a typed empty/error state.
- **Dependencies:** existing loader; keeps its missing-feed and unparseable-feed behaviour.
- **Size target:** +60 lines on the existing file.

### Module: `scripts/alerts.py`
- **Responsibility:** Threshold-filter a result set, apply per-CV sent-state (including quiet first run), push Telegram.
- **Interface:** In — results JSON, CV id, `min_fit`. Out — updated `sent/<id>.json`; sends messages.
- **Dependencies:** `scout.py`'s `send_telegram()` and `resolve_telegram()`.
- **Size target:** ~150 lines.

### Module: `.github/workflows/scout-cron.yml` (exists — rewrite)
- **Responsibility:** Hourly wake, due-check, sequential per-CV scan, publish, alert.
- **Interface:** In — `profiles.json` + `scout-data` state + secrets. Out — updated `scout-data` branch.
- **Dependencies:** `scout.py --profile`, `alerts.py`.
- **Size target:** ~120 lines of YAML.

## Testing

`test_scope: true`, `ui_scope: true`. Per the project rule, every implementation
cycle ends with Playwright assertions against the **real rendered DOM** — real
selectors, text and element counts, scoped to the visible container — not
screenshots and not "it compiles".

**Playwright (per cycle, non-skippable):**
- Switching CV changes the board's rendered rows, not just a label.
- Saving a schedule persists across reload.
- New-CV flow adds a switcher entry and writes the expected files.
- Container/read-only mode renders the notice and disables save.

**pytest:**
- `--profile` path skips extraction and produces the same scoring as a PDF run.
- Due-check: correct hour runs, wrong hour skips, disabled skips, already-run-this-hour skips.
- Per-CV sent-state isolation: same ad alerts on two CVs independently.
- Quiet first run pushes nothing and records everything.

Coverage gate stays at ≥90% (`--cov=crawler --cov-fail-under=90`).

## Risks

1. ~~**The cron publish path has never executed on GitHub.**~~ **Verified
   locally, and it was broken.** Replaying the publish step against a throwaway
   branch showed the orphan-create path works but the update path fails on every
   run after the first: `actions/checkout` sets a narrow fetch refspec, so
   `git fetch origin $FEED_BRANCH` never creates `origin/$FEED_BRANCH` and the
   checkout dies with `not a commit`. Fixed by checking out `FETCH_HEAD`;
   re-verified across two runs with history accumulating correctly and the raw
   URL readable. Note this was verified with local git plumbing, not on an
   Actions runner — the runner environment itself is still unexercised.
2. **GitHub disables scheduled workflows on public repos after 60 days without
   commits.** Silent failure: alerts simply stop. The workflow logs a heartbeat
   into `runs/` so a stale timestamp is visible on the dashboard.
3. **Scan-time variance is unexplained** — 29.7s vs 4m18s for the same CV and
   endpoint. Streaming will expose which source stalls; if it is karriere.at's
   Playwright path, it may need a per-source timeout.
4. **`scout/` is public.** Profiles are PII-free today, but every future field
   added there is published. Enforced by a header comment and review, not code.

## Out of scope

Deleting the crawler pages or schema. Deploying the dashboard. Per-CV LLM
tuning. Multi-user support. StepStone (still WAF-blocked) and jobhive (still
minutes-long parquet download) stay out of the default source set.
