/**
 * Express server — serves the built Vite UI and JSON API for the crawl data.
 *
 * API:
 *   GET  /api/stats                              → counts + last run
 *   GET  /api/jobs?location=&source=             → jobs (with enrichment joined), most recent first
 *   GET  /api/locations                          → distinct (location, count) pairs
 *   GET  /api/jobs/:id                           → single job with description
 *   POST /api/jobs/enrich-batch                  → { ids: number[] } → run LLM enrichment
 *
 * Reads DATABASE_URL from env (defaults to local docker-compose PG).
 * Uses NVIDIA_API_KEY for LLM salary estimation (optional; absent → salary null).
 */
import express from "express";
import { Client } from "pg";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  extractKeywords,
  estimateSalary,
  getCachedEnrichment,
  upsertEnrichment,
  type EnrichmentRow,
} from "./server/enrichment.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PORT = Number(process.env.PORT ?? 3012);
const DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://jobcrawler:dev@localhost:5433/jobcrawler";

const app = express();
app.use(express.json({ limit: "256kb" }));

const db = new Client({ connectionString: DATABASE_URL });
await db.connect();

// Idempotent schema setup. V002 migration ships the canonical DDL; we apply
// the create-table here so the UI can boot against an existing DB without
// needing the full migration runner.
await db.query(`
  CREATE TABLE IF NOT EXISTS job_enrichments (
    content_hash    TEXT PRIMARY KEY
                     REFERENCES jobs(content_hash) ON DELETE CASCADE,
    salary_min      INTEGER,
    salary_max      INTEGER,
    salary_currency TEXT,
    salary_reason   TEXT,
    keywords        TEXT[] NOT NULL DEFAULT '{}',
    reviews_note    TEXT NOT NULL DEFAULT 'No review source wired yet (AMS listings only).',
    enriched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    enrichment_model TEXT
  );
  CREATE INDEX IF NOT EXISTS idx_job_enrichments_enriched_at
    ON job_enrichments (enriched_at DESC);
`);

app.get("/api/stats", async (_req, res) => {
  try {
    const r = await db.query(`
      SELECT
        (SELECT COUNT(*)::int FROM jobs)              AS jobs_total,
        (SELECT COUNT(*)::int FROM runs)              AS runs_total,
        (SELECT COUNT(*)::int FROM runs WHERE status = 'success') AS runs_success,
        (SELECT COUNT(*)::int FROM runs WHERE status IN ('failed','partial')) AS runs_failed,
        (SELECT COUNT(*)::int FROM run_errors)       AS errors_total,
        (SELECT json_build_object('source', source, 'status', status, 'started_at', started_at)
           FROM runs ORDER BY started_at DESC LIMIT 1) AS last_run
    `);
    const row = r.rows[0];
    res.json({
      jobsTotal: row.jobs_total,
      runsTotal: row.runs_total,
      runsSuccess: row.runs_success,
      runsFailed: row.runs_failed,
      errorsTotal: row.errors_total,
      lastRun: row.last_run,
    });
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

app.get("/api/jobs", async (req, res) => {
  const location = (req.query.location as string | undefined)?.trim();
  const source = (req.query.source as string | undefined)?.trim();
  const params: unknown[] = [];
  const where: string[] = [];
  if (location) {
    params.push(`%${location}%`);
    where.push(`j.location ILIKE $${params.length}`);
  }
  if (source) {
    params.push(source);
    where.push(`j.source = $${params.length}`);
  }
  const whereSql = where.length ? `WHERE ${where.join(" AND ")}` : "";
  try {
    const r = await db.query(
      `
      SELECT j.id, j.source, j.title, j.company, j.location, j.url,
             j.last_seen_at, j.content_hash,
             e.salary_min, e.salary_max, e.salary_currency, e.salary_reason,
             e.keywords, e.reviews_note, e.enriched_at
        FROM jobs j
        LEFT JOIN job_enrichments e ON e.content_hash = j.content_hash
        ${whereSql}
       ORDER BY j.last_seen_at DESC
       LIMIT 500
      `,
      params,
    );
    res.json(r.rows);
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

app.get("/api/locations", async (_req, res) => {
  try {
    const r = await db.query<{ location: string; n: number }>(`
      SELECT COALESCE(location, '(unknown)') AS location, COUNT(*)::int AS n
        FROM jobs
       GROUP BY location
       ORDER BY n DESC
       LIMIT 50
    `);
    res.json(r.rows);
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

app.get("/api/jobs/:id", async (req, res) => {
  const id = Number(req.params.id);
  if (!Number.isInteger(id) || id <= 0) {
    res.status(400).json({ error: "bad id" });
    return;
  }
  try {
    const r = await db.query(`SELECT * FROM jobs WHERE id = $1`, [id]);
    if (!r.rows.length) {
      res.status(404).json({ error: "not found" });
      return;
    }
    res.json(r.rows[0]);
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

/** Run keyword + LLM-salary enrichment for the requested job ids.
 *  Idempotent — already-enriched jobs are skipped unless `force=true`. */
app.post("/api/jobs/enrich-batch", async (req, res) => {
  const ids = Array.isArray(req.body?.ids) ? req.body.ids : [];
  const force = req.body?.force === true;
  if (!ids.length || !ids.every((n: unknown) => Number.isInteger(n))) {
    res.status(400).json({ error: "ids: number[] required" });
    return;
  }
  const results: { id: number; status: "ok" | "skipped" | "failed"; reason?: string }[] = [];
  try {
    const jobs = await db.query<{
      id: number;
      content_hash: string;
      title: string;
      company: string | null;
      location: string | null;
      description: string | null;
    }>(
      `SELECT id, content_hash, title, company, location, description
         FROM jobs WHERE id = ANY($1::bigint[])`,
      [ids],
    );
    for (const job of jobs.rows) {
      if (!force) {
        const cached = await getCachedEnrichment(db, job.content_hash);
        if (cached) {
          results.push({ id: job.id, status: "skipped" });
          continue;
        }
      }
      try {
        const keywords = extractKeywords(job.title, job.description);
        const salary = await estimateSalary({
          title: job.title,
          company: job.company,
          location: job.location,
          description: job.description,
        });
        await upsertEnrichment(db, job.content_hash, {
          salary_min: salary.min,
          salary_max: salary.max,
          salary_currency: salary.currency,
          salary_reason: salary.reason,
          keywords,
          model: process.env.NVIDIA_SALARY_MODEL ?? "meta/llama-3.1-8b-instruct",
        });
        results.push({ id: job.id, status: "ok" });
      } catch (e) {
        results.push({
          id: job.id,
          status: "failed",
          reason: (e as Error).message,
        });
      }
    }
    res.json({ processed: jobs.rows.length, results });
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

/** Single-job enrichment lookup. Returns 404 if not yet enriched. */
app.get("/api/jobs/:id/enrichment", async (req, res) => {
  const id = Number(req.params.id);
  if (!Number.isInteger(id) || id <= 0) {
    res.status(400).json({ error: "bad id" });
    return;
  }
  try {
    const r = await db.query<EnrichmentRow & { job_id: number }>(
      `SELECT j.id AS job_id, e.content_hash, e.salary_min, e.salary_max,
              e.salary_currency, e.salary_reason, e.keywords, e.reviews_note,
              e.enriched_at, e.enrichment_model
         FROM jobs j
         LEFT JOIN job_enrichments e ON e.content_hash = j.content_hash
        WHERE j.id = $1`,
      [id],
    );
    if (!r.rows.length) {
      res.status(404).json({ error: "job not found" });
      return;
    }
    const row = r.rows[0];
    if (!row.content_hash) {
      res.json({ job_id: id, enriched: false });
      return;
    }
    res.json({ enriched: true, ...row });
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

// Serve Vite build output (Vite writes to ./dist relative to project root)
// After tsc compile, this file lives in ./dist-server/, so go up one level.
const distDir = path.resolve(__dirname, "..", "dist");
app.use(express.static(distDir));
// Express 5: use middleware instead of "*" route
app.use((_req, res) => res.sendFile(path.join(distDir, "index.html")));

app.listen(PORT, () => {
  console.log(`JobCrawler UI: http://localhost:${PORT}`);
  console.log(`  using DATABASE_URL: ${DATABASE_URL}`);
  console.log(
    `  LLM salary: ${process.env.NVIDIA_API_KEY ? "enabled" : "disabled (set NVIDIA_API_KEY)"}`,
  );
});
