import { getDb } from "./db";

// --- Row types (mirror V001__initial.sql) ---

export interface JobRow {
  id: number;
  source: string;
  source_id: string;
  url: string;
  title: string;
  company: string | null;
  location: string | null;
  description: string | null;
  salary: string | null;
  employment_type: string | null;
  posted_at: string | null;
  content_hash: string;
  raw_html: string | null;
  first_seen_at: string;
  last_seen_at: string;
  is_active: number;
}

export interface RunRow {
  id: number;
  source: string;
  started_at: string;
  finished_at: string | null;
  status: "running" | "success" | "partial" | "failed" | "dry_run";
  jobs_found: number | null;
  jobs_inserted: number | null;
  jobs_updated: number | null;
  errors_count: number | null;
}

export interface ErrorRow {
  id: number;
  run_id: number;
  source: string;
  url: string | null;
  error_type: string;
  error_message: string | null;
  occurred_at: string;
}

export interface Stats {
  totalJobs: number;
  activeJobs: number;
  totalRuns: number;
  lastRun: RunRow | null;
  last24hErrors: number;
}

// --- Queries ---

const JOB_COLUMNS =
  "id, source, source_id, url, title, company, location, description, salary, " +
  "employment_type, posted_at, content_hash, raw_html, first_seen_at, last_seen_at, is_active";

const RUN_COLUMNS =
  "id, source, started_at, finished_at, status, jobs_found, jobs_inserted, " +
  "jobs_updated, errors_count";

export function getStats(): Stats {
  const db = getDb();
  const totalJobs =
    (db.prepare("SELECT COUNT(*) AS n FROM jobs").get() as { n: number }).n ?? 0;
  const activeJobs =
    (db
      .prepare("SELECT COUNT(*) AS n FROM jobs WHERE is_active = 1")
      .get() as { n: number }).n ?? 0;
  const totalRuns =
    (db.prepare("SELECT COUNT(*) AS n FROM crawl_runs").get() as {
      n: number;
    }).n ?? 0;
  const lastRun = db
    .prepare(
      `SELECT ${RUN_COLUMNS} FROM crawl_runs ORDER BY id DESC LIMIT 1`
    )
    .get() as RunRow | undefined;

  // Errors in the last 24 hours
  const cutoff = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  const last24hErrors =
    (db
      .prepare("SELECT COUNT(*) AS n FROM crawl_errors WHERE occurred_at >= ?")
      .get(cutoff) as { n: number }).n ?? 0;

  return {
    totalJobs,
    activeJobs,
    totalRuns,
    lastRun: lastRun ?? null,
    last24hErrors,
  };
}

export interface ListJobsOptions {
  limit?: number;
  offset?: number;
  source?: string;
  search?: string;
}

export interface ListJobsResult {
  jobs: JobRow[];
  total: number;
}

export function listJobs(opts: ListJobsOptions = {}): ListJobsResult {
  const db = getDb();
  const limit = Math.min(opts.limit ?? 100, 500);
  const offset = opts.offset ?? 0;
  const params: (string | number)[] = [];
  const where: string[] = [];

  if (opts.source) {
    where.push("source = ?");
    params.push(opts.source);
  }
  if (opts.search) {
    where.push("(title LIKE ? OR company LIKE ?)");
    const q = `%${opts.search}%`;
    params.push(q, q);
  }

  const whereClause = where.length ? `WHERE ${where.join(" AND ")}` : "";

  const jobs = db
    .prepare(
      `SELECT ${JOB_COLUMNS} FROM jobs ${whereClause} ` +
        `ORDER BY last_seen_at DESC LIMIT ? OFFSET ?`
    )
    .all(...params, limit, offset) as JobRow[];

  const total =
    (db
      .prepare(`SELECT COUNT(*) AS n FROM jobs ${whereClause}`)
      .get(...params) as { n: number }).n ?? 0;

  return { jobs, total };
}

export function listSources(): string[] {
  const db = getDb();
  const rows = db
    .prepare("SELECT DISTINCT source FROM jobs ORDER BY source")
    .all() as { source: string }[];
  return rows.map((r) => r.source);
}

export function listRuns(limit = 50): RunRow[] {
  const db = getDb();
  return db
    .prepare(
      `SELECT ${RUN_COLUMNS} FROM crawl_runs ORDER BY id DESC LIMIT ?`
    )
    .all(limit) as RunRow[];
}

export function listErrors(limit = 50): ErrorRow[] {
  const db = getDb();
  return db
    .prepare(
      "SELECT id, run_id, source, url, error_type, error_message, occurred_at " +
        "FROM crawl_errors ORDER BY id DESC LIMIT ?"
    )
    .all(limit) as ErrorRow[];
}

export function listErrorsForRun(runId: number): ErrorRow[] {
  const db = getDb();
  return db
    .prepare(
      "SELECT id, run_id, source, url, error_type, error_message, occurred_at " +
        "FROM crawl_errors WHERE run_id = ? ORDER BY id ASC"
    )
    .all(runId) as ErrorRow[];
}
