import { test, expect } from "@playwright/test";

import { POST } from "../app/api/scout/route";

/**
 * /api/scout is the most expensive route in the app: it writes an upload to
 * disk and spawns a scan that runs for minutes and bills NVIDIA_API_KEY.
 *
 * It used to be guarded only by "scripts/scout.py must exist", which happens to
 * hold on Vercel and in the Docker image but is a deployment-layout accident,
 * not an authorization decision. These tests pin the actual rule: when a
 * password is configured, a session is required.
 */

function upload(cookie?: string): Request {
  const form = new FormData();
  form.set("cv", new File([new Uint8Array([1, 2, 3])], "cv.pdf", { type: "application/pdf" }));
  return new Request("http://localhost/api/scout", {
    method: "POST",
    headers: cookie ? { cookie } : {},
    body: form,
  });
}

test.afterEach(() => {
  delete process.env.DASHBOARD_PASSWORD;
});

test("with a password configured, an unauthenticated scan is refused", async () => {
  process.env.DASHBOARD_PASSWORD = "correct horse battery staple";
  const res = await POST(upload() as never);
  expect(res.status).toBe(401);
});

test("a forged session cookie does not buy a scan", async () => {
  process.env.DASHBOARD_PASSWORD = "correct horse battery staple";
  const forged = `scout_session=${Date.now() + 60_000}.notavalidmac`;
  const res = await POST(upload(forged) as never);
  expect(res.status).toBe(401);
});

test("the auth check runs before any upload is written to disk", async () => {
  // Ordering matters: a 401 that arrives only after the multipart body has been
  // buffered and written to a temp file has already paid most of the cost the
  // check exists to avoid.
  process.env.DASHBOARD_PASSWORD = "correct horse battery staple";
  const res = await POST(
    new Request("http://localhost/api/scout", {
      method: "POST",
      headers: { "content-type": "multipart/form-data; boundary=x" },
      body: "not actually multipart",
    }) as never,
  );
  // 401, not the 400 that malformed multipart would produce further down.
  expect(res.status).toBe(401);
});

test("with no password configured the local checkout still scans", async () => {
  // The local dev checkout is this route's only real user, and it has no
  // password set. Requiring a session unconditionally would delete the feature
  // there; the scout.py-existence check is what keeps it off deployments.
  const res = await POST(upload() as never);
  expect(res.status).not.toBe(401);
});
