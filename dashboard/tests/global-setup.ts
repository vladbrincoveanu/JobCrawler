import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync, existsSync } from "node:fs";
import path from "node:path";

/**
 * Global setup: regenerate a clean test DB at .next/test.db before each
 * Playwright run. Invokes the Python seed script with --force so the
 * dashboard sees a deterministic 5-job / 2-run / 1-error fixture set.
 */
const TEST_DB = path.resolve(__dirname, "../.next/test.db");
const PROJECT_ROOT = path.resolve(__dirname, "../..");
const SEED_SCRIPT = path.join(PROJECT_ROOT, "scripts/seed_demo_data.py");

export default async function globalSetup() {
  mkdirSync(path.dirname(TEST_DB), { recursive: true });
  if (existsSync(TEST_DB)) {
    rmSync(TEST_DB, { force: true });
    // WAL mode leaves sidecar files; remove them too.
    for (const suffix of ["-shm", "-wal"]) {
      const p = TEST_DB + suffix;
      if (existsSync(p)) rmSync(p, { force: true });
    }
  }

  execFileSync(
    "python",
    [SEED_SCRIPT, "--force", "--db", TEST_DB],
    {
      cwd: PROJECT_ROOT,
      env: { ...process.env, PYTHONPATH: PROJECT_ROOT },
      stdio: "inherit",
    }
  );
}
