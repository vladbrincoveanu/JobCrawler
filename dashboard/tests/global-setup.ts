import { execFileSync } from "node:child_process";
import { Client } from "pg";
import path from "node:path";

/**
 * Global setup: create clean PG test DB, run migrations, seed.
 *
 * Uses DATABASE_URL or defaults to local docker-compose PG on port 5433
 * (5432 is occupied by knowledgeforge-postgres on this dev box).
 */
const DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://jobcrawler:dev@localhost:5433/jobcrawler_test";

const PROJECT_ROOT = path.resolve(__dirname, "../..");
const SEED_SCRIPT = path.join(PROJECT_ROOT, "scripts/seed_demo_data.py");

export default async function globalSetup() {
  // Drop + recreate test DB for isolation
  const adminUrl = DATABASE_URL.replace(/\/[^/]+$/, "/postgres");
  const admin = new Client({ connectionString: adminUrl });
  await admin.connect();
  try {
    await admin.query(
      `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'jobcrawler_test'`
    );
    await admin.query(`DROP DATABASE IF EXISTS jobcrawler_test`);
    await admin.query(`CREATE DATABASE jobcrawler_test`);
  } finally {
    await admin.end();
  }

  // Run migrations
  execFileSync(
    "python",
    [
      "-c",
      "from pathlib import Path; from crawler.storage.db import connect; from crawler.storage.migrations.runner import migrate; migrate(connect(), Path('crawler/storage/migrations'))",
    ],
    {
      cwd: PROJECT_ROOT,
      env: { ...process.env, DATABASE_URL, PYTHONPATH: PROJECT_ROOT },
      stdio: "inherit",
    }
  );

  // Seed demo data
  execFileSync(
    "python",
    [SEED_SCRIPT, "--force", "--database-url", DATABASE_URL],
    {
      cwd: PROJECT_ROOT,
      env: { ...process.env, DATABASE_URL, PYTHONPATH: PROJECT_ROOT },
      stdio: "inherit",
    }
  );
}
