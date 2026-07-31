import { NextResponse } from "next/server";

import {
  SESSION_COOKIE,
  SESSION_COOKIE_OPTIONS,
  authConfigured,
  checkPassword,
  issueSession,
} from "@/lib/auth";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  if (!authConfigured()) {
    return NextResponse.json(
      { error: "DASHBOARD_PASSWORD is not set on this deployment." },
      { status: 503 },
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
    // One message for every failure. "No such user" versus "wrong password" is
    // not a distinction worth making when there is exactly one user.
    return NextResponse.json({ error: "Wrong password." }, { status: 401 });
  }

  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, await issueSession(Date.now()), {
    ...SESSION_COOKIE_OPTIONS,
    // Vercel is always HTTPS; a local `next start` over http is not, and a
    // secure cookie there would be set and never sent back.
    secure: process.env.NODE_ENV === "production",
  });
  return res;
}

export async function DELETE() {
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, "", { ...SESSION_COOKIE_OPTIONS, maxAge: 0 });
  return res;
}
