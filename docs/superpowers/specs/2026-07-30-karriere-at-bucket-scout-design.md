---
title: karriere.at source + CV-bucket matching for the job scout
date: 2026-07-30
status: approved
ui_scope: false
graph_scope: false
test_scope: true
---

# karriere.at source + CV-bucket matching

## Problem

`scripts/scout.py` scouts jobs against a single CV profile using jobhive's ATS
parquet slices plus three free remote-job APIs. Two gaps:

1. **No Austrian-local boards.** Every current source is an international ATS
   aggregator. Vienna-local roles posted only to Austrian portals never enter
   the pool — which is most of the `.net Wien` market.
2. **One CV, one score.** `~/Desktop/Startup/career/Resume/` ships **four** CV
   variants aimed at different buckets. The scout can't say *which CV to send*,
   which is the actual decision the user makes per job.

## Source selection (decided)

The trigger was `https://www.metajob.at/.net-wien`. Probing both candidates:

| | metajob.at | karriere.at |
|---|---|---|
| robots.txt | pages allowed, but `/dres/jc` (apply click-through) is `Disallow:` for `User-agent: *` | `Disallow:` blank — fully open |
| Rendering | client-side Mantine/React; zero jobs in static HTML | server-rendered, `m-jobsListItem__*` BEM markup |
| Role | meta-aggregator (sources include karriere.at, StepStone) | primary board, largest in AT |

**Decision: karriere.at only.** metajob would need a headless browser to see any
result and a robots-disallowed endpoint to resolve any apply link, in exchange
for data that largely originates on boards we can read directly.

`CAREER-BUCKETS.md` independently ranks **devjobs.at** as highest-signal for all
three buckets. It is out of scope here and recorded as follow-up work.

## Pagination finding (constrains the design)

karriere.at's SSR HTML returns **16 jobs and no pagination**. Verified inert:
`?page=`, `?seite=`, `?p=`, `?pageIndex=`, `?currentPage=`, `?start=`, `?offset=`
(byte-identical result sets); path forms `/jobs/<q>/seite-2` and `/jobs/<q>/2`
return 404. Deeper results load from an internal API reachable only through
minified JS bundles.

**Consequence — breadth by query diversity, not by depth.** Instead of paging one
broad query, issue many narrow queries and union them. Search terms come from the
bucket definitions (~8 per bucket) crossed with locations, each yielding up to 16
high-relevance rows. This keeps the source on plain `requests`, needs no browser,
and stays robots-clean. Verified distinct result sets per slug: `/jobs/.net`,
`/jobs/java`, `/jobs/kubernetes`, `/jobs/.net/wien` all differ.

Query slug is the canonical form (`/jobs/<slug>` and `/jobs/<slug>/<location>`);
`?keywords=` is equivalent but the slug is what the site's own links use.

## Locations (decided)

**Wien + Austria-wide remote.** Two location arms per query term: the `wien`
location slug, and an unlocated arm filtered down to remote/homeoffice ads by the
existing `reachable_from_home()` logic in `scout.py`.

## Bucket matching

`career/Resume/JOB-SEARCH/` already holds a bucket system: `CAREER-BUCKETS.md`
(three buckets A/B/C), `kwcheck.sh` (top-5 + next-5 keywords per CV variant,
hardcoded in a bash array), `kwcount.py`, and `keywords/devops-sre.txt` (the one
keyword file that exists, in a documented `keyword|synonym|synonym` format where
the first five lines are the top five).

**Single source of truth: the `keywords/*.txt` files.** The three missing files are
transcribed from `kwcheck.sh`'s `variants` array into the existing format — this
is step 6 of the coaching method, already listed as pending in `CAREER-BUCKETS.md`,
and `kwcount.py`'s own docstring already documents the
`./kwcount.py backend keywords/backend-streaming.txt` path convention. Nothing is
invented: rankings are transcribed, with provenance noted in each file header.

JobCrawler owns *how to search*; `career/` owns *what the CV claims*.

## Modules

### Module: `scripts/sources/karriere_at.py`
- **Responsibility:** turn search terms + locations into karriere.at job dicts
- **Interface:** `fetch(terms: list[str], locations: list[str], days: int, detail: bool) -> list[dict]` — emits the exact key set `fetch_free_apis()` emits (`url, title, company, ats_type, location, is_remote, country_iso, salary_*, employment_type, description, posted, apply_url`), with `ats_type="karriere_at"`
- **Dependencies:** `requests`, `re` (no new dependencies; matches the codebase's regex-parsing convention)
- **Size target:** ~180 lines
- **Behavior:** one GET per (term, location); regex-parse `m-jobsListItem__*` cards for title/href/company/location/date; optional detail GET per new job for description + salary; ~1 req/s; any single request failing is logged and skipped, never aborts the run (mirrors `_api_get`)

### Module: `scripts/buckets.py`
- **Responsibility:** load bucket definitions + keyword sets, score a job against each bucket, name the best-fit CV variant
- **Interface:** `load_buckets(config_path, keywords_dir) -> list[Bucket]`; `best_bucket(job, buckets) -> tuple[Bucket, float]`
- **Dependencies:** `data/buckets.json` (search terms, CV filenames, keyword-file names), `career/Resume/JOB-SEARCH/keywords/*.txt` (keyword sets)
- **Size target:** ~140 lines
- **Scoring:** top-5 keyword hit in title = 6 pts, in description = 2; next-5 = 3 / 1; synonyms count as their parent keyword; normalized to 0–100 by the bucket's maximum attainable score so buckets with different keyword counts stay comparable

### Wiring: `scripts/scout.py`
- `--sources jobhive,apis,karriere` (default all) to run boards independently
- `--buckets A,B,C,D` to restrict which CV variants drive search terms and scoring
- karriere rows join the **existing** pipeline unchanged: `reachable_from_home` → `dedupe` (fingerprint is company+normalized title, so a karriere repost of a Greenhouse job collapses into one entry) → salary filter → `score_job` → LLM rerank → Telegram → dashboard
- Each job carries `bucket` + `bucket_fit`; the Telegram line and dashboard column show which CV to send

## Testing (`test_scope: true`)

- `tests/test_karriere_at.py` parses a **saved HTML fixture** committed under `tests/fixtures/` — asserts exact title/company/location/url/date for known cards. A site redesign then fails as a detectable, specific test failure rather than silently returning zero jobs.
- `tests/test_buckets.py` — a job description dense in Kubernetes/Terraform must select bucket C over bucket B; keyword-file parsing must handle comments, synonyms, and top-5 ordering.
- Guard test: parser returning **zero** cards from a non-empty fixture is a failure, not a pass. This is the failure mode that would otherwise degrade silently in production.
- Live smoke: one real run asserting ≥1 job parsed with non-empty title, company, and URL.

## Out of scope

- devjobs.at (recorded as the highest-value follow-up)
- metajob.at via Playwright
- Writing back to `applications.csv`
