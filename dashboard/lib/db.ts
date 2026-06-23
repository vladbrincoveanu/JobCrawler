import Database from "better-sqlite3";
import path from "node:path";

/**
 * Read-only SQLite connection to the JobCrawler DB.
 *
 * Path resolution:
 *   1. JOB_CRAWLER_DB env var (relative to dashboard/cwd, or absolute)
 *   2. Default: ../data/jobs.db (project root data dir, since npm run dev
 *      is invoked from dashboard/)
 *
 * Opened with `{ readonly: true }` so the dashboard cannot mutate jobs/runs
 * even by accident. The Python crawler writes via its own connection (WAL is
 * enabled, so concurrent readers are safe).
 */
let _db: Database.Database | null = null;

function resolveDbPath(): string {
  const raw = process.env.JOB_CRAWLER_DB ?? "../data/jobs.db";
  return path.resolve(process.cwd(), raw);
}

export function getDb(): Database.Database {
  if (_db) return _db;
  const dbPath = resolveDbPath();
  _db = new Database(dbPath, { readonly: true, fileMustExist: true });
  _db.pragma("journal_mode = WAL");
  return _db;
}

/** For tests: reset the cached connection so a different path can be used. */
export function resetDb(): void {
  if (_db) {
    _db.close();
    _db = null;
  }
}
