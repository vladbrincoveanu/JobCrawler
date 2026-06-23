-- V001: initial schema (PG dialect)
-- Spec: 2026-06-23-pg-migration-design.md

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version     INTEGER PRIMARY KEY,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  description TEXT NOT NULL
);

CREATE TABLE sources (
  name               TEXT PRIMARY KEY,
  enabled            BOOLEAN NOT NULL DEFAULT TRUE,
  rate_limit_per_min INTEGER NOT NULL DEFAULT 30,
  last_crawled_at    TIMESTAMPTZ
);

CREATE TYPE run_status AS ENUM ('pending', 'running', 'success', 'partial', 'failed');

CREATE TABLE runs (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source     TEXT NOT NULL REFERENCES sources(name),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at   TIMESTAMPTZ,
  status     run_status NOT NULL DEFAULT 'pending',
  jobs_found INTEGER NOT NULL DEFAULT 0,
  jobs_new   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE jobs (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source        TEXT NOT NULL REFERENCES sources(name),
  source_id     TEXT NOT NULL,
  url           TEXT NOT NULL,
  title         TEXT NOT NULL,
  company       TEXT,
  location      TEXT,
  description   TEXT,
  embedding     vector(384),
  content_hash  TEXT NOT NULL UNIQUE,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  raw_payload   JSONB,
  UNIQUE (source, source_id)
);

CREATE TABLE run_errors (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id      BIGINT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  stage       TEXT NOT NULL,
  message     TEXT NOT NULL,
  context     JSONB
);

CREATE INDEX idx_jobs_source      ON jobs (source);
CREATE INDEX idx_jobs_last_seen   ON jobs (last_seen_at DESC);
CREATE INDEX idx_runs_source_time ON runs (source, started_at DESC);
CREATE INDEX idx_run_errors_run   ON run_errors (run_id);
