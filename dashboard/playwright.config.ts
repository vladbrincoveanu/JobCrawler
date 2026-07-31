import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for the dashboard.
 *
 * Test isolation: global setup creates a dedicated test DB (jobcrawler_test),
 * runs migrations, seeds demo data. The webServer points the dashboard at
 * this DB via DATABASE_URL.
 *
 * Port 3011 by default because port 3010 is occupied by knowledgeforge-ui.
 * Override with DASHBOARD_PORT: the port was hard-coded in three places, so a
 * second dashboard already listening on 3011 (another dev server, a parallel
 * checkout) made the whole suite die with EADDRINUSE and no way to move it.
 */
const PORT = Number(process.env.DASHBOARD_PORT ?? 3011);
const BASE_URL = `http://127.0.0.1:${PORT}`;
const FEED_FIXTURE = require("node:path").resolve(
  __dirname,
  "tests/fixtures/scout-feed.json",
);
const TEST_DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://jobcrawler:dev@localhost:5433/jobcrawler_test";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: "list",

  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    actionTimeout: 5000,
    navigationTimeout: 10000,
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  globalSetup: require("node:path").resolve(__dirname, "tests/global-setup.ts"),

  // The lib specs (cv-profiles, credentials, feed) are pure Node: they call
  // filesystem helpers directly and never open a page. Booting Next for them
  // costs a two-minute build, and in a sandbox that forbids listen(2) it fails
  // outright -- which reported as "0 tests ran", not as an error. PW_NO_SERVER=1
  // runs them against no server at all.
  webServer: process.env.PW_NO_SERVER ? undefined : {
    // `next start` needs a build, and the suite previously assumed one already
    // existed -- on a clean checkout it just timed out waiting for a server that
    // could never boot. Building here also means a broken build fails the test
    // run instead of silently reusing a stale .next.
    // SCOUT_FEED_PATH points /matches at a checked-in fixture scan instead of
    // whatever data/scout/latest.json happens to hold on this machine -- the
    // page must be asserted against a known feed, and a developer's real scan
    // is neither known nor safe to overwrite.
    command:
      `npx next build && DATABASE_URL=${TEST_DATABASE_URL} ` +
      `SCOUT_FEED_PATH=${FEED_FIXTURE} ` +
      `npx next start --port ${PORT}`,
    // Readiness is probed on /scout, NOT on "/". The overview page queries
    // PostgreSQL while rendering, and with no database running that request
    // HANGS rather than erroring -- so Playwright never saw the server come up,
    // timed out after four minutes, and the whole suite failed to start. That
    // defeated global-setup's deliberate "skip the DB specs but still run the
    // scout specs" handling, because nothing ran at all. /scout is statically
    // rendered and touches no database, which is exactly the question
    // "is the server listening?" should be asking.
    url: `${BASE_URL}/scout`,
    timeout: 240_000,
    reuseExistingServer: !process.env.CI,
    stdout: "pipe",
    stderr: "pipe",
  },
});
