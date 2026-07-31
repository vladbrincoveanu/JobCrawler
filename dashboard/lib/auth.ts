/**
 * The gate in front of everything that costs something.
 *
 * Until now the dashboard read a local database on localhost and had no auth,
 * which was fine. Deployed, it holds a token that can commit to this repository
 * and dispatch a workflow -- so an unauthenticated POST is a stranger rewriting
 * the CV config and spending Actions minutes.
 *
 * The session cookie is an HMAC over an expiry, keyed by DASHBOARD_PASSWORD.
 * There is no user table and no session store, because there is one user; the
 * point is only that the cookie cannot be forged without the password, and
 * expires on its own.
 *
 * Fail-closed rule: with DASHBOARD_PASSWORD unset there is no way to prove
 * anything, so every mutating route refuses. It does NOT fall back to "allow" --
 * a missing env var on a deployment is exactly when that would matter.
 * Reads stay open: the published feed is a public branch anyway.
 *
 * Web Crypto only (no node:crypto), so this runs unchanged on the edge runtime
 * as well as in Node -- there is no middleware today, but nothing here would
 * have to change to add one.
 */

export const SESSION_COOKIE = "scout_session";
const SESSION_TTL_MS = 7 * 24 * 60 * 60 * 1000;

function password(): string {
  return process.env.DASHBOARD_PASSWORD ?? "";
}

export function authConfigured(): boolean {
  return password().length > 0;
}

function b64url(bytes: Uint8Array): string {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function sign(payload: string, key: string): Promise<string> {
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(key),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const mac = await crypto.subtle.sign("HMAC", cryptoKey, new TextEncoder().encode(payload));
  return b64url(new Uint8Array(mac));
}

/** Length-independent, branch-free compare: a fast reject leaks the prefix. */
function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

/** The cookie value for a session that expires `now + TTL`. */
export async function issueSession(now: number): Promise<string> {
  if (!authConfigured()) {
    throw new Error("DASHBOARD_PASSWORD is not set; refusing to issue a session.");
  }
  const expires = String(now + SESSION_TTL_MS);
  return `${expires}.${await sign(expires, password())}`;
}

export async function verifySession(
  value: string | undefined | null,
  now: number,
): Promise<boolean> {
  if (!authConfigured() || !value) return false;
  const dot = value.lastIndexOf(".");
  if (dot <= 0) return false;
  const expires = value.slice(0, dot);
  const mac = value.slice(dot + 1);
  if (!/^\d+$/.test(expires)) return false;
  // Signature first, then expiry: checking expiry first would answer "is this
  // a well-formed unexpired token" for a forged one, which is a free oracle.
  if (!timingSafeEqual(mac, await sign(expires, password()))) return false;
  return Number(expires) > now;
}

export async function checkPassword(candidate: string): Promise<boolean> {
  if (!authConfigured()) return false;
  return timingSafeEqual(
    await sign(candidate, "login"),
    await sign(password(), "login"),
  );
}

export const SESSION_COOKIE_OPTIONS = {
  httpOnly: true,
  sameSite: "lax" as const,
  secure: true,
  path: "/",
  maxAge: SESSION_TTL_MS / 1000,
};
