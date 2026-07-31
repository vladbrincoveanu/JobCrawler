import { NextResponse } from "next/server";

import {
  SESSION_COOKIE,
  SESSION_COOKIE_OPTIONS,
  authConfigured,
  checkPassword,
  issueSession,
} from "@/lib/auth";

export const dynamic = "force-dynamic";

// Vercel is always HTTPS; a local `next start` over http is not, and a Secure
// cookie there is dropped by the browser -- silently, which on the DELETE path
// means "signed out" that did not sign anything out.
const COOKIE_SECURE = process.env.NODE_ENV === "production";

/**
 * Failed-attempt throttle.
 *
 * One password and no lockout means an online guess costs an attacker nothing
 * but a request. This does not pretend to be a distributed rate limiter -- the
 * map is per serverless instance, so a determined attacker spread across enough
 * cold starts still gets more attempts than this number suggests. What it does
 * buy is that the cheap case -- one host hammering one instance -- stops being
 * free, and that a locked-out window is visible in the response instead of
 * looking like an ordinary wrong password.
 */
const MAX_FAILURES = 10;
const LOCKOUT_MS = 15 * 60 * 1000;
const failures = new Map<string, { count: number; until: number }>();

function clientKey(req: Request): string {
  // x-forwarded-for is attacker-controlled in general; on Vercel the platform
  // rewrites it, and a wrong key here degrades to "throttle the shared bucket",
  // never to "skip the check".
  return (req.headers.get("x-forwarded-for") ?? "unknown").split(",")[0].trim();
}

function lockedOutFor(key: string, now: number): number {
  const entry = failures.get(key);
  if (!entry || entry.until <= now) return 0;
  return entry.count >= MAX_FAILURES ? entry.until - now : 0;
}

function recordFailure(key: string, now: number): void {
  const entry = failures.get(key);
  const count = entry && entry.until > now ? entry.count + 1 : 1;
  failures.set(key, { count, until: now + LOCKOUT_MS });
}

export async function POST(req: Request) {
  if (!authConfigured()) {
    return NextResponse.json(
      { error: "DASHBOARD_PASSWORD is not set on this deployment." },
      { status: 503 },
    );
  }

  const now = Date.now();
  const key = clientKey(req);
  const waitMs = lockedOutFor(key, now);
  if (waitMs > 0) {
    return NextResponse.json(
      { error: `Too many failed attempts. Try again in ${Math.ceil(waitMs / 60000)} minutes.` },
      { status: 429, headers: { "Retry-After": String(Math.ceil(waitMs / 1000)) } },
    );
  }

  let password = "";
  const type = req.headers.get("content-type") ?? "";
  if (type.includes("application/json")) {
    password = ((await req.json().catch(() => ({}))) as { password?: string }).password ?? "";
  } else {
    password = String((await req.formData()).get("password") ?? "");
  }

  if (!(await checkPassword(password))) {
    recordFailure(key, now);
    // One message for every failure. "No such user" versus "wrong password" is
    // not a distinction worth making when there is exactly one user.
    return NextResponse.json({ error: "Wrong password." }, { status: 401 });
  }

  failures.delete(key);
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, await issueSession(now), {
    ...SESSION_COOKIE_OPTIONS,
    secure: COOKIE_SECURE,
  });
  return res;
}

export async function DELETE() {
  const res = NextResponse.json({ ok: true });
  // Same secure flag as the cookie being cleared: a Secure clearing cookie sent
  // over http is dropped, so the session would outlive its own logout.
  res.cookies.set(SESSION_COOKIE, "", {
    ...SESSION_COOKIE_OPTIONS,
    secure: COOKIE_SECURE,
    maxAge: 0,
  });
  return res;
}
