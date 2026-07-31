import { test, expect } from "@playwright/test";

/**
 * /matches — the standing job list produced by the scheduled scout-cron scan.
 *
 * The page reads its feed on the SERVER, so `page.route` cannot fake it the
 * way scout.spec.ts fakes /api/scout. Instead playwright.config.ts starts the
 * dashboard with SCOUT_FEED_PATH pointed at tests/fixtures/scout-feed.json,
 * and these tests assert against that known scan. Its three ads are chosen to
 * cover exactly what the filters have to get right: one fresh ad with a
 * numeric salary, one three-week-old ad with no salary, and one undated ad
 * whose salary is a raw German pay string rather than a number.
 */

const FEED_TOTAL = 3;

test.describe("matches feed", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/matches");
  });

  test("renders every job in the feed by default", async ({ page }) => {
    await expect(page.getByTestId("matches-count")).toHaveText(
      `${FEED_TOTAL} of ${FEED_TOTAL} shown`,
    );
    await expect(page.getByTestId("scout-job-row")).toHaveCount(FEED_TOTAL);
    await expect(page.getByText("Senior .NET Engineer")).toBeVisible();
  });

  test("states when the scan ran, so a stale feed is visible as stale", async ({
    page,
  }) => {
    await expect(page.getByTestId("matches-provenance")).toContainText("137 scored");
  });

  test("salary column shows both parsed and raw pay, and blanks the silent ad", async ({
    page,
  }) => {
    const cells = page.getByTestId("scout-salary");
    await expect(cells.nth(0)).toContainText("85,900");
    await expect(cells.nth(1)).toHaveText("—");
    await expect(cells.nth(2)).toContainText("4.500");
  });

  test("the salary filter drops ads that state no pay", async ({ page }) => {
    await page.getByTestId("filter-require-salary").check();
    // Beta AG is the only ad with salary: null; the raw-string one must stay.
    await expect(page.getByTestId("scout-job-row")).toHaveCount(2);
    await expect(page.getByText("Kafka Platform Engineer")).toBeHidden();
    await expect(page.getByTestId("matches-count")).toHaveText(`2 of ${FEED_TOTAL} shown`);
  });

  test("the recency filter drops ads older than the window", async ({ page }) => {
    // Feed generated 2026-07-30; Beta AG posted 2026-07-10 is 20 days back.
    await page.getByTestId("filter-days").selectOption("7");
    await expect(page.getByText("Kafka Platform Engineer")).toBeHidden();
    await expect(page.getByText("Senior .NET Engineer")).toBeVisible();
  });

  test("an undated ad survives the recency filter", async ({ page }) => {
    // Boards that omit the posting date would otherwise vanish entirely the
    // moment any date filter is touched -- silently, and looking like a scan
    // that found nothing.
    await page.getByTestId("filter-days").selectOption("1");
    await expect(page.getByText("Backend Developer (undated ad)")).toBeVisible();
  });

  test("the two filters compose", async ({ page }) => {
    await page.getByTestId("filter-days").selectOption("1");
    await page.getByTestId("filter-require-salary").check();
    // Beta AG fails both (20 days old, no salary). ACME passes on freshness,
    // Gamma passes as undated-with-pay -- so composing must leave exactly those.
    await expect(page.getByTestId("scout-job-row")).toHaveCount(2);
    await expect(page.getByText("Kafka Platform Engineer")).toBeHidden();
    await expect(page.getByTestId("matches-count")).toHaveText(`2 of ${FEED_TOTAL} shown`);
  });

  test("company pros/cons expand on demand and carry the provenance caveat", async ({
    page,
  }) => {
    await expect(page.getByTestId("company-review-panel")).toHaveCount(0);
    await page.getByTestId("company-review-toggle").first().click();
    const panel = page.getByTestId("company-review-panel");
    await expect(panel).toContainText("strong engineering culture");
    await expect(panel).toContainText("slow promotion cycles");
    // The caveat is not decoration: these pros/cons are model output, and the
    // page must never let them read as scraped from a review site.
    await expect(page.getByTestId("company-review-caveat")).toContainText(
      "not read",
    );
  });

  test("only companies with a review offer the toggle", async ({ page }) => {
    await expect(page.getByTestId("company-review-toggle")).toHaveCount(1);
  });

  test("is reachable from the nav", async ({ page }) => {
    await page.goto("/scout");
    await page.getByTestId("nav-link-matches").click();
    await expect(page).toHaveURL(/\/matches$/);
  });
});
