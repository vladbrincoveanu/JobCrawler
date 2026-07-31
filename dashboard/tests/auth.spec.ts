import { test, expect } from "@playwright/test";

import {
  authConfigured,
  checkPassword,
  issueSession,
  verifySession,
} from "@/lib/auth";

/** Node-context tests (no browser). */

const NOW = 1_800_000_000_000;

test.beforeEach(() => {
  process.env.DASHBOARD_PASSWORD = "correct horse battery staple";
});
test.afterEach(() => {
  delete process.env.DASHBOARD_PASSWORD;
});

test("a freshly issued session verifies", async () => {
  expect(await verifySession(await issueSession(NOW), NOW)).toBe(true);
});

test("a session does not verify after its expiry", async () => {
  const cookie = await issueSession(NOW);
  const eightDays = 8 * 24 * 60 * 60 * 1000;
  expect(await verifySession(cookie, NOW + eightDays)).toBe(false);
});

test("editing the expiry to extend a session invalidates it", async () => {
  // The whole point of the MAC: the expiry is client-visible, so it must not be
  // client-editable.
  const cookie = await issueSession(NOW);
  const [, mac] = cookie.split(".");
  const forged = `${NOW + 10 * 365 * 24 * 3600 * 1000}.${mac}`;
  expect(await verifySession(forged, NOW)).toBe(false);
});

test("a session issued under a different password does not verify", async () => {
  // Rotating DASHBOARD_PASSWORD must log everyone out; that is the only
  // revocation mechanism there is.
  const cookie = await issueSession(NOW);
  process.env.DASHBOARD_PASSWORD = "something else entirely";
  expect(await verifySession(cookie, NOW)).toBe(false);
});

test("garbage cookie values are rejected, not crashed on", async () => {
  for (const value of ["", "no-dot", ".", "abc.def", "999999999999.", undefined, null]) {
    expect(await verifySession(value as string, NOW)).toBe(false);
  }
});

test("with no password configured nothing verifies and nothing can be issued", async () => {
  delete process.env.DASHBOARD_PASSWORD;
  expect(authConfigured()).toBe(false);
  expect(await verifySession("anything", NOW)).toBe(false);
  expect(await checkPassword("")).toBe(false);
  // Fail closed: an unset password must not become an open door.
  await expect(issueSession(NOW)).rejects.toThrow(/DASHBOARD_PASSWORD/);
});

test("checkPassword accepts only the exact password", async () => {
  expect(await checkPassword("correct horse battery staple")).toBe(true);
  expect(await checkPassword("correct horse battery stapl")).toBe(false);
  expect(await checkPassword("correct horse battery staple ")).toBe(false);
  expect(await checkPassword("")).toBe(false);
});
