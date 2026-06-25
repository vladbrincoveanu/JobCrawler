import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for the Vite UI.
 *
 * Assumes the UI server is already running on :3012 (started via
 * `npm run start` in another terminal). We don't auto-start it from
 * the webServer directive because the user may want to keep the
 * dev session interactive while iterating.
 *
 * To run:
 *   1. Start the server: `cd ui && DATABASE_URL=... npm run start`
 *   2. Run tests:        `cd ui && npx playwright test`
 */
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false, // single-user tool; jobs are mutated by tests
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: "list",

  use: {
    baseURL: "http://127.0.0.1:3012",
    trace: "on-first-retry",
    actionTimeout: 5000,
    navigationTimeout: 10000,
  },

  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
