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
| Alert credentials | Entered in the UI, written to gitignored `.env.local`; user mirrors to GitHub secrets | Public repo — a committed token is a published token; no PAT stored in the app |
| Company reviews | **Local only.** Dropped from the cron entirely | The runner's cache is always cold and its results can't reach the Mac once stripped from the feed; enriching where the cache lives costs nothing |
| Who sends alerts | `scripts/alerts.py`, sole owner. `scout.py`'s native Telegram path stays for manual CLI use, documented legacy | Two senders with two sent-stores would drift; the cron already runs `--json-out`, which returns before that path |
| Alert threshold field | `match_pct`, not `fit` | `fit` is only set when `NVIDIA_API_KEY` is present, so a `fit >= 75` cutoff silently alerts nothing without a key |

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

**Company reviews are never published.** `company_review` is stripped from
anything written to `scout-data`. Today it is not: `scout-cron.yml` runs with
`--company-reviews`, `scout.py:1019` copies the field into every published job,
and the result is committed to a public branch — so model-*generated* cons about
named real employers ("management churn", "low pay") are world-readable right
now, with `company_reviews.py`'s own "not a source of fact, may invent something
plausible for a small company" caveat living only in the dashboard UI. Dropping
`--company-reviews` from the cron removes the source; the publish step strips the
key regardless, so a hand-run local scan cannot leak it either.

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
      "alert": { "min_match": 75 }
    }
  ]
}
```

`schedule` is **one** form only: `hours_utc` is an explicit list of UTC hours at
which this CV runs. Daily-at-05:00 is `[5]`; twice a day is `[5, 15]`. There is
no `every: "24h"` field — expressing the same schedule two ways is how the two
drift apart.

**At most 4 entries per CV**, rejected by `lib/cvProfiles.ts` on write. Job ads
do not turn over hourly, so the cap costs nothing real, and it makes a runaway
config (`[0..23]` × 4 CVs) unreachable rather than merely unlikely.

`min_match` compares against `match_pct` — the deterministic skill-overlap
number from `match_evidence()`, set unconditionally in the `--json-out` path.
Deliberately **not** `fit`: `llm_rerank()` (`scout.py:527`) only runs when
`NVIDIA_API_KEY` is set, so a `fit`-based threshold sends nothing at all, and
sends it silently, on a keyless runner.

`hours_utc` is UTC, so `[5]` is 07:00 in Vienna in summer and 06:00 in winter.
Accepted: a one-hour seasonal drift on a pre-working-day scan is not worth a
timezone field and its DST edge cases.

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
| `results/<id>.json` | Latest ranked matches for that CV, **without `company_review`** | Dashboard match board |
| `sent/<id>.json` | Alert dedupe: `fingerprint -> {sent_date, title, company}` | Alert step |
| `runs/<id>.json` | Last-attempt timestamp + status (`ok`/`error`) + slot + counts | Due-check, status strip |

`sent/<id>.json` mirrors today's `data/sent_jobs.json` shape rather than being a
bare hash list: entries older than **90 days are dropped on write**, so a genuine
repost re-alerts and the file stays bounded on a branch nothing ever prunes. The
stored title and company are what makes "why did this not alert me" answerable —
a list of md5 hashes is not debuggable.

Per-CV `sent/` is required, not cosmetic: today's `data/sent_jobs.json` is a
single global map. Shared, an ad alerted for the DevOps CV would be silently
suppressed for the Backend CV, which is precisely the case the user cares about.

## Behaviour

### Due-check

The hourly cron wakes every hour, reads `profiles.json`, and for each `enabled`
CV computes its **due slot**: the newest entry in `hours_utc` at or before now.
The CV runs when that slot is less than 6 hours old and `runs/<id>.json` shows no
successful run for it.

Not exact-hour equality. GitHub delays scheduled workflows on public repos by
5–20+ minutes routinely and drops ticks under load; a 05:00 slot firing at 06:04
would fail an `hour in hours_utc` test and that day's scan would vanish with no
error anywhere. The window lets the next wake pick it up.

**Failure is recorded.** A crashed scan writes `runs/<id>.json` with
`status: "error"` and its slot, and that slot gets **one** retry on the next wake
before being abandoned until its next scheduled hour. Without a written failure
record the window sees "no successful run" and re-runs a hard failure every hour
for six hours; without any retry, one transient network blip costs a whole day.

Scans run sequentially. With company reviews out of the cron (below) a scan is
~9s of source fetching plus rerank, so four CVs is around a minute rather than
the previously measured ~17. `concurrency.group` stays, `cancel-in-progress:
false`.

### Quiet first run

When a CV has no `sent/<id>.json`, the first scan **records every match as sent
and pushes nothing**. Without this, day one is four CVs × up to 50 matches ≈ 200
Telegram messages. The dashboard still shows the full board immediately; only
the push is suppressed, and only once per CV.

### Company reviews are local, not scheduled

Company review enrichment is the entire runtime cost of a scan: ~9 seconds of
source fetching against minutes of sequential LLM calls, one per unseen company.

An earlier draft of this spec proposed "enrich only the published top-N" as the
fix. **That is already the shipped behaviour** — `scout.py:986` enriches
`output_jobs`, after the `--top` cut, and `--company-review-limit` (`scout.py:863`)
already caps lookups at 20 distinct companies per run. There was no order of
magnitude left to cut. The measured 4m18s run was already bounded.

The real cost driver is that `data/company_reviews/` is **gitignored**
(`.gitignore:96`), so the cache never reaches a runner: every wake pays 20 cold
LLM calls per CV, forever, and paid for them again the next hour. Warming that
cache in CI does not help either, because the reviews then have no way back to
the local dashboard once they are stripped from the published feed (below).

**Rule:** the cron does not pass `--company-reviews` at all. Enrichment runs
locally, on the machine where the disk cache lives and where the dashboard reads
it, warm across runs and shared between all four CVs. This removes the cold-cache
cost, the per-wake LLM bill and the need for any CI cache layer in one move.

Consequence: a match that only the cron has ever seen has no review panel until a
local scan or an on-render lookup fills it. That is the correct trade — the
panels are decoration on a board whose job is to rank ads.

### Credentials

Alert credentials (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and optionally
`NVIDIA_API_KEY`, `ADZUNA_*`, `JOOBLE_API_KEY`) are entered in the UI when
creating an alert, and written to **`.env.local`, which is gitignored**.

This is a hard boundary. The repository is public and the config-sync model
writes files the user then commits — a credential in any committed file is a
published credential. `lib/cvProfiles.ts` writes `scout/`; credentials go
through a separate writer that can only target `.env.local`, so no future edit
can route a token into `scout/`. A test asserts that a profile write containing
a token-shaped value fails rather than being written.

Local scans and local alerts work immediately from `.env.local`. For scheduled
runs, GitHub Actions cannot read it, so the UI displays the exact
`gh secret set <NAME>` commands to paste. The dashboard never stores a GitHub
token and never writes to the repository's secrets itself.

Current state: `gh secret list` is empty. Nothing scheduled will run, and no
alert will send, until those secrets are set on the repo.

### Alerting

For each scanned CV: take matches with `match_pct >= alert.min_match`, drop any
fingerprint already in `sent/<id>.json`, push the rest to Telegram as chunked
messages (chunking already exists), then append the fingerprints with today's
date. Failure to send must not lose the results — write `results/` before
attempting the push.

**`scripts/alerts.py` is the only sender.** `scout.py` already contains a
complete, different alerting path (`scout.py:1046-1078`): a global
`data/sent_jobs.json`, dedupe applied *before* ranking rather than thresholding
after it, its own `--top` cut and its own `generate_dashboard()`. That path is
unreachable from the cron — `--json-out` returns at `scout.py:1044`, before it —
and it stays exactly as it is for manual CLI use, documented as legacy. It is not
extended and it does not learn about per-CV state; two senders sharing a concept
of "already sent" is how the two stores drift into disagreeing.

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
only `./dashboard` (`docker-compose.yml:36`), so it reaches neither `scout/` nor
`data/company_reviews/`. In the container: the config editor renders read-only
with an explanatory notice, and no review panels render. This is a real
limitation of the chosen sync model, not a bug to fix later.

The container is also worse off than that today, and this is a bug. `lib/feed.ts`
resolves `REPO_ROOT` as `cwd/..`, which inside the container is `/`; the read of
`/data/scout/latest.json` ENOENTs, and that file treats ENOENT as the *innocuous*
"nobody has run the cron yet" empty state. So the containerised board silently
shows nothing, with no error, whatever the feed actually contains. Fix:
`docker-compose.yml` sets `SCOUT_FEED_URL` to the `scout-data` raw URL, so the
container reads the published feed over HTTP — the path `feed.ts` already
supports and prefers.

### Scan-now streaming

`scout.py` already writes progress via `log()` to **stderr** (line 112) while
`--json-out` writes results to a **file** — the two never collide. The API route
streams stderr lines to the browser as server-sent events, so the user sees
`karriere.at: 41 ads … Remotive: 12 … scoring` instead of a blank four-minute
spinner.

## Modules

### Module: `lib/cvProfiles.ts`
- **Responsibility:** Read, validate and write `scout/profiles.json`.
- **Interface:** In — profile objects. Out — typed profile list; write returns the changed paths. Throws on duplicate/invalid id, empty `hours_utc`, more than 4 `hours_utc` entries, `min_match` outside 0–100.
- **PII gate:** a profile write is stripped to exactly `{skills, role_titles, source}` and hard-fails on any other key, on an email/phone-shaped value, or on a token-shaped value. Risk 4 said "enforced by a header comment and review"; this makes it enforced by code, using the same mechanism the credentials boundary already commits to. Ten lines, and it turns "someone notices in a diff" into "it cannot be written".
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

### Module: `lib/credentials.ts`
- **Responsibility:** Read and write alert credentials to `.env.local` only.
- **Interface:** In — key/value pairs from the alert form. Out — merged `.env.local`; returns the `gh secret set` commands to mirror them to GitHub. Refuses any path outside `.env.local`.
- **Dependencies:** `node:fs`. Deliberately shares nothing with `lib/cvProfiles`, so no edit there can route a token into the committed `scout/` tree.
- **Size target:** ~100 lines.

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
- **Responsibility:** Threshold-filter a result set on `match_pct`, apply per-CV sent-state (including quiet first run and 90-day expiry), push Telegram. Sole owner of sending for scheduled runs.
- **Interface:** In — results JSON, CV id, `min_match`. Out — updated `sent/<id>.json`; sends messages.
- **Dependencies:** `scout.py`'s `send_telegram()` and `resolve_telegram()` only. Does not touch `load_sent`/`save_sent` or `data/sent_jobs.json`.
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
- Due-check: correct slot runs, disabled skips, already-succeeded-for-this-slot
  skips, a slot older than the 6h window skips, and — the case exact-hour
  matching got wrong — **a wake at 06:04 still runs the 05:00 slot**.
- Failure path: a crashed scan writes `status: "error"`, the next wake retries
  that slot exactly once, and the wake after that does not.
- Per-CV sent-state isolation: same ad alerts on two CVs independently.
- Sent entries older than 90 days are dropped, and the ad they referenced alerts
  again.
- Quiet first run pushes nothing and records everything.
- Threshold uses `match_pct`: with `NVIDIA_API_KEY` unset (so no `fit` on any
  job) a match above `min_match` **still alerts**. This is the regression test
  for the silent-no-alerts failure mode.
- The cron passes no `--company-reviews`, and nothing written to `scout-data`
  carries a `company_review` key even when the input result set has one.
- `lib/credentials.ts` refuses to write anywhere but `.env.local`; a profile
  write carrying a token-shaped, email-shaped or unknown key is rejected, not
  published.

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
3. ~~**Scan-time variance is unexplained**~~ **Measured and explained.** It is
   not the job sources: free APIs 2.4s, karriere.at 6.6s (307 ads → 247 jobs),
   Adzuna+Jooble 0.1s, all sources with `--no-llm` ~9s total. The same run with
   `--company-reviews` exceeded **10 minutes**. Company review enrichment makes
   one sequential LLM call per unseen company; the 29.7s run had a warm
   `data/company_reviews` cache, the 4m18s run did not. The earlier "bound it to
   top-N" mitigation was a no-op — that bound already shipped. Resolved instead
   by taking reviews out of the cron entirely, so the runner never pays it.
4. ~~**`scout/` is public**, enforced by comment and review~~ — now enforced by
   the key whitelist in `lib/cvProfiles.ts`. The residual risk is a *deliberate*
   future widening of that whitelist, which a header comment does still only warn
   about.
5. **Generated employer cons are already on a public branch.** Every `scout-data`
   commit to date carries `company_review` inside `latest.json`. Dropping it from
   future writes does not unpublish the existing history; those commits stay
   readable unless the branch is rewritten. Decide separately whether to force-
   push `scout-data` clean — out of scope here, flagged so it is not forgotten.
6. **`.claude/rules/ui-testing.md` gates on routes that do not exist.** It names
   `/`, `/dashboard` and `/dashboard/map`; this app serves `/`, `/jobs`, `/runs`,
   `/scout` and `/matches`. The final-gate check has therefore never verified the
   pages it was meant to. Not fixed here — it is a rules file, not this design —
   but the UI work in this spec is gated by it and should update it first.

## Out of scope

Deleting the crawler pages or schema. Deploying the dashboard. Per-CV LLM
tuning. Multi-user support. StepStone (still WAF-blocked) and jobhive (still
minutes-long parquet download) stay out of the default source set.
