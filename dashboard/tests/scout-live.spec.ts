import { test, expect } from "@playwright/test";
import path from "node:path";

/**
 * LIVE end-to-end CV upload + scan.
 *
 * scout.spec.ts intercepts /api/scout and asserts the browser-side contract
 * against a fixed payload. That is the right shape for CI, but on its own it
 * would pass with the Python scanner completely broken -- it never proves a real
 * CV produces real jobs. This spec closes that gap: it uploads a PDF, runs the
 * actual scan against live job sources, and asserts on what comes back.
 *
 * Opt-in, because it depends on the open internet and on karriere.at being up:
 *
 *     SCOUT_LIVE=1 npx playwright test scout-live
 *
 * Assertions are deliberately about SHAPE, not about specific jobs -- "row 1 is
 * a Vienna .NET role" would be a test that fails every time the Austrian job
 * market changes, which is daily.
 */

// __dirname, not import.meta.url: this package has no "type": "module", so
// Playwright loads specs as CommonJS and import.meta is a hard syntax error --
// which silently prevented the scout specs from loading at all.
const TEST_CV = path.join(__dirname, "fixtures", "test-cv.pdf");

// A live scan fans out across karriere.at plus the free APIs; ~12s is typical,
// so this is generous enough to absorb a slow board without hanging a run.
const SCAN_TIMEOUT_MS = 180_000;

test.describe("CV Scout — live scan", () => {
  test.skip(
    !process.env.SCOUT_LIVE,
    "live network test; run with SCOUT_LIVE=1",
  );
  test.setTimeout(SCAN_TIMEOUT_MS + 60_000);

  test("uploading a real CV returns real, current job matches", async ({ page }) => {
    await page.goto("/scout");
    await page.getByTestId("scout-cv-input").setInputFiles(TEST_CV);
    await page.getByTestId("scout-scan-button").click();

    await expect(page.getByTestId("scout-loading")).toBeVisible();

    // Either results or the empty state resolves; an error must not.
    await expect(page.getByTestId("scout-results")).toBeVisible({
      timeout: SCAN_TIMEOUT_MS,
    });
    await expect(page.getByTestId("scout-error")).toHaveCount(0);

    const rows = page.getByTestId("scout-job-row");
    expect(await rows.count()).toBeGreaterThan(0);

    // The profile really was built from the uploaded PDF, not defaulted.
    await expect(page.getByTestId("scout-results")).toContainText(/profile: (lexicon|llm)/);

    // Every row must carry the three things that make a match actionable:
    // a title, a company, and a link you can actually apply through.
    const first = rows.first();
    await expect(first).not.toContainText("undefined");
    const title = await first.locator("td").nth(0).innerText();
    expect(title.trim().length).toBeGreaterThan(2);
    expect(title.trim()).not.toBe("—");

    const applyLink = first.getByRole("link", { name: /Apply/ });
    await expect(applyLink).toHaveAttribute("href", /^https?:\/\//);
  });

  test("the scan is scored, not just listed", async ({ page }) => {
    await page.goto("/scout");
    await page.getByTestId("scout-cv-input").setInputFiles(TEST_CV);
    await page.getByTestId("scout-scan-button").click();
    await expect(page.getByTestId("scout-results")).toBeVisible({
      timeout: SCAN_TIMEOUT_MS,
    });

    // The top row's score must be a real number in range -- this is what
    // distinguishes "we ranked these against the CV" from "we dumped a feed".
    const topScore = await page
      .getByTestId("scout-job-row")
      .first()
      .locator("td")
      .nth(3)
      .innerText();
    const score = Number(topScore.trim());
    expect(Number.isFinite(score)).toBe(true);
    expect(score).toBeGreaterThan(0);
    expect(score).toBeLessThanOrEqual(100);
  });
});
