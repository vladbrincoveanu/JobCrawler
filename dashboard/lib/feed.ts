import { readFile } from "node:fs/promises";
import path from "node:path";
import type { ScoutResult } from "@/app/api/scout/route";

/**
 * Loads the scan produced by the scheduled GitHub Actions run.
 *
 * Two ways in, in priority order:
 *   1. SCOUT_FEED_URL — the raw URL of latest.json on the data branch, for a
 *      deployed dashboard that has no checkout of the repo to read from.
 *   2. data/scout/latest.json in the repo — what you get locally after the
 *      workflow's commit is pulled, or after running scout.py by hand.
 *
 * A missing feed is a normal state (nobody has run the cron yet), not an
 * error, so it resolves to null and the page explains how to populate it.
 */

const REPO_ROOT = process.env.SCOUT_REPO_ROOT ?? path.resolve(process.cwd(), "..");

/** Resolved per call, not once at module load: the test suite points this at a
 *  fixture, and a module-level constant would freeze whichever value happened
 *  to be set when Next first imported this file. */
export function feedPath(): string {
  return process.env.SCOUT_FEED_PATH ?? path.join(REPO_ROOT, "data", "scout", "latest.json");
}

export interface FeedLoad {
  result: ScoutResult | null;
  origin: string | null;
  error: string | null;
}

export async function loadFeed(): Promise<FeedLoad> {
  const url = process.env.SCOUT_FEED_URL;
  if (url) {
    try {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) {
        return { result: null, origin: url, error: `Feed URL returned ${res.status}.` };
      }
      return { result: (await res.json()) as ScoutResult, origin: url, error: null };
    } catch (err) {
      return {
        result: null,
        origin: url,
        error: err instanceof Error ? err.message : "Feed fetch failed.",
      };
    }
  }

  const file = feedPath();
  try {
    const raw = await readFile(file, "utf-8");
    return { result: JSON.parse(raw) as ScoutResult, origin: file, error: null };
  } catch (err) {
    const code = (err as NodeJS.ErrnoException)?.code;
    if (code === "ENOENT") return { result: null, origin: file, error: null };
    return {
      result: null,
      origin: file,
      // A truncated or half-written latest.json must not read as "no scan yet":
      // that would hide a broken cron behind an innocuous empty state.
      error: err instanceof Error ? err.message : "Feed file unreadable.",
    };
  }
}
