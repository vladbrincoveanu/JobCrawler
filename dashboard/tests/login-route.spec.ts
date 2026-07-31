import { test, expect } from "@playwright/test";

import { DELETE, POST } from "../app/api/login/route";

/**
 * The /api/login route handler, called directly (no browser, no server).
 *
 * Two behaviours here are invisible from the UI and were both wrong:
 *
 *   - DELETE cleared the session with a Secure cookie regardless of scheme. Over
 *     plain http the browser drops it, so "signed out" signed nothing out -- and
 *     the response said {ok: true} either way.
 *   - Nothing throttled a wrong password, so an online guess cost one request.
 *
 * The route keeps its failure counter in module scope and keys it by client, so
 * these tests isolate themselves with a distinct IP each rather than trying to
 * reload the module -- Playwright loads specs as CommonJS here, where a
 * cache-busting dynamic import does not resolve.
 */

const PASSWORD = "correct horse battery staple";

function attempt(password: string, ip = "203.0.113.7"): Request {
  return new Request("http://localhost/api/login", {
    method: "POST",
    headers: { "content-type": "application/json", "x-forwarded-for": ip },
    body: JSON.stringify({ password }),
  });
}

test.beforeEach(() => {
  process.env.DASHBOARD_PASSWORD = PASSWORD;
});
test.afterEach(() => {
  delete process.env.DASHBOARD_PASSWORD;
});

test("the right password sets a session cookie", async () => {
  const res = await POST(attempt(PASSWORD));
  expect(res.status).toBe(200);
  expect(res.headers.get("set-cookie")).toContain("scout_session=");
});

test("repeated wrong passwords are locked out with a 429 and a Retry-After", async () => {
  const ip = "198.51.100.4";

  for (let i = 0; i < 10; i++) {
    expect((await POST(attempt("wrong", ip))).status).toBe(401);
  }

  const res = await POST(attempt("wrong", ip));
  expect(res.status).toBe(429);
  expect(Number(res.headers.get("retry-after"))).toBeGreaterThan(0);

  // Locked out means locked out: the correct password must not be a way to
  // probe past the throttle, or the throttle only slows down the wrong guesses.
  expect((await POST(attempt(PASSWORD, ip))).status).toBe(429);
});

test("one client's lockout does not lock out another", async () => {
  for (let i = 0; i < 11; i++) await POST(attempt("wrong", "198.51.100.5"));

  expect((await POST(attempt("wrong", "198.51.100.5"))).status).toBe(429);
  expect((await POST(attempt(PASSWORD, "203.0.113.9"))).status).toBe(200);
});

test("a successful sign-in clears the failure count", async () => {
  const ip = "198.51.100.6";
  for (let i = 0; i < 9; i++) await POST(attempt("wrong", ip));

  expect((await POST(attempt(PASSWORD, ip))).status).toBe(200);
  // Nine failures then a success: the counter is back to zero, so the next
  // wrong password is attempt one, not attempt ten.
  for (let i = 0; i < 9; i++) {
    expect((await POST(attempt("wrong", ip))).status).toBe(401);
  }
});

test("logout clears the cookie with the same secure flag it was set with", async () => {
  const setCookie = (await POST(attempt(PASSWORD))).headers.get("set-cookie") ?? "";
  const clearCookie = (await DELETE()).headers.get("set-cookie") ?? "";

  expect(clearCookie).toContain("scout_session=");
  expect(clearCookie).toMatch(/Max-Age=0/i);
  // The asymmetry that broke logout on http: Secure on the clearing cookie but
  // not on the one being cleared means the browser drops the clear.
  expect(/Secure/i.test(clearCookie)).toBe(/Secure/i.test(setCookie));
});

test("with no password configured the route refuses instead of failing open", async () => {
  delete process.env.DASHBOARD_PASSWORD;
  const res = await POST(attempt(""));
  expect(res.status).toBe(503);
  expect(res.headers.get("set-cookie")).toBeNull();
});
