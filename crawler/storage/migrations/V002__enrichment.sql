-- V002: job enrichment cache
-- Caches LLM-derived signals (estimated salary, extracted skills) and a
-- placeholder for review data. Keyed by content_hash so it survives
-- source_id churn (jobs are deduped by content_hash in upsert_job).

CREATE TABLE IF NOT EXISTS job_enrichments (
  content_hash    TEXT PRIMARY KEY
                   REFERENCES jobs(content_hash) ON DELETE CASCADE,
  -- LLM-estimated annual gross salary range, EUR.
  salary_min      INTEGER,
  salary_max      INTEGER,
  salary_currency TEXT,
  salary_reason   TEXT,
  -- Skills/keywords extracted from title + description.
  keywords        TEXT[] NOT NULL DEFAULT '{}',
  -- Placeholder for employee-review data; populated when a review source is wired.
  reviews_note    TEXT NOT NULL DEFAULT 'No review source wired yet (AMS listings only).',
  enriched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  enrichment_model TEXT
);

CREATE INDEX IF NOT EXISTS idx_job_enrichments_enriched_at
  ON job_enrichments (enriched_at DESC);
