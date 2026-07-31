import { cookies } from "next/headers";
import Link from "next/link";

import ScoutClient from "./ScoutClient";
import { SESSION_COOKIE, authConfigured, verifySession } from "@/lib/auth";
import { localScanAvailable } from "@/lib/localScan";

/**
 * The upload-and-scan page.
 *
 * A server shell around the client form, because whether the form can work at
 * all is a property of the deployment, not of the browser. /api/scout refuses
 * with 501 where scripts/scout.py is absent and 401 where a session is
 * required; discovering either by picking a PDF, waiting, and reading an error
 * is a worse way to learn it than being told before you start.
 */
export const dynamic = "force-dynamic";

export default async function ScoutPage() {
  const available = localScanAvailable();
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  // Matches the route's own gate: no password configured means no session is
  // possible and none is asked for.
  const needsSignIn = authConfigured() && !(await verifySession(session, Date.now()));

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-semibold text-gray-900">CV Scout</h1>
        <p className="mt-1 text-sm text-gray-600">
          Upload a CV (PDF) and scan live job sources for the best matches right now.
        </p>
      </header>

      {!available ? (
        <div
          data-testid="scout-unavailable"
          className="rounded-lg border border-dashed border-gray-300 p-6 text-sm text-gray-600"
        >
          <p className="font-medium text-gray-900">Not available on this deployment.</p>
          <p className="mt-2">
            Scanning an uploaded PDF runs{" "}
            <code className="rounded bg-gray-100 px-1">scripts/scout.py</code>, which only
            exists on a local checkout — and a scan takes longer than a serverless
            function is allowed to live.
          </p>
          <p className="mt-2">
            Here, scans run on GitHub Actions on a schedule. Configure a CV under{" "}
            <Link className="underline" href="/profiles">
              CVs
            </Link>{" "}
            and use <span className="font-medium">Scan now</span>; results land on{" "}
            <Link className="underline" href="/matches">
              Matches
            </Link>
            .
          </p>
          <p className="mt-2 text-xs text-gray-500">
            To use it locally: <code className="rounded bg-gray-100 px-1">cd dashboard &amp;&amp; npm run dev</code>
          </p>
        </div>
      ) : needsSignIn ? (
        <div
          data-testid="scout-signin-required"
          className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800"
        >
          A scan spends real time and API credit, so it needs a session.{" "}
          <Link className="underline" href="/login">
            Sign in
          </Link>{" "}
          to upload a CV.
        </div>
      ) : (
        <ScoutClient />
      )}
    </div>
  );
}
