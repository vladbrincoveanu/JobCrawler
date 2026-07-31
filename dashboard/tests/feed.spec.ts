import { test, expect } from "@playwright/test";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { loadFeed, loadRun, feedUrlFor, runUrlFor } from "../lib/feed";

/**
 * loadFeed's failure modes, which /matches renders very differently and which
 * the browser spec cannot reach (the server reads the feed once, at request
 * time, from whatever SCOUT_FEED_PATH the test server was started with).
 *
 * The distinction that matters: "no scan has run yet" is a normal empty state
 * with setup instructions, while "the feed is there but unreadable" is an
 * error. Collapsing the second into the first would hide a broken cron behind
 * a friendly "nothing yet" message for as long as nobody checked Actions.
 */

const ORIGINAL = process.env.SCOUT_FEED_PATH;

test.afterEach(() => {
  if (ORIGINAL === undefined) delete process.env.SCOUT_FEED_PATH;
  else process.env.SCOUT_FEED_PATH = ORIGINAL;
  delete process.env.SCOUT_FEED_URL;
  delete process.env.SCOUT_FEED_DIR;
  delete process.env.SCOUT_FEED_BASE_URL;
});

test("a missing feed is an empty state, not an error", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "feed-"));
  process.env.SCOUT_FEED_PATH = path.join(dir, "never-written.json");

  const { result, error } = await loadFeed();
  expect(result).toBeNull();
  expect(error).toBeNull();
});

test("a corrupt feed is reported as an error, not as an empty state", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "feed-"));
  const file = path.join(dir, "latest.json");
  // Exactly what a scan killed mid-write leaves behind.
  await writeFile(file, '{"generated_at": "2026-07-30T12:00:00", "jobs": [');
  process.env.SCOUT_FEED_PATH = file;

  const { result, error } = await loadFeed();
  expect(result).toBeNull();
  expect(error).not.toBeNull();
});

test("a valid feed is parsed and its origin reported", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "feed-"));
  const file = path.join(dir, "latest.json");
  await writeFile(
    file,
    JSON.stringify({
      generated_at: "2026-07-30T12:00:00",
      cv: "cv.pdf",
      profile_source: "lexicon",
      total_matches: 1,
      jobs: [{ title: "Dev" }],
    }),
  );
  process.env.SCOUT_FEED_PATH = file;

  const { result, origin, error } = await loadFeed();
  expect(error).toBeNull();
  expect(result?.jobs).toHaveLength(1);
  // The page prints this so "which scan am I looking at" is answerable.
  expect(origin).toBe(file);
});

test("SCOUT_FEED_URL takes priority over the local file", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "feed-"));
  const file = path.join(dir, "latest.json");
  await writeFile(file, JSON.stringify({ jobs: [{ title: "local" }] }));
  process.env.SCOUT_FEED_PATH = file;
  // A deployed dashboard has no checkout to read; if the URL were ignored in
  // favour of a stale local file it would silently serve the wrong scan.
  process.env.SCOUT_FEED_URL = "http://127.0.0.1:9/unreachable.json";

  const { result, origin } = await loadFeed();
  expect(result).toBeNull();
  expect(origin).toBe("http://127.0.0.1:9/unreachable.json");
});

// --- per-CV feeds -----------------------------------------------------------

test("loads a per-CV feed from the state directory", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "feed-"));
  await mkdir(path.join(dir, "results"), { recursive: true });
  await writeFile(
    path.join(dir, "results", "backend-streaming.json"),
    JSON.stringify({
      generated_at: "2026-07-31T05:10:00",
      cv: "backend-streaming",
      total_matches: 1,
      jobs: [{ title: "T" }],
    }),
  );
  process.env.SCOUT_FEED_DIR = dir;

  const { result, error } = await loadFeed("backend-streaming");
  expect(error).toBeNull();
  expect(result?.jobs).toHaveLength(1);
});

test("a missing per-CV feed is an empty state, not an error", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "feed-"));
  process.env.SCOUT_FEED_DIR = dir;

  const { result, error } = await loadFeed("never-scanned");
  expect(result).toBeNull();
  expect(error).toBeNull();
});

test("one CV's feed is never served for another CV", async () => {
  // The id addresses the file; if it were ignored anywhere in the lookup the
  // switcher would show four identical boards and nobody would notice for days.
  const dir = await mkdtemp(path.join(tmpdir(), "feed-"));
  await mkdir(path.join(dir, "results"), { recursive: true });
  await writeFile(
    path.join(dir, "results", "devops-sre.json"),
    JSON.stringify({ jobs: [{ title: "sre" }] }),
  );
  process.env.SCOUT_FEED_DIR = dir;

  expect((await loadFeed("devops-sre")).result?.jobs).toHaveLength(1);
  expect((await loadFeed("fullstack")).result).toBeNull();
});

test("SCOUT_FEED_BASE_URL builds the per-CV URLs", () => {
  process.env.SCOUT_FEED_BASE_URL = "https://raw.example/repo/scout-data";
  expect(feedUrlFor("backend-streaming")).toBe(
    "https://raw.example/repo/scout-data/results/backend-streaming.json",
  );
  expect(runUrlFor("backend-streaming")).toBe(
    "https://raw.example/repo/scout-data/runs/backend-streaming.json",
  );
});

test("a trailing slash on the base URL does not produce a double slash", () => {
  process.env.SCOUT_FEED_BASE_URL = "https://raw.example/repo/scout-data/";
  expect(feedUrlFor("x")).toBe("https://raw.example/repo/scout-data/results/x.json");
});

test("a CV id with a path separator is refused", () => {
  expect(() => feedUrlFor("../../secrets")).toThrow(/Invalid CV id/);
  // ...including when no base URL is set, where the id would otherwise reach
  // the filesystem path builder unchecked.
  expect(() => feedUrlFor("a/b")).toThrow(/Invalid CV id/);
});

test("a run record is read per CV, and absent before the first run", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "feed-"));
  await mkdir(path.join(dir, "runs"), { recursive: true });
  await writeFile(
    path.join(dir, "runs", "fullstack.json"),
    JSON.stringify({
      slot: "2026-07-31T05",
      status: "ok",
      attempts: 1,
      matches: 12,
      finished_at: "2026-07-31T05:12:00Z",
    }),
  );
  process.env.SCOUT_FEED_DIR = dir;

  expect((await loadRun("fullstack"))?.matches).toBe(12);
  expect(await loadRun("devops-sre")).toBeNull();
});
