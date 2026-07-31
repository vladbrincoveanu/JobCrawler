import { CvSwitcher, type CvTab } from "@/components/CvSwitcher";
import { MatchesView } from "@/components/MatchesView";
import { ScanNowButton } from "@/components/ScanNowButton";
import { loadConfig } from "@/lib/cvStore";
import { loadFeed, loadRun } from "@/lib/feed";

/**
 * The board, per CV.
 *
 * Every CV has its own profile, its own schedule and its own feed file, so this
 * page picks one with ?cv=<id> and renders that one's last scheduled scan. With
 * no id it falls back to the first configured CV, and with no CVs configured at
 * all it falls back to the legacy single feed -- which is what a checkout that
 * has not migrated still has on disk.
 */
export const dynamic = "force-dynamic";

export default async function MatchesPage({
  searchParams,
}: {
  searchParams: Promise<{ cv?: string }>;
}) {
  const { cv: requested } = await searchParams;
  const config = await loadConfig();

  const cvs: CvTab[] = await Promise.all(
    config.profiles.map(async (p) => ({ ...p, lastRun: await loadRun(p.id) })),
  );

  // An unknown ?cv= must not silently show a different CV's jobs: that is the
  // one bug on this page nobody would catch by looking.
  const known = cvs.some((c) => c.id === requested);
  const active = known ? requested! : (cvs[0]?.id ?? null);
  const activeCv = cvs.find((c) => c.id === active) ?? null;

  const { result, origin, error } = await loadFeed(active ?? undefined);
  const lastRun = activeCv?.lastRun ?? null;

  return (
    <div className="space-y-8">
      <header className="space-y-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Matches</h1>
          <p className="mt-1 text-sm text-gray-600">
            Open roles from the most recent scheduled scan, best match first.
          </p>
        </div>

        {requested && !known && (
          <p
            data-testid="matches-unknown-cv"
            className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"
          >
            No CV is configured with the id <code>{requested}</code>
            {active ? <> — showing {activeCv?.label} instead.</> : "."}
          </p>
        )}

        <CvSwitcher cvs={cvs} active={active ?? ""} />
      </header>

      {config.error && (
        <div
          data-testid="matches-config-error"
          className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
        >
          Could not read the CV configuration: {config.error}
        </div>
      )}

      {lastRun?.status === "error" && (
        <div
          data-testid="matches-run-failed"
          className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
        >
          The last scan of {activeCv?.label} failed ({lastRun.attempts} attempt
          {lastRun.attempts === 1 ? "" : "s"}, {lastRun.finished_at}). The jobs below,
          if any, are from an older run.
        </div>
      )}

      {error && (
        <div
          data-testid="matches-error"
          className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
        >
          Could not read the scan feed: {error}
          <div className="mt-1 text-xs text-red-500">{origin}</div>
        </div>
      )}

      {!error && !result && (
        <div
          data-testid="matches-empty"
          className="space-y-3 rounded-lg border border-dashed border-gray-300 p-6 text-sm text-gray-600"
        >
          <p className="font-medium text-gray-800">
            {activeCv
              ? `${activeCv.label} has not been scanned yet.`
              : "No scheduled scan has run yet."}
          </p>
          <p>
            The <code className="rounded bg-gray-100 px-1">scout-cron</code> workflow
            scans each CV on its own schedule and publishes the result to the{" "}
            <code className="rounded bg-gray-100 px-1">scout-data</code> branch. Start
            one now instead of waiting for the next slot:
          </p>
          {activeCv && <ScanNowButton cvId={activeCv.id} label={activeCv.label} />}
          <p className="text-xs text-gray-400">Looked in: {origin}</p>
        </div>
      )}

      {result && (
        <>
          {activeCv && (
            <div className="flex items-center justify-between gap-4 rounded-lg border border-gray-200 bg-white p-4">
              <div className="text-sm text-gray-600">
                <span className="font-medium text-gray-900">{activeCv.label}</span> ·
                scheduled {activeCv.schedule.hours_utc.join(", ")}:00 UTC
                {activeCv.schedule.weekdays_only ? " on weekdays" : ""} · alerts above{" "}
                {activeCv.alert.min_match}%
              </div>
              <ScanNowButton cvId={activeCv.id} label={activeCv.label} />
            </div>
          )}
          <MatchesView result={result} origin={origin} />
        </>
      )}
    </div>
  );
}
