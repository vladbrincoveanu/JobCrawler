import { NextResponse } from "next/server";

import { errorResponse, requireSession } from "@/lib/apiAuth";
import { CV_ID_RE } from "@/lib/cvProfiles";
import { SCOUT_WORKFLOW, githubFromEnv } from "@/lib/github";

/**
 * "Scan now" -- which, on this deployment, means dispatching the workflow that
 * already owns scanning rather than running one here.
 *
 * The old design streamed scout.py's stdout over SSE from the dashboard process.
 * That cannot work on Vercel (no Python, and a serverless function is killed
 * long before a four-minute scan finishes), and it should not: the cron is the
 * thing whose behaviour matters, and a second scan path would let the button
 * work while the scheduled run stayed broken.
 *
 * So there is no progress stream. There is a dispatch and a poll of the run
 * list, which is the same information GitHub has.
 */

export const dynamic = "force-dynamic";

export async function GET() {
  const gh = githubFromEnv();
  if (!gh) {
    return NextResponse.json({ configured: false, runs: [] });
  }
  try {
    return NextResponse.json({ configured: true, runs: await gh.listRuns(SCOUT_WORKFLOW, 5) });
  } catch (err) {
    return errorResponse(err, 502);
  }
}

export async function POST(req: Request) {
  const denied = await requireSession(req);
  if (denied) return denied;

  const gh = githubFromEnv();
  if (!gh) {
    return errorResponse(
      new Error("GITHUB_REPO and GITHUB_TOKEN are not set, so no scan can be dispatched."),
      503,
    );
  }

  let body: { cvId?: string; force?: boolean };
  try {
    body = (await req.json()) as typeof body;
  } catch {
    body = {};
  }
  const cvId = body.cvId ?? "";
  if (cvId && !CV_ID_RE.test(cvId)) {
    return errorResponse(new Error(`Invalid CV id: ${cvId}`));
  }

  try {
    await gh.dispatchWorkflow(SCOUT_WORKFLOW, {
      cv_id: cvId,
      // force must be "false" whenever cv_id is set: the workflow tests force
      // FIRST and scans every enabled CV when it is true, so sending both would
      // turn "scan this one CV" into "scan all four" -- four times the runner
      // minutes, and a scan the user did not ask for on three other CVs.
      force: cvId ? "false" : String(Boolean(body.force)),
    });
  } catch (err) {
    return errorResponse(err, 502);
  }

  // The dispatch returns 204 with no run id, and the run takes a few seconds to
  // appear. The client polls GET rather than being told a run id that does not
  // exist yet.
  return NextResponse.json({
    ok: true,
    dispatched: cvId || "all due CVs",
    actionsUrl: `https://github.com/${gh.repo}/actions/workflows/${SCOUT_WORKFLOW}`,
  });
}
