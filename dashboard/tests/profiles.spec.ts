import { test, expect } from "@playwright/test";

/**
 * The deployed half of the product: pick a CV, see its board, change its
 * settings.
 *
 * The test server runs with SCOUT_CONFIG_ROOT at tests/fixtures/config (one CV,
 * "test-cv") and SCOUT_FEED_DIR at tests/fixtures/feed, so the switcher and the
 * settings page are asserted against a known configuration rather than whatever
 * scout/profiles.json holds in this checkout.
 *
 * DASHBOARD_PASSWORD is NOT set for the test server, which is the important
 * case: an unauthenticated deployment must render the config read-only and
 * refuse every write, rather than falling open.
 */

test.describe("CV settings", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/profiles");
  });

  test("lists the configured CVs with their schedule and threshold", async ({ page }) => {
    await expect(page.getByTestId("cv-card-test-cv")).toBeVisible();
    await expect(page.getByTestId("cv-days-test-cv")).toHaveValue("7");
    await expect(page.getByTestId("cv-top-test-cv")).toHaveValue("50");
    await expect(page.getByTestId("cv-minmatch-test-cv")).toHaveValue("75");
    await expect(page.getByTestId("cv-hours-test-cv")).toHaveValue("5");
  });

  test("is read-only when signed out, and says so", async ({ page }) => {
    await expect(page.getByTestId("cvs-readonly")).toBeVisible();
    await expect(page.getByTestId("cv-save-test-cv")).toBeDisabled();
    await expect(page.getByTestId("cv-enabled-test-cv")).toBeDisabled();
    await expect(page.getByTestId("cv-delete-test-cv")).toBeDisabled();
  });

  test("names the credentials each capability is missing, without a value", async ({
    page,
  }) => {
    const alerts = page.getByTestId("capability-alerts");
    await expect(alerts).toContainText("not configured");
    // The remedy is a command that PROMPTS for the secret. If a value ever
    // appeared here it would be in the HTML, the browser cache and any screenshot.
    await expect(alerts).toContainText("gh secret set TELEGRAM_BOT_TOKEN");
    await expect(alerts).toContainText("gh secret set TELEGRAM_CHAT_ID");
  });

  test("warns that no password means no writes at all", async ({ page }) => {
    await expect(page.getByTestId("no-auth-configured")).toBeVisible();
  });

  test("is reachable from the nav", async ({ page }) => {
    await page.goto("/matches");
    await page.getByTestId("nav-link-cvs").click();
    await expect(page).toHaveURL(/\/profiles$/);
  });
});

test.describe("write gate", () => {
  test("an unauthenticated save is refused by the server, not just the UI", async ({
    request,
  }) => {
    // The disabled buttons above are a courtesy. This is the check that matters:
    // a POST straight at the API, which is what an attacker sends.
    const res = await request.post("/api/cv", {
      data: {
        profile: {
          id: "test-cv",
          label: "Hijacked",
          enabled: true,
          schedule: { hours_utc: [5], weekdays_only: false },
          filters: { days: 7, top: 50, require_salary: false, sources: "apis" },
          alert: { min_match: 75 },
        },
      },
    });
    expect(res.status()).toBe(503);
    expect(await res.text()).toContain("DASHBOARD_PASSWORD");
  });

  test("an unauthenticated scan dispatch is refused", async ({ request }) => {
    // Dispatching costs GitHub Actions minutes; it must not be free to anyone
    // who can reach the URL.
    const res = await request.post("/api/scan", { data: { cvId: "test-cv" } });
    expect(res.status()).toBe(503);
  });

  test("a login attempt with no password configured fails closed", async ({ request }) => {
    const res = await request.post("/api/login", { data: { password: "" } });
    expect(res.status()).toBe(503);
  });
});

test.describe("per-CV board", () => {
  test("the switcher offers the configured CV and selects it by default", async ({
    page,
  }) => {
    await page.goto("/matches");
    const tab = page.getByTestId("cv-tab-test-cv");
    await expect(tab).toBeVisible();
    await expect(tab).toHaveAttribute("data-selected", "true");
  });

  test("renders that CV's own feed, not the legacy single feed", async ({ page }) => {
    await page.goto("/matches?cv=test-cv");
    await expect(page.getByTestId("matches-count")).toHaveText("3 of 3 shown");
  });

  test("an unknown ?cv= says so instead of quietly showing another CV", async ({
    page,
  }) => {
    // The one bug on this page nobody would catch by looking: falling back to
    // some other CV's jobs under a heading that names the one you asked for.
    await page.goto("/matches?cv=not-a-real-cv");
    await expect(page.getByTestId("matches-unknown-cv")).toContainText("not-a-real-cv");
    await expect(page.getByTestId("cv-tab-test-cv")).toHaveAttribute(
      "data-selected",
      "true",
    );
  });

  test("a path-traversal cv id does not read a file outside the feed dir", async ({
    page,
  }) => {
    const res = await page.goto("/matches?cv=..%2F..%2Fetc%2Fpasswd");
    // Rejected as an unknown CV, and the page still renders.
    expect(res?.status()).toBe(200);
    await expect(page.getByTestId("matches-unknown-cv")).toBeVisible();
  });
});
