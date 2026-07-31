import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { Client } from "pg";
import {
  clearDatabaseUnavailable,
  recordDatabaseUnavailable,
} from "./db-availability";
import path from "node:path";

/**
 * Global setup: create a clean PG test DB, run migrations, seed demo data.
 *
 * Uses DATABASE_URL or defaults to local docker-compose PG on port 5433
 * (5432 is occupied by knowledgeforge-postgres on this dev box).
 *
 * Postgres is REQUIRED by the dashboard specs (they assert on seeded rows) and
 * IRRELEVANT to the scout specs (the CV upload flow never touches the database
 * -- it shells out to scripts/scout.py, which reads live job sources). This
 * setup used to throw when PG was unreachable, which failed the entire run and
 * took the DB-free scout specs down with it. Now an unreachable PG is recorded
 * in a marker file and the DB-dependent specs skip themselves with a visible
 * reason, so "Postgres is not running" reads as skipped-and-why rather than as
 * a wall of failures -- or, worse, as a suite nobody can run at all.
 */
const DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://jobcrawler:dev@localhost:5433/jobcrawler_test";

const PROJECT_ROOT = path.resolve(__dirname, "../..");
const SEED_SCRIPT = path.join(PROJECT_ROOT, "scripts/seed_demo_data.py");

/**
 * The repo venv, if present. A bare `python` is frequently absent on macOS
 * (only `python3` exists) and, when it does exist, is rarely the interpreter
 * holding this project's psycopg -- so the previous hard-coded "python" failed
 * on a correctly set-up machine.
 */
function pythonBin(): string {
  const venv = path.join(PROJECT_ROOT, ".venv", "bin", "python");
  return existsSync(venv) ? venv : "python3";
}

export default async function globalSetup() {
  clearDatabaseUnavailable();

  const adminUrl = DATABASE_URL.replace(/\/[^/]+$/, "/postgres");
  const admin = new Client({
    connectionString: adminUrl,
    connectionTimeoutMillis: 4000,
  });

  try {
    await admin.connect();
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    recordDatabaseUnavailable(message);
    console.warn(
      `\n[global-setup] PostgreSQL unreachable at ${adminUrl}: ${message}\n` +
        `[global-setup] Dashboard specs will SKIP. Start it with:  docker compose up -d postgres\n`,
    );
    return;
  }

  try {
    await admin.query(
      `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'jobcrawler_test'`,
    );
    await admin.query(`DROP DATABASE IF EXISTS jobcrawler_test`);
    await admin.query(`CREATE DATABASE jobcrawler_test`);
  } finally {
    await admin.end();
  }

  const env = { ...process.env, DATABASE_URL, PYTHONPATH: PROJECT_ROOT };

  execFileSync(
    pythonBin(),
    [
      "-c",
      "from pathlib import Path; from crawler.storage.db import connect; from crawler.storage.migrations.runner import migrate; migrate(connect(), Path('crawler/storage/migrations'))",
    ],
    { cwd: PROJECT_ROOT, env, stdio: "inherit" },
  );

  execFileSync(
    pythonBin(),
    [SEED_SCRIPT, "--force", "--database-url", DATABASE_URL],
    { cwd: PROJECT_ROOT, env, stdio: "inherit" },
  );
}
