import { test, expect, type Page } from "@playwright/test";
import { databaseUnavailable } from "./db-availability";

/**
 * Tests run against a fresh test DB seeded by global-setup.ts:
 *   - 5 jobs (all source=ams): 2 at DemoCo, and one each at DataCorp,
 *     CloudOps, AIStartup
 *   - 2 runs (1 success, 1 partial with 1 error)
 *   - 1 error: a parse failure on the partial run
 *
 * These assertions describe scripts/seed_demo_data.py. They previously
 * described a different fixture entirely -- jobs at "ACME GmbH", a captcha
 * error, an "active" job count that no query or page has ever computed -- and
 * nobody noticed, because the whole describe block skips when PostgreSQL is
 * unreachable and PostgreSQL was never up. Keep them in step with the seeder.
 *
 * No console errors should appear on any page.
 *
 * Every assertion here reads seeded rows, so without PostgreSQL there is nothing
 * to assert against. global-setup.ts records an unreachable database in
 * tests/db-availability.ts; skipping on it keeps "the DB is down" legible instead of
 * reporting it as a dozen unrelated UI failures.
 */
test.skip(
  databaseUnavailable(),
  "PostgreSQL unavailable — run: docker compose up -d postgres",
);

async function expectNoConsoleErrors(page: Page) {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(err.message));
  // Attach to the test for later assertion
  return errors;
}

test.describe("Overview", () => {
  test("loads and renders 4 stat cards with expected values", async ({ page }) => {
    const errors = await expectNoConsoleErrors(page);
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

    // 5 seeded jobs
    await expect(page.getByTestId("stat-total-jobs")).toContainText("5");

    // The card counts SUCCESSFUL runs, with failed/partial as its hint -- so
    // the seeder's two runs read as 1 and 1, not as a total of 2.
    await expect(page.getByTestId("stat-total-runs")).toContainText("1");
    await expect(page.getByTestId("stat-total-runs")).toContainText("1 failed/partial");

    // Last run is the partial one (most recent)
    await expect(page.getByTestId("stat-last-run")).toContainText("ams");
    await expect(page.getByTestId("stat-last-run")).toContainText("partial");

    // The fourth card is a lifetime error total (stat-errors-total); there has
    // never been a last-24h card, which is what this used to look for. The
    // seeder records exactly one error, on the partial run.
    await expect(page.getByTestId("stat-errors-total")).toContainText("1");

    expect(errors).toEqual([]);
  });

  test("shows recent jobs table", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Recent jobs" })).toBeVisible();
    // 5 jobs in seed, all visible on overview
    const rows = page.getByTestId("job-row");
    await expect(rows).toHaveCount(5);
  });

  test("shows recent runs table", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Recent runs" })).toBeVisible();
    const rows = page.getByTestId("run-row");
    await expect(rows).toHaveCount(2);
  });

  test("'View all' links navigate to detail pages", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("link-all-jobs").click();
    await expect(page).toHaveURL(/\/jobs$/);
    await expect(page.getByRole("heading", { name: "Jobs" })).toBeVisible();
  });
});

test.describe("Jobs page", () => {
  test("lists all 5 jobs with source pills", async ({ page }) => {
    await page.goto("/jobs");
    await expect(page.getByRole("heading", { name: "Jobs" })).toBeVisible();
    const rows = page.getByTestId("job-row");
    await expect(rows).toHaveCount(5);
    // All jobs are from ams source
    await expect(page.getByTestId("job-row").first()).toHaveAttribute("data-source", "ams");
  });

  test("filter by source=ams shows 5 jobs", async ({ page }) => {
    await page.goto("/jobs?source=ams");
    await expect(page.getByTestId("job-row")).toHaveCount(5);
  });

  test("filter by unknown source shows empty state", async ({ page }) => {
    await page.goto("/jobs?source=does-not-exist");
    await expect(page.getByTestId("job-table-empty")).toBeVisible();
  });

  test("search for 'DemoCo' returns that company's 2 jobs", async ({ page }) => {
    await page.goto("/jobs?search=DemoCo");
    const rows = page.getByTestId("job-row");
    await expect(rows).toHaveCount(2);
    await expect(rows.first()).toContainText("DemoCo");
  });

  test("search for 'python' returns jobs with 'python' in title/company", async ({ page }) => {
    await page.goto("/jobs?search=python");
    const rows = page.getByTestId("job-row");
    // Matches "Senior Backend Engineer (Python)" on title. The WHERE clause
    // covers title + company only, never description.
    await expect(rows.first()).toContainText(/python/i);
  });

  test("submitting the filter form navigates with new query", async ({ page }) => {
    await page.goto("/jobs");
    await page.getByTestId("jobs-source-filter").selectOption("ams");
    await page.getByTestId("jobs-search").fill("DemoCo");
    await page.getByTestId("jobs-filter-submit").click();
    await expect(page).toHaveURL(/source=ams/);
    await expect(page).toHaveURL(/search=DemoCo/);
    await expect(page.getByTestId("job-row")).toHaveCount(2);
  });
});

test.describe("Runs page", () => {
  test("lists both runs with correct status badges", async ({ page }) => {
    await page.goto("/runs");
    await expect(page.getByRole("heading", { name: "Runs" })).toBeVisible();
    const rows = page.getByTestId("run-row");
    await expect(rows).toHaveCount(2);

    // One partial, one success
    await expect(page.getByTestId("status-partial")).toHaveCount(1);
    await expect(page.getByTestId("status-success")).toHaveCount(1);
  });

  test("expanding error toggle reveals the seeded parse error", async ({ page }) => {
    await page.goto("/runs");
    // The partial run has 1 error
    const errorToggle = page.getByTestId("run-errors-toggle");
    await expect(errorToggle).toHaveCount(1);
    await errorToggle.click();
    const errs = page.getByTestId("run-error");
    await expect(errs).toHaveCount(1);
    await expect(errs.first()).toContainText("Failed to parse one listing");
  });
});

test.describe("Navigation", () => {
  test("brand link returns to overview", async ({ page }) => {
    await page.goto("/jobs");
    await page.getByTestId("nav-brand").click();
    await expect(page).toHaveURL(/\/$/);
  });

  test("nav links go to overview, jobs, runs", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("nav-link-jobs").click();
    await expect(page).toHaveURL(/\/jobs$/);
    await page.getByTestId("nav-link-runs").click();
    await expect(page).toHaveURL(/\/runs$/);
    await page.getByTestId("nav-link-overview").click();
    await expect(page).toHaveURL(/\/$/);
  });
});
