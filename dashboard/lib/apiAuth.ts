import { NextResponse } from "next/server";

import { SESSION_COOKIE, authConfigured, verifySession } from "@/lib/auth";

/**
 * The guard every mutating route calls first.
 *
 * There is deliberately no middleware.ts. An earlier version of this comment
 * claimed one existed and treated it as the first line of defence, which was
 * wrong in the way that matters: /api/scout was left unguarded for a while on
 * the strength of a layer that was never there. Each route checks for itself,
 * and each page checks its own session (see app/profiles/page.tsx) -- so there
 * is no matcher list that can silently stop covering a new path.
 */
export async function requireSession(req: Request): Promise<NextResponse | null> {
  if (!authConfigured()) {
    return NextResponse.json(
      {
        error:
          "DASHBOARD_PASSWORD is not set on this deployment, so no request can be " +
          "authenticated and writes are disabled.",
      },
      { status: 503 },
    );
  }

  const cookie = req.headers
    .get("cookie")
    ?.split(";")
    .map((c) => c.trim())
    .find((c) => c.startsWith(`${SESSION_COOKIE}=`))
    ?.slice(SESSION_COOKIE.length + 1);

  if (!(await verifySession(cookie, Date.now()))) {
    return NextResponse.json({ error: "Not signed in." }, { status: 401 });
  }
  return null;
}

/** Turns a thrown validation/PII/GitHub error into a response that says why. */
export function errorResponse(err: unknown, status = 400): NextResponse {
  const message = err instanceof Error ? err.message : "Request failed.";
  return NextResponse.json({ error: message }, { status });
}
