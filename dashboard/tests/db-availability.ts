import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

/**
 * Whether global-setup could reach PostgreSQL, shared with the spec files.
 *
 * This is a file on disk rather than an environment variable because Playwright
 * runs globalSetup in a different process from the test workers, so a
 * `process.env.X = ...` written in setup is simply not visible in a spec -- the
 * DB-dependent tests went on running (and failing) against a database that
 * global-setup had already reported as unreachable.
 */
const MARKER = path.join(__dirname, "..", "test-results", ".no-db");

export function recordDatabaseUnavailable(reason: string): void {
  mkdirSync(path.dirname(MARKER), { recursive: true });
  writeFileSync(MARKER, reason || "unreachable", "utf-8");
}

export function clearDatabaseUnavailable(): void {
  rmSync(MARKER, { force: true });
}

export function databaseUnavailable(): boolean {
  return existsSync(MARKER);
}
