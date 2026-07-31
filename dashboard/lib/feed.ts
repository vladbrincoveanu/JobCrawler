import { readFile } from "node:fs/promises";
import path from "node:path";
import type { ScoutResult } from "@/app/api/scout/route";

/**
 * Loads the scans produced by the scheduled GitHub Actions run.
 *
 * The cron publishes one directory tree to the public `scout-data` branch:
 *
 *   results/<cv-id>.json   the scored jobs for that CV
 *   runs/<cv-id>.json      that CV's last run record (slot, status, matches)
 *   sent/<cv-id>.json      alert de-duplication state (not read here)
 *
 * Three ways in, in priority order:
 *   1. SCOUT_FEED_BASE_URL — the raw base URL of that branch. This is what the
 *      Vercel deployment uses: it has no checkout and no filesystem to read.
 *   2. SCOUT_FEED_URL — the legacy single-CV feed, kept for one release.
 *   3. The local tree, for a checkout that has pulled the branch.
 *
 * A missing feed is a normal state (that CV has not been scanned yet), not an
 * error, so it resolves to null and the page explains how to populate it. An
 * unreadable one is an error and must stay distinguishable: collapsing the two
 * would hide a broken cron behind a friendly "nothing yet" for as long as
 * nobody thought to open the Actions tab.
 */

const REPO_ROOT = process.env.SCOUT_REPO_ROOT ?? path.resolve(process.cwd(), "..");
const CV_ID_RE = /^[a-z0-9-]{1,40}$/;

/** Resolved per call, not once at module load: the test suite points this at a
 *  fixture, and a module-level constant would freeze whichever value happened
 *  to be set when Next first imported this file. */
export function feedPath(): string {
  return process.env.SCOUT_FEED_PATH ?? path.join(REPO_ROOT, "data", "scout", "latest.json");
}

/** A local checkout of the scout-data branch, or the cron's state directory. */
function feedDir(): string {
  return process.env.SCOUT_FEED_DIR ?? path.join(REPO_ROOT, "data", "scout");
}

function assertCvId(cvId: string): void {
  // Validated before the base-URL check, not after: otherwise "../../secrets"
  // is accepted whenever SCOUT_FEED_BASE_URL happens to be unset, and the
  // traversal only surfaces in the deployment that does have it set.
  if (!CV_ID_RE.test(cvId)) throw new Error(`Invalid CV id: ${cvId}`);
}

export function feedUrlFor(cvId: string): string | null {
  assertCvId(cvId);
  const base = process.env.SCOUT_FEED_BASE_URL;
  if (!base) return null;
  return `${base.replace(/\/$/, "")}/results/${cvId}.json`;
}

export function feedPathFor(cvId: string): string {
  assertCvId(cvId);
  return path.join(feedDir(), "results", `${cvId}.json`);
}

export function runUrlFor(cvId: string): string | null {
  assertCvId(cvId);
  const base = process.env.SCOUT_FEED_BASE_URL;
  if (!base) return null;
  return `${base.replace(/\/$/, "")}/runs/${cvId}.json`;
}

export function runPathFor(cvId: string): string {
  assertCvId(cvId);
  return path.join(feedDir(), "runs", `${cvId}.json`);
}

export interface FeedLoad {
  result: ScoutResult | null;
  origin: string | null;
  error: string | null;
}

/** One CV's last run, as written by scripts/publish.py `run`. */
export interface RunRecord {
  slot: string;
  status: "ok" | "error";
  attempts: number;
  matches: number;
  finished_at: string;
}

async function loadJson<T>(
  url: string | null | undefined,
  file: string,
): Promise<{ value: T | null; origin: string | null; error: string | null }> {
  if (url) {
    try {
      const res = await fetch(url, { cache: "no-store" });
      // 404 is "this CV has never been scanned", which is an empty state on a
      // fresh feed branch -- not something to render as a failure.
      if (res.status === 404) return { value: null, origin: url, error: null };
      if (!res.ok) {
        return { value: null, origin: url, error: `Feed URL returned ${res.status}.` };
      }
      return { value: (await res.json()) as T, origin: url, error: null };
    } catch (err) {
      return {
        value: null,
        origin: url,
        error: err instanceof Error ? err.message : "Feed fetch failed.",
      };
    }
  }

  try {
    const raw = await readFile(file, "utf-8");
    return { value: JSON.parse(raw) as T, origin: file, error: null };
  } catch (err) {
    const code = (err as NodeJS.ErrnoException)?.code;
    if (code === "ENOENT") return { value: null, origin: file, error: null };
    return {
      value: null,
      origin: file,
      error: err instanceof Error ? err.message : "Feed file unreadable.",
    };
  }
}

/** Load one CV's feed, or the legacy single feed when no id is given. */
export async function loadFeed(cvId?: string): Promise<FeedLoad> {
  const url = (cvId ? feedUrlFor(cvId) : null) ?? process.env.SCOUT_FEED_URL;
  const file = cvId ? feedPathFor(cvId) : feedPath();
  const { value, origin, error } = await loadJson<ScoutResult>(url, file);
  return { result: value, origin, error };
}

/** Load one CV's run record. Absent until that CV has run once. */
export async function loadRun(cvId: string): Promise<RunRecord | null> {
  const { value } = await loadJson<RunRecord>(runUrlFor(cvId), runPathFor(cvId));
  return value;
}
