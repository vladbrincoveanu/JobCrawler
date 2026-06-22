-- V001: initial schema
-- Spec: § Storage Schema + grill-me amendment 4 (raw_html column for AMS)

CREATE TABLE schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL,
  description TEXT NOT NULL
);

CREATE TABLE sources (
  name TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL DEFAULT 1,
  rate_limit_per_min INTEGER NOT NULL DEFAULT 30,
  last_crawled_at TEXT
);

CREATE TABLE jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  source_id TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT NOT NULL,
  company TEXT,
  location TEXT,
  description TEXT,
  salary TEXT,
  employment_type TEXT,
  posted_at TEXT,
  content_hash TEXT NOT NULL,
  raw_html TEXT,  -- AMS: store rendered HTML for re-parse on schema change
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  UNIQUE(source, source_id)
);
CREATE INDEX idx_jobs_hash ON jobs(content_hash);
CREATE INDEX idx_jobs_posted ON jobs(posted_at DESC);
CREATE INDEX idx_jobs_company ON jobs(company);
CREATE INDEX idx_jobs_active_posted ON jobs(is_active, posted_at DESC);

CREATE TABLE crawl_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,  -- running|success|partial|failed|dry_run
  jobs_found INTEGER DEFAULT 0,
  jobs_inserted INTEGER DEFAULT 0,
  jobs_updated INTEGER DEFAULT 0,
  errors_count INTEGER DEFAULT 0
);
CREATE INDEX idx_runs_source ON crawl_runs(source);
CREATE INDEX idx_runs_started ON crawl_runs(started_at DESC);

CREATE TABLE crawl_errors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES crawl_runs(id),
  source TEXT NOT NULL,
  url TEXT,
  error_type TEXT NOT NULL,
  error_message TEXT,
  occurred_at TEXT NOT NULL
);
CREATE INDEX idx_errors_run ON crawl_errors(run_id);
