/**
 * Express server — serves the built Vite UI and JSON API for the crawl data.
 *
 * API:
 *   GET /api/stats  → counts + last run
 *   GET /api/jobs   → all jobs, most recent first
 *   GET /api/runs   → all runs, most recent first
 *
 * Reads DATABASE_URL from env (defaults to local docker-compose PG).
 */
import express from "express";
import { Client } from "pg";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PORT = Number(process.env.PORT ?? 3012);
const DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://jobcrawler:dev@localhost:5433/jobcrawler";

const app = express();

// Single PG client reused across requests (jobcrawler is single-user; fine).
const db = new Client({ connectionString: DATABASE_URL });
await db.connect();

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

app.get("/api/jobs", async (_req, res) => {
  try {
    const r = await db.query(`
      SELECT id, source, title, company, location, url, last_seen_at
        FROM jobs
        ORDER BY last_seen_at DESC
        LIMIT 500
    `);
    res.json(r.rows);
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

app.get("/api/runs", async (_req, res) => {
  try {
    const r = await db.query(`
      SELECT id, source, status, jobs_found, jobs_new, started_at
        FROM runs
        ORDER BY started_at DESC
        LIMIT 100
    `);
    res.json(r.rows);
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
});
