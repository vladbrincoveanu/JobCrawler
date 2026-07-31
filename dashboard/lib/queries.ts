import { getPool } from "./db";

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
  content_hash: string;
  first_seen_at: string;
  last_seen_at: string;
}

export interface RunRow {
  id: number;
  source: string;
  started_at: string;
  ended_at: string | null;
  status: "pending" | "running" | "success" | "partial" | "failed";
  jobs_found: number;
  jobs_new: number;
}

export interface ErrorRow {
  id: number;
  run_id: number;
  occurred_at: string;
  stage: string;
  message: string;
}

export interface Stats {
  jobsTotal: number;
  runsSuccess: number;
  runsFailed: number;
  errorsTotal: number;
  bySource: Record<string, number>;
  lastRun: RunRow | null;
}

// --- Queries (async — pg.Pool is async) ---

export async function getStats(): Promise<Stats> {
  const pool = getPool();
  const [jobsRes, successRes, failedRes, errorsRes, bySourceRes, lastRunRes] =
    await Promise.all([
      pool.query<{ n: string }>("SELECT COUNT(*)::int AS n FROM jobs"),
      pool.query<{ n: string }>(
        "SELECT COUNT(*)::int AS n FROM runs WHERE status = 'success'"
      ),
      pool.query<{ n: string }>(
        "SELECT COUNT(*)::int AS n FROM runs WHERE status IN ('failed', 'partial')"
      ),
      pool.query<{ n: string }>("SELECT COUNT(*)::int AS n FROM run_errors"),
      pool.query<{ source: string; n: string }>(
        "SELECT source, COUNT(*)::int AS n FROM jobs GROUP BY source"
      ),
      pool.query<RunRow>(
        // id DESC breaks ties on started_at. Without it two runs that begin
        // inside the same clock tick -- which the seeder does, and which two
        // sources crawled back-to-back do in production -- order arbitrarily,
        // so the "Last run" card could show the earlier of the two.
        "SELECT * FROM runs ORDER BY started_at DESC, id DESC LIMIT 1"
      ),
    ]);
  return {
    jobsTotal: Number(jobsRes.rows[0]?.n ?? 0),
    runsSuccess: Number(successRes.rows[0]?.n ?? 0),
    runsFailed: Number(failedRes.rows[0]?.n ?? 0),
    errorsTotal: Number(errorsRes.rows[0]?.n ?? 0),
    bySource: Object.fromEntries(
      bySourceRes.rows.map((r) => [r.source, Number(r.n)])
    ),
    lastRun: lastRunRes.rows[0] ?? null,
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

export async function listJobs(
  opts: ListJobsOptions = {}
): Promise<ListJobsResult> {
  const pool = getPool();
  const limit = Math.min(opts.limit ?? 100, 500);
  const offset = opts.offset ?? 0;
  const params: (string | number)[] = [];
  const where: string[] = [];

  if (opts.source) {
    where.push(`source = $${params.length + 1}`);
    params.push(opts.source);
  }
  if (opts.search) {
    where.push(
      `(title ILIKE $${params.length + 1} OR company ILIKE $${params.length + 2})`
    );
    const q = `%${opts.search}%`;
    params.push(q, q);
  }

  const whereClause = where.length ? `WHERE ${where.join(" AND ")}` : "";

  const jobsRes = await pool.query<JobRow>(
    `SELECT id, source, source_id, url, title, company, location, description, ` +
      `content_hash, first_seen_at, last_seen_at ` +
      `FROM jobs ${whereClause} ` +
      `ORDER BY last_seen_at DESC LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
    [...params, limit, offset]
  );

  const totalRes = await pool.query<{ n: string }>(
    `SELECT COUNT(*)::int AS n FROM jobs ${whereClause}`,
    params
  );

  return { jobs: jobsRes.rows, total: Number(totalRes.rows[0]?.n ?? 0) };
}

export async function listSources(): Promise<string[]> {
  const pool = getPool();
  const res = await pool.query<{ source: string }>(
    "SELECT DISTINCT source FROM jobs ORDER BY source"
  );
  return res.rows.map((r) => r.source);
}

export async function listRuns(limit = 50): Promise<RunRow[]> {
  const pool = getPool();
  const res = await pool.query<RunRow>(
    // Same tie-break as getStats(): equal timestamps must not shuffle the list.
    "SELECT * FROM runs ORDER BY started_at DESC, id DESC LIMIT $1",
    [limit]
  );
  return res.rows;
}

export async function listErrors(limit = 50): Promise<ErrorRow[]> {
  const pool = getPool();
  const res = await pool.query<ErrorRow>(
    "SELECT id, run_id, occurred_at, stage, message FROM run_errors " +
      "ORDER BY occurred_at DESC LIMIT $1",
    [limit]
  );
  return res.rows;
}

export async function listErrorsForRun(runId: number): Promise<ErrorRow[]> {
  const pool = getPool();
  const res = await pool.query<ErrorRow>(
    "SELECT id, run_id, occurred_at, stage, message FROM run_errors " +
      "WHERE run_id = $1 ORDER BY occurred_at ASC",
    [runId]
  );
  return res.rows;
}
