import { cookies } from "next/headers";

import { CvManager } from "@/components/CvManager";
import { SESSION_COOKIE, authConfigured, verifySession } from "@/lib/auth";
import { CAPABILITIES, configuredKeys, ghSecretCommands, type Capability } from "@/lib/credentials";
import { loadConfig } from "@/lib/cvStore";
import { SCOUT_WORKFLOW, githubFromEnv } from "@/lib/github";

/**
 * The control panel: which CVs are scanned, when, and with what.
 *
 * Reading is public -- scout/profiles.json is a committed file in a public
 * repository, so hiding it here would protect nothing. Writing needs a session.
 */
export const dynamic = "force-dynamic";

export default async function CvsPage() {
  const config = await loadConfig();
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  const signedIn = await verifySession(session, Date.now());

  const gh = githubFromEnv();
  const present = new Set(configuredKeys());
  const runs = gh ? await gh.listRuns(SCOUT_WORKFLOW, 5).catch(() => []) : [];

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-semibold text-gray-900">CVs</h1>
        <p className="mt-1 text-sm text-gray-600">
          Each CV is scanned on its own schedule by the{" "}
          <code className="rounded bg-gray-100 px-1">scout-cron</code> workflow. Saving
          here commits{" "}
          <a className="underline" href={config.origin}>
            scout/profiles.json
          </a>
          , which is the file that workflow reads.
        </p>
      </header>

      {config.error && (
        <div
          data-testid="cvs-error"
          className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
        >
          Could not read the CV configuration: {config.error}
        </div>
      )}

      <CvManager
        cvs={config.profiles}
        writable={config.writable}
        backend={config.backend}
        origin={config.origin}
        signedIn={signedIn}
      />

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-gray-900">Credentials</h2>
        <p className="text-sm text-gray-600">
          Set on the deployment (for this page) and as GitHub Actions secrets (for
          the scan). Values are never shown or stored here — run the command on
          your own terminal and it will prompt for the value.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          {(Object.keys(CAPABILITIES) as Capability[]).map((cap) => {
            const { label, keys, detail } = CAPABILITIES[cap];
            const missing = keys.filter((k) => !present.has(k));
            return (
              <div
                key={cap}
                data-testid={`capability-${cap}`}
                className="rounded-lg border border-gray-200 bg-white p-4 text-sm"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-gray-900">{label}</span>
                  <span
                    className={
                      missing.length === 0
                        ? "rounded bg-green-100 px-2 py-0.5 text-xs text-green-800"
                        : "rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600"
                    }
                  >
                    {missing.length === 0 ? "configured" : "not configured"}
                  </span>
                </div>
                <p className="mt-1 text-xs text-gray-600">{detail}</p>
                {missing.length > 0 && (
                  <pre className="mt-2 overflow-x-auto rounded bg-gray-900 p-2 text-xs text-gray-100">
                    {ghSecretCommands(missing).join("\n")}
                  </pre>
                )}
              </div>
            );
          })}
        </div>
        {!authConfigured() && (
          <p className="text-xs text-amber-700" data-testid="no-auth-configured">
            DASHBOARD_PASSWORD is not set, so nobody can sign in and every write is
            refused. Set it in the Vercel project environment.
          </p>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-gray-900">Recent scans</h2>
        {runs.length === 0 ? (
          <p className="text-sm text-gray-500" data-testid="runs-empty">
            {gh
              ? "No scout-cron run has been recorded yet."
              : "GITHUB_REPO and GITHUB_TOKEN are not set, so run history is unavailable."}
          </p>
        ) : (
          <ul className="divide-y divide-gray-200 rounded-lg border border-gray-200 bg-white text-sm">
            {runs.map((r) => (
              <li key={r.id} className="flex items-center justify-between px-4 py-2">
                <span className="text-gray-700">
                  {new Date(r.created_at).toLocaleString()}
                </span>
                <span className="text-gray-600">{r.conclusion ?? r.status}</span>
                <a className="underline" href={r.html_url} target="_blank" rel="noreferrer">
                  open
                </a>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
