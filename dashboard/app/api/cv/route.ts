import { NextResponse } from "next/server";

import { errorResponse, requireSession } from "@/lib/apiAuth";
import { CV_ID_RE, type CvProfile } from "@/lib/cvProfiles";
import { deleteProfile, loadConfig, saveProfile } from "@/lib/cvStore";
import { loadRun } from "@/lib/feed";

/**
 * The CV configuration, read and written over the same repository the cron reads.
 *
 * GET is public: it returns the same list that is already visible in the public
 * scout/ directory, plus each CV's last run. POST and DELETE are not -- they
 * commit to the repository.
 */

// Config lives on GitHub, so nothing here may be cached at build time: a page
// rendered against last week's profile list would be indistinguishable from a
// correct one.
export const dynamic = "force-dynamic";

export interface CvSummary extends CvProfile {
  lastRun: Awaited<ReturnType<typeof loadRun>>;
}

export async function GET() {
  const config = await loadConfig();
  const cvs: CvSummary[] = await Promise.all(
    config.profiles.map(async (p) => ({ ...p, lastRun: await loadRun(p.id) })),
  );
  return NextResponse.json({
    cvs,
    backend: config.backend,
    origin: config.origin,
    writable: config.writable,
    error: config.error,
  });
}

export async function POST(req: Request) {
  const denied = await requireSession(req);
  if (denied) return denied;

  let body: { profile?: CvProfile; doc?: unknown };
  try {
    body = (await req.json()) as typeof body;
  } catch {
    return errorResponse(new Error("Request body is not JSON."));
  }
  if (!body?.profile) return errorResponse(new Error("A `profile` object is required."));

  try {
    // saveProfile validates the profile and runs the PII gate over the document
    // before anything is sent to GitHub, so a rejected request commits nothing.
    const result = await saveProfile(body.profile, body.doc);
    return NextResponse.json({ ok: true, ...result });
  } catch (err) {
    return errorResponse(err);
  }
}

export async function DELETE(req: Request) {
  const denied = await requireSession(req);
  if (denied) return denied;

  const id = new URL(req.url).searchParams.get("id") ?? "";
  if (!CV_ID_RE.test(id)) return errorResponse(new Error(`Invalid CV id: ${id}`));

  try {
    return NextResponse.json({ ok: true, ...(await deleteProfile(id)) });
  } catch (err) {
    return errorResponse(err);
  }
}
