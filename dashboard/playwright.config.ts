import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for the dashboard.
 *
 * Test isolation: global setup creates a dedicated test DB (jobcrawler_test),
 * runs migrations, seeds demo data. The webServer points the dashboard at
 * this DB via DATABASE_URL.
 *
 * Port 3011 used because port 3010 is occupied by knowledgeforge-ui.
 */
export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: "list",

  use: {
    baseURL: "http://127.0.0.1:3011",
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

  webServer: {
    command: `DATABASE_URL=postgresql://jobcrawler:dev@localhost:5433/jobcrawler_test npx next start --port 3011`,
    url: "http://127.0.0.1:3011",
    timeout: 30_000,
    reuseExistingServer: !process.env.CI,
    stdout: "pipe",
    stderr: "pipe",
  },
});
