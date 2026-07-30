import { test, expect } from "@playwright/test";
import path from "node:path";

/**
 * CV upload + scan flow.
 *
 * The /api/scout route shells out to scripts/scout.py, which hits live job
 * sources (karriere.at, StepStone.at, arbeitnow/remotive/jobicy) over the
 * network. That's inherently non-deterministic for CI/sandboxed test runs
 * (results depend on what's posted right now, and some environments have no
 * outbound access to those domains at all), so these tests intercept
 * `**\/api/scout` with `page.route` and assert against the UI's handling of a
 * fixed response -- the same technique the rest of this suite would use for
 * any third-party-network-dependent endpoint. This verifies the browser-side
 * upload/scan/render contract; it does not exercise the live Python scan
 * end-to-end (that's covered by scripts/scout.py's own pytest suite, notably
 * tests/test_scout_json_out.py).
 */

// __dirname, not import.meta.url: this package has no "type": "module", so
// Playwright loads specs as CommonJS and import.meta is a hard syntax error --
// which silently prevented this whole spec file from loading.
const FIXTURES_DIR = __dirname;
// Regenerate with `python scripts/make_test_cv.py`. The previous fixture
// (dummy-cv.pdf) was a valid PDF containing no text objects, so pypdf extracted
// "" from it and every profile built from it had zero skills -- it could not
// have caught a break in the extraction or scoring path.
const DUMMY_CV = path.join(FIXTURES_DIR, "fixtures", "test-cv.pdf");

const MOCK_RESULT = {
  generated_at: "2026-07-30T12:00:00",
  cv: "/tmp/uploaded-cv.pdf",
  profile_source: "lexicon",
  total_matches: 2,
  jobs: [
    {
      title: "Senior Backend Engineer",
      company: "ACME GmbH",
      location: "Wien, Austria",
      posted: "2026-07-29",
      salary: 75000,
      source: "karriere_at",
      apply_url: "https://example.com/jobs/1",
      score: 42,
      rank: 1,
      rank_score: 100,
      fit: null,
      reason: null,
      bucket: null,
    },
    {
      title: "Kafka Platform Engineer",
      company: "Beta AG",
      location: "Remote, EU",
      posted: "2026-07-28",
      salary: null,
      source: "arbeitnow",
      apply_url: "https://example.com/jobs/2",
      score: 30,
      rank: 2,
      rank_score: 50,
      fit: null,
      reason: null,
      bucket: null,
    },
  ],
};

test.describe("CV Scout", () => {
  test("uploads a CV, scans, and renders ranked matches", async ({ page }) => {
    await page.route("**/api/scout", async (route) => {
      await route.fulfill({ json: MOCK_RESULT });
    });

    await page.goto("/scout");
    await expect(page.getByRole("heading", { name: "CV Scout" })).toBeVisible();

    await page.getByTestId("scout-cv-input").setInputFiles(DUMMY_CV);
    await page.getByTestId("scout-scan-button").click();

    await expect(page.getByTestId("scout-results")).toBeVisible();
    const rows = page.getByTestId("scout-job-row");
    await expect(rows).toHaveCount(2);
    await expect(rows.first()).toContainText("Senior Backend Engineer");
    await expect(rows.first()).toContainText("ACME GmbH");
    await expect(rows.nth(1)).toContainText("Kafka Platform Engineer");
  });

  test("scan button is disabled until a CV is chosen", async ({ page }) => {
    await page.goto("/scout");
    await expect(page.getByTestId("scout-scan-button")).toBeDisabled();
    await page.getByTestId("scout-cv-input").setInputFiles(DUMMY_CV);
    await expect(page.getByTestId("scout-scan-button")).toBeEnabled();
  });

  test("shows a graceful empty state when nothing matches", async ({ page }) => {
    await page.route("**/api/scout", async (route) => {
      await route.fulfill({
        json: { ...MOCK_RESULT, total_matches: 0, jobs: [] },
      });
    });

    await page.goto("/scout");
    await page.getByTestId("scout-cv-input").setInputFiles(DUMMY_CV);
    await page.getByTestId("scout-scan-button").click();

    await expect(page.getByTestId("scout-results-empty")).toBeVisible();
  });

  test("shows an error message when the scan fails", async ({ page }) => {
    await page.route("**/api/scout", async (route) => {
      await route.fulfill({
        status: 502,
        json: { error: "Scan failed.", detail: "scout.py exited non-zero" },
      });
    });

    await page.goto("/scout");
    await page.getByTestId("scout-cv-input").setInputFiles(DUMMY_CV);
    await page.getByTestId("scout-scan-button").click();

    await expect(page.getByTestId("scout-error")).toBeVisible();
    await expect(page.getByTestId("scout-error")).toContainText("scout.py exited non-zero");
  });
});

/**
 * End-to-end through the REAL /api/scout route -- no page.route stub of the
 * response.
 *
 * The browser uploads the fixture PDF, Next.js spawns scripts/scout.py, the CLI
 * extracts the CV text with pypdf, builds a skill profile, writes --json-out,
 * and the page renders what came back. Every link in that chain runs except the
 * job boards themselves, which are switched off with `sources=none` so the test
 * cannot fail because karriere.at was slow or Adzuna renamed a field. That
 * gives a deterministic assertion here, plus an opt-in live variant below that
 * does hit the real boards.
 */
test.describe("CV Scout — real API route", () => {
  test("uploads a CV and runs the real scan pipeline", async ({ page }) => {
    const statuses: number[] = [];
    page.on("response", (r) => {
      if (r.url().includes("/api/scout")) statuses.push(r.status());
    });

    await page.route("**/api/scout", (route) => {
      const url = new URL(route.request().url());
      url.searchParams.set("sources", "none");
      return route.continue({ url: url.toString() });
    });

    await page.goto("/scout");
    await page.getByTestId("scout-cv-input").setInputFiles(DUMMY_CV);
    await page.getByTestId("scout-scan-button").click();

    // scout.py cold-starts an interpreter and parses the PDF; allow for that.
    await expect(page.getByTestId("scout-results-empty")).toBeVisible({
      timeout: 120_000,
    });
    // A 502 here means scout.py itself failed -- the failure mode this test
    // exists to catch, and the one a mocked response can never see.
    expect(statuses).toEqual([200]);
  });

  test("live scan against real job sources", async ({ page }) => {
    test.skip(
      !process.env.SCOUT_LIVE,
      "opt-in: needs outbound network to karriere.at / arbeitnow; set SCOUT_LIVE=1",
    );
    test.setTimeout(300_000);

    await page.goto("/scout");
    await page.getByTestId("scout-cv-input").setInputFiles(DUMMY_CV);
    await page.getByTestId("scout-scan-button").click();

    await expect(page.getByTestId("scout-results")).toBeVisible({ timeout: 280_000 });
    expect(await page.getByTestId("scout-job-row").count()).toBeGreaterThan(0);
    // The fixture CV is a .NET/C#/Azure backend engineer in Vienna. A scan that
    // returns rows matching none of that vocabulary is not a working match.
    await expect(page.getByTestId("scout-results")).toContainText(
      /engineer|developer|entwickler/i,
    );
  });
});
