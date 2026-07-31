import { test, expect } from "@playwright/test";

import {
  ALLOWED_KEYS,
  configuredKeys,
  ghSecretCommands,
  missingFor,
} from "@/lib/credentials";

/**
 * Node-context tests (no browser).
 *
 * The dashboard is deployed on Vercel and never writes a credential anywhere:
 * the runtime reads them from the platform environment, and the scheduled scan
 * reads them from GitHub Actions secrets. So the interesting assertions are the
 * ones about NOT leaking a value -- into a response body, a command line, or a
 * settings page.
 */

test("the allowed key list is exactly the documented one", () => {
  expect([...ALLOWED_KEYS].sort()).toEqual([
    "ADZUNA_APP_ID",
    "ADZUNA_APP_KEY",
    "JOOBLE_KEY",
    "NVIDIA_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
  ]);
});

test("reports which credentials are set, by name only", () => {
  process.env.TELEGRAM_CHAT_ID = "42";
  delete process.env.JOOBLE_KEY;
  try {
    const keys = configuredKeys();
    expect(keys).toContain("TELEGRAM_CHAT_ID");
    expect(keys).not.toContain("JOOBLE_KEY");
    // The value must not be reachable through this API at all: whatever it
    // returns ends up rendered in a settings page and in an HTTP response.
    expect(JSON.stringify(keys)).not.toContain("42");
  } finally {
    delete process.env.TELEGRAM_CHAT_ID;
  }
});

test("an empty-string credential counts as unset, not as configured", () => {
  // Vercel happily stores an empty env var, and a settings page that shows
  // "Telegram: configured" for one is worse than showing nothing: the user
  // stops looking for the reason no alert ever arrives.
  process.env.JOOBLE_KEY = "";
  try {
    expect(configuredKeys()).not.toContain("JOOBLE_KEY");
  } finally {
    delete process.env.JOOBLE_KEY;
  }
});

test("missingFor names the credentials a capability needs", () => {
  delete process.env.TELEGRAM_BOT_TOKEN;
  delete process.env.TELEGRAM_CHAT_ID;
  expect(missingFor("alerts")).toEqual(["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]);

  process.env.TELEGRAM_BOT_TOKEN = "123:abc";
  try {
    expect(missingFor("alerts")).toEqual(["TELEGRAM_CHAT_ID"]);
  } finally {
    delete process.env.TELEGRAM_BOT_TOKEN;
  }
});

test("returns the gh commands to mirror the secrets, without the values", () => {
  const cmds = ghSecretCommands(["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]);
  expect(cmds).toEqual([
    "gh secret set TELEGRAM_BOT_TOKEN",
    "gh secret set TELEGRAM_CHAT_ID",
  ]);
});

test("gh commands refuse a key that is not an alert credential", () => {
  expect(() => ghSecretCommands(["DATABASE_URL" as never])).toThrow(/DATABASE_URL/);
});
