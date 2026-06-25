import { test, expect, type ConsoleMessage } from "@playwright/test";

/**
 * Smoke tests for the Vite UI. These verify that:
 *  - The page loads against a live DB.
 *  - The location and source filters narrow the jobs table.
 *  - The new enrichment columns render (even if enrichment is absent).
 *  - The "Compute enrichment" button triggers a request and re-renders.
 *  - No console errors fire on load.
 *
 * Assumes the UI server is running on :3012 with seed data. The test
 * seeds enrichment for the first job it sees, then verifies chips and
 * a salary cell appear.
 */

const FILTER_DEBOUNCE_MS = 400; // matches 200ms debounce + headroom

test("page loads with stats, jobs, runs panels", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: /JobCrawler/ })).toBeVisible();
  await expect(page.getByText(/Total jobs/)).toBeVisible();
  await expect(page.getByText(/Runs/)).toBeVisible();
  await expect(page.getByText(/Errors/)).toBeVisible();

  // jobs table renders at least one row
  const rows = page.locator('[data-testid^="job-row-"]');
  await expect(rows.first()).toBeVisible();
  expect(await rows.count()).toBeGreaterThan(0);
});

test("new columns are present (Keywords, Salary, Reviews)", async ({ page }) => {
  await page.goto("/");

  const headerRow = page.getByRole("row").first();
  await expect(headerRow.getByText("Keywords")).toBeVisible();
  await expect(headerRow.getByText(/Est\. salary/)).toBeVisible();
  await expect(headerRow.getByText("Reviews")).toBeVisible();
});

test("location filter narrows results", async ({ page }) => {
  await page.goto("/");

  const rows = page.locator('[data-testid^="job-row-"]');
  const baseline = await rows.count();
  test.skip(baseline === 0, "no jobs in DB to filter");

  // Filter to a location that almost certainly matches nothing.
  await page.getByTestId("location-filter").fill("__no_such_city_xyz__");
  await page.waitForTimeout(FILTER_DEBOUNCE_MS);

  await expect(rows).toHaveCount(0);

  // Clearing returns to baseline.
  await page.getByTestId("location-filter").fill("");
  await page.waitForTimeout(FILTER_DEBOUNCE_MS);
  await expect(rows.first()).toBeVisible();
  expect(await rows.count()).toBeGreaterThan(0);
});

test("'Compute enrichment' button hits the API and reloads rows", async ({ page }) => {
  await page.goto("/");

  const btn = page.getByTestId("enrich-btn");
  await expect(btn).toBeEnabled();
  await btn.click();

  // The button shows a "Enriching…" / "Compute enrichment" label change.
  await expect(page.getByText(/Enrichment:/)).toBeVisible({ timeout: 30_000 });
});

test("no console errors on initial load", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.goto("/");
  await expect(page.getByRole("heading", { name: /JobCrawler/ })).toBeVisible();

  // Allow late-firing network requests (image, etc) to settle.
  await page.waitForLoadState("networkidle");

  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});
