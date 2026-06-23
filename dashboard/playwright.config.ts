import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

/**
 * Playwright config for the dashboard.
 *
 * Test isolation: uses a dedicated test DB at .next/test.db (gitignored,
 * regenerated per run). Global setup invokes the Python seed script with
 * --force so each run starts from a known state. The webServer points the
 * dashboard at this test DB via JOB_CRAWLER_DB.
 */
const TEST_DB = path.resolve(__dirname, ".next/test.db");
const PROJECT_ROOT = path.resolve(__dirname, "..");
const SEED_SCRIPT = path.join(PROJECT_ROOT, "scripts/seed_demo_data.py");

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: "list",

  use: {
    baseURL: "http://127.0.0.1:3010",
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

  globalSetup: path.resolve(__dirname, "tests/global-setup.ts"),

  webServer: {
    command: `JOB_CRAWLER_DB=${TEST_DB} npx next start --port 3010`,
    url: "http://127.0.0.1:3010",
    timeout: 30_000,
    reuseExistingServer: !process.env.CI,
    stdout: "pipe",
    stderr: "pipe",
  },
});
