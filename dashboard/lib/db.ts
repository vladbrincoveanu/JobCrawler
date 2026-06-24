import { Pool } from "pg";

/**
 * PostgreSQL connection pool for the dashboard.
 *
 * Path resolution:
 *   1. DATABASE_URL env var
 *   2. Default: postgresql://jobcrawler:dev@localhost:5433/jobcrawler
 *      (host port 5433 because host 5432 is occupied by knowledgeforge-postgres on this dev box)
 *
 * Async (vs previous sync better-sqlite3). RSC supports async natively.
 */
let _pool: Pool | null = null;

function resolveDatabaseUrl(): string {
  return (
    process.env.DATABASE_URL ??
    "postgresql://jobcrawler:dev@localhost:5433/jobcrawler"
  );
}

export function getPool(): Pool {
  if (_pool) return _pool;
  _pool = new Pool({
    connectionString: resolveDatabaseUrl(),
    min: 2,
    max: 10,
    idleTimeoutMillis: 30_000,
    connectionTimeoutMillis: 5_000,
  });
  return _pool;
}

/** For tests: reset cached pool so a different connection can be used. */
export async function resetPool(): Promise<void> {
  if (_pool) {
    await _pool.end();
    _pool = null;
  }
}
